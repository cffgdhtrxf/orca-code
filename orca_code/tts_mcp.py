"""orca_code.tts_mcp — TTS, voice input, MCP protocol."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from orca_code.config import (
    HAS_BERT_VITS2,
    HAS_SPEECH_RECOGNITION,
    HAS_TTS,
    SPEECH_BACKEND,
    WORKING_DIR,
    console,
)

# Speech recognition — three-tier import fallback
init_speech_recognition = None
speech_to_text = None
try:
    from _speech_recognition_hybrid import init_speech_recognition as _init_sp
    from _speech_recognition_hybrid import speech_to_text as _stt
    HAS_SPEECH_RECOGNITION = True
    SPEECH_BACKEND = "hybrid"
except ImportError:
    try:
        from _speech_recognition_vosk import init_speech_recognition as _init_sp
        from _speech_recognition_vosk import speech_to_text as _stt
        HAS_SPEECH_RECOGNITION = True
        SPEECH_BACKEND = "vosk"
    except ImportError:
        try:
            from _speech_recognition_whisper import init_speech_recognition as _init_sp
            from _speech_recognition_whisper import speech_to_text as _stt
            HAS_SPEECH_RECOGNITION = True
            SPEECH_BACKEND = "whisper"
        except ImportError:
            HAS_SPEECH_RECOGNITION = False
            SPEECH_BACKEND = None
            _init_sp = None
            _stt = None

if _init_sp:
    init_speech_recognition = _init_sp
    speech_to_text = _stt

class BertVits2TTS:
    """BERT-VITS2 PyTorch 文本转语音引擎
    
    注意：完整的 BERT-VITS2 需要：
    1. 下载预训练模型权重（G_0.pth, D_0.pth等）
    2. 配置 BERT 模型（chinese-roberta-wwm-ext-large）
    3. 实现文本预处理（分词、拼音转换、音素化）
    4. 加载 VITS 声学模型和声码器
    
    当前为简化框架，实际使用时需要完整实现。
    参考：https://github.com/fishaudio/BERT-VITS2
    """

    def __init__(self, model_dir=None):
        self.model_dir = model_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "bert_vits2_models")
        self.is_initialized = False
        self.device = None
        self.hps = None
        self.net_g = None
        self.tokenizer = None
        self.bert_model = None

    def initialize(self):
        """初始化 BERT-VITS2 模型"""
        if self.is_initialized:
            return True

        try:
            console.print("[yellow][警告] BERT-VITS2 PyTorch 版本需要完整实现[/yellow]")
            console.print("[dim]当前使用简化框架，建议继续使用 Windows SAPI[/dim]")
            console.print("[dim]如需启用完整版，请参考: https://github.com/fishaudio/BERT-VITS2[/dim]")
            return False

        except Exception as e:
            console.print(f"[red][✗] BERT-VITS2 初始化失败: {e}[/red]")
            import traceback
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            return False

    def text_to_speech(self, text: str, output_path: str = None) -> str:
        """将文本转换为语音（需要完整实现）"""
        console.print("[yellow][提示] BERT-VITS2 推理功能尚未完整实现[/yellow]")
        return None
bert_vits2_engine = None
_sapi_speaker_cache = None   # 复用 SAPI SpVoice，避免每次创建销毁
_sapi_chinese_voice = None   # 缓存的中文语音
_sapi_english_voice = None   # 缓存的英文语音
_tts_queue = []
_tts_processing = False
_tts_lock = threading.Lock()
_tts_condition = threading.Condition(_tts_lock)
def _detect_tts_lang(text):
    """简单语言检测：中文 / 英文 / 其他"""
    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')
    english_chars = sum(1 for c in text if c.isascii() and c.isalpha())
    if chinese_chars > english_chars and chinese_chars > len(text) * 0.1:
        return "zh"
    if english_chars > len(text) * 0.3:
        return "en"
    return "other"
def _get_sapi_speaker():
    """获取或创建 SAPI SpVoice（复用避免重复初始化延迟）"""
    global _sapi_speaker_cache, _sapi_chinese_voice, _sapi_english_voice
    import pythoncom
    pythoncom.CoInitialize()
    if _sapi_speaker_cache is not None:
        return _sapi_speaker_cache

    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    speaker.Rate = 0
    speaker.Volume = 100
    _sapi_speaker_cache = speaker

    # 枚举并缓存语言对应的语音
    voices = speaker.GetVoices()
    for voice in voices:
        desc = voice.GetDescription().lower()
        vid = voice.Id.lower()
        if _sapi_chinese_voice is None and ("chinese" in desc or "zh-cn" in vid or "zh" in vid):
            _sapi_chinese_voice = voice
        if _sapi_english_voice is None and ("english" in desc or "en-us" in vid or "en" in vid):
            _sapi_english_voice = voice
    return speaker
def _tts_worker():
    """TTS 工作线程：从队列中取出任务并执行"""
    # [FIX] COM must be initialized on the thread that calls SAPI
    if sys.platform == "win32":
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
    global _tts_processing, bert_vits2_engine

    while True:
        with _tts_condition:
            while not _tts_queue:
                _tts_processing = False
                _tts_condition.wait()
            text = _tts_queue.pop(0)
            _tts_processing = True

        try:
            # 尝试使用 BERT-VITS2 MNN
            if HAS_BERT_VITS2:
                try:
                    if bert_vits2_engine is None:
                        bert_vits2_engine = BertVits2TTS()
                    temp_dir = tempfile.gettempdir()
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    audio_path = os.path.join(temp_dir, f"tts_{timestamp}.wav")
                    result_path = bert_vits2_engine.text_to_speech(text, audio_path)
                    if result_path and os.path.exists(result_path):
                        if sys.platform == "win32":
                            try:
                                import winsound
                                winsound.PlaySound(result_path, winsound.SND_FILENAME | winsound.SND_SYNC)
                            except:
                                os.startfile(result_path)
                        elif sys.platform == "darwin":
                            subprocess.run(["afplay", result_path])
                        else:
                            subprocess.run(["aplay", result_path])
                        continue
                except Exception as e:
                    console.print(f"[dim][提示] BERT-VITS2 失败，回退到 SAPI: {e}[/dim]")

            # 回退到 Windows SAPI（复用 speaker 对象）
            if HAS_TTS:
                try:
                    speaker = _get_sapi_speaker()
                    lang = _detect_tts_lang(text)
                    if lang == "zh" and _sapi_chinese_voice is not None:
                        speaker.Voice = _sapi_chinese_voice
                    elif lang == "en" and _sapi_english_voice is not None:
                        speaker.Voice = _sapi_english_voice
                    speaker.Speak(text, 0)
                except Exception as e:
                    console.print(f"[dim][警告] TTS 失败: {e}[/dim]")
            else:
                console.print("[dim][提示] TTS 不可用，请安装: pip install pywin32[/dim]")
        except Exception as e:
            console.print(f"[dim][错误] TTS 处理异常: {e}[/dim]")
_tts_worker_thread = threading.Thread(target=_tts_worker, daemon=True)
def speak_text(text: str):
    """将文本加入 TTS 队列"""
    with _tts_condition:
        _tts_queue.append(text)
        _tts_condition.notify_all()
def voice_input():
    """Initialize recognizer and capture speech, return transcribed text"""
    if not HAS_SPEECH_RECOGNITION:
        return None
    try:
        rec = init_speech_recognition()
        if not rec or not rec.is_initialized:
            console.print("[red]Voice recognizer init failed[/red]")
            return None
        return speech_to_text(duration=60)
    except Exception as e:
        console.print(f"[red]Voice error: {e}[/red]")
        return None
def _load_mcp_config() -> dict:
    for p in [Path(WORKING_DIR) / ".assistant_mcp.json", Path.home() / ".assistant_mcp.json"]:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("mcpServers", {})
            except Exception as e:
                logging.debug("MCP config read error (%s): %s", p, e)
    return {}
def mcp_call_tool(qualified_name: str, arguments: dict) -> str:
    config = _load_mcp_config()
    if not qualified_name.startswith("mcp_"):
        return f"错误: 无效的 MCP 工具名 {qualified_name}"
    inner = qualified_name[4:]
    sep = inner.find("_")
    if sep == -1:
        return f"错误: 无法解析 MCP 工具名 {qualified_name}"
    server_name = inner[:sep]
    tool_name = inner[sep + 1:]
    server_config = config.get(server_name)
    if not server_config:
        return f"错误: MCP 服务器 '{server_name}' 未配置"

    async def _call():
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(
                command=server_config["command"],
                args=server_config.get("args", []),
                env=server_config.get("env"),
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    parts = []
                    for item in result.content:
                        if hasattr(item, "text"):
                            parts.append(item.text)
                        else:
                            parts.append(str(item))
                    return "\n".join(parts)[:8000]
        except ImportError:
            return "错误: 请安装 mcp 包: pip install mcp"
        except Exception as e:
            return f"错误: MCP 调用失败 - {e}"

    return asyncio.run(_call())
def _enumerate_mcp_tools() -> list:
    config = _load_mcp_config()
    tools = []
    for server_name, server_config in config.items():
        async def _list():
            try:
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client
                params = StdioServerParameters(
                    command=server_config["command"],
                    args=server_config.get("args", []),
                    env=server_config.get("env"),
                )
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        for tool in result.tools:
                            tools.append({
                                "type": "function",
                                "function": {
                                    "name": f"mcp_{server_name}_{tool.name}",
                                    "description": tool.description or f"MCP tool: {server_name}/{tool.name}",
                                    "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                                }
                            })
            except Exception as e:
                logging.debug("MCP tool enum error (server=%s): %s", server_name, e)
        try:
            asyncio.run(_list())
        except Exception:
            pass
    return tools
def init_mcp_tools():
    if "--no-mcp" in sys.argv:
        return []
    from orca_code.tool_registry import TOOL_MAP, TOOLS
    mcp_tools = _enumerate_mcp_tools()
    if mcp_tools:
        for t in mcp_tools:
            TOOLS.append(t)
            name = t["function"]["name"]
            def _make_mcp(_n=name):
                return lambda **kw: mcp_call_tool(_n, kw)
            TOOL_MAP[name] = _make_mcp()
    return mcp_tools
