"""사양 필드 정의 — 단일 원천은 `spec_field_defs` 테이블 (슬라이스 56).

필드 목록이 코드 상수 다섯 곳에 흩어져 있었다(적재·대안·후보 로드·검수 승인·필수 판정).
컬럼을 하나 늘리면 그 다섯과 뷰 두 개를 사람이 전부 따라가야 했고, 하나만 빠지면
NULL 불통과로 견적이 **조용히** 0이 됐다(슬라이스 46).

이제 코드가 이 모듈을 통해 DB를 읽는다. 필드를 추가하면 적재·검수·판정이 함께 따라온다.
따라오지 **못하는** 것은 둘뿐이고, 그래서 필드 추가 API가 그 둘을 직접 처리한다:
  · `product_specs` 실제 컬럼 (ALTER TABLE)
  · 추천 뷰 두 개 (컬럼을 명시 나열하므로 재생성)

캐시: 매 요청 조회는 낭비이므로 프로세스에 담아 두고, 필드가 추가되면 `reload()`가 비운다.
"""
import threading

from sqlalchemy import text

from .db import engine

# 핵심 부품 — 적재·추천이 다루는 종류. 주변기기 전용 필드는 적재 대상이 아니다.
CORE_TYPES = {"CPU", "MB", "RAM", "GPU", "SSD", "HDD", "POWER", "CASE",
              "COOLER_CPU_AIR", "COOLER_CPU_AIO"}

_lock = threading.Lock()
_cache: list | None = None


def _rows() -> list:
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        with engine.connect() as conn:
            rs = conn.execute(text(
                "SELECT field_key, label, data_type, unit, part_types, required_for,"
                " is_engine, is_custom, in_ingest, sort_order, note"
                " FROM spec_field_defs ORDER BY sort_order, field_key")).mappings().all()
        _cache = [dict(r) for r in rs]
        return _cache


def reload() -> None:
    """필드가 추가·변경된 뒤 호출 — 다음 조회가 DB를 다시 읽는다."""
    global _cache
    with _lock:
        _cache = None


def all_fields() -> list:
    return list(_rows())


def by_key(key: str) -> dict | None:
    for r in _rows():
        if r["field_key"] == key:
            return r
    return None


def spec_cols() -> list:
    """적재가 product_specs에 넣는 컬럼 — `in_ingest` 플래그가 단일 원천.

    part_types로 유도하지 않는다. 실제 목록이 불규칙해서(모니터는 포함·키보드는 제외,
    socket_list는 포함·form_factor_list는 별도 경로) 추측하면 적재가 조용히 달라진다.
    """
    return [r["field_key"] for r in _rows() if r.get("in_ingest")]


def json_cols() -> set:
    """JSONB 컬럼 — 값이 JSON 문자열이어야 한다."""
    return {r["field_key"] for r in _rows() if r["data_type"] == "JSONB"}


def engine_cols() -> list:
    """추천 뷰가 실어야 하는 컬럼 — 호환 규칙·견적이 읽는 값."""
    return [r["field_key"] for r in _rows() if r["is_engine"]]


def field_cast() -> dict:
    """검수 승인이 쓰는 SQL 캐스트 타입."""
    out = {}
    for r in _rows():
        t = r["data_type"]
        out[r["field_key"]] = "NUMERIC(4,1)" if t == "NUMERIC" else t
    return out


def required_for(part_type: str) -> list:
    """이 부품 종류의 필수 사양 — 게이트 판정이 쓴다."""
    return [r["field_key"] for r in _rows()
            if part_type in (r["required_for"] or [])]


def required_map() -> dict:
    """part_type -> 필수 사양 목록 (기존 REQUIRED_SPEC_FIELDS와 같은 모양)."""
    out: dict[str, list] = {}
    for r in _rows():
        for pt in (r["required_for"] or []):
            out.setdefault(pt, []).append(r["field_key"])
    return out


def fields_for(part_type: str) -> list:
    """이 부품 종류에서 쓰는 필드 전체(필수 여부 포함) — 화면이 폼을 그릴 때 쓴다."""
    out = []
    for r in _rows():
        pts = r["part_types"] or []
        if pts and part_type not in pts:
            continue
        out.append({**r, "required": part_type in (r["required_for"] or [])})
    return out


def rule_readers(conn) -> dict:
    """(부품 종류, 필드) → 그 값을 실제로 읽는 규칙 이름들 (슬라이스 83).

    **필드 이름만 맞춰선 안 된다.** case_board의 ref_field는 메인보드의 form_factor다 —
    이름만 보면 파워·SSD의 form_factor까지 "읽고 있다"고 말하게 되는데, 그 둘은
    실제로 아무도 안 읽는다(근거 없이 검수 대기로 묶고 있다는 뜻이라 정확해야 한다).

    호환 규칙과 용도 하한을 함께 본다. 호환 규칙만 보면 capacity_gb가 '죽은 필드'로
    보이는데, 실제로는 게임용 SSD 500GB 하한 등이 그걸 쓴다.

    관리자 화면 두 곳(조립 호환 규칙 · 사양 항목 정의)이 같은 답을 해야 하므로
    여기 한 곳에 둔다 — 두 번 구현하면 언젠가 서로 다른 말을 한다.
    """
    from .recommend import SLOT_TYPES

    out: dict = {}

    def add(pt, field, name):
        out.setdefault((pt, field), set()).add(name)

    for r in conn.execute(text(
            "SELECT rule_key, slot, field, ref_slot, ref_field, part_types"
            " FROM compat_rules WHERE active")).mappings():
        own = r["part_types"] or list(SLOT_TYPES.get(r["slot"], ()))
        for pt in own:
            add(pt, r["field"], r["rule_key"])
        for pt in SLOT_TYPES.get(r["ref_slot"], ()):
            add(pt, r["ref_field"], r["rule_key"])

    for r in conn.execute(text(
            "SELECT DISTINCT slot, field FROM usage_floors")).mappings():
        for pt in SLOT_TYPES.get(r["slot"], ()):
            add(pt, r["field"], "용도 하한")

    return {k: sorted(v) for k, v in out.items()}
