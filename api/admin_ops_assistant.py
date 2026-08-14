"""운영 도우미 설정(ADM-AI-070) API — `api/main.py`가 자동으로 싣는다(§discovery).

요구사항: `docs/design/req/req-ops-assistant.md`. 디자인 정본: `docs/design/dc-ops-
assistant.html`. 실측 근거: `ai-screens-datamap.md` §5.

■ 이 화면이 편집하는 것과 편집하지 않는 것
  이 API는 `ops_assistant_faqs`·`ops_assistant_scopes`(마이그레이션 0048, DBA 미적용
  상태일 수 있음)를 읽고 쓴다. **`mockups/shared/admin-helper.js`(위젯 본체)는 건드리지
  않는다** — 이번 제작 범위 밖으로 지정된 파일이다. 그래서 위젯은 지금도 자기 코드
  상수(FAQ 5개)를 그대로 쓰고, 이 화면에서 저장해도 위젯에 실시간 반영되지 않는다.
  `GET /ops-assistant`의 `widget_sync_note`가 그 사실을 화면에 정직하게 밝힌다 —
  "저장하면 위젯에 즉시 반영됩니다"라고 말하지 않는다(디자인 원안 dc-ops-assistant.html
  의 해당 문구를 의도적으로 바꾼 지점, 제작 보고서 참조).

■ 바로가기 경로 검증은 **하드코딩하지 않는다**
  `_real_routes()`가 매 요청마다 `request.app.routes`를 훑어 지금 실제로 등록된
  `/admin2/*` GET 경로만 돌려준다. 디자인 원안의 `ROUTES` 상수는 제작 시점 실측으로
  이미 낡아 있었다(`/admin2/reviews`를 `exists:false`로 적어 뒀는데 실제로는 이미
  지어져 있었다) — 그래서 상수를 옮기지 않았다. 화면이 늘면(새 `admin_ui_*.py`)
  서버 재기동만으로 이 목록이 자동으로 늘어난다.

■ 권한 — owner 쓰기를 이 파일 스스로도 강제한다
  `/api/admin/ops-assistant`는 아직 `api/auth.OWNER_WRITE_PREFIXES`에 등록돼 있지
  않다(그 파일은 제작팀 공유 파일이라 이 화면 담당자가 직접 고치지 않는다 — 필요한
  prefix를 제작 보고서에 명시해 하네스가 반영한다). 그때까지는 미들웨어가 기본값
  (operator)만 요구하므로, 이 모듈이 `_require_owner()`로 **직접** owner를 강제한다
  — 이중 방어이지 중복이 아니다.
"""
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .admin_nav import NAV
from .auth import current_operator, current_operator_id
from .db import engine

router = APIRouter(prefix="/api/admin", tags=["ops-assistant"])

MAX_LINKS = 2

# 이 두 화면(AI 응답 기록·운영 도우미 설정) 자신은 `admin_nav.py`의 href가 아직
# None("신설")이라 아래 `_nav_label_by_href()`로는 라벨을 못 찾는다 — harness가
# admin_nav.py를 갱신하기 전까지의 임시 표시일 뿐 정본을 복제하는 것이 아니다
# (admin_nav.py는 이 화면 담당자가 건드리지 않는 파일이다).
_LOCAL_LABELS = {
    "/admin2/ai-response-log": "AI 응답 기록",
    "/admin2/ops-assistant": "운영 도우미 설정",
}


def _require_owner() -> dict:
    op = current_operator()
    role = (op or {}).get("role")
    if role != "owner":
        raise HTTPException(403, f"권한이 부족합니다(필요: owner, 현재: {role or '(로그인 필요)'})")
    return op


def _table_ready(conn) -> bool:
    return bool(conn.execute(text(
        "SELECT to_regclass('public.ops_assistant_faqs') IS NOT NULL")).scalar())


def _nav_label_by_href() -> dict:
    out = {}
    for _title, _icon, items in NAV:
        for label, href, _note in items:
            if href:
                key = href.rstrip("/") or "/admin2"
                out[key] = label
    return out


def _humanize(path: str) -> str:
    tail = path.rstrip("/").rsplit("/", 1)[-1] or "admin2"
    return tail.replace("-", " ")


def _iter_routes(routes):
    """`app.routes`를 평평하게 편다.

    이 저장소가 쓰는 FastAPI 버전(실측 0.139.2)은 `app.include_router()`로 실은
    라우트를 `_IncludedRouter`(원본 `APIRouter`를 감싼 래퍼)로 등록한다 —
    `app.routes`를 바로 훑으면 개별 경로의 `.path`가 보이지 않는다(실측:
    `type(r).__name__ == '_IncludedRouter'`이고, 실제 경로는
    `r.original_router.routes`에 있다 — 프리픽스는 이미 적용된 채로).
    래퍼가 있으면 한 겹 더 들어가고, 없으면(일반 `Route`/`APIRoute`) 그대로 쓴다 —
    한 번 겪은 뒤로는 "부르기 전에 있는지 본다"는 이 저장소의 교훈과 같은 이유로,
    이 함수 없이 `app.routes`를 직접 훑으면 **항상 빈 목록**이 나가는데도 겉으로는
    조용히 통과한다(예외가 없다) — 화면 정직성 규약이 정면으로 걸리는 지점이라
    제작 중 자체 점검(Node/Jinja 렌더와 별개로 `api.main.app`을 실제로 띄워 대조)에서
    잡았다.
    """
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None and hasattr(inner, "routes"):
            for r2 in _iter_routes(inner.routes):
                yield r2
        else:
            yield r


def _real_routes(app) -> list:
    """지금 실제로 등록된 admin2 GET 페이지 경로. 하드코딩 목록이 아니다(위 docstring)."""
    nav_labels = _nav_label_by_href()
    seen: dict = {}
    for r in _iter_routes(app.routes):
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if not path or "GET" not in methods or not path.startswith("/admin2"):
            continue
        if "{" in path:            # 파라미터 있는 경로는 "바로가기" 후보가 아니다
            continue
        norm = path.rstrip("/") or "/admin2"
        if norm in seen:
            continue
        seen[norm] = nav_labels.get(norm) or _LOCAL_LABELS.get(norm) or _humanize(norm)
    return [{"path": p, "label": seen[p]} for p in sorted(seen)]


class LinkBody(BaseModel):
    label: str
    path: str


class FaqBody(BaseModel):
    question: str
    answer: str
    links: list[LinkBody] = Field(default_factory=list)


def _validate_faq(body: FaqBody, real_paths: set):
    q = (body.question or "").strip()
    a = (body.answer or "").strip()
    if not q:
        raise HTTPException(400, "질문이 비었습니다")
    if not a:
        raise HTTPException(400, "답변이 비었습니다")
    if len(body.links) > MAX_LINKS:
        raise HTTPException(400, f"바로가기는 최대 {MAX_LINKS}개입니다")
    bad = [ln.path for ln in body.links if ln.path not in real_paths]
    if bad:
        raise HTTPException(400, "존재하지 않는 admin2 경로입니다: " + ", ".join(bad))
    links = [{"label": (ln.label or "").strip()[:60] or ln.path, "path": ln.path}
             for ln in body.links]
    return q[:200], a, links


def _faq_out(row, real_paths: set) -> dict:
    links = row["links"] or []
    return {
        "faq_id": row["faq_id"], "sort_order": row["sort_order"],
        "question": row["question"], "answer": row["answer"],
        "links": [{"label": ln.get("label"), "path": ln.get("path"),
                   "exists": ln.get("path") in real_paths} for ln in links],
    }


@router.get("/ops-assistant")
def get_ops_assistant(request: Request):
    """FAQ·답할 범위·바로가기 점검 — 화면 하나가 쓰는 값을 한 번에 준다."""
    routes = _real_routes(request.app)
    real_paths = {r["path"] for r in routes}
    with engine.connect() as conn:
        if not _table_ready(conn):
            return {
                "ready": False, "faqs": [], "scopes": [], "routes": routes,
                "broken_links": 0,
                "note": ("FAQ 원천이 아직 준비되지 않았습니다 — 마이그레이션 0048이"
                         " 적용되면(DBA 작업) 이 화면이 채워집니다."),
                "widget_sync_note": None,
            }
        faqs = conn.execute(text(
            "SELECT faq_id, sort_order, question, answer, links FROM ops_assistant_faqs"
            " ORDER BY sort_order, faq_id")).mappings().all()
        scopes = conn.execute(text(
            "SELECT scope_key, label, enabled, locked, lock_note, sort_order"
            " FROM ops_assistant_scopes ORDER BY sort_order, scope_key")).mappings().all()
    faq_out = [_faq_out(f, real_paths) for f in faqs]
    broken = sum(1 for f in faq_out for ln in f["links"] if not ln["exists"])
    return {
        "ready": True, "faqs": faq_out,
        "scopes": [dict(s) for s in scopes],
        "routes": routes, "broken_links": broken,
        "note": ("도우미는 첫 릴리스에서 읽기만 합니다 — 이 화면에 자동 응답을 끄고"
                 " 켜는 옵션 자체가 없습니다. 자유 질문에는 아직 답하지 않습니다"
                 "(FAQ 문자열 매칭만, LLM 연동 보류)."),
        "widget_sync_note": ("저장하면 이 목록(DB)에는 즉시 반영되고 이력에 남습니다."
                              " 다만 실제 위젯(admin-helper.js)은 아직 이 표를 읽지"
                              " 않고 자체 코드 상수를 씁니다 — 위젯이 이 표를 읽도록"
                              " 배선하는 것은 이 화면의 범위 밖입니다."),
    }


@router.post("/ops-assistant/faqs")
def add_faq(body: FaqBody, request: Request):
    _require_owner()
    real_paths = {r["path"] for r in _real_routes(request.app)}
    q, a, links = _validate_faq(body, real_paths)
    from .admin_orders import _log
    with engine.begin() as conn:
        if not _table_ready(conn):
            raise HTTPException(409, "FAQ 원천이 아직 준비되지 않았습니다(마이그레이션 미적용)")
        nxt = conn.execute(text(
            "SELECT COALESCE(MAX(sort_order), 0) + 10 FROM ops_assistant_faqs")).scalar()
        faq_id = conn.execute(text(
            "INSERT INTO ops_assistant_faqs (sort_order, question, answer, links, updated_by)"
            " VALUES (:so, :q, :a, CAST(:l AS JSONB), :op) RETURNING faq_id"),
            {"so": nxt, "q": q, "a": a, "l": json.dumps(links, ensure_ascii=False),
             "op": current_operator_id()}).scalar()
        undo_id = _log(conn, "ops_assistant_faq_add", str(faq_id),
                        {"question": q, "answer": a, "links": links},
                        kind="ops_assistant_faq")
    return {"ok": True, "faq_id": faq_id, "undo_id": undo_id,
            "note": "FAQ를 추가했습니다 — 질문·답변을 채우고 저장하세요."}


@router.patch("/ops-assistant/faqs/{faq_id}")
def edit_faq(faq_id: int, body: FaqBody, request: Request):
    _require_owner()
    real_paths = {r["path"] for r in _real_routes(request.app)}
    q, a, links = _validate_faq(body, real_paths)
    from .admin_orders import _log
    with engine.begin() as conn:
        if not _table_ready(conn):
            raise HTTPException(409, "FAQ 원천이 아직 준비되지 않았습니다(마이그레이션 미적용)")
        before = conn.execute(text(
            "SELECT faq_id, question, answer, links FROM ops_assistant_faqs"
            " WHERE faq_id=:i FOR UPDATE"), {"i": faq_id}).mappings().first()
        if before is None:
            raise HTTPException(404, "FAQ가 없습니다")
        conn.execute(text(
            "UPDATE ops_assistant_faqs SET question=:q, answer=:a, links=CAST(:l AS JSONB),"
            " updated_at=now(), updated_by=:op WHERE faq_id=:i"),
            {"q": q, "a": a, "l": json.dumps(links, ensure_ascii=False),
             "op": current_operator_id(), "i": faq_id})
        undo_id = _log(conn, "ops_assistant_faq_edit", str(faq_id),
                        {"before": {"question": before["question"], "answer": before["answer"],
                                    "links": before["links"]},
                         "after": {"question": q, "answer": a, "links": links}},
                        kind="ops_assistant_faq")
    return {"ok": True, "undo_id": undo_id,
            "note": "저장했습니다 — 위젯 연동 배선 전까지는 이 화면(DB)에만 반영됩니다."}


@router.delete("/ops-assistant/faqs/{faq_id}")
def delete_faq(faq_id: int):
    _require_owner()
    from .admin_orders import _log
    with engine.begin() as conn:
        if not _table_ready(conn):
            raise HTTPException(409, "FAQ 원천이 아직 준비되지 않았습니다(마이그레이션 미적용)")
        total = conn.execute(text("SELECT count(*) FROM ops_assistant_faqs")).scalar()
        row = conn.execute(text(
            "SELECT question, answer, links FROM ops_assistant_faqs"
            " WHERE faq_id=:i FOR UPDATE"), {"i": faq_id}).mappings().first()
        if row is None:
            raise HTTPException(404, "FAQ가 없습니다")
        if total <= 1:
            raise HTTPException(409, "FAQ는 최소 1개가 남아야 합니다 — 0개가 되면 위젯이"
                                     " 답할 것이 없습니다")
        conn.execute(text("DELETE FROM ops_assistant_faqs WHERE faq_id=:i"), {"i": faq_id})
        undo_id = _log(conn, "ops_assistant_faq_delete", str(faq_id),
                        {"question": row["question"], "answer": row["answer"],
                         "links": row["links"]}, kind="ops_assistant_faq")
    return {"ok": True, "undo_id": undo_id, "note": "FAQ를 삭제했습니다."}


class MoveBody(BaseModel):
    direction: str  # "up" | "down"


@router.post("/ops-assistant/faqs/{faq_id}/move")
def move_faq(faq_id: int, body: MoveBody):
    _require_owner()
    if body.direction not in ("up", "down"):
        raise HTTPException(400, "direction은 up 또는 down 이어야 합니다")
    with engine.begin() as conn:
        if not _table_ready(conn):
            raise HTTPException(409, "FAQ 원천이 아직 준비되지 않았습니다(마이그레이션 미적용)")
        rows = conn.execute(text(
            "SELECT faq_id, sort_order FROM ops_assistant_faqs"
            " ORDER BY sort_order, faq_id FOR UPDATE")).mappings().all()
        ids = [r["faq_id"] for r in rows]
        if faq_id not in ids:
            raise HTTPException(404, "FAQ가 없습니다")
        i = ids.index(faq_id)
        j = i - 1 if body.direction == "up" else i + 1
        if j < 0 or j >= len(rows):
            raise HTTPException(409, "더 이동할 수 없습니다 — 이미 맨 " +
                                 ("위" if body.direction == "up" else "아래") + "입니다")
        a, b = rows[i], rows[j]
        conn.execute(text("UPDATE ops_assistant_faqs SET sort_order=:s WHERE faq_id=:i"),
                     {"s": b["sort_order"], "i": a["faq_id"]})
        conn.execute(text("UPDATE ops_assistant_faqs SET sort_order=:s WHERE faq_id=:i"),
                     {"s": a["sort_order"], "i": b["faq_id"]})
    return {"ok": True, "note": "순서를 옮겼습니다."}


class ScopeBody(BaseModel):
    enabled: bool


@router.patch("/ops-assistant/scopes/{scope_key}")
def set_scope(scope_key: str, body: ScopeBody):
    _require_owner()
    from .admin_orders import _log
    with engine.begin() as conn:
        if not _table_ready(conn):
            raise HTTPException(409, "답할 범위 원천이 아직 준비되지 않았습니다(마이그레이션 미적용)")
        row = conn.execute(text(
            "SELECT scope_key, label, enabled, locked, lock_note FROM ops_assistant_scopes"
            " WHERE scope_key=:k FOR UPDATE"), {"k": scope_key}).mappings().first()
        if row is None:
            raise HTTPException(404, "알 수 없는 항목입니다")
        if row["locked"]:
            raise HTTPException(400, f"{row['label']}은(는) 답변 대상이 될 수 없습니다"
                                     f" — 잠긴 항목입니다({row['lock_note'] or ''})")
        conn.execute(text(
            "UPDATE ops_assistant_scopes SET enabled=:e, updated_at=now(), updated_by=:op"
            " WHERE scope_key=:k"),
            {"e": body.enabled, "op": current_operator_id(), "k": scope_key})
        _log(conn, "ops_assistant_scope_set", scope_key,
             {"label": row["label"], "before": row["enabled"], "after": body.enabled},
             kind="ops_assistant_scope")
        label, enabled = row["label"], body.enabled
    return {"ok": True, "note": label + (
        "을(를) 답변 범위에 넣었습니다" if enabled else "을(를) 답변 범위에서 뺐습니다")}
