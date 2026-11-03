#!/usr/bin/env python3
"""Verify actual ARMv7 instructions and compare against the original ARM binary."""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[1]);build=root/'build';reports=root/'reports'
reference=root/'reference/SmartBox_ZedBoard_Voice_V8_20261020'
model=reference/'models/asr';qemu=root/'tools/cross/usr/bin/qemu-arm-static'
rows=[json.loads(x) for x in (reports/'replay_manifest.jsonl').read_text().splitlines()]
rows=[x for x in rows if x.get('partition')=='dev']
recorded={r['id']:r['baseline'] for r in map(json.loads,(reports/'dev_replay.jsonl').read_text().splitlines())}
selected=[]
for intent in ['CMD_SET_SIGNAL_FREQ','CMD_MEASURE_RMS',None]:
    selected.append(min((x for x in rows if x['intent']==intent),key=lambda x:x['duration_s']))
def command(binary,args):return [str(qemu),'-cpu','cortex-a9',str(binary)]+list(map(str,args))
server=subprocess.Popen(command(build/'smartbox_asr_resident',['--server',model]),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(root/'logs/arm_resident.stderr').open('w'),text=True,bufsize=1)
report={'execution':'QEMU ARMv7, Cortex-A9 CPU model; instruction compatibility and output check only','real_board_latency_verified':False,'real_microphone_verified':False,'comparisons':[]}
try:
    report['ready']=json.loads(server.stdout.readline())
    for row in selected:
        start=time.monotonic()
        legacy=subprocess.run(command(reference/'bin/smartbox_asr_armv7',[row['audio'],model]),capture_output=True,text=True,timeout=600)
        old=json.loads(legacy.stdout) if legacy.returncode==0 else recorded[row['id']]
        server.stdin.write(row['audio']+'\n');server.stdin.flush();new=json.loads(server.stdout.readline())
        same=all(old.get(key)==new.get(key) for key in ['transcript','intent_proposal','frequency_hz','reason'])
        report['comparisons'].append({'id':row['id'],'same_output':same,'baseline':old,'resident':new,'baseline_source':'original_ARM' if legacy.returncode==0 else 'recorded_original_x86_64_native',
            'original_ARM_returncode':legacy.returncode,'original_ARM_stderr':legacy.stderr,'emulation_elapsed_seconds':time.monotonic()-start})
        print(row['intent'],same,flush=True)
    # The endpoint detector must produce byte-identical crops on x86 and ARM.
    sample=selected[0];destination=build/'arm_segments';destination.mkdir(exist_ok=True)
    raw=subprocess.run(command(build/'smartbox_voice_live',['--segment',sample['audio'],destination]),capture_output=True,text=True,check=True,timeout=90)
    armsegments=[json.loads(line) for line in raw.stdout.splitlines()]
    hostraw=subprocess.run([str(build/'voice_live_host'),'--segment',sample['audio'],str(build/'host_smoke_segments')],capture_output=True,text=True,check=True)
    hostsegments=[json.loads(line) for line in hostraw.stdout.splitlines()]
    report['endpoint_ARM_host_byte_agreement']=len(armsegments)==len(hostsegments) and all(hashlib.sha256(Path(a['segment']).read_bytes()).digest()==hashlib.sha256(Path(b['segment']).read_bytes()).digest() for a,b in zip(armsegments,hostsegments))
    report['passed']=all(x['same_output'] for x in report['comparisons']) and report['endpoint_ARM_host_byte_agreement']
    (reports/'arm_execution.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    assert report['passed'],'ARM output regression'
finally:
    server.stdin.close()
    try:server.wait(timeout=30)
    except subprocess.TimeoutExpired:server.terminate();server.wait()
