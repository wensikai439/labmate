# 工程对应与复现边界

本目录的复用单位是提示工作流和踩坑清单。以下映射帮助使用者把示例、证据和工程实现对上；所需源码、程序、模型与测试位于同一提交目录，基础系统和外部依赖按部署说明准备。本文路径相对当前 `labmate/` 根目录；`dashboard/` 简写为 `src/boot/labmate-control-v2/dashboard/`。

## 当前使用入口

技能已位于 `labmate/skill/`。在当前 `labmate/` 根目录按 [checks.md](checks.md) 执行核验与示例回归，脚本直接读取本目录中的工程文件。新结果另存到工程目录外，并保留运行环境、日期与源码摘要。

## 历史验证来源

2026-11-02 的归档回归读取了当时的 `v20261101_09/工程包.zip`；该历史 ZIP 的 SHA-256 为：

```text
cb63ccf158b2afab39323fa8d7a07bfb72bcef77fdda5f0b822cf3140d5d40a5
```

该次回归记录见 [current-results.json](evidence/current-results.json)，其中保存当时工程 ZIP 与参与运行源码的摘要；11 月 1 日结果单独保留。上述 ZIP 名称和摘要用于追溯历史验证，当前复现直接使用现有工程目录。

## 五项技能与实现

| 技能 | 实际代码和状态含义 | 对应验证与边界 |
| --- | --- | --- |
| S1 | `src/boot/labmate-control-v2/src/channel_control.c` 的 `complete()`、`prepare_afg_modes()`、`set_afg_parameters()` 分段完成、查错、回读；AFG 分支使用 `*WAI` 后查错及状态回读，其他分支使用 `*OPC?`，不能统一套用设备命令。`dashboard/control.py` 的 `NativeRunner` 核对执行回执，`Controls.run()` 保存验证状态并通知刷新 | `old-reproduction.json` 与 `candidate-hardware.json` 是 10 月 30 日旧失败及修正后实机归档；`local-test-results.json` 是当时测试摘要，不是本次重新跑出的结果 |
| S2 | `dashboard/polling.py` 调度完成后计时及事件；`server.py` 的 `status_snapshot()` 在同一快照中为全部设备填入共享 `round_age`、`round_revision`，并另算单台 `age`；`app.js` 使用共享时间显示，变化字段触发绿色高亮；`instruments.py`、`panel.py` 处理读数和状态 | 5 项离线测试只验证调度。及时回读、三卡/底部时间及高亮依据历史 `ui_checks`；移植后仍需按 S2 步骤观察实际界面 |
| S3 | `dashboard/asr_engine.py` 的 `Engine` 管理模式；`voice.py` 管理录音与识别任务，`model_runtime.py` 的 `ModelRuntime` 管理模型子进程；`guide_resources.py` 的 `GuideResources.lease()` 在文档处理期间释放所属模型，恢复失败保留 `recovery_needed`，本地语音在下次请求按需加载；视觉入口为 `student_vision.py` | 38 个模型检查点及 23 项综合检查是 10 月 28 日板卡记录；电脑离线核验不加载 ARM 模型，不代表重测延迟、内存或识别精度 |
| S4 | `control.py` 在作业创建时记录 `job.workflow_run`；`experiment_summary.py:evidence()` 按 `workflow.run_id` 筛选，以成功且 `result.verified is True` 标记可信回执，失败项不附可信 `after`；`local()` 按操作类型提取测量，云端 `operations` 与 `current_settings` 分开；`current(token)`、`workspace.py:save_summary()` 核对 `completed` 和 `summary.id` | 7 项模拟测试覆盖回执归属、持久化重启、重复请求、迟到响应、云端失败及旧对话隔离。总结令牌与轮次标识职责不同，源码没有 `summary.run_id` 字段 |
| S5 | `src/pc-background-launcher/run_cloud.py` 的后台监督循环负责退出后延迟重连及人工停止；`start-background.ps1:Test-RelayReady` 检查任务、唯一正确进程、本轮 PID/日志及停止状态；`src/pc-relay/start-cloud.ps1` 是现场启动入口 | 4 项 Python 替身测试＋11 项 PowerShell 判定案例；`ds-reconnect.json` 是 11 月 1 日三次真实链路回复，前后持久化摘要一致且未控制仪器。本次不执行启停入口 |

## 模型和板端运行前置条件

这些是核对配套工程时的默认值与依赖，不是跨项目通用参数。复用技能本身不要求部署板卡；确需复现实机示例时，按工程提供的完整文档准备环境。

- 系统为 ZedBoard / Kuiper GNU/Linux 11.2、ARMv7 hard-float、Python 3.9.2。新卡基础镜像、依赖、桌面和 256 MiB 应用交换文件见 [board/system_setup.md](../board/system_setup.md)；设备连接、服务和启动检查见 [board/README.md](../board/README.md)。Windows 离线回归已验证 Python 3.12.14＋PowerShell，不能用该环境替代板端运行环境。
- 存档路径采用小写，Linux 原运行路径保留大小写。先按上述文档使用 `build/restore_runtime.py` 和 `board/runtime_manifest.json` 校验并恢复，再安装；不能将小写模型目录直接当运行目录。`server.py` 默认语音根为 `/boot/labmate-control-v2/SmartBox_ZedBoard_Voice_V8_2_20261022`（可由 `LABMATE_VOICE_DIR` 替换），视觉根为同目录的 `LabMate_Vision_V2_20261022`。模型二进制和模型文件均来自配套工程；本包不提供替代模型。
- 语音运行器调用模型根下 `bin/smartbox_asr_resident --server <root>/models/asr`。录音输入由 `voice.py:validate_wav()` 检查：16 kHz、单声道、PCM16、完整 WAV、0.1—6 秒且文件不超过 400000 字节。输入时长和完整采集均需满足，不能只在界面停表。
- 默认 `active=desired='hy'`，实际状态经 `asr_engine`、`asr_requested`、`asr_ready`、`asr_switching` 暴露；BTN8 / PB1 / MIO50 切换。选择本地后等待资源空闲并加载常驻模型，切回 Hy 释放本地模型；失败不冒充切换成功。指导书处理释放语音和视觉所属进程，完成后保留选中模式，本地模型下次请求再加载。
- 模型准入要求可用物理内存至少 24 MiB，且加空闲交换空间至少 192 MiB；指导书租约释放模型后检查物理可用内存至少 192 MiB，恢复视觉前要求至少 `max(256, 所属视觉进程组RSS向上取MiB＋96)` MiB。这些是不同入口的保护线，须结合实际峰值重新确定。
- 首次运行必须建立 `/etc/labmate/pc-relay.env`，本地识别也需要该服务配置；云端还需 DS 与 Hy 各自 API key，凭据不随包提供。生成配置、权限、登录 root shell、释放串口和电脑转发步骤见 [board/config/credentials.md](../board/config/credentials.md) 与 [board/README.md](../board/README.md)。端口 COM15 为本工程默认值，使用前核对现场占用；维护按现有停/启脚本等待释放并恢复唯一转发进程。

## 结果怎样复用

先运行 [checks.md](checks.md) 的离线入口，核对实际输出与预期数；再根据 S1—S5 的输入表替换自己工程的协议、任务标识、事件和资源所有者。保留原始失败、修改和新验证结果的对应关系。需要新实机证据的检查项另行安排，不用离线 PASS 填补硬件、界面或模型测试。
