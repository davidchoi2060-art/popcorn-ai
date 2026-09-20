"""조건부 부품 규칙 로더 — `part_cond_rules` 표가 단일 원천(0101 · 2026-09-18).

설계 정본: docs/design/usage-rules-rebuild-2026-09-18.md

■ 왜 표가 셋이 되었는가 — 세 표는 «축»이 다르다
      usage_floors      (용도)              고정 하한. 예산이 얼마든 같다.
      usage_tier_rules  (용도, 예산)        겨냥. 못 맞추면 풀고 짓는다.
      part_cond_rules   (이미 고른 부품)    ← 이 표. 다른 슬롯의 선택에 달렸다.

  `usage_floors.passes` 와 `usage_tier_rules.passes` 는 둘 다 **부품 하나**를
  **자기 슬롯의 규칙**과 비교한다. 그래서 「VRAM 8GB 그래픽카드를 골랐으면 RAM 을
  32GB 로」처럼 **슬롯을 건너뛰는** 조건은 어느 쪽으로도 쓸 수 없다 — 규칙에
  "어떤 GPU 를 골랐는지"가 들어올 자리가 없기 때문이다. 표를 새로 만든 이유다
  (P-08 스키마 신설이 정규 경로인 자리).

■ 값의 근거 (지어내지 않았다)
  TechSpot 2026-01 전수 확인(검은신화 오공 · 킹덤컴 딜리버런스2 · 사이버펑크2077 ·
  배틀필드6): **최신 게임 대부분 시스템 램 16GB 로 충분**하다. 32GB 가 필요해지는
  결정적 조건은 **VRAM 8GB 그래픽카드를 쓸 때**다 — 8GB 초과분이 시스템 램으로
  넘어가 페이지파일 스왑이 일어나고 프레임타임이 무너진다. 32GB 로 1% low 60% 개선.
  즉 이것은 **게임별 값이 아니라 GPU 선택에 달린 조건**이라 `games` 에도 자리가 없다.

■ 적용 방식 (엔진이 쓰는 법) — `apply()` 한 함수
  견적이 GPU 를 정한 «뒤», RAM 후보를 고르기 «전»에 부른다:

      extra = PCR.apply({"GPU": gpu_row}, usage_key)     # -> {"RAM": [(field, op, value, label)]}

  돌아온 것은 `usage_floors.slot_floors()` 와 **같은 모양의 추가 하한**이라, 부르는
  쪽은 기존 `passes()` 를 그대로 쓰면 된다 — 판정 술어를 새로 만들지 않는다.

■ ⚠ 하한인가 겨냥인가 — **겨냥이다**(usage_tier_rules 쪽 성격)
  8GB 카드 + 16GB 램도 «돌아간다». 프레임타임이 나쁠 뿐이다. 그래서 예산이 모자라
  32GB 를 못 넣으면 **규칙을 풀고 짓되 근거에 그 사실을 남긴다** — 조합이 아예
  안 나오는 것보다 낫다. 하한(usage_floors)처럼 절대 못 푸는 것이 아니다.

`usage_floors` 와 같은 캐시 방식이다 — 요청마다 읽지 않고, 관리자가 고치면 `reload()`.
"""
from sqlalchemy import text

from .db import engine

_CACHE: list | None = None


def _num(v):
    """VARCHAR 컬럼에서 온 값을 숫자로 — 캐스팅은 **여기서 한 번만** 한다.

    `usage_tier_rules` 가 value 를 INTEGER 로 만들었다가 op='in'(칩셋 집합) 때문에
    뒤늦게 넓히고 로더에 캐스팅을 덧대야 했다(api/usage_tier_rules.py 45행). 같은
    길을 걷지 않으려고 이 표는 처음부터 VARCHAR 이고, 소비처는 "숫자 op 면 값은
    숫자"라는 계약만 믿으면 된다.
    """
    if isinstance(v, (int, float)):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        return v            # 'in' 같은 비숫자 op 의 값 — 그대로 넘긴다


def _rows() -> list:
    global _CACHE
    if _CACHE is None:
        try:
            with engine.connect() as conn:
                _CACHE = [dict(r) for r in conn.execute(text(
                    "SELECT cond_id, usage_key, when_slot, when_field, when_op,"
                    " when_value, then_slot, then_field, then_op, then_value, label,"
                    " note FROM part_cond_rules WHERE active"
                    " ORDER BY sort_order, cond_id")).mappings().all()]
        except Exception as e:  # 표가 없거나 DB 를 못 읽으면 규칙 없이 동작(견적이 죽지 않게)
            print(f"[part_cond_rules] load failed: {e}")
            _CACHE = []
    return _CACHE


def reload() -> int:
    global _CACHE
    _CACHE = None
    return len(_rows())


def _holds(part: dict, field: str, op: str, value) -> bool:
    """조건절 판정 — `usage_floors.passes` 와 같은 술어(값을 모르면 «불성립»).

    ⚠ NULL 원칙의 방향이 하한과 «반대로 작동»한다는 점이 중요하다. 하한에서
    값을 모르면 «불통과»(보수적으로 거른다)인데, 여기서는 값을 모르면 조건이
    **성립하지 않아** 추가 규칙이 안 걸린다. 둘 다 같은 뜻이다 — **모르는 것을
    근거로 삼지 않는다.** VRAM 을 모르는 GPU 를 두고 "8GB 카드다"라고 말할 수 없다.
    """
    v = part.get(field)
    if v is None:
        return False
    if op == "lte":
        return v <= value
    if op == "gte":
        return v >= value
    if op == "eq":
        return v == value
    if op == "in":
        return str(v) in {s.strip() for s in str(value).split(",")}
    return False


def apply(chosen: dict, usage_key: str | None = None) -> dict:
    """이미 고른 부품들 → 추가로 걸어야 할 규칙 {슬롯: [(필드, 연산, 값, 라벨), ...]}.

    chosen     {슬롯: 부품dict} — 지금까지 확정한 것. 없는 슬롯은 그냥 건너뛴다.
    usage_key  용도 한정 규칙만 가려 쓰기 위한 키. 표의 `usage_key` 가 NULL 인 행은
               **모든 용도에 적용**된다(VRAM 8GB 규칙이 그렇다 — 게임만의 문제가
               아니라 VRAM 을 넘기는 모든 작업에서 같은 스왑이 일어난다).

    같은 (슬롯, 필드) 에 여러 규칙이 맞으면 **가장 엄격한 것**을 남긴다(gte 는 최대값,
    lte 는 최소값) — 조건 두 개가 32GB·64GB 를 말하면 64GB 가 이긴다.
    """
    best: dict = {}
    for r in _rows():
        if r["usage_key"] and r["usage_key"] != usage_key:
            continue
        src = chosen.get(r["when_slot"])
        if not src:
            continue
        if not _holds(src, r["when_field"], r["when_op"], _num(r["when_value"])):
            continue
        k = (r["then_slot"], r["then_field"], r["then_op"])
        val = _num(r["then_value"])
        cur = best.get(k)
        if cur is None:
            best[k] = (val, r["label"])
        elif r["then_op"] == "gte" and val > cur[0]:
            best[k] = (val, r["label"])
        elif r["then_op"] == "lte" and val < cur[0]:
            best[k] = (val, r["label"])
    out: dict = {}
    for (slot, field, op), (val, label) in best.items():
        out.setdefault(slot, []).append((field, op, val, label))
    return out


def items(rules: dict) -> list:
    """응답용 목록 — 서버가 실제로 건 조건부 규칙만 말한다."""
    return [{"slot": s, "field": f, "op": o, "value": v, "label": lb}
            for s, rs in rules.items() for (f, o, v, lb) in rs]


def summary(rules: dict) -> str | None:
    """{슬롯: 규칙들} → 근거 한 줄. **라벨에 숫자가 이미 들어 있다**(§근거 규약)."""
    if not rules:
        return None
    return "선택한 부품 조건 — " + " · ".join(
        lb for rs in rules.values() for (_f, _o, _v, lb) in rs)
