"""Overlap microphone capture with provisional full-prefix V8.1 recognition.

The supplied encoder is offline, not a chunk-state streaming graph. Prefixes
are replaced by newer audio (bounded queue), and only the final full recording
can leave this adapter as an actionable result. No controls or DS calls here.
"""
from array import array
from pathlib import Path
import sys
import tempfile
import threading
import wave
from model_runtime import RUNTIME


class CaptureRecognition:
    def __init__(self, root, provisional, runtime=RUNTIME):
        self.root=root;self.provisional=provisional;self.runtime=runtime
        self.condition=threading.Condition();self.pending=None
        self.closed=False;self.result=None;self.error=None;self.finished=False
        self.worker=threading.Thread(target=self.run,name='capture-asr',daemon=True)

    def __enter__(self):
        self.worker.start();return self

    def __exit__(self, *unused):
        with self.condition:
            self.closed=True;self.pending=None;self.condition.notify_all()
        self.worker.join()  # Native calls have bounded initialization/inference timeouts.

    def submit(self, pcm, state):
        samples=array('h');samples.frombytes(pcm)
        if sys.byteorder!='little':samples.byteswap()
        mono=samples[state['channel']::state['channels']]
        if sys.byteorder!='little':mono.byteswap()
        with self.condition:
            if not self.closed:
                self.pending=(mono.tobytes(),False);self.condition.notify()

    def finish(self, audio):
        with wave.open(str(audio),'rb') as wav:pcm=wav.readframes(wav.getnframes())
        with self.condition:
            self.pending=(pcm,True);self.condition.notify()
            self.condition.wait_for(lambda:self.finished)
        if self.error:raise self.error
        return self.result

    def run(self):
        previous=None;cached=None
        with tempfile.TemporaryDirectory(prefix='labmate-capture-asr-') as folder:
            path=Path(folder)/'prefix.wav'
            while True:
                with self.condition:
                    self.condition.wait_for(lambda:self.pending is not None or self.closed)
                    if self.closed:return
                    pcm,final=self.pending;self.pending=None
                try:
                    if previous==pcm and cached is not None:
                        raw=cached
                    else:
                        with wave.open(str(path),'wb') as wav:
                            wav.setparams((1,2,16000,0,'NONE','none'));wav.writeframes(pcm)
                        raw=self.runtime.request('voice',self.root,str(path),timeout=180 if final else 90)
                        if raw.get('instrument_control_executed') is not False:raise ValueError('Invalid preview result')
                        previous=pcm;cached=raw
                    if final:
                        with self.condition:
                            self.result=raw;self.finished=True;self.condition.notify_all()
                        return
                    text=raw.get('transcript')
                    if isinstance(text,str) and len(text)<=4000:
                        with self.condition:
                            if not self.closed:self.provisional(text)
                except Exception as exc:
                    if final:
                        with self.condition:
                            self.error=exc;self.finished=True;self.condition.notify_all()
                        return
                    # Failed preview must not discard a valid final recording.
                    previous=None;cached=None
