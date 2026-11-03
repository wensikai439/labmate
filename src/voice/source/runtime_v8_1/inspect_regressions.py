import collections,json,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]);counts=collections.Counter();examples={}
keys=('intent_proposal','frequency_hz','confirmation_required','instrument_control_executed')
for part in ('dev','test'):
    for line in (root/'reports'/(part+'_replay.jsonl')).read_text().splitlines():
        row=json.loads(line)
        if not row.get('baseline_correct_intent') or 'vad' not in row:continue
        old=row['baseline_cascade']
        new=json.loads(subprocess.check_output([str(root/'build/voice_live_host'),'--parse-vad',row['vad']['transcript']],text=True))
        if any(old.get(k)!=new.get(k) for k in keys):
            key=(old['intent_proposal'],new['intent_proposal'],new.get('reason'))
            counts[key]+=1;examples.setdefault(key,[])
            if len(examples[key])<5:examples[key].append({'reference':row['reference'],'transcript':new['transcript'],'old':old,'new':new})
print(json.dumps([{'case':key,'n':value,'examples':examples[key]} for key,value in counts.items()],ensure_ascii=False,indent=2))
