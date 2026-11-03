#!/usr/bin/env python3
"""Start workstation replay while the much larger ARM runtime source downloads."""
import concurrent.futures,shutil,subprocess,urllib.request,zipfile
from pathlib import Path
root=Path('/home/wsk/qiansai/audio/v8_1_20261022')
reference=root/'reference/SmartBox_ZedBoard_Voice_V8_20261020'
if not (reference/'models/asr/encoder.quant.onnx').exists():
    with zipfile.ZipFile(root/'reference/v8.zip') as z:
        for info in z.infolist():assert (root/'reference'/info.filename).resolve().is_relative_to((root/'reference').resolve())
        z.extractall(root/'reference')
headers=root/'tools/headers';headers.mkdir(exist_ok=True)
def fetch(name):
    url='https://raw.githubusercontent.com/microsoft/onnxruntime/v1.22.2/include/onnxruntime/core/session/'+name
    (headers/name).write_bytes(urllib.request.urlopen(url,timeout=120).read())
with concurrent.futures.ThreadPoolExecutor(4) as pool:
    list(pool.map(fetch,['onnxruntime_c_api.h','onnxruntime_cxx_api.h','onnxruntime_cxx_inline.h','onnxruntime_float16.h']))
vad=root/'tools/webrtcvad'
if not vad.exists():subprocess.run(['git','clone','--depth','1','https://github.com/wiseman/py-webrtcvad.git',str(vad)],check=True,timeout=240)
shutil.copytree(reference/'source/cascade/vendor',root/'src/vendor',dirs_exist_ok=True)
subprocess.run(['python3',str(root/'src/make_resident.py'),str(root)],check=True)
subprocess.run(['python3',str(root/'src/compile_programs.py'),str(root),'host'],check=True)
marker=root/'reports/evaluation.started'
if not marker.exists():
    marker.write_text('started by prepare_host.py\n')
    with (root/'logs/evaluate.log').open('w') as log:
        subprocess.Popen(['python3',str(root/'src/evaluate_runtime.py'),str(root)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
