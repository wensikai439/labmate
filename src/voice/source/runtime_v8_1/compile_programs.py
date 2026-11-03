#!/usr/bin/env python3
import hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]);cross=root/'tools/cross'
phase=sys.argv[2] if len(sys.argv)>2 else 'both'
out=root/'build';ort=root/'tools/onnxruntime';headers=ort/'include/onnxruntime/core/session'
if (root/'tools/headers/onnxruntime_cxx_api.h').exists():headers=root/'tools/headers'
reference=root/'reference/SmartBox_ZedBoard_Voice_V8_20261020'
hostlib=next(Path('/home/wsk/asr_v7/.venv/lib').glob('python*/site-packages/onnxruntime/capi/libonnxruntime.so.*'))
local_host_lib=out/'hostlib';local_host_lib.mkdir(exist_ok=True)
if not (local_host_lib/'libonnxruntime.so.1').exists():(local_host_lib/'libonnxruntime.so.1').symlink_to(hostlib)
compile_log=[]
def run(command):
    command=list(map(str,command));compile_log.append(command.copy())
    if '-o' in command:
        index=command.index('-o')+1;destination=Path(command[index]);temporary=destination.with_name(destination.name+'.next')
        command[index]=str(temporary);subprocess.run(command,check=True);os.replace(temporary,destination)
    else:subprocess.run(command,check=True)
flags=['-O3','-std=c++17','-ffp-contract=off','-pthread','-I'+str(root/'src')]
host=['g++']+flags+['-I'+str(headers)]
if phase in ('host','both'):
    for variant in ('baseline','resident'):
        run(host+['-shared','-fPIC',root/'src'/('frontend_'+variant+'.cpp'),'-o',out/('frontend_'+variant+'.so')])
    for source,name in [(reference/'source/asr/asr_native.cpp','asr_baseline_host'),(root/'src/asr_resident.cpp','asr_resident_host')]:
        run(host+[source,hostlib,'-Wl,-rpath,'+str(local_host_lib),'-o',out/name])
armflags=['--sysroot='+str(cross),'-B'+str(cross/'usr/bin'),'-march=armv7-a','-mfpu=neon','-mfloat-abi=hard','-Wno-psabi']
arm=[cross/'usr/bin/arm-linux-gnueabihf-g++-13']+flags+armflags
if phase in ('arm','both'):
    archives=sorted((out/'ort_arm/Release').rglob('*.a'))
    if not archives:raise RuntimeError('Missing ORT static libraries')
    run(arm+['-static','-I'+str(headers),root/'src/asr_resident.cpp','-Wl,--start-group']+archives+['-Wl,--end-group','-ldl','-lm','-o',out/'smartbox_asr_resident'])
vadroot=root/'tools/webrtcvad/cbits'
cfiles=list((vadroot/'webrtc/common_audio/signal_processing').glob('*.c'))+list((vadroot/'webrtc/common_audio/vad').glob('*.c'))
extra=list((vadroot/'webrtc/rtc_base').glob('checks.cc'))
for target in (['host','arm'] if phase=='both' else [phase]):
    objects=[];folder=out/('vad_'+target);folder.mkdir(exist_ok=True)
    cc='gcc' if target=='host' else cross/'usr/bin/arm-linux-gnueabihf-gcc-13'
    for source in cfiles:
        obj=folder/(source.stem+'.o')
        run([cc,'-O2','-DWEBRTC_POSIX','-I'+str(vadroot),'-c',source,'-o',obj]+([] if target=='host' else armflags))
        objects.append(obj)
    cxx=['g++']+flags if target=='host' else arm+['-static']
    run(cxx+['-DWEBRTC_POSIX','-I'+str(vadroot),root/'src/voice_live.cpp']+extra+objects+['-o',out/('voice_live_host' if target=='host' else 'smartbox_voice_live')])
# A matching host fast model allows exact cascade comparisons on the workstation.
if phase in ('host','both'):
    run(['g++']+flags+['-I'+str(reference/'fpga/source'),reference/'fpga/source/voice_native.cpp',reference/'source/native/voice_kernel_neon.cpp','-o',out/'fast_host'])
revision=subprocess.run(['git','-C',str(ort),'rev-parse','HEAD'],capture_output=True,text=True)
report={'commands':compile_log,'compiler':subprocess.check_output([str(arm[0]),'--version'],text=True).splitlines()[0],
        'ORT_source_commit':revision.stdout.strip() if revision.returncode==0 else 'v1.22.2 (checkout pending)',
        'VAD_source_commit':subprocess.check_output(['git','-C',str(root/'tools/webrtcvad'),'rev-parse','HEAD'],text=True).strip(),
        'weights_changed':False,'frontend_math_changed':False,'frontend_skips_zero_mel_coefficients':True,'decoder_changed':False,'artifacts':{}}
if (root/'reports/arm_convinteger_patch.json').exists():report['ARM_ConvInteger_support_patch']=json.loads((root/'reports/arm_convinteger_patch.json').read_text())
for name in ([] if phase=='host' else ['smartbox_asr_resident','smartbox_voice_live']):
    elf=subprocess.check_output([str(cross/'usr/bin/arm-linux-gnueabihf-readelf'),'-h','-A','-l','-d',str(out/name)],text=True,env={**os.environ,'LC_ALL':'C'})
    (out/(name+'.elf.txt')).write_text(elf)
    header=(out/name).read_bytes()[:20]
    if 'INTERP' in elf or '(NEEDED)' in elf or header[:6]!=b'\x7fELF\x01\x01' or int.from_bytes(header[18:20],'little')!=40:raise RuntimeError('Expected static little-endian ARM32 ELF')
    report['artifacts'][name]={'bytes':(out/name).stat().st_size,'sha256':hashlib.sha256((out/name).read_bytes()).hexdigest()}
(root/('reports/build_host.json' if phase=='host' else 'reports/build.json')).write_text(json.dumps(report,indent=2))
if phase=='host':(root/'reports/host_build.complete').write_text('complete\n')
