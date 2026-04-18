"""
Memory system with three tiers:
1. Session cache (in-process, TTL-based) — avoids repeated LLM/API calls within a pipeline run
2. Persistent cache (Redis) — survives across requests for the same query patterns
3. Vector memory (optional) — semantic retrieval of past plans/strategies for similar queries

Design principle: memory is ADVISORY, not authoritative. Stale cache is better
than no cache, but agents always validate cached data before trusting it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class CacheEntry(BaseModel):
    key: str
    value: Any
    created_at: float
    ttl_seconds: float
    hit_count: int = 0
    source_agent: str = ""

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


class SessionMemory:
    """
    In-process, per-pipeline-run memory.
    Fast. No network calls. Cleared when the pipeline completes.
    """

    def __init__(self, default_ttl: float = 300.0):
        self._store: dict[str, CacheEntry] = {}
        self._default_ttl = default_ttl

    def _make_key(self, namespace: str, identifier: str) -> str:
        raw = f"{namespace}:{identifier}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, namespace: str, identifier: str) -> Any | None:
        key = self._make_key(namespace, identifier)
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            del self._store[key]
            return None
        entry.hit_count += 1
        return entry.value

    def set(
        self,
        namespace: str,
        identifier: str,
        value: Any,
        ttl: float | None = None,
        source_agent: str = "",
    ) -> None:
        key = self._make_key(namespace, identifier)
        self._store[key] = CacheEntry(
            key=key,
            value=value,
            created_at=time.time(),
            ttl_seconds=ttl or self._default_ttl,
            source_agent=source_agent,
        )

    def invalidate(self, namespace: str, identifier: str) -> None:
        key = self._make_key(namespace, identifier)
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    @property
    def stats(self) -> dict[str, int]:
        expired = sum(1 for e in self._store.values() if e.is_expired)
        return {
            "total_entries": len(self._store),
            "expired": expired,
            "active": len(self._store) - expired,
            "total_hits": sum(e.hit_count for e in self._store.values()),
        }


class PersistentCache:
    """
    Redis-backed cache for cross-request deduplication.

    Use cases:
    - Same company queried by different users within a window → skip enrichment
    - Same query pattern → reuse plan (with freshness check)
    """

    def __init__(self, redis_client: Any, prefix: str = "outmate", default_ttl: int = 3600):
        self._redis = redis_client
        self._prefix = prefix
        self._default_ttl = default_ttl

    def _key(self, namespace: str, identifier: str) -> str:
        return f"{self._prefix}:{namespace}:{identifier}"

    async def get(self, namespace: str, identifier: str) -> Any | None:
        key = self._key(namespace, identifier)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(
        self, namespace: str, identifier: str, value: Any, ttl: int | None = None
    ) -> None:
        key = self._key(namespace, identifier)
        await self._redis.setex(
            key, ttl or self._default_ttl, json.dumps(value, default=str)
        )

    async def invalidate(self, namespace: str, identifier: str) -> None:
        key = self._key(namespace, identifier)
        await self._redis.delete(key)


class VectorMemory:
    """
    Semantic memory using vector embeddings.

    Stores past (query → plan → outcome) tuples. When a new query arrives,
    we retrieve similar past plans to warm-start the Planner.

    This is the IMPROVEMENT loop — the system gets better over time.
    """

    def __init__(self, vector_store: Any, embedding_fn: Any):
        """
        vector_store: any object with .upsert(id, vector, metadata) and .query(vector, top_k)
        embedding_fn: async callable that returns a vector from text
        """
        self._store = vector_store
        self._embed = embedding_fn

    async def store_outcome(
        self,
        query: str,
        plan: dict[str, Any],
        quality_score: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a completed pipeline run for future reference."""
        vector = await self._embed(query)
        doc_id = hashlib.sha256(query.encode()).hexdigest()[:16]
        self._store.upsert(
            id=doc_id,
            vector=vector,
            metadata={
                "query": query,
                "plan": json.dumps(plan, default=str),
                "quality_score": quality_score,
                "timestamp": time.time(),
                **(metadata or {}),
            },
        )
        logger.info("Stored outcome for query: %s (quality=%.2f)", query[:80], quality_score)

    async def retrieve_similar(
        self, query: str, top_k: int = 3, min_quality: float = 0.6
    ) -> list[dict[str, Any]]:
        """Retrieve past outcomes for similar queries."""
        vector = await self._embed(query)
        results = self._store.query(vector=vector, top_k=top_k)

        # Filter by quality — don't learn from bad runs
        return [
            r.metadata
            for r in results
            if r.metadata.get("quality_score", 0) >= min_quality
        ]
