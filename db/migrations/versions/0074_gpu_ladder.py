# -*- coding: utf-8 -*-
"""GPU 성능 서열표 — gpu_ladder

■ 왜 개별 GPU 모델 표가 필요한가
  엔진의 용도 하한(`usage_floors`, CLAUDE.md §용도 하한)은 GPU 성능 지표가 없어
  `required_power_watt`(300/550/750 3등급)를 성능 근사축으로 쓴다. 이 등급은
  거칠다 — 550W 등급 하나에 RTX 3050(상대성능 21.9%)과 RX 9070 XT(76.9%)가
  같이 묶인다. 게임 판정(`docs/design/game-quote-mapping-2026-09-07.md` §1)이
  "이 견적으로 이 게임이 되는가"를 답하려면 3단계보다 촘촘한 서열이 필요해
  `gpu_ladder`를 신설한다. `usage_floors`를 대체하지 않는다 — 전력 배분(파워
  용량 산정)은 여전히 `required_power_watt` 소관이고, 이 표는 성능 서열만 맡는다
  (같은 개념 두 벌 금지, CANON §1과 무관한 별개 축).

■ chipset 은 `api/catalog_map.gpu_chipset_key()` 정규형과 같은 어휘여야 한다
  이 함수가 상품명에서 뽑는 키는 `"{그룹1.upper()} {그룹2}{suffix.upper()}"`
  형태다(예: "RTX 5070 Ti" → "RTX 5070 TI", "RX 9070 XT" → "RX 9070 XT").
  이 표의 `chipset` 값도 그 형태 그대로 넣는다 — 로더가 상품 → 서열 매핑을
  문자열 대조로 하므로, 어휘가 갈리면 매핑이 조용히 실패한다(NULL 매칭이지
  에러가 아니다).
  예외: 팝콘PC 판매몰이 "RTX 5090 XT"(워터블럭 변형)로 표기하는 상품이 있는데,
  이는 `gpu_chipset_key()`가 별도 키("RTX 5090 XT")로 뽑아낸다. 이 표에는
  "RTX 5090" 한 행만 두고 note에 흡수 규칙을 적는다 — 로더가 매핑 시점에
  suffix "XT"를 접두 칩셋과 같은 세대로 합칠지는 로더 구현 소관이다(이
  마이그레이션은 표만 짓는다).

■ vram_gb 는 정확 매칭이 아니라 판정용 근사값이다
  RTX 5060 Ti·RX 9060 XT·RTX 3050은 재고에 VRAM 용량이 다른 변형이 혼재한다
  (예: RTX 5060 Ti 8GB/16GB). chipset 자체가 UNIQUE라 용량별로 행을 나누지
  않고, 실제로 더 많이 유통되는 쪽을 대표값으로 채택했다 — note에 혼재 사실과
  대표값 채택 근거를 남긴다. 정확한 VRAM은 `product_specs`에서 상품별로 읽는다.

■ ladder_score 출처
  정본 = Tom's Hardware GPU Hierarchy, 1440p Ultra 상대성능(%), RTX 5090=100
  기준, 2026-09-07 확인. 표에 직접 없는 2종(RX 9060 non-XT·GTX 1660 SUPER)은
  2차 출처로 추정 계산했고, note에 계산식과 출처를 남긴다(추정값임을 숨기지
  않는다 — CLAUDE.md §화면 정직성과 같은 원칙을 데이터에도 적용).

■ 시드 건수
  `docs/design/game-quote-mapping-2026-09-07.md` §1이 "재고 실측 17종"이라
  적었으나, 같은 절이 확정한 값 목록 자체는 16종이다(RX 7900 XT까지 포함해
  16행). 지어내지 않고 받은 값 그대로 16행만 넣는다 — 17번째 칩셋이 무엇인지는
  문서 쪽에서 확인이 필요하다(기록자에게 전달).

Revision ID: 0074
Revises: 0073
"""
import sqlalchemy as sa
from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


TOMS_URL = "https://www.tomshardware.com/reviews/gpu-hierarchy,4388.html"

# (chipset, ladder_score, vram_gb, source_url, checked_date, note)
# chipset 은 api/catalog_map.gpu_chipset_key() 정규형과 같은 표기.
GPU_LADDER = [
    ("RTX 5090", "100.0", 32, TOMS_URL, "2026-09-07",
     "팝콘PC 판매몰 표기 'RTX 5090 XT'(워터블럭 변형)도 같은 칩셋 — "
     "gpu_chipset_key()는 이를 별도 키로 뽑으므로 로더가 흡수해야 함"),
    ("RTX 5080", "81.9", 16, TOMS_URL, "2026-09-07", None),
    ("RTX 5070 TI", "76.2", 16, TOMS_URL, "2026-09-07", None),
    ("RX 9070 XT", "76.9", 16, TOMS_URL, "2026-09-07", None),
    ("RX 9070", "69.1", 16, TOMS_URL, "2026-09-07", None),
    ("RTX 5070", "65.1", 12, TOMS_URL, "2026-09-07", None),
    ("RTX 5060 TI", "51.6", 16, TOMS_URL, "2026-09-07",
     "재고 8GB/16GB 혼재 — 대표 VRAM 16GB, 판정용 근사치(정확 매칭 아님)"),
    ("RX 9060 XT", "48.2", 16, TOMS_URL, "2026-09-07",
     "재고 8GB/16GB 혼재 — 대표 VRAM 16GB, 판정용 근사치(정확 매칭 아님)"),
    ("RX 7600", "34.3", 8, TOMS_URL, "2026-09-07", None),
    ("RX 7900 XT", "71.3", 20, TOMS_URL, "2026-09-07", None),
    ("RTX 5060", "43.4", 8, TOMS_URL, "2026-09-07", None),
    ("RTX 5050", "34.0", 8, TOMS_URL, "2026-09-07", None),
    ("RTX 3060", "30.2", 12, TOMS_URL, "2026-09-07",
     "Tom's Hardware 표는 'RTX 3060 12GB' 단일 항목 — 우리 재고와 일치"),
    ("RTX 3050", "21.9", 6, TOMS_URL, "2026-09-07",
     "Tom's Hardware 표 RTX 3050 값 그대로 — 재고는 6GB/8GB 혼재하나 "
     "표가 용량별로 나뉘어 있지 않아 대표값 채택(판정용 근사치)"),
    ("RX 9060", "41.7", 8,
     "https://videocardz.com/newz/amd-radeon-rx-9060-non-xt-has-been-"
     "tested-13-14-slower-than-rx-9060-xt-8gb", "2026-09-07",
     "Tom's Hardware 표에 직접 없음 — RX 9060 XT(48.2) 대비 13.5% 느림"
     "(videocardz.com 실측 'RX 9060 non-XT has been tested 13-14% slower "
     "than RX 9060 XT')으로 추정 계산: 48.2*0.865=41.7"),
    ("GTX 1660 SUPER", "23.2", 6,
     "https://dropreference.com/en/compare/gpu/nvidia-geforce-gtx-1660-"
     "super-vs-nvidia-geforce-rtx-3050-6gb", "2026-09-07",
     "Tom's Hardware 표에 직접 없음 — RTX 3050(21.9) 대비 +6%"
     "(dropreference.com 'GTX 1660 Super is on average 6% faster than "
     "the RTX 3050')으로 추정 계산: 21.9*1.06=23.2"),
]


def upgrade() -> None:
    op.create_table(
        "gpu_ladder",
        sa.Column("gpu_id", sa.Integer, primary_key=True),
        sa.Column("chipset", sa.String(40), nullable=False, unique=True),
        sa.Column("ladder_score", sa.Numeric(5, 1), nullable=False),
        sa.Column("vram_gb", sa.Integer, nullable=False),
        sa.Column("source_url", sa.String(300), nullable=False),
        sa.Column("checked_date", sa.Date, nullable=False),
        sa.Column("note", sa.String(200)),
    )
    op.execute(
        "COMMENT ON TABLE gpu_ladder IS "
        "'GPU 칩셋당 1행 — 상대성능 서열(RTX 5090=100 기준). chipset은 "
        "api/catalog_map.gpu_chipset_key() 정규형과 같은 어휘. "
        "docs/design/game-quote-mapping-2026-09-07.md §1'"
    )

    conn = op.get_bind()
    for chipset, score, vram, source_url, checked_date, note in GPU_LADDER:
        conn.execute(sa.text(
            "INSERT INTO gpu_ladder "
            "(chipset, ladder_score, vram_gb, source_url, checked_date, note) "
            "VALUES (:chipset, :score, :vram, :source_url, :checked_date, :note)"
        ), {
            "chipset": chipset,
            "score": score,
            "vram": vram,
            "source_url": source_url,
            "checked_date": checked_date,
            "note": note,
        })
    print(f"[0074] gpu_ladder 시드: {len(GPU_LADDER)}건")


def downgrade() -> None:
    op.drop_table("gpu_ladder")
