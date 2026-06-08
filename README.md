# 🐋 Orca Code v5.1

**桌面 AI 助手 — 58 工具，多 Provider，支持 Windows/Linux/macOS。**

融合 Claude Code 权限模型、CodeWhale Constitution 权威体系、Proma Provider 适配器架构。

```
说「重构这个模块」→ AI diff 精确替换 + LSP 诊断
说「搜一下上次那个bug」→ FTS5 全文记忆搜索
说「打开浏览器看新闻」→ Playwright 浏览器自动化
```

---

## 快速开始

```bash
pip install -e .                    # 安装
cp config.example.json config.json  # 编辑 api_key
python orca_code.py                 # 启动
```

```bash
python orca_code.py --version       # v5.1.0
python orca_code.py --help          # 帮助
python orca_code.py --no-mcp        # 跳过 MCP
```

---

## 架构

```
orca_code/
├── config.py             配置 + 懒加载客户端
├── tool_registry.py      58 工具定义 + TOOL_MAP + dispatch
├── main.py               CLI 主循环
├── session.py            Session 状态 + 持久化
│   ├── session_messages  消息清洗/压缩/token估算
│   ├── session_prompt     System prompt 构建
│   ├── session_ui        终端 UI (Rich)
│   └── session_stream    API 调用/流处理/工具执行
├── security.py           Layer 0 安全网 + 技能沙箱
├── permissions.py        三级权限 (READ/WRITE/EXEC)
├── constitution.py       五级权威体系
├── tools_core/dev/web/office/skills/automation/  工具实现
├── tools/                类化工具系统 (57 类)
├── providers/            多 Provider 适配器
├── infrastructure/       平台/配置/特征开关/日志
├── core/                 错误分类/事件总线
├── cli/                  CLI 命令处理
├── dashboard.py          Flask Web 仪表盘
├── lsp.py                LSP 集成
├── subagent.py           并发子代理
└── tts_mcp.py            TTS + 语音 + MCP
```

---

## 核心能力

| 能力 | 说明 |
|------|------|
| **58 工具** | 文件读写/搜索/Git/GUI/浏览器/Office/OCR/TTS/天气/位置 |
| **多 Provider** | DeepSeek / OpenAI / Anthropic / 本地模型，自动检测 |
| **智能压缩** | 3 级对话压缩 (LLM→规则→空)，SQLite FTS5 全文记忆 |
| **安全沙箱** | Layer 0 安全网 + 技能 AST 沙箱 (14 逃逸向量测试) |
| **权限系统** | 只读/自动/YOLO 三种模式，每工具风险分级 |
| **并发执行** | ThreadPoolExecutor 并行工具 + SubAgent 后台代理 |
| **LSP 集成** | Python/TypeScript/Rust/Go 诊断/引用/定义 |
| **调度器** | Cron + Interval 定时任务，持久化日志 |
| **Web 仪表盘** | Flask :8499，/stats /tools /health |
| **Rust 加速** | ripgrep 引擎，搜索 0.011s (10-100x) |

---

## 安装选项

```bash
pip install -e .                  # 最小安装
pip install -e ".[gui]"           # + GUI 自动化
pip install -e ".[browser]"       # + 浏览器自动化
pip install -e ".[office]"        # + Excel/Word
pip install -e ".[speech,tts]"    # + 语音/TTS
pip install -e ".[all]"           # 全部
```

---

## 配置

`config.json` 关键设置：

```json
{
  "api_key": "sk-xxx",
  "base_url": "https://api.deepseek.com",
  "model_name": "deepseek-chat",
  "permission_mode": "auto",
  "context_max_tokens": 100000
}
```

---

## 测试

```bash
python -m pytest tests/ -v        # 99+ tests
python -m pytest tests/ -q        # 快速
```

---

## 文档

| 文件 | 内容 |
|------|------|
| [INSTALL.md](INSTALL.md) | 安装指南 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构设计 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 变更日志 |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | 贡献指南 |

---

## License

MIT
