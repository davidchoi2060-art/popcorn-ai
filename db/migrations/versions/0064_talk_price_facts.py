# -*- coding: utf-8 -*-
"""팝콘톡 캔드 답변 4종을 계산 없는 고정 수치에서 실계산 참조로 바꾼다 (2026-08-23, A-99).

■ 왜 (전수조사 promises C2 — 계산 코드 없는 고정 수치가 «자체 데이터»를 표방)
  `discount`·`price_compare`·`gpu_compare`·`price_trend` 네 인텐트는 0062 에서
  `answer_kind='text'` 로 심어졌는데, 그 문구 안의 수치가 **계산 코드 없이 마이그레이션에
  박힌 고정 문자열**이었다(`0062_talk_intents_seed.py` 57·60·61행) --

      discount        "최저가 조합보다 보통 2~3만원 높다"
      gpu_compare      "RTX 4060 Ti가 4060보다 평균 +18% 빠르고 … 약 11만원 차이"
      price_trend      "저희 실제 매입가 기준(자체 데이터) … 그래픽카드 -3.2%·DDR5 +5.1%"

  "자체 데이터"·"실제 매입가 기준"이라 표방하면서 실제로는 아무것도 계산하지 않았다 --
  A-01(신뢰 정체성 -- "모든 견적에는 이유가 있습니다") 위반이고, 전수조사
  (`docs/design/service-foundation-audit-2026-08-23.md`)가 이 넷을 promises C2 로
  적시했다. 사장님이 세 선택지(①실제 계산 연결 ②"예시" 표기로 낮춤 ③절에서 뺌) 중
  **①**을 확정했다(`docs/decisions/decision-log.md` **A-99**).

■ 성능 수치는 자료가 없어 버린다
  "+18% 빠르다" 류는 벤치마크 성능 데이터가 필요한데 우리에게 없다. A-99 사장님
  확정 그대로 "자료가 없는 주장은 말하지 않는다" -- 그래서 이번에 실제로 잇는 계산은
  **가격·재고 원장 기반**(우리 판매가 대 시장가 차이 · 부품별 가격 추세)으로
  한정한다. 성능 비교라는 발상 자체를 버린다 -- 나중에 벤치마크 데이터가 생기기
  전까지는 다시 만들 근거도 없다.

■ 이번 UPDATE가 하는 일
  네 행을 전부 `answer_kind='band_cards'` · `answer_ref='/api/talk/price-facts'` ·
  `answer_body=NULL` 로 바꾼다(`monitor_recommend`가 이미 쓰던 것과 같은 모양 --
  0063 참조). `match_terms`·`min_hits`·`status`·`answer_pack`은 손대지 않는다 --
  gpu_compare의 answer_pack(관심 부품 조건팩)은 여전히 유효하다.

  실제 계산은 `api/talk.py`의 `GET /api/talk/price-facts`가 한다(같은 물결,
  `api/talk.py` 담당). 이 마이그레이션은 데이터만 옮긴다 -- 계산 로직을 여기
  SQL에 심지 않는다(CANON §1 -- 계산은 API 모듈이 단일 원천).

■ 왜 UPDATE이지 새 행이 아닌가
  같은 intent_key로 이미 상담 원장(`talk_intent_hits.matched_terms`)과 화면
  `TALKS` 폴백이 그 이름을 참조한다. 새 키로 갈아타면 폴백·이력 조인이 갈라진다.

■ downgrade
  0061~0063 과 같은 규칙 -- 지우지 않는다. 운영자가 이 네 행의 `answer_body`·
  `answer_pack`을 이미 손으로 고쳤을 수 있고, downgrade로 되돌리면 그 노동이
  사라진다. `pass`로 둔다.
"""
from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None

_KEYS = ("discount", "price_compare", "gpu_compare", "price_trend")


def upgrade() -> None:
    op.execute("""
        UPDATE talk_intents
           SET answer_kind = 'band_cards',
               answer_ref  = '/api/talk/price-facts',
               answer_body = NULL
         WHERE intent_key IN ('discount', 'price_compare', 'gpu_compare', 'price_trend');
    """)


def downgrade() -> None:
    # 0061~0063 과 같은 규칙 — 지우지도 되돌리지도 않는다. 운영자가 이미 이 행들을
    # 고쳤을 수 있고, downgrade 로 옛 고정 문구를 되살리면 A-99 확정을 무효로 만든다.
    pass
