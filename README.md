# Orca Code

**桌面 AI 编程助手 — 66 工具 · 6 Provider 回退链 · 多代理编排 · 5 层安全沙箱**

一个在终端里运行的 AI 编程助手。能读写文件、执行命令、搜索网页、操控 GUI、调用 LSP——全程由你控制权限。

---

## 快速开始

```bash
git clone https://github.com/cffgdhtrxf/orca-code.git
cd orca-code
双击 start.bat
```

首次运行会自动创建虚拟环境、安装依赖。在 `config.json` 中填入 DeepSeek API Key 即可使用。

> 也支持 OpenAI / Anthropic / 本地模型（Ollama / LM Studio），改 `base_url` + `model_name` 就行。

---

## 和其他工具比

| 能力 | Claude Code | Open Interpreter | Orca Code |
|------|:-----------:|:----------------:|:---------:|
| 内置工具 | ~50 | ~30 | **66** |
| Provider 数量 | 1 | 1 | **6** (含回退链) |
| 多代理编排 | ❌ | ❌ | ✅ parallel / pipeline / judge |
| 生命周期工作流 | ❌ | ❌ | ✅ 35 个 SKILL.md |
| 上下文压缩 | ❌ | ❌ | ✅ 自动触发 + 降级摘要 |
| 安全沙箱 | 内置 | 无 | **5 层** (AST + 子进程 + 权限) |
| 权限模式 | 单一 | 无 | 3 级 (只读 / 自动 / YOLO) |
| 本地模型 | ❌ | ✅ | ✅ |
| MCP 协议 | ✅ | ❌ | ✅ |
| GUI 自动化 | ❌ | ❌ | ✅ |
| Office (Word/Excel) | ❌ | ❌ | ✅ |
| 语音输入/TTS | ❌ | ❌ | ✅ |

---

## 架构

```
用户输入
    │
    ▼
┌─────────────────────────────────────────────┐
│  提示词引擎                                    │
│  Constitution(5+1) + AGENTS.md + SKILL.md    │
│  自动注入 · 动态构建                             │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  Provider 层 (6 适配器)                        │
│  DeepSeek → OpenAI → Anthropic → 本地          │
│  自动回退 + 熔断 + 多 Key 轮换                   │
└─────────────────────────────────────────────┘
    │
    ▼
┌──────────────┬──────────────┬─────────────────┐
│ 66 工具       │ 多代理编排    │ 安全沙箱          │
│ 文件/搜索/Git │ parallel     │ AST 扫描          │
│ GUI/浏览器    │ pipeline     │ 子进程隔离         │
│ Office/OCR    │ judge        │ 权限分级           │
│ LSP/MCP       │ auto_decompose│ URL 白名单       │
└──────────────┴──────────────┴─────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  会话管理                                     │
│  JSONL 持久化 · 上下文压缩 · 记忆系统 · 加密     │
└─────────────────────────────────────────────┘
```

---

## 核心能力

### 工具系统
- **66 个内置工具**：文件读写、内容搜索、命令执行、Git 操作、GUI 操控、浏览器自动化、Office 文档、OCR、LSP 跳转
- **MCP 协议**：自动发现外部工具，扩展无限
- **批量并行执行**：ThreadPoolExecutor，`max_workers` 可配
- **参数验证**：JSON Schema 自动校验 + 截断修复

### 多代理编排
```
coordinator_parallel(["分析 utils.py", "分析 main.py", "审计 security.py"])
    → 3 个子代理并行执行 → 汇总结果

coordinator_pipeline(["需求分析", "方案设计", "代码实现"])
    → 串行执行，每阶段接收上阶段成果

coordinator_judge("设计一个缓存策略", n_solutions=3)
    → 3 个方案并行生成 → Judge 选出最优
```

### 安全模型（5 层）
1. **命令安全检查** — 禁止 `rm -rf /`、`format C:` 等危险操作
2. **权限分级** — 只读 / 自动询问 / YOLO 全放行，按工具粒度可配
3. **URL 安全** — SSRF 防护，内网地址自动拦截
4. **AST 静态扫描** — Skill 代码写入前扫描 eval/exec/metaclass 等危险模式
5. **子进程隔离** — Skill 在独立子进程中执行，超时自动 kill

### Provider 回退链
```
DeepSeek (主) → OpenAI (备1) → Anthropic (备2) → 本地模型 (备3)
     │                │                │               │
     └─ 失败 ─────────┘                │               │
          └──────── 失败 ──────────────┘               │
               └────────── 失败 ───────────────────────┘
```
每个 Provider 独立熔断器，2 分钟内连续失败 3 次自动降级。

### 上下文压缩
Token 用量超 70% 自动触发。三级策略：LLM 智能摘要 → 规则摘要 → 丢弃最旧轮次。保护最近 4 轮不被压缩。

---

## 配置

复制 `config.example.json` 为 `config.json`：

```json
{
  "api_key": "sk-your-deepseek-key",
  "base_url": "https://api.deepseek.com",
  "model_name": "deepseek-v4-flash",
  "permission_mode": "yolo",
  "context_max_tokens": 100000
}
```

| 关键配置 | 说明 |
|---------|------|
| `permission_mode` | `read-only` 仅允许读取 / `auto` 首次询问 / `yolo` 全放行 |
| `enable_think_mode` | DeepSeek 思考模式（推理质量 ↑，速度 ↓） |
| `enable_gui_auto` | 允许 AI 控制鼠标键盘（需二次确认） |
| `enable_browser_auto` | 允许 AI 操控浏览器 |
| `enable_tts` | AI 回复语音朗读 |
| `max_workers` | 并行工具数（建议 3-8） |

---

## 项目结构

```
orca_code/
├── main.py               主循环 + 用户输入
├── session_stream.py     LLM 流式调用 + 重试
├── session_ui.py         Rich 终端渲染
├── session_messages.py   消息净化 + 压缩
├── session_prompt.py     动态系统提示词
├── session_compaction.py 上下文自动压缩
├── tool_registry.py      66 工具注册 + 验证
├── tool_validator.py     JSON Schema 参数验证
├── tool_cache.py         LRU 缓存
├── batch_executor.py     批量并行执行
├── tools_web.py          Web 搜索/抓取/天气/位置
├── tools_office.py       Word/Excel/截图
├── tools_dev.py          LSP/代码分析/视觉
├── tools_core.py         Shell/文件/Git
├── tools_memory.py       记忆/知识图谱
├── tools_skills.py       技能生命周期
├── orchestrator.py       多代理编排
├── subagent.py           子代理执行
├── security.py           5 层安全沙箱
├── permissions.py        3 级权限 + 审计
├── fallback.py           Provider 回退链 + 熔断
├── mcp_client.py         MCP 协议客户端
├── hooks.py              工具前后钩子
├── rollback.py           文件回滚
├── worktree.py           Git worktree 隔离
├── config.py             配置加载 + 客户端工厂
├── providers/            6 Provider 适配器
├── infrastructure/       指标/日志/密钥/更新
└── skills/               35 个 SKILL.md 生命周期工作流
```

---

## 开发

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

---

## License

MIT
