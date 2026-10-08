"""Hybrid retrieval against embedded Qdrant. Uses the hashing embedder, so no downloads."""

from __future__ import annotations

from app.config import ROOT
from app.rag.chunking import load_runbooks
from app.rag.embeddings import HashDense, SparseBM25
from app.rag.store import RunbookStore


def make_store() -> RunbookStore:
    store = RunbookStore.connect("", "", "runbooks", HashDense(), SparseBM25())
    store.ingest(load_runbooks(ROOT / "data" / "runbooks"))
    return store


def test_ingest_is_idempotent():
    store = make_store()
    n = store.count()
    store.ingest(load_runbooks(ROOT / "data" / "runbooks"))
    assert store.count() == n == 75


def test_exact_error_strings_find_the_right_runbook():
    store = make_store()
    cases = {
        "could not extend file No space left on device postgres writes failing": "RB-003",
        "pods CrashLoopBackOff OOMKilled exit code 137": "RB-001",
        "getaddrinfo EAI_AGAIN internal service names coredns": "RB-009",
        "IKE_SA_INIT timeout branch office tunnel": "RB-010",
    }
    for query, expected in cases.items():
        ids = [r["runbook_id"] for r in store.retrieve(query, k=3).runbooks]
        assert expected in ids, (query, ids)


def test_service_bonus_and_full_runbook_fetch():
    store = make_store()
    res = store.retrieve("certificate expired renew", service="auth-service", k=3)
    assert res.runbooks[0]["runbook_id"] == "RB-004"
    sections = [c["section"] for c in res.chunks if c["runbook_id"] == "RB-004"]
    assert sections == ["Symptoms", "Diagnosis", "Remediation", "Rollback", "Escalation"]
