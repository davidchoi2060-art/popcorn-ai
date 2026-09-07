# -*- coding: utf-8 -*-
"""게임·AI 성능 DB — games·game_performance·ai_workloads (격자-7)

■ 배경 — `docs/design/prebuilt-grid-benchmark-2026-09-07.md` §7
  별칭 레이어(격자 칸)만으로는 "이 견적으로 배그 몇 프레임 나와요?" 에 답하지
  못한다. LLM이 성능을 추측하지 않고 **DB를 읽고 답한다**(재현성 원칙, A-02의
  연장) — 그래서 게임·AI 작업별 요구사양·예상 성능을 표로 둔다. 문서 §7.1이
  제안한 테이블 3종을 그대로 만든다.

■ gpu_band 는 개별 GPU 모델이 아니라 «전력 등급»이다
  엔진의 용도 하한(`usage_floors`, CLAUDE.md §용도 하한)이 이미 GPU 성능 지표가
  없다는 전제로 `required_power_watt`(300/550/750 등급)를 성능 근사축으로 쓰고
  있다. 여기서 새 GPU 밴드 어휘(예: "중급"/"고급")를 또 만들면 같은 개념이 두
  벌 생긴다(CANON §1, 단일 원천 원칙). 그래서 `game_performance.gpu_band` 는
  `usage_floors` 와 **같은 정수 등급**을 그대로 쓴다 — 로더(`tools/game_db_load.py`)가
  수집된 GPU 모델명을 `v_recommendation_candidates` 실측으로 이 등급에 매핑한다.
  신제품이 나와도 후보 뷰에 그 상품만 들어오면 밴드 판정이 자동으로 따라온다
  (문서 §7.2 "GPU는 등급으로 참조" 원칙).

■ fps_band 는 정확값이 아니라 구간이다 (문서 §7.2)
  "프레임은 정확값이 아니라 구간(60+/100+/144+)" — 갱신 부담을 낮추고, 실측 오차를
  구간 안에 흡수해 "우리가 62프레임이라 했는데 실제 58이 나왔다"는 식의 신뢰
  훼손을 피한다. `fps_avg` 는 출처가 준 실측 평균이 있을 때만 참고로 함께 저장하되,
  화면·엔진이 참조하는 정본은 `fps_band` 다.

■ source_url·checked_date 는 game_performance·ai_workloads 에서 NOT NULL이다
  "행마다 출처·측정일을 기록한다"(문서 §7.2) — 근거 없는 수를 만들지 않는다는
  이 저장소의 정직성 규약(CLAUDE.md §화면 정직성)을 성능 수치에도 그대로 적용한다.
  `games` 자체는 게임이 존재한다는 사실(이름·장르)이라 출처 없이도 행을 만들 수
  있게 두되, 사양·순위 같은 «주장»이 붙는 필드는 전부 NULL 허용으로 시드에서
  비워 둔다(④ 참조).

■ ai_workloads.recommended_tier 는 grid_cells.tier 와 같은 어휘다
  "팝콘 3/5/5+/7/7+/9/X" — 새 티어 이름을 만들지 않는다(0072 TIERS 참조).
  FK 로 묶지 않은 이유: grid_cells 는 (tier, usage, platform) 좌표가 정체성이라
  tier 단독으로는 참조 무결성을 걸 수 없다(용도·플랫폼이 여러 개 걸린다) — 문자열
  일치로 두고, 어긋나면 화면·로더가 조회 시점에 드러낸다.

■ games 시드는 뼈대뿐이다 (문서 §7.3의 23종)
  이름·장르만 넣는다. 사양(min/rec)·인기순위·프레임 값은 이 마이그레이션이
  지어내지 않는다 — 출처가 있는 수집 작업(조사자/검증자)이 별도로 진행 중이고,
  그 결과는 `tools/game_db_load.py` 로 채운다. 지어낸 값을 시드에 박으면
  "모든 견적에는 이유가 있습니다"와 정면으로 부딪힌다(CLAUDE.md 반복 원칙).

Revision ID: 0073
Revises: 0072
"""
import sqlalchemy as sa
from alembic import op

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


# 문서 §7.3 그대로 — 이름·장르만. 사양·순위·프레임은 넣지 않는다(③참조).
GAMES = [
    ("리그 오브 레전드", "MOBA"),
    ("FC온라인", "스포츠"),
    ("서든어택", "FPS"),
    ("발로란트", "FPS"),
    ("오버워치2", "FPS"),
    ("로스트아크", "MMORPG"),
    ("메이플스토리", "MMORPG"),
    ("던전앤파이터", "액션RPG"),
    ("디아블로4", "액션RPG"),
    ("패스 오브 엑자일2", "액션RPG"),
    ("배틀그라운드", "배틀로얄"),
    ("사이버펑크2077", "오픈월드RPG"),
    ("붉은사막", "오픈월드액션"),
    ("몬스터헌터 와일즈", "액션RPG"),
    ("스텔라 블레이드", "액션"),
    ("검은신화 오공", "액션RPG"),
    ("GTA", "오픈월드액션"),
    ("콜 오브 듀티", "FPS"),
    ("아크 서바이벌", "서바이벌"),
    ("헬다이버즈2", "협동슈팅"),
    ("로블록스", "샌드박스"),
    ("마인크래프트", "샌드박스"),
    ("스팀 인디(통칭)", "인디(통칭)"),
]


def upgrade() -> None:
    op.create_table(
        "games",
        sa.Column("game_id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(60), nullable=False, unique=True),
        sa.Column("genre", sa.String(30), nullable=False),
        sa.Column("popularity_rank", sa.Integer),
        sa.Column("official_source_url", sa.String(300)),
        sa.Column("min_cpu", sa.String(160)),
        sa.Column("min_gpu", sa.String(160)),
        sa.Column("min_ram_gb", sa.Integer),
        sa.Column("rec_cpu", sa.String(160)),
        sa.Column("rec_gpu", sa.String(160)),
        sa.Column("rec_ram_gb", sa.Integer),
        sa.Column("checked_date", sa.Date),
        sa.Column("note", sa.String(200)),
    )
    op.execute(
        "COMMENT ON TABLE games IS "
        "'게임당 1행 — docs/design/prebuilt-grid-benchmark-2026-09-07.md §7.1. "
        "사양·순위는 출처 있는 수집으로만 채운다(tools/game_db_load.py)'"
    )

    op.create_table(
        "game_performance",
        sa.Column("perf_id", sa.Integer, primary_key=True),
        sa.Column("game_id", sa.Integer,
                   sa.ForeignKey("games.game_id"), nullable=False),
        # required_power_watt 등급(300/550/750) — usage_floors 와 같은 축. 개별
        # GPU 모델이 아니다(머리 주석 참조, 같은 것 두 벌 금지 - CANON §1).
        sa.Column("gpu_band", sa.Integer, nullable=False),
        sa.Column("resolution", sa.String(8), nullable=False),   # FHD/QHD/4K
        # 구간 표기(60+/100+/144+) — 정확값 아님, §7.2 갱신 부담 원칙
        sa.Column("fps_band", sa.String(12), nullable=False),
        sa.Column("fps_avg", sa.Integer),   # 출처가 준 실측 평균(있으면) — 참고용
        sa.Column("source_url", sa.String(300), nullable=False),
        sa.Column("checked_date", sa.Date, nullable=False),
        sa.UniqueConstraint("game_id", "gpu_band", "resolution",
                             name="uq_game_performance_coord"),
    )
    op.execute(
        "COMMENT ON TABLE game_performance IS "
        "'게임 x GPU전력등급 x 해상도 -> 예상 프레임 구간. gpu_band는 required_power_watt "
        "등급이지 개별 GPU 모델이 아니다(usage_floors와 같은 축)'"
    )

    op.create_table(
        "ai_workloads",
        sa.Column("workload_id", sa.Integer, primary_key=True),
        sa.Column("task", sa.String(40), nullable=False),
        sa.Column("model_size", sa.String(60)),   # 7B/14B/30B/70B/기본/고해상도 + 모델명 병기("Wan2.2 TI2V-5B (720p/24fps)" 실측 27자)
        sa.Column("min_vram_gb", sa.Integer),
        sa.Column("rec_vram_gb", sa.Integer),
        sa.Column("min_ram_gb", sa.Integer),
        # grid_cells.tier 와 같은 어휘("팝콘 3"..."팝콘 X") — 새 티어 이름을 만들지 않는다
        sa.Column("recommended_tier", sa.String(12)),
        sa.Column("source_url", sa.String(300), nullable=False),
        sa.Column("checked_date", sa.Date, nullable=False),
        sa.Column("note", sa.String(200)),
        sa.UniqueConstraint("task", "model_size", name="uq_ai_workloads_task_size"),
    )
    op.execute(
        "COMMENT ON TABLE ai_workloads IS "
        "'AI 작업 x 모델크기 -> 필요 VRAM/RAM, 권장 격자 티어. "
        "recommended_tier는 grid_cells.tier와 같은 문자열 어휘'"
    )

    conn = op.get_bind()
    for name, genre in GAMES:
        conn.execute(sa.text(
            "INSERT INTO games (name, genre) VALUES (:n, :g)"),
            {"n": name, "g": genre})
    print(f"[0073] games 시드: {len(GAMES)}건 (이름·장르만 - 사양/순위/프레임 없음)")


def downgrade() -> None:
    op.drop_table("ai_workloads")
    op.drop_table("game_performance")
    op.drop_table("games")
