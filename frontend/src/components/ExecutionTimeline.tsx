import { Check, X, Loader2, Clock, RotateCcw, Brain, Search, Zap, ShieldCheck, BarChart2, Megaphone } from 'lucide-react'
import type { AgentStep } from '../types'

interface Props {
  steps: AgentStep[]
  retries: number
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
  pending:  <Clock size={14} />,
  running:  <Loader2 size={14} className="spinning" />,
  complete: <Check size={14} />,
  failed:   <X size={14} />,
  retrying: <RotateCcw size={14} />,
}

const AGENT_META: Record<string, { icon: React.ReactNode; color: string; label: string; description: string }> = {
  planner:     { icon: <Brain size={16} />,       color: '#a78bfa', label: 'Planner',      description: 'Interpreting query → execution plan' },
  retrieval:   { icon: <Search size={16} />,      color: '#38bdf8', label: 'Retrieval',    description: 'Searching company database' },
  enrichment:  { icon: <Zap size={16} />,         color: '#34d399', label: 'Enrichment',   description: 'Fetching signals & data' },
  critic:      { icon: <ShieldCheck size={16} />, color: '#fb923c', label: 'Critic',       description: 'Validating data quality' },
  scorer:      { icon: <BarChart2 size={16} />,   color: '#f472b6', label: 'Scorer',       description: 'Computing ICP scores' },
  gtm_strategy:{ icon: <Megaphone size={16} />,   color: '#facc15', label: 'Strategy',     description: 'Generating personalized outreach' },
}

function formatPct(val: unknown): string {
  const n = Number(val)
  return isNaN(n) ? '' : `${(n * 100).toFixed(0)}%`
}

function AgentThinkingCard({ step }: { step: AgentStep }) {
  const meta = AGENT_META[step.name]
  const d = step.data
  if (!meta || (step.status !== 'complete' && step.status !== 'running' && step.status !== 'failed')) return null

  const duration = step.endTime && step.startTime
    ? `${((step.endTime - step.startTime) / 1000).toFixed(1)}s`
    : null

  return (
    <div className={`thinking-card thinking-card--${step.status} thinking-card--${step.name}`} data-agent={step.name}>
      <div className="thinking-card__header">
        <span className="thinking-card__icon">{meta.icon}</span>
        <span className="thinking-card__name">{meta.label}</span>
        <span className={`thinking-card__status thinking-card__status--${step.status}`}>
          {STATUS_ICONS[step.status]}
          {step.status === 'running' ? 'thinking...' : step.status}
        </span>
        {duration && <span className="thinking-card__duration">{duration}</span>}
      </div>

      {step.status === 'running' && (
        <div className="thinking-card__body">
          <p className="thinking-card__desc">{meta.description}</p>
          <div className="thinking-card__dots">
            <span /><span /><span />
          </div>
        </div>
      )}

      {step.status === 'complete' && (
        <div className="thinking-card__body">
          {/* Planner reasoning */}
          {step.name === 'planner' && (
            <>
              {d.reasoning_summary && (
                <p className="thinking-card__reasoning">{String(d.reasoning_summary)}</p>
              )}
              {d.strategy && (
                <div className="thinking-card__fact">
                  <span className="thinking-card__fact-label">Strategy</span>
                  <span>{String(d.strategy)}</span>
                </div>
              )}
              <div className="thinking-card__chips">
                {d.confidence !== undefined && (
                  <span className="thinking-chip">Confidence {formatPct(d.confidence)}</span>
                )}
                {Array.isArray(d.target_personas) && d.target_personas.map((p: string) => (
                  <span key={p} className="thinking-chip thinking-chip--persona">{p.replace('_', ' ')}</span>
                ))}
                {Array.isArray(d.tasks) && (
                  <span className="thinking-chip">{(d.tasks as string[]).length} tasks</span>
                )}
              </div>
            </>
          )}

          {/* Retrieval */}
          {step.name === 'retrieval' && (
            <div className="thinking-card__chips">
              {d.count !== undefined && (
                <span className="thinking-chip thinking-chip--success">{String(d.count)} companies found</span>
              )}
              {d.relaxation !== undefined && Number(d.relaxation) > 0 && (
                <span className="thinking-chip thinking-chip--warn">filter relaxed ×{String(d.relaxation)}</span>
              )}
              {d.relaxation === 0 && (
                <span className="thinking-chip">strict filters matched</span>
              )}
            </div>
          )}

          {/* Enrichment */}
          {step.name === 'enrichment' && (
            <div className="thinking-card__chips">
              {d.count !== undefined && (
                <span className="thinking-chip thinking-chip--success">{String(d.count)} companies enriched</span>
              )}
              {d.enrichment_rate !== undefined && (
                <span className="thinking-chip">Signal coverage {formatPct(d.enrichment_rate)}</span>
              )}
            </div>
          )}

          {/* Critic */}
          {step.name === 'critic' && (
            <>
              {d.reasoning_summary && (
                <p className="thinking-card__reasoning">{String(d.reasoning_summary)}</p>
              )}
              <div className="thinking-card__chips">
                {d.quality !== undefined && (
                  <span className={`thinking-chip ${Number(d.quality) >= 0.7 ? 'thinking-chip--success' : 'thinking-chip--warn'}`}>
                    Quality {formatPct(d.quality)}
                  </span>
                )}
                {d.companies_approved !== undefined && (
                  <span className="thinking-chip thinking-chip--success">{String(d.companies_approved)} approved</span>
                )}
                {d.companies_rejected !== undefined && Number(d.companies_rejected) > 0 && (
                  <span className="thinking-chip thinking-chip--error">{String(d.companies_rejected)} rejected</span>
                )}
                {d.action && (
                  <span className="thinking-chip">→ {String(d.action).replace('_', ' ')}</span>
                )}
              </div>
            </>
          )}

          {/* Scorer */}
          {step.name === 'scorer' && (
            <div className="thinking-card__chips">
              {d.scored !== undefined && (
                <span className="thinking-chip thinking-chip--success">{String(d.scored)} companies scored</span>
              )}
              {d.avg_composite !== undefined && (
                <span className="thinking-chip">Avg ICP score {formatPct(d.avg_composite)}</span>
              )}
            </div>
          )}

          {/* Strategy */}
          {step.name === 'gtm_strategy' && (
            <div className="thinking-card__chips">
              {d.strategies !== undefined && (
                <span className="thinking-chip thinking-chip--success">{String(d.strategies)} strategies generated</span>
              )}
              {d.confidence !== undefined && (
                <span className="thinking-chip">Confidence {formatPct(d.confidence)}</span>
              )}
            </div>
          )}
        </div>
      )}

      {step.status === 'failed' && (
        <div className="thinking-card__body">
          <p className="thinking-card__error">{String(d.error ?? 'Agent failed — pipeline will retry')}</p>
        </div>
      )}

      {step.attempt > 1 && (
        <div className="thinking-card__retry-badge">retry #{step.attempt}</div>
      )}
    </div>
  )
}

export function ExecutionTimeline({ steps, retries }: Props) {
  if (steps.length === 0) return null

  const activeSteps = steps.filter(
    (s) => s.status === 'running' || s.status === 'complete' || s.status === 'failed' || s.status === 'retrying'
  )

  return (
    <div className="timeline-section">
      {/* Compact stepper */}
      <div className="stepper">
        {steps.map((step, i) => {
          const meta = AGENT_META[step.name]
          return (
            <div key={step.name} className="stepper__item">
              <div className={`stepper__dot stepper__dot--${step.status}`}>
                {STATUS_ICONS[step.status]}
              </div>
              <span className="stepper__label">{meta?.label ?? step.label}</span>
              {i < steps.length - 1 && (
                <div className={`stepper__line ${step.status === 'complete' ? 'stepper__line--done' : ''}`} />
              )}
            </div>
          )
        })}
      </div>

      {/* Thinking log */}
      {activeSteps.length > 0 && (
        <div className="thinking-log">
          <div className="thinking-log__title">Agent Reasoning</div>
          {activeSteps.map((step) => (
            <AgentThinkingCard key={step.name} step={step} />
          ))}
        </div>
      )}

      {retries > 0 && (
        <div className="pipeline-retry-note">
          <RotateCcw size={12} />
          Pipeline retried {retries} time{retries > 1 ? 's' : ''}
        </div>
      )}

      <style>{`
        .spinning { animation: spin 1s linear infinite; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes blink { 0%, 80%, 100% { opacity: 0.2; } 40% { opacity: 1; } }
      `}</style>
    </div>
  )
}
