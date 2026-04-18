"""
Canonical data schemas for the Outmate.ai multi-agent system.
All inter-agent communication uses these types — no ad-hoc dicts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentRole(str, Enum):
    PLANNER = "planner"
    RETRIEVAL = "retrieval"
    ENRICHMENT = "enrichment"
    CRITIC = "critic"
    GTM_STRATEGY = "gtm_strategy"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


class Persona(str, Enum):
    CEO = "ceo"
    VP_SALES = "vp_sales"
    CTO = "cto"
    VP_ENGINEERING = "vp_engineering"
    HEAD_OF_GROWTH = "head_of_growth"


class SignalType(str, Enum):
    HIRING = "hiring"
    FUNDING = "funding"
    TECH_STACK = "tech_stack"
    GROWTH = "growth"
    COMPETITOR_CHURN = "competitor_churn"
    EXPANSION = "expansion"


# ---------------------------------------------------------------------------
# Planner schemas
# ---------------------------------------------------------------------------

class PlannerOutput(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    entity_type: str  # "company", "person", "both"
    tasks: list[str]
    filters: dict[str, Any]  # structured extraction from NL query
    strategy: str  # brief strategy description
    target_personas: list[Persona]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str  # summarized, NOT chain-of-thought


# ---------------------------------------------------------------------------
# Retrieval schemas
# ---------------------------------------------------------------------------

class RetrievalFilter(BaseModel):
    industry: list[str] | None = None
    geography: list[str] | None = None
    employee_range: tuple[int, int] | None = None
    funding_stage: list[str] | None = None
    keywords: list[str] | None = None
    tech_stack: list[str] | None = None
    founded_after: int | None = None  # year


class CompanyRecord(BaseModel):
    company_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    domain: str | None = None
    industry: str | None = None
    geography: str | None = None
    employee_count: int | None = None
    funding_stage: str | None = None
    funding_total_usd: float | None = None
    founded_year: int | None = None
    description: str | None = None
    source: str = "unknown"
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class RetrievalOutput(BaseModel):
    companies: list[CompanyRecord]
    total_found: int
    filters_applied: RetrievalFilter
    filters_relaxed: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Enrichment schemas
# ---------------------------------------------------------------------------

class HiringSignal(BaseModel):
    open_roles: int | None = None
    engineering_roles: int | None = None
    sales_roles: int | None = None
    growth_rate_30d: float | None = None  # % change in job postings
    notable_roles: list[str] = Field(default_factory=list)
    source: str = "unknown"
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class GrowthSignal(BaseModel):
    revenue_estimate: str | None = None  # range string
    employee_growth_6m: float | None = None  # percentage
    web_traffic_trend: str | None = None  # "up", "down", "stable"
    social_mentions_trend: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class TechStackSignal(BaseModel):
    detected_technologies: list[str] = Field(default_factory=list)
    infrastructure: list[str] = Field(default_factory=list)
    source: str = "unknown"
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class CompetitorSignal(BaseModel):
    current_tools: list[str] = Field(default_factory=list)
    likely_competitors: list[str] = Field(default_factory=list)
    churn_indicators: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class EnrichedCompany(BaseModel):
    company: CompanyRecord
    hiring: HiringSignal | None = None
    growth: GrowthSignal | None = None
    tech_stack: TechStackSignal | None = None
    competitors: CompetitorSignal | None = None
    enrichment_completeness: float = Field(ge=0.0, le=1.0)
    # tracks which fields came back empty or unreliable
    missing_fields: list[str] = Field(default_factory=list)


class EnrichmentOutput(BaseModel):
    companies: list[EnrichedCompany]
    enrichment_rate: float  # fraction of fields successfully filled
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Critic / Validation schemas
# ---------------------------------------------------------------------------

class ValidationIssue(BaseModel):
    severity: str  # "error", "warning", "info"
    category: str  # "hallucination", "contradiction", "overconfidence", "irrelevant", "missing_data"
    message: str
    affected_company_ids: list[str] = Field(default_factory=list)
    suggested_action: str  # "retry", "remove", "relax_filters", "re_plan", "accept_with_caveat"


class CriticOutput(BaseModel):
    approved: bool
    overall_quality: float = Field(ge=0.0, le=1.0)
    issues: list[ValidationIssue]
    companies_approved: list[str]  # IDs that pass validation
    companies_rejected: list[str]  # IDs that fail
    recommended_action: str  # "proceed", "retry_enrichment", "retry_retrieval", "re_plan"
    reasoning_summary: str


# ---------------------------------------------------------------------------
# ICP Scoring
# ---------------------------------------------------------------------------

class ICPScore(BaseModel):
    company_id: str
    fit_score: float = Field(ge=0.0, le=1.0)
    intent_score: float = Field(ge=0.0, le=1.0)
    growth_score: float = Field(ge=0.0, le=1.0)
    composite_score: float = Field(ge=0.0, le=1.0)
    breakdown: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# GTM Strategy schemas
# ---------------------------------------------------------------------------

class OutreachHook(BaseModel):
    persona: Persona
    hook: str
    angle: str
    reasoning: str  # why this hook for this company+persona


class EmailSnippet(BaseModel):
    persona: Persona
    subject: str
    body: str
    personalization_points: list[str]


class CompanyGTMStrategy(BaseModel):
    company_id: str
    company_name: str
    icp_score: ICPScore
    hooks: list[OutreachHook]
    email_snippets: list[EmailSnippet]
    competitive_positioning: str | None = None
    recommended_channel: str  # "email", "linkedin", "cold_call"


class GTMStrategyOutput(BaseModel):
    strategies: list[CompanyGTMStrategy]
    confidence: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Pipeline-level schemas
# ---------------------------------------------------------------------------

class AgentStepTrace(BaseModel):
    agent: AgentRole | str
    status: TaskStatus
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    attempt: int = 1
    error: str | None = None
    summary: str = ""


class PipelineResult(BaseModel):
    """The final output shipped to the client."""
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query: str
    plan: PlannerOutput
    results: list[EnrichedCompany]
    signals: list[dict[str, Any]]
    gtm_strategy: GTMStrategyOutput
    icp_scores: list[ICPScore]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_trace: list[AgentStepTrace]
    total_duration_ms: int
    retries: int = 0
