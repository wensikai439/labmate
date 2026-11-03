#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/wsk/qiansai/audio/v8_1_20261022
export PATH="$ROOT/tools/build_env/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT/tools/cross/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
python3 "$ROOT/src/fix_arm_convinteger.py" "$ROOT"
cmake --build "$ROOT/build/ort_arm/Release" --target onnxruntime_providers re2 --parallel 12
python3 "$ROOT/src/make_resident.py" "$ROOT"
python3 "$ROOT/src/make_vad_phrases.py" "$ROOT"
python3 "$ROOT/src/compile_programs.py" "$ROOT" arm
printf '%s\n' complete > "$ROOT/reports/build.complete"
