# PC 云端转发

`source/relay/pc_gateway.py` 转发 DeepSeek 与 Hy ASR 请求；`board_relay.py` 在已登录的板端串口终端提供鉴权的本机 HTTP 接口；`protocol.py` 处理有界分帧和格式校验。公开版去掉了依赖整机界面的 VoiceBridge，只保留语音 API 传输。

Windows Python 环境安装 `python -m pip install -r requirements.txt`。默认 COM15 的隐藏后台入口为 `start-cloud.ps1`，退出入口为 `stop-cloud.ps1`。相邻 `../pc-background-launcher` 实现单实例、日志与断线恢复。首次后台启动会注册当前用户的 `LabMate-Open-DS-COM15` 计划任务，并沿用登录后启动行为；停止文件阻止当前重连，但不删除登录触发器。不得并行打开串口终端。退出可能等待正在处理的请求结束；重连仅恢复会话，不重发业务请求。

配置步骤见[板端运行](../../board/README.md)。默认 `--key-from-board` 从板端受限文件读取 DeepSeek 和 Hy 密钥。未使用该选项时，原网关支持 DeepSeek 环境变量和 Windows 当前用户 DPAPI Hy 凭据；默认便捷启动器采用板端配置。凭据不进入源码和日志。

传输测试见 [sim](../../sim/README.md)。默认模型和端点为 v09 中已有配置，运行者需具有相应服务权限。开源许可不包含云端服务额度。串口网关保留 v09 仪器工具名称白名单；直连接口接受调用方提供的工具定义，串口模式的工具名还需满足 `validate_payload` 中的白名单。
