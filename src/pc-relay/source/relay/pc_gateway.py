"""PC Wi-Fi DeepSeek gateway. Requires explicit --port; never uploads/deploys."""
import argparse
import json
import os
import time
import uuid
import base64
import re
from pathlib import Path
from urllib import request, error
from protocol import encode, Lines
import hy_provider

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

def credential_line(buffer, marker):
    for line in bytes(buffer).split(b'\n')[:-1]:
        line=re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]',b'',line).strip(b'\r')
        if not line.startswith(marker.encode()):continue
        try:
            value=base64.b64decode(line[len(marker):],validate=True).decode('ascii').strip()
            if re.fullmatch(r'sk-[A-Za-z0-9]{20,}',value):return value
        except (ValueError,UnicodeError):pass
    return None

def startup_frames(buffer):
    clean=re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]',b'',bytes(buffer))
    return Lines().feed(b'\n'.join(line.strip(b'\r') for line in clean.split(b'\n')))

def ensure_root_shell(port):
    """Recover only a positively identified orphaned LabMate relay, never arbitrary jobs."""
    def probe():
        marker='LM_SHELL_'+uuid.uuid4().hex+'_'
        port.write(("printf '\\n%s%s\\n' '"+marker+"' \"$(id -u)\"\r\n").encode('ascii'))
        data=bytearray();deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            data.extend(port.read(max(1,port.in_waiting)))
            clean=re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]',b'',bytes(data))
            if (marker+'0').encode() in [line.strip(b'\r') for line in clean.split(b'\n')[:-1]]:
                return True
            if len(data)>8192:break
        return False
    port.reset_input_buffer()
    if probe():return
    hello=uuid.uuid4().hex
    port.write(encode({'type':'ping','id':hello}))
    data=bytearray();deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        data.extend(port.read(max(1,port.in_waiting)))
        if any(v['type']=='ready' and v.get('id')==hello for v in startup_frames(data)):
            print('检测到上次遗留的板卡转发，正在恢复连接。',flush=True)
            port.write(b'\x03');time.sleep(1)
            port.reset_input_buffer()
            if probe():return
            break
        if len(data)>8192:break
    raise SystemExit('板卡尚未进入 root 命令行。请等待启动完成；若仍失败，用 MobaXterm 登录到 root 后断开串口，再启动转发。')

def validate_payload(value, model):
    allowed = {'model','messages','stream','thinking','max_tokens','response_format','tools','tool_choice'}
    if not isinstance(value, dict) or set(value) - allowed or value.get('model') != model or value.get('stream') is not False:
        raise ValueError('invalid model/request')
    if type(value.get('max_tokens')) is not int or not 1 <= value['max_tokens'] <= 6000: raise ValueError('token bound')
    messages = value.get('messages')
    # Board retains 12 user/assistant turns, plus system, snapshot, and new input.
    if not isinstance(messages, list) or not 1 <= len(messages) <= 27: raise ValueError('message bound')
    for message in messages:
        if not isinstance(message, dict) or set(message) != {'role','content'} or message['role'] not in ('system','user','assistant'):
            raise ValueError('invalid message')
        if not isinstance(message['content'], str) or len(message['content']) > 70000: raise ValueError('content bound')
    if value.get('thinking') != {'type':'disabled'}: raise ValueError('thinking mode')
    if 'response_format' in value and value['response_format'] != {'type':'json_object'}: raise ValueError('format')
    if 'tool_choice' in value and value['tool_choice'] != 'auto': raise ValueError('tool choice')
    if 'tools' in value:
        names = {'measure_scope', 'set_scope_time_cursors', 'set_scope_math', 'set_scope_fft', 'set_scope_cursor_state', 'save_scope_screenshot', 'set_power', 'set_scope_vertical', 'measure_vpp', 'set_scope_trigger_mode', 'set_scope_trigger', 'output_off', 'set_scope_acquisition', 'set_signal', 'set_scope', 'set_scope_voltage_cursors', 'output_pulse', 'set_scope_timebase', 'set_scope_autoset'}
        if not isinstance(value['tools'], list) or len(value['tools']) > len(names): raise ValueError('tools bound')
        for tool in value['tools']:
            if not isinstance(tool, dict) or tool.get('type') != 'function' or tool.get('function',{}).get('name') not in names: raise ValueError('tool')
    return value

def forward(payload, key, model, opener=None):
    try: validate_payload(payload, model)
    except (ValueError, TypeError, AttributeError): return 400, {'error':'relay rejected malformed request'}
    if not key: return 503, {'error':'DeepSeek key is not configured on PC'}
    opener = opener or request.build_opener(NoRedirect()).open
    req = request.Request('https://api.deepseek.com/chat/completions', method='POST',
                          data=json.dumps(payload).encode('utf-8'),
                          headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
    try:
        with opener(req, timeout=45) as response: raw = response.read(128001)
        if len(raw) > 128000: return 502, {'error':'provider response exceeds relay limit'}
        return 200, json.loads(raw)
    except error.HTTPError as exc:
        status=exc.code;exc.close();return status, {'error':'provider rejected request'}
    except (OSError, ValueError): return 502, {'error':'provider connection or response failed; no automatic retry'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',required=True,help='UART port, e.g. COM15; must not be in use by MobaXterm')
    parser.add_argument('--model',default=os.environ.get('DEEPSEEK_MODEL','deepseek-flash'))
    parser.add_argument('--check-link',action='store_true',help='Only verify the UART handshake; no API key or cloud request')
    parser.add_argument('--key-from-board',action='store_true',help='Read the root-only board credential into memory and start the board UART relay')
    parser.add_argument('--stop-file',help='Stop gracefully when this local file exists')
    parser.add_argument('--max-requests',type=int,default=0,help='Stop after this many forwarded requests; zero keeps running')
    args=parser.parse_args()
    import serial
    key=os.environ.get('DEEPSEEK_API_KEY','').strip()
    hy_key='' if args.key_from_board else hy_provider.load_key()
    if not key and not args.check_link and not args.key_from_board: raise SystemExit('Set DEEPSEEK_API_KEY locally before starting; do not paste it into chat.')
    port=serial.Serial(port=None,baudrate=115200,timeout=1,write_timeout=35,rtscts=False,dsrdtr=False)
    port.dtr=False;port.rts=False;port.port=args.port
    with port:
        time.sleep(.2)
        deferred=[]
        if args.key_from_board:
            ensure_root_shell(port)
            marker='LM_KEY_'+uuid.uuid4().hex+'_'
            command='python3 -c "import base64,pathlib; p=pathlib.Path(\'/etc/labmate/deepseek.key\'); assert not p.is_symlink() and p.stat().st_mode & 63 == 0; print(\''+marker+'\'+base64.b64encode(p.read_bytes()).decode())"\r'
            port.reset_input_buffer();port.write(command.encode('ascii'))
            buf=bytearray();deadline=time.monotonic()+10;found=None
            while time.monotonic()<deadline:
                buf.extend(port.read(max(1,port.in_waiting)))
                found=credential_line(buf,marker)
                if found:break
                if len(buf)>8192:break
            buf.clear()
            if not found:raise SystemExit('已连接板卡 root 命令行，但无法读取密钥。请检查板卡密钥文件及权限；不要把密钥贴到终端或截图中。')
            key=found;found=None
            marker='LM_HY_KEY_'+uuid.uuid4().hex+'_'
            command='python3 -c "import base64,pathlib; p=pathlib.Path(\'/etc/labmate/hy-asr.key\'); assert not p.is_symlink() and p.stat().st_uid == 0 and p.stat().st_mode & 63 == 0; print(\''+marker+'\'+base64.b64encode(p.read_bytes()).decode())"\r'
            port.reset_input_buffer();port.write(command.encode('ascii'))
            buf=bytearray();deadline=time.monotonic()+10;found=None
            while time.monotonic()<deadline:
                buf.extend(port.read(max(1,port.in_waiting)))
                found=credential_line(buf,marker)
                if found:break
                if len(buf)>8192:break
            buf.clear()
            hy_key=found or '';found=None
            port.write(b'sh /boot/labmate-control-v2/relay/start_pc_relay.sh\r')
            # Consume startup acknowledgement before ping; do not send JSON to a shell.
            startup=bytearray();deadline=time.monotonic()+10;started=False
            while time.monotonic()<deadline:
                startup.extend(port.read(max(1,port.in_waiting)))
                frames=startup_frames(startup)
                if any(v['type']=='ready' for v in frames):
                    deferred.extend(v for v in frames if v['type']=='request')
                    started=True;break
                if len(startup)>8192:break
            if not started:
                port.write(b'\x03');time.sleep(.5)
                raise SystemExit('Board relay did not start.')
        lines=Lines();hello=uuid.uuid4().hex;port.write(encode({'type':'ping','id':hello}));deadline=time.monotonic()+12;ready=False
        while time.monotonic()<deadline:
            frames=lines.feed(port.read(max(1,port.in_waiting)))
            deferred.extend(v for v in frames if v['type']=='request')
            if any(v['type']=='ready' and v['id']==hello for v in frames):
                ready=True;break
        if not ready:
            if args.key_from_board: port.write(b'\x03');time.sleep(.5)
            raise SystemExit('No board relay handshake. Start board_relay.py first. No cloud request was made.')
        if args.check_link:
            print('UART_HANDSHAKE_PASS: board relay replied; no cloud request or instrument command.',flush=True)
            if args.key_from_board: port.write(b'\x03');time.sleep(.5)
            return
        print('UART relay ready. Fixed destination: official DeepSeek API. Ctrl-C stops PC forwarding.',flush=True)
        print('Hy ASR 3.0 Preview: '+('configured' if hy_key else 'key missing'),flush=True)
        seen=set()
        try:
            while True:
                if args.stop_file and Path(args.stop_file).exists(): break
                frames=deferred+lines.feed(port.read(max(1,port.in_waiting)));deferred=[]
                for value in frames:
                    if value['type']!='request': continue
                    if value['id'] in seen: status,body=409,{'error':'duplicate request refused; no retry'}
                    else:
                        if len(seen)>=10000: raise SystemExit('Session request limit reached; restart relay explicitly.')
                        seen.add(value['id'])
                        service=value.get('service','deepseek')
                        if service == 'hy_asr':
                            status,body=hy_provider.forward(value.get('payload'),hy_key,request.build_opener(NoRedirect()).open)
                        elif service == 'deepseek':
                            status,body=forward(value.get('payload'),key,args.model)
                        else:
                            status,body=400,{'error':'unknown relay service'}
                    port.write(encode({'type':'response','id':value['id'],'status':status,'body':body}))
                    print('Cloud request finished; HTTP '+str(status),flush=True)
                    if args.max_requests and len(seen)>=args.max_requests:
                        time.sleep(1)
                        return
        finally:
            key=''
            hy_key=''
            if args.key_from_board:
                port.write(b'\x03');time.sleep(.5)

def run_cli():
    import serial
    try:
        main()
        return 0
    except serial.SerialException:
        print('串口无法打开或连接已中断。请检查 USB 连接，并关闭占用该串口的 MobaXterm 会话或其他转发程序。')
        print('如已有云端转发运行，无需重复启动；切换到 MobaXterm 前请运行 stop-cloud.cmd 并等待转发退出。')
        return 2
    except KeyboardInterrupt:
        print('PC forwarding stopped. Board instruments were not changed.')
        return 0

if __name__=='__main__':
    raise SystemExit(run_cli())
