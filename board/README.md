# 板端运行

目标为 ZedBoard / Zynq-7000 的 ARMv7 hard-float Linux（项目使用 ADI Kuiper），需 Python 3、ALSA `arecord`、XVF3800 USB 麦克风。Hy 录音压缩还需系统的 `libmp3lame.so.0`；本包不分发 LAME 库。文件输入不需要麦克风。Windows 不能运行随包 ARM 二进制。

将仓库放到板卡可写的英文路径。在仓库根目录恢复程序权限：

```sh
chmod +x src/voice/bin/* src/voice/*.sh
python3 -B src/voice_app/main.py --audio sample.wav --engine local
```

WAV 使用 16 kHz、单声道 PCM16。录音入口为 `--record`，最长六秒。运行时检查 MemAvailable ≥24 MiB 且 MemAvailable+SwapFree ≥192 MiB；这是原程序的准入阈值，实际余量还受其他进程影响。模型加载后占用应以本机测量为准。

## DeepSeek 直连

通过环境变量提供 `DEEPSEEK_API_KEY`，或以权限 0600 的文件通过 `DEEPSEEK_API_KEY_FILE` 提供。`DEEPSEEK_MODEL` 指定账号可用模型；默认值保留提交版配置。客户端只允许 `https://api.deepseek.com` 或其 `/v1` 路径，不跟随携带密钥的重定向。

```sh
export DEEPSEEK_API_KEY_FILE=/etc/labmate/deepseek.key
python3 -B src/voice_app/main.py --text '解释频率和周期的关系'
```

凭据由运行者自行配置，仓库不附带有效密钥。模型名称和服务可用性以账号实际开通情况为准。

## 电脑转发

串口转发使用板端本地 HTTP `127.0.0.1:8767`、UART 和 Windows 网关。把 `src/pc-relay/source/relay` 内的板端 `board_relay.py`、`protocol.py`、`start_pc_relay.sh` 安装到 `/boot/labmate-control-v2/relay/`，保持该路径以兼容原启动器。为 shell 脚本设置执行权限。

`/etc/labmate/pc-relay.env` 由使用者创建并设置 0600，包含 `LABMATE_RELAY_TOKEN`（至少 24 个 ASCII 字符的随机值）；值按 shell 环境文件语法填写。语音进程设置同一个 token 以及 `LABMATE_CLOUD_RELAY=serial`。启动器通过已登录的 root 串口终端读取 `/etc/labmate/deepseek.key`（0600），将凭据载入电脑进程内存，不在日志中保存密钥。电脑网关与语音客户端的 `DEEPSEEK_MODEL` 须一致。

Windows 端安装 `requirements.txt`，在本仓库目录执行 `src/pc-relay/start-cloud.ps1`。该便捷入口沿用 COM15；其他端口可直接运行 `python src/pc-relay/source/relay/pc_gateway.py --port COMx --key-from-board`。需保证串口已登录板端 shell，且没有其他终端占用。关闭使用 `stop-cloud.ps1`，等待网关正常退出。电脑端细节见[转发说明](../src/pc-relay/README.md)。

Hy ASR 通过同一个转发运行。默认 `--key-from-board` 流程沿用 v09，从板端 `/etc/labmate/hy-asr.key` 读取密钥，文件须归 root 所有、非符号链接、权限 0600。随后执行 `--engine hy`。未配置 Hy 密钥时该通路返回配置错误；本地识别不需要此密钥。Hy 失败时不自动重复请求，可以另行选择本地识别。

本次整理未更改板卡、串口或真实仪器状态。当前公开包没有整机安装脚本，以上操作仅安装和运行语音模块。
