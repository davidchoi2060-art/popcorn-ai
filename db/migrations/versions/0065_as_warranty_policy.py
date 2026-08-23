# -*- coding: utf-8 -*-
"""talk_intents.as_warranty answer_body 를 확정 정책 문구로 UPDATE (2026-08-23, A-105).

■ 왜
  `as_warranty`(A/S·보증) 인텐트는 0062 에서 "무상 보증 2년, 왕복 택배비는 저희
  부담입니다. 초기 불량은 수령 7일 내 교환, 지원은 전화·원격·용산 방문 세 가지예요.
  (*정책 확정 전 예시)" 로 심어졌다. 이 문구는 몰(popcornpc.co.kr) 정책 원문과
  대조된 적 없는 예시값이었다 -- `docs/design/as-policy-options-2026-08-23.md` §②
  가 curl 원문(EUC-KR)을 직접 받아 대조한 결과, 완제PC는 "3년 무상(로젠택배
  이용 시)", 맞춤PC(부품 조합 주문)는 "1년, 그것도 자체 보증이 아니라 각 부품
  제조사 규정을 따르는 것"이었다 -- 우리 문구의 "2년"은 두 숫자(3년·1년) 어느
  쪽과도 다른 제3의 수였고, "전화·원격·용산 방문" 세 지원채널도 몰 정책 원문에
  없었다(§③ -- 샵다나와의 "전국 120개 AS센터 무상 방문 출장"과 혼동됐을 가능성).

■ 인계 트랙 = 맞춤PC (A-105 근거)
  `create_handoff()` 가 만드는 `lines` 는 부품마다 별도 원소(`kind:"core_part"`,
  code=`product_code`) + 조립비 1개(`kind:"assembly_service"`, code=92983) 구조다
  -- 완제PC 단일 SKU 로 묶는 코드는 없다. 그래서 완제PC 의 3년 무상이 아니라
  맞춤PC 의 "1년·제조사 규정" 트랙이 적용된다 -- 사장님이 안 1(몰 맞춤PC 정책
  그대로)을 확정했다(`docs/decisions/decision-log.md` A-105, 2026-08-23).

■ 이번 UPDATE 가 하는 일
  `as_warranty` 한 행의 `answer_body` 를 정본 문구(보증·초기·접수 세 줄 요지)로
  바꾼다. `match_terms`·`min_hits`·`status`·`answer_kind`·`answer_pack` 은
  손대지 않는다 -- 0064 가 `discount`·`price_compare`·`gpu_compare`·`price_trend`
  넷만 `band_cards` 로 옮긴 것과 달리, `as_warranty` 는 실계산이 필요 없는 고정
  정책 문구라 계속 `answer_kind='text'` 로 둔다(A-99 범위 밖 -- A-99 는 "계산
  없이 수치를 주장하는" 넷만 대상이었고 A/S 정책 문구는 계산이 아니라 확정된
  약관이다).

  화면 폴백(`mockups/mvp1/s1-session.html` 의 `TALKS` 배열, `as_warranty` 항목)도
  같은 물결에서 같은 문구로 맞췄다(제작자 C 담당) -- API 가 실패해도 팝콘톡이
  같은 답을 하도록.

■ 몰 정책 원문
  `docs/design/as-policy-options-2026-08-23.md` §②(popcornpc.co.kr, curl 원문
  대조 완료) -- "무상: 제품 구입 후 3년 이내(3년보증 완제 구입시, 로젠 택배
  이용시) / 맞춤PC의 구성부품의 A/S는 기본 1년간 보장되며, 해당제품 제조사
  규정에 의거하여 처리됩니다" / "제품 수령 후 7일 이내 제품불량시 교환이나
  환불에 필요한 운송료 전액(왕복)을 회사에서 부담합니다... 로젠 택배를
  이용하실 경우에만 해당" / "제품 구입 후 7일 이후의 소비자 변심에 의한 경우
  왕복 배송비는 고객님께서 부담".

■ 왜 UPDATE 이지 새 행이 아닌가
  같은 intent_key 로 이미 상담 원장(`talk_intent_hits.matched_terms`)과 화면
  `TALKS` 폴백이 그 이름을 참조한다. 새 키로 갈아타면 폴백·이력 조인이 갈라진다
  (0064 와 같은 이유).

■ downgrade
  0061~0064 와 같은 규칙 -- 지우지도 되돌리지도 않는다. 운영자가 이 행을 이미
  손으로 고쳤을 수 있고, downgrade 로 옛 "2년" 예시 문구를 되살리면 A-105 확정을
  무효로 만든다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None

_AS_WARRANTY_BODY = (
    "맞춤PC 구성 부품의 A/S는 <b>기본 1년</b>이며, 각 부품 제조사의 보증 규정을 "
    "따릅니다.<br>수령 후 <b>7일 이내</b> 제품 불량은 교환·환불 운송료(왕복)를 "
    "팝콘PC가 부담합니다(로젠택배 이용 시).<br>A/S·교환 접수는 "
    "<b>팝콘PC 쇼핑몰 고객센터</b>에서 진행됩니다."
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE talk_intents SET answer_body = :body WHERE intent_key = 'as_warranty'"
        ).bindparams(body=_AS_WARRANTY_BODY)
    )


def downgrade() -> None:
    # 0061~0064 와 같은 규칙 — 지우지도 되돌리지도 않는다. 운영자가 이미 이 행을
    # 고쳤을 수 있고, downgrade 로 "2년" 예시 문구를 되살리면 A-105 확정을 무효로
    # 만든다.
    pass
