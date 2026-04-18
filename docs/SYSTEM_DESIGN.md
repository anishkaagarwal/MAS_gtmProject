# Outmate.ai — System Design Document

## 1. SYSTEM ARCHITECTURE

```
                         ┌──────────────────────────────────────┐
                         │           API Gateway                │
                         │   POST /query  GET /query/:id/stream │
                         └──────────────┬───────────────────────┘
                                        │
                         ┌──────────────▼───────────────────────┐
                         │       Pipeline Orchestrator           │
                         │  (control loop, retry, budget mgmt)   │
                         └──┬────┬────┬────┬────┬───────────────┘
                            │    │    │    │    │
              ┌─────────────┘    │    │    │    └─────────────┐
              ▼                  ▼    │    ▼                  ▼
        ┌──────────┐    ┌──────────┐ │ ┌──────────┐   ┌──────────┐
        │ Planner  │    │Retrieval │ │ │  Critic  │   │   GTM    │
        │  Agent   │    │  Agent   │ │ │  Agent   │   │ Strategy │
        └──────────┘    └──────────┘ │ └──────────┘   └──────────┘
                                     ▼
                              ┌──────────┐
                              │Enrichment│
                              │  Agent   │
                              └────┬─────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
              ┌──────────┐  ┌──────────┐   ┌──────────┐
              │  Hiring  │  │  Growth  │   │  Tech    │
              │ Signals  │  │ Signals  │   │  Stack   │
              └──────────┘  └──────────┘   └──────────┘

        ┌────────────────────────────────────────────────────┐
        │                 Memory Layer                        │
        │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
        │  │ Session  │  │  Redis   │  │  Vector Memory   │ │
        │  │  Cache   │  │  Cache   │  │  (Pinecone/QD)   │ │
        │  └──────────┘  └──────────┘  └──────────────────┘ │
        └────────────────────────────────────────────────────┘
```

### Component Breakdown

| Component | Responsibility | Stateful? |
|-----------|---------------|-----------|
| **API Gateway** | HTTP/SSE, rate limiting, auth | No |
| **Orchestrator** | Control loop, retry logic, budget enforcement | Per-request only |
| **Planner Agent** | NL → structured plan decomposition | No |
| **Retrieval Agent** | Plan → API calls → company records | No |
| **Enrichment Agent** | Company → signals (hiring, growth, tech) | No |
| **Critic Agent** | Quality gate: hallucination/contradiction detection | No |
| **ICP Scorer** | Deterministic fit/intent/growth scoring | No |
| **GTM Strategy Agent** | Approved companies → hooks, emails, angles | No |
| **Session Memory** | In-process TTL cache per pipeline run | Yes (ephemeral) |
| **Redis Cache** | Cross-request dedup, intermediate results | Yes (persistent) |
| **Vector Memory** | Semantic retrieval of past query→plan→outcome | Yes (persistent) |

### Data Flow

```
Query (NL) → Planner → Structured Plan
                          ↓
              Retrieval → CompanyRecord[]
                          ↓
              Enrichment → EnrichedCompany[] (with signals)
                          ↓
              Critic → Approved | Retry | Re-plan
                          ↓ (if approved)
              ICP Scorer → ICPScore[]
                          ↓
              GTM Strategy → Hooks + Emails + Angles
                          ↓
              PipelineResult → SSE → Frontend
```

---

## 2. AGENT DESIGN (DETAILED)

### 2.1 Planner Agent

**Role**: Decompose natural-language GTM query into a structured execution plan.

**Input Schema**:
```json
{
  "query": "Find high-growth AI SaaS companies in the US...",
  "session_context": {"user_id": "...", "similar_past_query": "..."},
  "previous_plan": null
}
```

**Output Schema**:
```json
{
  "plan_id": "uuid",
  "entity_type": "company",
  "tasks": ["search", "enrich", "analyze_signals", "score_icp", "generate_outreach"],
  "filters": {
    "industry": ["ai", "saas"],
    "geography": ["us"],
    "employee_range": [50, 500],
    "funding_stage": ["series_a", "series_b"],
    "keywords": ["machine learning", "artificial intelligence"]
  },
  "strategy": "Target mid-market AI SaaS in growth phase. Focus on VP Sales who feel pipeline pressure from fast scaling.",
  "target_personas": ["vp_sales"],
  "confidence": 0.85,
  "reasoning_summary": "Query clearly specifies AI SaaS, US market, high-growth. Targeting VP Sales as specified."
}
```

**Internal Reasoning Steps**:
1. Parse entity type from query (company vs person vs both)
2. Extract explicit filters (industry, geo, size)
3. Infer implicit filters from context (e.g., "high-growth" → employee_growth > 20%)
4. Select applicable tasks based on query intent
5. Identify target personas from role mentions
6. Score own confidence based on filter clarity

**Failure Modes**:
- Ambiguous query → low confidence, vague filters
- Contradictory constraints → impossible filter combinations
- Out-of-domain query → entity_type mismatch

**Retry Strategy**:
- Attempt 1: strict interpretation
- Attempt 2: relax interpretation, ask for broader filters
- Attempt 3: fallback to minimal plan (search + enrich only)

---

### 2.2 Retrieval Agent

**Role**: Convert plan filters into API calls, return deduplicated company records.

**Input Schema**:
```json
{
  "plan": { "...PlannerOutput..." },
  "relaxation_level": 0,
  "excluded_company_ids": []
}
```

**Output Schema**:
```json
{
  "companies": [{ "company_id": "...", "name": "...", "domain": "...", ... }],
  "total_found": 25,
  "filters_applied": { "industry": ["ai"], "geography": ["us"], ... },
  "filters_relaxed": [],
  "confidence": 0.8,
  "warnings": []
}
```

**Internal Reasoning Steps**:
1. Translate plan filters to source-specific query formats
2. Query multiple sources concurrently
3. Deduplicate by domain
4. Assess result quality (count, diversity)
5. Decide if relaxation is needed

**Failure Modes**:
- Over-constrained query → zero results
- Source API outage → partial results
- Stale data → outdated company info

**Retry Strategy**:
- Level 0: apply all filters strictly
- Level 1: drop employee_range and funding_stage
- Level 2: keep only industry + geography

---

### 2.3 Enrichment Agent

**Role**: Augment company records with buying signals.

**Input/Output**: See `EnrichmentInput`/`EnrichmentOutput` in schemas.

**Internal Reasoning Steps**:
1. Determine which signals to fetch per company
2. Fan out to signal providers concurrently (bounded semaphore)
3. Aggregate results, tracking missing fields
4. Calculate enrichment completeness per company

**Failure Modes**:
- Signal provider timeout → missing field (not failure)
- Rate limiting → partial enrichment
- Bad data from provider → confidence degradation

**Retry Strategy**: Bounded to 2 retries (expensive). On retry, only re-fetch failed signals.

---

### 2.4 Validation / Critic Agent

**Role**: Quality gate — detect hallucinations, contradictions, irrelevance.

**Two-phase design**:
1. **Rule-based checks** (fast, deterministic): employee/funding contradictions, suspicious round numbers, sparse records
2. **LLM-based semantic checks**: query-relevance scoring, nuanced contradiction detection

**Failure Modes**:
- Critic too strict → rejects everything → re-plan loops
- Critic too lenient → bad data passes through
- LLM hallucination in critic itself → contradictory approval

**Retry Strategy**: Max 2 attempts. If critic fails, default to conservative (reject + re-plan).

---

### 2.5 GTM Strategy Agent

**Role**: Generate personalized outreach per company+persona.

**Internal Reasoning Steps**:
1. Build rich context from enrichment data + ICP score
2. Match signals to persona pain points
3. Generate hooks using specific company data points
4. Draft email snippets with personalization
5. Recommend outreach channel based on persona + company size

**Failure Modes**:
- Sparse enrichment data → generic hooks (detected by self-validation)
- Wrong persona targeting → messaging mismatch
- Hallucinated company details in outreach copy

**Retry Strategy**: 2 attempts. On retry, simplify to fewer personas.

---

## 3. ORCHESTRATION ENGINE

### Control Loop Logic

```
WHILE pipeline_attempt < MAX_RETRIES:
    elapsed = wall_clock_time()
    IF elapsed > BUDGET: BREAK

    // PLAN
    plan = planner.run(query, previous_plan?)
    IF plan.failed: CONTINUE (re-plan)

    // RETRIEVE (with filter relaxation)
    FOR relaxation IN 0..MAX_RELAXATION:
        results = retriever.run(plan, relaxation)
        IF results.count >= MIN_REQUIRED: BREAK
    IF results.empty:
        previous_plan = plan
        CONTINUE (re-plan with context)

    // ENRICH
    enriched = enricher.run(results)

    // CRITIQUE
    FOR critic_attempt IN 0..MAX_CRITIC_RETRIES:
        verdict = critic.run(query, plan, enriched)
        IF verdict.approved AND verdict.quality >= MIN_QUALITY:
            BREAK
        SWITCH verdict.recommended_action:
            "re_plan":         previous_plan = plan; BREAK inner; CONTINUE outer
            "retry_retrieval": BREAK inner; CONTINUE outer
            "retry_enrichment": re-enrich rejected subset; CONTINUE inner
            "proceed":         BREAK inner (accept with caveats)

    // SCORE + STRATEGY (only reached if critic approves)
    scores = icp_scorer.score(approved_companies)
    strategy = gtm_agent.run(approved_companies, scores)
    RETURN result

// EXHAUSTED — return degraded result with confidence=0
RETURN degraded_result
```

### Retry Conditions

| Condition | Action | Max |
|-----------|--------|-----|
| Zero retrieval results | Relax filters, then re-plan | 2 relaxations + 3 re-plans |
| Critic rejects (hallucination) | Re-enrich rejected subset | 2 |
| Critic rejects (irrelevance) | Re-plan with feedback | 3 |
| Agent timeout | Retry with same input | 3 per agent |
| Circuit breaker open | Fail fast, return degraded | — |
| Wall-clock budget exceeded | Return best available result | 120s default |

### Adaptive Behavior

1. **Filter relaxation**: progressive — drops least-important constraints first
2. **Re-planning**: critic feedback is injected into the planner's context
3. **Partial retry**: only re-enrich companies that failed, not the whole batch
4. **Degraded return**: always returns *something* — never a raw error to the user

---

## 4. MEMORY SYSTEM

### What / When / How

| Layer | What | When Stored | How Retrieved | TTL |
|-------|------|-------------|---------------|-----|
| **Session Cache** | Intermediate agent outputs, deduped API responses | After each agent step | Key lookup (namespace:identifier) | 5 min |
| **Redis Cache** | Company enrichment data, query→plan mappings | After successful enrichment | Hash key (company domain, query hash) | 1 hour |
| **Vector Memory** | (query, plan, quality_score) tuples | After pipeline completes | Semantic similarity search | ∞ (quality-filtered) |

### Cache Strategy

```
ON enrichment_request(company):
    cached = redis.get("enrichment", company.domain)
    IF cached AND cached.age < 1h:
        RETURN cached  // skip API calls
    ELSE:
        result = call_signal_providers(company)
        redis.set("enrichment", company.domain, result, ttl=3600)
        RETURN result
```

### Vector Memory (Improvement Loop)

```
ON pipeline_complete(query, plan, quality):
    IF quality >= 0.6:  // only learn from good runs
        embedding = embed(query)
        vector_store.upsert(embedding, {query, plan, quality})

ON new_query(query):
    similar = vector_store.query(embed(query), top_k=3)
    IF similar:
        inject into planner context as "similar past approaches"
```

---

## 5. FAILURE & HALLUCINATION HANDLING

### Detection Strategies

**Fabricated Data**:
- All numeric fields suspiciously round (e.g., 100 employees, $10M funding, 50 open roles)
- Data too complete for a small/private company
- Revenue figures for pre-revenue startups

**Contradictions**:
- 5 employees but Series C funding
- "Stealth mode" company with detailed tech stack
- Founded 2024 but 500+ employees

**Overconfidence**:
- Enrichment confidence 0.9 but 70% fields missing
- Hiring growth_rate_30d = 100% (likely data artifact)
- All companies scoring identically on ICP

### Recovery Strategies

| Detection | Recovery |
|-----------|----------|
| Fabricated numbers | Flag company, re-enrich from different source |
| Contradiction | Remove contradictory company, log for review |
| Overconfidence | Downgrade confidence scores, add caveat to output |
| Empty results | Relax filters → re-plan → return degraded result |
| Critic self-contradiction | Default to conservative (reject + re-plan) |

### Confidence Propagation

Final confidence = `min(plan.confidence, critic.quality, strategy.confidence)`

This means the weakest link determines overall confidence — a strong plan
with a weak enrichment still gets a low confidence score.

---

## 6. DATA & SIGNAL ENGINE

### Signal Inference

| Signal | Primary Source | Inference Logic |
|--------|---------------|-----------------|
| Hiring velocity | LinkedIn Jobs, Indeed | `(new_postings_30d - old_postings_30d) / old_postings_30d` |
| Growth | LinkedIn headcount, SimilarWeb | `(current_employees - 6mo_ago) / 6mo_ago` |
| Tech stack | BuiltWith, job posts, GitHub | NLP extraction from job descriptions + web scraping |
| Funding | Crunchbase, PitchBook | Direct lookup + news article NLP |
| Competitor churn | G2 reviews, job posts | Keyword detection: "migrating from", "replacing", negative reviews |

### Noisy Data Simulation

The signal engine realistically simulates:
- **Missing fields**: 20-40% of signals return null (mimics real API gaps)
- **Stale data**: job postings may be 3+ days old
- **Noise**: ±15% on numeric values
- **False positives**: competitor detection has high false-positive rate (40% no-data)

### Transformation Logic

```python
# Hiring signal normalization
raw_roles = api_response.get("total_jobs", None)
IF raw_roles IS NULL:
    return HiringSignal(confidence=0.1)  # unknown, not zero

normalized = {
    "open_roles": raw_roles,
    "engineering_roles": categorize(raw_roles, "engineering"),
    "growth_rate": (raw_roles - cached_roles_30d_ago) / max(cached, 1),
}
confidence = 0.8 IF source == "linkedin" ELSE 0.5
```

---

## 7. ICP SCORING ENGINE

### Formula

```
composite = (W_fit * fit) + (W_intent * intent) + (W_growth * growth)

WHERE:
  W_fit    = 0.35
  W_intent = 0.40  (highest — intent is the strongest signal)
  W_growth = 0.25

fit    = 0.30*industry_match + 0.15*geo_match + 0.25*size_match + 0.30*funding_match
intent = 0.35*hiring_velocity + 0.35*competitor_churn + 0.30*tech_stack_fit
growth = 0.40*employee_growth + 0.30*web_traffic + 0.30*funding_recency
```

### Scoring Details

- **industry_match**: 1.0 (exact), 0.6 (partial keyword), 0.5 (unknown)
- **size_match**: Gaussian decay from target range center. Missing = 0.3 penalty.
- **hiring_velocity**: `min(growth_rate_30d / 20%, 1.0)` — 20%+ growth = max score
- **competitor_churn**: `min(churn_indicators_count / 3, 1.0)` — 3+ signals = max
- **tech_stack_fit**: Jaccard similarity between detected and target tech

### Pseudocode

```python
def score(company: EnrichedCompany) -> ICPScore:
    fit = weighted_sum(
        industry_match(company.industry, target_industries),
        geo_match(company.geography, target_geos),
        size_match(company.employee_count, target_range),
        funding_match(company.funding_stage, target_stages),
    )
    intent = weighted_sum(
        hiring_velocity(company.hiring),
        competitor_churn(company.competitors),
        tech_stack_fit(company.tech_stack, target_tech),
    )
    growth = weighted_sum(
        employee_growth(company.growth),
        web_traffic(company.growth),
        funding_recency(company.funding_stage),
    )
    composite = 0.35*fit + 0.40*intent + 0.25*growth
    return ICPScore(fit, intent, growth, composite)
```

---

## 8. GTM STRATEGY GENERATION

### Personalization Approach

1. **Signal → Pain Point mapping**: each signal type maps to persona-specific pain points
2. **Specificity enforcement**: hooks MUST reference a concrete data point from enrichment
3. **Channel recommendation**: based on persona + company size + signal strength

### Persona Differentiation

| Persona | Focus Areas | Hook Style | Channel |
|---------|-------------|-----------|---------|
| **CEO** | Revenue, market position, board-level metrics | Strategic, forward-looking | Email + warm intro |
| **VP Sales** | Pipeline, quota, rep productivity, tool consolidation | Direct, ROI-focused | LinkedIn + email |
| **CTO** | Architecture, tech debt, build vs buy, integration | Technical, credibility-first | Email + community |
| **VP Eng** | Dev velocity, hiring, platform stability | Pragmatic, empathetic | LinkedIn |
| **Head of Growth** | CAC, LTV, experimentation, channel expansion | Data-driven, experimental | Email |

### Sample Output Structure

```json
{
  "company_id": "abc-123",
  "company_name": "DataFlow AI",
  "icp_score": {
    "fit_score": 0.82,
    "intent_score": 0.71,
    "growth_score": 0.88,
    "composite_score": 0.79
  },
  "hooks": [
    {
      "persona": "vp_sales",
      "hook": "Noticed DataFlow just posted 8 new SDR roles — when pipeline demand scales that fast, the tools either keep up or become the bottleneck.",
      "angle": "Sales tech consolidation during hypergrowth",
      "reasoning": "8 SDR postings in 30 days + 40% employee growth signals pipeline pressure. VP Sales feels this directly."
    }
  ],
  "email_snippets": [
    {
      "persona": "vp_sales",
      "subject": "Re: scaling SDR ops at DataFlow",
      "body": "Hi [Name],\n\nSaw your team just posted 8 new SDR roles — congrats on the growth. When teams scale that fast, the ops tooling usually becomes the constraint before the people do.\n\nWe helped [similar company] cut ramp time by 40% during a similar hiring push. Worth a 15-min look?\n\nBest,\n[Sender]",
      "personalization_points": ["8 SDR postings", "employee growth rate", "series B stage"]
    }
  ],
  "competitive_positioning": "DataFlow uses Outreach — position against their lack of AI-driven sequencing",
  "recommended_channel": "linkedin"
}
```

---

## 9. BACKEND DESIGN

### Tech Stack

| Component | Technology | Justification |
|-----------|-----------|---------------|
| **Runtime** | Python 3.11+ | Ecosystem (ML/AI libs), async support, team familiarity |
| **Framework** | FastAPI | Async native, Pydantic integration, SSE support |
| **LLM** | Claude (Anthropic SDK) | Best structured output quality, tool use capability |
| **Cache** | Redis 7+ | Mature, fast, TTL support, pub/sub for events |
| **Vector DB** | Pinecone (or Qdrant) | Managed, scalable, metadata filtering |
| **Task Queue** | None initially → Temporal for v2 | Start simple, add workflow engine when retry logic outgrows the orchestrator |
| **Observability** | Structlog + OpenTelemetry | Structured logs for grep-ability, distributed traces for debugging |

### API Endpoints

```
POST   /api/v1/query                    → Submit query, get request_id
GET    /api/v1/query/{id}/stream        → SSE event stream
GET    /api/v1/query/{id}               → Poll for result (fallback)
GET    /health                          → Readiness check

Request:
{
  "query": "Find high-growth AI SaaS companies...",
  "session_context": {}  // optional
}

Response (SSE stream):
event: stage_start
data: {"agent": "planner", "attempt": 1}

event: stage_complete
data: {"agent": "planner", "confidence": 0.85, "tasks": ["search", "enrich"]}

event: stage_start
data: {"agent": "retrieval", "relaxation_level": 0}

...

event: complete
data: { ...PipelineResult... }
```

### Logging & Observability

```python
# Structured logging — every log line is machine-parseable
logger.info(
    "agent.completed",
    agent="planner",
    call_id="abc123",
    attempt=1,
    duration_ms=1200,
    confidence=0.85,
)

# OpenTelemetry spans — one per agent step
with tracer.start_as_current_span("planner.execute") as span:
    span.set_attribute("query.length", len(query))
    span.set_attribute("attempt", attempt)
    result = await planner.run(input)
    span.set_attribute("confidence", result.confidence)
```

**Dashboards** (Grafana):
- Pipeline success rate (per hour)
- Agent-level latency (p50, p95, p99)
- Retry rate per agent
- Critic rejection rate
- Mean ICP score distribution

---

## 10. FRONTEND DESIGN

### Component Breakdown

```
<App>
  <QueryInput />              // NL prompt input + submit button
  <ExecutionTimeline>         // Real-time agent progress
    <AgentStep agent="planner" status="complete" />
    <AgentStep agent="retrieval" status="running" />
    <AgentStep agent="enrichment" status="pending" />
    <AgentStep agent="critic" status="pending" />
    <RetryIndicator attempt={2} maxAttempts={3} />
  </ExecutionTimeline>
  <ConfidenceMeter value={0.82} />
  <ResultsPanel>
    <CompanyCard>
      <ICPScoreBar fit={0.82} intent={0.71} growth={0.88} />
      <SignalBadges signals={["hiring_surge", "competitor_churn"]} />
      <OutreachTabs>
        <PersonaTab persona="VP Sales">
          <HookDisplay />
          <EmailPreview />
        </PersonaTab>
        <PersonaTab persona="CTO">...</PersonaTab>
      </OutreachTabs>
      <ExplainButton />       // "Why this result?" expandable
    </CompanyCard>
  </ResultsPanel>
</App>
```

### Execution Timeline Visualization

```
[✓ Plan] ──→ [✓ Retrieve] ──→ [⟳ Enrich] ──→ [  Critic  ] ──→ [  Strategy  ]
  0.8s         2.1s            running...
                               ↳ retry #1 (3 signals failed)
```

### Streaming UX Strategy

1. **SSE connection** established on query submit
2. Each `stage_start` event adds a new step to the timeline (pending → running)
3. Each `stage_complete` updates the step (running → complete) with metadata
4. Partial results shown as soon as enrichment completes (before strategy)
5. Final result replaces partial view
6. On disconnect: fall back to polling GET `/api/v1/query/{id}`

---

## 11. SCALABILITY & EXTENSIBILITY

### Horizontal Scaling

```
                    ┌──────────┐
                    │   LB     │
                    └────┬─────┘
                  ┌──────┼──────┐
                  ▼      ▼      ▼
             ┌────────┐ ┌────────┐ ┌────────┐
             │ API #1 │ │ API #2 │ │ API #3 │
             └───┬────┘ └───┬────┘ └───┬────┘
                 └──────────┼──────────┘
                            ▼
                    ┌──────────────┐
                    │    Redis     │  ← shared state
                    └──────────────┘
```

Each API instance runs its own orchestrator. Statefulness is pushed to Redis.
No inter-instance coordination needed.

**Scaling triggers**:
- CPU-bound? Add API instances (stateless)
- LLM-bound? Add more API key pools, implement request batching
- Data-source-bound? Add caching layers, increase Redis TTL

### Plug-and-Play Agent System

New agents register via a simple protocol:

```python
class MyNewAgent(BaseAgent[MyInput, MyOutput]):
    role = AgentRole.MY_AGENT
    async def _execute(self, input_data: MyInput) -> MyOutput: ...
    def _validate_output(self, output: MyOutput) -> list[str]: ...
```

The orchestrator doesn't know about agent internals. It only knows:
1. What input each agent takes
2. What output it returns
3. That `run()` handles retries/circuit-breaking

### Parallel Execution Opportunities

| Stage | Parallelizable? | How |
|-------|----------------|-----|
| Retrieval across sources | Yes | `asyncio.gather` over data sources |
| Enrichment across companies | Yes | Semaphore-bounded concurrency (5) |
| Signal extraction per company | Yes | `asyncio.gather` over signal types |
| ICP scoring | Yes | Pure CPU, trivially parallelizable |
| GTM strategy | Partially | Could split by company, but LLM is the bottleneck |

---

## 12. CODE STRUCTURE

```
outmate-ai/
├── pyproject.toml
├── config/
│   └── settings.py           # Pydantic settings from env
├── src/
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py         # ALL inter-agent schemas (Pydantic)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py            # BaseAgent: retry, circuit-breaker, tracing
│   │   ├── planner.py         # NL → structured plan
│   │   ├── retrieval.py       # Plan → company records
│   │   ├── enrichment.py      # Company → signals
│   │   ├── critic.py          # Quality gate (rule-based + LLM)
│   │   └── gtm_strategy.py    # Companies → outreach
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   └── pipeline.py        # Main control loop
│   ├── memory/
│   │   ├── __init__.py
│   │   └── session_memory.py  # 3-tier memory (session, Redis, vector)
│   ├── scoring/
│   │   ├── __init__.py
│   │   └── icp_scorer.py      # Deterministic ICP scoring
│   ├── signals/
│   │   ├── __init__.py
│   │   └── signal_engine.py   # Signal extraction + noise simulation
│   ├── tools/
│   │   └── __init__.py        # External tool wrappers (APIs, scrapers)
│   └── api/
│       ├── __init__.py
│       └── server.py          # FastAPI app, SSE streaming
├── tests/
└── docs/
    └── SYSTEM_DESIGN.md       # This file
```

---

## ASSUMPTIONS & JUSTIFICATIONS

1. **Python over Go/Rust**: The LLM call latency (1-5s) dwarfs any language overhead. Python's AI ecosystem is unmatched. If we hit CPU bottlenecks, we move ICP scoring to a Go microservice.

2. **No Celery/Temporal initially**: The orchestrator's retry logic is < 300 lines. Adding a workflow engine adds operational overhead (broker, workers, monitoring). We migrate when retry logic exceeds what's maintainable in-process.

3. **Redis over PostgreSQL for cache**: We don't need ACID for cache. Redis TTL is exactly what we need. If we later need durable query history, we add PostgreSQL for that specific use case.

4. **Single LLM provider**: Claude for all LLM calls. We could multi-provider for redundancy, but it complicates prompt engineering (each model responds differently to structured output prompts). Adding a second provider is a v2 concern.

5. **ICP scoring is deterministic (no LLM)**: Scoring must be explainable and reproducible. If two runs on the same data produce different scores, users lose trust. The LLM handles the fuzzy parts (planning, strategy); scoring is math.

6. **Critic uses both rules AND LLM**: Rule-based checks are fast and catch obvious problems. LLM catches subtle issues (query relevance, nuanced contradictions). Neither alone is sufficient.
