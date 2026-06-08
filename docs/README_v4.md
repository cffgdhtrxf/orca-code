# 🐋 Orca Code v4.0

> **AI Desktop Agent × Security Testing Platform**
>
> Control your PC with natural language. Run authorized penetration tests. All in one tool.

Orca Code merges the desktop automation power of **Orca Code v3** (~7,600 行) with the professional pentesting capabilities of **VulnClaw** (~22,450 行), creating the first unified AI agent that handles both daily office tasks and security assessments.

---

## What It Does

### Desktop Assistant Mode
```
> Open Notepad and write a shopping list
> Take a screenshot and extract the text with OCR
> Search for Python async patterns across my project
> Convert data.json to an Excel file
> What's the weather in Beijing today?
```

### Security Testing Mode
```
orca> target http://testphp.vulnweb.com
orca sec> Run a full penetration test
  Round 1: Recon — ports 80,443 open, Apache/2.4.62
  Round 2: Vuln discovery — SQL injection found in /login
  Round 3: Exploitation — verified with sqlmap
  Round 4: Report generated → report_20260607.md
```

---

## Quick Start

```bash
# 1. Install
pip install orca-code

# 2. Configure a provider
orca config provider deepseek
orca config set llm.api_key sk-your-key

# 3. Launch
orca                          # Desktop assistant REPL
orca security run target.com  # Full pentest
orca doctor                   # Environment check
```

---

## Project Stats

| 维度 | 数值 |
|------|:---:|
| Python 源文件 | 51 |
| 测试文件 | 10 |
| 测试用例 | 100 |
| 注册工具 | 39 |
| Skill 文件 | 184 |
| LLM Provider | 13 |
| MCP 安全服务 | 12 |
| 代码行数 | ~7,000 (重构后) |

---

## Architecture

```
orca_code/
├── config/              Pydantic config + 13 LLM providers
│   ├── schema.py            6 Pydantic models + provider presets
│   └── settings.py          Load/save/migrate/switch
├── session/             LLM client + context management
│   ├── llm_client.py        Streaming + thinking mode + retry
│   ├── prompts.py           Dynamic system prompts (desktop/security)
│   ├── context.py           Smart trim + token estimation + sanitize
│   └── manager.py           Session state (tokens/turns/findings)
├── core/                Agent engine
│   ├── agent_loop.py        Multi-turn: LLM → tools → results → repeat
│   ├── registry.py          Tool registry (TOOLS + TOOL_MAP)
│   ├── init_tools.py        One-call 39-tool registration
│   └── loop.py              Desktop & pentest orchestration
├── tools/               39 built-in tools (8 modules)
│   ├── file_ops.py          6 tools (read/write/list/search)
│   ├── system.py            1 tool  (execute_command)
│   ├── web.py               5 tools (fetch/search/weather/location)
│   ├── office.py            6 tools (Excel/Word/screenshot/OCR)
│   ├── automation.py        9 tools (GUI click/type/hotkey + browser)
│   ├── dev.py               7 tools (git + code nav + image analysis)
│   ├── codec_tools.py      20+ ops (base64/hex/hash/JWT/morse)
│   └── security/            Python sandbox execution
├── security/            Sandbox & safety
│   ├── sandbox.py           AST-level skill sandbox
│   └── patterns.py          Command interception + URL/IP validation
├── skills/              Skill system (184 files)
│   ├── core/                12 Orca Code behavior skills
│   ├── pentest/             7 core pentest skills
│   └── specialized/         13 specialized pentest skills (138 refs)
├── report/              Report generation (Jinja2 templates)
├── target_state/        Snapshot/rollback/diff/resume
├── kb/                  Security knowledge base (CVE/technique/tool)
├── mcp/                 12 MCP security service definitions
├── i18n/                zh + en translations
├── memory/              SQLite FTS5 conversation memory
├── tts/                 TTS & speech recognition (placeholder)
├── ui/                  CLI entry + TUI placeholder
│   ├── cli.py               Typer CLI with REPL + security commands
│   └── web/                 Web UI placeholder
└── tests/               10 test files · 100 tests
```

---

## Commands

| Command | Description |
|---------|-------------|
| `orca` | Desktop assistant REPL |
| `orca config provider <name>` | Switch LLM provider (13 available) |
| `orca config set llm.api_key <key>` | Set API key |
| `orca config list` | Show all settings |
| `orca security run <target>` | Full pentest (multi-round) |
| `orca security recon <target>` | Reconnaissance only |
| `orca security scan <target>` | Vulnerability scan |
| `orca security report <target>` | Generate pentest report |
| `orca doctor` | Environment check |

### REPL Commands

| Command | Action |
|---------|--------|
| `target <host>` | Set pentest target |
| `mode` | Toggle desktop/security mode |
| `status` | Session status (target/phase/tokens/tools) |
| `think` | Toggle LLM reasoning display |
| `report` | Generate pentest report |
| `clear` | Clear session |
| `help` | Show help |

---

## Built-in Tools (39)

| Domain | Count | Tools |
|--------|:-----:|-------|
| **File Ops** | 6 | `read_file` `write_file` `list_files` `search_files` `search_content` `get_system_info` |
| **System** | 1 | `execute_command` |
| **Web** | 5 | `web_fetch` `read_webpage` `web_search` `get_weather` `get_location` |
| **Office** | 6 | `read_excel` `write_excel` `read_word` `write_word` `take_screenshot` `ocr_image` |
| **GUI Auto** | 7 | `gui_click` `gui_type` `gui_hotkey` `gui_move` `gui_press` `window_focus` `find_on_screen` |
| **Browser** | 2 | `browser_open` `browser_screenshot` |
| **Dev** | 7 | `git_status` `git_diff` `git_log` `git_blame` `go_to_definition` `find_references` `analyze_image` |
| **Codec** | 1 | `crypto_decode` (20+ ops: base64/hex/hash/JWT/morse/auto) |
| **Python** | 1 | `execute_python` |
| **Skills** | 3 | `load_skill` `load_md_skill` `list_skills` |

---

## LLM Providers (13)

| Provider | Model | Command |
|----------|-------|---------|
| DeepSeek | deepseek-v4-pro | `orca config provider deepseek` |
| OpenAI | gpt-4o | `orca config provider openai` |
| MiniMax | MiniMax-M3 | `orca config provider minimax` |
| Zhipu GLM | glm-4.7 | `orca config provider zhipu` |
| Kimi | kimi-k2.6 | `orca config provider moonshot` |
| Tongyi Qwen | qwen3-max | `orca config provider qwen` |
| SiliconFlow | DeepSeek-V4-Flash | `orca config provider siliconflow` |
| Doubao | Doubao-Seed-2.0-Pro | `orca config provider doubao` |
| Baichuan | Baichuan4-Turbo | `orca config provider baichuan` |
| StepFun | step-3.5-flash | `orca config provider stepfun` |
| SenseTime | SenseNova-6.7-Flash-Lite | `orca config provider sensetime` |
| Yi | yi-lightning | `orca config provider yi` |
| Custom | manual | `orca config provider custom` |

---

## Pentest Skills (20)

### Core (7)
`pentest-flow` · `recon` · `vuln-discovery` · `exploitation` · `post-exploitation` · `reporting` · `waf-bypass`

### Specialized (13)
`web-pentest` · `android-pentest` · `client-reverse` · `web-security-advanced` · `ai-mcp-security` · `intranet-pentest-advanced` · `pentest-tools` · `rapid-checklist` · `crypto-toolkit` · `ctf-web` · `ctf-crypto` · `ctf-misc` · `osint-recon`

---

## Security Features

| Layer | Mechanism |
|:-----:|-----------|
| 1. Command | Regex-based dangerous pattern interception (`rm -rf /`, `mkfs`, `format`) |
| 2. File | Atomic writes (temp→rename), project file write protection |
| 3. Skill | AST static analysis — blocks imports, `eval`/`exec`, dunder attribute chains |
| 4. Data | API key masking, `.gitignore` exclusion, save-time sanitization |
| 5. GUI | `KeyboardInterrupt` resilience — all Rich console ops wrapped in try/except |

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (100 tests)
pytest orca_code/tests/ -v

# Lint
ruff check orca_code/

# Type check
mypy orca_code/ --ignore-missing-imports
```

---

## License

MIT License — see [LICENSE](LICENSE)

---

> 🐋 **Orca Code** — Speak naturally. Control everything.
