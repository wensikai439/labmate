"""Bounded ASCII framing over the existing UART; never carries shell commands."""
import base64
import json

PREFIX = b'@LABMATE4:'
MAX_RAW = 160000
MAX_LINE = 220000

def encode(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(raw) > MAX_RAW: raise ValueError('relay payload too large')
    return PREFIX + base64.b64encode(raw) + b'\n'

def decode(line):
    if len(line) > MAX_LINE or not line.startswith(PREFIX): return None
    try:
        raw = base64.b64decode(line[len(PREFIX):].strip(), validate=True)
        if len(raw) > MAX_RAW: return None
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('type') not in ('ping', 'ready', 'request', 'response'): return None
        if not isinstance(value.get('id'), str) or len(value['id']) > 64: return None
        return value
    except (ValueError, UnicodeError): return None

class Lines:
    def __init__(self): self.buffer = bytearray(); self.dropping = False
    def feed(self, chunk):
        values = []
        for byte in chunk:
            if byte == 10:
                if not self.dropping:
                    value = decode(bytes(self.buffer))
                    if value: values.append(value)
                self.buffer.clear(); self.dropping = False
            elif not self.dropping:
                self.buffer.append(byte)
                if len(self.buffer) > MAX_LINE: self.buffer.clear(); self.dropping = True
        return values
