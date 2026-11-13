"""HTTP API. Triage runs stream their progress as Server-Sent Events."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.types import Command

from app import __version__
from app.observability import METRICS, log_event
from app.schemas import ResumeRequest, TriageRequest

log = logging.getLogger(__name__)
router = APIRouter()
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def public_update(update: dict) -> dict:
    """What the UI needs from a node's state update (drops bulky or internal fields)."""
    out = {k: v for k, v in update.items() if k not in {"trace", "context_chunks", "_note"}}
    if "context_chunks" in update:
        out["context_chunk_ids"] = [c["chunk_id"] for c in update["context_chunks"]]
    return out


def friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "429" in text or "rate limit" in text.lower():
        return "The LLM provider's rate limit was hit. Wait a minute and try again."
    if "model_not_found" in text or "does not exist" in text:
        return "The configured model isn't available on your Groq account. Set LLM_MODEL_FAST and LLM_MODEL_SMART to models listed at console.groq.com/docs/models."
    if "api_key" in text.lower() or "401" in text:
        return "The LLM provider rejected the API key. Check GROQ_API_KEY."
    return f"The triage run failed ({type(exc).__name__}): {text[:200]}"


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def get_graph(request: Request):
    graph = request.app.state.graph
    if graph is None:
        raise HTTPException(503, "The LLM is not configured. Set GROQ_API_KEY (or Azure OpenAI settings) and restart.")
    return graph


async def run_stream(graph, payload: Any, thread_id: str, start: dict | None = None) -> AsyncIterator[str]:
    cfg = {"configurable": {"thread_id": thread_id}}
    if start:
        yield sse("start", start)
    try:
        async for chunk in graph.astream(payload, cfg, stream_mode="updates"):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    METRICS.inc("runs.awaiting_approval")
                    yield sse("approval_required", {"thread_id": thread_id, **update[0].value})
                else:
                    update = update or {}
                    trace = (update.get("trace") or [None])[-1]
                    yield sse("node", {"node": node, "trace": trace, "data": public_update(update)})
        snap = await graph.aget_state(cfg)
        if not snap.next:
            METRICS.inc("runs.completed")
            log_event("run completed", thread_id=thread_id, **(snap.values.get("report", {}).get("totals", {})))
            yield sse("done", {"thread_id": thread_id, "report": snap.values.get("report")})
    except Exception as exc:
        METRICS.inc("runs.failed")
        log.exception("run failed", extra={"fields": {"thread_id": thread_id}})
        yield sse("error", {"thread_id": thread_id, "message": friendly_error(exc)})


@router.get("/health")
async def health(request: Request) -> dict:
    deps = request.app.state.deps
    s = deps.settings
    return {
        "status": "ok",
        "version": __version__,
        "llm": {"provider": s.llm_provider if deps.llms else "not configured",
                "fast": s.llm_model_fast if s.llm_provider == "groq" else s.azure_deployment_fast,
                "smart": s.llm_model_smart if s.llm_provider == "groq" else s.azure_deployment_smart},
        "vector_store": {"backend": deps.store.backend, "collection": deps.store.collection,
                         "chunks": deps.store.count(), "embeddings": deps.store.dense.tag,
                         **({"fallback_reason": deps.store.fallback_reason} if deps.store.fallback_reason else {})},
        "incidents": deps.db.count(),
        "auto_approve_max_risk": s.auto_approve_max_risk,
    }


@router.get("/samples")
async def samples(request: Request) -> list[dict]:
    path = request.app.state.deps.settings.data_dir / "samples.json"
    return json.loads(path.read_text())


@router.post("/triage")
async def triage(body: TriageRequest, request: Request) -> StreamingResponse:
    s = request.app.state.deps.settings
    if len(body.ticket) > s.max_ticket_chars or len(body.logs) > s.max_log_chars:
        raise HTTPException(413, f"Ticket must be under {s.max_ticket_chars} characters and logs under {s.max_log_chars}.")
    graph = get_graph(request)
    allowed, retry = request.app.state.limiter.check(client_ip(request))
    if not allowed:
        raise HTTPException(429, f"Rate limit reached. Try again in {retry} seconds.", headers={"Retry-After": str(retry)})
    thread_id = uuid.uuid4().hex
    ticket_id = f"TKT-{thread_id[:6].upper()}"
    state = {"thread_id": thread_id, "ticket_id": ticket_id, "ticket": body.ticket, "logs": body.logs,
             "trace": [], "done_workers": [], "supervisor_steps": 0, "planner_runs": 0}
    METRICS.inc("runs.started")
    log_event("run started", thread_id=thread_id, ticket_id=ticket_id)
    return StreamingResponse(run_stream(graph, state, thread_id, {"thread_id": thread_id, "ticket_id": ticket_id}),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/runs/{thread_id}/resume")
async def resume(thread_id: str, body: ResumeRequest, request: Request) -> StreamingResponse:
    graph = get_graph(request)
    snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    if not snap.values:
        raise HTTPException(404, "Unknown run. It may have expired when the server restarted.")
    if "approval_gate" not in (snap.next or ()):
        raise HTTPException(409, "This run is not waiting for approval.")
    log_event("approval decision", thread_id=thread_id, approved=body.approved, reviewer=body.reviewer)
    return StreamingResponse(run_stream(graph, Command(resume=body.model_dump()), thread_id),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/runs/{thread_id}")
async def get_run(thread_id: str, request: Request) -> dict:
    graph = get_graph(request)
    snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    if not snap.values:
        raise HTTPException(404, "Unknown run.")
    values = public_update(dict(snap.values))
    values["trace"] = snap.values.get("trace", [])
    return {"thread_id": thread_id, "next": list(snap.next or ()), "awaiting_approval": "approval_gate" in (snap.next or ()),
            "state": values, "audit": request.app.state.deps.audit.for_thread(thread_id)}


@router.get("/metrics")
async def metrics() -> dict:
    return METRICS.snapshot()


@router.get("/eval/latest")
async def eval_latest(request: Request):
    path = request.app.state.deps.settings.eval_results_path
    if not path.exists():
        return JSONResponse({"detail": "No evaluation results yet. Run: python -m eval.run"}, status_code=404)
    return json.loads(path.read_text())
