"""Create a new self-contained release; never alter the previous release."""
import hashlib,json,os,shutil,stat,subprocess,zipfile
from pathlib import Path
R=Path('/home/wsk/qiansai/audio/v8_2_20261022');old=Path('/home/wsk/qiansai/audio/v8_1_20261022')
name='SmartBox_ZedBoard_Voice_V8_2_20261022';out=R/'release'/name;out.parent.mkdir(exist_ok=True)
assert not out.exists(),'Use a fresh release directory to avoid mixing artifacts'
quality=json.loads((R/'reports/service_validation.json').read_text());interaction=json.loads((R/'reports/interaction.json').read_text());arm=json.loads((R/'reports/arm_benchmark.json').read_text());numeric=json.loads((R/'reports/numeric.log').read_text())
assert quality['historical_replay']['mismatch_count']==0 and quality['historical_replay']['inferences']==1654 and interaction['passed'] and numeric['mismatches']==0
original=old/'package/SmartBox_ZedBoard_Voice_V8_1_20261022'
shutil.copytree(original,out,ignore=shutil.ignore_patterns('reports','release_manifest.json','SHA256SUMS','README_中文.md'))
(out/'reports/v8_1_reference').mkdir(parents=True)
for source in (original/'reports').iterdir():
    if source.is_file():shutil.copy2(source,out/'reports/v8_1_reference'/source.name)
(out/'reports/v8_1_reference/说明.txt').write_text('本目录是 V8.1 历史报告，不是 V8.2 的新测量。V8.2 报告在上一层目录。\n')
for source in (R/'models/asr_external').iterdir():shutil.copy2(source,out/'models/asr'/source.name)
for target,source in [('smartbox_asr_resident','asr_client_arm'),('smartbox_voice_service','voice_service_arm'),('smartbox_voice_live','voice_live_arm')]:
    dest=out/'bin'/target;shutil.copy2(R/'build'/source,dest);subprocess.run([str(old/'tools/cross/usr/bin/arm-linux-gnueabihf-strip'),'--strip-unneeded',str(dest)],check=True);dest.chmod(0o755)
for name2 in ('start.sh','warmup.sh','status.sh','stop.sh','diagnose.sh','README_中文.md'):shutil.copy2(R/'src'/name2,out/name2)
for source in (R/'src').iterdir():
    if source.suffix in ('.cpp','.h','.py','.sh'):
        dest=out/'source/v8_2'/source.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
for report in ('service_validation.json','interaction.json','arm_benchmark.json','external_weights.json','quantize_patch.json','model_audit.json','numeric.log','service_build.json'):
    shutil.copy2(R/'reports'/report,out/'reports'/report)
group=Path('/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/qiansai.slice')
resource={'cpu_logical':os.cpu_count(),'cpu_max':(group/'cpu.max').read_text().strip(),'memory_max_bytes':int((group/'memory.max').read_text()),'memory_peak_bytes':int((group/'memory.peak').read_text()),'memory_events':(group/'memory.events').read_text(),'gpu_used':False,'scope':'All heavy work for this audio task used qiansai.slice; CPU quota 5 cores / 12 logical = 41.67%; RAM cap 3 GiB; no GPU jobs.'}
(out/'reports/resource_limit.json').write_text(json.dumps(resource,indent=2))
lines=[]
for item in arm['runs']:
    if item['version']=='v8_2_external_patched':
        previous=next(v for v in arm['runs'] if v['version']=='v8_1_original' and v['audio']==item['audio'])
        lines.append(f"| {item['duration_s']:.2f} 秒 | {previous['median_total_ms']/1000:.2f} 秒 | {item['median_total_ms']/1000:.2f} 秒 | {(1-item['median_total_ms']/previous['median_total_ms'])*100:.1f}% |")
report='''# V8.2 优化结果

## 已完成

1. 常驻服务跨多次按钮调用保留模型；复用已有 V8.1 输入接口。
2. 主界面启动时可预热，按钮仍只负责收音；增加可选状态事件。
3. 外部权重布局和 ARMv7 精确取整优化。权重数值、特征、VAD、搜索宽度及规则未改变。

## 识别一致性

- 历史合成数据 827 段，原音频和 VAD 音频共 1654 次推理：转写、意图、频率槽位等与 V8.1 对照 0 差异。
- 以上是旧数据一致性检查，不是新真人录音准确率；没有用它宣称泛化率。
- ARM 精确量化：90 组参数和取整模式检查，约 927 万个值，0 差异。
- 三个独立按钮程序调用使用同一服务 PID，模型加载次数保持 1；忙碌请求不进入服务队列。
- 状态事件、默认最终 JSON、麦克风失败和坏文件恢复检查通过。

## 耗时

下表是公司 x86 工作站上 QEMU Cortex-A9 模拟，均为已加载后总处理时间的三次中位数；不是 ZedBoard 实板性能，也不包含录音时间或 800 ms 句尾等待。

| 音频时长 | V8.1 | V8.2 | 改善 |
|---|---|---|---|
'''+ '\n'.join(lines)+'''

工作站原生的独立客户端重复调用，连接已热服务的等待约 0.14～0.18 ms；这是客户端连接耗时，不是识别耗时。
模拟环境首次模型加载约 1.75 秒；预热移出按钮流程后，后续调用不再重复加载。

**编码器计算只改善约 1%～5%，仍是主要瓶颈。这一版不能承诺把“约 30 秒”的主观体感降到即时响应。**
若板上 V8.1 原本已在按钮之间保留进程，常驻优化的收益也会较小。
真正的剩余延迟需在板卡用同一 WAV、`diagnose.sh` 和 JSON 分项测量；尤其应排查内存换页、CPU 频率及 UI/视频争用。

## 部署边界

Zynq ARM CPU 软件包；未更新 FPGA 逻辑。模型存储约 97 MB，RAM 需要另算。
QEMU 服务首次加载后 RSS 约 134 MiB；工作站回放后 RSS 约 163 MiB，均不包含板卡 Linux、UI、视频的总占用，不能当作板卡 RAM 结论。
没有连接板卡，未做实板麦克风、延迟或总内存验收。

公司端本项目 CPU 硬上限 41.67%、RAM 上限 3 GiB；没有使用 GPU。详见 `reports/resource_limit.json`。
'''
(out/'优化结果.md').write_text(report)
manifest={'version':'8.2','architecture':'armv7-linux-gnueabihf','execution':'Zynq PS Cortex-A9 CPU, no new PL bitstream','board_runtime_verified':False,'weights_changed':False,'historical_replay_mismatches':0,'microphone_activation':'button only; model service does not capture audio','files':{}}
for file in sorted(out.rglob('*')):
    if file.is_file():
        if file.suffix=='.sh':file.chmod(0o755);subprocess.run(['/bin/sh','-n',str(file)],check=True)
        if file.suffix=='.py':compile(file.read_text(),str(file),'exec')
        if file.parent==out/'bin':
            info=subprocess.check_output([str(old/'tools/cross/usr/bin/arm-linux-gnueabihf-readelf'),'-h',str(file)],text=True);assert 'ELF32' in info and 'ARM' in info
        manifest['files'][str(file.relative_to(out))]={'bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
(out/'release_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
checks=''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+str(f.relative_to(out))+'\n' for f in sorted(out.rglob('*')) if f.is_file())
(out/'SHA256SUMS').write_text(checks)
archive=out.parent/(out.name+'.zip')
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for file in sorted(out.rglob('*')):
        if file.is_file():z.write(file,file.relative_to(out.parent))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for path,meta in manifest['files'].items():assert hashlib.sha256(z.read(out.name+'/'+path)).hexdigest()==meta['sha256']
summary={'path':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'members':len(manifest['files'])+2,'validated':True}
(R/'reports/release.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True)
