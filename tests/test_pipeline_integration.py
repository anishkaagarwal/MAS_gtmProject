"""Integration test — runs the full pipeline end-to-end with mock LLM."""

from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Settings
from main import build_orchestrator
from src.orchestrator.pipeline import PipelineEvent


class TestPipelineIntegration:

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _build(self):
        s = Settings()
        s.llm_provider = "mock"
        return build_orchestrator(s)

    def test_basic_query_produces_results(self):
        async def run():
            o = self._build()
            result = await o.execute("Find AI SaaS companies in the US")
            assert result.confidence > 0, "Confidence should be > 0"
            assert len(result.results) > 0, "Should return at least 1 company"
            assert result.plan.entity_type == "company"
            assert result.total_duration_ms > 0
            return result
        self._run(run())

    def test_strategies_generated_for_results(self):
        async def run():
            o = self._build()
            result = await o.execute("Find AI startups and generate outbound hooks for VP Sales")
            assert len(result.gtm_strategy.strategies) > 0, "Should generate strategies"
            for s in result.gtm_strategy.strategies:
                assert len(s.hooks) > 0, f"Strategy for {s.company_name} has no hooks"
                assert len(s.email_snippets) > 0, f"Strategy for {s.company_name} has no emails"
            return result
        self._run(run())

    def test_icp_scores_computed(self):
        async def run():
            o = self._build()
            result = await o.execute("Find SaaS companies in the US")
            assert len(result.icp_scores) > 0
            for score in result.icp_scores:
                assert 0 <= score.composite_score <= 1
                assert 0 <= score.fit_score <= 1
                assert 0 <= score.intent_score <= 1
                assert 0 <= score.growth_score <= 1
            # Scores should be sorted descending
            composites = [s.composite_score for s in result.icp_scores]
            assert composites == sorted(composites, reverse=True), "ICP scores should be sorted desc"
        self._run(run())

    def test_reasoning_trace_populated(self):
        async def run():
            o = self._build()
            result = await o.execute("Find AI SaaS startups in the US")
            assert len(result.reasoning_trace) >= 3, (
                f"Should trace at least planner, retrieval, enrichment. Got {len(result.reasoning_trace)}"
            )
            agents_traced = [t.agent for t in result.reasoning_trace]
            agent_strs = [str(a).lower() for a in agents_traced]
            assert any("planner" in a for a in agent_strs), f"Planner not in trace: {agent_strs}"
        self._run(run())

    def test_events_emitted(self):
        async def run():
            o = self._build()
            events = []
            o.on_event(lambda e: events.append(e))
            await o.execute("Find AI companies")
            event_types = [e.event_type for e in events]
            assert "stage_start" in event_types
            assert "stage_complete" in event_types
            assert "complete" in event_types
            # Should have events for multiple agents
            agents = set(e.agent for e in events)
            assert len(agents) >= 3, f"Expected events from 3+ agents, got {agents}"
        self._run(run())

    def test_fintech_query_returns_fintech(self):
        async def run():
            o = self._build()
            result = await o.execute("Find fintech startups hiring aggressively")
            # The planner should extract fintech as an industry
            assert "fintech" in result.plan.filters.get("industry", [])
            # Should return at least 1 result (FinLedger is US fintech in mock data)
            assert len(result.results) >= 1, "Should find at least 1 fintech company"
        self._run(run())

    def test_pipeline_result_is_serializable(self):
        """The result must be JSON-serializable for the API layer."""
        import json
        async def run():
            o = self._build()
            result = await o.execute("Find AI companies")
            # This will throw if not serializable
            serialized = result.model_dump_json()
            parsed = json.loads(serialized)
            assert parsed["query"] == "Find AI companies"
            assert "plan" in parsed
            assert "results" in parsed
            assert "gtm_strategy" in parsed
        self._run(run())
