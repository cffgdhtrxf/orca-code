# 🐋 Orca Code v5.1

**桌面 AI 代理 — 用自然语言控制你的 Windows 电脑，兼具专业级代码编辑能力。**

融合了 Claude Code 的权限模型和任务系统、CodeWhale 的 Constitution 权威体系、Proma 的 Provider 适配器架构。

```
说「打开网易云播我收藏的歌」→ AI 自动搜索→点击→播放
说「重构这个模块，去掉循环导入」→ AI diff 精确替换 + LSP 诊断
说「分析这个项目的安全漏洞」→ AI 启动子代理并发扫描
```

---

## v5.1 新特性

| 特性 | 说明 |
|------|------|
| **多 Provider** | DeepSeek / OpenAI / Anthropic / 本地模型 — 自动检测，无缝切换 |
| **智能错误恢复** | 7 类错误自动分类 + 指数退避重试（网络/限流自动重试） |
| **任务系统** | TaskCreate → TaskUpdate → TaskComplete 完整状态机 + 依赖管理 |
| **事件总线** | 23 种事件类型，发布-订阅解耦，工具执行全生命周期可观测 |
| **指标收集** | 工具耗时 p50/p95/p99，错误率追踪，JSONL 文件日志 |
| **特征开关** | 15 个 FeatureFlags，编译时按需启用（GUI/Browser/OCR 默认关闭） |
| **模块化架构** | 27 个模块，import 加速 143x（4s → 0.028s） |
| **107 测试** | 覆盖错误分类/Provider/工具/安全/指标（v5.0 仅 20 个） |

---

## ✨ 核心能力

| 能力 | 实现 |
|------|------|
| **桌面自动化** | GUI 点击/输入/热键/窗口控制 + OCR 找图 |
| **专业编码** | edit_file (精确替换) + apply_diff (unified diff) + LSP 诊断 |
| **子代理并发** | agent_open → 后台执行 → agent_eval 获取结果 + EventBus 事件 |
| **语音交互** | Whisper/Vosk/Hybrid 语音输入 + SAPI TTS 朗读 |
| **办公处理** | Excel/Word 读写 + 截图 + OCR |
| **网页/搜索** | web_fetch + web_search + 天气 + 定位 |
| **长期记忆** | SQLite FTS5 全文检索 + 用户画像跨会话学习 |
| **技能扩展** | .py 工具技能 + .md 行为协议 + MCP 外部工具 |
| **定时任务** | Cron / Interval 调度器 |
| **多 Provider** | DeepSeek / OpenAI / Anthropic / Ollama / LM Studio |
| **任务追踪** | TaskCreate/Update/Get/List — 结构化任务管理 + JSON 持久化 |

---

## 🛡 安全

三层纵深防御，Claude Code 风格——**不烦人**：

```
Layer 0  → 始终拦截 (rm -rf /、format、curl|bash、fork bomb 等 8 条)
Layer 1  → 权限系统 (read/write/exec 风险等级 + read-only/auto/yolo 三种模式)
Layer 2  → 技能沙箱 (AST 静态分析 + 受限命名空间)
```

三个权限模式 `/permissions mode <read-only|auto|yolo>`：
- **read-only** — 只读工具自动放行
- **auto** — 首次使用询问一次，选择后记住（默认）
- **yolo** — 全部自动放行

---

## 🚀 快速开始

```powershell
# 1. 双击 start.bat（自动创建 venv + 安装依赖）
#    或手动：
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. 编辑 config.json 填入 API Key
# 3. 编译 Rust 原生引擎（可选，10-100x 搜索加速）：
cd orca_native
.venv\Scripts\pip install maturin
$env:PYTHONUTF8=1; maturin develop --release
cd ..

# 4. 启动
python orca_code.py
```

---

## 🏗 架构

```
orca_code/                          # 27 个模块
├── main.py / session.py            # 主循环 + LLM 会话
├── config.py                       # 配置（懒加载客户端）
├── constitution.py                 # Constitution 五级权威体系
├── permissions.py / security.py    # 权限 + 安全
│
├── core/                           # 核心抽象层
│   ├── errors.py                   # 7 类错误 + 智能重试
│   └── event_bus.py                # 23 种事件发布-订阅
│
├── providers/                      # 多 LLM 适配器
│   ├── base.py                     # ProviderAdapter 抽象基类
│   ├── registry.py                 # 注册表 + 自动检测
│   ├── deepseek.py                 # DeepSeek（思考模式）
│   ├── openai_compat.py            # OpenAI 兼容
│   ├── anthropic_compat.py         # Anthropic 协议
│   └── local.py                    # 本地模型
│
├── tools/                          # 工具系统
│   ├── base.py                     # Tool 基类 + ToolRegistry
│   ├── bridge.py                   # 63 工具桥接 + EventBus
│   ├── core.py                     # 8 核心文件/命令工具
│   ├── web.py                      # 5 Web 工具
│   ├── dev.py                      # 6 Git/代码导航工具
│   ├── office.py                   # 6 办公工具
│   ├── automation.py               # 12 GUI/浏览器工具
│   ├── tasks.py                    # 4 任务管理工具
│   └── extended.py                 # 14 LSP/子代理/语音工具
│
├── infrastructure/                 # 基础设施
│   ├── config_loader.py            # 纯配置加载
│   ├── provider_client.py          # Provider 感知客户端
│   ├── feature_flags.py            # 编译时特征开关
│   ├── platform.py                 # 平台检测
│   ├── metrics.py                  # 工具耗时 p50/p95/p99
│   └── file_logger.py              # JSONL 结构化日志
│
└── cli/                            # CLI 层
    ├── commands.py                 # /命令处理器
    ├── input_handler.py            # 输入处理（键盘/语音/粘贴）
    └── main_loop.py                # 主循环

orca_native/                        # Rust 原生引擎 (PyO3)
├── src/search.rs                   # ripgrep 代码搜索
├── src/diff.rs                     # unified diff 应用
└── src/walk.rs                     # .gitignore 感知文件遍历
```

---

## 🧰 工具一览 (63+4 任务)

### 核心
`execute_command` `read_file` `write_file` `edit_file` `apply_diff` `list_files` `search_files` `search_content` `get_system_info`

### 任务系统 (v5.1 新增)
`task_create` `task_update` `task_get` `task_list`

### LSP
`lsp_diagnostics` `lsp_references` `lsp_definition`

### 子代理
`agent_open` `agent_eval` `agent_close`

### GUI
`gui_click` `gui_type` `gui_move` `gui_hotkey` `gui_press` `window_focus` `find_on_screen`

### 浏览器
`browser_open` `browser_click` `browser_type` `browser_screenshot` `browser_close`

### 办公
`read_excel` `write_excel` `read_word` `write_word` `take_screenshot` `ocr_image`

### 网络
`web_fetch` `read_webpage` `web_search` `get_weather` `get_location`

### 开发
`git_status` `git_diff` `git_log` `git_blame` `go_to_definition` `find_references` `analyze_image` `capture_camera` `execute_python`

### 技能
`load_skill` `create_skill` `edit_skill` `list_skills` `load_md_skill` `list_md_skills` `add_task` `list_tasks` `remove_task`

### 记忆
`recall_conversation` `update_profile` `speak_text`

---

## ⌨️ 命令

| 命令 | 功能 |
|------|------|
| `/help` | 帮助 |
| `/voice` | 语音输入 |
| `/config` | 查看/修改配置 |
| `/permissions` | 管理工具权限 |
| `/skills` | 已加载技能 |
| `/tasks` | 任务列表 |
| `/stats` | 会话统计 + 工具耗时 |
| `/memories` | 记忆摘要 |
| `/profile` | 用户画像 |
| `/think` | 上次推理过程 |
| `/save` | 导出对话 |
| `/clear` | 清空对话 |
| `/exit` | 退出 |

---

## ⚙️ 配置

`config.json` 主要配置项：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_key` | API Key | — |
| `base_url` | API 端点 | `https://api.deepseek.com` |
| `model_name` | 模型名称 | `deepseek-chat` |
| `permission_mode` | 权限模式 | `auto` |
| `enable_gui_auto` | GUI 自动化 | `false` |
| `enable_browser_auto` | 浏览器自动化 | `false` |
| `enable_voice` | 语音输入 | `true` |
| `enable_tts` | 语音朗读 | `true` |
| `local_model` | 本地模型 | `false` |

---

## 📦 技术栈

| 层 | 技术 |
|----|------|
| 编排 | Python 3.12+ asyncio |
| 性能 | Rust (PyO3) — ripgrep 搜索 / diff 应用 / 文件遍历 |
| LLM | DeepSeek / OpenAI 兼容 / Anthropic 兼容 / Ollama / LM Studio |
| UI | Rich (流式 Markdown + 语法高亮 + diff 着色) |
| 记忆 | SQLite + FTS5 全文检索 |
| 语音 | Whisper / Vosk / Sherpa-ONNX |
| TTS | Windows SAPI |

---

## 🧪 测试

```bash
# 核心测试
pytest tests/test_errors.py tests/test_feature_flags.py tests/test_providers.py tests/test_tools.py

# 安全测试
pytest tests/test_security.py

# 全部测试
pytest tests/ -v
```

---

## 📄 许可证

[MIT License](LICENSE)
