"""Tests for infrastructure/metrics.py — MetricsCollector and tool timing."""

import time
import pytest
from orca_code.infrastructure.metrics import (
    MetricsCollector, get_metrics_collector, _percentile,
)


class TestPercentile:
    def test_p50(self):
        assert _percentile([1, 2, 3, 4, 5], 50) == 3.0

    def test_p95(self):
        data = list(range(100))
        result = _percentile(data, 95)
        assert 94 <= result <= 95  # Linear interpolation

    def test_p99(self):
        data = list(range(100))
        result = _percentile(data, 99)
        assert 98 <= result <= 99  # Linear interpolation

    def test_empty(self):
        assert _percentile([], 50) == 0.0

    def test_single(self):
        assert _percentile([42.0], 50) == 42.0


class TestMetricsCollector:
    def test_record_and_stats(self):
        c = MetricsCollector()
        c.record_start("read_file", "ev1")
        c.record_result("read_file", "ev1", elapsed_ms=15.0)
        c.record_start("read_file", "ev2")
        c.record_result("read_file", "ev2", elapsed_ms=25.0)

        stats = c.get_tool_stats("read_file")
        assert stats is not None
        assert stats["calls"] == 2
        assert stats["p50_ms"] == 20.0  # median of [15, 25]

    def test_record_error(self):
        c = MetricsCollector()
        c.record_start("execute_command", "ev1")
        c.record_error("execute_command", "ev1", elapsed_ms=100.0)

        stats = c.get_tool_stats("execute_command")
        assert stats["errors"] == 1
        assert stats["calls"] == 1

    def test_get_all_stats_sorted(self):
        c = MetricsCollector()
        c.record_start("tool_a", "a1")
        c.record_result("tool_a", "a1", 10)
        c.record_start("tool_b", "b1")
        c.record_result("tool_b", "b1", 20)
        c.record_start("tool_b", "b2")
        c.record_result("tool_b", "b2", 30)

        all_stats = c.get_all_stats()
        assert len(all_stats) == 2
        assert all_stats[0]["tool"] == "tool_b"  # most calls first

    def test_get_summary(self):
        c = MetricsCollector()
        c.record_start("t1", "e1")
        c.record_result("t1", "e1", 10)
        c.record_start("t2", "e2")
        c.record_error("t2", "e2", 20)

        summary = c.get_summary()
        assert summary["total_calls"] == 2
        assert summary["total_errors"] == 1
        assert summary["error_rate"] == 0.5
        assert summary["unique_tools"] == 2

    def test_top_slowest(self):
        c = MetricsCollector()
        c.record_start("fast", "f1")
        c.record_result("fast", "f1", 1)
        c.record_start("slow", "s1")
        c.record_result("slow", "s1", 1000)

        top = c.get_top_slowest(1)
        assert len(top) == 1
        assert top[0]["tool"] == "slow"

    def test_unknown_tool_stats(self):
        c = MetricsCollector()
        assert c.get_tool_stats("nonexistent") is None

    def test_singleton(self):
        c1 = get_metrics_collector()
        c2 = get_metrics_collector()
        assert c1 is c2
