import { useEffect, useState } from 'react'
import { getJSON } from './api.js'
import Triage from './components/Triage.jsx'
import Evaluation from './components/Evaluation.jsx'
import About from './components/About.jsx'

const TABS = [
  { id: 'triage', label: 'Triage' },
  { id: 'eval', label: 'Evaluation' },
  { id: 'about', label: 'How it works' },
]

function HealthChip({ health, error }) {
  if (error) return <span className="chip chip-bad">Backend unreachable</span>
  if (!health) return <span className="chip">Connecting…</span>
  const llmOk = health.llm.provider !== 'not configured'
  return (
    <span className={`chip ${llmOk ? 'chip-ok' : 'chip-warn'}`} title={`${health.vector_store.chunks} runbook chunks · ${health.incidents} past incidents`}>
      {llmOk ? `${health.llm.provider} · ${health.vector_store.backend}` : 'LLM not configured'}
    </span>
  )
}

export default function App() {
  const [tab, setTab] = useState('triage')
  const [health, setHealth] = useState(null)
  const [healthError, setHealthError] = useState(false)

  useEffect(() => {
    getJSON('/api/health').then(setHealth).catch(() => setHealthError(true))
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="var(--accent)" />
            <path d="M8 22 L14 10 L18 18 L24 8" stroke="white" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <div className="brand-name">TriageGraph</div>
            <div className="brand-sub">Multi-agent incident triage</div>
          </div>
        </div>
        <nav className="tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className="tab" onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </nav>
        <HealthChip health={health} error={healthError} />
      </header>
      <main className="main">
        {tab === 'triage' && <Triage health={health} />}
        {tab === 'eval' && <Evaluation />}
        {tab === 'about' && <About health={health} />}
      </main>
      <footer className="footer">
        Synthetic runbooks and incident data. Remediation actions are simulated and logged; nothing touches real infrastructure.
      </footer>
    </div>
  )
}
