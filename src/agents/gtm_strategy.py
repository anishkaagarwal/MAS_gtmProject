"""
GTM Strategy Agent — generates personalized outreach for each company+persona.

This runs AFTER validation passes. It takes approved, enriched companies
and produces hooks, messaging angles, and email snippets tailored to
each target persona.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.agents.json_utils import parse_json_array
from src.models.schemas import (
    AgentRole,
    CompanyGTMStrategy,
    EmailSnippet,
    EnrichedCompany,
    GTMStrategyOutput,
    ICPScore,
    OutreachHook,
    Persona,
    PlannerOutput,
)

logger = logging.getLogger(__name__)


class GTMStrategyInput(BaseModel):
    plan: PlannerOutput
    approved_companies: list[EnrichedCompany]
    icp_scores: list[ICPScore]
    original_query: str


GTM_SYSTEM_PROMPT = """\
You are a GTM strategist generating personalized outbound messaging.

For each company and persona combination, generate:
1. A hook: the opening line / attention grabber. Must reference something
   specific about the company (recent hire, growth signal, tech they use).
2. An angle: the strategic positioning — WHY should they care about our product.
3. An email snippet: subject + body (3-5 sentences). Must feel hand-written,
   not templated.

Persona guidelines:
- CEO: focus on revenue impact, market positioning, competitive advantage
- VP Sales: focus on pipeline, conversion, sales efficiency, quota attainment
- CTO: focus on technical integration, scalability, engineering velocity
- VP Engineering: focus on developer experience, build vs buy, tech debt
- Head of Growth: focus on CAC, LTV, channel expansion, experimentation velocity

Rules:
- NEVER use generic hooks like "I noticed your company is growing."
- ALWAYS reference specific signals from the enrichment data.
- If data is sparse, acknowledge uncertainty — don't fabricate specifics.
- Each email subject must be <60 characters.
- Email body: 3-4 sentences max. Be punchy, not verbose.
- Generate ONE hook and ONE email per company-persona pair.
- Recommend the best outreach channel per company.
- Keep total output concise — quality over quantity.

Output JSON array — one entry per company:
[
  {
    "company_id": "...",
    "company_name": "...",
    "hooks": [{"persona": "...", "hook": "...", "angle": "...", "reasoning": "..."}],
    "email_snippets": [{"persona": "...", "subject": "...", "body": "...", "personalization_points": [...]}],
    "competitive_positioning": "...",
    "recommended_channel": "email|linkedin|cold_call"
  }
]
"""


class GTMStrategyAgent(BaseAgent[GTMStrategyInput, GTMStrategyOutput]):
    role = AgentRole.GTM_STRATEGY
    max_retries = 2
    timeout = 180.0  # Groq rate-limit waits can exceed 50s per retry

    def __init__(self, llm_client: Any) -> None:
        super().__init__()
        self.llm = llm_client

    def _build_company_context(self, ec: EnrichedCompany, score: ICPScore | None) -> dict:
        """Build a rich context block for the LLM — no raw object dumps."""
        ctx: dict[str, Any] = {
            "company_id": ec.company.company_id,
            "name": ec.company.name,
            "industry": ec.company.industry,
            "geography": ec.company.geography,
            "employees": ec.company.employee_count,
            "funding_stage": ec.company.funding_stage,
            "description": ec.company.description,
        }
        if ec.hiring:
            ctx["hiring"] = {
                "open_roles": ec.hiring.open_roles,
                "engineering_roles": ec.hiring.engineering_roles,
                "growth_rate_30d": ec.hiring.growth_rate_30d,
                "notable_roles": ec.hiring.notable_roles,
            }
        if ec.growth:
            ctx["growth"] = {
                "employee_growth_6m": ec.growth.employee_growth_6m,
                "web_traffic_trend": ec.growth.web_traffic_trend,
            }
        if ec.tech_stack:
            ctx["tech_stack"] = ec.tech_stack.detected_technologies
        if ec.competitors:
            ctx["competitors"] = {
                "current_tools": ec.competitors.current_tools,
                "likely_competitors": ec.competitors.likely_competitors,
                "churn_indicators": ec.competitors.churn_indicators,
            }
        if score:
            ctx["icp_score"] = {
                "fit": score.fit_score,
                "intent": score.intent_score,
                "growth": score.growth_score,
                "composite": score.composite_score,
            }
        return ctx

    async def _execute(self, input_data: GTMStrategyInput) -> GTMStrategyOutput:
        # Build score lookup
        score_map = {s.company_id: s for s in input_data.icp_scores}

        company_contexts = [
            self._build_company_context(ec, score_map.get(ec.company.company_id))
            for ec in input_data.approved_companies
        ]

        personas = [p.value for p in input_data.plan.target_personas]

        user_prompt = (
            f"Original query: {input_data.original_query}\n\n"
            f"Target personas: {personas}\n\n"
            f"Companies ({len(company_contexts)}):\n"
            f"{json.dumps(company_contexts, indent=2)}"
        )

        raw = await self.llm.complete(system=GTM_SYSTEM_PROMPT, user=user_prompt)
        parsed = parse_json_array(raw)

        strategies: list[CompanyGTMStrategy] = []
        for entry in parsed:
            cid = entry.get("company_id") or entry.get("id", "")
            strategies.append(CompanyGTMStrategy(
                company_id=cid,
                company_name=entry.get("company_name", ""),
                icp_score=score_map.get(cid, ICPScore(
                    company_id=cid, fit_score=0, intent_score=0,
                    growth_score=0, composite_score=0,
                )),
                hooks=[OutreachHook(**h) for h in entry.get("hooks", [])],
                email_snippets=[EmailSnippet(**e) for e in entry.get("email_snippets", [])],
                competitive_positioning=entry.get("competitive_positioning"),
                recommended_channel=entry.get("recommended_channel", "email"),
            ))

        # Confidence based on how many companies got complete strategies
        complete = sum(1 for s in strategies if s.hooks and s.email_snippets)
        confidence = complete / max(len(strategies), 1)

        return GTMStrategyOutput(strategies=strategies, confidence=confidence)

    def _validate_output(self, output: GTMStrategyOutput) -> list[str]:
        issues: list[str] = []
        if not output.strategies:
            issues.append("No strategies generated.")
        for s in output.strategies:
            if not s.hooks:
                issues.append(f"No hooks for {s.company_name}")
            if not s.email_snippets:
                issues.append(f"No email snippets for {s.company_name}")
        return issues
