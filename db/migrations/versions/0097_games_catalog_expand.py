# -*- coding: utf-8 -*-
"""0097: games 확장(컬럼 추가) + 실측fps/인기스냅샷/평점 표 신설

■ 왜 컬럼을 추가하나 — 기존 전제가 세 군데에서 깨졌다

지금 games 는 "게임 1개 = 공식 사양 1쌍" 이라는 전제 위에 서 있다.
86종 조사에서 그 전제가 깨졌다(근거: D:/Hermes-Workspace/game_schema_proposal.md).

  (A) 권장사양의 '조건'이 컬럼에 없다.
      몬스터헌터 와일즈 권장 RTX 2060 SUPER = 1080p/Medium/60fps/프레임생성 ON
      스텔라 블레이드 권장 RTX 2060 SUPER = 1440p/Medium/60fps
      같은 GPU 인데 의미가 다르다. 지금은 이 조건이 전부 note 자유텍스트에 묻혀 있다.
  (B) 실측 fps 는 본질적으로 1:N 이다.
      배틀필드6 하나에 TechPowerUp 결론만 1080p/1440p/4K 세 줄이다.
  (C) 인기 지표는 시계열이다.
      PC방 점유율은 주 단위, 스팀 동접은 분 단위로 바뀐다.
      여기에 오늘 값을 스칼라로 넣으면 내일부터 틀린 값이 된다.

(A)는 컬럼 추가로, (B)(C)는 별도 표로 푼다.

■ 컬럼 추가가 기존 코드를 깨지 않는 근거

참조처를 전수 확인했다 — api/admin_game_matrix.py · api/admin_grid.py ·
api/talk_schema.py · tools/game_cell_mapper.py · tools/game_db_load.py.
`SELECT *` 가 한 군데도 없고 전부 명시적 컬럼 나열이다. 그래서 컬럼 추가는
기존 조회에 영향이 없다. 기존 컬럼은 하나도 고치지 않는다(추가만).

■ 등급 체계는 건드리지 않는다

game_load_grades · game_grade_assignments · game_grade_resolution_tiers 는
사장님 확정 이력이 있다. 이 마이그레이션은 그 셋을 읽지도 쓰지도 않는다.
(63종 신규 게임의 등급 배정은 별건이다 — bottleneck/fps_sensitivity 가 생겼으니
 다음 단계에서 배정 근거를 기계적으로 좁힐 수 있다.)

■ rec_gpu 를 벤더별로 쪼갠 이유

현재 6행이 mapping_skip_reason='rec_gpu_parse_failed' 다(롤·FC온라인·서든어택·
발로란트·메이플·로블록스). 원인은 rec_gpu 한 칸에 "GTX 1060 / RX 580 / Arc A750"
처럼 여러 벤더가 섞이거나, 로블록스처럼 모델명이 아예 없기 때문이다.
원문 rec_gpu 는 출처 보존용으로 그대로 두고 정규화 칸을 따로 둔다 —
파서를 고치는 것보다 출처 추적성이 지켜진다.

■ popularity_rank 는 그대로 둔다

23행 전부 NULL 인 채다. 지우지 않고 남기되, 정본은 game_popularity_snapshots 다.
스냅샷 표 없이 오늘 순위를 채우면 갱신 시점을 알 수 없는 값이 된다 —
틀린 값은 빈 값보다 나쁘다.

■ 이 마이그레이션이 하지 않는 것

usage_floors · 견적 엔진 · spec_tiers 를 건드리지 않는다. 표만 준비한다.

Revision ID: 0097
Revises: 0096
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0097"
down_revision = "0096"
branch_labels = None
depends_on = None


# (컬럼명, 타입, 코멘트) — 제안서 우선순위 1~8 전체
_GAME_COLS = [
    # 우선순위 2 — 권장/최소사양의 '조건'
    ("rec_target_resolution", sa.String(16),
     "권장사양이 전제한 해상도. 1080p/1440p/4K"),
    ("rec_target_fps", sa.Integer,
     "권장사양이 전제한 fps. 몬헌 라이즈는 권장이 30fps 다"),
    ("rec_preset", sa.String(40),
     "권장사양이 전제한 그래픽 프리셋. 대부분 Medium - 고객이 기대하는 '최고옵션'이 아니다"),
    ("rec_assumes_upscaling", sa.Boolean,
     "권장사양이 DLSS/FSR 업스케일을 켠 기준인가"),
    ("rec_assumes_frame_gen", sa.Boolean,
     "권장사양이 프레임생성을 켠 기준인가. 와일즈가 그렇다"),
    ("min_target_resolution", sa.String(16), None),
    ("min_target_fps", sa.Integer, None),
    ("min_preset", sa.String(40), None),
    ("min_spec_note_raw", sa.Text,
     "공식 사양표 최소 항목에 붙어 있던 조건 원문. 위 정규화 칸의 출처"),
    ("rec_spec_note_raw", sa.Text,
     "공식 사양표 권장 항목에 붙어 있던 조건 원문. 위 정규화 칸의 출처"),
    # 우선순위 3 — VRAM/스토리지
    ("min_vram_gb", sa.Integer,
     "game_grade_resolution_tiers 의 note 가 이미 VRAM 8/12/16GB 계단을 말하는데 "
     "games 에 VRAM 컬럼이 없었다 - 정의와 데이터가 따로 놀던 것을 메운다"),
    ("rec_vram_gb", sa.Integer, None),
    ("min_storage_gb", sa.Integer,
     "콜옵 161GB / ARK 180GB - SSD 용량 견적에 직접 쓰인다"),
    ("rec_storage_gb", sa.Integer, None),
    ("requires_ssd", sa.Boolean, None),
    ("requires_nvme", sa.Boolean,
     "듄 어웨이크닝은 최소=SSD, 권장=NVMe 로 구분해 요구한다"),
    # 우선순위 5 — 병목/프레임 민감도 (사장님 지시 4,5)
    ("bottleneck", sa.String(16),
     "cpu/gpu/balanced. 헬다이버즈2/POE2 는 CPU 바운드, 로스트아크/메이플도 CPU"),
    ("bottleneck_evidence", sa.Text, "근거 문장 + URL"),
    ("fps_sensitivity", sa.String(8),
     "high/mid/low. game_load_grades E등급('1080p 144fps+')에 암묵적으로 들어 있던 축을 "
     "컬럼으로 뺀다 - E등급이 아닌 게임(철권8/포르자)도 고주사율에 민감하다"),
    # 우선순위 4,8 — 정체성/운영
    ("name_en", sa.String(160),
     "스팀 매칭 키. '붉은사막' -> 'Crimson Desert Enhanced'"),
    ("steam_appid", sa.Integer,
     "사양/평가/동접을 자동 갱신하는 유일한 안정 키. 86종 중 68종 확보"),
    ("vendor", sa.String(80),
     "넥슨 FC온라인 vs EA SPORTS FC 26 구분 - 고객이 '피파' 라고 할 때 갈라야 한다"),
    ("release_date", sa.Date, "신작 여부 판단"),
    ("is_bucket", sa.Boolean,
     "'스팀 인디(통칭)' 같은 실존하지 않는 장르 버킷 표시. 지금은 실제 게임과 섞여 통계가 오염된다"),
    ("is_active", sa.Boolean,
     "콜옵 BO7 은 스팀 동접 0명 - 카탈로그에 두되 비활성 표시"),
    ("confidence", sa.String(120),
     "확인 / 2차출처 / 추정 / 미확보. 조사자가 남긴 문자열을 그대로 싣는다"),
    # 우선순위 2-4 — rec_gpu 정규화 (원문은 rec_gpu 에 그대로 둔다)
    ("rec_gpu_nvidia", sa.String(80), None),
    ("rec_gpu_amd", sa.String(80), None),
    ("rec_gpu_intel", sa.String(80), None),
    # 커뮤니티 근거 (공식 사양과 다른 종류의 근거라 별도 칸)
    ("community_note", sa.Text, None),
    ("community_source_urls", postgresql.JSONB, None),
    ("source_urls", postgresql.JSONB,
     "근거 URL 배열. 0096 software.source_urls 와 같은 관례(jsonb 한 칸)"),
]


def upgrade():
    for name, type_, comment in _GAME_COLS:
        op.add_column("games", sa.Column(name, type_, nullable=True,
                                         comment=comment))
    op.create_index("ix_games_steam_appid", "games", ["steam_appid"],
                    unique=True, postgresql_where=sa.text("steam_appid IS NOT NULL"))
    op.create_index("ix_games_bottleneck", "games", ["bottleneck"])
    op.create_index("ix_games_fps_sensitivity", "games", ["fps_sensitivity"])

    # ---- 실측 fps (문제 B) ----
    # is_threshold 가 왜 중요한가: TechPowerUp 결론 문장은 "RTX 4070 Ti 가 105fps" 가
    # 아니라 "60fps 를 넘으려면 RTX 4070 Ti 이상이 필요하다" 는 임계값 형태다.
    # 이건 우리 티어 사다리(T1~T5)에 직접 매핑되는 형태라 견적 엔진에 가장 값지다.
    #
    # source_url 을 NOT NULL 로 건 이유: fps 는 GPU/해상도/옵션이 같이 없으면 무의미하고,
    # 출처가 없으면 검증할 수 없다. 출처 없는 행은 아예 넣지 않는다.
    op.create_table(
        "game_measured_fps",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("game_id", sa.Integer,
                  sa.ForeignKey("games.game_id", ondelete="CASCADE"), nullable=False),
        sa.Column("gpu_model", sa.String(160), nullable=False),
        sa.Column("cpu_model", sa.String(120), nullable=True,
                  comment="테스트 시스템 CPU"),
        sa.Column("resolution", sa.String(16), nullable=False),
        sa.Column("preset", sa.String(160), nullable=False),
        sa.Column("upscaling", sa.String(40), nullable=True,
                  comment="null / 'DLSS Quality' / 'FSR3 Balanced'"),
        sa.Column("frame_gen", sa.Boolean, nullable=True),
        sa.Column("ray_tracing", sa.Boolean, nullable=True),
        sa.Column("fps_avg", sa.Integer, nullable=True),
        sa.Column("fps_1pct_low", sa.Integer, nullable=True,
                  comment="로스트아크 사례처럼 평균보다 중요할 때가 있다"),
        sa.Column("is_threshold", sa.Boolean, nullable=True,
                  comment="true 면 '이 GPU 가 해당 조건 60fps 를 넘는 최저 등급'이라는 뜻"),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("source_name", sa.String(60), nullable=True),
        sa.Column("measured_date", sa.Date, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.UniqueConstraint("game_id", "gpu_model", "resolution", "preset",
                            name="game_measured_fps_key"),
    )
    op.create_index("ix_game_measured_fps_game", "game_measured_fps", ["game_id"])

    # ---- 인기 시계열 (문제 C) ----
    # source 를 키에 넣는 이유: 이번 조사에서 PC방 TOP10 은 게임트릭스 원본 당일치
    # (2026-09-17), 11위 이하는 2차 출처 집계(2026-09-03)였다. 기준일과 출처가 다른
    # 값을 같은 칸에 섞으면 안 된다.
    op.create_table(
        "game_popularity_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("game_id", sa.Integer,
                  sa.ForeignKey("games.game_id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("source", sa.String(40), nullable=False,
                  comment="gametrics / gametrics_secondary / steam_api"),
        sa.Column("pcbang_rank", sa.Integer, nullable=True),
        sa.Column("pcbang_share_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("steam_ccu", sa.Integer, nullable=True),
        sa.Column("steam_ccu_peak", sa.Integer, nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.UniqueConstraint("game_id", "snapshot_date", "source",
                            name="game_popularity_snapshots_key"),
    )
    op.create_index("ix_game_popularity_snapshots_game",
                    "game_popularity_snapshots", ["game_id"])

    # ---- 평점 (출처별 1:N) ----
    # sample_size 를 둔 이유: 디아블로2 레저렉션 86.4%(n=6,122)와 발더스게이트3
    # 96.8%(n=857,969)는 신뢰도가 두 자릿수 배 차이다. 비율만 보면 오판한다.
    # (사장님 지시: "비율엔 표본 수 병기")
    # games 스칼라 컬럼으로 두지 않은 이유: 오픈크리틱이 아직 0건인데 나중에 채우려면
    # 컬럼을 또 추가해야 한다. 출처별 행 구조면 그냥 INSERT 다.
    op.create_table(
        "game_ratings",
        sa.Column("game_id", sa.Integer,
                  sa.ForeignKey("games.game_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("source", sa.String(24), primary_key=True,
                  comment="metacritic / opencritic / steam"),
        sa.Column("score", sa.Numeric(5, 2), nullable=True,
                  comment="메타=0~100, 스팀=0~100(긍정 비율 %)"),
        sa.Column("sample_size", sa.Integer, nullable=True,
                  comment="스팀은 리뷰 수. 비율엔 표본 수를 반드시 붙인다"),
        sa.Column("score_desc", sa.String(60), nullable=True,
                  comment="'Overwhelmingly Positive'"),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("checked_date", sa.Date, nullable=True),
    )


def downgrade():
    op.drop_table("game_ratings")
    op.drop_index("ix_game_popularity_snapshots_game",
                  table_name="game_popularity_snapshots")
    op.drop_table("game_popularity_snapshots")
    op.drop_index("ix_game_measured_fps_game", table_name="game_measured_fps")
    op.drop_table("game_measured_fps")
    op.drop_index("ix_games_fps_sensitivity", table_name="games")
    op.drop_index("ix_games_bottleneck", table_name="games")
    op.drop_index("ix_games_steam_appid", table_name="games")
    for name, _type, _c in reversed(_GAME_COLS):
        op.drop_column("games", name)
