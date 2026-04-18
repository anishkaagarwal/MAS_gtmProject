"""
LLM-Powered Data Source — uses Gemini to retrieve real company data.

Instead of querying a static mock pool, this asks the LLM to provide
real companies matching the given filters. The LLM has broad knowledge
of real companies, funding rounds, employee counts, etc.

Trade-off: data may be slightly outdated (LLM training cutoff) but
covers the entire global market without needing paid API subscriptions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.models.schemas import CompanyRecord, RetrievalFilter

logger = logging.getLogger(__name__)

SEARCH_SYSTEM_PROMPT = """\
You are a company research database. Given search filters, return REAL companies
that match. Use your knowledge of actual companies — do NOT invent fictional ones.

Return a JSON array of companies. Each entry:
{
  "name": "Actual Company Name",
  "domain": "company.com",
  "industry": "ai|saas|fintech|cybersecurity|healthtech|biotech|devtools|etc",
  "geography": "us|uk|eu|india|etc",
  "employee_count": 150,
  "funding_stage": "seed|series_a|series_b|series_c|series_d|ipo|bootstrapped",
  "funding_total_usd": 25000000,
  "founded_year": 2020,
  "description": "One sentence about what they do."
}

Rules:
- Return 8-15 companies that ACTUALLY EXIST.
- Use real company names, real domains, real approximate data.
- If unsure about exact numbers, give your best estimate and round.
- Cover a mix of company sizes and stages within the filter range.
- geography should be lowercase short code (us, uk, eu, india, etc).
- industry should be lowercase.
- Return ONLY the JSON array, no markdown fences, no explanation.
"""


class LLMDataSource:
    """
    Uses the LLM to search for real companies matching filters.
    Replaces mock data with actual company knowledge from the model.
    """

    def __init__(self, llm_client: Any, source_name: str = "llm_search"):
        self.llm = llm_client
        self.source_name = source_name

    async def search(self, filters: RetrievalFilter) -> list[CompanyRecord]:
        user_prompt = self._build_prompt(filters)

        try:
            raw = await self.llm.complete(system=SEARCH_SYSTEM_PROMPT, user=user_prompt)
        except Exception as e:
            logger.error("LLM search failed: %s", e)
            return []

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to repair truncated JSON
            parsed = self._repair_json_array(cleaned)

        if not isinstance(parsed, list):
            logger.warning("LLM search returned non-list: %s", type(parsed))
            return []

        records = []
        for entry in parsed:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            try:
                records.append(CompanyRecord(
                    name=entry["name"],
                    domain=entry.get("domain"),
                    industry=entry.get("industry"),
                    geography=entry.get("geography"),
                    employee_count=entry.get("employee_count"),
                    funding_stage=entry.get("funding_stage"),
                    funding_total_usd=entry.get("funding_total_usd"),
                    founded_year=entry.get("founded_year"),
                    description=entry.get("description"),
                    source=self.source_name,
                ))
            except Exception as e:
                logger.warning("Skipping malformed company entry: %s", e)

        logger.info("LLM search returned %d real companies", len(records))
        return records

    def _build_prompt(self, filters: RetrievalFilter) -> str:
        parts = ["Find real companies matching these criteria:\n"]

        if filters.industry:
            parts.append(f"- Industries: {', '.join(filters.industry)}")
        if filters.geography:
            parts.append(f"- Geography: {', '.join(filters.geography)}")
        if filters.employee_range:
            lo, hi = filters.employee_range
            parts.append(f"- Employee count: {lo} to {hi}")
        if filters.funding_stage:
            parts.append(f"- Funding stages: {', '.join(filters.funding_stage)}")
        if filters.keywords:
            parts.append(f"- Keywords/focus areas: {', '.join(filters.keywords)}")
        if filters.founded_after:
            parts.append(f"- Founded after: {filters.founded_after}")

        parts.append("\nReturn 8-15 REAL companies as a JSON array.")
        return "\n".join(parts)

    @staticmethod
    def _repair_json_array(text: str) -> list:
        """Try to salvage a truncated JSON array."""
        depth_brace = 0
        depth_bracket = 0
        last_complete = -1
        in_string = False
        escape_next = False

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
            if ch == '{':
                depth_brace += 1
            elif ch == '}':
                depth_brace -= 1
                if depth_brace == 0 and depth_bracket == 1:
                    last_complete = i
            elif ch == '[':
                depth_bracket += 1
            elif ch == ']':
                depth_bracket -= 1

        if last_complete > 0:
            try:
                return json.loads(text[:last_complete + 1] + "]")
            except json.JSONDecodeError:
                pass

        return []
