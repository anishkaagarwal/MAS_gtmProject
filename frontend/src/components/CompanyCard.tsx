import { useState } from 'react'
import { ChevronDown, ChevronRight, HelpCircle } from 'lucide-react'
import type { EnrichedCompany, CompanyGTMStrategy, ICPScore } from '../types'

interface Props {
  company: EnrichedCompany
  strategy: CompanyGTMStrategy | undefined
  score: ICPScore | undefined
  rank: number
}

export function CompanyCard({ company, strategy, score, rank }: Props) {
  const [expanded, setExpanded] = useState(rank === 0)
  const [activePersona, setActivePersona] = useState<string | null>(null)
  const [showExplain, setShowExplain] = useState(false)

  const c = company.company
  const compositePercent = score ? (score.composite_score * 100).toFixed(0) : '?'
  const compositeColor = score
    ? score.composite_score >= 0.7
      ? 'var(--success)'
      : score.composite_score >= 0.4
        ? 'var(--warning)'
        : 'var(--error)'
    : 'var(--text-muted)'

  // Collect unique personas from hooks + emails
  const personas = strategy
    ? [...new Set([
        ...strategy.hooks.map(h => h.persona),
        ...strategy.email_snippets.map(e => e.persona),
      ])]
    : []
  const currentPersona = activePersona || personas[0] || null

  // Build signal badges
  const signals: { label: string; type: string }[] = []
  if (company.hiring?.open_roles && company.hiring.open_roles > 10) {
    signals.push({ label: `${company.hiring.open_roles} open roles`, type: 'hiring' })
  }
  if (company.hiring?.growth_rate_30d && company.hiring.growth_rate_30d > 15) {
    signals.push({ label: `${company.hiring.growth_rate_30d.toFixed(0)}% hiring growth`, type: 'hiring' })
  }
  if (company.growth?.employee_growth_6m && company.growth.employee_growth_6m > 20) {
    signals.push({ label: `${company.growth.employee_growth_6m.toFixed(0)}% employee growth`, type: 'growth' })
  }
  if (company.growth?.web_traffic_trend === 'up') {
    signals.push({ label: 'Traffic trending up', type: 'growth' })
  }
  if (company.tech_stack?.detected_technologies?.length) {
    signals.push({ label: company.tech_stack.detected_technologies.slice(0, 3).join(', '), type: 'tech' })
  }
  if (company.competitors?.churn_indicators?.length) {
    signals.push({ label: `${company.competitors.churn_indicators.length} churn signals`, type: 'competitor' })
  }

  return (
    <div className={`company-card ${expanded ? 'expanded' : ''}`}>
      <div className="company-header" onClick={() => setExpanded(!expanded)}>
        <div className="company-left">
          <div className="company-name">
            {expanded ? <ChevronDown size={16} style={{ display: 'inline', marginRight: 6 }} /> : <ChevronRight size={16} style={{ display: 'inline', marginRight: 6 }} />}
            {c.name}
          </div>
          <div className="company-meta">
            {c.industry && <span className="meta-tag">{c.industry}</span>}
            {c.geography && <span className="meta-tag">{c.geography.toUpperCase()}</span>}
            {c.employee_count && <span className="meta-tag">{c.employee_count} employees</span>}
            {c.funding_stage && <span className="meta-tag">{c.funding_stage.replace('_', ' ')}</span>}
          </div>
        </div>
        <div className="icp-badge" style={{ color: compositeColor }}>
          {compositePercent}
        </div>
      </div>

      {expanded && (
        <div className="company-body">
          {/* ICP Score Bars */}
          {score && (
            <div className="icp-bars">
              <div className="icp-bar-item">
                <div className="icp-bar-label">
                  <span>Fit</span>
                  <span>{(score.fit_score * 100).toFixed(0)}%</span>
                </div>
                <div className="icp-bar-track">
                  <div className="icp-bar-fill fit" style={{ width: `${score.fit_score * 100}%` }} />
                </div>
              </div>
              <div className="icp-bar-item">
                <div className="icp-bar-label">
                  <span>Intent</span>
                  <span>{(score.intent_score * 100).toFixed(0)}%</span>
                </div>
                <div className="icp-bar-track">
                  <div className="icp-bar-fill intent" style={{ width: `${score.intent_score * 100}%` }} />
                </div>
              </div>
              <div className="icp-bar-item">
                <div className="icp-bar-label">
                  <span>Growth</span>
                  <span>{(score.growth_score * 100).toFixed(0)}%</span>
                </div>
                <div className="icp-bar-track">
                  <div className="icp-bar-fill growth" style={{ width: `${score.growth_score * 100}%` }} />
                </div>
              </div>
            </div>
          )}

          {/* Signal Badges */}
          {signals.length > 0 && (
            <div className="signals-row">
              {signals.map((s, i) => (
                <span key={i} className={`signal-badge ${s.type}`}>{s.label}</span>
              ))}
            </div>
          )}

          {/* Persona Tabs + Outreach Content */}
          {strategy && personas.length > 0 && (
            <>
              <div className="persona-tabs">
                {personas.map(p => (
                  <button
                    key={p}
                    className={`persona-tab ${currentPersona === p ? 'active' : ''}`}
                    onClick={() => setActivePersona(p)}
                  >
                    {p.replace('_', ' ').toUpperCase()}
                  </button>
                ))}
              </div>

              <div className="outreach-content">
                {strategy.hooks
                  .filter(h => h.persona === currentPersona)
                  .map((hook, i) => (
                    <div key={i} className="hook-card">
                      <div className="hook-label">Hook</div>
                      <div className="hook-text">{hook.hook}</div>
                      <div className="hook-label" style={{ marginTop: '0.75rem' }}>Angle</div>
                      <div className="hook-text" style={{ color: 'var(--text-secondary)' }}>{hook.angle}</div>
                    </div>
                  ))}

                {strategy.email_snippets
                  .filter(e => e.persona === currentPersona)
                  .map((email, i) => (
                    <div key={i} className="email-card">
                      <div className="email-subject">{email.subject}</div>
                      <div className="email-body">{email.body}</div>
                      {email.personalization_points.length > 0 && (
                        <div className="personalization-tags">
                          {email.personalization_points.map((p, j) => (
                            <span key={j} className="p-tag">{p}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
              </div>

              {strategy.competitive_positioning && (
                <div style={{ marginBottom: '0.75rem' }}>
                  <div className="hook-label">Competitive Positioning</div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    {strategy.competitive_positioning}
                  </div>
                </div>
              )}

              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Recommended channel: <strong style={{ color: 'var(--text-secondary)' }}>{strategy.recommended_channel}</strong>
              </div>
            </>
          )}

          {/* Why this result? */}
          <button className="explain-toggle" onClick={() => setShowExplain(!showExplain)}>
            <HelpCircle size={14} />
            {showExplain ? 'Hide explanation' : 'Why this result?'}
          </button>

          {showExplain && (
            <div className="explain-content">
              <p><strong>Company:</strong> {c.description || 'No description available'}</p>
              <p><strong>Enrichment completeness:</strong> {(company.enrichment_completeness * 100).toFixed(0)}%</p>
              {company.missing_fields.length > 0 && (
                <p><strong>Missing signals:</strong> {company.missing_fields.join(', ')}</p>
              )}
              {score && (
                <>
                  <p style={{ marginTop: '0.5rem' }}><strong>Score breakdown:</strong></p>
                  <ul className="breakdown-list">
                    {Object.entries(score.breakdown).map(([key, val]) => (
                      <li key={key}>
                        <span>{key.replace(/_/g, ' ')}</span>
                        <span>{(val * 100).toFixed(0)}%</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
