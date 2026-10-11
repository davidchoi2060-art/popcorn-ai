"""상담 해석 바로잡기 — 관리자 데이터 API (2026-10-11 품질관리 · 개편 14번 · R8 나머지).

■ 왜 있는가
  「롤 120」을 120Hz 로, 「100만원대」를 상한 100만원으로 읽은 것은 코드로 고쳤다(#88).
  그다음에 잘못 읽힌 표현은 다시 개발이 필요했다. 관리자가 «표현 → 바로잡을 값»을
  등록하면 고객 상담이 AI 가 읽은 값 대신 이 값을 쓴다(`api/talk_text_fixes`).

■ 규칙
  ① 종류는 둘이다: «예산»(금액 · 이하/이상/없음) · «해상도»(1080p · 1440p · 4K).
  ② 표현은 글자 그대로 비교한다(공백·대소문자 무시, 2~30자). 같은 표현은 한 줄만 둔다.
  ③ 등록·수정은 대표 권한(owner)만 한다. 새 규칙은 «미사용»으로 저장해 «시험»으로
     확인한 뒤 «사용»으로 올릴 수 있다.
  ④ 행을 지우지 않는다 — «미사용»으로 내린다.
  ⑤ 시험(`POST .../try`)은 저장된 «사용» 규칙과 입력 중인 규칙으로 문장을 읽어 볼 뿐
     아무것도 쓰지 않는다. AI 는 부르지 않는다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sqlalchemy import text

from . import talk_text_fixes as TF
from .auth import current_operator
from .db import engine
from .talk_schema import BUDGET_BOUND_VALUES, RESOLUTION_VALUES
from .timeutil import iso

router = APIRouter(prefix="/api/admin", tags=["admin-talk-text-fixes"])

STATUSES = ("사용", "미사용")
MEMO_MAX = 200
BUDGET_MIN, BUDGET_MAX = 100_000, 50_000_000


def _owner():
    me = current_operator() or {}
    if me.get("role") != "owner":
        raise HTTPException(403, "대표 권한만 바꿀 수 있습니다")
    return me


class FixBody(BaseModel):
    phrase: str
    kind: str
    budget_man: int | None = None        # 만원 단위로 받는다(화면 입력이 만원이다)
    budget_bound: str | None = None
    resolution: str | None = None
    memo: str | None = None
    status: str = "미사용"


def _clean(p: FixBody) -> dict:
    phrase = (p.phrase or "").strip()
    pn = TF.norm(phrase)
    if len(pn) < TF.PHRASE_MIN or len(phrase) > TF.PHRASE_MAX:
        raise HTTPException(400, "표현은 %d~%d자로 적어야 합니다" % (TF.PHRASE_MIN, TF.PHRASE_MAX))
    if p.kind not in TF.KINDS:
        raise HTTPException(400, "종류는 «예산» 또는 «해상도»입니다")
    if p.status not in STATUSES:
        raise HTTPException(400, "상태는 «사용» 또는 «미사용»입니다")
    memo = (p.memo or "").strip() or None
    if memo and len(memo) > MEMO_MAX:
        raise HTTPException(400, "메모는 %d자까지 적을 수 있습니다" % MEMO_MAX)
    out = {"phrase": phrase, "phrase_norm": pn, "kind": p.kind, "budget_won": None,
           "budget_bound": None, "resolution": None, "memo": memo, "status": p.status}
    if p.kind == "예산":
        won = (p.budget_man or 0) * 10_000
        if not BUDGET_MIN <= won <= BUDGET_MAX:
            raise HTTPException(400, "예산은 %d~%d만원으로 적어야 합니다" % (BUDGET_MIN // 10_000, BUDGET_MAX // 10_000))
        if p.budget_bound not in (None, "") + BUDGET_BOUND_VALUES:
            raise HTTPException(400, "예산 경계는 «이하» · «이상» · 없음 중 하나입니다")
        out["budget_won"], out["budget_bound"] = won, (p.budget_bound or None)
    else:
        if p.resolution not in RESOLUTION_VALUES:
            raise HTTPException(400, "해상도는 %s 중 하나입니다" % " · ".join(RESOLUTION_VALUES))
        out["resolution"] = p.resolution
    return out


def _row(r) -> dict:
    return {"fix_id": r["fix_id"], "phrase": r["phrase"], "kind": r["kind"],
            "budget_man": r["budget_won"] // 10_000 if r["budget_won"] else None,
            "budget_bound": r["budget_bound"], "resolution": r["resolution"],
            "memo": r["memo"], "status": r["status"], "updated_at": iso(r["updated_at"])}


@router.get("/talk-text-fixes")
def list_fixes():
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT fix_id, phrase, kind, budget_won, budget_bound, resolution, memo, status, updated_at"
                " FROM talk_text_fixes ORDER BY fix_id")).mappings().all()
    except Exception:                                         # noqa: BLE001
        raise HTTPException(503, "해석 바로잡기 표가 아직 없습니다(마이그레이션 0151 전)")
    return {"ok": True, "items": [_row(r) for r in rows], "kinds": list(TF.KINDS),
            "bounds": list(BUDGET_BOUND_VALUES), "resolutions": list(RESOLUTION_VALUES),
            "phrase_rule": {"min": TF.PHRASE_MIN, "max": TF.PHRASE_MAX}}


def _saved(status: str) -> str:
    return ("저장했습니다. 다음 문의부터 이 표현을 이 값으로 읽습니다." if status == "사용"
            else "저장했습니다. «미사용»이라 상담에는 쓰이지 않습니다.")


_UPSERT_COLS = "phrase, phrase_norm, kind, budget_won, budget_bound, resolution, memo, status"


@router.post("/talk-text-fixes")
def add_fix(payload: FixBody):
    me = _owner()
    v = _clean(payload)
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM talk_text_fixes WHERE phrase_norm = :n"),
                        {"n": v["phrase_norm"]}).first():
            raise HTTPException(409, "같은 표현이 이미 있습니다")
        fid = conn.execute(text(
            f"INSERT INTO talk_text_fixes ({_UPSERT_COLS}, created_by, updated_by)"
            " VALUES (:phrase, :phrase_norm, :kind, :budget_won, :budget_bound, :resolution, :memo,"
            " :status, :who, :who) RETURNING fix_id"), dict(v, who=me.get("operator_id"))).scalar_one()
    return {"ok": True, "fix_id": fid, "status": v["status"], "note": _saved(v["status"])}


@router.put("/talk-text-fixes/{fix_id}")
def save_fix(fix_id: int, payload: FixBody):
    me = _owner()
    v = _clean(payload)
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM talk_text_fixes WHERE phrase_norm = :n AND fix_id <> :id"),
                        {"n": v["phrase_norm"], "id": fix_id}).first():
            raise HTTPException(409, "같은 표현이 이미 있습니다")
        n = conn.execute(text("""
            UPDATE talk_text_fixes
               SET phrase = :phrase, phrase_norm = :phrase_norm, kind = :kind, budget_won = :budget_won,
                   budget_bound = :budget_bound, resolution = :resolution, memo = :memo, status = :status,
                   updated_by = :who, updated_at = now()
             WHERE fix_id = :id"""), dict(v, who=me.get("operator_id"), id=fix_id)).rowcount
    if not n:
        raise HTTPException(404, "없는 규칙입니다")
    return {"ok": True, "fix_id": fix_id, "status": v["status"], "note": _saved(v["status"])}


class TryBody(BaseModel):
    sentence: str
    draft: FixBody | None = None


@router.post("/talk-text-fixes/try")
def try_sentence(body: TryBody):
    """문장 하나를 «사용» 규칙(+ 입력 중인 규칙)으로 읽어 본다. 쓰지 않는다."""
    sentence = (body.sentence or "").strip()
    if not sentence or len(sentence) > 300:
        raise HTTPException(400, "시험 문장은 1~300자로 적어야 합니다")
    rules = []
    if body.draft is not None:
        rules.append(_clean(body.draft.model_copy(update={"status": "사용"})))
    with engine.connect() as conn:
        rules += TF.load(conn)
    rules.sort(key=lambda r: -len(r["phrase_norm"]))
    raw: dict = {}
    fixes = TF.apply(sentence, raw, rules)
    game = raw.get("game") or {}
    return {"ok": True, "applied": [f["reason"] for f in fixes],
            "budget_won": raw.get("budget_won"), "budget_bound": raw.get("budget_bound"),
            "resolution": game.get("resolution"),
            "note": "맞는 규칙이 없습니다." if not fixes else "이 문장은 위 규칙대로 읽힙니다."}
