# 语音程序构建

源码、模型和预编译 ARMv7 程序取自 v20261101_09。`src/voice/source/v8_2` 是当前服务，`runtime_v8_1` 与 `original_v8` 保存编译依赖。`src/voice/fpga/source` 是沿用历史目录名的整数参考与意图源码，不表示本公开版已完成 PL 加速或提供了综合、时序、资源利用率报告。

构建工作站为 x86-64 Ubuntu 24.04、Python 3.12、GCC/G++ 13.3.0 arm-linux-gnueabihf；目标为 ARMv7-A、NEON、hard-float。ONNX Runtime 固定 v1.22.2 / `5630b081cd25e4eccc7516a652ff956e51676794`，WebRTC VAD 固定 `e283ca41df3a84b0e87fb1f5cb9b21580a286b09`。这些是原构建记录，不是新版本推荐。

## 1. 建立构建目录

在本仓库根目录执行：

```sh
export LABMATE_BUILD="$HOME/labmate-model-build"
python3 -B build/prepare_model_workspace.py \
  --runtime-root . --output "$LABMATE_BUILD"
export V81="$LABMATE_BUILD/audio/v8_1_20261022"
export V82="$LABMATE_BUILD/audio/v8_2_20261022"
```

构建目录须尚未存在，路径使用英文字母、数字、下划线或连字符。准备脚本复制源码与模型，建立前版引用目录，并把工作副本中的原开发机绝对路径改为当前目录。源码包保持原样；映射、调整的文件和模型摘要记录在生成的 `workspace.json` 中。

V8.1 的 `src/vendor/json.hpp`、已生成的 `vad_training_phrases.h`、前版意图源码与 ARM 程序均由脚本放到编译需要的位置。当前程序编译直接使用这些文件。

## 2. 准备开发库

按 [toolchain.md](toolchain.md) 取得工具链安装包并核对版本。把 GCC、G++、binutils、armhf libc 和 libstdc++ 的 deb 全部解压到 `$V81/tools/cross/`。该目录下应存在 `usr/bin/arm-linux-gnueabihf-g++-13`。仅编译程序不需要 QEMU，执行原 ARM 基准脚本时再安装 qemu-user-static。

在同一终端中执行：

```sh
python3 -m venv "$LABMATE_BUILD/.venv"
"$LABMATE_BUILD/.venv/bin/python" -m pip install onnxruntime==1.30.0 onnx==1.23.2 numpy==2.5.4
python3 -m venv "$V81/tools/build_env"
"$V81/tools/build_env/bin/python" -m pip install cmake==3.31.6 ninja==1.11.1.4 packaging==25.0
git clone --branch v1.22.2 https://github.com/microsoft/onnxruntime.git "$V81/tools/onnxruntime"
git -C "$V81/tools/onnxruntime" checkout 5630b081cd25e4eccc7516a652ff956e51676794
git -C "$V81/tools/onnxruntime" submodule update --init --recursive
git clone https://github.com/wiseman/py-webrtcvad.git "$V81/tools/webrtcvad"
git -C "$V81/tools/webrtcvad" checkout e283ca41df3a84b0e87fb1f5cb9b21580a286b09
cp -a "$V81/tools/onnxruntime/include/onnxruntime/core/session" "$V81/tools/headers"
export PATH="$V81/tools/build_env/bin:$PATH"
export LD_LIBRARY_PATH="$V81/tools/cross/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
```

protoc 使用 ORT 的 `cmake/deps.txt` 指定版本，下载并核对摘要：

```sh
python3 - <<'PY'
import hashlib, os, urllib.request, zipfile
from pathlib import Path
root=Path(os.environ['V81'])
line=next(x for x in (root/'tools/onnxruntime/cmake/deps.txt').read_text().splitlines() if x.startswith('protoc_linux_x64;'))
_,url,expected=line.split(';')
archive=root/'tools/protoc.zip'
urllib.request.urlretrieve(url,archive)
assert hashlib.sha1(archive.read_bytes()).hexdigest()==expected
destination=root/'tools/protoc'
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        assert (destination/item.filename).resolve().is_relative_to(destination.resolve())
    z.extractall(destination)
(destination/'bin/protoc').chmod(0o755)
PY
```

## 3. 构建语音程序

先构建 ARM ORT，再应用原工程中的 ConvInteger 补丁并重建相应库：

```sh
cd "$V81/tools/onnxruntime"
./build.sh --config Release --parallel 4 --skip_tests --skip_submodule_sync \
  --compile_no_warning_as_error --cmake_generator Ninja \
  --disable_ml_ops --disable_contrib_ops --no_kleidiai \
  --path_to_protoc_exe "$V81/tools/protoc/bin/protoc" \
  --build_dir "$V81/build/ort_arm" \
  --cmake_extra_defines CMAKE_TOOLCHAIN_FILE="$V81/src/armv7_toolchain.cmake" \
  onnxruntime_BUILD_UNIT_TESTS=OFF onnxruntime_ENABLE_LTO=OFF
python3 "$V81/src/fix_arm_convinteger.py" "$V81"
cmake --build "$V81/build/ort_arm/Release" --target onnxruntime_providers re2 --parallel 4
python3 "$V81/src/compile_programs.py" "$V81" host
python3 "$V81/src/compile_programs.py" "$V81" arm
"$LABMATE_BUILD/.venv/bin/python" "$V82/src/prepare_exact.py"
"$LABMATE_BUILD/.venv/bin/python" "$V82/src/build_probe.py"
"$LABMATE_BUILD/.venv/bin/python" "$V82/src/build_service.py"
```

`compile_programs.py` 分别建立 host/ARM 的 VAD 对象和前置程序。`prepare_exact.py` 核对模型 initializer，生成外置权重及 ARM32 取整修正后的 MLAS 库；`build_service.py` 链接该库，建立常驻识别、客户端与录音程序。

输出位于 `$V82/build/`，其中 `runtime_arm/` 与 `runtime_host/` 是测试运行目录。命令与模型检查结果写入 `$V82/reports/`，主要文件为 `service_build.json`、`external_weights.json` 和 `quantize_patch.json`。ARM 程序采用 `-O3 -std=c++17 -ffp-contract=off -pthread -static`，目标为 ARMv7-A、NEON、hard-float。

## 训练和运行的边界

运行模型来自 WeNet `20220506_u2pp_conformer_exp`，经 SmartBox 合成指令微调、ONNX 导出和动态 INT8 量化。V8.2 沿用权重，主要调整权重外置、常驻服务与 ARM32 数值处理。包内包含运行模型、编译源码与 dev/test 音频；完整训练集与训练环境不在公开包内。此构建流程复编译推理程序，不声称可以从零复现训练。

`prepare_exact.py` 保留原 initializer 校验，公开版额外避免将旧外置权重文件覆盖到新生成的权重上。准备脚本只在新工作目录替换历史绝对路径。原开发阶段的 remote 脚本作为源码记录保留；本页为公开版编译入口。

[原文件映射](source_map.json)记录提取来源和源文件摘要；[公开版变更记录](adaptations.json)记录为独立运行做的修改。[验证结果](../sim/results/package_checks.json)区分本次实际检查与历史编译结果。本次整理未重新执行 Linux 交叉编译。
