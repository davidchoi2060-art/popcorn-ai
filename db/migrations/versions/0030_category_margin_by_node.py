"""마진 정책을 **판매 분류 노드**에 건다 (사용자 지시 2026-08-05).

지금까지 `category_margin_policies`는 `category VARCHAR` 자유 문자열이었고 **0행이었다.**
화면(`margin-policy.html`)은 읽기만 했고, 저장 API는 어느 화면도 부르지 않았다 —
표만 있고 아무 데도 이어지지 않은 죽은 테이블이었다.

**왜 part_type이 아니라 노드인가.** 판매 분류 트리는 이미 part_type과 갈라져 있다:
34노드 중 **13개가 `ETC` 하나를 공유**한다(케이블·젠더 704 · 쿨링·튜닝 1,668 ·
완제품 PC 318 · 소프트웨어 20 …). part_type에 마진을 걸면 **완제품 PC와 케이블이
같은 마진**을 받는다. 마진은 파는 물건의 성격을 따르므로 트리가 맞는 축이다.
도매꾹도 같은 구조다(카테고리가 판매수수료를 정한다 —
`docs/research/domeggook-sc-2026-08-05.md`).

**엔진 축은 그대로다.** 여기서 정하는 것은 `sale_price`를 *다시 계산할 때* 쓰는
마진일 뿐이다. 카테고리를 옮겨도 **저장된 판매가는 그 자리에서 바뀌지 않는다** —
다음 재산정(미리보기 → 확인 → 반영)에서 반영된다. 그래서 '분류를 옮겼더니 값이
말없이 달라졌다'는 사고가 생기지 않는다.

`ON DELETE CASCADE` — 노드를 지우면 그 정책도 사라진다. 남겨두면 다음에 같은
category_id가 재사용될 때 **엉뚱한 노드가 남의 마진을 물려받는다**(0029에서 노드를
지워 본 직후라 더 분명하다).

0행이므로 옮길 데이터가 없다. 되돌리기는 옛 모양을 그대로 되살린다.
"""
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP TABLE IF EXISTS category_margin_policies")
    op.execute("""
        CREATE TABLE category_margin_policies (
          category_id INTEGER PRIMARY KEY
                      REFERENCES categories(category_id) ON DELETE CASCADE,
          margin_rate NUMERIC(7,6) NOT NULL,
          updated_at  TIMESTAMP NOT NULL DEFAULT now(),
          CONSTRAINT margin_rate_range CHECK (margin_rate >= 0 AND margin_rate < 1)
        )""")
    # NUMERIC(7,6) — 0028에서 겪은 그 일이다. (5,4)였다면 0.02585가 0.0259로 조용히
    # 반올림된다. 마진도 소수 셋째 자리를 쓸 수 있어야 한다.
    op.execute("COMMENT ON TABLE category_margin_policies IS"
               " '판매 분류 노드별 마진율. 없으면 상위 노드, 그것도 없으면"
               " pricing_settings.margin_rate(전역).'")


def downgrade():
    op.execute("DROP TABLE IF EXISTS category_margin_policies")
    op.execute("""
        CREATE TABLE category_margin_policies (
          category    VARCHAR(60) PRIMARY KEY,
          margin_rate NUMERIC(7,6) NOT NULL,
          updated_at  TIMESTAMP NOT NULL DEFAULT now()
        )""")
