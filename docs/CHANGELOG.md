# Changelog

## v5.2.0 (2026-06-09) — TUI 生产就绪

### TypeScript TUI (orca-ts/) — FullscreenLayout 架构
- ✅ **FullscreenLayout 模式** (源自 Claude Code) — `flexShrink={0}` 固定 banner/输入栏, `flexGrow={1}` 滚动区吸收剩余空间, `overflow="hidden"` 溢出裁剪
- ✅ **Welcome 页布局** — `<Box flexGrow={1} />` 占位将输入栏推至底部
- ✅ **消息顺序修正 (chronological)** — `flushFinalToMessages` 拆分为两条消息: 思考 (插在 user 后、tools 前) + 回答 (追加在 tools 后)
- ✅ 显示: `💭思考` → `⚡工具` → `●回复`

### 流式与工具执行
- ✅ `tool_executing` 携带 `tools: string[]` — TUI 显示 `⚡ search_web, read_webpage …`
- ✅ `tool_executing` 时清空 `streamTextRef` (每个 agent-loop turn 独立)
- ✅ 流式缓冲分离: `streamReasoningRef` / `streamTextRef` 独立更新
- ✅ Spinner 动画 80ms 切换 + 计时 `[Ns]`
- ✅ Token 显示: 0/0 时隐藏, 仅 >0 时显示 `↑Nt ↓Nt`

### 输入修复
- ✅ **退格修复** — Windows 终端发送 `\x7f` (DEL), Ink 映射为 `key.delete`, handler 同时检查 `backspace` + `delete` + 原始字节
- ✅ **IME 光标** — `\x1b[?25h` (DECTCEM) 显示终端光标, IME 组合窗口正确定位
- ✅ **稳定 handler** — `useCallback([], [])` + `useRef` 防止 Ink listener churn

### Banner 修复
- ✅ 渐变 banner 从 468 个 `<Text>` 简化到 6 个 (每行一个), 预计算 `BANNER_COLORS` 数组
- ✅ `v5.2` 版本号不再合并到 banner 末尾行

### 后端
- ✅ **Agent loop** (server.py) — 模型调用工具 → 结果反馈 → 重复 (max 10 turns)
- ✅ **YOLO 强制** — server 模式下设置 `PERMISSION_MODE = PermissionMode.YOLO`, 避免 `msvcrt.getwch()` 阻塞
- ✅ **健康检查** — `/v1/health` 端点 (修复自 `/health`)
- ✅ **一键启动** — `start_all.bat` 带 PowerShell 健康检查

### 参考架构
- ✅ 研究 Claude Code: `FullscreenLayout.tsx` (flex layout), `store.ts` (external store), `ScrollBox.tsx`
- ✅ 研究 oh-my-pi: `tui.ts` (custom renderer), `scroll-view.ts`

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
