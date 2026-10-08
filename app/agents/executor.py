"""Executor: SIMULATED. Nothing touches real infrastructure.

Each approved step is recorded as a dry run in the audit log, with who approved it.
Swapping in real executors (Kubernetes API, Azure Automation runbooks) would happen here,
behind the same approval gate.
"""

from __future__ import annotations

from app.deps import Deps
from app.observability import traced


def make_executor(deps: Deps):
    @traced("executor")
    async def executor(state: dict) -> dict:
        approval = state["approval"]
        effective = state.get("critique", {}).get("effective_risks", [])
        records = []
        for n, step in enumerate(state["plan"]["steps"], start=1):
            risk = effective[n - 1] if n - 1 < len(effective) else step["risk"]
            output = f"dry run: would run `{step['command']}`" if step.get("command") else "manual step recorded"
            record = {"step": n, "action": step["action"], "command": step.get("command", ""), "risk": risk,
                      "status": "simulated", "output": output}
            records.append(record)
            deps.audit.write(thread_id=state.get("thread_id"), ticket_id=state.get("ticket_id"), step=n,
                             action=step["action"], command=step.get("command", ""), risk=risk,
                             approved_by=approval.get("reviewer"), status="simulated", detail={"output": output})
        return {"execution": records, "_note": f"{len(records)} step(s) recorded as dry runs"}

    return executor
