"""
Enrichment Agent — augments retrieved companies with signals.

Adds: hiring data, growth indicators, tech stack, competitor intelligence.

Key design decision: enrichment is BEST-EFFORT. Missing fields are flagged,
never fabricated. Each signal carries its own confidence score.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.models.schemas import (
    AgentRole,
    CompanyRecord,
    CompetitorSignal,
    EnrichedCompany,
    EnrichmentOutput,
    GrowthSignal,
    HiringSignal,
    RetrievalOutput,
    TechStackSignal,
)

logger = logging.getLogger(__name__)


class SignalProvider(Protocol):
    """Each enrichment source implements this protocol."""
    async def enrich(self, company: CompanyRecord) -> dict[str, Any]: ...


class EnrichmentInput(BaseModel):
    retrieval_output: RetrievalOutput
    signal_types: list[str] = Field(
        default_factory=lambda: ["hiring", "growth", "tech_stack", "competitors"]
    )


class EnrichmentAgent(BaseAgent[EnrichmentInput, EnrichmentOutput]):
    role = AgentRole.ENRICHMENT
    max_retries = 2  # enrichment is expensive — limit retries
    timeout = 60.0  # multiple external calls per company

    def __init__(self, signal_providers: dict[str, SignalProvider]) -> None:
        """
        signal_providers: {"hiring": HiringProvider(), "growth": GrowthProvider(), ...}
        """
        super().__init__()
        self.providers = signal_providers

    async def _enrich_single(
        self, company: CompanyRecord, signal_types: list[str]
    ) -> EnrichedCompany:
        """Enrich one company. Failures in individual signals don't fail the whole company."""
        hiring = None
        growth = None
        tech = None
        competitors = None
        missing: list[str] = []

        tasks = {}
        for sig_type in signal_types:
            provider = self.providers.get(sig_type)
            if provider:
                tasks[sig_type] = asyncio.create_task(provider.enrich(company))

        for sig_type, task in tasks.items():
            try:
                result = await asyncio.wait_for(task, timeout=15.0)
                if sig_type == "hiring":
                    hiring = HiringSignal(**result)
                elif sig_type == "growth":
                    growth = GrowthSignal(**result)
                elif sig_type == "tech_stack":
                    tech = TechStackSignal(**result)
                elif sig_type == "competitors":
                    competitors = CompetitorSignal(**result)
            except Exception as e:
                missing.append(sig_type)
                logger.warning(
                    "Enrichment failed for %s/%s: %s", company.name, sig_type, e
                )

        # Calculate completeness
        requested = len(signal_types)
        filled = requested - len(missing)
        completeness = filled / max(requested, 1)

        return EnrichedCompany(
            company=company,
            hiring=hiring,
            growth=growth,
            tech_stack=tech,
            competitors=competitors,
            enrichment_completeness=completeness,
            missing_fields=missing,
        )

    async def _execute(self, input_data: EnrichmentInput) -> EnrichmentOutput:
        # Enrich all companies concurrently (bounded to avoid rate limits)
        sem = asyncio.Semaphore(5)  # max 5 concurrent enrichments

        async def bounded_enrich(company: CompanyRecord) -> EnrichedCompany:
            async with sem:
                return await self._enrich_single(company, input_data.signal_types)

        enriched = await asyncio.gather(
            *[bounded_enrich(c) for c in input_data.retrieval_output.companies]
        )

        total_fields = 0
        filled_fields = 0
        for e in enriched:
            total_fields += len(input_data.signal_types)
            filled_fields += len(input_data.signal_types) - len(e.missing_fields)

        enrichment_rate = filled_fields / max(total_fields, 1)

        warnings: list[str] = []
        if enrichment_rate < 0.5:
            warnings.append(
                f"Low enrichment rate ({enrichment_rate:.0%}). "
                "Many signals are missing — results may be thin."
            )

        return EnrichmentOutput(
            companies=list(enriched),
            enrichment_rate=enrichment_rate,
            warnings=warnings,
        )

    def _validate_output(self, output: EnrichmentOutput) -> list[str]:
        issues: list[str] = []
        if not output.companies:
            issues.append("No enriched companies produced.")
        if output.enrichment_rate < 0.2:
            issues.append(
                f"Enrichment rate critically low ({output.enrichment_rate:.0%}). "
                "Almost all signals failed."
            )
        return issues
