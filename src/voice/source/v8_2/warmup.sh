#!/usr/bin/env sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
chmod +x "$root/bin/smartbox_asr_resident" "$root/bin/smartbox_voice_service"
exec "$root/bin/smartbox_asr_resident" --warmup "$root"
