# -*- coding: utf-8 -*-
"""신규 표준을 **별도 스키마 `std`** 에 짓는다 — 기존 테이블은 건드리지 않는다 (2026-08-10)

■ 왜 0035 를 되돌리나 (사용자 지시)
  0035 는 `product_specs` 에 컬럼 26개를 붙였다. **그건 기존 테이블을 건드린 것이다.**
  사용자 원칙: *"기존 DB 테이블을 건드리지 말고 신규 테이블을 생성해서 admin2 에서
  접근해도 됩니다. … 왜냐면 지금 새로 구축하고 신규 표준을 만드는 과정이기 때문입니다."*

  되돌려도 잃을 값이 없다 — 26개 컬럼은 **전부 비어 있었다**(직접 확인).
  그리고 빈 컬럼 26개를 남겨 두는 것은 우리가 방금 진단한 바로 그 병이다
  (저쪽 메인보드에 붙은 324개 중 대부분이 채울 수 없는 필드였다).

■ 왜 **새 DB** 가 아니라 **새 스키마**인가
  사용자가 "DB 를 신규로 생성해서 old DB 에서 데이터만 추출해도 된다"고 했다.
  **완전히 다른 DB 로 가면 조인이 안 된다** — 견적 엔진은 사양을 **가격·재고와 함께**
  읽어야 하는데(`v_recommendation_candidates`), 가격·재고는 계속 변하는 운영 데이터다.
  그걸 새 DB 로 복제하면 **두 벌이 되어 갈라진다** — 이 리포가 가장 자주 앓은 병을
  DB 단위로 반복하는 것이다.

  **같은 DB 안의 새 스키마**면 셋 다 만족한다:
    · `public` 을 한 줄도 건드리지 않는다
    · 조인이 된다 (`std.part_specs` ⋈ `public.products`)
    · 롤백이 `DROP SCHEMA std CASCADE` 한 줄이고, 백업·PITR 는 인스턴스 하나로 간다

■ 왜 **EAV** 인가 (기존 `product_specs` 는 wide 다)
  ① **값마다 출처를 남겨야 한다.** 파싱한 값과 사람이 넣은 값과 외부 제안을 구분하지
     못하면 "이 사양을 믿어도 되는가"에 답할 수 없다. wide 테이블은 컬럼당 출처를 못 단다.
  ② **항목이 계속 는다.** wide 는 항목마다 ALTER + 마이그레이션이고, 그 마이그레이션
     파일 쓰기가 배포 서버에서 실패한 전례가 있다(슬라이스 81 `cpu_gpu`).
     EAV 는 정의 행 하나를 넣으면 끝이라 그 실패 경로가 아예 없다.
  ③ 67개 항목을 10개 부품이 나눠 쓰므로 wide 면 대부분 NULL 이다.

  엔진이 읽을 때가 되면 **피벗 뷰**를 만든다. 지금은 만들지 않는다 —
  엔진을 건드리지 않는 것이 이 단계의 요점이다.

■ 이 마이그레이션이 하지 않는 것
  · 기존 `public.*` 테이블 변경 (0035 되돌림 제외)
  · 엔진·추천 뷰 연결
  · 데이터 이관 (다음 단계 — `pd_spec` 원문 재파싱)
"""
from alembic import op
import sqlalchemy as sa

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

# 0035 가 붙인 컬럼들 — 전부 비어 있음을 확인하고 되돌린다
COLS_0035 = [
    "mem_type_support", "igpu_yn", "cpu_generation", "supported_cpu_gens",
    "bios_min_version", "mem_slots", "mem_max_gb", "mem_max_clock_mhz",
    "pcie_x16_gen", "m2_slots", "m2_form_factors", "sata_ports", "m2_sata_shared",
    "eps_connectors", "module_count", "height_mm", "thickness_slots",
    "aux_power_req", "aux_power_provided", "sata_connectors", "gpu_max_slots",
    "psu_form_factor_list", "psu_max_mm", "bay_35_count", "bay_25_count",
    "ram_clearance_mm",
]
EXTEND_0035 = [("length_mm", "POWER"), ("pcie_gen", "SSD"), ("size_inch", "HDD")]


def _revert_0035(conn):
    """`product_specs` 를 0035 이전 상태로 되돌린다.

    **값이 있으면 지우지 않는다.** 컬럼 삭제는 값이 함께 사라지고 되돌릴 수 없다 —
    이건 0035 가 방금 만든 빈 컬럼이라서만 허용된다.
    """
    # ① **뷰가 먼저다.** 뷰가 컬럼을 잡고 있어서 순서를 바꾸면
    #    "cannot drop column ... because other objects depend on it" 로 막힌다.
    #    그리고 정의를 **손으로 다시 쓰지 않는다** — 새로 쓰면 컬럼 구성·순서가 달라져
    #    엔진이 조용히 다른 것을 읽는다. 0035 가 끝에 덧붙인 26개만 정확히 걷어낸다.
    #    (`CREATE OR REPLACE` 로는 컬럼을 뺄 수 없어 DROP 후 CREATE 다 —
    #     이 뷰에 의존하는 객체가 없음을 미리 확인했다.)
    import re as _re
    ddl = conn.execute(sa.text(
        "SELECT pg_get_viewdef('v_recommendation_candidates'::regclass, true)")).scalar()
    if ddl:
        cleaned = ddl
        for col in COLS_0035:
            cleaned = _re.sub(r",\s*\n?\s*ps\.%s\b" % _re.escape(col), "", cleaned)
        left = [c for c in COLS_0035 if _re.search(r"\bps\.%s\b" % _re.escape(c), cleaned)]
        if left:
            raise RuntimeError(f"[0036] 뷰에서 못 걷어낸 컬럼: {left} — 손으로 확인하십시오")
        conn.execute(sa.text("DROP VIEW v_recommendation_candidates"))
        conn.execute(sa.text("CREATE VIEW v_recommendation_candidates AS " + cleaned))

    # ② 컬럼 — 값이 있으면 지우지 않는다
    kept = []
    for col in COLS_0035:
        exists = conn.execute(sa.text(
            "SELECT 1 FROM information_schema.columns"
            " WHERE table_name='product_specs' AND column_name=:c"), {"c": col}).first()
        if not exists:
            continue
        n = conn.execute(sa.text(
            f'SELECT COUNT(*) FROM product_specs WHERE "{col}" IS NOT NULL')).scalar()
        if n:
            kept.append((col, n))       # 값이 생겼다면 남긴다 — 사람이 결정할 일이다
            continue
        conn.execute(sa.text(f"ALTER TABLE product_specs DROP COLUMN {col}"))
    if kept:
        print(f"[0036] 값이 있어 남긴 컬럼: {kept} — 손으로 판단하십시오")

    # ③ 메타 되돌림
    conn.execute(sa.text("DELETE FROM spec_field_defs WHERE field_key = ANY(:ks)"),
                 {"ks": COLS_0035})
    for key, added in EXTEND_0035:
        conn.execute(sa.text(
            "UPDATE spec_field_defs SET part_types = part_types - :a"
            " WHERE field_key = :k"), {"k": key, "a": added})


def upgrade():
    conn = op.get_bind()
    _revert_0035(conn)

    # ── 새 표준 스키마 ────────────────────────────────────────────────────
    conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS std"))
    conn.execute(sa.text("COMMENT ON SCHEMA std IS "
                         "'조립 보증 표준(P-08 재구축). public 을 건드리지 않는다.'"))

    # 사양 항목 정의 — 무엇을 알아야 하는가
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS std.spec_defs (
            field_key   VARCHAR(40)  PRIMARY KEY,
            label       VARCHAR(60)  NOT NULL,
            data_type   VARCHAR(10)  NOT NULL,          -- INT NUM TEXT BOOL LIST
            unit        VARCHAR(10),
            part_types  JSONB        NOT NULL DEFAULT '[]'::jsonb,
            required_for JSONB       NOT NULL DEFAULT '[]'::jsonb,
            compat_pair VARCHAR(8),                     -- A1..F5 (호환성 관계 번호)
            is_blocking BOOLEAN      NOT NULL DEFAULT true,
            fill_hint   TEXT,                           -- 원문에서 찾을 단서
            note        TEXT,
            sort_order  INTEGER      NOT NULL DEFAULT 0,
            created_at  TIMESTAMP    NOT NULL DEFAULT now(),
            CONSTRAINT std_spec_defs_type CHECK
                (data_type IN ('INT','NUM','TEXT','BOOL','LIST'))
        )"""))
    conn.execute(sa.text(
        "COMMENT ON COLUMN std.spec_defs.is_blocking IS "
        "'false 면 조립을 막지 않고 경고만 한다(예: PCIe 세대는 하위호환)'"))
    conn.execute(sa.text(
        "COMMENT ON COLUMN std.spec_defs.required_for IS "
        "'필수로 지정된 부품 종류. 빈 목록으로 시작해 채운 뒤 항목별로 승격한다 — "
        "한꺼번에 올리면 추천 후보가 0이 된다'"))

    # 값 — **출처를 값마다 남긴다**
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS std.part_specs (
            product_code BIGINT      NOT NULL REFERENCES products(product_code),
            field_key    VARCHAR(40) NOT NULL REFERENCES std.spec_defs(field_key),
            value_text   VARCHAR(200),
            value_num    NUMERIC(12,2),
            value_json   JSONB,
            source       VARCHAR(12) NOT NULL,
            source_ref   TEXT,
            confidence   NUMERIC(3,2),
            verified_by  INTEGER,
            verified_at  TIMESTAMP,
            locked       BOOLEAN     NOT NULL DEFAULT false,
            updated_at   TIMESTAMP   NOT NULL DEFAULT now(),
            PRIMARY KEY (product_code, field_key),
            CONSTRAINT std_part_specs_source CHECK
                (source IN ('parsed','human','external','vendor')),
            CONSTRAINT std_part_specs_has_value CHECK
                (value_text IS NOT NULL OR value_num IS NOT NULL OR value_json IS NOT NULL)
        )"""))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_std_part_specs_field"
        " ON std.part_specs (field_key)"))
    conn.execute(sa.text(
        "COMMENT ON COLUMN std.part_specs.source IS "
        "'parsed=원문 파싱 · human=사람 입력 · external=외부 제안(다나와 등) · vendor=제조사 자료'"))
    conn.execute(sa.text(
        "COMMENT ON COLUMN std.part_specs.source_ref IS "
        "'근거. parsed 면 원문 스니펫, external 이면 출처 URL, human 이면 검수 메모. "
        "근거 없는 값은 지어낸 값과 구별되지 않는다'"))
    conn.execute(sa.text(
        "COMMENT ON COLUMN std.part_specs.locked IS "
        "'사람이 고친 값은 잠근다 — 다음 파싱이 덮어쓰면 어제 고친 값이 오늘 되돌아간다'"))


def downgrade():
    """`std` 를 통째로 내린다. `public` 은 이 마이그레이션이 되돌린 0035 상태 그대로 둔다."""
    op.get_bind().execute(sa.text("DROP SCHEMA IF EXISTS std CASCADE"))
