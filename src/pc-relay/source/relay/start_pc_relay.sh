#!/bin/sh
set -eu
set -a
. /etc/labmate/pc-relay.env
set +a
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -B "$root/board_relay.py"
