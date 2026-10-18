"""파워 기준 보기(2026-10-18 관리자 정리 기획 A07 · 3묶음) — 관리자 데이터 API, 읽기 전용.

조립 호환 규칙 화면의 「파워 기준」 상자가 읽는다. 기준이 셋이고 서로 다른 축이다:
  · 조립 판정   compat_rules 의 rule_key='power' 행 — 파워 정격 >= 그래픽카드 소비전력 + ref_offset(DB 정본)
  · 코드 기본값 power_rule.SYSTEM_POWER_OVERHEAD_W — 규칙 값을 못 읽을 때만 쓴다
  · 고객 안내   power_rule.PSU_ADVICE_MARGIN_W — 그래픽카드 «권장 파워 + 여유»(상담 답 · 상품 상세)

`/api/admin/engine-rules` 는 가격 정책 보호 검사가 파일 전체를 고정하고 있어 손대지 않고, 같은
compat_rules 행을 여기서 따로 읽는다. 값을 바꾸는 경로는 없다. 규칙 행이 없으면 없다고 답한다
(기본값으로 메우지 않는다).
"""
from fastapi import APIRouter
from sqlalchemy import text

from .db import engine
from .power_rule import PSU_ADVICE_MARGIN_W, SYSTEM_POWER_OVERHEAD_W

router = APIRouter(prefix="/api/admin", tags=["admin-power-basis"])


@router.get("/power-basis")
def power_basis():
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT ref_offset, active, blocking, null_ref_mode FROM compat_rules"
            " WHERE rule_key = 'power' ORDER BY rule_id LIMIT 1")).mappings().first()
    rule = None if r is None else {
        "ref_offset": r["ref_offset"], "active": bool(r["active"]),
        "blocking": bool(r["blocking"]), "null_ref_mode": r["null_ref_mode"]}
    return {
        "rule": rule,
        "fallback_offset_w": SYSTEM_POWER_OVERHEAD_W,
        "advice_margin_w": PSU_ADVICE_MARGIN_W,
        "note": "조립 판정 값은 이 서버가 연결된 DB의 규칙 값이며 운영 서버의 값을 확인한 것이 아닙니다.",
    }
