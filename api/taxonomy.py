"""부품 어휘의 단일 원천 — 세 개념을 가른다(슬라이스 A).

  part_type   상품 종류. 19종. `products.part_type`의 값. 엔진과 화면이 함께 읽는다.
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
# 19종: 조립 부품 10 + 주변기기 6 + **완성품 2**(완제품·베어본) + 미분류 1.
# (판매용 분류는 별도 축인 `categories`가 맡는다 — 그쪽은 운영자가 자유롭게 만든다.)
# 회귀가 이 집합 = DB `products.part_type` distinct 를 대조한다.
PART_LABELS = {
    "CPU": "CPU", "MB": "메인보드", "RAM": "메모리", "GPU": "그래픽카드",
    "SSD": "SSD", "HDD": "HDD", "POWER": "파워", "CASE": "케이스",
    "COOLER_CPU_AIR": "CPU쿨러(공랭)", "COOLER_CPU_AIO": "CPU쿨러(수랭)",
    "MONITOR": "모니터", "KEYBOARD": "키보드", "MOUSE": "마우스",
    "HEADSET": "헤드셋", "SPEAKER": "스피커", "WEBCAM": "웹캠",
    # 완성품 축(2026-08-05 사용자 결정). **부품이 아니라 그 자체가 한 대다.**
    #   · 엔진은 이 둘을 읽지 않는다 — 두 후보 뷰가 `category_group`(core_part/peripheral)과
    #     `part_type` 을 **둘 다 화이트리스트**로 걸어서 정의상 들어갈 수 없다(회귀가 지킨다).
    #   · 그런데도 `part_type` 에 둔 이유: **사양을 걸 수 있는 축이 이것 하나**이고
    #     (`spec_field_defs.part_types` · `ASSIGNABLE_TYPES`), 주문·견적 스냅샷이 박는 것도
    #     `part_type` 이다. 판매 분류(`categories`)는 어느 스냅샷에도 없어서 과거 주문에서
    #     되살릴 수 없고, 적재는 `category_id` 를 읽지도 쓰지도 않는다.
    #   · 둘을 나눠 둔다 — 조립비·필요 사양이 다르다. 합쳤다 나누는 것이 더 비싸다.
    "PC_COMPLETE": "완제품 PC", "BAREBONE": "베어본·미니PC",
    "ETC": "기타(ETC)",   # 적재 시 부품 종류를 정하지 못한 상품(슬라이스 39) — 추천 대상 아님
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


def slot_of(part_type: str) -> str:
    """part_type → 견적 자리. 쿨러만 두 종류가 한 자리다."""
    return "COOLER" if part_type.startswith("COOLER_") else part_type


# ── 표시 종류 = 운영자가 고르는 자리 ──────────────────────────────────
# 사용자 결정(2026-08-05): **화면에서는 CPU쿨러 공랭·수랭을 하나로 본다.** 18종(19종 − 쿨러 1).
#
# **part_type 은 합치지 않는다.** `radiator_rows`(라디에이터 열)는 `COOLER_CPU_AIO`에만
# 적용되고(0022), 라디에이터 장착 규칙이 그 값으로 케이스 수납을 판정한다. 합치면
# 수랭 628건 중 **589건이 들고 있는 판정 근거가 대상을 잃고**, 수랭이 안 들어가는
# 케이스에 수랭이 붙는다. 견적이 조립 불가를 내는 것보다 나쁜 결과다.
#
# 접는 방식은 **견적 슬롯과 같다**(`slot_of`) — 두 번째 정의를 만들지 않는다.
# 그래서 "쿨러는 하나"라는 사실이 이 파일 안에서 한 번만 적힌다.
#
# 상품 한 건의 표시는 이것을 쓰지 않는다: 목록 행은 여전히 `part_label`로
# 'CPU쿨러(수랭)'이라 적는다 — 고르는 자리를 합치는 것이지 **사실을 감추는 게 아니다.**
DISPLAY_LABELS: dict[str, str] = {}
_members: dict[str, list[str]] = {}
for _t, _l in PART_LABELS.items():
    _k = slot_of(_t)
    DISPLAY_LABELS.setdefault(_k, SLOT_LABELS.get(_k) or _l)
    _members.setdefault(_k, []).append(_t)
DISPLAY_MEMBERS = {_k: tuple(_v) for _k, _v in _members.items()}
DISPLAY_TYPES = tuple(DISPLAY_LABELS)
del _t, _l, _k, _members


# 접힌 종류의 **두 번째 칸** 라벨 — 2단 선택(2026-08-06 사용자 결정)에서 쓴다.
# "CPU쿨러(공랭)" 에서 괄호를 벗겨 만들지 않는다 — 표기가 바뀌면 조용히 깨진다.
SUB_LABELS = {"COOLER_CPU_AIR": "공랭", "COOLER_CPU_AIO": "수랭"}


def choice_tree(types) -> list[dict]:
    """고르는 자리에 쓸 **2단 선택지**. 접히는 종류만 `options` 를 갖는다.

        [{"key": "CPU", "label": "CPU"},
         {"key": "COOLER", "label": "CPU쿨러",
          "options": [{"key": "COOLER_CPU_AIR", "label": "공랭"}, …]}]

    화면은 `options` 가 있으면 두 번째 칸을 띄우기만 한다 — **무엇이 접히는지는
    이 파일만 안다.** 화면이 'COOLER 는 공랭·수랭' 을 알기 시작하면 그 지식이
    화면 수만큼 복제되고, 종류가 늘 때 한 곳만 빠진다.
    """
    order, members = [], {}
    for t in types:
        k = slot_of(t)
        if k not in members:
            order.append(k)
            members[k] = []
        members[k].append(t)
    out = []
    for k in order:
        ts = members[k]
        e = {"key": k if len(ts) > 1 else ts[0],
             "label": DISPLAY_LABELS.get(k, PART_LABELS.get(ts[0], k))}
        if len(ts) > 1:
            e["options"] = [{"key": t, "label": SUB_LABELS.get(t, PART_LABELS.get(t, t))}
                            for t in ts]
        out.append(e)
    return out


def expand_display(key: str) -> tuple[str, ...]:
    """표시 종류 → 실제 part_type들. 'COOLER' → 공랭·수랭. 모르는 값은 그대로."""
    return DISPLAY_MEMBERS.get(key, (key,))


def display_labels(part_types) -> list[str]:
    """part_type 목록 → 표시 라벨(중복 제거·순서 보존). 공랭+수랭 → 'CPU쿨러' 한 줄."""
    out: list[str] = []
    for t in part_types or []:
        lb = DISPLAY_LABELS.get(slot_of(t), PART_LABELS.get(t, t))
        if lb not in out:
            out.append(lb)
    return out

# ── 핵심 부품 ─────────────────────────────────────────────────────────
# 견적에 쓰이는 부품 종류. 후보 풀·검수 집계의 대상.
# SSD 자리만 견적 필수라 HDD는 SLOTS에 없지만, **핵심 부품이긴 하다**.
CORE_TYPES = ("CPU", "GPU", "MB", "RAM", "SSD", "HDD", "POWER", "CASE",
              "COOLER_CPU_AIR", "COOLER_CPU_AIO")

# 사양 항목을 걸 수 있는 종류 = ETC를 뺀 전부.
# **미분류에 필수 사양을 걸면 그 상품들이 영원히 검수 대기가 된다**(슬라이스 56 규약).
ASSIGNABLE_TYPES = tuple(t for t in PART_TYPES if t != "ETC")

# 완성품은 부품이 아니다 — 어느 슬롯에도 들어가지 않고 후보 뷰에도 없다.
# 화면이 '조립 부품 / 주변기기' **이진 분기**로 갈라 왔기 때문에 이 집합이 필요하다:
# 그 분기만 두면 완제품이 '주변기기'라 불린다(실제로 두 곳이 그랬다).
BUILT_TYPES = ("PC_COMPLETE", "BAREBONE")

# `slot_of` 는 위(SLOT_LABELS 아래)에 한 번만 정의한다 — 여기 있던 두 번째 정의를 지웠다.
# 같은 파일 안에서 두 벌이 되면 이 파일이 존재하는 이유가 없어진다.


def part_label(part_type: str | None) -> str:
    """미등록 코드는 원문 폴백(적재가 새 코드를 만들어도 화면이 깨지지 않게)."""
    return PART_LABELS.get(part_type, part_type or "—")


def slot_label(slot: str | None) -> str:
    return SLOT_LABELS.get(slot, slot or "—")
