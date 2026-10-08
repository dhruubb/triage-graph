"""Approval gate: human-in-the-loop via LangGraph interrupt().

Policy: pause for a human when the effective risk is above AUTO_APPROVE_MAX_RISK, when
the incident is SEV1, or when the critic couldn't confirm the plan is grounded.
Otherwise approve automatically and record why. The graph state is checkpointed, so
the run resumes exactly here when the reviewer answers.
"""

from __future__ import annotations

from langgraph.types import interrupt

from app.config import RISK_ORDER
from app.deps import Deps
from app.observability import METRICS, traced


def approval_reasons(state: dict, auto_max: str) -> list[str]:
    critique = state.get("critique", {})
    eff = critique.get("effective_max_risk", "high")
    reasons = []
    if RISK_ORDER[eff] > RISK_ORDER[auto_max]:
        reasons.append(f"the plan contains {eff}-risk steps")
    if state["intake"]["severity"] == "SEV1":
        reasons.append("SEV1 incident")
    if not critique.get("grounded", False):
        reasons.append("the critic could not confirm every step is grounded in a source")
    return reasons


def make_approval_gate(deps: Deps):
    auto_max = deps.settings.auto_approve_max_risk

    @traced("approval_gate")
    async def approval_gate(state: dict) -> dict:
        reasons = approval_reasons(state, auto_max)
        if not reasons:
            eff = state.get("critique", {}).get("effective_max_risk", "low")
            METRICS.inc("approvals.auto")
            return {"approval": {"required": False, "approved": True, "reviewer": "policy",
                                 "comment": f"Auto-approved: highest risk is {eff}.", "reasons": []},
                    "_note": "auto-approved by policy"}

        METRICS.inc("approvals.requested")
        decision = interrupt({
            "ticket_id": state.get("ticket_id"),
            "service": state["intake"]["service"],
            "severity": state["intake"]["severity"],
            "reasons": reasons,
            "plan": state["plan"],
            "effective_risks": state.get("critique", {}).get("effective_risks", []),
        })
        approved = bool(decision.get("approved"))
        METRICS.inc("approvals.approved" if approved else "approvals.rejected")
        return {"approval": {"required": True, "approved": approved,
                             "reviewer": decision.get("reviewer", "on-call engineer"),
                             "comment": decision.get("comment", ""), "reasons": reasons},
                "_note": f"{'approved' if approved else 'rejected'} by {decision.get('reviewer', 'on-call engineer')}"}

    return approval_gate
