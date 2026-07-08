# Orca Code 安装指南

## 系统要求

- Windows 10/11
- Python 3.11+
- 网络连接（首次安装依赖需要）

## 安装

### 方式 1：ZIP 下载（推荐，不需要 Git）

1. 打开 [GitHub 仓库](https://github.com/cffgdhtrxf/orca-code)
2. 点击绿色 `Code` 按钮 → `Download ZIP`
3. 解压到任意目录
4. 双击 `start.bat` — 自动完成：创建虚拟环境 → 安装依赖 → 创建配置 → 启动
5. 首次启动会提示输入 DeepSeek API 密钥

### 方式 2：Git Clone

```bash
git clone https://github.com/cffgdhtrxf/orca-code.git
cd orca-code
python -m venv .venv
.venv\Scripts\pip install -e .
python orca_code.py
```

### 更新

双击 `update.bat` 自动从 GitHub 拉取最新版本。
- 不需要安装 Git
- 使用 Windows 内置 PowerShell 下载和解压
- 保留 `config.json`、`.venv`、`memory/`、`save/` 等个人数据

### 可选依赖

```bash
# 安装全部功能（含浏览器自动化、GUI 自动化、Office 支持）
.venv\Scripts\pip install -e ".[all]"

# 安装 headroom 上下文压缩（节省 60-95% token）
.venv\Scripts\pip install -e ".[compression]"
# 或在 config.json 中设置 auto_install_deps: true 自动安装
```

## 配置

Edit `config.json`:

```json
{
  "api_key": "sk-your-deepseek-api-key",
  "base_url": "https://api.deepseek.com",
  "model_name": "deepseek-v4-flash",
  "permission_mode": "auto",
  "max_output_tokens": 8192,
  "context_max_tokens": 100000
}
```

Key settings:
- `api_key` — DeepSeek or OpenAI-compatible API key
- `base_url` — API endpoint (default: DeepSeek)
- `model_name` — Model ID (deepseek-v4-flash, gpt-4o, etc.)
- `permission_mode` — `read-only` | `auto` | `yolo`
- `enable_gui_auto` — Enable GUI automation (requires pyautogui)
- `enable_browser_auto` — Enable browser automation (requires playwright)

## Optional Features

### GUI Automation
```bash
pip install pyautogui pygetwindow pyperclip mss rapidocr-onnxruntime
```

### Browser Automation
```bash
pip install playwright
playwright install chromium
```

### Speech Recognition
```bash
pip install vosk sounddevice
# Or for Whisper:
pip install faster-whisper
```

### TTS (Text-to-Speech)
Windows SAPI is used by default. For BERT-VITS2:
```bash
pip install torch torchaudio transformers
```

### Rust Native Acceleration (10-100x search speedup)
```bash
cd orca_native
cargo build --release
# Copy target/release/orca_native.dll to project root
```

## CLI Arguments

```
python orca_code.py --help      Show help
python orca_code.py --version   Show version (v5.1.0)
python orca_code.py --no-mcp    Skip MCP tool loading
```

## Build Standalone EXE

```bash
pip install pyinstaller
pyinstaller orca_code.spec
# Output: dist/orca_code.exe
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ImportError: openai` | `pip install openai` |
| `ImportError: rich` | `pip install rich` |
| `401 Invalid API Key` | Check `api_key` in config.json |
| `404 Model not found` | Check `model_name` in config.json |
| Console garbled | Set terminal to UTF-8 encoding |

## Development

```bash
pip install -r requirements-dev.txt  # includes pytest
python -m pytest tests/ -v           # run tests
```
