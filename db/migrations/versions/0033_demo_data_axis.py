"""데모 구분 축을 상담 세션에 넣는다 — 무엇을 비울지 알 수 있게 (2026-08-09).

■ 왜 필요한가
  I-01 은 "운영 DB 는 **원장을 비우고** 시작하되 카탈로그·규칙은 이관한다"고 정했다.
  그런데 **무엇을 비울지 구분할 수 없으면 그 결정을 실행할 수 없다.**

  이 프로젝트는 이미 두 번 당했다 — 검증하다 만들어진 `nobody-zz@example.com` 이
  승인돼 owner 권한 계정이 됐고(슬라이스 78), 실주문 `ORD-84222` 는 재고 원장까지
  건드려 정리에 별도 작업이 필요했다. 둘 다 **나중에 구분하려니 못 하겠던** 사례다.

  곧 고객 흐름(S0~S5)으로 예시 주문 10~30건을 만든다(사용자 결정 2026-08-09).
  지금 표시 축을 넣지 않으면 그 30건이 진짜 데이터와 영원히 섞인다.

■ 왜 다섯이 아니라 하나인가
  대상 후보는 다섯이었다 — consult_sessions · quote_snapshots · order_items ·
  payments · shipments. 그런데 FK 를 실제로 세어 보면 넷은 **파생된다**:

      consult_sessions ──< quote_snapshots        (session_id)
             ▲ (orders.session_id)
           orders ──< order_items · payments · shipments   (order_id)

  `orders` 는 이미 `data_origin` 을 갖고 있다. 그러니 **뿌리 중 표시가 없는 것은
  `consult_sessions` 하나뿐**이다. 나머지 넷에 컬럼을 더 만들면 부모와 값이 어긋날
  수 있고, 그건 이 리포가 반복해서 앓은 「같은 것을 두 벌 두지 않는다」다.

  파생으로 지우는 법은 `docs/06_db-erd.md` 와 `deploy/README.md` 에 적는다.

■ 기본값을 'real' 로 두는 이유
  기존 3,885 행은 개발 중 만들어진 것이 대부분이지만 **우리는 어느 것이 무엇인지
  모른다.** 모르는 과거를 'demo' 로 단정하면 지어낸 값이 된다 — 재고 7,594 건을
  `inbound` 가 아니라 **기초 재고**(`opening`)로 기록한 것과 같은 규칙이다.
  그래서 과거는 'real' 로 두고, **지금부터 만드는 것만** 스위치로 찍는다.

  즉 이 컬럼은 "과거를 분류하는 축"이 아니라 **"앞으로를 구분하는 축"**이다.

■ 값은 products 와 같은 어휘를 쓴다
  `products` · `orders` · `members` · `csv_import_jobs` 가 이미
  varchar NOT NULL DEFAULT 'real' 이고 값은 'real' / 'demo' 다. 같은 어휘를 쓴다 —
  테이블마다 다른 말을 쓰면 정리 SQL 을 매번 다시 짜야 한다.
"""
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE consult_sessions
            ADD COLUMN IF NOT EXISTS data_origin VARCHAR(10) NOT NULL DEFAULT 'real'
    """)
    # 정리 SQL 이 이 컬럼으로 훑으므로 인덱스를 둔다. demo 는 소수라 부분 인덱스가 맞다.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_consult_sessions_demo
            ON consult_sessions (data_origin) WHERE data_origin <> 'real'
    """)


def downgrade():
    # 컬럼을 지우면 '무엇이 예시였는지'가 함께 사라진다. 되돌릴 수 없는 손실이라
    # 인덱스만 걷고 컬럼은 남긴다 — 사양 항목 삭제를 열지 않은 것과 같은 규칙이다.
    op.execute("DROP INDEX IF EXISTS ix_consult_sessions_demo")
