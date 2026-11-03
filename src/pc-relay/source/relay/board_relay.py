"""Run in the logged-in board serial terminal; localhost HTTP -> PC UART relay."""
import hmac
import json
import os
import queue
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from protocol import encode, Lines, MAX_RAW

def main():
    import termios, tty
    token = os.environ.get('LABMATE_RELAY_TOKEN', '')
    if len(token) < 24 or not token.isascii(): raise SystemExit('Set LABMATE_RELAY_TOKEN (at least 24 ASCII characters) in the board environment first.')
    if not sys.stdin.isatty(): raise SystemExit('Start this in the board UART terminal, not as a background pipe.')
    busy = threading.Lock(); send_lock = threading.Lock(); pending = {}; mutex = threading.Lock()
    def send(value):
        data = encode(value)
        with send_lock: sys.stdout.buffer.write(data); sys.stdout.buffer.flush()
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers()
            try: self.wfile.write(data)
            except OSError: pass
        def do_POST(self):
            if self.path not in ('/chat/completions', '/asr/transcribe') or not hmac.compare_digest(self.headers.get('X-LabMate-Relay', '').encode('utf-8'), token.encode('ascii')):
                self.reply(403, {'error':'relay authorization failed'}); return
            if not busy.acquire(False): self.reply(429, {'error':'relay busy'}); return
            key = uuid.uuid4().hex
            try:
                self.connection.settimeout(10)
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size < MAX_RAW - 2000: raise ValueError()
                payload = json.loads(self.rfile.read(size))
                inbox = queue.Queue(maxsize=1)
                with mutex: pending[key] = inbox
                send({'type':'request', 'id':key, 'payload':payload,
                      'service':'hy_asr' if self.path == '/asr/transcribe' else 'deepseek'})
                response = inbox.get(timeout=110)
                status = response.get('status')
                if type(status) is not int or not 200 <= status <= 599: raise ValueError()
                self.reply(status, response.get('body', {'error':'invalid PC response'}))
            except queue.Empty: self.reply(504, {'error':'PC relay timeout; no automatic retry'})
            except (ValueError, OSError): self.reply(400, {'error':'invalid relay request'})
            finally:
                with mutex: pending.pop(key, None)
                busy.release()
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 8767), Handler)
    server.daemon_threads = True
    old = termios.tcgetattr(sys.stdin.fileno())
    try:
        # Full raw mode avoids echo, canonical line truncation and XON/XOFF.
        tty.setraw(sys.stdin.fileno())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        send({'type':'ready','id':'startup'})
        lines = Lines()
        while True:
            chunk = os.read(sys.stdin.fileno(), 4096)
            if not chunk: break
            # Ctrl-C from a serial terminal explicitly exits and restores it.
            if b'\x03' in chunk: break
            for value in lines.feed(chunk):
                if value['type'] == 'ping': send({'type':'ready','id':value['id']})
                elif value['type'] == 'response':
                    with mutex:
                        inbox = pending.get(value['id'])
                        if inbox and inbox.empty(): inbox.put_nowait(value)
    finally:
        server.shutdown(); server.server_close(); termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, old)

if __name__ == '__main__': main()
