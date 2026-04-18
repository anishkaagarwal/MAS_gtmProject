"""
Signal Engine — infers buying signals from noisy, incomplete data.

Signal types:
- Hiring:    job posting velocity, role types, seniority patterns
- Growth:    employee count trends, web traffic, social mentions
- Tech stack: detected technologies from job posts, website, GitHub
- Competitor churn: tool reviews, job posts mentioning competitor migrations

Design principle: signals are PROBABILISTIC. Every signal carries a confidence
score. Missing data doesn't mean zero — it means unknown (confidence = 0.2).
"""

from __future__ import annotations

import logging
import random
from typing import Any

from src.models.schemas import (
    CompanyRecord,
    CompetitorSignal,
    GrowthSignal,
    HiringSignal,
    TechStackSignal,
)

logger = logging.getLogger(__name__)


class SignalEngine:
    """
    Coordinates signal extraction across sources.
    In production, each method would call real APIs.
    This implementation includes realistic noise simulation.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    # --- Hiring signals ---

    async def extract_hiring(self, company: CompanyRecord) -> dict[str, Any]:
        """
        Sources: LinkedIn Jobs API, Indeed API, company careers page scraper.

        Simulates real-world conditions:
        - Some companies have no public job postings
        - Job counts may be stale (scraped 3 days ago)
        - Role categorization is imperfect
        """
        # Simulate: 20% chance of no data (private company, no public postings)
        if random.random() < 0.2:
            return {
                "open_roles": None,
                "engineering_roles": None,
                "sales_roles": None,
                "growth_rate_30d": None,
                "notable_roles": [],
                "source": "none",
                "confidence": 0.1,
            }

        # Simulate noisy data
        base_roles = random.randint(3, 80)
        eng_fraction = random.uniform(0.2, 0.6)
        sales_fraction = random.uniform(0.1, 0.3)

        # Add noise: ±15% from "true" value
        noise = lambda v: max(0, int(v * random.uniform(0.85, 1.15)))

        notable = []
        if random.random() > 0.5:
            notable.append("VP of Engineering")
        if random.random() > 0.7:
            notable.append("Head of AI/ML")
        if random.random() > 0.6:
            notable.append("Senior Sales Director")

        return {
            "open_roles": noise(base_roles),
            "engineering_roles": noise(base_roles * eng_fraction),
            "sales_roles": noise(base_roles * sales_fraction),
            "growth_rate_30d": round(random.uniform(-10, 40), 1),
            "notable_roles": notable,
            "source": random.choice(["linkedin", "indeed", "careers_page"]),
            "confidence": round(random.uniform(0.5, 0.9), 2),
        }

    # --- Growth signals ---

    async def extract_growth(self, company: CompanyRecord) -> dict[str, Any]:
        """
        Sources: LinkedIn employee count history, SimilarWeb, Crunchbase.

        Simulates:
        - Missing revenue data (very common — most private companies don't disclose)
        - Stale traffic data
        """
        # 30% chance of very sparse data
        if random.random() < 0.3:
            return {
                "revenue_estimate": None,
                "employee_growth_6m": None,
                "web_traffic_trend": random.choice(["up", "down", "stable", None]),
                "social_mentions_trend": None,
                "confidence": 0.2,
            }

        revenue_ranges = [
            "$1M-$5M", "$5M-$10M", "$10M-$25M", "$25M-$50M",
            "$50M-$100M", "$100M-$500M", None,  # None = unknown
        ]

        return {
            "revenue_estimate": random.choice(revenue_ranges),
            "employee_growth_6m": round(random.uniform(-5, 60), 1),
            "web_traffic_trend": random.choice(["up", "down", "stable"]),
            "social_mentions_trend": random.choice(["up", "down", "stable"]),
            "confidence": round(random.uniform(0.4, 0.85), 2),
        }

    # --- Tech stack signals ---

    async def extract_tech_stack(self, company: CompanyRecord) -> dict[str, Any]:
        """
        Sources: BuiltWith, Wappalyzer, GitHub org, job posting NLP.

        Simulates:
        - Partial detection (only web-facing tech is visible)
        - Stale data (tech may have changed since last scan)
        """
        tech_pools = {
            "frontend": ["React", "Vue.js", "Angular", "Next.js", "Svelte"],
            "backend": ["Python", "Node.js", "Go", "Java", "Rust", "Ruby"],
            "infrastructure": ["AWS", "GCP", "Azure", "Kubernetes", "Docker", "Terraform"],
            "data": ["Snowflake", "BigQuery", "PostgreSQL", "MongoDB", "Redis", "Kafka"],
            "ml": ["PyTorch", "TensorFlow", "Hugging Face", "LangChain", "OpenAI API"],
        }

        detected = []
        infra = []
        for category, pool in tech_pools.items():
            # Each category: 60% chance of detecting something
            if random.random() < 0.6:
                n = random.randint(1, min(3, len(pool)))
                picks = random.sample(pool, n)
                if category == "infrastructure":
                    infra.extend(picks)
                else:
                    detected.extend(picks)

        return {
            "detected_technologies": detected,
            "infrastructure": infra,
            "source": random.choice(["builtwith", "wappalyzer", "github", "job_posts"]),
            "confidence": round(random.uniform(0.4, 0.8), 2),
        }

    # --- Competitor signals ---

    async def extract_competitors(self, company: CompanyRecord) -> dict[str, Any]:
        """
        Sources: G2, Capterra reviews, job posting analysis, news articles.

        Simulates:
        - Very noisy data (competitor detection is inherently uncertain)
        - False positives from tangential mentions
        """
        # 40% chance of no useful data
        if random.random() < 0.4:
            return {
                "current_tools": [],
                "likely_competitors": [],
                "churn_indicators": [],
                "confidence": 0.15,
            }

        tool_pools = [
            "Salesforce", "HubSpot", "Outreach", "Apollo", "ZoomInfo",
            "Gong", "Chorus", "Clari", "6sense", "Drift", "Intercom",
        ]
        competitor_pools = [
            "Competitor A (similar space)", "Competitor B (adjacent)",
            "Legacy vendor C", "Open-source alternative D",
        ]
        churn_indicators_pool = [
            "Negative G2 review mentioning migration",
            "Job post seeking replacement tool expertise",
            "News article about vendor dissatisfaction",
            "Contract renewal approaching (inferred)",
        ]

        return {
            "current_tools": random.sample(tool_pools, min(random.randint(1, 4), len(tool_pools))),
            "likely_competitors": random.sample(competitor_pools, random.randint(0, 2)),
            "churn_indicators": random.sample(
                churn_indicators_pool, random.randint(0, 2)
            ) if random.random() > 0.4 else [],
            "confidence": round(random.uniform(0.25, 0.65), 2),
        }
