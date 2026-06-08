# Contributing to Orca Code

## Development Setup

```bash
# 1. Clone
git clone <repo-url>
cd orca_code

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 3. Install in dev mode
pip install -e ".[dev]"

# 4. (Optional) Build Rust native engine — 10-100x search speedup
cd orca_native
cargo build --release
python build_and_install.py
cd ..
```

## Running Tests

```bash
# All tests
python -m pytest tests/ -v

# Specific suites
python -m pytest tests/test_tools.py -v       # Tool tests (30)
python -m pytest tests/test_security.py -v    # Security tests (35+)
python -m pytest tests/test_providers.py -v   # Provider tests (24)
python -m pytest tests/test_integration.py -v # Integration tests (22+)

# With coverage
python -m pytest tests/ --cov=orca_code --cov-report=html
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full module map and data flow.

Key principles:
- **No circular imports** — `tool_registry.py` is the single source of truth for tools
- **Lazy resolution** — `update_profile`/`recall_conversation` resolved at call time
- **Explicit imports only** — zero wildcard imports in main.py
- **Session split** — messages/prompt/ui/stream in separate submodules

## Adding a New Tool

### Option A: Class-based (recommended)

```python
# orca_code/tools/example.py
from orca_code.tools.base import Tool
from orca_code.permissions import RiskLevel

class MyTool(Tool):
    name = "my_tool"
    description = "Does something useful"
    parameters = {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Input data"},
        },
    }
    required = ["input"]
    risk_level = RiskLevel.READ

    def execute(self, input: str) -> str:
        # Implementation
        return f"Result: {input}"
```

Then register:
```python
from orca_code.tools import tool_registry
from orca_code.tools.example import MyTool
tool_registry.register(MyTool())
```

### Option B: Flat function (legacy)

```python
# orca_code/tools_core.py
def my_tool(input: str) -> str:
    return f"Result: {input}"

# orca_code/tool_registry.py
from orca_code.tools_core import my_tool
TOOL_MAP["my_tool"] = my_tool
TOOLS.append({...})  # Add schema definition
```

## Code Style

- 中文 UI，英文代码
- 函数用 snake_case，类用 PascalCase
- 不写注释——代码自解释
- 不过度抽象——一个函数做一件事
- 导入顺序：标准库 → 第三方 → 项目内部

## Testing Guidelines

- 每个新工具至少 3 个测试
- 安全相关必须有参数化测试（逃逸向量）
- 用 `tmp_path` fixture 做文件测试
- Mock 外部 API 调用

## Release Checklist

- [ ] 所有测试通过
- [ ] CHANGELOG.md 更新
- [ ] pyproject.toml 版本号更新
- [ ] `python orca_code.py --version` 正确
- [ ] `pip install -e .` 成功
- [ ] git tag vX.Y.Z
