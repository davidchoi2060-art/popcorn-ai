# -*- coding: utf-8 -*-
"""격자를 «예산대» 축으로 재설계 — grid_cells·grid_quotes v3 (A-135 후속, 2026-09-20).

■ 왜 또 갈아엎나 — 0092 스펙축 격자의 실측된 결함 둘(조사자 보고서
  `D:/Hermes-Workspace/game_budget_measure.md`, 읽기 전용 실호출 ROLLBACK)

  (A) **등급이 엔진에 도달하지 않는다.** `tools/grid_generate.py cell_spec_floor()`
      가 `game_grade` 를 tier 조회 키로만 쓰고 반환 dict 에서 버린다. DB 실값에서
      `E/1080p` 와 `L/1080p` 가 둘 다 `gpu_tier_key='T1', cpu_tier_key_override=NULL`
      로 **같은 행**이라, 두 칸이 엔진에 보내는 body 가 바이트 단위로 같다
      (`550/6/16/1000`). 게임 18칸이 실제로는 **5가지 하한**밖에 없고 6칸
      (E/1080p·E/1440p·L 3칸·A/1080p)은 완전히 동일한 구성이다.

  (B) **하한이 가격을 정하지 못한다.** `api/recommend.py _order_of()` 는 숫자
      예산이 없으면 `"median"`(후보 풀 중앙값)을 쓴다. 실측: GPU 하한을 **완전히
      제거**해도 추천 총액 2,229,400 — T1(550W) 의 2,199,300 과 1.4% 차이이고
      오히려 더 비싸다. T1 은 GPU 175장 중 7장만 거른다(중앙값 852,000→883,500).
      즉 219만원은 «요구사양의 결과»가 아니라 «부품 풀 모양의 결과»다.
      같은 T1 하한에 **숫자 예산만 더하면** 추천이 1,000,000/1,199,900/1,499,900
      으로 실제로 만들어진다 — 엔진은 낮은 구간을 만들 수 있고, 배치가 묻지
      않았을 뿐이다.

■ 왜 «기존 표로는 부족»한가 — 새 컬럼·새 표가 정규 경로인 이유(P-08)
  0092 는 `budget_min`/`budget_max` 를 **입력에서 관측값으로** 바꿨다(그 표
  주석이 정본: "배치가 실제로 만든 견적 총액의 관측값(입력 아님)"). 예산대를
  표현하려고 그 두 컬럼을 다시 «입력»으로 쓰면 **한 컬럼이 입력과 출력 두 뜻을
  동시에** 갖게 된다 — 0092 가 없애려고 만든 바로 그 혼동이 되살아난다.
  그래서 예산대는 **새 축 컬럼** `grid_cells.budget_band_key`(입력)로 두고,
  `budget_min`/`budget_max` 는 관측값 자리에 그대로 둔다(다만 이제 min=가성비·
  max=고성능 **실제 범위**다 — 0092 시절 min=max=추천 단일점이 아니다).
  예산대의 «정의»(구간·표본 수·근거·엔진에 보낼 라벨)는 칸마다 복사하면 원천이
  126벌로 갈라지므로 별도 표 `grid_budget_bands` 하나에 둔다(§단일 원천).

■ 축이 바뀐다 — 비게임 칸에서 tier_key 가 빠진다
  0092 비게임 칸 = (tier_key, usage, platform). 이 축이 «사무·인강 × T5 =
  1,344만원» 같은 헛칸을 만들었다(pc_tier_ladder.json dissent 가 그 칸이 왜
  헛칸인지 증명한다: 사무는 L0 40~70만에서 이미 100% 충족되고 L6 는 사무를
  «포함»할 뿐 사무 때문에 사는 물건이 아니다).
  새 비게임 칸 = (usage, budget_band_key, platform). 스펙 하한은
  `usage_floors`(용도 라벨)가 이미 단일 원천으로 들고 있으므로 spec_tiers 의
  T0~T5 를 비게임 칸에 겹쳐 걸지 않는다 — 그게 헛칸의 직접 원인이었다.
  게임 칸 = (game_grade, game_resolution, budget_band_key, platform) — 스펙
  하한은 여전히 `game_grade_resolution_tiers` 조인으로 구한다(0092 그대로).

■ 예산대 구간은 어디서 왔나 — 전부 실측 인용, 지어낸 경계 없음
  · 게임 5구간: 조사자 실측 §③ 시장 실판매 234벌 분포 + 사장님 확정 네이밍 중
    **검증된 둘**(FHD 고주사율 100~150만 n=32 · QHD 게이밍 160~250만 n=49)을
    그대로 쓴다. 4K 는 조사자가 "T3까지만 260~400만이고 T4·T5는 440만+"이라고
    했으므로 **실측에 맞춰 두 구간으로 가르고** 네이밍을 거기 맞췄다(반대로 하지
    않았다). 내장그래픽 구간은 §③ "70~100만 8벌 중 5벌이 내장그래픽" +
    office_pc_market.json 의 신품 내장그래픽 풀(70~80만 n=22 · 80~100만 n=78).
  · 비게임 7구간: `pc_tier_ladder.json` 의 L0~L6 가격 경계와 builtpc_count 를
    **그대로** 옮겼다(실판매 234벌). 새 경계를 만들지 않았다.

■ 어느 칸에 어느 예산대를 두는가 — 칸마다 근거를 `band_note` 에 적는다
  비게임: 그 용도의 실판매 표본·`usage_tier_rules.budget_min` 계단이 실제로
  존재하는 구간만. 사무·주식은 상한 200만(사장님 확정 · office_pc_market
  source_1 "200만~" n=0)을 넘지 않는다.
  게임: (등급×해상도)의 tier 로 실측된 **가성비 최저가**(조사자 §②)를 담을 수
  있는 첫 구간부터 한 칸 위까지 둘. 내장그래픽 구간은 **L/1080p 에만** 둔다 —
  근거와 유보는 아래 IGPU_NOTE 문자열에 그대로 적혀 있다.

■ 옛 격자는 지우지 않는다 — `_legacy_v2` 로 보존(0092 가 `_legacy_v1` 로 한 그대로)
  `grid_quotes` 는 원장이다(0072 주석). 축이 바뀌어 공존할 수 없으므로 이름만
  바꿔 남긴다. downgrade 는 새 표를 버리고 옛 이름을 복원한다.

Revision ID: 0105
Revises: 0104
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0105"
down_revision = "0104"
branch_labels = None
depends_on = None


# ── 예산대 정의 ────────────────────────────────────────────────────────────
# budget_label 은 **엔진이 실제로 읽는 형식**이어야 한다 — `api/candidates.py`
# `_budget_cap()` 의 정규식 `(-)?\s*(\d{1,3}(?:,\d{3})+|\d+)\s*만` 이 상한을 뽑고,
# "이상" 이 들어 있으면 상한 없음(None)을 준다. 여기 값은 그 형식에 맞춰 뒀다 —
# 형식을 벗어나면 엔진이 **조용히 무시**하고 median 동작으로 되돌아간다.
# (band_key, axis, label, min, max, budget_label, gpu_required, engine_usage, n, source, sort)
BANDS = [
    # ── 게임 5구간 ─────────────────────────────────────────────────────
    ("GB_IGPU", "game", "내장그래픽 캐주얼", 650000, 900000, "90만원", False,
     "내장그래픽 캐주얼", 5,
     "game_budget_measure.md §③ 실판매 70~100만 8벌 중 5벌이 내장그래픽(외장GPU는"
     " RX 6600 1벌=967,400원뿐) + office_pc_market.json source_3 신품 내장그래픽"
     " 풀 70~80만 n=22 · 80~100만 n=78. 우리 풀 최저 외장 GPU 가 297,700원(RTX 3050"
     " 6GB)이라 65~90만에 외장 GPU 게임 PC 는 성립하지 않는다 — 그래서 이 구간은"
     " 내장그래픽 전용이다(gpu_required=false)", 10),
    ("GB_FHD", "game", "FHD 고주사율", 1000000, 1500000, "150만원", True, None, 32,
     "사장님 확정 네이밍 중 실측으로 검증된 구간 — game_budget_measure.md §③"
     " 실판매 100-130만 18벌 + 130-160만 14벌 = 32벌(주력 GPU RTX 3050 20 · GTX 1650 2)."
     " 실측 §④: T1 하한 + '150만원' 예산으로 추천 1,499,900 이 실제로 생성된다", 20),
    ("GB_QHD", "game", "QHD 게이밍", 1600000, 2500000, "250만원", True, None, 49,
     "사장님 확정 네이밍 중 실측으로 검증된 구간 — 실판매 160-190만 22벌 +"
     " 190-250만 27벌 = 49벌(RTX 5060 10 · 5060Ti 10 · 5070 4). T2 가성비 실측"
     " 1,836,900 · S등급 1,918,600 이 이 구간 안에 있다", 30),
    ("GB_4K", "game", "4K 입문·고성능", 2600000, 4000000, "400만원", True, None, 62,
     "사장님 네이밍 '4K·최고사양 260~400만'의 **맞는 절반** — 실판매 250-300만 26벌"
     " + 300-400만 36벌 = 62벌. T3 가성비 실측 2,691,400 이 여기 들어간다."
     " 조사자 판정: T3 까지만 이 구간이 맞는다", 40),
    ("GB_4KMAX", "game", "4K 최고사양", 4400000, 7000000, "700만원", True, None, 30,
     "조사자가 '네이밍에 400만 위 칸이 하나 더 있어야 한다'고 한 구간 —"
     " T4 가성비 실측 4,394,000 이 이미 400만을 넘는다. 상한 700만은 실판매"
     " 400만+ 72벌(중앙값 11,600,800)을 그대로 쓰지 않고 pc_tier_ladder L5"
     "(4,000,000~7,000,000 · 실판매 30벌 · 중앙값 4,889,800)를 쓴다 — 조사자가"
     " '400만+ 72벌은 워크스테이션·서버가 섞인 이질 집단'이라 대조 불가라고"
     " 적었기 때문이다."
     " ⚠ 상한을 닫은 이유(실측): '440만원 이상'으로 열어 두면 _budget_cap 이"
     " None 을 주고 _order_of 가 median 으로 되돌아가, A/4K 칸이 추천 4,087,100"
     "(= 자기 구간 하한 440만보다 낮은 값)을 내민다. 구간 이름이 거짓이 된다", 50),
    ("GB_ULTRA", "game", "울트라 4K", 7000000, None, "700만원 이상", True, None, 42,
     "T5(C/4K) 전용 — 가성비 실측 12,676,100. 상한을 닫지 않았고 «닫을 근거가"
     " 없어서» 닫지 않았다: 조사자가 'C/4K(T5)는 시장 대조가 불가능하다 — 우리"
     " 풀에 1000W GPU 가 2장·128GB RAM 이 8종뿐'이라고 적었고, 실판매 400만+"
     " 72벌은 워크스테이션·서버 혼재라 게임 칸 상한으로 쓸 수 없다. 숫자를"
     " 지어내지 않고 비워 둔다 — 상한이 없어도 이 칸은 하한(T5 스펙)만으로"
     " 12,676,100 이상이 나와 구간 이름이 거짓이 되지 않는다(실측 확인)."
     " 참고 표본 n=42 는 pc_tier_ladder L6(700만~, 중앙값 20,069,350)", 55),

    # ── 비게임 7구간 — pc_tier_ladder.json L0~L6 경계·표본을 그대로 ────
    ("NB_L0", "nongame", "사무·웹", 400000, 700000, "70만원", True, None, 11,
     "pc_tier_ladder.json L0(실판매 11벌·중앙값 609,400·전부 내장그래픽)", 100),
    ("NB_L1", "nongame", "가정·인강", 700000, 1300000, "130만원", True, None, 26,
     "pc_tier_ladder.json L1(실판매 26벌·중앙값 1,032,950)", 110),
    ("NB_L2", "nongame", "실무 주력", 1300000, 1900000, "190만원", True, None, 36,
     "pc_tier_ladder.json L2(실판매 36벌·중앙값 1,664,300)", 120),
    ("NB_L3", "nongame", "고성능 작업", 1900000, 2900000, "290만원", True, None, 45,
     "pc_tier_ladder.json L3(실판매 45벌·중앙값 2,405,500)", 130),
    ("NB_L4", "nongame", "전문 작업", 2900000, 4000000, "400만원", True, None, 44,
     "pc_tier_ladder.json L4(실판매 44벌·중앙값 3,321,200)", 140),
    ("NB_L5", "nongame", "하이엔드·크리에이터", 4000000, 7000000, "700만원", True, None, 30,
     "pc_tier_ladder.json L5(실판매 30벌·중앙값 4,889,800)", 150),
    ("NB_L6", "nongame", "워크스테이션·AI", 7000000, None, "2,006만원", True, None, 42,
     "pc_tier_ladder.json L6(실판매 42벌·중앙값 20,069,350). budget_label 은 그"
     " **실판매 중앙값**이다 — '700만원 이상'으로 열어 두면 _budget_cap 이 None 을"
     " 주고 _order_of 가 median 으로 되돌아가, 3D 렌더링 칸이 추천 3,069,000"
     "(= 자기 구간 하한 700만보다 낮은 값)을 내민다(실측). 상한을 중앙값으로 닫으면"
     " 추천 14,466,300 이 나와 구간 안에 들어온다", 160),
]

PLATFORMS = ["인텔", "AMD"]

# ── 비게임: 용도 → 예산대 + 그 근거 ────────────────────────────────────
# ⚠ 사무·주식 상한 200만(사장님 확정)을 넘는 구간은 두지 않는다 — office_pc_market
#   .json source_1 의 '200만~' 밴드가 n=0 이다(실판매 0벌). 0092 격자가 사무·인강
#   칸에 T5(1,344만원)를 만든 것이 이 규칙 위반의 실례다.
# ⚠ 표본이 없는 용도(개발·음악·주식)는 «표본 없음»을 그대로 적는다 — 근거는
#   usage_tier_rules.budget_min 계단(그 표가 "이 예산부터 시장이 이 급을 산다"를
#   담고 있다)뿐이고, 그 사실을 감추지 않는다.
NONGAME_BANDS = {
    "단순 사무용": [
        ("NB_L0", "pc_tier_ladder L0 가 '한글·엑셀·PPT·웹서핑·인터넷강의'를 전부"
                  " newly_enabled 로 적는다. office_pc_market 컴퓨존 사무용 17벌 최저"
                  " 506,000원"),
        ("NB_L1", "office_pc_market 다나와 사무용 진열 30벌 중앙값 1,102,500원 ·"
                  " 신품 내장그래픽 풀 80~100만 n=78 · 100~120만 n=54"),
        ("NB_L2", "office_pc_market 다나와 사무용 진열 130~160만 n=8 · 160~200만 n=2"
                  "(진열 최고가 1,920,000원). 사장님 확정 상한 200만 안 — 이 위는"
                  " 실판매 0벌('200만~' 밴드 n=0)이라 칸을 만들지 않는다."
                  " ⚠ 실측 후 확인된 한계: 이 칸의 **고성능(highend) 구성은 236만원**이다."
                  " `api/recommend.py HIGHEND_CAP_X = 1.5` 가 고성능 티어의 상한을"
                  " 예산의 1.5배로 잡기 때문에, 190만 구간에 칸을 두는 한 고성능은"
                  " 구조적으로 200만을 넘는다(190만 x 1.5 = 285만 상한). 가성비·추천은"
                  " 200만 안이다(41만 / 190만). 이 자리는 예산대로 풀리지 않는다 —"
                  " 엔진 상수를 용도별로 가르는 판단이 필요하고 그건 전체 견적에"
                  " 영향을 주므로 여기서 고치지 않았다"),
    ],
    "복합 사무용": [
        ("NB_L1", "usage_floors office_complex 하한 RAM 16GB·SSD 500GB — 신품 내장그래픽"
                  " 풀 80~130만 구간이 16GB 를 표준으로 단다(office_pc_market)"),
        ("NB_L2", "office_pc_market 다나와 사무용 130~200만 n=10(U5-225·R7-8700G 급)."
                  " 사장님 확정 상한 200만 안"),
    ],
    "주식·트레이딩": [
        ("NB_L1", "⚠ 실판매 표본 0 — builtpc 234벌에 '주식/트레이딩/증권' 상품명이"
                  " 없다. usage_floors trading 하한(RAM 16GB·SSD 500GB)을 담는 최저"
                  " 구간으로 둔다"),
        ("NB_L2", "⚠ 실판매 표본 0. usage_tier_rules trading budget_min=1,500,000 에서"
                  " RAM 32GB 겨냥이 켜진다('창을 수십 개 띄우는 전업 트레이더 기준')."
                  " 사장님 확정 상한 200만 안"),
    ],
    "개발": [
        ("NB_L2", "⚠ 실판매 표본 0. usage_tier_rules dev budget_min=1,500,000 에서"
                  " RAM 32GB 겨냥('32GB 미만 사지 말라' 웹 조사)"),
        ("NB_L3", "⚠ 실판매 표본 0. usage_tier_rules dev 는 8,000,000 위에서 RAM 상한"
                  " 64GB 를 건다 — 그 아래 구간을 한 칸 더 둔다"),
    ],
    "음악 작업": [
        ("NB_L2", "⚠ 실판매 표본 0. usage_tier_rules music budget_min=1,500,000 에서"
                  " RAM 32GB 겨냥(큐베이스·에이블톤 커뮤니티)"),
        ("NB_L3", "⚠ 실판매 표본 0. usage_floors music 하한(RAM 16GB·SSD 500GB) 위로"
                  " 한 칸 — 대형 샘플 라이브러리 구간"),
    ],
    "디자인": [
        ("NB_L2", "usage_tier_rules design budget_min=1,500,000 에서 VRAM 8GB 겨냥"),
        ("NB_L3", "pc_tier_ladder L3 이 'VRAM 12~16GB — 고해상도 텍스처·생성형 AI 입문'"
                  "을 newly_enabled 로 적는다"),
        ("NB_L4", "usage_tier_rules design budget_min=3,000,000 에서 RAM 32GB·CPU 12코어"
                  " 겨냥('디자인 7 100%(n=14)')"),
    ],
    "영상편집": [
        ("NB_L2", "usage_tier_rules video budget_min=1,500,000 VRAM 8GB 겨냥 +"
                  " pc_tier_ladder L2 'GPU 가속 영상편집 실사용 구간 진입'"),
        ("NB_L3", "usage_tier_rules video budget_min=2,200,000 RAM 32GB('영상편집 5+"
                  " 63%(n=33)') · 3,000,000 VRAM 12GB·CPU 12코어"),
        ("NB_L4", "usage_tier_rules video budget_min=4,000,000 VRAM 16GB('5070Ti"
                  " 60%(n=41)'). builtpc '방송·편집' 2벌 중 3,401,600 이 여기"),
        ("NB_L5", "usage_floors video 하한 SSD 2TB·RAM 32GB + pc_tier_ladder L5"
                  " '고해상도 영상편집 + 게임방송 병행'(실판매 30벌)"),
    ],
    "방송 송출": [
        ("NB_L2", "usage_floors stream 하한(RAM 16GB·SSD 500GB, 스트림랩스 공식 권장)."
                  " builtpc '방송·편집' 최저 1,805,500 이 이 구간"),
        ("NB_L3", "builtpc '방송·편집' 2벌 중앙 2,603,550"),
        ("NB_L4", "pc_tier_ladder L4 가 '게임방송 원컴(방송+게임 동시)'을 newly_enabled"
                  " 로 적고 '우리 실판매 방송·편집 상품이 이 구간'이라고 명시한다"
                  "(3,401,600)"),
    ],
    "캐드·설계": [
        ("NB_L3", "usage_floors cad 하한 VRAM 8GB·RAM 16GB·SSD 500GB 를 담는 최저"
                  " 구간. usage_tier_rules cad budget_min=1,500,000 RAM 32GB 겨냥"),
        ("NB_L4", "pc_tier_ladder L4(RTX 5070 Ti·RAM 32GB) — 캐드 하한 위 한 칸"),
        ("NB_L5", "pc_tier_ladder L5 '전문 CAD·3D — 우리 실판매 캐드 상품 4벌이 이"
                  " 구간, 4,572,700원~'. builtpc '캐드' 8벌 최저가가 4,572,700 이다"),
    ],
    "3D 렌더링": [
        ("NB_L4", "usage_floors render_3d 하한 VRAM 12GB·RAM 32GB 를 담는 최저 구간 +"
                  " pc_tier_ladder L4"),
        ("NB_L5", "pc_tier_ladder L5(RTX 5080·RAM 64GB) — '전문 CAD·3D' 구간"),
        ("NB_L6", "builtpc '렌더' 2벌이 15,412,200 / 15,575,800 원 — pc_tier_ladder L6"
                  " '8K 영상·VFX 렌더링'"),
    ],
    "AI 작업": [
        ("NB_L4", "usage_tier_rules ai budget_min=3,000,000 VRAM 12GB 겨냥"
                  "('RTX 5070 12GB — AI 88%(n=25)')"),
        ("NB_L5", "usage_tier_rules ai budget_min=4,000,000 RAM 64GB · 5,500,000"
                  " VRAM 16GB·CPU 20코어. builtpc 'AI·딥러닝' 26벌 최저 5,987,800"),
        ("NB_L6", "usage_tier_rules ai budget_min=8,000,000 VRAM 32GB·CPU 24코어."
                  " pc_tier_ladder L6 는 실판매 'AI·딥러닝' 26벌 중 24벌이 이 구간"
                  " 이라고 적는다"),
    ],
}

# ── 게임: (등급, 해상도) → 예산대 ─────────────────────────────────────
# 규칙(지어내지 않는다): 조사자 §② 가 실측한 그 칸의 **가성비 최저가**(= 그 스펙
# 하한을 만족하는 진짜 최소 조립비)를 담을 수 있는 첫 구간부터 한 칸 위까지.
#   T1 921,100 / T2 1,836,900 / T2+cpuT4 1,918,600 / T3 2,691,400
#   T4 4,394,000 / T5 12,676,100
# 구간 상한: GB_IGPU 90만 · GB_FHD 150만 · GB_QHD 250만 · GB_4K 400만 · GB_4KMAX 없음
TIER_MIN_MEASURED = {
    "T1": 921100, "T2": 1836900, "T2+T4": 1918600,
    "T3": 2691400, "T4": 4394000, "T5": 12676100,
}
GAME_BAND_LADDER = ["GB_FHD", "GB_QHD", "GB_4K", "GB_4KMAX", "GB_ULTRA"]  # 외장 GPU 구간만
GAME_BAND_MAX = {"GB_FHD": 1500000, "GB_QHD": 2500000,
                 "GB_4K": 4000000, "GB_4KMAX": 7000000, "GB_ULTRA": None}

# 내장그래픽 칸은 **L/1080p 하나에만** 둔다. 근거와 유보를 그대로 적는다.
IGPU_CELL = ("L", "1080p")
IGPU_NOTE = (
    "이 칸은 «돌아간다»와 «고주사율로 쾌적하게 돌아간다»를 구분한다."
    " ● 돌아간다(DB 근거): games.min_gpu 가 내장그래픽을 **공식 최소사양으로 명시**한"
    " 게임 — 로블록스(DirectX 10·'3년 이내 노트북 내장그래픽'), 던전앤파이터"
    "(Intel UHD 610 내장 / Radeon Vega 3 내장 이상), 마인크래프트(Intel i5-6400+"
    " 내장그래픽). E등급의 리그 오브 레전드(Intel HD 4600)·발로란트(Intel HD 4000)도"
    " 공식 최소사양은 내장그래픽이다."
    " ● 쾌적하게 돌아간다고는 말할 수 없다(유보): L등급 5종의 typical_monitor_hz 는"
    " **전부 144**, comfortable_fps_target 은 120~144 다. 내장그래픽이 그 144 를"
    " 낸다는 근거가 우리 DB 에 없다 — game_measured_fps 150행은 전부 A/B/C 등급이고"
    " E·L·S 는 **0행**이다. pc_tier_ladder L0 도 '롤·발로란트를 FHD 고옵·고주사율"
    "(144fps+)로 돌리는 것'을 not_capable 로 적는다."
    " ● E등급에는 이 칸을 두지 않았다: E 6종의 typical_monitor_hz 평균 212(최대 240)로"
    " 고주사율이 등급 정의에 들어 있고, 배틀그라운드는 pc_tier_ladder L0 not_capable"
    " 에 '공식 권장 GTX 1060 3GB — 내장그래픽으로 부족'이라고 명시돼 있다."
    " ● 마인크래프트는 최소사양만 내장그래픽이고 rec_gpu 는 RTX 2060 이다 —"
    " 판정 근거가 약하다."
    " ● 메이플스토리는 min_gpu 가 NULL 이라 판정하지 않았다(지어내지 않는다)."
)


def _game_bands_for(gpu_tier, cpu_override):
    """(등급,해상도)의 tier → 예산대 목록. 위 규칙 그대로, 예외 없음.

    ⚠ «한 칸 위»는 **상한이 닫힌 구간일 때만** 붙인다(실측으로 얻은 제약).
    상한이 없는 구간(GB_ULTRA)은 budget_label 이 '이상'이라 `_budget_cap` 이
    None 을 주고, 그러면 `_order_of` 가 median(풀 중앙값)으로 되돌아간다 —
    실측: T4 칸에 GB_ULTRA 를 붙이면 추천 5,102,200 이 나와 **자기 구간 하한
    700만보다 낮은 값**을 «울트라 4K» 이름으로 내밀게 된다. 구간 이름이 거짓이
    되므로 붙이지 않는다. GB_ULTRA 는 자기 하한(T5 12,676,100)으로 그 구간에
    자연히 들어오는 칸에만 **첫 구간으로** 붙는다.
    """
    key = f"{gpu_tier}+{cpu_override}" if cpu_override else gpu_tier
    floor_cost = TIER_MIN_MEASURED[key]
    idx = None
    for i, b in enumerate(GAME_BAND_LADDER):
        mx = GAME_BAND_MAX[b]
        if mx is None or mx >= floor_cost:
            idx = i
            break
    if idx is None:                       # 사다리 밖 — 지어내지 않는다
        return []
    out = [GAME_BAND_LADDER[idx]]
    if idx + 1 < len(GAME_BAND_LADDER):
        nxt = GAME_BAND_LADDER[idx + 1]
        if GAME_BAND_MAX[nxt] is not None:      # 위 ⚠ 참조
            out.append(nxt)
    return out


def upgrade() -> None:
    conn = op.get_bind()

    # ── 옛 격자 보존 — 이름만 바꾼다(0092 가 v1 에 한 그대로) ───────────
    op.execute("ALTER INDEX ix_grid_quotes_cell_id RENAME TO ix_grid_quotes_cell_id_legacy_v2")
    op.execute("ALTER INDEX uq_grid_quotes_current_per_cell_variant"
               " RENAME TO uq_grid_quotes_current_per_cell_variant_legacy_v2")
    op.execute("ALTER INDEX uq_grid_cells_nongame_coord RENAME TO uq_grid_cells_nongame_coord_legacy_v2")
    op.execute("ALTER INDEX uq_grid_cells_game_coord RENAME TO uq_grid_cells_game_coord_legacy_v2")
    op.rename_table("grid_cells", "grid_cells_legacy_v2")
    op.rename_table("grid_quotes", "grid_quotes_legacy_v2")
    op.execute(
        "COMMENT ON TABLE grid_cells_legacy_v2 IS "
        "'0092 스펙축 격자(비게임 tier_key x usage 108칸) — 0105 예산대축 전환으로 "
        "보존만. 예산이 입력이 아니어서 E/L 등급이 같은 219만원으로 발행되던 판'"
    )
    op.execute(
        "COMMENT ON TABLE grid_quotes_legacy_v2 IS "
        "'0092~0104 스펙축 격자의 견적 원장 — 보존만, 새 쓰기 없음'"
    )

    # ── 예산대 정의표 ──────────────────────────────────────────────────
    op.create_table(
        "grid_budget_bands",
        sa.Column("band_key", sa.String(12), primary_key=True),
        sa.Column("axis", sa.String(8), nullable=False),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("budget_min_won", sa.Integer, nullable=False),
        sa.Column("budget_max_won", sa.Integer, nullable=True),
        # 엔진에 그대로 실어 보내는 「예산」 라벨 — candidates._budget_cap 형식
        sa.Column("budget_label", sa.String(20), nullable=False),
        # false = 이 구간은 외장 GPU 가 성립하지 않는다(내장그래픽 전용)
        sa.Column("gpu_required", sa.Boolean, nullable=False, server_default=sa.true()),
        # 엔진에 보낼 「용도」 라벨 override — NULL 이면 칸의 usage 를 그대로 쓴다
        sa.Column("engine_usage_label", sa.String(30), nullable=True),
        sa.Column("sample_n", sa.Integer, nullable=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.CheckConstraint("axis IN ('game','nongame')", name="ck_grid_bands_axis"),
        sa.CheckConstraint("budget_max_won IS NULL OR budget_max_won > budget_min_won",
                           name="ck_grid_bands_range"),
    )
    op.execute(
        "COMMENT ON TABLE grid_budget_bands IS "
        "'격자의 예산대 축 정의(0105) — 구간 경계·표본 수·근거·엔진에 보낼 「예산」 "
        "라벨의 단일 원천. 경계는 전부 실측 인용(game: game_budget_measure.md 시장 "
        "234벌 분포 + 사장님 확정 네이밍 중 검증된 둘 / nongame: pc_tier_ladder.json "
        "L0~L6). budget_label 은 api/candidates.py _budget_cap 이 읽는 형식이어야 "
        "한다 — 벗어나면 엔진이 조용히 무시하고 median 동작으로 되돌아간다'"
    )
    op.execute(
        "COMMENT ON COLUMN grid_budget_bands.gpu_required IS "
        "'false = 이 구간에는 외장 GPU 가 성립하지 않는다(우리 풀 최저 외장 GPU 가 "
        "297,700원). 배치가 gpu_watt_min 을 NULL 로 넘겨 엔진의 iGPU 전용 탐색 "
        "패스(api/recommend.py, 사무용에 쓰는 그것)를 타게 한다'"
    )
    for (bk, axis, label, bmin, bmax, blabel, gpu_req, eng_usage, n, src, sort) in BANDS:
        conn.execute(sa.text(
            "INSERT INTO grid_budget_bands (band_key, axis, label, budget_min_won,"
            " budget_max_won, budget_label, gpu_required, engine_usage_label,"
            " sample_n, source, sort_order)"
            " VALUES (:k,:a,:l,:mn,:mx,:bl,:gr,:eu,:n,:s,:o)"),
            {"k": bk, "a": axis, "l": label, "mn": bmin, "mx": bmax, "bl": blabel,
             "gr": gpu_req, "eu": eng_usage, "n": n, "s": src, "o": sort})

    # ── 새 grid_cells — 예산대가 축이다 ─────────────────────────────────
    op.create_table(
        "grid_cells",
        sa.Column("cell_id", sa.Integer, primary_key=True),
        sa.Column("usage", sa.String(20), nullable=False),
        sa.Column("budget_band_key", sa.String(12),
                  sa.ForeignKey("grid_budget_bands.band_key"), nullable=False),
        sa.Column("game_grade", sa.String(1), sa.ForeignKey("game_load_grades.grade"),
                  nullable=True),
        sa.Column("game_resolution", sa.String(6), nullable=True),
        sa.Column("platform", sa.String(4), nullable=False),
        # 관측값 — 이제 단일점이 아니라 **실제 범위**다(min=가성비, max=고성능)
        sa.Column("budget_min", sa.Integer, nullable=True),
        sa.Column("budget_max", sa.Integer, nullable=True),
        sa.Column("band_note", sa.Text, nullable=True),
        sa.Column("intended_empty", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint(
            "(usage = '게임' AND game_grade IS NOT NULL AND game_resolution IS NOT NULL)"
            " OR (usage <> '게임' AND game_grade IS NULL AND game_resolution IS NULL)",
            name="ck_grid_cells_axis",
        ),
        sa.CheckConstraint(
            "game_resolution IS NULL OR game_resolution IN ('1080p','1440p','4K')",
            name="ck_grid_cells_resolution",
        ),
    )
    op.create_index(
        "uq_grid_cells_nongame_coord", "grid_cells",
        ["usage", "budget_band_key", "platform"], unique=True,
        postgresql_where=sa.text("usage <> '게임'"),
    )
    op.create_index(
        "uq_grid_cells_game_coord", "grid_cells",
        ["game_grade", "game_resolution", "budget_band_key", "platform"], unique=True,
        postgresql_where=sa.text("usage = '게임'"),
    )
    op.execute(
        "COMMENT ON TABLE grid_cells IS "
        "'예산대 축 격자 칸(0105). 비게임 = (usage, budget_band_key, platform) — "
        "tier_key 축을 뺐다(그 축이 «사무·인강 x T5 = 1,344만원» 헛칸을 만들었다). "
        "게임 = (game_grade, game_resolution, budget_band_key, platform). "
        "budget_min/max 는 여전히 관측값이지만 이제 min=가성비·max=고성능 실제 범위다'"
    )
    op.execute(
        "COMMENT ON COLUMN grid_cells.budget_band_key IS "
        "'격자의 예산대 축(입력). budget_min/max(관측값)와 역할이 다르다 — 한 컬럼이 "
        "입력과 출력 두 뜻을 갖지 않게 새 컬럼으로 둔다(0092 가 없앤 혼동의 재발 방지)'"
    )
    op.execute(
        "COMMENT ON COLUMN grid_cells.band_note IS "
        "'이 칸에 이 예산대를 둔 근거(표본 수 병기). 내장그래픽 칸은 «돌아간다»와 "
        "«고주사율로 쾌적하게 돌아간다»의 차이를 여기서 먼저 말한다'"
    )

    # ── 새 grid_quotes — 0092 와 같은 모양(tier_variant 3종) ────────────
    op.create_table(
        "grid_quotes",
        sa.Column("quote_id", sa.Integer, primary_key=True),
        sa.Column("cell_id", sa.Integer, sa.ForeignKey("grid_cells.cell_id"), nullable=False),
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
        sa.CheckConstraint("tier_variant IN ('가성비','추천','고성능')",
                           name="ck_grid_quotes_variant"),
    )
    op.create_index("ix_grid_quotes_cell_id", "grid_quotes", ["cell_id"])
    op.create_index(
        "uq_grid_quotes_current_per_cell_variant", "grid_quotes",
        ["cell_id", "tier_variant"], unique=True,
        postgresql_where=sa.text("is_current"),
    )

    # ── 시드 ───────────────────────────────────────────────────────────
    nongame_n = 0
    for usage, bands in NONGAME_BANDS.items():
        for band_key, note in bands:
            for pf in PLATFORMS:
                conn.execute(sa.text(
                    "INSERT INTO grid_cells (usage, budget_band_key, platform,"
                    " band_note, intended_empty) VALUES (:u,:b,:p,:n,false)"),
                    {"u": usage, "b": band_key, "p": pf, "n": note})
                nongame_n += 1

    gtiers = conn.execute(sa.text(
        "SELECT grade, resolution, gpu_tier_key, cpu_tier_key_override"
        " FROM game_grade_resolution_tiers ORDER BY grade, resolution")).mappings().all()
    game_n = 0
    for gt in gtiers:
        grade, res = gt["grade"], gt["resolution"]
        key = (f"{gt['gpu_tier_key']}+{gt['cpu_tier_key_override']}"
               if gt["cpu_tier_key_override"] else gt["gpu_tier_key"])
        bands = _game_bands_for(gt["gpu_tier_key"], gt["cpu_tier_key_override"])
        note_base = (
            f"(등급 {grade} x {res}) = spec_tiers {key}. 조사자 실측 가성비 최저가"
            f" {TIER_MIN_MEASURED[key]:,}원을 담을 수 있는 첫 구간부터 한 칸 위까지"
            " (game_budget_measure.md §②)")
        for band_key in bands:
            for pf in PLATFORMS:
                conn.execute(sa.text(
                    "INSERT INTO grid_cells (usage, budget_band_key, game_grade,"
                    " game_resolution, platform, band_note, intended_empty)"
                    " VALUES ('게임',:b,:g,:r,:p,:n,false)"),
                    {"b": band_key, "g": grade, "r": res, "p": pf, "n": note_base})
                game_n += 1
        if (grade, res) == IGPU_CELL:
            for pf in PLATFORMS:
                conn.execute(sa.text(
                    "INSERT INTO grid_cells (usage, budget_band_key, game_grade,"
                    " game_resolution, platform, band_note, intended_empty)"
                    " VALUES ('게임','GB_IGPU',:g,:r,:p,:n,false)"),
                    {"g": grade, "r": res, "p": pf, "n": IGPU_NOTE})
                game_n += 1

    print(f"[0105] grid_budget_bands {len(BANDS)}행 · grid_cells 비게임 {nongame_n}"
          f" + 게임 {game_n} = {nongame_n + game_n}행 (전부 intended_empty=false —"
          " 불성립 판단은 tools/grid_generate.py 실행 결과로 한다)")


def downgrade() -> None:
    op.drop_index("uq_grid_quotes_current_per_cell_variant", table_name="grid_quotes")
    op.drop_index("ix_grid_quotes_cell_id", table_name="grid_quotes")
    op.drop_table("grid_quotes")
    op.drop_index("uq_grid_cells_game_coord", table_name="grid_cells")
    op.drop_index("uq_grid_cells_nongame_coord", table_name="grid_cells")
    op.drop_table("grid_cells")
    op.drop_table("grid_budget_bands")

    op.rename_table("grid_quotes_legacy_v2", "grid_quotes")
    op.rename_table("grid_cells_legacy_v2", "grid_cells")
    op.execute("ALTER INDEX uq_grid_cells_game_coord_legacy_v2 RENAME TO uq_grid_cells_game_coord")
    op.execute("ALTER INDEX uq_grid_cells_nongame_coord_legacy_v2 RENAME TO uq_grid_cells_nongame_coord")
    op.execute("ALTER INDEX uq_grid_quotes_current_per_cell_variant_legacy_v2"
               " RENAME TO uq_grid_quotes_current_per_cell_variant")
    op.execute("ALTER INDEX ix_grid_quotes_cell_id_legacy_v2 RENAME TO ix_grid_quotes_cell_id")
