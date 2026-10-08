const STACK = [
  ['Orchestration', 'LangGraph StateGraph with a supervisor, conditional edges, a critic loop and interrupt() for human approval. State is checkpointed per run.'],
  ['LLMs', 'Groq (gpt-oss-20b for routing, intake, tool calling and judging; gpt-oss-120b for planning). Azure OpenAI is a config switch.'],
  ['Retrieval', 'Qdrant with named dense (bge-small, FastEmbed) and sparse (BM25) vectors, fused with Reciprocal Rank Fusion, plus a service-metadata boost.'],
  ['Tools', 'Native function calling over a read-only SQLite incident database. Model-written SQL goes through a sqlglot guard (single SELECT, table allow-list, forced LIMIT).'],
  ['Guardrails', 'Critic rules (citations must exist, commands must match the runbook, risk cannot be under-labelled), invented incident ids dropped, prompt-injection-aware prompts.'],
  ['Serving', 'FastAPI streaming Server-Sent Events, React front end, one Docker image, deployed to Azure Container Apps.'],
  ['Observability', 'JSON logs per node with latency and token counts, /api/metrics, optional LangSmith tracing.'],
  ['Quality', 'pytest suite with a scripted fake LLM (runs offline in CI), and a 20-case golden-set evaluation runner.'],
]

export default function About({ health }) {
  return (
    <div className="about">
      <section className="card">
        <h3>The graph</h3>
        <div className="flow" role="img" aria-label="Intake, then a supervisor that routes to the runbook and history agents, then planner, critic, approval gate, executor and reporter">
          <div className="flow-row"><span className="node">Intake</span><span className="arrow">→</span><span className="node node-accent">Supervisor</span></div>
          <div className="flow-row indent"><span className="arrow">↳</span><span className="node">Runbook RAG</span><span className="node">History (tools)</span><span className="muted small">back to supervisor</span></div>
          <div className="flow-row"><span className="node">Planner</span><span className="arrow">⇄</span><span className="node">Critic</span><span className="muted small">one revision if not grounded</span></div>
          <div className="flow-row"><span className="node node-human">Approval gate</span><span className="arrow">→</span><span className="node">Executor (simulated)</span><span className="arrow">→</span><span className="node">Reporter</span></div>
        </div>
        <p className="small muted">
          The approval gate pauses when the effective risk is above {health?.auto_approve_max_risk ?? 'medium'}, the incident is SEV1, or the critic can't confirm every step is grounded.
        </p>
      </section>
      <section className="card">
        <h3>Stack</h3>
        <dl className="stack">
          {STACK.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}
        </dl>
      </section>
    </div>
  )
}
