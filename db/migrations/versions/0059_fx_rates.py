# -*- coding: utf-8 -*-
"""fx_rates -- 환율을 «날마다 관측해 쌓는» 자리 (사장님 확정 2026-08-17 · 파일만 · 적용 보류).

■ 왜 필요한가
  AI 관리 화면의 금액 표기에 **( )로 환산금액**을 함께 보이기로 했다(사장님 확정).
      「반드시 금액이 맞아야 되는건 아니고, 대략의 금액정보를 알고 싶은 것임」
  그리고 값의 출처는 **웹에서 하루 한 번 갱신**한다(사장님 확정 2026-08-17).
  환율 코드·설정은 저장소 전체에 **0건**이었다(조사 실측) -- 담을 자리가 없다.

■ ★ 왜 `pricing_settings` 가 아닌가 -- 실측 근거 (처음엔 그쪽으로 검토했다)
  ㉠ **그 표를 읽는 코드 7곳이 전부 `ORDER BY effective_from DESC LIMIT 1` 이다**(실측:
     admin_categories:45 · admin_engine_rules:68,208 · admin_payments:47 ·
     admin_price_import:38 · admin_setup:51,53). 즉 **최신 «한 행»이 곧 현행 정책**이다.
     환율이 날마다 행을 만들면 **그 환율 행이 정책 최신값 행세를 한다** -- 카드수수료율·
     마진율을 매일 함께 복제해야 하고, 하루라도 빠뜨리면 요율이 옛 값으로 되돌아가
     **판매가 산정이 조용히 틀어진다.** 가격을 만지는 자리라 감수할 위험이 아니다.
  ㉡ `pricing_settings` 는 **사람이 정하는 정책 개정 이력**이고(6행 · 2026-07-23~08-05),
     환율은 **바깥에서 관측한 시세**다. 출처·수집 시각이 필요한 쪽은 관측값뿐이다 --
     정책 행에 그 컬럼 넷을 붙이면 정책 행에서는 언제나 빈 칸이 된다.
  ㉢ 담아야 하는 것이 다르다: **기준일 · 값 · 출처 · 수집 시각**(지시 명시).
  -> 그래서 **별도 표**를 만든다.

■ ★ 「출처」를 컬럼으로 둔다 -- 이 저장소가 반복해서 당한 병이다
  수만 남고 출처가 없으면 나중에 **「이 수가 어디서 왔나」를 아무도 모른다.**
  `source`(짧은 식별자)와 `source_url`(실제 호출한 주소)을 **둘 다** 남긴다 --
  식별자만 있으면 경로가 바뀐 뒤 재현이 안 되고, URL만 있으면 집계가 안 된다.

■ 컬럼
  · `base_code`·`quote_code` -- **통화쌍을 적지 않으면 1415.099364 라는 수가 뜻이 없다.**
    지금은 USD->KRW 하나지만 값이 아니라 «구조»라 기본값을 두지 않는다(지어내지 않는다).
  · `rate` NUMERIC(18,6) -- 실측 원문이 소수 6자리다(open.er-api.com: 1415.099364).
    절사하면 우리가 저장한 수가 원문과 달라진다. 정수부는 1,400 대라 여유가 충분하다.
    CHECK (rate > 0) -- 0 이나 음수는 환산을 무의미하게 만들고, 화면이 «0으로 보여주는 것»은
    금지다(§화면이 숫자를 지어내지 않는다). DB가 먼저 막는다.
  · `rate_date` DATE NOT NULL -- **원문이 말하는 기준일**이다. 우리가 「오늘」로 채우지 않는다.
    실측: frankfurter 는 `date` 를 그대로 준다(2026-08-17 조회 -> `2026-08-14`.
    ECB 공시가 평일 오후라 월요일 오전에는 지난 금요일자다). **그 사실이 값과 함께 남아야
    화면이 「언제 기준」을 말할 수 있다** -- 아래 「실패해도 조용하지 않다」 참조.
  · `fetched_at` -- 언제 가져왔는지. `rate_date` 와 «다르다»(기준일 vs 수집 시각).
  ⚠ **원문 전체는 DB에 넣지 않는다** -- `tools/danawa_fetch.py` 전례대로 `.cache/`(gitignore)에
    남긴다. 파서를 고칠 때 재수집하지 않기 위한 것이지 원장이 아니다.

■ ★ UNIQUE (base, quote, rate_date, source) -- 도구를 몇 번 돌려도 안전하다
  하루에 여러 번 돌리거나, 주말처럼 **기준일이 그대로인 날** 돌려도 행이 쌓이지 않는다
  (도구가 `ON CONFLICT DO NOTHING`). `source` 를 키에 넣어 **출처가 다르면 같은 날도 각각
  남는다** -- 두 출처가 다른 값을 말하면 그 사실 자체가 기록돼야 한다(덮지 않는다).
  ⚠ 별도 조회 인덱스를 만들지 않았다. 「최신 환율」 조회는
    `WHERE base_code=.. AND quote_code=.. ORDER BY rate_date DESC LIMIT 1` 인데
    이 UNIQUE 인덱스의 앞 세 컬럼이 그대로 그 순서라 그것으로 처리된다.

■ ⚠ 값을 이 마이그레이션이 정하지 않는다
  첫 값은 `tools/fx_fetch.py` 가 넣는다. 마이그레이션이 숫자를 박으면 **그 순간부터 낡는다** --
  이 저장소가 문서에 수를 박아 여러 번 어긋난 것과 같은 병이다. **자리만 만든다.**

■ ⚠⚠ 이 마이그레이션은 파일만 만든다 -- DB 에 적용하지 않는다 (DBA 소관)
  0054~0058 과 같다. 검증은 **트랜잭션 안에서 DDL 을 돌리고 ROLLBACK** 했다
  (alembic_version 은 0056 그대로, 표에 실제 변화 0).

■ downgrade -- **비어 있으면 지우고, 관측이 쌓였으면 남긴다**
  0056(표를 남긴다)과 0057(지운다)의 판단이 갈렸던 이유를 여기에 그대로 적용한다:
  «다시 만들 수 있는 값인가».
    · frankfurter 는 **과거 기준일 조회가 된다**(실측: `/v1/2026-08-10` -> 1416.62).
    · open.er-api.com 무료 등급은 **과거 조회가 404 다**(실측). 그 출처로 쌓인 행은
      지우면 **다시 못 모은다.**
  즉 「전부 재수집 가능」도 「전부 불가」도 아니다. 그래서 판단을 사람에게 미루지 않고
  **행이 있으면 남기고 없으면 지운다** -- 되돌리는 시점의 사실로 스스로 정한다.

Revision ID: 0059
Revises: 0058
"""
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS fx_rates (
            fx_id      BIGSERIAL     PRIMARY KEY,
            base_code  VARCHAR(3)    NOT NULL,
            quote_code VARCHAR(3)    NOT NULL,
            rate       NUMERIC(18,6) NOT NULL CHECK (rate > 0),
            rate_date  DATE          NOT NULL,
            source     VARCHAR(64)   NOT NULL,
            source_url TEXT          NOT NULL,
            fetched_at TIMESTAMP     NOT NULL DEFAULT now()
        );

        CREATE UNIQUE INDEX IF NOT EXISTS ux_fx_rates_pair_date_source
            ON fx_rates (base_code, quote_code, rate_date, source);

        COMMENT ON TABLE fx_rates IS
            '환율 관측 이력 - tools/fx_fetch.py 가 하루 단위로 넣는다. 정책이 아니라 관측값이라 pricing_settings 와 분리한다';
        COMMENT ON COLUMN fx_rates.rate_date IS
            '원문이 말하는 기준일. 수집일이 아니다 - 주말/공휴일에는 직전 영업일자가 그대로 온다';
        COMMENT ON COLUMN fx_rates.source_url IS
            '실제로 호출한 주소. 이 수가 어디서 왔는지에 답하는 자리다';
    """)


def downgrade() -> None:
    # 판단을 코드에 적는다(위 docstring 참조): 관측이 쌓였으면 남기고, 비어 있으면 지운다.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM fx_rates) THEN
                DROP TABLE fx_rates;
            ELSE
                RAISE NOTICE 'fx_rates: 관측 행이 있어 표를 남깁니다(과거 환율은 출처에 따라 재수집이 불가능합니다)';
            END IF;
        END $$;
    """)
