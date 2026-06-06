# TTS 语音朗读使用指南

## 当前状态

### ✅ 已启用：Windows SAPI（系统自带语音）
- **音质**：标准（取决于系统语音包）
- **速度**：快速
- **稳定性**：非常稳定
- **语言支持**：中文、英文等（取决于系统安装的语音包）

### ⏸️ 已下载但未启用：BERT-VITS2-MNN
- **原因**：MNN 模型需要专用的推理代码和文本预处理流程
- **模型大小**：1.3 GB（已下载完成）
- **位置**：`C:\Users\Cffgd\bert-vits2-MNN`
- **计划**：后续找到正确的使用方法后启用

---

## 快速开始（Windows SAPI）

### 1. 安装依赖

```bash
pip install pywin32
```

**注意**：不需要安装 MNN、numpy、modelscope，因为当前使用 Windows SAPI。

### 2. 检查系统语音包

Windows 10/11 通常自带中文语音包。检查方法：
1. 打开 **控制面板** → **语音识别** → **文本到语音转换**
2. 查看“语音选择”中是否有中文语音（如 "Microsoft Huihui Desktop - Chinese (Simplified)"）
3. 如果没有，可以在线下载更多语音

### 3. 运行程序

```bash
python new.py
```

### 4. 测试 TTS

在程序中输入：
```
/tts
```

会播放测试语音：“你好，这是 Windows SAPI 语音合成测试”

## 功能说明

### 自动语音朗读

- **默认行为**：每次 AI 回复后，系统会自动用 Windows SAPI 朗读回复内容
- **后台执行**：朗读在后台线程中进行，不会阻塞主程序
- **智能分段**：长文本按句子分割，最多朗读前2段（约300字符）
- **同步模式**：确保完整朗读，不会被新对话中断

### 手动测试 TTS

在程序中输入 `/tts` 命令：
- 播放测试语音：“你好，这是 Windows SAPI 语音合成测试”
- 验证 TTS 功能是否正常

### 回退机制

当前仅使用 Windows SAPI，无需回退。

## 常见问题

### Q1: 没有声音

**检查：**
1. 系统音量是否正常
2. 默认播放设备是否正确
3. Windows SAPI 是否正常工作（控制面板 → 语音识别 → 文本到语音转换）
4. 是否安装了中文语音包

**解决：**
- 在控制面板中测试语音
- 下载更多语音包：设置 → 时间和语言 → 语音 → 添加语音

## 高级配置

### 调整语音参数

在 `speak_text` 函数中可以调整：
- **语速**：修改 `speaker.Rate` (-10 到 10，0 为正常)
- **音量**：修改 `speaker.Volume` (0 到 100)
- **语音选择**：修改语音选择逻辑，指定特定语音

### 禁用自动朗读

如果不需要自动朗读，可以注释掉 `main()` 函数中的朗读代码：

```python
# if HAS_TTS and answer.strip():
#     speak_text(clean_text)
```

## 技术细节

### Windows SAPI

- **接口**：SAPI.SpVoice COM 组件
- **同步模式**：使用 `Speak(text, 0)` 确保完整朗读
- **COM 初始化**：在多线程中必须调用 `pythoncom.CoInitialize()`
- **语音选择**：自动选择中文语音（如果可用）

### 音频参数

- **采样率**：由系统语音包决定（通常 22050 Hz 或 44100 Hz）
- **位深度**：16-bit PCM
- **声道**：单声道
- **格式**：实时合成，不生成文件

### 性能优化

- **同步模式**：确保朗读完成后再返回，避免中断
- **状态跟踪**：使用 `_tts_speaking` 标志防止并发朗读
- **线程锁**：保护共享状态，确保线程安全
- **后台执行**：在 daemon 线程中运行，不阻塞主程序
- **智能分段**：长文本按句子分割，提高稳定性

## 故障排除

如果遇到任何问题，请：

1. **检查依赖是否安装**：
   ```bash
   pip list | findstr "pywin32"
   ```

2. **测试 Windows SAPI**：
   - 打开控制面板 → 语音识别 → 文本到语音转换
   - 输入测试文本，点击“预览语音”
   - 确认能听到声音

3. **运行测试命令 `/tts`** 查看详细错误信息

4. **查看控制台输出的完整错误堆栈**

## 更多信息

- **Windows SAPI 文档**：https://docs.microsoft.com/en-us/previous-versions/windows/desktop/ms723627
- **MNN 官方文档**：https://www.yuque.com/mnn/en
- **BERT-VITS2 项目**：https://github.com/fishaudio/BERT-VITS2
- **ModelScope BERT-VITS2-MNN**：https://www.modelscope.cn/models/MNN/bert-vits2-MNN
