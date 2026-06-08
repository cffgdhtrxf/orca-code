# Orca Code Installation Guide

## Requirements

- Windows 10/11 (primary) or Linux/macOS
- Python 3.11+
- Git (optional, for development)

## Quick Start

```bash
# 1. Clone or download
git clone <repo-url>
cd orca_code

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API key
cp config.example.json config.json
# Edit config.json — set your api_key

# 5. Run
python orca_code.py
```

## Configuration

Edit `config.json`:

```json
{
  "api_key": "sk-your-deepseek-api-key",
  "base_url": "https://api.deepseek.com",
  "model_name": "deepseek-chat",
  "permission_mode": "auto",
  "max_output_tokens": 8192,
  "context_max_tokens": 100000
}
```

Key settings:
- `api_key` — DeepSeek or OpenAI-compatible API key
- `base_url` — API endpoint (default: DeepSeek)
- `model_name` — Model ID (deepseek-chat, gpt-4o, etc.)
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
