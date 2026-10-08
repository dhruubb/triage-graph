# TriageGraph: interview notes

Read this once end to end, then practise the 60-second pitch and the walkthrough out loud. The interviewer will pick one design choice and push on it. Every answer below points to the file where it lives, so open that file and read the code before you rely on the answer.

## 60-second pitch

> "TriageGraph is a multi-agent copilot for IT incident triage. You paste a ticket and some logs. An intake agent classifies it, and a supervisor agent decides which specialists to call: a runbook agent that does hybrid RAG on Qdrant, and a history agent that uses tool calling over a past-incidents database. A planner writes a remediation plan where every step cites a source. A critic checks it with hard rules plus an LLM judge and can send it back once. If anything is high-risk or the incident is SEV1, LangGraph's interrupt pauses the run for a human to approve before the simulated executor runs it. It's FastAPI with a React UI, packaged in one Docker image and deployed on Azure Container Apps. I evaluate it with a 20-case golden set and test it offline in CI with a scripted fake LLM."

## Numbers to know

- 9 graph nodes. Six call an LLM (intake, supervisor, history, planner, the critic's judge, reporter); runbook retrieval, the approval gate and the executor are plain code
- 15 runbooks → 75 section chunks; 160 synthetic past incidents
- 44 pytest tests, run offline in CI
- 20 golden eval cases, one of them a prompt-injection case
- Your eval numbers: fill these in from `eval/results/latest.json` after you run it. **Only quote numbers you actually ran.**

## Walkthrough of one run (practise this with the demo open)

1. **Intake** (`app/agents/intake.py`). Regexes pull known error signatures from the logs first (cheap, reliable). Then the fast model returns a Pydantic `IntakeResult`. Validators normalise sloppy answers, so "P1" becomes SEV1 and "Orders DB" becomes orders-db.
2. **Supervisor** (`supervisor.py`). The model chooses the next worker, but code decides what's allowed: the planner is only an option after the runbook agent has run, and there's a step cap. An invalid choice falls back to the first allowed option. *"LLM for judgement, code for control."*
3. **Runbook agent** (`app/rag/store.py`). A single Qdrant query runs dense (bge-small via FastEmbed) and sparse (BM25) search and fuses them with RRF. Chunks tagged with the ticket's service get a small bonus. Then it fetches every section of the top 3 runbooks, so the planner sees remediation and rollback together (parent-document retrieval).
4. **History agent** (`history.py`). Native tool calling: `bind_tools`, the model emits `tool_calls`, the code runs them and returns `ToolMessage`s, capped at 3 rounds. If the model skips its tools, a deterministic lookup runs instead. Incident ids in the answer are checked against the database, and invented ones are dropped.
5. **Planner** (`planner.py`). Uses the stronger model and sees only the sources. Rules: cite one source id per step, copy commands exactly, and use the runbook's risk label.
6. **Critic** (`critic.py`). Rules first: citations must be sources the planner saw, commands must match a command in the cited runbook section exactly (only placeholders like `<pod>` may be filled in), and risk can't be lower than the runbook's. Then an LLM judge scores the plan 1–5. If the plan isn't grounded, it goes back once with the problems listed.
7. **Approval gate** (`approval.py`). `interrupt()` saves the state through the checkpointer, and the API streams `approval_required`. The UI posts the decision, and the run resumes with `Command(resume=...)`. The gate uses the *effective* risk: the higher of the planner's label and the runbook's.
8. **Executor** (`executor.py`). A dry run that writes each step to an audit log with the approver's name.
9. **Reporter** (`reporter.py`). A short summary from the model. The rest of the report (totals, citations, approval) is assembled in code.

## Likely questions

**Why LangGraph and not a plain LangChain agent or CrewAI?**
I needed explicit control flow: conditional edges, a bounded critic loop, and a pause-and-resume for human approval that survives between HTTP requests. LangGraph gives me a typed state, a checkpointer and `interrupt()`. A free-running agent loop makes it hard to guarantee that high-risk steps always stop for a human.

**Why a supervisor instead of a fixed pipeline?**
Not every ticket needs history. For a certificate warning the supervisor goes straight from runbooks to the planner, which saves calls and tokens. The code still bounds it: it can't plan without runbook context and can't loop forever.

**Why hybrid search, and why RRF?**
Incident text is full of exact tokens like `EAI_AGAIN`, `OOMKilled` or `exit code 137`. Dense embeddings blur those, and BM25 matches them exactly, while dense search handles paraphrases ("customers can't pay"). Cosine and BM25 scores aren't on the same scale, so I fuse by rank with Reciprocal Rank Fusion instead of adding raw scores. Qdrant applies the IDF part of BM25 on the server (`Modifier.IDF`).

**How did you chunk?**
One chunk per runbook section, and each chunk repeats the runbook's title and services, so it makes sense on its own. After retrieval I expand to the whole runbook, because the remediation steps are useless without the rollback and escalation sections.

**How do you stop hallucinated commands?**
Structurally, not just with prompts. The critic turns each runbook command into a pattern where only the `<placeholders>` can vary, and rejects any command that doesn't match one exactly; the rejection names the closest runbook command so the planner can fix it on the revision. It also rejects citations to sources the planner wasn't shown. Nothing executes without passing the gate, and anything ungrounded forces human review.

**Text-to-SQL is dangerous. How is it safe here?**
Five layers in `sql_guard.py` and `incidents_db.py`: parse with sqlglot; allow exactly one SELECT; allow-list the table; block PRAGMA, ATTACH and extension functions; force a LIMIT. It then runs on a read-only SQLite connection with `query_only` on and a step budget. The tests check that `DELETE`, multiple statements and `sqlite_master` are rejected.

**What about prompt injection?**
Prompts mark tickets and tool output as untrusted data, but I don't rely on that. The model can't execute anything, commands have to exist in a runbook, and the risk used for approval comes from the runbook, not the model. Golden case g20 plants an injected `rm -rf`, and the eval checks it never reaches the plan.

**Why two models?**
Cost and rate limits. Classification, routing, tool calling and judging work fine on gpt-oss-20b. Planning gets gpt-oss-120b. Both are reasoning models, so I set reasoning effort to low to keep tokens and latency down. Splitting the work also spreads load across two per-model quotas on Groq's free tier. Switching to Azure OpenAI is a config change. (I started on Llama 3.1 8B and 3.3 70B; Groq retired them in August 2026, and because the model names are config, migrating was a two-line change.)

**How do you evaluate it?**
`eval/run.py` runs 20 golden tickets through the full graph and measures service and severity accuracy, retrieval hit@k and MRR, root-cause match, grounded-plan rate, judge score, revision rate, whether every SEV1 case paused for a human, and injection resistance, plus latency and tokens. There's a retrieval-only mode that needs no LLM, and a harder ticket-text-only mode. *Be honest here:* the set is small, and I wrote it myself, so it's a regression check, not a benchmark. Next I'd add RAGAS and tickets written by someone else.

**How do you test agents deterministically?**
`tests/fakes.py` has a scripted chat model that implements `bind_tools` and `with_structured_output`, so the real graph runs offline in CI. The tests cover the interrupt and resume path, rejection, auto-approval, the critic revision loop, a bad supervisor route, and a model that skips its tools.

**How is it monitored?**
A `@traced` decorator times every node and counts its tokens through a context variable. Each node writes one JSON log line, which Azure sends to Log Analytics and I can query with KQL. `/api/metrics` shows per-node p95 latency, approvals and token totals. LangSmith tracing turns on with an environment variable.

**How is it deployed?**
A multi-stage Dockerfile: Node builds the React app, then a slim Python image serves both the API and the UI. The embedding model is baked in, the container runs as a non-root user, and it has a health check. GitHub Actions runs lint and tests, then pushes the image to GHCR, and Azure Container Apps runs it with secrets passed as `secretref` environment variables. It scales to zero when idle.

**What would break at scale, and what would you change?**
Paused runs are in memory, so it's one replica: move to LangGraph's Postgres checkpointer. The rate limiter is in memory: move to Redis. The executor is simulated: add real actions through Azure Automation with RBAC per action, behind the same approval gate. Other next steps: a cross-encoder reranker, SSO on the approval endpoint, and learning from approve/reject decisions.

**What was hard?**
A real bug from testing: on a pods-crashing ticket the planner wrote `kubectl get pods | grep Running`, but the runbook says `grep -v Running`, and `-v` flips the meaning. My first rule check used fuzzy string similarity, and the two commands were 97% similar, so it passed. The LLM judge caught it and scored the plan 3/5, which forced human review. I replaced fuzzy matching with exact matching where only placeholders may change, added the closest runbook command to the error so the planner can fix it, and added regression tests. The lesson: for safety checks, rules should be strict and the model is the second layer, not the first.
In the same run the reporter wrote "we raised the memory limit" although nothing ran. Now it's told the executor is a dry run, and a code check appends that fact if the summary leaves it out.
Other candidates: fitting a multi-agent run into free-tier token limits, and the Groq model retirement.

## Be upfront about

- The data is synthetic, and the executor is a dry run.
- You built it quickly with AI-assisted coding. That's fine: the JD itself mentions AI-assisted engineering. What matters is that you can explain and defend every decision above.

## Resume entry (fill the brackets from your own eval run)

**TriageGraph: Multi-Agent Incident Triage Copilot** | LangGraph, Groq gpt-oss-120b, Qdrant, FastAPI, React, Docker, Azure | Sep '26
- Built a LangGraph supervisor multi-agent system (intake, hybrid-RAG runbook agent, SQL tool-calling history agent, planner, critic) that turns an incident ticket into a cited, risk-labelled remediation plan; SEV1 or high-risk plans pause via `interrupt()` for human approval.
- Added guardrails and evaluation: sqlglot-validated read-only SQL, critic rules that reject uncited commands and under-rated risk, and a 20-case golden set ([X]% retrieval hit@3, [Y]% grounded plans); 44 offline pytest tests in CI, deployed on Azure Container Apps.
