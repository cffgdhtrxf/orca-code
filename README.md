# Orca Code

桌面 AI 助手 —— 通过工具调用操控计算机。

## 快速开始

```bash
# 1. 创建虚拟环境 & 安装依赖
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. 编辑 config.json 填入 API Key
# 3. 启动
python ultimate_agent.py
```

或双击 `start.bat`。

## 项目结构

```
ultimate_agent/          # 主包（12 模块）
├── config.py            # 配置、全局变量、缓存、客户端
├── utils.py             # 编码检测、路径解析、token 估算
├── security.py          # 危险命令检测、URL 校验、技能沙箱
├── tools_core.py        # execute_command, read/write/list/search 文件
├── tools_office.py      # Excel, Word, 截图, OCR
├── tools_web.py         # 网页抓取, 搜索, 天气, 定位
├── tools_dev.py         # Git, 代码导航, 视觉分析, 摄像头
├── tools_skills.py      # 技能系统 + 定时任务调度
├── tools_automation.py  # GUI 自动化 (点击/输入/热键/窗口/屏幕搜索)
├── tts_mcp.py           # TTS 语音合成, 语音输入, MCP 协议
├── session.py           # 会话管理, 系统提示词, 消息处理, API 调用
├── main.py              # 工具注册表, 用户输入, 主循环
│
ultimate_agent.py        # 兼容入口 (from ultimate_agent import *)
python_repl.py           # 持久化 Python REPL (IPython)
memory_manager.py        # SQLite + FTS5 长期记忆
tray_app.py              # 系统托盘启动器 (Win+Shift+A)
token_counter.py         # DeepSeek tokenizer
```

## 配置

编辑 `config.json`：

```json
{
  "api_key": "sk-your-key",
  "base_url": "https://api.deepseek.com",
  "model_name": "deepseek-chat",
  "enable_think_mode": true,
  "enable_gui_auto": true,
  "enable_voice": true,
  "enable_tts": true,
  "tavily_api_key": "",
  "vision_model": ""
}
```

| 配置项 | 说明 |
|--------|------|
| `api_key` | API Key（DeepSeek / OpenAI 兼容） |
| `base_url` | API 端点 |
| `model_name` | 模型名称 |
| `enable_think_mode` | DeepSeek 思考模式 |
| `enable_gui_auto` | GUI 自动化（鼠标/键盘/窗口） |
| `enable_browser_auto` | Playwright 浏览器自动化 |
| `enable_voice` | 语音输入 |
| `enable_tts` | 语音朗读输出 |
| `tavily_api_key` | Tavily 搜索 API Key |
| `vision_model` | 视觉模型（独立于主模型） |

## 内置工具 (50 个)

### 核心工具
`execute_command` `read_file` `write_file` `list_files` `search_files` `search_content`

### 办公工具
`read_excel` `write_excel` `read_word` `write_word` `take_screenshot` `ocr_image`

### 网络 & 搜索
`web_fetch` `read_webpage` `web_search` `get_weather` `get_location`

### 开发工具
`git_status` `git_diff` `git_log` `git_blame` `go_to_definition` `find_references`
`analyze_image` `capture_camera` `execute_python`

### 技能 & 调度
`load_skill` `create_skill` `edit_skill` `list_skills` `load_md_skill` `list_md_skills`
`add_task` `list_tasks` `remove_task`

### GUI 自动化
`gui_click` `gui_type` `gui_move` `gui_hotkey` `gui_press` `window_focus` `find_on_screen`

### 浏览器自动化
`browser_open` `browser_click` `browser_type` `browser_screenshot` `browser_close`

### 其他
`get_system_info` `speak_text` `recall_conversation` `update_profile`

## 内置命令

| 命令 | 功能 |
|------|------|
| `/help` | 帮助 |
| `/clear` | 清空对话 |
| `/stats` | 会话统计 |
| `/save` | 导出对话 |
| `/cache` | KV 缓存状态 |
| `/think` | 上次思考过程 |
| `/skills` | 已加载技能 |
| `/tasks` | 定时任务 |
| `/memories` | 记忆摘要 |
| `/profile` | 用户画像 |
| `/config` | 查看/修改配置 |
| `/voice` | 语音输入 |
| `exit` | 退出 |

## 架构决策

- **无沙箱限制** — 本地桌面智能体，所有命令/文件操作/URL 访问全部放行，仅拦截 `format` 和 `rm -rf /`
- **PowerShell 优先** — `execute_command` 直接支持 PowerShell，用于 App 启动、注册表查询
- **GUI → UWP** — `gui_type` 使用剪贴板+Ctrl+V（非键盘模拟），`gui_press` 使用 pyautogui.press()
- **文件输出** — 所有截图/生成文件强制输出到 `output/` 目录
- **编码自适应** — `cmd /c` 使用系统编码(GBK)，Python/git 子进程使用 UTF-8

## 依赖

```
openai tenacity rich requests
pyautogui pyperclip pygetwindow  # GUI 自动化
Pillow mss rapidocr-onnxruntime  # 截图 + OCR
openpyxl python-docx              # 办公文档
faster-whisper sounddevice numpy  # 语音识别 (可选)
pywin32 pystray                   # Windows TTS + 托盘 (可选)
playwright                        # 浏览器自动化 (可选)
```
