#!/bin/bash
set -euo pipefail
ROOT=/home/wsk/qiansai/audio/v8_2_20261022
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CUDA_VISIBLE_DEVICES=""
export TMPDIR="$ROOT/cache" XDG_CACHE_HOME="$ROOT/cache" TORCH_HOME="$ROOT/cache/torch"
export HF_HOME="$ROOT/cache/hf" PIP_CACHE_DIR="$ROOT/cache/pip" MPLCONFIGDIR="$ROOT/cache/matplotlib"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
export LD_LIBRARY_PATH=/home/wsk/qiansai/audio/v8_1_20261022/tools/cross/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}
exec "$@"
