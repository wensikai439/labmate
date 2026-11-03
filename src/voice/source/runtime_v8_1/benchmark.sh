#!/usr/bin/env sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -ne 1 ]; then echo 'Usage: sh benchmark.sh audio.wav' >&2; exit 2; fi
case "$1" in /*) audio=$1 ;; *) audio=$(pwd)/$1 ;; esac
chmod +x "$root/bin/smartbox_asr_resident"
printf '%s\n%s\n%s\n' "$audio" "$audio" "$audio" | "$root/bin/smartbox_asr_resident" --server "$root/models/asr"
