"""Resident voice runtime with admission checks for the shared memory budget."""
import atexit
import json
import os
from pathlib import Path
import selectors
import signal
import shutil
import subprocess
import tempfile
import threading
import time


def check_memory_budget():
    values = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemAvailable:', 'SwapFree:'))}
    available = values.get('MemAvailable', 0)
    if available < 24*1024 or available + values.get('SwapFree', 0) < 192*1024:
        raise RuntimeError('当前内存余量不足，已暂停本次识别以保护语音服务；请稍候重试')


class ModelRuntime:
    def __init__(self):
        self.lock = threading.RLock()
        self.child = None
        self.key = None
        self.service_root = None
        self.folder = None
        self.buffer = b''
        atexit.register(self.close)

    def _line(self, timeout):
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(self.child.stdout, selectors.EVENT_READ)
            while b'\n' not in self.buffer:
                if not selector.select(max(0, deadline-time.monotonic())):
                    raise TimeoutError('模型运行超时，请缩短录音或稍后重试')
                block = os.read(self.child.stdout.fileno(), 4096)
                if not block:
                    raise RuntimeError('模型进程退出，请检查内存和模型文件')
                self.buffer += block
                if len(self.buffer) > 65536:
                    raise RuntimeError('模型返回内容过长')
            line, self.buffer = self.buffer.split(b'\n', 1)
        value = json.loads(line)
        if not isinstance(value, dict) or value.get('error'):
            raise RuntimeError('模型处理失败：' + str(value.get('error', '无效结果') if isinstance(value, dict) else '无效结果')[:180])
        return value

    def _close(self):
        if self.child is not None:
            self.child.terminate()
            try:
                self.child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.child.kill(); self.child.wait()
            self.child.stdin.close(); self.child.stdout.close()
        self.child = None
        self._stop_service()
        self.key = None
        self.buffer = b''
        if self.folder is not None:
            self.folder.cleanup()
            self.folder = None

    def _stop_service(self):
        root = self.service_root
        if root is None:
            return
        # Only this exact package's daemon may be stopped. Never kill by process name.
        try:
            pid = int((root/'run/service.pid').read_text().strip())
        except (OSError, ValueError):
            self.service_root = None
            return
        expected = str(root/'bin/smartbox_voice_service').encode()
        def owned():
            try:
                cmd = Path('/proc/%s/cmdline' % pid).read_bytes().split(b'\0')
                return cmd[:2] == [expected, str(root).encode()]
            except OSError:
                return False
        if owned():
            try:
                subprocess.run([str(root/'bin/smartbox_asr_resident'), '--stop', str(root)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            except subprocess.TimeoutExpired:
                pass
            deadline = time.monotonic()+5
            while owned() and time.monotonic()<deadline:
                time.sleep(.05)
            if owned():
                os.kill(pid, signal.SIGTERM)
                deadline = time.monotonic()+2
                while owned() and time.monotonic()<deadline:
                    time.sleep(.05)
            if owned():
                os.kill(pid, signal.SIGKILL)
                deadline = time.monotonic()+2
                while owned() and time.monotonic()<deadline:
                    time.sleep(.05)
            if owned():
                raise RuntimeError('语音模型尚未释放')
        self.service_root = None

    def warmup(self, root):
        return self.request('voice', root, None)

    def close(self):
        with self.lock:
            self._close()

    def close_voice(self, root):
        with self.lock:
            # Also adopt the exact-package daemon left by a previous server.
            # _stop_service verifies both executable and root before stopping it.
            if self.key is not None and self.key[0] != 'voice':
                raise RuntimeError('Voice runtime state is invalid')
            self.service_root = Path(root).resolve()
            self._close()

    def request(self, kind, root, request, timeout=120):
        if kind != 'voice':
            raise ValueError('Only voice runtime is included')
        root = Path(root).resolve()
        key = (kind, str(root.resolve()))
        with self.lock:
            check_memory_budget()
            try:
                if self.key != key or self.child is None or self.child.poll() is not None:
                    self._close()
                    self.folder = tempfile.TemporaryDirectory(prefix='labmate-model-')
                    target = Path(self.folder.name)/'infer'
                    binary = 'smartbox_asr_resident'
                    shutil.copyfile(root/'bin'/binary, target)
                    target.chmod(0o700)
                    if kind == 'voice':
                        self.service_root = root.resolve()
                    arguments = ['--server', str(root/'models/asr')]
                    self.child = subprocess.Popen([str(target)] + arguments, stdin=subprocess.PIPE,
                                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                                  bufsize=0)
                    if self._line(90).get('type') != 'ready':
                        raise RuntimeError('模型未完成初始化')
                    self.key = key
                if request is None:
                    return {'ready': True}
                line = str(request)
                if '\n' in line or '\r' in line:
                    raise ValueError('Invalid native request')
                self.child.stdin.write((line+'\n').encode())
                self.child.stdin.flush()
                return self._line(timeout)
            except Exception:
                self._close()
                raise


RUNTIME = ModelRuntime()
