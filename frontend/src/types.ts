export interface PipelineEvent {
  event_type: string
  agent: string
  attempt: number
  data: Record<string, unknown>
  timestamp: number
}

export interface ICPScore {
  company_id: string
  fit_score: number
  intent_score: number
  growth_score: number
  composite_score: number
  breakdown: Record<string, number>
}

export interface OutreachHook {
  persona: string
  hook: string
  angle: string
  reasoning: string
}

export interface EmailSnippet {
  persona: string
  subject: string
  body: string
  personalization_points: string[]
}

export interface CompanyGTMStrategy {
  company_id: string
  company_name: string
  icp_score: ICPScore
  hooks: OutreachHook[]
  email_snippets: EmailSnippet[]
  competitive_positioning: string | null
  recommended_channel: string
}

export interface HiringSignal {
  open_roles: number | null
  engineering_roles: number | null
  sales_roles: number | null
  growth_rate_30d: number | null
  notable_roles: string[]
  source: string
  confidence: number
}

export interface GrowthSignal {
  revenue_estimate: string | null
  employee_growth_6m: number | null
  web_traffic_trend: string | null
  social_mentions_trend: string | null
  confidence: number
}

export interface TechStackSignal {
  detected_technologies: string[]
  infrastructure: string[]
  source: string
  confidence: number
}

export interface CompetitorSignal {
  current_tools: string[]
  likely_competitors: string[]
  churn_indicators: string[]
  confidence: number
}

export interface CompanyRecord {
  company_id: string
  name: string
  domain: string | null
  industry: string | null
  geography: string | null
  employee_count: number | null
  funding_stage: string | null
  funding_total_usd: number | null
  founded_year: number | null
  description: string | null
  source: string
}

export interface EnrichedCompany {
  company: CompanyRecord
  hiring: HiringSignal | null
  growth: GrowthSignal | null
  tech_stack: TechStackSignal | null
  competitors: CompetitorSignal | null
  enrichment_completeness: number
  missing_fields: string[]
}

export interface PlannerOutput {
  plan_id: string
  entity_type: string
  tasks: string[]
  filters: Record<string, unknown>
  strategy: string
  target_personas: string[]
  confidence: number
  reasoning_summary: string
}

export interface AgentStepTrace {
  agent: string
  status: string
  started_at: string
  completed_at: string | null
  duration_ms: number | null
  attempt: number
  error: string | null
  summary: string
}

export interface PipelineResult {
  request_id: string
  query: string
  plan: PlannerOutput
  results: EnrichedCompany[]
  signals: Record<string, unknown>[]
  gtm_strategy: {
    strategies: CompanyGTMStrategy[]
    confidence: number
  }
  icp_scores: ICPScore[]
  confidence: number
  reasoning_trace: AgentStepTrace[]
  total_duration_ms: number
  retries: number
}

export type AgentStatus = 'pending' | 'running' | 'complete' | 'failed' | 'retrying'

export interface AgentStep {
  name: string
  label: string
  status: AgentStatus
  attempt: number
  data: Record<string, unknown>
  startTime?: number
  endTime?: number
}
