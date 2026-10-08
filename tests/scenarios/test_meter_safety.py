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
