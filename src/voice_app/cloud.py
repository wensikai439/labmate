"""DeepSeek text adapter. Model output is data, never an instrument command."""
import json
import os
import socket
import threading
from pathlib import Path
from urllib import request, error, parse


class ServiceError(Exception):
    def __init__(self, message, code='cloud_error', status=502):
        super().__init__(message)
        self.code, self.status = code, status


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward an API key to a redirect target.


class Cloud:
    def __init__(self, env=None, opener=None):
        env = os.environ if env is None else env
        self.key = env.get('DEEPSEEK_API_KEY', '').strip()
        key_path = env.get('DEEPSEEK_API_KEY_FILE', '')
        if not self.key and key_path:
            try:
                path = Path(key_path)
                mode = path.stat().st_mode
                if path.is_symlink() or mode & 0o077:
                    raise ValueError('Credential permissions must be 0600')
                self.key = path.read_text(encoding='ascii').strip()
            except (OSError, ValueError):
                self.key = ''
        self.base = env.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')
        self.model = env.get('DEEPSEEK_MODEL', 'deepseek-flash').strip()
        self.relay = env.get('LABMATE_CLOUD_RELAY', '') == 'serial'
        self.relay_token = env.get('LABMATE_RELAY_TOKEN', '').strip()
        try:
            url = parse.urlsplit(self.base)
            self.valid = (url.scheme == 'https' and url.hostname == 'api.deepseek.com'
                          and url.port in (None, 443) and not url.username and not url.password
                          and not url.query and not url.fragment and url.path in ('', '/v1'))
        except ValueError:
            self.valid = False
        self.opener = opener or (request.build_opener(request.ProxyHandler({}), NoRedirect()).open if self.relay else request.build_opener(NoRedirect()).open)
        self.lock = threading.Lock()

    def status(self):
        configured = bool(self.model and ((self.relay and len(self.relay_token) >= 24 and self.relay_token.isascii()) or (not self.relay and self.key and self.valid)))
        return dict(configured=configured, provider='DeepSeek', model=self.model,
                    message='已配置 · 待请求验证' if configured else '未配置有效的 DeepSeek API',
                    endpoint_valid=self.valid, transport='电脑串口转发' if self.relay else '直接联网')

    def connection_ready(self):
        """Missing local relay can fall back immediately; do not send a cloud request."""
        if not self.status()['configured']:
            return False
        if self.relay:
            try:
                with socket.create_connection(('127.0.0.1', 8767), timeout=.2):
                    return True
            except OSError:
                return False
        return True

    def complete(self, messages, plan=False, tools=None):
        if not self.status()['configured']:
            raise ServiceError('DeepSeek 尚未配置，消息没有发送到云端。请先配置直连或电脑转发。', 'cloud_not_configured', 503)
        if not self.lock.acquire(False):
            raise ServiceError('另一个云端请求正在进行，请稍候。', 'cloud_busy', 429)
        try:
            payload = dict(model=self.model, messages=messages, stream=False,
                           thinking={'type': 'disabled'}, max_tokens=6000 if plan else 1800)
            if plan:
                payload['response_format'] = {'type': 'json_object'}
            if tools:
                payload.update(tools=tools, tool_choice='auto')
            req = request.Request('http://127.0.0.1:8767/chat/completions' if self.relay else self.base + '/chat/completions',
                                  data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                  headers={'Content-Type': 'application/json', **({'X-LabMate-Relay': self.relay_token} if self.relay else {'Authorization': 'Bearer ' + self.key})},
                                  method='POST')
            try:
                with self.opener(req, timeout=120 if self.relay else 45) as response:
                    raw = response.read(512001)
                if len(raw) > 512000:
                    raise ServiceError('云端回复过长，请缩短问题或拆分教程。')
                value = json.loads(raw)
                choice = value['choices'][0]
                if tools and choice.get('finish_reason') in ('stop', 'tool_calls'):
                    message = choice['message']
                    if not isinstance(message, dict): raise ValueError()
                    return message
                if choice.get('finish_reason') != 'stop':
                    raise ServiceError('云端回复未完整生成，请缩短问题或拆分教程。', 'cloud_incomplete')
                text = choice['message']['content']
                if not isinstance(text, str) or not text.strip() or len(text) > 65000:
                    raise ValueError()
                return text.strip()
            except error.HTTPError as exc:
                status = exc.code
                exc.close()
                message = {401: '云端密钥无效，请检查后台配置。', 402: '云端账户余额不足。',
                           429: '云端请求过于频繁，请稍后重试。'}.get(status, '云端服务拒绝请求，请检查模型配置或稍后重试。')
                raise ServiceError(message, 'provider_http_' + str(status)) from None
            except (socket.timeout, TimeoutError):
                raise ServiceError('云端请求超时，请稍后重试。', 'cloud_timeout', 504) from None
            except error.URLError:
                raise ServiceError('无法连接 DeepSeek，请检查板卡联网及系统时间。', 'cloud_network') from None
            except (ValueError, KeyError, IndexError, TypeError):
                raise ServiceError('云端回复格式无效，请重试。', 'cloud_invalid_response') from None
        finally:
            self.lock.release()
