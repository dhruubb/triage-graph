"""Tools the history agent can call (LangChain tool calling)."""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.tools.incidents_db import SCHEMA_DOC, IncidentsDB
from app.tools.sql_guard import UnsafeSQLError


class SimilarArgs(BaseModel):
    service: str = Field(description="Service name, e.g. orders-db")
    keywords: list[str] = Field(description="3-6 keywords from the symptoms or error messages")
    limit: int = Field(default=5, description="Max incidents to return (1-10)")


class StatsArgs(BaseModel):
    service: str = Field(description="Service name")
    days: int = Field(default=90, description="Look-back window in days (1-365)")


class SQLArgs(BaseModel):
    query: str = Field(description=f"One read-only SQLite SELECT over {SCHEMA_DOC}")


def _dump(obj: object) -> str:
    return json.dumps(obj, default=str)[:4000]


def make_history_tools(db: IncidentsDB) -> list[BaseTool]:
    def find_similar_incidents(service: str, keywords: list[str], limit: int = 5) -> str:
        return _dump(db.similar(service, keywords, limit))

    def service_health_stats(service: str, days: int = 90) -> str:
        return _dump(db.service_stats(service, days))

    def run_readonly_sql(query: str) -> str:
        try:
            return _dump(db.query(query))
        except UnsafeSQLError as exc:
            return f"error: query rejected by SQL guard: {exc}"
        except Exception as exc:  # sqlite errors, e.g. unknown column
            return f"error: {exc}"

    return [
        StructuredTool.from_function(
            find_similar_incidents, name="find_similar_incidents", args_schema=SimilarArgs,
            description="Find past incidents on a service whose title, symptoms or root cause match keywords."),
        StructuredTool.from_function(
            service_health_stats, name="service_health_stats", args_schema=StatsArgs,
            description="Incident counts by severity, average MTTR and top root causes for a service."),
        StructuredTool.from_function(
            run_readonly_sql, name="run_readonly_sql", args_schema=SQLArgs,
            description=f"Run one read-only SELECT on the incidents table: {SCHEMA_DOC}. Max 50 rows."),
    ]
