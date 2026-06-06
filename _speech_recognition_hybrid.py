"""
混合语音识别：Vosk 实时预览 + Whisper 最终高精度识别
录音一次，双重引擎，取长补短
"""
import os
import sys
import json
import time
import numpy as np
from pathlib import Path

import sounddevice as sd

# ---- 尝试导入两个后端 ----
try:
    from vosk import Model as VoskModel, KaldiRecognizer
    HAS_VOSK = True
except ImportError:
    HAS_VOSK = False

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "600")

SAMPLE_RATE = 16000
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- 模型路径 ----
_VOSK_MODEL_REL = os.path.join("vosk_models", "vosk-model-cn-0.22")
_VOSK_MODEL_ABS = os.path.join(PROJECT_DIR, _VOSK_MODEL_REL)
_WHISPER_MODEL_DIR = os.path.join(PROJECT_DIR, "models", "whisper-large-v3-turbo-ct2")
_WHISPER_MODEL = str(_WHISPER_MODEL_DIR) if os.path.exists(_WHISPER_MODEL_DIR) else "small"


class HybridRecognizer:
    """Vosk 实时预览 + Whisper 最终校正"""

    def __init__(self):
        self.vosk_model = None
        self.vosk_recognizer = None
        self.whisper_model = None
        self.is_initialized = False
        self.sample_rate = SAMPLE_RATE
        self.has_vosk = False
        self.has_whisper = False

    def initialize(self):
        if self.is_initialized:
            return True

        ok = False

        # --- 加载 Vosk ---
        if HAS_VOSK and os.path.exists(_VOSK_MODEL_ABS):
            try:
                print("[提示] 加载 Vosk 模型（实时预览）...")
                original_cwd = os.getcwd()
                os.chdir(PROJECT_DIR)
                try:
                    self.vosk_model = VoskModel(_VOSK_MODEL_REL)
                finally:
                    os.chdir(original_cwd)
                self.vosk_recognizer = KaldiRecognizer(self.vosk_model, SAMPLE_RATE)
                self.vosk_recognizer.SetWords(True)
                self.has_vosk = True
                print("[OK] Vosk 就绪")
                ok = True
            except Exception as e:
                print(f"[提示] Vosk 加载失败: {e}")
                import traceback
                traceback.print_exc()
        elif not HAS_VOSK:
            print("[提示] Vosk 未安装")
        elif not os.path.exists(_VOSK_MODEL_ABS):
            print(f"[提示] Vosk 模型目录不存在: {_VOSK_MODEL_ABS}")

        # --- 加载 Whisper ---
        if HAS_WHISPER:
            try:
                print("[提示] 加载 Whisper 模型（高精度校正）...")
                self.whisper_model = WhisperModel(
                    _WHISPER_MODEL,
                    device="cpu",
                    compute_type="int8",
                    download_root=None,
                )
                self.has_whisper = True
                print("[OK] Whisper 就绪")
                ok = True
            except Exception as e:
                print(f"[提示] Whisper 加载失败: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("[提示] faster-whisper 未安装")

        if not ok:
            print("[错误] 所有语音引擎均不可用")
            return False

        self.is_initialized = True
        return True

    def recognize_from_microphone(self, duration=10, callback=None):
        if not self.is_initialized:
            if not self.initialize():
                return ""

        device_info = sd.query_devices(kind="input")
        print(f"[提示] 录音设备: {device_info.get('name', '未知')}")
        print(f"[提示] 说完自动停止，最长 {duration} 秒，也可 Ctrl+C")
        if self.has_vosk:
            print("[提示] Vosk 实时预览已开启")
        print()

        audio_chunks = []
        vosk_results = []
        block_size = int(SAMPLE_RATE * 0.1)

        # 智能停用参数
        SILENCE_THRESHOLD = 0.008      # RMS 低于此值视为静音
        SILENCE_BLOCKS = 20            # 连续静音 2 秒后停止
        MAX_DURATION = 60              # 最长 60 秒兜底
        if duration > 0:
            MAX_DURATION = duration    # 直接用调用方传入的时长

        speech_started = False
        silent_blocks = 0
        status = "等待说话..."

        try:
            rec_start = time.time()

            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=block_size,
            ) as stream:
                last_vosk_text = ""
                last_display = ""
                while time.time() - rec_start < MAX_DURATION:
                    data, _ = stream.read(block_size)
                    audio_chunks.append(data.copy())

                    rms = np.sqrt(np.mean(data.astype(np.float32) ** 2)) / 32768.0
                    is_speech = rms > SILENCE_THRESHOLD

                    if is_speech:
                        if not speech_started:
                            speech_started = True
                        silent_blocks = 0
                        status = "聆听中..."
                    elif speech_started:
                        silent_blocks += 1
                        remaining = SILENCE_BLOCKS - silent_blocks
                        if remaining > 0:
                            status = f"静音中... {remaining * 0.1:.1f}s 后停止"

                    # Vosk 实时预览 — 只在文本变化时显示
                    vosk_line = ""
                    if self.has_vosk and self.vosk_recognizer is not None:
                        audio_bytes = data.tobytes()
                        if self.vosk_recognizer.AcceptWaveform(audio_bytes):
                            result = json.loads(self.vosk_recognizer.Result())
                            text = result.get('text', '').strip()
                            if text and text != last_vosk_text:
                                vosk_results.append(text)
                                last_vosk_text = text
                                vosk_line = text
                                if callback:
                                    callback(text)
                        else:
                            partial = json.loads(self.vosk_recognizer.PartialResult())
                            partial_text = partial.get('partial', '').strip()
                            if partial_text:
                                vosk_line = partial_text

                    # 一行输出：音量条 + 状态 + Vosk预览（截断防换行）
                    bar_len = 15
                    filled = int(min(rms / 0.05, 1.0) * bar_len)
                    bar = "#" * filled + "-" * (bar_len - filled)
                    prefix = f"[{bar}] {status}"
                    display = prefix
                    if vosk_line:
                        # 预留空间给前缀 + 分隔符 + 终端宽度余量
                        max_text = max(20, 78 - len(prefix) - 6)
                        short = vosk_line if len(vosk_line) <= max_text else "..." + vosk_line[-(max_text - 3):]
                        display += f"  |  {short}"
                    # 只在内容变化时刷新，避免终端闪烁
                    if display != last_display:
                        last_display = display
                        # 填充空格覆盖上一行残余字符
                        print(f"\r{display:<78s}", end="", flush=True)

                    # 检测到足够长的静音 → 自动停止
                    if speech_started and silent_blocks >= SILENCE_BLOCKS:
                        print(f"\n[提示] 检测到停顿，自动停止")
                        break

                # 获取 Vosk 最后的结果
                if self.has_vosk and self.vosk_recognizer is not None:
                    final = json.loads(self.vosk_recognizer.FinalResult())
                    final_text = final.get('text', '').strip()
                    if final_text and (not vosk_results or final_text != vosk_results[-1]):
                        vosk_results.append(final_text)

            print()

        except KeyboardInterrupt:
            print("\n[提示] 用户中断")
        except Exception as e:
            print(f"\n[错误] 录音失败: {e}")
            import traceback
            traceback.print_exc()
            return ""

        if not audio_chunks:
            return ""

        audio = np.concatenate(audio_chunks).flatten().astype(np.float32) / 32768.0
        duration_s = len(audio) / SAMPLE_RATE

        if len(audio) < SAMPLE_RATE * 0.3:
            print("[!] 录音太短")
            return ""

        if self._is_silence(audio):
            print("[!] 未检测到语音")
            return ""

        # Vosk 结果
        vosk_text = " ".join(vosk_results)
        if vosk_text and self.has_vosk:
            print(f"[Vosk 预览] {vosk_text}")

        # 智能跳过 Whisper：Vosk 结果足够可信
        skip_whisper = False
        if vosk_text and self._vosk_confident(vosk_text):
            print("[提示] Vosk 结果可信，跳过 Whisper 校正")
            skip_whisper = True

        whisper_text = ""
        if self.has_whisper and self.whisper_model is not None and not skip_whisper:
            print(f"\n[提示] 录音完成 ({duration_s:.1f}s)，Whisper 校正中...")
            try:
                segments, info = self.whisper_model.transcribe(
                    audio,
                    language=None,
                    beam_size=1,
                    vad_filter=True,
                    vad_parameters=dict(
                        min_silence_duration_ms=500,
                        threshold=0.5,
                    ),
                )
                lang = info.language
                prob = info.language_probability
                print(f"[提示] 语言: {lang} ({prob:.0%})")

                whisper_parts = []
                for seg in segments:
                    t = seg.text.strip()
                    if t:
                        whisper_parts.append(t)
                        print(f"[Whisper] [{seg.start:.1f}s-{seg.end:.1f}s] {t}")

                whisper_text = " ".join(whisper_parts)
            except Exception as e:
                print(f"[提示] Whisper 校正失败，使用 Vosk 结果: {e}")

        if whisper_text:
            final = whisper_text
            print(f"\n[完成] {final}")
        elif vosk_text:
            final = vosk_text
            print(f"\n[完成] {final}")
        else:
            final = ""
            print("[!] 未识别到有效内容")

        return final

    @staticmethod
    def _vosk_confident(text):
        """短句 Vosk 足够可信，无需 Whisper 校正"""
        if not text:
            return False
        # 只有 10 字以内且无重复词的短句才跳过 Whisper
        if len(text) > 10:
            return False
        words = text.split()
        if len(words) >= 4:
            unique = len(set(words))
            if (1.0 - unique / len(words)) > 0.3:
                return False
        return True

    @staticmethod
    def _is_silence(audio):
        """检测音频是否为纯静音"""
        peak = np.max(np.abs(audio)) if len(audio) > 0 else 0
        return peak < 0.005


recognizer = None


def init_speech_recognition():
    global recognizer
    if recognizer is None:
        recognizer = HybridRecognizer()
    if not recognizer.is_initialized:
        recognizer.initialize()
    return recognizer


def speech_to_text(duration=10, callback=None):
    rec = init_speech_recognition()
    return rec.recognize_from_microphone(duration=duration, callback=callback)
