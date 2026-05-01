"""
Planner Agent — decomposes a natural-language GTM query into a structured plan.

This is the FIRST agent in the pipeline. It decides:
  - What entity types to search for
  - What filters to apply
  - Which personas to target
  - What downstream tasks to execute

It does NOT search for data itself. It produces a plan consumed by Retrieval.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.agents.json_utils import parse_json_object
from src.models.schemas import AgentRole, Persona, PlannerOutput

logger = logging.getLogger(__name__)


class PlannerInput(BaseModel):
    query: str
    session_context: dict[str, Any] = Field(default_factory=dict)
    previous_plan: PlannerOutput | None = None  # set on re-plan


# ---------------------------------------------------------------------------
# Prompt template — kept here, NOT in a yaml file nobody reads.
# The prompt is code; version it like code.
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """\
You are a GTM intelligence planner. Given a natural-language outbound query,
produce a structured execution plan.

Rules:
1. Extract entity_type: "company", "person", or "both".
2. Identify concrete filters (industry, geography, size, funding stage, keywords).
   IMPORTANT filter rules:
   - Only add geography if the query explicitly names a region/country. Omit it for global queries.
   - "startup" means high hiring velocity, NOT necessarily early-stage funding. Do NOT restrict
     funding_stage to series_a/series_b unless the user explicitly says early-stage.
   - "hiring aggressively" is a signal hint — add keywords: ["hiring"] but do NOT restrict
     funding_stage or employee_range, as aggressive hiring happens across all stages.
3. Decide which tasks to run: subset of [search, enrich, analyze_signals, score_icp, generate_outreach].
4. Identify target personas from: ceo, vp_sales, cto, vp_engineering, head_of_growth.
5. If the query is ambiguous, set confidence < 0.6 and note what is unclear in reasoning_summary.
6. If a previous_plan is provided, you are RE-PLANNING after a failed attempt.
   Incorporate the feedback and adjust filters or strategy. Widen filters if previous attempt
   found zero results.

Output ONLY valid JSON matching this schema:
{
  "entity_type": "company",
  "tasks": ["search", "enrich"],
  "filters": { "industry": [...], "geography": [...], ... },
  "strategy": "...",
  "target_personas": ["vp_sales"],
  "confidence": 0.85,
  "reasoning_summary": "..."
}
"""


class PlannerAgent(BaseAgent[PlannerInput, PlannerOutput]):
    role = AgentRole.PLANNER
    max_retries = 3
    timeout = 120.0

    def __init__(self, llm_client: Any) -> None:
        """
        llm_client: any object exposing `async def complete(system, user) -> str`.
        We don't couple to a specific SDK — the orchestrator injects the client.
        """
        super().__init__()
        self.llm = llm_client

    async def _execute(self, input_data: PlannerInput) -> PlannerOutput:
        user_message = f"Query: {input_data.query}"
        if input_data.previous_plan:
            user_message += (
                f"\n\nPrevious plan (FAILED — adjust accordingly):\n"
                f"{input_data.previous_plan.model_dump_json(indent=2)}"
            )
        if input_data.session_context:
            user_message += f"\n\nSession context: {json.dumps(input_data.session_context)}"

        raw = await self.llm.complete(
            system=PLANNER_SYSTEM_PROMPT,
            user=user_message,
        )

        parsed = parse_json_object(raw)

        # Normalize personas to enum values
        personas = [Persona(p) for p in parsed.get("target_personas", ["vp_sales"])]

        return PlannerOutput(
            entity_type=parsed["entity_type"],
            tasks=parsed["tasks"],
            filters=parsed.get("filters", {}),
            strategy=parsed.get("strategy", ""),
            target_personas=personas,
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning_summary=parsed.get("reasoning_summary", ""),
        )

    def _validate_output(self, output: PlannerOutput) -> list[str]:
        issues: list[str] = []
        if not output.tasks:
            issues.append("Plan has no tasks — nothing to execute.")
        if not output.entity_type:
            issues.append("entity_type is empty.")
        if output.confidence < 0.1:
            issues.append(f"Confidence suspiciously low ({output.confidence}).")
        return issues
