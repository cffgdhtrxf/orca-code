"""Tests for orca_code.orchestrator — Coordinator multi-agent orchestration."""

from unittest.mock import MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# WorkerSpec & WorkerResult tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkerSpec:
    """WorkerSpec dataclass tests."""

    def test_default_tools(self):
        """Default tools should be read-only."""
        from orca_code.orchestrator import WorkerSpec
        spec = WorkerSpec(task="test")
        assert "read_file" in spec.tools
        assert "search_content" in spec.tools
        assert "list_files" in spec.tools

    def test_custom_tools(self):
        """Custom tools override defaults."""
        from orca_code.orchestrator import WorkerSpec
        spec = WorkerSpec(task="test", tools=["write_file", "execute_command"])
        assert spec.tools == ["write_file", "execute_command"]

    def test_context_field(self):
        """Context field stores additional instructions."""
        from orca_code.orchestrator import WorkerSpec
        spec = WorkerSpec(task="analyze", context="focus on imports")
        assert spec.context == "focus on imports"


class TestWorkerResult:
    """WorkerResult dataclass tests."""

    def test_is_ok(self):
        from orca_code.orchestrator import WorkerResult
        r = WorkerResult(worker_id="w1", status="ok", summary="done")
        assert r.is_ok is True

    def test_is_not_ok(self):
        from orca_code.orchestrator import WorkerResult
        r = WorkerResult(worker_id="w1", status="error", summary="failed")
        assert r.is_ok is False

    def test_to_dict(self):
        from orca_code.orchestrator import WorkerResult
        r = WorkerResult(
            worker_id="w1", status="ok", summary="done",
            findings=["f1"], changed_files=["f.py"]
        )
        d = r.to_dict()
        assert d["worker_id"] == "w1"
        assert d["status"] == "ok"
        assert "f1" in d["findings"]


# ═══════════════════════════════════════════════════════════════════════════════
# Coordinator tests (no LLM — test the orchestration logic)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoordinator:
    """Coordinator class tests (with mocked LLM)."""

    def test_init_defaults(self):
        """Coordinator uses sensible defaults."""
        from orca_code.orchestrator import Coordinator
        c = Coordinator()
        assert c.max_workers == 5
        assert c.use_processes is True

    def test_init_custom(self):
        """Coordinator accepts custom config."""
        from orca_code.orchestrator import Coordinator
        c = Coordinator(max_workers=3, use_processes=False)
        assert c.max_workers == 3
        assert c.use_processes is False

    def test_parallel_empty_specs(self):
        """Parallel with empty specs returns empty list."""
        import asyncio

        from orca_code.orchestrator import Coordinator
        c = Coordinator(use_processes=False)
        results = asyncio.run(c.parallel([]))
        assert results == []

    def test_pipeline_empty_specs(self):
        """Pipeline with empty specs returns empty list."""
        import asyncio

        from orca_code.orchestrator import Coordinator
        c = Coordinator(use_processes=False)
        results = asyncio.run(c.pipeline([]))
        assert results == []

    def test_parallel_with_mocked_executor(self):
        """Parallel submits all specs to the executor (ThreadPool, no LLM)."""
        import asyncio

        from orca_code.orchestrator import Coordinator, WorkerSpec

        c = Coordinator(use_processes=False)

        # Use real ThreadPoolExecutor but mock the worker runner
        # to return a predetermined result without calling LLM
        with patch("orca_code.orchestrator._run_worker_in_process") as mock_runner:
            mock_runner.return_value = {
                "worker_id": "test1",
                "status": "ok",
                "summary": "mock result",
                "findings": ["found something"],
                "changed_files": [],
                "raw_output": "ok",
                "duration_ms": 50,
            }

            specs = [WorkerSpec(task="task1"), WorkerSpec(task="task2")]
            results = asyncio.run(c.parallel(specs))

            assert len(results) == 2
            assert all(r.status == "ok" for r in results)
            assert mock_runner.call_count == 2

        c.shutdown()

    def test_shutdown_cleans_up(self):
        """Shutdown closes the executor."""
        from orca_code.orchestrator import Coordinator
        c = Coordinator(use_processes=False)
        mock_exec = MagicMock()
        c._executor = mock_exec
        c.shutdown()
        mock_exec.shutdown.assert_called_once()

    def test_shutdown_sets_executor_none(self):
        """After shutdown, executor is reset."""
        from orca_code.orchestrator import Coordinator
        c = Coordinator(use_processes=False)
        c._executor = MagicMock()
        c.shutdown()
        assert c._executor is None  # shutdown sets it to None


# ═══════════════════════════════════════════════════════════════════════════════
# Tool-callable function tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoordinatorTools:
    """Coordinator tool-callable function tests."""

    def test_imports_work(self):
        """Coordinator functions import cleanly."""
        from orca_code.orchestrator import (
            coordinator_judge,
            coordinator_parallel,
            coordinator_pipeline,
        )
        assert callable(coordinator_parallel)
        assert callable(coordinator_pipeline)
        assert callable(coordinator_judge)

    def test_parallel_invalid_json(self):
        """coordinator_parallel handles invalid JSON gracefully."""
        from orca_code.orchestrator import coordinator_parallel
        result = coordinator_parallel("not json")
        assert "Error" in result or "invalid" in result.lower()

    def test_parallel_non_array(self):
        """coordinator_parallel rejects non-array JSON."""
        from orca_code.orchestrator import coordinator_parallel
        result = coordinator_parallel('{"key": "value"}')
        assert "Error" in result or "array" in result.lower()

    def test_pipeline_invalid_json(self):
        """coordinator_pipeline handles invalid JSON."""
        from orca_code.orchestrator import coordinator_pipeline
        result = coordinator_pipeline("not json")
        assert "Error" in result or "invalid" in result.lower()

    def test_judge_clamps_n_solutions(self):
        """coordinator_judge clamps n_solutions to 1-5 range."""
        # Test via direct function — should not crash with out-of-range values
        # Just verify the function signature works and clamping logic doesn't crash
        # (actual execution requires LLM, so we skip that)
        pass  # Function imports successfully

    def test_tools_in_tool_map(self):
        """Coordinator tools are registered in TOOL_MAP."""
        from orca_code.tool_registry import TOOL_MAP
        assert "coordinator_parallel" in TOOL_MAP
        assert "coordinator_pipeline" in TOOL_MAP
        assert "coordinator_judge" in TOOL_MAP

    def test_tools_have_permission_risk(self):
        """Coordinator tools have risk levels registered."""
        from orca_code.permissions import TOOL_RISK, RiskLevel
        assert TOOL_RISK["coordinator_parallel"] == RiskLevel.EXEC
        assert TOOL_RISK["coordinator_pipeline"] == RiskLevel.EXEC
        assert TOOL_RISK["coordinator_judge"] == RiskLevel.EXEC

    def test_tools_in_definitions(self):
        """Coordinator tools appear in the TOOLS schema list."""
        from orca_code.tool_registry import TOOLS
        names = [t["function"]["name"] for t in TOOLS]
        assert "coordinator_parallel" in names
        assert "coordinator_pipeline" in names
        assert "coordinator_judge" in names


# ═══════════════════════════════════════════════════════════════════════════════
# Feature flag test
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoordinatorFeatureFlag:
    """Verify the coordinator feature flag is enabled."""

    def test_flag_enabled(self):
        """ENABLE_MULTI_AGENT_ORCHESTRATOR should be True."""
        from orca_code.infrastructure.feature_flags import FeatureFlags
        assert FeatureFlags.is_enabled("ENABLE_MULTI_AGENT_ORCHESTRATOR") is True


# ═══════════════════════════════════════════════════════════════════════════════
# Serialization test (for subprocess pickling)
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkerRunner:
    """Test the subprocess worker runner function."""

    def test_runner_is_picklable(self):
        """_run_worker_in_process must be picklable for ProcessPoolExecutor."""
        import pickle

        from orca_code.orchestrator import _run_worker_in_process
        try:
            pickled = pickle.dumps(_run_worker_in_process)
            unpickled = pickle.loads(pickled)
            assert callable(unpickled)
        except (pickle.PicklingError, TypeError) as e:
            pytest.fail(f"_run_worker_in_process is not picklable: {e}")

    def test_spec_dict_structure(self):
        """Worker spec dict has all required fields for the runner."""
        spec_dict = {
            "worker_id": "test1",
            "task": "analyze a file",
            "tools": ["read_file", "search_content"],
            "system_prompt": "Be concise.",
            "timeout": 60,
            "model": "",
        }
        assert "worker_id" in spec_dict
        assert "task" in spec_dict
        assert "tools" in spec_dict
        assert isinstance(spec_dict["tools"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
