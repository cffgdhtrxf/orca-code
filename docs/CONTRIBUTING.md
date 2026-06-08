# Contributing to Orca Code

## Development Setup

```powershell
# 1. Create venv
python -m venv .venv
.venv\Scripts\activate

# 2. Install Python deps
pip install -r requirements.txt

# 3. Build Rust native engine (optional, 10-100x search boost)
cd orca_native
pip install maturin
$env:PYTHONUTF8=1; maturin develop --release
cd ..
```

## Running Tests

```bash
# All fast tests
pytest tests/test_errors.py tests/test_feature_flags.py tests/test_providers.py tests/test_tools.py tests/test_security.py

# Specific test file
pytest tests/test_security.py -v

# Full suite (may be slow due to config init)
pytest tests/ -v
```

## Architecture

```
orca_code/                          # 27 modules
├── main.py / session.py            # Main loop + LLM session
├── config.py                       # Lazy config (delegates to config_loader)
├── constitution.py                 # 5-tier authority hierarchy
├── permissions.py / security.py    # Permission + security layers
│
├── core/                           # Core abstractions
│   ├── errors.py                   # Error classification + retry
│   └── event_bus.py                # Pub-sub event bus (23 types)
│
├── providers/                      # Multi-LLM adapters (Proma pattern)
│   ├── base.py                     # ProviderAdapter ABC
│   ├── registry.py                 # Adapter registry + auto-detect
│   ├── deepseek.py                 # DeepSeek (thinking mode)
│   ├── openai_compat.py            # OpenAI compatible
│   ├── anthropic_compat.py         # Anthropic Messages API
│   └── local.py                    # Ollama / LM Studio
│
├── tools/                          # Tool system (Claude Code Tool class)
│   ├── base.py                     # Tool ABC + ToolRegistry
│   ├── bridge.py                   # 63 legacy → new registry + EventBus
│   ├── core.py                     # 8 file/command/search tools
│   ├── web.py                      # 5 web tools
│   ├── dev.py                      # 6 Git/code nav tools
│   ├── office.py                   # 6 office tools
│   ├── automation.py               # 12 GUI/browser tools
│   ├── tasks.py                    # 4 task management tools
│   └── extended.py                 # 14 skills/LSP/subagent/voice
│
├── infrastructure/                 # Infrastructure layer
│   ├── config_loader.py            # Pure config loading (zero side effects)
│   ├── provider_client.py          # Provider-aware client factory
│   ├── feature_flags.py            # Compile-time feature gates
│   ├── platform.py                 # Platform detection + console init
│   ├── metrics.py                  # Tool timing p50/p95/p99
│   └── file_logger.py              # JSONL structured logging
│
└── cli/                            # CLI layer
    ├── commands.py                 # /command handlers
    ├── input_handler.py            # Keyboard/voice/paste input
    └── main_loop.py                # Main event loop

orca_native/                         # Rust native engine (PyO3)
├── Cargo.toml
├── src/search.rs                    # ripgrep code search
├── src/diff.rs                      # unified diff application
└── src/walk.rs                      # .gitignore-aware file walk
```

## Adding a New Tool

### Option A: Tool Class (recommended)

```python
# In orca_code/tools/xxx.py
from orca_code.permissions import RiskLevel
from orca_code.tools.base import Tool

class MyNewTool(Tool):
    name = "my_new_tool"
    description = "What this tool does"
    risk_level = RiskLevel.READ  # READ | WRITE | EXEC
    parameters = {
        "type": "object",
        "properties": {
            "arg1": {"type": "string", "description": "..."},
        },
        "required": ["arg1"],
    }

    def execute(self, arg1: str) -> str:
        # Implementation
        return f"Result: {arg1}"

def register_xxx_tools(registry) -> int:
    tools = [MyNewTool()]
    count = 0
    for t in tools:
        if t.name not in registry:
            registry.register(t)
            count += 1
    return count
```

Then register in `tools/bridge.py` → `init_bridge()`.

### Option B: Legacy Function (for quick additions)

```python
# In orca_code/tools_core.py or similar
def my_new_tool(arg1: str) -> str:
    """What this tool does."""
    return f"Result: {arg1}"

# In main.py TOOL_MAP
"my_new_tool": my_new_tool,
```

Add risk level in `permissions.py` → `TOOL_RISK`.

## Permission System

Every tool must declare a risk level in `permissions.py`:

```python
TOOL_RISK = {
    "my_new_tool": RiskLevel.READ,    # or WRITE, EXEC
}
```

- `READ` — reads data, no mutation
- `WRITE` — mutates files but no arbitrary code execution
- `EXEC` — executes code, shells out, drives GUI/browser

## Provider System

Add a new LLM provider by implementing `ProviderAdapter`:

```python
from orca_code.providers.base import ProviderAdapter, StreamRequestInput, ProviderRequest

class MyProvider(ProviderAdapter):
    provider_type = "my_provider"
    provider_label = "My Provider"

    def build_stream_request(self, input: StreamRequestInput) -> ProviderRequest:
        ...

    def parse_stream_line(self, json_line: str) -> list[StreamEvent]:
        ...
```

Register in `providers/__init__.py` → `_init()`.

## EventBus

Listen to tool events:

```python
from orca_code.core.event_bus import get_event_bus, EventType

bus = get_event_bus()

@bus.on(EventType.TOOL_RESULT)
def on_tool_done(event):
    data = event.data
    print(f"Tool {data['name']} done in {data['elapsed_ms']:.0f}ms")
```

## Code Style

- Python 3.12+ idioms preferred
- `from __future__ import annotations` in all new modules
- Full type hints on public APIs
- Minimal comments — code should be self-documenting
- Chinese strings in tool descriptions for DeepSeek compatibility
- Import from submodules directly: `from orca_code.tools import tool_registry`

## Feature Flags

Control experimental features:

```python
from orca_code.infrastructure import FeatureFlags

if FeatureFlags.is_enabled("ENABLE_BROWSER"):
    # Browser automation code
    ...
```

Environment overrides: `ORCA_ENABLE_BROWSER=1` or `ORCA_DISABLE_VOICE=1`.

## Release Process

1. Update `docs/2026-MM-DD_开发总结.md`
2. Update `docs/CHANGELOG.md`
3. Bump `__version__` in `orca_code/__init__.py`
4. Run full test suite: `pytest tests/ -v`
5. Tag: `git tag v5.x.x && git push --tags`
