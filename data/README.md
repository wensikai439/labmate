# 语音评测数据

`evaluation/voice/audio` 为 827 条 dev/test 无损 FLAC；`audio_index.json` 保存原 WAV 摘要和恢复信息；`replay_manifest.jsonl` 为文本、划分和音频对应关系；`reference_results` 为原 V8.1 与 V8.2 逐条输出。`evaluation/files.json` 为本次公开数据的摘要索引。

数据来自项目使用 Qwen3-TTS 生成的 SmartBox 指令语料，评测音频随项目公开用于复现；不包含完整训练集或 TTS 模型权重。数据划分、合成条件、指标和局限见 [sim/README.md](../sim/README.md)。数据的项目自有部分按顶层 MIT 许可分发，不由此授予第三方声音、模型或商标权利。
