"""Application settings, read from environment variables or a .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

SERVICES = [
    "payments-api",
    "checkout-web",
    "auth-service",
    "orders-db",
    "kafka-events",
    "k8s-platform",
    "vpn-gateway",
    "email-service",
]

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_provider: Literal["groq", "azure_openai"] = "groq"
    groq_api_key: str = ""
    # Groq retired the Llama 3.1 8B / 3.3 70B models on free tiers on 16 Aug 2026.
    llm_model_smart: str = "openai/gpt-oss-120b"
    llm_model_fast: str = "openai/gpt-oss-20b"
    llm_reasoning_effort: str = "low"  # gpt-oss models reason before answering; "low" keeps tokens and latency down
    llm_temperature: float = 0.0
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 4

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_deployment_smart: str = ""
    azure_deployment_fast: str = ""

    # Vector store
    qdrant_url: str = ""  # empty = embedded in-memory Qdrant (local dev and tests)
    qdrant_api_key: str = ""
    qdrant_collection: str = "runbooks"
    embeddings: Literal["fastembed", "hash"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    retrieval_top_runbooks: int = 3

    # Data
    data_dir: Path = ROOT / "data"
    runtime_dir: Path = Path("/tmp/triagegraph")

    # Policy
    auto_approve_max_risk: Literal["low", "medium", "high"] = "medium"
    max_plan_revisions: int = 1
    max_supervisor_steps: int = 4

    # API
    rate_limit_per_hour: int = 30
    max_ticket_chars: int = 4000
    max_log_chars: int = 8000
    cors_origins: str = "http://localhost:5173"  # comma-separated exact origins
    cors_origin_regex: str = ""  # optional, e.g. https://triage-graph(-[a-z0-9-]+)?\.vercel\.app for Vercel previews
    log_level: str = "INFO"
    frontend_dist: Path = ROOT / "frontend" / "dist"
    eval_results_path: Path = ROOT / "eval" / "results" / "latest.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
