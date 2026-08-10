# -*- coding: utf-8 -*-
"""조립 호환성 사양 표준 — 코어 8부품 (2026-08-10)

■ 무엇을 하나
  `docs/design/part-spec-standard-2026-08-10.md` 가 정한 **(가) 호환 판정용 표준** 중
  **코어 8부품 몫**을 스키마에 올린다(사용자 결정: 팬·확장카드·ODD 는 다음 단계).

    · `product_specs` 컬럼 **26개** 신설
    · `spec_field_defs` 메타 **26행** 추가
    · 기존 3행의 **적용 대상(part_types) 확장** — 26 + 6배정 = 문서의 32개 배정
    · 추천 뷰(`v_recommendation_candidates`)에 26개 컬럼 append

■ ⚠ `required_for` 는 전부 **빈 목록**이다 — 이게 이 마이그레이션의 핵심 안전장치다
  호환 사양은 NULL 불통과이고(`recommend._cmp`), 필수 사양이 비면 4중 게이트의
  `need_review` 로 빠진다. **26개를 필수로 올리면 채워진 상품이 0건이므로 추천 후보가
  0이 되고 모든 견적이 불성립한다.**

      순서:  ① 컬럼·메타만 추가(여기) → ② 채운다 → ③ **항목별로 따로** 필수 승격

  ③은 "이 항목을 필수로 올리면 후보가 몇 건 빠지는가"를 먼저 보여주고 확인받는다
  (분류 변경이 `preview` 로 영향을 먼저 보여주는 것과 같은 규칙).

■ 왜 컬럼을 재사용하는가 (26개인데 배정은 32개)
  같은 사실은 한 컬럼에 담는다 — 두 벌을 만들면 갈라진다.
    · `height_mm`        RAM(모듈 높이) + GPU(카드 높이) — 둘 다 "이 부품의 높이"
    · `eps_connectors`   MB(필요 개수) + POWER(제공 개수) — 규칙이 제공 ≥ 필요로 비교
    · `length_mm`        GPU(카드 길이) + POWER(파워 길이) — 케이스가 각각 수용 판정
    · `pcie_gen`         GPU + SSD — 세대는 하위호환이라 **막는 규칙이 아니라 성능 경고**
    · `size_inch`        MONITOR + HDD(3.5"/2.5") — 케이스 베이 판정

■ `in_ingest=False` 인 이유
  이 값들은 적재 원문(`pd_spec` 텍스트)에 없다. 저쪽 시스템이 **팔기 위한** 정보를
  모았기 때문이고 우리는 **조립을 보증하기 위한** 정보를 모으는 것이라 목적이 다르다.
  사람 입력·외부 제안·저쪽 옵션 적재로 채운다. 파서가 못 찾을 것을 찾게 하지 않는다.

■ downgrade 는 컬럼을 지우지 않는다
  값이 함께 사라지고 되돌릴 수 없다(ADM-PRD-050 과 같은 정책). 메타만 되돌린다.
"""
import re

from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

VIEW = "v_recommendation_candidates"

# (컬럼, 자료형, 라벨, 단위, 적용 대상, 메모)
FIELDS = [
    # ── CPU ────────────────────────────────────────────────────────────────
    ("mem_type_support", "JSONB",   "지원 메모리 규격", None, ["CPU"],
     "A4 보강 — AM5 는 DDR5 만 받는다. 보드뿐 아니라 CPU 도 메모리 컨트롤러를 갖는다"),
    ("igpu_yn",          "BOOLEAN", "내장그래픽 유무", None, ["CPU"],
     "GPU 슬롯 생략 가능 판정. 지금은 내장그래픽 CPU 에도 GPU 를 반드시 붙인다"),
    ("cpu_generation",   "VARCHAR", "CPU 세대",       None, ["CPU"],
     "A2 칩셋 지원 판정용(랩터레이크R·Zen5). 소켓만으로는 세대를 알 수 없다"),
    # ── 메인보드 — 호환성의 허브라 항목이 가장 많다 ────────────────────────
    ("supported_cpu_gens",  "JSONB",   "지원 CPU 세대",   None, ["MB"],
     "A2 — 같은 소켓이어도 칩셋이 그 세대를 지원하지 않을 수 있다"),
    ("bios_min_version",    "JSONB",   "세대별 최소 BIOS", None, ["MB"],
     "A3 — 소켓·칩셋이 맞아도 BIOS 가 낮으면 부팅하지 않는다. 실무에서 가장 흔한 사고"),
    ("mem_slots",           "INTEGER", "메모리 슬롯 수",  "개", ["MB"], "A5"),
    ("mem_max_gb",          "INTEGER", "최대 메모리 용량", "GB", ["MB"], "A5"),
    ("mem_max_clock_mhz",   "INTEGER", "지원 최대 클럭",  "MHz", ["MB"],
     "A6 — 초과하면 다운클럭된다(조립은 되지만 산 성능이 안 나온다)"),
    ("pcie_x16_gen",        "INTEGER", "x16 슬롯 세대",   None, ["MB"], "A7"),
    ("m2_slots",            "INTEGER", "M.2 슬롯 수",    "개", ["MB"],
     "A8 — SSD 는 견적 슬롯인데 지금 호환 규칙이 0개다. NVMe 를 M.2 없는 보드와 묶어도 통과한다"),
    ("m2_form_factors",     "JSONB",   "M.2 지원 규격",   None, ["MB"], "A8 (2280·22110)"),
    ("sata_ports",          "INTEGER", "SATA 포트 수",   "개", ["MB"], "A8"),
    ("m2_sata_shared",      "VARCHAR", "M.2/SATA 레인 공유", None, ["MB"],
     "A8 — M.2 를 쓰면 특정 SATA 포트가 죽는 보드가 흔하다. 규칙이 아니라 경고 문구로 쓴다"),
    ("eps_connectors",      "INTEGER", "EPS 12V 커넥터", "개", ["MB", "POWER"],
     "C4 — MB 는 필요 개수, POWER 는 제공 개수. 규칙은 제공 >= 필요"),
    # ── 메모리 ─────────────────────────────────────────────────────────────
    ("module_count", "INTEGER", "모듈 개수", "개", ["RAM"],
     "A5 — 4모듈 세트를 2슬롯 보드에 꽂을 수 없다"),
    ("height_mm",    "INTEGER", "높이",     "mm", ["RAM", "GPU"],
     "D3 쿨러 간섭(RAM) · B2 케이스 여유(GPU). 둘 다 '이 부품의 높이'라 한 컬럼에 담는다"),
    # ── 그래픽카드 ─────────────────────────────────────────────────────────
    ("thickness_slots", "NUMERIC", "두께(슬롯)", "슬롯", ["GPU"],
     "B2 — 3슬롯 두께 카드는 아래 PCIe 슬롯을 물리적으로 막는다"),
    ("aux_power_req",   "JSONB",   "요구 보조전원", None, ["GPU"],
     "C3 — 8pin x N 또는 12V-2x6. RTX 50 계열은 12V-2x6 이다"),
    # ── 파워 ───────────────────────────────────────────────────────────────
    ("aux_power_provided", "JSONB",   "제공 보조전원",   None, ["POWER"], "C3 의 짝"),
    ("sata_connectors",    "INTEGER", "SATA 전원 커넥터", "개", ["POWER"], "저장장치 개수 대응"),
    # ── 케이스 ─────────────────────────────────────────────────────────────
    ("gpu_max_slots",        "NUMERIC", "GPU 최대 두께",  "슬롯", ["CASE"], "B2"),
    ("psu_form_factor_list", "JSONB",   "수용 파워 규격",  None, ["CASE"],
     "B5 — SFX 케이스에 ATX 파워는 물리적으로 안 들어간다"),
    ("psu_max_mm",           "INTEGER", "파워 최대 길이",  "mm", ["CASE"], "B5"),
    ("bay_35_count",         "INTEGER", "3.5\" 베이 수",  "개", ["CASE"], "B6"),
    ("bay_25_count",         "INTEGER", "2.5\" 베이 수",  "개", ["CASE"], "B6"),
    # ── CPU 쿨러 ───────────────────────────────────────────────────────────
    ("ram_clearance_mm", "INTEGER", "램 방향 여유", "mm", ["COOLER_CPU_AIR"],
     "D3 — PCPartPicker 도 못 한다고 밝히는 항목이다. 잡으면 차별점이 된다"),
]

# 기존 항목의 적용 대상 확장 — 같은 사실을 새 컬럼으로 또 만들지 않는다
EXTEND = [
    ("length_mm", ["POWER"], "B5 파워 길이 — GPU 카드 길이와 같은 '길이' 축"),
    ("pcie_gen",  ["SSD"],   "A8 성능 경고 — 세대는 하위호환이라 막지 않고 알린다"),
    ("size_inch", ["HDD"],   "B6 케이스 베이 판정(3.5\"/2.5\")"),
]

TYPES = {"INTEGER": "INTEGER", "NUMERIC": "NUMERIC(10,2)", "VARCHAR": "VARCHAR(80)",
         "BOOLEAN": "BOOLEAN", "JSONB": "JSONB"}


def _append_to_view(conn, keys):
    """추천 뷰의 SELECT 목록 **끝에** 컬럼을 붙인다.

    `CREATE OR REPLACE VIEW` 는 끝에 추가만 허용한다 — 순서를 바꾸거나 빼면
    "cannot drop columns from view" 로 거부한다. 뷰에 안 넣으면 화면엔 값이 있는데
    **엔진은 그 값을 못 본다**(슬라이스 46 전례).
    """
    ddl = conn.execute(sa.text("SELECT pg_get_viewdef(:v, true)"), {"v": VIEW}).scalar()
    if not ddl:
        return 0
    m = re.search(r"\n\s*FROM\s", ddl)
    if not m:
        return 0
    head, tail = ddl[:m.start()], ddl[m.start():]
    add = "".join(",\n    ps." + k for k in keys)
    conn.execute(sa.text("CREATE OR REPLACE VIEW " + VIEW + " AS " + head + add + tail))
    return len(keys)


def upgrade():
    conn = op.get_bind()

    # ① 컬럼 — 전부 NULL 허용. 값이 없다는 사실 자체가 정보다(게이트가 읽는다)
    for key, dt, *_ in FIELDS:
        conn.execute(sa.text(
            f"ALTER TABLE product_specs ADD COLUMN IF NOT EXISTS {key} {TYPES[dt]}"))

    # ② 메타 — required_for 는 **빈 목록**이다(위 경고 참조)
    base = conn.execute(sa.text(
        "SELECT COALESCE(MAX(sort_order), 0) FROM spec_field_defs")).scalar() or 0
    for i, (key, dt, label, unit, parts, note) in enumerate(FIELDS, start=1):
        conn.execute(sa.text(
            "INSERT INTO spec_field_defs"
            " (field_key, label, data_type, unit, part_types, required_for,"
            "  is_engine, is_custom, in_ingest, sort_order, note)"
            " VALUES (:k, :l, :t, :u, CAST(:p AS JSONB), CAST('[]' AS JSONB),"
            "         true, false, false, :s, :n)"
            " ON CONFLICT (field_key) DO NOTHING"),
            {"k": key, "l": label, "t": dt, "u": unit, "p": _json(parts),
             "s": base + i * 10, "n": note})

    # ③ 기존 항목의 적용 대상 확장
    for key, add, note in EXTEND:
        conn.execute(sa.text(
            "UPDATE spec_field_defs"
            " SET part_types = part_types || CAST(:a AS JSONB),"
            "     note = COALESCE(note, '') || :n"
            " WHERE field_key = :k"
            "   AND NOT (part_types @> CAST(:a AS JSONB))"),
            {"k": key, "a": _json(add), "n": " / " + note})

    # ④ 추천 뷰 — 엔진이 읽는 자리
    _append_to_view(conn, [k for k, *_ in FIELDS])


def downgrade():
    """**컬럼은 지우지 않는다.** 값이 함께 사라지고 되돌릴 수 없다(ADM-PRD-050 과 같은 정책).

    메타와 적용 대상 확장만 되돌린다. 뷰의 컬럼도 남는다 —
    `CREATE OR REPLACE VIEW` 로는 뺄 수 없고 `DROP VIEW` 는 의존을 끊는다.
    """
    conn = op.get_bind()
    for key, add, note in EXTEND:
        conn.execute(sa.text(
            "UPDATE spec_field_defs SET part_types = part_types - :a0"
            " WHERE field_key = :k"), {"k": key, "a0": add[0]})
    conn.execute(sa.text(
        "DELETE FROM spec_field_defs WHERE field_key = ANY(:ks)"),
        {"ks": [k for k, *_ in FIELDS]})


def _json(v):
    import json
    return json.dumps(v, ensure_ascii=False)
