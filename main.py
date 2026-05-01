"""
Outmate.ai — Application Entry Point

Wires all components together and starts the server.

Usage:
    # With real LLM (needs OUTMATE_LLM_API_KEY env var):
    python main.py

    # With mock LLM (no API key needed — for development):
    OUTMATE_LLM_PROVIDER=mock python main.py

    # Override port:
    OUTMATE_API_PORT=3001 python main.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import sys

import uvicorn

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import Settings
from src.agents.planner import PlannerAgent
from src.agents.retrieval import RetrievalAgent
from src.agents.enrichment import EnrichmentAgent
from src.agents.critic import CriticAgent
from src.agents.gtm_strategy import GTMStrategyAgent
from src.memory.session_memory import SessionMemory
from src.orchestrator.pipeline import PipelineOrchestrator, PipelineConfig
from src.signals.signal_engine import SignalEngine
from src.tools.data_sources import MockDataSource, MockSecondarySource
from src.tools.signal_providers import create_signal_providers
from src.tools.llm_data_source import LLMDataSource
from src.tools.llm_signal_providers import create_llm_signal_providers
from src.api.server import create_app


# ---------------------------------------------------------------------------
# Mock LLM client — for development without an API key
# ---------------------------------------------------------------------------

class MockLLMClient:
    """
    Returns plausible structured JSON for each agent's prompt.
    Good enough to test the full pipeline without burning API credits.
    """

    async def complete(self, system: str, user: str) -> str:
        # Simulate LLM latency
        await asyncio.sleep(random.uniform(0.3, 1.2))

        # Detect which agent is calling based on system prompt keywords
        system_lower = system.lower()

        if "planner" in system_lower or "execution plan" in system_lower:
            return self._mock_planner_response(user)
        elif "critic" in system_lower or "data quality" in system_lower:
            return self._mock_critic_response(user)
        elif "gtm strategist" in system_lower or "outbound messaging" in system_lower:
            return self._mock_gtm_response(user)
        else:
            return json.dumps({"error": "unknown agent"})

    def _mock_planner_response(self, user: str) -> str:
        user_lower = user.lower()

        # Extract industry hints from query
        industries = []
        if "ai" in user_lower or "artificial intelligence" in user_lower:
            industries.append("ai")
        if "saas" in user_lower:
            industries.append("saas")
        if "fintech" in user_lower or "finance" in user_lower or "payments" in user_lower:
            industries.append("fintech")
        if "cyber" in user_lower or "security" in user_lower:
            industries.append("cybersecurity")
        if not industries:
            industries = ["saas", "ai"]

        # Only add geography if the query explicitly names a region
        geos = []
        if "us " in user_lower or "united states" in user_lower or "america" in user_lower or " us," in user_lower:
            geos.append("us")
        if "uk" in user_lower or "britain" in user_lower:
            geos.append("uk")
        if "europe" in user_lower or "eu" in user_lower:
            geos.append("eu")
        if "india" in user_lower:
            geos.append("india")
        # No default — leave geos empty for global searches

        # Only add employee_range if query explicitly mentions company size
        employee_range = None
        if "50-200" in user_lower or "50 to 200" in user_lower:
            employee_range = [50, 200]
        elif "series a" in user_lower or "early stage" in user_lower or "early-stage" in user_lower:
            employee_range = [10, 150]
        # "hiring aggressively" or "startup" alone does NOT restrict size

        # Extract persona hints
        personas = []
        if "vp sales" in user_lower or "sales" in user_lower:
            personas.append("vp_sales")
        if "cto" in user_lower or "technical" in user_lower or "engineer" in user_lower:
            personas.append("cto")
        if "ceo" in user_lower or "founder" in user_lower:
            personas.append("ceo")
        if "head of growth" in user_lower or "growth" in user_lower:
            personas.append("head_of_growth")
        if not personas:
            personas = ["vp_sales"]

        geo_label = f"in {', '.join(geos)}" if geos else "globally"
        filters: dict = {"industry": industries}
        if geos:
            filters["geography"] = geos
        if employee_range:
            filters["employee_range"] = employee_range

        # Tag hiring-aggressive queries with keywords
        if "hiring" in user_lower or "aggressively" in user_lower or "scaling" in user_lower:
            filters["keywords"] = ["hiring"]

        return json.dumps({
            "entity_type": "company",
            "tasks": ["search", "enrich", "analyze_signals", "score_icp", "generate_outreach"],
            "filters": filters,
            "strategy": f"Target {', '.join(industries)} companies {geo_label} with strong growth signals. Focus on companies showing hiring velocity and recent funding.",
            "target_personas": personas,
            "confidence": round(random.uniform(0.72, 0.92), 2),
            "reasoning_summary": f"Query targets {', '.join(industries)} sector {geo_label}. Extracted {len(industries)} industry filters, {len(personas)} personas. High confidence due to clear query intent.",
        })

    def _extract_json_array(self, text: str, after_marker: str) -> list:
        """Robust JSON array extraction: find the first '[' after a marker string."""
        idx = text.find(after_marker)
        if idx < 0:
            idx = 0
        else:
            idx += len(after_marker)
        # Find the opening bracket
        bracket_start = text.find("[", idx)
        if bracket_start < 0:
            return []
        # Walk to find the matching close bracket
        depth = 0
        for i in range(bracket_start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[bracket_start:i + 1])
                    except json.JSONDecodeError:
                        return []
        return []

    def _mock_critic_response(self, user: str) -> str:
        # Parse company IDs — the companies array appears after "Companies to review"
        companies = self._extract_json_array(user, "Companies to review")
        company_ids = [c.get("id", "") for c in companies if isinstance(c, dict) and c.get("id")]

        if not company_ids:
            # Fallback: try to find any dicts with "id" fields
            companies = self._extract_json_array(user, "")
            company_ids = [c.get("id", "") for c in companies if isinstance(c, dict) and c.get("id")]

        # Approve most, reject a few
        if len(company_ids) > 2:
            approved = company_ids[:-1]
            rejected = company_ids[-1:]
        else:
            approved = company_ids
            rejected = []

        return json.dumps({
            "approved": True,
            "overall_quality": round(random.uniform(0.65, 0.88), 2),
            "issues": [
                {
                    "severity": "warning",
                    "category": "missing_data",
                    "message": "Some companies have sparse enrichment data",
                    "affected_company_ids": rejected,
                    "suggested_action": "accept_with_caveat",
                }
            ] if rejected else [],
            "companies_approved": approved,
            "companies_rejected": rejected,
            "recommended_action": "proceed",
            "reasoning_summary": f"Reviewed {len(company_ids)} companies. {len(approved)} approved with adequate data quality. {len(rejected)} rejected due to sparse enrichment.",
        })

    def _mock_gtm_response(self, user: str) -> str:
        # Parse company contexts — the companies array appears after "Companies ("
        companies = self._extract_json_array(user, "Companies (")
        if not companies:
            # Fallback: try last array in the prompt
            companies = self._extract_json_array(user, "Companies")
        if not companies:
            companies = self._extract_json_array(user, "")

        strategies = []
        for c in companies:
            if not isinstance(c, dict):
                continue
            cid = c.get("company_id", "unknown")
            name = c.get("name", "Company")
            industry = c.get("industry", "tech")
            employees = c.get("employees", "unknown")
            hiring = c.get("hiring", {})
            open_roles = hiring.get("open_roles", "several") if isinstance(hiring, dict) else "several"

            strategies.append({
                "company_id": cid,
                "company_name": name,
                "hooks": [
                    {
                        "persona": "vp_sales",
                        "hook": f"Noticed {name} just posted {open_roles} new roles — when teams scale that fast, the tooling either keeps up or becomes the constraint.",
                        "angle": f"Sales efficiency during hypergrowth at {name}",
                        "reasoning": f"Hiring velocity at {name} ({open_roles} open roles) signals growth pressure. VP Sales feels this directly through pipeline demands.",
                    }
                ],
                "email_snippets": [
                    {
                        "persona": "vp_sales",
                        "subject": f"Re: scaling ops at {name}",
                        "body": f"Hi [Name],\n\nSaw {name} is on a serious hiring push — {open_roles} new roles is no small move. In our experience, the ops tooling becomes the bottleneck before the people do when teams grow this fast.\n\nWe helped a similar {industry} company cut ramp time by 40% during a comparable growth phase. Worth a 15-min look?\n\nBest,\n[Sender]",
                        "personalization_points": [
                            f"{open_roles} open roles",
                            f"{industry} industry",
                            f"{employees} employees",
                        ],
                    }
                ],
                "competitive_positioning": f"Position against legacy tools that can't scale with {name}'s growth trajectory.",
                "recommended_channel": random.choice(["email", "linkedin"]),
            })

        return json.dumps(strategies)

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_orchestrator(settings: Settings) -> PipelineOrchestrator:
    """Assemble all components into a configured orchestrator."""

    # LLM client
    if settings.llm_provider == "mock":
        llm = MockLLMClient()
        logging.info("Using MOCK LLM client (no API key required)")
    elif settings.llm_provider == "google":
        from src.tools.llm_client import GeminiClient
        if not settings.llm_api_key:
            logging.error("OUTMATE_LLM_API_KEY is required for Google Gemini provider")
            raise ValueError("Set OUTMATE_LLM_API_KEY to your Google AI Studio key")
        llm = GeminiClient(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )
        logging.info("Using Google Gemini LLM (%s)", settings.llm_model)
    elif settings.llm_provider == "anthropic":
        from src.tools.llm_client import AnthropicClient
        if not settings.llm_api_key:
            logging.error("OUTMATE_LLM_API_KEY is required for Anthropic provider")
            raise ValueError("Set OUTMATE_LLM_API_KEY to your Anthropic API key")
        llm = AnthropicClient(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )
        logging.info("Using Anthropic Claude LLM (%s)", settings.llm_model)
    elif settings.llm_provider == "groq":
        from src.tools.llm_client import GroqClient
        if not settings.llm_api_key:
            logging.error("OUTMATE_LLM_API_KEY is required for Groq provider")
            raise ValueError("Set OUTMATE_LLM_API_KEY to your Groq API key")
        llm = GroqClient(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )
        logging.info("Using Groq LLM (%s)", settings.llm_model)
    elif settings.llm_provider == "openai":
        from src.tools.llm_client import OpenAIClient
        if not settings.llm_api_key:
            logging.error("OUTMATE_LLM_API_KEY is required for OpenAI provider")
            raise ValueError("Set OUTMATE_LLM_API_KEY to your OpenAI API key")
        llm = OpenAIClient(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )
        logging.info("Using OpenAI LLM (%s)", settings.llm_model)
    else:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider}. Use 'google', 'anthropic', 'groq', 'openai', or 'mock'")

    # Retrieval always uses mock data — fast, deterministic, no LLM tokens wasted
    data_sources = [
        MockDataSource(source_name="primary_db", failure_rate=0.02),
        MockSecondarySource(),
    ]

    # Signal enrichment uses LLM for real providers, mock engine for dev
    batch_enricher = None
    if settings.llm_provider == "mock":
        signal_engine = SignalEngine()
        signal_providers = create_signal_providers(signal_engine)
        logging.info("Using MOCK data sources and MOCK signal providers")
    else:
        signal_providers, batch_enricher = create_llm_signal_providers(llm_client=llm)
        logging.info("Using MOCK retrieval + LLM signal/enrichment providers")

    # Agents
    planner = PlannerAgent(llm_client=llm)
    retriever = RetrievalAgent(data_sources=data_sources)
    enricher = EnrichmentAgent(signal_providers=signal_providers)
    critic = CriticAgent(llm_client=llm)
    strategist = GTMStrategyAgent(llm_client=llm)

    # Memory
    session_memory = SessionMemory(default_ttl=300.0)

    # Pipeline config
    config = PipelineConfig(
        max_pipeline_retries=settings.max_pipeline_retries,
        max_wall_clock_seconds=settings.max_wall_clock_seconds,
        min_companies_required=settings.min_companies_required,
        min_critic_quality=settings.min_critic_quality,
    )

    return PipelineOrchestrator(
        planner=planner,
        retriever=retriever,
        enricher=enricher,
        critic=critic,
        strategist=strategist,
        session_memory=session_memory,
        config=config,
        batch_enricher=batch_enricher,
    )


def main() -> None:
    settings = Settings()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # Suppress noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    key_hint = f"***{settings.llm_api_key[-4:]}" if len(settings.llm_api_key) > 4 else "(NOT SET)"
    logging.info(
        "Config resolved — provider=%s model=%s api_key=%s port=%d",
        settings.llm_provider, settings.llm_model, key_hint, settings.api_port,
    )

    # Build orchestrator at startup so misconfiguration fails immediately
    # (rather than crashing silently on the first request)
    try:
        orchestrator = build_orchestrator(settings)
    except ValueError as exc:
        logging.error("STARTUP CONFIG ERROR: %s", exc)
        logging.error(
            "Required Railway service variables: "
            "OUTMATE_LLM_PROVIDER, OUTMATE_LLM_API_KEY, OUTMATE_LLM_MODEL"
        )
        sys.exit(1)

    app = create_app(orchestrator_factory=lambda: orchestrator)

    logging.info(
        "Starting Multi-Agent GTM Intelligence System on %s:%d (LLM: %s)",
        settings.api_host,
        settings.api_port,
        settings.llm_provider,
    )

    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
