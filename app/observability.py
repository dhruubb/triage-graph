"""Structured logging, per-node tracing and in-process metrics.

Every graph node is wrapped with @traced. The wrapper times the node, collects the
tokens its LLM calls used, writes one JSON log line, updates the metrics registry and
appends a trace event to the graph state so the UI can show it live.
"""

from __future__ import annotations

import functools
import json
import logging
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from langgraph.errors import GraphBubbleUp

log = logging.getLogger("triagegraph")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpx2", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(msg: str, **fields: Any) -> None:
    log.info(msg, extra={"fields": fields})


# ---------- token usage ----------

@dataclass
class UsageMeter:
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0

    def add(self, message: Any) -> None:
        usage = getattr(message, "usage_metadata", None) or {}
        self.input_tokens += int(usage.get("input_tokens", 0) or 0)
        self.output_tokens += int(usage.get("output_tokens", 0) or 0)
        self.llm_calls += 1


current_meter: ContextVar[UsageMeter | None] = ContextVar("current_meter", default=None)


def record_usage(message: Any) -> None:
    meter = current_meter.get()
    if meter is not None and message is not None:
        meter.add(message)


# ---------- metrics ----------

@dataclass
class Metrics:
    started_at: float = field(default_factory=time.time)
    counters: dict[str, int] = field(default_factory=dict)
    node_latency_ms: dict[str, list[float]] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def inc(self, name: str, by: int = 1) -> None:
        with self._lock:
            self.counters[name] = self.counters.get(name, 0) + by

    def observe_node(self, node: str, ms: float, meter: UsageMeter) -> None:
        with self._lock:
            series = self.node_latency_ms.setdefault(node, [])
            series.append(ms)
            if len(series) > 500:
                del series[: len(series) - 500]
            self.tokens_in += meter.input_tokens
            self.tokens_out += meter.output_tokens

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            nodes = {}
            for node, series in self.node_latency_ms.items():
                s = sorted(series)
                nodes[node] = {
                    "count": len(s),
                    "avg_ms": round(sum(s) / len(s), 1),
                    "p95_ms": round(s[min(len(s) - 1, int(len(s) * 0.95))], 1),
                }
            return {
                "uptime_s": round(time.time() - self.started_at),
                "counters": dict(self.counters),
                "tokens": {"input": self.tokens_in, "output": self.tokens_out},
                "nodes": nodes,
            }


METRICS = Metrics()


def traced(node: str) -> Callable[[Callable[..., Awaitable[dict]]], Callable[..., Awaitable[dict]]]:
    """Wrap an async graph node: time it, meter its tokens, log it, add a trace event."""

    def decorator(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[dict]]:
        @functools.wraps(fn)
        async def wrapper(state: dict, *args: Any, **kwargs: Any) -> dict:
            meter = UsageMeter()
            token = current_meter.set(meter)
            t0 = time.perf_counter()
            try:
                result = await fn(state, *args, **kwargs)
            except GraphBubbleUp:  # interrupt() for human approval: not an error
                raise
            except Exception:
                METRICS.inc(f"node_errors.{node}")
                log.exception("node failed", extra={"fields": {"node": node, "thread_id": state.get("thread_id")}})
                raise
            finally:
                current_meter.reset(token)
            ms = (time.perf_counter() - t0) * 1000
            note = result.pop("_note", "")
            event = {
                "node": node,
                "latency_ms": round(ms, 1),
                "input_tokens": meter.input_tokens,
                "output_tokens": meter.output_tokens,
                "llm_calls": meter.llm_calls,
                "note": note,
            }
            METRICS.observe_node(node, ms, meter)
            log_event("node completed", thread_id=state.get("thread_id"), **event)
            result["trace"] = [event]
            return result

        return wrapper

    return decorator
