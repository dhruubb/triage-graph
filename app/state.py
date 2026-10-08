"""Shared graph state. Each node returns a partial update; `trace` is appended, not replaced."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class TriageState(TypedDict, total=False):
    thread_id: str
    ticket_id: str
    ticket: str
    logs: str

    signatures: list[dict]          # regex log signatures
    intake: dict                    # IntakeResult
    next: str                       # supervisor's choice
    route_reason: str
    supervisor_steps: int
    done_workers: list[str]

    runbook_hits: list[dict]        # ranked runbooks from hybrid search
    context_chunks: list[dict]      # full sections of the top runbooks
    history: dict                   # HistoryFindings + tool call log

    plan: dict                      # Plan
    planner_runs: int
    critique: dict                  # rule checks + LLM judge
    approval: dict                  # human or policy decision
    execution: list[dict]           # simulated actions
    report: dict                    # final report

    trace: Annotated[list[dict], operator.add]
