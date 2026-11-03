# LabMate Open — 语音交互与大模型接入

LabMate 是基于 AMD Zynq-7000 / ZedBoard 的嵌入式实验助手。本仓库从 `v20261101_09` 提交版提取语音模块，公开音频采集、本地语音识别与意图结果、Hy 云端转写、DeepSeek 大模型接入和电脑串口转发。语音服务运行在 ARMv7 Linux 上，兼顾小内存环境下的模型驻留与释放。

这是 LabMate 的部分开源版本，内容处理、视觉识别和最终整机界面及控制集成不在公开源码范围内。公开入口返回识别文字、大模型回复或工具调用提议，不直接执行仪器动作。大模型部分公开实际 API 客户端、语音提示词与转发代码；DeepSeek、Hy 的云端模型权重不属于本项目，也未包含在仓库中。

## 功能与实现

- XVF3800 / ALSA 音频采集，单次最长六秒，处理无音频与流中断。
- WeNet / Conformer 本地 ASR，ONNX INT8 模型、外置权重、VAD 与常驻服务；保留原生意图解析结果。
- Hy ASR 云端转写与 DeepSeek 文本、工具调用接口；支持直接联网或 Windows 电脑串口转发。
- 云端网络类失败时，已取得的本地识别结果作为返回结果；不将 API 错误伪装成成功，不重发业务请求。
- dev/test 共 827 条音频、逐样本参考输出和数据复算脚本，保留模型来源与第三方许可。

```text
麦克风 / WAV → 本地 ASR 或 Hy ASR → 识别文本
                                      ↓
                          DeepSeek API → 回复 / 工具调用提议
                          直连或板端 HTTP ↔ UART ↔ Windows 网关
```

## 文件入口

|目录|内容|
|---|---|
|[src/voice](src/voice/README.md)|ASR 源码、模型、ARM 程序与原构建结果|
|[src/voice_app](src/voice_app/README.md)|独立录音、识别和大模型入口|
|[src/pc-relay](src/pc-relay/README.md)|电脑网关、板端转发与启停脚本|
|[build](build/README.md)|Linux 交叉编译、工具链记录与提取映射|
|[board](board/README.md)|目标板运行环境与接口配置|
|[data](data/README.md)、[sim](sim/README.md)|音频、参考结果、复算与测试|
|[skill](skill/README.md)|提交版原始完整 Skill、提示词和真实协作摘录（保持不变）|
|[report/design_report.pdf](report/design_report.pdf)|提交版已有设计报告（保持不变）|
|[licenses](licenses/README.md)|第三方许可、模型来源与署名|

## 使用

板端本地识别（16 kHz、单声道 PCM16 WAV）：

```sh
python3 -B src/voice_app/main.py --audio sample.wav --engine local
python3 -B src/voice_app/main.py --record --engine local --ask
```

大模型文本入口：

```sh
python3 -B src/voice_app/main.py --text '解释峰峰值的含义'
```

运行前的系统依赖、模型权限、云端凭据和串口配置见[板端说明](board/README.md)。数据复算和无设备测试见[验证说明](sim/README.md)，重编译见[构建说明](build/README.md)。

## 竞赛材料与复现边界

本项目为 2026 FPGA 创新设计赛道 AMD 自主选题。公开材料参照题目指南 3.3.5.1—3.3.5.4，提供已有源码、模型与运行文件、评测材料、Skill、设计报告和可再分发许可。文件使用英文路径；按实际模块组织，不将示例目录当作强制模板。

技能包和设计报告按 v09 原文件完整保留，未裁剪、未改写。它们描述整机项目，技能中的完整工程回归入口仍依赖原完整工程，不属于本语音公开包的可运行入口；相应路径引用按原样保留。工程公开范围和新入口以本页及下列工程说明为准。

本仓库可核验语音数据与已有结果，并提供语音程序的构建及运行入口；不包含完整训练集，不复现未公开的整机内容和视觉功能。语音 `fpga` 目录为历史整数参考源码，当前语音推理使用 PS 端 ARM；未把不存在的 PL 综合、实现或上板结果补写为材料。历史 host/QEMU 结果和本次检查分别标注，具体见 [sim/results](sim/results/README.md)。

## 许可证

项目自有代码与文档采用可再分发的 [MIT License](LICENSE)。第三方代码、模型及其来源分别遵循[许可与署名说明](licenses/README.md)，不由顶层 MIT 覆盖。仓库不含服务密钥、账号配置或付费服务访问权。

## 开源说明

本次公开项目的主要语音功能，最终整机形态未完整开源。按指导老师要求开源语音部分。
