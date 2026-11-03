#!/usr/bin/env sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$(uname -m)" in armv7l|armv8l) ;; *) echo 'Requires ZedBoard 32-bit ARMv7 Linux.' >&2; exit 2 ;; esac
mode=auto
case "${1:-}" in --fast) mode=fast; shift ;; --asr) mode=asr; shift ;; esac
if [ "$#" -gt 1 ]; then echo 'Usage: sh start.sh [--fast|--asr] [audio.wav]' >&2; exit 2; fi
chmod +x "$root/bin/smartbox_cascade_armv7" "$root/bin/smartbox_voice_armv7" "$root/bin/smartbox_asr_armv7"
if [ "$#" -eq 1 ]; then exec "$root/bin/smartbox_cascade_armv7" "$root" "$1" "$mode"; fi
if ! command -v arecord >/dev/null 2>&1; then echo 'Configure ALSA recording or pass a 16 kHz mono PCM16 WAV.' >&2; exit 2; fi
seconds=${RECORD_SECONDS:-4}
case "$seconds" in 1|2|3|4|5|6|7|8|9|10|11|12) ;; *) echo 'RECORD_SECONDS must be 1..12.' >&2; exit 2 ;; esac
audio=$(mktemp "${TMPDIR:-/tmp}/smartbox-voice-XXXXXX.wav")
trap 'rm -f -- "$audio"' EXIT HUP INT TERM
arecord -q -D "${ALSA_DEVICE:-default}" -f S16_LE -r 16000 -c 1 -d "$seconds" "$audio"
"$root/bin/smartbox_cascade_armv7" "$root" "$audio" "$mode"
