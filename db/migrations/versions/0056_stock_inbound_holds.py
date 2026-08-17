# -*- coding: utf-8 -*-
"""stock_inbound_holds -- 재고 입고 「보류」를 담을 자리 (2026-08-17 사장님 확정 ㉡ · 파일만 · 적용 보류).

■ 왜 필요한가 -- 대기 목록은 «저장»이 아니라 «파생»이다
  입고 대기 목록에 상태를 담는 컬럼·표가 없다(실측: `api/admin_stock.py` `_PENDING` 은
  `products.stock_qty` · `products.safety_stock` 에서 조건으로 뽑는다).
    조건: status NOT IN ('단종','삭제대기')
          AND (stock_qty = 0 OR (safety_stock IS NOT NULL AND stock_qty < safety_stock))
  그래서 구 화면(`mockups/admin/stock-inbound.html:347-350`)의 「보류」는 `R.splice(i,1)`
  로 **브라우저 배열에서만** 지우고 「보류 -- 재고 미반영」을 띄웠다. 목록이 파생이므로
  **다음 조회에 그대로 다시 나온다** -- 운영자는 「처리됐다」고 읽는데 서버는 모른다.
  사장님 확정(2026-08-17): **㉡ 서버 상태로 남긴다.** 담을 것은 승인 디자인
  (`docs/design/spec-stock-inbound.md`)이 정했다 -- **보류 사유 · 해제 시각**, 그리고
  원장 규약대로 **누가 언제**.

■ 왜 기존 표로 부족한가 (무근거 신설 금지 -- 검토한 넷을 전부 적는다)
  ㉮ `products` 에 컬럼 넉 개(hold_reason·held_at·held_by·hold_released_at)를 더하는 안
     · 보류는 상품 «속성»이 아니라 이 화면의 «작업 상태»다. 상품 마스터는 카탈로그
       적재 UPSERT 의 대상이고, 그 UPSERT 에서 잠기는 것은 **매입가·판매가 둘뿐**이다
       (CLAUDE.md §데이터: `locked_fields` 를 참조하는 줄이 2개). 「사람이 넣은 사실이
       적재마다 지워진다」는 사고가 **정확히 그 표에서** 났다(상품 123034 의 검수 플래그가
       2026-08-15 적재로 후보로 되돌아갔다). 같은 표에 또 사람 입력을 얹지 않는다.
     · **한 컬럼 세트는 한 회차만 담는다.** 보류 -> 해제 -> 재보류가 반복되면 이전 사유와
       해제 시각이 «덮인다». 원장·되돌림 규약은 덮어쓰기가 아니라 행 추가를 요구한다.
  ㉯ `stock_movements` 에 끼워 넣는 안
     · 보류는 **수량 변동이 아니다.** `qty_delta=0` 행을 넣으면 불변식
       `stock_qty = SUM(qty_delta)` 는 통과하지만, 그것이 바로 CLAUDE.md
       §「이 화면 작업은 재구축이다」가 금지한 **의미 겹치기·컬럼 재활용**이다.
       재고 원장에 재고가 안 변한 행이 섞이면 「이 재고의 출처」를 못 읽는다.
  ㉰ `admin_operator_activity_logs` 에만 남기고 파생하는 안
     · 로그는 «사건»이지 «상태»가 아니다. 「지금 보류인가」를 매 목록 조회마다 도메인
       17종이 섞인 로그 전수에서 파생해야 한다.
     · 그리고 **DB가 「한 상품에 활성 보류 하나」를 보장할 수 없다** -- 아래 부분 유니크
       인덱스에 해당하는 장치를 로그 표에는 걸 수 없다(같은 상품 보류 로그가 두 번
       들어가는 것을 막을 수단이 없고, 그러면 해제가 어느 것을 푸는지 모호해진다).
  ㉱ 새 표 (택한 안)
     · 회차마다 한 행. 해제는 **행 삭제가 아니라 `released_at` 기록** -- 되돌림이 삭제가
       아닌 것과 같은 규칙이다. 보류 이력이 남아 「왜 이 상품을 계속 보류하나」에 답한다.

■ 활성 보류의 정의 -- 코드가 아니라 DB가 지킨다
  활성 = `released_at IS NULL`. 부분 유니크 인덱스가 **상품당 활성 보류 1건**을 강제한다.
  해제된 행은 인덱스 대상이 아니므로 같은 상품을 여러 번 보류·해제할 수 있다.
  대기 목록에서 보류분을 빼는 조건은 이 정의를 그대로 쓴다(코드가 새로 정의하지 않는다).

■ ⚠ 기존 표를 건드리지 않는다 -- NOT NULL 백필도, 기본값 채우기도 없다
  0055 의 docstring 이 남긴 판단과 같은 이유다: 기존 표에 NOT NULL 을 걸면 **적용 시점부터
  그 컬럼을 안 넣는 옛 코드의 INSERT 가 전부 죽는다.** 이 마이그레이션은 `products` 를
  포함해 **어떤 기존 표도 ALTER 하지 않는다** -- 새 표 하나와 인덱스 둘뿐이다. 새 표의
  NOT NULL(product_code·reason·held_by·held_at)은 백필 대상이 0행이라 안전하고,
  `held_by` 는 `api/auth.current_operator_id()` 가 세션이 없어도 시드 운영자 1을 돌려주므로
  (실측 `api/auth.py:214-217`) 값이 비는 경로가 없다.

■ ⚠ 적용 순서 -- 코드가 이 표를 먼저 참조하면 500 이 난다
      ① 이 마이그레이션 적용(DBA)
      ② 보류 쓰기·해제 API + 대기 목록의 「보류분 제외」 조건 추가
      ③ 화면의 「보류」 단추
  ②를 먼저 배포하면 표가 없는 DB 에서 입고 대기 목록 조회 자체가 죽는다(0052 계열이 겪은
  것과 같은 순서 문제). 그래서 **이번 작업에서는 `api/admin_stock.py` 에 이 표를 참조하는
  SQL 을 한 줄도 넣지 않았다.**

■ ⚠⚠ 이 마이그레이션은 파일만 만든다 -- DB 에 적용하지 않는다 (DBA 소관)
  0051~0055 와 같다. 이번 작업 지시서도 "마이그레이션은 파일만, DB 적용은 DBA"를 명시했다.

■ ERD 개정은 기록자 몫이다 (`docs/06_db-erd.md`)
  적어야 할 것: 새 표 `stock_inbound_holds`(컬럼·PK·FK 둘·부분 유니크 인덱스) ·
  「입고 대기는 파생이고 보류만 저장된다」는 관계 설명 · `products` 를 참조하는 표 목록에
  이 표 추가(`api/admin_products.CHECK_REFS` 등재도 필요 -- 그 파일은 이 작업의 담당 밖).

Revision ID: 0056
Revises: 0055
"""
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS -- downgrade 가 표를 남기므로(아래) 재적용이 안전해야 한다.
    op.execute("""
        CREATE TABLE IF NOT EXISTS stock_inbound_holds (
            hold_id      BIGSERIAL   PRIMARY KEY,
            product_code BIGINT      NOT NULL REFERENCES products (product_code),
            reason       TEXT        NOT NULL,
            held_by      BIGINT      NOT NULL REFERENCES admin_operators (operator_id),
            held_at      TIMESTAMP   NOT NULL DEFAULT now(),
            released_at  TIMESTAMP,
            released_by  BIGINT      REFERENCES admin_operators (operator_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS ux_stock_inbound_holds_active
            ON stock_inbound_holds (product_code) WHERE released_at IS NULL;

        CREATE INDEX IF NOT EXISTS ix_stock_inbound_holds_product
            ON stock_inbound_holds (product_code, held_at DESC);

        COMMENT ON TABLE stock_inbound_holds IS
            '재고 입고(ADM-SRC-020) 보류 - 대기 목록은 파생이라 보류만 저장한다. 활성 = released_at IS NULL';
        COMMENT ON COLUMN stock_inbound_holds.reason IS '보류 사유 - 운영자가 적는다(필수)';
        COMMENT ON COLUMN stock_inbound_holds.released_at IS
            '해제 시각. NULL = 보류 중. 해제는 행 삭제가 아니라 이 값 기록이다';
    """)


def downgrade() -> None:
    # 보류 «사유»는 운영자가 손으로 적은 값이고 복원 경로가 없다 -- 표를 지우면 함께
    # 사라진다. 0054(CHECK 만 걷음) · 0055(인덱스만 걷음)와 같은 판단으로 **표는 남기고
    # 부분 유니크 인덱스만 걷는다**(그 인덱스가 「활성 보류 1건」 제약이므로, 보류 개념을
    # 되돌리는 데 필요한 최소 조치다). 표를 실제로 버릴 때는 이관·삭제 계획과 함께 낸다.
    op.execute("""
        DROP INDEX IF EXISTS ux_stock_inbound_holds_active;
    """)
