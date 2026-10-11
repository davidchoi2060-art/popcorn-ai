"""결제·정산 기록장(ADM-PAY-020) — DB 없이 지키는 경계 (2026-10-11 사장님 「기록장」 · 「표시만」).

DB 흐름(기록 → 중복 409 → 정정 → 철회 → 월 점검 → 금융 표 불변)은 PR 본문에 적은 로컬 Postgres
검증으로 확인했다. 여기서는 CI 의 빈 DB 에서도 깨지면 안 되는 약속을 고정한다.
"""
import ast
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api" / "admin_payment_records.py"
TPL = ROOT / "templates" / "admin" / "payment_records.html.j2"
MIG = ROOT / "db" / "migrations" / "versions" / "0155_payment_records.py"
OWN_TABLES = {"payment_confirmation_records", "payment_confirmation_allocations",
              "payment_month_reviews"}


def _sql_strings(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # 문자열 조각마다 따로 본다 — 붙이면 「FOR UPDATE」 뒤 조각의 첫 낱말이 표 이름처럼 잡힌다.
    return "\n".join(n.value for n in ast.walk(tree)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str))


def test_writes_only_its_own_tables():
    """기록 저장이 주문·결제·환불·재고·commerce 상태를 바꾸지 않는다 — 쓰기 대상은 세 표뿐."""
    sql = _sql_strings(API)
    targets = set(re.findall(r"\b(?:INSERT\s+INTO|(?<!FOR )UPDATE|DELETE\s+FROM)[ \t]+([a-z_]+)", sql))
    assert targets, "쓰기 문장을 하나도 못 찾았다 — 검사가 아무것도 안 보고 있다"
    assert targets <= OWN_TABLES, targets - OWN_TABLES
    assert not re.search(r"\b(TRUNCATE|DROP|ALTER)\b", sql)


def test_no_fallback_operator():
    """작성자는 실제 로그인 운영자만. `current_operator_id()` 의 대체값 1 을 쓰지 않는다."""
    tree = ast.parse(API.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "current_operator_id" not in names


def test_writer_requires_real_session(monkeypatch):
    from api import admin_payment_records as M
    monkeypatch.setattr(M, "current_operator", lambda: None)
    with pytest.raises(HTTPException) as e:
        M._writer()
    assert e.value.status_code == 401
    monkeypatch.setattr(M, "current_operator", lambda: {"operator_id": 7, "role": "operator"})
    assert M._writer() == 7


def _body(**k):
    from api.admin_payment_records import RecordBody
    d = dict(kind="deposit", source="bank", institution=" 국민은행 ", external_ref="  ",
             amount=1000, occurred_on=date(2026, 10, 4), confirmed_on=date(2026, 10, 5),
             allocations=[{"order_no": "ORD-1", "amount": 1000}])
    d.update(k)
    return RecordBody(**d)


def test_clean_trims_and_blank_ref_becomes_none():
    from api.admin_payment_records import _clean
    row = _clean(_body())
    assert row["institution"] == "국민은행"
    assert row["external_ref"] is None


@pytest.mark.parametrize("kw", [
    {"institution": "  "},
    {"amount": 0},
    {"occurred_on": date(2026, 10, 6)},                      # 확인일이 거래일보다 앞선다
    {"allocations": [{"order_no": "ORD-1", "amount": 1}, {"order_no": "ORD-1", "amount": 2}]},
    {"allocations": [{"order_no": "ORD-1", "amount": 0}]},
])
def test_clean_rejects(kw):
    from api.admin_payment_records import _clean
    with pytest.raises(HTTPException) as e:
        _clean(_body(**kw))
    assert e.value.status_code == 422


def test_no_ref_only_warns():
    from api.admin_payment_records import NO_REF_WARNING, _check_duplicate
    assert _check_duplicate(object(), "국민은행", None, None) == [NO_REF_WARNING]


def test_month_parsing():
    from api.admin_payment_records import _month, _next_month
    assert _month("2026-10") == date(2026, 10, 1)
    assert _next_month(date(2026, 12, 1)) == date(2027, 1, 1)
    with pytest.raises(HTTPException):
        _month("10월")


def test_migration_shape():
    src = MIG.read_text(encoding="utf-8")
    assert "revision = '0155'" in src and "down_revision = '0154'" in src
    # 한 행은 한 번만 이어받는다 — 동시 정정을 DB 가 막는다.
    assert re.search(r"UNIQUE INDEX \w+\s+ON payment_confirmation_records\(supersedes_id\)", src)
    # 월 점검은 표시만 — 잠금 열이 없다.
    assert "locked" not in src.lower()
    for t in OWN_TABLES:
        assert f"CREATE TABLE {t}" in src


def test_permissions_follow_shared_gate():
    from api.auth import required_role
    assert required_role("GET", "/api/admin/payment-records") == "viewer"
    assert required_role("POST", "/api/admin/payment-records") == "operator"
    assert required_role("POST", "/api/admin/payment-records/3/withdraw") == "operator"


def test_screen_is_reachable_and_returns_to_group():
    from api.admin_page_intro import back_for, entries_for, group_crumb
    nav = (ROOT / "api" / "admin_nav.py").read_text(encoding="utf-8")
    assert "'/admin2/payment-records')" in nav
    assert back_for("/admin2/payment-records") == {"href": "/admin2/commerce-orders",
                                                   "label": "주문 운영으로 돌아가기"}
    assert group_crumb("/admin2/payment-records")["label"] == "주문 운영"
    assert {"label": "결제·정산 기록", "href": "/admin2/payment-records"} in entries_for("/admin2/commerce-orders")


def test_screen_copy_does_not_claim_settlement():
    """저장은 기록일 뿐이다. 거래 확정처럼 읽히는 말을 쓰지 않는다(코덱스 1813 문구 기준)."""
    html = TPL.read_text(encoding="utf-8")
    body = html.split("{% block content %}", 1)[1]
    for banned in ("입금 완료", "정산 완료", "월 마감 완료", "잠김", "작성 불가", "마감 확정"):
        assert banned not in body, banned
    for needed in ("실제 거래 상태는 해당 기관의 기록으로 확인해 주세요",
                   "옛 계산 기준 참고 금액 · 실제 은행·PG 금액 아님",
                   "미해결 차이: 거래 금액과 주문별 배분 합계가 다릅니다.",
                   "이 처리는 기록의 효력만 거두며 실제 거래를 취소하지 않습니다.",
                   "점검 이후 기록이 바뀌었습니다. 다시 확인해 주세요.",
                   'data-screen-id="ADM-PAY-020"'):
        assert needed in body, needed


def test_review_counts_corrections_in_original_month_too():
    """9월 점검 뒤 거래일을 10월로 옮긴 정정이 9월 「점검 뒤 바뀜」에서 빠지지 않는다(코덱스 #144 검수).
    로컬 Postgres 에서 옛 쿼리는 9월 0건, 새 쿼리는 9월·10월 각 1건으로 확인했다."""
    sql = _sql_strings(API)
    assert "LEFT JOIN payment_confirmation_records prev ON prev.record_id = r.supersedes_id" in sql
    assert re.search(r"r\.action <> 'create' AND prev\.occurred_on >= :lo AND prev\.occurred_on < :hi", sql)
