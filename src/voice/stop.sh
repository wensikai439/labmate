#!/usr/bin/env sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
chmod +x "$root/bin/smartbox_asr_resident"
exec "$root/bin/smartbox_asr_resident" --stop "$root"
