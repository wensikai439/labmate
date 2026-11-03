# 许可、来源与署名

顶层 [MIT License](../LICENSE) 适用于 LabMate 自有代码、公开版适配和自有文档；允许使用、修改和再分发，保留版权及许可声明。它不覆盖以下第三方材料或云端服务。

|组件|许可与材料|
|---|---|
|ONNX Runtime，静态链接于语音程序|MIT，见 [license](onnxruntime-license) 及 [third-party notices](onnxruntime-thirdpartynotices.txt)|
|WebRTC VAD|保留 [webrtc-vad-license](webrtc-vad-license) 与源码头部声明|
|nlohmann/json|MIT，见 [nlohmann_license.mit](nlohmann_license.mit)|
|WeNet / WenetSpeech 语音模型来源|见下方模型来源及 [CC BY 4.0 全文](cc-by-4.0.txt)，不得将其一概改标 MIT|
|pyserial|BSD-3-Clause；通过依赖安装，不在包内复制其源码|
|LAME|系统动态库，使用方按上游 LGPL 条款安装；本包不分发该库|
|DeepSeek / Hy|仅公开 API 集成代码，不分发服务端模型，不附带服务额度或访问授权|

## 本地语音模型

来源为 WeNet `20220506_u2pp_conformer_exp` / WenetSpeech 10000 小时预训练模型，项目以 SmartBox 合成指令微调，导出 ONNX、动态 INT8 量化，并在 V8.2 使用外置权重。模型名称与配置保留在 `src/voice/models`，原模型署名保留。

WeNet 上游说明预训练模型遵循对应数据集许可：
https://github.com/wenet-e2e/wenet/blob/main/docs/pretrained_models.md

WenetSpeech：Binbin Zhang、Hang Lv、Pengcheng Guo 等，*WenetSpeech: A 10000+ Hours Multi-domain Mandarin Corpus for Speech Recognition*，ICASSP 2022。来源：
https://wenet-e2e.github.io/WenetSpeech/
https://www.openslr.org/121/

上述来源标注 CC BY 4.0，但 WenetSpeech 项目说明同时出现 “non-commercial purposes” 表述，并说明音频权利属于原权利人。此处如实保留该上游限制说明，不替上游消除条款差异，不承诺权重具有无限制商业授权；涉及商业使用应向上游确认。本仓库对模型的转换和微调不改变上游权利。引用、修改和再分发时保留出处、许可及修改说明，不暗示上游认可本项目。

CC BY 4.0 原文来源：https://creativecommons.org/licenses/by/4.0/legalcode.txt 。本目录保留上游许可文本与署名。
