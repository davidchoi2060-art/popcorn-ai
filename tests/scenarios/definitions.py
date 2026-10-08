"""「끝까지 시나리오」 정의 — 고객과 운영자가 실제로 끝내야 하는 여정과 그 단계.

이 파일이 «완료»의 정의다(협업 분담표 7번). 단계 하나는 HTTP 요청 하나이고,
측정기(`meter.py`)가 실제 API 에 보내서 통과·실패를 기록한다.

    초록  이번 실행에서 실제 요청이 기대대로 끝났다 (유일한 통과 근거)
    노랑  경로는 있는데 이번 실행에서 확인하지 못했다
          (쓰기 금지 상태 · 앞 단계 실패 · 대상 없이 경로만 두드림)
    빨강  실제 요청이 실패했다(상태 코드를 적는다) · 또는 경로 자체가 없다

정적 검사(경로가 코드에 있다)는 노랑이 최대치다. 초록은 실행 기록으로만 나온다.

■ 쓰기 안전 (PR #2 PC 쪽 검토 b)
  `readonly` 는 기본 False 다. **코드를 읽어 DB 에 쓰지 않음을 확인한 단계만** True 로
  두고, 그 근거(파일:줄)를 `readonly` 옆 주석에 적는다. HTTP 메서드는 근거가 아니다 —
  인증된 GET 도 세션 last_seen 을 쓸 수 있다. 그래서 guest 가 아닌 단계(쿠키를 보내는 단계)는
  readonly 여도 쓰기 허용일 때만 보낸다(meter.py).

■ 기록 (PR #2 PC 쪽 검토 c)
  응답 원문은 남기지 않는다. 기록에는 상태 코드, JSON 여부, 그리고 단계가 `evidence` 로
  지정한 키의 «숫자·참거짓» 값, 오류 응답의 오류 코드(`^[a-z0-9_]+$`)만 남는다.

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
    readonly: bool = False                  # 코드로 «쓰지 않음»을 확인한 단계만 True (위 머리말)
    audience: str = 'guest'                 # guest | member | admin — 어느 쿠키 상자를 쓰나
    expect: Callable[..., str | None] = None  # (status, data, ctx) -> None 통과 · 문자열 실패 사유
    keep: Callable[[Any, Ctx], None] | None = None  # 통과 시 ctx 에 남길 값
    evidence: tuple[str, ...] = ()          # 기록에 남길 응답 키(숫자·참거짓만 남는다)


@dataclass
class Scenario:
    key: str
    title: str
    actor: str          # 고객 | 운영자
    steps: list[Step]
    note: str = ''      # 이 시나리오가 무엇을 증명하지 «않는지»
    end_to_end: bool = True  # False = 가용성 점검(「끝까지 되는 시나리오」 수에 넣지 않는다)


# ── 기대값 도우미 ──────────────────────────────────────────────────────────
def ok_json(check: Callable[[Any], str | None] | None = None, codes=(200, 201)):
    """기대 상태 코드 + JSON 본문. HTML 200(정적 캐치올·로그인 화면 등)은 실패다."""
    def _expect(status: int, data: Any, ctx: Ctx | None = None) -> str | None:
        if status not in codes:
            return f'HTTP {status}'
        if data is None:
            return f'HTTP {status} 인데 JSON 이 아님'
        if check is None:
            return None
        return check(data)
    return _expect


def _has(key: str, want: Any = ...):
    def _check(data: Any) -> str | None:
        if not isinstance(data, dict) or key not in data:
            return f'응답에 {key} 없음'
        if want is not ... and data[key] != want:
            got = data[key] if isinstance(data[key], (bool, int)) or data[key] is None else '다른 값'
            return f'{key}={got} (기대 {want})'
        return None
    return _check


def _list_at(*keys: str):
    """목록 응답: 지정한 키 중 하나가 리스트여야 한다(빈 목록도 «조회 가능»으로는 통과)."""
    def _check(data: Any) -> str | None:
        if isinstance(data, dict):
            for k in keys:
                if isinstance(data.get(k), list):
                    return None
        return f'목록 키({"/".join(keys)}) 없음'
    return _check


def _quote_ready(data: Any) -> str | None:
    sets = data.get('sets') if isinstance(data, dict) else None
    if not isinstance(sets, dict):
        return '응답에 sets 없음'
    if not any(sets.get(t) for t in ('recommend', 'value', 'highend')):
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


def _state_of(data: Any) -> Any:
    if isinstance(data, dict):
        for k in ('state', 'status', 'order_state'):
            if isinstance(data.get(k), str):
                return data[k]
        rec = data.get('record') or data.get('order')
        if isinstance(rec, dict):
            return _state_of(rec)
    return None


def _state_changed(data: Any, ctx: Ctx) -> str | None:
    before, after = ctx.get('order_state_before'), _state_of(data)
    if after is None:
        return '응답에서 주문 상태를 읽지 못함'
    if after == before:
        return '출고 등록 뒤에도 주문 상태가 그대로'
    return None


# 시나리오에서 쓰는 고객 조건 — 견적 화면의 기본 흐름과 같은 두 조건(용도 + 예산)
QUOTE_CONSTRAINTS = [{'l': '용도', 'v': '게임'}, {'l': '예산', 'v': '150만원'}]
SCENARIO_MEMBER = {'nick': '시나리오', 'email': 'scenario-member@ci.popcorn.invalid', 'via': 'email'}
SCENARIO_SHIPPING = {'name': '시나리오', 'phone': '010-0000-0000', 'addr': '측정기 전용 주소'}
NO_SUCH_ORDER = 'ORD-SCENARIO-NONE'


def _order_body(ctx: Ctx) -> dict:
    return {'session_id': ctx['session_id'], 'tier': ctx['tier'], 'member': SCENARIO_MEMBER,
            'shipping': SCENARIO_SHIPPING, 'access_key': ctx.get('access_key')}


# 견적까지의 공통 앞부분 — 주문·인계 시나리오도 이 두 단계를 다시 밟는다
def _quote_steps(prefix: str) -> list[Step]:
    return [
        Step(f'{prefix}.count', '조건에 맞는 부품으로 조립 가능한지 확인', 'POST', '/api/candidates/count',
             body=lambda c: {'constraints': QUOTE_CONSTRAINTS},
             readonly=True,  # api/candidates.py count_candidates: engine.connect() 의 SELECT 뿐, 방문자 키 발급 없음
             expect=ok_json(_has('buildable', True)), evidence=('buildable', 'total', 'count')),
        # recommend 는 consult_sessions·quote_snapshots 에 행을 만든다(api/recommend.py recommend)
        Step(f'{prefix}.quote', '견적 받기(용도 게임 · 예산 150만원)', 'POST', '/api/recommend',
             body=lambda c: {'mode': 'guided', 'constraints': QUOTE_CONSTRAINTS},
             expect=ok_json(_quote_ready), keep=_keep_quote),
    ]


SCENARIOS: list[Scenario] = [
    Scenario('quote', '추천에서 견적까지', '고객', [
        Step('quote.bands', '예산 구간 보기', 'GET', '/api/budget-bands',
             readonly=True,  # api/budget_bands.py: engine.connect() SELECT 뿐
             expect=ok_json(_has('ok', True))),
        *_quote_steps('quote'),
        Step('quote.revalidate', '견적 부품의 가격·재고 다시 확인', 'POST', '/api/recommend/revalidate',
             body=lambda c: {'product_codes': c['product_codes']}, needs=('product_codes',),
             readonly=True,  # api/recommend.py revalidate: engine.connect() SELECT 뿐
             expect=ok_json()),
    ]),
    Scenario('handoff', '견적을 쇼핑몰 주문으로 넘기기(몰 인계)', '고객', [
        *_quote_steps('handoff'),
        Step('handoff.create', '쇼핑몰 인계 접수', 'POST', '/api/handoff',
             body=lambda c: {'session_id': c['session_id'], 'tier': c['tier'], 'access_key': c.get('access_key')},
             needs=('session_id', 'tier'), expect=ok_json(),
             keep=lambda d, c: c.__setitem__('handoff_no', d.get('handoff_no'))),
        Step('handoff.view', '인계 내역 조회', 'GET', '/api/handoff/{handoff_no}', needs=('handoff_no',),
             probe={'handoff_no': 'HO-0'},
             readonly=True,  # api/handoff.py 조회: engine.connect() SELECT 뿐
             expect=ok_json()),
    ]),
    Scenario('login', '고객 로그인', '고객', [
        Step('login.login', '로그인(가입)', 'POST', '/api/auth/login', audience='member',
             body=lambda c: {'email': SCENARIO_MEMBER['email'], 'provider': 'email'},
             expect=ok_json(_has('state', 'active')), keep=lambda d, c: c.__setitem__('member', True)),
        Step('login.me', '로그인 상태 확인', 'GET', '/api/auth/me', audience='member', needs=('member',),
             expect=ok_json(_has('authenticated', True)), evidence=('authenticated',)),
        Step('login.my_orders', '내 주문 보기', 'GET', '/api/my/orders', audience='member', needs=('member',),
             expect=ok_json()),
    ]),
    Scenario('order', '주문 만들기', '고객', [
        *_quote_steps('order'),
        Step('order.create', '주문 생성', 'POST', '/api/orders', body=_order_body,
             needs=('session_id', 'tier'), expect=ok_json(), keep=_keep_order),
        Step('order.view', '주문 조회', 'GET', '/api/commerce/orders/{order_no}', needs=('order_no',),
             probe={'order_no': NO_SUCH_ORDER},
             readonly=True,  # api/commerce_orders.py read_order_detail: engine.connect() 읽기
             expect=ok_json()),
    ]),
    Scenario('payment', '결제하기', '고객', [
        Step('payment.prepare', '결제 준비(주문 금액 확정)', missing=(
            'HTTP 경로 없음 — api/commerce_writer.py 의 create_draft·prepare 를 부르는 라우트가 없다')),
        Step('payment.approve', '결제 승인', missing=(
            'HTTP 경로 없음 — commerce_writer 의 dispatch·finalize 를 부르는 라우트가 없다')),
        Step('payment.history', '내 결제 내역 보기', 'GET', '/api/my/payments', audience='member',
             needs=('order_no', 'member'), expect=ok_json()),
    ]),
    Scenario('admin_lists', '운영자 목록 조회', '운영자', [
        Step('admin.login', '관리자 로그인', 'POST', '/api/admin/auth/login', audience='admin',
             body=lambda c: {'email': c['admin_email'], 'password': c.get('admin_password')},
             needs=('admin_email',), expect=ok_json(_has('state', 'active')),
             keep=lambda d, c: c.__setitem__('admin', True)),
        Step('admin.commerce_orders', '커머스 주문 목록', 'GET', '/api/admin/commerce/orders', audience='admin',
             needs=('admin',), readonly=True,  # admin_commerce_orders._stored_list: READ ONLY 트랜잭션
             expect=ok_json(_list_at('records', 'orders', 'items')), evidence=('total',)),
        Step('admin.payments', '결제 내역 목록', 'GET', '/api/admin/payments', audience='admin',
             needs=('admin',), expect=ok_json(_list_at('items', 'payments', 'rows')), evidence=('total',)),
        Step('admin.refunds', '환불 요청 목록', 'GET', '/api/admin/refunds', audience='admin',
             needs=('admin',), expect=ok_json(_list_at('items', 'refunds', 'rows')), evidence=('total',)),
        # 반례: 없는 주문을 «있는 것처럼» 200 으로 주지 않는다
        Step('admin.wrong_target', '없는 주문 상세는 찾을 수 없음으로 답함', 'GET',
             f'/api/admin/commerce/orders/{NO_SUCH_ORDER}', audience='admin', needs=('admin',),
             readonly=True,  # admin_commerce_orders._stored_detail: 읽기
             expect=ok_json(codes=(404,))),
    ], note='목록이 열린다는 것만 증명한다(빈 목록이어도 통과). 주문을 실제로 처리했다는 증거는 '
            '아래 「운영자 주문 처리」다. 그래서 「끝까지 되는 시나리오」 수에 넣지 않는다.', end_to_end=False),
    Scenario('admin_task', '운영자 주문 처리(실제 대상)', '운영자', [
        Step('task.detail', '대상 주문 상세 보기', 'GET', '/api/admin/commerce/orders/{order_no}', audience='admin',
             needs=('order_no', 'admin'), readonly=True, expect=ok_json(),
             keep=lambda d, c: c.__setitem__('order_state_before', _state_of(d))),
        Step('task.fulfill', '출고 등록', 'POST', '/api/admin/commerce/orders/{order_no}/fulfillment',
             audience='admin', needs=('order_no', 'admin'), probe={'order_no': NO_SUCH_ORDER},
             body=lambda c: {}, expect=ok_json(), keep=lambda d, c: c.__setitem__('fulfilled', True)),
        Step('task.after', '처리 뒤 주문 상태가 바뀌었는지 확인', 'GET', '/api/admin/commerce/orders/{order_no}',
             audience='admin', needs=('order_no', 'admin', 'fulfilled'), readonly=True,
             expect=lambda s, d, c: ok_json()(s, d) or _state_changed(d, c)),
        Step('task.recover', '잘못 처리한 출고 되돌리기', missing=(
            '복구 기준 미정 — 커머스 출고를 되돌리는 HTTP 경로가 정의되지 않았다(PC 쪽 8번에서 정한다)')),
    ], note='실제 주문 하나가 출고 등록으로 상태가 바뀌고 되돌릴 수 있어야 초록이다.'),
    Scenario('fulfillment', '고객 배송 조회', '고객', [
        Step('fulfillment.customer_view', '고객이 배송 상태 보기', 'GET',
             '/api/commerce/orders/{order_no}/fulfillment', needs=('order_no',),
             probe={'order_no': NO_SUCH_ORDER},
             readonly=True,  # commerce_fulfillment_http._read: READ ONLY 트랜잭션
             expect=ok_json()),
    ]),
    Scenario('return', '반품', '고객 · 운영자', [
        Step('return.request', '고객 반품 접수', missing=(
            'HTTP 경로 없음 — 실물 반품 접수 라우트가 없다(api/commerce_physical_return_http.py 는 관리자 조회 GET 둘뿐)')),
        Step('return.pickup', '회수·입고 처리', missing='HTTP 경로 없음 — 회수·입고·실행 라우트가 없다'),
        Step('return.admin_view', '운영자 반품 내역 보기', 'GET', '/api/admin/commerce/orders/{order_no}/physical-returns',
             audience='admin', needs=('order_no', 'admin'), probe={'order_no': NO_SUCH_ORDER},
             readonly=True, expect=ok_json()),
    ]),
]
