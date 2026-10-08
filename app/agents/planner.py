"""Planner agent: a cited, risk-labelled remediation plan from the gathered sources."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts import PLANNER_SYSTEM
from app.config import RISK_ORDER
from app.deps import Deps
from app.llm import invoke_structured
from app.observability import traced
from app.schemas import Plan

PLAN_SECTIONS = {"diagnosis", "remediation", "rollback", "escalation"}


def format_sources(state: dict) -> tuple[str, set[str]]:
    """Sources shown to the planner and critic, and the set of ids that may be cited."""
    blocks, ids = [], set()
    for c in state.get("context_chunks", []):
        if c["section"].lower() not in PLAN_SECTIONS:
            continue
        blocks.append(f"[{c['chunk_id']}]\n{c['text']}")
        ids.add(c["chunk_id"])
    for s in (state.get("history") or {}).get("similar_incidents", []):
        blocks.append(f"[{s['incident_id']}] Past incident: {s.get('title', '')}. "
                      f"Cause: {s.get('root_cause', '')}. Fix: {s.get('resolution', '')}")
        ids.add(s["incident_id"])
    return "\n\n".join(blocks), ids


def make_planner(deps: Deps):
    @traced("planner")
    async def planner(state: dict) -> dict:
        intake = state["intake"]
        sources, _ = format_sources(state)
        history = (state.get("history") or {}).get("summary", "not checked")
        feedback = ""
        critique = state.get("critique")
        if critique and critique.get("revise"):
            problems = critique.get("rule_issues", []) + critique.get("judge_issues", [])
            feedback = "\n\nYour previous plan had these problems. Fix them:\n- " + "\n- ".join(problems[:6])
        messages = [
            SystemMessage(content=PLANNER_SYSTEM),
            HumanMessage(content=f"Incident: {intake['service']} {intake['severity']}: {intake['summary']}\n"
                                 f"Symptoms: {'; '.join(intake['symptoms'])}\n"
                                 f"History: {history}\n\nSources:\n{sources}{feedback}"),
        ]
        plan = await invoke_structured(deps.llms.smart, Plan, messages)
        runs = state.get("planner_runs", 0) + 1
        max_risk = max((s.risk for s in plan.steps), key=lambda r: RISK_ORDER[r])
        return {
            "plan": plan.model_dump(),
            "planner_runs": runs,
            "_note": f"{len(plan.steps)} steps · max risk {max_risk} · confidence {plan.confidence:.2f}"
                     + (" · revision" if runs > 1 else ""),
        }

    return planner
