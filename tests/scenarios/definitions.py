"""「끝까지 시나리오」 정의 — 고객과 운영자가 실제로 끝내야 하는 여정과 그 단계.

이 파일이 «완료»의 정의다(협업 분담표 7번). 단계 하나는 HTTP 요청 하나이고,
측정기(`meter.py`)가 실제 API 에 보내서 통과·실패를 기록한다.

    초록  이번 실행에서 실제 요청이 기대대로 끝났다 (유일한 통과 근거)
    노랑  경로는 코드에 있는데 이번 실행에서 확인하지 못했다
          (쓰기 금지 상태 · 앞 단계 실패 · 대상 없이 경로만 두드림)
    빨강  실제 요청이 실패했다(상태 코드를 적는다) · 또는 경로 자체가 없다

정적 검사(경로가 코드에 있다)는 노랑이 최대치다. 초록은 실행 기록으로만 나온다.

■ 고치는 규칙
  - 경로가 새로 생기면(예: 커머스 주문 생성·결제) 그 단계의 `path` 를 채우고 `missing`
    을 지운다. 기대값(`expect`)을 낮춰서 초록을 만들지 않는다 — 기대값은 «고객이
    그 단계를 끝냈다»는 사실을 말해야 한다.
  - 단계 이름은 고객·운영자가 하는 일이다(함수 이름이 아니다).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

Ctx = dict[str, Any]


@dataclass
class Step:
    key: str
    title: str
    method: str = 'GET'
    path: str | None = None                 # None = 이 단계를 하는 경로가 코드에 없다
    missing: str = ''                       # path 가 None 일 때: 무엇이 없는지(근거)
    body: Callable[[Ctx], Any] | None = None
    needs: tuple[str, ...] = ()             # 앞 단계가 ctx 에 남겨야 하는 값
    probe: dict[str, str] = field(default_factory=dict)  # needs 가 없을 때 경로만 두드릴 자리표시 값
    writes: bool = False                    # DB 에 행을 만든다 — --allow-writes 일 때만 보낸다
    audience: str = 'guest'                 # guest | member | admin — 어느 쿠키 상자를 쓰나
    expect: Callable[[int, Any], str | None] = None  # None = 통과, 문자열 = 실패 사유
    keep: Callable[[Any, Ctx], None] | None = None  # 통과 시 ctx 에 남길 값


@dataclass
class Scenario:
    key: str
    title: str
    actor: str          # 고객 | 운영자
    steps: list[Step]


# ── 기대값 도우미 ──────────────────────────────────────────────────────────
def ok_json(check: Callable[[Any], str | None] | None = None, codes=(200, 201)):
    def _expect(status: int, data: Any) -> str | None:
        if status not in codes:
            return f'HTTP {status}'
        if check is None:
            return None
        return check(data)
    return _expect


def _has(key: str, want: Any = ...):
    def _check(data: Any) -> str | None:
        if not isinstance(data, dict) or key not in data:
            return f'응답에 {key} 없음'
        if want is not ... and data[key] != want:
            return f'{key}={data[key]!r} (기대 {want!r})'
        return None
    return _check


def _quote_ready(data: Any) -> str | None:
    sets = data.get('sets') if isinstance(data, dict) else None
    if not isinstance(sets, dict):
        return '응답에 sets 없음'
    built = [t for t in ('recommend', 'value', 'highend') if sets.get(t)]
    if not built:
        return '세 티어 모두 구성 불가(sets 전부 null)'
    if not data.get('session_id'):
        return 'session_id 없음'
    return None


def _keep_quote(data: Any, ctx: Ctx) -> None:
    sets = data['sets']
    tier = next(t for t in ('recommend', 'value', 'highend') if sets.get(t))
    ctx['session_id'] = data['session_id']
    ctx['access_key'] = data.get('access_key')
    ctx['tier'] = tier
    codes = []
    for part in (sets[tier] or {}).get('parts', []) or []:
        code = part.get('product_code') if isinstance(part, dict) else None
        if isinstance(code, int):
            codes.append(code)
    ctx['product_codes'] = codes


def _keep_order(data: Any, ctx: Ctx) -> None:
    no = data.get('order_no') or (data.get('order') or {}).get('order_no')
    if no:
        ctx['order_no'] = no


# 시나리오에서 쓰는 고객 조건 — 견적 화면의 기본 흐름과 같은 두 조건(용도 + 예산)
QUOTE_CONSTRAINTS = [{'l': '용도', 'v': '게임'}, {'l': '예산', 'v': '150만원'}]
SCENARIO_MEMBER = {'nick': '시나리오', 'email': 'scenario-member@ci.popcorn.invalid', 'via': 'email'}
SCENARIO_SHIPPING = {'name': '시나리오', 'phone': '010-0000-0000', 'addr': '측정기 전용 주소'}


def _order_body(ctx: Ctx) -> dict:
    return {'session_id': ctx['session_id'], 'tier': ctx['tier'], 'member': SCENARIO_MEMBER,
            'shipping': SCENARIO_SHIPPING, 'access_key': ctx.get('access_key')}


# 견적까지의 공통 앞부분 — 주문·인계 시나리오도 이 두 단계를 다시 밟는다
def _quote_steps(prefix: str) -> list[Step]:
    return [
        Step(f'{prefix}.count', '조건에 맞는 부품으로 조립 가능한지 확인', 'POST', '/api/candidates/count',
             body=lambda c: {'constraints': QUOTE_CONSTRAINTS},
             expect=ok_json(_has('buildable', True))),
        Step(f'{prefix}.quote', '견적 받기(용도 게임 · 예산 150만원)', 'POST', '/api/recommend',
             body=lambda c: {'mode': 'guided', 'constraints': QUOTE_CONSTRAINTS},
             writes=True, expect=ok_json(_quote_ready), keep=_keep_quote),
    ]


SCENARIOS: list[Scenario] = [
    Scenario('quote', '추천에서 견적까지', '고객', [
        Step('quote.bands', '예산 구간 보기', 'GET', '/api/budget-bands', expect=ok_json(_has('ok', True))),
        *_quote_steps('quote'),
        Step('quote.revalidate', '견적 부품의 가격·재고 다시 확인', 'POST', '/api/recommend/revalidate',
             body=lambda c: {'product_codes': c['product_codes']}, needs=('product_codes',),
             expect=ok_json()),
    ]),
    Scenario('handoff', '견적을 쇼핑몰 주문으로 넘기기(몰 인계)', '고객', [
        *_quote_steps('handoff'),
        Step('handoff.create', '쇼핑몰 인계 접수', 'POST', '/api/handoff',
             body=lambda c: {'session_id': c['session_id'], 'tier': c['tier'], 'access_key': c.get('access_key')},
             needs=('session_id', 'tier'), writes=True, expect=ok_json(),
             keep=lambda d, c: c.__setitem__('handoff_no', d.get('handoff_no'))),
        Step('handoff.view', '인계 내역 조회', 'GET', '/api/handoff/{handoff_no}', needs=('handoff_no',),
             probe={'handoff_no': 'HO-0'}, expect=ok_json()),
    ]),
    Scenario('login', '고객 로그인', '고객', [
        Step('login.login', '로그인(가입)', 'POST', '/api/auth/login', audience='member',
             body=lambda c: {'email': SCENARIO_MEMBER['email'], 'provider': 'email'},
             writes=True, expect=ok_json(_has('state', 'active')),
             keep=lambda d, c: c.__setitem__('member', True)),
        Step('login.me', '로그인 상태 확인', 'GET', '/api/auth/me', audience='member', needs=('member',),
             expect=ok_json(_has('authenticated', True))),
        Step('login.my_orders', '내 주문 보기', 'GET', '/api/my/orders', audience='member', needs=('member',),
             expect=ok_json()),
    ]),
    Scenario('order', '주문 만들기', '고객', [
        *_quote_steps('order'),
        Step('order.create', '주문 생성', 'POST', '/api/orders', body=_order_body,
             needs=('session_id', 'tier'), writes=True, expect=ok_json(), keep=_keep_order),
        Step('order.view', '주문 조회', 'GET', '/api/commerce/orders/{order_no}', needs=('order_no',),
             probe={'order_no': 'ORD-SCENARIO-PROBE'}, expect=ok_json()),
    ]),
    Scenario('payment', '결제하기', '고객', [
        Step('payment.prepare', '결제 준비(주문 금액 확정)', missing=(
            'HTTP 경로 없음 — api/commerce_writer.py 의 create_draft·prepare 를 부르는 라우트가 없다')),
        Step('payment.approve', '결제 승인', missing=(
            'HTTP 경로 없음 — commerce_writer 의 dispatch·finalize 를 부르는 라우트가 없다')),
        Step('payment.history', '내 결제 내역 보기', 'GET', '/api/my/payments', audience='member',
             needs=('order_no', 'member'), expect=ok_json()),
    ]),
    Scenario('admin', '운영자 주문 관리', '운영자', [
        Step('admin.login', '관리자 로그인', 'POST', '/api/admin/auth/login', audience='admin',
             body=lambda c: {'email': c['admin_email'], 'password': c.get('admin_password')},
             needs=('admin_email',), writes=True, expect=ok_json(_has('state', 'active')),
             keep=lambda d, c: c.__setitem__('admin', True)),
        Step('admin.commerce_orders', '커머스 주문 목록', 'GET', '/api/admin/commerce/orders', audience='admin',
             needs=('admin',), expect=ok_json()),
        Step('admin.payments', '결제 내역 목록', 'GET', '/api/admin/payments', audience='admin',
             needs=('admin',), expect=ok_json()),
        Step('admin.refunds', '환불 요청 목록', 'GET', '/api/admin/refunds', audience='admin',
             needs=('admin',), expect=ok_json()),
    ]),
    Scenario('fulfillment', '출고 등록과 배송 조회', '운영자', [
        Step('fulfillment.register', '출고 등록', 'POST', '/api/admin/commerce/orders/{order_no}/fulfillment',
             audience='admin', needs=('order_no', 'admin'), probe={'order_no': 'ORD-SCENARIO-PROBE'},
             body=lambda c: {}, writes=True, expect=ok_json()),
        Step('fulfillment.customer_view', '고객이 배송 상태 보기', 'GET',
             '/api/commerce/orders/{order_no}/fulfillment', needs=('order_no',),
             probe={'order_no': 'ORD-SCENARIO-PROBE'}, expect=ok_json()),
    ]),
    Scenario('return', '반품', '고객 · 운영자', [
        Step('return.request', '고객 반품 접수', missing=(
            'HTTP 경로 없음 — 실물 반품 접수 라우트가 없다(api/commerce_physical_return_http.py 는 관리자 조회 GET 둘뿐)')),
        Step('return.pickup', '회수·입고 처리', missing='HTTP 경로 없음 — 회수·입고·실행 라우트가 없다'),
        Step('return.admin_view', '운영자 반품 내역 보기', 'GET', '/api/admin/commerce/orders/{order_no}/physical-returns',
             audience='admin', needs=('order_no', 'admin'), probe={'order_no': 'ORD-SCENARIO-PROBE'},
             expect=ok_json()),
    ]),
]
