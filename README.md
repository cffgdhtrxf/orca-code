# Orca Code

**桌面 AI 编程助手 — 66 工具 · 生命周期工作流 · 上下文压缩 · 3 层安全**

---

## 快速开始

### 方式 1: 下载 ZIP 运行
1. 从 [GitHub](https://github.com/cffgdhtrxf/orca-code) 下载 ZIP
2. 解压到任意目录
3. 双击 `start.bat`（自动创建虚拟环境 + 安装依赖 + 启动）
4. 首次运行会提示输入 API 密钥

### 方式 2: Git Clone 运行
```bash
git clone https://github.com/cffgdhtrxf/orca-code.git
cd orca-code
python -m venv .venv
.venv\Scripts\pip install -e .
python orca_code.py
```

### 更新
双击 `update.bat` 自动从 GitHub 拉取最新版本（无需 Git，使用 PowerShell）。

---

## 架构

```
┌──────────────────────────────────────────┐
│  Python CLI (orca_code.py)               │
│  │                                       │
│  │  main.py         主循环               │
│  │  session_*.py    会话管理 + 压缩       │
│  │  tools/          66 工具              │
│  │  security.py     3 层安全             │
│  │  slash_commands  19+8 命令            │
│  │  session_prompt  动态系统提示词        │
│  │  constitution.py  宪法(5+1 条)        │
│  └──────────────────────────────────────│
│  纯 Python · 单进程 · 零外部依赖         │
└──────────────────────────────────────────┘
```

## 特性

| 特性 | 说明 |
|------|------|
| 工具数量 | 66 个（自动生成 Schema） |
| 安全模型 | 3 层：安全网 → 静态扫描(AST+regex) → 子进程沙箱 |
| 生命周期工作流 | DEFINE→PLAN→BUILD→VERIFY→REVIEW→SHIP（23 个 SKILL.md） |
| 上下文压缩 | 可选 headroom-ai（6 算法），自动降级规则摘要 |
| 命令 | 19 个内置 + 8 个生命周期 slash 命令 |
| 系统提示词 | Constitution + 技能清单 + AGENTS.md 自动注入 |
| 持久化 | 3 层：chat_history.json → session.jsonl → FTS5 记忆 |
| 开箱即用 | 明文密钥可接受 + 自动安装依赖 + 零环境变量 |
├── rpc-client.ts   Python 子进程管理器
└── components/     7 组件 (ToolCard/Diff/Markdown/...)

orca_code/                        ← Python 后端
├── rpc_server.py         RPC stdin/stdout 服务器
├── server.py             FastAPI (远程模式)
├── session_stream.py     LLM 流 + 重试
├── tool_registry.py      61 工具注册 + 验证 + MCP
├── tool_cache.py         LRU 缓存 + 大输出截断
├── tool_validator.py     JSON Schema 参数验证
├── batch_executor.py     批量工具并行执行
├── mcp_client.py         MCP 协议客户端
├── fallback.py           Provider 回退链 + 熔断
├── hooks.py              工具前后钩子
├── plugin_loader.py      外部插件加载
├── rollback.py           文件回滚
├── worktree.py           Git worktree 隔离
├── shell_session.py      持久化 Shell 会话
├── config_validator.py   启动配置验证
├── workspace_detect.py   项目自动检测
├── rate_tracker.py       API RPM/TPM 统计
├── latency_tracker.py    p50/p95/p99 延迟
├── cost_estimator.py     Token 成本估算
├── session_compaction.py 上下文自动压缩
├── session_crypto.py     AES 会话加密
├── key_rotation.py       多 API Key 轮换
├── structured_log.py     结构化日志
├── response_cache.py     LLM 响应缓存
├── smart_context.py      智能上下文注入
├── permissions.py        3 级权限 + 审计
├── subagent.py           后台子代理
├── orchestrator.py       多代理编排
└── ... (共 60+ 模块)
```

---

## 核心能力

| 能力 | 说明 |
|------|------|
| **单进程** | `bun run dev` 一键启动，TypeScript 自动管理 Python 子进程 |
| **94 TUI 命令** | 文件/系统/开发/AI/会话/诊断/配置 全覆盖 |
| **61 工具** | 读写/搜索/Git/GUI/浏览器/Office/OCR/LSP/MCP/子代理 |
| **Cursor 输入** | 不可变 Cursor 类，方向键+退格+删除+Home/End |
| **流式显示** | 思考→工具→回答，正确时序，不重复 |
| **上下文压缩** | Token 超 70% 自动触发，保留近期 + 摘要 |
| **多 Provider** | DeepSeek/OpenAI/Anthropic/本地，回退链+熔断 |
| **权限系统** | 只读/自动/YOLO，每工具风险分级，审计日志 |
| **会话管理** | JSONL 持久化 · 分叉 · 合并 · 标签 · 多格式导出 |
| **MCP 协议** | stdio transport，自动发现工具 |
| **工作区隔离** | Git worktree + 目录复制，子代理沙箱 |
| **安全** | Fernet AES 加密 · 配置验证 · 代理字符清理 |

---

## 配置

`config.json` 关键设置：

```json
{
  "api_key": "sk-xxx",
  "base_url": "https://api.deepseek.com",
  "model_name": "deepseek-chat",
  "permission_mode": "auto",
  "context_max_tokens": 100000,
  "hooks": {},
  "mcp_servers": {}
}
```

---

## 测试

```bash
python -m pytest tests/ -v
python -m pytest tests/test_new_modules.py -q   # 29 tests
```

---

## License

MIT
