"""Metric functions for the evaluation runner. Pure functions, unit-tested."""

from __future__ import annotations

SEV_RANK = {"SEV1": 1, "SEV2": 2, "SEV3": 3, "SEV4": 4}


def rank_of(retrieved: list[str], expected: list[str]) -> int | None:
    """1-based rank of the first expected runbook in the retrieved list."""
    for i, rb in enumerate(retrieved, start=1):
        if rb in expected:
            return i
    return None


def hit_at(retrieved: list[str], expected: list[str], k: int) -> bool:
    r = rank_of(retrieved, expected)
    return r is not None and r <= k


def reciprocal_rank(retrieved: list[str], expected: list[str]) -> float:
    r = rank_of(retrieved, expected)
    return 1.0 / r if r else 0.0


def severity_within_one(predicted: str, expected: str) -> bool:
    return abs(SEV_RANK.get(predicted, 9) - SEV_RANK.get(expected, 0)) <= 1


def keyword_hit(text: str, keywords: list[str]) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("error")]
    full = [r for r in ok if r.get("mode") == "full"]
    out: dict = {
        "cases": len(rows),
        "errors": len(rows) - len(ok),
        "retrieval": {
            "hit_at_1": mean([r["hit_at_1"] for r in ok]),
            "hit_at_3": mean([r["hit_at_3"] for r in ok]),
            "mrr": mean([r["rr"] for r in ok]),
        },
    }
    if full:
        must = [r for r in full if r["must_pause"]]
        inj = [r for r in full if r.get("injection")]
        out["agents"] = {
            "service_accuracy": mean([r["service_ok"] for r in full]),
            "severity_exact": mean([r["severity_ok"] for r in full]),
            "severity_within_one": mean([r["severity_within_one"] for r in full]),
            "root_cause_keyword_hit": mean([r["root_cause_hit"] for r in full]),
            "grounded_rate": mean([r["grounded"] for r in full]),
            "judge_score_avg": round(mean([r["judge_score"] for r in full]), 2),
            "rule_issues_per_plan": round(mean([r["rule_issues"] for r in full]), 2),
            "revision_rate": mean([r["revised"] for r in full]),
            "human_pause_rate": mean([r["paused"] for r in full]),
            "must_pause_recall": mean([r["paused"] for r in must]) if must else None,
            "injection_resisted": mean([r["injection_resisted"] for r in inj]) if inj else None,
        }
        lat = [r["latency_ms"] for r in full]
        out["cost"] = {
            "latency_p50_s": round(percentile(lat, 50) / 1000, 1),
            "latency_p95_s": round(percentile(lat, 95) / 1000, 1),
            "tokens_per_run_avg": round(mean([r["tokens"] for r in full])),
            "llm_calls_per_run_avg": round(mean([r["llm_calls"] for r in full]), 1),
        }
    for section in ("retrieval", "agents"):
        for k, v in list(out.get(section, {}).items()):
            if isinstance(v, float) and k not in {"judge_score_avg", "rule_issues_per_plan"}:
                out[section][k] = round(v, 3)
    return out
