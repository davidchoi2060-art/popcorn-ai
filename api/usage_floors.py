"""용도별 부품 하한 로더 — `usage_floors` 테이블이 단일 원천(슬라이스 58).

화면은 오래전부터 용도 칩에 "저사양 GPU 제외(프레임 미달)" · "램 32GB↑ 우선"이라고
적어 왔는데 **서버는 용도로 아무것도 하지 않았다.** 그래서 "롤·배그 하려고요"에
GT710 2GB가 나왔다 — 저소음 + 최저가를 정확히 만족한 결과다.

여기서 하는 일은 하나다: 용도 문구 → 하한 규칙 목록. 필터링은 부르는 쪽이 한다
(후보 카운터와 견적 엔진이 같은 규칙을 써야 화면과 결과가 어긋나지 않는다).

`spec_fields`와 같은 캐시 방식이다 — 요청마다 읽지 않고, 관리자가 고치면 `reload()`.
"""
from sqlalchemy import text

from .db import engine

_CACHE: list | None = None


def _rows() -> list:
    global _CACHE
    if _CACHE is None:
        try:
            with engine.connect() as conn:
                _CACHE = [dict(r) for r in conn.execute(text(
                    "SELECT usage_key, usage_label, match_terms, slot, field, op, value,"
                    " label, detail_fmt FROM usage_floors WHERE active"
                    " ORDER BY sort_order, floor_id")).mappings().all()]
        except Exception as e:      # DB를 못 읽으면 하한 없이 동작한다(견적이 죽지 않게)
            print(f"[usage_floors] load failed: {e}")
            _CACHE = []
    return _CACHE


def reload() -> int:
    global _CACHE
    _CACHE = None
    return len(_rows())


def match(value: str) -> list:
    """용도 문구 → 적용할 하한 규칙들. **먼저 맞는 usage_key 하나만** 쓴다.

    '고사양 게임'은 '게임'도 포함하므로 둘 다 적용하면 하한이 뒤섞인다.
    시드가 좁은 것(고사양 게임)부터 정렬돼 있어 앞선 것이 이긴다.
    """
    if not value:
        return []
    rows = _rows()
    hit = next((r["usage_key"] for r in rows
                if any(t in value for t in (r["match_terms"] or []))), None)
    return [r for r in rows if r["usage_key"] == hit] if hit else []


def slot_floors(value: str) -> dict:
    """용도 문구 → {슬롯: [(필드, 연산, 값, 라벨, 상세형식), ...]}"""
    out: dict = {}
    for r in match(value):
        out.setdefault(r["slot"], []).append(
            (r["field"], r["op"], r["value"], r["label"], r["detail_fmt"]))
    return out


def passes(part: dict, floors: list) -> bool:
    """부품 하나가 그 슬롯의 하한을 전부 만족하는가.

    **값을 모르면 불통과**다(호환 규칙의 NULL 원칙과 같다) — 용량을 모르는 SSD를
    '게임에 충분하다'고 말할 수는 없다.
    """
    for field, op, val, _label, _fmt in floors:
        v = part.get(field)
        if v is None:
            return False
        if op == "gte" and not v >= val:
            return False
        if op == "lte" and not v <= val:
            return False
    return True


def label_of(value: str) -> str | None:
    rows = match(value)
    return rows[0]["usage_label"] if rows else None


def summary(value: str) -> list:
    """화면·근거용 한 줄 목록 — 서버가 실제로 건 하한만 말한다."""
    return [{"slot": r["slot"], "label": r["label"], "field": r["field"],
             "op": r["op"], "value": r["value"]} for r in match(value)]
