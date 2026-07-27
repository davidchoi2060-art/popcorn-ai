"""사양 필드 정의를 데이터로 — spec_field_defs (슬라이스 56).

**왜 필요한가.** 사양 필드 목록이 코드 상수 다섯 곳에 흩어져 있었다:
`catalog_ingest.SPEC_COLS`(적재) · `swap.SPEC_COLS`(대안) · `recommend._load_pool`(후보) ·
`admin_reviews.FIELD_CAST`(검수 승인) · `admin_products.REQUIRED_SPEC_FIELDS`(필수 판정).
컬럼을 하나 늘리면 다섯 곳과 뷰 두 개를 **사람이 전부 따라가야** 했고, 하나만 빠져도
NULL 불통과로 견적이 조용히 0이 됐다(슬라이스 46 전례).

실제 운영자가 현장에서 필요한 사양을 계속 발견하고 있다. 그때마다 개발 배포를 기다릴 수
없으므로 **화면에서 사양 항목을 추가**하기로 했다(2026-07-28 결정). 그러려면 필드 목록이
코드가 아니라 **데이터**여야 한다 — 이 테이블이 그 단일 원천이다.

  · `is_engine=true`  → 추천 뷰에 실린다. 호환 규칙·견적이 읽는 값.
  · `is_required`     → part_type별 필수 사양(게이트 판정). `required_for`에 종류 목록.
  · `data_type`       → ALTER TABLE과 검수 승인 캐스트가 같은 값을 쓴다.

기존 35컬럼 중 사양 필드를 여기에 시드한다 — 지금 동작을 그대로 데이터로 옮기는 것이고,
동작이 바뀌면 안 된다. 그래서 시드 값은 코드 상수를 **그대로 옮겨 적었다**.

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE spec_field_defs (
            field_key    VARCHAR(40)  PRIMARY KEY,
            label        VARCHAR(60)  NOT NULL,
            data_type    VARCHAR(20)  NOT NULL,
            unit         VARCHAR(20),
            -- 어느 부품 종류에서 쓰이는가(빈 배열이면 전 종류 공통)
            part_types   JSONB        NOT NULL DEFAULT '[]'::jsonb,
            -- 필수 사양으로 볼 부품 종류(게이트 판정) — part_types의 부분집합
            required_for JSONB        NOT NULL DEFAULT '[]'::jsonb,
            -- 추천 뷰·엔진이 읽는 값인가. false면 표시용(판정에 영향 없음).
            is_engine    BOOLEAN      NOT NULL DEFAULT false,
            -- 운영자가 화면에서 만든 항목인가(시드분과 구분)
            is_custom    BOOLEAN      NOT NULL DEFAULT false,
            sort_order   INTEGER      NOT NULL DEFAULT 100,
            note         TEXT,
            created_by   INTEGER,
            created_at   TIMESTAMP    NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_spec_field_defs_engine ON spec_field_defs (is_engine, sort_order);
    """)

    # 시드 — 지금 코드 상수와 **정확히 같은 내용**을 데이터로 옮긴다.
    # (field_key, label, data_type, unit, part_types, required_for, is_engine, sort)
    CORE = "CPU,MB,RAM,GPU,SSD,HDD,POWER,CASE,COOLER_CPU_AIR,COOLER_CPU_AIO"
    rows = [
        ("socket", "소켓", "VARCHAR", None, "CPU,MB", "CPU,MB", True, 10),
        ("socket_list", "지원 소켓 목록", "JSONB", None,
         "COOLER_CPU_AIR,COOLER_CPU_AIO", "COOLER_CPU_AIR,COOLER_CPU_AIO", True, 11),
        ("chipset", "칩셋", "VARCHAR", None, "MB", "MB", True, 20),
        ("mem_type", "메모리 규격", "VARCHAR", None, "MB,RAM", "MB,RAM", True, 30),
        ("capacity_gb", "용량", "INTEGER", "GB", "RAM,SSD,HDD", "RAM,SSD,HDD", True, 40),
        ("clock_mhz", "클럭", "INTEGER", "MHz", "RAM", "RAM", True, 50),
        ("tdp_watt", "발열(TDP)", "INTEGER", "W", "CPU", "CPU", True, 60),
        ("rated_watt", "정격 출력", "INTEGER", "W", "POWER", "POWER", True, 70),
        ("required_power_watt", "권장 전원", "INTEGER", "W", "GPU", "GPU", True, 80),
        ("length_mm", "길이", "INTEGER", "mm", "GPU", "GPU", True, 90),
        ("gpu_max_mm", "그래픽카드 장착 길이", "INTEGER", "mm", "CASE", "CASE", True, 100),
        ("cooler_height_mm", "쿨러 높이", "INTEGER", "mm",
         "CASE,COOLER_CPU_AIR", "CASE,COOLER_CPU_AIR", True, 110),
        ("cooler_tdp", "쿨러 발열 한도", "INTEGER", "W",
         "COOLER_CPU_AIR,COOLER_CPU_AIO", "COOLER_CPU_AIR,COOLER_CPU_AIO", True, 120),
        ("pcie_gen", "PCIe 세대", "VARCHAR", None, "GPU", "GPU", True, 130),
        ("form_factor", "규격", "VARCHAR", None, "MB,SSD,HDD,POWER", "MB,SSD,HDD,POWER", True, 140),
        ("form_factor_list", "수용 보드 규격", "JSONB", None, "CASE", "CASE", True, 150),
        ("interface", "인터페이스", "VARCHAR", None, "SSD,HDD", "SSD,HDD", True, 160),
        ("tag_white", "화이트", "BOOLEAN", None, "CASE", "", True, 200),
        ("tag_rgb", "RGB", "BOOLEAN", None, CORE, "", True, 201),
        ("tag_silent", "저소음", "BOOLEAN", None,
         "GPU,POWER,CASE,COOLER_CPU_AIR,COOLER_CPU_AIO", "", True, 202),
        ("size_inch", "화면 크기", "NUMERIC", "인치", "MONITOR", "MONITOR", False, 300),
        ("resolution", "해상도", "VARCHAR", None, "MONITOR", "MONITOR", False, 310),
        ("refresh_hz", "주사율", "INTEGER", "Hz", "MONITOR", "MONITOR", False, 320),
        ("panel", "패널", "VARCHAR", None, "MONITOR", "MONITOR", False, 330),
        ("switch_type", "스위치", "VARCHAR", None, "KEYBOARD", "KEYBOARD", False, 340),
        ("key_layout", "키 배열", "VARCHAR", None, "KEYBOARD", "KEYBOARD", False, 350),
        ("connection", "연결 방식", "VARCHAR", None,
         "KEYBOARD,MOUSE,HEADSET,SPEAKER,WEBCAM",
         "KEYBOARD,MOUSE,HEADSET,SPEAKER,WEBCAM", False, 360),
        ("ports", "포트 구성", "JSONB", None, "MB,MONITOR", "", False, 400),
    ]
    for key, label, dt, unit, pts, req, eng, order in rows:
        op.execute(f"""
            INSERT INTO spec_field_defs
              (field_key, label, data_type, unit, part_types, required_for,
               is_engine, is_custom, sort_order, note)
            VALUES ('{key}', '{label}', '{dt}',
                    {"NULL" if unit is None else "'" + unit + "'"},
                    '{_arr(pts)}'::jsonb, '{_arr(req)}'::jsonb,
                    {str(eng).lower()}, false, {order},
                    '초기 스키마에서 이관 — 코드 상수와 같은 정의')
        """)


def _arr(csv: str) -> str:
    if not csv:
        return "[]"
    items = ",".join('"%s"' % x.strip() for x in csv.split(",") if x.strip())
    return "[%s]" % items


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS spec_field_defs")
