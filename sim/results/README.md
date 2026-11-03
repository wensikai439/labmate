# 本次公开包检查

`package_checks.json` 记录当前公开包的结构、语法、依赖边界与来源摘要检查；`input_checks.json` 复算保存的逐样本评测输出；`audio_restore.json` 记录 827 条 WAV 恢复摘要验证。测试结果另存 `tests.txt`。

这些检查不等价于重新训练、重新交叉编译或板卡实测。原构建与 host/QEMU 测量仍在 `src/voice/reports`，历史整机观察在 `skill/evidence`，保留原时间与环境。
