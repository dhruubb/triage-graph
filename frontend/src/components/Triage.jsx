import { useEffect, useRef, useState } from 'react'
import { getJSON, streamSSE } from '../api.js'

export const AGENTS = [
  { id: 'intake', label: 'Intake', kind: 'LLM' },
  { id: 'supervisor', label: 'Supervisor', kind: 'LLM router' },
  { id: 'runbook_agent', label: 'Runbook RAG', kind: 'Qdrant hybrid' },
  { id: 'history_agent', label: 'History', kind: 'SQL tools' },
  { id: 'planner', label: 'Planner', kind: 'LLM' },
  { id: 'critic', label: 'Critic', kind: 'rules + judge' },
  { id: 'approval_gate', label: 'Approval', kind: 'human' },
  { id: 'executor', label: 'Executor', kind: 'simulated' },
  { id: 'reporter', label: 'Reporter', kind: 'LLM' },
]
const LABEL = Object.fromEntries(AGENTS.map((a) => [a.id, a.label]))

function Risk({ level, from }) {
  return (
    <span className={`risk risk-${level}`} title={from ? `Planner said ${from}; the runbook says ${level}` : undefined}>
      {from ? `${from} → ${level}` : level}
    </span>
  )
}

function Pipeline({ trace, running, paused }) {
  const done = new Set(trace.map((t) => t.node))
  return (
    <ol className="pipeline" aria-label="Agent pipeline">
      {AGENTS.map((a) => {
        let state = done.has(a.id) ? 'done' : 'pending'
        if (a.id === 'approval_gate' && paused) state = 'waiting'
        return (
          <li key={a.id} className={`pipe pipe-${state}`}>
            <span className="pipe-dot" />
            <span className="pipe-label">{a.label}</span>
          </li>
        )
      })}
      {running && <li className="pipe-running" aria-live="polite">running…</li>}
    </ol>
  )
}

function Timeline({ trace, running }) {
  const end = useRef(null)
  // Block body on purpose: newer browsers return a Promise from scrollIntoView, and an effect
  // may only return a cleanup function.
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest' })
  }, [trace.length])
  if (!trace.length && !running) return <p className="muted">Each agent's step appears here as it runs.</p>
  return (
    <ul className="timeline">
      {trace.map((t, i) => (
        <li key={i} className="tl-row">
          <span className={`tl-agent tl-${t.node}`}>{LABEL[t.node] || t.node}</span>
          <span className="tl-note">{t.note}</span>
          <span className="tl-meta mono">
            {(t.latency_ms / 1000).toFixed(1)}s{t.llm_calls ? ` · ${t.input_tokens + t.output_tokens} tok` : ''}
          </span>
        </li>
      ))}
      {running && (
        <li className="tl-row tl-working">
          <span className="spinner" aria-hidden="true" />
          <span className="tl-note muted">working…</span>
        </li>
      )}
      <li ref={end} />
    </ul>
  )
}

function Intake({ intake, signatures }) {
  return (
    <section className="card">
      <h3>Intake</h3>
      <div className="kv">
        <span>Service</span><strong className="mono">{intake.service}</strong>
        <span>Severity</span><strong><span className={`sev sev-${intake.severity}`}>{intake.severity}</span></strong>
        <span>Category</span><strong>{intake.category}</strong>
      </div>
      <p>{intake.summary}</p>
      {intake.symptoms?.length > 0 && (
        <ul className="tags">{intake.symptoms.map((s, i) => <li key={i}>{s}</li>)}</ul>
      )}
      {signatures?.length > 0 && (
        <p className="small muted">Log signatures (regex): {signatures.map((s) => s.signature).join(', ')}</p>
      )}
    </section>
  )
}

function Runbooks({ hits }) {
  return (
    <section className="card">
      <h3>Retrieved runbooks <span className="muted small">hybrid search · dense + BM25 · RRF</span></h3>
      <ul className="hits">
        {hits.map((h) => (
          <li key={h.runbook_id}>
            <div className="hit-head">
              <span className="mono cite">{h.runbook_id}</span>
              <span className="hit-title">{h.title}</span>
              <span className="mono small">{h.score.toFixed(2)}</span>
            </div>
            <div className="bar"><span style={{ width: `${Math.round(h.score * 100)}%` }} /></div>
            <div className="small muted">matched: {[...new Set(h.matched_sections)].join(', ')}</div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function History({ history }) {
  return (
    <section className="card">
      <h3>Incident history <span className="muted small">tool calling over SQLite</span></h3>
      <p>{history.summary}</p>
      {history.similar_incidents?.length > 0 && (
        <ul className="incidents">
          {history.similar_incidents.map((s) => (
            <li key={s.incident_id}>
              <span className="mono cite">{s.incident_id}</span> {s.title}
              <div className="small muted">Cause: {s.root_cause}. Fix: {s.resolution}.</div>
            </li>
          ))}
        </ul>
      )}
      <details>
        <summary className="small">{history.tool_calls?.length || 0} tool call(s){history.dropped_ids?.length ? ` · ${history.dropped_ids.length} invented id(s) dropped` : ''}</summary>
        <ul className="calls">
          {(history.tool_calls || []).map((c, i) => (
            <li key={i} className="mono small">
              <span className={c.ok ? 'ok' : 'bad'}>{c.ok ? '✓' : '✗'}</span> {c.tool}({JSON.stringify(c.args)}){c.fallback ? ' · fallback' : ''}
            </li>
          ))}
        </ul>
      </details>
    </section>
  )
}

function PlanView({ plan, critique }) {
  const eff = critique?.effective_risks || []
  return (
    <section className="card">
      <h3>Remediation plan</h3>
      <p><strong>Likely cause:</strong> {plan.root_cause_hypothesis}{' '}
        <span className="muted small">confidence {Math.round(plan.confidence * 100)}%</span></p>
      <ol className="steps">
        {plan.steps.map((s, i) => {
          const effective = eff[i] || s.risk
          return (
            <li key={i}>
              <div className="step-head">
                <span className="step-action">{s.action}</span>
                <Risk level={effective} from={effective !== s.risk ? s.risk : null} />
                <span className="mono cite">{s.citation}</span>
              </div>
              {s.command && <code className="cmd">{s.command}</code>}
            </li>
          )
        })}
      </ol>
      {plan.escalate_to && <p className="small muted">Escalate to: {plan.escalate_to}</p>}
      {critique && (
        <div className={`critic ${critique.grounded ? 'critic-ok' : 'critic-bad'}`}>
          <strong>Critic:</strong> {critique.grounded ? 'grounded' : 'not grounded'} · judge {critique.score}/5
          {[...(critique.rule_issues || []), ...(critique.judge_issues || [])].length > 0 && (
            <ul>{[...critique.rule_issues, ...critique.judge_issues].map((x, i) => <li key={i}>{x}</li>)}</ul>
          )}
        </div>
      )}
    </section>
  )
}

function Approval({ payload, onDecide, busy }) {
  const [reviewer, setReviewer] = useState('on-call engineer')
  const [comment, setComment] = useState('')
  return (
    <section className="card approval" aria-live="assertive">
      <h3>Human approval needed</h3>
      <p>The run is paused at the approval gate because:</p>
      <ul>{payload.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
      <div className="form-row">
        <label>Reviewer<input value={reviewer} onChange={(e) => setReviewer(e.target.value)} maxLength={80} /></label>
        <label className="grow">Comment<input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} placeholder="optional" /></label>
      </div>
      <div className="actions">
        <button className="btn btn-primary" disabled={busy} onClick={() => onDecide(true, reviewer, comment)}>Approve and run (simulated)</button>
        <button className="btn" disabled={busy} onClick={() => onDecide(false, reviewer, comment)}>Reject</button>
      </div>
    </section>
  )
}

function Report({ report }) {
  const t = report.totals
  return (
    <section className="card report">
      <div className="report-head">
        <h3>Triage report · <span className="mono">{report.ticket_id}</span></h3>
        <span className={`status ${report.approval?.approved ? 'status-ok' : 'status-bad'}`}>{report.status}</span>
      </div>
      <p className="lead">{report.executive_summary}</p>
      <div className="stats">
        <div><span className="stat">{(t.latency_ms / 1000).toFixed(1)}s</span><span className="muted small">agent time</span></div>
        <div><span className="stat">{t.llm_calls}</span><span className="muted small">LLM calls</span></div>
        <div><span className="stat">{(t.input_tokens + t.output_tokens).toLocaleString()}</span><span className="muted small">tokens</span></div>
        <div><span className="stat">{report.critic_score}/5</span><span className="muted small">critic score</span></div>
      </div>
      <p className="small muted">
        Approval: {report.approval?.required ? `${report.approval.approved ? 'approved' : 'rejected'} by ${report.approval.reviewer}` : report.approval?.comment}
        {report.approval?.comment && report.approval?.required ? ` · “${report.approval.comment}”` : ''}
      </p>
    </section>
  )
}

export default function Triage() {
  const [samples, setSamples] = useState([])
  const [ticket, setTicket] = useState('')
  const [logs, setLogs] = useState('')
  const [running, setRunning] = useState(false)
  const [trace, setTrace] = useState([])
  const [result, setResult] = useState({})
  const [approval, setApproval] = useState(null)
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [run, setRun] = useState(null)

  useEffect(() => {
    getJSON('/api/samples').then((s) => {
      setSamples(s)
      if (s[0]) { setTicket(s[0].ticket); setLogs(s[0].logs) }
    }).catch(() => {})
  }, [])

  function onEvent(event, data) {
    if (event === 'start') setRun(data)
    else if (event === 'node') {
      if (data.trace) setTrace((t) => [...t, data.trace])
      setResult((r) => ({ ...r, ...data.data }))
    } else if (event === 'approval_required') setApproval(data)
    else if (event === 'done') setReport(data.report)
    else if (event === 'error') setError(data.message)
  }

  async function go(url, body) {
    setRunning(true)
    setError('')
    try {
      await streamSSE(url, body, onEvent)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  function start(e) {
    e.preventDefault()
    setTrace([]); setResult({}); setApproval(null); setReport(null); setRun(null)
    go('/api/triage', { ticket, logs })
  }

  function decide(approved, reviewer, comment) {
    const thread = approval.thread_id
    setApproval(null)
    go(`/api/runs/${thread}/resume`, { approved, reviewer, comment })
  }

  function pick(id) {
    const s = samples.find((x) => x.id === id)
    if (s) { setTicket(s.ticket); setLogs(s.logs) }
  }

  const empty = !trace.length && !running && !error
  return (
    <div className="triage">
      <div className="col">
        <form className="card" onSubmit={start}>
          <h3>New incident</h3>
          <label>Example tickets
            <select onChange={(e) => pick(e.target.value)} defaultValue="">
              <option value="" disabled>Choose an example…</option>
              {samples.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </label>
          <label>Ticket
            <textarea rows={5} value={ticket} onChange={(e) => setTicket(e.target.value)} maxLength={4000} required minLength={10} />
          </label>
          <label>Log excerpt <span className="muted small">optional</span>
            <textarea rows={5} className="mono" value={logs} onChange={(e) => setLogs(e.target.value)} maxLength={8000} />
          </label>
          <div className="actions">
            <button className="btn btn-primary" disabled={running || ticket.trim().length < 10}>
              {running ? 'Running…' : 'Run triage'}
            </button>
            {run && <span className="muted small mono">{run.ticket_id}</span>}
          </div>
        </form>
        <section className="card">
          <h3>Agent timeline</h3>
          <Pipeline trace={trace} running={running} paused={!!approval} />
          <Timeline trace={trace} running={running} />
        </section>
      </div>

      <div className="col">
        {error && <div className="alert" role="alert">{error}</div>}
        {approval && <Approval payload={approval} onDecide={decide} busy={running} />}
        {report && <Report report={report} />}
        {result.plan && <PlanView plan={result.plan} critique={result.critique} />}
        {result.intake && <Intake intake={result.intake} signatures={result.signatures} />}
        {result.runbook_hits && <Runbooks hits={result.runbook_hits} />}
        {result.history && <History history={result.history} />}
        {empty && (
          <section className="card empty">
            <h3>Pick an example and run it</h3>
            <p className="muted">
              The first example (orders database rejecting writes) is SEV1 and includes a high-risk step, so it will pause for your approval.
              The certificate warning is low risk and is approved automatically by policy.
            </p>
          </section>
        )}
      </div>
    </div>
  )
}
