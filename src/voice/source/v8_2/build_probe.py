import json,os,subprocess
from pathlib import Path
R=Path('/home/wsk/qiansai/audio/v8_2_20261022');ref=Path('/home/wsk/qiansai/audio/v8_1_20261022');cross=ref/'tools/cross';headers=ref/'tools/headers'
common=['-O3','-std=c++17','-ffp-contract=off','-pthread','-I'+str(R/'src'),'-I'+str(headers)]
lib=next(Path('/home/wsk/qiansai/.venv/lib').glob('python*/site-packages/onnxruntime/capi/libonnxruntime.so.*'))
link=R/'build/hostlib';link.mkdir(exist_ok=True)
if not (link/'libonnxruntime.so.1').exists():(link/'libonnxruntime.so.1').symlink_to(lib)
commands=[['g++',*common,str(R/'src/asr_probe.cpp'),str(lib),'-Wl,-rpath,'+str(link),'-o',str(R/'build/asr_probe_host')],
[str(cross/'usr/bin/arm-linux-gnueabihf-g++-13'),*common,'-static','--sysroot='+str(cross),'-B'+str(cross/'usr/bin'),'-march=armv7-a','-mfpu=neon','-mfloat-abi=hard','-Wno-psabi',str(R/'src/asr_probe.cpp'),'-Wl,--start-group',*map(str,(ref/'build/ort_arm/Release').rglob('*.a')),'-Wl,--end-group','-ldl','-lm','-o',str(R/'build/asr_probe_arm')]]
for cmd in commands:subprocess.run(cmd,check=True)
(R/'reports/probe_build.json').write_text(json.dumps(commands,indent=2));print('PROBE_BUILT',flush=True)
