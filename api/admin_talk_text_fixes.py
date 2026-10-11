"""상담 해석 바로잡기 — 관리자 데이터 API (2026-10-11 품질관리 · 개편 14번 · R8 나머지).

■ 왜 있는가
  「롤 120」을 120Hz 로, 「100만원대」를 상한 100만원으로 읽은 것은 코드로 고쳤다(#88).
  그다음에 잘못 읽힌 표현은 다시 개발이 필요했다. 관리자가 «표현 → 바로잡을 값»을
  등록하면 고객 상담이 AI 가 읽은 값 대신 이 값을 쓴다(`api/talk_text_fixes`).

■ 규칙
  ① 종류는 둘이다: «예산»(금액 · 이하/이상/없음) · «해상도»(1080p · 1440p · 4K).
  ② 표현은 글자 그대로 비교한다(공백·대소문자 무시, 2~30자). 같은 표현은 한 줄만 둔다.
  ③ 등록·수정은 대표 권한(owner)만 한다. 새 규칙은 «미사용»으로만 저장한다. 저장한 규칙을
     «시험»해서 그 규칙이 문장에 맞아야 «사용»으로 올릴 수 있다 — 서버가 지킨다(0154,
     코덱스 검수 #111). 이미 «사용»인 규칙은 값을 바꾸지 않으면 그대로 저장된다.
  ④ 행을 지우지 않는다 — «미사용»으로 내린다.
  ⑤ 시험(`POST .../try`)은 저장된 «사용» 규칙과 입력 중인 규칙(또는 `fix_id` 로 고른 저장된
     규칙)으로 문장을 읽어 본다. 규칙은 바꾸지 않는다. `fix_id` 규칙이 맞으면 그 값의 지문만
     남긴다(`tested_sig`). AI 는 부르지 않는다.
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


def sig(v) -> str:
    """시험한 값의 지문 — 이 값이 바뀌면 다시 시험해야 한다. 메모는 읽기에 쓰이지 않아 뺀다."""
    return "|".join(str(v.get(k) if v.get(k) is not None else "")
                    for k in ("phrase_norm", "kind", "budget_won", "budget_bound", "resolution"))


NOT_TESTED = "이 값으로 시험한 뒤 «사용»으로 올릴 수 있습니다. «미사용»으로 저장하고 시험해 주세요."


def _row(r) -> dict:
    return {"fix_id": r["fix_id"], "phrase": r["phrase"], "kind": r["kind"],
            "budget_man": r["budget_won"] // 10_000 if r["budget_won"] else None,
            "budget_bound": r["budget_bound"], "resolution": r["resolution"],
            "memo": r["memo"], "status": r["status"], "updated_at": iso(r["updated_at"]),
            "tested": r["tested_sig"] is not None and r["tested_sig"] == sig(r)}


@router.get("/talk-text-fixes")
def list_fixes():
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT fix_id, phrase, phrase_norm, kind, budget_won, budget_bound, resolution, memo, status,"
                " tested_sig, updated_at"
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
    if v["status"] == "사용":
        raise HTTPException(409, "새 규칙은 «미사용»으로 저장합니다. 저장한 뒤 시험해서 «사용»으로 올려 주세요.")
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
        cur = conn.execute(text(
            "SELECT phrase_norm, kind, budget_won, budget_bound, resolution, status, tested_sig"
            " FROM talk_text_fixes WHERE fix_id = :id FOR UPDATE"), {"id": fix_id}).mappings().first()
        if cur is None:
            raise HTTPException(404, "없는 규칙입니다")
        # «사용»으로 저장하려면: 이미 «사용»이고 값이 그대로이거나, 지금 값으로 시험해 맞았어야 한다.
        if v["status"] == "사용" and not (
                (cur["status"] == "사용" and sig(cur) == sig(v)) or cur["tested_sig"] == sig(v)):
            raise HTTPException(409, NOT_TESTED)
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
    fix_id: int | None = None            # 저장된 규칙 하나를 시험한다(상태와 관계없이)


@router.post("/talk-text-fixes/try")
def try_sentence(body: TryBody):
    """문장 하나를 «사용» 규칙(+ 입력 중인 규칙 또는 `fix_id` 규칙)으로 읽어 본다.

    규칙은 바꾸지 않는다. `fix_id` 규칙이 이 문장에 맞아 실제로 쓰였으면 그 값의 지문을 남긴다 —
    «사용»으로 올릴 수 있는 근거다(코덱스 검수 #111). 지문을 남기는 것은 대표 권한만 한다.
    """
    sentence = (body.sentence or "").strip()
    if not sentence or len(sentence) > 300:
        raise HTTPException(400, "시험 문장은 1~300자로 적어야 합니다")
    rules = []
    if body.draft is not None:
        rules.append(_clean(body.draft.model_copy(update={"status": "사용"})))
    picked = None
    me = _owner() if body.fix_id is not None else None
    with engine.connect() as conn:
        if body.fix_id is not None:
            picked = conn.execute(text(
                "SELECT fix_id, phrase, phrase_norm, kind, budget_won, budget_bound, resolution"
                " FROM talk_text_fixes WHERE fix_id = :id"), {"id": body.fix_id}).mappings().first()
            if picked is None:
                raise HTTPException(404, "없는 규칙입니다")
            picked = dict(picked)
            rules.append(picked)
        rules += [r for r in TF.load(conn) if picked is None or r["fix_id"] != picked["fix_id"]]
    rules.sort(key=lambda r: -len(r["phrase_norm"]))
    raw: dict = {}
    fixes = TF.apply(sentence, raw, rules)
    game = raw.get("game") or {}
    out = {"ok": True, "applied": [f["reason"] for f in fixes],
           "budget_won": raw.get("budget_won"), "budget_bound": raw.get("budget_bound"),
           "resolution": game.get("resolution"),
           "note": "맞는 규칙이 없습니다." if not fixes else "이 문장은 위 규칙대로 읽힙니다."}
    if picked is not None:
        out["tested"] = _used(sentence, rules, picked)
        if out["tested"]:
            with engine.begin() as conn:
                conn.execute(text(
                    "UPDATE talk_text_fixes SET tested_sig = :s, tested_at = now(), tested_by = :who"
                    " WHERE fix_id = :id AND phrase_norm = :n AND kind = :k"
                    " AND budget_won IS NOT DISTINCT FROM :b AND budget_bound IS NOT DISTINCT FROM :bb"
                    " AND resolution IS NOT DISTINCT FROM :r"),
                    {"s": sig(picked), "who": me.get("operator_id"), "id": picked["fix_id"],
                     "n": picked["phrase_norm"], "k": picked["kind"], "b": picked["budget_won"],
                     "bb": picked["budget_bound"], "r": picked["resolution"]})
            out["note"] = "이 규칙이 문장에 맞았습니다. 이 값으로 «사용»으로 올릴 수 있습니다."
        else:
            out["note"] = "이 규칙이 문장에 쓰이지 않았습니다. 표현이 든 문장으로 다시 시험해 주세요."
    return out


def _used(sentence: str, rules: list, rule: dict) -> bool:
    """`TF.apply` 와 같은 순서(긴 표현 먼저, 종류마다 처음 맞는 하나)로 이 규칙이 쓰였나."""
    t = TF.norm(sentence)
    for r in rules:
        if r["kind"] == rule["kind"] and r["phrase_norm"] and r["phrase_norm"] in t:
            return r is rule
    return False
