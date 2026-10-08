"""The LangGraph workflow.

    intake → supervisor ─┬→ runbook_agent ─┐
                         ├→ history_agent ─┤ (back to supervisor)
                         └→ planner → critic ─┬→ planner (one revision if not grounded)
                                              └→ approval_gate ─┬→ executor → reporter → END
                                                   (interrupt)  └→ reporter (rejected) → END
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.approval import make_approval_gate
from app.agents.critic import make_critic
from app.agents.executor import make_executor
from app.agents.history import make_history_agent
from app.agents.intake import make_intake
from app.agents.planner import make_planner
from app.agents.reporter import make_reporter
from app.agents.runbook import make_runbook_agent
from app.agents.supervisor import make_supervisor
from app.deps import Deps
from app.state import TriageState

NODES = ["intake", "supervisor", "runbook_agent", "history_agent", "planner", "critic",
         "approval_gate", "executor", "reporter"]


def route_supervisor(state: dict) -> str:
    return state["next"]


def route_critic(state: dict) -> str:
    return "planner" if state["critique"].get("revise") else "approval_gate"


def route_approval(state: dict) -> str:
    return "executor" if state["approval"].get("approved") else "reporter"


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(TriageState)
    g.add_node("intake", make_intake(deps))
    g.add_node("supervisor", make_supervisor(deps))
    g.add_node("runbook_agent", make_runbook_agent(deps))
    g.add_node("history_agent", make_history_agent(deps))
    g.add_node("planner", make_planner(deps))
    g.add_node("critic", make_critic(deps))
    g.add_node("approval_gate", make_approval_gate(deps))
    g.add_node("executor", make_executor(deps))
    g.add_node("reporter", make_reporter(deps))

    g.add_edge(START, "intake")
    g.add_edge("intake", "supervisor")
    g.add_conditional_edges("supervisor", route_supervisor,
                            {"runbook_agent": "runbook_agent", "history_agent": "history_agent", "planner": "planner"})
    g.add_edge("runbook_agent", "supervisor")
    g.add_edge("history_agent", "supervisor")
    g.add_edge("planner", "critic")
    g.add_conditional_edges("critic", route_critic, {"planner": "planner", "approval_gate": "approval_gate"})
    g.add_conditional_edges("approval_gate", route_approval, {"executor": "executor", "reporter": "reporter"})
    g.add_edge("executor", "reporter")
    g.add_edge("reporter", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
