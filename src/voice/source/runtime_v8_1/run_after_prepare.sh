#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/wsk/qiansai/audio/v8_1_20261022
trap 'result=$?; printf "%s\n" "$result" > "$ROOT/reports/pipeline.exit"' EXIT
for attempt in $(seq 1 180); do
  if test -f "$ROOT/reports/preparation.complete"; then bash "$ROOT/src/build_remote.sh"; exit 0; fi
  sleep 10
done
echo 'Preparation has not completed; inspect logs/prepare.log.' >&2
exit 2
