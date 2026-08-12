# -*- coding: utf-8 -*-
"""시연용 상품이 고객 견적에 들어가지 않게 — 후보 뷰에서 `demo` 제외 (2026-08-11)

■ 어떻게 드러났나
  S4 인계를 만들다가 나왔다. 견적에 든 부품 8개의 몰 가격을 재확인했는데 둘이 0원으로
  돌아왔다. 코드가 8자리(2천만 대)였고, 전부 `data_origin='demo'` — **몰에 없는
  시연용 가짜 상품**이었다. 상세 페이지는 200 으로 열리는데 가격 필드가 비어 나온다.

      20483003  삼성 DDR5-5600 32GB   95,000원  (몰에 없음)
      20486102  WD Blue SN580 500GB   55,000원  (몰에 없음)

  **인계를 만들지 않았으면 오픈 후에 고객이 발견했을 것이다.** 장바구니에 담기지 않는
  부품이 견적에 들어 있는 상태로 나갔을 것이고, 그 자리에서 신뢰가 깨진다.

■ 무엇이 문제였나
  후보 뷰가 `data_origin` 을 **컬럼으로 읽기만 하고 조건으로 걸지 않았다.**
  `v_companion_candidates` 는 아예 보지도 않았다. 4중 게이트(사양·검수·후보·가격)가
  전부 통과되니 demo 23건이 진짜처럼 추천되고 있었다.

■ 왜 플래그가 아니라 뷰인가
  `ai_candidate_yn=false` 로 꺼도 되지만, 그러면 「후보가 아님」과 「시연용임」이 한 칸에
  섞이고 누군가 다시 켜면 조용히 되살아난다. **뷰에서 막으면 구조적으로 못 들어온다** —
  이 프로젝트가 미검증 부품에 쓰는 원칙과 같다.

■ 영향 (적용 전 실측)
  demo 는 전체 22,840건 중 **45건**. 제외해도 슬롯마다 44~801개가 남는다.
      CASE 803->801 · CPU 227->224 · GPU 353->347 · SSD 273->269 · 주변기기 1043->1038
"""
from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

# `IS DISTINCT FROM` 을 쓴다 — data_origin 이 NULL 인 행도 통과시켜야 한다(= real 취급).
COND = "p.data_origin IS DISTINCT FROM 'demo'::character varying"


def _patch(conn, view: str, add: bool):
    """뷰 정의를 읽어 WHERE 에 조건을 더하거나 뺀다.

    **정의를 다시 쓰지 않고 조건만 얹는다.** 뷰 본문이 길고(컬럼 40여 개) 다시 쓰면
    나중에 컬럼이 추가됐을 때 조용히 되돌린다 — 0036 에서 같은 실수를 할 뻔했다.
    """
    d = conn.execute(sa.text(
        "SELECT pg_get_viewdef('%s'::regclass, true)" % view)).scalar()
    d = d.strip().rstrip(";")
    if add:
        if COND in d:
            return False
        d = d + "\n  AND " + COND
    else:
        if COND not in d:
            return False
        d = d.replace("\n  AND " + COND, "")
    conn.execute(sa.text("CREATE OR REPLACE VIEW %s AS %s" % (view, d)))
    return True


def upgrade():
    conn = op.get_bind()
    for v in ("v_recommendation_candidates", "v_companion_candidates"):
        changed = _patch(conn, v, add=True)
        print("   %s : %s" % (v, "demo 제외 적용" if changed else "이미 적용됨"))


def downgrade():
    conn = op.get_bind()
    for v in ("v_recommendation_candidates", "v_companion_candidates"):
        _patch(conn, v, add=False)
