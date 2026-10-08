"""측정기 안전 검사 (PR #2 PC 쪽 검토 a·b·c).

가짜 전송기로 측정기를 돌려 다음을 확인한다. 네트워크·DB 가 없어도 돈다.
  a  원격 모드는 api(앱)·.env·DB 엔진을 불러오지 않는다
  b  --allow-writes 없이는 readonly guest 단계만 보내고, 실제 소켓 연결은 한 번도 열지 않는다
  c  기록에 응답 원문·열쇠·세션 번호·예외 문장이 남지 않는다

실행: python -m pytest tests/scenarios/test_meter_safety.py -q
"""
import json
import socket
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import definitions  # noqa: E402
import meter  # noqa: E402

SECRET_KEY = 'AK-should-never-be-recorded'
SECRET_MAIL = 'person@example.com'


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self.headers = {'content-type': 'application/json'}
        self._payload = payload

    def json(self):
        return self._payload


class FakeTransport:
    """모든 요청을 기록만 하고, 민감해 보이는 값을 일부러 섞어 돌려준다."""

    def __init__(self):
        self.calls = []

    def send(self, audience, method, path, body):
        self.calls.append((audience, method, path))
        return FakeResponse(200, {
            'ok': True, 'buildable': True, 'total': 3, 'count': 2, 'session_id': 98765,
            'access_key': SECRET_KEY, 'member': {'email': SECRET_MAIL},
            'detail': {'error': 'some_code', 'detail': f'trace mentions {SECRET_MAIL}'},
            'sets': {'recommend': {'parts': [{'product_code': 1}]}},
        })


@pytest.fixture
def no_sockets(monkeypatch):
    opened = []

    def refuse(self, *a, **k):
        opened.append(a)
        raise AssertionError('측정기가 실제 연결을 열었다')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket.socket, 'connect_ex', refuse)
    return opened


def test_remote_without_writes_sends_only_reviewed_guest_steps(monkeypatch, tmp_path, no_sockets):
    for mod in [m for m in sys.modules if m == 'api' or m.startswith('api.')]:
        monkeypatch.delitem(sys.modules, mod)
    fake = FakeTransport()
    rc = meter.main(['--base-url', 'http://scenario.invalid', '--out', str(tmp_path)], transport=fake)
    assert rc == 0

    # a: 앱·DB 모듈을 하나도 불러오지 않았다
    assert not [m for m in sys.modules if m == 'api' or m.startswith('api.')]
    # b: 실제 연결 0 · 보낸 것은 readonly + guest 단계뿐
    assert no_sockets == []
    readonly_guest = {(s.method, s.path.split('{')[0]) for sc in definitions.SCENARIOS for s in sc.steps
                      if s.path and s.readonly and s.audience == 'guest'}
    assert fake.calls, '읽기 단계조차 보내지 않았다'
    for audience, method, path in fake.calls:
        assert audience == 'guest'
        assert any(method == m and path.startswith(p) for m, p in readonly_guest), (method, path)
    sent_paths = {p for _, _, p in fake.calls}
    for never in ('/api/recommend', '/api/auth/login', '/api/orders', '/api/admin/auth/login', '/api/handoff'):
        assert never not in sent_paths

    # c: 기록에 원문·열쇠·세션 번호·메일이 없다
    recorded = (tmp_path / 'last-run.json').read_text(encoding='utf-8') + (tmp_path / 'status.md').read_text(encoding='utf-8')
    for leak in (SECRET_KEY, SECRET_MAIL, '98765', 'trace mentions'):
        assert leak not in recorded, leak
    run = json.loads((tmp_path / 'last-run.json').read_text(encoding='utf-8'))
    allowed = {'key', 'title', 'sent', 'state', 'reason', 'ms', 'status', 'json', 'code', 'evidence'}
    for sc in run['scenarios']:
        for s in sc['steps']:
            assert set(s) <= allowed, set(s) - allowed
            for v in s.get('evidence', {}).values():
                assert isinstance(v, (bool, int, float))


def test_html_200_is_not_a_pass():
    step = definitions.Step('x', 'x', 'GET', '/x', readonly=True, expect=definitions.ok_json())
    assert step.expect(200, None, {}) is not None


def test_server_error_keeps_only_exception_kind():
    try:
        raise ValueError(f'column secret for {SECRET_MAIL}')
    except ValueError as exc:
        err = meter._ServerError(exc)
    assert err.exception == 'ValueError'
    assert not hasattr(err, 'text')


class _SetCookieMsg:
    """requests 가 Set-Cookie 를 읽는 원응답 모양(`_original_response.msg.get_all`)의 최소 구현."""

    class _Msg:
        @staticmethod
        def get_all(name, default=None):
            return ['popcorn_session=leak123; Path=/'] if name.lower() == 'set-cookie' else default

    _original_response = type('Orig', (), {'msg': _Msg()})()


class _CookieSettingAdapter:
    """연결을 열지 않는 가짜 어댑터. 모든 응답에 Set-Cookie 를 싣고, 받은 요청의 Cookie 를 기록한다.
    쿠키 저장은 requests 의 실제 함수(extract_cookies_to_jar)로 세션 쿠키 통에 넣어,
    세션에 걸린 쿠키 정책이 실제로 적용되는지를 본다."""

    def __init__(self, jar, seen, auth_seen, record=None):
        self.jar, self.seen, self.auth_seen = jar, seen, auth_seen
        record = {} if record is None else record
        self.proxies_seen = record.setdefault('proxies', [])
        self.proxy_auth_seen = record.setdefault('proxy_auth', [])

    def send(self, request, **kwargs):
        import requests
        from requests.cookies import extract_cookies_to_jar
        self.seen.append(request.headers.get('Cookie'))
        self.auth_seen.append(request.headers.get('Authorization'))
        self.proxy_auth_seen.append(request.headers.get('Proxy-Authorization'))
        self.proxies_seen.append(dict(kwargs.get('proxies') or {}))
        extract_cookies_to_jar(self.jar, request, _SetCookieMsg)
        resp = requests.Response()
        resp.status_code, resp._content, resp.encoding = 200, b'{"ok": true}', 'utf-8'
        resp.headers['Content-Type'] = 'application/json'
        resp.url, resp.request = request.url, request
        return resp

    def close(self):
        pass


def _fake_session_factory(seen, auth_seen=None, record=None, inject_auth=False):
    import requests
    auth_seen = [] if auth_seen is None else auth_seen

    def make():
        s = requests.Session()
        if inject_auth:   # 누군가 세션에 인증을 미리 실어 둔 경우(공장·전역 설정)
            s.auth = ('leaky', 'injected-secret')
            s.headers['Authorization'] = 'Bearer injected-token'
            s.headers['Proxy-Authorization'] = 'Basic injected-proxy'
        adapter = _CookieSettingAdapter(s.cookies, seen, auth_seen, record)
        s.mount('http://', adapter)
        s.mount('https://', adapter)
        return s
    return make


def test_remote_readonly_never_resends_cookie(no_sockets):
    """실제 Remote + 실제 requests.Session(가짜 어댑터): 첫 응답이 준 쿠키가 둘째 요청에 실리지 않는다."""
    seen = []
    remote = meter.Remote('http://scenario.invalid', allow_writes=False,
                          session_factory=_fake_session_factory(seen))
    remote.send('guest', 'GET', '/api/budget-bands', None)
    remote.send('guest', 'GET', '/api/budget-bands', None)
    assert seen == [None, None], seen
    assert no_sockets == []


def test_cookie_counter_case_shared_session_would_leak(no_sockets):
    """반례: 쓰기 허용(세션 공유)에서는 같은 가짜가 쿠키를 되보낸다 — 위 시험이 헛통과가 아님을 보인다."""
    seen = []
    remote = meter.Remote('http://scenario.invalid', allow_writes=True,
                          session_factory=_fake_session_factory(seen))
    remote.send('guest', 'GET', '/api/budget-bands', None)
    remote.send('guest', 'GET', '/api/budget-bands', None)
    assert seen[0] is None and seen[1] and 'leak123' in seen[1], seen


@pytest.fixture
def netrc_for_target(tmp_path, monkeypatch):
    """환경 자동 인증: requests 는 trust_env 이면 NETRC 파일의 계정을 Authorization 으로 싣는다."""
    rc = tmp_path / 'netrc'
    rc.write_text('machine scenario.invalid login leaky password netrc-secret\n', encoding='utf-8')
    rc.chmod(0o600)
    monkeypatch.setenv('NETRC', str(rc))
    monkeypatch.setenv('HTTP_PROXY', 'http://proxy.invalid:9')
    return rc


def test_remote_readonly_ignores_environment_auth(no_sockets, netrc_for_target):
    """쓰기 금지 Remote: .netrc·프록시 환경이 있어도 Authorization 을 싣지 않고 연결도 열지 않는다."""
    seen, auth_seen = [], []
    remote = meter.Remote('http://scenario.invalid', allow_writes=False,
                          session_factory=_fake_session_factory(seen, auth_seen))
    remote.send('guest', 'GET', '/api/budget-bands', None)
    assert auth_seen == [None], auth_seen
    assert no_sockets == []


def test_environment_auth_counter_case(no_sockets, netrc_for_target):
    """반례: 환경을 믿는 세션(쓰기 허용 = 기존 동작 유지)은 같은 환경에서 .netrc 계정을 싣는다."""
    seen, auth_seen = [], []
    remote = meter.Remote('http://scenario.invalid', allow_writes=True,
                          session_factory=_fake_session_factory(seen, auth_seen))
    remote.send('guest', 'GET', '/api/budget-bands', None)
    assert auth_seen[0] and auth_seen[0].startswith('Basic '), auth_seen
    assert no_sockets == []


def test_remote_readonly_does_not_inherit_proxy_env(no_sockets, netrc_for_target):
    """쓰기 금지 Remote: HTTP_PROXY 환경을 물려받지 않는다(어댑터가 받은 proxies 로 확인). 반례: 쓰기 허용은 물려받는다."""
    record = {}
    meter.Remote('http://scenario.invalid', session_factory=_fake_session_factory([], [], record)) \
        .send('guest', 'GET', '/api/budget-bands', None)
    assert not any('proxy.invalid' in v for v in record['proxies'][0].values()), record
    shared = {}
    meter.Remote('http://scenario.invalid', allow_writes=True, session_factory=_fake_session_factory([], [], shared)) \
        .send('guest', 'GET', '/api/budget-bands', None)
    assert any('proxy.invalid' in v for v in shared['proxies'][0].values()), shared
    assert no_sockets == []


def test_remote_readonly_strips_injected_auth(no_sockets):
    """세션에 auth·Authorization·Proxy-Authorization 이 미리 실려 있어도 쓰기 금지 요청에는 하나도 없다. 반례: 쓰기 허용은 그대로."""
    auth_seen, record = [], {}
    meter.Remote('http://scenario.invalid',
                 session_factory=_fake_session_factory([], auth_seen, record, inject_auth=True)) \
        .send('guest', 'GET', '/api/budget-bands', None)
    assert auth_seen == [None] and record['proxy_auth'] == [None], (auth_seen, record)
    auth_kept, kept = [], {}
    meter.Remote('http://scenario.invalid', allow_writes=True,
                 session_factory=_fake_session_factory([], auth_kept, kept, inject_auth=True)) \
        .send('guest', 'GET', '/api/budget-bands', None)
    assert auth_kept[0] and kept['proxy_auth'][0], (auth_kept, kept)
    assert no_sockets == []


def _lookup_step():
    return next(s for sc in definitions.SCENARIOS for s in sc.steps if s.key == 'task.recover_lookup')


def test_original_result_lookup_rejects_everything_but_the_same_confirmed_operation():
    op = '11111111-1111-4111-8111-111111111111'
    ctx = dict(order_no='ORD-A', request_basis='a' * 64,
               fulfillment_command=dict(operation_id=op, action='prepare_shipment'))
    good = dict(state='confirmed', order_no='ORD-A', operation_id=op, action='prepare_shipment', request_basis='a' * 64)
    expect = _lookup_step().expect
    assert expect(200, good, ctx) is None
    for wrong in (dict(order_no='ORD-B'), dict(operation_id='22222222-2222-4222-8222-222222222222'),
                  dict(action='handoff'), dict(state='pending'), dict(request_basis='b' * 64)):
        assert expect(200, good | wrong, ctx), wrong
    assert expect(404, {'detail': {'code': 'physical_operation_not_found'}}, ctx)   # 미실행 증명 아님
    assert expect(503, {'detail': {'code': 'physical_result_unconfirmed'}}, ctx)    # 미확인 유지
    assert expect(200, None, ctx)                                                   # HTML 200
