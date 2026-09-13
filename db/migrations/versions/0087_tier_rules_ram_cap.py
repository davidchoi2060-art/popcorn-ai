"""0087 — usage_tier_rules 에 RAM 상한(lte) 행 — 「정직하게」(2026-09-13 사장님 확정)

배경: 배분율(0086) 적용 뒤 첫 배치(20260913-01)에서 팝콘 X(800~1,500만) 의 개발·영상편집·
디자인 칸이 **128GB 램(328만)** 으로 예산을 채웠다. 규칙(0085)엔 RAM 하한(gte)만 있고 상한이
없어, 배분 상한(RAM 25~30%) 안에서 가장 비싼 램을 잡은 것이다. 협력사 크롤(analysis.md (a)·(d))
에서 128GB 는 **1,500만 초과 워크스테이션에서만** 나온다(팝콘 X 800~1,500만 n=18 은 64GB 88%).

사장님 원문: *"정직하게 해.. 굳이 1500만원을 맞추라는 의미가 아니야"* — 용도에 맞는 구성이
900만원이면 900만원 카드가 맞다. 예산을 채우려고 시장에 없는 구성을 만들지 않는다.

이 행들이 표현하는 것: 「X 티어에서 개발·영상편집·디자인의 RAM 은 64GB 까지」.
api/usage_tier_rules.for_usage 가 (slot, field, op) 로 키를 잡도록 같은 날 고쳐 gte·lte 가 공존한다.

AI 작업은 상한을 두지 않는다 — 시장 팝콘 X AI(n=13)는 64GB 92% 이지만 1,500만 경계 근처에서
128GB 로 넘어가는 것이 자연스럽고(X초과 AI n=25 는 128GB 68%), 배분 상한(RAM 30%)이 이미 잡는다.
게임 둘도 상한 없음 — 게임 RAM 규칙은 gte 32 뿐이고 배분(RAM ≤25%)이 잡는다(실측 X 고사양게임 64GB).
"""
from alembic import op

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None

ROWS = [
    # (usage_key, budget_min, slot, field, op, value, label, note)
    ("dev",    8000000, "RAM", "capacity_gb", "lte", 64,
     "개발 메모리 상한", "X 800~1500만 RAM 64GB 88%(n=18) · 128GB 는 1500만 초과에서만 — 정직하게(2026-09-13)"),
    ("video",  8000000, "RAM", "capacity_gb", "lte", 64,
     "영상편집 메모리 상한", "X 영상편집 64GB 100%(n=3) · 128GB 는 8K/VFX·1500만 초과 — 정직하게(2026-09-13)"),
    ("design", 8000000, "RAM", "capacity_gb", "lte", 64,
     "디자인 메모리 상한", "X 디자인 64GB(n=1) · X초과 디자인 128GB 는 1500만 초과(n=4) — 정직하게(2026-09-13)"),
]


def upgrade() -> None:
    for uk, bmin, slot, field, o, val, label, note in ROWS:
        op.execute(
            "INSERT INTO usage_tier_rules (usage_key, budget_min, slot, field, op, value, label, active, note, sort_order)"
            f" VALUES ('{uk}', {bmin}, '{slot}', '{field}', '{o}', {val}, '{label}', true, '{note}', 900)"
        )


def downgrade() -> None:
    op.execute("DELETE FROM usage_tier_rules WHERE op='lte' AND budget_min=8000000 AND slot='RAM'"
               " AND usage_key IN ('dev','video','design')")
