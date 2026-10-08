"""합성 출고 명령 검사 (PR #2 PC 쪽 출고 담당 fixture 원천).

원천 사슬: tests/test_commerce_fulfillment_http.py make -> tests/test_commerce_fulfillment_writer.py
prep_request -> h.intent -> h.command. 그 사슬로 만든 기대 명령과, 측정기가 «서버 응답 값만으로»
만드는 명령(definitions.build_prepare_command)이 같은 모양·같은 값인지 본다.
fixture 는 시뮬레이터 위 값이다(PostgreSQL·실서버 증명 아님). DB·네트워크 불필요.

실행: python -m pytest tests/scenarios/test_fulfillment_command.py -q
"""
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import definitions  # noqa: E402
from api import commerce_fulfillment_http as h  # noqa: E402
from tests.test_commerce_fulfillment_writer import Connection, prep_request  # noqa: E402


def _fixture_request():
    conn = Connection()
    return prep_request(conn)   # serial·UUID(int=…)·'d'*64 는 시뮬레이터 자리표시 값


def _server_payload(req, **act_changes):
    """출고 원천이 연결됐을 때 관리자 현황 GET 이 줄 actionable 값(모양 가정 — 생산자 연결 시 PC 쪽 확정)."""
    act = dict(allowed=True, expected_policy_basis=req['expected_policy_basis'],
               lines=[dict(line_id=l['line_id'], qty=l['qty']) for l in req['lines']]) | act_changes
    return dict(state='confirmed', order_no=req['order_no'], order_state=req['expected_order_state'],
                order_revision=req['expected_order_revision'], expected_order_basis=req['expected_order_basis'],
                actions=dict(prepare_shipment=act))


def test_built_command_matches_fixture_chain_and_parses():
    req = _fixture_request()
    expected = h.command(h.intent(req))
    cmd, why = definitions.build_prepare_command(_server_payload(req))
    assert why is None
    parsed = h.command(cmd)                       # 서버 파서를 통과한다(422 대상 아님)
    assert set(cmd) == set(definitions.FULFILLMENT_FIELDS)
    assert {k: v for k, v in parsed.items() if k != 'operation_id'} == \
           {k: v for k, v in expected.items() if k != 'operation_id'}
    # operation_id 는 fixture 자리표시(UUID int)가 아니라 새 실제 UUID
    assert parsed['operation_id'] != expected['operation_id']
    assert uuid.UUID(cmd['operation_id']).version == 4


def test_each_run_gets_a_fresh_operation_id():
    payload = _server_payload(_fixture_request())
    a, _ = definitions.build_prepare_command(payload)
    b, _ = definitions.build_prepare_command(payload)
    assert a['operation_id'] != b['operation_id']


def test_current_server_source_unconnected_builds_nothing():
    """오늘 서버(commerce_fulfillment_read.read_current): expected_order_basis=None, 모든 action allowed=False."""
    today = dict(state='confirmed', order_no='x', order_state='결제완료', order_revision=3, expected_order_basis=None,
                 actions={a: dict(allowed=False, reason='source_unconnected') for a in ('prepare_shipment', 'handoff')})
    cmd, why = definitions.build_prepare_command(today)
    assert cmd is None and why == 'source_unconnected'
    assert definitions._expect_actionable(200, today) is not None   # 열렸다고 초록이 아니다


def test_missing_server_values_build_nothing():
    req = _fixture_request()
    for broken in (_server_payload(req) | dict(expected_order_basis=None),
                   _server_payload(req) | dict(order_revision='3'),
                   _server_payload(req, lines=[]),
                   _server_payload(req, expected_policy_basis=None)):
        cmd, why = definitions.build_prepare_command(broken)
        assert cmd is None and why


def test_lookup_compares_request_basis_but_not_checked_at():
    req = _fixture_request()
    cmd, _ = definitions.build_prepare_command(_server_payload(req))
    ctx = dict(order_no=req['order_no'], fulfillment_command=cmd, request_basis='a' * 64)
    ok = dict(state='confirmed', order_no=req['order_no'], operation_id=cmd['operation_id'],
              action='prepare_shipment', request_basis='a' * 64, checked_at=1)
    assert definitions._confirmed_original(ok, ctx) is None
    assert definitions._confirmed_original(ok | dict(checked_at=999), ctx) is None
    assert definitions._confirmed_original(ok | dict(request_basis='b' * 64), ctx)
    assert definitions._confirmed_original(ok | dict(state='pending'), ctx)
    assert definitions._confirmed_original(ok | dict(operation_id=str(uuid.uuid4())), ctx)
