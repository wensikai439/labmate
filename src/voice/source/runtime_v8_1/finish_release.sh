#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/wsk/qiansai/audio/v8_1_20261022
trap 'status=$?; printf "%s\n" "$status" > "$ROOT/reports/release_pipeline.exit"' EXIT
for attempt in $(seq 1 360); do
  if test -f "$ROOT/reports/build.complete" && test -f "$ROOT/reports/regression.json"; then
    python3 "$ROOT/src/smoke_arm.py" "$ROOT"
    python3 "$ROOT/src/package_release.py" "$ROOT"
    exit 0
  fi
  sleep 10
done
echo 'Build or regression did not complete. Inspect logs before packaging.' >&2
exit 2
