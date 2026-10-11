"""AI 답 점검 — 문의마다 고객에게 나간 답과 점검 상태 (2026-10-11 품질관리 · 관리자 확인 R1·R2·R7·R11).

AI 답은 어디에도 저장되지 않아 관리자가 「윈도우 깔아서 배송」 같은 약속을 볼 수 없었다.
문의 한 건(`talk_intent_hits`)마다 한 행을 둔다:

  ai_reply        모델이 낸 말풍선(서버가 바꾸기 전)
  shown_reply     고객이 실제로 본 말풍선
  answer          답변 경로 [B] 의 자유 답변
  flags           약속하는 말 자동 표시(「해 드릴게요」「확인했습니다」 등)
  question_key    같은 질문 묶음 키 — 마스킹된 문장을 정규화한 sha256. 원문은 싣지 않는다
  status · memo   관리자 점검(미확인 · 문제 있음 · 확인)

고객 문장 원문은 이 표에 두지 않는다(원문 단건 열람은 미정 — req-talk-patterns §9 ㉢).
AI 답은 고객 말을 되짚을 수 있으므로 원문과 같은 보관 기한(`purge_at`)을 둔다.
"""
from alembic import op

revision = '0138'
down_revision = '0137'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE talk_reply_reviews (
      hit_id BIGINT PRIMARY KEY REFERENCES talk_intent_hits(hit_id) ON DELETE CASCADE,
      ai_reply TEXT,
      shown_reply TEXT,
      answer TEXT,
      answer_error BOOLEAN NOT NULL DEFAULT FALSE,
      flags JSONB NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(flags)='array'),
      question_key VARCHAR(64) CHECK(question_key IS NULL OR length(question_key)=64),
      status VARCHAR(8) NOT NULL DEFAULT '미확인' CHECK(status IN ('미확인','문제 있음','확인')),
      memo TEXT CHECK(memo IS NULL OR length(memo) <= 500),
      reviewed_by BIGINT,
      reviewed_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      purge_at TIMESTAMPTZ)''')
    op.execute('CREATE INDEX talk_reply_reviews_q_idx ON talk_reply_reviews(question_key, created_at DESC)')
    op.execute('CREATE INDEX talk_reply_reviews_status_idx ON talk_reply_reviews(status, created_at DESC)')


def downgrade():
    op.execute('DROP TABLE talk_reply_reviews')
