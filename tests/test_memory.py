"""Tests for the session memory system."""

from __future__ import annotations

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.memory.session_memory import SessionMemory


class TestSessionMemory:
    def setup_method(self):
        self.mem = SessionMemory(default_ttl=2.0)

    def test_set_and_get(self):
        self.mem.set("agent", "plan_v1", {"tasks": ["search"]})
        result = self.mem.get("agent", "plan_v1")
        assert result == {"tasks": ["search"]}

    def test_get_nonexistent_returns_none(self):
        assert self.mem.get("agent", "nonexistent") is None

    def test_ttl_expiration(self):
        self.mem.set("agent", "short_lived", "data", ttl=0.1)
        assert self.mem.get("agent", "short_lived") == "data"
        time.sleep(0.15)
        assert self.mem.get("agent", "short_lived") is None

    def test_overwrite(self):
        self.mem.set("ns", "key", "v1")
        self.mem.set("ns", "key", "v2")
        assert self.mem.get("ns", "key") == "v2"

    def test_invalidate(self):
        self.mem.set("ns", "key", "data")
        self.mem.invalidate("ns", "key")
        assert self.mem.get("ns", "key") is None

    def test_clear(self):
        self.mem.set("ns1", "k1", "v1")
        self.mem.set("ns2", "k2", "v2")
        self.mem.clear()
        assert self.mem.get("ns1", "k1") is None
        assert self.mem.get("ns2", "k2") is None

    def test_stats(self):
        self.mem.set("ns", "k1", "v1")
        self.mem.set("ns", "k2", "v2")
        self.mem.get("ns", "k1")  # 1 hit
        self.mem.get("ns", "k1")  # 2 hits
        stats = self.mem.stats
        assert stats["total_entries"] == 2
        assert stats["active"] == 2
        assert stats["total_hits"] == 2

    def test_different_namespaces_are_isolated(self):
        self.mem.set("ns1", "key", "value1")
        self.mem.set("ns2", "key", "value2")
        assert self.mem.get("ns1", "key") == "value1"
        assert self.mem.get("ns2", "key") == "value2"

    def test_source_agent_tracking(self):
        self.mem.set("ns", "key", "val", source_agent="planner")
        # Source agent is tracked internally but doesn't affect retrieval
        assert self.mem.get("ns", "key") == "val"
