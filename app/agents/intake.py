"""Intake agent: classify the ticket (service, severity, category, symptoms)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts import INTAKE_SYSTEM
from app.deps import Deps
from app.llm import invoke_structured
from app.observability import traced
from app.schemas import IntakeResult
from app.tools.log_parser import parse_log_signatures


def make_intake(deps: Deps):
    @traced("intake")
    async def intake(state: dict) -> dict:
        ticket, logs = state["ticket"], state.get("logs", "")
        signatures = parse_log_signatures(f"{ticket}\n{logs}")
        names = ", ".join(s["signature"] for s in signatures) or "none"
        messages = [
            SystemMessage(content=INTAKE_SYSTEM),
            HumanMessage(content=f"<ticket>\n{ticket}\n</ticket>\n<logs>\n{logs[:3000] or '(none)'}\n</logs>\n"
                                 f"Detected log signatures: {names}"),
        ]
        result = await invoke_structured(deps.llms.fast, IntakeResult, messages)
        return {
            "intake": result.model_dump(),
            "signatures": signatures,
            "_note": f"{result.service} · {result.severity} · {result.category}",
        }

    return intake
