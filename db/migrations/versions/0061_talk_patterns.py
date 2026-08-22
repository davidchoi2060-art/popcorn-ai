# -*- coding: utf-8 -*-
"""talk_intents · talk_intent_hits -- 팝콘톡 질문을 쌓아 답변 패턴으로 만든다 (2026-08-22 A-95·A-96).

정의서 = `docs/design/req/req-talk-patterns.md` · 결정 = **A-95**(대화 원문 저장) ·
**A-96**(자동 승격). 사장님 지시: *"해당 질문과 답변을 저장하고 기억해서, 나중에 사용이
가능하도록 패턴으로 만들 수 있으면 좋겠어"*.

■ 왜 필요한가 -- 지금은 「무엇을 물었는지」가 아무 데도 없다
  팝콘톡의 답변 패턴은 화면 코드에 박힌 20종이 전부다(`mockups/mvp1/s1-session.html`
  의 `TALKS`). 그래서 셋이 안 된다: ① 늘리려면 코드를 고쳐야 한다(운영자가 못 늘린다)
  ② 고객이 무엇을 묻는지 모른다(걸린 것도 안 걸린 것도 기록이 없다) ③ 어느 답이 실제로
  쓰였는지 모른다(20종 중 죽은 것이 있어도 알 수 없다).

■ 왜 기존 표로 부족한가 (무근거 신설 금지 -- 검토한 넷을 전부 적는다)
  ㉮ `consult_sessions` 에 컬럼을 더하는 안
     · 한 세션에 질문이 여럿 온다. 한 컬럼 세트는 한 회차만 담으므로 **덮인다.**
     · 그리고 `/api/talk/parse` 는 **세션을 만들지 않는다**(응답 `stored:false`) --
       세션이 없는 질문이 실재하는데 세션 표에는 담을 자리가 없다.
  ㉯ `product_reviews`(검수 큐)를 재활용하는 안
     · 그 표는 «상품의 사양 값»을 사람이 확인하는 자리다. 도메인이 다르고,
       `product_code` NOT NULL 이라 상품 없는 질문을 담을 수 없다.
     · CLAUDE.md §「이 화면 작업은 재구축이다」가 금지한 **의미 겹치기·컬럼 재활용**이다.
  ㉰ `api_cost_logs` 에 얹는 안
     · 그 표는 «비용»이다(프로바이더·모델·토큰·금액). LLM 을 안 태운 질문
       (정규식·조기 처리)은 애초에 행이 안 생긴다 -- 모니터 구간 응답이 바로 그런 경우다.
  ㉱ 새 표 둘 (택한 안)
     · 정본(`talk_intents`)과 이력(`talk_intent_hits`)을 나눈다. 검수 큐가
       `product_specs`(정본)와 `product_reviews`(이력)로 나뉜 것과 같은 모양이다.

■ ⚠ 이 표의 존재 이유는 `intent_key IS NULL` 인 행이다
  「우리가 아직 답을 못 만든 질문」이 거기 쌓인다. 그것이 새 의도를 만들 후보 큐이고,
  A-96(자동 승격)이 세는 대상이다. 그래서 그 컬럼은 **nullable 이어야 한다** --
  NOT NULL 로 두면 정확히 가장 중요한 행을 못 담는다.

■ ⚠ A-95 의 안전장치를 «DB가» 강제한다 (코드에 맡기지 않는다)
  0056 이 「활성 보류 1건」을 부분 유니크 인덱스로 강제한 것과 같은 규칙이다.

      ck_talk_hits_masked   마스킹을 거치지 않은 원문은 **INSERT 자체가 거부된다.**
                            코드가 실수로 raw 를 그대로 넣는 경로를 만들 수 없다.
      ck_talk_hits_purge    원문이 있으면 삭제 예정 시각이 **반드시** 있다.
                            「지우기로 해 놓고 안 지우는」 상태가 생기지 않는다.

  보관 기간 **90일** · 자동 승격 임계 **서로 다른 방문자 5명** (2026-08-22 사장님 확정).
  두 값은 코드 상수가 아니라 운영 설정이 될 수 있으나, 지금은 배선 코드가 들고 있다 --
  표에 박지 않는다(값을 여기 적으면 바꿀 때 마이그레이션이 필요해진다).

■ ⚠ `data_origin` 을 이 표에도 둔다 -- 단일 원천 원칙의 «의도된» 예외
  회귀 트래픽을 자동 승격에서 빼려면(A-96 ㉮) 세션의 `data_origin` 을 봐야 하는데,
  위 ㉮ 에 적었듯 **세션 없이 생기는 행이 있다.** 조인으로는 그 행을 판정할 수 없어
  자체 컬럼을 둔다. **어휘는 `consult_sessions.data_origin` 과 같은 것을 쓴다**
  (`real` · `test`) -- 새 어휘를 만들지 않는다.

■ ⚠ 기존 표를 건드리지 않는다
  ALTER 가 하나도 없다. 새 표 둘과 인덱스 넷뿐이라 적용 시점에 깨지는 옛 코드가 없다.

■ 적용 순서 -- 코드가 이 표를 먼저 참조하면 500 이 난다
      ① 이 마이그레이션 적용
      ② `api/talk.py` 의 기록 배선(마스킹 포함)
      ③ `TALKS` 20종 이관
      ④ 관리자 화면(ADM-TLK-010)
"""
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS talk_intents (
            intent_key   VARCHAR(64)  PRIMARY KEY,
            label        VARCHAR(80)  NOT NULL,
            match_terms  JSONB        NOT NULL DEFAULT '[]'::jsonb,
            min_hits     SMALLINT     NOT NULL DEFAULT 1,
            answer_kind  VARCHAR(24)  NOT NULL,
            answer_body  TEXT,
            answer_ref   VARCHAR(120),
            status       VARCHAR(12)  NOT NULL DEFAULT '대기',
            approved_by  BIGINT       REFERENCES admin_operators (operator_id),
            approved_at  TIMESTAMP,
            created_at   TIMESTAMP    NOT NULL DEFAULT now(),
            updated_at   TIMESTAMP    NOT NULL DEFAULT now(),
            CONSTRAINT ck_talk_intents_status
                CHECK (status IN ('대기', '사용', '자동', '미사용')),
            CONSTRAINT ck_talk_intents_kind
                CHECK (answer_kind IN ('text', 'band_cards', 'constraint_parse', 'handoff')),
            CONSTRAINT ck_talk_intents_answer
                CHECK (status NOT IN ('사용', '자동')
                       OR answer_body IS NOT NULL OR answer_ref IS NOT NULL)
        );

        CREATE TABLE IF NOT EXISTS talk_intent_hits (
            hit_id        BIGSERIAL   PRIMARY KEY,
            session_id    BIGINT      REFERENCES consult_sessions (session_id),
            intent_key    VARCHAR(64) REFERENCES talk_intents (intent_key),
            matched_terms JSONB       NOT NULL DEFAULT '[]'::jsonb,
            unmatched_n   SMALLINT    NOT NULL DEFAULT 0,
            raw_text      TEXT,
            raw_masked_yn BOOLEAN     NOT NULL DEFAULT false,
            raw_purge_at  TIMESTAMP,
            visitor_key   VARCHAR(64),
            answer_kind   VARCHAR(24),
            llm_called    BOOLEAN     NOT NULL DEFAULT false,
            data_origin   VARCHAR(12) NOT NULL DEFAULT 'real',
            created_at    TIMESTAMP   NOT NULL DEFAULT now(),
            CONSTRAINT ck_talk_hits_masked
                CHECK (raw_text IS NULL OR raw_masked_yn),
            CONSTRAINT ck_talk_hits_purge
                CHECK (raw_text IS NULL OR raw_purge_at IS NOT NULL),
            CONSTRAINT ck_talk_hits_origin
                CHECK (data_origin IN ('real', 'test'))
        );

        -- 「안 걸린 질문」 큐 -- 이 표의 존재 이유라 전용 인덱스를 둔다
        CREATE INDEX IF NOT EXISTS ix_talk_hits_unmatched
            ON talk_intent_hits (created_at DESC) WHERE intent_key IS NULL;

        -- 자동 승격 집계 -- 「서로 다른 방문자」를 세는 자리
        CREATE INDEX IF NOT EXISTS ix_talk_hits_intent_visitor
            ON talk_intent_hits (intent_key, visitor_key)
            WHERE data_origin = 'real';

        -- 원문 삭제 배치 -- 지울 것이 있는 행만 훑는다
        CREATE INDEX IF NOT EXISTS ix_talk_hits_purge
            ON talk_intent_hits (raw_purge_at) WHERE raw_text IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ix_talk_intents_status
            ON talk_intents (status);

        COMMENT ON TABLE talk_intents IS
            '팝콘톡 답변 패턴 정본(ADM-TLK-010) - 화면 코드의 TALKS 를 옮겨 담는 자리';
        COMMENT ON COLUMN talk_intents.status IS
            '대기/사용/자동/미사용. 자동 = A-96 으로 승격된 것(사람 승인분과 구분해 표시한다)';
        COMMENT ON COLUMN talk_intents.answer_body IS
            '문구 답변. 부품명/가격/후보 수를 적지 않는다(A-01,A-02) - 수가 필요하면 answer_ref';
        COMMENT ON COLUMN talk_intents.answer_ref IS
            'band_cards 일 때 부를 API. 예: /api/talk/monitor-bands - 수는 서버가 센다';

        COMMENT ON TABLE talk_intent_hits IS
            '팝콘톡 질문 이력(원장) - intent_key IS NULL 인 행이 이 표의 존재 이유다';
        COMMENT ON COLUMN talk_intent_hits.intent_key IS
            'NULL = 어느 의도에도 안 걸렸다. 새 의도를 만들 후보 큐이므로 nullable 이어야 한다';
        COMMENT ON COLUMN talk_intent_hits.raw_text IS
            '고객 문장 원문(A-95). 마스킹을 거친 값만 들어간다(ck_talk_hits_masked). owner 전용 - 고객 경로는 반환하지 않는다';
        COMMENT ON COLUMN talk_intent_hits.raw_purge_at IS
            '이 시각 이후 raw_text 만 NULL 로 지운다(행은 남긴다). 원문이 있으면 필수(ck_talk_hits_purge)';
        COMMENT ON COLUMN talk_intent_hits.visitor_key IS
            '자동 승격의 「서로 다른 사람」 판정용. 한 사람의 반복은 1 로 센다';
        COMMENT ON COLUMN talk_intent_hits.data_origin IS
            'real/test. test 는 자동 승격 집계에서 뺀다 - 세션 없이 생기는 행이 있어 자체 컬럼을 둔다';
    """)


def downgrade() -> None:
    # 표를 지우지 않는다 -- 0056 과 같은 규칙이다.
    # 쌓인 질문 이력은 **되돌릴 수 없는 원장**이고, downgrade 로 지우면 A-95 로 모은 것이
    # 통째로 사라진다. 되돌려야 하면 사람이 판단해 DROP 한다(그 판단을 자동화하지 않는다).
    pass
