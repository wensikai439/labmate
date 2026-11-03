#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/wsk/qiansai/audio/v8_1_20261022
cd "$ROOT"
export PATH="$ROOT/tools/build_env/bin:$PATH"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export LD_LIBRARY_PATH="$ROOT/tools/cross/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
python src/make_resident.py "$ROOT"
python src/make_vad_phrases.py "$ROOT"
test -d tools/webrtcvad/.git || git clone --depth 1 https://github.com/wiseman/py-webrtcvad.git tools/webrtcvad
python - <<'PY'
from pathlib import Path
import shutil
root=Path('/home/wsk/qiansai/audio/v8_1_20261022')
shutil.copytree(root/'reference/SmartBox_ZedBoard_Voice_V8_20261020/source/cascade/vendor',root/'src/vendor',dirs_exist_ok=True)
cross=root/'tools/cross'
toolchain=f'''set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR armv7)
set(CMAKE_C_COMPILER {cross}/usr/bin/arm-linux-gnueabihf-gcc-13)
set(CMAKE_CXX_COMPILER {cross}/usr/bin/arm-linux-gnueabihf-g++-13)
set(CMAKE_SYSROOT {cross})
set(CMAKE_C_FLAGS_INIT "-march=armv7-a -mfpu=neon -mfloat-abi=hard -Wno-psabi -B{cross}/usr/bin")
set(CMAKE_CXX_FLAGS_INIT "-march=armv7-a -mfpu=neon -mfloat-abi=hard -Wno-psabi -B{cross}/usr/bin")
set(CMAKE_FIND_ROOT_PATH {cross}/usr/arm-linux-gnueabihf)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
'''
(root/'src/armv7_toolchain.cmake').write_text(toolchain)
PY
test -f reports/host_build.complete || python src/compile_programs.py "$ROOT" host
if ! test -f reports/evaluation.started; then
  /home/wsk/asr_v7/.venv/bin/python src/normalize_replay.py "$ROOT"
  touch reports/evaluation.started
  nohup python src/evaluate_runtime.py "$ROOT" > "$ROOT/logs/evaluate.log" 2>&1 < /dev/null &
fi
cd "$ROOT/tools/onnxruntime"
./build.sh --config Release --parallel 4 --skip_tests --skip_submodule_sync \
  --compile_no_warning_as_error --cmake_generator Ninja --disable_ml_ops --disable_contrib_ops --no_kleidiai \
  --path_to_protoc_exe "$ROOT/tools/protoc/bin/protoc" --build_dir "$ROOT/build/ort_arm" \
  --cmake_extra_defines CMAKE_TOOLCHAIN_FILE="$ROOT/src/armv7_toolchain.cmake" onnxruntime_BUILD_UNIT_TESTS=OFF onnxruntime_ENABLE_LTO=OFF
cd "$ROOT"
cmake --build "$ROOT/build/ort_arm/Release" --target re2 --parallel 4
python src/compile_programs.py "$ROOT" arm
printf '%s\n' complete > reports/build.complete
