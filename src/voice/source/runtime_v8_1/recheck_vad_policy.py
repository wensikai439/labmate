#!/usr/bin/env python3
"""Re-score previously recorded real inference outputs under the guarded policy.

No acoustic scores are changed or regenerated. Preserve the rejected cascade
result so the reason for the runtime guard remains independently inspectable.
"""
import json,shutil,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]);reports=root/'reports'
original=reports/'regression_before_vad_guard.json'
if not original.exists():shutil.copyfile(reports/'regression.json',original)
report=json.loads(original.read_text())
labels={r['id']:(r.get('intent') or 'UNMATCHED') for r in map(json.loads,(reports/'replay_manifest.jsonl').read_text().splitlines())}
def decision(v):return {k:v.get(k) for k in ('intent_proposal','frequency_hz','confirmation_required','instrument_control_executed')}
for partition,result in report['partitions'].items():
    result['rejected_unguarded_fast_route_regressions']=result['vad_command_regressions']
    regressions=0;decisions=0;rejections=0;rejection_regressions=0
    for line in (reports/(partition+'_replay.jsonl')).read_text().splitlines():
        row=json.loads(line)
        if 'vad' not in row:regressions+=1;continue
        guarded=json.loads(subprocess.check_output([str(root/'build/voice_live_host'),'--parse-vad',row['vad']['transcript']],text=True))
        changed=decision(row['baseline_cascade'])!=decision(guarded)
        baseline_correct=row['baseline_cascade']['intent_proposal']==labels[row['id']]
        regressions+=bool(baseline_correct and changed)
        if labels[row['id']]=='UNMATCHED':
            rejections+=1
            rejection_regressions+=bool(baseline_correct and changed)
        decisions+=decision(row['baseline'])!=decision(row['vad'])
    result['vad_command_regressions']=regressions
    result['vad_asr_decision_changes']=decisions
    result['negative_samples']=rejections
    result['vad_correct_rejection_regressions']=rejection_regressions
report['vad_policy']='Endpointed live audio uses unchanged full V8 ASR and exact whole command phrases from training labels only. Original fast cascade retained for fixed-window and file modes.'
report['vad_default_gate_passed']=all(x['vad_command_regressions']==0 for x in report['partitions'].values())
report['guard_selected_after_historical_test_replay']=True
report['scope']='Existing synthetic regression replay; includes a post-replay runtime policy fix, not a fresh independent accuracy benchmark.'
(reports/'regression.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
