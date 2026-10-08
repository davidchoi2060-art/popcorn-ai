"""「끝까지 시나리오」 진척 측정기 — 협업 분담표 7번.

시나리오(`definitions.py`)의 단계마다 실제 HTTP 요청을 보내고 결과를 표로 남긴다.
초록은 «이번 실행에서 실제 요청이 통과했다»일 때만 나온다. 코드에 경로가 있다는 것은
노랑까지다.

실행
    # 이 저장소의 앱을 프로세스 안에서 띄워 DATABASE_URL 의 DB 로 확인 (CI 기본)
    python tests/scenarios/meter.py --allow-writes --out docs/scenarios

    # 떠 있는 서버를 두드린다 (개발 서버 등). 쓰기 단계는 기본으로 보내지 않는다.
    python tests/scenarios/meter.py --base-url https://admin.popcornai.co.kr --out docs/scenarios

    관리자 단계: SCENARIO_ADMIN_EMAIL (+ SCENARIO_ADMIN_PASSWORD). CI 는 일회용 DB 에
    ADMIN_BOOTSTRAP_EMAILS 로 첫 owner 를 만들어 쓴다.

쓰기
    견적·로그인·주문처럼 행을 만드는 단계는 `--allow-writes` 일 때만 보낸다. 공유 Cloud SQL
    을 가리키는 PC 의 .env 로 돌릴 때는 무엇이 만들어지는지 알고 켠다(CLAUDE.md 「검증이
    흔적을 남긴다」). CI 의 DB 는 작업이 끝나면 사라진다.

종료 코드
    0  측정이 끝났다(빨강이 있어도 0 — 이것은 진척 측정이지 합격 판정이 아니다)
    2  측정기 자체가 돌지 못했다(앱 import 실패 등)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import string
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from definitions import SCENARIOS, Scenario, Step  # noqa: E402

GREEN, YELLOW, RED = 'green', 'yellow', 'red'
MARK = {GREEN: '🟢 통과', YELLOW: '🟡 미확인', RED: '🔴 실패'}
EXCERPT = 240


# ── 경로가 코드에 있나 (정적 — 노랑의 근거) ─────────────────────────────────
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
class Transport:
    """audience(guest·member·admin)마다 쿠키 상자를 따로 둔다 — 고객·관리자 세션이 섞이지 않게."""

    def __init__(self, app=None, base_url: str | None = None):
        self.target = base_url or 'in-process'
        self.clients: dict[str, Any] = {}
        self._app, self._base = app, base_url

    def client(self, audience: str):
        if audience not in self.clients:
            if self._base:
                self.clients[audience] = _Remote(self._base)
            else:
                from fastapi.testclient import TestClient
                # https: 커머스 경로는 https 가 아니면 503 이다(commerce_owner_contexts) — 실제 배포와 같은 조건으로 본다.
                # 500 의 원인(예외)을 기록에 남기려고 예외를 그대로 받는다 — send() 가 500 으로 바꾼다.
                self.clients[audience] = TestClient(self._app, base_url='https://testserver')
        return self.clients[audience]

    def send(self, audience: str, method: str, path: str, body: Any):
        kwargs = {'json': body} if body is not None else {}
        try:
            return self.client(audience).request(method, path, **kwargs)
        except Exception as exc:  # noqa: BLE001 — 프로세스 안 실행에서만 온다: 서버라면 500 을 줬을 자리
            return _ServerError(exc)


class _Remote:
    """떠 있는 서버용 — requirements.txt 에 이미 있는 requests 로 보낸다. 쿠키는 세션이 들고 있다."""

    def __init__(self, base_url: str):
        import requests
        self.base, self.session = base_url.rstrip('/'), requests.Session()

    def request(self, method: str, path: str, **kwargs):
        return self.session.request(method, self.base + path, timeout=60, allow_redirects=False, **kwargs)


class _ServerError:
    """프로세스 안 실행에서 처리되지 않은 예외 = 실제 서버의 500. 원인 한 줄을 응답 본문 대신 남긴다."""

    status_code = 500

    def __init__(self, exc: Exception):
        root = exc
        while root.__cause__ is not None:
            root = root.__cause__
        self.text = f'500 {type(root).__name__}: {str(root).splitlines()[0] if str(root) else ""}'

    def json(self):
        raise ValueError('not json')


def _excerpt(resp) -> tuple[Any, str]:
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001 — 본문이 JSON 이 아니면 글자로 남긴다
        return None, resp.text[:EXCERPT]
    detail = data.get('detail') if isinstance(data, dict) else None
    shown = detail if detail is not None else data
    text = json.dumps(shown, ensure_ascii=False)
    # 열쇠·세션 값은 기록에 남기지 않는다
    for secret in ('access_key',):
        if isinstance(data, dict) and data.get(secret):
            text = text.replace(str(data[secret]), '***')
    return data, text[:EXCERPT]


# ── 단계 하나 판정 ──────────────────────────────────────────────────────────
def run_step(step: Step, ctx: dict, routes: RouteIndex, transport: Transport, allow_writes: bool) -> dict:
    rec = {'key': step.key, 'title': step.title, 'method': step.method, 'path': step.path}
    if step.path is None:
        return {**rec, 'state': RED, 'reason': step.missing}

    names = [f for _, f, _, _ in string.Formatter().parse(step.path) if f]
    probe_path = step.path.format(**{k: 'x' for k in names})
    if not routes.has(step.method, probe_path):
        return {**rec, 'state': RED, 'reason': f'경로 없음 — {step.method} {step.path} 가 앱에 등록돼 있지 않다'}

    absent = [k for k in step.needs if not ctx.get(k)]
    probing = bool(absent) and all(k in step.probe for k in absent)
    if absent and not probing:
        return {**rec, 'state': YELLOW, 'reason': f'경로는 있음 · 앞 단계가 남긴 값 없음({", ".join(absent)})'}
    if step.writes and not allow_writes:
        return {**rec, 'state': YELLOW, 'reason': '경로는 있음 · 쓰기 단계라 보내지 않음(--allow-writes 꺼짐)'}

    values = {**ctx, **{k: step.probe[k] for k in absent}}
    path = step.path.format(**{k: values[k] for k in names})
    body = step.body(values) if step.body else None
    started = time.perf_counter()
    resp = transport.send(step.audience, step.method, path, body)
    ms = round((time.perf_counter() - started) * 1000)
    data, text = _excerpt(resp)
    rec.update(status=resp.status_code, ms=ms, sent=f'{step.method} {path}', response=text)

    if probing:
        # 앞 단계가 대상을 못 만들어 자리표시 값으로 경로만 두드렸다. 통과 근거가 될 수 없다.
        if resp.status_code >= 500 or resp.status_code == 409:
            return {**rec, 'state': RED, 'reason': f'대상 없이 두드려도 HTTP {resp.status_code} — 이 단계는 지금 막혀 있다'}
        return {**rec, 'state': YELLOW,
                'reason': f'경로는 응답함(HTTP {resp.status_code}) · 앞 단계가 대상({", ".join(absent)})을 못 만들어 실제 확인 못 함'}

    failure = step.expect(resp.status_code, data)
    if failure:
        return {**rec, 'state': RED, 'reason': failure}
    if step.keep:
        step.keep(data, ctx)
    return {**rec, 'state': GREEN, 'reason': '실제 요청 통과'}


def run(scenarios: list[Scenario], routes: RouteIndex, transport: Transport, allow_writes: bool,
        ctx: dict) -> list[dict]:
    out = []
    for sc in scenarios:
        steps = []
        for step in sc.steps:
            try:
                steps.append(run_step(step, ctx, routes, transport, allow_writes))
            except Exception as exc:  # noqa: BLE001 — 한 단계의 예외가 측정 전체를 멈추지 않게
                steps.append({'key': step.key, 'title': step.title, 'method': step.method, 'path': step.path,
                              'state': RED, 'reason': f'요청 중 예외: {type(exc).__name__}: {str(exc)[:EXCERPT]}'})
        done = all(s['state'] == GREEN for s in steps)
        out.append({'key': sc.key, 'title': sc.title, 'actor': sc.actor, 'complete': done, 'steps': steps})
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
    complete = sum(1 for sc in results if sc['complete'])
    lines = [
        '# 끝까지 시나리오 진척',
        '',
        f"측정 {run_info['at']} · 커밋 `{run_info['commit'][:7] or '?'}` · 대상 {run_info['target']}"
        f" · 쓰기 {'허용' if run_info['allow_writes'] else '금지'}",
        '',
        f"**끝까지 되는 시나리오 {complete}/{len(results)} · 단계 통과 {n[GREEN]}/{len(steps)}**"
        f" (🟢 {n[GREEN]} · 🟡 {n[YELLOW]} · 🔴 {n[RED]})",
        '',
        '판정: 🟢 이번 실행에서 실제 요청이 기대대로 끝남(유일한 통과 근거) · 🟡 경로는 코드에 있으나 '
        '이번에 확인 못 함 · 🔴 실제 요청 실패 또는 경로 없음. 정의 `tests/scenarios/definitions.py`.',
        '',
    ]
    for sc in results:
        head = '✅' if sc['complete'] else '⬜'
        lines += [f"## {head} {sc['title']} <sub>{sc['actor']}</sub>", '',
                  '| 단계 | 판정 | 요청 | 근거 |', '|---|---|---|---|']
        for s in sc['steps']:
            req = s.get('sent') or (f"{s['method']} {s['path']}" if s.get('path') else '—')
            status = f" → {s['status']}" if 'status' in s else ''
            reason = s['reason']
            if s.get('response') and s['state'] != GREEN:
                reason += f" · 응답 `{s['response'][:140].replace('|', '/')}`"
            lines.append(f"| {s['title']} | {MARK[s['state']]} | `{req}{status}` | {reason} |")
        lines.append('')
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--base-url', help='떠 있는 서버 주소. 없으면 이 저장소의 앱을 프로세스 안에서 띄운다')
    ap.add_argument('--allow-writes', action='store_true', help='행을 만드는 단계도 보낸다')
    ap.add_argument('--out', help='status.md · last-run.json 을 쓸 폴더')
    ap.add_argument('--target-label', help='기록에 적을 대상 설명(예: CI 일회용 DB)')
    ap.add_argument('--summary', help='표를 덧붙일 파일(GitHub Actions 의 $GITHUB_STEP_SUMMARY)')
    args = ap.parse_args(argv)

    try:
        from api.main import app  # 라우트 목록(정적 검사)과 프로세스 안 실행에 쓴다
    except Exception as exc:  # noqa: BLE001
        print(f'[meter] 앱을 불러오지 못했다: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2

    ctx = {'admin_email': os.environ.get('SCENARIO_ADMIN_EMAIL', ''),
           'admin_password': os.environ.get('SCENARIO_ADMIN_PASSWORD') or None}
    transport = Transport(app=None if args.base_url else app, base_url=args.base_url)
    results = run(SCENARIOS, RouteIndex(app), transport, args.allow_writes, ctx)
    run_info = {'at': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                'commit': _git('rev-parse', 'HEAD'),
                'target': args.target_label or (args.base_url or '이 저장소 앱 + DATABASE_URL 의 DB'),
                'allow_writes': args.allow_writes}
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
