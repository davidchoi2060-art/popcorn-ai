# -*- coding: utf-8 -*-
"""monitor_recommend 의도 등재 — 화면에만 있던 답변 하나를 표로 옮긴다 (2026-08-22).

■ 무엇이 잘못돼 있었나 (검증에서 잡혔다)
  「모니터도 하나 추천해주세요」는 화면이 조기 처리해 **답을 준다**(24/27/32인치 구간).
  그런데 그 답이 `talk_intents` 에 없어서 원장에 `intent_key = NULL` 로 남았고,
  그러면 **「우리가 아직 답을 못 만든 질문」 큐에 후보로 올라간다.** 답이 있는데 없다고
  말하는 상태다.

      실측(2026-08-22 화면 검증):
        #11  intent_key=NULL · answer_kind=band_cards · llm_called=false
             「모니터도 하나 추천해주세요」   <- 답을 줬는데 «안 걸림»

  0062 가 `TALKS` 20종을 옮길 때 **이 답변은 그 배열에 없어서** 함께 옮겨지지 않았다
  (화면의 조기 처리 분기에 직접 박혀 있다). 이관이 한 칸 덜 된 것이다.

■ 왜 `text` 가 아니라 `band_cards` 인가
  이 답은 **수를 말한다**(구간별 건수·가격대·해상도 분포·144Hz 이상 개수).
  A-01·A-02 상 그런 답은 문구로 적으면 안 되고 서버가 세야 한다 — 그래서
  `answer_ref = /api/talk/monitor-bands` 로 두고 `answer_body` 는 비운다.
  **A-96 이 「`text` 는 자동 승격하지 않는다」고 한 이유의 반대편**이 이것이다:
  수를 서버가 세는 답은 굳어도 거짓말을 하지 않는다.

■ status = '사용'
  이미 고객에게 나가고 있는 답이다. 「대기」로 넣으면 등재하는 순간 화면과 표가
  어긋난 채로 남는다.

■ ⚠ 화면도 함께 고쳐야 뜻이 산다
  `mockups/mvp1/s1-session.html` 의 `monitorBands()` 가 `/api/talk/hit` 에
  `intent_key` 를 **null 로** 보내고 있었다. 이 마이그레이션과 같은 커밋에서
  `'monitor_recommend'` 를 보내도록 고쳤다 — 표만 세우면 기록은 그대로 NULL 이다.
"""
from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO talk_intents
            (intent_key, label, match_terms, min_hits, answer_kind,
             answer_body, answer_ref, status)
        VALUES
            ('monitor_recommend', '모니터 추천',
             CAST('["모니터"]' AS JSONB), 1, 'band_cards',
             NULL, '/api/talk/monitor-bands', '사용')
        ON CONFLICT (intent_key) DO NOTHING;

        COMMENT ON TABLE talk_intents IS
            '팝콘톡 답변 패턴 정본(ADM-TLK-010) - 화면 코드의 TALKS 를 옮겨 담는 자리. band_cards 는 수를 서버가 센다';
    """)


def downgrade() -> None:
    # 0061·0062 와 같은 규칙 — 지우지 않는다. 운영자가 이 행을 고쳤을 수 있다.
    pass
