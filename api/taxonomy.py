"""부품 어휘의 단일 원천 — 세 개념을 가른다(슬라이스 A).

  part_type   상품 종류. 17종. `products.part_type`의 값. 엔진과 화면이 함께 읽는다.
  slot        **견적서의 자리.** 8종. part_type에서 파생된다(공랭·수랭 → 한 자리).
  CORE_TYPES  견적에 쓰이는 핵심 부품 종류. 10종.

**셋은 서로 다르다 — 뭉개면 안 된다.**
  · slot(8)에는 HDD가 없다. HDD는 핵심 부품이지만 **견적 필수 자리는 아니다**(선택품).
  · CORE_TYPES(10)에는 HDD가 있다. 그래서 `set(CORE_TYPES) != QUOTE_SLOTS의 값 합집합(9)`이다.
  · 공랭·수랭은 견적에서 한 자리지만 **상품 분류로는 다른 것**이다(슬라이스 49).
    같은 라벨을 쓰면 집계에 'CPU쿨러'가 두 줄로 나와 어느 쪽인지 알 수 없다.

왜 한 곳에 모았나 — 흩어져 있었고, **이미 두 곳이 어긋나 있었다**:
    SLOT_KO      admin_setup · admin_swap_logs · candidates · swap  네 벌
                 → swap.py만 SSD를 "저장장치"로 표시했다(나머지 셋은 "SSD").
                   부품 교체 안내에서만 다른 말이 나가고 있었다.
    라벨 맵      PART_TYPE_LABELS · PART_KO · SLOT_KO  세 어휘 여섯 곳
                 → PART_KO만 수랭을 "수랭", PART_TYPE_LABELS는 "수냉"으로 썼다.
                   PART_TYPE_LABELS는 자기 안에서도 공"랭"/수"냉"으로 어긋나 있었다.
    코어 집합    admin_pool.CORE_TYPES · admin_products.CORE_PARTS  두 벌(당시엔 일치)

기존 임대 관리자(윈윈소프트)의 `베스트7주력부품` — 부품 분류 트리를 약어로 복제한 두 번째
트리 — 과 **같은 병이다**(`docs/research/legacy-admin-2026-08-04.md`). 정의를 여러 벌 두면
어긋난다. 회귀 `[32] 부품 어휘 단일 원천`이 "이 파일 밖에서 정의하지 않는다"를 지킨다.

표기: 冷을 '랭'으로 적는다(공랭·수랭). 표준 표기이자 프로젝트 우세 표기(수랭 32 : 수냉 12).
"""

# ── part_type = 상품 종류 ─────────────────────────────────────────────
# 닫힌 집합이다. **운영자가 늘릴 수 없다** — 엔진이 읽기 때문에 슬라이스로만 바뀐다.
# (판매용 분류는 별도 축인 `categories`가 맡는다 — 그쪽은 운영자가 자유롭게 만든다.)
# 회귀가 이 집합 = DB `products.part_type` distinct 를 대조한다.
PART_LABELS = {
    "CPU": "CPU", "MB": "메인보드", "RAM": "메모리", "GPU": "그래픽카드",
    "SSD": "SSD", "HDD": "HDD", "POWER": "파워", "CASE": "케이스",
    "COOLER_CPU_AIR": "CPU쿨러(공랭)", "COOLER_CPU_AIO": "CPU쿨러(수랭)",
    "MONITOR": "모니터", "KEYBOARD": "키보드", "MOUSE": "마우스",
    "HEADSET": "헤드셋", "SPEAKER": "스피커", "WEBCAM": "웹캠",
    "ETC": "미분류",   # 적재 시 부품 종류를 정하지 못한 상품(슬라이스 39) — 추천 대상 아님
}
PART_TYPES = tuple(PART_LABELS)

# ── slot = 견적서의 자리 ──────────────────────────────────────────────
# 순서가 곧 견적서 표시 순서다. 바꾸면 화면이 바뀐다.
SLOTS = ["CPU", "MB", "RAM", "GPU", "CASE", "COOLER", "POWER", "SSD"]

# 자리 → 그 자리를 채울 수 있는 part_type들.
# **part_type 단위로 세면 오판한다**: 쿨러는 공랭·수랭이 한 자리라 수랭이 0이어도
# 공랭이 남아 있으면 견적이 성립한다(슬라이스 48에서 실제로 헷갈렸다).
QUOTE_SLOTS = {
    "CPU": ("CPU",), "MB": ("MB",), "RAM": ("RAM",), "GPU": ("GPU",),
    "CASE": ("CASE",), "COOLER": ("COOLER_CPU_AIR", "COOLER_CPU_AIO"),
    "POWER": ("POWER",), "SSD": ("SSD",),
}
SLOT_LABELS = {
    "CPU": "CPU", "MB": "메인보드", "RAM": "메모리", "GPU": "그래픽카드",
    "CASE": "케이스", "COOLER": "CPU쿨러", "POWER": "파워", "SSD": "SSD",
}

# ── 핵심 부품 ─────────────────────────────────────────────────────────
# 견적에 쓰이는 부품 종류. 후보 풀·검수 집계의 대상.
# SSD 자리만 견적 필수라 HDD는 SLOTS에 없지만, **핵심 부품이긴 하다**.
CORE_TYPES = ("CPU", "GPU", "MB", "RAM", "SSD", "HDD", "POWER", "CASE",
              "COOLER_CPU_AIR", "COOLER_CPU_AIO")

# 사양 항목을 걸 수 있는 종류 = ETC를 뺀 전부.
# **미분류에 필수 사양을 걸면 그 상품들이 영원히 검수 대기가 된다**(슬라이스 56 규약).
ASSIGNABLE_TYPES = tuple(t for t in PART_TYPES if t != "ETC")


def slot_of(part_type: str) -> str:
    """part_type → 견적 자리. 쿨러만 두 종류가 한 자리다."""
    return "COOLER" if part_type.startswith("COOLER_") else part_type


def part_label(part_type: str | None) -> str:
    """미등록 코드는 원문 폴백(적재가 새 코드를 만들어도 화면이 깨지지 않게)."""
    return PART_LABELS.get(part_type, part_type or "—")


def slot_label(slot: str | None) -> str:
    return SLOT_LABELS.get(slot, slot or "—")
