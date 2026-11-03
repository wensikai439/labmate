#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/wsk/qiansai/audio/v8_1_20261022
mkdir -p "$ROOT"/{src,reference,tools,build,reports,package,logs}
cd "$ROOT"
export PIP_CACHE_DIR="$ROOT/tools/pip_cache"
python3 -m venv tools/build_env
tools/build_env/bin/python -m pip install --disable-pip-version-check cmake==3.31.6 ninja==1.11.1.4 packaging==25.0
mkdir -p tools/downloads tools/cross
cd tools/downloads
apt-get download binutils-arm-linux-gnueabihf cpp-13-arm-linux-gnueabihf gcc-13-arm-linux-gnueabihf g++-13-arm-linux-gnueabihf libgcc-13-dev-armhf-cross libstdc++-13-dev-armhf-cross libstdc++6-armhf-cross libgcc-s1-armhf-cross libc6-dev-armhf-cross libc6-armhf-cross linux-libc-dev-armhf-cross qemu-user-static
for package in ./*.deb; do dpkg-deb -x "$package" "$ROOT/tools/cross"; done
cd "$ROOT"
git clone --depth 1 --branch v1.22.2 https://github.com/microsoft/onnxruntime.git tools/onnxruntime
tools/build_env/bin/python - <<'PY'
import hashlib, pathlib, urllib.request, zipfile
root=pathlib.Path('/home/wsk/qiansai/audio/v8_1_20261022')
line=next(x for x in (root/'tools/onnxruntime/cmake/deps.txt').read_text().splitlines() if x.startswith('protoc_linux_x64;'))
_,url,expected=line.split(';')
archive=root/'tools/downloads/protoc.zip'
urllib.request.urlretrieve(url,archive)
assert hashlib.sha1(archive.read_bytes()).hexdigest()==expected
destination=root/'tools/protoc'
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        assert (destination/item.filename).resolve().is_relative_to(destination.resolve())
    z.extractall(destination)
(destination/'bin/protoc').chmod(0o755)
with zipfile.ZipFile(root/'reference/v8.zip') as z:
    for item in z.infolist():
        assert (root/'reference'/item.filename).resolve().is_relative_to((root/'reference').resolve())
    z.extractall(root/'reference')
PY
printf '%s\n' complete > "$ROOT/reports/preparation.complete"
