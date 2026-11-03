"""Preserve weight arrays, store them externally, and patch only task-owned MLAS."""
import hashlib,json,re,shlex,shutil,subprocess
from pathlib import Path
import onnx,numpy as np
from onnx import numpy_helper
R=Path('/home/wsk/qiansai/audio/v8_2_20261022');old=Path('/home/wsk/qiansai/audio/v8_1_20261022')
dest=R/'models/asr_external';dest.mkdir(exist_ok=True)
provenance={}
for name in ('encoder.quant.onnx','ctc.quant.onnx'):
    source=R/'models/asr'/name;net=onnx.load(source)
    hashes={t.name:hashlib.sha256(numpy_helper.to_array(t).tobytes()).hexdigest() for t in net.graph.initializer}
    weights=name.replace('.onnx','.weights.bin');target=dest/name
    if not target.exists():onnx.save_model(net,target,save_as_external_data=True,all_tensors_to_one_file=True,location=weights,size_threshold=1024,convert_attribute=False)
    check=onnx.load(target);assert hashes=={t.name:hashlib.sha256(numpy_helper.to_array(t).tobytes()).hexdigest() for t in check.graph.initializer}
    provenance[name]={'all_initializer_values_identical':True,'original_bytes':source.stat().st_size,'graph_bytes':target.stat().st_size,'weights_bytes':(dest/weights).stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
for file in (R/'models/asr').iterdir():
    if file.is_file() and file.suffix!='.onnx' and not file.name.endswith('.weights.bin'):shutil.copyfile(file,dest/file.name)
(R/'reports/external_weights.json').write_text(json.dumps(provenance,indent=2))
source=old/'tools/onnxruntime/onnxruntime/core/mlas/lib/quantize.cpp';text=source.read_text()
text=text.replace('#include "mlasi.h"','#include "mlasi.h"\n#include <cfenv>\n#if defined(__arm__) && defined(__ARM_NEON)\n#include <arm_neon.h>\n#endif',1)
needle='''    for (size_t n = 0; n < N; n++) {

        float FloatValue = std::nearbyintf(Input[n] / Scale) + float(ZeroPoint);'''
replacement='''    size_t start = 0;
#if defined(__arm__) && defined(__ARM_NEON)
    // ARMv7 has no VCVTN. Use exact float division, then an IEEE754 RNE
    // integer-bias addition on clamped finite values. No reciprocal approximation.
    if (std::fegetround() == FE_TONEAREST && Scale > 0.f && std::isfinite(Scale)) {
        const float32x4_t lower=vdupq_n_f32(float(MinimumValue)-float(ZeroPoint));
        const float32x4_t upper=vdupq_n_f32(float(MaximumValue)-float(ZeroPoint));
        const float32x4_t magic=vdupq_n_f32(12582912.f);
        const int32x4_t bits=vdupq_n_s32(0x4b400000), zero=vdupq_n_s32(int32_t(ZeroPoint));
        for (; start+4<=N;start+=4) {
            float divided[4]={Input[start]/Scale,Input[start+1]/Scale,Input[start+2]/Scale,Input[start+3]/Scale};
            if (!(std::isfinite(divided[0]) && std::isfinite(divided[1]) && std::isfinite(divided[2]) && std::isfinite(divided[3]))) {
                for(int i=0;i<4;++i){float q=std::nearbyintf(Input[start+i]/Scale)+float(ZeroPoint);q=std::max(q,float(MinimumValue));q=std::min(q,float(MaximumValue));Output[start+i]=(OutputType)(int32_t)q;}
                continue;
            }
            float32x4_t q=vminq_f32(vmaxq_f32(vld1q_f32(divided),lower),upper);
            int32x4_t rounded=vaddq_s32(vsubq_s32(vreinterpretq_s32_f32(vaddq_f32(q,magic)),bits),zero);
            int32_t values[4];vst1q_s32(values,rounded);
            for(int i=0;i<4;++i)Output[start+i]=(OutputType)values[i];
        }
    }
#endif
    for (size_t n = start; n < N; n++) {

        float FloatValue = std::nearbyintf(Input[n] / Scale) + float(ZeroPoint);'''
assert text.count(needle)==1;text=text.replace(needle,replacement)
(R/'src/quantize_arm32.cpp').write_text(text)
build=old/'build/ort_arm/Release';ninja=old/'tools/build_env/bin/ninja'
contents=(build/'build.ninja').read_text();target=re.search(r'^build (\S*[/]quantize\.cpp\.o):',contents,re.M).group(1)
command=shlex.split(subprocess.check_output([str(ninja),'-C',str(build),'-t','commands',target],text=True).strip().splitlines()[-1]);clean=[];i=0
while i<len(command):
    if command[i] in ('-MF','-MT','-MQ'):i+=2;continue
    if command[i] in ('-MD','-MMD'):i+=1;continue
    if command[i]=='-o':clean+=['-o',str(R/'build/quantize.cpp.o')];i+=2;continue
    if command[i]=='-c':clean+=['-c',str(R/'src/quantize_arm32.cpp')];i+=2;continue
    clean.append(command[i]);i+=1
subprocess.run(clean,check=True,cwd=build)
archive=R/'build/libonnxruntime_mlas.a';shutil.copyfile(build/'libonnxruntime_mlas.a',archive)
subprocess.run([str(old/'tools/cross/usr/bin/arm-linux-gnueabihf-ar'),'r',str(archive),str(R/'build/quantize.cpp.o')],check=True)
(R/'reports/quantize_patch.json').write_text(json.dumps({'source':str(source),'modified_original':False,'patched_source_sha256':hashlib.sha256(text.encode()).hexdigest(),'arithmetic':'same scalar division, exact IEEE754 round-to-nearest-even; non-finite/non-default-rounding paths fall back','command':clean},indent=2))
print('EXACT_ASSETS_READY',flush=True)
