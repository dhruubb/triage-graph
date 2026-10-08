"""Reporter: a short executive summary plus a structured report assembled in code."""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts import REPORTER_SYSTEM
from app.deps import Deps
from app.llm import StructuredOutputError, invoke_structured
from app.observability import traced
from app.schemas import ExecutiveSummary


def ensure_outcome_stated(summary: str, approved: bool) -> str:
    """Safety net: the model sometimes writes "we raised the limit" as if it happened.
    If the summary doesn't say the actions were simulated (or rejected), say it."""
    if approved and not re.search(r"dry run|simulat|not (?:yet )?(?:run|executed|applied)", summary, re.IGNORECASE):
        summary = f"{summary.rstrip()} No changes were made to real systems: the approved steps were recorded as a dry run."
    if not approved and not re.search(r"reject|nothing was run|not run", summary, re.IGNORECASE):
        summary = f"{summary.rstrip()} The plan was rejected, so nothing was run."
    return summary


def make_reporter(deps: Deps):
    @traced("reporter")
    async def reporter(state: dict) -> dict:
        intake, plan = state["intake"], state["plan"]
        approval, critique = state.get("approval", {}), state.get("critique", {})
        history = state.get("history") or {}
        approved = bool(approval.get("approved"))
        status = "executed (simulated)" if approved else "rejected by reviewer"
        who = approval.get("reviewer", "policy")
        outcome = (f"Approved by {who}. The steps were recorded as a dry run only; nothing was changed on any real system."
                   if approved else f"Rejected by {who}. Nothing was run.")
        steps_text = "; ".join(s["action"] for s in plan["steps"])
        messages = [
            SystemMessage(content=REPORTER_SYSTEM),
            HumanMessage(content=f"Service: {intake['service']} ({intake['severity']}). Problem: {intake['summary']}\n"
                                 f"Likely cause: {plan['root_cause_hypothesis']} (confidence {plan['confidence']:.2f})\n"
                                 f"Planned steps: {steps_text}\nOutcome: {outcome} Reviewer comment: {approval.get('comment') or 'none'}\n"
                                 f"Escalate to: {plan.get('escalate_to') or 'not specified'}\n"
                                 f"History: {history.get('summary', 'not checked')}"),
        ]
        try:
            summary = (await invoke_structured(deps.llms.fast, ExecutiveSummary, messages)).summary
        except StructuredOutputError:
            summary = f"{intake['summary']} Likely cause: {plan['root_cause_hypothesis']}."
        summary = ensure_outcome_stated(summary, approved)

        trace = state.get("trace", [])
        report = {
            "ticket_id": state.get("ticket_id"),
            "status": status,
            "service": intake["service"],
            "severity": intake["severity"],
            "category": intake["category"],
            "executive_summary": summary,
            "root_cause_hypothesis": plan["root_cause_hypothesis"],
            "confidence": plan["confidence"],
            "steps": [{**s, "effective_risk": r} for s, r in
                      zip(plan["steps"], critique.get("effective_risks", [s["risk"] for s in plan["steps"]]))],
            "escalate_to": plan.get("escalate_to", ""),
            "runbooks": [{"runbook_id": r["runbook_id"], "title": r["title"], "score": r["score"]}
                         for r in state.get("runbook_hits", [])],
            "similar_incidents": history.get("similar_incidents", []),
            "grounded": critique.get("grounded"),
            "critic_score": critique.get("score"),
            "approval": approval,
            "executed_steps": len(state.get("execution", [])),
            "totals": {
                "latency_ms": round(sum(e["latency_ms"] for e in trace)),
                "input_tokens": sum(e["input_tokens"] for e in trace),
                "output_tokens": sum(e["output_tokens"] for e in trace),
                "llm_calls": sum(e["llm_calls"] for e in trace),
            },
        }
        return {"report": report, "_note": status}

    return reporter
