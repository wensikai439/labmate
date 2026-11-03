"""Check supplied evaluation inputs and recompute statistics from per-sample records."""
import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/evaluation'
IGNORED = {'timing_ms', 'backend', 'process_peak_rss_kib', 'memory', 'asr_service_pid',
           'model_load_count', 'service_model_load_ms', 'service_model_reused',
           'service_queue_wait_ms', 'service_startup_wait_ms'}


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]


def comparable(value):
    return {k: v for k, v in value.items() if k not in IGNORED}


def distance(a, b):
    last = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        now = [i]
        for j, y in enumerate(b, 1):
            now.append(min(now[-1] + 1, last[j] + 1, last[j - 1] + (x != y)))
        last = now
    return last[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    checks = []
    def check(name, passed, **details):
        checks.append({'name': name, 'passed': bool(passed), **details})
    inventory = json.loads((DATA / 'files.json').read_text(encoding='utf-8'))
    failures = [p for p, digest in inventory.items() if not (DATA / p).is_file() or hashlib.sha256((DATA / p).read_bytes()).hexdigest() != digest]
    check('input_sha256', not failures, files=len(inventory), failures=failures)
    manifest = rows(DATA / 'voice/replay_manifest.jsonl')
    by_id = {r['id']: r for r in manifest}
    audio = json.loads((DATA / 'voice/audio_index.json').read_text(encoding='utf-8'))
    check('voice_sample_ids', len(by_id) == len(manifest) == len(audio) == 827 and set(by_id) == {r['id'] for r in audio})
    check('voice_partitions', {p: sum(r['partition'] == p for r in manifest) for p in ('dev', 'test')} == {'dev': 412, 'test': 415})
    check('voice_sample_format', all(r['sample_rate'] == 16000 and abs(r['samples'] / 16000 - by_id[r['id']]['duration_s']) < 1e-4 for r in audio))
    reference = DATA / 'voice/reference_results'
    old = {}
    summary = json.loads((reference / 'v8.1_regression.json').read_text(encoding='utf-8'))
    for partition in ('dev', 'test'):
        records = rows(reference / ('v8.1_' + partition + '_replay.jsonl'))
        expected = summary['partitions'][partition]
        old.update({r['id']: r for r in records})
        check(partition + '_record_ids', len(records) == expected['samples'] and {r['id'] for r in records} == {r['id'] for r in manifest if r['partition'] == partition})
        errors = sum(distance(by_id[r['id']]['text'], r['baseline']['transcript']) for r in records)
        characters = sum(len(by_id[r['id']]['text']) for r in records)
        check(partition + '_cer', errors == expected['original_asr_errors'] and characters == expected['original_characters'], errors=errors, characters=characters, cer=errors / characters)
        changed = sum(r['baseline']['transcript'] != r['vad']['transcript'] for r in records)
        check(partition + '_vad_transcripts', changed == expected['vad_transcript_changes'], changed=changed)
        check(partition + '_resident_outputs', all(comparable(r['baseline']) == comparable(r['resident']) for r in records))
    service = rows(reference / 'v8.2_service_replay.jsonl')
    keys = [(r['id'], r['route']) for r in service]
    check('service_coverage', len(keys) == len(set(keys)) == 1654 and set(keys) == {(i, route) for i in by_id for route in ('full', 'vad')})
    differences = [r['id'] + ':' + r['route'] for r in service if comparable(r['result']) != comparable(old[r['id']]['resident' if r['route'] == 'full' else 'vad'])]
    check('service_outputs', not differences, inferences=len(service), differences=differences)
    check('service_model_reuse', len({r['result']['asr_service_pid'] for r in service}) == 1 and all(r['result']['model_load_count'] == 1 for r in service))
    probes = json.loads((DATA / 'voice/original_probe_samples.json').read_text(encoding='utf-8'))
    check('benchmark_audio', len(probes) >= 3 and all(Path(r['audio']).stem in by_id for r in probes[:3]))
    result = {'method': 'Input integrity and recomputation of saved per-sample outputs', 'checks': checks, 'passed': all(c['passed'] for c in checks)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': len(checks), 'passed': result['passed'], 'failed': [c['name'] for c in checks if not c['passed']]}))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
