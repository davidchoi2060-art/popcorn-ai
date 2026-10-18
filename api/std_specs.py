"""엔진이 읽는 사양 표준(`std.part_specs`) 값 — 케이스가 받는 파워 규격.

조립 보증 표준 항목은 `std` 스키마에만 둔다(0036 · 회귀 [43] 「신설 표준 항목이 public 에 새지 않았다」).
그래서 규칙 `case_psu_form`(0160)이 읽는 `psu_form_factor_list` 는 `product_specs` 컬럼이 아니라 여기서
부품 행에 붙인다. 값이 없으면 키를 None 으로 둔다 — 규칙이 `skip_any` 라 판정하지 않는다.
"""
from sqlalchemy import text

STD_FIELDS = ('psu_form_factor_list',)
SQL = text("""SELECT product_code, field_key, value_json FROM std.part_specs
               WHERE field_key = ANY(:f) AND product_code = ANY(:c) AND value_json IS NOT NULL""")


def attach(conn, rows):
    """rows(dict 목록, product_code 키)에 표준 값을 붙인다. std 스키마가 없으면 None 으로만 채운다."""
    rows = [r for r in rows if r is not None]
    for r in rows:
        for f in STD_FIELDS:
            r.setdefault(f, None)
    codes = sorted({int(r['product_code']) for r in rows if r.get('product_code') is not None})
    if not codes:
        return rows
    # 표준 스키마가 없는 DB(빈 DB 관통 등)에서도 견적은 돈다 -- 실패한 조회로 트랜잭션을 깨지 않게 먼저 본다.
    if not conn.execute(text("SELECT to_regclass('std.part_specs') IS NOT NULL")).scalar():
        return rows
    found = conn.execute(SQL, dict(f=list(STD_FIELDS), c=codes)).all()
    by = {}
    for code, field, value in found:
        if isinstance(value, list) and value:
            by[(code, field)] = value
    for r in rows:
        for f in STD_FIELDS:
            if r.get(f) is None:
                r[f] = by.get((r.get('product_code'), f))
    return rows
