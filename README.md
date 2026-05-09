# Outmate.ai — Multi-Agent GTM Intelligence System

A production-grade AI system that converts natural language GTM (Go-To-Market) queries into actionable outbound intelligence. Powered by 5 autonomous AI agents orchestrated through a pipeline with retry logic, ICP scoring, and real-time streaming.
<img width="1919" height="679" alt="image" src="https://github.com/user-attachments/assets/e4302366-c940-440b-ab66-84f04c17ffe3" />


## What It Does

Type a query like:
> "Find high-growth AI SaaS companies in India and generate personalized outbound hooks for their VP Sales"

The system will:
1. **Plan** — AI interprets your query into structured search filters
2. **Retrieve** — Finds real companies matching your criteria (using AI knowledge)
3. **Enrich** — Gathers hiring signals, growth data, tech stack, and competitor intel
4. **Validate** — Critic agent checks data quality, detects hallucinations
5. **Score** — ICP scoring ranks companies by fit, intent, and growth
6. **Strategize** — Generates personalized outreach hooks and email drafts per company

Results display in a real-time UI with a downloadable PDF report.

**This is not a simple LLM pipeline — it is a reasoning-driven, failure-aware, self-correcting system.

deployed on vercel for frontend and railway for backend. Try it yourself: https://mas-gtm-projecth.vercel.app/
---

## Quick Start

### Prerequisites

- **Python 3.9+**
- **Node.js 18+** (for frontend)
- **Google AI Studio API Key** (free): https://aistudio.google.com/apikey

### 1. Clone & Setup

```bash
cd outmate-ai

# Install Python dependencies
pip install -e ".[dev]"

# Install frontend dependencies
cd frontend
npm install
cd ..
```

### 2. Configure

```bash
# Copy the example env file
cp .env.example .env

# Edit .env and add your Google AI Studio API key
# Get one free at: https://aistudio.google.com/apikey
```

Open `.env` and replace `your-google-ai-studio-api-key-here` with your actual key.

### 3. Run

Open **two terminals**:

**Terminal 1 — Backend (FastAPI on port 8000):**
```bash
python main.py
```

**Terminal 2 — Frontend (Vite on port 5173):**
```bash
cd frontend
npm run dev
```

### 4. Use

Open **http://localhost:5173** in your browser.

Type a GTM query and click **Analyze**. Watch the agents work in real-time, then browse company results with ICP scores and GTM strategies. Click **Download PDF Report** to get a shareable report.

---

## Running Without an API Key (Mock Mode)

If you don't have an API key or want to test the system quickly:

```bash
OUTMATE_LLM_PROVIDER=mock python main.py
```

This uses a built-in mock LLM that returns realistic but fake results. Good for testing the full pipeline, UI, and PDF export without any API costs.

---

## Project Structure

```
outmate-ai/
├── main.py                     # Entry point — wires everything together
├── config/
│   └── settings.py             # Pydantic settings (env vars)
├── src/
│   ├── agents/
│   │   ├── base.py             # BaseAgent with retry, circuit breaker, timeout
│   │   ├── planner.py          # NL query → structured plan
│   │   ├── retrieval.py        # Plan → company search
│   │   ├── enrichment.py       # Companies → enriched with signals
│   │   ├── critic.py           # Data quality validation
│   │   └── gtm_strategy.py     # Outreach hooks & email generation
│   ├── orchestrator/
│   │   └── pipeline.py         # Control loop with nested retry logic
│   ├── scoring/
│   │   └── icp_scorer.py       # Deterministic ICP scoring (fit/intent/growth)
│   ├── signals/
│   │   └── signal_engine.py    # Signal simulation engine
│   ├── memory/
│   │   └── session_memory.py   # In-process TTL cache
│   ├── models/
│   │   └── schemas.py          # 22+ Pydantic models for all data contracts
│   ├── tools/
│   │   ├── llm_client.py       # Gemini & Claude API wrappers with rate limiting
│   │   ├── llm_data_source.py  # LLM-powered real company search
│   │   ├── llm_signal_providers.py # LLM-powered batch enrichment
│   │   ├── data_sources.py     # Mock company database (dev mode)
│   │   ├── signal_providers.py # Mock signal providers (dev mode)
│   │   └── pdf_report.py       # PDF report generator
│   └── api/
│       └── server.py           # FastAPI endpoints + SSE streaming
├── frontend/
│   └── src/
│       ├── App.tsx              # Main React component
│       ├── api.ts               # API client with SSE streaming
│       ├── types.ts             # TypeScript type definitions
│       └── components/
│           ├── QueryInput.tsx   # Search input with example queries
│           ├── ExecutionTimeline.tsx # Real-time agent progress
│           ├── StatsBar.tsx     # Confidence, count, duration meters
│           └── CompanyCard.tsx  # Company card with signals & strategies
├── tests/
│   ├── test_pipeline_integration.py  # End-to-end pipeline tests
│   ├── test_icp_scorer.py            # ICP scoring tests
│   ├── test_critic_rules.py          # Critic rule-based checks
│   ├── test_memory.py                # Session memory tests
│   └── test_api.py                   # API endpoint tests
├── .env.example                # Environment template
└── pyproject.toml              # Python project config
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/query` | Submit a GTM query |
| `GET` | `/api/v1/query/{id}/stream` | SSE stream of pipeline events |
| `GET` | `/api/v1/query/{id}` | Poll for result (fallback) |
| `GET` | `/api/v1/query/{id}/pdf` | Download PDF report |

### Example API Usage

```bash
# Submit a query
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Find AI startups in India with 50-200 employees"}'

# Response: {"request_id": "abc-123", "status": "accepted"}

# Poll for result
curl http://localhost:8000/api/v1/query/abc-123

# Download PDF
curl -o report.pdf http://localhost:8000/api/v1/query/abc-123/pdf
```

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

44 tests pass covering: pipeline integration, ICP scoring, critic rules, memory, and API endpoints.

---

## Architecture

### 5 Autonomous Agents

| Agent | Role | Input | Output |
|-------|------|-------|--------|
| **Planner** | Interprets NL query | User query | Structured filters, personas, strategy |
| **Retrieval** | Finds companies | Plan filters | Deduplicated company records |
| **Enrichment** | Adds signals | Company records | Hiring, growth, tech, competitors |
| **Critic** | Validates quality | Enriched data | Approve/reject with recommendations |
| **GTM Strategy** | Generates outreach | Approved companies | Hooks, emails, positioning |

### Pipeline Control Flow

```
PLAN → RETRIEVE → ENRICH → CRITIQUE → SCORE → STRATEGY
  ↑         ↑                  |
  |         |        reject: retry enrichment
  |         +------- reject: relax filters
  +----------------- reject: re-plan entirely
```

- **Outer loop**: Re-plan (max 3 attempts)
- **Inner loop**: Filter relaxation (max 2 levels)
- **Critic loop**: Re-enrich rejected companies
- **Wall-clock budget**: 300 seconds max

### ICP Scoring

Deterministic 3-dimension composite score:
```
composite = 0.35 × fit + 0.40 × intent + 0.25 × growth
```

- **Fit**: Industry match, geography, company size, funding stage
- **Intent**: Hiring velocity, competitor churn signals, tech stack overlap
- **Growth**: Employee growth, web traffic trend, funding recency

---

## Free Tier Limits

Google AI Studio free tier allows:
- **20 requests/day** per model
- **10 requests/minute** per model

Each pipeline run uses ~5 API calls, so you get **~4 runs per day** per model. The built-in rate limiter (7s between calls) prevents hitting the per-minute limit.

**Tip**: If one model's quota is exhausted, switch to another in `.env`:
```
OUTMATE_LLM_MODEL=gemini-2.5-flash       # try a different model
```

Each model has its own separate quota bucket.

---
## Demo Video link: 
https://drive.google.com/file/d/194OAq2YXT1IJYaabAHW-iST3whUy-cNn/view?usp=drive_link

## Tech Stack

- **Backend**: Python, FastAPI, Pydantic v2, asyncio
- **Frontend**: React 19, TypeScript, Vite
- **AI**: Google Gemini (free tier) or Anthropic Claude
- **PDF**: ReportLab
- **Streaming**: Server-Sent Events (SSE)

---

## License

MIT
