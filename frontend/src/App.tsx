import { useState, useCallback, useRef } from 'react'
import { QueryInput } from './components/QueryInput'
import { ExecutionTimeline } from './components/ExecutionTimeline'
import { StatsBar } from './components/StatsBar'
import { CompanyCard } from './components/CompanyCard'
import { submitQuery, streamEvents } from './api'
import type { AgentStep, PipelineEvent, PipelineResult } from './types'

const AGENT_PIPELINE: { name: string; label: string }[] = [
  { name: 'planner', label: 'Plan' },
  { name: 'retrieval', label: 'Retrieve' },
  { name: 'enrichment', label: 'Enrich' },
  { name: 'critic', label: 'Validate' },
  { name: 'scorer', label: 'Score' },
  { name: 'gtm_strategy', label: 'Strategy' },
]

function initSteps(): AgentStep[] {
  return AGENT_PIPELINE.map((a) => ({
    name: a.name,
    label: a.label,
    status: 'pending',
    attempt: 1,
    data: {},
  }))
}

export default function App() {
  const [isLoading, setIsLoading] = useState(false)
  const [steps, setSteps] = useState<AgentStep[]>([])
  const [result, setResult] = useState<PipelineResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retries, setRetries] = useState(0)
  const [requestId, setRequestId] = useState<string | null>(null)
  const cleanupRef = useRef<(() => void) | null>(null)

  const updateStep = useCallback((agentName: string, updates: Partial<AgentStep>) => {
    setSteps((prev) =>
      prev.map((s) => (s.name === agentName ? { ...s, ...updates } : s)),
    )
  }, [])

  const handleEvent = useCallback(
    (event: PipelineEvent) => {
      const agent = event.agent
      const now = Date.now()

      if (event.event_type === 'stage_start') {
        updateStep(agent, {
          status: 'running',
          attempt: event.attempt,
          startTime: now,
        })
      } else if (event.event_type === 'stage_complete') {
        updateStep(agent, {
          status: 'complete',
          data: event.data,
          endTime: now,
        })
      } else if (event.event_type === 'stage_failed') {
        updateStep(agent, {
          status: 'failed',
          data: event.data,
          endTime: now,
        })
      } else if (event.event_type === 'retry') {
        setRetries((r) => r + 1)
        updateStep(agent, {
          status: 'retrying',
          attempt: event.attempt,
        })
      }
    },
    [updateStep],
  )

  const handleSubmit = useCallback(
    async (query: string) => {
      // Clean up previous stream
      if (cleanupRef.current) {
        cleanupRef.current()
        cleanupRef.current = null
      }

      setIsLoading(true)
      setResult(null)
      setError(null)
      setRetries(0)
      setRequestId(null)
      setSteps(initSteps())

      try {
        const { request_id } = await submitQuery(query)
        setRequestId(request_id)

        const cleanup = streamEvents(
          request_id,
          handleEvent,
          (pipelineResult) => {
            setResult(pipelineResult)
            setIsLoading(false)
            // Mark remaining pending steps as complete if we got a result
            if (pipelineResult) {
              setSteps((prev) =>
                prev.map((s) => {
                  if (s.status === 'pending' || s.status === 'running') {
                    return { ...s, status: 'complete', endTime: Date.now() }
                  }
                  return s
                }),
              )
              setRetries(pipelineResult.retries)
            }
          },
          (errMsg) => {
            setError(errMsg)
            setIsLoading(false)
          },
        )
        cleanupRef.current = cleanup
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to submit query')
        setIsLoading(false)
      }
    },
    [handleEvent],
  )

  // Build lookup maps for results
  const strategyMap = new Map(
    result?.gtm_strategy.strategies.map((s) => [s.company_id, s]) ?? [],
  )
  const scoreMap = new Map(
    result?.icp_scores.map((s) => [s.company_id, s]) ?? [],
  )

  return (
    <div className="app">
      <header className="header">
        <div className="header-badge">AI-Powered</div>
        <h1>Multi-Agent GTM Intelligence System</h1>
        <p>Six specialized AI agents working in concert — plan, retrieve, enrich, validate, score, and generate hyper-personalized outreach</p>
      </header>

      <QueryInput onSubmit={handleSubmit} isLoading={isLoading} />

      {(isLoading || result) && (
        <ExecutionTimeline steps={steps} retries={retries} />
      )}

      {error && <div className="error-banner">{error}</div>}

      {result && (
        <>
          <StatsBar result={result} />

          {/* Download PDF button */}
          {requestId && result.results.length > 0 && (
            <div className="pdf-row">
              <button
                type="button"
                className="download-btn"
                onClick={() => {
                  window.open(`/api/v1/query/${requestId}/pdf`, '_blank')
                }}
              >
                Download PDF Report
              </button>
            </div>
          )}

          {result.plan && (
            <div className="strategy-banner">
              <strong className="strategy-label">Strategy: </strong>
              {result.plan.strategy}
            </div>
          )}

          <div className="results-section">
            <div className="section-title">
              Results ({result.results.length} companies, ranked by ICP score)
            </div>
            {result.results
              .sort((a, b) => {
                const sa = scoreMap.get(a.company.company_id)?.composite_score ?? 0
                const sb = scoreMap.get(b.company.company_id)?.composite_score ?? 0
                return sb - sa
              })
              .map((company, i) => (
                <CompanyCard
                  key={company.company.company_id}
                  company={company}
                  strategy={strategyMap.get(company.company.company_id)}
                  score={scoreMap.get(company.company.company_id)}
                  rank={i}
                />
              ))}
          </div>
        </>
      )}
    </div>
  )
}
