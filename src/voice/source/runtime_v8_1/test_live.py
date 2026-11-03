#!/usr/bin/env python3
"""Exercise microphone process handling with a deterministic PCM replay source."""
import json,os,signal,subprocess,sys,time,wave
from pathlib import Path
root=Path(sys.argv[1]);build=root/'build';out=build/'live_smoke';out.mkdir(exist_ok=True)
package=out/'package';(package/'bin').mkdir(parents=True,exist_ok=True)
if not (package/'models').exists():(package/'models').symlink_to(root/'reference/SmartBox_ZedBoard_Voice_V8_20261020/models')
for name,target in [('smartbox_voice_armv7',build/'fast_host'),('smartbox_asr_resident',build/'asr_resident_host')]:
    link=package/'bin'/name
    if not link.exists():link.symlink_to(target)
rows=[json.loads(x) for x in (root/'reports/replay_manifest.jsonl').read_text().splitlines()]
row=next(x for x in rows if x['partition']=='dev' and x['intent']=='CMD_IDENTIFY_INSTRUMENT')
with wave.open(row['audio'],'rb') as f:raw=f.readframes(f.getnframes())
pcm=out/'pcm.raw';pcm.write_bytes(raw+b'\0'*64000)
fake=out/'fakebin';fake.mkdir(exist_ok=True)
arecord=fake/'arecord'
arecord.write_text('''#!/usr/bin/python3
import os,sys,time
data=open(os.environ['SMARTBOX_TEST_PCM'],'rb').read()
if os.environ.get('SMARTBOX_TEST_EMPTY'):sys.exit(1)
for start in range(0,len(data),640):
    os.write(1,data[start:start+640]);time.sleep(.001)
if os.environ.get('SMARTBOX_TEST_IDLE'):
    while True:os.write(1,bytes(640));time.sleep(.02)
''');arecord.chmod(0o755)
env=os.environ.copy();env['PATH']=str(fake)+':'+env['PATH'];env['SMARTBOX_TEST_PCM']=str(pcm)
temp=out/'tmp';temp.mkdir(exist_ok=True);env['TMPDIR']=str(temp)
report={}
cases=[('查一下仪器身份信息','CMD_IDENTIFY_INSTRUMENT'),('帮我采集一次频率读数','CMD_MEASURE_FREQ'),('让信号源开始输出','CMD_OUTPUT_ON'),('请开始输出测试波形','CMD_OUTPUT_ON'),('不要让信号源开始输出','UNMATCHED'),('不要开始输出测试波形','UNMATCHED'),('开始输出测试波形吗','UNMATCHED'),('开始输出测试波形额外文字','UNMATCHED'),('别采集一次频率读数','UNMATCHED'),('把频率设为一千赫兹','CMD_SET_SIGNAL_FREQ'),('把频率设为负一千赫兹','UNMATCHED')]
for text,intent in cases:
    parsed=json.loads(subprocess.check_output([str(build/'voice_live_host'),'--parse-vad',text],text=True))
    assert parsed['intent_proposal']==intent,(text,parsed)
report['alias_and_rejection_cases']={'passed':True,'n':len(cases)}
file_result=subprocess.run([str(build/'voice_live_host'),str(package),'--asr',row['audio']],env=env,capture_output=True,text=True,timeout=60)
assert file_result.returncode==0,file_result.stderr
parsed=json.loads(file_result.stdout)
assert parsed['cascade_route']=='asr_only' and parsed['intent_proposal']==row['intent']
report['resident_pipeline_file']={'passed':True,'result':parsed}
# Confirm the automatic microphone route actually applies the VAD ASR guard.
p=subprocess.run([str(build/'voice_live_host'),str(package),'--once'],env=env,capture_output=True,text=True,timeout=60)
assert p.returncode==0,p.stderr
guarded=json.loads(p.stdout)
assert guarded['cascade_route']=='vad_asr_guarded' and guarded['intent_proposal']==row['intent']
report['VAD_auto_ASR_guard']={'passed':True,'result':guarded}
for mode in ('endpoint','fixed4'):
    args=[str(build/'voice_live_host'),str(package),'--fast','--once']+(['--fixed4'] if mode=='fixed4' else [])
    p=subprocess.run(args,env=env,capture_output=True,text=True,timeout=30)
    values=[json.loads(line) for line in p.stdout.splitlines() if line]
    report[mode]={'returncode':p.returncode,'results':values}
    assert p.returncode==0 and len(values)==1 and 'intent_proposal' in values[0],p.stderr
    assert values[0]['instrument_control_executed'] is False
env['SMARTBOX_TEST_IDLE']='1'
p=subprocess.Popen([str(build/'voice_live_host'),str(package),'--fast'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
time.sleep(.4);p.send_signal(signal.SIGTERM);stdout,stderr=p.communicate(timeout=10)
report['signal_shutdown']={'returncode':p.returncode,'passed':p.returncode==0}
assert p.returncode==0,(stdout,stderr)
env['SMARTBOX_TEST_EMPTY']='1'
p=subprocess.run([str(build/'voice_live_host'),str(package),'--fast','--once'],env=env,capture_output=True,text=True,timeout=10)
report['microphone_failure']={'returncode':p.returncode,'output':p.stdout}
assert p.returncode==2 and 'microphone_stream_closed' in p.stdout
report['passed']=True
(root/'reports/live_smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
