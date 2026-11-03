"""Historical quality replay and button-client reuse checks, within qiansai.slice."""
import concurrent.futures,json,os,statistics,subprocess,time,wave
from pathlib import Path
R=Path('/home/wsk/qiansai/audio/v8_2_20261022');old=Path('/home/wsk/qiansai/audio/v8_1_20261022')
host=R/'build/runtime_host';arm=R/'build/runtime_arm';qemu=old/'tools/cross/usr/bin/qemu-arm-static'
client=R/'build/asr_client_host';samples=json.loads((R/'reports/probe_samples.json').read_text())
def invoke(args,**kw):
    p=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=kw.pop('timeout',180),**kw)
    if p.returncode:raise RuntimeError(str(args)+': '+p.stdout+p.stderr)
    return json.loads(p.stdout)
def call(root,*args):return invoke([client,*args,root])
def comparable(value):return {k:v for k,v in value.items() if k not in ('timing_ms','backend','process_peak_rss_kib','memory','asr_service_pid','model_load_count','service_model_load_ms','service_model_reused','service_queue_wait_ms','service_startup_wait_ms')}
report={'scope':'Historical synthetic replay and workstation/QEMU emulation; no real board or new microphone accuracy measurement.','board_runtime_verified':False,'weights_changed':False}
try:
    warm=call(host,'--warmup');report['host_warmup']=warm
    assert warm['ready'] and warm['model_load_count']==1
    results=[];mismatches=[];count=0
    for partition in ('dev','test'):
        rows=[json.loads(x) for x in (old/'reports'/f'{partition}_replay.jsonl').read_text().splitlines()]
        for row in rows:
            for route,filename,expected in [('full',old/'build/replay16k'/(row['id']+'.wav'),row['resident']),('vad',old/'build/segmented'/partition/row['id']/'segment_0.wav',row['vad'])]:
                assert filename.is_file(),filename
                result=invoke([client,filename,host/'models/asr'])
                assert result.get('model_load_count')==1 and result['asr_service_pid']==warm['asr_service_pid'],result
                if comparable(result)!=comparable(expected):mismatches.append({'id':row['id'],'route':route,'expected':comparable(expected),'actual':comparable(result)})
                results.append({'id':row['id'],'route':route,'result':result});count+=1
            if count%100==0:print('REPLAY',count,'mismatches',len(mismatches),flush=True)
    (R/'reports/service_replay.jsonl').write_text('\n'.join(json.dumps(v,ensure_ascii=False) for v in results)+'\n')
    report['historical_replay']={'audio_count':len(results)//2,'inferences':len(results),'mismatch_count':len(mismatches),'details':mismatches,'same_service_pid':warm['asr_service_pid'],'model_load_count':1,'independent_accuracy_benchmark':False}
    assert not mismatches,mismatches[:2]
    # Separate button-style client invocations reuse the already loaded service.
    raw=[]
    for sample in samples[:3]:
        result=invoke([client,sample['audio'],host/'models/asr']);raw.append(result)
    report['separate_client_reuse']={'pids':[v['asr_service_pid'] for v in raw],'loads':[v['model_load_count'] for v in raw],'startup_wait_ms':[v['service_startup_wait_ms'] for v in raw],'passed':len({v['asr_service_pid'] for v in raw})==1}
    # The daemon is idle between requests and never owns a microphone handle.
    report['host_after_replay']=call(host,'--status')
finally:
    try:call(host,'--stop')
    except Exception:pass
(R/'reports/service_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print('HOST_SERVICE_VALIDATED',flush=True)
