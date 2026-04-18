"""
LLM-Powered Signal Providers — uses Gemini to enrich real companies.

CRITICAL DESIGN: The free Gemini tier only allows 20 requests/day.
A full pipeline needs: Planner(1) + Search(1) + Enrich + Critic(1) + GTM(1) = ~5 calls.
So enrichment must batch ALL companies into ONE call, not 4 calls per company.

We achieve this with a BatchLLMEnricher that pre-fetches all signals for all
companies in a single LLM call, then individual providers just look up the cache.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.models.schemas import CompanyRecord

logger = logging.getLogger(__name__)

BATCH_ENRICHMENT_PROMPT = """\
You are a company intelligence analyst. For each company below, provide enrichment data
based on your real knowledge. Use REAL data where you know it. Where uncertain, estimate.

Return a JSON object keyed by company name, with ALL signal types per company:

{
  "Company Name": {
    "hiring": {
      "open_roles": <int or null>,
      "engineering_roles": <int or null>,
      "sales_roles": <int or null>,
      "growth_rate_30d": <float 0-1 or null>,
      "notable_roles": ["role1", "role2"],
      "source": "llm_knowledge",
      "confidence": <0.0-1.0>
    },
    "growth": {
      "revenue_estimate": "<string or null>",
      "employee_growth_6m": <float or null>,
      "web_traffic_trend": "<up|down|stable>",
      "social_mentions_trend": "<up|down|stable>",
      "confidence": <0.0-1.0>
    },
    "tech_stack": {
      "detected_technologies": ["tech1", "tech2"],
      "infrastructure": ["cloud1"],
      "source": "llm_knowledge",
      "confidence": <0.0-1.0>
    },
    "competitors": {
      "current_tools": ["tool1"],
      "likely_competitors": ["comp1", "comp2"],
      "churn_indicators": ["reason1"],
      "confidence": <0.0-1.0>
    }
  }
}

Return ONLY valid JSON. No markdown fences, no explanation."""


class BatchLLMEnricher:
    """
    Fetches all enrichment signals for all companies in ONE LLM call.
    Individual signal providers then read from this shared cache.
    """

    def __init__(self, llm_client: Any) -> None:
        self.llm = llm_client
        self._cache: dict[str, dict[str, Any]] = {}
        self._fetched = False

    async def prefetch(self, companies: list[CompanyRecord]) -> None:
        """Call this before individual enrich() calls. Resets on new company set."""
        new_names = {c.name for c in companies}
        cached_names = set(self._cache.keys())
        if self._fetched and new_names == cached_names:
            return  # same companies, skip re-fetch
        # Reset for new company set
        self._cache = {}
        self._fetched = False

        company_list = "\n".join(
            f"- {c.name} ({c.domain}) | {c.industry} | {c.geography} | "
            f"{c.employee_count} emp | {c.funding_stage} | ${(c.funding_total_usd or 0)/1e6:.0f}M | "
            f"{c.description or 'N/A'}"
            for c in companies
        )

        user_prompt = (
            f"Provide enrichment data for these {len(companies)} companies:\n\n"
            f"{company_list}\n\n"
            "Return the JSON object with all signals for each company."
        )

        try:
            raw = await self.llm.complete(system=BATCH_ENRICHMENT_PROMPT, user=user_prompt)
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                self._cache = parsed
                logger.info("Batch enrichment loaded signals for %d companies", len(self._cache))
            else:
                logger.warning("Batch enrichment returned non-dict: %s", type(parsed))
        except json.JSONDecodeError:
            # Try to repair truncated JSON
            try:
                repaired = self._repair_json_obj(cleaned)
                self._cache = repaired
                logger.warning("Repaired truncated batch enrichment — got %d companies", len(self._cache))
            except Exception:
                logger.error("Failed to parse batch enrichment response")
        except Exception as e:
            logger.error("Batch enrichment failed: %s", e)

        self._fetched = True

    def get_signal(self, company_name: str, signal_type: str) -> dict[str, Any] | None:
        """Look up a specific signal from the cache."""
        company_data = self._cache.get(company_name)
        if company_data and isinstance(company_data, dict):
            return company_data.get(signal_type)
        return None

    @staticmethod
    def _repair_json_obj(text: str) -> dict:
        """Attempt to repair a truncated JSON object."""
        # Find complete key-value pairs
        depth = 0
        last_complete_value = -1
        in_string = False
        escape_next = False
        top_level_comma = -1

        for i, ch in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in '{[':
                depth += 1
            elif ch in '}]':
                depth -= 1
                if depth == 1 and ch == '}':
                    last_complete_value = i
            elif ch == ',' and depth == 1:
                top_level_comma = i

        # Cut at the last complete top-level value
        cut_point = last_complete_value if last_complete_value > top_level_comma else top_level_comma - 1
        if cut_point > 0:
            repaired = text[:cut_point + 1] + "}"
            return json.loads(repaired)
        raise json.JSONDecodeError("Cannot repair", text, 0)


class CachedSignalProvider:
    """Wraps BatchLLMEnricher as a signal provider for one signal type."""

    def __init__(self, enricher: BatchLLMEnricher, signal_type: str) -> None:
        self._enricher = enricher
        self._signal_type = signal_type

    async def enrich(self, company: CompanyRecord) -> dict[str, Any]:
        result = self._enricher.get_signal(company.name, self._signal_type)
        if result:
            return result
        # Return minimal defaults if not in cache
        return self._defaults()

    def _defaults(self) -> dict[str, Any]:
        if self._signal_type == "hiring":
            return {"open_roles": None, "engineering_roles": None, "sales_roles": None,
                    "growth_rate_30d": None, "notable_roles": [], "source": "llm_knowledge", "confidence": 0.3}
        elif self._signal_type == "growth":
            return {"revenue_estimate": None, "employee_growth_6m": None,
                    "web_traffic_trend": None, "social_mentions_trend": None, "confidence": 0.3}
        elif self._signal_type == "tech_stack":
            return {"detected_technologies": [], "infrastructure": [],
                    "source": "llm_knowledge", "confidence": 0.3}
        elif self._signal_type == "competitors":
            return {"current_tools": [], "likely_competitors": [],
                    "churn_indicators": [], "confidence": 0.3}
        return {"confidence": 0.3}


def create_llm_signal_providers(llm_client: Any) -> tuple[dict[str, Any], BatchLLMEnricher]:
    """
    Factory — returns LLM-powered providers and the batch enricher.
    The caller MUST call enricher.prefetch(companies) before running enrichment.
    """
    enricher = BatchLLMEnricher(llm_client)
    providers = {
        "hiring": CachedSignalProvider(enricher, "hiring"),
        "growth": CachedSignalProvider(enricher, "growth"),
        "tech_stack": CachedSignalProvider(enricher, "tech_stack"),
        "competitors": CachedSignalProvider(enricher, "competitors"),
    }
    return providers, enricher
