"""Bounded 16-kHz mono WAV encoder using the board's installed LAME library."""
import ctypes as C
from pathlib import Path
import sys
import wave


def encode(source, target):
    with wave.open(str(source), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('Expected mono 16-kHz PCM16')
        if not 1600 <= wav.getnframes() <= 96000:
            raise ValueError('Audio duration out of bounds')
        pcm = wav.readframes(wav.getnframes())
    lib = C.CDLL('libmp3lame.so.0')
    lib.lame_init.restype = C.c_void_p
    for name in ('lame_set_num_channels', 'lame_set_in_samplerate', 'lame_set_brate', 'lame_set_quality'):
        getattr(lib, name).argtypes = [C.c_void_p, C.c_int]
    lib.lame_init_params.argtypes = [C.c_void_p]
    lib.lame_close.argtypes = [C.c_void_p]
    lib.lame_encode_buffer.argtypes = [C.c_void_p, C.POINTER(C.c_short), C.POINTER(C.c_short), C.c_int, C.POINTER(C.c_ubyte), C.c_int]
    lib.lame_encode_flush.argtypes = [C.c_void_p, C.POINTER(C.c_ubyte), C.c_int]
    handle = lib.lame_init()
    if not handle: raise RuntimeError('Encoder initialization failed')
    try:
        for name, value in (('lame_set_num_channels',1),('lame_set_in_samplerate',16000),('lame_set_brate',48),('lame_set_quality',5)):
            if getattr(lib,name)(handle,value) < 0: raise RuntimeError('Encoder configuration failed')
        if lib.lame_init_params(handle) < 0: raise RuntimeError('Encoder configuration failed')
        count = len(pcm)//2
        samples = (C.c_short*count).from_buffer_copy(pcm)
        output = (C.c_ubyte*(count*5//4+7200))()
        size = lib.lame_encode_buffer(handle,samples,samples,count,output,len(output))
        if size < 0: raise RuntimeError('Encoder failed')
        data = bytes(output[:size])
        size = lib.lame_encode_flush(handle,output,len(output))
        if size < 0: raise RuntimeError('Encoder flush failed')
        data += bytes(output[:size])
        if not 4 <= len(data) <= 65000: raise ValueError('Encoded audio out of bounds')
        Path(target).write_bytes(data)
    finally:
        lib.lame_close(handle)


if __name__ == '__main__':
    encode(sys.argv[1],sys.argv[2])
