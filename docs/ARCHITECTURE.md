# Orca Code Architecture

> v5.2.0 — Desktop AI assistant. 58 tools, multi-provider LLM, TUI + CLI.

## Module Map

```
orca_code.py                    Entry point (4 lines)
orca_code/
├── __init__.py                 Lazy-loading package facade
├── config.py                   Configuration globals + lazy client init
├── constitution.py             Five-tier authority hierarchy (system prompt)
├── permissions.py              Three-tier permission system (READ/WRITE/EXEC)
├── security.py                 Layer 0 safety net + skill sandbox
├── tool_registry.py            Centralized TOOLS definitions + TOOL_MAP + dispatch
├── server.py                   FastAPI HTTP/WS server (port 8498) — agent loop, streaming
├── main.py                     CLI loop, user input, command dispatch
├── session.py                  Session state + persistence + re-export hub
├── session_messages.py         Message sanitization, compression, token estimation
├── session_prompt.py           System prompt construction
├── session_ui.py               Terminal UI rendering (Rich)
├── session_stream.py           LLM API calling, stream processing, tool execution
├── subagent.py                 Concurrent sub-agent execution
├── lsp.py                      LSP integration (diagnostics, references, definition)
├── utils.py                    Encoding, paths, token counting, cleanup
├── bridge.py                   Class system ↔ legacy TOOL_MAP bidirectional sync
├── daemon.py                   Background persistent assistant
├── orchestrator.py             Multi-agent coordinator (parallel/pipeline/judge)
├── tools_core.py               Core tools (exec, read, write, edit, list, search)
├── tools_web.py                Web tools (fetch, search, weather, location)
├── tools_office.py             Office tools (Excel, Word, screenshot, OCR)
├── tools_dev.py                Dev tools (git, code nav, vision, Python REPL)
├── tools_skills.py             Skill system + scheduler
├── tools_automation.py         GUI + browser automation
├── tts_mcp.py                  TTS, voice input, MCP protocol
├── cli/
│   ├── __init__.py
│   └── commands.py             CLI command handlers (/config, /profile)
├── core/
│   ├── __init__.py
│   ├── errors.py               Error classification + retry logic
│   └── event_bus.py            Pub-sub event bus for agent communication
├── infrastructure/
│   ├── __init__.py
│   ├── config_loader.py        Pure config loading (JSON, TXT, defaults)
│   ├── platform.py             Platform detection, console init
│   ├── provider_client.py      Provider-aware LLM client factory
│   ├── feature_flags.py        Compile-time feature gating
│   ├── file_logger.py          Structured file logging
│   ├── metrics.py              Usage metrics
│   └── helpers.py              Utility functions (balance, auto-install)
├── providers/
│   ├── __init__.py
│   ├── base.py                 ProviderAdapter ABC + stream event types
│   ├── registry.py             Provider registry (register, autodetect, list)
│   ├── deepseek.py             DeepSeek API adapter (thinking, reasoning_effort)
│   ├── openai_compat.py        OpenAI-compatible adapter
│   ├── anthropic_compat.py     Anthropic-compatible adapter
│   └── local.py                Local model adapter (Ollama, etc.)
└── tools/                      Placeholder for future class-based tools
    └── __init__.py

orca-ts/  (TypeScript Ink+React TUI)
├── src/
│   ├── loader.mjs              ENTRY — NODE_ENV=production, Ink render
│   ├── app.tsx                 Main App — FullscreenLayout (Claude Code pattern)
│   ├── useChat.ts              WebSocket streaming hook
│   ├── client.ts               HTTP/WS client (localhost:8498)
│   └── components/             (future components)
├── package.json                ink 5.2, react 18, ws
└── tsconfig.json
```

## Data Flow

```
TUI (orca-ts/)                 CLI (orca_code/)
    │                               │
    │  WebSocket @ :8498            │  in-process call
    ▼                               ▼
orca_code/server.py (FastAPI)
    │
    ▼
call_model(messages) → OpenAI/DeepSeek API (streaming)
    │
    ▼
process_stream(stream)
    │
    ├─ reasoning_content ► ws.send_json({"type":"reasoning_delta",...})
    ├─ content           ► ws.send_json({"type":"text_delta",...})
    └─ tool_calls        ► ws.send_json({"type":"tool_executing",...})
                              │
                              ▼
                         execute_tool_calls()
                              │
                              ├─ resolve_permission()
                              ├─ TOOL_MAP[name](**args)
                              ├─ ws.send_json({"type":"tool_call",...})
                              ├─ ws.send_json({"type":"tool_result",...})
                              └─ loop: feed results back to model (max 10 turns)
                                  │
                                  ▼
                              ws.send_json({"type":"done",...})
```

### TUI Display Order (chronological)

```
你 › 用户输入
💭 模型思考         ← reasoning_delta → message (before tools)
⚡ tool_name        ← tool_call → message
⚡ tool_name        ← tool_result → message
● 最终回答          ← text_delta → message (after tools)
```

`flushFinalToMessages` in `useChat.ts` splits the assistant response into TWO messages:
1. Reasoning → inserted after user msg, before tool msgs
2. Answer → appended at end, after tool msgs

## Key Design Decisions

### 1. Lazy Import Pattern
`orca_code/__init__.py` uses `__getattr__` to defer imports until first access.
Makes `import orca_code` O(1) instead of O(all modules).

### 2. Constitution Hierarchy (Tier 1-5)
Injected as system prompt prefix. DeepSeek KV cache makes it free after first request.
- Tier 1: Safety (non-negotiable)
- Tier 2: User Intent
- Tier 3: Evidence (tool output is truth)
- Tier 4: Verification (every action leaves evidence)
- Tier 5: Workspace Legacy

### 3. Three-Layer Security
- Layer 0: Always-on safety net (blocks disk destroy, system takeover, fork bombs) — even in YOLO
- Layer 1: Permission system (READ/WRITE/EXEC risk levels × read-only/auto/yolo modes)
- Layer 2: Skill sandbox (AST scan + restricted builtins)

### 4. Provider Adapter Pattern
`StreamRequestInput` → `ProviderAdapter.build_stream_request()` → `ProviderRequest`
Unified across DeepSeek, OpenAI, Anthropic, and local models.

### 5. Message Context Management
`smart_trim_messages()` with 3-tier compression:
- Level 1: LLM summarization of old blocks
- Level 2: Rule-based concatenation (fallback)
- Level 3: Empty (nothing to compress)

## Tool Dispatch Flow

```
TOOLS (schemas) ◄──────────────── tool_registry.py
    │
TOOL_MAP (name → callable) ◄───── tool_registry.py
    │
run_tool(name, args) ◄─────────── tool_registry.py
    │
    ├─ _resolve(name) ──── lazy resolution for main.py functions
    ├─ resolve_permission()
    ├─ func(**valid_args)
    └─ verification_marker()
```

## Rust Native Engine

```
orca_native/
├── Cargo.toml              Rust crate (ripgrep + ignore + pyo3)
├── build_and_install.py    Build + install script
├── src/                    Rust source (search, diff, walk)
├── target/release/         Compiled .pyd (2.5MB)
└── python/orca_native/     Python package + pure Python fallbacks
```

加载: `importlib.util.spec_from_file_location` + `sys.modules` 恢复。
搜索性能: 0.011s (10-100x vs Python 回退).

## Web Dashboard

```
FastAPI at localhost:8498
  /dashboard      Web dashboard (auto-refresh)
  /v1/health      JSON health check
  /v1/tools       JSON tool list
  /v1/sessions    Session CRUD
  /v1/chat/stream WebSocket streaming chat
  /docs           OpenAPI docs (Swagger)
```

## Key Metrics

| Metric | Value |
|--------|-------|
| Tools | 58 (57 class-based + bridge) |
| Tests | 99+ passed |
| Providers | 4 (DeepSeek/OpenAI/Anthropic/Local) |
| TUI framework | Ink 5.2 + React 18 |
| Backend server | FastAPI (port 8498) |
| Circular deps | 0 |
| Wildcard imports | 0 |
| Rust search | 0.011s |

## Testing

```
tests/
├── conftest.py              Fixtures (temp_dir, temp_file, mock_config)
├── test_security.py         35+ tests: sandbox escape, command injection, config coercion
├── test_tools.py            30 tests: execute, edit, diff, write, read, list
├── test_errors.py           Error classification
├── test_feature_flags.py    Feature flag system
├── test_integration.py      Integration tests
├── test_metrics.py          Metrics collection
├── test_providers.py        Provider adapters
└── test_tasks.py            Task scheduler