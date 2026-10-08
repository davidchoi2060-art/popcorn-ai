"""「끝까지 시나리오」 진척 측정기 — 협업 분담표 7번.

시나리오(`definitions.py`)의 단계마다 실제 HTTP 요청을 보내고 결과를 표로 남긴다.
초록은 «이번 실행에서 실제 요청이 통과했다»일 때만 나온다. 코드에 경로가 있다는 것은
노랑까지다.

실행
    # 이 저장소의 앱을 프로세스 안에서 띄워 DATABASE_URL 의 DB 로 확인 (CI 방식)
    python tests/scenarios/meter.py --allow-writes --out docs/scenarios/ci

    # 떠 있는 서버를 두드린다. 이 모드는 앱(api)·.env·DB 엔진을 불러오지 않는다.
    python tests/scenarios/meter.py --base-url http://127.0.0.1:8000 --out docs/scenarios/dev

    관리자 단계: SCENARIO_ADMIN_EMAIL (+ SCENARIO_ADMIN_PASSWORD). CI 는 일회용 DB 에
    ADMIN_BOOTSTRAP_EMAILS 로 첫 owner 를 만들어 쓴다.

쓰기 (PR #2 PC 쪽 검토 b)
    `--allow-writes` 가 없으면 «코드로 쓰지 않음을 확인한(readonly) guest 단계»만 보낸다.
    쿠키를 보내는 단계는 readonly 여도 보내지 않는다(인증 GET 도 세션 last_seen 을 쓸 수 있다).
    PC 의 .env 는 공유 Cloud SQL 이다 — 켜기 전에 무엇이 만들어지는지 안다.

기록 (PR #2 PC 쪽 검토 c)
    응답 원문·예외 문장은 남기지 않는다. 상태 코드 · JSON 여부 · 오류 코드(영문 소문자·숫자·_)
    · 단계가 지정한 키의 숫자/참거짓 값 · 보낸 경로의 «틀»(실제 주문번호 등은 넣지 않음)만 남는다.

종료 코드
    0  측정이 끝났다(빨강이 있어도 0 — 이것은 진척 측정이지 합격 판정이 아니다)
    2  측정기 자체가 돌지 못했다(앱 import 실패 등)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import string
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from definitions import SCENARIOS, Scenario, Step  # noqa: E402

GREEN, YELLOW, RED = 'green', 'yellow', 'red'
MARK = {GREEN: '🟢 통과', YELLOW: '🟡 미확인', RED: '🔴 실패'}
CODE_RE = re.compile(r'^[A-Za-z0-9_]{1,64}$')


# ── 경로가 코드에 있나 (프로세스 안 실행에서만 — 노랑의 근거) ──────────────────
class RouteIndex:
    """앱의 라우터에 그 메서드·경로가 걸려 있는지 본다. 정적 파일 캐치올(`/`)은 뺀다."""

    def __init__(self, app):
        self.app = app

    def has(self, method: str, path: str) -> bool:
        from starlette.routing import Match, Mount
        scope = {'type': 'http', 'path': path, 'method': method, 'root_path': '',
                 'headers': [], 'query_string': b''}
        for route in self.app.router.routes:
            if isinstance(route, Mount) and route.path in ('', '/'):
                continue
            match, _ = route.matches(scope)
            if match == Match.FULL:
                return True
        return False


# ── 요청 보내는 쪽 ──────────────────────────────────────────────────────────
class InProcess:
    """이 저장소의 앱을 TestClient 로 부른다. audience 마다 쿠키 상자를 따로 둔다."""

    def __init__(self, app):
        self.app, self.clients = app, {}

    def send(self, audience: str, method: str, path: str, body: Any):
        if audience not in self.clients:
            from fastapi.testclient import TestClient
            # https: 커머스 경로는 https 가 아니면 503 이다(commerce_owner_contexts) — 배포와 같은 조건.
            self.clients[audience] = TestClient(self.app, base_url='https://testserver')
        try:
            return self.clients[audience].request(method, path, **({'json': body} if body is not None else {}))
        except Exception as exc:  # noqa: BLE001 — 처리 안 된 예외 = 실제 서버의 500
            return _ServerError(exc)


class Remote:
    """떠 있는 서버용 — requests 만 쓴다. 앱·DB 모듈을 불러오지 않는다.

    쓰기 금지(기본)면 쿠키를 저장도 전송도 하지 않는다(PR #2 재검토): 비로그인 읽기 응답이
    Set-Cookie 를 주더라도 다음 요청에 Cookie 로 실려 «로그인한 요청»이 되면 안 된다.
    요청마다 새 세션을 쓰고, 그 세션의 쿠키 정책이 모든 쿠키를 거부하며, Cookie 머리글도 비운다.
    같은 이유로 환경(.netrc·프록시 변수)을 믿지 않고 auth·Authorization 도 비운다.
    --allow-writes 의 인증 세션 동작은 바꾸지 않는다.
    """

    def __init__(self, base_url: str, allow_writes: bool = False, session_factory=None):
        self.base, self.allow_writes, self.sessions = base_url.rstrip('/'), allow_writes, {}
        self._factory = session_factory

    def _new_session(self):
        if self._factory is not None:
            return self._factory()
        import requests
        return requests.Session()

    def send(self, audience: str, method: str, path: str, body: Any):
        kw = {'timeout': 60, 'allow_redirects': False, **({'json': body} if body is not None else {})}
        if self.allow_writes:
            session = self.sessions.get(audience)
            if session is None:
                session = self.sessions[audience] = self._new_session()
            return session.request(method, self.base + path, **kw)
        import http.cookiejar
        session = self._new_session()   # 요청마다 새 세션 — 이전 응답의 쿠키가 남을 자리가 없다
        session.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
        # 익명 유지: .netrc 자동 인증·환경 프록시 설정을 읽지 않고, 인증 머리글을 싣지 않는다
        session.trust_env, session.auth = False, None
        for header in ('Cookie', 'Authorization', 'Proxy-Authorization'):
            session.headers.pop(header, None)
        try:
            return session.request(method, self.base + path, **kw)
        finally:
            session.close()


class _ServerError:
    """프로세스 안 500. 예외 «종류»만 남긴다(문장은 남기지 않는다 — 검토 c)."""

    status_code = 500
    headers: dict = {}

    def __init__(self, exc: Exception):
        root = exc
        while root.__cause__ is not None:
            root = root.__cause__
        self.exception = type(root).__name__


def _read(resp) -> tuple[Any, bool]:
    ctype = (getattr(resp, 'headers', {}) or {}).get('content-type', '')
    if 'json' not in ctype.lower():
        return None, False
    try:
        return resp.json(), True
    except Exception:  # noqa: BLE001
        return None, False


def _error_code(data: Any) -> str | None:
    """오류 응답에서 기계용 코드만 꺼낸다(`error` · `code`). 자연어 detail 은 버린다."""
    if not isinstance(data, dict):
        return None
    for src in (data, data.get('detail')):
        if isinstance(src, dict):
            for k in ('error', 'code'):
                v = src.get(k)
                if isinstance(v, str) and CODE_RE.match(v):
                    return v
    return None


def _evidence(data: Any, keys: tuple[str, ...]) -> dict:
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in keys
            if isinstance(data.get(k), (bool, int, float)) and not isinstance(data.get(k), str)}


def _is_generic_404(status: int, data: Any) -> bool:
    return status == 404 and data == {'detail': 'Not Found'}


# ── 단계 하나 판정 ──────────────────────────────────────────────────────────
def run_step(step: Step, ctx: dict, routes: RouteIndex | None, transport, allow_writes: bool) -> dict:
    rec = {'key': step.key, 'title': step.title, 'sent': f'{step.method} {step.path}' if step.path else None}
    if step.path is None:
        return {**rec, 'state': RED, 'reason': step.missing}

    names = [f for _, f, _, _ in string.Formatter().parse(step.path) if f]
    if routes is not None and not routes.has(step.method, step.path.format(**{k: 'x' for k in names})):
        return {**rec, 'state': RED, 'reason': '경로 없음 — 앱에 등록돼 있지 않다'}
    route_note = '경로는 있음' if routes is not None else '경로 확인 안 함(원격)'

    absent = [k for k in step.needs if not ctx.get(k)]
    probing = bool(absent) and all(k in step.probe for k in absent)
    if absent and not probing:
        return {**rec, 'state': YELLOW, 'reason': f'{route_note} · 앞 단계가 남긴 값 없음({", ".join(absent)})'}
    if not allow_writes and not (step.readonly and step.audience == 'guest'):
        why = '쓰기 단계' if not step.readonly else '쿠키를 보내는 단계'
        return {**rec, 'state': YELLOW, 'reason': f'{route_note} · {why}라 보내지 않음(--allow-writes 꺼짐)'}

    values = {**ctx, **{k: step.probe[k] for k in absent}}
    path = step.path.format(**{k: values[k] for k in names})
    body = step.body(values) if step.body else None
    started = time.perf_counter()
    resp = transport.send(step.audience, step.method, path, body)
    rec['ms'] = round((time.perf_counter() - started) * 1000)
    data, is_json = _read(resp)
    rec.update(status=resp.status_code, json=is_json)
    code = getattr(resp, 'exception', None) or _error_code(data)
    if code:
        rec['code'] = code
    ev = _evidence(data, step.evidence)
    if ev:
        rec['evidence'] = ev

    if _is_generic_404(resp.status_code, data):
        return {**rec, 'state': RED, 'reason': '경로 없음 — 서버가 라우트 없음(404 Not Found)으로 답함'}
    if probing:
        # 앞 단계가 대상을 못 만들어 자리표시 값으로 경로만 두드렸다. 통과 근거가 될 수 없다.
        if resp.status_code >= 500 or resp.status_code == 409:
            return {**rec, 'state': RED, 'reason': f'대상 없이 두드려도 HTTP {resp.status_code} — 이 단계는 지금 막혀 있다'}
        return {**rec, 'state': YELLOW,
                'reason': f'경로는 응답함 · 앞 단계가 대상({", ".join(absent)})을 못 만들어 실제 확인 못 함'}

    failure = step.expect(resp.status_code, data, ctx)
    if failure:
        return {**rec, 'state': RED, 'reason': failure}
    if step.keep:
        step.keep(data, ctx)
    return {**rec, 'state': GREEN, 'reason': '실제 요청 통과'}


def run(scenarios: list[Scenario], routes: RouteIndex | None, transport, allow_writes: bool,
        ctx: dict) -> list[dict]:
    out = []
    for sc in scenarios:
        steps = []
        for step in sc.steps:
            try:
                steps.append(run_step(step, ctx, routes, transport, allow_writes))
            except Exception as exc:  # noqa: BLE001 — 한 단계의 예외가 측정 전체를 멈추지 않게
                steps.append({'key': step.key, 'title': step.title, 'state': RED,
                              'sent': f'{step.method} {step.path}' if step.path else None,
                              'reason': f'측정 중 예외({type(exc).__name__})'})
        out.append({'key': sc.key, 'title': sc.title, 'actor': sc.actor, 'note': sc.note,
                    'end_to_end': sc.end_to_end,
                    'complete': all(s['state'] == GREEN for s in steps), 'steps': steps})
    return out


# ── 기록 ────────────────────────────────────────────────────────────────────
def _git(*args: str) -> str:
    try:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ''


def render_md(run_info: dict, results: list[dict]) -> str:
    steps = [s for sc in results for s in sc['steps']]
    n = {k: sum(1 for s in steps if s['state'] == k) for k in (GREEN, YELLOW, RED)}
    e2e = [sc for sc in results if sc.get('end_to_end', True)]
    checks = [sc for sc in results if not sc.get('end_to_end', True)]
    complete = sum(1 for sc in e2e if sc['complete'])
    lines = [
        '# 끝까지 시나리오 진척',
        '',
        f"측정 {run_info['at']} · 커밋 `{run_info['commit'][:7] or '?'}` · 대상 {run_info['target']}"
        f" · 쓰기 {'허용' if run_info['allow_writes'] else '금지'} · 측정자 {run_info['measured_by']}",
        '',
        f"**끝까지 되는 시나리오 {complete}/{len(e2e)} · 단계 통과 {n[GREEN]}/{len(steps)}**"
        f" (🟢 {n[GREEN]} · 🟡 {n[YELLOW]} · 🔴 {n[RED]})"
        + (f" · 가용성 점검 {sum(1 for sc in checks if sc['complete'])}/{len(checks)} 통과(완료 수에 넣지 않음)"
           if checks else ''),
        '',
        '판정: 🟢 이번 실행에서 실제 요청이 기대대로 끝남(유일한 통과 근거) · 🟡 경로는 있으나 '
        '이번에 확인 못 함 · 🔴 실제 요청 실패 또는 경로 없음. 정의 `tests/scenarios/definitions.py`.',
        '',
    ]
    for sc in results:
        head = ('✅' if sc['complete'] else '⬜') if sc.get('end_to_end', True) else '🔎'
        lines += [f"## {head} {sc['title']} <sub>{sc['actor']}</sub>", '']
        if sc.get('note'):
            lines += [f"> {sc['note']}", '']
        lines += ['| 단계 | 판정 | 요청 | 근거 |', '|---|---|---|---|']
        for s in sc['steps']:
            got = ''
            if 'status' in s:
                got = f" → {s['status']}" + ('' if s.get('json') else ' (JSON 아님)')
            extra = ''
            if s.get('code'):
                extra += f" · 코드 `{s['code']}`"
            if s.get('evidence'):
                extra += ' · ' + ', '.join(f'{k}={v}' for k, v in s['evidence'].items())
            lines.append(f"| {s['title']} | {MARK[s['state']]} | `{s.get('sent') or '—'}{got}` | {s['reason']}{extra} |")
        lines.append('')
    return '\n'.join(lines)


def main(argv: list[str] | None = None, transport=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--base-url', help='떠 있는 서버 주소. 없으면 이 저장소의 앱을 프로세스 안에서 띄운다')
    ap.add_argument('--allow-writes', action='store_true', help='readonly 가 아닌 단계·쿠키를 보내는 단계도 보낸다')
    ap.add_argument('--out', help='status.md · last-run.json 을 쓸 폴더')
    ap.add_argument('--target-label', help='기록에 적을 대상 설명(예: CI 일회용 DB)')
    ap.add_argument('--measured-by', default='클라우드 쪽', help='기록에 적을 측정 주체(예: PC 쪽)')
    ap.add_argument('--summary', help='표를 덧붙일 파일(GitHub Actions 의 $GITHUB_STEP_SUMMARY)')
    args = ap.parse_args(argv)

    routes = None
    if args.base_url:
        transport = transport or Remote(args.base_url, args.allow_writes)   # 원격: api·.env·DB 엔진을 불러오지 않는다
    else:
        sys.path.insert(0, str(ROOT))
        try:
            from api.main import app
        except Exception as exc:  # noqa: BLE001
            print(f'[meter] 앱을 불러오지 못했다: {type(exc).__name__}', file=sys.stderr)
            return 2
        routes, transport = RouteIndex(app), transport or InProcess(app)

    ctx = {'admin_email': os.environ.get('SCENARIO_ADMIN_EMAIL', ''),
           'admin_password': os.environ.get('SCENARIO_ADMIN_PASSWORD') or None}
    results = run(SCENARIOS, routes, transport, args.allow_writes, ctx)
    run_info = {'at': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                'commit': _git('rev-parse', 'HEAD'),
                'target': args.target_label or (args.base_url or '이 저장소 앱 + DATABASE_URL 의 DB'),
                'allow_writes': args.allow_writes, 'measured_by': args.measured_by}
    md = render_md(run_info, results)
    print(md)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'status.md').write_text(md + '\n', encoding='utf-8')
        (out / 'last-run.json').write_text(
            json.dumps({'run': run_info, 'scenarios': results}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    if args.summary:
        with open(args.summary, 'a', encoding='utf-8') as fh:
            fh.write(md + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
