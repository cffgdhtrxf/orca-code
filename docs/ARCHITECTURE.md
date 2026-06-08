# Orca Code Architecture

> v5.1.0 — Desktop AI assistant. 58 tools, multi-provider LLM support.

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
├── main.py                     CLI loop, user input, command dispatch
├── session.py                  Session state + persistence + re-export hub
├── session_messages.py         Message sanitization, compression, token estimation
├── session_prompt.py           System prompt construction
├── session_ui.py               Terminal UI rendering (Rich)
├── session_stream.py           LLM API calling, stream processing, tool execution
├── subagent.py                 Concurrent sub-agent execution
├── lsp.py                      LSP integration (diagnostics, references, definition)
├── utils.py                    Encoding, paths, token counting, cleanup
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
```

## Data Flow

```
User Input (get_user_input)
    │
    ▼
main() loop
    │
    ├─ /command ──────────► handle_config_cmd / handle_profile_cmd / show_help / ...
    │
    └─ message ───────────► session.messages.append(user_msg)
                                │
                                ▼
                           call_model(messages)
                                │
                                ▼
                           OpenAI/DeepSeek API (streaming)
                                │
                                ▼
                           process_stream(stream)
                                │
                                ├─ reasoning_content ► console (dim italic)
                                ├─ content           ► console (Rich Markdown)
                                └─ tool_calls        ► execute_tool_calls()
                                                          │
                                                          ▼
                                                     run_tool(name, args)
                                                          │
                                                          ├─ resolve_permission()
                                                          ├─ TOOL_MAP[name](**args)
                                                          └─ verification_marker()
```

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

## Testing

```
tests/
├── conftest.py              Fixtures (temp_dir, temp_file, mock_config)
├── test_security.py         35 tests: sandbox escape, command injection, config coercion
├── test_tools.py            30 tests: execute, edit, diff, write, read, list
├── test_errors.py           Error classification
├── test_feature_flags.py    Feature flag system
├── test_integration.py      Integration tests
├── test_metrics.py          Metrics collection
├── test_providers.py        Provider adapters
└── test_tasks.py            Task scheduler
```
