"""Check button-mode microphone replay without changing endpoint/decision policy."""
import json,os,signal,subprocess,time,wave
from pathlib import Path
R=Path('/home/wsk/qiansai/audio/v8_2_20261022');old=Path('/home/wsk/qiansai/audio/v8_1_20261022');root=R/'build/runtime_host'
out=R/'build/interaction';out.mkdir(exist_ok=True);fake=out/'fakebin';fake.mkdir(exist_ok=True)
client=R/'build/asr_client_host';live=root/'bin/smartbox_voice_live'
def run(args,**kw):
    result=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=60,**kw)
    assert result.returncode==0,(args,result.stdout,result.stderr)
    return [json.loads(v) for v in result.stdout.splitlines() if v]
def status():return run([client,'--status',root])[0]
samples=[json.loads(v) for v in (old/'reports/replay_manifest.jsonl').read_text().splitlines()]
sample=next(v for v in samples if v['partition']=='dev' and v['intent']=='CMD_IDENTIFY_INSTRUMENT')
with wave.open(sample['audio'],'rb') as f:pcm=f.readframes(f.getnframes())
(out/'capture.raw').write_bytes(pcm+b'\0'*64000)
(fake/'arecord').write_text('''#!/usr/bin/python3
import os,sys,time
if os.environ.get('SMARTBOX_CHECK_EMPTY'):sys.exit(1)
data=open(os.environ['SMARTBOX_CHECK_PCM'],'rb').read()
for start in range(0,len(data),640):os.write(1,data[start:start+640]);time.sleep(.001)
if os.environ.get('SMARTBOX_CHECK_IDLE'):
    while True:os.write(1,bytes(640));time.sleep(.02)
''');(fake/'arecord').chmod(0o755)
env=dict(os.environ,PATH=str(fake)+':'+os.environ['PATH'],SMARTBOX_CHECK_PCM=str(out/'capture.raw'),TMPDIR=str(out))
report={'scope':'Deterministic workstation microphone replay, not a physical-board microphone measurement.'}
try:
    ready=run([client,'--warmup',root])[0];pid=ready['asr_service_pid'];events=[]
    for optional in ([],['--events'],[]):
        result=run([live,root,'--once',*optional],env=env);events.append(result)
        final=result[-1];assert final['intent_proposal']==sample['intent'] and final['cascade_route']=='vad_asr_guarded',final
        assert final['asr_service_pid']==pid and final['model_load_count']==1,final
        if optional:assert {'listening','speech_started','recognizing'}<={v.get('state') for v in result},result
        else:assert len(result)==1
    report['three_separate_button_processes']={'passed':True,'same_service_pid':pid,'results':events}
    # Duplicate input is rejected immediately rather than forming a slow backlog.
    long_sample=json.loads((R/'reports/probe_samples.json').read_text())[2]
    job=subprocess.Popen([str(client),long_sample['audio'],str(root/'models/asr')],stdout=subprocess.PIPE,text=True)
    for attempt in range(200):
        if status()['busy']:break
        time.sleep(.002)
    assert status()['busy']
    rejected=run([client,long_sample['audio'],root/'models/asr'])[0]
    result=json.loads(job.communicate(timeout=60)[0]);assert 'error' not in result
    assert rejected.get('error')=='recognition_busy',rejected
    report['busy_rejection']={'passed':True,'response':rejected}
    invalid=run([client,out/'missing.wav',root/'models/asr'])[0];assert 'error' in invalid
    assert status()['ready'] and not status()['busy'];report['bad_file_recovery']={'passed':True}
    fail=subprocess.run([str(live),str(root),'--once'],env=dict(env,SMARTBOX_CHECK_EMPTY='1'),capture_output=True,text=True,timeout=30)
    assert fail.returncode==2 and 'microphone_stream_closed' in fail.stdout,(fail.stdout,fail.stderr)
    report['microphone_failure']={'passed':True}
    assert status()['asr_service_pid']==pid;report['status']=status()
finally:
    try:run([client,'--stop',root])
    except Exception:pass
report['passed']=True;(R/'reports/interaction.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('INTERACTION_CHECKS_PASSED',flush=True)
