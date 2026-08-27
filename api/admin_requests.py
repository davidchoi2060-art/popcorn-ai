"""요청 · 승인(ADM-SYS-060 · 제안) — 직원 요청 · 하네스 판단 · 사장님 결재 데이터 API.

■ 흐름 (요구사항 정의서 `docs/design/req/req-work-request.md` §①·⑤)
    직원(운영자)   화면을 쓰다 불편한 것을 캡처와 글로 올린다
    하네스(AI)     읽고 판단한다 — 작은 것은 바로 고치고, 큰 것은 사장님 결재로
    사장님(owner)  승인 · 반려(사유 필수) · 보류를 정한다

■ 표 셋 — `db/migrations/versions/0070_admin_requests.py` 가 정본. 그 파일 docstring이
  「왜 기존 표로 안 되는지」·「왜 캡처가 세 번째 표인지」·「반려가 별도 상태인 이유」를
  진다 — 여기서 다시 설명하지 않는다.

■ ★ URL 을 둘로 가른 이유 — `OWNER_WRITE_PREFIXES` 는 문자열 접두어 매칭이라 `{id}`가
  중간에 낀 경로를 못 가른다(`api/auth.py`가 정규식을 안 쓰는 이유와 같다).
  그래서 **경로 자체를 둘로** 나눴다:
      /api/admin/requests/...            등록 · 댓글 · 취소 · 캡처 — operator 이상
      /api/admin/request-decisions/...   판정 · 처리 · 승인 · 반려 · 보류 — owner 전용
  `api/auth.py`의 `OWNER_WRITE_PREFIXES`에 뒷줄 접두어 하나만 등록하면 미들웨어가
  전부 막는다 — **안 넣으면 운영자가 자기 요청을 스스로 승인·판정할 수 있다.**
  각 owner 엔드포인트는 그 등록과 별개로 `_owner()`를 한 번 더 부른다(이중 방어 —
  `api/admin_mall_supplier.py`·AI 관리 3화면과 같은 관례. 미들웨어가 먼저 막지만,
  이 모듈만 따로 시험할 때도 방어가 산다).

■ ★ 「하네스」라는 로그인 주체가 없다 — 그래서 판정 · 처리도 owner 전용이다
  이 시스템의 등급은 viewer/operator/owner 셋뿐이다(`api/auth.py` `ROLE_RANK`).
  「하네스가 판정한다」·「하네스가 처리한다」는 요구사항 정의서의 개념 모델이지,
  이 코드베이스에 그 이름의 로그인 주체가 있다는 뜻이 아니다(결정 5 「하네스 알림
  수단」이 미정이라 그 정체성 자체가 아직 안 만들어졌다). 정직한 매핑은 둘 중 하나다:
      ① operator 도 판정 · 처리를 부를 수 있게 연다 → 그러면 **직원이 자기가 올린
         요청을 스스로 「작은 것 · 처리 완료」로 표시**할 수 있다 — 신뢰 경계가 없다.
      ② owner 전용으로 좁힌다 → 하네스는 실제로는 owner 세션(부트스트랩 계정 또는
         사장님 세션)으로 동작한다고 본다.
  ②를 택했다. 사장님이 정하신 것은 「승인 · 반려 · 보류는 owner 전용」뿐이지만, 판정 ·
  처리를 operator 에 열면 그 경계가 원천에서 무너지므로 같은 등급으로 묶었다 —
  **이 판단은 지시서에 명시되지 않은 확장이라 보고에도 남긴다.** 결정 5 가 풀려
  「하네스」 전용 신원이 생기면 이 경계를 다시 그을 자리다.

■ 캡처 정책 — 결정 3(한도) **확정(2026-08-27 사장님 결정) — 3MB**. 1920×1080 화면
  캡처가 흔히 1~3MB라 1MB에서는 직원이 올리다 막히는 사례가 있었다(요구사항 정의서
  `req-work-request.md` §결정 3의 우려가 실제로 맞았다). `CAPTURE_MAX_BYTES`(환경변수
  `WORK_REQUEST_CAPTURE_MAX_BYTES`, 기본 3MB)가 이 상수 하나로 단일 원천이다.
  화면은 `GET /api/admin/requests/meta`의 `capture_policy`로 그 값을
  받아 말한다 — 숫자를 스스로 적지 않는다(`api/admin_profile_photo.photo_rules()`와
  같은 패턴). 형식 판정은 **그 파일의 `_sniff()`를 그대로 재사용**한다(매직넘버 · SVG
  명시 거부) — 새로 궁리하지 않는다(지시서 문구 그대로). ⚠ **「내 정보」 프로필 사진의
  1MB 한도(`api/admin_profile_photo.py`)는 별개 정책이다 — 같이 올리지 않는다**(사장님이
  정하신 것은 요청 캡처뿐).

■ 방치(「방치」배지) 기준도 설정으로 뺀다 — `STALE_DAYS`(환경변수
  `WORK_REQUEST_STALE_DAYS`, 기본 3일). 판정은 SQL 한 표현(`_ROW_SELECT`의 `is_stale`)
  «하나»에서만 한다 — 목록 배지 · 상단 띠 건수 · 필터가 각자 다시 계산하면
  «판정을 두 곳에 적어 갈라지는» 사고(CLAUDE.md §화면 정직성, U-17 후속)가 난다.

■ 직원은 자기 것만 본다(요구사항 §⑥). owner 는 전체를 본다. 시각화(레인 vs 목록)는
  화면(`admin_ui_requests.py`/템플릿) 몫이고, 이 API 는 「누가 무엇을 볼 수 있는가」만
  가른다 — 그 경계가 화면마다 다시 구현되면 언젠가 갈린다.
"""
import os

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from .admin_nav import NAV
from .admin_orders import _log
from .admin_profile_photo import ALLOWED_LABEL, _sniff
from .auth import current_operator
from .dash import notify_harness
from .db import engine
from .timeutil import iso

# 접두어를 나누지 않는다 — 위 모듈 docstring §URL 을 둘로 가른 이유. 전체 경로를
# 엔드포인트마다 명시하고, `router` 하나만 둔다(`api/main.py`의 자동 등록은 모듈에
# `router` 속성 하나만 찾는다 — 여러 개를 만들면 나머지는 조용히 안 실린다).
router = APIRouter(tags=["work-requests"])

STATUSES = ("접수", "검토", "처리", "결재대기", "승인", "반려", "보류", "완료", "취소")
# 「닫힘」 레인(1b 디자인)이 묶는 상태 — 화면이 다시 나열하지 않게 여기서도 상수로 둔다.
CLOSED_STATUSES = ("완료", "반려", "취소")
VERDICTS = ("작은 것", "큰 것")
URGENCIES = ("낮음", "보통", "높음")

# ── 설정값 — 캡처 한도는 확정(2026-08-27, 3MB) · 방치 기준은 여전히 정책값이라
# 코드에 «숫자»를 박지 않는다(환경변수로 뺀다 — 값을 바꿀 때 이 파일을 고치지 않는다).
CAPTURE_MAX_BYTES = int(os.environ.get("WORK_REQUEST_CAPTURE_MAX_BYTES", str(3 * 1024 * 1024)))
STALE_DAYS = int(os.environ.get("WORK_REQUEST_STALE_DAYS", "3"))

_MIN_CAPTURE_HEAD = 12  # WebP 서명 판정에 필요한 최소 길이(admin_profile_photo와 동일)


def _me() -> dict:
    me = current_operator()
    if not me:
        raise HTTPException(401, "로그인이 필요하다")
    return me


def _owner() -> dict:
    """판정 · 처리 · 승인 · 반려 · 보류 — owner 전용의 «이중 방어»(위 모듈 docstring 참조).

    `api/auth.py`의 `OWNER_WRITE_PREFIXES`(미들웨어)가 먼저 막지만, 이 함수가 그 등록에만
    기대지 않는다 — 등록이 빠지는 사고가 실제로 있었다(모듈 docstring 참조, mall-supplier
    ·AI 관리 3화면과 같은 관례).
    """
    me = _me()
    if me["role"] != "owner":
        raise HTTPException(403, "판정 · 처리 · 승인 · 반려 · 보류는 사장님(owner)만 할 수 있다")
    return me


def _target_screen_options() -> list:
    """대상 화면 선택지 — `api/admin_nav.NAV` 를 그대로 편다(요구사항 §④ 「목록은
    admin_nav.py 에서 온다」). 라벨을 이 표에 복제하지 않는 이유는 `admin_requests`
    컬럼 주석(마이그레이션 0070) 참조 — NAV 가 단일 원천이다.
    """
    return [{"href": href, "label": f"{title} · {label}"}
            for title, _icon, items in NAV for label, href, _note in items if href]


def _target_label(href: str | None) -> str | None:
    """저장된 href 로 지금 NAV 라벨을 찾는다. 화면이 없어졌으면 href 원문을 그대로
    보여준다(라벨을 지어내지 않는다) — `None` 이면 애초에 대상 화면을 고르지 않은 것.
    """
    if not href:
        return None
    for opt in _target_screen_options():
        if opt["href"] == href:
            return opt["label"]
    return href


# 목록·상세·등록 응답이 전부 같은 모양을 쓴다 — 판정(is_stale)을 한 표현에서만 한다.
_ROW_SELECT = """
    SELECT r.*, o.name AS created_by_name, o.email AS created_by_email,
           dop.name AS decided_by_name,
           (SELECT count(*) FROM admin_request_comments c
             WHERE c.request_id = r.request_id) AS comment_count,
           (SELECT count(*) FROM admin_request_captures p
             WHERE p.request_id = r.request_id) AS capture_count,
           (r.status NOT IN ('완료','반려','취소')
            AND r.updated_at < now() - (:stale_days || ' days')::interval) AS is_stale,
           GREATEST(0, EXTRACT(DAY FROM now() - r.updated_at)::int) AS idle_days
    FROM admin_requests r
    JOIN admin_operators o ON o.operator_id = r.created_by
    LEFT JOIN admin_operators dop ON dop.operator_id = r.decided_by
"""


def _shape_row(r) -> dict:
    return {
        "request_id": r["request_id"],
        "title": r["title"],
        "body": r["body"],
        "status": r["status"],
        "target_screen_href": r["target_screen_href"],
        "target_screen_label": _target_label(r["target_screen_href"]),
        "urgency": r["urgency"],
        "verdict": r["verdict"],
        "verdict_note": r["verdict_note"],
        "result_note": r["result_note"],
        "reject_reason": r["reject_reason"],
        "hold_reason": r["hold_reason"],
        "created_by": r["created_by"],
        "created_by_name": r["created_by_name"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "decided_by": r["decided_by"],
        "decided_by_name": r["decided_by_name"],
        "decided_at": iso(r["decided_at"]),
        "resolved_at": iso(r["resolved_at"]),
        "cancelled_at": iso(r["cancelled_at"]),
        "comment_count": r["comment_count"],
        "capture_count": r["capture_count"],
        "is_stale": bool(r["is_stale"]),
        "idle_days": r["idle_days"],
    }


def _shape_comment(c) -> dict:
    return {
        "comment_id": c["comment_id"],
        "author_kind": c["author_kind"],
        "author_name": c["author_name"],
        "body": c["body"],
        "created_at": iso(c["created_at"]),
    }


def _shape_capture(p) -> dict:
    return {
        "capture_id": p["capture_id"],
        "seq": p["seq"],
        "content_type": p["content_type"],
        "byte_size": p["byte_size"],
        "uploaded_at": iso(p["uploaded_at"]),
        "url": f"/api/admin/requests/{p['request_id']}/captures/{p['capture_id']}",
    }


def _visible(row, me) -> bool:
    """직원은 자기 것만 본다(요구사항 §⑥) — owner 는 전체."""
    return me["role"] == "owner" or row["created_by"] == me["operator_id"]


def _fetch_row(conn, request_id: int, *, lock: bool = False):
    sql = _ROW_SELECT + " WHERE r.request_id = :rid" + (" FOR UPDATE OF r" if lock else "")
    return conn.execute(text(sql), {"rid": request_id, "stale_days": STALE_DAYS}).mappings().first()


def _not_found() -> HTTPException:
    # 없음과 「봐서는 안 됨」을 같은 404 로 답한다 — 남의 요청 id 로 존재 여부를 캐지 못하게.
    return HTTPException(404, "요청을 찾을 수 없다")


# ───────────────────────────── 메타 · 설정값 ─────────────────────────────
@router.get("/api/admin/requests/meta")
def requests_meta():
    """화면이 값을 스스로 적지 않도록 서버가 문장까지 만들어 준다(§캡처 정책 참조)."""
    me = _me()
    max_kb = CAPTURE_MAX_BYTES // 1024
    return {
        "statuses": list(STATUSES),
        "closed_statuses": list(CLOSED_STATUSES),
        "verdicts": list(VERDICTS),
        "urgencies": list(URGENCIES),
        "stale_days": STALE_DAYS,
        "target_screens": _target_screen_options(),
        "capture_policy": {
            "max_bytes": CAPTURE_MAX_BYTES,
            "max_kb": max_kb,
            "allowed_label": ALLOWED_LABEL,
            "short": f"{ALLOWED_LABEL} · {max_kb}KB 이하 · 여러 장",
            "rules": [
                f"{ALLOWED_LABEL} 파일만 등록",
                f"{max_kb}KB 이하",
                "형식은 파일 앞머리로 판정 — 확장자 · Content-Type 은 보지 않는다",
                "SVG 등록 불가",
            ],
        },
        # 결정 5 — 확정(2026-08-27 사장님 지시, 요청·승인 결함⑦): 등록하면
        # `notify_harness()`(api/dash.py)가 하네스를 부른다. 화면이 여전히 지어내지
        # 않는 것: 「닿았다」가 아니라 「불렀다」까지만 — 로컬 감시자가 알림 모드로
        # 떠 있어야 실제로 세션이 깨어난다(그 감시자 가동 여부는 이 API 가 알 방법이
        # 없다). `configured=False` 였을 때는 이 note 를 화면이 그대로 띄웠는데
        # (`requests.html.j2`), 지금은 `configured=True` 라 그 문장은 안 뜬다 — 그래도
        # 문구 자체는 사실과 맞게 남겨 둔다(다음 사람이 이 값을 다시 쓸 수 있다).
        "harness_notify": {
            "configured": True,
            "note": "요청을 등록하면 하네스를 부른다 — 다만 로컬 감시자가 알림 모드로"
                    " 떠 있어야 실제로 세션이 깨어난다.",
        },
        "viewer": {"operator_id": me["operator_id"], "name": me["name"], "role": me["role"],
                   "is_owner": me["role"] == "owner"},
    }


# ───────────────────────────── 목록 ─────────────────────────────
@router.get("/api/admin/requests")
def list_requests(status: str | None = None, mine: bool = False, stale: bool = False,
                   limit: int = 150, offset: int = 0):
    """목록 — 서버 페이지네이션(`total` 을 함께 준다, 화면이 세지 않는다).

    레인(1b) 화면은 상태별로 다시 나누지 않고 이 한 호출의 결과를 상태로 묶어 그린다
    (원안의 `laneDefs`가 하는 일과 같다 — 원천은 이 응답 하나뿐).
    """
    me = _me()
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    is_owner = me["role"] == "owner"

    conds = []
    params = {"stale_days": STALE_DAYS, "limit": limit, "offset": offset}
    if not is_owner or mine:
        conds.append("r.created_by = :me")
        params["me"] = me["operator_id"]
    if status:
        sts = [s.strip() for s in status.split(",") if s.strip()]
        bad = [s for s in sts if s not in STATUSES]
        if bad:
            raise HTTPException(400, f"status 값이 올바르지 않다: {', '.join(bad)}")
        if sts:
            conds.append("r.status = ANY(:sts)")
            params["sts"] = sts
    if stale:
        conds.append("r.status NOT IN ('완료','반려','취소')"
                      " AND r.updated_at < now() - (:stale_days || ' days')::interval")
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM admin_requests r{where}"),
                              params).scalar()
        rows = conn.execute(text(
            _ROW_SELECT + where + " ORDER BY r.updated_at DESC, r.request_id DESC"
            " LIMIT :limit OFFSET :offset"), params).mappings().all()
        # 상단 띠(「N건이 방치됐습니다」) — 현재 필터와 무관하게 같은 시야(내 것/전체) 안에서 센다.
        scope_cond = "r.created_by = :me AND " if (not is_owner or mine) else ""
        stale_where = (" WHERE " + scope_cond +
                        "r.status NOT IN ('완료','반려','취소')"
                        " AND r.updated_at < now() - (:stale_days || ' days')::interval")
        stale_total = conn.execute(text(
            f"SELECT count(*) FROM admin_requests r{stale_where}"),
            {"me": params.get("me"), "stale_days": STALE_DAYS}).scalar()

    return {"items": [_shape_row(r) for r in rows], "total": total,
            "limit": limit, "offset": offset, "stale_total": stale_total,
            "scope": "mine" if (not is_owner or mine) else "all"}


# ───────────────────────────── 등록 ─────────────────────────────
class CreateBody(BaseModel):
    title: str
    body: str
    target_screen_href: str | None = None
    urgency: str | None = None


@router.post("/api/admin/requests")
def create_request(body: CreateBody):
    me = _me()
    title = (body.title or "").strip()
    text_body = (body.body or "").strip()
    if not title:
        raise HTTPException(400, "제목을 입력해야 한다")
    if len(title) > 200:
        raise HTTPException(400, "제목은 200자 이하로 입력해야 한다")
    if not text_body:
        raise HTTPException(400, "본문을 입력해야 한다")
    if len(text_body) > 8000:
        raise HTTPException(400, "본문은 8,000자 이하로 입력해야 한다")
    href = (body.target_screen_href or "").strip() or None
    if href and len(href) > 200:
        raise HTTPException(400, "대상 화면 값이 올바르지 않다")
    urgency = (body.urgency or "").strip() or None
    if urgency and urgency not in URGENCIES:
        raise HTTPException(400, f"급함 정도는 {', '.join(URGENCIES)} 중 하나다")

    with engine.begin() as conn:
        rid = conn.execute(text(
            "INSERT INTO admin_requests (title, body, target_screen_href, urgency, created_by)"
            " VALUES (:t, :b, :h, :u, :me) RETURNING request_id"),
            {"t": title, "b": text_body, "h": href, "u": urgency,
             "me": me["operator_id"]}).scalar()
        _log(conn, "work_request_create", str(rid),
             {"title": title, "target_screen_href": href, "urgency": urgency}, kind="request")
        row = _fetch_row(conn, rid)

    # 하네스에게 알린다(2026-08-27, 요청·승인 결함⑦) — «등록»만 알린다. 댓글 · 취소는
    # 알리지 않는다: 댓글은 대개 하네스가 먼저 물어서 오는 답이라(§흐름 「검토」 단계)
    # 그 대화 안에 이미 있고, 취소는 할 일이 «줄어드는» 신호라 급하지 않다. 너무 잦은
    # 알림은 무시당한다(사장님 지시 — 결함⑦ 지시서) — 그래서 v1은 가장 신호가 큰
    # 한 지점만 울린다. 본문 전체는 넣지 않는다(캡처와 함께 화면에서 보면 된다) —
    # 무엇이 올라왔는지(REQ 번호 · 제목 · 올린 사람)와 어디로 가면 되는지(경로)만.
    # commit 뒤에 부른다 — 알림 실패가 등록 자체를 롤백하면 안 된다(notify_harness()는
    # 스스로도 예외를 삼키지만, 트랜잭션 밖에 두어 이중으로 안전하게 한다).
    notify_harness(
        f"새 요청 #REQ-{rid:04d} \"{title}\" — {me['name']} 올림 · /admin2/requests",
        source="work_request")

    return {"ok": True, "item": _shape_row(row), "note": "요청을 등록했다 — 상태는 접수다."}


# ───────────────────────────── 상세 ─────────────────────────────
@router.get("/api/admin/requests/{request_id}")
def get_request(request_id: int):
    me = _me()
    with engine.connect() as conn:
        row = _fetch_row(conn, request_id)
        if row is None or not _visible(row, me):
            raise _not_found()
        comments = conn.execute(text(
            "SELECT c.comment_id, c.author_kind, o.name AS author_name, c.body, c.created_at"
            " FROM admin_request_comments c JOIN admin_operators o ON o.operator_id = c.author_id"
            " WHERE c.request_id = :r ORDER BY c.created_at, c.comment_id"),
            {"r": request_id}).mappings().all()
        captures = conn.execute(text(
            "SELECT capture_id, request_id, seq, content_type, byte_size, uploaded_at"
            " FROM admin_request_captures WHERE request_id = :r ORDER BY seq"),
            {"r": request_id}).mappings().all()

    item = _shape_row(row)
    item["comments"] = [_shape_comment(c) for c in comments]
    item["captures"] = [_shape_capture(p) for p in captures]
    return item


# ───────────────────────────── 댓글 ─────────────────────────────
class CommentBody(BaseModel):
    body: str


@router.post("/api/admin/requests/{request_id}/comments")
def add_comment(request_id: int, body: CommentBody):
    me = _me()
    text_body = (body.body or "").strip()
    if not text_body:
        raise HTTPException(400, "댓글 내용을 입력해야 한다")
    if len(text_body) > 4000:
        raise HTTPException(400, "댓글은 4,000자 이하로 입력해야 한다")

    with engine.begin() as conn:
        row = _fetch_row(conn, request_id)
        if row is None or not _visible(row, me):
            raise _not_found()
        kind = "사장님" if me["role"] == "owner" else "직원"
        cid = conn.execute(text(
            "INSERT INTO admin_request_comments (request_id, author_id, author_kind, body)"
            " VALUES (:r, :a, :k, :b) RETURNING comment_id"),
            {"r": request_id, "a": me["operator_id"], "k": kind, "b": text_body}).scalar()
        # 올린 사람이 아닌 누군가 답하면(=owner) 「검토」가 시작된 것으로 본다.
        # 본인이 덧붙인 말로는 상태를 옮기지 않는다.
        if row["status"] == "접수" and row["created_by"] != me["operator_id"]:
            conn.execute(text("UPDATE admin_requests SET status='검토', updated_at=now()"
                               " WHERE request_id = :r"), {"r": request_id})
        else:
            conn.execute(text("UPDATE admin_requests SET updated_at=now() WHERE request_id=:r"),
                          {"r": request_id})
        _log(conn, "work_request_comment", str(request_id), {"author_kind": kind}, kind="request")

    return {"ok": True, "comment_id": cid, "note": "댓글을 남겼다."}


# ───────────────────────────── 취소 ─────────────────────────────
@router.post("/api/admin/requests/{request_id}/cancel")
def cancel_request(request_id: int):
    me = _me()
    with engine.begin() as conn:
        row = _fetch_row(conn, request_id, lock=True)
        if row is None or not _visible(row, me):
            raise _not_found()
        if row["created_by"] != me["operator_id"] and me["role"] != "owner":
            raise HTTPException(403, "본인이 올린 요청만 취소할 수 있다")
        if row["status"] not in ("접수", "검토"):
            raise HTTPException(409, f"지금 상태({row['status']})에서는 취소할 수 없다"
                                      " — 처리가 시작된 요청은 취소할 수 없다")
        conn.execute(text(
            "UPDATE admin_requests SET status='취소', cancelled_at=now(), updated_at=now()"
            " WHERE request_id = :r"), {"r": request_id})
        _log(conn, "work_request_cancel", str(request_id), {}, kind="request")

    return {"ok": True, "note": "요청을 취소했다."}


# ───────────────────────────── 캡처 업로드 · 서빙 ─────────────────────────────
async def _read_capped(request: Request, limit: int) -> bytes:
    """상한을 «넘는 순간» 끊는다 — `api/admin_profile_photo._read_capped()`와 같은 방식을
    이 파일의 한도(`CAPTURE_MAX_BYTES` = 3MB, 정책값이라 프로필 사진의 1MB 와 다르다)로
    재구현한다.
    """
    n = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        if not chunk:
            continue
        n += len(chunk)
        if n > limit:
            raise HTTPException(413, f"캡처는 {limit // 1024}KB 이하만 올릴 수 있다")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/admin/requests/{request_id}/captures")
async def upload_capture(request_id: int, request: Request):
    """캡처 한 장 등록 — 본문은 이미지 바이트 그대로(멀티파트 아님, 프로필 사진과 같은
    이유: 「읽기 전에 막는다」를 지키려면 `UploadFile`(다 받은 뒤 판정)을 쓸 수 없다).
    여러 장은 이 엔드포인트를 여러 번 부른다 — 화면이 붙여넣기마다 한 번씩 호출한다.
    """
    me = _me()
    with engine.connect() as conn:
        row = _fetch_row(conn, request_id)
    if row is None or not _visible(row, me):
        raise _not_found()
    if row["status"] in CLOSED_STATUSES:
        raise HTTPException(409, "이미 닫힌 요청에는 캡처를 더할 수 없다")

    # ㉠ 한 바이트도 읽기 전에 — 헤더가 이미 넘는다고 말하면 거기서 끝낸다.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > CAPTURE_MAX_BYTES:
        raise HTTPException(413, f"캡처는 {CAPTURE_MAX_BYTES // 1024}KB 이하만 올릴 수 있다"
                                  f" (보낸 크기 {int(declared) / 1024:.0f}KB)")
    # ㉡ 헤더는 거짓말할 수 있다 — 세면서 읽는다.
    raw = await _read_capped(request, CAPTURE_MAX_BYTES)

    if len(raw) < _MIN_CAPTURE_HEAD:
        raise HTTPException(400, "파일이 비어 있거나 너무 작다")
    ctype = _sniff(raw[:_MIN_CAPTURE_HEAD])
    if ctype is None:
        raise HTTPException(400, f"{ALLOWED_LABEL} 파일만 올릴 수 있다"
                                  " (파일 앞머리로 판정했다 — SVG 는 등록할 수 없다)")

    with engine.begin() as conn:
        seq = conn.execute(text(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM admin_request_captures WHERE request_id=:r"),
            {"r": request_id}).scalar()
        cid = conn.execute(text(
            "INSERT INTO admin_request_captures"
            " (request_id, seq, content_type, bytes, byte_size, uploaded_by)"
            " VALUES (:r, :s, :ct, :b, :n, :by) RETURNING capture_id"),
            {"r": request_id, "s": seq, "ct": ctype, "b": raw, "n": len(raw),
             "by": me["operator_id"]}).scalar()
        conn.execute(text("UPDATE admin_requests SET updated_at=now() WHERE request_id=:r"),
                      {"r": request_id})
        _log(conn, "work_request_capture", str(request_id),
             {"capture_id": cid, "content_type": ctype, "byte_size": len(raw)}, kind="request")

    return {"ok": True, "capture_id": cid, "seq": seq, "content_type": ctype,
            "byte_size": len(raw), "url": f"/api/admin/requests/{request_id}/captures/{cid}"}


@router.get("/api/admin/requests/{request_id}/captures/{capture_id}")
def get_capture(request_id: int, capture_id: int):
    me = _me()
    with engine.connect() as conn:
        row = _fetch_row(conn, request_id)
        if row is None or not _visible(row, me):
            raise _not_found()
        cap = conn.execute(text(
            "SELECT content_type, bytes FROM admin_request_captures"
            " WHERE capture_id = :c AND request_id = :r"),
            {"c": capture_id, "r": request_id}).mappings().first()
    if cap is None:
        raise HTTPException(404, "캡처를 찾을 수 없다")
    headers = {
        # 재인코딩(EXIF 제거 등)은 하지 않는다 — 이미지 라이브러리가 없다
        # (api/admin_profile_photo.py 모듈 docstring과 같은 사정). 대신 브라우저가
        # 이 바이트를 이미지 아닌 것으로 재해석·실행하지 못하게 헤더로 막는다.
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
        "Content-Security-Policy": "sandbox; default-src 'none'",
        "Cache-Control": "private, max-age=3600",
    }
    return Response(content=bytes(cap["bytes"]), media_type=cap["content_type"], headers=headers)


# ═══════════════════════ owner 전용 — 판정 · 처리 · 결재 ═══════════════════════
# 아래 넷은 전부 `/api/admin/request-decisions/...` 다 — `api/auth.py`의
# `OWNER_WRITE_PREFIXES`에 이 접두어가 등록돼 있어야 미들웨어가 막는다(모듈 docstring
# §URL 을 둘로 가른 이유 참조). 등록 여부와 무관하게 `_owner()`가 다시 확인한다.

class VerdictBody(BaseModel):
    verdict: str
    note: str


@router.post("/api/admin/request-decisions/{request_id}/verdict")
def set_verdict(request_id: int, body: VerdictBody):
    """하네스 판정 — 「작은 것」(→처리) / 「큰 것」(→결재대기). 근거(`note`)는 필수다 —
    없으면 사장님이 결재를 판단할 재료가 없다(요구사항 §⑧).
    """
    me = _owner()
    if body.verdict not in VERDICTS:
        raise HTTPException(400, f"판정은 {', '.join(VERDICTS)} 중 하나다")
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(400, "판정 근거를 남겨야 한다")

    with engine.begin() as conn:
        row = _fetch_row(conn, request_id, lock=True)
        if row is None:
            raise _not_found()
        if row["status"] not in ("접수", "검토"):
            raise HTTPException(409, f"지금 상태({row['status']})에서는 판정할 수 없다")
        new_status = "처리" if body.verdict == "작은 것" else "결재대기"
        conn.execute(text(
            "UPDATE admin_requests SET verdict=:v, verdict_note=:n, status=:s, updated_at=now()"
            " WHERE request_id=:r"),
            {"v": body.verdict, "n": note, "s": new_status, "r": request_id})
        conn.execute(text(
            "INSERT INTO admin_request_comments (request_id, author_id, author_kind, body)"
            " VALUES (:r, :a, '하네스', :b)"),
            {"r": request_id, "a": me["operator_id"], "b": f"[판정: {body.verdict}] {note}"})
        _log(conn, "work_request_verdict", str(request_id),
             {"verdict": body.verdict, "new_status": new_status}, kind="request")

    return {"ok": True, "status": new_status, "note": f"{body.verdict}으로 판정했다."}


class ResolveBody(BaseModel):
    success: bool
    note: str


@router.post("/api/admin/request-decisions/{request_id}/resolve")
def resolve_request(request_id: int, body: ResolveBody):
    """처리 결과 — 성공하면 「완료」로 전이(`result_note`에 남는다). **실패하면 상태를
    「완료」로 만들지 않는다** — 실패 사유는 댓글 스레드에 그대로 남는다(요구사항 §⑨).
    「처리」(작은 것) 또는 「승인」(큰 것, 사장님이 하라고 한 뒤) 두 상태에서만 부른다.
    """
    me = _owner()
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(400, "처리 결과를 남겨야 한다")

    with engine.begin() as conn:
        row = _fetch_row(conn, request_id, lock=True)
        if row is None:
            raise _not_found()
        if row["status"] not in ("처리", "승인"):
            raise HTTPException(409, f"지금 상태({row['status']})에서는 처리 결과를 남길 수 없다")
        if body.success:
            conn.execute(text(
                "UPDATE admin_requests SET status='완료', result_note=:n, resolved_at=now(),"
                " updated_at=now() WHERE request_id=:r"), {"n": note, "r": request_id})
            comment = f"[처리 완료] {note}"
        else:
            conn.execute(text("UPDATE admin_requests SET updated_at=now() WHERE request_id=:r"),
                          {"r": request_id})
            comment = f"[처리 실패] {note}"
        conn.execute(text(
            "INSERT INTO admin_request_comments (request_id, author_id, author_kind, body)"
            " VALUES (:r, :a, '하네스', :b)"),
            {"r": request_id, "a": me["operator_id"], "b": comment})
        _log(conn, "work_request_resolve", str(request_id),
             {"success": body.success}, kind="request")

    return {"ok": True, "success": body.success,
            "note": "처리를 완료로 남겼다." if body.success else
                    "실패를 기록했다 — 상태를 완료로 만들지 않았다."}


class DecisionNoteBody(BaseModel):
    note: str | None = None


@router.post("/api/admin/request-decisions/{request_id}/approve")
def approve_request(request_id: int, body: DecisionNoteBody):
    me = _owner()
    with engine.begin() as conn:
        row = _fetch_row(conn, request_id, lock=True)
        if row is None:
            raise _not_found()
        if row["status"] != "결재대기":
            raise HTTPException(409, f"지금 상태({row['status']})에서는 승인할 수 없다"
                                      " — 이미 처리된 요청일 수 있다")
        conn.execute(text(
            "UPDATE admin_requests SET status='승인', decided_by=:me, decided_at=now(),"
            " updated_at=now() WHERE request_id=:r"), {"me": me["operator_id"], "r": request_id})
        note = (body.note or "").strip()
        conn.execute(text(
            "INSERT INTO admin_request_comments (request_id, author_id, author_kind, body)"
            " VALUES (:r, :a, '사장님', :b)"),
            {"r": request_id, "a": me["operator_id"],
             "b": "[승인]" + (f" {note}" if note else "")})
        _log(conn, "work_request_approve", str(request_id), {}, kind="request")

    return {"ok": True, "note": "승인했다 — 하네스가 고치고 배포되면 완료로 전이한다."}


class RejectBody(BaseModel):
    reason: str


@router.post("/api/admin/request-decisions/{request_id}/reject")
def reject_request(request_id: int, body: RejectBody):
    """반려 — **사유가 없으면 저장 자체가 막힌다**(애플리케이션에서 먼저 400, DB
    CHECK(`ck_admin_requests_reject_reason`)가 한 번 더 막는다). 기존 `product_reviews`의
    반려(보류+텍스트, 실사용 0건)를 반복하지 않는다 — 별도 상태 + 전용 컬럼.
    """
    me = _owner()
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "반려 사유를 입력해야 한다")
    if len(reason) > 2000:
        raise HTTPException(400, "반려 사유는 2,000자 이하로 입력해야 한다")

    with engine.begin() as conn:
        row = _fetch_row(conn, request_id, lock=True)
        if row is None:
            raise _not_found()
        if row["status"] in CLOSED_STATUSES:
            raise HTTPException(409, f"지금 상태({row['status']})에서는 반려할 수 없다"
                                      " — 이미 처리된 요청입니다")
        conn.execute(text(
            "UPDATE admin_requests SET status='반려', reject_reason=:rs, decided_by=:me,"
            " decided_at=now(), updated_at=now() WHERE request_id=:r"),
            {"rs": reason, "me": me["operator_id"], "r": request_id})
        conn.execute(text(
            "INSERT INTO admin_request_comments (request_id, author_id, author_kind, body)"
            " VALUES (:r, :a, '사장님', :b)"),
            {"r": request_id, "a": me["operator_id"], "b": f"[반려] {reason}"})
        _log(conn, "work_request_reject", str(request_id), {"reason": reason}, kind="request")

    return {"ok": True, "note": "반려했다 — 사유가 함께 기록됐다."}


class HoldBody(BaseModel):
    reason: str | None = None


@router.post("/api/admin/request-decisions/{request_id}/hold")
def hold_request(request_id: int, body: HoldBody):
    """보류 — 사유는 선택이다(요구사항 §⑦). 길어지면 「방치」 배지가 대신 알린다."""
    me = _owner()
    reason = (body.reason or "").strip() or None
    with engine.begin() as conn:
        row = _fetch_row(conn, request_id, lock=True)
        if row is None:
            raise _not_found()
        if row["status"] in CLOSED_STATUSES:
            raise HTTPException(409, f"지금 상태({row['status']})에서는 보류할 수 없다"
                                      " — 이미 처리된 요청입니다")
        conn.execute(text(
            "UPDATE admin_requests SET status='보류', hold_reason=:rs, decided_by=:me,"
            " decided_at=now(), updated_at=now() WHERE request_id=:r"),
            {"rs": reason, "me": me["operator_id"], "r": request_id})
        conn.execute(text(
            "INSERT INTO admin_request_comments (request_id, author_id, author_kind, body)"
            " VALUES (:r, :a, '사장님', :b)"),
            {"r": request_id, "a": me["operator_id"],
             "b": "[보류]" + (f" {reason}" if reason else " 나중에 다시 봅니다")})
        _log(conn, "work_request_hold", str(request_id), {"reason": reason}, kind="request")

    return {"ok": True, "note": "보류했다 — 나중에 다시 본다."}
