"""Runbook agent: hybrid retrieval over the runbook knowledge base (Qdrant)."""

from __future__ import annotations

import asyncio

from app.deps import Deps
from app.observability import traced


def build_query(state: dict) -> str:
    intake = state["intake"]
    parts = [intake.get("summary", ""), " ".join(intake.get("symptoms", []))]
    parts += [s["signature"].replace("_", " ") for s in state.get("signatures", [])]
    parts += [s["evidence"] for s in state.get("signatures", [])[:3]]
    parts.append(state["ticket"][:400])
    return "\n".join(p for p in parts if p)


def make_runbook_agent(deps: Deps):
    k = deps.settings.retrieval_top_runbooks

    @traced("runbook_agent")
    async def runbook_agent(state: dict) -> dict:
        query = build_query(state)
        # Embedding runs on CPU; keep it off the event loop.
        result = await asyncio.to_thread(deps.store.retrieve, query, state["intake"]["service"], k)
        return {
            "runbook_hits": result.runbooks,
            "context_chunks": result.chunks,
            "done_workers": state.get("done_workers", []) + ["runbook_agent"],
            "_note": ", ".join(f"{r['runbook_id']} ({r['score']:.2f})" for r in result.runbooks) or "no match",
        }

    return runbook_agent
