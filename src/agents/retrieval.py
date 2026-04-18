"""
Retrieval Agent — converts a plan's filters into API calls and returns company records.

Handles:
- Over-constrained queries (progressively relaxes filters)
- Empty results (widens search)
- Source deduplication
- Partial/missing data (flags it, doesn't fabricate)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.models.schemas import (
    AgentRole,
    CompanyRecord,
    PlannerOutput,
    RetrievalFilter,
    RetrievalOutput,
)

logger = logging.getLogger(__name__)


class RetrievalInput(BaseModel):
    plan: PlannerOutput
    relaxation_level: int = 0  # 0 = strict, 1 = relaxed, 2 = very relaxed
    excluded_company_ids: list[str] = Field(default_factory=list)


class RetrievalAgent(BaseAgent[RetrievalInput, RetrievalOutput]):
    role = AgentRole.RETRIEVAL
    max_retries = 3
    timeout = 90.0  # LLM-powered search can be slow

    def __init__(self, data_sources: list[Any]) -> None:
        """
        data_sources: list of objects implementing DataSourceProtocol:
            async def search(filters: RetrievalFilter) -> list[CompanyRecord]

        In production these are wrappers around:
        - Apollo.io / Clearbit / ZoomInfo APIs
        - Internal company database
        - Web scraping pipelines
        """
        super().__init__()
        self.data_sources = data_sources

    def _build_filters(self, plan: PlannerOutput, relaxation_level: int) -> tuple[RetrievalFilter, list[str]]:
        """
        Build filters from plan. At higher relaxation levels, drop the least
        important constraints. Returns (filter, list_of_relaxed_field_names).
        """
        f = plan.filters
        relaxed: list[str] = []

        base = RetrievalFilter(
            industry=f.get("industry"),
            geography=f.get("geography"),
            employee_range=tuple(f["employee_range"]) if f.get("employee_range") else None,
            funding_stage=f.get("funding_stage"),
            keywords=f.get("keywords"),
            tech_stack=f.get("tech_stack"),
            founded_after=f.get("founded_after"),
        )

        if relaxation_level >= 1:
            # Drop the most restrictive filters first
            if base.employee_range:
                relaxed.append("employee_range")
                base.employee_range = None
            if base.funding_stage:
                relaxed.append("funding_stage")
                base.funding_stage = None

        if relaxation_level >= 2:
            # Keep only industry + geography
            if base.tech_stack:
                relaxed.append("tech_stack")
                base.tech_stack = None
            if base.founded_after:
                relaxed.append("founded_after")
                base.founded_after = None

        return base, relaxed

    async def _execute(self, input_data: RetrievalInput) -> RetrievalOutput:
        filters, relaxed = self._build_filters(
            input_data.plan, input_data.relaxation_level
        )

        all_companies: list[CompanyRecord] = []
        seen_domains: set[str] = set()

        for source in self.data_sources:
            try:
                results = await source.search(filters)
                for company in results:
                    # Deduplicate by domain
                    key = (company.domain or company.name).lower()
                    if key in seen_domains:
                        continue
                    if company.company_id in input_data.excluded_company_ids:
                        continue
                    seen_domains.add(key)
                    all_companies.append(company)
            except Exception as e:
                # One source failing shouldn't kill the whole retrieval
                logger.warning("Data source %s failed: %s", type(source).__name__, e)

        warnings: list[str] = []
        if not all_companies:
            warnings.append(
                f"Zero results at relaxation_level={input_data.relaxation_level}. "
                "Consider relaxing filters or re-planning."
            )
        if relaxed:
            warnings.append(f"Filters relaxed: {relaxed}")
        if len(all_companies) < 3:
            warnings.append(f"Low result count ({len(all_companies)}). Consider widening search.")

        return RetrievalOutput(
            companies=all_companies,
            total_found=len(all_companies),
            filters_applied=filters,
            filters_relaxed=relaxed,
            confidence=min(1.0, len(all_companies) / 10),  # rough heuristic
            warnings=warnings,
        )

    def _validate_output(self, output: RetrievalOutput) -> list[str]:
        issues: list[str] = []
        # 0 results is normal at strict relaxation levels — the orchestrator
        # handles progressive relaxation. Only flag actual data integrity issues.
        names = [c.name.lower() for c in output.companies]
        if len(names) != len(set(names)):
            issues.append("Duplicate company names detected after dedup — possible source bug.")
        return issues
