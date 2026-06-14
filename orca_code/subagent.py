"""orca_code.subagent — Concurrent sub-agent execution.

Inspired by CodeWhale's agent_open/agent_eval pattern.
Sub-agents run with their own message history and limited tool set.
They execute concurrently via ThreadPoolExecutor and return structured summaries.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

# Global sub-agent registry
_subagents: dict[str, SubAgent] = {}
_subagent_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="orca-sub")


class SubAgent:
    """A sub-agent runs a single task with limited tools in its own context.

    Usage:
        agent = SubAgent(
            task="Analyze utils.py for performance issues",
            tools=["read_file", "search_content"],
            system_prompt="You are a code reviewer. Be concise."
        )
        agent.start()  # non-blocking
        # ... parent continues working ...
        result = agent.wait()  # blocks until done
        print(result.summary)
    """

    def __init__(
        self,
        task: str,
        tools: list[str] | None = None,
        system_prompt: str | None = None,
        max_turns: int = 10,
        parent_session=None,
        use_worktree: bool = False,
        worktree_source: str | None = None,
    ):
        self.id = f"sub_{int(time.time() * 1000) % 100000:05d}"
        self.task = task
        self.tool_names = tools or ["read_file", "search_content", "list_files"]
        self.system_prompt = system_prompt or "You are a focused sub-agent. Complete your task efficiently."
        self.max_turns = max_turns
        self.parent_session = parent_session
        self.use_worktree = use_worktree
        self.worktree_source = worktree_source  # path to isolate, None = cwd

        # Results
        self._future: Future | None = None
        self._started = False
        self._done = False
        self._result: SubAgentResult | None = None
        self._error: str | None = None
        self._workspace_path: str | None = None

    @property
    def transcript_handle(self) -> str:
        """Opaque handle for retrieving the full transcript later."""
        return f"sub://{self.id}"

    def start(self) -> SubAgent:
        """Launch the sub-agent in background. Non-blocking."""
        if self._started:
            return self
        self._started = True

        with _subagent_lock:
            _subagents[self.id] = self

        self._future = _executor.submit(self._run)
        return self

    def wait(self, timeout: float | None = None) -> SubAgentResult:
        """Block until the sub-agent completes. Returns result."""
        if not self._future:
            return SubAgentResult(self.id, "error", "Agent was never started")

        try:
            self._result = self._future.result(timeout=timeout)
            self._done = True
            return self._result
        except Exception as e:
            self._done = True
            self._error = str(e)
            return SubAgentResult(self.id, "error", f"Sub-agent failed: {e}")

    def is_done(self) -> bool:
        """Check if sub-agent has completed without blocking."""
        if self._done:
            return True
        if self._future and self._future.done():
            self._done = True
            try:
                self._result = self._future.result(timeout=0)
            except Exception as e:
                self._error = str(e)
                self._result = SubAgentResult(self.id, "error", str(e))
            return True
        return False

    def _run(self) -> SubAgentResult:
        """Internal: execute the sub-agent task synchronously."""
        try:
            from orca_code.config import MAX_OUTPUT_TOKENS, MODEL, _estimate_tokens, client, WORKING_DIR
            from orca_code.session import sanitize_messages, smart_trim_messages
            from orca_code.tool_registry import TOOL_MAP
            from orca_code.tool_registry import run_tool as _parent_run_tool
        except ImportError as e:
            return SubAgentResult(self.id, "error", f"Import error: {e}")

        # ── P2-14: Worktree isolation ──────────────────────────────────────
        _worktree_cleanup = None
        if self.use_worktree:
            import os as _os
            try:
                from pathlib import Path as _Path
                from orca_code.worktree import get_worktree_manager
                source = _Path(self.worktree_source) if self.worktree_source else WORKING_DIR
                mgr = get_worktree_manager()
                _wt_ctx = mgr.create(name=f"agent-{self.id}", source_dir=source)
                _workspace = _wt_ctx.__enter__()
                self._workspace_path = str(_workspace)
                _worktree_cleanup = lambda: _wt_ctx.__exit__(None, None, None)
                _os.chdir(str(_workspace))
            except Exception:
                pass  # Continue without isolation

        # Build messages
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.task},
        ]
        findings = []
        changed_files = []
        tool_calls_count = 0

        for turn in range(self.max_turns):
            try:
                # Get available tools (subset)
                available_tools = [
                    {"type": "function", "function": {
                        "name": name,
                        "description": f"Sub-agent tool: {name}",
                        "parameters": {"type": "object", "properties": {}, "required": []}
                    }}
                    for name in self.tool_names
                ]

                kwargs = {
                    "model": MODEL,
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

                    # Check if task is complete
                    if "TASK_COMPLETE" in answer or turn >= self.max_turns - 1:
                        findings.append(answer)
                        break

                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        fn_name = tc.function.name
                        if fn_name not in self.tool_names:
                            continue
                        try:
                            fn_args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            fn_args = {}

                        func = _parent_run_tool if fn_name not in TOOL_MAP else TOOL_MAP[fn_name]
                        if func is _parent_run_tool:
                            result = f"Tool '{fn_name}' not available to sub-agent"
                        else:
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
                                "id": tc.id or f"call_{tool_calls_count}",
                                "type": "function",
                                "function": {"name": fn_name, "arguments": tc.function.arguments}
                            }]
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id or f"call_{tool_calls_count}",
                            "content": str(result)[:4000]
                        })

                        if isinstance(result, str) and len(result) > 50:
                            findings.append(f"[{fn_name}] {result[:200]}")

            except Exception as e:
                if _worktree_cleanup:
                    try: _worktree_cleanup()
                    except Exception: pass
                return SubAgentResult(self.id, "error", f"API error at turn {turn}: {e}")

        summary = self._build_summary(findings, changed_files, tool_calls_count)
        result = SubAgentResult(self.id, "ok", summary, changed_files, findings, tool_calls_count)
        if _worktree_cleanup:
            try: _worktree_cleanup()
            except Exception: pass
        return result

    def _build_summary(self, findings: list, changed_files: list, tool_calls: int) -> str:
        parts = [f"Sub-agent {self.id} completed: {self.task[:100]}"]
        if findings:
            key_findings = [f for f in findings if len(f) > 20][:3]
            if key_findings:
                parts.append("Key findings:")
                parts.extend(f"  - {f[:150]}" for f in key_findings)
        if changed_files:
            parts.append(f"Changed files: {', '.join(changed_files[:5])}")
        parts.append(f"Tool calls: {tool_calls}")
        return "\n".join(parts)


class SubAgentResult:
    """Structured result from a sub-agent execution."""

    def __init__(self, agent_id: str, status: str, summary: str,
                 changed_files: list[str] | None = None,
                 findings: list[str] | None = None,
                 tool_calls: int = 0):
        self.agent_id = agent_id
        self.status = status  # "ok" or "error"
        self.summary = summary
        self.changed_files = changed_files or []
        self.findings = findings or []
        self.tool_calls = tool_calls

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "summary": self.summary,
            "changed_files": self.changed_files,
            "findings": self.findings,
            "tool_calls": self.tool_calls,
        }

    def __str__(self) -> str:
        return self.summary


# ── Tool-callable functions for the main agent ───────────────────────────────

def agent_open(task: str, tools: str | None = None, context: str = "") -> str:
    """Launch a background sub-agent to investigate a task. Non-blocking.
    Returns a handle you can use with agent_eval to get results later.

    Args:
        task: What the sub-agent should investigate/do.
        tools: Comma-separated tool names, e.g. "read_file,search_content".
               Default: read_file, search_content, list_files.
        context: Optional additional context for the sub-agent.
    """
    tool_list = [t.strip() for t in tools.split(",")] if tools else None
    full_task = task
    if context:
        full_task = f"{task}\n\nAdditional context:\n{context}"

    agent = SubAgent(task=full_task, tools=tool_list)
    agent.start()
    return (
        f"Sub-agent launched: {agent.id}\n"
        f"Handle: {agent.transcript_handle}\n"
        f"Use agent_eval('{agent.transcript_handle}') to check results."
    )


def agent_eval(handle: str, timeout: int = 60) -> str:
    """Check the result of a previously launched sub-agent.
    Blocks until the agent completes or timeout is reached.

    Args:
        handle: The transcript handle from agent_open (format: sub://XXXXX).
        timeout: Max seconds to wait. Default 60.
    """
    agent_id = handle.replace("sub://", "")
    with _subagent_lock:
        agent = _subagents.get(agent_id)

    if not agent:
        return f"Error: no sub-agent found with handle '{handle}'. It may have already been cleaned up."

    if agent.is_done():
        result = agent._result or SubAgentResult(agent_id, "error", agent._error or "Unknown error")
        # Clean up
        with _subagent_lock:
            _subagents.pop(agent_id, None)
        return str(result)

    # Wait for completion
    result = agent.wait(timeout=min(timeout, 60))
    with _subagent_lock:
        _subagents.pop(agent_id, None)
    return str(result)


def agent_close(handle: str) -> str:
    """Terminate a running sub-agent and clean up."""
    agent_id = handle.replace("sub://", "")
    with _subagent_lock:
        agent = _subagents.pop(agent_id, None)

    if not agent:
        return f"No active sub-agent found with handle '{handle}'."
    return f"Sub-agent {agent_id} terminated."
