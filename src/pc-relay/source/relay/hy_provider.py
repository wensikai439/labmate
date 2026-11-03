"""Fixed Tencent ASR destination. Credentials stay encrypted on this Windows PC."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import time
from urllib import request, error

MODEL = 'hy-asr-3.0-preview'
ENDPOINT = 'https://tokenhub.tencentmaas.com/v1/wand/asrproxy/sync_transcribe'


def load_key(path=None):
    # Current-user DPAPI; no plaintext key in sources, argv, board or browser.
    if os.name != 'nt':
        return ''
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    try:
        raw = Path(path or Path(__file__).resolve().parents[2] / '.hy-asr.key.dpapi').read_bytes()
        buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        src, dst = Blob(len(raw), buf), Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst)):
            return ''
        try:
            return ctypes.string_at(dst.data, dst.size).decode('ascii').strip()
        finally:
            ctypes.windll.kernel32.LocalFree(ctypes.cast(dst.data, ctypes.c_void_p))
    except (OSError, ValueError, UnicodeError):
        return ''


def validate(value):
    if not isinstance(value, dict) or set(value) != {'model', 'data', 'voice_encode_format', 'duration_ms'}:
        raise ValueError()
    if value['model'] != MODEL or value['voice_encode_format'] != 'mp3':
        raise ValueError()
    if type(value['duration_ms']) is not int or not 100 <= value['duration_ms'] <= 6000:
        raise ValueError()
    if not isinstance(value['data'], str) or len(value['data']) > 87000:
        raise ValueError()
    audio = base64.b64decode(value['data'], validate=True)
    if not 4 <= len(audio) <= 65000 or not (audio.startswith(b'ID3') or audio[0] == 255 and audio[1] & 224 == 224):
        raise ValueError()
    return {k: value[k] for k in ('model', 'data', 'voice_encode_format')}


def forward(payload, key, opener):
    try:
        body = validate(payload)
    except (ValueError, TypeError, KeyError):
        return 400, {'error': 'invalid bounded Hy audio request'}
    if not key:
        return 503, {'error': 'Hy key is not configured on PC'}
    req = request.Request(ENDPOINT, method='POST', data=json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+key})
    started = time.monotonic()
    try:
        with opener(req, timeout=60) as response:
            raw = response.read(128001)
        if len(raw) > 128000:
            raise ValueError()
        value = json.loads(raw)
        if value.get('status') != 'completed':
            raise ValueError()
        text = value['output']['text']
        if not isinstance(text, str) or len(text) > 4000:
            raise ValueError()
        return 200, dict(text=text, model=MODEL, provider_ms=round((time.monotonic()-started)*1000))
    except error.HTTPError as exc:
        status = exc.code
        exc.close()
        return status, {'error': 'Hy provider rejected request'}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 502, {'error': 'Hy connection or response failed; no automatic retry'}
