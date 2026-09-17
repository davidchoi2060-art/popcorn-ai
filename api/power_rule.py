"""파워(전원) 판정의 단일 원천 — 여유율 계산과 고객 문구.

왜 이 파일이 생겼나
  `power_headroom_pct` 계산이 **완전히 같은 3줄로 세 파일에 복제**돼 있었다:
  `recommend.py:758` · `swap.py:158` · `expert.py:469`. 하나만 고치면 나머지 둘이
  «조용히» 옛 값을 쓴다 — CLAUDE.md §단일 원천이 금지하는 바로 그 상태다.
  2026-09-17 파워 규칙 재설계(`gpu_power_draw_watt` 신설 · 마이그레이션 0094)가
  분모를 갈아엎으므로, 이 기회에 한 곳으로 모은다.

왜 `recommend.py`(엔진 정본)가 아니라 별도 파일인가
  · `swap.py`·`expert.py` 는 이미 `recommend.py` 를 import 한다. 반대 방향은 없다 —
    즉 recommend 에 두어도 순환은 안 나지만, 두 파일의 기존 주석이 「엔진 정본에 새
    공용 함수를 늘리지 않는다」를 명시적으로 지키고 있다(`expert._partial_compat`
    docstring). 그 합의를 깨지 않으면서 복제를 없애려면 **세 파일 모두가 부를 수 있는
    제3의 작은 모듈**이 맞다.
  · 이 모듈은 DB·FastAPI 에 의존하지 않는다(순수 계산 + 문구). 그래서 테스트·하네스가
    엔진 전체를 끌어오지 않고 이 한 파일만 import 해서 판정을 재현할 수 있다.

용어 (혼동하면 오늘의 사고가 되풀이된다)
  `gpu_power_draw_watt`   카드 **자체** 소비전력(TDP/TGP/TBP). 규칙이 보는 값.
  `required_power_watt`   성능 **등급** 근사축. 용도 하한(usage_floors)이 쓴다.
                          «시스템 권장 파워»로 의도적으로 상향된 값이라
                          전력 판정에 쓰면 안 된다 - 그게 RTX 3050 6GB(실 70W)를
                          550W 로 취급해 실판매품 9건을 탈락시킨 원인이다.
"""

# GPU 외 시스템 전력(CPU·메인보드·RAM·드라이브·팬)의 보수적 정액 대체값.
# **정본은 DB 다** — `compat_rules.ref_offset`(rule_key='power')이 진짜 값이고,
# 이 상수는 규칙 행을 못 읽는 자리(문구 생성 등)에서 쓰는 **폴백**이다.
# 근거와 한계는 마이그레이션 0094 의 머리말 참조: 실판매 234벌 관측 최소 여유는
# +400W 였고 +200 은 「실판매를 다 통과시키면서 위험 조합은 잡는」 구간에서 고른 값이다.
SYSTEM_POWER_OVERHEAD_W = 200


def required_watt(gpu: dict | None, offset: int = SYSTEM_POWER_OVERHEAD_W):
    """이 GPU 구성이 요구하는 파워 정격(W). 모르면 None(= 판정 불가).

    None 을 0 이나 기본값으로 바꾸지 않는다 — "모른다"를 "괜찮다"로 만드는 순간
    확인한 적 없는 결론을 고객에게 말하게 된다(§화면 정직성).
    """
    if not gpu:
        return None
    draw = gpu.get("gpu_power_draw_watt")
    if draw is None:
        return None
    return int(draw) + int(offset or 0)


def headroom_pct(gpu: dict | None, power: dict | None,
                 offset: int = SYSTEM_POWER_OVERHEAD_W):
    """전원 여유율(%) — `rated_watt / (카드 소비전력 + 오프셋) * 100`. 모르면 None.

    분모가 «규칙이 요구하는 값 그 자체»라서 **여유율 100% 이상 == 파워 규칙 통과**가
    된다(회귀 1044행이 그 성질을 검사한다). 예전 분모(`required_power_watt`=등급값)는
    규칙과도 어긋났고 숫자 자체가 무의미했다 — RTX 3050 6GB(실 70W) 500W 구성이
    "여유율 90%"로 나왔다.
    """
    need = required_watt(gpu, offset)
    if not need or not power or not power.get("rated_watt"):
        return None
    return int(power["rated_watt"] / need * 100)


def shortage_text(need_watt: int | None, part_label: str = "그래픽카드") -> str:
    """파워 부족을 고객에게 알리는 문구 — **결론만**(사장님 지시 2026-09-17 #2).

    카드 TDP 숫자를 고객에게 다 밝히지 않는다. 옛 문구는
      "이 그래픽카드는 필요 전력이 550W라 현재 파워(500W)로는 부족해요"
    였는데, 그 550 은 등급값이라 **사실이 아니었다** — RTX 3050 6GB 는 70W 고 실제로
    500W 파워로 팔린다. 숫자를 말할 거면 맞는 숫자여야 하고, 고객에게 필요한 숫자는
    "그럼 파워를 몇 W 로 올려야 하나"(= 권장 정격) 하나뿐이다.
    """
    if need_watt:
        return (f"파워 용량이 부족해요(권장 {int(need_watt)}W)"
                " - 파워를 함께 바꿔야 조립할 수 있어요.")
    return ("파워 용량을 확인할 수 없어요"
            " - 이 부품은 전원을 직접 확인해야 해요.")


# ── 다중 GPU (사장님 지시 2026-09-17 #3) ────────────────────────────────────
# 지시: "멀티 GPU 는 1장 기준으로 둔다 + 다중 GPU 구성은 「전원 수동 확인 필요」로 표시".
#
# **실측 결론: 지금 견적 엔진에는 GPU 수량 개념이 없다.** 억지로 만들지 않았다.
#   · 견적 스냅샷 `quote_snapshots.items.parts[]` 항목은 product_code/name/price 뿐 —
#     수량 키가 아예 없다(슬롯당 1개가 구조적 전제다).
#   · `products.product_name` 에 "* 2개" 표기가 있는 GPU 는 **0건**(전수 확인).
#     완제PC 상세(`builtpc_parsed.json`)에는 `RTX A6000 * 4개` 같은 것이 14벌 있지만,
#     그건 몰 상품 설명 파싱 결과이고 우리 부품 카탈로그의 상품이 아니다.
#   · 따라서 규칙은 자동으로 "1장 기준"이다(지시의 앞 절반은 이미 만족).
# 수량 개념이 생기는 날(완제PC 구성 해석기가 견적 엔진에 붙는 등) 이 함수를 쓰면 된다 —
# 그때까지는 호출부가 없다. 값을 지어내 표시하는 것보다 안 하는 쪽이 맞다.
MULTI_GPU_NOTE = "그래픽카드가 여러 장인 구성이라 전원은 수동 확인이 필요해요."


def multi_gpu_note(qty) -> str | None:
    """GPU 수량이 2 이상으로 «확인되면» 수동 확인 고지, 아니면 None.

    qty 가 None(모름)이면 아무 말도 하지 않는다 — 모르는 것을 1로 단정하지도,
    여러 장이라고 추측하지도 않는다.
    """
    try:
        n = int(qty)
    except (TypeError, ValueError):
        return None
    return MULTI_GPU_NOTE if n >= 2 else None
