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
  `/api/admin/ops-assistant`는 `api/auth.OWNER_WRITE_PREFIXES`에 이미 등록돼
  있다(실측: `auth.py:310-323`, 2026-08-17 확인 — 전에는 "아직 등록 안 됨"이라 적혀
  있었는데 그 사이 다른 물결에서 등록됐다. CANON §5 그대로 여기서 정정한다). 그
  접두어는 `/api/admin/ops-assistant`로 시작하는 모든 하위 경로에 적용되므로 아래
  `POST /ops-assistant/ask`도 **새로 등록하지 않아도** GET/HEAD/OPTIONS가 아니면
  자동으로 owner를 요구한다(`auth.required_role`). 이 모듈은 그래도 각 쓰기
  엔드포인트에서 `_require_owner()`로 **직접** owner를 강제한다 — 미들웨어가
  막아 주더라도 이 파일만 보고는 그 사실을 알 수 없으므로 이중 방어다(중복이 아니다).
  **읽기(GET) 경로**도 인증은 걸린다 — `auth._is_gated`가 `/api/admin/*` 전체를
  게이트하고, GET은 `required_role`이 "viewer"를 요구한다(무세션이면 401). 이
  파일이 별도로 미인증 읽기를 열어 두지 않는다(실측, 2026-08-17).

■ 질문·답변(`POST /ops-assistant/ask`, 2026-08-17 신설) — 운영자가 실제로 AI에게
  묻고 답을 받는다. `api/llm.py`를 **부르기만** 한다(그 파일은 고치지 않음).
  프롬프트에는 매 요청마다 DB에서 다시 읽은 ① `ops_assistant_scopes`(켜진 것만
  구체적으로 답하게 하고, 잠긴 셋과 아직 안 켜진 것들은 각각 다른 이유로 금지)
  ② `ops_assistant_faqs` 5행(질문이 근접하면 그 답을 쓰게) ③ `_real_routes()`
  결과(화면 안내는 실제 admin2 경로만)를 싣는다 — 코드에 박으면 운영자가 화면에서
  범위를 켜고 꺼도 반영되지 않는다는 사장님 지시를 그대로 따른 것이다. 대화 이력은
  저장하지 않는다(이번 범위 밖 — `api_cost_logs`에는 provider·model·토큰·비용만
  남고 질문·답변 본문은 어디에도 적재되지 않는다. 화면도 브라우저 메모리에서만
  들고 있다가 새로고침하면 사라진다). 상세 근거는 아래 함수들의 주석 참고.
"""
import json
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from . import llm
from .admin_nav import NAV
from .auth import current_operator, current_operator_id
from .db import engine

router = APIRouter(prefix="/api/admin", tags=["ops-assistant"])

MAX_LINKS = 2

# ⚠ 2026-08-17 정정(CANON §5 그대로 — 낡은 채로 두면 다음 사람이 사실로 읽는다):
# 이 주석은 원래 "이 두 화면 자신은 admin_nav.py의 href가 아직 None(신설)이라
# _nav_label_by_href()로는 라벨을 못 찾는다"고 적혀 있었다. 그런데 지금 admin_nav.py를
# 실측하면 둘 다 이미 실제 href를 갖고 있다(`_nav_label_by_href()`가 스스로 두 라벨을
# 찾아낸다 — 2026-08-17 확인). 그래서 아래 딕셔너리는 지금은 **닿지 않는 폴백**이다 —
# 지우지는 않는다(admin_nav.py는 이 화면 담당자가 건드리지 않는 파일이라, 그쪽에서
# 다시 href를 비우는 변경이 나중에 와도 이 화면이 라벨 없이 죽지 않게 막아 준다).
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


# ============================================================================
# 질문·답변 — 프롬프트를 만드는 함수 셋 + 엔드포인트 하나 (2026-08-17 신설)
#
# 셋 다 "매 요청마다" DB 값을 받아 문자열로 접는다 — 캐시하지 않는다. 답변 범위를
# 운영자가 화면에서 막 켰는데 다음 질문이 옛 값을 쓰면 그 화면의 존재 이유가
# 없어진다("정본을 매 요청마다 읽는다"는 지시를 코드로 옮긴 자리).
# ============================================================================
MAX_QUESTION_LEN = 500


class AskBody(BaseModel):
    question: str


def _plain(html_ish: str) -> str:
    """FAQ 답변의 `<b>` 등 최소 서식을 벗긴다 — 프롬프트는 순수 텍스트로 받는다."""
    return re.sub(r"<[^>]+>", "", html_ish or "").strip()


def _scope_prompt_block(scopes: list[dict]) -> str:
    """켜진 것 / 잠긴 것(영구 금지) / 안 켜진 것(잠기지 않음 — 운영자가 나중에 켤 수
    있음)을 **서로 다른 문구**로 나눠 싣는다. 셋을 한 덩어리로 섞으면 모델이 "잠금"과
    "아직 미승인"을 구분해 답하지 못한다 — 운영자에게는 "왜 안 되는지"가 다른 정보다.
    """
    enabled = [s for s in scopes if s["enabled"] and not s["locked"]]
    off = [s for s in scopes if not s["enabled"] and not s["locked"]]
    locked = [s for s in scopes if s["locked"]]
    lines = ["[답변 가능 범위 -- 이 주제의 질문에만 구체적으로 답한다]"]
    lines += ([f"- {s['label']}" for s in enabled]
              or ["- (지금 켜진 범위가 없다 -- 데이터 질문은 전부 보류한다)"])
    lines.append("")
    lines.append("[금지 범위 -- 절대 답하지 않는다. \"이 항목은 답변 대상이 아닙니다\"라고만"
                  " 답하고 이유를 한 줄 덧붙인다. 예외 없음]")
    lines += [f"- {s['label']} -- {s['lock_note'] or '잠긴 항목입니다'}" for s in locked]
    lines.append("")
    lines.append("[아직 켜지지 않은 범위 -- 지금은 금지 범위와 똑같이 취급해 답하지 않는다."
                  " 다만 \"운영자가 화면에서 범위를 켜면 답할 수 있다\"고 안내한다"
                  "(위 금지 범위와는 이유가 다르다 -- 잠금이 아니라 아직 미승인)]")
    lines += ([f"- {s['label']}" for s in off] or ["- (없음)"])
    return "\n".join(lines)


def _faq_prompt_block(faqs: list[dict]) -> str:
    lines = ["[자주 묻는 질문 -- 운영자 질문이 이것과 같거나 매우 비슷하면 이 답을 그대로 쓴다]"]
    for f in faqs:
        lines.append(f"Q: {f['question']}")
        lines.append(f"A: {_plain(f['answer'])}")
        links = f["links"] or []
        if links:
            lines.append("바로가기: " + ", ".join(
                f"{ln.get('label')} {ln.get('path')}" for ln in links))
        lines.append("")
    return "\n".join(lines)


def _routes_prompt_block(routes: list[dict]) -> str:
    lines = ["[실제 admin2 화면 경로 -- 화면을 안내할 때 이 목록에 있는 경로만 쓴다."
             " 목록에 없는 주소를 지어내지 않는다. 안내할 화면이 없으면 경로 없이 말로만 답한다]"]
    lines += [f"{r['path']} -- {r['label']}" for r in routes]
    return "\n".join(lines)


_SYSTEM_HEADER = (
    "당신은 팝콘PC AI 관리자 화면(admin2)의 운영 도우미다. 운영자의 질문에 한국어"
    " 평서체로 답한다. 감탄사·반문·구어체를 쓰지 않는다. 마크다운 서식(별표 굵게, #,"
    " 코드블록, 목록 기호)을 쓰지 않고 줄글로만 답한다. 3~6문장 이내로 간결하게 답한다.\n\n"
    "답변 원칙:\n"
    "1. 아래 자주 묻는 질문과 같거나 매우 비슷한 질문이면 그 답을 그대로 쓴다.\n"
    "2. 금지 범위·아직 켜지지 않은 범위에 해당하는 질문에는 데이터를 답하지 않는다.\n"
    "3. 이 프롬프트에 없는 구체적인 수치(재고 수·가격·건수 등)는 절대 지어내지 않는다"
    " -- 모르면 모른다고 답한다.\n"
    "4. 화면을 안내할 때는 실제 admin2 경로 목록에 있는 경로만 쓴다.\n"
)


def _build_prompt(question: str, scopes: list[dict], faqs: list[dict], routes: list[dict]) -> str:
    return "\n\n".join([
        _SYSTEM_HEADER,
        _scope_prompt_block(scopes),
        _faq_prompt_block(faqs),
        _routes_prompt_block(routes),
        f"[운영자 질문]\n{question}",
    ])


_BLOCK_KIND_KO = {"cost": "비용", "rate_minute": "분당 호출 횟수", "rate_day": "일일 호출 횟수"}


@router.post("/ops-assistant/ask")
def ask_ops_assistant(body: AskBody, request: Request):
    """운영자 질문에 AI가 답한다 -- `api/llm.py`를 부르기만 한다(그 파일은 고치지 않음).

    캡(비용·호출 빈도)은 `llm.py`가 **프로바이더 전체 기준**으로 막는다 -- 여기서
    한도를 다시 정의하지 않는다. 막히면 429로 사유를 그대로 올린다. 화면(JS)은 이미
    있는 `window.popcornProgress.errText()` 경로로 `detail`을 그대로 보여준다(다른
    쓰기 엔드포인트와 동일 -- 새로 만들지 않았다).
    """
    _require_owner()
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(400, "질문이 비었습니다")
    if len(q) > MAX_QUESTION_LEN:
        raise HTTPException(400, f"질문이 너무 깁니다(최대 {MAX_QUESTION_LEN}자)")

    routes = _real_routes(request.app)
    with engine.connect() as conn:
        if not _table_ready(conn):
            raise HTTPException(409, "FAQ·답변 범위 원천이 아직 준비되지 않았습니다(마이그레이션 미적용)")
        faqs = [dict(r) for r in conn.execute(text(
            "SELECT question, answer, links FROM ops_assistant_faqs"
            " ORDER BY sort_order, faq_id")).mappings().all()]
        scopes = [dict(r) for r in conn.execute(text(
            "SELECT scope_key, label, enabled, locked, lock_note FROM ops_assistant_scopes"
            " ORDER BY sort_order, scope_key")).mappings().all()]

    prompt = _build_prompt(q, scopes, faqs, routes)

    try:
        result = llm.call(prompt, task_key="task.ops_assist", customer_facing=False)
    except llm.LLMNotConfiguredError as e:
        raise HTTPException(503, f"AI 연동이 설정되지 않았습니다 — {e}")
    except llm.LLMBlockedError as e:
        kind_ko = _BLOCK_KIND_KO.get(e.kind, e.kind)
        raise HTTPException(429, f"{kind_ko} 한도에 걸렸습니다({e.provider}) — {e}")
    except llm.LLMAllProvidersFailedError as e:
        raise HTTPException(502, f"AI 응답을 받지 못했습니다 — 연동된 프로바이더가 모두 실패했습니다: {e}")
    except llm.LLMProviderError as e:
        raise HTTPException(502, f"AI 응답을 받지 못했습니다 — {e}")

    return {
        "ok": True, "answer": result.text,
        "provider": result.provider, "model": result.model,
        "elapsed_sec": result.elapsed_sec, "cost_usd": result.cost_usd,
        "note": "이 질문·답변은 저장하지 않습니다 — 새로고침하면 사라집니다.",
    }
