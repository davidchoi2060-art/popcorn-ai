"""용도×예산 티어 겨냥 규칙 로더 — `usage_tier_rules` 테이블이 단일 원천(2026-09-12).

설계 정본: docs/design/usage-tier-rules-2026-09-12.md · 표 생성/시드 0085.

`usage_floors`(슬라이스 58)는 **용도당 하나의 하한** — 예산이 얼마든 같은 최저선이다.
이 표는 그 위에서 "이 예산 티어에선 이 급을 겨냥한다"를 말한다(팝콘 X AI 는 VRAM 32GB ·
RAM 64GB · CPU 24코어 — 시장 표본의 다수값). 하한과 달리 **조립 조건이 아니라 목표**라서
걸러서 조합이 안 나오면 부르는 쪽이 이 규칙만 풀고(usage_floors 는 유지) 근거에 남긴다.

여기서 하는 일은 하나다: (usage_key, cap) → 슬롯별 규칙 목록. 필터링은 부르는 쪽이
`usage_floors.passes` 와 같은 술어로 한다(NULL 원칙 동일 — 값을 모르면 불통과).
**용도 문구 해석은 하지 않는다** — usage_key 는 `usage_floors.match` 가 고른 것을 그대로
받는다(어휘를 두 벌 두지 않는다).

`usage_floors` 와 같은 캐시 방식이다 — 요청마다 읽지 않고, 관리자가 고치면 `reload()`.
"""
from sqlalchemy import text

from .db import engine
from .taxonomy import SLOT_LABELS as SLOT_KO   # 슬롯 한글 이름의 단일 원천(슬라이스 A)

_CACHE: list | None = None


def _rows() -> list:
    global _CACHE
    if _CACHE is None:
        try:
            with engine.connect() as conn:
                _CACHE = [dict(r) for r in conn.execute(text(
                    "SELECT rule_id, usage_key, budget_min, slot, field, op, value, label,"
                    " note FROM usage_tier_rules WHERE active"
                    " ORDER BY sort_order, rule_id")).mappings().all()]
        except Exception as e:      # 표가 아직 없거나 DB를 못 읽으면 규칙 없이 동작(견적이 죽지 않게)
            print(f"[usage_tier_rules] load failed: {e}")
            _CACHE = []
    return _CACHE


def reload() -> int:
    global _CACHE
    _CACHE = None
    return len(_rows())


def for_usage(usage_key: str | None, cap: int | None) -> dict:
    """(usage_key, 예산 상한) → {슬롯: [(필드, 연산, 값, 라벨), ...]}.

    budget_min < cap 인 행 중 **(usage_key, slot, field) 별로 budget_min 이 가장 큰 하나**
    만 쓴다(설계 문서 §적용 방식). cap 이 None 이면 규칙 없음 — 상한 없는 예산('200만원
    이상'·'AI 추천 예산')에는 어느 티어를 겨냥할지 정할 근거가 없다(지어내지 않는다).

    ⚠ 부등호는 «미만»이다(2026-09-12 첫 배치 실사고). 격자 티어는 [min, max) 반열림이라
    「800만원」 예산은 팝콘 9(550~800)의 상한이지 팝콘 X(800~)의 구간이 아니다. `<=` 로
    두면 800만 cap 에 팝콘 X 규칙(5090·64GB)이 걸리고, 그 조합이 800만에 안 들어가
    규칙 전체가 해제돼 팝콘 9 12칸이 용도 무관 같은 구성으로 돌아갔다.
    """
    if not usage_key or cap is None:
        return {}
    best: dict = {}                       # (slot, field, op) -> row
    for r in _rows():
        if r["usage_key"] != usage_key or r["budget_min"] >= cap:
            continue
        # op 까지 키에 넣는다(2026-09-13) — 같은 필드에 gte(하한)와 lte(상한)를 함께 둘 수 있어야
        # 「X 티어 개발·영상·디자인은 RAM 64GB 까지」(사장님 확정 「정직하게」 — 128GB 로 예산을
        # 채우지 않는다)가 표현된다. (slot, field) 만으로 키를 잡으면 둘 중 하나가 묻힌다.
        k = (r["slot"], r["field"], r["op"])
        if k not in best or r["budget_min"] > best[k]["budget_min"]:
            best[k] = r
    out: dict = {}
    for (slot, field, _op), r in best.items():
        out.setdefault(slot, []).append((field, r["op"], r["value"], r["label"]))
    return out


def passes(part: dict, rules: list) -> bool:
    """부품 하나가 그 슬롯의 겨냥 규칙을 전부 만족하는가 — `usage_floors.passes` 와 같은
    술어(NULL 불통과). 튜플 길이만 다르다(detail_fmt 없음)."""
    for field, op, val, _label in rules:
        v = part.get(field)
        if v is None:
            return False
        if op == "gte" and not v >= val:
            return False
        if op == "lte" and not v <= val:
            return False
        if op == "eq" and not v == val:
            return False
    return True


def items(rules: dict) -> list:
    """응답용 목록 — 서버가 실제로 건 규칙만 말한다(슬롯 순서는 for_usage 가 준 그대로)."""
    return [{"slot": s, "field": f, "op": o, "value": v, "label": lb}
            for s, rs in rules.items() for (f, o, v, lb) in rs]


# ── 근거 한 줄 문구 — **숫자가 있어야 근거다**(슬라이스 58 규약과 같다) ──────────
_UNIT = {"vram_gb": "GB", "capacity_gb": "GB", "cpu_cores": "코어"}
_FIELD_KO = {"vram_gb": "VRAM ", "capacity_gb": "", "cpu_cores": ""}


def summary(rules: dict) -> str | None:
    """{슬롯: 규칙들} → "시장 표준 — 그래픽카드 VRAM 32GB 이상 · 메모리 64GB 이상 · CPU 24코어 이상"."""
    if not rules:
        return None
    parts = []
    for slot, rs in rules.items():
        for field, op, val, _label in rs:
            word = {"gte": "이상", "lte": "이하", "eq": ""}.get(op, "")
            parts.append(f"{SLOT_KO.get(slot, slot)} {_FIELD_KO.get(field, field + ' ')}"
                         f"{val:,}{_UNIT.get(field, '')} {word}".strip())
    return "시장 표준 — " + " · ".join(parts)
