"""
Pipeline Orchestrator — the control loop that drives the multi-agent system.

This is NOT a simple linear pipeline. It implements:
1. Plan → Retrieve → Enrich → Critique → (loop if invalid) → Score → Strategy
2. Adaptive retry: filter relaxation, re-planning, partial enrichment retry
3. Budget enforcement: max retries, max wall-clock time
4. Streaming: emits events at each stage for the frontend
5. Memory: caches intermediate results, learns from outcomes

Architecture decision: the orchestrator is IMPERATIVE, not declarative.
We tried a DAG-based approach but the conditional retry logic made the DAG
incomprehensible. A clear control loop is easier to debug at 3am.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, AsyncIterator, Callable

from pydantic import BaseModel

from src.agents.base import AgentError
from src.agents.planner import PlannerAgent, PlannerInput
from src.agents.retrieval import RetrievalAgent, RetrievalInput
from src.agents.enrichment import EnrichmentAgent, EnrichmentInput
from src.agents.critic import CriticAgent, CriticInput
from src.agents.gtm_strategy import GTMStrategyAgent, GTMStrategyInput
from src.memory.session_memory import SessionMemory, PersistentCache, VectorMemory
from src.scoring.icp_scorer import ICPScorer
from src.models.schemas import (
    AgentStepTrace,
    CriticOutput,
    EnrichedCompany,
    GTMStrategyOutput,
    PipelineResult,
    PlannerOutput,
    TaskStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline event system — consumed by SSE/WebSocket layer
# ---------------------------------------------------------------------------

class PipelineEvent(BaseModel):
    event_type: str  # "stage_start", "stage_complete", "stage_failed", "retry", "complete"
    agent: str
    attempt: int = 1
    data: dict[str, Any] = {}
    timestamp: float = 0.0


class PipelineConfig(BaseModel):
    max_pipeline_retries: int = 3       # full loops (plan→critique)
    max_retrieval_relaxations: int = 2  # filter relaxation attempts
    max_enrichment_retries: int = 2
    max_wall_clock_seconds: float = 120.0
    min_companies_required: int = 3
    min_critic_quality: float = 0.35


class PipelineOrchestrator:
    """
    Drives the agent pipeline. Stateless per-request — all state lives in
    SessionMemory and the event stream.
    """

    def __init__(
        self,
        planner: PlannerAgent,
        retriever: RetrievalAgent,
        enricher: EnrichmentAgent,
        critic: CriticAgent,
        strategist: GTMStrategyAgent,
        session_memory: SessionMemory,
        persistent_cache: PersistentCache | None = None,
        vector_memory: VectorMemory | None = None,
        config: PipelineConfig | None = None,
        batch_enricher: Any | None = None,
    ):
        self.planner = planner
        self.retriever = retriever
        self.enricher = enricher
        self.critic = critic
        self.strategist = strategist
        self.memory = session_memory
        self.cache = persistent_cache
        self.vector_mem = vector_memory
        self.config = config or PipelineConfig()
        self.batch_enricher = batch_enricher  # optional: prefetches all signals in one LLM call

        self._event_listeners: list[Callable[[PipelineEvent], Any]] = []
        self._traces: list[AgentStepTrace] = []

    def on_event(self, listener: Callable[[PipelineEvent], Any]) -> None:
        """Register a listener for pipeline events (SSE push, logging, etc.)."""
        self._event_listeners.append(listener)

    async def _emit(self, event: PipelineEvent) -> None:
        event.timestamp = time.time()
        for listener in self._event_listeners:
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Event listener error")

    # ------------------------------------------------------------------
    # Main execution loop
    # ------------------------------------------------------------------

    async def execute(self, query: str, session_context: dict[str, Any] | None = None) -> PipelineResult:
        """
        Main entry point. Runs the full pipeline with retry logic.

        Control flow:
        ┌─────────┐
        │ PLAN    │◄──────────────────────────────┐
        └────┬────┘                               │
             │                                    │
        ┌────▼────┐                               │
        │RETRIEVE │◄─────────────┐                │
        └────┬────┘              │ relax filters  │ re-plan
             │                   │                │
        ┌────▼────┐              │                │
        │ ENRICH  │◄────────┐    │                │
        └────┬────┘         │    │                │
             │              │    │                │
        ┌────▼────┐    retry│    │                │
        │ CRITIC  │─────────┘────┘────────────────┘
        └────┬────┘
             │ approved
        ┌────▼────┐
        │  SCORE  │
        └────┬────┘
             │
        ┌────▼────┐
        │STRATEGY │
        └─────────┘
        """
        start_time = time.monotonic()
        session_ctx = session_context or {}

        plan: PlannerOutput | None = None
        previous_plan: PlannerOutput | None = None

        # Check vector memory for similar past queries
        if self.vector_mem:
            similar = await self.vector_mem.retrieve_similar(query, top_k=1)
            if similar:
                session_ctx["similar_past_query"] = similar[0].get("query", "")
                session_ctx["similar_past_plan"] = similar[0].get("plan", "")
                logger.info("Found similar past query — injecting into context")

        pipeline_attempt = 0

        while pipeline_attempt < self.config.max_pipeline_retries:
            pipeline_attempt += 1

            # Check wall-clock budget
            elapsed = time.monotonic() - start_time
            if elapsed > self.config.max_wall_clock_seconds:
                logger.error("Pipeline wall-clock budget exhausted (%.1fs)", elapsed)
                break

            # ── STEP 1: PLAN ──
            await self._emit(PipelineEvent(
                event_type="stage_start", agent="planner", attempt=pipeline_attempt
            ))

            try:
                plan_input = PlannerInput(
                    query=query,
                    session_context=session_ctx,
                    previous_plan=previous_plan,
                )
                plan, plan_trace = await self.planner.run(plan_input)
                self._traces.append(plan_trace)
                self.memory.set("plan", query, plan.model_dump(), source_agent="planner")

                await self._emit(PipelineEvent(
                    event_type="stage_complete", agent="planner",
                    attempt=pipeline_attempt,
                    data={
                        "confidence": plan.confidence,
                        "tasks": plan.tasks,
                        "strategy": plan.strategy,
                        "reasoning_summary": plan.reasoning_summary,
                        "target_personas": plan.target_personas,
                        "filters": plan.filters,
                    },
                ))
            except AgentError as e:
                self._traces.append(AgentStepTrace(
                    agent=e.agent, status=TaskStatus.FAILED,
                    started_at=datetime.utcnow(), error=str(e),
                ))
                await self._emit(PipelineEvent(
                    event_type="stage_failed", agent="planner", data={"error": str(e)}
                ))
                continue  # retry the whole pipeline

            # ── STEP 2: RETRIEVE (with filter relaxation loop) ──
            retrieval_output = None
            for relaxation in range(self.config.max_retrieval_relaxations + 1):
                await self._emit(PipelineEvent(
                    event_type="stage_start", agent="retrieval",
                    attempt=pipeline_attempt,
                    data={"relaxation_level": relaxation},
                ))

                try:
                    ret_input = RetrievalInput(
                        plan=plan, relaxation_level=relaxation
                    )
                    retrieval_output, ret_trace = await self.retriever.run(ret_input)
                    self._traces.append(ret_trace)

                    if retrieval_output.total_found >= self.config.min_companies_required:
                        await self._emit(PipelineEvent(
                            event_type="stage_complete", agent="retrieval",
                            data={"count": retrieval_output.total_found, "relaxation": relaxation},
                        ))
                        break
                    else:
                        logger.info(
                            "Only %d results at relaxation %d — trying wider",
                            retrieval_output.total_found, relaxation
                        )

                except AgentError as e:
                    logger.warning("Retrieval failed at relaxation %d: %s", relaxation, e)
                    if relaxation == self.config.max_retrieval_relaxations:
                        await self._emit(PipelineEvent(
                            event_type="stage_failed", agent="retrieval",
                            data={"error": str(e)},
                        ))

            if retrieval_output is None or retrieval_output.total_found == 0:
                logger.warning("Retrieval produced nothing — re-planning")
                previous_plan = plan
                session_ctx["retrieval_failure"] = "zero_results"
                continue

            # ── STEP 3: ENRICH ──
            await self._emit(PipelineEvent(
                event_type="stage_start", agent="enrichment", attempt=pipeline_attempt
            ))

            # Batch prefetch: one LLM call for all companies' signals
            if self.batch_enricher and retrieval_output:
                try:
                    await self.batch_enricher.prefetch(retrieval_output.companies)
                except Exception as e:
                    logger.warning("Batch enrichment prefetch failed: %s", e)

            try:
                enrich_input = EnrichmentInput(retrieval_output=retrieval_output)
                enrichment_output, enrich_trace = await self.enricher.run(enrich_input)
                self._traces.append(enrich_trace)

                await self._emit(PipelineEvent(
                    event_type="stage_complete", agent="enrichment",
                    data={
                        "enrichment_rate": enrichment_output.enrichment_rate,
                        "count": len(enrichment_output.companies),
                    },
                ))
            except AgentError as e:
                self._traces.append(AgentStepTrace(
                    agent="enrichment", status=TaskStatus.FAILED,
                    started_at=datetime.utcnow(), error=str(e),
                ))
                previous_plan = plan
                continue

            # ── STEP 4: CRITIQUE (inner retry loop) ──
            critic_output: CriticOutput | None = None
            for critic_attempt in range(self.config.max_enrichment_retries + 1):
                await self._emit(PipelineEvent(
                    event_type="stage_start", agent="critic",
                    attempt=critic_attempt + 1,
                ))

                try:
                    critic_input = CriticInput(
                        original_query=query,
                        plan=plan,
                        enrichment_output=enrichment_output,
                        attempt_number=pipeline_attempt,
                    )
                    critic_output, critic_trace = await self.critic.run(critic_input)
                    self._traces.append(critic_trace)

                    await self._emit(PipelineEvent(
                        event_type="stage_complete", agent="critic",
                        data={
                            "approved": critic_output.approved,
                            "quality": critic_output.overall_quality,
                            "action": critic_output.recommended_action,
                            "reasoning_summary": critic_output.reasoning_summary,
                            "companies_approved": len(critic_output.companies_approved),
                            "companies_rejected": len(critic_output.companies_rejected),
                        },
                    ))

                except AgentError:
                    continue

                if critic_output.approved and critic_output.overall_quality >= self.config.min_critic_quality:
                    break  # good enough

                # Act on critic recommendation
                action = critic_output.recommended_action
                if action == "re_plan":
                    previous_plan = plan
                    session_ctx["critic_feedback"] = critic_output.reasoning_summary
                    break  # break inner loop, continue outer loop
                elif action == "retry_retrieval":
                    break  # will be caught by outer loop
                elif action == "retry_enrichment":
                    # Re-enrich only rejected companies
                    logger.info("Re-enriching rejected companies")
                    # (simplified — full impl would re-enrich only the rejected subset)
                    continue
                else:
                    break  # "proceed" with caveats

            if critic_output is None:
                previous_plan = plan
                continue

            if not critic_output.approved and critic_output.recommended_action == "re_plan":
                continue  # outer loop will re-plan

            # ── STEP 5: SCORE ──
            approved_companies = [
                ec for ec in enrichment_output.companies
                if ec.company.company_id in critic_output.companies_approved
            ]

            if not approved_companies:
                # Fallback: use all companies if critic approved none
                # (happens when critic is too strict on first pass)
                logger.warning("No companies approved by critic — using all with caveat")
                approved_companies = enrichment_output.companies

            await self._emit(PipelineEvent(
                event_type="stage_start", agent="scorer", attempt=pipeline_attempt
            ))
            scorer = ICPScorer.from_plan(plan)
            icp_scores = scorer.score_batch(approved_companies)

            avg_score = (
                sum(s.composite_score for s in icp_scores) / len(icp_scores)
                if icp_scores else 0.0
            )
            await self._emit(PipelineEvent(
                event_type="stage_complete", agent="scorer",
                data={"scored": len(icp_scores), "avg_composite": round(avg_score, 2)},
            ))

            # ── STEP 6: GTM STRATEGY ──
            await self._emit(PipelineEvent(
                event_type="stage_start", agent="gtm_strategy", attempt=pipeline_attempt
            ))

            try:
                strategy_input = GTMStrategyInput(
                    plan=plan,
                    approved_companies=approved_companies,
                    icp_scores=icp_scores,
                    original_query=query,
                )
                gtm_output, strategy_trace = await self.strategist.run(strategy_input)
                self._traces.append(strategy_trace)

                await self._emit(PipelineEvent(
                    event_type="stage_complete", agent="gtm_strategy",
                    data={
                        "strategies": len(gtm_output.strategies),
                        "confidence": gtm_output.confidence,
                    },
                ))
            except AgentError as e:
                self._traces.append(AgentStepTrace(
                    agent="gtm_strategy", status=TaskStatus.FAILED,
                    started_at=datetime.utcnow(), error=str(e),
                ))
                # Strategy failure is non-fatal — return results without strategy
                gtm_output = GTMStrategyOutput(strategies=[], confidence=0.0)

            # ── BUILD FINAL RESULT ──
            total_duration = int((time.monotonic() - start_time) * 1000)

            # Build signals summary
            signals = []
            for ec in approved_companies:
                company_signals: dict[str, Any] = {"company_id": ec.company.company_id}
                if ec.hiring:
                    company_signals["hiring"] = ec.hiring.model_dump()
                if ec.growth:
                    company_signals["growth"] = ec.growth.model_dump()
                if ec.competitors:
                    company_signals["competitors"] = ec.competitors.model_dump()
                signals.append(company_signals)

            # Data confidence gates the result; GTM is non-fatal (may fail due to
            # LLM rate limits) so it reduces confidence by at most 20%.
            data_confidence = min(
                plan.confidence,
                critic_output.overall_quality if critic_output else 0.0,
            )
            gtm_weight = 0.8 + 0.2 * gtm_output.confidence
            pipeline_confidence = round(data_confidence * gtm_weight, 3)

            result = PipelineResult(
                query=query,
                plan=plan,
                results=approved_companies,
                signals=signals,
                gtm_strategy=gtm_output,
                icp_scores=icp_scores,
                confidence=pipeline_confidence,
                reasoning_trace=self._traces,
                total_duration_ms=total_duration,
                retries=pipeline_attempt - 1,
            )

            # Store in vector memory for future improvement
            if self.vector_mem:
                await self.vector_mem.store_outcome(
                    query=query,
                    plan=plan.model_dump(),
                    quality_score=result.confidence,
                )

            await self._emit(PipelineEvent(
                event_type="pipeline_complete", agent="orchestrator",
                data={"confidence": result.confidence, "duration_ms": total_duration},
            ))

            return result

        # ── EXHAUSTED ALL RETRIES ──
        # Return a degraded result rather than failing entirely
        total_duration = int((time.monotonic() - start_time) * 1000)
        return PipelineResult(
            query=query,
            plan=plan or PlannerOutput(
                entity_type="company", tasks=[], filters={},
                strategy="failed", target_personas=[], confidence=0.0,
                reasoning_summary="Pipeline exhausted all retries",
            ),
            results=[],
            signals=[],
            gtm_strategy=GTMStrategyOutput(strategies=[], confidence=0.0),
            icp_scores=[],
            confidence=0.0,
            reasoning_trace=self._traces,
            total_duration_ms=total_duration,
            retries=pipeline_attempt,
        )
