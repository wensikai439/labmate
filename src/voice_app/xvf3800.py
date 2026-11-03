"""XVF3800 USB capture for Kuiper; standard library + ALSA arecord only.

Capture all USB channels, then select one processed channel. Never mix raw
microphones into the ASR input and never fall back to the system default.
"""
import argparse
from array import array
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave

SECONDS = 8
RATE = 16000
HANDSFREE_STATE = '/run/labmate-voice/handsfree.json'


class CaptureError(Exception):
    pass


def reset_usb_audio(device, sound=Path('/sys/class/sound'), nodes=Path('/dev/bus/usb')):
    """Reset only the selected, positively identified Seeed USB microphone."""
    import fcntl
    card = Path(sound) / ('card%d' % device['card'])
    if (card / 'id').read_text().strip() != device['card_id']:
        raise CaptureError('麦克风编号已变化，已取消 USB 恢复')
    interface = (card / 'device').resolve(strict=True)
    usb = next((p for p in (interface,) + tuple(interface.parents)
                if (p / 'idVendor').is_file() and (p / 'idProduct').is_file()), None)
    if usb is None or ((usb / 'idVendor').read_text().strip(),
                       (usb / 'idProduct').read_text().strip()) != ('2886', '001a'):
        raise CaptureError('设备身份不匹配，已取消 USB 恢复')
    node = Path(nodes) / ('%03d' % int((usb / 'busnum').read_text())) / (
        '%03d' % int((usb / 'devnum').read_text()))
    with os.fdopen(os.open(str(node), os.O_WRONLY), 'wb', buffering=0) as handle:
        fcntl.ioctl(handle, 0x5514, 0)  # USBDEVFS_RESET, this device only.


def handsfree_status():
    """A stale worker must never look like an active listener in the UI."""
    try:
        path = Path(os.environ.get('LABMATE_HANDSFREE_STATE', HANDSFREE_STATE))
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or not 0 <= time.time() - value.get('updated', 0) < 6:
            return {}
        return value
    except (OSError, ValueError, TypeError):
        return {}


def discover(proc=Path('/proc/asound')):
    """Read descriptors only. No capture, USB writes, or instrument access."""
    proc = Path(proc)
    try:
        cards = (proc / 'cards').read_text(errors='replace')
    except OSError:
        return []
    # Kuiper may omit per-PCM proc directories. Its global PCM table still
    # lists capture endpoints; do not reject a usable card for missing debug info.
    try:
        pcm_table = (proc / 'pcm').read_text(errors='replace')
    except OSError:
        pcm_table = ''
    capture_endpoints = set()
    for line in pcm_table.splitlines():
        endpoint = re.match(r'^\s*(\d+)-(\d+):', line)
        capture_count = re.search(r'\bcapture\s+(\d+)\b', line)
        if endpoint and capture_count and int(capture_count[1]) > 0:
            capture_endpoints.add((int(endpoint[1]), int(endpoint[2])))
    result = []
    entries = list(re.finditer(r'^\s*(\d+)\s+\[([^\]]+)\]\s*:', cards, re.M))
    for i, entry in enumerate(entries):
        description = cards[entry.start():entries[i + 1].start() if i + 1 < len(entries) else len(cards)]
        if not re.search(r'XVF[\s_-]*3800', description, re.I):
            continue
        number, card_id = int(entry[1]), entry[2].strip()
        folder = proc / ('card%d' % number)
        # streamN corresponds to USB PCM device N; only accept capture endpoints.
        for stream in sorted(folder.glob('stream*')):
            if not re.fullmatch(r'stream\d+', stream.name):
                continue
            device = int(stream.name[6:])
            if (not (folder / ('pcm%dc' % device)).is_dir()
                    and (number, device) not in capture_endpoints):
                continue
            try:
                descriptor = stream.read_text(errors='replace')
            except OSError:
                continue
            capture = re.search(r'^Capture:\s*\n(.*?)(?=^Playback:|\Z)', descriptor, re.M | re.S)
            if not capture:
                continue
            counts = {int(n) for n in re.findall(r'^\s*Channels:\s*(\d+)', capture[1], re.M)}
            # Firmware exposes two processed channels or six including raw mics.
            supported = sorted(counts.intersection((2, 6)))
            if not supported:
                continue
            result.append(dict(card=number, card_id=card_id, device=device,
                               channels=supported[0],
                               name=description.splitlines()[0].strip(),
                               alsa='plughw:CARD=%s,DEV=%d' % (card_id, device)))
    return result


def select_device(devices, env):
    card = env.get('LABMATE_XVF3800_CARD', '').strip()
    if card:
        devices = [d for d in devices if d['card_id'] == card]
    if not devices:
        raise CaptureError('未发现 XVF3800 USB 录音设备；请检查 HUB、XMOS USB 接口及 USB 音频固件。')
    if len(devices) != 1:
        raise CaptureError('发现多个 XVF3800 录音端点；请只连接一台，或用 LABMATE_XVF3800_CARD 指定声卡 ID。')
    selected = dict(devices[0])
    try:
        channel = int(env.get('LABMATE_XVF3800_CHANNEL', '1'))
    except ValueError:
        raise CaptureError('LABMATE_XVF3800_CHANNEL 必须为 0 或 1。') from None
    if channel not in (0, 1):
        raise CaptureError('只允许选择处理后的通道 0 或 1，不使用原始麦克风通道。')
    selected['channel'] = channel
    return selected


def extract_channel(source, target, channels, channel, seconds=SECONDS, expected_frames=None):
    """ALSA plug handles format/rate conversion; Python only deinterleaves."""
    if channels not in (2, 6) or channel not in (0, 1):
        raise CaptureError('录音通道配置无效。')
    count = RATE * seconds if expected_frames is None else expected_frames
    if not 1600 <= count <= RATE * 12:
        raise CaptureError('录音时长无效，请录制 0.1 至 12 秒。')
    try:
        if Path(source).stat().st_size > count * channels * 2 + 65536:
            raise CaptureError('录音文件异常过大。')
        with wave.open(str(source), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (channels, 2, RATE, 'NONE'):
                raise CaptureError('麦克风返回的 WAV 格式与采集参数不一致。')
            frames = wav.getnframes()
            if frames != count:
                raise CaptureError('录音不完整，可能是麦克风断开；本条不提交识别。')
            data = wav.readframes(frames)
            if len(data) != frames * channels * 2:
                raise CaptureError('录音数据被截断；本条不提交识别。')
    except (OSError, wave.Error, EOFError) as exc:
        raise CaptureError('录音文件无法读取：%s' % exc) from None
    samples = array('h')
    samples.frombytes(data)
    if sys.byteorder != 'little':
        samples.byteswap()
    mono = samples[channel::channels]
    peak = max(abs(x) for x in mono)
    rms = math.sqrt(sum(x * x for x in mono) / len(mono))
    if peak == 0:
        raise CaptureError('XVF3800 录音全静音；检查 USB 音频及固件通道路由，本条不提交识别。')
    clipped = sum(abs(x) >= 32760 for x in mono) / len(mono)
    if sys.byteorder != 'little':
        mono.byteswap()
    with wave.open(str(target), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(mono.tobytes())
    return dict(peak=peak, rms=round(rms, 2), clipped_fraction=round(clipped, 5),
                seconds=count / RATE, sample_rate=RATE, channels=1, sample_width=2)


class Recorder:
    def __init__(self, proc=Path('/proc/asound'), env=None):
        self.proc = Path(proc)
        self.env = os.environ if env is None else env
        self.last_recovery = None

    def recover_stream(self, previous):
        """One guarded recovery after an actual stalled stream, never on busy."""
        import fcntl
        now = time.monotonic()
        if self.last_recovery is not None and now - self.last_recovery < 10:
            raise CaptureError('麦克风音频仍未恢复；稍候重试或重新插拔麦克风 USB')
        lock_path = self.env.get('LABMATE_XVF3800_LOCK', '/tmp/labmate-xvf3800-record.lock')
        with open(lock_path, 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CaptureError('麦克风正在使用中，已取消 USB 恢复') from None
            current = self.status()
            if not current['available'] or any(current.get(k) != previous[k]
                                              for k in ('card', 'card_id', 'device', 'channels')):
                raise CaptureError('麦克风设备发生变化，已取消 USB 恢复')
            self.last_recovery = now
            try:
                reset_usb_audio(current)
            except OSError as exc:
                raise CaptureError('麦克风 USB 恢复失败：%s' % exc) from None
            time.sleep(1)  # Let the USB audio interface settle before reopening.

    def status(self):
        try:
            if not sys.platform.startswith('linux'):
                raise CaptureError('XVF3800 采集需在 Kuiper/Linux 板卡运行。')
            if not shutil.which('arecord'):
                raise CaptureError('板卡缺少 arecord（alsa-utils）。')
            device = select_device(discover(self.proc), self.env)
            return dict(available=True, message='XVF3800 已识别，开始录音后验证音频数据', **device)
        except CaptureError as exc:
            return dict(available=False, message=str(exc))

    def capture(self, target):
        state = self.status()
        if not state['available']:
            raise CaptureError(state['message'])
        # Imported only on Linux; the module remains testable on Windows.
        import fcntl
        lock_path = self.env.get('LABMATE_XVF3800_LOCK', '/tmp/labmate-xvf3800-record.lock')
        with open(lock_path, 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CaptureError('XVF3800 正在被另一条录音任务使用，请稍候。') from None
            with tempfile.TemporaryDirectory(prefix='labmate-xvf3800-') as folder:
                raw = Path(folder) / 'multichannel.wav'
                argv = ['arecord', '-q', '-D', state['alsa'], '-t', 'wav',
                        '-f', 'S16_LE', '-r', str(RATE), '-c', str(state['channels']),
                        '-d', str(SECONDS), str(raw)]
                try:
                    result = subprocess.run(argv, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.PIPE, timeout=SECONDS + 6)
                except subprocess.TimeoutExpired:
                    raise CaptureError('XVF3800 录音超时，采集进程已停止；请检查 USB 连接。') from None
                except OSError as exc:
                    raise CaptureError('无法启动录音：%s' % exc) from None
                if result.returncode:
                    detail = result.stderr.decode('utf-8', errors='replace').strip()[-600:]
                    raise CaptureError('XVF3800 录音失败，可能被占用或格式不支持：' + detail)
                # Detect renumber/disconnect during capture; never re-record automatically.
                current = self.status()
                if not current['available'] or any(current.get(k) != state[k] for k in ('card', 'card_id', 'device', 'channels', 'channel')):
                    raise CaptureError('录音期间麦克风设备发生变化，请重新检查连接。')
                info = extract_channel(raw, target, state['channels'], state['channel'])
                return dict(info, device=state['alsa'], input_channels=state['channels'],
                            selected_channel=state['channel'])


def main():
    parser = argparse.ArgumentParser(description='XVF3800 检查/录音；不调用识别、云端或仪器。')
    parser.add_argument('--record', type=Path, help='手动录制 8 秒并保存为模型格式 WAV')
    args = parser.parse_args()
    recorder = Recorder()
    try:
        if args.record:
            if args.record.exists():
                raise CaptureError('目标文件已存在，请使用新文件名。')
            value = recorder.capture(args.record)
        else:
            value = recorder.status()
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value.get('available', True) else 1
    except CaptureError as exc:
        print(json.dumps(dict(available=False, message=str(exc)), ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
