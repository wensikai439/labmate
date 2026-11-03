# 语音验证与回放

以下为语音 V8.2 的数据、原评测方法与本次检查。表中的 `reports/` 相对于 `src/voice/`；历史计时不作为本次板卡实测。


数据为 Qwen3-TTS 生成的 SmartBox 合成指令集，包含 `smartbox_synthetic_voice_v2_20261003` 和 `smartbox_synthetic_contrastive_v3_20261003`。原音频为 24 kHz、单声道 PCM16，使用 torchaudio 重采样至 16 kHz 后四舍五入回 PCM16。前端为 80 维 Kaldi fbank，25 ms 窗、10 ms 帧移、povey 窗、预加重 0.97、dither 0。

划分为 train 14046、calibration 1283、dev 412、test 415。dev/test 使用 `phrase_partition` 做文本划分；calibration 从 train 按说话人 ID 的 SHA-256 切出 8%。dev 音色为 v2voice-00/11/20/31，test 为 01/10/21/30。

|结果|输入与比较对象|环境及含义|
|---|---|---|
|`reports/service_validation.json`|dev+test 共 827 条，原音频及 VAD 切分共 1654 次；V8.2 常驻服务与 V8.1 比较|x86 原生回放，输出差异 0、加载模型 1 次；衡量服务一致性|
|`reports/arm_benchmark.json`|`probe_samples.json` 前三条，时长 1.52/2.48/4.00 秒，每条各运行 3 次取中位数|QEMU Cortex-A9，比较 V8.1 与 V8.2 的程序耗时|
|`reports/interaction.json`|固定麦克风回放|电脑端交互流程检查|

三条计时输入的 ID 为：

- `v2p-aa2e3761b1f67db7--v2voice-00`：读取波形频率。
- `v2p-2bc4f0e936dd481c--v2voice-00`：请查询信号发生器的型号。
- `v2p-bbd5fd87d385d623--v2voice-11`：嗯老师刚才讲了峰峰值的含义。

827 条实际回放音频均保存于 `data/evaluation/voice/audio/`，以无损 FLAC 存储。`audio_index.json` 保存原 WAV 摘要及 RIFF 头尾字节；恢复脚本逐条验证原文件 SHA-256。`original_probe_samples.json` 保存四条原记录，其中最后一条重复第三条，计时脚本取前三条。

`voice/reference_results/` 保存 V8.1 的 dev/test 逐条输出及 V8.2 的 1654 次服务输出。`verify_evaluation_data.py` 根据文本和逐条输出重新计算 CER、VAD 转写变化、服务输出一致性及加载次数。

重新执行语音推理时，使用 [构建说明](../build/README.md) 中的 Linux 工作目录与运行库。将恢复的 827 条 WAV 放到 V8.1 工作目录的 `build/replay16k/`，将本包 `voice/reference_results/v8.1_dev_replay.jsonl`、`v8.1_test_replay.jsonl` 分别放到其 `reports/dev_replay.jsonl`、`reports/test_replay.jsonl`。逐条调用编译后的 `voice_live_host --segment <WAV> <V8.1工作目录>/build/segmented/<partition>/<id>`，生成 VAD 输入。V8.2 的 `source/v8_2/validate_service.py` 使用这些输入及 V8.1 的 resident/vad 输出进行比较；脚本顶部的 `R`、`old`、`client`、`host` 按工作目录设置。该过程使用文件音频。

`benchmark_arm.py` 使用同三条计时输入及 `qemu-arm-static -cpu cortex-a9`；新运行产生的耗时保存在新的结果目录，历史耗时记录保留原环境。原脚本中的 `src/` 对应本包的 `source/v8_2/`。


## 数据与逐条结果检查

在仓库根目录执行：

```sh
python -m pip install -r sim/evaluation_requirements.txt
python -B sim/verify_evaluation_data.py --output evaluation-work/input-checks.json
python -B sim/restore_evaluation_audio.py --output evaluation-work/wav
python -B -m unittest discover -s sim -p 'test_*.py'
```

Windows 启动脚本的无设备测试：

```powershell
powershell -NoProfile -File sim/test_relay_startup.ps1
```

输入检查从保存的逐条结果复算，不运行新模型推理。音频恢复逐个检查 827 条原 WAV 的 SHA-256。测试使用替身验证转发重连和启动，不打开 COM15，不调用付费接口，不操作仪器。

本次结果保存在 [results](results/README.md)。重新推理需 Linux 构建环境或 ARM 板卡；真实麦克风、在线云服务和整机联调未在本次打包过程中重跑。
