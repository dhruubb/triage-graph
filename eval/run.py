"""Evaluation runner.

    python -m eval.run --retrieval-only        # no LLM calls: hit@k and MRR of hybrid search
    python -m eval.run                         # full graph on every golden case (uses your Groq quota)
    python -m eval.run --cases g01,g07 --sleep 30
    python -m eval.run --resume                # continue after a rate-limit stop

Every case that needs approval is approved automatically (reviewer "eval") so the run
finishes; whether it paused is recorded. Results go to eval/results/latest.json, which
the UI's Evaluation tab shows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from langgraph.types import Command

from app.config import ROOT, get_settings
from app.deps import build_deps
from app.graph import build_graph
from eval.metrics import aggregate, hit_at, keyword_hit, reciprocal_rank, severity_within_one

GOLDEN = ROOT / "eval" / "golden.jsonl"
RESULTS = ROOT / "eval" / "results"
PARTIAL = RESULTS / "partial.jsonl"


def load_cases(only: str | None) -> list[dict]:
    cases = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    if only:
        wanted = set(only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    return cases


def retrieval_row(case: dict, runbooks: list[str]) -> dict:
    return {
        "id": case["id"],
        "expected_runbooks": case["runbooks"],
        "retrieved": runbooks,
        "hit_at_1": hit_at(runbooks, case["runbooks"], 1),
        "hit_at_3": hit_at(runbooks, case["runbooks"], 3),
        "rr": reciprocal_rank(runbooks, case["runbooks"]),
    }


def run_retrieval_only(deps, case: dict, oracle_service: bool = False, with_logs: bool = True) -> dict:
    """Retrieval from the raw ticket text. By default no service hint is given, because in a
    real run the service comes from the intake agent; --oracle-service passes the labelled one."""
    query = f"{case['ticket']}\n{case['logs']}" if with_logs else case["ticket"]
    res = deps.store.retrieve(query, service=case["service"] if oracle_service else None, k=3)
    return {**retrieval_row(case, [r["runbook_id"] for r in res.runbooks]), "mode": "retrieval"}


async def run_full(graph, case: dict) -> dict:
    thread = f"eval-{case['id']}-{int(time.time())}"
    cfg = {"configurable": {"thread_id": thread}}
    state = {"thread_id": thread, "ticket_id": case["id"], "ticket": case["ticket"], "logs": case["logs"],
             "trace": [], "done_workers": [], "supervisor_steps": 0, "planner_runs": 0}
    await graph.ainvoke(state, cfg)
    snap = await graph.aget_state(cfg)
    paused = "approval_gate" in (snap.next or ())
    if paused:
        await graph.ainvoke(Command(resume={"approved": True, "reviewer": "eval"}), cfg)
        snap = await graph.aget_state(cfg)
    v = snap.values
    intake, plan, critique = v["intake"], v["plan"], v["critique"]
    trace = v.get("trace", [])
    commands = " ".join(s.get("command", "") for s in plan["steps"])
    row = {
        **retrieval_row(case, [r["runbook_id"] for r in v.get("runbook_hits", [])]),
        "mode": "full",
        "predicted_service": intake["service"],
        "predicted_severity": intake["severity"],
        "service_ok": intake["service"] == case["service"],
        "severity_ok": intake["severity"] == case["severity"],
        "severity_within_one": severity_within_one(intake["severity"], case["severity"]),
        "root_cause": plan["root_cause_hypothesis"],
        "root_cause_hit": keyword_hit(plan["root_cause_hypothesis"], case["root_cause_keywords"]),
        "grounded": bool(critique.get("grounded")),
        "judge_score": critique.get("score", 0),
        "rule_issues": len(critique.get("rule_issues", [])),
        "revised": v.get("planner_runs", 1) > 1,
        "paused": paused,
        "must_pause": case["must_pause"],
        "route": [e["note"] for e in trace if e["node"] == "supervisor"],
        "latency_ms": sum(e["latency_ms"] for e in trace),
        "tokens": sum(e["input_tokens"] + e["output_tokens"] for e in trace),
        "llm_calls": sum(e["llm_calls"] for e in trace),
    }
    if case.get("injection"):
        row["injection"] = True
        row["injection_resisted"] = case["injection"] not in commands
    return row


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except OSError:
        return ""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--oracle-service", action="store_true", help="retrieval-only: give the labelled service as a hint")
    ap.add_argument("--no-logs", action="store_true", help="retrieval-only: search with the ticket text alone (harder)")
    ap.add_argument("--cases", help="comma-separated case ids")
    ap.add_argument("--sleep", type=float, default=45.0, help="seconds between full runs (free-tier token limits)")
    ap.add_argument("--resume", action="store_true", help="skip cases already in eval/results/partial.jsonl")
    ap.add_argument("--out", default=str(RESULTS / "latest.json"))
    args = ap.parse_args()

    settings = get_settings()
    RESULTS.mkdir(parents=True, exist_ok=True)
    deps = build_deps(settings)
    cases = load_cases(args.cases)

    rows: list[dict] = []
    if args.retrieval_only:
        rows = [run_retrieval_only(deps, c, args.oracle_service, not args.no_logs) for c in cases]
    else:
        if deps.llms is None:
            print("GROQ_API_KEY is not set. Use --retrieval-only, or add the key to .env.")
            return 1
        graph = build_graph(deps)
        done = {}
        if args.resume and PARTIAL.exists():
            done = {r["id"]: r for r in map(json.loads, PARTIAL.read_text().splitlines()) if not r.get("error")}
        elif PARTIAL.exists():
            PARTIAL.unlink()
        for i, case in enumerate(cases):
            if case["id"] in done:
                rows.append(done[case["id"]])
                continue
            print(f"[{i + 1}/{len(cases)}] {case['id']} ...", flush=True)
            try:
                row = await run_full(graph, case)
            except Exception as exc:
                msg = str(exc)
                row = {"id": case["id"], "error": msg[:300]}
                print(f"  error: {msg[:200]}")
                if "per day" in msg.lower() or "tpd" in msg.lower():
                    print("Daily token limit reached. Run again tomorrow with --resume.")
                    rows.append(row)
                    break
            else:
                print(f"  service={row['predicted_service']} sev={row['predicted_severity']} "
                      f"top={row['retrieved'][:1]} grounded={row['grounded']} paused={row['paused']}")
            rows.append(row)
            with PARTIAL.open("a") as f:
                f.write(json.dumps(row) + "\n")
            if i < len(cases) - 1 and args.sleep:
                await asyncio.sleep(args.sleep)

    summary = aggregate(rows)
    s = settings
    result = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "mode": ("retrieval-only" + (" (ticket text only)" if args.no_logs else "")) if args.retrieval_only else "full",
        "config": {
            "llm_provider": s.llm_provider, "model_fast": s.llm_model_fast, "model_smart": s.llm_model_smart,
            "embeddings": deps.store.dense.tag, "vector_store": deps.store.backend,
            "auto_approve_max_risk": s.auto_approve_max_risk,
        },
        "summary": summary,
        "cases": rows,
    }
    Path(args.out).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(summary, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
