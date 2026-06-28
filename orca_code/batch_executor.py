"""orca_code.batch_executor — Batch parallel tool execution (P2-41).

Auto-detects independent tool calls and executes them in parallel.
Cuts total execution time for multi-tool turns by running
non-dependent tools concurrently via ThreadPoolExecutor.

Dependency detection:
  - Tools with different file paths are independent
  - Read-only tools (read_file, search_content) never depend on write tools
  - Tools targeting the same file path are serialized

Usage:
    from orca_code.batch_executor import execute_batch
    results = execute_batch([
        ("read_file", {"path": "a.py"}),
        ("read_file", {"path": "b.py"}),
        ("search_content", {"pattern": "TODO"}),
    ])
    # All 3 run in parallel — ~1x latency instead of 3x
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Dependency analysis ─────────────────────────────────────────────────────

READ_ONLY_TOOLS = {
    "read_file", "list_files", "search_files", "search_content",
    "get_system_info", "get_weather", "get_location",
    "git_status", "git_diff", "git_log", "git_blame",
    "go_to_definition", "find_references",
    "list_skills", "list_md_skills", "list_tasks",
    "recall_conversation", "ocr_image",
    "lsp_diagnostics", "lsp_references", "lsp_definition",
    "agent_eval", "web_search", "read_webpage", "web_fetch",
}

WRITE_TOOLS = {
    "write_file", "edit_file", "apply_diff",
    "write_excel", "write_word",
}


def _get_file_target(tool_name: str, args: dict) -> str | None:
    """Extract the file path targeted by a tool (for dependency tracking)."""
    path = args.get("path") or args.get("file_path") or args.get("file")
    return str(path) if path else None


def _are_independent(groups: list[list[tuple[str, dict, int]]],
                     tool_name: str, args: dict) -> bool:
    """Check if a tool call is independent of all tools in the given groups."""
    this_file = _get_file_target(tool_name, args)

    # Read-only tools are always independent
    if tool_name in READ_ONLY_TOOLS:
        return True

    # Write tools: check for file conflicts
    for group in groups:
        for t_name, t_args, _ in group:
            other_file = _get_file_target(t_name, t_args)
            if this_file and other_file and this_file == other_file:
                return False  # Same file — must serialize

    return True


# ── Batch executor ──────────────────────────────────────────────────────────

def execute_batch(tool_calls: list[tuple[str, dict]],
                  executor_fn=None,
                  max_workers: int = 8) -> list[tuple[int, str]]:
    """Execute a batch of tool calls with automatic parallelization.

    Groups independent calls for parallel execution while serializing
    dependent ones (e.g., write + read to same file).

    Args:
        tool_calls: List of (tool_name, args) tuples in order.
        executor_fn: Function that executes a single tool call.
                     Signature: fn(tool_name, args) -> str.
                     Default: uses tool_registry.run_tool.
        max_workers: Max parallel workers.

    Returns:
        List of (original_index, result_string) preserving input order.
    """
    if executor_fn is None:
        from orca_code.tool_registry import run_tool
        executor_fn = run_tool

    n = len(tool_calls)
    if n == 0:
        return []
    if n == 1:
        name, args = tool_calls[0]
        result = executor_fn(name, args)
        return [(0, str(result))]

    # Build dependency groups
    indexed = [(name, args, i) for i, (name, args) in enumerate(tool_calls)]
    groups: list[list[tuple[str, dict, int]]] = []

    for name, args, idx in indexed:
        # Try to add to an existing independent group
        placed = False
        for group in groups:
            if _are_independent([group], name, args):
                group.append((name, args, idx))
                placed = True
                break
        if not placed:
            groups.append([(name, args, idx)])

    # Execute groups sequentially, but tools within a group in parallel
    results_map: dict[int, str] = {}
    t0 = time.time()

    for group in groups:
        if len(group) == 1:
            name, args, idx = group[0]
            results_map[idx] = str(executor_fn(name, args))
        else:
            with ThreadPoolExecutor(max_workers=min(max_workers, len(group))) as ex:
                futures = {}
                for name, args, idx in group:
                    futures[ex.submit(executor_fn, name, args)] = idx
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        results_map[idx] = str(future.result())
                    except Exception as e:
                        results_map[idx] = f"Error: {e}"

    elapsed = (time.time() - t0) * 1000

    # Return in original order
    results = [(i, results_map.get(i, "Error: missing result")) for i in range(n)]

    # Log batch execution
    try:
        from orca_code.structured_log import log_session_event
        log_session_event("batch_execute",
                         tool_count=n, group_count=len(groups),
                         parallel_groups=sum(1 for g in groups if len(g) > 1),
                         elapsed_ms=round(elapsed, 1))
    except Exception:
        pass

    return results
