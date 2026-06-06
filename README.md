 🐋 Orca Code

**用自然语言控制你的 Windows 电脑。**

Orca Code 是一个桌面 AI 智能体，你只需要说话，它就能替你操作电脑——点击按钮、填写表单、打开软件、搜索文件、读写文档、抓取网页……一切自然语言驱动。

```
你说「打开网易云音乐播放我收藏的歌」→ AI 自动搜索→点击→播放
你说「帮我整理下载文件夹，把 PDF 放到 Documents/PDFs」→ AI 自动操作
你说「截图这片区域并 OCR 出文字」→ AI 截图+识别一气呵成
```

> 🎬 ***[演示 GIF 在此 — 看看 Orca Code 的实际操作]*(docs/assets/demo.gif)*

---

## ✨ 核心能力

| 能力 | 你能做什么 |
|------|-----------|
| **GUI 自动化** | 说「打开设置 → 关闭蓝牙」AI 自动点击鼠标、输入文字、操作窗口 |
| **浏览器控制** | 「搜索 Python 异步框架对比并总结」AI 打开浏览器、搜索、阅读、总结 |
| **语音交互** | 直接说话，AI 听懂并执行。支持 TTS 语音朗读回复 |
| **办公处理** | 读/写 Excel、Word；截图 + OCR 提取文字 |
| **代码开发** | Git 操作、代码导航、Python 即时执行、视觉分析 |
| **技能扩展** | 用 Markdown 写技能，AI 自动加载执行，支持定时任务 |
| **长期记忆** | AI 记住你的偏好和对话历史，越用越懂你 |

更具体的 50+ 工具列表参见下方 [工具一览](#-内置工具-50-个)。

---

## 🚀 5 秒快速开始

```bash
# 1. 双击 start.bat（自动安装依赖 + 启动）
# 或手动操作：
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. 编辑 config.json 填入你的 API Key
# 3. 启动
python ultimate_agent.py
```

> **只需一个入口：** `ultimate_agent.py`。所有功能都在这里。

---

## 🔒 隐私与安全

Orca Code 是**本地优先**的桌面智能体：

- **数据不出本机** — 所有对话、记忆、文件操作全在你的电脑上。唯一的网络请求是调用 LLM API
- **完全离线可用** — 搭配 LM Studio / Ollama 等本地模型，可完全断网运行
- **智能拦截** — 自动检测并阻止 `rm -rf /`、`format` 等破坏性命令
- **技能沙箱** — 技能在受限 Python 环境中运行，无法访问文件系统或网络
- **配置文件隔离** — API 密钥仅在 `config.json` (已加入 `.gitignore`)，不会被意外提交

---

## 🏗 架构一览

```
ultimate_agent/              # 主包（12 个模块）
├── main.py                  # 工具注册表 + 主循环
├── session.py               # 会话管理 + LLM API 调用
├── config.py                # 配置加载 + 缓存 + 客户端
├── security.py              # 危险命令检测 + 技能沙箱
├── utils.py                 # 编码检测 + 路径解析 + token 估算
│
├── tools_core.py            # 文件读写、搜索、命令执行
├── tools_automation.py      # GUI 自动化（鼠标/键盘/窗口）
├── tools_web.py             # 网页抓取、搜索、天气、定位
├── tools_office.py          # Excel、Word、截图、OCR
├── tools_dev.py             # Git、代码导航、视觉分析、摄像头
├── tools_skills.py          # 技能系统 + 定时任务调度
├── tts_mcp.py               # TTS 语音合成 + 语音输入
```

---

## ⚙️ 配置

编辑 `config.json`（仅需填写 `api_key` 即可运行）：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_key` | API Key（DeepSeek/OpenAI 兼容） | `sk-your-key` |
| `base_url` | API 端点 | `https://api.deepseek.com` |
| `model_name` | 模型名称 | `deepseek-chat` |
| `enable_gui_auto` | GUI 自动化开关 | `false` |
| `enable_voice` | 语音输入 | `true` |
| `enable_tts` | 语音朗读 | `true` |
| `local_model` | 本地模型模式（无需 API Key） | `false` |
| `tavily_api_key` | Tavily 搜索密钥（可选） | `""` |

> 参考 `config.example.json` 获取完整模板。

---

## 🧰 内置工具 (50+ 个)

### 🖱 GUI 自动化
`gui_click` `gui_type` `gui_move` `gui_hotkey` `gui_press` `window_focus` `find_on_screen`

### 🌐 浏览器控制
`browser_open` `browser_click` `browser_type` `browser_screenshot` `browser_close`

### 📂 文件 & 命令
`execute_command` `read_file` `write_file` `list_files` `search_files` `search_content`

### 📊 办公文档
`read_excel` `write_excel` `read_word` `write_word` `take_screenshot` `ocr_image`

### 🔗 网络 & 搜索
`web_fetch` `read_webpage` `web_search` `get_weather` `get_location`

### 💻 开发 & 代码
`git_status` `git_diff` `git_log` `git_blame` `go_to_definition` `find_references` `analyze_image` `capture_camera` `execute_python`

### 🧩 技能 & 调度
`load_skill` `create_skill` `edit_skill` `list_skills` `load_md_skill` `list_md_skills` `add_task` `list_tasks` `remove_task`

### ⚡ 其他
`get_system_info` `speak_text` `recall_conversation` `update_profile`

---

## ⌨️ 内置命令

| 命令 | 功能 |
|------|------|
| `/help` | 显示帮助 |
| `/voice` | 进入语音输入模式 |
| `/config` | 查看/修改配置 |
| `/skills` | 查看已加载技能 |
| `/memories` | 查看记忆摘要 |
| `/tasks` | 管理定时任务 |
| `/save` | 导出对话记录 |
| `/clear` | 清空当前对话 |
| `/stats` | 会话统计信息 |
| `/think` | 查看上次推理过程 |

---

## 📦 依赖

| 包 | 用途 | 必选 |
|----|------|------|
| `openai` `tenacity` `rich` `requests` | LLM 通信、UI、网络 | ✅ |
| `pyautogui` `pyperclip` `pygetwindow` | GUI 自动化 | ✅ |
| `Pillow` `mss` `rapidocr-onnxruntime` | 截图 + OCR | ✅ |
| `openpyxl` `python-docx` | 办公文档 | ✅ |
| `beautifulsoup4` | 网页解析 | ✅ |
| `faster-whisper` `sounddevice` | 语音识别 | 🟡 可选 |
| `pywin32` `pystray` | TTS + 系统托盘 | 🟡 可选 |
| `playwright` | 浏览器自动化 | 🟡 可选 |

---

## 📄 开源协议

[MIT License](LICENSE)
