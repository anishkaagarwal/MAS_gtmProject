"""Tests for the ICP Scoring Engine — deterministic, no mocks needed."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models.schemas import (
    CompanyRecord,
    CompetitorSignal,
    EnrichedCompany,
    GrowthSignal,
    HiringSignal,
    TechStackSignal,
)
from src.scoring.icp_scorer import ICPScorer, ScoringWeights


def _make_enriched(
    name: str = "TestCo",
    industry: str = "ai",
    geography: str = "us",
    employee_count: int = 100,
    funding_stage: str = "series_a",
    hiring_roles: int = 20,
    hiring_growth: float = 25.0,
    employee_growth_6m: float = 30.0,
    web_traffic: str = "up",
    tech: list = None,
    churn_indicators: list = None,
) -> EnrichedCompany:
    return EnrichedCompany(
        company=CompanyRecord(
            name=name,
            industry=industry,
            geography=geography,
            employee_count=employee_count,
            funding_stage=funding_stage,
        ),
        hiring=HiringSignal(
            open_roles=hiring_roles,
            engineering_roles=int(hiring_roles * 0.5),
            growth_rate_30d=hiring_growth,
            confidence=0.8,
        ),
        growth=GrowthSignal(
            employee_growth_6m=employee_growth_6m,
            web_traffic_trend=web_traffic,
            confidence=0.7,
        ),
        tech_stack=TechStackSignal(
            detected_technologies=tech or ["Python", "React", "AWS"],
            confidence=0.6,
        ),
        competitors=CompetitorSignal(
            churn_indicators=churn_indicators or [],
            confidence=0.5,
        ),
        enrichment_completeness=1.0,
    )


class TestICPScorer:
    def setup_method(self):
        self.scorer = ICPScorer(
            target_industries=["ai", "saas"],
            target_geographies=["us"],
            target_size_range=(50, 300),
            target_funding_stages=["series_a", "series_b"],
            target_tech_stack=["python", "react"],
        )

    def test_perfect_fit_scores_high(self):
        ec = _make_enriched(
            industry="ai",
            geography="us",
            employee_count=150,
            funding_stage="series_a",
        )
        score = self.scorer.score(ec)
        assert score.fit_score >= 0.8, f"Perfect fit should score >= 0.8, got {score.fit_score}"

    def test_wrong_industry_scores_lower_than_match(self):
        wrong = _make_enriched(industry="healthcare", geography="us")
        right = _make_enriched(industry="ai", geography="us")
        wrong_score = self.scorer.score(wrong)
        right_score = self.scorer.score(right)
        assert wrong_score.fit_score < right_score.fit_score, (
            f"Wrong industry ({wrong_score.fit_score}) should score lower than "
            f"matching industry ({right_score.fit_score})"
        )

    def test_wrong_geography_penalizes(self):
        ec = _make_enriched(geography="japan")
        score = self.scorer.score(ec)
        baseline = self.scorer.score(_make_enriched(geography="us"))
        assert score.composite_score < baseline.composite_score

    def test_employee_count_outside_range_penalizes(self):
        small = self.scorer.score(_make_enriched(employee_count=5))
        perfect = self.scorer.score(_make_enriched(employee_count=150))
        large = self.scorer.score(_make_enriched(employee_count=5000))
        assert perfect.fit_score > small.fit_score
        assert perfect.fit_score > large.fit_score

    def test_missing_employee_count_gets_penalty(self):
        ec = _make_enriched()
        ec.company.employee_count = None
        score = self.scorer.score(ec)
        full = self.scorer.score(_make_enriched(employee_count=150))
        assert score.fit_score < full.fit_score, "Missing employee count should penalize"

    def test_high_hiring_velocity_boosts_intent(self):
        high = self.scorer.score(_make_enriched(hiring_growth=50.0))
        low = self.scorer.score(_make_enriched(hiring_growth=2.0))
        assert high.intent_score > low.intent_score

    def test_churn_indicators_boost_intent(self):
        with_churn = self.scorer.score(
            _make_enriched(churn_indicators=["negative review", "migration post", "contract ending"])
        )
        without = self.scorer.score(_make_enriched(churn_indicators=[]))
        assert with_churn.intent_score > without.intent_score

    def test_tech_stack_overlap_boosts_intent(self):
        match = self.scorer.score(_make_enriched(tech=["Python", "React"]))
        no_match = self.scorer.score(_make_enriched(tech=["Java", "Angular"]))
        assert match.intent_score > no_match.intent_score

    def test_high_growth_boosts_growth_score(self):
        growing = self.scorer.score(_make_enriched(employee_growth_6m=50.0, web_traffic="up"))
        shrinking = self.scorer.score(_make_enriched(employee_growth_6m=-5.0, web_traffic="down"))
        assert growing.growth_score > shrinking.growth_score

    def test_composite_is_weighted_sum(self):
        ec = _make_enriched()
        score = self.scorer.score(ec)
        w = self.scorer.w
        expected = w.fit_weight * score.fit_score + w.intent_weight * score.intent_score + w.growth_weight * score.growth_score
        assert abs(score.composite_score - round(expected, 3)) < 0.01

    def test_scores_are_bounded(self):
        ec = _make_enriched()
        score = self.scorer.score(ec)
        for val in [score.fit_score, score.intent_score, score.growth_score, score.composite_score]:
            assert 0.0 <= val <= 1.0, f"Score {val} out of bounds"

    def test_batch_returns_sorted_descending(self):
        companies = [
            _make_enriched(name="Low", hiring_growth=1.0, employee_growth_6m=1.0),
            _make_enriched(name="High", hiring_growth=50.0, employee_growth_6m=60.0),
            _make_enriched(name="Mid", hiring_growth=15.0, employee_growth_6m=20.0),
        ]
        scores = self.scorer.score_batch(companies)
        assert scores[0].composite_score >= scores[1].composite_score >= scores[2].composite_score

    def test_breakdown_contains_all_dimensions(self):
        ec = _make_enriched()
        score = self.scorer.score(ec)
        assert "fit_industry" in score.breakdown
        assert "fit_geography" in score.breakdown
        assert "fit_size" in score.breakdown
        assert "intent_hiring_velocity" in score.breakdown
        assert "intent_competitor_churn" in score.breakdown
        assert "growth_employee_growth" in score.breakdown
        assert "growth_web_traffic" in score.breakdown

    def test_from_plan_factory(self):
        from src.models.schemas import PlannerOutput, Persona
        plan = PlannerOutput(
            entity_type="company",
            tasks=["search"],
            filters={
                "industry": ["fintech"],
                "geography": ["eu"],
                "employee_range": [100, 1000],
            },
            strategy="test",
            target_personas=[Persona.CTO],
            confidence=0.8,
            reasoning_summary="test",
        )
        scorer = ICPScorer.from_plan(plan)
        assert "fintech" in scorer.target_industries
        assert "eu" in scorer.target_geographies
        assert scorer.target_size_range == (100, 1000)
