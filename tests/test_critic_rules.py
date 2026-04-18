"""Tests for the Critic agent's rule-based checks — no LLM needed."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.critic import CriticAgent
from src.models.schemas import (
    CompanyRecord,
    EnrichedCompany,
    HiringSignal,
    GrowthSignal,
)


def _make_enriched(
    name: str = "TestCo",
    employee_count: int = 100,
    funding_stage: str = "series_a",
    funding_total_usd: float = None,
    enrichment_completeness: float = 0.8,
    hiring_confidence: float = 0.7,
    hiring_open_roles: int = None,
    hiring_eng_roles: int = None,
) -> EnrichedCompany:
    hiring = None
    if hiring_open_roles is not None or hiring_confidence is not None:
        hiring = HiringSignal(
            open_roles=hiring_open_roles,
            engineering_roles=hiring_eng_roles,
            confidence=hiring_confidence,
        )

    return EnrichedCompany(
        company=CompanyRecord(
            name=name,
            employee_count=employee_count,
            funding_stage=funding_stage,
            funding_total_usd=funding_total_usd,
        ),
        hiring=hiring,
        enrichment_completeness=enrichment_completeness,
    )


class TestCriticRuleBasedChecks:
    def setup_method(self):
        # We only test _rule_based_checks — no LLM needed
        self.critic = CriticAgent.__new__(CriticAgent)

    def test_contradiction_small_company_large_funding(self):
        """5 employees with Series C is a contradiction."""
        ec = _make_enriched(
            name="TinyButRich",
            employee_count=3,
            funding_stage="series_c",
        )
        issues = self.critic._rule_based_checks([ec])
        categories = [i.category for i in issues]
        assert "contradiction" in categories, f"Expected contradiction, got {categories}"

    def test_no_contradiction_normal_company(self):
        """100 employees with Series A is fine."""
        ec = _make_enriched(employee_count=100, funding_stage="series_a")
        issues = self.critic._rule_based_checks([ec])
        contradictions = [i for i in issues if i.category == "contradiction"]
        assert len(contradictions) == 0

    def test_overconfidence_sparse_but_high_confidence(self):
        """Low enrichment completeness but high hiring confidence = overconfidence."""
        ec = _make_enriched(
            enrichment_completeness=0.2,
            hiring_confidence=0.95,
        )
        issues = self.critic._rule_based_checks([ec])
        categories = [i.category for i in issues]
        assert "overconfidence" in categories, f"Expected overconfidence, got {categories}"

    def test_no_overconfidence_when_well_enriched(self):
        """High completeness with high confidence is fine."""
        ec = _make_enriched(
            enrichment_completeness=0.9,
            hiring_confidence=0.9,
        )
        issues = self.critic._rule_based_checks([ec])
        overconfidence = [i for i in issues if i.category == "overconfidence"]
        assert len(overconfidence) == 0

    def test_hallucination_all_round_numbers(self):
        """All numeric fields being round numbers is suspicious."""
        ec = _make_enriched(
            employee_count=100,
            funding_total_usd=10_000_000,
            hiring_open_roles=20,
            hiring_eng_roles=10,
        )
        issues = self.critic._rule_based_checks([ec])
        categories = [i.category for i in issues]
        assert "hallucination" in categories, f"Expected hallucination flag, got {categories}"

    def test_no_hallucination_mixed_numbers(self):
        """Mix of round and non-round numbers is fine."""
        ec = _make_enriched(
            employee_count=127,
            funding_total_usd=18_500_000,
            hiring_open_roles=23,
            hiring_eng_roles=11,
        )
        issues = self.critic._rule_based_checks([ec])
        hallucinations = [i for i in issues if i.category == "hallucination"]
        assert len(hallucinations) == 0

    def test_sparse_record_flagged(self):
        """Very low enrichment completeness should be flagged."""
        ec = _make_enriched(enrichment_completeness=0.1)
        issues = self.critic._rule_based_checks([ec])
        categories = [i.category for i in issues]
        assert "missing_data" in categories

    def test_multiple_issues_on_same_company(self):
        """A company can have multiple issues."""
        ec = _make_enriched(
            employee_count=3,
            funding_stage="series_d",
            enrichment_completeness=0.1,
        )
        issues = self.critic._rule_based_checks([ec])
        assert len(issues) >= 2, f"Expected multiple issues, got {len(issues)}"

    def test_multiple_companies_checked_independently(self):
        """Issues from one company don't affect another."""
        good = _make_enriched(name="GoodCo", employee_count=150, enrichment_completeness=0.9)
        bad = _make_enriched(name="BadCo", employee_count=2, funding_stage="series_c", enrichment_completeness=0.05)
        issues = self.critic._rule_based_checks([good, bad])
        bad_ids = set()
        for i in issues:
            bad_ids.update(i.affected_company_ids)
        assert good.company.company_id not in bad_ids, "Good company should not be flagged"

    def test_no_issues_for_healthy_company(self):
        """A well-formed company with reasonable data should pass."""
        ec = _make_enriched(
            employee_count=200,
            funding_stage="series_b",
            funding_total_usd=45_000_000,
            enrichment_completeness=0.85,
            hiring_confidence=0.7,
            hiring_open_roles=23,
            hiring_eng_roles=11,
        )
        issues = self.critic._rule_based_checks([ec])
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0, f"Healthy company should have no errors, got {errors}"
