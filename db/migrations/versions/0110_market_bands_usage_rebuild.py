# -*- coding: utf-8 -*-
"""예산 구간·용도 체계를 «시장 기준»으로 재구축한다 — 격자 v4 (2026-09-21).

■ 왜 — 사장님 지적 「관리자 격자에 칸 없음이 너무 많다」에서 출발해 조사 4회.
  결론은 **예산 구간 정의 자체가 틀렸다**였다.

  (1) 구간을 «먼저 고정»하고 그 안에서 견적을 내야 하는데 지금은 반대다.
      `grid_cells.budget_min/max` 가 «견적 총액 관측값»인데 이름이 구간처럼 생겼다.
      그래서 같은 `NB_L2` 가 하한 33만~171만으로 갈려 보였다.
      -> 이 마이그레이션이 그 둘을 `quote_low` / `quote_high` 로 개명한다.
         구간의 단일 원천은 `grid_budget_bands` 한 벌뿐이다.

  (2) 기준이 시장이 아니었다. 현행 13구간의 유일한 출처가 `pc_tier_ladder.json`
      (= 우리 실판매 234벌)이다. 사장님 확정 ②는 «우리가 팔 수 있는 것과
      무관하게 시장 구간을 정한다»였다.
      -> 정화 표본 **782벌**(`D:/Hermes-Workspace/band_redesign_v2.json`)의
         10만원 칸 히스토그램 **국소 최소**에서 나온 경계로 갈아 끼운다.
      ⚠ 앞 조사 2회(`band_redesign.md`·`market_gap.md`)는 오염 표본이다 —
         모니터·가구·노트북 433행이 「조립 PC」로 잡혔다. 그 수치는 쓰지 않았다.

  (3) 용도 13종이 시장과 어긋났다. 상품명 782벌에 「엑셀·화상회의·줌·팀즈·재택」이
      **0회**다 — 시장은 단순/복합 사무를 구분하지 않는다.
      -> 사장님 확정대로 합치고(④) AI 를 둘로 가른다.

  (4) `intended_empty` 가 boolean 이라 「시장에도 없다」와 「표본이 없어 모른다」를
      구분하지 못했다. 게다가 134칸 전부 false 이고 **쓰는 코드가 없었다**(읽기만).
      -> `handling_state` 4값으로 바꾸고 이 마이그레이션이 실제로 값을 넣는다.

■ 새 구간 — 사장님 확정 ③ 그대로
  게임 7구간  G0 90~120 · G1 120~180 · G2 180~220 · G3 220~300 · G4 300~410
              · G5 410~650 · G6 650만~
  비게임 8구간 W0 ~90 · W1 90~110 · W2 110~150 · W3 150~220 · W4 220~280
              · W5 280~460 · W6 460~780 · W7 780만~

  ★ 게임을 6구간이 아니라 **7구간으로 한다**(사장님이 판단을 맡긴 자리).
    근거 둘 — 하나는 시장, 하나는 엔진이다.
    · 시장: 10만원 칸으로 **650만이 0벌**이다(좌 640만 8벌 / 우 660만 0 · 670만 1).
      게임축에서 300만(2벌) 다음으로 깊은 골이고, 그 위 G6 에 13벌이 있다.
    · 엔진(이게 결정적이다): 6구간이면 G5 가 410만~ **열린 구간**이 된다.
      열린 구간의 `budget_label` 은 「…이상」이라야 정직한데, 그러면
      `api/candidates.py _budget_cap()` 이 None 을 주고 `_order_of` 가
      median(풀 중앙값)으로 되돌아간다(0105 헤더가 실측으로 적어 둔 결함 B).
      그 결과 **B/4K(T4 하한 439만)와 C/4K(T5 하한 1,267만)가 같은 구간·같은
      예산 라벨**을 받아 0105 가 없앤 «두 칸이 같은 body 를 보낸다»가 되살아난다.
      7구간이면 G5(410~650 · 닫힘)에 T4 가, G6(650만~)에 T5 가 따로 들어간다.
    · G6 상한을 닫지 않은 이유는 0105 의 GB_ULTRA 와 같다 — 그 칸(C/4K)은
      자기 스펙 하한만으로 1,267만이 나와 구간 이름이 거짓이 되지 않는다.
    ⚠ 유보: G6 표본은 **13벌**이다. 얇다는 것을 감추지 않는다.

  ★ G0 하한 90만 — 사장님 ③ 「우리제품중 가장 싼 제품의 하한에」.
    시장 외장 GPU 최저 945,590(포유 RTX3050) · 우리 외장 GPU 칸 최저 908,800.
    ⚠ **대가가 있다**: 현행 `GB_IGPU`(65~90만)가 통째로 구간 밖이 된다.
      그 칸의 실측 645,000원(L/1080p 내장그래픽 AMD 가성비)은 새 격자에
      **자리가 없다**. 사장님 확정을 그대로 따른 결과이고, 지어내 메우지 않는다.

  ★ 열린 구간의 budget_label — W7 만 예외로 시장 중앙값을 쓴다.
    「780만원 이상」으로 두면 위와 같은 median 되돌림이 일어나, 3D 렌더링 W7 칸이
    자기 하한보다 낮은 값을 내민다(0105 가 NB_L6 에서 실측한 그것).
    그래서 W7 표본 35벌의 **중앙값 14,914,800** 을 라벨로 쓴다(band_redesign_v2 §3-2).
    지어낸 값이 아니라 그 구간 시장의 실측 중앙값이다.

■ 용도 재편 — 사장님 확정 ④ 전부
    사진·후보정(2벌) -> 디자인·조판       방송 송출(5벌) -> 영상편집
    단순+복합 사무용 -> 「사무용」
    AI 작업 -> 「학습용 AI」 / 「사무형 AI」 (판별 = 외장 GPU 유무 · VRAM 문턱 없음)

  ⚠ **`usage_floors.usage_key` 를 하나도 지우지 않는다.** `api/talk.py:157` 과
    `api/talk_schema.py` 가 그 표를 팝콘톡 어휘의 정본으로 읽는다 — 키를 지우면
    팝콘톡이 「포토샵」·「방송」·「업무용」을 못 알아듣는다.
    그래서 **키는 남기고 `usage_label` 만 합친다**:
      office_simple  -> 사무용      office_complex -> 사무용
      design_photo   -> 디자인·조판  stream         -> 영상편집
    각 키의 **숫자 하한은 그대로 둔다**. 「업무용」이라 말한 고객은 여전히
    office_complex 의 RAM 16GB 를 받고, 「사무용」이라 말한 고객은 office_simple 의
    8GB 를 받는다 — 합친 것은 «격자에서 칸을 가르는 이름»이지 하한이 아니다.

  AI 분할만 키를 하나 **더한다**(`ai_office`). 지우는 것이 아니라 더하는 것이라
  팝콘톡 어휘가 깨지지 않는다. `ai` 는 「학습용 AI」로 이름만 바뀐다.
  ⚠ `ai_office` 에 `usage_tier_rules` 를 두지 않았다 — 표본 15벌의 부품 구성을
    재지 않았으므로 예산별 겨냥값의 근거가 없다. 지어내지 않고 비워 둔다.

■ 원장 52건 — 고치지 않는다(규약). 매핑표 `usage_label_map` 을 신설해 잇는다.
  `consult_sessions.constraints` 에 남은 옛 용도 이름(단순 사무용 31 · 복합 사무용 21
  · 방송 송출 21 · 사진·후보정 17 …)은 원장이라 그대로 둔다. 읽는 쪽이 이 표로 옮긴다.

Revision ID: 0110
Revises: 0109
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0110"
down_revision = "0109"
branch_labels = None
depends_on = None


# ── 새 예산 구간 ────────────────────────────────────────────────────────────
# (band_key, axis, label, min, max, budget_label, gpu_required, engine_usage, n, source, sort)
#
# budget_label 형식 제약: `api/candidates.py _budget_cap()` 의 정규식
#   (-)?\s*(\d{1,3}(?:,\d{3})+|\d+)\s*만  이 상한을 뽑고 「이상」이 있으면 None.
#   벗어나면 엔진이 **조용히 무시**하고 median 으로 되돌아간다(0105 가 실측).
_SRC = "band_redesign_v2.md §3 — 정화 표본 782벌(게임 421 / 비게임 361)의 10만원 칸 국소 최소"

BANDS = [
    # ── 게임 7구간 (모수 421벌 · 미배정 0) ───────────────────────────────
    ("G0", "game", "내장그래픽·저사양", 900000, 1200000, "120만원", True, None, 4,
     _SRC + ". G0 하한 90만은 사장님 확정 — 시장 외장 GPU 최저 945,590원(포유컴퓨터"
     " 퍼포먼스PC 49 R5 5600 RTX3050) · 우리 외장 GPU 칸 최저 908,800원. 그 아래"
     " 819,900원 1벌은 상품명이 「사무용 i5-14400」이고 GPU 가 내장(UHD 730)이라"
     " 게임 본체로 세지 않았다. 표본 4벌(80/90/100/110만 각 1) — 120만부터 10벌로 급증",
     10),
    ("G1", "game", "FHD", 1200000, 1800000, "180만원", True, None, 64,
     _SRC + ". 경계 180만 칸 11벌(좌 170만 11 / 우 190만 13) — 완만한 골."
     " 중앙값 1,569,110", 20),
    ("G2", "game", "QHD", 1800000, 2200000, "220만원", True, None, 50,
     _SRC + ". 경계 220만 칸 14벌(좌 210만 11 / 우 230만 12). 중앙값 1,998,670", 30),
    ("G3", "game", "4K 입문", 2200000, 3000000, "300만원", True, None, 77,
     _SRC + ". 경계 300만 칸 **2벌** — 게임축에서 가장 깊은 골(좌 290만 9 / 우 310만 5)."
     " 중앙값 2,503,360", 40),
    ("G4", "game", "4K 고성능", 3000000, 4100000, "410만원", True, None, 107,
     _SRC + ". 경계 400만 칸 4벌(좌 390만 12 / 우 410만 7). 중앙값 3,549,000", 50),
    ("G5", "game", "4K 최고사양", 4100000, 6500000, "650만원", True, None, 106,
     _SRC + ". 경계 **650만 칸 0벌**(좌 640만 8 / 우 660만 0 · 670만 1)."
     " 중앙값 4,893,565. 이 0벌이 게임축을 7구간으로 가른 시장 근거다", 60),
    ("G6", "game", "4K 극한·다중GPU", 6500000, None, "650만원 이상", True, None, 13,
     _SRC + ". 상한 없음 — 표본 최고 23,710,000(중앙값 7,700,000)."
     " ⚠ 표본 13벌로 얇다. 상한을 닫지 않은 이유는 0105 GB_ULTRA 와 같다 —"
     " 이 구간의 유일한 칸 C/4K 는 자기 스펙 하한(spec_tiers T5)만으로 실측"
     " 12,676,100 이 나와, 예산 라벨이 상한을 주지 않아도 구간 이름이 거짓이 되지"
     " 않는다. 반대로 닫으면 T5 하한이 상한을 넘어 모든 구성이 「예산 상한 초과」가 된다",
     70),

    # ── 비게임 8구간 (모수 361벌 · 미배정 0) ─────────────────────────────
    ("W0", "nongame", "사무·웹", 0, 900000, "90만원", True, None, 74,
     _SRC + ". 경계 90만 칸 18벌 뒤 100만이 11벌로 꺾인다. 중앙값 657,450", 100),
    ("W1", "nongame", "가정·실무", 900000, 1100000, "110만원", True, None, 29,
     _SRC + ". 경계 110만 칸 18벌(좌 100만 11 / 우 120만 14) — ⚠ 얕은 골이다."
     " 중앙값 990,000", 110),
    ("W2", "nongame", "실무 주력", 1100000, 1500000, "150만원", True, None, 52,
     _SRC + ". 경계 150만 칸 11벌(좌 140만 5 / 우 160만 7)."
     " ⚠ 실제 최저점은 140만(5벌)이다 — 150만을 쓴 것은 사장님 확정 경계이기 때문이고,"
     " 그 사실을 감추지 않는다. 중앙값 1,249,500", 120),
    ("W3", "nongame", "전문 입문", 1500000, 2200000, "220만원", True, None, 54,
     _SRC + ". 경계 220만 칸 3벌(좌 210만 2 / 우 230만 3). 중앙값 1,813,615", 130),
    ("W4", "nongame", "전문", 2200000, 2800000, "280만원", True, None, 28,
     _SRC + ". 경계 280만 칸 3벌(좌 270만 3 / 우 290만 5). 중앙값 2,498,385", 140),
    ("W5", "nongame", "하이엔드", 2800000, 4600000, "460만원", True, None, 45,
     _SRC + ". 경계 460만 칸 1벌(좌 450만 0 / 우 470만 0) — 450~470만이 전부 0~1벌인"
     " 넓은 골. 중앙값 3,490,000", 150),
    ("W6", "nongame", "워크스테이션", 4600000, 7800000, "780만원", True, None, 44,
     _SRC + ". 경계 **780만 칸 0벌**(좌 770만 1 / 우 790만 0 · 800만 0)."
     " 중앙값 6,520,980. 사장님 확정 ③ 「최상위를 쪼갠다」의 비게임 쪽 골이 여기다", 160),
    ("W7", "nongame", "AI 학습·서버", 7800000, None, "1,491만원", True, None, 35,
     _SRC + ". 상한 없음 — 표본 최고 41,919,990."
     " ⚠ budget_label 이 「780만원 이상」이 아니라 **1,491만원**인 이유(0105 NB_L6 과"
     " 같은 실측 근거): 「이상」이 들어가면 _budget_cap 이 None 을 주고 _order_of 가"
     " median(풀 중앙값)으로 되돌아가, 이 구간 칸이 자기 하한 780만보다 낮은 값을"
     " 내민다. 1,491만원은 지어낸 값이 아니라 **이 구간 시장 표본 35벌의 중앙값**"
     "(14,914,800)이다", 170),
]

PLATFORMS = ["인텔", "AMD"]

# ── 칸 상태 4값 — 사장님 확정 ⑥ 「일부러 비움 / 모름 / 채울 예정」 + 취급함 ──
ST_ACTIVE = "취급함"          # 배치가 견적을 만든다(옛 intended_empty=false 자리)
ST_DELIBERATE = "일부러 비움"  # 시장 표본은 있으나 우리가 그 구간을 취급하지 않는다
ST_UNKNOWN = "모름"           # 시장 표본이 0이라 있는지 없는지 모른다
ST_PLANNED = "채울 예정"      # 취급하기로 했으나 아직 견적이 없다
STATES = (ST_ACTIVE, ST_DELIBERATE, ST_UNKNOWN, ST_PLANNED)

# ── 비게임 용도별 주력 구간 — 사장님 확정 ⑤ ────────────────────────────
#   값 = (주력 구간 하한 index, 상한 index, 교차표 8칸, 근거)
#   교차표는 `usage_recount.json > ③ 비게임축_중복허용` 에 AI 분할·합치기를 적용한 것
#   (재현: D:/Hermes-Workspace/plan_grid.py — final_grid_calc2.py 와 같은 계산).
#   주력 판정 = 10% 문턱(그 용도 표본의 10% 이상인 구간의 최저~최고를 잇는다).
W = ["W0", "W1", "W2", "W3", "W4", "W5", "W6", "W7"]
NONGAME_PLAN = {
    "사무용": (0, 3, [67, 20, 34, 33, 7, 1, 1, 0],
              "사무 163벌(단순 156 + 복합 7 합산 — 상품명 782벌에 「엑셀·화상회의·줌·"
              "팀즈·재택」이 0회라 시장이 둘을 구분하지 않는다). 10% 문턱 W0~W3."
              " ⚠ W4~W6 에 9벌이 있으나 전체의 5.5%라 주력으로 보지 않았다"),
    "영상편집": (3, 6, [0, 2, 7, 30, 19, 71, 19, 1],
               "영상편집 144 + 방송 송출 5 = 149벌(방송은 영상편집과 항상 함께 나오고"
               " 전용이 0벌이다). 10% 문턱 W3~W6"),
    "디자인·조판": (3, 6, [3, 3, 4, 27, 19, 41, 19, 2],
                 "디자인·조판 116 + 사진·후보정 2 = 118벌(사진 2벌은 같은 상품의 용량"
                 " 변형이고 둘 다 디자인과 겹친다). 10% 문턱 W3~W6"),
    "캐드·설계": (3, 5, [5, 4, 5, 21, 12, 24, 3, 1],
                "75벌. 10% 문턱 W3~W5. ⚠ **전용이 0벌**이다 — 「캐드」가 판매자 키워드"
                " 나열의 한 낱말로만 나온다. 그래도 칸을 두는 것은 «전용»이 아니라"
                " «전체»로 판정했기 때문이다(전용으로 판정하면 캐드·방송·사진 용도의"
                " 칸이 통째로 사라진다)"),
    "주식·트레이딩": (2, 4, [2, 1, 6, 18, 7, 1, 0, 0], "35벌. 10% 문턱 W2~W4"),
    "3D 렌더링": (6, 7, [5, 2, 4, 2, 4, 3, 9, 5],
                "34벌. ⚠ 10% 문턱은 W0~W7 전부를 내놓았지만 **사장님이 「좁힌다(3D는"
                " 수요가 많지 않음)」으로 확정**했다. 근거도 있다 — 저가 8벌(W0~W2)이"
                " CPU 단품 1벌 + 레노버 워크스테이션의 «용도 나열» 7벌"
                "(「딥러닝 3D 렌더링 CAD 서버용 AI 게이밍」)이고, 진짜 3D 전용 상품은"
                " 203만부터다. usage_recount.json 의 3D 「주력대」도 W6 이다"),
    "학습용 AI": (5, 7, [0, 0, 0, 0, 2, 6, 17, 9],
                "AI 62벌을 **외장 GPU 유무**로 갈라 나온 34벌(사장님 확정 ④)."
                " VRAM 문턱은 걸지 않았다 — 검증 표본이 6벌뿐이라 문턱을 정할 근거가"
                " 없다. 10% 문턱 W5~W7"),
    "음악 작업": (1, 3, [1, 5, 10, 7, 0, 0, 0, 0],
                "23벌. 10% 문턱 W1~W3. ⚠ 표본 최고가가 2,009,000원이라 W4 이상이"
                " 전부 0인데, 23벌이 판매자 2곳의 변형이라 시장을 대표하는지 확신이 없다"),
    "사무형 AI": (0, 4, [6, 2, 3, 2, 2, 0, 0, 0],
                "AI 62벌 중 외장 GPU 가 없는 15벌(내장그래픽 + NPU 내장 CPU)."
                " 10% 문턱 W0~W4. ⚠ AI 62벌 중 13벌은 spec 에 GPU 정보가 없어"
                " **어느 쪽에도 넣지 않았다** — 추정으로 메우지 않는다"),
    "개발": (5, 6, [0, 1, 0, 0, 0, 7, 3, 0],
           "11벌. 10% 문턱 W5~W6. ⚠ 표본이 얇다(11벌)"),
}

# ── 게임: (등급,해상도) -> 예산 구간 ────────────────────────────────────
# 0105 와 **같은 규칙**이다: 그 칸 스펙 하한의 실측 가성비 최저가를 담을 수 있는
# 첫 구간부터 한 칸 위까지. 「한 칸 위」는 상한이 닫힌 구간일 때만 붙인다
# (열린 구간을 붙이면 median 되돌림이 일어난다 — 0105 _game_bands_for 주석 참조).
TIER_MIN_MEASURED = {"T1": 921100, "T2": 1836900, "T2+T4": 1918600,
                     "T3": 2691400, "T4": 4394000, "T5": 12676100}
GAME_LADDER = ["G0", "G1", "G2", "G3", "G4", "G5", "G6"]
GAME_MAX = {"G0": 1200000, "G1": 1800000, "G2": 2200000, "G3": 3000000,
            "G4": 4100000, "G5": 6500000, "G6": None}


def _game_bands_for(gpu_tier, cpu_override):
    key = f"{gpu_tier}+{cpu_override}" if cpu_override else gpu_tier
    cost = TIER_MIN_MEASURED[key]
    idx = next((i for i, b in enumerate(GAME_LADDER)
                if GAME_MAX[b] is None or GAME_MAX[b] >= cost), None)
    if idx is None:
        return []
    out = [GAME_LADDER[idx]]
    if idx + 1 < len(GAME_LADDER) and GAME_MAX[GAME_LADDER[idx + 1]] is not None:
        out.append(GAME_LADDER[idx + 1])
    return out


# ── 용도 라벨 재편 (키는 유지 · 라벨만 합친다) ──────────────────────────
USAGE_LABEL_RENAME = {
    "office_simple": "사무용",
    "office_complex": "사무용",
    "design_photo": "디자인·조판",
    "stream": "영상편집",
    "ai": "학습용 AI",
}
# 격자 용도 라벨이 usage_floors.match() 에 **반드시 걸려야** 한다 — 걸리지 않으면
# 배치가 보내는 「용도」를 엔진이 못 알아듣고 하한 없이 견적을 만든다.
# 「사무용」·「디자인·조판」·「영상편집」·「캐드·설계」·「3D 렌더링」·「음악 작업」·
# 「주식·트레이딩」·「개발」은 기존 match_terms 에 이미 걸린다(실측).
# 새 라벨 둘만 어휘를 더한다.
USAGE_TERM_ADD = {
    "ai": ["학습용 AI", "AI 학습", "모델 학습", "파인튜닝", "LLM"],
}

# 사무형 AI — 새 키. 하한은 「외장 GPU 없음」이 정의라 GPU 하한을 걸지 않는다.
# ⚠ sort_order 를 office_simple(62)보다 **앞**에 둬야 한다. 「사무형 AI」에
#   「사무」가 들어 있어 match() 가 먼저 맞는 하나만 쓰는 규칙 때문에 office_simple
#   에 먹힌다(실측으로 확인하고 정한 값이다).
AI_OFFICE_TERMS = ["사무형 AI", "AI PC", "NPU", "코파일럿", "Copilot", "온디바이스 AI",
                   "로컬 AI", "AI 비서", "문서 AI"]
AI_OFFICE_FLOORS = [
    ("RAM", "capacity_gb", "gte", 16, "사무형 AI 메모리",
     "{v}GB — 내장 NPU 가속은 모델을 시스템 메모리에 올린다"),
    ("SSD", "capacity_gb", "gte", 500, "사무형 AI 저장 용량", "{v}GB"),
]

# ── 원장 매핑 — 옛 용도 이름 -> 새 이름 (원장은 고치지 않는다) ──────────
LABEL_MAP = [
    ("단순 사무용", "사무용", "0110 합병 — 시장이 단순/복합을 구분하지 않는다(상품명 782벌에 「엑셀·화상회의·줌·팀즈·재택」 0회)"),
    ("복합 사무용", "사무용", "0110 합병 — 위와 같다. 복합 7벌은 전부 HP 프로타워 400 G9 한 모델의 구성 변형이었다"),
    ("사무·인강", "사무용", "0090 이전 옛 이름 — 원장 596건"),
    ("사무·인터넷", "사무용", "옛 이름 — 원장 30건"),
    ("사무", "사무용", "옛 이름 — 원장 79건"),
    ("사진·후보정", "디자인·조판", "0110 합병 — 시장 표본 2벌이고 그 2벌도 같은 상품의 용량 변형이다"),
    ("디자인", "디자인·조판", "0108 분할 이전 이름 — 원장 127건"),
    ("디자인·3D설계", "디자인·조판", "옛 이름 — 원장 124건. ⚠ 3D 를 포함한 이름이라 정확한 대응이 아니다"),
    ("방송 송출", "영상편집", "0110 합병 — 방송 5벌이 전부 영상편집·게임과 함께 나오고 전용이 0벌이다"),
    ("방송·스트리밍", "영상편집", "옛 이름"),
    ("영상편집·방송", "영상편집", "옛 이름 — 원장 127건"),
    ("영상 편집", "영상편집", "띄어쓰기 변형"),
    ("3D 그래픽", "3D 렌더링", "0104 분할 이전 이름 — 원장 60건"),
    ("캐드", "캐드·설계", "옛 이름 — 원장 24건"),
    ("개발·프로그래밍", "개발", "옛 이름 — 원장 126건"),
    ("고사양 게임", "게임", "격자 게임축은 등급·해상도로 가른다 — 용도 이름으로는 「게임」 하나다"),
    ("고사양게임 (4K·하이엔드)", "게임", "옛 이름"),
    ("온라인게임 (라이트~중급)", "게임", "옛 이름"),
    ("게임(롤·발로란트)", "게임", "옛 이름"),
    ("가벼운 게임", "게임", "옛 이름"),
    ("게임용", "게임", "옛 이름"),
    ("내장그래픽 캐주얼", "게임", "0105 GB_IGPU 의 engine_usage_label — 0110 에서 그 구간이 사라졌다"),
    ("캐주얼 게임", "게임", "usage_floors game_casual 라벨"),
    # AI — 원장의 「AI 작업」은 외장 GPU 유무를 알 수 없다. 지어내지 않는다.
    ("AI 작업", None, "⚠ 대응 없음 — 0110 이 AI 를 외장 GPU 유무로 갈랐는데 원장의 이 값에는 그 정보가 없다. 「모름」으로 둔다"),
    ("AI", None, "⚠ 대응 없음 — 위와 같다"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ─────────────────────────────────────────────────────────────────
    # 1. grid_cells: budget_min/max -> quote_low/quote_high 개명
    # ─────────────────────────────────────────────────────────────────
    op.alter_column("grid_cells", "budget_min", new_column_name="quote_low")
    op.alter_column("grid_cells", "budget_max", new_column_name="quote_high")
    op.execute(
        "COMMENT ON COLUMN grid_cells.quote_low IS "
        "'배치가 실제로 만든 견적 총액의 **관측** 하단(가성비 구성). 예산 구간이 "
        "아니다 — 구간의 단일 원천은 grid_budget_bands 다. 0110 이 budget_min 에서 "
        "개명했다: 0092 가 뜻을 입력->관측으로 바꾸고 0105 가 범위로 또 바꾸는 동안 "
        "이름이 그대로라 «같은 NB_L2 의 하한이 33만~171만»처럼 읽혔다'"
    )
    op.execute(
        "COMMENT ON COLUMN grid_cells.quote_high IS "
        "'배치가 실제로 만든 견적 총액의 관측 상단(고성능 구성). 위 quote_low 참조'"
    )

    # ─────────────────────────────────────────────────────────────────
    # 2. intended_empty(boolean) -> handling_state(4값)
    # ─────────────────────────────────────────────────────────────────
    op.add_column("grid_cells", sa.Column("handling_state", sa.Text(), nullable=True))
    op.add_column("grid_cells", sa.Column("handling_note", sa.Text(), nullable=True))
    conn.execute(sa.text(
        "UPDATE grid_cells SET handling_state = CASE WHEN intended_empty"
        " THEN :de ELSE :ac END"), {"de": ST_DELIBERATE, "ac": ST_ACTIVE})
    op.alter_column("grid_cells", "handling_state", nullable=False)
    op.create_check_constraint(
        "ck_grid_cells_handling_state", "grid_cells",
        "handling_state IN ('%s')" % "','".join(STATES))
    op.drop_column("grid_cells", "intended_empty")
    op.execute(
        "COMMENT ON COLUMN grid_cells.handling_state IS "
        "'칸의 취급 상태 4값(0110 · 사장님 확정 ⑥). 옛 intended_empty(boolean)는 "
        "«시장에도 없다»와 «표본이 없어 모른다»를 구분하지 못했고, 134칸 전부 false "
        "인 채 쓰는 코드가 없었다. "
        "취급함=배치가 견적을 만든다 / 일부러 비움=시장 표본은 있으나 우리가 그 구간을 "
        "취급하지 않는다(주력 구간 밖) / 모름=시장 표본이 0이라 판단 근거가 없다 / "
        "채울 예정=취급하기로 했으나 아직 견적이 없다'"
    )

    # ─────────────────────────────────────────────────────────────────
    # 3. 예산 구간 교체 — 옛 13구간을 지우고 새 15구간을 넣는다
    #    ⚠ grid_cells 가 FK 로 band_key 를 잡고 있으므로 칸을 먼저 비운다.
    # ─────────────────────────────────────────────────────────────────
    conn.execute(sa.text("DELETE FROM game_cell_map"))
    conn.execute(sa.text("DELETE FROM workload_cell_map"))
    conn.execute(sa.text("DELETE FROM grid_quotes"))
    conn.execute(sa.text("DELETE FROM grid_cells"))
    conn.execute(sa.text("DELETE FROM grid_budget_bands"))
    for (bk, axis, label, bmin, bmax, blabel, gpu_req, eng, n, src, sort) in BANDS:
        conn.execute(sa.text(
            "INSERT INTO grid_budget_bands (band_key, axis, label, budget_min_won,"
            " budget_max_won, budget_label, gpu_required, engine_usage_label,"
            " sample_n, source, sort_order)"
            " VALUES (:k,:a,:l,:mn,:mx,:bl,:gr,:eu,:n,:s,:o)"),
            {"k": bk, "a": axis, "l": label, "mn": bmin, "mx": bmax, "bl": blabel,
             "gr": gpu_req, "eu": eng, "n": n, "s": src, "o": sort})

    # ─────────────────────────────────────────────────────────────────
    # 4. 용도 재편 — 키는 유지, 라벨만 합친다(팝콘톡 어휘 보존)
    # ─────────────────────────────────────────────────────────────────
    for key, label in USAGE_LABEL_RENAME.items():
        conn.execute(sa.text(
            "UPDATE usage_floors SET usage_label=:l WHERE usage_key=:k"),
            {"l": label, "k": key})
    for key, terms in USAGE_TERM_ADD.items():
        for t in terms:
            # ⚠ jsonb 의 `?` 연산자를 쓰지 않는다 — SQLAlchemy 가 bindparam 으로 읽어
            #   «syntax error at or near ":"» 가 난다. 같은 뜻의 jsonb_exists() 를 쓴다.
            conn.execute(sa.text(
                "UPDATE usage_floors SET match_terms = match_terms || CAST(:t AS JSONB)"
                " WHERE usage_key=:k AND NOT jsonb_exists(match_terms, :raw)"),
                {"t": json.dumps([t], ensure_ascii=False), "k": key, "raw": t})

    # 사무형 AI — 새 키(지우는 게 아니라 더한다)
    terms_json = json.dumps(AI_OFFICE_TERMS, ensure_ascii=False)
    so = 40
    for (slot, field, op_, val, label, fmt) in AI_OFFICE_FLOORS:
        conn.execute(sa.text(
            "INSERT INTO usage_floors (usage_key, usage_label, match_terms, slot,"
            " field, op, value, label, detail_fmt, active, sort_order)"
            " VALUES ('ai_office','사무형 AI', CAST(:terms AS JSONB), :slot, :field,"
            " :op, :val, :label, :fmt, true, :so)"),
            {"terms": terms_json, "slot": slot, "field": field, "op": op_,
             "val": val, "label": label, "fmt": fmt, "so": so})
        so += 1

    # ─────────────────────────────────────────────────────────────────
    # 5. 원장 매핑표
    # ─────────────────────────────────────────────────────────────────
    op.create_table(
        "usage_label_map",
        sa.Column("legacy_label", sa.String(60), primary_key=True),
        sa.Column("canonical_label", sa.String(30), nullable=True),
        sa.Column("note", sa.Text, nullable=False),
    )
    op.execute(
        "COMMENT ON TABLE usage_label_map IS "
        "'원장(consult_sessions.constraints)에 남은 옛 용도 이름 -> 현행 격자 용도 "
        "이름. 원장은 고치지 않는다(규약) — 읽는 쪽이 이 표로 옮긴다. "
        "canonical_label 이 NULL 이면 «대응을 모른다»는 뜻이고 그 사유가 note 에 있다 "
        "— 지어내 잇지 않는다'"
    )
    for legacy, canon, note in LABEL_MAP:
        conn.execute(sa.text(
            "INSERT INTO usage_label_map (legacy_label, canonical_label, note)"
            " VALUES (:l,:c,:n)"), {"l": legacy, "c": canon, "n": note})

    # ─────────────────────────────────────────────────────────────────
    # 6. 격자 시드 — 용도 x 구간 x 플랫폼
    #    주력 구간 = 취급함 / 주력 밖이되 시장 표본 있음 = 일부러 비움
    #    / 시장 표본 0 = 모름
    # ─────────────────────────────────────────────────────────────────
    n_active = n_delib = n_unknown = 0
    for usage, (lo, hi, counts, why) in NONGAME_PLAN.items():
        core = set(range(lo, hi + 1))
        for i, band_key in enumerate(W):
            n = counts[i]
            if i in core:
                state, note = ST_ACTIVE, f"주력 구간({W[lo]}~{W[hi]}) — 시장 표본 {n}벌. {why}"
                n_active += 1
            elif n > 0:
                state = ST_DELIBERATE
                note = (f"시장 표본 {n}벌이 있으나 주력 구간({W[lo]}~{W[hi]}) 밖이다 —"
                        f" 사장님 확정 ⑤ 「주력 구간만 남긴다」. {why}")
                n_delib += 1
            else:
                state = ST_UNKNOWN
                note = (f"시장 표본 0벌 — 이 용도의 이 구간에 상품이 있는지 없는지"
                        f" 판단할 근거가 없다(782벌 표본 기준). {why}")
                n_unknown += 1
            for pf in PLATFORMS:
                conn.execute(sa.text(
                    "INSERT INTO grid_cells (usage, budget_band_key, platform,"
                    " band_note, handling_state, handling_note)"
                    " VALUES (:u,:b,:p,:n,:s,:hn)"),
                    {"u": usage, "b": band_key, "p": pf, "n": note,
                     "s": state, "hn": note})

    gtiers = conn.execute(sa.text(
        "SELECT grade, resolution, gpu_tier_key, cpu_tier_key_override"
        " FROM game_grade_resolution_tiers ORDER BY grade, resolution")).mappings().all()
    game_n = 0
    for gt in gtiers:
        key = (f"{gt['gpu_tier_key']}+{gt['cpu_tier_key_override']}"
               if gt["cpu_tier_key_override"] else gt["gpu_tier_key"])
        bands = _game_bands_for(gt["gpu_tier_key"], gt["cpu_tier_key_override"])
        note = (f"(등급 {gt['grade']} x {gt['resolution']}) = spec_tiers {key}."
                f" 실측 가성비 최저가 {TIER_MIN_MEASURED[key]:,}원을 담을 수 있는 첫"
                " 구간부터 한 칸 위까지(상한이 닫힌 구간일 때만 — 0105 와 같은 규칙)")
        for band_key in bands:
            for pf in PLATFORMS:
                conn.execute(sa.text(
                    "INSERT INTO grid_cells (usage, budget_band_key, game_grade,"
                    " game_resolution, platform, band_note, handling_state, handling_note)"
                    " VALUES ('게임',:b,:g,:r,:p,:n,:s,:hn)"),
                    {"b": band_key, "g": gt["grade"], "r": gt["resolution"], "p": pf,
                     "n": note, "s": ST_ACTIVE, "hn": note})
                game_n += 1

    total = (n_active + n_delib + n_unknown) * 2 + game_n
    print(f"[0110] bands {len(BANDS)} (game 7 / nongame 8)"
          f" | nongame coords active={n_active} deliberate={n_delib}"
          f" unknown={n_unknown} -> cells {(n_active + n_delib + n_unknown) * 2}"
          f" | game cells {game_n} | TOTAL {total} (was 134)")
    print("[0110] NOTE: old GB_IGPU (650k-900k, iGPU casual game) has no successor -- "
          "owner fixed G0 floor at 900k. The 645,000 KRW cell is gone by decision, "
          "not by accident.")


def downgrade() -> None:
    conn = op.get_bind()
    op.drop_table("usage_label_map")
    conn.execute(sa.text("DELETE FROM usage_floors WHERE usage_key='ai_office'"))
    op.add_column("grid_cells", sa.Column(
        "intended_empty", sa.Boolean(), nullable=False, server_default=sa.false()))
    conn.execute(sa.text(
        "UPDATE grid_cells SET intended_empty = (handling_state <> :ac)"),
        {"ac": ST_ACTIVE})
    op.drop_constraint("ck_grid_cells_handling_state", "grid_cells", type_="check")
    op.drop_column("grid_cells", "handling_note")
    op.drop_column("grid_cells", "handling_state")
    op.alter_column("grid_cells", "quote_low", new_column_name="budget_min")
    op.alter_column("grid_cells", "quote_high", new_column_name="budget_max")
    # ⚠ 구간·칸·견적 원장은 되돌리지 않는다 — 0110 이 지운 옛 13구간과 134칸을
    #   복원하려면 0105 의 시드를 다시 돌려야 한다. downgrade 후
    #   `alembic downgrade 0104 && alembic upgrade 0109` 로 재시드하라.
