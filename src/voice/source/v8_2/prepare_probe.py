"""Read V8.1 assets and create isolated runtime-instrumentation candidates."""
import json,shutil
from pathlib import Path
R=Path('/home/wsk/qiansai/audio/v8_2_20261022');old=Path('/home/wsk/qiansai/audio/v8_1_20261022')
for name in ('models','build','reports','cache','src'):(R/name).mkdir(exist_ok=True)
model=old/'reference/SmartBox_ZedBoard_Voice_V8_20261020/models/asr'
if not (R/'models/asr').exists():(R/'models/asr').symlink_to(model)
for name in ('asr_frontend_constants.h','ctc_context_decoder.h','intent_slots_native.h','voice_live.cpp','vad_training_phrases.h'):
    shutil.copyfile(old/'src'/name,R/'src'/name)
(R/'src/vendor').mkdir(exist_ok=True)
shutil.copyfile(old/'src/vendor/json.hpp',R/'src/vendor/json.hpp')
source=(old/'src/asr_resident.cpp').read_text()
source=source.replace('#include <chrono>','#include <cstdlib>\n#include <chrono>',1)
source=source.replace('options.SetIntraOpNumThreads(2); options.SetInterOpNumThreads(1);','''
        int threads=getenv("ASR_THREADS")?std::stoi(getenv("ASR_THREADS")):2;
        options.SetIntraOpNumThreads(threads); options.SetInterOpNumThreads(1);
''')
source=source.replace('options.DisableMemPattern(); options.DisableCpuMemArena();','''
        options.DisableMemPattern();
        if(!getenv("ASR_ARENA") || std::string(getenv("ASR_ARENA"))!="1")options.DisableCpuMemArena();
''')
source=source.replace('options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_BASIC);','''
        std::string level=getenv("ASR_OPT")?getenv("ASR_OPT"):"basic";
        options.SetGraphOptimizationLevel(level=="all"?GraphOptimizationLevel::ORT_ENABLE_ALL:level=="extended"?GraphOptimizationLevel::ORT_ENABLE_EXTENDED:GraphOptimizationLevel::ORT_ENABLE_BASIC);
        if(getenv("ASR_PROFILE"))options.EnableProfiling(getenv("ASR_PROFILE"));
''')
source=source.replace('auto proposal=smartbox_slots::parse(text);','''double combined_decode_ms=millis(decode_start);
        auto proposal=smartbox_slots::parse(text);''')
source=source.replace('<<millis(decode_start)','<<combined_decode_ms')
(R/'src/asr_probe.cpp').write_text(source)
import onnx,collections,numpy as np
report={'models':{}}
for name in ('encoder.quant.onnx','ctc.quant.onnx'):
    net=onnx.load(model/name)
    sizes=[]
    for t in net.graph.initializer:
        sizes.append({'name':t.name,'shape':list(t.dims),'type':t.data_type,'bytes':len(t.raw_data)})
    report['models'][name]={'bytes':(model/name).stat().st_size,'ops':dict(collections.Counter(n.op_type for n in net.graph.node)),'types_bytes':dict(collections.Counter({str(t):sum(v['bytes'] for v in sizes if v['type']==t) for t in set(v['type'] for v in sizes)})),'largest_initializers':sorted(sizes,key=lambda v:v['bytes'],reverse=True)[:15]}
(R/'reports/model_audit.json').write_text(json.dumps(report,indent=2))
rows=[json.loads(line) for line in (old/'reports/replay_manifest.jsonl').read_text().splitlines()]
selected=[]
for sec in (1.5,2.5,4.,6.):
    candidates=[row for row in rows if row['partition']=='dev']
    selected.append(min(candidates,key=lambda row:abs(row['duration_s']-sec)))
(R/'reports/probe_samples.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2))
print(json.dumps(report,indent=2),flush=True)
