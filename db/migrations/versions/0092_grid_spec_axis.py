# -*- coding: utf-8 -*-
"""grid_cells·grid_quotes 를 스펙 축으로 재설계 — A-135 격자 재설계 2단계.

■ 왜 필요한가 — 0091(spec_tiers·게임 등급)이 "스펙 하한이 무엇인가"를 정의했다면,
  이 마이그레이션은 "격자 칸이 그 스펙 하한으로 정의되게" 만든다. 지금까지
  `grid_cells.tier`는 브랜드명 문자열("팝콘 3" 등)이었고 `budget_min`/`budget_max`
  가 칸을 정의하는 **입력**이었다 — 이것이 "가격 구간을 먼저 정해두고 그 안에
  부품을 욱여넣는" 방식이었다(2026-09-15 사장님 지적 "억지로 금액에 맞추다
  보니까 이상해진다" — iGPU 미장착 CPU에 GPU를 중복 구매해 사무용 65만원 구성이
  나온 실사고가 이 방식의 직접 결과였다, b4180fd 로 근본 해소).

  이 마이그레이션 이후 `budget_min`/`budget_max`는 **배치가 실제로 만든 견적
  총액의 관측값**으로 역할이 바뀐다(입력이 아니다) — 칸을 정의하는 것은
  `tier_key`(스펙 하한)다.

■ 브랜드명 개정 — 2026-09-15 사장님 확정
  기존 "팝콘3~X"(3·5·5+·7·7+·9·X 7단)는 애초 CPU 등급(i3~i5 등)을 흉내 낸
  이름이었다는 사장님 지적에 따라 **팝콘1~5+X**(T0~T4=팝콘1~5, T5만 팝콘X 유지)
  로 바꾼다. 0091 이 이미 넣은 옛 이름(spec_tiers.popcorn_name = "팝콘3" 등)을
  이 마이그레이션 시작에서 UPDATE 한다.

■ 게임 축 분리 — 2026-09-15 사장님 확정(3항목 clarify)
  게임은 `usage='게임'` 하나로 묶고, 세부는 `game_load_grades.grade`
  (E/A/B/C/S/L) + 해상도(1080p/1440p/4K) 로 가른다 — usage_key 문자열
  세분(game/game_casual/gaming_high)과는 다른 축이다(usage_floors 레이어는
  대화 파싱용, 격자 레이어는 등급용 — 목적이 다르므로 섞지 않는다).

  S등급(패스오브엑자일2·헬다이버즈2)은 GPU 기준과 CPU 기준이 다르다
  (`game_grade_resolution_tiers.cpu_tier_key_override`) — 단일 tier_key로
  못 담아서, 게임 칸은 `tier_key`를 직접 안 갖고 `(game_grade, game_resolution)`
  만 가진다. 스펙이 필요한 자리(엔진 연결)는 `game_grade_resolution_tiers`를
  조인해서 구한다(단일 원천 — CLAUDE.md, 값을 격자에 복사하지 않는다).

■ 칸 3종 저장 — 2026-09-15 사장님 확정
  카드 하나(칸 하나)가 가성비/추천/고성능 3종 구성을 전부 갖는다 — 고객이
  탭으로 바로 비교해 보는 UI 전제(req-grid-matrix-2026-09-15.md §⑤-4).
  `grid_quotes.tier_variant` 컬럼을 신설하고, "칸당 현재본 하나"였던 기존
  부분 유니크를 "칸×variant 당 현재본 하나"로 재설계한다.

■ 축 CHECK — 비게임/게임 칸이 서로의 컬럼을 침범하지 않는다
  usage='게임' 인 칸은 tier_key가 반드시 NULL이고 game_grade·game_resolution이
  반드시 채워진다. 그 반대(비게임 칸)는 정반대다. 한 칸이 두 축을 동시에
  갖거나 아무것도 안 갖는 모순 상태를 DB가 직접 막는다.

■ 기존 데이터(112칸·견적 639행·현재본 82행)는 지우지 않는다
  `tools/grid_generate.py`가 이미 실행돼 실제 견적을 만든 원장이다(0072
  자신의 주석: "grid_quotes — 원장이다"). 새 스키마와 공존할 수 없으므로
  (칸 정의 자체가 바뀐다) `_legacy_v1` 로 이름만 바꿔 보존한다 — 필요하면
  과거 격자가 무엇을 보여줬는지 SQL로 되짚을 수 있다. downgrade는 새 표를
  버리고 옛 이름을 복원한다(원 데이터 손실 없음).

■ intended_empty — 지어내지 않는다(0072 자신의 원칙을 그대로 잇는다)
  이 물결에서 "이 스펙 티어 × 이 용도가 불가능하다"는 근거(시장 조사·재고
  실측)를 새로 확보하지 않았다. 0072가 "문서에 없는 조합은 일단 채우는
  쪽에 둔다 — 배치가 실행돼 후보가 없거나 예산 불성립이면 grid_quotes.status
  로 정직하게 드러난다"고 밝힌 것과 같은 이유로, 이번 108칸도 전부
  intended_empty=false 로 시작한다. 빈칸 재판단(req-grid-matrix-2026-09-15.md
  §⑤-4)은 배치 도구(`tools/grid_generate.py`) 재설계 이후 실행 결과로 한다.

Revision ID: 0092
Revises: 0091
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None


# 팝콘1~5+X — 2026-09-15 사장님 확정(0091 의 옛 이름 "팝콘3~X" 대체)
POPCORN_NAMES = {
    "T0": "팝콘1", "T1": "팝콘2", "T2": "팝콘3",
    "T3": "팝콘4", "T4": "팝콘5", "T5": "팝콘X",
}

# 비게임 용도 6종 — usage_floors(0090) 의 usage_label 을 그대로 쓴다(단일 원천,
# 2026-09-15 Cloud SQL 실측: ai/video/design/office/trading/video_3d distinct label)
NONGAME_USAGES = ["AI 작업", "영상편집", "디자인", "사무·인강", "주식·트레이딩", "3D 그래픽"]

SPEC_TIER_KEYS = ["T0", "T1", "T2", "T3", "T4", "T5"]
GAME_GRADES = ["E", "A", "B", "C", "S", "L"]
RESOLUTIONS = ["1080p", "1440p", "4K"]
PLATFORMS = ["인텔", "AMD"]
VARIANTS = ["가성비", "추천", "고성능"]


def upgrade() -> None:
    conn = op.get_bind()

    # ── 브랜드명 개정 — 0091 이 넣은 옛 이름을 새 이름으로 UPDATE ──────────
    for tier_key, name in POPCORN_NAMES.items():
        conn.execute(sa.text(
            "UPDATE spec_tiers SET popcorn_name=:n WHERE tier_key=:t"),
            {"n": name, "t": tier_key})

    # ── 기존 표 보존 — 이름만 바꾼다(데이터·FK 그대로 유지) ─────────────
    # PostgreSQL은 테이블을 RENAME 해도 인덱스 이름은 그대로 남는다 — 새
    # grid_quotes가 같은 인덱스 이름(ix_grid_quotes_cell_id 등)을 못 쓰므로
    # 레거시 쪽 인덱스도 먼저 이름을 바꿔 충돌을 없앤다.
    op.execute("ALTER INDEX ix_grid_quotes_cell_id RENAME TO ix_grid_quotes_cell_id_legacy_v1")
    op.execute("ALTER INDEX uq_grid_quotes_current_per_cell RENAME TO uq_grid_quotes_current_per_cell_legacy_v1")
    op.execute("ALTER TABLE grid_cells RENAME CONSTRAINT uq_grid_cells_coord TO uq_grid_cells_coord_legacy_v1")
    op.rename_table("grid_cells", "grid_cells_legacy_v1")
    op.rename_table("grid_quotes", "grid_quotes_legacy_v1")
    op.execute(
        "COMMENT ON TABLE grid_cells_legacy_v1 IS "
        "'0072~0082 가격축 격자(브랜드명 7단×budget_min/max) — 0092 스펙축 "
        "전환으로 보존만. 새 쓰기 없음, 과거 견적 조회용'"
    )
    op.execute(
        "COMMENT ON TABLE grid_quotes_legacy_v1 IS "
        "'0092 이전 가격축 격자의 견적 원장(639행, 현재본 82행) — 보존만'"
    )

    # ── 새 grid_cells — 스펙 축(tier_key) + 게임 등급 축(game_grade) ────
    op.create_table(
        "grid_cells",
        sa.Column("cell_id", sa.Integer, primary_key=True),
        sa.Column("tier_key", sa.String(4), sa.ForeignKey("spec_tiers.tier_key"),
                   nullable=True),   # 게임 칸은 NULL — 스펙은 등급×해상도가 대신 정한다
        sa.Column("usage", sa.String(20), nullable=False),
        sa.Column("game_grade", sa.String(1), sa.ForeignKey("game_load_grades.grade"),
                   nullable=True),
        sa.Column("game_resolution", sa.String(6), nullable=True),
        sa.Column("platform", sa.String(4), nullable=False),
        # 입력이 아니라 배치 결과 관측값 — nullable(칸이 아직 배치되지 않았으면 NULL)
        sa.Column("budget_min", sa.Integer, nullable=True),
        sa.Column("budget_max", sa.Integer, nullable=True),
        sa.Column("intended_empty", sa.Boolean, nullable=False,
                   server_default=sa.false()),
        sa.CheckConstraint(
            "(usage = '게임' AND tier_key IS NULL AND game_grade IS NOT NULL"
            "  AND game_resolution IS NOT NULL)"
            " OR "
            "(usage <> '게임' AND tier_key IS NOT NULL AND game_grade IS NULL"
            "  AND game_resolution IS NULL)",
            name="ck_grid_cells_axis",
        ),
        sa.CheckConstraint(
            "game_resolution IS NULL OR game_resolution IN ('1080p','1440p','4K')",
            name="ck_grid_cells_resolution",
        ),
    )
    # 비게임 칸: (스펙티어, 용도, 플랫폼) 조합은 하나
    op.create_index(
        "uq_grid_cells_nongame_coord", "grid_cells",
        ["tier_key", "usage", "platform"], unique=True,
        postgresql_where=sa.text("usage <> '게임'"),
    )
    # 게임 칸: (등급, 해상도, 플랫폼) 조합은 하나
    op.create_index(
        "uq_grid_cells_game_coord", "grid_cells",
        ["game_grade", "game_resolution", "platform"], unique=True,
        postgresql_where=sa.text("usage = '게임'"),
    )
    op.execute(
        "COMMENT ON TABLE grid_cells IS "
        "'스펙 축 격자 칸 정의(A-135) — 비게임: tier_key(spec_tiers T0~T5). "
        "게임: game_grade x game_resolution(game_grade_resolution_tiers 조인으로 "
        "스펙 구함). budget_min/max는 입력이 아니라 배치 결과 관측값'"
    )
    op.execute(
        "COMMENT ON COLUMN grid_cells.budget_min IS "
        "'배치가 실제로 만든 견적 총액의 관측값(입력 아님) — 0092 이전엔 입력이었다'"
    )

    # ── 새 grid_quotes — tier_variant(가성비/추천/고성능) 축 추가 ──────
    op.create_table(
        "grid_quotes",
        sa.Column("quote_id", sa.Integer, primary_key=True),
        sa.Column("cell_id", sa.Integer,
                   sa.ForeignKey("grid_cells.cell_id"), nullable=False),
        sa.Column("tier_variant", sa.String(10), nullable=False),
        sa.Column("batch_id", sa.String(20), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.func.now()),
        sa.Column("engine_note", sa.String(200)),
        sa.Column("total", sa.Integer),
        sa.Column("verdict", sa.String(20)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", postgresql.JSONB),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint(
            "tier_variant IN ('가성비','추천','고성능')",
            name="ck_grid_quotes_variant",
        ),
    )
    op.create_index("ix_grid_quotes_cell_id", "grid_quotes", ["cell_id"])
    # 칸 x variant 당 현재본 하나(기존 "칸당 현재본 하나"를 3종 저장에 맞게 확장)
    op.create_index(
        "uq_grid_quotes_current_per_cell_variant", "grid_quotes",
        ["cell_id", "tier_variant"], unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.execute(
        "COMMENT ON TABLE grid_quotes IS "
        "'격자 칸 x 구성종류(가성비/추천/고성능) 별 생성 견적 원장 — 0092 "
        "이전엔 칸당 1개였다. UPDATE 하지 않고 새 행을 INSERT, 이전 "
        "is_current를 false로 내린다'"
    )

    # ── 시드 — 108칸(비게임 72 + 게임 36), 전부 intended_empty=false ────
    filled = 0
    for tier_key in SPEC_TIER_KEYS:
        for usage in NONGAME_USAGES:
            for platform in PLATFORMS:
                conn.execute(sa.text(
                    "INSERT INTO grid_cells (tier_key, usage, platform,"
                    " intended_empty) VALUES (:t, :u, :p, false)"),
                    {"t": tier_key, "u": usage, "p": platform})
                filled += 1
    for grade in GAME_GRADES:
        for resolution in RESOLUTIONS:
            for platform in PLATFORMS:
                conn.execute(sa.text(
                    "INSERT INTO grid_cells (usage, game_grade, game_resolution,"
                    " platform, intended_empty) VALUES ('게임', :g, :r, :p, false)"),
                    {"g": grade, "r": resolution, "p": platform})
                filled += 1

    print(f"[0092] grid_cells 시드: 비게임 {len(SPEC_TIER_KEYS) * len(NONGAME_USAGES) * len(PLATFORMS)}"
          f" + 게임 {len(GAME_GRADES) * len(RESOLUTIONS) * len(PLATFORMS)} = 총 {filled}행"
          f" (전부 intended_empty=false — 빈칸 재판단은 배치 실행 이후)")


def downgrade() -> None:
    op.drop_index("uq_grid_quotes_current_per_cell_variant", table_name="grid_quotes")
    op.drop_index("ix_grid_quotes_cell_id", table_name="grid_quotes")
    op.drop_table("grid_quotes")
    op.drop_index("uq_grid_cells_game_coord", table_name="grid_cells")
    op.drop_index("uq_grid_cells_nongame_coord", table_name="grid_cells")
    op.drop_table("grid_cells")

    op.rename_table("grid_quotes_legacy_v1", "grid_quotes")
    op.rename_table("grid_cells_legacy_v1", "grid_cells")
    op.execute("ALTER TABLE grid_cells RENAME CONSTRAINT uq_grid_cells_coord_legacy_v1 TO uq_grid_cells_coord")
    op.execute("ALTER INDEX uq_grid_quotes_current_per_cell_legacy_v1 RENAME TO uq_grid_quotes_current_per_cell")
    op.execute("ALTER INDEX ix_grid_quotes_cell_id_legacy_v1 RENAME TO ix_grid_quotes_cell_id")

    conn = op.get_bind()
    OLD_NAMES = {"T0": "팝콘3", "T1": "팝콘5", "T2": "팝콘7",
                 "T3": "팝콘7+", "T4": "팝콘9", "T5": "팝콘X"}
    for tier_key, name in OLD_NAMES.items():
        conn.execute(sa.text(
            "UPDATE spec_tiers SET popcorn_name=:n WHERE tier_key=:t"),
            {"n": name, "t": tier_key})
