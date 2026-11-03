# 本地语音运行模块

`source/v8_2` 保存当前常驻服务，`source/runtime_v8_1` 与 `source/original_v8` 为复用的前端、解析器及构建依赖。`models/asr` 包含量化模型与外置权重，`models/asr_external` 是构建阶段的对应布局。`bin` 为提交版 ARMv7 程序，`reports` 为原始构建及评测记录。去重保存的文件已按提交版 runtime manifest 恢复为独立文件。

`fpga` 是原项目目录名，所含前端、意图权重、策略和整数参考源码服务于现有 ARM 实现；本公开版不附带语音 PL 工程或 bitstream。

从仓库根目录运行 `python3 -B src/voice_app/main.py --audio sample.wav --engine local`。原生服务提供 `warmup.sh`、`status.sh`、`stop.sh`，每次仅操作本目录的服务。[环境与运行](../../board/README.md)、[重新编译](../../build/README.md)、[模型许可](../../licenses/README.md)。
