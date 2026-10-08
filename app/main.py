"""FastAPI entry point: `uvicorn app.main:app`."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import router
from app.config import Settings, get_settings
from app.deps import Deps, build_deps
from app.graph import build_graph
from app.observability import setup_logging
from app.ratelimit import RateLimiter


def create_app(settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(settings.log_level)
        d = deps or await asyncio.to_thread(build_deps, settings)
        app.state.deps = d
        app.state.graph = build_graph(d) if d.llms else None
        app.state.limiter = RateLimiter(settings.rate_limit_per_hour)
        yield

    app = FastAPI(title="TriageGraph", version=__version__, lifespan=lifespan,
                  description="Multi-agent IT incident triage copilot (LangGraph + RAG + human-in-the-loop).")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(router, prefix="/api")
    if settings.frontend_dist.exists():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="ui")
    return app


app = create_app()
