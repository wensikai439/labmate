#!/usr/bin/env sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$(uname -m)" in armv7l|armv8l) ;; *) echo 'Requires ZedBoard 32-bit ARMv7 Linux.' >&2; exit 2 ;; esac
if [ "${1:-}" = --legacy ]; then shift; exec sh "$root/start_legacy.sh" "$@"; fi
chmod +x "$root/bin/smartbox_voice_live" "$root/bin/smartbox_asr_resident" "$root/bin/smartbox_voice_armv7"
exec "$root/bin/smartbox_voice_live" "$root" "$@"
