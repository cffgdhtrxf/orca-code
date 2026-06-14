"""orca_code.orchestrator — Multi-agent Coordinator for parallel task execution.

Inspired by Claude Code's Coordinator pattern. The Coordinator manages
multiple SubAgent workers with three execution modes:

  parallel(specs)  — Fan out N workers, barrier await all results
  pipeline(specs)  — Chain workers sequentially, each receives prior context
  judge(task, n)   — Generate N solutions → judge picks the best one

Workers run in isolated subprocesses via ProcessPoolExecutor.
Each worker gets its own tool set, memory scope, and time budget.

Usage:
    from orca_code.orchestrator import Coordinator, WorkerSpec

    coordinator = Coordinator(max_workers=5)
    specs = [
        WorkerSpec(task="Analyze utils.py", tools=["read_file", "search_content"]),
        WorkerSpec(task="Analyze main.py", tools=["read_file", "search_content"]),
    ]
    results = await coordinator.parallel(specs)
    for r in results:
        print(r.summary)
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WorkerSpec:
    """Specification for a worker sub-agent task.

    Attributes:
        task: Natural language description of what the worker should do.
        tools: List of tool names the worker can use. Default: read-only tools.
        system_prompt: Custom system prompt. If empty, uses default.
        context: Optional additional context for the worker.
        worktree: Optional isolated worktree path (git worktree).
        timeout: Max seconds for the worker to complete. Default 300.
        model: Override model name. Empty = use default model.
    """
    task: str
    tools: list[str] | None = None
    system_prompt: str = ""
    context: str = ""
    worktree: Path | None = None
    timeout: float = 300
    model: str = ""

    def __post_init__(self):
        if self.tools is None:
            self.tools = ["read_file", "search_content", "list_files", "search_files"]


@dataclass
class WorkerResult:
    """Structured result from a worker execution.

    Attributes:
        worker_id: Unique worker identifier.
        status: "ok", "error", or "timeout".
        summary: Human-readable summary of findings.
        findings: List of individual findings discovered by the worker.
        changed_files: List of file paths modified by the worker.
        raw_output: Complete raw output from the worker.
        duration_ms: Wall-clock execution time in milliseconds.
    """
    worker_id: str
    status: str  # "ok" | "error" | "timeout"
    summary: str
    findings: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    raw_output: str = ""
    duration_ms: float = 0

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "status": self.status,
            "summary": self.summary,
            "findings": self.findings,
            "changed_files": self.changed_files,
            "duration_ms": self.duration_ms,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Worker Runner (runs in subprocess)
# ═══════════════════════════════════════════════════════════════════════════════

def _run_worker_in_process(spec_dict: dict) -> dict:
    """Execute a single worker task in a subprocess.

    This function is pickled and sent to the ProcessPoolExecutor.
    It MUST be a module-level function (not a method) for pickling.

    Args:
        spec_dict: Serialized WorkerSpec as a dict.

    Returns:
        Serialized WorkerResult as a dict.
    """
    worker_id = spec_dict.get("worker_id", str(uuid.uuid4())[:8])
    task = spec_dict.get("task", "")
    tool_names = spec_dict.get("tools", ["read_file", "search_content", "list_files"])
    system_prompt = spec_dict.get("system_prompt", "")
    timeout_sec = spec_dict.get("timeout", 300)
    model = spec_dict.get("model", "")

    start_time = time.time()
    findings = []
    changed_files = []
    tool_calls_count = 0

    try:
        # Import inside subprocess (fresh interpreter)
        from orca_code.config import MAX_OUTPUT_TOKENS, MODEL, client
        from orca_code.tool_registry import TOOL_MAP

        effective_model = model or MODEL

        # Build messages
        if not system_prompt:
            system_prompt = (
                "You are a focused sub-agent. Complete your task efficiently.\n"
                "Report your findings clearly. When done, output TASK_COMPLETE."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        # Build tool schemas (subset of available tools)
        available_tools = []
        for name in tool_names:
            if name in TOOL_MAP:
                available_tools.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": f"Sub-agent tool: {name}",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    },
                })

        max_turns = 10
        for turn in range(max_turns):
            kwargs = {
                "model": effective_model,
                "messages": messages,
                "tools": available_tools,
                "stream": False,
                "max_tokens": min(MAX_OUTPUT_TOKENS, 2048),
            }

            response = client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            msg = choice.message

            if msg.content:
                answer = msg.content.strip()
                messages.append({"role": "assistant", "content": answer})

                if "TASK_COMPLETE" in answer or turn >= max_turns - 1:
                    findings.append(answer)
                    break

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    if fn_name not in TOOL_MAP:
                        continue
                    try:
                        fn_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        fn_args = {}

                    func = TOOL_MAP[fn_name]
                    try:
                        result = func(**fn_args)
                    except Exception as e:
                        result = f"Tool error: {e}"

                    tool_calls_count += 1

                    # Track file changes
                    if fn_name in ("write_file", "edit_file", "apply_diff"):
                        changed_files.append(fn_args.get("path", "unknown"))

                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": f"call_{tool_calls_count}",
                            "type": "function",
                            "function": {"name": fn_name, "arguments": tc.function.arguments},
                        }],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": f"call_{tool_calls_count}",
                        "content": str(result)[:4000],
                    })

                    if isinstance(result, str) and len(result) > 50:
                        findings.append(f"[{fn_name}] {result[:200]}")

        summary_parts = [f"Worker {worker_id} completed: {task[:100]}"]
        if changed_files:
            summary_parts.append(f"Changed: {', '.join(changed_files[:5])}")
        summary_parts.append(f"Tool calls: {tool_calls_count}")

        return {
            "worker_id": worker_id,
            "status": "ok",
            "summary": "\n".join(summary_parts),
            "findings": findings,
            "changed_files": changed_files,
            "raw_output": "\n".join(findings[-5:]),
            "duration_ms": (time.time() - start_time) * 1000,
        }

    except Exception as e:
        return {
            "worker_id": worker_id,
            "status": "error",
            "summary": f"Worker {worker_id} failed: {e}",
            "findings": [],
            "changed_files": [],
            "raw_output": str(e),
            "duration_ms": (time.time() - start_time) * 1000,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Coordinator
# ═══════════════════════════════════════════════════════════════════════════════

class Coordinator:
    """Manages multiple sub-agent workers for concurrent task execution.

    Three execution modes:
      parallel() — Fan-out N workers, barrier await all
      pipeline() — Chain workers: each receives prior worker's context
      judge()   — N independent solutions → judge picks the best

    Args:
        max_workers: Max concurrent workers. Default 5.
        use_processes: True = ProcessPoolExecutor (isolated), False = ThreadPoolExecutor.
    """

    def __init__(self, max_workers: int = 5, use_processes: bool = True):
        self.max_workers = max_workers
        self.use_processes = use_processes
        self._executor = None

    def _get_executor(self):
        if self._executor is None:
            if self.use_processes:
                self._executor = ProcessPoolExecutor(max_workers=self.max_workers)
            else:
                self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        return self._executor

    # ── Parallel ────────────────────────────────────────────────────────────

    async def parallel(self, specs: list[WorkerSpec]) -> list[WorkerResult]:
        """Fan out N workers concurrently, barrier await all results.

        All workers start simultaneously. Results are returned in the same
        order as the input specs. A worker that throws results in a
        WorkerResult with status="error".

        Args:
            specs: List of WorkerSpec defining each worker's task.

        Returns:
            List of WorkerResult, same length as specs.
        """
        if not specs:
            return []

        loop = asyncio.get_running_loop()
        executor = self._get_executor()

        # Convert specs to dicts for pickling
        spec_dicts = []
        for spec in specs:
            wid = str(uuid.uuid4())[:8]
            spec_dicts.append({
                "worker_id": wid,
                "task": f"{spec.task}\n\n{spec.context}" if spec.context else spec.task,
                "tools": spec.tools,
                "system_prompt": spec.system_prompt,
                "timeout": spec.timeout,
                "model": spec.model,
            })

        # Submit all workers
        futures = [
            loop.run_in_executor(executor, _run_worker_in_process, sd)
            for sd in spec_dicts
        ]

        # Wait for all with timeout
        results = []
        for i, future in enumerate(futures):
            try:
                spec_timeout = specs[i].timeout if i < len(specs) else 300
                result_dict = await asyncio.wait_for(
                    future, timeout=spec_timeout
                )
                results.append(WorkerResult(**result_dict))
            except TimeoutError:
                results.append(WorkerResult(
                    worker_id=spec_dicts[i]["worker_id"],
                    status="timeout",
                    summary=f"Worker timed out after {specs[i].timeout}s",
                ))

        return results

    # ── Pipeline ────────────────────────────────────────────────────────────

    async def pipeline(
        self,
        specs: list[WorkerSpec],
        reducer: Callable[[WorkerResult, WorkerSpec], WorkerSpec] | None = None,
    ) -> list[WorkerResult]:
        """Chain workers sequentially. Each worker receives prior context.

        Worker 1 runs → Worker 2 sees Worker 1's summary → Worker 3 sees both, etc.

        Args:
            specs: List of WorkerSpec defining each stage.
            reducer: Optional function(prev_result, next_spec) → modified_spec.
                     Can inject prior findings into the next task.

        Returns:
            List of WorkerResult, one per stage.
        """
        if not specs:
            return []

        results = []
        context = ""

        for i, spec in enumerate(specs):
            # Inject prior context
            if context and not spec.context:
                spec.context = context
            elif context:
                spec.context = f"{context}\n\n---\n{spec.context}"

            # Apply reducer if provided
            if reducer and results:
                spec = reducer(results[-1], spec)

            # Run this stage (single worker)
            stage_results = await self.parallel([spec])
            result = stage_results[0] if stage_results else WorkerResult(
                worker_id=f"pipe_{i}",
                status="error",
                summary="Pipeline stage produced no result",
            )

            results.append(result)

            # Accumulate context for next stage
            if result.is_ok:
                context = (
                    f"Previous stage ({i+1}/{len(specs)}) result:\n{result.summary}"
                )

        return results

    # ── Judge ───────────────────────────────────────────────────────────────

    async def judge(
        self,
        task: str,
        n_solutions: int = 3,
        judge_prompt: str = "",
        tools: list[str] | None = None,
    ) -> tuple[WorkerResult, list[WorkerResult]]:
        """Generate N independent solutions, then judge which is best.

        Step 1: N workers solve the task from different angles.
        Step 2: 1 judge worker evaluates all solutions and picks the best.

        Args:
            task: The task to solve.
            n_solutions: Number of independent solutions to generate.
            judge_prompt: Custom judging criteria. Default: score 1-10, pick best.
            tools: Tools available to solution workers.

        Returns:
            (verdict: WorkerResult, solutions: List[WorkerResult])
            verdict.summary contains the judge's reasoning and pick.
        """
        if tools is None:
            tools = ["read_file", "search_content", "list_files", "write_file"]

        # Step 1: Generate N solutions in parallel
        solution_specs = [
            WorkerSpec(
                task=f"Solve this task (approach angle {i+1}/{n_solutions}):\n\n{task}",
                tools=tools,
                system_prompt=(
                    "You are a creative problem solver. Approach the task from a unique angle. "
                    "Be thorough. Output your complete solution and reasoning."
                ),
            )
            for i in range(n_solutions)
        ]

        solutions = await self.parallel(solution_specs)

        # Filter out failed solutions
        ok_solutions = [s for s in solutions if s.is_ok]
        if not ok_solutions:
            return WorkerResult(
                worker_id="judge",
                status="error",
                summary="All solution workers failed",
            ), solutions

        # Step 2: Judge evaluates all solutions
        if not judge_prompt:
            judge_prompt = (
                "Evaluate each solution on: correctness, completeness, efficiency, clarity.\n"
                "Score each 1-10. Pick the best solution and explain why.\n"
                "Output: 'BEST: Solution N' followed by your reasoning."
            )

        solutions_text = "\n\n---\n\n".join(
            f"## Solution {i+1}\n{s.summary}\nFindings:\n" +
            "\n".join(f"  - {f}" for f in s.findings[:5])
            for i, s in enumerate(ok_solutions)
        )

        judge_spec = WorkerSpec(
            task=f"{judge_prompt}\n\n{solutions_text}",
            tools=["read_file", "write_file"],
            system_prompt=(
                "You are an expert judge. Evaluate solutions objectively. "
                "Be specific about strengths and weaknesses. Output a clear verdict."
            ),
        )

        judge_results = await self.parallel([judge_spec])
        verdict = judge_results[0] if judge_results else WorkerResult(
            worker_id="judge",
            status="error",
            summary="Judge failed to produce a verdict",
        )

        # Augment verdict with solution references
        verdict.findings = [
            f"Evaluated {len(ok_solutions)}/{len(solutions)} valid solutions",
            f"Solution worker IDs: {[s.worker_id for s in ok_solutions]}",
        ] + verdict.findings

        return verdict, solutions

    # ── Auto Decompose ──────────────────────────────────────────────────────

    async def auto_decompose(
        self,
        task: str,
        max_subtasks: int = 5,
        tools: list[str] | None = None,
    ) -> list[WorkerResult]:
        """Decompose a complex task into sub-tasks, then execute in parallel.

        Uses the LLM to break down the task into independent sub-tasks,
        then runs them concurrently.

        Args:
            task: The complex task to decompose and execute.
            max_subtasks: Maximum number of sub-tasks to create.
            tools: Tools available to each sub-task worker.

        Returns:
            List of WorkerResult from all sub-tasks.
        """
        if tools is None:
            tools = ["read_file", "search_content", "list_files", "write_file"]

        # Step 1: Decompose
        decomposer = WorkerSpec(
            task=(
                f"Decompose the following task into {max_subtasks} or fewer "
                f"independent sub-tasks. Each sub-task should be self-contained "
                f"and not depend on other sub-tasks.\n\n"
                f"Task: {task}\n\n"
                f"Output as JSON array of objects with fields:\n"
                f"  - task: description of the sub-task\n"
                f"  - tools: list of required tool names\n\n"
                f"Output ONLY valid JSON array. No explanation."
            ),
            tools=["read_file", "search_content", "list_files"],
            system_prompt=(
                "You are a task decomposition expert. Break complex tasks into "
                "independent, parallelizable sub-tasks. Output valid JSON only."
            ),
        )

        plan_results = await self.parallel([decomposer])
        plan = plan_results[0] if plan_results else None

        if not plan or not plan.is_ok:
            return [WorkerResult(
                worker_id="decomposer",
                status="error",
                summary=f"Failed to decompose task: {plan.summary if plan else 'no result'}",
            )]

        # Parse sub-tasks from JSON
        try:
            # Extract JSON from the summary (may contain extra text)
            raw = plan.summary
            json_start = raw.find("[")
            json_end = raw.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                subtasks = json.loads(raw[json_start:json_end])
            else:
                return [WorkerResult(
                    worker_id="decomposer",
                    status="error",
                    summary="Decomposer did not output valid JSON array",
                )]
        except json.JSONDecodeError:
            return [WorkerResult(
                worker_id="decomposer",
                status="error",
                summary=f"Failed to parse decomposition JSON: {plan.summary[:200]}",
            )]

        if not isinstance(subtasks, list) or not subtasks:
            return [WorkerResult(
                worker_id="decomposer",
                status="error",
                summary="Decomposer produced empty sub-task list",
            )]

        # Step 2: Execute sub-tasks in parallel
        sub_specs = [
            WorkerSpec(
                task=s.get("task", f"Sub-task {i+1}"),
                tools=s.get("tools", tools),
                system_prompt=(
                    "You are a focused sub-agent. Complete your sub-task efficiently. "
                    "Report your findings clearly."
                ),
            )
            for i, s in enumerate(subtasks[:max_subtasks])
        ]

        results = await self.parallel(sub_specs)
        return results

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def shutdown(self):
        """Shut down the executor, waiting for running workers to finish."""
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None


# ═══════════════════════════════════════════════════════════════════════════════
# Tool-callable functions (for integration with tool_registry)
# ═══════════════════════════════════════════════════════════════════════════════

_coordinator_instance: Coordinator | None = None


def _get_coordinator() -> Coordinator:
    """Get or create the global Coordinator instance."""
    global _coordination_instance
    if _coordination_instance is None:
        from orca_code.config import MAX_WORKERS
        _coordination_instance = Coordinator(max_workers=min(MAX_WORKERS, 5))
    return _coordination_instance


def coordinator_parallel(tasks_json: str, tools: str = "") -> str:
    """Run multiple tasks in parallel across sub-agents.

    Args:
        tasks_json: JSON array of task descriptions, e.g. '["analyze utils.py", "analyze main.py"]'
        tools: Comma-separated tool names. Default: read-only tools.

    Returns:
        Formatted summary of all worker results.
    """
    try:
        tasks = json.loads(tasks_json)
        if not isinstance(tasks, list):
            return "Error: tasks_json must be a JSON array of task strings"
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON — {e}"

    tool_list = [t.strip() for t in tools.split(",") if t.strip()] if tools else None
    specs = [WorkerSpec(task=t, tools=tool_list) for t in tasks[:5]]

    coordinator = _get_coordinator()
    try:
        results = asyncio.run(coordinator.parallel(specs))
    except Exception as e:
        return f"Coordinator parallel error: {e}"

    lines = [f"=== Coordinator Parallel: {len(results)} workers ==="]
    for r in results:
        icon = "✓" if r.is_ok else "✗"
        lines.append(f"\n{icon} Worker {r.worker_id} ({r.status}) — {r.duration_ms:.0f}ms")
        lines.append(f"  {r.summary[:300]}")
        if r.changed_files:
            lines.append(f"  Changed: {', '.join(r.changed_files[:5])}")

    return "\n".join(lines)


def coordinator_pipeline(stages_json: str, tools: str = "") -> str:
    """Run tasks in a sequential pipeline. Each stage receives the prior stage's context.

    Args:
        stages_json: JSON array of stage descriptions.
        tools: Comma-separated tool names.

    Returns:
        Formatted summary of all stage results.
    """
    try:
        stages = json.loads(stages_json)
        if not isinstance(stages, list):
            return "Error: stages_json must be a JSON array"
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON — {e}"

    tool_list = [t.strip() for t in tools.split(",") if t.strip()] if tools else None
    specs = [WorkerSpec(task=s, tools=tool_list) for s in stages[:5]]

    coordinator = _get_coordinator()
    try:
        results = asyncio.run(coordinator.pipeline(specs))
    except Exception as e:
        return f"Coordinator pipeline error: {e}"

    lines = [f"=== Coordinator Pipeline: {len(results)} stages ==="]
    for i, r in enumerate(results):
        icon = "✓" if r.is_ok else "✗"
        lines.append(f"\nStage {i+1}: {icon} {r.status} — {r.duration_ms:.0f}ms")
        lines.append(f"  {r.summary[:300]}")

    return "\n".join(lines)


def coordinator_judge(task: str, n_solutions: int = 3, tools: str = "") -> str:
    """Generate multiple solutions to a task, then judge which is best.

    Args:
        task: The task description.
        n_solutions: Number of independent solutions to generate (1-5, default 3).
        tools: Comma-separated tool names for solution workers.

    Returns:
        Judge's verdict and summary of all solutions.
    """
    n = min(max(1, n_solutions), 5)
    tool_list = [t.strip() for t in tools.split(",") if t.strip()] if tools else None

    coordinator = _get_coordinator()
    try:
        verdict, solutions = asyncio.run(
            coordinator.judge(task, n_solutions=n, tools=tool_list)
        )
    except Exception as e:
        return f"Coordinator judge error: {e}"

    lines = [f"=== Coordinator Judge: {n} solutions → 1 verdict ==="]
    lines.append(f"\n📋 VERDICT:\n{verdict.summary}")

    lines.append(f"\n--- {len(solutions)} Solutions ---")
    for i, s in enumerate(solutions):
        icon = "✓" if s.is_ok else "✗"
        lines.append(f"\nSolution {i+1} ({s.worker_id}): {icon} — {s.duration_ms:.0f}ms")
        lines.append(f"  {s.summary[:200]}")

    return "\n".join(lines)
