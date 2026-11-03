#!/usr/bin/env bash
# Resume only files and processes created for this task. No system installs.
set -euo pipefail
ROOT=/home/wsk/qiansai/audio/v8_1_20261022
export PATH="$ROOT/tools/build_env/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT/tools/cross/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p "$ROOT/build/tmp"
export TMPDIR="$ROOT/build/tmp"
# Stop only the earlier waiting finalizer from this exact task, so it cannot
# race the verification below. SSH, forwarding and other projects are untouched.
pkill -TERM -f '^bash /home/wsk/qiansai/audio/v8_1_20261022/src/finish_release.sh$' || true
python3 "$ROOT/src/make_resident.py" "$ROOT"
python3 "$ROOT/src/make_vad_phrases.py" "$ROOT"
python3 "$ROOT/src/compile_programs.py" "$ROOT" host
python3 "$ROOT/src/recheck_vad_policy.py" "$ROOT"
python3 "$ROOT/src/test_live.py" "$ROOT"
bash "$ROOT/src/resume_link.sh"
"/home/wsk/asr_v7/.venv/bin/python" "$ROOT/src/test_arm_convinteger.py" "$ROOT"
python3 "$ROOT/src/smoke_arm.py" "$ROOT"
python3 "$ROOT/src/package_release.py" "$ROOT"
