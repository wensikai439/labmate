"""Compare native ARM binaries on Cortex-A9 QEMU; not real-board latency."""
import json,os,statistics,subprocess,time
from pathlib import Path
R=Path('/home/wsk/qiansai/audio/v8_2_20261022');old=Path('/home/wsk/qiansai/audio/v8_1_20261022')
qemu=old/'tools/cross/usr/bin/qemu-arm-static';arm=R/'build/runtime_arm';client=R/'build/asr_client_host'
samples=json.loads((R/'reports/probe_samples.json').read_text())[:3]
def run(args):
    p=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=180)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    return json.loads(p.stdout)
report={'scope':'ARMv7 native binaries emulated on company x86 workstation using qemu-arm-static -cpu cortex-a9; these times are not ZedBoard measurements.','board_runtime_verified':False,'runs':[]}
for modeldir,name in [(old/'reference/SmartBox_ZedBoard_Voice_V8_20261020/models/asr','v8_1_original'),(arm/'models/asr','v8_2_external_patched')]:
    if name=='v8_1_original':
        p=subprocess.Popen([str(qemu),'-cpu','cortex-a9',str(old/'package/SmartBox_ZedBoard_Voice_V8_1_20261022/bin/smartbox_asr_resident'),'--server',str(modeldir)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        ready=json.loads(p.stdout.readline());print(name,ready,flush=True)
        try:
            for sample in samples:
                values=[]
                for repeat in range(3):
                    p.stdin.write(sample['audio']+'\n');p.stdin.flush();result=json.loads(p.stdout.readline());assert 'error' not in result,result;values.append(result)
                report['runs'].append({'version':name,'audio':sample['id'],'duration_s':sample['duration_s'],'load_ms':ready['model_load_ms'],'results':values,'median_total_ms':statistics.median(v['timing_ms']['total'] for v in values)})
                print(name,sample['duration_s'],report['runs'][-1]['median_total_ms'],flush=True)
        finally:p.stdin.close();p.wait(timeout=60)
    else:
        p=subprocess.Popen([str(qemu),'-cpu','cortex-a9',str(arm/'bin/smartbox_voice_service'),str(arm)],stdout=subprocess.DEVNULL,stderr=open(R/'reports/arm_service.log','w'))
        try:
            ready=run([client,'--warmup',arm]);print(name,ready,flush=True);report['arm_service_warmup']=ready
            for sample in samples:
                values=[]
                for repeat in range(3):
                    result=run([client,sample['audio'],modeldir]);assert 'error' not in result,result;values.append(result)
                baseline=next(v for v in report['runs'] if v['version']=='v8_1_original' and v['audio']==sample['id'])
                keys=('transcript','intent_proposal','frequency_hz','confirmation_required','instrument_control_executed','reason')
                assert all({k:v.get(k) for k in keys}=={k:baseline['results'][0].get(k) for k in keys} for v in values)
                report['runs'].append({'version':name,'audio':sample['id'],'duration_s':sample['duration_s'],'load_ms':ready['model_load_ms'],'results':values,'median_total_ms':statistics.median(v['timing_ms']['total'] for v in values)})
                print(name,sample['duration_s'],report['runs'][-1]['median_total_ms'],flush=True)
            # The actual ARM client protocol must work across separate launches, too.
            report['arm_client_status']=run([qemu,'-cpu','cortex-a9',arm/'bin/smartbox_asr_resident','--status',arm])
        finally:
            try:run([client,'--stop',arm])
            finally:p.wait(timeout=60)
(R/'reports/arm_benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('ARM_BENCHMARK_DONE',flush=True)
