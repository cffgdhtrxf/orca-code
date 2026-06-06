"""
详细诊断语音识别流程
"""
import os
import numpy as np
import sounddevice as sd
import sherpa_onnx
import time

print("=" * 80)
print("语音识别详细诊断")
print("=" * 80)

# 模型路径
model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sherpa_onnx_models")

encoder = os.path.join(model_dir, "encoder-epoch-99-avg-1.onnx")
decoder = os.path.join(model_dir, "decoder-epoch-99-avg-1.onnx")
joiner = os.path.join(model_dir, "joiner-epoch-99-avg-1.onnx")
tokens = os.path.join(model_dir, "tokens.txt")

print("\n检查模型文件:")
for name, path in [("编码器", encoder), ("解码器", decoder), ("连接器", joiner), ("词表", tokens)]:
    if os.path.exists(path):
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"  ✓ {name}: {size_mb:.1f} MB")
    else:
        print(f"  ✗ {name}: 不存在")

if not all(os.path.exists(f) for f in [encoder, decoder, joiner, tokens]):
    print("\n❌ 模型文件不完整")
    exit(1)

# 创建识别器
print("\n正在初始化识别器...")
sample_rate = 16000
samples_per_read = int(0.1 * sample_rate)  # 100ms

recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
    encoder=encoder,
    decoder=decoder,
    joiner=joiner,
    tokens=tokens,
    num_threads=2,
    sample_rate=sample_rate,
    feature_dim=80,
    decoding_method="greedy_search",
    max_active_paths=4,
    enable_endpoint_detection=True,
    rule1_min_trailing_silence=2.4,
    rule2_min_trailing_silence=1.2,
    rule3_min_utterance_length=300,
)

print("✓ 识别器初始化成功")

# 创建流
stream = recognizer.create_stream()

result_texts = []
audio_block_count = 0
total_samples = 0

def audio_callback(indata, frames, time_info, status):
    global audio_block_count, total_samples
    
    if status:
        print(f"[警告] {status}")
    
    audio_block_count += 1
    samples = np.ascontiguousarray(indata.reshape(-1), dtype=np.float32)
    total_samples += len(samples)
    
    # 打印音频数据统计
    if audio_block_count <= 5 or audio_block_count % 10 == 0:
        max_val = np.max(np.abs(samples))
        mean_val = np.mean(np.abs(samples))
        print(f"[音频块 #{audio_block_count}] 帧数={frames}, 最大值={max_val:.4f}, 平均值={mean_val:.4f}")
    
    # 送入流
    stream.accept_waveform(sample_rate, samples)
    
    # 解码
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    
    # 获取结果（每次都尝试）
    try:
        result = recognizer.get_result(stream)
        text = result.text.strip() if hasattr(result, 'text') else str(result).strip()
        
        if text:
            print(f"\r[识别结果] '{text}'", end="", flush=True)
            
            if not result_texts or text != result_texts[-1]:
                result_texts.append(text)
    except Exception as e:
        print(f"\n[错误] get_result失败: {e}")
    
    # 检查端点
    is_endpoint = recognizer.is_endpoint(stream)
    if is_endpoint:
        print("\n[提示] 检测到语音结束")

print("\n" + "=" * 80)
print("开始录音测试（5秒）")
print("请对着麦克风清晰地说话！")
print("=" * 80)
print("[提示] 按 Ctrl+C 停止\n")

start_time = time.time()

try:
    with sd.InputStream(
        channels=1,
        dtype="float32",
        samplerate=sample_rate,
        callback=audio_callback,
        blocksize=samples_per_read
    ):
        sd.sleep(5000)  # 录音5秒
        
except KeyboardInterrupt:
    print("\n[提示] 用户中断")

elapsed = time.time() - start_time

# 最终统计
final_text = " ".join(result_texts)
print(f"\n\n{'=' * 80}")
print(f"[统计信息]")
print(f"  录音时长: {elapsed:.2f} 秒")
print(f"  音频块数量: {audio_block_count}")
print(f"  总采样点数: {total_samples}")
print(f"  识别到的文本片段数: {len(result_texts)}")
print(f"  最终识别结果: '{final_text}'")
print(f"{'=' * 80}")

if len(result_texts) == 0:
    print("\n⚠️  未识别到任何文本！可能的原因：")
    print("   1. 麦克风音量太小 - 请调大系统音量或靠近麦克风")
    print("   2. 环境噪音太大 - 请在安静环境中测试")
    print("   3. 说话不够清晰 - 请清晰、缓慢地说话")
    print("   4. 模型问题 - 可能需要重新下载模型")
else:
    print(f"\n✅ 识别成功！共识别到 {len(result_texts)} 个文本片段")
