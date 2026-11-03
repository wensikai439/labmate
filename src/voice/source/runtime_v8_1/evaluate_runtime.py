#!/usr/bin/env python3
"""Replay existing synthetic dev/test recordings; these are regression sets."""
import ctypes,hashlib,json,os,statistics,subprocess,sys,time,traceback
from pathlib import Path
root=Path(sys.argv[1]);build=root/'build';reports=root/'reports'
hostlib=next(Path('/home/wsk/asr_v7/.venv/lib').glob('python*/site-packages/onnxruntime/capi/libonnxruntime.so.*'))
library_dir=build/'hostlib';library_dir.mkdir(exist_ok=True)
if not (library_dir/'libonnxruntime.so.1').exists():(library_dir/'libonnxruntime.so.1').symlink_to(hostlib)
os.environ['LD_LIBRARY_PATH']=str(library_dir)+':'+os.environ.get('LD_LIBRARY_PATH','')
reference=root/'reference/SmartBox_ZedBoard_Voice_V8_20261020'
manifest=reports/'replay_manifest.jsonl'
rows=[json.loads(line) for line in manifest.read_text().splitlines()]
rows=[row for row in rows if row.get('partition') in ('dev','test')]
model=reference/'models/asr'
def call(command):
    start=time.monotonic();p=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=180)
    if p.returncode:raise RuntimeError(p.stderr[-2000:])
    return json.loads(p.stdout),1000*(time.monotonic()-start)
def summary(values):
    values=sorted(values)
    return {'n':len(values),'median_ms':statistics.median(values),'p95_ms':values[min(len(values)-1,int(len(values)*.95))]}
def decision(value):
    return {key:value.get(key) for key in ('intent_proposal','frequency_hz','confirmation_required','instrument_control_executed')}
def fast_command(value):
    intent=value['intent_proposal'];return intent.startswith('CMD_') and intent!='CMD_SET_SIGNAL_FREQ'
def distance(a,b):
    last=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        now=[i]
        for j,y in enumerate(b,1):now.append(min(now[-1]+1,last[j]+1,last[j-1]+(x!=y)))
        last=now
    return last[-1]
server=subprocess.Popen([str(build/'asr_resident_host'),'--server',str(model)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(root/'logs/resident_host.stderr').open('w'),text=True,bufsize=1)
def infer(path):
    server.stdin.write(str(path)+'\n');server.stdin.flush();result=json.loads(server.stdout.readline())
    if 'error' in result:raise RuntimeError(result['error'])
    return result
report={'scope':'Existing synthetic dev/test replay, not real-microphone or fresh independent validation','board_runtime_verified':False,'weights_changed':False,'partitions':{}}
try:
    frontends=[ctypes.CDLL(str(build/('frontend_'+v+'.so'))) for v in ('baseline','resident')]
    for library in frontends:
        library.smartbox_fbank.argtypes=[ctypes.c_char_p,ctypes.POINTER(ctypes.c_float),ctypes.c_int]
        library.smartbox_fbank.restype=ctypes.c_int
    buffers=[(ctypes.c_float*(1200*80))() for _ in range(2)]
    report['frontend_bitwise_samples']=0;report['frontend_bitwise_mismatches']=0
    for row in rows:
        sizes=[library.smartbox_fbank(os.fsencode(row['audio']),buffer,len(buffer)) for library,buffer in zip(frontends,buffers)]
        if min(sizes)<1 or sizes[0]!=sizes[1]:raise RuntimeError('Frontend frame mismatch: '+row['id']+' '+repr(sizes))
        matches=ctypes.string_at(buffers[0],sizes[0]*80*4)==ctypes.string_at(buffers[1],sizes[1]*80*4)
        report['frontend_bitwise_samples']+=1;report['frontend_bitwise_mismatches']+=not matches
    if report['frontend_bitwise_mismatches']:raise RuntimeError('Frontend values changed')
    report['ready']=json.loads(server.stdout.readline())
    sample=next(row for row in rows if row['partition']=='dev')
    infer(sample['audio'])
    cold,warm=[],[]
    for _ in range(5):
        old,ms=call([build/'asr_baseline_host',sample['audio'],model]);new=infer(sample['audio'])
        assert old['transcript']==new['transcript'] and decision(old)==decision(new)
        cold.append(ms);warm.append(new['timing_ms']['total'])
    report['host_benchmark']={'original_cold_process':summary(cold),'resident_warm':summary(warm),'CPU':'company workstation x86_64; not Cortex-A9 latency','ORT_threads':2}
    for partition in ('dev','test'):
        entries=[row for row in rows if row['partition']==partition]
        result={'samples':len(entries),'same_audio_transcript_mismatches':0,'same_audio_decision_mismatches':0,'vad_split_or_missing':0,'vad_command_regressions':0,'vad_asr_decision_changes':0,'vad_transcript_changes':0,'original_asr_errors':0,'original_characters':0,'details':[]}
        destination=build/'segmented'/partition;destination.mkdir(parents=True,exist_ok=True)
        with (reports/(partition+'_replay.jsonl')).open('w') as output:
            for index,row in enumerate(entries):
                old,_=call([build/'asr_baseline_host',row['audio'],model]);new=infer(row['audio'])
                same_text=old['transcript']==new['transcript'];same_decision=decision(old)==decision(new)
                result['same_audio_transcript_mismatches']+=not same_text
                result['same_audio_decision_mismatches']+=not same_decision
                result['original_asr_errors']+=distance(row['text'],old['transcript'])
                result['original_characters']+=len(row['text'])
                folder=destination/row['id']
                segmented=subprocess.run([str(build/'voice_live_host'),'--segment',row['audio'],str(folder)],capture_output=True,text=True,timeout=20)
                if segmented.returncode:raise RuntimeError(segmented.stderr[-1000:])
                segments=[json.loads(line) for line in segmented.stdout.splitlines() if line]
                item={'id':row['id'],'partition':partition,'reference':row['text'],'baseline':old,'resident':new,'segment_count':len(segments)}
                if len(segments)!=1 or 'segment' not in segments[0]:
                    result['vad_split_or_missing']+=1;result['vad_command_regressions']+=1
                else:
                    clipped=segments[0]['segment'];vad=infer(clipped)
                    fast_old,_=call([build/'fast_host',row['audio']]);fast_new,_=call([build/'fast_host',clipped])
                    baseline_decision=fast_old if fast_command(fast_old) else old
                    vad_decision=vad # Endpointed audio uses full V8 ASR, not V6 fast thresholds.
                    changed=decision(baseline_decision)!=decision(vad_decision)
                    # A V8-correct command or rejection must stay correct, including numeric slots.
                    old_correct=baseline_decision['intent_proposal']==(row['intent'] or 'UNMATCHED')
                    result['vad_command_regressions']+=bool(old_correct and changed)
                    result['vad_asr_decision_changes']+=decision(old)!=decision(vad)
                    result['vad_transcript_changes']+=old['transcript']!=vad['transcript']
                    item.update(vad=vad,baseline_cascade=baseline_decision,vad_cascade=vad_decision,baseline_correct_intent=old_correct,decision_changed=changed)
                output.write(json.dumps(item,ensure_ascii=False)+'\n');output.flush()
                if index%40==0:print(partition,index+1,'/',len(entries),flush=True)
        result['baseline_native_CER']=result['original_asr_errors']/max(1,result['original_characters'])
        report['partitions'][partition]=result
        (reports/'regression_progress.json').write_text(json.dumps(report,indent=2))
        # Endpoint defaults are fixed before replaying the historical test split.
        if partition=='dev':
            report['vad_default_gate_passed']=result['vad_command_regressions']==0
    report['same_audio_regression_passed']=all(p['same_audio_transcript_mismatches']==0 and p['same_audio_decision_mismatches']==0 for p in report['partitions'].values())
    report['vad_default_gate_passed']=all(p['vad_command_regressions']==0 for p in report['partitions'].values())
    report['complete']=True
    (reports/'regression.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)
except Exception:
    (reports/'regression_failure.txt').write_text(traceback.format_exc());raise
finally:
    if server.stdin:server.stdin.close()
    try:server.wait(timeout=30)
    except subprocess.TimeoutExpired:server.terminate();server.wait()
