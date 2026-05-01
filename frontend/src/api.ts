import type { PipelineEvent, PipelineResult } from './types'

const API_BASE = '/api/v1'

export async function submitQuery(
  query: string,
): Promise<{ request_id: string; status: string }> {
  const res = await fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`Submit failed: ${err}`)
  }
  return res.json()
}

export function streamEvents(
  requestId: string,
  onEvent: (event: PipelineEvent) => void,
  onComplete: (result: PipelineResult | null) => void,
  onError: (error: string) => void,
): () => void {
  const source = new EventSource(`${API_BASE}/query/${requestId}/stream`)

  source.addEventListener('stage_start', (e) => {
    onEvent(JSON.parse(e.data))
  })

  source.addEventListener('stage_complete', (e) => {
    onEvent(JSON.parse(e.data))
  })

  source.addEventListener('stage_failed', (e) => {
    onEvent(JSON.parse(e.data))
  })

  source.addEventListener('retry', (e) => {
    onEvent(JSON.parse(e.data))
  })

  // pipeline_complete is a progress event from the orchestrator (no result data)
  source.addEventListener('pipeline_complete', (e) => {
    onEvent(JSON.parse(e.data))
  })

  // complete is the final event with the full result payload
  source.addEventListener('complete', (e) => {
    const data = JSON.parse(e.data)
    onComplete(data.result || null)
    source.close()
  })

  source.onerror = () => {
    // SSE disconnected — fall back to polling
    source.close()
    pollResult(requestId, onComplete, onError)
  }

  return () => source.close()
}

async function pollResult(
  requestId: string,
  onComplete: (result: PipelineResult | null) => void,
  onError: (error: string) => void,
) {
  for (let i = 0; i < 180; i++) {
    await new Promise((r) => setTimeout(r, 1000))
    try {
      const res = await fetch(`${API_BASE}/query/${requestId}`)
      const data = await res.json()
      if (data.status === 'complete') {
        onComplete(data.result)
        return
      }
      if (data.status === 'failed') {
        onError(data.error || 'Pipeline failed')
        return
      }
    } catch {
      // keep polling
    }
  }
  onError('Timeout waiting for results')
}
