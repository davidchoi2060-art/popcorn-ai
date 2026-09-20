# -*- coding: utf-8 -*-
"""3D 용도 2분할 — `video_3d` -> «캐드·설계»(cad) · «3D 렌더링»(render_3d).

설계 정본: docs/design/usage-rules-rebuild-2026-09-18.md §2-개정2
사장님 확정(2026-09-19): 3D 용도를 **프로그램 계열로** 둘로 가른다.
    캐드·설계   부제: 오토캐드 · 솔리드웍스 · 인벤터 · 스케치업
    3D 렌더링   부제: 블렌더 · 마야 · 3ds 맥스
이름 근거: 시장 조사 산출물 `usage_naming_3d.json` `recommendation`(후보 A5 채택).

■ 왜 나누는가 — `software` 실조회가 병목이 «정반대»라고 말한다
  (2026-09-19 실조회 · software 카테고리 '3D·설계' 7종 + software_community_spec)

      프로그램      bottleneck  min/rec RAM  min/rec VRAM  note 가 말하는 것
      오토캐드      cpu         8 / 32       2 / 8         "코어 수가 아니라 클럭을 지목"
      솔리드웍스     cpu         16 / 32      - / -         "형상 재생성이 순차 연산"
      인벤터        cpu         16 / 32      2 / 8         "부품 500개↑ 32GB, 초대형 64GB"
      스케치업       vram        - / 8        - / 8         "PBR 재질은 VRAM 32GB↑"
      블렌더        gpu         8 / 32       2 / 8         "Cycles 렌더링이 GPU 연산"
      마야          balanced    8 / 16       - / -         "뷰포트는 GPU, 렌더링(Arnold)은 CPU"
      3ds 맥스      cpu         4 / 8        - / -         "공식이 현저히 낮아 그대로 쓰면 안 된다"

  **앞 넷(캐드 계열)은 CPU/VRAM 병목이고 뒤 셋(렌더 계열)은 GPU/혼합이다.**
  그런데 `video_3d` 는 이 일곱을 한 키로 묶고 **GPU 850W · RAM 64GB · SSD 2TB** 를
  걸었다. 850W 는 `software` 어디에도 근거가 없는 값이고(0090 이 시장 표본 없이
  넣었다), 캐드 고객에게 이 하한을 걸면 **그가 쓰지 않는 GPU 때문에 CPU 예산이
  깎인다.** 오토캐드 note 원문이 정확히 그 반대를 말한다 —
  "GPU는 화면 표시용이라 권장(8GB)을 넘겨 투자할 실익이 작다".

■ ★ 판정 ⓐ/ⓑ/ⓒ — **ⓑ(video_3d 를 render_3d 로 개명 + cad 신설)**
  0102(office 분할)와 **같은 방식**이다. 이유도 같다:
  ⓐ video_3d 를 남기고 둘을 추가 — 버린다. 세 키가 되면 「3D」가 어디로 갈지 다시
     모호해진다. 사장님 구분의 요점은 «둘 중 하나로 갈라라»다.
  ⓒ video_3d 를 지우고 둘 다 신설 — 버린다. 회귀 [52]① 이
     「활성 usage_alloc.usage_key ⊆ usage_floors.usage_key」를 불변식으로 검사한다.
     video_3d 는 지금 usage_alloc 행이 **없어서** 당장은 안 깨지지만, floor_id
     67·68·69 의 이력이 끊기고 `grid_cells.usage='3D 그래픽'`(12행) 을 상속할
     주인이 사라진다.
  ⓑ **개명** — 고른 쪽.

  ★ 어느 쪽을 개명하는가 — **video_3d -> render_3d(3D 렌더링)**. 근거 둘:
    ① **값이 렌더링 쪽이다.** 기존 video_3d 는 GPU 850W · RAM 64GB · SSD 2TB 로
       «GPU 를 몰아 쓰는 무거운 쪽»을 겨눈 값이다. 그 성격을 물려받을 자리는
       블렌더(bottleneck=gpu · 커뮤니티 RAM 64 · VRAM 12)가 있는 렌더링이지
       CPU 병목 넷이 있는 캐드가 아니다.
    ② **라벨의 이력이 렌더링 쪽이다.** `grid_cells.usage` 12행 · `consult_sessions`
       60건 · `grid_quotes.payload` 72건이 문자열 「3D 그래픽」을 들고 있고
       `api/grid_public.py USAGE_TO_GRID` 가 그 격자를 쓴다. 조사 산출물도
       「3D 그래픽」을 **렌더링 쪽 이름의 기각 후보(A2)**로 다뤘다 — 즉 그 말이
       가리키던 사람은 렌더링 고객이다. 개명이면 격자 상속이 자연스럽다.
    ⚠ 그래서 render_3d 의 낱말에 **「3D 그래픽」을 그대로 남긴다**(아래 TERMS).
      옛 세션·격자 입력이 통째로 needs=['usages'] 로 떨어지지 않게 하는 자리다.

■ ★ CPU 클럭 하한을 걸 수 있는가 — **못 건다. 걸지 않았다.**
  캐드의 핵심 근거는 「코어 수가 아니라 클럭」인데(오토캐드·인벤터·솔리드웍스 3종
  note 가 공통으로 그렇게 적는다), **재고에 CPU 클럭 값이 없다.** 실조회:

      spec_field_defs.clock_mhz   part_types = ['RAM']        ← CPU 가 아니다
      product_specs               CPU 683행 중 clock_mhz **0행**(전부 NULL)
                                  clock_mhz 가 채워진 것은 RAM 1,697행뿐(1600~21000)

  `usage_floors.passes()` 는 «값을 모르면 불통과»가 원칙이라, 클럭 하한을 넣으면
  **CPU 683종이 전부 탈락해 견적이 0건**이 된다. 근거가 있는데 데이터가 없다 —
  **없는 규칙을 지어내지 않는다.** 대신 할 수 있는 것만 했다(아래 ★ GPU 상한).
  ⇒ 후속 과제: `product_specs.clock_mhz` 를 CPU 로 확장(spec_field_defs.part_types
    에 'CPU' 추가 + 수집). 그 전까지 캐드의 「고클럭」은 견적에 반영되지 않는다.

■ 하한 값 — 전부 `software` / `software_community_spec` 실조회다. 한 값도 짓지 않았다
  기준은 §4 확립분: **하한 = 카테고리 최저 커뮤니티값**, 겨냥 = 무거운 쪽.

  cad(캐드·설계)
    RAM 16  솔리드웍스 min_ram_gb=16 · 인벤터 min_ram_gb=16 (공식 최소 둘)
            + 솔리드웍스 커뮤니티 note "조립품 500MB 미만 16GB"
            + 인벤터 공식 "부품 500개 미만 16GB". **넷이 같은 선을 말한다.**
            (오토캐드 min 8 은 더 낮지만, 16 을 말하는 근거가 셋이라 16 을 하한으로
             둔다 — 커뮤니티 aggregate 는 넷 다 32 이고 그건 겨냥으로 보낸다)
    GPU VRAM 8  오토캐드 커뮤니티 vram_gb=8 · 인벤터 커뮤니티 vram_gb=8
            · 스케치업 공식 rec_vram_gb=8 · 오토캐드/인벤터 공식 rec_vram_gb=8.
            **카테고리 최저이자 유일한 커뮤니티 VRAM 값이 8 이다.**
            ⚠ 옛 850W(required_power_watt) 는 버린다 — `software` 에 근거가 없다.
    SSD 500  인벤터 min_storage_gb=40 · 오토캐드 10 · 3ds맥스 9 · 스케치업 rec 6
            중 최대(40) + 도면·조립품 파일 보관. 재고 500/512GB 가 넉넉하다.
            (옛 2000GB 는 근거 없음 — 캐드 파일은 영상 소스와 성격이 다르다)

  render_3d(3D 렌더링)
    RAM 32  마야 커뮤니티 ram_gb=32 — **카테고리 렌더 3종 중 최저 커뮤니티값**
            (블렌더 64 · 3ds맥스 null). 블렌더 공식 rec_ram_gb=32 가 같은 선.
            64 는 겨냥으로 보낸다(블렌더 커뮤 note "여러 앱 동시 고급 사용자 64~128").
    GPU VRAM 12  블렌더 커뮤니티 vram_gb=12 — 렌더 3종 중 **유일한** 커뮤니티 VRAM
            값이므로 최저이자 최고다. 블렌더 공식 rec_vram_gb=8 보다 높은 쪽을 쓰는
            이유는 note 원문이 "부족하면 시스템 메모리로 넘어가 성능이 크게 떨어지므로
            넉넉히 잡으라"고 적기 때문 — 렌더링에서 VRAM 부족은 느려짐이 아니라
            작업 실패에 가깝다(AI 의 VRAM 하드 제약과 같은 성격).
    SSD 500  마야 min_storage_gb=7 · 3ds맥스 9 · 블렌더 null 로 프로그램 자체는
            작다. 500 은 렌더 출력·텍스처 보관 기준이고 재고가 넓은 선이다.
            (옛 2000GB 를 유지할 근거를 `software` 에서 찾지 못했다 — 내린다)

■ ★ GPU 상한을 캐드에 건다 — `usage_tier_rules` (예산이 올라도 GPU 로 안 간다)
  오토캐드 note 원문: "GPU는 화면 표시용이라 권장(8GB)을 넘겨 투자할 실익이 작다."
  이것은 하한이 아니라 **겨냥의 반대**(상한)라서 `usage_tier_rules` 다(§4 판정 ②).
  선례가 있다 — design/dev/video 의 RAM `lte` 「정직하게」 행(0013-09-13).
      cad  GPU vram_gb **lte 8**   근거: 위 note 원문 + 캐드 4종 중 3종이 cpu 병목
  ⚠ **판단이 갈린 자리다.** 스케치업 note 는 "PBR 재질은 VRAM 32GB 이상"이라고
    적는다. 그러나 같은 표의 조사자가 커뮤니티 note 에 "이 32GB 조건은 특정 PBR
    워크플로 한정이므로 일반 상담에 그대로 적용하면 **과잉 견적**이 된다"고 직접
    경고한다 — 그 경고를 따랐다. PBR 고객은 상담에서 되물어 render_3d 로 보낸다.
  ⚠ 클럭 하한을 못 거는 것(위)의 **차선**이기도 하다. CPU 를 직접 올릴 수단이
    없으니, GPU 를 8GB 로 묶어 남는 예산이 CPU·RAM 으로 흐르게 한다.

  겨냥 2행도 같이 넣는다(budget_min 은 이 표의 표준 단계 150만 — 8키 중 7키가 쓴다):
      cad       RAM gte 32   오토캐드·솔리드웍스·인벤터 커뮤니티 aggregate 전부 32
      render_3d RAM gte 64   블렌더 커뮤니티 aggregate 64

■ 낱말 — 조사 산출물 `ambiguity_rules` 를 그대로 구현했다
  shared_words = ["모델링", "3d", "디자인"] — **단독으로 분기하면 안 되는 말**이다.
  0102 와 **같은 장치**로 푼다:
    · cad 의 낱말은 전부 «특정 신호»다(프로그램명·도면·설계·건축). 모호어가 없다.
    · 모호어(「3D」·「3D 작업」·「모델링」)는 **render_3d 만** 갖는다.
    · **cad 가 sort_order 에서 앞선다**(100~102 < 103~105).
  따라서 「3D 캐드」·「3D 모델링(인벤터)」처럼 **둘 다 걸리는 문장은 cad 가 이긴다** —
  프로그램명이라는 구체적 신호가 「3D」라는 빈 말을 이겨야 한다. 반대로 모호어만
  있으면 render_3d 로 떨어진다(조사 결론: 「3D 작업」 입말 7회로 3D 계열 최다
  자기호명어이고, 캐드 고객은 자기를 「캐드」라고 부른다).
  ⚠ `match()` 는 **대소문자를 구분**한다(`t in value`). 그래서 "CAD"/"cad",
    "3D"/"3d" 처럼 **양쪽 표기를 다 넣는다** — 옛 시드가 'CAD'·'Maya'·'Blender'만
    넣어 둔 탓에 실제 고객 말("캐드 돌리려고요")이 **하나도 안 걸렸다**(실측:
    match() -> None 이 19/20). 이것이 이번 분할이 고치는 두 번째 결함이다.

■ design 보강 — 「그래픽 작업(포샵, 일러)」이 3D 로 새지 않게
  조사자가 지적한 실측 위험이다("그래픽작업"은 국내 입말에서 2D 를 뜻한다).
  실조회하니 `design` 낱말이 **["디자인"] 하나뿐**이라 이 문장은 지금 아무 데도
  안 걸린다(match -> None). 2D 프로그램명을 넣어 design 으로 받는다 —
  ⚠ 「그래픽」이라는 말 자체는 **넣지 않는다.** 그 말을 넣으면 render_3d 가 물려받은
    옛 라벨 「3D 그래픽」이 design(sort 15) 에 먼저 걸려 격자가 끊긴다.
  ⚠ 알려진 변화: 옛 video_3d 시드 낱말 「건축 디자인」은 이제 design(15)이 먼저
    잡는다(「디자인」 부분일치). 「건축」·「건축 설계」는 cad 로 정상 이동한다.
    ambiguity_rules 의 "「디자인」 단독 -> 2D" 와 방향이 같아 그대로 둔다.

■ usage_alloc — **행을 만들지 않는다**
  `video_3d` 는 지금 `usage_alloc` 행이 **0행**이다(실조회) — 즉 기본(NULL) 배분을
  쓴다. 0102 의 원칙 그대로다: **갈래별 표본이 없으면 값을 짓지 않는다.**
  「캐드는 GPU 비중을 낮춰야 한다」는 근거는 있지만, 그것을 몇 %로 적을지는
  시장 표본이 없다 — 그래서 **비율이 아니라 규칙으로** 표현했다(위 GPU vram lte 8).
  근거가 있는 만큼만, 근거가 있는 형태로 쓴다.

Revision ID: 0104
Revises: 0103
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None


CAD_KEY, CAD_LABEL = "cad", "캐드·설계"
RENDER_KEY, RENDER_LABEL = "render_3d", "3D 렌더링"

# ⚠ 전부 «특정 신호»만 — 모호어(3D·모델링)를 넣으면 위 ★ 판정이 무너진다.
#   대소문자 양쪽 표기를 다 넣는다(match 가 대소문자를 구분한다).
CAD_TERMS = [
    "캐드", "오토캐드", "AutoCAD", "autocad", "AUTOCAD", "CAD", "cad",
    "도면", "제도",
    "솔리드웍스", "솔리드워크", "솔리드웍", "SolidWorks", "solidworks",
    "인벤터", "Inventor", "inventor",
    "카티아", "CATIA", "catia",
    "퓨전360", "퓨전 360", "Fusion360", "fusion360",
    "스케치업", "SketchUp", "sketchup",
    "라이노", "Rhino", "rhino",
    "레빗", "Revit", "revit", "BIM", "bim",
    "캐드캠",
    "설계",            # 「기계 설계」·「제품 설계」·「건축 설계」를 부분일치로 받는다
    "건축", "인테리어", "토목", "엔지니어링",
]

# ⚠ 모호어(「3D」·「3D 작업」·「모델링」)는 **여기에만** 있다. cad 가 앞서므로
#   프로그램명이 함께 나오면 cad 가 이긴다 — ambiguity_rules 구현.
RENDER_TERMS = [
    "3D 그래픽", "3D그래픽",          # ★ 옛 라벨 — grid_cells·consult_sessions 이력
    "렌더링", "랜더링", "렌더",
    "블렌더", "블랜더", "Blender", "blender",
    "3ds 맥스", "3ds맥스", "3ds", "3Ds", "3DS", "3dsmax", "3ds Max", "맥스",
    "마야", "Maya", "maya",
    "지브러시", "ZBrush", "zbrush",
    "시네마4d", "시네마 4D", "C4D", "c4d",
    "후디니", "Houdini", "houdini",
    "브이레이", "V-Ray", "v-ray", "VRay", "vray",
    "코로나렌더", "아놀드", "Arnold", "arnold", "옥테인", "Octane", "octane",
    "언리얼", "Unreal", "unreal", "유니티", "Unity",
    "애니메이션", "시각화", "캐릭터모델링", "CG",
    # ── 모호어 — 마지막 보루 ──
    "3D 모델링", "3D모델링", "3d모델링", "모델링",
    "3D 작업", "3D작업", "3d작업",
    "3D", "3d",
]

# (slot, field, op, value, label, detail_fmt)
CAD_RULES = [
    ("GPU", "vram_gb", "gte", 8, "캐드 그래픽 메모리",
     "VRAM {v}GB — 오토캐드·인벤터 커뮤니티 권장 {r}GB(공식 권장도 8GB)."
     " 캐드는 GPU 가 화면 표시용이라 이 위로 올려도 실익이 작습니다"),
    ("RAM", "capacity_gb", "gte", 16, "캐드 메모리",
     "{v}GB — 솔리드웍스·인벤터 공식 최소 {r}GB"
     " (인벤터 공식: 부품 500개 미만 조립품 기준). 대형 조립품·초대형은 32~64GB 로 올립니다"),
    ("SSD", "capacity_gb", "gte", 500, "캐드 저장 용량",
     "{v}GB (인벤터 공식 설치 40GB + 도면·조립품 파일 보관 기준)"),
]
RENDER_RULES = [
    ("GPU", "vram_gb", "gte", 12, "3D 렌더링 그래픽 메모리",
     "VRAM {v}GB — 블렌더 커뮤니티 권장 {r}GB."
     " Cycles 렌더링이 GPU 연산이라 VRAM 이 모자라면 속도가 급락합니다"),
    ("RAM", "capacity_gb", "gte", 32, "3D 렌더링 메모리",
     "{v}GB — 마야 커뮤니티 권장 {r}GB(블렌더 공식 권장도 32GB)."
     " 여러 앱을 함께 쓰는 전업 작업은 64GB 로 올립니다"),
    ("SSD", "capacity_gb", "gte", 500, "3D 렌더링 저장 용량",
     "{v}GB (렌더 출력·텍스처·에셋 보관 기준)"),
]

CAD_ORDER = {"GPU": 100, "RAM": 101, "SSD": 102}
RENDER_ORDER = {"GPU": 103, "RAM": 104, "SSD": 105}   # video_3d 가 쓰던 자리

# design 보강 — 2D 프로그램명만. 「그래픽」이라는 말 자체는 넣지 않는다(위 ■ 참조).
_DESIGN_TERMS_OLD = ["디자인"]
_DESIGN_TERMS_NEW = ["디자인", "포토샵", "포샵", "일러스트", "일러",
                     "인디자인", "라이트룸", "피그마"]

# 0090 이 남긴 video_3d 의 상태(downgrade 복원용) — 실조회값 그대로
_V3D_LABEL = "3D 그래픽"
_V3D_TERMS = ["3D 그래픽", "건축 디자인", "3ds Max", "Maya", "Blender", "CAD",
              "엔지니어링", "수백만 폴리곤 렌더링"]
_V3D_RULES = {
    "GPU": ("required_power_watt", 850, "3D 그래픽 GPU 등급",
            "권장 전원 {v}W 이상 (기준 {r}W 이상)"),
    "RAM": ("capacity_gb", 64, "3D 그래픽 메모리", "{v}GB (기준 {r}GB 이상)"),
    "SSD": ("capacity_gb", 2000, "3D 그래픽 저장 용량",
            "{v}GB (고속 NVMe 기준 {r}GB 이상)"),
}
_V3D_ORDER = {"GPU": 103, "RAM": 104, "SSD": 105}

# ── usage_tier_rules — 겨냥 + 캐드 GPU 상한 ────────────────────────────────
# (usage_key, budget_min, slot, field, op, value, label, note, sort_order)
_TIER_ROWS = [
    (CAD_KEY, 1500000, "RAM", "capacity_gb", "gte", "32", "메모리 32GB 이상",
     "오토캐드·솔리드웍스·인벤터 커뮤니티 aggregate 전부 32GB"
     " (인벤터 공식: 부품 500개 이상 조립품 32GB) — 하한은 16, 겨냥이 32", 210),
    (CAD_KEY, 1500000, "GPU", "vram_gb", "lte", "8", "캐드 그래픽 메모리 상한",
     "오토캐드 note 원문 \"GPU는 화면 표시용이라 권장(8GB)을 넘겨 투자할 실익이 작다\""
     " — 캐드 4종 중 3종이 cpu 병목. 예산이 올라도 GPU 가 아니라 CPU·RAM 으로 간다"
     " (스케치업 PBR 32GB 는 커뮤니티 note 가 \"일반 상담에 적용하면 과잉 견적\"이라"
     " 스스로 경고해 제외 — 판단이 갈린 자리)", 901),
    (RENDER_KEY, 1500000, "RAM", "capacity_gb", "gte", "64", "메모리 64GB 이상",
     "블렌더 커뮤니티 aggregate 64GB (\"여러 앱을 같이 쓰는 고급 사용자는 64~128GB\")"
     " — 하한은 마야 커뮤니티 32, 겨냥이 64", 211),
]


_INS_FLOOR = sa.text(
    "INSERT INTO usage_floors (usage_key, usage_label, match_terms, slot,"
    " field, op, value, label, detail_fmt, sort_order)"
    " VALUES (:k, :ul, CAST(:t AS JSONB), :s, :f, :o, :v, :l, :d, :so)")


def upgrade() -> None:
    conn = op.get_bind()

    # ── ① video_3d -> render_3d 개명 + 값 개정 (floor_id 67·68·69 유지) ─────
    render_blob = json.dumps(RENDER_TERMS, ensure_ascii=False)
    for slot, field, oper, val, rlabel, fmt in RENDER_RULES:
        conn.execute(sa.text(
            "UPDATE usage_floors SET usage_key=:k, usage_label=:ul,"
            " match_terms=CAST(:t AS JSONB), field=:f, op=:o, value=:v,"
            " label=:l, detail_fmt=:d, sort_order=:so"
            " WHERE usage_key='video_3d' AND slot=:s"),
            {"k": RENDER_KEY, "ul": RENDER_LABEL, "t": render_blob, "f": field,
             "o": oper, "v": val, "l": rlabel, "d": fmt,
             "so": RENDER_ORDER[slot], "s": slot})

    # ── ② cad 신설 — 재실행 안전 ──────────────────────────────────────────
    have = {r[0] for r in conn.execute(sa.text(
        "SELECT DISTINCT usage_key FROM usage_floors")).all()}
    if CAD_KEY not in have:
        cad_blob = json.dumps(CAD_TERMS, ensure_ascii=False)
        for slot, field, oper, val, rlabel, fmt in CAD_RULES:
            conn.execute(_INS_FLOOR, {
                "k": CAD_KEY, "ul": CAD_LABEL, "t": cad_blob, "s": slot,
                "f": field, "o": oper, "v": val, "l": rlabel, "d": fmt,
                "so": CAD_ORDER[slot]})

    # ── ③ design 낱말 보강 — 2D 가 3D 로 새지 않게 ─────────────────────────
    conn.execute(sa.text(
        "UPDATE usage_floors SET match_terms=CAST(:t AS JSONB)"
        " WHERE usage_key='design'"),
        {"t": json.dumps(_DESIGN_TERMS_NEW, ensure_ascii=False)})

    # ── ④ usage_tier_rules — 겨냥 + 캐드 GPU 상한 ─────────────────────────
    for key, bmin, slot, field, oper, val, lab, note, so in _TIER_ROWS:
        exists = conn.execute(sa.text(
            "SELECT 1 FROM usage_tier_rules WHERE usage_key=:k AND slot=:s"
            " AND field=:f AND op=:o AND budget_min=:b LIMIT 1"),
            {"k": key, "s": slot, "f": field, "o": oper, "b": bmin}).first()
        if exists:
            continue
        conn.execute(sa.text(
            "INSERT INTO usage_tier_rules (usage_key, budget_min, slot, field,"
            " op, value, label, active, note, sort_order)"
            " VALUES (:k, :b, :s, :f, :o, :v, :l, TRUE, :n, :so)"),
            {"k": key, "b": bmin, "s": slot, "f": field, "o": oper, "v": val,
             "l": lab, "n": note, "so": so})


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text(
        "DELETE FROM usage_tier_rules WHERE usage_key IN (:a, :b)"),
        {"a": CAD_KEY, "b": RENDER_KEY})

    conn.execute(sa.text(
        "UPDATE usage_floors SET match_terms=CAST(:t AS JSONB)"
        " WHERE usage_key='design'"),
        {"t": json.dumps(_DESIGN_TERMS_OLD, ensure_ascii=False)})

    conn.execute(sa.text("DELETE FROM usage_floors WHERE usage_key=:k"),
                 {"k": CAD_KEY})

    v3d_blob = json.dumps(_V3D_TERMS, ensure_ascii=False)
    for slot, (field, val, rlabel, fmt) in _V3D_RULES.items():
        conn.execute(sa.text(
            "UPDATE usage_floors SET usage_key='video_3d', usage_label=:ul,"
            " match_terms=CAST(:t AS JSONB), field=:f, value=:v, label=:l,"
            " detail_fmt=:d, sort_order=:so WHERE usage_key=:k AND slot=:s"),
            {"ul": _V3D_LABEL, "t": v3d_blob, "f": field, "v": val,
             "l": rlabel, "d": fmt, "so": _V3D_ORDER[slot],
             "k": RENDER_KEY, "s": slot})
