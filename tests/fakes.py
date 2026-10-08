"""A scripted chat model so the whole graph runs offline, deterministically, in tests and CI.

It supports the three ways the app talks to a model: plain calls, bind_tools()
(native tool calling) and with_structured_output().
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

USAGE = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


class ScriptedChatModel(BaseChatModel):
    responder: Any  # Callable[[str, Any, list[BaseMessage]], Any]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        tools = kwargs.get("tools")
        msg = self.responder("tools" if tools else "text", tools, messages)
        if isinstance(msg, str):
            msg = AIMessage(content=msg)
        msg.usage_metadata = dict(USAGE)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs: Any):
        return self.bind(tools=[t.name for t in tools])

    def with_structured_output(self, schema, *, include_raw: bool = False, **kwargs: Any):
        def run(inp: Any) -> Any:
            messages = inp if isinstance(inp, list) else inp.to_messages()
            obj = self.responder("structured", schema, messages)
            if include_raw:
                return {"raw": AIMessage(content="", usage_metadata=dict(USAGE)), "parsed": obj, "parsing_error": None}
            return obj

        return RunnableLambda(run)


DISK_PLAN = {
    "root_cause_hypothesis": "An inactive replication slot left by the decommissioned replica is retaining WAL and filled the data volume.",
    "confidence": 0.82,
    "escalate_to": "Database Reliability on-call",
    "steps": [
        {"action": "Check free space on the data volume", "command": "df -h /var/lib/postgresql",
         "risk": "low", "citation": "RB-003#diagnosis"},
        {"action": "Check for an inactive replication slot holding WAL",
         "command": "psql -c \"SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) FROM pg_replication_slots;\"",
         "risk": "low", "citation": "RB-003#diagnosis"},
        {"action": "Drop the inactive replication slot after confirming the replica is gone",
         "command": "psql -c \"SELECT pg_drop_replication_slot('<slot_name>');\"",
         "risk": "high", "citation": "RB-003#remediation"},
        {"action": "Check the recent similar incident for the fix that worked", "command": "",
         "risk": "low", "citation": "INC-1155"},
    ],
}

CERT_PLAN = {
    "root_cause_hypothesis": "cert-manager cannot renew the certificate.",
    "confidence": 0.7,
    "escalate_to": "Platform Security",
    "steps": [
        {"action": "Check the Certificate resource", "command": "kubectl describe certificate <name> -n <namespace>",
         "risk": "low", "citation": "RB-004#diagnosis"},
        {"action": "Trigger a renewal", "command": "cmctl renew <name> -n <namespace>",
         "risk": "medium", "citation": "RB-004#remediation"},
    ],
}


class Scenario:
    """Scripted answers for one run. Lists are consumed in order."""

    def __init__(self, intake: dict, routes: list[str], plans: list[dict], judge_scores: list[int] | None = None,
                 similar_id: str = "INC-1155", use_tools: bool = True):
        self.intake = intake
        self.routes = list(routes)
        self.plans = list(plans)
        self.judge_scores = list(judge_scores or [])
        self.similar_id = similar_id
        self.use_tools = use_tools
        self.tool_rounds = 0
        self.calls: list[str] = []

    def __call__(self, kind: str, spec: Any, messages: list[BaseMessage]) -> Any:
        from app.schemas import ExecutiveSummary, HistoryFindings, Judgement, Plan, Route, SimilarIncident

        if kind == "tools":
            self.tool_rounds += 1
            self.calls.append(f"tools:{self.tool_rounds}")
            if self.use_tools and self.tool_rounds == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "find_similar_incidents", "id": "c1",
                     "args": {"service": self.intake["service"], "keywords": ["space", "disk", "write"]}},
                    {"name": "run_readonly_sql", "id": "c2", "args": {"query": "DELETE FROM incidents"}},
                ])
            return AIMessage(content="Enough history gathered.")

        name = spec.__name__
        self.calls.append(name)
        if name == "IntakeResult":
            return spec(**self.intake)
        if name == "Route":
            return Route(next=self.routes.pop(0) if self.routes else "planner", reason="scripted")
        if name == "HistoryFindings":
            return HistoryFindings(summary="This has happened before on this service.",
                                   similar_incidents=[SimilarIncident(incident_id=self.similar_id),
                                                      SimilarIncident(incident_id="INC-9999")],
                                   recurring=True, typical_mttr_minutes=90)
        if name == "Plan":
            return Plan(**(self.plans.pop(0) if len(self.plans) > 1 else self.plans[0]))
        if name == "Judgement":
            return Judgement(score=self.judge_scores.pop(0) if self.judge_scores else 5, issues=[])
        if name == "ExecutiveSummary":
            return ExecutiveSummary(summary="Scripted executive summary.")
        raise AssertionError(f"unexpected schema {name}")


def scripted(scenario: Callable) -> ScriptedChatModel:
    return ScriptedChatModel(responder=scenario)
