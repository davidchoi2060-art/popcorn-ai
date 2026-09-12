"""용도×티어 구성 규칙 표 — usage_tier_rules (2026-09-12 사장님 확정).

설계 정본: docs/design/usage-tier-rules-2026-09-12.md
근거 자료: D:/Hermes-Workspace/crawl/analysis.md (협력사 3사 1,733건 · 표본 n 병기)

**아래 규칙 값은 시장 표본에서 옮겼다 — 지어내지 않았다.** 각 행의 note 에 설계 문서의
근거(표본 n·다수값 비율)를 그대로 적는다. 문서 표에서 용도 여러 개가 한 줄에 있으면
용도별로 펼쳐 행 하나씩 넣는다(usage_key 는 usage_floors 와 같은 어휘 —
game·gaming_high·video·ai·design·dev).

■ usage_floors 와 어떻게 다른가
  `usage_floors` 는 **용도당 하나의 하한 세트**다 — "게임이면 이 밑으로는 안 된다"는
  최저선이고 예산이 얼마든 같은 값이다. 그래서 티어별 차이(팝콘 5 AI RAM 32GB vs
  팝콘 X AI RAM 64GB)를 표현할 수 없고, BUDGET_ALLOC 은 전 용도 고정 배분이라 "같은
  예산에서 게임은 GPU 에, AI 는 RAM 에 쓴다"는 시장 행동도 못 담는다. 이 표는
  (usage_key, budget_min) 축을 가져 **하한 위에서 "이 예산 티어에선 이 급을 겨냥한다"**
  를 말한다. usage_floors 는 그대로 두고(하한 = 최저선), 엔진은 budget_min ≤ cap 인
  규칙 중 (usage_key, slot, field) 별로 budget_min 이 가장 큰 행 하나를 골라 후보를
  거른다. 하한과 달리 **걸러서 조합이 안 나오면 이 표만 풀고**(usage_floors 는 유지)
  근거에 그 사실을 남긴다 — 겨냥은 목표이지 조립 조건이 아니기 때문이다.

재실행 안전: 표는 IF NOT EXISTS, 행은 표가 비어 있을 때만 넣는다.

Revision ID: 0085
Revises: 0084
"""
from alembic import op
from sqlalchemy import text

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None


# (usage_key, budget_min, slot, field, op, value, label, note, sort_order)
# 티어 경계는 0082(팝콘5 150만 · 5+ 220만 · 7 300만 · 7+ 400만 · 9 550만 · X 800만).
RULES = [
    # ── GPU vram_gb (gte) — VRAM 단계가 가격을 결정한다(analysis (d)절) ─────────
    ("game",        1_500_000, "GPU", "vram_gb", "gte", 8,  "VRAM 8GB 이상",
     "5060/5060Ti 8GB — 팝콘5 57%(n=421)", 100),
    ("gaming_high", 1_500_000, "GPU", "vram_gb", "gte", 8,  "VRAM 8GB 이상",
     "5060/5060Ti 8GB — 팝콘5 57%(n=421)", 101),
    ("video",       1_500_000, "GPU", "vram_gb", "gte", 8,  "VRAM 8GB 이상",
     "5060/5060Ti 8GB — 팝콘5 57%(n=421)", 102),
    ("ai",          1_500_000, "GPU", "vram_gb", "gte", 8,  "VRAM 8GB 이상",
     "5060/5060Ti 8GB — 팝콘5 57%(n=421)", 103),
    ("design",      1_500_000, "GPU", "vram_gb", "gte", 8,  "VRAM 8GB 이상",
     "5060/5060Ti 8GB — 팝콘5 57%(n=421)", 104),
    ("gaming_high", 3_000_000, "GPU", "vram_gb", "gte", 12, "VRAM 12GB 이상",
     "RTX 5070 12GB — 팝콘7 57%(n=290), AI 88%(n=25)", 110),
    ("video",       3_000_000, "GPU", "vram_gb", "gte", 12, "VRAM 12GB 이상",
     "RTX 5070 12GB — 팝콘7 57%(n=290), AI 88%(n=25)", 111),
    ("ai",          3_000_000, "GPU", "vram_gb", "gte", 12, "VRAM 12GB 이상",
     "RTX 5070 12GB — 팝콘7 57%(n=290), AI 88%(n=25)", 112),
    ("gaming_high", 4_000_000, "GPU", "vram_gb", "gte", 16, "VRAM 16GB 이상",
     "RTX 5080 53%(n=13)", 120),
    ("video",       4_000_000, "GPU", "vram_gb", "gte", 16, "VRAM 16GB 이상",
     "5070Ti 60%(n=41)", 121),
    ("ai",          5_500_000, "GPU", "vram_gb", "gte", 16, "VRAM 16GB 이상",
     "RTX 5080 84%(n=59), AI 89%(n=38)", 130),
    ("gaming_high", 5_500_000, "GPU", "vram_gb", "gte", 16, "VRAM 16GB 이상",
     "RTX 5080 84%(n=59), AI 89%(n=38)", 131),
    ("video",       5_500_000, "GPU", "vram_gb", "gte", 16, "VRAM 16GB 이상",
     "RTX 5080 84%(n=59), AI 89%(n=38)", 132),
    ("ai",          8_000_000, "GPU", "vram_gb", "gte", 32, "VRAM 32GB 이상",
     "RTX 5090 72%(n=18), AI 84%(n=13) — 5090 재고 판매중 14개, 최저 756만", 140),
    ("video",       8_000_000, "GPU", "vram_gb", "gte", 32, "VRAM 32GB 이상",
     "RTX 5090 72%(n=18), AI 84%(n=13)", 141),
    ("gaming_high", 8_000_000, "GPU", "vram_gb", "gte", 32, "VRAM 32GB 이상",
     "RTX 5090 72%(n=18), AI 84%(n=13)", 142),
    # ── RAM capacity_gb (gte) — 용도가 RAM 을 가른다((b)절) ─────────────────────
    ("game",        2_200_000, "RAM", "capacity_gb", "gte", 32, "메모리 32GB 이상",
     "온라인게임 5+ 73%(n=15), 7 이상 100%", 200),
    ("gaming_high", 3_000_000, "RAM", "capacity_gb", "gte", 32, "메모리 32GB 이상",
     "76%(n=30), 7+ 92%, 9 100%", 201),
    ("video",       2_200_000, "RAM", "capacity_gb", "gte", 32, "메모리 32GB 이상",
     "영상편집 5+ 63%(n=33) · 7 96%(n=30)", 202),
    ("ai",          1_500_000, "RAM", "capacity_gb", "gte", 32, "메모리 32GB 이상",
     "AI 팝콘5 53%(n=13) → 5+ 89%(n=19) → 7 100%", 203),
    ("ai",          4_000_000, "RAM", "capacity_gb", "gte", 64, "메모리 64GB 이상",
     "AI 7+ 55%(n=20) → 9 97%(n=38) → X 92%(n=13)", 204),
    ("video",       8_000_000, "RAM", "capacity_gb", "gte", 64, "메모리 64GB 이상",
     "X 영상편집 100%(n=3, 표본 얇음 — 9 는 32GB 81% 이므로 X 만)", 205),
    ("design",      3_000_000, "RAM", "capacity_gb", "gte", 32, "메모리 32GB 이상",
     "디자인 7 100%(n=14)", 206),
    ("dev",         1_500_000, "RAM", "capacity_gb", "gte", 32, "메모리 32GB 이상",
     "시장 표본 0 — 웹 조사(Medium 2026-04 \"32GB 미만 사지 말라\")", 207),
    # ── CPU cpu_cores (gte) — 영상편집·AI·디자인 고티어는 다코어((b)절) ─────────
    # 게임(game·gaming_high)은 코어 규칙 없음 — 시장은 X3D(8코어)를 고른다. 코어 하한을
    # 걸면 시장 표준(9800X3D)이 탈락한다. **게임 CPU 는 규칙을 두지 않는다.**
    ("video",       3_000_000, "CPU", "cpu_cores", "gte", 12, "CPU 12코어 이상",
     "팝콘7 영상편집 CPU 상위 U7 265KF(20)·R9 9900X(12)", 300),
    ("ai",          3_000_000, "CPU", "cpu_cores", "gte", 12, "CPU 12코어 이상",
     "팝콘7 영상편집 CPU 상위 U7 265KF(20)·R9 9900X(12)", 301),
    ("design",      3_000_000, "CPU", "cpu_cores", "gte", 12, "CPU 12코어 이상",
     "팝콘7 영상편집 CPU 상위 U7 265KF(20)·R9 9900X(12)", 302),
    ("video",       5_500_000, "CPU", "cpu_cores", "gte", 20, "CPU 20코어 이상",
     "U7 270K(20) 23%·U9 285K(24) 13%(n=59)", 310),
    ("ai",          5_500_000, "CPU", "cpu_cores", "gte", 20, "CPU 20코어 이상",
     "U7 270K(20) 23%·U9 285K(24) 13%(n=59)", 311),
    ("ai",          8_000_000, "CPU", "cpu_cores", "gte", 24, "CPU 24코어 이상",
     "U9 285K 46%(n=13)", 320),
]
# 사무(office) — 규칙 없음(팝콘 3만 채우고 iGPU 74% 인데 엔진은 GPU 슬롯 필수 — 범위 밖).


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS usage_tier_rules (
            rule_id     SERIAL PRIMARY KEY,
            usage_key   VARCHAR(32)  NOT NULL,
            budget_min  INTEGER      NOT NULL,
            slot        VARCHAR(16)  NOT NULL,
            field       VARCHAR(64)  NOT NULL,
            op          VARCHAR(8)   NOT NULL DEFAULT 'gte',
            value       INTEGER      NOT NULL,
            label       VARCHAR(80)  NOT NULL,
            active      BOOLEAN      NOT NULL DEFAULT TRUE,
            note        TEXT,
            sort_order  INTEGER      NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)
    op.execute("COMMENT ON TABLE usage_tier_rules IS "
               "'용도×예산 티어 겨냥 규칙(0085) — usage_floors(하한) 위에서 budget_min 이하 예산에 "
               "적용, (usage_key,slot,field)별 budget_min 최대 하나만. "
               "정본 docs/design/usage-tier-rules-2026-09-12.md'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_usage_tier_rules_usage"
               " ON usage_tier_rules (usage_key, budget_min)")
    conn = op.get_bind()
    if conn.execute(text("SELECT count(*) FROM usage_tier_rules")).scalar():
        return          # 이미 값이 있는 DB 에서는 한 행도 바꾸지 않는다(0019 와 같은 규약)
    for (uk, bmin, slot, field, o, val, label, note, so) in RULES:
        conn.execute(text(
            "INSERT INTO usage_tier_rules"
            " (usage_key, budget_min, slot, field, op, value, label, note, sort_order)"
            " VALUES (:uk, :bmin, :slot, :field, :op, :val, :label, :note, :so)"),
            {"uk": uk, "bmin": bmin, "slot": slot, "field": field, "op": o,
             "val": val, "label": label, "note": note, "so": so})


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_tier_rules")
