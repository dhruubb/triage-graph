from __future__ import annotations

import json

import pytest

from app.config import ROOT
from app.graph import build_graph
from eval.metrics import aggregate, hit_at, keyword_hit, reciprocal_rank, severity_within_one
from eval.run import run_full, run_retrieval_only
from tests.conftest import DISK_INTAKE
from tests.fakes import DISK_PLAN, Scenario


def test_metric_functions():
    assert hit_at(["RB-002", "RB-003"], ["RB-003"], 1) is False
    assert hit_at(["RB-002", "RB-003"], ["RB-003"], 3) is True
    assert reciprocal_rank(["RB-002", "RB-003"], ["RB-003"]) == 0.5
    assert reciprocal_rank(["RB-001"], ["RB-003"]) == 0.0
    assert severity_within_one("SEV2", "SEV1") and not severity_within_one("SEV3", "SEV1")
    assert keyword_hit("Inactive replication SLOT held WAL", ["replication slot"])


def test_golden_set_is_well_formed():
    cases = [json.loads(line) for line in (ROOT / "eval" / "golden.jsonl").read_text().splitlines()]
    assert len(cases) == 20 and len({c["id"] for c in cases}) == 20
    for c in cases:
        assert {"ticket", "logs", "service", "severity", "runbooks", "root_cause_keywords", "must_pause"} <= c.keys()


def test_retrieval_only_mode(make_deps):
    deps = make_deps(Scenario(DISK_INTAKE, [], [DISK_PLAN]))
    cases = [json.loads(line) for line in (ROOT / "eval" / "golden.jsonl").read_text().splitlines()]
    rows = [run_retrieval_only(deps, c) for c in cases]
    summary = aggregate(rows)
    assert summary["cases"] == 20
    assert 0 <= summary["retrieval"]["mrr"] <= 1


@pytest.mark.asyncio
async def test_full_mode_row(make_deps):
    deps = make_deps(Scenario(DISK_INTAKE, ["runbook_agent", "history_agent"], [DISK_PLAN]))
    case = json.loads((ROOT / "eval" / "golden.jsonl").read_text().splitlines()[0])
    row = await run_full(build_graph(deps), case)
    assert row["service_ok"] and row["paused"] and row["must_pause"]
    assert row["hit_at_3"] and row["root_cause_hit"]
    agg = aggregate([row])
    assert agg["agents"]["must_pause_recall"] == 1.0
