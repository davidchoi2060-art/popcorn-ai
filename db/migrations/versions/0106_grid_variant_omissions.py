# -*- coding: utf-8 -*-
"""사무·주식 용도에서 「고성능」 카드를 없애고 그 사유를 데이터로 남긴다 (2026-09-20).

■ 무엇을 결정했나 — 사장님 확정
  *"사무·주식에는 「고성능」 카드를 안 만든다 — 그 용도에 고성능을 파는 것 자체가
  시장에 없다(실판매 0벌)."*
  대상은 `단순 사무용`·`복합 사무용`·`주식·트레이딩` 셋이다. 개발·방송·음악은
  **지명되지 않았고 여기서도 건드리지 않는다**(아래 §어디까지).

■ 왜 이 표가 필요한가 — 0105 가 남긴 자리
  0105 가 격자를 예산대 축으로 재설계하면서 사무·주식의 상한을 200만으로 닫았다.
  그런데 발행되는 견적은 칸마다 **항상 3종**(가성비·추천·고성능)이라, 190만원
  구간(NB_L2)의 고성능이 200만을 넘는다:
      단순 사무용 고성능 2,368,600 · 복합 사무용 고성능 2,560,200
      주식·트레이딩 고성능 2,504,300
  원인은 `api/recommend.py HIGHEND_CAP_X = 1.5` — 고성능 티어는 설계상 예산의
  1.5배까지 쓰는 «위쪽 선택지»다. 190만 x 1.5 = 285만이라, 그 구간에 칸이 있는 한
  고성능은 구조적으로 200만을 넘는다(0105 의 `단순 사무용 NB_L2` band_note 가 이
  한계를 이미 적어 뒀다). 가성비·추천은 200만 안이다.
  **엔진 상수는 건드리지 않는다** — 그 상수는 전체 견적에 걸리고, 사장님이 고른
  방안은 「엔진을 고치는 것」이 아니라 「그 용도에 그 카드를 두지 않는 것」이다.

■ 왜 «발행 목록»이 아니라 «제외 목록»인가 — 판단과 근거
  ⓐ 용도마다 «발행할 variant 목록»을 두는 방법과 ⓑ «제외할 variant 를 사유와 함께»
  두는 방법이 있다. 둘 다 데이터이고 단일 원천이다. 제외 목록을 고른 이유 둘:
    (1) **기본값이 현재 동작이다.** 발행 목록이면 새 용도를 추가할 때 목록 행을
        빠뜨리는 순간 그 용도는 카드가 **한 장도** 안 나온다 — 조용한 실패다.
        제외 목록이면 행이 없을 때 3종 전부가 나온다(지금 동작 그대로).
    (2) **사유가 사라질 수 없다.** 「왜 없는지」는 없어진 자리에 붙어야 하고,
        `reason_public` 이 NOT NULL 이라 **사유 없이 카드를 없앨 수 없다.**
        발행 목록에서는 사유가 별도 컬럼이라 비워 둔 채로도 카드가 사라진다.
  우리 정체성이 「모든 견적에는 이유가 있습니다」이므로, 스키마가 그 규칙을 강제하는
  쪽을 쓴다.

■ 화면이 무엇을 읽나
  `reason_public` — 고객 화면이 그대로 출력하는 문구(CLAUDE.md §문서·화면 어휘
  표준: 평서·간결체 「~합니다」). 「~일 수 있습니다」 같은 추정 표현을 쓰지 않는다.
  `reason_source` — 그 문구의 근거(표본·출처). 관리자 화면·검수용이다. 고객
  문구와 근거를 한 컬럼에 겹쳐 담지 않는다(0105 가 정의/관측을 가른 것과 같은 규칙).

■ 숫자는 어디서 왔나 — 전부 실조회, 지어낸 값 없음
  · 「실판매 사무용 완제품 16벌 · 최고가 1,296,600원 · 200만원 초과 0벌」
    products 실조회: part_type='PC_COMPLETE' AND status='판매중' AND
    (product_name LIKE '%사무%' OR '%오피스%') -> count 16, max(sale_price) 1,296,600.
  · 「실판매 목록에 주식·트레이딩 상품 0벌」
    같은 조건 + product_name LIKE '%주식%'/'%트레이딩%'/'%증권%' -> count 0.
    0105 의 주식·트레이딩 band_note 가 이미 «실판매 표본 0»이라고 적어 뒀다.
  · 「시장 조립 내장그래픽 신품 262벌 중 200만원 초과 9벌(3.4%)」
    조사자 보고서 office_pc_market.md §가격대 분포(다나와 조립PC 486벌에서 내장
    그래픽 262벌 추출) — "200만 초과 9벌뿐 (3.4%)".

■ 어디까지 적용하나 — 개발·방송·음악을 뺀 판단
  사장님이 지명한 것은 「사무·주식」이다. 개발·방송 송출·음악 작업은 지명되지
  않았고, 이 표에도 넣지 않는다. 근거:
    · 그 셋의 고성능 구성에는 **영상·렌더링이 걸친다**(개발은 컨테이너·빌드,
      방송은 원컴 인코딩, 음악은 대형 샘플 라이브러리). 0105 가 그 셋에 NB_L2·L3
      (130~290만)을 둔 것도 200만 위 수요를 인정한 결과다.
    · 사무·주식을 뺀 근거는 「200만 위 실판매가 0벌」이라는 **관측**이다. 개발·방송
      ·음악에는 그 관측이 없다 — 0105 band_note 가 셋 다 «실판매 표본 0»이라고
      적었는데, 그것은 「200만 위가 안 팔린다」가 아니라 「이 이름으로 집계된 상품이
      없다」는 뜻이다. 같은 «0» 이 아니다. 없는 관측으로 카드를 없애지 않는다.
  판단이 필요하면 그때 이 표에 행을 한 줄 더 넣는다 — 그게 이 표를 만든 이유다.

■ 옛 고성능 견적은 지우지 않는다
  `grid_quotes` 는 원장이다(0072 이후). 해당 칸의 고성능 현재본은 **삭제가 아니라
  `is_current=false`** 로 내린다. 행은 남고 화면에서만 사라진다.

Revision ID: 0106
Revises: 0105
"""
import sqlalchemy as sa
from alembic import op

revision = "0106"
down_revision = "0105"
branch_labels = None
depends_on = None


HIGHEND = "고성능"

# 사무 두 용도가 같은 문장을 쓴다 — 같은 근거(사무용 실판매 분포)에서 나온 판단이라
# 문구를 갈라 두면 원천이 둘이 된다.
OFFICE_PUBLIC = (
    "사무용 PC 는 고성능 구성을 두지 않습니다."
    " 실판매 사무용 완제품 16벌의 최고가가 1,296,600원이고, 200만원을 넘는 판매는 0벌입니다."
    " 시장 조립 내장그래픽 신품 262벌 중 200만원 초과도 9벌(3.4%)에 그칩니다."
    " 그래서 이 용도는 가성비·추천 두 구성만 발행합니다."
)
OFFICE_SOURCE = (
    "products 실조회(part_type='PC_COMPLETE', status='판매중', product_name LIKE"
    " '%사무%' OR '%오피스%'): 16벌 · max(sale_price)=1,296,600 · 200만원 초과 0벌."
    " 시장 표본은 조사자 보고서 office_pc_market.md(다나와 조립PC 486벌에서 내장그래픽"
    " 262벌 추출, '200만 초과 9벌뿐 3.4%')."
    " 구조적 원인: api/recommend.py HIGHEND_CAP_X=1.5 가 고성능 상한을 예산의 1.5배로"
    " 잡아, 상한 190만 구간(NB_L2)에 칸이 있는 한 고성능은 200만을 넘는다"
    "(실측 단순 2,368,600 · 복합 2,560,200). 엔진 상수는 전체 견적에 걸리므로 고치지"
    " 않고, 이 용도에 그 카드를 두지 않는 쪽으로 정했다(사장님 확정 2026-09-20)."
)

TRADING_PUBLIC = (
    "주식·트레이딩 PC 는 고성능 구성을 두지 않습니다."
    " 실판매 완제품 목록에 주식·트레이딩 상품이 0벌이고, 같은 내장그래픽 계열인"
    " 사무용도 200만원을 넘는 판매는 0벌입니다."
    " 시장 조립 내장그래픽 신품 262벌 중 200만원 초과도 9벌(3.4%)에 그칩니다."
    " 그래서 이 용도는 가성비·추천 두 구성만 발행합니다."
)
TRADING_SOURCE = (
    "products 실조회(part_type='PC_COMPLETE', status='판매중', product_name LIKE"
    " '%주식%' OR '%트레이딩%' OR '%증권%'): 0벌. 0105 의 주식·트레이딩 band_note 도"
    " «실판매 표본 0»을 이미 적어 뒀다. 사무용 분포는 위 사무 행과 같은 실조회"
    "(16벌 · 최고가 1,296,600 · 200만원 초과 0벌) + office_pc_market.md 262벌 중"
    " 9벌(3.4%)."
    " 구조적 원인은 사무와 같다(HIGHEND_CAP_X=1.5 · 실측 고성능 2,504,300)."
)

# (usage, tier_variant, reason_public, reason_source)
OMISSIONS = [
    ("단순 사무용", HIGHEND, OFFICE_PUBLIC, OFFICE_SOURCE),
    ("복합 사무용", HIGHEND, OFFICE_PUBLIC, OFFICE_SOURCE),
    ("주식·트레이딩", HIGHEND, TRADING_PUBLIC, TRADING_SOURCE),
]

DECIDED_BY = "사장님 확정 2026-09-20"


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "grid_variant_omissions",
        sa.Column("usage", sa.String(20), primary_key=True),
        sa.Column("tier_variant", sa.String(10), primary_key=True),
        # 고객 화면이 그대로 출력하는 문구 — 사유 없이 카드를 없앨 수 없게 NOT NULL
        sa.Column("reason_public", sa.Text, nullable=False),
        # 그 문구의 근거(표본·출처) — 관리자·검수용
        sa.Column("reason_source", sa.Text, nullable=False),
        sa.Column("decided_by", sa.String(40), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("tier_variant IN ('가성비','추천','고성능')",
                           name="ck_grid_variant_omissions_variant"),
        sa.CheckConstraint("length(btrim(reason_public)) > 0",
                           name="ck_grid_variant_omissions_reason"),
        sa.CheckConstraint("length(btrim(reason_source)) > 0",
                           name="ck_grid_variant_omissions_source"),
    )
    op.execute(
        "COMMENT ON TABLE grid_variant_omissions IS "
        "'용도별로 «발행하지 않는» 견적 구성(variant)과 그 사유의 단일 원천(0106). "
        "행이 없으면 그 용도는 3종(가성비·추천·고성능) 전부를 발행한다 — 기본값이 "
        "현재 동작이라, 새 용도를 추가할 때 이 표를 잊어도 카드가 사라지지 않는다. "
        "tools/grid_generate.py 가 이 표를 읽어 해당 variant 를 발행하지 않고, "
        "api/grid_public.py 가 같은 표를 읽어 «왜 없는지»를 화면에 내려준다'"
    )
    op.execute(
        "COMMENT ON COLUMN grid_variant_omissions.reason_public IS "
        "'고객 화면이 그대로 출력하는 문구. CLAUDE.md §문서·화면 어휘 표준 — 평서·"
        "간결체 「~합니다」. NOT NULL 이라 사유 없이 카드를 없앨 수 없다"
        "(「모든 견적에는 이유가 있습니다」를 스키마가 강제한다)'"
    )
    op.execute(
        "COMMENT ON COLUMN grid_variant_omissions.reason_source IS "
        "'reason_public 의 근거(실조회 조건·표본 수·출처 문서). 고객 문구와 근거를 "
        "한 컬럼에 겹쳐 담지 않는다'"
    )

    for usage, variant, public, source in OMISSIONS:
        conn.execute(sa.text(
            "INSERT INTO grid_variant_omissions (usage, tier_variant, reason_public,"
            " reason_source, decided_by) VALUES (:u,:v,:p,:s,:d)"),
            {"u": usage, "v": variant, "p": public, "s": source, "d": DECIDED_BY})

    # ── 옛 고성능 현재본을 내린다 — 삭제가 아니라 is_current=false (원장 보존) ──
    n = conn.execute(sa.text(
        "UPDATE grid_quotes SET is_current=false"
        " WHERE is_current AND tier_variant = :v"
        " AND cell_id IN (SELECT cell_id FROM grid_cells WHERE usage IN"
        "   (SELECT usage FROM grid_variant_omissions WHERE tier_variant = :v))"),
        {"v": HIGHEND}).rowcount

    # 관측 범위(budget_max = 고성능 총액)도 더 이상 사실이 아니다 — 남은 현재본의
    # 실제 최대값으로 다시 쓴다. 다음 배치가 같은 값을 다시 쓰지만, 배치 전까지
    # 화면이 «없어진 카드의 가격»을 범위 상한으로 말하게 두지 않는다.
    conn.execute(sa.text(
        "UPDATE grid_cells c SET"
        " budget_min = s.lo, budget_max = s.hi"
        " FROM (SELECT cell_id, min(total) AS lo, max(total) AS hi FROM grid_quotes"
        "       WHERE is_current AND total IS NOT NULL GROUP BY cell_id) s"
        " WHERE s.cell_id = c.cell_id"
        " AND c.usage IN (SELECT usage FROM grid_variant_omissions)"))

    print(f"[0106] grid_variant_omissions {len(OMISSIONS)} rows"
          f" · grid_quotes highend current -> false: {n} rows"
          " (ledger preserved, rows not deleted)")


def downgrade() -> None:
    conn = op.get_bind()
    # 내렸던 고성능 현재본을 되살린다 — 칸×variant 당 가장 최근 행 하나만.
    conn.execute(sa.text(
        "UPDATE grid_quotes SET is_current=true WHERE quote_id IN ("
        "  SELECT DISTINCT ON (cell_id) quote_id FROM grid_quotes"
        "  WHERE tier_variant = :v AND NOT is_current"
        "  AND cell_id IN (SELECT cell_id FROM grid_cells WHERE usage IN"
        "    (SELECT usage FROM grid_variant_omissions WHERE tier_variant = :v))"
        "  ORDER BY cell_id, generated_at DESC, quote_id DESC)"),
        {"v": HIGHEND})
    op.drop_table("grid_variant_omissions")
