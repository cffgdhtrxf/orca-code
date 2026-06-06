# 语音输入功能使用指南

## 功能说明

已集成 **Sherpa-ONNX streaming-zipformer** 双语语音识别模型，支持：
- ✅ 中英文实时语音识别
- ✅ 流式识别（边说边识别）
- ✅ 离线运行（无需网络）
- ✅ 自动端点检测（说完自动停止）

## 安装步骤

### 1. 安装依赖

```bash
pip install sherpa-onnx sounddevice numpy
```

### 2. 下载语音识别模型

模型大小约 **100 MB**，下载地址：

```
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
```

#### 下载方法一：使用 wget（推荐）

```bash
cd d:\Users\Cffgd\Desktop\智能编码代理
mkdir sherpa_onnx_models
cd sherpa_onnx_models
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
tar xvf sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
```

#### 下载方法二：使用浏览器

1. 点击上面的下载链接
2. 下载完成后解压到 `d:\Users\Cffgd\Desktop\智能编码代理\sherpa_onnx_models\`
3. 确保目录结构如下：

```
sherpa_onnx_models/
└── sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/
    ├── encoder-epoch-99-avg-1.onnx
    ├── decoder-epoch-99-avg-1.onnx
    ├── joiner-epoch-99-avg-1.onnx
    └── tokens.txt
```

## 使用方法

### 在程序中启动语音输入

运行程序后，输入：

```
/voice
```

程序会：
1. 初始化语音识别器
2. 开始录音（10秒或直到检测到静音）
3. 实时显示识别结果
4. 将识别结果作为输入发送给 AI

### 录音提示

- 🎤 **请对着麦克风清晰说话**
- ⏱️ **最长录音 10 秒**
- 🔇 **说完后停顿会自动停止**
- ⌨️ **按 Ctrl+C 可手动停止**

## 示例对话

```
你 > /voice

正在启动语音输入...
请对着麦克风说话（10秒后自动停止）
或按 Ctrl+C 手动停止

[提示] 开始录音... (说话吧)
[识别] 你好
[识别] 你好请帮我写一个Python函数

[完成] 识别结果: 你好 你好请帮我写一个Python函数

[✓] 识别成功: 你好 你好请帮我写一个Python函数
已将识别结果作为输入

────────────────────────────────────────

✻ 
  用户想要我帮他写一个 Python 函数。我需要了解具体要实现什么功能。
  
●   好的！请告诉我你想要这个 Python 函数实现什么功能？例如：
    - 数据处理
    - 文件操作
    - 网络请求
    - 其他特定任务
    
    我会根据你的需求编写相应的代码。
```

## 技术细节

### 模型信息

- **模型名称**: sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20
- **语言支持**: 中文 + 英文（双语）
- **模型大小**: ~100 MB
- **采样率**: 16000 Hz
- **声道**: 单声道
- **实时率**: RTF < 0.3（非常快）

### 工作原理

1. **音频采集**: 使用 `sounddevice` 从麦克风采集音频
2. **特征提取**: 提取 Fbank 特征（80维）
3. **模型推理**: Zipformer 编码器-解码器架构
4. **流式解码**: 贪婪搜索，实时输出结果
5. **端点检测**: 自动检测语音结束

### 性能优化

- **多线程**: 使用 2 个线程进行推理
- **增量解码**: 边录音边识别，低延迟
- **端点检测**: 说完自动停止，无需手动控制

## 常见问题

### Q1: 提示 "未安装 sherpa-onnx"

**解决：**
```bash
pip install sherpa-onnx sounddevice numpy
```

### Q2: 模型文件不存在

**解决：**
按照上面的步骤下载并解压模型到正确位置。

### Q3: 没有声音或识别不准确

**检查：**
1. 麦克风是否正常工作
2. 系统音量是否正常
3. 是否在安静的环境中
4. 说话是否清晰

**建议：**
- 靠近麦克风说话
- 语速适中
- 避免背景噪音

### Q4: 识别速度慢

**可能原因：**
- CPU 性能不足
- 其他程序占用资源

**解决：**
- 关闭不必要的程序
- 考虑使用 GPU 版本（需要 CUDA）

### Q5: 只识别到部分文字

**可能原因：**
- 说话时间超过 10 秒
- 中间停顿太长被判定为结束

**解决：**
- 分段说话
- 或者修改代码增加录音时长

## 高级配置

### 修改录音时长

编辑 `new.py` 中的 `/voice` 命令处理部分：

```python
result = rec.recognize_from_microphone(duration=10)  # 改为想要的秒数
```

### 持续录音模式

修改 `speech_recognition.py`：

```python
result = rec.recognize_from_microphone(duration=0)  # 0 表示持续录音
```

然后按 Ctrl+C 手动停止。

### 更换模型

如果需要纯中文模型（更小更快）：

```
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-zh-2023-03-28.tar.bz2
```

## 更多信息

- **Sherpa-ONNX 官方文档**: https://k2-fsa.github.io/sherpa/onnx/
- **GitHub 仓库**: https://github.com/k2-fsa/sherpa-onnx
- **模型列表**: https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models

## 故障排除

如果遇到问题，请：

1. 检查所有依赖是否安装：
   ```bash
   pip list | findstr "sherpa-onnx sounddevice numpy"
   ```

2. 验证模型文件是否完整：
   ```powershell
   Test-Path "sherpa_onnx_models\sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20\encoder-epoch-99-avg-1.onnx"
   ```

3. 测试麦克风：
   ```python
   python -c "import sounddevice as sd; print(sd.query_devices())"
   ```

4. 运行独立测试：
   ```bash
   python speech_recognition.py
   ```
