"""API tests: SSE streaming, approval over HTTP, validation and rate limiting."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import CERT_INTAKE, DISK_INTAKE, DISK_LOGS, DISK_TICKET
from tests.fakes import CERT_PLAN, DISK_PLAN, Scenario


def events(response) -> list[tuple[str, dict]]:
    out, event = [], None
    for line in response.iter_lines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            out.append((event, json.loads(line[6:])))
    return out


def client_for(make_deps, scenario, settings=None):
    deps = make_deps(scenario, settings)
    return TestClient(create_app(settings=deps.settings, deps=deps))


def test_health_and_samples(make_deps):
    with client_for(make_deps, Scenario(CERT_INTAKE, [], [CERT_PLAN])) as c:
        h = c.get("/api/health").json()
        assert h["vector_store"]["chunks"] == 75 and h["incidents"] == 160
        assert len(c.get("/api/samples").json()) >= 5
        assert c.get("/api/eval/latest").status_code == 404


def test_triage_stream_and_approval_over_http(make_deps):
    with client_for(make_deps, Scenario(DISK_INTAKE, ["runbook_agent", "history_agent"], [DISK_PLAN])) as c:
        with c.stream("POST", "/api/triage", json={"ticket": DISK_TICKET, "logs": DISK_LOGS}) as r:
            assert r.status_code == 200
            evs = events(r)
        kinds = [e for e, _ in evs]
        assert kinds[0] == "start" and kinds[-1] == "approval_required"
        thread = evs[0][1]["thread_id"]
        node_events = [d for e, d in evs if e == "node"]
        assert node_events[0]["node"] == "intake" and node_events[0]["trace"]["latency_ms"] >= 0
        assert "context_chunks" not in json.dumps(node_events)  # bulky text stays server-side

        run = c.get(f"/api/runs/{thread}").json()
        assert run["awaiting_approval"] is True

        with c.stream("POST", f"/api/runs/{thread}/resume", json={"approved": True, "reviewer": "asha"}) as r:
            evs = events(r)
        assert evs[-1][0] == "done"
        assert evs[-1][1]["report"]["status"] == "executed (simulated)"
        assert c.post(f"/api/runs/{thread}/resume", json={"approved": True}).status_code == 409
        assert c.get("/api/metrics").json()["counters"]["runs.completed"] == 1


def test_validation_and_unknown_run(make_deps):
    with client_for(make_deps, Scenario(CERT_INTAKE, [], [CERT_PLAN])) as c:
        assert c.post("/api/triage", json={"ticket": "short"}).status_code == 422
        assert c.post("/api/triage", json={"ticket": "x" * 5000}).status_code == 413
        assert c.post("/api/runs/nope/resume", json={"approved": True}).status_code == 404


def test_rate_limit(make_deps, settings):
    limited = settings.model_copy(update={"rate_limit_per_hour": 1})
    with client_for(make_deps, Scenario(CERT_INTAKE, ["runbook_agent", "planner"], [CERT_PLAN]), limited) as c:
        with c.stream("POST", "/api/triage", json={"ticket": "Login certificate expires in 9 days"}) as r:
            events(r)
        r2 = c.post("/api/triage", json={"ticket": "Login certificate expires in 9 days"})
        assert r2.status_code == 429 and "Retry-After" in r2.headers
