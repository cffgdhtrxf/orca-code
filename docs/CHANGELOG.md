# Changelog

## v5.1.0 (2026-06-08) — 融合增强

### Provider 适配器层
- ✅ **providers/** 包：多 LLM 适配器架构（Proma ProviderAdapter 模式）
- ✅ **DeepSeekAdapter**：思考模式 + 缓存命中 + reasoning_effort
- ✅ **OpenAICompatAdapter**：OpenAI 兼容协议适配器
- ✅ **AnthropicCompatAdapter**：Anthropic Messages API（解锁 Claude API）
- ✅ **LocalAdapter**：Ollama / LM Studio 本地模型
- ✅ **自动检测**：autodetect_provider() 从 base_url + model_name 推断
- ✅ **provider_client.py**：ProviderAwareClient 懒初始化

### 工具系统重构
- ✅ **Tool 基类**：ABC + JSON Schema 声明 + RiskLevel 自标注
- ✅ **ToolRegistry**：中心化注册表 + execute + schema 导出 + 遗留兼容
- ✅ **8 核心工具**：ReadFile, WriteFile, EditFile, ListFiles, SearchFiles, SearchContent, ExecuteCommand, GetSystemInfo
- ✅ **5 Web 工具**：WebFetch, ReadWebpage, WebSearch, GetWeather, GetLocation
- ✅ **6 Dev 工具**：GitStatus, GitDiff, GitLog, GitBlame, GoToDefinition, FindReferences
- ✅ **6 Office 工具**：ReadExcel, WriteExcel, ReadWord, WriteWord, TakeScreenshot, OcrImage
- ✅ **12 Automation 工具**：GUI Click/Type/Hotkey/Press/Move + WindowFocus + FindOnScreen + Browser
- ✅ **14 Extended 工具**：Skills(6) + LSP(3) + SubAgent(3) + SpeakText + ExecutePython
- ✅ **4 Task 工具**：TaskCreate, TaskUpdate, TaskGet, TaskList（Claude Code Task 状态机）
- ✅ **bridge.py**：63 遗留工具 → 新 ToolRegistry 桥接 + EventBus 接线

### 核心抽象层
- ✅ **错误分类** (core/errors.py)：7 类错误（Network/Auth/RateLimit/Model/Tool/Permission/Internal）
- ✅ **智能重试**：classify_error() + execute_with_retry() 指数退避
- ✅ **事件总线** (core/event_bus.py)：23 种事件类型 + 线程安全发布-订阅
- ✅ **EventBus 单例**：get_event_bus() 全局访问

### 基础设施
- ✅ **纯配置加载** (config_loader.py)：零副作用 + 热重载
- ✅ **配置懒加载** (config.py)：client/mem_mgr 延迟初始化
- ✅ **特征开关** (feature_flags.py)：15 个编译时开关（Claude Code feature() 模式）
- ✅ **平台检测** (platform.py)：Windows/macOS/Linux + 设备类型
- ✅ **指标收集** (metrics.py)：工具耗时 p50/p95/p99 + 错误率
- ✅ **文件日志** (file_logger.py)：JSONL 结构化日志 + 按日切割

### 包结构
- ✅ 重命名 `ultimate_agent` → `orca_code`（54 文件替换）
- ✅ `__init__.py` 懒加载 `__getattr__`（import 143x 加速：4s → 0.028s）
- ✅ `config.py` 拆分：纯加载 → config_loader，薄兼容层 → config
- ✅ 星号导入根除：11 处 `from X import *` → 按需懒加载

### 工程化
- ✅ **CI/CD**：GitHub Actions（多 OS + lint + test + type-check）
- ✅ **版本管理**：`__version__ = "5.1.0"`
- ✅ **测试**：20 → 98 (+390%)，覆盖 errors/flags/providers/tools/security

### 文档
- ✅ **README v5.1**：完整架构图 + Provider/EventBus/Task 文档
- ✅ **FUSION_REPORT.md**：融合实施完整报告
- ✅ **三项目深度对比分析报告**：Orca Code vs Claude Code vs Proma

---

## v5.0.0 (2026-06-08) — 融合升级

### 安全系统重构
- ✅ **权限系统** (permissions.py)：57 工具风险分级 + 3 模式 (read-only/auto/yolo)
- ✅ **安全层重写** (security.py)：Layer 0 始终拦截 (8 条) + Layer 0.5 非 YOLO 拦截 (6 条)
- ✅ **SSRF 防护恢复**：is_safe_url() 拦截 localhost/私有IP/链路本地
- ✅ **check_command_safety()** 统一安全入口

### 编码能力
- ✅ **edit_file**: 精确字符串替换 + AST 验证 + 原子写入
- ✅ **apply_diff**: unified diff 解析和应用
- ✅ **LSP 集成** (lsp.py)：diagnostics/references/definition + 自动触发
- ✅ **子代理并发** (subagent.py)：agent_open/eval/close

### Constitution 系统
- ✅ 五级权威层级 (Safety > User > Evidence > Verify > Legacy)
- ✅ System prompt 前缀注入 (KV 缓存零成本)
- ✅ 工具结果验证标记 [✓ VERIFIED] / [✗ FAILED]

### Rust 原生引擎
- ✅ **orca_native/** crate：ripgrep 搜索 + diff 应用 + 文件遍历
- ✅ PyO3 绑定 + Python fallback
- ✅ search_content/search_files 自动优先使用 Rust

### 工程改进
- ✅ **config.py 去重**：708 → 535 行
- ✅ **TUI 升级**：ANSI → Rich Live 流式 Markdown + diff 着色
- ✅ **GUI 降级**：system prompt 重写为 CLI > API > GUI 优先级
- ✅ **权限命令**：/permissions mode/allow/deny/ask/reset

### 工具增长
- 50 → 63 (+13：edit_file, apply_diff, lsp_diagnostics, lsp_references, lsp_definition, agent_open, agent_eval, agent_close + /permissions)

---

## v4.0.0 (2026-06-06) — 模块化重构

- ✅ 单文件 4644 行 → 12 模块包
- ✅ 工具 43 → 50
- ✅ GUI 自动化重构（剪贴板粘贴替代逐字符输入）
- ✅ 安全策略调整、命令执行重构
- ✅ 循环导入解决方案

---

## v3.0.0 (2026-06-05) — 功能完整版

- ✅ Bug 修复 (8 项)
- ✅ Token 优化 (6 项)
- ✅ 功能新增：Python REPL, 记忆系统, 混合视觉架构
- ✅ 安全加固、记忆系统重构、用户画像
- ✅ 工具健康状态：40 可用 / 1 需配置 / 4 需安装
