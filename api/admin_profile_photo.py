"""ADM-SYS-022 내 정보 — 프로필 사진 등록·교체·삭제·열람 (사장님 확정 2026-08-17).

■ 사장님이 확정한 넷
    ① 사진 저장     **표를 하나 새로 만든다** → `admin_operator_photos`
                    (마이그레이션 `db/migrations/versions/0060_admin_operator_photos.py`)
    ② 상단바 아바타  띄운다 — 39개 공통 셸. **이번 물결이 아니다**(화면·셸 미착수)
    ③ 열람 범위     **전 운영자가 서로 본다** → 아래 `/operators/{id}/photo` 는
                    로그인한 운영자면 등급 불문 200 (`api/auth.required_role` 예외 참조)
    ④ 크기 상한     **1MB** → `MAX_PHOTO_BYTES`

■ ★ 왜 `admin_profile.py` 가 아니라 별도 파일인가
  이 모듈이 다루는 것은 **바이너리**다 — 나머지 「내 정보」 API 는 전부 JSON 이다.
  `admin_profile.py` 는 `_shape()`/`identity_reasons()` 라는 **JSON 응답 모양의 단일
  원천**이라 그 파일에 스트리밍 업로드·ETag·매직 넘버 판정을 섞으면 두 관심사가 한
  파일에서 자란다. 이름은 `admin_<도메인>` 규칙 그대로다(`admin_price_history` ·
  `admin_category_mapping` 과 같은 결). ⚠ `admin_my_profile.py` 로 짓지 «않았다» —
  기존 `admin_profile.py` 와 한 글자 차이라 다음 사람이 어느 쪽을 고칠지 헷갈린다.
  ⚠ `api/main.py` 는 고치지 않는다 — 라우터 **자동 등록**이라 `api/*.py` 에
  module-level `router` 만 있으면 실린다(`main.py` `_discover_routers`, 2026-08-13).

■ ★ 1MB 는 «서버가» 막는다 — 그것도 «읽어 들이기 전에»
  화면만 막으면 안 막은 것이다(화면은 고쳐서 보낼 수 있다). 그리고 **다 받고 나서 재면
  이미 늦다** — 그 시점엔 100MB 가 이미 프로세스 메모리에 있다. 그래서 둘 다 한다:
    ㉠ `Content-Length` 를 **한 바이트도 읽기 전에** 본다 → 넘으면 즉시 413
    ㉡ 헤더는 거짓말할 수 있고 chunked 면 아예 없다 → **스트림을 조각마다 세면서**
       상한을 넘는 «순간» 끊는다. 최대 메모리 = 1MB + 조각 하나.
  ㉠만 있으면 헤더를 지운 요청에 뚫리고, ㉡만 있으면 막기 전에 1MB 를 다 받는다.

■ ★ 형식은 «파일 앞머리»로 판정한다 — 확장자도 Content-Type 도 믿지 않는다
  둘 다 보내는 쪽이 정하는 값이다. `api/auth.py` 의 `provider` 를 그대로 믿어 지금
  관리자 신원 검증이 없는 것과 **같은 부류의 실수**다 — 반복하지 않는다.
  DB 에 저장하는 `content_type` 은 **우리가 판정한 값**이지 받은 값이 아니다.
  · **SVG 는 명시적으로 거절된다** — 앞머리가 어느 서명과도 안 맞아 400 이다. SVG 는
    스크립트를 품을 수 있고, 같은 출처에서 서빙되면 그 스크립트가 **관리자 세션
    문맥에서 돈다.** 이건 사고가 아니라 설계다.

■ ⚠ 리사이즈·재인코딩(EXIF 제거·크기 정규화)은 «하지 않는다» — 왜 안 하는지
  **저장소에 이미지 라이브러리가 없다**(실측 2026-08-17: `requirements.txt` 전수 ·
  `.venv` 에 PIL 미설치). Pillow 등을 새로 넣는 것은 사장님이 「의존성을 늘리지 마라」로
  정하셨다. 그래서 **원본 바이트를 그대로 보관**한다.
  ⚠ 그 대가를 적어 둔다: ㉠ EXIF(촬영 위치·기기)가 그대로 남는다 ㉡ 폴리글롯 파일
  (앞머리는 PNG 인데 뒤에 다른 것이 붙은 파일)을 앞머리 검사만으로는 완전히 못 막는다.
  ㉡ 의 실효 위험은 **응답 헤더로** 줄인다(아래 `_photo_response`: `X-Content-Type-Options`
  · `Content-Disposition: inline` · CSP `sandbox`) — 브라우저가 이 바이트를 이미지
  아닌 것으로 «재해석»하지 못하게 한다. 라이브러리를 넣기로 결정되면 이 주석이 그 자리다.

■ 사진은 원장이 아니다 — 삭제는 «실제로» 지운다 (정의서 판정)
  원장 규약이 지키는 것은 「사실의 이력」이고 **사진은 본인의 개인 자료**다. 지운 사진을
  계속 갖고 있는 것은 필요 없어진 개인정보를 보관하는 것이다(ERD §3.9 「우리가 갖지 않은
  정보는 유출될 수 없다」). **다만 행위는 남긴다** — 비밀번호와 같은 결이다
  (원문은 안 남기고 활동 로그는 남는다). **자료는 지우고 사실은 남긴다.**

■ 권한
  · 등록·교체·삭제 = **본인만.** 경로가 `/my-profile/photo` 이고 대상이 세션의 나다 —
    남의 id 를 받는 자리가 아예 없다.
  · 열람 = **로그인한 운영자 전체**(사장님 확정 ③).
  ⚠ **owner 가 남의 사진을 지우거나 대신 올리는 경로는 «짓지 않았다»** — 정의서
    결정대기 ⑤ 이고 사장님은 「전 운영자 열람」만 답하셨다. **미정이다.** 필요하면
    「운영자·권한」(ADM-SYS-020) 쪽에 별도로 짓는다(그쪽이 남의 계정을 다루는 화면이다).

■ 표가 아직 없다 — 그것을 「사진 없음」이라고 «말하지 않는다»
  0060 은 파일만 만들고 적용하지 않았다(사장님 지시). 그래서 네 경로 모두
  **503 `photo_schema_missing`** 을 준다 — 404 `no_photo` 와 **다른 사실**이다.
  0051(기기 기억)이 `ready:false` 로 같은 구분을 한 것과 같은 판단이다.
"""
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import text

from .admin_orders import _log
from .auth import current_operator
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin")

# ★ 상한 단일 원천. DB 에 CHECK 로 박지 않았다 — 정책값이라 나중에 올릴 수 있고,
# 같은 수가 두 곳에 살면 언젠가 어긋난다(0060 docstring §CHECK 참조).
MAX_PHOTO_BYTES = 1024 * 1024          # 1MB (사장님 확정 2026-08-17 ④)

# 앞머리 서명 — 이 목록이 「허용 형식」의 단일 원천이다(DB CHECK 로 복제하지 않는다).
# WebP 는 `RIFF....WEBP` 라 연속 서명이 아니다 → 아래 `_sniff()`가 따로 본다.
_MAGIC = ((b"\xff\xd8\xff", "image/jpeg"),
          (b"\x89PNG\r\n\x1a\n", "image/png"))
ALLOWED_LABEL = "JPEG · PNG · WebP"

# 앞머리 판정에 필요한 최소 길이 — WebP 가 12바이트로 가장 길다.
_MIN_HEAD = 12

_table_ready: bool | None = None


def _photo_table_ready() -> bool:
    """마이그레이션 0060 이 이 DB 에 실제로 적용됐는가.

    `api/auth.py` `_schema_ready()`(0051 용)와 **같은 방식**이다 — 미적용 상태에서
    없는 표를 SELECT 하면 500 이 나고, 그러면 화면은 「서버 오류」만 보게 된다.
    여기서는 죽지 않고 **이유 있는 503**을 준다.
    결과는 프로세스 안에서 캐싱한다(스키마는 이 프로세스가 떠 있는 동안 바뀌지 않는다 —
    마이그레이션은 항상 재배포로 적용된다).
    """
    global _table_ready
    if _table_ready is None:
        with engine.connect() as conn:
            _table_ready = conn.execute(
                text("SELECT to_regclass('admin_operator_photos')")).scalar() is not None
    return _table_ready


def _need_table() -> None:
    if not _photo_table_ready():
        # 404(사진 없음)와 «다른 사실»이다 — 적용 안 된 것을 「없다」고 말하면 지어낸 것이다.
        raise HTTPException(503, {"error": "photo_schema_missing",
                                  "message": "프로필 사진 기능이 아직 이 서버에 적용되지 않았습니다"})


def _me():
    me = current_operator()
    if not me:
        raise HTTPException(401, "로그인이 필요합니다")
    return me


def _sniff(head: bytes) -> str | None:
    """파일 앞머리로 형식을 판정한다. 모르면 None — 추측하지 않는다."""
    for sig, ctype in _MAGIC:
        if head.startswith(sig):
            return ctype
    # WebP: 0-3 'RIFF' · 4-7 파일크기(값은 안 본다) · 8-11 'WEBP'
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _etag(operator_id: int, uploaded_at, byte_size: int) -> str:
    """바뀐 사진이 옛 사진으로 보이면 결함이다 — 그것을 막는 값.

    **바이트를 읽지 않고** 만든다: 교체는 언제나 `uploaded_at` 을 새로 찍으므로
    (마이크로초 정밀도) 그 셋이 바뀌면 내용도 바뀐 것이다. 그래서 조건부 GET 은
    메타 한 줄만 읽고 304 로 답할 수 있다 — BYTEA 를 꺼내지 않는다.
    해시 컬럼을 따로 두지 «않은» 이유가 이것이다(정의서가 제안한 여섯 컬럼 그대로).
    """
    return '"%d-%s-%d"' % (operator_id, uploaded_at.strftime("%Y%m%d%H%M%S%f"), byte_size)


def _meta(conn, operator_id: int):
    """메타만 — `bytes` 를 SELECT 하지 않는다(조건부 GET 이 1MB 를 헛되이 읽지 않게)."""
    return conn.execute(text(
        "SELECT operator_id, content_type, byte_size, uploaded_at, uploaded_by"
        " FROM admin_operator_photos WHERE operator_id = :id"),
        {"id": operator_id}).mappings().first()


def _no_photo() -> HTTPException:
    """사진이 없을 때는 **404 다**(사장님 지시 §4 「정해서 문서에 적어라」).

    왜 「빈 응답 200」이 아닌가: 이 경로는 **바이너리를 돌려주는 자리**라 「빈 이미지」라는
    것이 없다. 0바이트 200 을 주면 `<img>` 는 깨진 이미지를 그리고 `onerror` 도 안 뜬다 —
    화면이 「사진 없음」을 알아챌 방법이 사라진다. 404 면 `<img onerror>` 하나로
    이니셜 대체가 되고, fetch 로 부르는 쪽은 `res.status` 로 갈린다.
    ⚠ 화면은 **세 가지를 구분해야 한다**: 404 `no_photo`(없다) · 503
    `photo_schema_missing`(아직 기능이 없다) · 401(로그인이 끊겼다).
    """
    return HTTPException(404, {"error": "no_photo", "message": "등록된 사진이 없습니다"})


def _photo_response(request: Request, r_meta, raw: bytes | None) -> Response:
    """사진 한 장을 «바이너리 그대로» 내보낸다 — base64 로 JSON 에 싣지 않는다.

    base64 는 1/3 을 부풀리고, 브라우저의 이미지 캐시·조건부 요청·`<img src>` 를 전부
    못 쓰게 만든다(화면이 직접 디코드해야 한다). 그래서 이 경로는 이미지 자체다.
    """
    etag = _etag(r_meta["operator_id"], r_meta["uploaded_at"], r_meta["byte_size"])
    headers = {
        "ETag": etag,
        # `no-cache` 는 「캐시하지 마라」가 아니라 「쓰기 전에 반드시 물어봐라」다 —
        # 그래서 사진을 바꾸면 즉시 새것이 보이고, 안 바꿨으면 304 로 끝난다.
        # `private` — 공용 프록시가 남의 관리자 사진을 들고 있으면 안 된다.
        "Cache-Control": "private, no-cache, max-age=0, must-revalidate",
        # 아래 셋은 재인코딩을 «안 하기로» 한 대가를 줄인다(모듈 docstring ⚠ 참조):
        # 브라우저가 이 바이트를 이미지 아닌 것으로 재해석하거나 실행하지 못하게 한다.
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }
    if request.headers.get("if-none-match") == etag:
        # 조건부 요청 — 여기까지 오는 동안 `bytes` 는 한 번도 읽지 않았다.
        return Response(status_code=304, headers=headers)
    if raw is None:                       # 호출자가 메타만 들고 온 경우(조건부 아님)
        raise HTTPException(500, "사진 본문을 읽지 못했습니다")
    return Response(content=bytes(raw), media_type=r_meta["content_type"], headers=headers)


async def _read_capped(request: Request) -> bytes:
    """상한을 «넘는 순간» 끊으면서 본문을 읽는다 — 모듈 docstring ㉡.

    최대로 들고 있는 양 = 상한 + 조각 하나. 다 받아 놓고 재는 것과 이것이 다른 점이다.
    """
    n = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        if not chunk:
            continue
        n += len(chunk)
        if n > MAX_PHOTO_BYTES:
            # **여기서 끊는다** — 남은 바이트를 더 받지 않는다.
            raise HTTPException(413, f"사진은 {MAX_PHOTO_BYTES // 1024}KB 이하만 등록할 수 있습니다")
        chunks.append(chunk)
    return b"".join(chunks)


# ───────────────────────────── 등록 · 교체 ─────────────────────────────
@router.post("/my-profile/photo")
async def upload_my_photo(request: Request):
    """본인 사진 등록·교체 — **본문이 이미지 바이트 그대로**다(multipart 아님).

    왜 multipart 가 아닌가: `UploadFile` 은 FastAPI 가 **본문을 다 받은 뒤에** 핸들러를
    부른다(`api/admin_catalog_import.py` `_read_upload` 가 그래서 `await f.read()` 뒤에
    크기를 잰다 — 64MB CSV 에는 맞는 방식이지만 여기서는 「읽기 전에 막아라」를 못 지킨다).
    본문을 날것으로 받으면 **첫 조각부터 우리가 센다.**
    화면은 `fetch(url, {method:'POST', body: file})` 한 줄이면 된다.
    """
    me = _me()
    _need_table()

    # ㉠ 한 바이트도 읽기 전에 — 헤더가 이미 넘는다고 «말하면» 거기서 끝낸다.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_PHOTO_BYTES:
        raise HTTPException(413, f"사진은 {MAX_PHOTO_BYTES // 1024}KB 이하만 등록할 수 있습니다"
                                 f" (보낸 크기 {int(declared) / 1024:.0f}KB)")

    # ㉡ 헤더는 거짓말할 수 있고 chunked 면 없다 — 세면서 읽는다.
    raw = await _read_capped(request)

    if len(raw) < _MIN_HEAD:
        raise HTTPException(400, "파일이 비어 있거나 너무 작습니다")
    ctype = _sniff(raw[:_MIN_HEAD])
    if ctype is None:
        # 확장자·Content-Type 을 믿지 않는다 — 앞머리가 답이다(SVG 도 여기서 걸린다).
        raise HTTPException(400, f"{ALLOWED_LABEL} 파일만 등록할 수 있습니다"
                                 " (파일 앞머리로 판정했습니다)")

    with engine.begin() as conn:
        before = _meta(conn, me["operator_id"])
        conn.execute(text(
            "INSERT INTO admin_operator_photos"
            " (operator_id, content_type, bytes, byte_size, uploaded_at, uploaded_by)"
            " VALUES (:id, :ct, :b, :n, now(), :by)"
            " ON CONFLICT (operator_id) DO UPDATE SET"
            "   content_type = EXCLUDED.content_type, bytes = EXCLUDED.bytes,"
            "   byte_size = EXCLUDED.byte_size, uploaded_at = now(),"
            "   uploaded_by = EXCLUDED.uploaded_by"),
            {"id": me["operator_id"], "ct": ctype, "b": raw, "n": len(raw),
             "by": me["operator_id"]})
        # 원문(바이트)은 로그에 넣지 않는다 — 비밀번호와 같은 결이다.
        _log(conn, "operator_photo_set", me.get("email") or str(me["operator_id"]),
             {"content_type": ctype, "byte_size": len(raw),
              "replaced": before is not None,
              "before_byte_size": before["byte_size"] if before else None},
             kind="operator")
        after = _meta(conn, me["operator_id"])

    return {"ok": True, "content_type": ctype, "byte_size": len(raw),
            "uploaded_at": iso(after["uploaded_at"]),
            "replaced": before is not None,
            "note": ("사진을 교체했습니다." if before else "사진을 등록했습니다.")
                    + " 삭제하면 되돌릴 수 없습니다."}


# ───────────────────────────── 삭제 ─────────────────────────────
@router.delete("/my-profile/photo")
def delete_my_photo():
    """실제로 지운다 — 원장이 아니다(모듈 docstring 참조). **되돌리기는 없다.**"""
    me = _me()
    _need_table()
    with engine.begin() as conn:
        before = _meta(conn, me["operator_id"])
        if before is None:
            raise _no_photo()
        conn.execute(text("DELETE FROM admin_operator_photos WHERE operator_id = :id"),
                     {"id": me["operator_id"]})
        # 자료는 지우고 «사실은 남긴다».
        _log(conn, "operator_photo_delete", me.get("email") or str(me["operator_id"]),
             {"content_type": before["content_type"], "byte_size": before["byte_size"],
              "uploaded_at": iso(before["uploaded_at"])}, kind="operator")
    return {"ok": True, "note": "사진을 삭제했습니다 — 되돌릴 수 없습니다."}


# ───────────────────────────── 열람 ─────────────────────────────
@router.get("/my-profile/photo")
def get_my_photo(request: Request):
    """본인 사진 — 바이너리 그대로."""
    me = _me()
    _need_table()
    with engine.connect() as conn:
        m = _meta(conn, me["operator_id"])
        if m is None:
            raise _no_photo()
        etag = _etag(m["operator_id"], m["uploaded_at"], m["byte_size"])
        if request.headers.get("if-none-match") == etag:
            return _photo_response(request, m, None)     # BYTEA 를 읽지 않고 304
        raw = conn.execute(text(
            "SELECT bytes FROM admin_operator_photos WHERE operator_id = :id"),
            {"id": me["operator_id"]}).scalar()
    return _photo_response(request, m, raw)


@router.get("/operators/{operator_id}/photo")
def get_operator_photo(operator_id: int, request: Request):
    """남의 사진 — **로그인한 운영자면 등급 불문 200**(사장님 확정 ③ 「전 운영자가 서로 본다」).

    ⚠ `/api/admin/operators` 는 `required_role()` 에서 **조회조차 owner** 다(계정 목록은
    민감하다). 그래서 이 경로 하나만 예외로 열려 있다 — 예외는 `api/auth.py`
    `required_role()` 이 **한 곳에서** 판정한다(여기서 또 판정하지 않는다. 두 곳이
    갈리면 한쪽만 고치는 사고가 난다).

    ⚠ **계정이 없는 것과 사진이 없는 것을 «구분하지 않는다»** — 둘 다 404 `no_photo` 다.
    viewer 등급은 운영자 목록을 볼 수 없는데(owner 전용) 여기서 답을 갈라 주면
    **id 를 세어 「이 번호에 계정이 있다」를 알아낼 수 있다.** 사진 열람을 연 것이지
    계정 존재 여부를 연 것이 아니다.
    """
    _me()
    _need_table()
    with engine.connect() as conn:
        m = _meta(conn, operator_id)
        if m is None:
            raise _no_photo()
        etag = _etag(m["operator_id"], m["uploaded_at"], m["byte_size"])
        if request.headers.get("if-none-match") == etag:
            return _photo_response(request, m, None)     # BYTEA 를 읽지 않고 304
        raw = conn.execute(text(
            "SELECT bytes FROM admin_operator_photos WHERE operator_id = :id"),
            {"id": operator_id}).scalar()
    return _photo_response(request, m, raw)
