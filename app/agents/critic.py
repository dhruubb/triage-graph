"""Critic agent: rule-based checks plus an LLM judge.

Rules (deterministic, cannot be argued with):
  * every citation must be a source the planner was shown
  * every command must match a command in the cited runbook exactly; only
    placeholders like <pod> may be filled in (`grep Running` is not `grep -v Running`)
  * a step's risk can't be lower than the risk the runbook gives it
LLM judge: scores 1-5 how well the plan is supported by the sources.

The critic also computes each step's *effective* risk (the higher of the planner's
label and the runbook's), which the approval gate uses. The model can't avoid human
review by under-labelling a risky step.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.planner import format_sources
from app.agents.prompts import CRITIC_SYSTEM
from app.config import RISK_ORDER
from app.deps import Deps
from app.llm import StructuredOutputError, invoke_structured
from app.observability import traced
from app.rag.chunking import RunbookIndex, RunbookStep
from app.schemas import Judgement

PLACEHOLDER = re.compile(r"<[^>]+>")
ACTION_MATCH_THRESHOLD = 0.5  # only used to find a runbook step's risk for steps with no command


def normalise_citation(c: str) -> str:
    c = c.strip().strip("[]()").strip()
    m = re.match(r"(RB-\d{3})\s*[#:\s-]*\s*([a-z-]*)", c, re.IGNORECASE)
    if m:
        rb, sec = m.group(1).upper(), m.group(2).lower().strip("-")
        return f"{rb}#{sec}" if sec else rb
    m = re.match(r"(INC-\d+)", c, re.IGNORECASE)
    return m.group(1).upper() if m else c


def normalise_command(cmd: str) -> str:
    return re.sub(r"\s+", " ", cmd.strip().strip("`")).strip()


def command_pattern(runbook_cmd: str) -> re.Pattern:
    """Runbook command -> regex. Literal text must match exactly; each <placeholder>
    may be left as is or filled with one token."""
    parts = PLACEHOLDER.split(normalise_command(runbook_cmd))
    return re.compile(r"\S+".join(re.escape(p) for p in parts))


def command_matches(command: str, runbook_cmd: str) -> bool:
    return command_pattern(runbook_cmd).fullmatch(normalise_command(command)) is not None


def closest_command(command: str, steps: list[RunbookStep]) -> str | None:
    """For the revision hint: the runbook command that looks most like the planner's."""
    best, score = None, 0.0
    for st in steps:
        for rc in st.commands:
            r = SequenceMatcher(None, normalise_command(command), normalise_command(rc)).ratio()
            if r > score:
                best, score = rc, r
    return best


def matching_step(command: str, action: str, steps: list[RunbookStep]) -> RunbookStep | None:
    """The runbook step this plan step corresponds to, or None."""
    if command:
        return next((st for st in steps if any(command_matches(command, rc) for rc in st.commands)), None)
    best, score = None, 0.0
    for st in steps:
        r = SequenceMatcher(None, action.lower(), st.text.lower()).ratio()
        if r > score:
            best, score = st, r
    return best if score >= ACTION_MATCH_THRESHOLD else None


def rule_checks(plan: dict, allowed_ids: set[str], index: RunbookIndex) -> tuple[list[str], list[str]]:
    """Return (issues, effective risk per step)."""
    issues, effective = [], []
    allowed_runbooks = {a.split("#")[0] for a in allowed_ids if a.startswith("RB-")}
    for n, step in enumerate(plan["steps"], start=1):
        cite = normalise_citation(step["citation"])
        risk = step["risk"]
        eff = risk
        if cite.startswith("INC-"):
            if cite not in allowed_ids:
                issues.append(f"Step {n} cites {cite}, which was not in the sources.")
            if step.get("command"):
                issues.append(f"Step {n} has a command but cites a past incident; commands must come from a runbook.")
        elif cite.startswith("RB-"):
            rb = cite.split("#")[0]
            if cite not in allowed_ids and not ("#" not in cite and rb in allowed_runbooks):
                issues.append(f"Step {n} cites {step['citation']}, which was not in the sources.")
            chunks = [index.get(cite)] if "#" in cite else index.chunks_for(rb)
            steps = [s for c in chunks if c for s in c.steps]
            command = step.get("command", "")
            match = matching_step(command, step["action"], steps)
            if command and match is None:
                hint = closest_command(command, steps)
                issues.append(f"Step {n} command `{command}` does not match any command in {cite}"
                              + (f"; the closest is `{hint}`." if hint else "."))
            if match and RISK_ORDER[match.risk] > RISK_ORDER[risk]:
                issues.append(f"Step {n} is labelled {risk} but {cite} marks it {match.risk}.")
                eff = match.risk
        else:
            issues.append(f"Step {n} has an unrecognised citation '{step['citation']}'.")
        effective.append(eff)
    return issues, effective


def make_critic(deps: Deps):
    max_revisions = deps.settings.max_plan_revisions

    @traced("critic")
    async def critic(state: dict) -> dict:
        plan = state["plan"]
        sources, allowed = format_sources(state)
        issues, effective = rule_checks(plan, allowed, deps.index)
        messages = [
            SystemMessage(content=CRITIC_SYSTEM),
            HumanMessage(content=f"Sources:\n{sources}\n\nPlan:\n{json.dumps(plan['steps'], indent=1)}"),
        ]
        try:
            judgement = await invoke_structured(deps.llms.fast, Judgement, messages)
        except StructuredOutputError:
            judgement = Judgement(score=3, issues=["judge unavailable"])
        grounded = not issues and judgement.score >= 4
        revise = not grounded and state.get("planner_runs", 1) <= max_revisions
        eff_max = max(effective, key=lambda r: RISK_ORDER[r]) if effective else "low"
        return {
            "critique": {
                "grounded": grounded,
                "score": judgement.score,
                "rule_issues": issues,
                "judge_issues": judgement.issues,
                "effective_risks": effective,
                "effective_max_risk": eff_max,
                "revise": revise,
            },
            "_note": f"{'grounded' if grounded else 'not grounded'} · judge {judgement.score}/5 · "
                     f"{len(issues)} rule issue(s)" + (" · sending back for revision" if revise else ""),
        }

    return critic
