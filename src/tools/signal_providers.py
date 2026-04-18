"""
Signal Providers — adapters that bridge SignalEngine to the EnrichmentAgent's
SignalProvider protocol.

Each provider wraps a SignalEngine method and implements:
    async def enrich(company: CompanyRecord) -> dict[str, Any]
"""

from __future__ import annotations

from typing import Any

from src.models.schemas import CompanyRecord
from src.signals.signal_engine import SignalEngine


class HiringSignalProvider:
    def __init__(self, engine: SignalEngine) -> None:
        self._engine = engine

    async def enrich(self, company: CompanyRecord) -> dict[str, Any]:
        return await self._engine.extract_hiring(company)


class GrowthSignalProvider:
    def __init__(self, engine: SignalEngine) -> None:
        self._engine = engine

    async def enrich(self, company: CompanyRecord) -> dict[str, Any]:
        return await self._engine.extract_growth(company)


class TechStackSignalProvider:
    def __init__(self, engine: SignalEngine) -> None:
        self._engine = engine

    async def enrich(self, company: CompanyRecord) -> dict[str, Any]:
        return await self._engine.extract_tech_stack(company)


class CompetitorSignalProvider:
    def __init__(self, engine: SignalEngine) -> None:
        self._engine = engine

    async def enrich(self, company: CompanyRecord) -> dict[str, Any]:
        return await self._engine.extract_competitors(company)


def create_signal_providers(engine: SignalEngine | None = None) -> dict[str, Any]:
    """Factory — returns the full provider dict expected by EnrichmentAgent."""
    engine = engine or SignalEngine()
    return {
        "hiring": HiringSignalProvider(engine),
        "growth": GrowthSignalProvider(engine),
        "tech_stack": TechStackSignalProvider(engine),
        "competitors": CompetitorSignalProvider(engine),
    }
