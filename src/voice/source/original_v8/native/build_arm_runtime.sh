#!/usr/bin/env sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compiler=${CXX:-arm-linux-gnueabihf-g++}
"$compiler" -static -O3 -std=c++17 -Wno-psabi -march=armv7-a -mfpu=neon -mfloat-abi=hard -ffp-contract=off -I "$root/fpga/source" "$root/fpga/source/voice_native.cpp" "$root/source/native/voice_kernel_neon.cpp" -lm -o "$root/bin/smartbox_voice_armv7"
printf '%s
' 'Runtime rebuilt; regenerate hashes and execution evidence after edits.'
