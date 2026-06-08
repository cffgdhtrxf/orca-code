# 🐋 Orca Code v5.0 — 项目分析报告

> 分析日期：2026-06-08 | 版本：v5.0 | 代码量：~6000 行 Python + ~500 行 Rust

---

## 一、定位

**桌面 + 编码全能 AI 代理。** v5.0 从纯桌面自动化代理升级为兼具专业编码能力的混合代理——融合了 Claude Code 的权限模型、CodeWhale 的 Constitution 权威体系、oh-my-pi 的精准编辑引擎。

```
操作优先级: CLI > API > GUI
```

---

## 二、架构

```
┌─────────────────────────────────────────────────────────┐
│                    用户交互层                              │
│  get_user_input() — 键盘 / 语音 / 粘贴 / /命令 / Skill   │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│                  Constitution 层                          │
│  五级权威体系 → System Prompt 前缀 (KV 缓存零成本)       │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│                   权限 & 安全层                            │
│  Layer 0: 始终拦截 (8 条)                                 │
│  Layer 1: 权限系统 (read/write/exec + 3 模式)             │
│  Layer 2: 技能沙箱 (AST 扫描)                             │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│                   会话 & LLM 层                            │
│  sanitize → smart_trim → call_model → process_stream    │
│  Tenacity 重试 · Thinking Mode · Rich Live 流式          │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│                    工具执行层                              │
│  63 工具 TOOL_MAP · 子代理并发 · LSP 诊断 · MCP           │
├──────────────────┬──────────────────────────────────────┤
│  Rust orca_native │         Python 工具                   │
│  · ripgrep 搜索   │  · CLI 工具 (优先)                    │
│  · diff 应用      │  · GUI 工具 (兜底)                    │
│  · 文件遍历       │  · LSP / Git / Office / Web           │
└──────────────────┴──────────────────────────────────────┘
```

---

## 三、模块清单 (15)

| 模块 | 行数 | 职责 |
|------|:----:|------|
| `main.py` | ~1400 | 工具注册表 (63) + 主循环 + 输入处理 |
| `session.py` | ~800 | 会话管理 + Constitution + System Prompt + API + 流式 |
| `config.py` | 535 | 配置加载 + 多 Provider + 余额 + 权限初始化 |
| `permissions.py` | ~240 | 权限系统 (57 工具风险分级 + 3 模式) |
| `security.py` | ~190 | 安全层 (14 条拦截 + SSRF 防护 + 技能沙箱) |
| `constitution.py` | ~60 | 五级权威体系 |
| `lsp.py` | ~350 | LSP 客户端 (pylsp/ts-ls/rust-analyzer/gopls) |
| `subagent.py` | ~230 | 子代理并发引擎 |
| `utils.py` | ~170 | 编码/token/路径/JSON 修复 |
| `tools_core.py` | ~380 | 文件/命令/edit/diff/搜索 |
| `tools_automation.py` | ~310 | GUI + 浏览器自动化 |
| `tools_web.py` | ~310 | 网页/搜索/天气/定位 |
| `tools_office.py` | ~250 | Excel/Word/截图/OCR |
| `tools_dev.py` | ~250 | Git/代码导航/视觉/摄像头 |
| `tools_skills.py` | ~260 | 技能系统 + 定时任务 |
| `tts_mcp.py` | ~290 | TTS/语音识别/MCP |
| **总计** | **~6000** | |

---

## 四、安全架构

### 4.1 权限系统 (Claude Code 风格)

```
Resolution order:
  1. config.json user rules → 最高优先级
  2. Saved choice (~/.orca_permissions.json) → 从上次提示记住
  3. Mode-based auto-approval
     - YOLO:     全部放行
     - AUTO:     READ 放行, WRITE/EXEC 首次询问
     - READ-ONLY: READ 放行, 其余询问
```

### 4.2 始终拦截 (Layer 0)

| 类型 | 模式 | 示例 |
|------|------|------|
| 磁盘破坏 | format, dd of=/dev, mkfs |
| 递归删除 | rm -rf /, rmdir / |
| 远程代码执行 | curl\|bash, wget\|python |
| Fork 炸弹 | :(){ :\|:& };: |
| 系统关机 | shutdown, reboot, halt |

### 4.3 非 YOLO 拦截 (Layer 0.5)

| 类型 | 示例 |
|------|------|
| 提权 | sudo, runas |
| 服务控制 | systemctl stop, sc delete |
| 系统路径写入 | write/cp 到 /etc, /boot, /sys |

---

## 五、技术栈

| 层 | 技术 | 版本 |
|----|------|------|
| 主语言 | Python | 3.12+ |
| 性能引擎 | Rust (PyO3) | 2021 edition |
| LLM SDK | openai | ≥1.0.0 |
| 重试 | tenacity | ≥8.0.0 |
| UI | Rich | ≥13.0.0 |
| GUI 自动化 | pyautogui, pyperclip, pygetwindow | — |
| 截图 | mss, Pillow | — |
| OCR | RapidOCR (ONNX Runtime) | — |
| 办公 | openpyxl, python-docx | — |
| 网页解析 | BeautifulSoup4 | — |
| 语音识别 | Whisper / Vosk / Sherpa-ONNX | — |
| TTS | Windows SAPI | — |
| 浏览器 | Playwright (Chromium) | — |
| Rust 依赖 | grep-searcher, grep-regex, ignore, pyo3, similar | — |

---

## 六、关键指标

| 指标 | v4.0 | v5.0 |
|------|:----:|:----:|
| 模块数 | 12 | **15** |
| 工具数 | 50 | **63** |
| Python 行数 | ~5000 | ~6000 |
| Rust 行数 | 0 | **~500** |
| 安全层级 | 1 | **3** |
| 权限模式 | 无 | **3** |
| 编码工具 | 基础 | **edit/diff/LSP** |
| 子代理 | 无 | **并发 5** |
| Constitution | 无 | **五级** |
| TUI 渲染 | ANSI | **Rich Live** |
| config.py | 708 行 | **535 行** |
| 测试用例 | 20 | 20 (安全) |

---

## 七、工具分类统计

| 类别 | 数量 | 工具 |
|------|:----:|------|
| 核心 | 9 | execute_command, read_file, write_file, edit_file, apply_diff, list_files, search_files, search_content, get_system_info |
| LSP | 3 | lsp_diagnostics, lsp_references, lsp_definition |
| 子代理 | 3 | agent_open, agent_eval, agent_close |
| GUI | 7 | gui_click/type/move/hotkey/press, window_focus, find_on_screen |
| 浏览器 | 5 | browser_open/click/type/screenshot/close |
| 办公 | 6 | read/write_excel, read/write_word, take_screenshot, ocr_image |
| 网络 | 5 | web_fetch, read_webpage, web_search, get_weather, get_location |
| Git | 4 | git_status, git_diff, git_log, git_blame |
| 代码 | 5 | go_to_definition, find_references, analyze_image, capture_camera, execute_python |
| 技能 | 9 | load/create/edit/list_skill, load/list_md_skill, add/list/remove_task |
| 记忆 | 3 | recall_conversation, update_profile, speak_text |
| MCP | 4 | mcp_* |
| **总计** | **63** | |

---

## 八、优缺点

### 优势

1. **独有定位**：唯一同时覆盖桌面自动化和专业编码的开源代理
2. **安全不烦人**：Claude Code 风格——首次问一次就记住，不逐次审批
3. **Rust 加速**：代码搜索和 diff 应用 10-100x 性能提升
4. **Constitution**：形式化权威层级，模型不再猜测优先级
5. **Windows 原生**：PowerShell/注册表/SAPI/COM 深度集成
6. **离线可用**：LM Studio/Ollama 本地模型 + Vosk 离线语音

### 待改进

1. **测试覆盖不足**：仅安全模块有 20 个测试用例，核心业务逻辑缺测试
2. **Rust 编译门槛**：需要本地 Rust 工具链，非开发者难以编译
3. **LSP 依赖外部**：需用户自行安装 pylsp/ts-ls/rust-analyzer
4. **浏览器依赖重**：Playwright + Chromium ~200MB
5. **config.py 仍有改善空间**：去重后 535 行但仍混杂配置/基础设施/工具函数
6. **macOS/Linux 支持有限**：GUI 自动化和语音深度绑定 Windows API

---

## 九、总结

Orca Code v5.0 完成了从"桌面自动化工具"到"桌面+编码全能代理"的蜕变。通过融合其他三个顶级 AI 编码代理的核心设计（Claude Code 权限模型、CodeWhale Constitution、oh-my-pi 编辑引擎），加上 Rust 原生性能引擎，它现在在功能广度上是独一无二的——既能操作任意 Windows 桌面软件，又能像专业 IDE 一样诊断代码、精确编辑、并发执行子任务。
