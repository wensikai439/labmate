"""Create a voice-only build workspace from labmate_open."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


def prepare(runtime, output):
    runtime = Path(runtime).resolve()
    output = Path(output).resolve()
    if os.name != 'posix':
        raise ValueError('Run in Linux from labmate_open')
    if output.exists():
        raise ValueError('Output must be a new directory')
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/_-.' for c in str(output)):
        raise ValueError('Use an ASCII output path without spaces or shell metacharacters')
    voice = runtime / 'src/voice'
    required = [voice/'source/runtime_v8_1', voice/'source/v8_2', voice/'source/original_v8',
                voice/'fpga', voice/'models', voice/'bin/smartbox_voice_armv7',
                voice/'source/original_v8/cascade/vendor/json.hpp',
                voice/'source/runtime_v8_1/vad_training_phrases.h']
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError('\n'.join(missing))
    output.mkdir(parents=True)
    old = output/'audio/v8_1_20261022'
    current = output/'audio/v8_2_20261022'
    reference = old/'reference/SmartBox_ZedBoard_Voice_V8_20261020'
    pairs = [(voice/'source/runtime_v8_1',old/'src'),(voice/'source/v8_2',current/'src'),
             (voice/'source/original_v8',reference/'source'),(voice/'fpga',reference/'fpga'),
             (voice/'models',current/'models')]
    for src,dst in pairs:
        shutil.copytree(src,dst,symlinks=True)
    (reference/'bin').mkdir()
    shutil.copy2(voice/'bin/smartbox_voice_armv7',reference/'bin/smartbox_voice_armv7')
    shutil.copytree(reference/'source/cascade/vendor',old/'src/vendor',dirs_exist_ok=True)
    for root in (old,current):
        for name in ('tools','build','reports','logs'):
            (root/name).mkdir(exist_ok=True)
    replacements = {'/home/wsk/qiansai':str(output),'/home/wsk/asr_v7/.venv':str(output/'.venv')}
    changed = []
    for root in (old/'src',current/'src'):
        for path in sorted(root.rglob('*')):
            if path.suffix not in {'.py','.sh','.cmake'} or not path.is_file():
                continue
            original = path.read_text(encoding='utf-8')
            text = original
            for before,after in replacements.items():
                text = text.replace(before,after)
            if text != original:
                path.write_text(text,encoding='utf-8')
                changed.append(path.relative_to(output).as_posix())
    sources = {str(src.relative_to(runtime)):str(dst.relative_to(output)) for src,dst in pairs}
    models = {str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
              for root in (current/'models',) for p in root.rglob('*') if p.is_file()}
    record = {'source_layout':sources,'path_adjusted_files':changed,'model_sha256':models,
              'external_dependencies':['ONNX Runtime v1.22.2','WebRTC VAD','ARM GCC/G++ 13.3.0','CMake','Ninja','protoc']}
    (output/'workspace.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'workspace':str(output),'path_adjusted_files':len(changed),'model_files':len(models)}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    prepare(args.runtime_root,args.output)
