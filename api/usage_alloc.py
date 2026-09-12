"""용도별 예산 배분율 로더 — `usage_alloc` 테이블이 단일 원천(2026-09-12 사장님 확정).

설계 정본: docs/design/usage-alloc-2026-09-12.md · 표 생성/시드 0086.

`candidates.BUDGET_ALLOC`(코드 상수)은 슬롯별 **상한**만 있고 전 용도 고정이었다.
그래서 팝콘 5 개발 = RTX 3050(13%) + 울트라9(46%) 가 나왔다 — GPU 에 하한이 없어
남는 돈이 CPU 로 갔다. 이 표는 (usage_key, slot) 마다 **하한(pct_min)·상한(pct_max)** 을
둔다. 이 모듈이 하는 일은 하나다: usage_key → {슬롯: (pct_min, pct_max)}.

  · 용도 행이 있는 슬롯은 그것, 없으면 기본(usage_key NULL) 행,
  · 기본 행에도 없는 슬롯은 **BUDGET_ALLOC 상수를 (0, v) 로** — 상수는 DB 를 못 읽을
    때의 폴백이지 정본이 아니다(spec_fields·usage_floors 와 같은 패턴).
  · **용도 문구 해석은 하지 않는다** — usage_key 는 `usage_floors.match` 가 고른 것을
    그대로 받는다(어휘를 두 벌 두지 않는다 · usage_tier_rules 와 같은 규약).

⚠ pct_min 은 후보 필터가 아니라 **완성된 조합의 판정**에 쓴다(설계 문서 ⚠) — 슬롯
후보를 하한으로 거르면 저가 티어에서 후보가 0 이 된다. 상한(pct_max)은 후보 필터.
이 모듈은 값만 준다 — 어디에 쓸지는 recommend.py 가 정한다.

`usage_floors` 와 같은 캐시 방식 — 요청마다 읽지 않고, 관리자가 고치면 `reload()`.
"""
from sqlalchemy import text

from .db import engine
from .taxonomy import SLOT_LABELS as SLOT_KO, slot_of   # 슬롯 한글 이름·part_type→슬롯(단일 원천)

_CACHE: list | None = None

# 응답·문구의 슬롯 순서 — 큰 돈이 가는 자리부터(고객이 먼저 보는 순서). 표에 없는 슬롯은
# 뒤에 SLOTS 순서로 붙는다.
_LEAD = ("GPU", "CPU", "RAM")


def _rows() -> list:
    global _CACHE
    if _CACHE is None:
        try:
            with engine.connect() as conn:
                _CACHE = [dict(r) for r in conn.execute(text(
                    "SELECT alloc_id, usage_key, slot, pct_min, pct_max, note"
                    " FROM usage_alloc WHERE active ORDER BY sort_order, alloc_id")).mappings().all()]
        except Exception as e:      # 표가 아직 없거나 DB를 못 읽으면 상수 폴백(견적이 죽지 않게)
            print(f"[usage_alloc] load failed: {e}")
            _CACHE = []
    return _CACHE


def reload() -> int:
    global _CACHE
    _CACHE = None
    return len(_rows())


def _constant_alloc() -> dict:
    """BUDGET_ALLOC 상수 → {슬롯: (0, v)}. part_type 키(COOLER_CPU_AIR/AIO)를 슬롯으로 접는다
    (둘 다 0.08 이라 max 로 접어도 값이 같다). 지연 import — candidates 가 이 모듈을 부른다."""
    from .candidates import BUDGET_ALLOC
    out: dict = {}
    for pt, v in BUDGET_ALLOC.items():
        s = slot_of(pt)
        out[s] = (0.0, max(v, out[s][1]) if s in out else v)
    return out


def for_usage(usage_key: str | None) -> dict:
    """usage_key → {슬롯: (pct_min, pct_max)} — 항상 전 슬롯을 준다(빈 dict 없음).

    용도 행 > 기본(NULL) 행 > BUDGET_ALLOC(0, v). 표가 비어도(DB 미접속) 상수 폴백으로
    옛 동작(상한만) 그대로다. 값은 float — DB 는 numeric 이라 Decimal 로 온다.
    """
    out = _constant_alloc()
    rows = _rows()
    for r in rows:                                   # 기본 행 먼저
        if r["usage_key"] is None:
            out[r["slot"]] = (float(r["pct_min"]), float(r["pct_max"]))
    if usage_key:
        for r in rows:                               # 용도 행이 덮어쓴다
            if r["usage_key"] == usage_key:
                out[r["slot"]] = (float(r["pct_min"]), float(r["pct_max"]))
    return out


def has_rows() -> bool:
    """표를 실제로 읽었는가 — False 면 for_usage 는 상수 폴백만 준다(하한 0)."""
    return bool(_rows())


def pct_max_of(alloc: dict, part_type: str, x: float = 1.0) -> float:
    """후보 필터용 — part_type 의 상한 배율(×x). 표·상수 어디에도 없으면 1.0(제한 없음)."""
    mm = alloc.get(slot_of(part_type))
    return min(1.0, mm[1] * x) if mm else 1.0


def violations(alloc: dict, chosen: dict, total: int) -> list:
    """완성된 조합의 하한 판정 — 슬롯가/총액 < pct_min 인 슬롯 목록(비어 있으면 통과).
    chosen = {슬롯: 부품 dict}. total 은 호출자가 잰 값(쿨러 포함 원 총액)."""
    if not total:
        return []
    return [s for s, p in chosen.items()
            if (mm := alloc.get(s)) and p["sale_price"] / total < mm[0]]


def _ordered_slots(alloc: dict, chosen: dict) -> list:
    from .taxonomy import SLOTS
    return [s for s in _LEAD if s in chosen and s in alloc] + \
           [s for s in SLOTS if s not in _LEAD and s in chosen and s in alloc]


def items(usage_key: str | None, chosen: dict, total: int) -> list:
    """응답용 — [{slot, pct_min, pct_max, actual_pct}] (표에 행이 있는 슬롯만 = GPU·CPU·RAM 급).
    actual_pct 는 실제 비율(소수 셋째 자리) — 화면이 다시 계산하지 않는다."""
    alloc = for_usage(usage_key)
    rows = _rows()
    tabled = {r["slot"] for r in rows if r["usage_key"] in (None, usage_key)}
    out = []
    for s in _ordered_slots(alloc, chosen):
        if s not in tabled:
            continue
        mn, mx = alloc[s]
        out.append({"slot": s, "pct_min": mn, "pct_max": mx,
                    "actual_pct": round(chosen[s]["sale_price"] / total, 3) if total else None})
    return out


def summary(usage_key: str | None, chosen: dict, total: int) -> str | None:
    """근거 한 줄 — **실제 비율을 적는다**(숫자가 있어야 근거다 · 슬라이스 58 규약).
    예: "예산 배분 — 그래픽카드 42%(시장 32~48%) · CPU 15%(8~20%) · 메모리 9%(5~25%)"
    표를 못 읽었으면(상수 폴백) None — 시장 범위가 없는 것을 있다고 말하지 않는다."""
    if not has_rows() or not total:
        return None
    its = items(usage_key, chosen, total)
    if not its:
        return None
    parts = [f"{SLOT_KO.get(i['slot'], i['slot'])} {round(i['actual_pct'] * 100)}%"
             f"(시장 {round(i['pct_min'] * 100)}~{round(i['pct_max'] * 100)}%)" for i in its]
    return "예산 배분 — " + " · ".join(parts)
