"""Structured outputs the agents produce, plus API request models.

Validators normalise what LLMs tend to return ("P1", "Critical", "Orders DB") so a
slightly off answer is corrected instead of failing the run.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import SERVICES

SEVERITY_ALIASES = {
    "sev1": "SEV1", "p1": "SEV1", "critical": "SEV1", "sev-1": "SEV1", "1": "SEV1",
    "sev2": "SEV2", "p2": "SEV2", "high": "SEV2", "major": "SEV2", "sev-2": "SEV2", "2": "SEV2",
    "sev3": "SEV3", "p3": "SEV3", "medium": "SEV3", "moderate": "SEV3", "sev-3": "SEV3", "3": "SEV3",
    "sev4": "SEV4", "p4": "SEV4", "low": "SEV4", "minor": "SEV4", "sev-4": "SEV4", "4": "SEV4",
}


def normalise_severity(value: str) -> str:
    key = re.sub(r"\s+", "", str(value)).lower()
    return SEVERITY_ALIASES.get(key, "SEV3")


def normalise_service(value: str) -> str:
    v = str(value).strip().lower().replace("_", "-").replace(" ", "-")
    if v in SERVICES:
        return v
    for s in SERVICES:
        if s in v or v in s:
            return s
    hints = {
        "postgres": "orders-db", "database": "orders-db", "db": "orders-db",
        "payment": "payments-api", "checkout": "checkout-web", "login": "auth-service",
        "jwt": "auth-service", "kafka": "kafka-events", "kubernetes": "k8s-platform",
        "k8s": "k8s-platform", "node": "k8s-platform", "vpn": "vpn-gateway",
        "email": "email-service", "smtp": "email-service",
    }
    for word, svc in hints.items():
        if word in v:
            return svc
    return "unknown"


def normalise_risk(value: str) -> str:
    v = str(value).strip().lower()
    if v.startswith("h") or v in {"critical", "severe"}:
        return "high"
    if v.startswith("m"):
        return "medium"
    return "low"


# ---------- agent outputs ----------

class IntakeResult(BaseModel):
    """First read of the ticket."""

    service: str = Field(description=f"Affected service, one of: {', '.join(SERVICES)}")
    severity: str = Field(description="SEV1 (outage or data loss) to SEV4 (minor)")
    category: str = Field(description="Short category, e.g. database, kubernetes, network, auth, email")
    summary: str = Field(description="One-sentence summary of the problem")
    symptoms: list[str] = Field(default_factory=list, description="Observable symptoms, max 5")

    @field_validator("service")
    @classmethod
    def _svc(cls, v: str) -> str:
        return normalise_service(v)

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str) -> str:
        return normalise_severity(v)

    @field_validator("symptoms")
    @classmethod
    def _sym(cls, v: list[str]) -> list[str]:
        return [s for s in v if s][:5]


class Route(BaseModel):
    """Supervisor decision."""

    next: str = Field(description="The next worker to run")
    reason: str = Field(description="One short sentence explaining the choice")


class SimilarIncident(BaseModel):
    incident_id: str
    title: str = ""
    root_cause: str = ""
    resolution: str = ""


class HistoryFindings(BaseModel):
    """What past incidents say about this one."""

    summary: str = Field(description="2-3 sentences on what history suggests")
    similar_incidents: list[SimilarIncident] = Field(default_factory=list, description="Most relevant past incidents, max 3")
    recurring: bool = Field(default=False, description="True if this looks like a recurring problem")
    typical_mttr_minutes: int | None = Field(default=None, description="Typical time to resolve, if known")


class PlanStep(BaseModel):
    action: str = Field(description="What to do, in one sentence")
    command: str = Field(default="", description="Exact command from the cited runbook, or empty")
    risk: str = Field(description="low, medium or high")
    citation: str = Field(description="Source id, e.g. RB-003#remediation or INC-1042")

    @field_validator("risk")
    @classmethod
    def _risk(cls, v: str) -> str:
        return normalise_risk(v)


class Plan(BaseModel):
    root_cause_hypothesis: str
    confidence: float = Field(ge=0, le=1, description="0 to 1")
    steps: list[PlanStep] = Field(min_length=1, max_length=8)
    escalate_to: str = Field(default="", description="Team to escalate to, from the runbook")

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.5
        return f / 100 if f > 1 else f


class Judgement(BaseModel):
    """LLM-as-judge verdict on groundedness."""

    score: int = Field(ge=1, le=5, description="5 = every step is supported by the sources")
    issues: list[str] = Field(default_factory=list, description="Unsupported or risky claims, max 5")

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, v):
        try:
            return max(1, min(5, round(float(v))))
        except (TypeError, ValueError):
            return 3


class ExecutiveSummary(BaseModel):
    summary: str = Field(description="3-4 plain sentences for an incident commander")


# ---------- API ----------

class TriageRequest(BaseModel):
    ticket: str = Field(min_length=10)
    logs: str = ""


class ResumeRequest(BaseModel):
    approved: bool
    reviewer: str = Field(default="on-call engineer", max_length=80)
    comment: str = Field(default="", max_length=500)


RiskLevel = Literal["low", "medium", "high"]
