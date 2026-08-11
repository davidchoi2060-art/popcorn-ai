# -*- coding: utf-8 -*-
"""표준의 빈 곳 3건 보강 + 한 사양이 여러 쌍에 걸치게 한다 (2026-08-11)

■ 조감도(`docs/design/build-map.html`)를 그리다 드러난 것

  1. **케이스에 GPU 최대 높이가 없다.** GPU 쪽 `height_mm` 은 있는데 받는 쪽이 없어
     B2 판정이 반쪽이었다. 요즘 3팬 카드는 높이가 커서 사이드패널에 닿는다.
  2. **라디에이터 두께가 없다.** B4 가 열 수만 본다. 실무에서는 두께(27mm vs 45mm)가
     상단 장착 시 메인보드·램과 간섭한다.
  3. **한 사양이 여러 쌍에 걸치는 것을 표현하지 못했다.**
       `height_mm` 은 RAM(D3 쿨러 간섭)과 GPU(B2 케이스 여유) 양쪽에 쓰이는데
       `compat_pair` 가 하나뿐이라 D3 로만 적혀 있었다.
       `length_mm` 도 GPU(B1)와 POWER(B5) 양쪽인데 B1 로만 적혀 있었다.
     → `compat_pair` (단수) 를 `compat_pairs` (목록) 으로 바꾼다.

■ C2(총 전력 합산)는 **사양이 아니라 규칙 상수**로 둔다
  RAM·SSD·보드·팬 몫까지 부품마다 소비전력을 받으면 채울 수 없는 항목이 또 는다.
  사용자 방침(2026-08-11): *"없는 스펙을 전부 맞추려고 하지 마라. 일부는 사람에게
  남겨두면 된다."* 나머지 몫은 엔진이 상수로 잡고 근거에 그렇게 밝힌다.

■ 사람이 항목을 직접 늘릴 수 있게 한다
  `is_custom` · `created_by` 를 둔다. 표준이 부족하면 **화면에서 항목을 추가**하고,
  그 항목이 우리가 만든 것인지 사람이 넣은 것인지 구분해 둔다.
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

# (키, 라벨, 형, 단위, 적용대상, 쌍목록, 막는가, 원문단서, 메모)
NEW = [
    ("gpu_max_height_mm", "GPU 최대 높이", "INT", "mm", ["CASE"], ["B2"], True, None,
     "GPU 쪽 height_mm 의 짝. 없어서 B2 판정이 반쪽이었다 — 3팬 카드는 사이드패널에 닿는다"),
    ("radiator_thickness_mm", "라디에이터 두께", "INT", "mm", ["COOLER_CPU_AIO"], ["B4"], True, None,
     "열 수만으로는 부족하다. 27mm 와 45mm 는 상단 장착 시 보드·램 간섭이 다르다"),
    ("radiator_max_thickness_mm", "라디에이터 최대 두께", "INT", "mm", ["CASE"], ["B4"], True, None,
     "위 항목의 짝"),
]

# 여러 쌍에 걸치는 사양 — 조감도가 드러낸 분류 오류
MULTI = {
    "height_mm": ["B2", "D3"],   # GPU=케이스 여유 · RAM=쿨러 간섭
    "length_mm": ["B1", "B5"],   # GPU=케이스 길이 · POWER=케이스 파워 길이
}


def upgrade():
    conn = op.get_bind()

    # ① compat_pair(단수) → compat_pairs(목록)
    conn.execute(sa.text(
        "ALTER TABLE std.spec_defs ADD COLUMN IF NOT EXISTS compat_pairs JSONB"
        " NOT NULL DEFAULT '[]'::jsonb"))
    conn.execute(sa.text(
        "UPDATE std.spec_defs SET compat_pairs = "
        " CASE WHEN compat_pair IS NULL THEN '[]'::jsonb"
        "      ELSE jsonb_build_array(compat_pair) END"))
    for key, pairs in MULTI.items():
        conn.execute(sa.text(
            "UPDATE std.spec_defs SET compat_pairs = CAST(:p AS JSONB) WHERE field_key = :k"),
            {"k": key, "p": json.dumps(pairs)})
    # 단수 컬럼은 **지우지 않는다** — 읽는 코드가 남아 있을 수 있고, 지우면 되돌릴 수 없다.
    # 대신 주석으로 정본을 가리킨다.
    conn.execute(sa.text(
        "COMMENT ON COLUMN std.spec_defs.compat_pair IS "
        "'폐기 예정 — 정본은 compat_pairs. 한 사양이 여러 쌍에 걸칠 수 있다(0038)'"))
    conn.execute(sa.text(
        "COMMENT ON COLUMN std.spec_defs.compat_pairs IS "
        "'이 사양이 쓰이는 호환성 관계 번호 목록(A1..F5). 빈 목록이면 정보 항목이다'"))

    # ② 사람이 항목을 늘릴 수 있게
    conn.execute(sa.text(
        "ALTER TABLE std.spec_defs ADD COLUMN IF NOT EXISTS is_custom BOOLEAN"
        " NOT NULL DEFAULT false"))
    conn.execute(sa.text(
        "ALTER TABLE std.spec_defs ADD COLUMN IF NOT EXISTS created_by INTEGER"))
    conn.execute(sa.text(
        "COMMENT ON COLUMN std.spec_defs.is_custom IS "
        "'화면에서 사람이 추가한 항목. 표준이 부족하면 늘릴 수 있어야 한다(0038)'"))

    # ③ 빈 곳 3건
    base = conn.execute(sa.text(
        "SELECT COALESCE(MAX(sort_order), 0) FROM std.spec_defs")).scalar() or 0
    for i, (key, label, dt, unit, parts, pairs, blocking, hint, note) in enumerate(NEW, start=1):
        conn.execute(sa.text(
            "INSERT INTO std.spec_defs"
            " (field_key, label, data_type, unit, part_types, required_for,"
            "  compat_pair, compat_pairs, is_blocking, fill_hint, note, sort_order)"
            " VALUES (:k, :l, :t, :u, CAST(:p AS JSONB), CAST('[]' AS JSONB),"
            "         :c1, CAST(:cs AS JSONB), :b, :h, :n, :s)"
            " ON CONFLICT (field_key) DO NOTHING"),
            {"k": key, "l": label, "t": dt, "u": unit,
             "p": json.dumps(parts, ensure_ascii=False), "c1": pairs[0],
             "cs": json.dumps(pairs), "b": blocking, "h": hint, "n": note,
             "s": base + i * 10})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM std.spec_defs WHERE field_key = ANY(:ks)"),
                 {"ks": [n[0] for n in NEW]})
    # compat_pairs · is_custom · created_by 는 남긴다 — 값이 함께 사라진다.
