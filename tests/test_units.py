from __future__ import annotations

import pytest

from app.agents.critic import normalise_citation, rule_checks
from app.agents.supervisor import allowed_next
from app.config import ROOT
from app.rag.chunking import RunbookIndex, load_runbooks
from app.ratelimit import RateLimiter
from app.schemas import IntakeResult, Plan, normalise_service, normalise_severity
from app.tools.log_parser import parse_log_signatures
from app.tools.sql_guard import UnsafeSQLError, validate_select

INDEX = RunbookIndex(load_runbooks(ROOT / "data" / "runbooks"))


# ---------- SQL guard ----------

@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE incidents",
    "DELETE FROM incidents",
    "UPDATE incidents SET status = 'x'",
    "PRAGMA table_info(incidents)",
    "ATTACH DATABASE 'x.db' AS x",
    "SELECT * FROM sqlite_master",
    "SELECT load_extension('evil')",
    "",
])
def test_sql_guard_rejects_unsafe(sql):
    with pytest.raises(UnsafeSQLError):
        validate_select(sql)


def test_sql_guard_forces_limit():
    assert validate_select("SELECT * FROM incidents").endswith("LIMIT 50")
    assert validate_select("SELECT * FROM incidents LIMIT 500").endswith("LIMIT 50")
    assert validate_select("SELECT * FROM incidents LIMIT 5").endswith("LIMIT 5")


def test_sql_guard_allows_cte():
    out = validate_select("WITH t AS (SELECT service FROM incidents) SELECT service, COUNT(*) FROM t GROUP BY service")
    assert "LIMIT 50" in out


# ---------- log parser ----------

def test_log_signatures():
    sigs = {s["signature"] for s in parse_log_signatures(
        "Reason: OOMKilled Exit Code: 137\nERROR: No space left on device\ngetaddrinfo EAI_AGAIN host")}
    assert {"oom_killed", "disk_full", "dns_failure"} <= sigs


# ---------- chunking ----------

def test_runbooks_chunk_by_section():
    assert len(INDEX.runbooks) == 15
    c = INDEX.get("RB-003#remediation")
    assert c is not None and c.services == ["orders-db"]
    assert [s.risk for s in c.steps] == ["medium", "high", "high"]
    assert "pg_drop_replication_slot" in c.steps[1].commands[0]


# ---------- normalisers ----------

def test_normalisers():
    assert normalise_severity("P1") == "SEV1"
    assert normalise_severity("Sev 2") == "SEV2"
    assert normalise_service("Orders DB (postgres)") == "orders-db"
    assert normalise_service("payments") == "payments-api"
    r = IntakeResult(service="Kubernetes", severity="critical", category="k8s", summary="x", symptoms=["a"] * 9)
    assert (r.service, r.severity, len(r.symptoms)) == ("k8s-platform", "SEV1", 5)


def test_plan_confidence_percent_is_scaled():
    p = Plan(root_cause_hypothesis="x", confidence=85, steps=[{"action": "a", "risk": "HIGH", "citation": "RB-001"}])
    assert p.confidence == 0.85 and p.steps[0].risk == "high"


# ---------- supervisor bounds ----------

def test_supervisor_allowed_options():
    assert allowed_next([]) == ["runbook_agent", "history_agent"]
    assert allowed_next(["history_agent"]) == ["runbook_agent"]
    assert allowed_next(["runbook_agent"]) == ["history_agent", "planner"]
    assert allowed_next(["runbook_agent", "history_agent"]) == ["planner"]


# ---------- critic rules ----------

def test_citation_normalisation():
    assert normalise_citation("[RB-003 remediation]") == "RB-003#remediation"
    assert normalise_citation("rb-003#Diagnosis") == "RB-003#diagnosis"
    assert normalise_citation("INC-1155") == "INC-1155"


def test_critic_flags_invented_and_underrated_steps():
    allowed = {"RB-003#diagnosis", "RB-003#remediation", "INC-1155"}
    plan = {"steps": [
        {"action": "Check disk", "command": "df -h /var/lib/postgresql", "risk": "low", "citation": "RB-003#diagnosis"},
        {"action": "Drop slot", "command": "psql -c \"SELECT pg_drop_replication_slot('<slot_name>');\"",
         "risk": "medium", "citation": "RB-003#remediation"},
        {"action": "Wipe the volume", "command": "rm -rf /var/lib/postgresql", "risk": "low", "citation": "RB-003#remediation"},
        {"action": "Restart", "command": "", "risk": "low", "citation": "RB-099#remediation"},
    ]}
    issues, effective = rule_checks(plan, allowed, INDEX)
    text = " ".join(issues)
    assert "Step 2 is labelled medium but RB-003#remediation marks it high" in text
    assert "Step 3 command" in text
    assert "Step 4 cites RB-099#remediation" in text
    assert effective[1] == "high"  # the gate sees the runbook's risk, not the model's label


def test_critic_accepts_grounded_plan():
    from tests.fakes import DISK_PLAN
    allowed = {"RB-003#diagnosis", "RB-003#remediation", "INC-1155"}
    issues, effective = rule_checks(DISK_PLAN, allowed, INDEX)
    assert issues == []
    assert effective == ["low", "low", "high", "low"]


# ---------- rate limiter ----------

def test_rate_limiter():
    rl = RateLimiter(per_hour=2)
    assert rl.check("a")[0] and rl.check("a")[0]
    ok, retry = rl.check("a")
    assert not ok and retry > 0
    assert rl.check("b")[0]
