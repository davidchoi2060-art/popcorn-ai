"""용도별 부품 하한 로더 — `usage_floors` 테이블이 단일 원천(슬라이스 58).

화면은 오래전부터 용도 칩에 "저사양 GPU 제외(프레임 미달)" · "램 32GB↑ 우선"이라고
적어 왔는데 **서버는 용도로 아무것도 하지 않았다.** 그래서 "롤·배그 하려고요"에
GT710 2GB가 나왔다 — 저소음 + 최저가를 정확히 만족한 결과다.

여기서 하는 일은 하나다: 용도 문구 → 하한 규칙 목록. 필터링은 부르는 쪽이 한다
(후보 카운터와 견적 엔진이 같은 규칙을 써야 화면과 결과가 어긋나지 않는다).

`spec_fields`와 같은 캐시 방식이다 — 요청마다 읽지 않고, 관리자가 고치면 `reload()`.
"""
from fastapi import APIRouter
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
                    "SELECT usage_key, usage_label, match_terms, slot, field, op, value,"
                    " label, detail_fmt FROM usage_floors WHERE active"
                    " ORDER BY sort_order, floor_id")).mappings().all()]
        except Exception as e:      # DB를 못 읽으면 하한 없이 동작한다(견적이 죽지 않게)
            print(f"[usage_floors] load failed: {e}")
            _CACHE = []
    return _CACHE


def reload() -> int:
    global _CACHE
    _CACHE = None
    return len(_rows())


def match(value: str) -> list:
    """용도 문구 → 적용할 하한 규칙들. **먼저 맞는 usage_key 하나만** 쓴다.

    '고사양 게임'은 '게임'도 포함하므로 둘 다 적용하면 하한이 뒤섞인다.
    시드가 좁은 것(고사양 게임)부터 정렬돼 있어 앞선 것이 이긴다.
    """
    if not value:
        return []
    rows = _rows()
    hit = next((r["usage_key"] for r in rows
                if any(t in value for t in (r["match_terms"] or []))), None)
    return [r for r in rows if r["usage_key"] == hit] if hit else []


def slot_floors(value: str) -> dict:
    """용도 문구 → {슬롯: [(필드, 연산, 값, 라벨, 상세형식), ...]}"""
    out: dict = {}
    for r in match(value):
        out.setdefault(r["slot"], []).append(
            (r["field"], r["op"], r["value"], r["label"], r["detail_fmt"]))
    return out


def passes(part: dict, floors: list) -> bool:
    """부품 하나가 그 슬롯의 하한을 전부 만족하는가.

    **값을 모르면 불통과**다(호환 규칙의 NULL 원칙과 같다) — 용량을 모르는 SSD를
    '게임에 충분하다'고 말할 수는 없다.
    """
    for field, op, val, _label, _fmt in floors:
        v = part.get(field)
        if v is None:
            return False
        if op == "gte" and not v >= val:
            return False
        if op == "lte" and not v <= val:
            return False
    return True


def label_of(value: str) -> str | None:
    rows = match(value)
    return rows[0]["usage_label"] if rows else None


def summary(value: str) -> list:
    """화면·근거용 한 줄 목록 — 서버가 실제로 건 하한만 말한다."""
    return [{"slot": r["slot"], "label": r["label"], "field": r["field"],
             "op": r["op"], "value": r["value"]} for r in match(value)]


# ── 근거 한 줄 문구 ────────────────────────────────────────────────────────
# "고사양 게임 GPU 등급"만으로는 무엇을 걸렀는지 알 수 없다 — **얼마 이상인지가
# 근거다**(슬라이스 58). 같은 조립이 `candidates._apply_one`(118-120행)과
# `recommend.py`(652-654행)에도 인라인으로 있다. 정본은 여기이고 저 둘은 각자
# 담당자가 이 함수를 부르도록 정리할 자리다 — 지금 고치면 담당 밖이라 남겨 둔다.
_UNIT = {"required_power_watt": "W", "capacity_gb": "GB"}


def floor_text(rows: list) -> str:
    """하한 규칙 행들 -> "그래픽카드 550W 이상 · 메모리 16GB 이상" 한 줄."""
    return " · ".join(f"{SLOT_KO.get(r['slot'], r['slot'])} {r['value']:,}"
                      f"{_UNIT.get(r['field'], '')} 이상" for r in rows)


router = APIRouter(prefix="/api", tags=["usages"])


@router.get("/usages")
def list_usages():
    """지금 서버가 하한을 갖고 있는 **용도 목록** — 읽기 전용·인증 없음.

    ■ 왜 있는가 (2026-08-17)
      S1 화면이 용도 어휘를 **자기 안에** 세 벌 들고 있었다(`USE_PAT` · guided
      `Q_USE` · 팝콘톡 `TALKS`). 그래서
        · 화면에만 있는 용도(인터넷·시청 / 주식·트레이딩 / 영화·미디어)가
          선택지로 떴는데 DB에 없어 `applied:false` — **후보 수가 그대로인데
          화면은 「저사양 GPU 제외」 같은 이유를 보여줬다**(§화면 정직성 위반).
        · DB에만 있는 용도(방송·스트리밍 / 디자인 / 개발)는 **진입로가 없었다.**
        · 같은 말이 입구마다 다른 용도로 잡혔다(「배그」= 고사양 게임 / 게임).
      화면이 목록을 갖는 한 표가 바뀌는 날 반드시 갈라진다. 그래서 **받아 쓰게** 한다.

    ■ 순서가 곧 우선순위다
      `_rows()`는 `sort_order, floor_id` 순이고 `match()`가 **먼저 맞는 하나만**
      쓴다('고사양 게임'이 '게임'보다 앞이라 이긴다). 이 응답의 배열 순서가 그
      우선순위 그대로다 — 화면이 같은 규칙으로 고르려면 **순서를 바꾸지 않아야** 한다.

    ■ 화면이 못 받으면
      빈 목록이 아니라 **요청 실패**로 돌아간다(DB를 못 읽으면 `_rows()`가 []를
      주므로 `usages`가 빈 배열일 수도 있다). 어느 쪽이든 화면은 **용도 선택지를
      내지 않는다** — 임의 어휘를 폴백으로 박으면 목록이 다시 갈라진다.

    응답 {ok, usages:[{key, label, terms[], floor_note}]}
      terms      `match_terms` 원본 — 부분일치 대상
      floor_note 서버가 실제로 거는 하한 한 줄(숫자 포함). 화면의 「이유」 자리는
                 이 값을 그대로 쓴다 — 화면이 이유를 지어내지 않는다.
    """
    out: list = []
    idx: dict = {}
    for r in _rows():
        k = r["usage_key"]
        if k not in idx:
            idx[k] = len(out)
            out.append({"key": k, "label": r["usage_label"],
                        "terms": list(r["match_terms"] or []), "_r": []})
        out[idx[k]]["_r"].append(r)
    for u in out:
        u["floor_note"] = floor_text(u.pop("_r"))
    return {"ok": True, "usages": out}
