# -*- coding: utf-8 -*-
"""격자 티어 경계 개정 — 2026 하반기 시장 반영 (grid_cells budget_min/max UPDATE)

■ 왜 — 0072 경계(60/100/150/220/300/450만)가 2026 시장과 맞지 않았다 (사장님 확정 2026-09-11)
  ① DDR5 가격 3~4배 폭등 — 메모리 한 슬롯이 옛 「팝콘 3」 예산(60만)의 큰 몫을 먹는다.
  ② 다나와 2026 상반기 조립PC 판매 TOP10 중 절반이 RTX 5060 Ti 구성 150만원대 —
     **150만 미만 판매 상위 구성이 없다.** 옛 경계는 150만 아래를 세 칸(팝콘 3·5·5+)으로
     잘게 나눴는데, 시장 밀도가 그 아래에 없다.
  ③ GPU 가격 계단(2026-09 실측): 5060 Ti ≈150만 / 5070 ≈200만 / 5070 Ti ≈300만 /
     5080 260만+ / 5090 600만+ (완성 견적 기준). 티어 경계는 이 계단에 맞아야 「한 티어
     = 한 GPU 등급」이 성립한다.
  ④ 우리 격자 실측: 첫 배치(20260907-01) 이후 **팝콘 3 은 16칸 전부 빈 채**였다 — 배치
     실패가 아니라 최저가 부품 합만으로도 60만을 넘는 구조적 불성립. 채울 수 없는 칸을
     격자에 두면 「비었다」가 정보가 아니라 잡음이 된다.

■ 새 경계 — 원 단위, [min, max) 반열림. **팝콘 X 도 상한을 둔다(1,500만)** — 0072 와 다르다
    팝콘 3      0 ~ 1,500,000
    팝콘 5      1,500,000 ~ 2,200,000
    팝콘 5+     2,200,000 ~ 3,000,000
    팝콘 7      3,000,000 ~ 4,000,000
    팝콘 7+     4,000,000 ~ 5,500,000
    팝콘 9      5,500,000 ~ 8,000,000
    팝콘 X      8,000,000 ~ 15,000,000
  ⑤ 팝콘 X 상한 근거(2026-09-11 사장님 확정 — 「900만원 넘는 로컬 LLM 머신도 팔고 있다」):
     우리 카탈로그 실측 — 판매중 GPU 단품에 RTX 6000 Ada 1,225만 · RTX PRO 5000 48GB
     1,388~1,915만 · RTX PRO 6000 Blackwell 96GB 2,575~2,625만 · H100 4,619만 · H200
     5,441만이 있고, 완제품(PC_COMPLETE) 워크스테이션은 3,465만~2억 2,546만(H100 NVL 4WAY).
     상한 없는 X 는 800만 로컬 LLM(RTX 5090 32GB)과 2,600만 96GB 머신을 한 칸에 섞는다.
     그래서 **X = 800~1,500만 = 로컬 LLM 머신(5090 ×2 / RTX PRO 5000 48GB)** 으로 겨냥하고,
     **1,500만 위는 격자가 아니라 「전문 상담」** 이다 — H100 4WAY 2억을 카드로 자동 추천하면
     「왜 이 부품인지 설명한다」(A-01)를 지킬 수 없다. 상한이 생겨 배치의 X 가상 상한 편법도
     필요 없어진다(tools/grid_generate.py 의 NULL 분기는 방어 코드로만 남는다).
  이름 7종은 그대로다(격자-2 명칭 결정 유지). 그래서 **행을 지우고 다시 만들지 않는다** —
  grid_cells.cell_id 는 grid_quotes.cell_id 의 FK 대상이고 grid_quotes 는 원장이다.
  UNIQUE(tier, usage, platform) 좌표도 그대로 보존되므로 budget_min/budget_max 만 UPDATE
  한다(112행). tools/grid_generate.py 는 이 값을 읽어 배치를 돌리므로 코드 상수 변경 없이
  다음 배치부터 새 경계가 적용된다(배치 쪽 팝콘 X 하한 미적용 결함은 별도 제작자 수정).

■ 기존 grid_quotes 처리 — 지우지 않고 is_current=false 로 내린다
  현재본 70행은 전부 옛 경계로 만든 견적이다. 경계가 바뀐 칸의 견적은 그 칸의 현재본
  자격이 없다(예: 옛 「팝콘 7」 150~220만 견적이 새 「팝콘 7」 300~400만 칸에 현재본으로
  남으면 고객에게 틀린 티어를 보여 준다). 원장·되돌림 규약(0072 머리 주석, CANON §2-4)대로
  UPDATE/DELETE 로 이력을 지우지 않고 **is_current 만 내린다** — 행은 배치 이력으로 남고,
  다음 배치 실행이 새 경계의 현재본을 INSERT 한다. 그 사이 진열대(is_current 집계)는
  0 이다 — A-126 확인법이 말하듯 그 상태로 화면에 내걸면 안 된다. DBA 는 적용 직후
  `tools/grid_generate.py` 를 돌린다.
  흔적: engine_note 에 '[0082 경계 개정으로 현재본 해제] ' 접두를 붙인다(VARCHAR(200),
  기존 문구는 뒤에 보존 — 잘림 방지로 left() 처리). 새 컬럼은 만들지 않는다.

■ intended_empty 재판정 — 새 경계 기준, 0072 ①②③ 패턴을 같은 기준으로 다시 잰 것
  ① 사무·인터넷(U1): **팝콘 3 만 채우고 팝콘 5 이상(6티어) 전부 비움**.
     0072 가 인용한 다나와 홈오피스 상한 112만은 새 경계에서 팝콘 3(0~150만) 안이다.
     0072 는 옛 경계에서 T5~T7 만 비웠는데(112만이 옛 팝콘 5+ 안이라 T1~T4 채움), 같은
     근거를 새 경계에 대면 T2 부터 수요 없음이 된다.
  ② 고사양게임(U3)·AI 작업(U7): **팝콘 3 비움, 팝콘 5 이상 채움**.
     150만 미만에서는 불가 — 실측 AI 하한(ai_workloads GPU required_power_watt 650W 급)
     최저 견적이 108만 GPU 단품이라 완성 견적이 150만을 넘는다. 0072 는 T1~T2 를
     비웠는데 새 팝콘 5(150~220만)는 5060 Ti 급이 들어가므로 채움으로 바뀐다.
  ③ 저소음·컴팩트(U8): 전부 비움 — 0072 그대로(문서 §4 「후순위」 유지).
  ④ 그 외(온라인게임 U2·영상편집 U4·디자인 U5·개발 U6): 전 티어 채움.
  칸 수(플랫폼 2 곱함): 비움 = U1 6티어×2 (12) + U3·U7 팝콘 3 ×2×2 (4) + U8 7×2 (14)
  = **30칸**, 채움 = 112 − 30 = **82칸**. 0072 는 28/84 였다 — U1 이 6칸 늘고 U3·U7 이
  4칸 줄었다(순증 +2). 아래 upgrade() 의 print 가 같은 수를 실행 시 다시 센다.

■ downgrade — 경계만 0072 값으로 되돌린다. is_current 는 복원하지 않는다
  upgrade 후 배치가 돌았으면 새 현재본이 이미 INSERT 돼 있어, 옛 행을 다시 true 로
  올리면 부분 유니크(uq_grid_quotes_current_per_cell)가 깨지거나 두 경계의 견적이 섞인다.
  되돌린 뒤에는 0072 경계로 배치를 다시 돌려 현재본을 만든다(사람 판단·DBA 절차).
  engine_note 접두는 이력이라 지우지 않는다. intended_empty 는 0072 _intended_empty 로 복원.

Revision ID: 0082
Revises: 0081
"""
import sys

from alembic import context, op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


# (티어명, budget_min원, budget_max원|None) — 2026-09-11 사장님 확정 경계
TIERS_2026H2 = [
    ("팝콘 3",  0,        1500000),
    ("팝콘 5",  1500000,  2200000),
    ("팝콘 5+", 2200000,  3000000),
    ("팝콘 7",  3000000,  4000000),
    ("팝콘 7+", 4000000,  5500000),
    ("팝콘 9",  5500000,  8000000),
    ("팝콘 X",  8000000,  15000000),
]

# 0072 경계 — downgrade 전용 사본(0072 를 import 하면 alembic 이 두 번 로드한다)
TIERS_0072 = [
    ("팝콘 3",  0,        600000),
    ("팝콘 5",  600000,   1000000),
    ("팝콘 5+", 1000000,  1500000),
    ("팝콘 7",  1500000,  2200000),
    ("팝콘 7+", 2200000,  3000000),
    ("팝콘 9",  3000000,  4500000),
    ("팝콘 X",  4500000,  None),
]

# 0072 USAGES 와 같은 순서(U1~U8) — 문자열은 grid_cells.usage 에 저장된 값 그대로
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

PLATFORM_COUNT = 2   # 인텔/AMD — 칸 수 집계용(UPDATE 는 플랫폼을 조건에 안 건다)

NOTE_PREFIX = "[0082 경계 개정으로 현재본 해제] "


def _intended_empty_2026h2(tier_no: int, usage_no: int) -> bool:
    """새 경계 기준 재판정 — 근거는 파일 머리 주석 ■ intended_empty 재판정."""
    if usage_no == 8:                          # ③ U8 전체
        return True
    if usage_no == 1 and tier_no >= 2:          # ① U1 은 팝콘 3 만 채움
        return True
    if usage_no in (3, 7) and tier_no == 1:     # ② U3·U7 은 팝콘 3 만 비움
        return True
    return False


def _intended_empty_0072(tier_no: int, usage_no: int) -> bool:
    """0072 판정 사본 — downgrade 복원용."""
    if usage_no == 8:
        return True
    if tier_no <= 2 and usage_no in (3, 7):
        return True
    if tier_no >= 5 and usage_no == 1:
        return True
    return False


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _log(msg: str) -> None:
    # --sql(오프라인) 모드에서는 stdout 이 SQL 스트림이라 stderr 로 보낸다
    print(msg, file=sys.stderr if context.is_offline_mode() else sys.stdout)


def _apply_tiers(tiers, judge) -> tuple[int, int]:
    """경계 UPDATE 7건 + intended_empty UPDATE 56건(티어×용도, 플랫폼 2행씩).
    리터럴 SQL 로 쓴다 — `alembic upgrade --sql` 오프라인 미리보기에서 값이 그대로
    보이도록(바인드 파라미터는 오프라인 모드에서 렌더되지 않는다)."""
    for tier_name, bmin, bmax in tiers:
        bmax_sql = "NULL" if bmax is None else str(bmax)
        op.execute(
            f"UPDATE grid_cells SET budget_min = {bmin}, budget_max = {bmax_sql}"
            f" WHERE tier = {_q(tier_name)}"
        )
    filled, empty = 0, 0
    for tier_no, (tier_name, _, _) in enumerate(tiers, start=1):
        for usage_no, usage_name in enumerate(USAGES, start=1):
            ie = judge(tier_no, usage_no)
            empty += ie
            filled += not ie
            op.execute(
                f"UPDATE grid_cells SET intended_empty = {'true' if ie else 'false'}"
                f" WHERE tier = {_q(tier_name)} AND usage = {_q(usage_name)}"
            )
    return filled * PLATFORM_COUNT, empty * PLATFORM_COUNT


def upgrade() -> None:
    filled, empty = _apply_tiers(TIERS_2026H2, _intended_empty_2026h2)

    # 옛 경계 견적의 현재본 자격 해제 — 행은 남긴다(원장). 흔적은 engine_note 접두.
    op.execute(
        "UPDATE grid_quotes SET is_current = false,"
        f" engine_note = left({_q(NOTE_PREFIX)} || coalesce(engine_note, ''), 200)"
        " WHERE is_current"
    )

    op.execute(
        "COMMENT ON TABLE grid_cells IS "
        "'사전 생성 견적 격자의 칸 정의(티어×용도×플랫폼) — docs/design/"
        "prebuilt-grid-benchmark-2026-09-07.md. 경계는 0082(2026-09-11)에서 2026 시장 기준으로 "
        "개정(0~150/220/300/400/550/800만/오픈). intended_empty=true 인 칸은 배치가 건너뛴다'"
    )
    _log(f"[0082] grid_cells 경계 개정: 채움 {filled} / 의도적 빈칸 {empty} = 총 {filled + empty}칸"
         " · grid_quotes 현재본 전부 해제(행 보존) — 배치 재실행 필요")


def downgrade() -> None:
    # 경계·intended_empty 만 0072 값으로. is_current 는 복원하지 않는다(머리 주석 ■ downgrade).
    filled, empty = _apply_tiers(TIERS_0072, _intended_empty_0072)
    op.execute(
        "COMMENT ON TABLE grid_cells IS "
        "'사전 생성 견적 격자의 칸 정의(티어×용도×플랫폼) — docs/design/"
        "prebuilt-grid-benchmark-2026-09-07.md. intended_empty=true 인 칸은 배치가 건너뛴다'"
    )
    _log(f"[0082↓] grid_cells 경계 0072 값으로 복원: 채움 {filled} / 빈칸 {empty}"
         " · grid_quotes.is_current 는 복원 안 함 — 0072 경계로 배치 재실행 필요")
