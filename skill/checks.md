# 检查入口与迁移方法

两个入口为提示工作流和踩坑清单提供配套检查：`verify_evidence.py` 是归档材料自检工具，`run_checks.py` 在临时副本中重跑已有功能回归。提示与踩坑清单可单独阅读；测试入口依赖下表所列工程文件。

<a id="commands"></a>
## 运行位置与依赖

先进入完整交付工程的 `labmate/` 根目录，确认其下有 `skill/`、`src/`、`sim/`。以下命令均从此目录执行：

当前提交目录已包含技能及其工程依赖，直接使用现有 `skill/` 入口即可。提示、清单和归档核验也可单独使用；示例回归读取同一 `labmate/` 下的源码与测试，具体对应关系见 [engineering.md](engineering.md)。

```text
python -B skill/verify_evidence.py
python -B skill/run_checks.py --project-root . --only all --output ../skill-check.json
```

- 证据检查只需 Python 3 标准库，以及本目录完整的 `evidence/`；独立复制技能目录后，从该目录运行 `python -B verify_evidence.py` 也可使用。
- 全量示例回归使用 Python 3、Windows PowerShell 和完整工程；已验证环境为 Windows 11、Python 3.12.14。`--only refresh` 或 `receipts` 不调用 PowerShell；`--only relay` 同时运行 Python 和 PowerShell 测试。
- 测试在临时副本内进行，使用模拟时钟、临时工作区、模拟云端和转发替身；就绪测试仅提取判定函数，不执行启停脚本主体。
- 默认使用系统临时目录；受限时，在回归命令后加 `--work-dir <可写目录>`。输出路径 `../skill-check.json` 位于工程外；多次留档时换用新文件名。

## 入口一：归档证据核验

[`verify_evidence.py`](verify_evidence.py) 读取 [`manifest.json`](evidence/manifest.json)，检查 9 个证据文件的 SHA-256，再检查记录中的失败/修复读数、状态恢复、38 个模型检查点、23 个综合检查、3 次通信回复、25 条带来源摘录，以及两次各 27 项的离线结果。

成功时输出 `PASS: 9 evidence files match SHA-256.` 等说明并返回 0；缺文件、摘要不符或声明结果不一致时输出 `FAIL: ...` 并返回 1。PASS 表示文件摘要与清单一致，且归档中的指定字段和结果符合检查项；原文、采集日期及来源见 [协作记录](collaboration.md) 和 [证据清单](evidence/manifest.json)。该脚本不访问原对话，不独立证明引文真实性，也不重新执行历史实机测试。

迁移此方法时，为自己的证据建立清单、采集日期和摘要，并按本项目的结果结构重写核验项。当前检查器包含 LabMate 的固定文件名、字段和案例数，不能仅改 `--evidence-dir` 就用于另一项目。源文件意外变化时先查原因，不以更新摘要代替排查。

## 入口二：已有代码回归

[`run_checks.py`](run_checks.py) 复制源模块及以下测试到临时目录，在模拟环境中执行。表中路径相对 `labmate/`，`dashboard/` 指 `src/boot/labmate-control-v2/dashboard/`。

| 分组及案例数 | 被检查模块 | 已有测试文件 | 迁移时替换什么，保留什么 |
| --- | --- | --- | --- |
| refresh：5 | `dashboard/polling.py` | [test_refresh_legacy.py](../sim/historical/file_b19f499ecdf0/test_refresh_legacy.py) | 替换调度器、事件标记及模拟时钟接口；保留完成后计时、忙时事件不丢和慢读不补刷的断言 |
| receipts：7 | `dashboard/experiment_summary.py`、`workspace.py` 及导入依赖 | [test_experiment_summary.py](../sim/historical/file_b19f499ecdf0/test_experiment_summary.py) | 替换工作区、作业字段及模拟服务；保留轮次隔离、设置/测量分离、重开与迟到结果的断言 |
| relay-reconnect：4 | `src/pc-background-launcher/run_cloud.py` | [test_relay_runner.py](../sim/test_relay_runner.py) | 替换监督函数、返回码、等待和停止信号；保留失败重试、启动未就绪和人工停止的测试顺序 |
| relay-readiness：11 | `src/pc-background-launcher/start-background.ps1` 的 `Test-RelayReady`；同时检查 `src/pc-relay/start-cloud.ps1` 语法 | [test_relay_startup.ps1](../sim/test_relay_startup.ps1) | 替换进程、服务和日志结构；保留陈旧日志、错误目标、重复进程、重连、退出和停止等就绪反例 |

全量成功输出为：

```text
refresh: PASS (5/5)
receipts: PASS (7/7)
relay-reconnect: PASS (4/4)
relay-readiness: PASS (11/11)
```

程序返回 0 表示所选分组均通过且案例数符合预期。返回 1、`FAIL`、案例数不符或 60 秒超时均表示检查未通过；先读输出中的异常或断言。缺源码说明工程不完整或路径需适配；缺 PowerShell 说明该组环境不满足，不等同于业务逻辑错误。新结果 JSON 包含环境、时间、源文件摘要、每组输出和状态。

外项目优先迁移表中的测试方法，接入自己的测试框架。若复用此运行器，还需一起修改源码复制清单、测试路径、导入目录、案例数和输出匹配规则，保留模拟 I/O 与明确的失败返回。更改案例数必须对应实际新增或调整的测试，不能以改预期数掩盖遗漏。S1、S3 当前使用历史板卡证据核验，新增设备需自行执行对应验收计划。

## 日期与结果归属

- [`evidence/reuse-results.json`](evidence/reuse-results.json)：2026-11-01 归档运行，27 项为 5＋7＋4＋11，受 manifest 摘要保护。
- [`evidence/current-results.json`](evidence/current-results.json)：2026-11-02 从交付工程 ZIP 读取源码后运行，27 项为 5＋7＋4＋11，记录工程 ZIP 与参与回归源码的摘要，受 manifest 摘要保护。
- 复用者的新运行另存 JSON，保留环境、日期和源版本；不覆盖上述历史记录。S1、S3 引用历史板卡记录；27 项离线测试覆盖 S2、S4、S5 的对应工程实现。
