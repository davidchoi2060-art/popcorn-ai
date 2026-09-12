"""용도별 예산 배분율 표 — usage_alloc (2026-09-12 사장님 확정 "배분율 먼저").

설계 정본: docs/design/usage-alloc-2026-09-12.md
근거 자료: D:/Hermes-Workspace/crawl/analysis.md (b-2)절 — 부품 단가 있는 291건,
          값 = 부품가 ÷ 완제품가 중앙값, 표본 n 병기.

**아래 값은 설계 문서 표를 그대로 옮겼다 — 지어내지 않았다.** 각 행의 note 에 문서의
근거(표본 n·비율 범위)를 그대로 적는다.

■ BUDGET_ALLOC(api/candidates.py 코드 상수)과의 관계
  BUDGET_ALLOC 은 슬롯별 **상한**만 있고(GPU 40%·CPU 25%·RAM 10%…) 전 용도 고정이다.
  그래서 팝콘 5 개발 = RTX 3050 29만(13%) + 울트라9 102만(46%) 같은 구성이 나왔다 —
  GPU 에 하한이 없어 남는 돈이 CPU 로 갔고, 폴백이 배분을 전면 해제했다.
  이 표는 (usage_key, slot) 축에 **하한(pct_min) + 상한(pct_max)** 을 둔다.
    · usage_key NULL = 기본 행. 용도 행이 있는 슬롯은 그것, 없으면 기본 행.
    · 기본 행에도 없는 슬롯(MB·SSD·POWER·CASE·COOLER)은 BUDGET_ALLOC 상수를 (0, v) 로.
    · **BUDGET_ALLOC 은 DB 를 못 읽을 때의 폴백**으로만 남는다(spec_fields·usage_floors 와
      같은 패턴). 읽는 곳: api/usage_alloc.py `for_usage`.
  dev(개발)는 시장 표본이 0 이라 행이 없다 = 기본 행 상속.

■ pct_min 은 DFS 가지치기가 아니라 «완성된 조합의 판정»에 쓴다(설계 문서 ⚠). 슬롯
  후보를 하한으로 거르면 저가 티어에서 후보가 0 이 된다. 상한(pct_max)은 후보 필터.

재실행 안전: 표는 IF NOT EXISTS, 행은 표가 비어 있을 때만 넣는다(0085 와 같은 규약).

Revision ID: 0086
Revises: 0085
"""
from alembic import op
from sqlalchemy import text

revision = "0086"
down_revision = "0085"
branch_labels = None
depends_on = None


# (usage_key, slot, pct_min, pct_max, note, sort_order) — 설계 문서 §값 표 그대로.
ROWS = [
    # ── 기본(NULL) — 용도 행이 없는 슬롯·용도(dev 등)가 상속 ─────────────────────
    (None, "GPU", 0.30, 0.50, "팝콘5~7 전 용도 GPU 32~46%", 10),
    (None, "CPU", 0.08, 0.25, "12~22%", 11),
    (None, "RAM", 0.05, 0.25, "15~28% (5+ 온라인게임 28%)", 12),
    # ── game ──────────────────────────────────────────────────────────────────
    ("game", "GPU", 0.32, 0.48, "5 42%(n=35) · 5+ 32%(n=10) · 7 34%", 100),
    ("game", "CPU", 0.08, 0.20, "12~16%", 101),
    # ── gaming_high ───────────────────────────────────────────────────────────
    ("gaming_high", "GPU", 0.35, 0.52, "5+ 36%(n=22) · 7 41%(n=18) · 7+ 46%(n=3)", 110),
    ("gaming_high", "CPU", 0.10, 0.25, "16~22% (X3D 가 비싸다)", 111),
    # ── video ─────────────────────────────────────────────────────────────────
    ("video", "GPU", 0.28, 0.45, "5+ 37% · 7 36%(n=6) · 7+ 31%(n=6)", 120),
    ("video", "CPU", 0.10, 0.22, "15~17%", 121),
    ("video", "RAM", 0.10, 0.25, "18~22%", 122),
    # ── ai ────────────────────────────────────────────────────────────────────
    ("ai", "GPU", 0.33, 0.62, "5 36% · 7 37% · X 59%(n=2) — 5090 이 절반 넘는다", 130),
    ("ai", "CPU", 0.05, 0.20, "6~16%", 131),
    ("ai", "RAM", 0.08, 0.30, "9~17%, 64GB 강제 구간은 더 큼", 132),
    # ── design ────────────────────────────────────────────────────────────────
    ("design", "GPU", 0.30, 0.45, "5 37%(n=9) · 7 38%", 140),
    ("design", "CPU", 0.08, 0.20, "11~12%", 141),
    # ── dev — 행 없음(시장 표본 0 — 기본값 상속) ───────────────────────────────
    # ── office ────────────────────────────────────────────────────────────────
    ("office", "GPU", 0.00, 0.15,
     "사무 GPU 9%(n=1)·iGPU 97% — GPU 슬롯 필수인 현 엔진에선 최저가로", 150),
    ("office", "CPU", 0.20, 0.40, "31%(n=31)", 151),
    ("office", "RAM", 0.10, 0.30, "21%(n=30)", 152),
]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS usage_alloc (
            alloc_id    SERIAL PRIMARY KEY,
            usage_key   VARCHAR(32),
            slot        VARCHAR(16)   NOT NULL,
            pct_min     NUMERIC(4,3)  NOT NULL DEFAULT 0,
            pct_max     NUMERIC(4,3)  NOT NULL,
            note        TEXT,
            active      BOOLEAN       NOT NULL DEFAULT TRUE,
            sort_order  INTEGER       NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
            CONSTRAINT ck_usage_alloc_range CHECK (pct_min >= 0 AND pct_min < pct_max AND pct_max <= 1)
        )
    """)
    op.execute("COMMENT ON TABLE usage_alloc IS "
               "'용도별 예산 배분율(0086) — usage_key NULL=기본 행, 슬롯별 pct_min(완성 조합 판정)·"
               "pct_max(후보 필터). candidates.BUDGET_ALLOC 은 DB 못 읽을 때 폴백. "
               "정본 docs/design/usage-alloc-2026-09-12.md'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_usage_alloc_usage ON usage_alloc (usage_key, slot)")
    conn = op.get_bind()
    if conn.execute(text("SELECT count(*) FROM usage_alloc")).scalar():
        return          # 이미 값이 있는 DB 에서는 한 행도 바꾸지 않는다(0019·0085 와 같은 규약)
    for (uk, slot, pmin, pmax, note, so) in ROWS:
        conn.execute(text(
            "INSERT INTO usage_alloc (usage_key, slot, pct_min, pct_max, note, sort_order)"
            " VALUES (:uk, :slot, :pmin, :pmax, :note, :so)"),
            {"uk": uk, "slot": slot, "pmin": pmin, "pmax": pmax, "note": note, "so": so})


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_alloc")
