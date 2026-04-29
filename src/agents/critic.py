"""
Critic / Validation Agent — the system's immune system.

This agent reviews enriched results and detects:
1. Hallucinated data (fabricated numbers, impossible combinations)
2. Contradictions (e.g., "10 employees" but "Series C funded $200M")
3. Overconfidence (high confidence scores with thin evidence)
4. Irrelevant results (companies that don't match the original query intent)
5. Missing critical data (companies that passed enrichment but are too sparse)

The Critic decides: proceed, retry enrichment, retry retrieval, or re-plan entirely.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.agents.json_utils import parse_json_object
from src.models.schemas import (
    AgentRole,
    CriticOutput,
    EnrichedCompany,
    EnrichmentOutput,
    PlannerOutput,
    ValidationIssue,
)

logger = logging.getLogger(__name__)


class CriticInput(BaseModel):
    original_query: str
    plan: PlannerOutput
    enrichment_output: EnrichmentOutput
    attempt_number: int = 1


CRITIC_SYSTEM_PROMPT = """\
You are a data quality critic for a GTM intelligence system.

Your job is to review enriched company data and identify problems.

Check for:
1. HALLUCINATION: Data that looks fabricated (round numbers everywhere,
   impossibly consistent data, details that couldn't come from public sources).
2. CONTRADICTION: Fields that conflict (tiny company with huge funding,
   "stealth mode" company with detailed revenue data).
3. OVERCONFIDENCE: High confidence scores backed by sparse evidence.
4. IRRELEVANCE: Companies that don't match the original query intent.
5. MISSING CRITICAL DATA: Companies too sparse to generate meaningful outreach.

For each company, output "approve" or "reject" with reasons.
Then recommend one overall action:
- "proceed": results are good enough
- "retry_enrichment": re-enrich rejected companies
- "retry_retrieval": search again with adjusted filters
- "re_plan": the plan itself was wrong, start over

Output valid JSON:
{
  "approved": true/false,
  "overall_quality": 0.0-1.0,
  "issues": [
    {
      "severity": "error|warning|info",
      "category": "hallucination|contradiction|overconfidence|irrelevant|missing_data",
      "message": "...",
      "affected_company_ids": ["..."],
      "suggested_action": "retry|remove|relax_filters|re_plan|accept_with_caveat"
    }
  ],
  "companies_approved": ["id1", "id2"],
  "companies_rejected": ["id3"],
  "recommended_action": "proceed|retry_enrichment|retry_retrieval|re_plan",
  "reasoning_summary": "..."
}
"""


class CriticAgent(BaseAgent[CriticInput, CriticOutput]):
    role = AgentRole.CRITIC
    max_retries = 2
    timeout = 120.0  # Groq rate-limit waits can exceed 50s

    def __init__(self, llm_client: Any) -> None:
        super().__init__()
        self.llm = llm_client

    def _rule_based_checks(self, companies: list[EnrichedCompany]) -> list[ValidationIssue]:
        """
        Hard-coded sanity checks that don't need an LLM.
        These catch obvious problems fast and cheaply.
        """
        issues: list[ValidationIssue] = []

        for ec in companies:
            c = ec.company

            # Check: employee count vs funding stage contradiction
            if c.employee_count and c.funding_stage:
                if c.employee_count < 5 and c.funding_stage in ("series_c", "series_d", "ipo"):
                    issues.append(ValidationIssue(
                        severity="error",
                        category="contradiction",
                        message=f"{c.name}: {c.employee_count} employees but {c.funding_stage} — likely bad data",
                        affected_company_ids=[c.company_id],
                        suggested_action="remove",
                    ))

            # Check: impossibly high enrichment confidence with many missing fields
            if ec.enrichment_completeness < 0.15 and ec.hiring and ec.hiring.confidence > 0.95:
                issues.append(ValidationIssue(
                    severity="warning",
                    category="overconfidence",
                    message=f"{c.name}: hiring confidence {ec.hiring.confidence} but only {ec.enrichment_completeness:.0%} fields filled",
                    affected_company_ids=[c.company_id],
                    suggested_action="accept_with_caveat",
                ))

            # Check: all numeric fields are suspiciously round (hallucination signal)
            round_count = 0
            total_numeric = 0
            for val in [c.employee_count, c.funding_total_usd]:
                if val is not None:
                    total_numeric += 1
                    if val % 100 == 0:
                        round_count += 1
            if ec.hiring:
                for val in [ec.hiring.open_roles, ec.hiring.engineering_roles]:
                    if val is not None:
                        total_numeric += 1
                        if val % 10 == 0:
                            round_count += 1
            if total_numeric >= 4 and round_count == total_numeric:
                issues.append(ValidationIssue(
                    severity="warning",
                    category="hallucination",
                    message=f"{c.name}: all {total_numeric} numeric fields are round numbers — possible fabrication",
                    affected_company_ids=[c.company_id],
                    suggested_action="accept_with_caveat",
                ))

            # Check: critically sparse record
            if ec.enrichment_completeness < 0.1:
                issues.append(ValidationIssue(
                    severity="error",
                    category="missing_data",
                    message=f"{c.name}: only {ec.enrichment_completeness:.0%} enrichment — too sparse for outreach",
                    affected_company_ids=[c.company_id],
                    suggested_action="remove",
                ))
            elif ec.enrichment_completeness < 0.2:
                issues.append(ValidationIssue(
                    severity="warning",
                    category="missing_data",
                    message=f"{c.name}: {ec.enrichment_completeness:.0%} enrichment — proceed with caveat",
                    affected_company_ids=[c.company_id],
                    suggested_action="accept_with_caveat",
                ))

        return issues

    async def _execute(self, input_data: CriticInput) -> CriticOutput:
        companies = input_data.enrichment_output.companies

        # Phase 1: deterministic rule-based checks
        rule_issues = self._rule_based_checks(companies)

        # Phase 2: LLM-based semantic checks (query relevance, nuanced contradictions)
        company_summaries = []
        for ec in companies:
            summary = {
                "id": ec.company.company_id,
                "name": ec.company.name,
                "industry": ec.company.industry,
                "employees": ec.company.employee_count,
                "funding": ec.company.funding_stage,
                "enrichment_completeness": ec.enrichment_completeness,
                "missing_fields": ec.missing_fields,
            }
            if ec.hiring:
                summary["hiring_roles"] = ec.hiring.open_roles
            company_summaries.append(summary)

        user_prompt = (
            f"Original query: {input_data.original_query}\n\n"
            f"Plan strategy: {input_data.plan.strategy}\n\n"
            f"Companies to review ({len(companies)}):\n"
            f"{json.dumps(company_summaries, indent=2)}\n\n"
            f"Pre-check found {len([i for i in rule_issues if i.severity == 'error'])} errors "
            f"and {len([i for i in rule_issues if i.severity == 'warning'])} warnings via rule-based checks. "
            f"Focus your review on semantic relevance and contradictions not already caught.\n\n"
            f"This is attempt #{input_data.attempt_number}."
        )

        try:
            raw = await self.llm.complete(system=CRITIC_SYSTEM_PROMPT, user=user_prompt)
            parsed = parse_json_object(raw)

            llm_issues = [ValidationIssue(**i) for i in parsed.get("issues", [])]
            all_issues = rule_issues + llm_issues

            return CriticOutput(
                approved=parsed.get("approved", True),
                overall_quality=float(parsed.get("overall_quality", 0.6)),
                issues=all_issues,
                companies_approved=parsed.get("companies_approved", []),
                companies_rejected=parsed.get("companies_rejected", []),
                recommended_action=parsed.get("recommended_action", "proceed"),
                reasoning_summary=parsed.get("reasoning_summary", "Rule-based validation only"),
            )

        except Exception as e:
            logger.warning("Critic LLM failed (%s) — falling back to rule-based validation", e)
            return self._rule_based_fallback(companies, rule_issues)

    def _rule_based_fallback(
        self,
        companies: list[EnrichedCompany],
        rule_issues: list[ValidationIssue],
    ) -> CriticOutput:
        """Approve all companies that pass rule-based checks when LLM is unavailable."""
        error_ids = {
            cid
            for issue in rule_issues
            if issue.severity == "error"
            for cid in issue.affected_company_ids
        }
        approved_ids = [ec.company.company_id for ec in companies if ec.company.company_id not in error_ids]
        rejected_ids = list(error_ids)
        quality = 0.65 if not error_ids else max(0.4, 0.65 - 0.05 * len(error_ids))
        return CriticOutput(
            approved=bool(approved_ids),
            overall_quality=quality,
            issues=rule_issues,
            companies_approved=approved_ids,
            companies_rejected=rejected_ids,
            recommended_action="proceed",
            reasoning_summary=(
                f"Rule-based validation only (LLM unavailable). "
                f"{len(approved_ids)} approved, {len(rejected_ids)} rejected."
            ),
        )

    def _validate_output(self, output: CriticOutput) -> list[str]:
        issues: list[str] = []
        if output.approved and output.overall_quality < 0.3:
            issues.append("Approved but quality < 0.3 — contradictory.")
        return issues
