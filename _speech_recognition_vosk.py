"""
Vosk 语音识别模块 - 离线中英文语音识别
使用 Vosk Kaldi 模型，完全离线运行
"""
import os
import sys
import json
from pathlib import Path

try:
    from vosk import Model, KaldiRecognizer
    import sounddevice as sd
    import numpy as np
    HAS_VOSK = True
except ImportError:
    HAS_VOSK = False


class VoskSpeechRecognizer:
    """Vosk 离线语音识别器"""
    
    def __init__(self, model_dir=None):
        if model_dir:
            self.model_dir = model_dir
        else:
            # 优先用相对路径（Vosk C++/Kaldi 不支持含中文的绝对路径）
            project_dir = os.path.dirname(os.path.abspath(__file__))
            workspace = os.path.join(os.environ.get('USERPROFILE', 'C:\\Users\\Cffgd'), ".openclaw-autoclaw", "workspace")
            possible_paths = [
                os.path.join("vosk_models", "vosk-model-cn-0.22"),
                os.path.join(project_dir, "vosk_models", "vosk-model-cn-0.22"),
                os.path.join(workspace, "vosk_models", "vosk-model-cn-0.22"),
                os.path.join("vosk_models", "vosk-model-small-cn-0.22"),
                os.path.join(project_dir, "vosk_models", "vosk-model-small-cn-0.22"),
                os.path.join(workspace, "vosk_models", "vosk-model-small-cn-0.22"),
            ]

            # 用相对路径时确保 CWD 切换到项目目录
            original_cwd = os.getcwd()
            os.chdir(project_dir)

            for path in possible_paths:
                if os.path.exists(path):
                    self.model_dir = path
                    break
            else:
                self.model_dir = possible_paths[0]

            os.chdir(original_cwd)
        self.model = None
        self.recognizer = None
        self.is_initialized = False
        self.sample_rate = 16000
        
    def initialize(self):
        """初始化语音识别器"""
        if self.is_initialized:
            return True

        if not HAS_VOSK:
            print("[错误] 未安装 vosk，请运行: pip install vosk")
            return False

        try:
            if not os.path.exists(self.model_dir):
                print(f"[错误] 模型目录不存在: {self.model_dir}")
                print(f"[提示] 请运行 download_vosk_model.py 下载模型")
                return False

            print("[提示] 正在加载 Vosk 语音识别模型...")

            # Vosk C++/Kaldi 底层不能正确处理含中文的绝对路径，
            # 需要确保 CWD 是项目目录以使用相对路径
            project_dir = os.path.dirname(os.path.abspath(__file__))
            original_cwd = os.getcwd()
            os.chdir(project_dir)

            try:
                self.model = Model(self.model_dir)
                self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            finally:
                os.chdir(original_cwd)

            self.is_initialized = True
            print("[OK] Vosk 语音识别器初始化成功")
            return True

        except Exception as e:
            print(f"[错误] 初始化失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def recognize_from_microphone(self, duration=10, callback=None):
        """
        从麦克风识别语音
        
        Args:
            duration: 录音时长（秒），0 表示持续录音直到手动停止
            callback: 回调函数，接收识别结果文本
            
        Returns:
            识别结果文本
        """
        if not self.is_initialized:
            if not self.initialize():
                return ""
        
        result_text = []
        
        try:
            print("[提示] 开始录音... (说话吧)")
            print("[提示] 按 Ctrl+C 停止录音")
            
            with sd.InputStream(
                channels=1,
                dtype="int16",
                samplerate=self.sample_rate,
                blocksize=4096
            ) as stream:
                import time
                start_time = time.time()
                
                while True:
                    # 检查是否超时
                    if duration > 0 and (time.time() - start_time) >= duration:
                        break
                    
                    # 读取音频数据
                    data, overflowed = stream.read(4096)
                    
                    # 转换为字节
                    audio_bytes = data.tobytes()
                    
                    # 送入识别器
                    if self.recognizer.AcceptWaveform(audio_bytes):
                        # 获取完整识别结果
                        result = json.loads(self.recognizer.Result())
                        text = result.get('text', '').strip()
                        
                        if text:
                            print(f"\r[识别] {text}", end="", flush=True)
                            result_text.append(text)
                            
                            if callback:
                                callback(text)
                    else:
                        # 获取部分识别结果
                        partial_result = json.loads(self.recognizer.PartialResult())
                        partial_text = partial_result.get('partial', '').strip()
                        
                        if partial_text:
                            print(f"\r[识别中] {partial_text}", end="", flush=True)
                
                # 获取最终结果
                final_result = json.loads(self.recognizer.FinalResult())
                final_text = final_result.get('text', '').strip()
                
                if final_text and (not result_text or final_text != result_text[-1]):
                    result_text.append(final_text)
                    print(f"\r[识别] {final_text}", end="", flush=True)
                    
                    if callback:
                        callback(final_text)
            
            final_output = " ".join(result_text)
            print(f"\n[完成] 识别结果: {final_output}")
            return final_output
            
        except KeyboardInterrupt:
            print("\n[提示] 用户中断录音")
            final_output = " ".join(result_text)
            print(f"\n[完成] 识别结果: {final_output}")
            return final_output
        except Exception as e:
            print(f"[错误] 录音失败: {e}")
            import traceback
            traceback.print_exc()
            return ""


# 全局识别器实例
recognizer = None


def init_speech_recognition():
    """初始化语音识别"""
    global recognizer
    if recognizer is None:
        recognizer = VoskSpeechRecognizer()
    if not recognizer.is_initialized:
        recognizer.initialize()
    return recognizer


def speech_to_text(duration=10, callback=None):
    """
    语音转文字（便捷函数）
    
    Args:
        duration: 录音时长（秒）
        callback: 回调函数
        
    Returns:
        识别结果文本
    """
    rec = init_speech_recognition()
    return rec.recognize_from_microphone(duration=duration, callback=callback)


if __name__ == "__main__":
    # 测试
    print("=" * 60)
    print("Vosk 语音识别测试")
    print("=" * 60)
    
    rec = init_speech_recognition()
    
    if not rec.is_initialized:
        print("\n请先下载模型并初始化")
        sys.exit(1)
    
    print("\n开始录音测试（10秒）...")
    result = rec.recognize_from_microphone(duration=10)
    
    print(f"\n最终结果: {result}")
