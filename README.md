# 🐋 Orca Code v5.3

**桌面 AI 编程助手 — 61 工具 · 30 API 端点 · 94 TUI 命令 · 单进程架构**

融合 Claude Code 权限模型 + omp 单进程架构 + Cursor 不可变输入模式。

---

## 快速开始

```bash
# 方式 1 (推荐): 单命令启动
cd orca-ts && bun run dev

# 方式 2: Windows 双击
双击 start.bat

# 方式 3: Python CLI 模式
python orca_code.py --simple
```

首次运行会自动检测依赖并安装。TypeScript 自动启动 Python 子进程，无需手动管理。

---

## 架构

```
┌──────────────────────────────────────┐
│  bun run dev (单命令)                 │
│                                      │
│  TypeScript TUI (主进程)              │
│  │ Ink+React · Cursor · 94 命令      │
│  │ stdin/stdout JSON-RPC             │
│  ▼                                   │
│  Python 子进程                        │
│  │ LLM · 61 工具 · 会话 · MCP        │
│  └───────────────────────────────────│
│  无需 WebSocket · 无需端口 · 零配置    │
└──────────────────────────────────────┘
```

### 模块地图

```
orca-ts/src/                     ← TypeScript 前端
├── app.tsx         主 TUI (FullscreenLayout + Cursor)
├── useChat.ts      RPC 流式钩子
├── commands.ts     94 斜杠命令
├── Cursor.ts       不可变光标类
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
