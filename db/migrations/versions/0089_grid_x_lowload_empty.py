"""0089 — 팝콘 X 저부하 용도 5칸 intended_empty=true (2026-09-13 사장님 확정)

배경: 슬롯별 정렬(RAM·SSD 는 규칙 충족 중 최저가 — 「정직하게」)을 적용한 첫 배치(20260913-03)
에서 팝콘 X(800~1,500만) 의 개발·영상편집·온라인게임·디자인(인텔) + 디자인(AMD) 5칸이
`below_tier_min` 으로 실패했다 — 정직하게 만든 최상급 구성(RTX 5080 + 울트라9 285K + 64GB)이
775~782만이라 X 하한 800만에 못 미친다.

시장도 같다: 협력사 크롤(analysis.md (b) 팝콘X n=18) 에서 이 용도 라벨은 개발 0 · 디자인 1 ·
온라인게임 1 · 영상편집 3(그나마 5090). 「800만 이상 개발용 PC」는 시장에 없는 물건이다.
억지로 채우려면 128GB 램을 다시 넣어야 하는데 그것은 0087 이 「정직하게」로 지운 것이다.

이 5칸을 비우면 고객이 그 예산에 그 용도를 말했을 때 격자 API 가 팝콘 9 카드(732만 등)를
「예산 안」으로 정직하게 답한다 — 「이 예산엔 이 용도의 상위 구성이 없습니다」가 맞는 말이다.

⚠ 재고가 바뀌어 5080 이 더 비싸지거나 새 부품이 들어와 800만을 넘기게 되면 이 판정은 낡는다.
그때는 intended_empty 를 false 로 되돌리고 배치를 다시 돌린다 — 이 파일 downgrade 가 그것이다.
"""
from alembic import op

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None

CELLS = [
    ("팝콘 X", "개발·프로그래밍", "인텔"),
    ("팝콘 X", "영상편집·방송", "인텔"),
    ("팝콘 X", "온라인게임 (라이트~중급)", "인텔"),
    ("팝콘 X", "디자인·3D설계", "인텔"),
    ("팝콘 X", "디자인·3D설계", "AMD"),
]


def _where(t, u, p):
    return f"tier='{t}' AND usage='{u}' AND platform='{p}'"


def upgrade() -> None:
    for t, u, p in CELLS:
        op.execute(f"UPDATE grid_cells SET intended_empty=true WHERE {_where(t, u, p)}")
    # 실패 현재본은 그대로 둔다(원장) — grid_public 은 intended_empty 를 먼저 보고 사유를 낸다.


def downgrade() -> None:
    for t, u, p in CELLS:
        op.execute(f"UPDATE grid_cells SET intended_empty=false WHERE {_where(t, u, p)}")
