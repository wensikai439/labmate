#!/usr/bin/env sh
# Read-only board information and timings. No governor/swap/system changes.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
uname -a
grep -E '^(model name|Processor|Features|CPU architecture)' /proc/cpuinfo || true
grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo
for path in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq; do
    if [ -r "$path" ]; then printf '%s: ' "$path"; cat "$path"; fi
done
sh "$root/status.sh" || true
if [ "$#" = 1 ]; then sh "$root/benchmark.sh" "$1"; fi
