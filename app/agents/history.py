"""History agent: a tool-calling loop over the past-incidents database.

The model decides which tools to call and with what arguments (native function
calling). Code caps the loop at 3 rounds, runs the tools, and drops any incident id
in the final answer that does not exist in the database.
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.agents.prompts import HISTORY_SUMMARY, HISTORY_SYSTEM
from app.deps import Deps
from app.llm import StructuredOutputError, invoke_structured, invoke_text
from app.observability import traced
from app.schemas import HistoryFindings

log = logging.getLogger(__name__)
MAX_ROUNDS = 3
MAX_CALLS_PER_ROUND = 3


def make_history_agent(deps: Deps):
    tools = {t.name: t for t in deps.tools}

    @traced("history_agent")
    async def history_agent(state: dict) -> dict:
        intake = state["intake"]
        sigs = ", ".join(s["signature"] for s in state.get("signatures", [])) or "none"
        messages = [
            SystemMessage(content=HISTORY_SYSTEM),
            HumanMessage(content=f"Service: {intake['service']}\nSeverity: {intake['severity']}\n"
                                 f"Summary: {intake['summary']}\nSymptoms: {'; '.join(intake['symptoms'])}\n"
                                 f"Log signatures: {sigs}"),
        ]
        # The fast model does the tool calling: it keeps the stronger model's per-minute quota for the planner.
        llm = deps.llms.fast.bind_tools(list(tools.values()))
        calls: list[dict] = []
        results: list[str] = []
        for _ in range(MAX_ROUNDS):
            try:
                ai = await invoke_text(llm, messages)
            except Exception as exc:  # e.g. the provider rejects a malformed tool call
                log.warning("tool-calling round failed", extra={"fields": {"error": str(exc)[:300]}})
                break
            messages.append(ai)
            if not ai.tool_calls:
                break
            for call in ai.tool_calls[:MAX_CALLS_PER_ROUND]:
                tool = tools.get(call["name"])
                try:
                    output = tool.invoke(call["args"]) if tool else f"error: unknown tool {call['name']}"
                except Exception as exc:  # bad arguments from the model
                    output = f"error: {exc}"
                output = str(output)[:2000]
                calls.append({"tool": call["name"], "args": call["args"], "ok": not output.startswith("error")})
                results.append(f"[{call['name']} {json.dumps(call['args'], default=str)}]\n{output}")
                messages.append(ToolMessage(content=output, tool_call_id=call["id"]))
            # Answer any extra tool calls so the transcript stays valid.
            for call in ai.tool_calls[MAX_CALLS_PER_ROUND:]:
                messages.append(ToolMessage(content="skipped: call limit reached", tool_call_id=call["id"]))

        if not calls:  # the model skipped its tools: fall back to a deterministic lookup
            keywords = [w for s in intake["symptoms"] for w in s.split()][:6] + [s["signature"] for s in state.get("signatures", [])]
            rows = deps.db.similar(intake["service"], keywords)
            calls.append({"tool": "find_similar_incidents", "args": {"service": intake["service"], "keywords": keywords}, "ok": True, "fallback": True})
            results.append(f"[find_similar_incidents]\n{json.dumps(rows, default=str)[:2000]}")

        # Summarise from a clean prompt: cheaper, and avoids replaying tool-call messages to a second model.
        summary_messages = [
            SystemMessage(content=HISTORY_SUMMARY),
            HumanMessage(content=f"Incident: {intake['service']} {intake['severity']}: {intake['summary']}\n\n"
                                 f"Tool results:\n" + "\n\n".join(results)[:6000]),
        ]
        try:
            findings = await invoke_structured(deps.llms.fast, HistoryFindings, summary_messages)
            data = findings.model_dump()
        except StructuredOutputError:
            data = HistoryFindings(summary="History lookup ran but could not be summarised.").model_dump()

        # Guard against invented incident ids.
        ids = [s["incident_id"] for s in data["similar_incidents"]]
        real = deps.db.exists(ids)
        dropped = [i for i in ids if i not in real]
        data["similar_incidents"] = [s for s in data["similar_incidents"] if s["incident_id"] in real][:3]
        # Fill in titles/causes from the database, not the model.
        facts = {r["incident_id"]: r for r in deps.db.get([s["incident_id"] for s in data["similar_incidents"]])}
        data["similar_incidents"] = [{**s, **facts.get(s["incident_id"], {})} for s in data["similar_incidents"]]
        data["tool_calls"] = calls
        data["dropped_ids"] = dropped
        return {
            "history": data,
            "done_workers": state.get("done_workers", []) + ["history_agent"],
            "_note": f"{len(calls)} tool call(s) · {len(data['similar_incidents'])} similar incident(s)"
                     + (f" · dropped {len(dropped)} invented id(s)" if dropped else ""),
        }

    return history_agent
