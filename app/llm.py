"""LLM clients and helpers.

Two tiers keep the free Groq quota usable: a fast model for routing, intake and
judging, and a stronger model for tool calling and planning. Switching to Azure OpenAI
is a config change (LLM_PROVIDER=azure_openai).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel

from app.config import Settings
from app.observability import record_usage

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    pass


@dataclass
class LLMs:
    fast: BaseChatModel
    smart: BaseChatModel


def build_llms(settings: Settings) -> LLMs:
    if settings.llm_provider == "azure_openai":
        from langchain_openai import AzureChatOpenAI

        def make(deployment: str) -> BaseChatModel:
            return AzureChatOpenAI(
                azure_endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                api_version=settings.azure_openai_api_version,
                azure_deployment=deployment,
                temperature=settings.llm_temperature,
                timeout=settings.llm_timeout_s,
                max_retries=settings.llm_max_retries,
            )

        return LLMs(fast=make(settings.azure_deployment_fast or settings.azure_deployment_smart),
                    smart=make(settings.azure_deployment_smart))

    from langchain_groq import ChatGroq

    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to .env or the container's secrets.")

    def make_groq(model: str) -> BaseChatModel:
        extra = {}
        if "gpt-oss" in model and settings.llm_reasoning_effort:
            extra["reasoning_effort"] = settings.llm_reasoning_effort
        return ChatGroq(
            model=model,
            api_key=settings.groq_api_key,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
            **extra,
        )

    return LLMs(fast=make_groq(settings.llm_model_fast), smart=make_groq(settings.llm_model_smart))


def _fatal(exc: Exception) -> bool:
    """Errors a retry can't fix: bad key, unknown model."""
    text = str(exc)
    return any(s in text for s in ("invalid_api_key", "model_not_found", "Error code: 401", "Error code: 404"))


async def invoke_structured(llm: BaseChatModel, schema: type[T], messages: list[BaseMessage],
                            retries: int = 1) -> T:
    """Call the model for a Pydantic object. On a parse or tool-use failure, show the
    model its error and try again once."""
    runnable = llm.with_structured_output(schema, include_raw=True)
    convo = list(messages)
    last_error: object = None
    for attempt in range(retries + 1):
        try:
            out = await runnable.ainvoke(convo)
        except Exception as exc:  # provider rejected a malformed tool call, timeout, etc.
            if _fatal(exc):
                raise
            last_error = exc
            log.warning("structured call failed", extra={"fields": {"schema": schema.__name__, "attempt": attempt, "error": str(exc)[:300]}})
            convo = list(messages) + [HumanMessage(content=f"Your previous reply was rejected ({str(exc)[:200]}). Reply again with valid arguments for {schema.__name__}.")]
            continue
        record_usage(out.get("raw"))
        parsed = out.get("parsed")
        if isinstance(parsed, schema):
            return parsed
        if isinstance(parsed, dict):
            try:
                return schema.model_validate(parsed)
            except Exception as exc:
                last_error = exc
        else:
            last_error = out.get("parsing_error") or "no structured output returned"
        convo = list(messages) + [HumanMessage(content=f"Your previous reply could not be parsed: {str(last_error)[:300]}. Reply again using the {schema.__name__} schema.")]
    raise StructuredOutputError(f"{schema.__name__}: {last_error}")


async def invoke_text(llm: BaseChatModel, messages: list[BaseMessage]) -> AIMessage:
    msg = await llm.ainvoke(messages)
    record_usage(msg)
    return msg
