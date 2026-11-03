import json,os,shutil,subprocess,sys
from pathlib import Path
R=Path('/home/wsk/qiansai/audio/v8_2_20261022');old=Path('/home/wsk/qiansai/audio/v8_1_20261022');cross=old/'tools/cross';headers=old/'tools/headers'
core=(R/'src/asr_probe.cpp').read_text().split('int main(int argc,char **argv) {')[0]
assert 'class ResidentAsr' in core and 'int main' not in core
(R/'src/asr_core.h').write_text(core)
voice=(old/'src/voice_live.cpp').read_text()
voice=voice.replace('static std::mutex output_mutex;','static bool progress_enabled=false;\nstatic std::mutex output_mutex;')
voice=voice.replace('if(arg=="--once")once=true;','if(arg=="--events")progress_enabled=true;else if(arg=="--once")once=true;')
voice=voice.replace('active.assign(prefix.begin(),prefix.end());prefix.clear();voiced=0;silent=0;','if(progress_enabled)emit({{"type","audio_state"},{"state","speech_started"}});\n            active.assign(prefix.begin(),prefix.end());prefix.clear();voiced=0;silent=0;')
voice=voice.replace('std::cerr<<"Ready. Speak an instruction; Ctrl+C stops.\\n";','std::cerr<<"Ready. Speak an instruction; Ctrl+C stops.\\n";\n        if(progress_enabled)emit({{"type","audio_state"},{"state","listening"}});')
voice=voice.replace('auto result=recognize(root,path,guarded?"asr":mode,asr.get());','if(progress_enabled)emit({{"type","audio_state"},{"state","recognizing"},{"endpoint_tail_ms",segment.tail_ms},{"capture_duration_ms",segment.audio.size()/16.0}});\n                auto result=recognize(root,path,guarded?"asr":mode,asr.get());')
(R/'src/voice_live.cpp').write_text(voice)
common=['-O3','-std=c++17','-ffp-contract=off','-pthread','-Wno-psabi','-I'+str(R/'src'),'-I'+str(headers)]
lib=next(Path('/home/wsk/qiansai/.venv/lib').glob('python*/site-packages/onnxruntime/capi/libonnxruntime.so.*'));hostlib=R/'build/hostlib';hostlib.mkdir(exist_ok=True)
if not (hostlib/'libonnxruntime.so.1').exists():(hostlib/'libonnxruntime.so.1').symlink_to(lib)
armflags=['-static','--sysroot='+str(cross),'-B'+str(cross/'usr/bin'),'-march=armv7-a','-mfpu=neon','-mfloat-abi=hard','-Wl,-z,noexecstack']
archives=[R/'build/libonnxruntime_mlas.a' if p.name=='libonnxruntime_mlas.a' else p for p in (old/'build/ort_arm/Release').rglob('*.a')]
commands=[]
for target,compiler,extra in [('host','g++',[]),('arm',str(cross/'usr/bin/arm-linux-gnueabihf-g++-13'),armflags)]:
    prefix=[compiler,*common,*extra]
    libs=[str(lib),'-Wl,-rpath,'+str(hostlib)] if target=='host' else ['-Wl,--start-group',*map(str,archives),'-Wl,--end-group','-ldl','-lm']
    for source,name,link in [('voice_service.cpp','voice_service',libs),('asr_client.cpp','asr_client',[])]:
        cmd=[*prefix,str(R/'src'/source),*link,'-o',str(R/'build'/f'{name}_{target}')];commands.append(cmd);subprocess.run(cmd,check=True)
    vad=old/'tools/webrtcvad/cbits';objects=list((old/'build'/('vad_'+target)).glob('*.o'))
    cmd=[*prefix,'-DWEBRTC_POSIX','-I'+str(vad),str(R/'src/voice_live.cpp'),*map(str,(vad/'webrtc/rtc_base').glob('checks.cc')),*map(str,objects),'-o',str(R/'build'/f'voice_live_{target}')];commands.append(cmd);subprocess.run(cmd,check=True)
    if target=='arm':
        cmd=[*prefix,'-I'+str(old/'tools/onnxruntime/onnxruntime/core/mlas/inc'),str(R/'src/quantize_check.cpp'),*libs,'-o',str(R/'build/quantize_check_arm')];commands.append(cmd);subprocess.run(cmd,check=True)
    # Isolated runtime fixture, without replacing old packages.
    fixture=R/'build'/('runtime_'+target)
    for part in ('bin','models','run'):(fixture/part).mkdir(parents=True,exist_ok=True)
    for name,source in [('smartbox_voice_service','voice_service'),('smartbox_asr_resident','asr_client'),('smartbox_voice_live','voice_live')]:shutil.copy2(R/'build'/f'{source}_{target}',fixture/'bin'/name)
    for name,path in [('asr',R/'models/asr_external')]:
        if not (fixture/'models'/name).exists():(fixture/'models'/name).symlink_to(path)
    fast=old/'reference/SmartBox_ZedBoard_Voice_V8_20261020/bin/smartbox_voice_armv7' if target=='arm' else old/'build/fast_host'
    shutil.copy2(fast,fixture/'bin/smartbox_voice_armv7')
(R/'reports/service_build.json').write_text(json.dumps(commands,indent=2));print('SERVICE_BUILT',flush=True)
