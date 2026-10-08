"""Regressions found in real runs."""

from __future__ import annotations

import pytest

from app.agents.critic import command_matches, rule_checks
from app.agents.reporter import ensure_outcome_stated
from app.config import ROOT
from app.graph import build_graph
from app.rag.chunking import RunbookIndex, load_runbooks
from app.schemas import ExecutiveSummary
from tests.conftest import CERT_INTAKE
from tests.fakes import CERT_PLAN, Scenario

INDEX = RunbookIndex(load_runbooks(ROOT / "data" / "runbooks"))
ALLOWED = {"RB-001#diagnosis", "RB-001#remediation"}


def step(command: str) -> dict:
    return {"steps": [{"action": "Check the pods", "command": command, "risk": "low", "citation": "RB-001#diagnosis"}]}


def test_altered_command_is_rejected_with_a_hint():
    # A real run: the planner dropped `-v`, which inverts what the command shows.
    issues, _ = rule_checks(step("kubectl get pods -n <namespace> | grep Running"), ALLOWED, INDEX)
    assert len(issues) == 1
    assert "does not match any command in RB-001#diagnosis" in issues[0]
    assert "the closest is `kubectl get pods -n <namespace> | grep -v Running`" in issues[0]


def test_exact_and_filled_placeholder_commands_pass():
    assert rule_checks(step("kubectl get pods -n <namespace> | grep -v Running"), ALLOWED, INDEX)[0] == []
    assert rule_checks(step("kubectl get pods -n payments | grep -v Running"), ALLOWED, INDEX)[0] == []
    assert rule_checks(step("kubectl  get pods -n payments |  grep -v Running"), ALLOWED, INDEX)[0] == []  # spacing


@pytest.mark.parametrize("command", [
    "kubectl get pods -n payments | grep -v Running; rm -rf /",   # extra command appended
    "kubectl get pods -n payments -o wide | grep -v Running",      # extra flag
    "sudo kubectl get pods -n payments | grep -v Running",         # prefix added
])
def test_additions_to_a_runbook_command_are_rejected(command):
    assert not command_matches(command, "kubectl get pods -n <namespace> | grep -v Running")


def test_placeholder_matches_one_token_only():
    assert command_matches("kubectl describe pod web-1 -n shop", "kubectl describe pod <pod> -n <namespace>")
    assert not command_matches("kubectl describe pod web-1 && reboot -n shop", "kubectl describe pod <pod> -n <namespace>")


def test_summary_that_claims_actions_gets_the_dry_run_stated():
    s = ensure_outcome_stated("We raised the memory limit and verified the pods are running.", approved=True)
    assert s.endswith("recorded as a dry run.")
    ok = "The plan was approved and recorded as a dry run."
    assert ensure_outcome_stated(ok, approved=True) == ok
    assert ensure_outcome_stated("Pods crashed from OOM.", approved=False).endswith("nothing was run.")


class OverclaimingScenario(Scenario):
    """The reporter model claims the fix was applied; capture what it was told."""

    seen: list = []

    def __call__(self, kind, spec, messages):
        if kind == "structured" and spec.__name__ == "ExecutiveSummary":
            self.seen.append(messages[-1].content)
            return ExecutiveSummary(summary="We renewed the certificate and confirmed it is valid.")
        return super().__call__(kind, spec, messages)


@pytest.mark.asyncio
async def test_reporter_is_told_the_truth_and_corrects_overclaims(make_deps):
    scenario = OverclaimingScenario(CERT_INTAKE, routes=["runbook_agent", "planner"], plans=[CERT_PLAN])
    graph = build_graph(make_deps(scenario))
    state = {"thread_id": "r1", "ticket_id": "TKT-R1", "ticket": "Login certificate expires in 9 days", "logs": "",
             "trace": [], "done_workers": [], "supervisor_steps": 0, "planner_runs": 0}
    await graph.ainvoke(state, {"configurable": {"thread_id": "r1"}})
    snap = await graph.aget_state({"configurable": {"thread_id": "r1"}})
    assert "recorded as a dry run only; nothing was changed" in scenario.seen[-1]
    assert snap.values["report"]["executive_summary"].endswith("recorded as a dry run.")
