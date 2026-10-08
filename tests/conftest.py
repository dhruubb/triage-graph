from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.deps import build_deps
from app.llm import LLMs
from tests.fakes import scripted

ROOT = Path(__file__).resolve().parent.parent

DISK_INTAKE = {"service": "orders-db", "severity": "SEV1", "category": "database",
               "summary": "Orders database rejects writes because the data volume is full.",
               "symptoms": ["No space left on device", "inserts failing", "reads still work"]}
CERT_INTAKE = {"service": "auth-service", "severity": "SEV3", "category": "certificate",
               "summary": "Login TLS certificate expires in 9 days and cert-manager shows it not ready.",
               "symptoms": ["certificate expiring", "Certificate not ready"]}

DISK_TICKET = ("Order placement failing since 09:40, database write errors, reads still work. "
               "We decommissioned the old reporting replica last week.")
DISK_LOGS = "ERROR: could not extend file: No space left on device\nDiskUsageHigh /var/lib/postgresql 97%"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        groq_api_key="test",
        embeddings="hash",
        qdrant_url="",
        runtime_dir=tmp_path / "runtime",
        frontend_dist=tmp_path / "no-dist",
        eval_results_path=tmp_path / "latest.json",
        rate_limit_per_hour=0,
    )


@pytest.fixture
def make_deps(settings: Settings):
    def _make(scenario, settings_override: Settings | None = None):
        model = scripted(scenario)
        return build_deps(settings_override or settings, llms=LLMs(fast=model, smart=model))

    return _make
