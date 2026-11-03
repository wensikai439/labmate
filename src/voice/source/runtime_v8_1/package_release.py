#!/usr/bin/env python3
"""Create an additive release only after regression and ARM execution gates pass."""
import datetime,hashlib,json,shutil,sys,zipfile
from pathlib import Path
root=Path(sys.argv[1]);reports=root/'reports';build=root/'build'
reference=root/'reference/SmartBox_ZedBoard_Voice_V8_20261020'
regression=json.loads((reports/'regression.json').read_text())
arm=json.loads((reports/'arm_execution.json').read_text())
assert json.loads((reports/'live_smoke.json').read_text())['passed']
assert 'VAD_auto_ASR_guard' in json.loads((reports/'live_smoke.json').read_text())
assert regression['complete'] and regression['same_audio_regression_passed']
assert regression['frontend_bitwise_mismatches']==0 and arm['passed']
assert json.loads((reports/'arm_convinteger_tests.json').read_text())['passed']
name='SmartBox_ZedBoard_Voice_V8_1_20261022';out=root/'package'/name
if out.exists():raise RuntimeError('Preserve previous release directory; inspect before rebuilding')
out.mkdir()
for folder in ('models','bin','fpga'):
    shutil.copytree(reference/folder,out/folder)
shutil.copyfile(reference/'start.sh',out/'start_legacy.sh')
shutil.copyfile(root/'src/start.sh',out/'start.sh')
shutil.copyfile(root/'src/benchmark.sh',out/'benchmark.sh')
for binary in ('smartbox_asr_resident','smartbox_voice_live'):
    shutil.copyfile(build/binary,out/'bin'/binary)
for file in (out/'bin').iterdir():file.chmod(0o755)
vad=regression['vad_default_gate_passed']
if not vad:
    script=(out/'start.sh').read_text().replace('"$root" "$@"','"$root" --fixed4 "$@"')
    (out/'start.sh').write_text(script)
shutil.copytree(reference/'source',out/'source/original_v8')
shutil.copytree(root/'src',out/'source/runtime_v8_1')
shutil.copytree(root/'tools/webrtcvad/cbits/webrtc',out/'source/webrtc')
licenses=out/'licenses';licenses.mkdir()
shutil.copyfile(root/'tools/webrtcvad/LICENSE',licenses/'WebRTC-VAD-LICENSE')
shutil.copyfile(root/'tools/onnxruntime/LICENSE',licenses/'ONNX-Runtime-LICENSE')
if (root/'tools/onnxruntime/ThirdPartyNotices.txt').exists():
    shutil.copyfile(root/'tools/onnxruntime/ThirdPartyNotices.txt',licenses/'ONNX-Runtime-ThirdPartyNotices.txt')
testout=out/'reports';testout.mkdir()
for filename in ('regression.json','arm_execution.json','arm_convinteger_patch.json','arm_convinteger_tests.json','build.json','build_host.json','replay_audio_formats.json','live_smoke.json','vad_phrase_provenance.json'):
    shutil.copyfile(reports/filename,testout/filename)
identities={}
for file in sorted((out/'models').rglob('*')):
    if file.is_file():
        relative=file.relative_to(out).as_posix();old=reference/relative
        newhash=hashlib.sha256(file.read_bytes()).hexdigest()
        assert newhash==hashlib.sha256(old.read_bytes()).hexdigest()
        identities[relative]=newhash
(testout/'unchanged_model_assets.json').write_text(json.dumps(identities,indent=2))
default='自动判断句尾后识别；连续待命' if vad else '固定 4 秒采音；连续待命（自动句尾检测未通过回归，默认关闭）'
readme=f'''# SmartBox 语音 V8.1 响应优化版

给正在运行 V8 的 ZedBoard：解压本包，进入目录，执行：

```sh
sh start.sh
```

第一次会加载模型，看到 `Ready. Speak an instruction` 后再说话。程序会一直运行，逐条输出 JSON；按 Ctrl+C 退出。默认：{default}。

```sh
ALSA_DEVICE=plughw:1,0 sh start.sh # 麦克风不是默认声卡时
sh start.sh --once              # 只识别一句
sh start.sh audio.wav           # 识别已有 16kHz/单声道/PCM16 WAV
sh start.sh --asr --once        # 强制走完整 ASR
sh start.sh --fixed4            # 固定长度采音对照，模型仍常驻
sh start.sh --legacy audio.wav  # 原 V8 程序对照
sh benchmark.sh audio.wav       # 一次加载、连续三次识别，输出分阶段耗时与峰值 RSS
```

系统要求：ZedBoard 32 位 ARMv7 Linux、可用的 ALSA 麦克风及 `arecord`。新增程序为静态链接 ARMv7/NEON ELF，无需 Python 或安装 ONNX Runtime。

本版保持 V8 的声学权重、词表、量化位宽、阈值和 CTC 束搜索不变。模型会话常驻；前端跳过零 mel 系数乘法，保留非零项累加顺序和 float64 FFT；采音与识别分离。自动切句路径补充已有训练词表中的完整指令短句，以及仪器身份、频率读数、开始输出的完整命令语法；保留原有否定、数值和单位拒识规则。没有用 dev/test 标签生成训练短句词表；语法修正在历史回归后完成，属于回归修复，不能当作全新独立测试成绩。

新增静态 ARM 运行库同时支持模型所需的 U8×S8 整数卷积。实现内部将滤波器权重和零点同时平移 128，中心化整数值完全相等；模型文件不变。补丁和整数逐值验证结果见 `source/runtime_v8_1/ort_convinteger_signed.patch` 与 `reports/arm_convinteger_tests.json`。

自动句尾检测使用 WebRTC VAD，预留 320 ms 句首、等待 800 ms 安静后提交。自动切句的音频统一用完整 V8 ASR 确认，避免旧快指令阈值在新切句长度上误触发；`--fixed4` 和文件输入保留原快指令级联路径。长停顿可能被分为两句；超过 12 秒的连续语音会报错并要求重说，不提交截断指令。识别积压会明确报错。需要保留原采音长度时用 `--fixed4`。

800 ms 是句尾判定等待，不是总响应时间；最终还要加上板上推理耗时和可能的排队时间。自动切句为保持现有回归效果使用完整 ASR，因此原先由极小指令模型直接命中的短命令不保证更快。工作站单条 ASR 的五次重复样例中位耗时从冷启动约 407 ms 降至常驻约 125 ms；这不能用于推算 ZedBoard 延迟。静态编译只免去安装运行库，不会改变板卡算力。

已完成现有合成录音的前端逐位一致性、原版/新版输出回归，以及 QEMU Cortex-A9 指令兼容检查。详情见 `reports/`。这些结果不代表新真人麦克风测试，也不是实板延迟数据；`benchmark.sh` 用于队友测量板上实际耗时。VAD 的回归结果仅覆盖这批合成录音，不能证明任意真人停顿和噪声都不影响准确率。

部署位置仍为 Zynq 的 PS/ARM。原有 `fpga/` 资料保留用于可选指令模型硬件加速，本包不含新的 `.bit`/SD 系统，也没有把 V8 Conformer 转成 PL 硬件。现有 V8 Linux 系统可直接运行本包。

权重逐文件 SHA256 与 V8 一致。校验包完整性：`sha256sum -c SHA256SUMS`。
源码、构建脚本与第三方许可证在 `source/` 和 `licenses/`。公司电脑上的构建根目录为 `/home/wsk/qiansai/audio/v8_1_20261022/`；没有删除或修改原始语音数据和其他项目。
'''
(out/'README_中文.md').write_text(readme)
manifest={'name':name,'created_UTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'target':'ZedBoard ARMv7 Cortex-A9 Linux','default':'continuous_resident_VAD' if vad else 'continuous_resident_fixed4',
          'weights_changed':False,'ASR_PL_accelerated':False,'bitstream_included':False,
          'same_audio_regression_passed':True,'frontend_bitwise_agreement':True,'VAD_synthetic_gate_passed':vad,
          'ARM_QEMU_execution_passed':True,'real_board_timing_verified':False,'real_microphone_accuracy_verified':False,'files':[]}
for file in sorted(out.rglob('*')):
    if file.is_file():manifest['files'].append({'path':file.relative_to(out).as_posix(),'bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
(out/'release_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
checksums=[]
for file in sorted(out.rglob('*')):
    if file.is_file():checksums.append(hashlib.sha256(file.read_bytes()).hexdigest()+'  '+file.relative_to(out).as_posix())
(out/'SHA256SUMS').write_text('\n'.join(checksums)+'\n')
archive=root/'package'/(name+'.zip')
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for file in sorted(out.rglob('*')):
        if file.is_file():z.write(file,name+'/'+file.relative_to(out).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for row in manifest['files']:
        data=z.read(name+'/'+row['path'])
        assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256']
release={'archive':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'VAD_default':vad,'files':len(manifest['files'])}
(reports/'release.json').write_text(json.dumps(release,indent=2));print(json.dumps(release,indent=2))
