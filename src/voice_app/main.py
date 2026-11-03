"""Standalone voice/LLM entry extracted from LabMate v09."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
from cloud import Cloud, ServiceError
from model_runtime import RUNTIME
from speech_prompt import SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[1] / 'voice'
FALLBACK_CODES = {'cloud_not_configured', 'cloud_network', 'cloud_timeout',
                  'provider_http_502', 'provider_http_503', 'provider_http_504'}

def recognize(audio, engine, root=ROOT):
    if engine == 'hy':
        from hy_asr import transcribe
        return transcribe(audio)
    return RUNTIME.request('voice', root, str(Path(audio).resolve()))

def respond(text, local_result=None, tools=None, cloud=None):
    client = cloud or Cloud()
    try:
        result = client.complete([{'role':'system','content':SYSTEM_PROMPT},
                                  {'role':'user','content':text}], tools=tools)
        return {'route':'deepseek', 'transcript':text, 'response':result,
                'instrument_control_executed':False}
    except ServiceError as exc:
        if exc.code not in FALLBACK_CODES or local_result is None:
            raise
        return {'route':'local', 'transcript':text, 'recognition':local_result,
                'cloud_error':exc.code, 'instrument_control_executed':False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--audio',type=Path)
    source.add_argument('--text')
    source.add_argument('--record',action='store_true',help='Capture up to six seconds on the board')
    p.add_argument('--engine',choices=('local','hy'),default='local')
    p.add_argument('--ask',action='store_true',help='Send the transcript to DeepSeek')
    p.add_argument('--tools',type=Path,help='Caller-supplied JSON array of tool schemas; proposals only')
    p.add_argument('--root',type=Path,default=ROOT)
    args=p.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix='labmate-voice-') as temporary:
            audio=args.audio
            if args.record:
                from xvf3800 import Recorder
                from manual_audio import capture
                audio=Path(temporary)/'capture.wav'
                capture(Recorder(),audio,lambda stage,started:print(stage,file=sys.stderr),threading.Event())
            result=recognize(audio,args.engine,args.root) if audio else None
            text=args.text if args.text is not None else result.get('transcript','')
            if not isinstance(text,str) or not text.strip():
                raise ValueError('No transcript or input text')
            schemas=json.loads(args.tools.read_text('utf-8')) if args.tools else None
            if schemas is not None and not isinstance(schemas,list):
                raise ValueError('Tool schemas must be a JSON array')
            if args.ask or args.text is not None:
                # Only native ASR supplies a local intent. A Hy-only result must not
                # be presented as offline semantic understanding.
                result=respond(text,result if args.engine=='local' else None,schemas)
            else:
                result=dict(result,instrument_control_executed=False)
            print(json.dumps(result,ensure_ascii=False))
        return 0
    except (ServiceError,OSError,ValueError,RuntimeError) as exc:
        print(json.dumps({'error':str(exc),'code':getattr(exc,'code','voice_error')},ensure_ascii=False),file=sys.stderr)
        return 1
    finally:
        RUNTIME.close()

if __name__ == '__main__':
    raise SystemExit(main())
