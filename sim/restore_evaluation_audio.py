"""Restore the 827 evaluation WAV files and verify their original SHA-256."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def restore(output):
    import soundfile as sf
    data = ROOT / 'data/evaluation/voice'
    index = json.loads((data / 'audio_index.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=True)
    for row in index:
        source = data / row['file']
        assert hashlib.sha256(source.read_bytes()).hexdigest() == row['flac_sha256'], source
        samples, rate = sf.read(source, dtype='int16')
        assert rate == row['sample_rate'] and samples.ndim == 1 and len(samples) == row['samples']
        wav = base64.b64decode(row['wav_prefix_base64']) + samples.astype('<i2').tobytes() + base64.b64decode(row['wav_suffix_base64'])
        assert hashlib.sha256(wav).hexdigest() == row['wav_sha256'], row['id']
        destination = output / (row['id'] + '.wav')
        if destination.exists():
            if destination.read_bytes() != wav:
                raise FileExistsError('Existing WAV differs: ' + str(destination))
        else:
            destination.write_bytes(wav)
    return {'method': 'Lossless FLAC decoding and original RIFF reconstruction', 'restored': len(index), 'sha256_matches': len(index)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = restore(args.output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
