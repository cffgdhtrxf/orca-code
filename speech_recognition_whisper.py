"""
Whisper 语音识别模块 - 使用 faster-whisper (CTranslate2 后端)
高精度离线中英文语音识别，无需 GPU
"""
import os
import sys
import json
import tempfile
import wave
import time
from pathlib import Path

if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "600")

import numpy as np
import sounddevice as sd

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

_MODEL_DIR = Path(__file__).resolve().parent / "models" / "whisper-large-v3-turbo-ct2"
MODEL_SIZE = str(_MODEL_DIR) if _MODEL_DIR.exists() else "small"
SAMPLE_RATE = 16000


class WhisperSpeechRecognizer:
    """faster-whisper 离线语音识别器"""

    def __init__(self, model_size=MODEL_SIZE, device="cpu", compute_type="int8",
                 model_dir=None):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model_dir = model_dir
        self.model = None
        self.is_initialized = False
        self.sample_rate = SAMPLE_RATE

    def initialize(self):
        if self.is_initialized:
            return True

        if not HAS_WHISPER:
            print("[错误] 未安装 faster-whisper，请运行: pip install faster-whisper")
            return False

        try:
            print(f"[提示] 正在加载 Whisper 模型 ({self.model_size}, CPU)...")

            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                download_root=self.model_dir,
            )

            self.is_initialized = True
            print(f"[✓] Whisper 初始化成功")
            return True

        except Exception as e:
            print(f"[错误] 模型加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def recognize_from_microphone(self, duration=10, callback=None):
        if not self.is_initialized:
            if not self.initialize():
                return ""
        if self.model is None:
            return ""

        try:
            audio = self._record(duration)

            if audio is None or len(audio) < self.sample_rate * 0.3:
                print("[!] 录音太短，请至少说 0.3 秒")
                return ""

            duration_s = len(audio) / self.sample_rate
            print(f"\n[提示] 录音完成 ({duration_s:.1f}s)，正在识别...\n")

            segments, info = self.model.transcribe(
                audio,
                language=None,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    threshold=0.5,
                ),
            )

            detected_lang = info.language
            lang_prob = info.language_probability
            print(f"[提示] 检测到语言: {detected_lang} (置信度: {lang_prob:.0%})")

            results = []
            for segment in segments:
                text = segment.text.strip()
                if text:
                    results.append(text)
                    seg_start = segment.start
                    seg_end = segment.end
                    print(f"[{seg_start:.1f}s - {seg_end:.1f}s] {text}")
                    if callback:
                        callback(text)

            final = " ".join(results)
            if not final:
                print("[!] 未识别到有效内容，请尝试：")
                print("    1. 确认麦克风已插好且未静音")
                print("    2. 说话时音量条是否有反应")
                print("    3. 靠近麦克风大声说话")
            else:
                print(f"\n[完成] 识别结果: {final}")

            return final

        except KeyboardInterrupt:
            print("\n[提示] 用户中断")
            return ""
        except Exception as e:
            print(f"[错误] 识别失败: {e}")
            import traceback
            traceback.print_exc()
            return ""

    def _record(self, duration):
        """录音并显示实时音量条"""
        if duration <= 0:
            duration = 60

        device_info = sd.query_devices(kind="input")
        print(f"[提示] 录音设备: {device_info.get('name', '未知')}")
        print(f"[提示] 录音中... 最长 {duration} 秒，说完可提前按 Ctrl+C")
        print("[音量] ", end="", flush=True)

        audio_chunks = []
        block_size = int(self.sample_rate * 0.1)
        peak_rms = 0.0

        try:
            rec_start = time.time()

            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=block_size,
            ) as stream:
                while time.time() - rec_start < duration:
                    data, _ = stream.read(block_size)
                    audio_chunks.append(data.copy())

                    rms = np.sqrt(np.mean(data ** 2))
                    peak_rms = max(peak_rms, rms)

                    bar_len = 25
                    filled = int(min(rms / 0.05, 1.0) * bar_len)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    db = 20 * np.log10(rms + 1e-10)
                    elapsed = time.time() - rec_start
                    remaining = duration - elapsed
                    print(f"\r[音量] [{bar}] {db:+.0f} dB  {remaining:.0f}s  ", end="", flush=True)

            print()

        except KeyboardInterrupt:
            print("\n[提示] 用户中断")
            if audio_chunks:
                return np.concatenate(audio_chunks).flatten()
            return np.array([])
        except Exception as e:
            print(f"\n[错误] 录音失败: {e}")
            import traceback
            traceback.print_exc()
            return None

        if not audio_chunks:
            return None

        audio = np.concatenate(audio_chunks).flatten()
        rms = np.sqrt(np.mean(audio ** 2))
        peak = np.max(np.abs(audio))
        db = 20 * np.log10(rms + 1e-10)
        print(f"[提示] 录音结束 — RMS: {rms:.4f}, 峰值: {peak:.2f}, {db:+.0f} dB")

        if peak < 0.01:
            print("[!] 音量极低，请检查麦克风是否静音或音量设置")

        return audio

    def transcribe_file(self, audio_path):
        if not self.is_initialized:
            if not self.initialize():
                return ""
        if self.model is None:
            return ""

        segments, info = self.model.transcribe(
            audio_path,
            language=None,
            beam_size=5,
            vad_filter=True,
        )
        results = []
        for seg in segments:
            t = seg.text.strip()
            if t:
                results.append(t)
        return " ".join(results)


recognizer = None


def init_speech_recognition(model_size=MODEL_SIZE):
    global recognizer
    if recognizer is None:
        recognizer = WhisperSpeechRecognizer(model_size=model_size)
    if not recognizer.is_initialized:
        recognizer.initialize()
    return recognizer


def speech_to_text(duration=10, callback=None):
    rec = init_speech_recognition()
    return rec.recognize_from_microphone(duration=duration, callback=callback)


if __name__ == "__main__":
    print("=" * 60)
    print("Whisper (faster-whisper) 语音识别测试")
    print(f"模型: {MODEL_SIZE}")
    print("=" * 60)

    rec = init_speech_recognition()

    if not rec.is_initialized:
        print("\n首次运行需要下载模型，请稍候...")
        sys.exit(1)

    print(f"\n录音测试（10秒）...")
    result = rec.recognize_from_microphone(duration=10)
    print(f"\n最终结果: {result}")
