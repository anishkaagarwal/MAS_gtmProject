import type { PipelineResult } from '../types'

interface Props {
  result: PipelineResult
}

function confidenceClass(v: number): string {
  if (v >= 0.7) return 'high'
  if (v >= 0.4) return 'medium'
  return 'low'
}

function confidenceColor(v: number): string {
  if (v >= 0.7) return 'var(--success)'
  if (v >= 0.4) return 'var(--warning)'
  return 'var(--error)'
}

export function StatsBar({ result }: Props) {
  return (
    <div className="confidence-section">
      <div className="stat-card">
        <div className="stat-label">Confidence</div>
        <div className={`stat-value ${confidenceClass(result.confidence)}`}>
          {(result.confidence * 100).toFixed(0)}%
        </div>
        <div className="confidence-bar">
          <div
            className="confidence-fill"
            style={{
              width: `${result.confidence * 100}%`,
              background: confidenceColor(result.confidence),
            }}
          />
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-label">Companies Found</div>
        <div className="stat-value" style={{ color: 'var(--info)' }}>
          {result.results.length}
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-label">Strategies Generated</div>
        <div className="stat-value" style={{ color: 'var(--accent)' }}>
          {result.gtm_strategy.strategies.length}
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-label">Duration</div>
        <div className="stat-value" style={{ color: 'var(--text-secondary)' }}>
          {(result.total_duration_ms / 1000).toFixed(1)}s
        </div>
      </div>
    </div>
  )
}
