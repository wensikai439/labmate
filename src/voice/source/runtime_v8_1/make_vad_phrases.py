#!/usr/bin/env python3
"""Recover existing supported full command phrases from TRAINING labels only."""
import collections,hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]);manifest=Path('/home/wsk/asr_v7/data/v7/manifest.jsonl')
labels=collections.defaultdict(set);partitions=set()
for line in manifest.read_text().splitlines():
    row=json.loads(line)
    if row.get('partition') not in ('train','train_only'):continue
    partitions.add(row['partition']);labels[row['text']].add(row['intent'])
allowed={'CMD_IDENTIFY_INSTRUMENT','CMD_MEASURE_FREQ','CMD_MEASURE_VPP','CMD_MEASURE_RMS','CMD_OUTPUT_ON','CMD_OUTPUT_OFF','CMD_NEXT'}
pairs=[]
for text,values in sorted(labels.items()):
    if len(values)!=1:continue
    intent=next(iter(values))
    if intent not in allowed or any(word in text for word in ('然后','并且','同时','接着','再','以及')):continue
    pairs.append((text,intent))
assert pairs,'No training-only command phrases found'
header='#pragma once\n#include <map>\n#include <string>\nstatic const std::pair<const char*,const char*> SMARTBOX_TRAINING_PHRASES[]={\n'
header+=''.join('{'+json.dumps(text,ensure_ascii=False)+','+json.dumps(intent)+'},\n' for text,intent in pairs)
header+='};\n'
path=root/'src/vad_training_phrases.h';path.write_text(header)
(root/'reports/vad_phrase_provenance.json').write_text(json.dumps({'source_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'partitions_used':sorted(partitions),'dev_test_rows_used':False,'exact_whole_phrases':len(pairs),'header_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'numeric_commands_excluded':True},indent=2))
