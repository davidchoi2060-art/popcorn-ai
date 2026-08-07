"""등급 축 — 부품에 "얼마나 좋은가"를 담는 자리를 만든다 (재설계안 §3-① · 2026-08-07).

■ 왜 필요한가
  지금 시스템이 가진 축은 셋이다 — `part_type`(뭔가) · `categories`(어디서 파나) ·
  `spec_field_defs`(어떤 값을 갖나). **사양 축은 전부 호환과 취향이다.**
  엔진이 읽는 22종을 실제로 세어 보면 CPU 는 소켓·TDP·쿨러높이·쿨러발열한도·
  라디에이터열·RGB·저소음이고, GPU 는 권장전원·길이·PCIe세대·RGB·저소음이다.
  **성능 지표가 하나도 없다.**

  그래서 지금 엔진이 하는 일은 정확히 이것이다 — **조건에 맞는 것 중 가장 싼 것을 고른다.**
  호환 규칙 · 용도 하한 · 티어 배분은 셋 다 **거르는 장치**이고 고르는 장치가 없다.
  하한은 바닥을 막지 최선을 고르지 않는다(GT710 사고가 그 구조였다).

  "모든 견적에는 이유가 있습니다"라고 말하면서 그 이유가 "제일 쌌습니다"인 것이
  지금 상태다. 데이터를 완벽히 채워도 `RTX 4060 = 등급 7` 을 넣을 곳이 없다 —
  **데이터 문제가 아니라 모델 결함이다.**

■ 왜 products 컬럼이 아니라 별도 표인가
  · **적재가 덮으면 안 된다.** 등급은 사람의 판단이고 `products` 는 적재마다 다시
    계산되는 값들이 사는 곳이다. 같은 표에 두면 `locked_fields` 로 지켜야 하는데,
    구조적으로 못 덮게 하는 편이 규율보다 낫다.
  · **근거를 함께 담아야 한다.** 등급만 있고 근거가 없으면 그건 지어낸 값이다.

■ `basis` 를 NOT NULL 로 둔다 — 이 표의 핵심 설계
  **근거 없는 등급은 저장할 수 없다.** 정체성("모든 견적에는 이유가 있습니다")을
  규율이 아니라 스키마로 강제한다. 지어낸 태그를 금지한 것과 같은 규칙이다
  (선호 태그는 명시 표현만 인정하고 추론을 금지했다).

■ 점수는 **슬롯 안에서만** 뜻을 갖는다
  GPU 80점과 CPU 80점은 같은 뜻이 아니다. `grade` 는 "그 슬롯 안에서 몇 점짜리인가"이고,
  가성비(점수/가격) 비교도 슬롯 안에서만 유효하다. 슬롯 간 환산은 하지 않는다 —
  하려면 근거가 필요한데 우리에겐 없다.

■ 엔진은 이번에 0줄 건드린다
  축만 만든다. 지금 연결하면 값이 비어 있어 **모든 부품이 등급 0 으로 취급되거나,
  등급 있는 소수만 추천되거나** 둘 중 하나가 된다. 둘 다 지금보다 나쁘다.
  완제품 축(0031)과 같은 순서다 — **축을 먼저 만들고, 배제 불변식을 회귀로 걸고,
  값이 찬 뒤에 연결한다.** 회귀가 "엔진이 아직 등급을 읽지 않는다"를 지킨다.
"""
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS part_grades (
            product_code  BIGINT PRIMARY KEY
                          REFERENCES products(product_code) ON DELETE CASCADE,
            grade         SMALLINT NOT NULL CHECK (grade BETWEEN 0 AND 100),
            basis         TEXT     NOT NULL CHECK (btrim(basis) <> ''),
            source        TEXT,
            graded_by     INTEGER  REFERENCES admin_operators(operator_id),
            graded_at     TIMESTAMP NOT NULL DEFAULT now(),
            updated_at    TIMESTAMP
        )
    """)
    # 슬롯별 서열을 뽑을 때 매번 products 와 조인한다 — 등급 있는 것만 빠르게 모은다.
    op.execute("CREATE INDEX IF NOT EXISTS ix_part_grades_grade ON part_grades (grade DESC)")


def downgrade():
    # 등급은 **사람이 넣은 판단**이다. 되돌리면 그 노동이 사라지고 재현할 수 없다
    # (사양 항목 삭제를 열지 않은 것과 같은 이유). 표는 남기고 인덱스만 지운다.
    op.execute("DROP INDEX IF EXISTS ix_part_grades_grade")
