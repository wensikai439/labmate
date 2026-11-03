"""Measure exact audio paths on host and emulated A9. No board-latency claims."""
import collections,json,os,statistics,subprocess,time
from pathlib import Path
R=Path('/home/wsk/qiansai/audio/v8_2_20261022');ref=Path('/home/wsk/qiansai/audio/v8_1_20261022')
rows=json.loads((R/'reports/probe_samples.json').read_text());sample=min(rows,key=lambda r:abs(r['duration_s']-4.))
qemu=ref/'tools/cross/usr/bin/qemu-arm-static'
report={'scope':'Workstation and Cortex-A9 QEMU; not real board latency','audio':sample,'runs':{}}
def launch(cmd,env):
    p=subprocess.Popen(list(map(str,cmd))+['--server',str(R/'models/asr')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(R/'reports'/('probe_'+env.get('ASR_OPT','basic')+'.stderr')).open('a'),text=True,env={**os.environ,**env},bufsize=1)
    first=p.stdout.readline()
    if not first:raise RuntimeError('Probe did not start: '+str(cmd))
    return p,json.loads(first)
for arch,cmd in [('host',[R/'build/asr_probe_host']),('A9',[qemu,'-cpu','cortex-a9',R/'build/asr_probe_arm'])]:
    for level,arena in [('basic','0'),('all','0'),('all','1')]:
        tag=arch+'_'+level+'_arena'+arena;p,ready=launch(cmd,{'ASR_OPT':level,'ASR_ARENA':arena});values=[]
        for i in range(3):
            p.stdin.write(sample['audio']+'\n');p.stdin.flush();row=json.loads(p.stdout.readline());values.append(row)
            if 'error' in row:raise RuntimeError(row['error'])
        p.stdin.close();p.wait(timeout=30)
        report['runs'][tag]={'ready':ready,'values':values,'median_warm_ms':statistics.median(v['timing_ms']['total'] for v in values[1:])}
        print(tag,report['runs'][tag]['median_warm_ms'],values[-1]['transcript'],flush=True)
        (R/'reports/probe_benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
# Profiling adds overhead. Use it only to locate operators, not for headline timings.
p,_=launch([qemu,'-cpu','cortex-a9',R/'build/asr_probe_arm'],{'ASR_OPT':'basic','ASR_PROFILE':str(R/'reports/A9_profile')})
p.stdin.write(sample['audio']+'\n');p.stdin.flush();result=json.loads(p.stdout.readline());p.stdin.close();p.wait(timeout=30)
ops=collections.Counter();top=[]
for file in (R/'reports').glob('A9_profile*.json'):
    for event in json.loads(file.read_text()):
        if event.get('cat')=='Node' and event['name'].endswith('_kernel_time'):
            op=event.get('args',{}).get('op_name','?');ops[op]+=event.get('dur',0);top.append({'name':event['name'],'op':op,'ms':event.get('dur',0)/1000,'args':{k:v for k,v in event.get('args',{}).items() if k in ('input_type_shape','output_type_shape','parameter_size','activation_size')}})
report['profile']={'op_ms':{k:v/1000 for k,v in ops.most_common()},'largest_nodes':sorted(top,key=lambda x:x['ms'],reverse=True)[:25]}
(R/'reports/probe_benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('PROFILING_COMPLETE',flush=True)
