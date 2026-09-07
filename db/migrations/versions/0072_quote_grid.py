# -*- coding: utf-8 -*-
"""사전 생성 견적 격자 — grid_cells(칸 정의)·grid_quotes(칸별 생성 견적, 원장)

■ 배경 — `docs/design/prebuilt-grid-benchmark-2026-09-07.md` §0
  지금까지는 고객 질문마다 recommend 엔진을 실시간으로 돌렸다. 이 표부터는 **격자
  (티어×용도×플랫폼)의 칸마다 견적을 미리 만들어 두고 주기 갱신**한다 — LLM은 실시간
  경로에서 칸 분류만 하고, 조합은 배치가 recommend 엔진을 그대로 재사용해 미리 한다
  (같은 질문 = 같은 답, A-02 재현성 연장). 이 마이그레이션은 그 저장 구조다.

■ 3축과 값 — 문서 §2·§3, 2026-09-07 사장님 확정(격자-1·격자-2·격자-3)
  tier   : 팝콘 3 / 팝콘 5 / 팝콘 5+ / 팝콘 7 / 팝콘 7+ / 팝콘 9 / 팝콘 X (7단, 저가를
           잘게·고가를 넓게 — 컴퓨존 관행, §1 결론 2)
  usage  : U1~U8 8종(§3). U8(저소음·컴팩트)은 문서가 "후순위 — 비워 두고 시작"이라
           명시해, 시드 단계부터 전 칸을 intended_empty=true 로 둔다.
  platform: 인텔/AMD. `api/candidates.py` PLATFORM_LABELS(격자 물결 2026-09-07 신설,
           이 표보다 먼저 들어간 짝)가 이미 이 두 값만 받는다 — 여기서 새 어휘를
           만들지 않는다.

■ budget_min/budget_max 는 «원» 단위다
  다른 금액 컬럼(products.sale_price·grid_quotes.total 등)과 같은 단위로 맞췄다 —
  한 프로젝트 안에서 "만원"과 "원"이 섞이면 대조·산술마다 10000을 곱하고 나누는
  실수가 난다(CANON §1, 같은 개념은 한 단위로). 문서 §2 표의 "만원" 표기를 그대로
  곱해 옮겼다: 60/100/150/220/300/450(경계, 사장님 확정) → 600000~4500000원.
  팝콘 X(T7)는 문서가 "450만~"(오픈)이라 budget_max=NULL — 상한 없음을 NULL로
  표현한다(지어낸 상한을 넣지 않는다).

■ UNIQUE(tier, usage, platform) — 칸은 한 조합에 하나
  격자 좌표 자체가 칸의 정체성이다. 같은 좌표가 두 행이면 배치가 어느 칸에
  써야 할지 모호해진다.

■ 비우는 칸(intended_empty) — 문서 §4가 «명시한» 세 패턴만 시드에 반영한다
  ① 저티어×고부하: T1~T2(팝콘3·팝콘5) × U3(고사양게임)·U7(AI 작업) — 예산으로 불가능
  ② 고티어×저부하: T5~T7(팝콘7+·팝콘9·팝콘X) × U1(사무·인터넷) — 다나와 홈오피스 최대
     112만이 근거, 그 위 티어에 수요가 없다
  ③ U8(저소음·컴팩트) 전체 — 문서가 "후순위, 비워 두고 시작 가능"이라 명시

  ⚠ 문서는 "실제 시작 규모는 60~70칸(수요 밀도 반영 후 확정)"이라고 적어 두었는데
  위 세 패턴만 반영하면 84칸(112-28)이 채워진다 — 문서 추정보다 많다. 이 차이는
  **의도적으로 메우지 않았다**: 문서 §6 표가 "격자-4(칸당 견적 수)·격자-6(게임
  타이틀)"과 함께 이 추가 비움을 아직 미정으로 남겨 뒀고(수요 밀도 분석 자체가
  "확정 대상"이라고 §4 말미에 명시), 시드가 임의로 더 비우면 다음 사람이 "왜 이
  칸은 비었나"를 물었을 때 이 마이그레이션 말고는 답할 근거가 없다. 지어낸 판단을
  스키마에 박지 않는다 — 문서에 없는 조합(예: T3×U4 조합의 수요가 있는지 없는지)은
  일단 채우는 쪽(intended_empty=false)에 둔다. 배치가 실행돼 후보가 없거나 예산
  불성립이면 grid_quotes.status 로 정직하게 드러난다(생성 실패/예산 상한 초과) —
  그게 이 미정을 메우는 안전한 경로다.

■ grid_quotes — 원장이다, is_current 로 현재본만 가리킨다
  칸을 갱신할 때 기존 행을 UPDATE 하지 않고 **새 행을 INSERT**하고 이전 is_current
  를 false 로 내린다(원장·되돌림 규약 — CLAUDE.md 「재고는 원장 밖에서 바뀌지
  않는다」와 같은 정신, 여기서는 "견적 이력은 덮어쓰지 않는다"). 그래서
  `is_current=true` 는 칸당 최대 하나여야 하는데 이건 일반 UNIQUE 로 못 건다
  (여러 과거본은 false 로 얼마든지 있어야 하므로) — **부분 유니크 인덱스**
  (WHERE is_current)로 "칸당 현재본 하나"만 강제한다.

  payload 는 recommend 응답의 해당 티어 build 전체(JSONB) — 슬롯·부품·가격·근거를
  통째로 보관해, 나중에 "이 견적이 언제·왜 이 구성이었나"를 recommend 엔진을 다시
  돌리지 않고도 답할 수 있게 한다.

Revision ID: 0072
Revises: 0071
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


# (티어명, budget_min원, budget_max원|None) — 문서 §2, 2026-09-07 확정 경계값
TIERS = [
    ("팝콘 3",  0,        600000),
    ("팝콘 5",  600000,   1000000),
    ("팝콘 5+", 1000000,  1500000),
    ("팝콘 7",  1500000,  2200000),
    ("팝콘 7+", 2200000,  3000000),
    ("팝콘 9",  3000000,  4500000),
    ("팝콘 X",  4500000,  None),
]

# 문서 §3 표의 용도 문구를 그대로 옮긴다(U1~U8 순서 보존 — 인덱스로 비움 패턴을 판정한다)
USAGES = [
    "사무·인터넷",              # U1
    "온라인게임 (라이트~중급)",   # U2
    "고사양게임 (4K·하이엔드)",   # U3
    "영상편집·방송",             # U4
    "디자인·3D설계",             # U5
    "개발·프로그래밍",           # U6
    "AI 작업",                  # U7
    "저소음·컴팩트 (특수형)",     # U8
]

PLATFORMS = ["인텔", "AMD"]


def _intended_empty(tier_no: int, usage_no: int) -> bool:
    """문서 §4가 명시한 세 패턴만 판정 — 근거는 파일 머리 주석 참조."""
    if usage_no == 8:                          # ③ U8 전체
        return True
    if tier_no <= 2 and usage_no in (3, 7):     # ① T1~T2 × 고사양게임·AI작업
        return True
    if tier_no >= 5 and usage_no == 1:          # ② T5~T7 × 사무·인터넷
        return True
    return False


def upgrade() -> None:
    op.create_table(
        "grid_cells",
        sa.Column("cell_id", sa.Integer, primary_key=True),
        sa.Column("tier", sa.String(12), nullable=False),
        sa.Column("usage", sa.String(20), nullable=False),
        sa.Column("platform", sa.String(4), nullable=False),
        sa.Column("budget_min", sa.Integer, nullable=False),
        sa.Column("budget_max", sa.Integer),   # NULL = 상한 없음(팝콘 X)
        sa.Column("intended_empty", sa.Boolean, nullable=False,
                   server_default=sa.false()),
        sa.UniqueConstraint("tier", "usage", "platform", name="uq_grid_cells_coord"),
    )
    op.execute(
        "COMMENT ON TABLE grid_cells IS "
        "'사전 생성 견적 격자의 칸 정의(티어×용도×플랫폼) — docs/design/"
        "prebuilt-grid-benchmark-2026-09-07.md. intended_empty=true 인 칸은 배치가 건너뛴다'"
    )
    op.execute(
        "COMMENT ON COLUMN grid_cells.intended_empty IS "
        "'의도적으로 비우는 칸(수요 없음/예산으로 불가능) — 문서 §4. 배치 실패로 빈 것과 다르다'"
    )

    op.create_table(
        "grid_quotes",
        sa.Column("quote_id", sa.Integer, primary_key=True),
        sa.Column("cell_id", sa.Integer,
                   sa.ForeignKey("grid_cells.cell_id"), nullable=False),
        sa.Column("batch_id", sa.String(20), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.func.now()),
        sa.Column("engine_note", sa.String(200)),
        sa.Column("total", sa.Integer),
        sa.Column("verdict", sa.String(20)),
        # 정상 / 예산 상한 초과 / 재고 소진 슬롯 있음 / 생성 실패 (tools/grid_generate.py 정본)
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", postgresql.JSONB),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_grid_quotes_cell_id", "grid_quotes", ["cell_id"])
    # 부분 유니크 — "칸당 현재본 하나"만 강제한다(과거본은 여러 개 있어도 된다)
    op.create_index(
        "uq_grid_quotes_current_per_cell", "grid_quotes", ["cell_id"],
        unique=True, postgresql_where=sa.text("is_current"),
    )
    op.execute(
        "COMMENT ON TABLE grid_quotes IS "
        "'격자 칸별 생성 견적 원장 — UPDATE 하지 않고 새 행을 INSERT, 이전 is_current를 "
        "false로 내린다. payload는 recommend 응답의 해당 티어 build 전체(JSONB)'"
    )
    op.execute(
        "COMMENT ON COLUMN grid_quotes.status IS "
        "'정상 / 예산 상한 초과 / 재고 소진 슬롯 있음 / 생성 실패 — tools/grid_generate.py 가 판정'"
    )

    conn = op.get_bind()
    filled, empty = 0, 0
    for tier_no, (tier_name, bmin, bmax) in enumerate(TIERS, start=1):
        for usage_no, usage_name in enumerate(USAGES, start=1):
            ie = _intended_empty(tier_no, usage_no)
            empty += ie
            filled += not ie
            for platform in PLATFORMS:
                conn.execute(sa.text(
                    "INSERT INTO grid_cells (tier, usage, platform, budget_min,"
                    " budget_max, intended_empty)"
                    " VALUES (:t, :u, :p, :bmin, :bmax, :ie)"),
                    {"t": tier_name, "u": usage_name, "p": platform,
                     "bmin": bmin, "bmax": bmax, "ie": ie})
    # 112칸 = 7티어×8용도×2플랫폼. filled/empty는 칸 «쌍»(tier×usage) 기준이라
    # 플랫폼을 곱해야 실제 행 수 — 확인은 downgrade 주석이 아니라 실행 시
    # grid_generate.py --dry 출력(§3 절차)이 한다, 여기서는 지어내지 않는다.
    print(f"[0072] grid_cells 시드: (tier x usage) 채움 {filled} / 의도적 빈칸 {empty} "
          f"x 플랫폼 2 = 총 {(filled + empty) * 2}행")


def downgrade() -> None:
    op.drop_index("uq_grid_quotes_current_per_cell", table_name="grid_quotes")
    op.drop_index("ix_grid_quotes_cell_id", table_name="grid_quotes")
    op.drop_table("grid_quotes")
    op.drop_table("grid_cells")
