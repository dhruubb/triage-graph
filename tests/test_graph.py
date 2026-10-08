"""End-to-end graph runs with a scripted model: routing, tools, critic, interrupt and resume."""

from __future__ import annotations

import pytest
from langgraph.types import Command

from app.graph import build_graph
from tests.conftest import CERT_INTAKE, DISK_INTAKE, DISK_LOGS, DISK_TICKET
from tests.fakes import CERT_PLAN, DISK_PLAN, Scenario

pytestmark = pytest.mark.asyncio


def initial(ticket: str, logs: str = "", thread: str = "t1") -> dict:
    return {"thread_id": thread, "ticket_id": "TKT-TEST", "ticket": ticket, "logs": logs, "trace": [],
            "done_workers": [], "supervisor_steps": 0, "planner_runs": 0}


async def run(graph, payload, thread="t1"):
    cfg = {"configurable": {"thread_id": thread}}
    nodes, interrupts = [], []
    async for chunk in graph.astream(payload, cfg, stream_mode="updates"):
        for node, update in chunk.items():
            (interrupts if node == "__interrupt__" else nodes).append(update if node == "__interrupt__" else node)
    return nodes, interrupts, await graph.aget_state(cfg)


async def test_high_risk_run_pauses_for_approval_then_executes(make_deps):
    scenario = Scenario(DISK_INTAKE, routes=["runbook_agent", "history_agent"], plans=[DISK_PLAN])
    deps = make_deps(scenario)
    graph = build_graph(deps)

    nodes, interrupts, snap = await run(graph, initial(DISK_TICKET, DISK_LOGS))
    assert nodes == ["intake", "supervisor", "runbook_agent", "supervisor", "history_agent", "supervisor",
                     "planner", "critic"]
    assert snap.next == ("approval_gate",)
    payload = interrupts[0][0].value
    assert "SEV1 incident" in payload["reasons"]
    assert any("high-risk" in r for r in payload["reasons"])

    values = snap.values
    assert values["runbook_hits"][0]["runbook_id"] == "RB-003"
    # The history agent called its tools, the SQL guard blocked the DELETE, and the invented id was dropped.
    calls = values["history"]["tool_calls"]
    assert [c["tool"] for c in calls] == ["find_similar_incidents", "run_readonly_sql"]
    assert calls[1]["ok"] is False
    assert values["history"]["dropped_ids"] == ["INC-9999"]
    assert values["critique"]["grounded"] is True

    nodes, _, snap = await run(graph, Command(resume={"approved": True, "reviewer": "asha", "comment": "go"}))
    assert nodes == ["approval_gate", "executor", "reporter"]
    report = snap.values["report"]
    assert report["status"] == "executed (simulated)"
    assert report["approval"]["reviewer"] == "asha"
    assert report["executed_steps"] == 4
    assert report["totals"]["llm_calls"] > 0
    assert len(deps.audit.for_thread("t1")) == 4


async def test_rejection_skips_execution(make_deps):
    deps = make_deps(Scenario(DISK_INTAKE, routes=["runbook_agent", "history_agent"], plans=[DISK_PLAN]))
    graph = build_graph(deps)
    await run(graph, initial(DISK_TICKET, DISK_LOGS, "t2"), "t2")
    nodes, _, snap = await run(graph, Command(resume={"approved": False, "reviewer": "asha"}), "t2")
    assert nodes == ["approval_gate", "reporter"]
    assert snap.values["report"]["status"] == "rejected by reviewer"
    assert deps.audit.for_thread("t2") == []


async def test_low_risk_run_is_auto_approved(make_deps):
    # Supervisor decides history isn't needed and goes straight to the planner.
    deps = make_deps(Scenario(CERT_INTAKE, routes=["runbook_agent", "planner"], plans=[CERT_PLAN]))
    graph = build_graph(deps)
    nodes, interrupts, snap = await run(graph, initial("Login certificate expires in 9 days; cert-manager not ready.", "", "t3"), "t3")
    assert interrupts == []
    assert "history_agent" not in nodes
    assert snap.values["approval"]["required"] is False
    assert snap.values["report"]["status"] == "executed (simulated)"


async def test_critic_sends_ungrounded_plan_back_once(make_deps):
    bad = {**DISK_PLAN, "steps": [dict(s) for s in DISK_PLAN["steps"]]}
    bad["steps"][2]["risk"] = "medium"                    # under-labelled
    bad["steps"][0]["citation"] = "RB-042#diagnosis"      # not a source
    deps = make_deps(Scenario(DISK_INTAKE, routes=["runbook_agent", "history_agent"], plans=[bad, DISK_PLAN]))
    graph = build_graph(deps)
    nodes, _, snap = await run(graph, initial(DISK_TICKET, DISK_LOGS, "t4"), "t4")
    assert nodes.count("planner") == 2 and nodes.count("critic") == 2
    assert snap.values["critique"]["grounded"] is True
    assert snap.values["planner_runs"] == 2


async def test_invalid_route_falls_back(make_deps):
    deps = make_deps(Scenario(CERT_INTAKE, routes=["reboot_everything", "planner"], plans=[CERT_PLAN]))
    graph = build_graph(deps)
    nodes, _, snap = await run(graph, initial("Login certificate expires soon", "", "t5"), "t5")
    assert nodes[2] == "runbook_agent"  # fallback to the first allowed option
    assert "fallback" in snap.values["trace"][1]["note"]


async def test_model_that_skips_tools_gets_deterministic_lookup(make_deps):
    deps = make_deps(Scenario(DISK_INTAKE, routes=["history_agent", "runbook_agent"], plans=[DISK_PLAN], use_tools=False))
    graph = build_graph(deps)
    _, _, snap = await run(graph, initial(DISK_TICKET, DISK_LOGS, "t6"), "t6")
    assert snap.values["history"]["tool_calls"][0].get("fallback") is True
