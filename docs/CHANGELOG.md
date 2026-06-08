# Changelog

## v5.1.0 (2026-06-08) — 生产就绪

### 代码审查修复
- ✅ 修复 `_balance_cache` UnboundLocalError
- ✅ 修复 `_browser_instance` NameError
- ✅ 添加编码 PowerShell 命令检测 (`-EncodedCommand`, `-enc`)
- ✅ 修复 `format` 正则误杀 `-Format` 参数

### 架构重构 (5 个循环依赖 → 0)
- ✅ **tool_registry.py**：提取 TOOLS/TOOL_MAP/run_tool 到独立模块
- ✅ 消除 6 个野 import (仅剩 session 显式导入)
- ✅ CLI handlers 移到 `cli/commands.py`
- ✅ 调度器线程显式启动（修复从未 start() 的 bug）

### Session 拆分 (810 → 253 行)
- ✅ **session_messages.py**：消息清洗/压缩/token 估算
- ✅ **session_prompt.py**：System prompt 构建
- ✅ **session_ui.py**：终端 UI 渲染 (Rich)
- ✅ **session_stream.py**：API 调用/流处理/工具执行

### Tool 类系统 (57 类化工具)
- ✅ **tools/base.py**：Tool ABC + ToolRegistry
- ✅ **tools/core.py**：9 核心工具 (ReadFile, WriteFile, EditFile...)
- ✅ **tools/web.py**：5 Web 工具
- ✅ **tools/office.py**：6 Office 工具
- ✅ **tools/dev.py**：8 Dev 工具
- ✅ **tools/skills.py**：6 技能工具
- ✅ **tools/tasks.py**：3 任务工具
- ✅ **tools/automation.py**：7 GUI 工具
- ✅ **tools/browser.py**：5 浏览器工具
- ✅ **tools/extended.py**：8 扩展工具 (TTS, SubAgent, REPL, LSP)
- ✅ **tools/bridge.py**：类系统 ↔ 遗留 TOOL_MAP 双向同步

### Provider 适配器层
- ✅ DeepSeekAdapter — 思考模式 + reasoning_effort + 缓存命中
- ✅ OpenAICompatAdapter — OpenAI 协议适配
- ✅ AnthropicCompatAdapter — Anthropic Messages API
- ✅ LocalAdapter — Ollama / LM Studio
- ✅ 自动检测：autodetect_provider()
- ✅ 修复 DeepSeekAdapter thinking 注入 (reasoner 模型)

### 安全增强
- ✅ 编码命令检测 (`-EncodedCommand`, `-enc`)
- ✅ 技能沙箱 14 逃逸向量测试 (9 基础 + 5 高级)
- ✅ 安全模式白名单测试 (7 种合法模式)
- ✅ 命令安全层 format 正则修复

### 基础设施
- ✅ **helpers.py**：get_api_balance, ensure_pkg, search_cache
- ✅ 配置统一为 JSON-only (TXT 自动迁移)
- ✅ SQLite 内存优化 (WAL + NORMAL sync + 8MB cache + incremental vacuum)
- ✅ Token 预算警告 (90% 上下文限制)
- ✅ CLI 参数：--version / --help / --no-mcp

### Rust 原生加速
- ✅ orca_native 编译通过 (cargo check/build)
- ✅ 修复 DLL 加载 (importlib + sys.modules 恢复)
- ✅ 搜索 0.011s — ripgrep 引擎 10-100x 加速
- ✅ 构建脚本：build_and_install.py

### Web 仪表盘
- ✅ Flask 仪表盘 (localhost:8499)
- ✅ /stats /tools /health 端点
- ✅ 自动刷新 HTML 界面

### 测试
- ✅ 30 新核心工具测试 (execute/edit/diff/write/read/list)
- ✅ 10 新 Provider 测试 (thinking mode, stream events, non-stream)
- ✅ 9 新集成测试 (Mock API stream, 错误分类)
- ✅ 12 新参数化测试 (编码/大小/位置/模式)
- ✅ 修复 13 预存在集成测试失败
- ✅ 总测试数：99+ passed

### 工程
- ✅ pyproject.toml + setup.py (pip install -e .)
- ✅ PyInstaller spec (单文件 .exe)
- ✅ GitHub Actions CI (Windows, Python 3.11/3.12)
- ✅ INSTALL.md 安装指南
- ✅ ARCHITECTURE.md 架构文档
- ✅ 0 野 import，0 循环依赖

---

## v5.0.0 (2026-06-06) — 初始架构

- ✅ orca_code/ 包结构
- ✅ 懒加载 import (143x 加速)
- ✅ Constitution 五级权威体系
- ✅ 三级权限模型
- ✅ Layer 0 安全网
- ✅ 技能 AST 沙箱
- ✅ 58 工具 (核心/Web/Office/Dev/GUI/浏览器)
- ✅ MCP 协议支持
- ✅ TTS + 语音识别
- ✅ 定时任务调度器
- ✅ 子代理并发执行
- ✅ FTS5 全文记忆
