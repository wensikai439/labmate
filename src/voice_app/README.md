# 语音与大模型接口

本目录由提交版 dashboard 中的语音组件拆出，保留 `manual_audio`、`xvf3800`、`voice_preview`、`hy_asr`、`mp3_encode`、`model_runtime` 和 `cloud` 的相关实现。`main.py` 是公开版独立入口，`speech_prompt.py` 从原 DS 提示词提炼语音边界，去掉教学内容、视觉与整机操作编排。

```sh
python3 -B src/voice_app/main.py --audio sample.wav --engine local
python3 -B src/voice_app/main.py --record --engine hy --ask
python3 -B src/voice_app/main.py --text '什么是时基'
```

`--ask` 将转写文本交给 DeepSeek；`--text` 直接请求大模型。`--tools schemas.json` 接收调用方提供的 OpenAI 兼容工具定义数组，原样传给 `Cloud.complete`，返回提议而不执行。模型回复属于不可信输入，下游接入方需自行校验工具名、参数范围、实际设备和执行授权。

只有本地识别产生的结果可在网络类故障时原样返回；Hy 请求失败不会自动再次上传或重录，也不会把空的 UNMATCHED 结果称为离线理解。模型进程在独立命令退出时清理；长驻应用可复用 `ModelRuntime` 的 `warmup/request/close` 接口。`voice_preview` 保留录音中的前缀识别支持，独立命令当前只输出最终结果。

配置方法见[板端说明](../../board/README.md)。本公开入口没有 UI、仪器驱动、自动执行器或内容编排服务。
