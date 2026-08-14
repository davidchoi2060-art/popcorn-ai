# -*- coding: utf-8 -*-
"""운영 도우미 FAQ·답할 범위를 데이터로 — ops_assistant_faqs · ops_assistant_scopes
(ADM-AI-070 운영 도우미 설정, 2026-08-13).

■ 왜 필요한가
  `mockups/shared/admin-helper.js`(운영 도우미 위젯 본체)의 FAQ 5개·바로가기는 지금
  파일 안 JS 상수(`FAQ` 배열)로만 존재한다 — DB도, 별도 코드 모듈도 아니다. 이 화면이
  없으면 FAQ를 바꾸는 유일한 방법이 코드를 고쳐 배포하는 것뿐이다
  (`docs/design/req/req-ops-assistant.md` ③). 그래서 이 축을 데이터로 옮긴다.

  이 마이그레이션은 **설정 화면(ADM-AI-070)이 편집하는 원천**만 만든다 — 위젯
  자신(`admin-helper.js`)이 이 표를 읽도록 배선하는 것은 이번 범위 밖이다(그 파일은
  제작팀 C의 담당 파일이 아니라 건드리지 않았다). 그래서 화면은 "저장하면 위젯에
  즉시 반영됩니다"라고 말하지 않는다 — 아직 거짓이기 때문이다.

■ 시드 값 — **코드 상수를 그대로 옮겨 적는다**(0014의 선례와 같은 원칙)
  `admin-helper.js`의 FAQ 5개를 질문·답변·바로가기까지 **한 글자도 안 고치고** 옮긴다.
  바로가기는 지금도 옛 admin 상대경로(`review-queue.html` 등)다 — admin2 기준으로는
  전부 깨져 있다(실측: 고유 7경로 중 admin2 라우트와 문자 그대로 일치하는 것 0/7,
  `ai-screens-datamap.md` §5-⑥). **일부러 고쳐 넣지 않는다**: 어떤 admin2 화면이
  어떤 옛 화면을 대체하는지는 사람이 결정할 일이고(요구사항 문서 "사장님 결정이 필요한
  지점" #3, 아직 미정), 마이그레이션이 조용히 다른 값으로 바꿔치면 그 판단을 대신하게
  된다. 화면(`/admin2/ops-assistant`)이 "깨진 바로가기 N곳"을 실제 라우트와 대조해
  세어 보여주고, owner가 드롭다운에서 **지금 존재하는 admin2 경로**로 직접 고친다.

■ 답할 범위(`ops_assistant_scopes`) — 9개, 잠금 3개
  회원 개인정보·매입가·마진·관리자 계정은 `locked=true`로 시드한다 — 화면에서 켤 수
  없다(요구사항 문서 ⑦). 잠금은 이 표의 데이터로 표현하지, 화면 코드의 if문으로
  숨기지 않는다 — 나중에 잠금 사유가 바뀌어도 데이터만 고치면 된다.

■ 재구축·복구에도 남는다
  `spec_field_defs`(0014)·`usage_floors`(0016)와 같은 이유 — 운영 규칙을 시드
  SQL(`db/seed/*.sql`, 더미 상품·주문 포함)이 아니라 마이그레이션에 둬야 빈 DB에서
  시작해도(`docs/07_운영-시작-순서.md`) 이 화면이 죽지 않는다.

■ 미적용 상태에서도 화면이 죽지 않는다
  이 파일이 `alembic upgrade`로 적용되기 전에도 `GET /api/admin/ops-assistant`는
  `to_regclass('public.ops_assistant_faqs')`로 표 존재 여부를 먼저 확인하고,
  없으면 `ready:false` + "원천 준비 중" 안내만 반환한다(500 대신) — `api/admin_ops_
  assistant.py`가 그 가드를 담당한다.

■ down_revision 관련 메모(제작 보고서에도 남김)
  제작 지시는 "0048 고정, A는 0046, B는 0047"이었다 — 세 제작자가 동시에 화면을
  짓는 동안 **파일명 충돌만** 막기 위한 번호 배정으로 읽었다. 실제 `down_revision`은
  지시대로 "0047"에 고정하지 않고 **이 저장소의 현재 실제 head(0045)**를 가리킨다 —
  0046·0047 파일이 이 작업 시점에 아직 없어(실측), 존재 여부를 모르는 리비전을
  가리키면 그 리비전이 끝내 안 생기거나 다른 내용으로 생길 경우 alembic 이 통째로
  멈춘다(이 프로젝트가 이미 겪은 "없는 리비전을 가리키면 다음 배포가 멈춘다" 함정,
  `api/admin_spec_fields.py` 주석 참조). 세 사람이 각자 0045에서 갈라지면 브랜치가
  생기는데, 이는 alembic이 `alembic merge heads`로 정상 처리하는 흔한 경우다 —
  DBA가 세 마이그레이션을 합칠 때 병합 리비전 하나만 추가하면 된다.

Revision ID: 0048
Revises: 0046
"""
from alembic import op

revision = "0048"
down_revision = "0046"
branch_labels = None
depends_on = None


# FAQ 5개 — admin-helper.js의 FAQ 배열을 그대로 옮긴다(문구 변경 없음).
# (question, answer, links=[(label, path), ...])
FAQS = [
    ("이 상품이 왜 추천에 안 나오죠?",
     "추천에 들어가려면 네 가지를 모두 통과해야 합니다 — 필수 사양이 채워졌고, "
     "검수가 끝났고, 판매가가 있고, 재고가 남아 있어야 합니다. "
     "하나라도 비면 후보에서 빠집니다.",
     [("상품 검수", "review-queue.html"), ("후보 풀 현황", "candidate-pool.html")]),
    ("검수 대기가 뭔가요?",
     "사양이 비어 있어 추천에 쓸 수 없는 상품입니다. 값을 채우면 그 자리에서 "
     "게이트를 다시 판정합니다. 전체보다 <b>판매중·재고 있는 것</b>부터 보시면 됩니다.",
     [("상품 검수", "review-queue.html")]),
    ("판매가는 어떻게 정해지나요?",
     "매입가에 마진 정책을 적용해 산정합니다. 단가표를 반영하면 해당 상품의 "
     "판매가가 다시 계산되고, 변동이 크면 검토 대기로 올라옵니다.",
     [("마진 정책", "margin-policy.html"), ("가격 검토", "price-review.html"),
      ("단가표 반영", "price-import.html")]),
    ("재고는 어디서 넣나요?",
     "재고 입고 화면에서 넣습니다. 재고가 0이거나 안전재고보다 적은 상품이 "
     "목록에 올라옵니다.",
     [("재고 입고", "stock-inbound.html")]),
    ("잘못 고쳤어요. 되돌릴 수 있나요?",
     "작업 기록에서 되돌릴 수 있습니다. 값만 되돌리는 게 아니라 잠금과 게이트 상태까지 "
     "함께 되돌립니다. 다만 <b>일괄 적재는 되돌릴 수 없습니다</b>.",
     [("작업 기록", "activity-logs.html")]),
]

# 답할 범위 9종 — (scope_key, label, enabled 초기값, locked, lock_note, sort_order)
# 잠긴 셋(회원 개인정보·매입가·마진·관리자 계정)은 enabled=false 로 고정 시드한다 —
# 화면에서 켤 수 없다(요구사항 문서 ⑦, 개인정보·원가·권한 노출 위험).
SCOPES = [
    ("product_specs", "상품 사양", True, False, None, 10),
    ("stock_qty", "재고 수량", True, False, None, 20),
    ("review_status", "검수 상태", True, False, None, 30),
    ("compat_check", "조립 호환 판정", True, False, None, 40),
    ("order_status", "주문 상태", False, False, None, 50),
    ("sell_price", "판매가", False, False, None, 60),
    ("member_pii", "회원 개인정보", False, True, "개인정보 — 답변 대상이 될 수 없습니다", 70),
    ("cost_margin", "매입가·마진", False, True, "원가 정보 — 답변 대상이 될 수 없습니다", 80),
    ("admin_accounts", "관리자 계정", False, True, "권한 정보 — 답변 대상이 될 수 없습니다", 90),
]


def _links_json(links) -> str:
    import json
    return json.dumps([{"label": lb, "path": pt} for lb, pt in links], ensure_ascii=False)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ops_assistant_faqs (
            faq_id       SERIAL PRIMARY KEY,
            sort_order   INTEGER      NOT NULL,
            question     VARCHAR(200) NOT NULL,
            answer       TEXT         NOT NULL,
            -- [{"label": "...", "path": "..."}, ...] — 최대 2개는 화면(API)이 강제한다
            links        JSONB        NOT NULL DEFAULT '[]'::jsonb,
            created_at   TIMESTAMP    NOT NULL DEFAULT now(),
            updated_at   TIMESTAMP    NOT NULL DEFAULT now(),
            updated_by   INTEGER
        );
        CREATE INDEX idx_ops_assistant_faqs_sort ON ops_assistant_faqs (sort_order);

        CREATE TABLE ops_assistant_scopes (
            scope_key    VARCHAR(40)  PRIMARY KEY,
            label        VARCHAR(60)  NOT NULL,
            enabled      BOOLEAN      NOT NULL DEFAULT false,
            -- locked=true 는 "끌 수 없다"가 아니라 "켤 수 없다" — 잠긴 항목은 항상 미답변 대상
            locked       BOOLEAN      NOT NULL DEFAULT false,
            lock_note    VARCHAR(160),
            sort_order   INTEGER      NOT NULL DEFAULT 0,
            updated_at   TIMESTAMP    NOT NULL DEFAULT now(),
            updated_by   INTEGER
        );
    """)

    conn = op.get_bind()
    for i, (q, a, links) in enumerate(FAQS):
        conn.exec_driver_sql(
            "INSERT INTO ops_assistant_faqs (sort_order, question, answer, links)"
            " VALUES (%s, %s, %s, %s::jsonb)",
            ((i + 1) * 10, q, a, _links_json(links)))
    for key, label, enabled, locked, lock_note, order in SCOPES:
        conn.exec_driver_sql(
            "INSERT INTO ops_assistant_scopes"
            " (scope_key, label, enabled, locked, lock_note, sort_order)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (key, label, enabled, locked, lock_note, order))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ops_assistant_faqs")
    op.execute("DROP TABLE IF EXISTS ops_assistant_scopes")
