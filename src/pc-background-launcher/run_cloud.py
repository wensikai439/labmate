"""Console-free launcher for the existing gateway; same mutex and stop file."""
import ctypes
from ctypes import wintypes
import datetime
import os
from pathlib import Path
import sys
import traceback
import time

ROOT = Path(__file__).resolve().parent
CLOUD = ROOT.parent / 'pc-relay'
LOGS = ROOT.parent.parent / 'logs' / 'pc-relay'

def supervise(run, stop, sleep=time.sleep):
    # Retry the transport session, never replay an API request or instrument command.
    while not stop.exists():
        try:
            result = run()
        except SystemExit as exc:
            result = exc.code if isinstance(exc.code, int) else 1
            print('Gateway exit:', exc.code, flush=True)
        except Exception:
            traceback.print_exc()
            result = 1
        if stop.exists() or result == 0:
            return 0
        print('RECONNECT waiting for board connection', flush=True)
        for _ in range(10):
            if stop.exists():
                return 0
            sleep(1)
    return 0

def main():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, 'Local\\LabMateCloud_COM15')
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    owned = False
    try:
        wait = kernel.WaitForSingleObject(handle, 0)
        if wait == 258:
            return 0  # Another original or background launcher already owns COM15.
        if wait not in (0, 128):
            raise ctypes.WinError(ctypes.get_last_error())
        owned = True
        LOGS.mkdir(parents=True, exist_ok=True)
        log = LOGS / 'cloud.log'
        if log.exists():
            log.replace(LOGS / 'cloud.previous.log')
        with log.open('w', encoding='utf-8', buffering=1) as output:
            sys.stdout = sys.stderr = output
            stamp = lambda: datetime.datetime.now().astimezone().isoformat(timespec='seconds')
            print('START', stamp(), 'pid='+str(os.getpid()), flush=True)
            try:
                stop = CLOUD / '.stop-cloud'
                stop.unlink(missing_ok=True)
                sys.path[:0] = [str(CLOUD / 'dependencies'), str(CLOUD / 'source/relay')]
                sys.argv = ['pc_gateway.py', '--port', 'COM15', '--key-from-board', '--stop-file', str(stop)]
                from pc_gateway import run_cli
                result = supervise(run_cli, stop)
            finally:
                print('EXIT', stamp(), flush=True)
            return result
    finally:
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        if owned:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)

if __name__ == '__main__':
    raise SystemExit(main())
