"""Offline regression tests for the extracted API boundary; no hardware/network."""
import io
import json
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError, URLError

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/voice_app'),str(ROOT/'src/pc-relay/source/relay')]
from cloud import Cloud, ServiceError
from main import respond
from protocol import Lines, encode, decode, MAX_LINE
from hy_provider import validate

class VoiceAPI(unittest.TestCase):
    def test_direct_request(self):
        seen=[]
        def opener(req,timeout):
            seen.append((req,timeout))
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'回答'}}]}).encode())
        client=Cloud({'DEEPSEEK_API_KEY':'unit-test-placeholder'},opener)
        self.assertEqual(client.complete([{'role':'user','content':'问题'}]),'回答')
        self.assertEqual(seen[0][0].full_url,'https://api.deepseek.com/chat/completions')
        self.assertEqual(seen[0][1],45)

    def test_reject_untrusted_endpoint(self):
        client=Cloud({'DEEPSEEK_API_KEY':'unit-test-placeholder','DEEPSEEK_BASE_URL':'https://invalid.example'},lambda *a,**k:self.fail('must not connect'))
        with self.assertRaises(ServiceError) as caught:client.complete([])
        self.assertEqual(caught.exception.code,'cloud_not_configured')

    def test_serial_auth_and_tools(self):
        def opener(req,timeout):
            self.assertEqual(req.full_url,'http://127.0.0.1:8767/chat/completions')
            self.assertEqual(req.get_header('X-labmate-relay'),'x'*24)
            self.assertIsNone(req.get_header('Authorization'))
            self.assertEqual(json.loads(req.data)['tool_choice'],'auto')
            return io.BytesIO(b'{"choices":[{"finish_reason":"tool_calls","message":{"tool_calls":[]}}]}')
        client=Cloud({'LABMATE_CLOUD_RELAY':'serial','LABMATE_RELAY_TOKEN':'x'*24},opener)
        self.assertEqual(client.complete([],tools=[{'type':'function'}]),{'tool_calls':[]})

    def test_network_fallback_does_not_execute(self):
        def opener(*a,**k):raise URLError('offline')
        result=respond('设置频率',{'transcript':'设置频率','intent_proposal':'UNMATCHED'},cloud=Cloud({'DEEPSEEK_API_KEY':'test'},opener))
        self.assertEqual(result['route'],'local')
        self.assertFalse(result['instrument_control_executed'])

    def test_auth_failure_not_hidden_by_fallback(self):
        def opener(*a,**k):raise HTTPError('https://api.deepseek.com',401,'unauthorized',{},None)
        with self.assertRaises(ServiceError) as caught:respond('问题',{'transcript':'问题'},cloud=Cloud({'DEEPSEEK_API_KEY':'test'},opener))
        self.assertEqual(caught.exception.code,'provider_http_401')

    def test_invalid_reply_and_lock_recovery(self):
        replies=iter([b'{}',b'{"choices":[{"finish_reason":"stop","message":{"content":"ok"}}]}'])
        client=Cloud({'DEEPSEEK_API_KEY':'test'},lambda *a,**k:io.BytesIO(next(replies)))
        with self.assertRaises(ServiceError):client.complete([])
        self.assertEqual(client.complete([]),'ok')

    def test_fragmented_protocol_and_oversize_recovery(self):
        item={'type':'request','id':'case','payload':{'text':'测试'}}
        packet=encode(item);lines=Lines()
        self.assertEqual(lines.feed(packet[:9]),[])
        self.assertEqual(lines.feed(packet[9:]),[item])
        self.assertEqual(lines.feed(b'x'*(MAX_LINE+1)+b'\n'+packet),[item])
        self.assertIsNone(decode(b'@LABMATE4:invalid!'))

    def test_hy_rejects_long_or_malformed_audio(self):
        base={'model':'hy-asr-3.0-preview','data':'SUQzAA==','voice_encode_format':'mp3','duration_ms':6000}
        self.assertEqual(validate(base)['data'],base['data'])
        for changed in ({'duration_ms':6001},{'data':'not-base64'},{'model':'untrusted'}):
            with self.assertRaises(ValueError):validate(dict(base,**changed))

if __name__=='__main__':unittest.main()
