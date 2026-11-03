"""Button-controlled capture, bounded by the six-second board memory budget."""
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time
import wave

from xvf3800 import CaptureError, RATE, extract_channel

MAX_SECONDS = 6


class CaptureCancelled(CaptureError):
    pass


class NoInitialAudio(CaptureError):
    def __init__(self, device):
        super().__init__('麦克风未返回音频，请重新插拔麦克风后再试')
        self.device = device


def capture(recorder, target, progress, stop_event, preview=None):
    progress('connecting', None)
    try:
        return capture_once(recorder, target, progress, stop_event, preview)
    except NoInitialAudio as exc:
        # Retry only if no audio has started; never re-record a partial utterance.
        if stop_event.is_set():
            raise CaptureCancelled('已取消录音') from None
        progress('recovering', None)
        recorder.recover_stream(exc.device)
        return capture_once(recorder, target, progress, stop_event, preview)


def capture_once(recorder, target, progress, stop_event, preview):
    import fcntl
    if stop_event.is_set():
        raise CaptureCancelled('已取消录音')
    state = recorder.status()
    if not state['available']:
        raise CaptureError(state['message'])
    lockpath = recorder.env.get('LABMATE_XVF3800_LOCK', '/tmp/labmate-xvf3800-record.lock')
    with open(lockpath, 'a') as lock, tempfile.TemporaryFile() as errors:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CaptureError('麦克风正在使用中，请稍候') from None
        argv = ['arecord', '-q', '-D', state['alsa'], '-t', 'raw', '-f', 'S16_LE',
                '-r', str(RATE), '-c', str(state['channels']),
                '--buffer-time=100000', '--period-time=20000']
        try:
            child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=errors)
        except OSError as exc:
            raise CaptureError('无法启动麦克风：' + str(exc)) from None
        data = bytearray()
        frame_bytes = state['channels'] * 2
        expected = RATE * MAX_SECONDS * frame_bytes
        start = time.monotonic()
        last_audio = first_audio = None
        stop_reason = 'limit'
        preview_at = RATE * 3 * frame_bytes
        try:
            while len(data) < expected:
                if stop_event.is_set():
                    if len(data) < RATE * frame_bytes // 10:
                        raise CaptureCancelled('录音已结束，未提交过短音频')
                    stop_reason = 'button'
                    break
                now = time.monotonic()
                if last_audio is None and now - start > 5:
                    raise NoInitialAudio(state)
                if last_audio is not None and now-last_audio > 3:
                    raise CaptureError('录音中断，已丢弃不完整音频，请重新按录音')
                # Bound both audio size and real recording time. USB scheduling
                # gaps must not leave the UI at 6 s while waiting for more frames.
                remaining = MAX_SECONDS if first_audio is None else MAX_SECONDS - (now-first_audio)
                if remaining <= 0:
                    break
                ready, _, _ = select.select([child.stdout], [], [], min(.1, remaining))
                if not ready:
                    continue
                chunk = os.read(child.stdout.fileno(), min(8192, expected-len(data)))
                if not chunk:
                    # Drain stdout before inspecting exit: a finished process can
                    # still have the end of a valid recording in its pipe.
                    errors.seek(0)
                    detail = errors.read(600).decode(errors='replace').strip()
                    raise CaptureError('麦克风采集停止：' + (detail or '连接断开，请重新连接'))
                last_audio = time.monotonic()
                if first_audio is None:
                    first_audio = last_audio
                    progress('recording', time.time())
                data.extend(chunk)
                if preview is not None and len(data) >= preview_at:
                    preview(bytes(data[:len(data)//frame_bytes*frame_bytes]), state)
                    preview_at += RATE * 3 * frame_bytes
            # Tell the UI recording has ended before waiting for process cleanup.
            progress('stopping', None)
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            child.stdout.close()
        # ALSA reads can end between channel samples when the stop arrives.
        del data[len(data) // frame_bytes * frame_bytes:]
        current = recorder.status()
        if not current['available'] or any(current.get(k) != state[k] for k in ('card', 'card_id', 'device', 'channels', 'channel')):
            raise CaptureError('录音期间麦克风设备发生变化，请检查连接')
        with tempfile.TemporaryDirectory(prefix='labmate-manual-') as folder:
            raw = Path(folder) / 'input.wav'
            with wave.open(str(raw), 'wb') as wav:
                wav.setnchannels(state['channels'])
                wav.setsampwidth(2)
                wav.setframerate(RATE)
                wav.writeframes(data)
            info = extract_channel(raw, target, state['channels'], state['channel'],
                                   expected_frames=len(data) // frame_bytes)
        return dict(info, device=state['alsa'], input_channels=state['channels'],
                    selected_channel=state['channel'],
                    stop_reason=stop_reason)
