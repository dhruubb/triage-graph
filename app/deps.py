"""Everything the graph needs, built once at startup and injected into the nodes."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.tools import BaseTool

from app.config import Settings
from app.llm import LLMs, build_llms
from app.observability import log_event
from app.rag.chunking import RunbookIndex, load_runbooks
from app.rag.embeddings import SparseBM25, build_dense
from app.rag.store import RunbookStore
from app.tools.history_tools import make_history_tools
from app.tools.incidents_db import AuditLog, IncidentsDB, build_incidents_db


@dataclass
class Deps:
    settings: Settings
    llms: LLMs | None
    store: RunbookStore
    index: RunbookIndex
    db: IncidentsDB
    audit: AuditLog
    tools: list[BaseTool]


def build_deps(settings: Settings, llms: LLMs | None = None, store: RunbookStore | None = None) -> Deps:
    runtime = settings.runtime_dir
    runtime.mkdir(parents=True, exist_ok=True)

    n_inc = build_incidents_db(settings.data_dir / "incidents.csv", runtime / "incidents.db")
    db = IncidentsDB(runtime / "incidents.db")
    audit = AuditLog(runtime / "audit.db")

    chunks = load_runbooks(settings.data_dir / "runbooks")
    index = RunbookIndex(chunks)
    if store is None:
        dense = build_dense(settings.embeddings, settings.embedding_model)
        store = RunbookStore.connect(settings.qdrant_url, settings.qdrant_api_key, settings.qdrant_collection,
                                     dense, SparseBM25())
    n_chunks = store.ingest(chunks)

    if llms is None:
        try:
            llms = build_llms(settings)
        except RuntimeError as exc:
            log_event("llm not configured", error=str(exc))
            llms = None

    log_event("startup complete", incidents=n_inc, runbook_chunks=n_chunks, vector_store=store.backend,
              collection=store.collection, llm_provider=settings.llm_provider if llms else "not configured")
    return Deps(settings=settings, llms=llms, store=store, index=index, db=db, audit=audit,
                tools=make_history_tools(db))
