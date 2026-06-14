"""orca_code.tool_chain — Tool chaining and piping (P2-100).

Chains tool outputs as inputs to subsequent tools.
Supports pipe syntax conceptually (the model does the chaining).

Also provides chain_execute() for programmatic multi-step workflows.
"""
from __future__ import annotations
from typing import Any

def chain_execute(steps: list[tuple[str, dict, str | None]]) -> list[dict]:
    """Execute a chain of tool calls where each step can reference prior output.

    Args:
        steps: List of (tool_name, args, output_key) tuples.
               output_key=None means don't capture output for later steps.
               Use "{prev}" in args values to reference the previous step's output.

    Returns:
        List of {tool, args, result, duration_ms} for each step.
    """
    import time
    from orca_code.tool_registry import run_tool
    results = []
    prev_output = ""
    for tool_name, args, output_key in steps:
        resolved_args = {}
        for k, v in args.items():
            if isinstance(v, str) and "{prev}" in v:
                resolved_args[k] = v.replace("{prev}", str(prev_output)[:500])
            else:
                resolved_args[k] = v
        t0 = time.time()
        result = run_tool(tool_name, resolved_args)
        elapsed = (time.time() - t0) * 1000
        results.append({"tool": tool_name, "args": resolved_args,
                        "result": str(result)[:500], "duration_ms": round(elapsed, 1)})
        if output_key:
            prev_output = result
    return results
