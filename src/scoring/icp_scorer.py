"""
ICP (Ideal Customer Profile) Scoring Engine.

Computes a composite score from three dimensions:
- Fit:    How well does the company match the target profile?
- Intent: How strong are the buying signals?
- Growth: How fast is the company growing?

Scoring is deterministic (no LLM) — rules and weights only.
This makes it auditable, fast, and reproducible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.models.schemas import EnrichedCompany, ICPScore, PlannerOutput

logger = logging.getLogger(__name__)


@dataclass
class ScoringWeights:
    """Tunable weights — these would be loaded from config in production."""
    # Fit dimension weights
    industry_match: float = 0.30
    geography_match: float = 0.15
    size_match: float = 0.25
    funding_match: float = 0.30

    # Intent dimension weights
    hiring_velocity: float = 0.35
    competitor_churn: float = 0.35
    tech_stack_fit: float = 0.30

    # Growth dimension weights
    employee_growth: float = 0.40
    web_traffic: float = 0.30
    funding_recency: float = 0.30

    # Dimension weights for composite
    fit_weight: float = 0.35
    intent_weight: float = 0.40
    growth_weight: float = 0.25


class ICPScorer:

    def __init__(
        self,
        weights: ScoringWeights | None = None,
        target_industries: list[str] | None = None,
        target_geographies: list[str] | None = None,
        target_size_range: tuple[int, int] = (50, 500),
        target_funding_stages: list[str] | None = None,
        target_tech_stack: list[str] | None = None,
    ):
        self.w = weights or ScoringWeights()
        self.target_industries = [i.lower() for i in (target_industries or [])]
        self.target_geographies = [g.lower() for g in (target_geographies or [])]
        self.target_size_range = target_size_range
        self.target_funding = [f.lower() for f in (target_funding_stages or [])]
        self.target_tech = [t.lower() for t in (target_tech_stack or [])]

    @classmethod
    def from_plan(cls, plan: PlannerOutput) -> ICPScorer:
        """Factory: derive scoring parameters from a Planner's output."""
        f = plan.filters
        return cls(
            target_industries=f.get("industry", []),
            target_geographies=f.get("geography", []),
            target_size_range=tuple(f.get("employee_range", [50, 500])),
            target_funding_stages=f.get("funding_stage", []),
            target_tech_stack=f.get("tech_stack", []),
        )

    # --- Fit scoring ---

    def _score_fit(self, ec: EnrichedCompany) -> tuple[float, dict[str, float]]:
        breakdown: dict[str, float] = {}
        c = ec.company

        # Industry match: exact or partial via keyword overlap
        if self.target_industries and c.industry:
            match = 1.0 if c.industry.lower() in self.target_industries else 0.0
            if match == 0.0:
                # Partial: check keyword overlap
                for ti in self.target_industries:
                    if ti in c.industry.lower() or c.industry.lower() in ti:
                        match = 0.6
                        break
        else:
            match = 0.5  # unknown → neutral
        breakdown["industry"] = match

        # Geography match
        if self.target_geographies and c.geography:
            geo_match = 1.0 if c.geography.lower() in self.target_geographies else 0.0
        else:
            geo_match = 0.5
        breakdown["geography"] = geo_match

        # Size match: Gaussian-ish decay from target range
        if c.employee_count is not None:
            lo, hi = self.target_size_range
            if lo <= c.employee_count <= hi:
                size_match = 1.0
            else:
                dist = min(abs(c.employee_count - lo), abs(c.employee_count - hi))
                range_width = max(hi - lo, 1)
                size_match = max(0.0, 1.0 - (dist / range_width))
        else:
            size_match = 0.3  # missing data penalty
        breakdown["size"] = size_match

        # Funding match
        if self.target_funding and c.funding_stage:
            fund_match = 1.0 if c.funding_stage.lower() in self.target_funding else 0.3
        else:
            fund_match = 0.5
        breakdown["funding"] = fund_match

        score = (
            self.w.industry_match * breakdown["industry"]
            + self.w.geography_match * breakdown["geography"]
            + self.w.size_match * breakdown["size"]
            + self.w.funding_match * breakdown["funding"]
        )
        return min(score, 1.0), breakdown

    # --- Intent scoring ---

    def _score_intent(self, ec: EnrichedCompany) -> tuple[float, dict[str, float]]:
        breakdown: dict[str, float] = {}

        # Hiring velocity as intent signal
        if ec.hiring and ec.hiring.growth_rate_30d is not None:
            # >20% growth in job postings = strong signal
            hv = min(ec.hiring.growth_rate_30d / 20.0, 1.0)
        elif ec.hiring and ec.hiring.open_roles is not None:
            hv = min(ec.hiring.open_roles / 30.0, 1.0)
        else:
            hv = 0.2  # no data
        breakdown["hiring_velocity"] = max(0.0, hv)

        # Competitor churn signal
        if ec.competitors and ec.competitors.churn_indicators:
            churn = min(len(ec.competitors.churn_indicators) / 3.0, 1.0)
        else:
            churn = 0.1
        breakdown["competitor_churn"] = churn

        # Tech stack fit
        if ec.tech_stack and self.target_tech:
            detected = {t.lower() for t in ec.tech_stack.detected_technologies}
            overlap = len(detected & set(self.target_tech))
            tech_fit = min(overlap / max(len(self.target_tech), 1), 1.0)
        else:
            tech_fit = 0.3
        breakdown["tech_stack_fit"] = tech_fit

        score = (
            self.w.hiring_velocity * breakdown["hiring_velocity"]
            + self.w.competitor_churn * breakdown["competitor_churn"]
            + self.w.tech_stack_fit * breakdown["tech_stack_fit"]
        )
        return min(score, 1.0), breakdown

    # --- Growth scoring ---

    def _score_growth(self, ec: EnrichedCompany) -> tuple[float, dict[str, float]]:
        breakdown: dict[str, float] = {}

        # Employee growth
        if ec.growth and ec.growth.employee_growth_6m is not None:
            eg = min(ec.growth.employee_growth_6m / 50.0, 1.0)
        else:
            eg = 0.2
        breakdown["employee_growth"] = max(0.0, eg)

        # Web traffic
        traffic_map = {"up": 0.8, "stable": 0.4, "down": 0.1}
        if ec.growth and ec.growth.web_traffic_trend:
            wt = traffic_map.get(ec.growth.web_traffic_trend, 0.3)
        else:
            wt = 0.3
        breakdown["web_traffic"] = wt

        # Funding recency (heuristic: later stage = more recent activity)
        stage_score = {
            "pre_seed": 0.3, "seed": 0.5, "series_a": 0.7,
            "series_b": 0.8, "series_c": 0.9, "series_d": 0.95,
        }
        if ec.company.funding_stage:
            fr = stage_score.get(ec.company.funding_stage.lower(), 0.4)
        else:
            fr = 0.2
        breakdown["funding_recency"] = fr

        score = (
            self.w.employee_growth * breakdown["employee_growth"]
            + self.w.web_traffic * breakdown["web_traffic"]
            + self.w.funding_recency * breakdown["funding_recency"]
        )
        return min(score, 1.0), breakdown

    # --- Composite ---

    def score(self, ec: EnrichedCompany) -> ICPScore:
        fit, fit_bd = self._score_fit(ec)
        intent, intent_bd = self._score_intent(ec)
        growth, growth_bd = self._score_growth(ec)

        composite = (
            self.w.fit_weight * fit
            + self.w.intent_weight * intent
            + self.w.growth_weight * growth
        )

        return ICPScore(
            company_id=ec.company.company_id,
            fit_score=round(fit, 3),
            intent_score=round(intent, 3),
            growth_score=round(growth, 3),
            composite_score=round(composite, 3),
            breakdown={
                **{f"fit_{k}": v for k, v in fit_bd.items()},
                **{f"intent_{k}": v for k, v in intent_bd.items()},
                **{f"growth_{k}": v for k, v in growth_bd.items()},
            },
        )

    def score_batch(self, companies: list[EnrichedCompany]) -> list[ICPScore]:
        scores = [self.score(ec) for ec in companies]
        scores.sort(key=lambda s: s.composite_score, reverse=True)
        return scores
