import { useState } from 'react'
import { Search } from 'lucide-react'

const EXAMPLES = [
  'Find high-growth AI SaaS companies in the US and generate outbound hooks for VP Sales',
  'Identify fintech startups hiring aggressively and suggest outreach strategies',
  'Give me companies likely to churn competitors and how to target their CTO',
  'Find Series A cybersecurity companies with 50-200 employees',
]

interface Props {
  onSubmit: (query: string) => void
  isLoading: boolean
}

export function QueryInput({ onSubmit, isLoading }: Props) {
  const [query, setQuery] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim() && !isLoading) {
      onSubmit(query.trim())
    }
  }

  return (
    <div className="query-section">
      <form className="query-form" onSubmit={handleSubmit}>
        <input
          type="text"
          className="query-input"
          placeholder="Describe your ideal target companies and outreach strategy..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={isLoading}
        />
        <button type="submit" className="submit-btn" disabled={isLoading || !query.trim()}>
          {isLoading ? 'Running...' : (
            <>
              <Search size={16} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 6 }} />
              Analyze
            </>
          )}
        </button>
      </form>
      <div className="examples">
        {EXAMPLES.map((ex, i) => (
          <button
            key={i}
            className="example-chip"
            onClick={() => { setQuery(ex); if (!isLoading) onSubmit(ex) }}
            disabled={isLoading}
          >
            {ex.length > 60 ? ex.slice(0, 57) + '...' : ex}
          </button>
        ))}
      </div>
    </div>
  )
}
