#!/usr/bin/env python3
"""Prepare the PCM16/mono/16kHz input contract used by the actual board binary."""
import collections,json,sys,wave
from pathlib import Path
import numpy as np
import torch
import torchaudio.functional as audio_ops
torch.set_num_threads(2)
root=Path(sys.argv[1]);target=root/'build/replay16k';target.mkdir(parents=True,exist_ok=True)
source=Path('/home/wsk/asr_v7/data/v7/manifest.jsonl')
formats=collections.Counter();rows=[]
for line in source.read_text().splitlines():
    row=json.loads(line)
    if row.get('partition') not in ('dev','test'):continue
    with wave.open(row['audio'],'rb') as file:
        rate,channels,width=file.getframerate(),file.getnchannels(),file.getsampwidth()
        data=file.readframes(file.getnframes())
    formats[(rate,channels,width)]+=1
    if (rate,channels,width)!=(16000,1,2):
        if width!=2:raise RuntimeError('Unsupported source PCM width')
        array=np.frombuffer(data,dtype='<i2').reshape(-1,channels)
        values=torch.from_numpy(array.mean(axis=1).astype(np.float32)/32768.0)
        if rate!=16000:values=audio_ops.resample(values,rate,16000)
        pcm=np.rint(values.numpy()*32768).clip(-32768,32767).astype('<i2')
        path=target/(row['id']+'.wav')
        with wave.open(str(path),'wb') as file:
            file.setparams((1,2,16000,0,'NONE','not compressed'));file.writeframes(pcm.tobytes())
        row['source_audio']=row['audio'];row['audio']=str(path)
    rows.append(row)
(root/'reports/replay_manifest.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))
(root/'reports/replay_audio_formats.json').write_text(json.dumps({'original_formats':{str(k):v for k,v in formats.items()},'clips':len(rows),'resampling':'torchaudio.functional.resample followed by PCM16 rounding; identical normalized WAV supplied to both binaries'},indent=2))
print(dict(formats),len(rows),flush=True)
