"""Supervisor: an LLM chooses the next worker; code bounds what it may choose.

The model decides the order and whether history is worth checking. The code decides
what is allowed (the planner needs runbook context first) and stops the loop after
max_supervisor_steps, so a confused model can't cycle forever.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts import SUPERVISOR_SYSTEM
from app.deps import Deps
from app.llm import StructuredOutputError, invoke_structured
from app.observability import traced
from app.schemas import Route

WORKERS = ["runbook_agent", "history_agent"]


def allowed_next(done: list[str]) -> list[str]:
    remaining = [w for w in WORKERS if w not in done]
    return remaining + (["planner"] if "runbook_agent" in done else [])


def make_supervisor(deps: Deps):
    max_steps = deps.settings.max_supervisor_steps

    @traced("supervisor")
    async def supervisor(state: dict) -> dict:
        done = state.get("done_workers", [])
        steps = state.get("supervisor_steps", 0)
        allowed = allowed_next(done)

        if steps >= max_steps:
            choice, reason = "planner", "step budget reached"
        elif allowed == ["planner"]:
            choice, reason = "planner", "all context gathered"
        else:
            intake = state["intake"]
            sigs = ", ".join(s["signature"] for s in state.get("signatures", [])) or "none"
            messages = [
                SystemMessage(content=SUPERVISOR_SYSTEM),
                HumanMessage(content=f"Incident: {intake['service']} {intake['severity']}: {intake['summary']}\n"
                                     f"Log signatures: {sigs}\n"
                                     f"Already done: {', '.join(done) or 'nothing'}\n"
                                     f"Allowed options: {', '.join(allowed)}"),
            ]
            try:
                route = await invoke_structured(deps.llms.fast, Route, messages)
                picked = route.next.strip().lower().replace(" ", "_")
                choice, reason = (picked, route.reason) if picked in allowed else (allowed[0], f"fallback: model chose '{route.next}'")
            except StructuredOutputError:
                choice, reason = allowed[0], "fallback: routing call failed"

        return {"next": choice, "route_reason": reason, "supervisor_steps": steps + 1,
                "_note": f"→ {choice}: {reason}"}

    return supervisor
