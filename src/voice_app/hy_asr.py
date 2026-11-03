"""Bounded microphone audio -> existing authenticated localhost UART relay."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave
from urllib import request, error
from cloud import ServiceError, NoRedirect

MODEL = 'hy-asr-3.0-preview'


def transcribe(audio, env=None, opener=None):
    env = os.environ if env is None else env
    token = env.get('LABMATE_RELAY_TOKEN', '')
    if len(token) < 24 or not token.isascii():
        raise ServiceError('Hy 电脑转发尚未配置；可使用 --engine local 进行板端识别', 'hy_unavailable', 503)
    started = time.monotonic()
    with wave.open(str(audio), 'rb') as wav:
        duration = round(wav.getnframes() * 1000 / wav.getframerate())
    target = Path(audio).with_suffix('.mp3')
    try:
        subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('mp3_encode.py')),
                        str(audio), str(target)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=15)
        data = target.read_bytes()
    except (OSError, subprocess.SubprocessError):
        raise ServiceError('录音压缩失败；可使用 --engine local 进行板端识别', 'hy_encode', 503) from None
    if not 0 < len(data) <= 65000 or not 100 <= duration <= 6000:
        raise ServiceError('Hy 录音长度超出限制', 'hy_audio', 400)
    encoded_at = time.monotonic()
    payload = dict(model=MODEL, data=base64.b64encode(data).decode('ascii'),
                   voice_encode_format='mp3', duration_ms=duration)
    req = request.Request('http://127.0.0.1:8767/asr/transcribe', method='POST',
                          data=json.dumps(payload).encode(),
                          headers={'Content-Type': 'application/json', 'X-LabMate-Relay': token})
    opener = opener or request.build_opener(request.ProxyHandler({}), NoRedirect()).open
    try:
        with opener(req, timeout=120) as response:
            raw = response.read(20001)
        if len(raw) > 20000:
            raise ValueError()
        value = json.loads(raw)
        text = value['text']
        if not isinstance(text, str) or len(text) > 4000:
            raise ValueError()
    except error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise ServiceError('Hy 识别未完成（HTTP %s）；可使用 --engine local 进行板端识别，本次不自动重试' % code,
                           'hy_http', 503) from None
    except (OSError, ValueError, KeyError, TypeError):
        raise ServiceError('Hy 电脑转发未连接或识别超时；可使用 --engine local 进行板端识别，本次不自动重试',
                           'hy_network', 503) from None
    return dict(instrument_control_executed=False, intent_proposal='UNMATCHED', transcript=text,
                timing_ms=dict(encode=round((encoded_at-started)*1000),
                               relay_and_api=round((time.monotonic()-encoded_at)*1000),
                               provider=value.get('provider_ms'), total=round((time.monotonic()-started)*1000)),
                audio_bytes=len(data))
