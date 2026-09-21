# -*- coding: utf-8 -*-
"""0112: game_customer_copy 에 «사람 검수» 칸을 붙인다 — 반려 사유 · 생성기 원문 보존

배경(2026-09-21 사장님 확정): "검수 화면을 짓고 86종을 보신 뒤 견적 화면에 쓴다".
0103 이 만든 표는 검수 «통과»만 표현할 수 있었다(reviewed_by / reviewed_at).
검수 화면을 지으려면 세 가지가 더 필요하다.

■ ① 반려를 «통과»로 오독하지 않게 한다 — review_state
  0103 의 유일한 신호는 `reviewed_by IS NOT NULL` 이고, `api/talk_answer.py`
  (load_game_facts)가 **그 조건 하나로** 고객 노출을 가른다. 반려를 표현하려고
  reviewed_by 에 반려자 이름을 적으면 **반려한 문구가 즉시 고객에게 나간다.**
  그래서 상태를 별도 칸으로 둔다:
      대기   아직 아무도 보지 않았다 (기본값 · 지금 86/86)
      승인   사람이 통과시켰다 -> reviewed_by/at 이 찬다 -> 고객에게 나간다
      반려   사람이 «이대로는 못 낸다»고 판정했다 -> reviewed_by 는 NULL 그대로

  ★ 그 규약을 DB 가 지킨다 — `ck_game_customer_copy_review_state` 체크 제약.
    (review_state='승인') 과 (reviewed_by IS NOT NULL) 이 **항상 같은 값**이어야 한다.
    코드가 실수로 반려에 reviewed_by 를 적으면 INSERT/UPDATE 가 거부된다.
    이 한 줄이 「검수 안 된 문구가 고객에게 나가지 않는다」를 애플리케이션 밖에서
    한 번 더 받친다 — 읽는 쪽(talk_answer)을 고치지 않고 지킬 수 있는 유일한 자리다.

■ ② 되돌리기는 삭제가 아니라 «역전이»다
  승인을 물리면 review_state 가 '대기' 로, reviewed_by/at 이 NULL 로 돌아간다.
  행을 지우지 않는다 — 누가 언제 승인했다 물렸는지는 활동 로그
  (`admin_operator_activity_logs`, target_kind='game_copy')가 갖는다.
  그래서 이 마이그레이션은 이력표를 새로 만들지 않는다(없는 요구를 미리 짓지 않는다 —
  0103 이 같은 판단을 이미 적어 두었다).

■ ③ 생성기 원문을 보존한다 — original_*
  검수자가 문구를 고쳐서 승인하면, **고친 뒤 문장만 남으면 «사람이 무엇을 고쳤는가»를
  영영 알 수 없다.** 그건 생성기(tools/game_copy_refresh9.py)를 고칠 때의 재료다.
  네 문단 각각의 «기계가 쓴 원문»을 첫 수정 시점에 한 번만 복사해 둔다(그 뒤 재수정은
  original_* 를 건드리지 않는다 — 원문은 «최초 기계 출력» 하나여야 한다).

  왜 활동 로그의 detail 에만 담지 않는가: 로그는 «사건»의 기록이라 행을 따라다니지
  않는다. 「이 게임의 기계 원문이 무엇이었나」를 알려면 로그 5,000행을 뒤져야 하고,
  그 로그는 보존 기간 정책이 생기면 지워질 수 있다. 원문은 행의 «상태»이므로 행에 둔다.
  (로그에도 before/after 를 남긴다 — 두 벌이 아니라 쓰임이 다르다: 로그는 «누가 언제»,
   이 칸은 «지금 이 행의 기계 원문».)

■ 이 마이그레이션이 하지 않는 것
  - `api/talk_answer.py` 의 조회 조건을 바꾸지 않는다(코드 무수정으로 나가게 둔다)
  - games 의 어떤 컬럼도 건드리지 않는다
  - 행을 넣거나 기존 값을 바꾸지 않는다(86행 전부 review_state 기본값 '대기' 로 채워진다 —
    reviewed_by 가 0/86 이라 체크 제약이 기존 데이터와 충돌하지 않는다. 실측 확인 후 적용)
"""
import sqlalchemy as sa
from alembic import op

revision = "0112"
down_revision = "0111"
branch_labels = None
depends_on = None

# 상태 어휘 — 화면·API 가 이 값을 서버에서 받아 간다(화면 하드코딩 금지).
STATES = ("대기", "승인", "반려")


def upgrade() -> None:
    op.add_column("game_customer_copy", sa.Column(
        "review_state", sa.String(10), nullable=False, server_default="대기",
        comment="대기 / 승인 / 반려. '승인'일 때만 reviewed_by 가 찬다(체크 제약)"))
    op.add_column("game_customer_copy", sa.Column(
        "reject_reason", sa.Text, nullable=True,
        comment="반려 사유. 반려일 때만 의미가 있다 — 왜 못 내보내는지를 적는다"))
    op.add_column("game_customer_copy", sa.Column(
        "reviewed_note", sa.Text, nullable=True,
        comment="승인자 메모(선택). 고객에게 나가지 않는다"))

    for col in ("spec_summary_ko", "why_this_pc", "upgrade_hint", "caution"):
        op.add_column("game_customer_copy", sa.Column(
            "original_" + col, sa.Text, nullable=True,
            comment="생성기가 쓴 원문. 사람이 처음 고칠 때 한 번만 채운다(NULL = 미수정)"))

    op.create_check_constraint(
        "ck_game_customer_copy_review_state",
        "game_customer_copy",
        "review_state IN ('대기','승인','반려')",
    )
    # ★ 핵심 불변식 — 승인과 검수자 이름은 반드시 함께 있거나 함께 없다.
    #   이게 「검수 안 된 문구는 고객에게 나가지 않는다」를 DB 가 받치는 자리다.
    op.create_check_constraint(
        "ck_game_customer_copy_reviewed_pair",
        "game_customer_copy",
        "(review_state = '승인') = (reviewed_by IS NOT NULL)",
    )
    op.create_index("ix_game_customer_copy_review_state",
                    "game_customer_copy", ["review_state"])


def downgrade() -> None:
    op.drop_index("ix_game_customer_copy_review_state",
                  table_name="game_customer_copy")
    op.drop_constraint("ck_game_customer_copy_reviewed_pair",
                       "game_customer_copy", type_="check")
    op.drop_constraint("ck_game_customer_copy_review_state",
                       "game_customer_copy", type_="check")
    for col in ("caution", "upgrade_hint", "why_this_pc", "spec_summary_ko"):
        op.drop_column("game_customer_copy", "original_" + col)
    op.drop_column("game_customer_copy", "reviewed_note")
    op.drop_column("game_customer_copy", "reject_reason")
    op.drop_column("game_customer_copy", "review_state")
