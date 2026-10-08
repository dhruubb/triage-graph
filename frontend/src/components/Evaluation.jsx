import { useEffect, useState } from 'react'
import { getJSON } from '../api.js'

const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)

const AGENT_METRICS = [
  ['service_accuracy', 'Service accuracy', pct],
  ['severity_exact', 'Severity exact', pct],
  ['severity_within_one', 'Severity within one level', pct],
  ['root_cause_keyword_hit', 'Root cause matches', pct],
  ['grounded_rate', 'Plans grounded (critic)', pct],
  ['judge_score_avg', 'Judge score (1–5)', (v) => v ?? '—'],
  ['revision_rate', 'Plans revised once', pct],
  ['must_pause_recall', 'SEV1 cases paused for a human', pct],
  ['injection_resisted', 'Prompt injection resisted', pct],
]

export default function Evaluation() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getJSON('/api/eval/latest').then(setData).catch((e) => setError(e.message))
  }, [])

  if (error) {
    return (
      <section className="card">
        <h3>No evaluation results yet</h3>
        <p className="muted">{error}</p>
        <pre className="cmd">python -m eval.run --retrieval-only{'\n'}python -m eval.run</pre>
      </section>
    )
  }
  if (!data) return <p className="muted">Loading…</p>

  const s = data.summary
  return (
    <div className="eval">
      <section className="card">
        <h3>Latest evaluation <span className="muted small">{data.mode} · {s.cases} cases · {data.generated_at}{data.git_sha ? ` · ${data.git_sha}` : ''}</span></h3>
        <p className="small muted">
          {data.config.llm_provider} ({data.config.model_fast} / {data.config.model_smart}) · embeddings {data.config.embeddings} · {data.config.vector_store}.
          Golden set: 20 synthetic tickets written for this project, so treat these numbers as a regression check, not a benchmark.
        </p>
        <div className="tiles">
          <div className="tile"><span className="stat">{pct(s.retrieval.hit_at_1)}</span><span className="muted small">retrieval hit@1</span></div>
          <div className="tile"><span className="stat">{pct(s.retrieval.hit_at_3)}</span><span className="muted small">retrieval hit@3</span></div>
          <div className="tile"><span className="stat">{s.retrieval.mrr.toFixed(2)}</span><span className="muted small">MRR</span></div>
          {s.cost && <div className="tile"><span className="stat">{s.cost.latency_p50_s}s</span><span className="muted small">p50 agent time</span></div>}
          {s.cost && <div className="tile"><span className="stat">{s.cost.tokens_per_run_avg.toLocaleString()}</span><span className="muted small">tokens / run</span></div>}
        </div>
        {s.agents && (
          <table className="metrics">
            <tbody>
              {AGENT_METRICS.map(([k, label, f]) => (
                <tr key={k}><td>{label}</td><td className="mono">{f(s.agents[k])}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="card">
        <h3>Per case</h3>
        <div className="table-wrap">
          <table className="cases">
            <thead>
              <tr><th>Case</th><th>Expected</th><th>Retrieved</th>{s.agents && <><th>Service</th><th>Severity</th><th>Grounded</th><th>Paused</th></>}</tr>
            </thead>
            <tbody>
              {data.cases.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.id}</td>
                  <td className="mono">{c.expected_runbooks?.join(', ')}</td>
                  <td className="mono">{c.error ? <span className="bad">error</span> : c.retrieved?.map((r) => (
                    <span key={r} className={c.expected_runbooks.includes(r) ? 'ok' : ''}>{r} </span>))}</td>
                  {s.agents && <>
                    <td className="mono">{c.predicted_service}{c.service_ok === false ? ' ✗' : ''}</td>
                    <td className="mono">{c.predicted_severity}{c.severity_ok === false ? ' ✗' : ''}</td>
                    <td>{c.grounded == null ? '—' : c.grounded ? 'yes' : 'no'}</td>
                    <td>{c.paused == null ? '—' : c.paused ? 'yes' : 'no'}</td>
                  </>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
