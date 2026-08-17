# -*- coding: utf-8 -*-
"""고객 화면 AI 의 접근 게이트 -- 「누구의 것인가」와 「몇 번까지인가」 (2026-08-17 사장님 확정).

`api/main.py`는 module-level `router`(APIRouter)가 있는 모듈만 싣는다(main.py L52).
이 모듈은 로직만 있고 `router`가 없어 자동 등록에서 빠진다 -- 의도한 대로다.

■ 왜 «한 벌»인가 (새 파일을 만든 근거)
  이 게이트를 쓰는 자리가 셋이다 -- `api/talk.py`(파싱) · `api/recommend.py`(견적·설명) ·
  `api/handoff.py`(인계). 횟수 제한은 **카운터가 하나여야 뜻이 있다**: 파일마다 복제하면
  같은 방문자가 파싱 5회 + 설명 5회를 따로 태워 실제로는 10회를 쓴다. CANON §1
  「정본을 복제하지 않는다」가 정확히 이 상태를 금지한다. 그래서 카운터·열쇠 생성·
  대조를 여기 한 곳에 둔다.

■ 열쇠 -- 새로 발명하지 않았다
  `secrets.token_urlsafe(24)` = 24바이트(192비트) 난수, 32자 URL-safe 문자열.
  **`api/visitor.py` L41 의 방문자 쿠키(`pc_vid`)와 같은 생성기·같은 길이**다. 그 값도
  「추측하면 남의 방문 이력이 열리는」 자리라 요구 수준이 같고, 이 열쇠는 **링크에 실려
  다니므로** URL-safe 여야 한다(`token_hex`보다 이쪽이 맞다 -- `api/auth.py` L248 의
  관리자 세션 쿠키는 링크에 들어가지 않아 hex 로도 됐다).
  길이를 늘리지 않은 이유: 192비트는 전수 탐색이 불가능하고, 링크가 길수록 사람이
  잘라 붙이다 깨뜨린다.

■ 열쇠가 없는 행(NULL)은 «닫힌» 것이다 -- 백필하지 않는다
  마이그레이션 0055 는 기존 `consult_sessions`·`handoffs` 행에 열쇠를 채우지 «않는다».
  그 행의 주인은 열쇠를 받은 적이 없으므로, 무작위 값을 채워 넣어도 **아무도 열 수 없는
  것은 똑같은데 「누군가 열쇠를 가진 행」처럼 보이게 된다.** CANON §2-3
  「모르는 것을 지어내지 않는다」 · `api/visitor.py`의 「과거는 소급하지 않는다」와 같은
  판단이다. NULL 은 그 자체로 «게이트 도입 이전 행 -- 링크로 열 수 없음»을 뜻한다.

■ 스키마가 아직 없을 수 있다 (0055 는 파일만 만든다 -- DBA 가 적용한다)
  컬럼이 없는 DB에서 `SELECT access_key`를 하면 500 이 난다. 그래서 컬럼 유무를 먼저
  재고(`column_ready`), 없으면 **503 으로 그 사실을 그대로 말한다** -- 조용히 열어 두면
  「막았다고 보고했는데 실제로는 안 막힌」 상태가 되고, 조용히 닫으면 「남의 견적」과
  「스키마 미적용」을 화면이 구분하지 못한다(CLAUDE.md §실패를 삼키지 않는다).

■ 횟수 제한 -- 축·저장 자리
  축 = **방문자 키**(`users.user_id`, `api/visitor.py`). 쿠키가 없어 방문자 키를 못 읽는
  요청은 **접속 IP**로 센다. 방문자 키를 여기서 «발급»하지는 않는다
  (`visitor.resolve(conn, request, None)` -- response 를 넘기지 않으면 읽기 전용) --
  발급하면 쿠키를 버리는 클라이언트가 요청마다 `users` 행을 만들어 표를 오염시킨다.
    ⚠ 그래서 **쿠키를 버리는 클라이언트는 IP 축으로만 잡힌다.** 같은 IP 뒤의 여러 사람이
      NAT 로 묶이면 서로의 몫을 먹는다 -- 맞바꿈이고, 지금은 IP 쪽 한도를 방문자 한도와
      같게 두되 이 사실을 보고에 적었다.
  저장 자리 = **프로세스 안의 슬라이딩 윈도우**. `api_cost_logs`(llm.py 가 세는 표)에는
  호출자 컬럼이 아예 없어(`0054`까지의 스키마 실측: log_id·provider·model·tokens_in·
  tokens_out·cost_usd·created_at·status·error_message) 방문자별로 셀 수가 없다.
  ⚠ `rate_limit_policies`(key varchar PK · per_minute · per_day)는 **정책**표이지
    카운터표가 아니다 -- 그래서 «몇 번까지인가»는 거기서 읽고(운영자가 코드 수정 없이
    조절할 수 있다), «지금 몇 번 썼나»만 프로세스가 센다.
  프로세스 재시작이면 카운터가 0 이 된다. 뒷단에 `api/llm.py`의 프로바이더 단위 캡
  (분당 10 · 일 500 · $2/일)이 그대로 남아 있어 총액은 여전히 막힌다.

■ 비밀값을 로그·응답에 싣지 않는다 (CANON §2-5)
  이 모듈은 열쇠 «값»을 절대 로그에 찍지 않는다 -- 있었는지(`provided=yes|no`)만 남긴다.
  로그 문자열은 ASCII 기호만 쓴다(서버 stdout 이 cp949).
"""
import logging
import secrets
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import text

from . import visitor

log = logging.getLogger(__name__)

KEY_BYTES = 24                 # api/visitor.py L41 과 같은 값 -- 32자 URL-safe(192비트)
POLICY_KEY = "visitor.ai"      # rate_limit_policies.key -- 프로바이더 키와 겹치지 않는다
HEADER = "X-Access-Key"        # 링크(?k=)로 못 실을 때 쓰는 자리(XHR)

# 방문자 한 사람의 기본 한도.
#   근거 -- **한 상담이 실제로 몇 번 부르는가**를 재서 잡았다.
#     S1 자유입력 파싱: 화면의 정규식 파서가 0건일 때만 부른다(api/talk.py 모듈 docstring).
#     S2 근거 문구:     티어 3종, 탭을 눌러야 부르고 화면·서버 양쪽에 캐시가 있다
#                       (mockups/mvp1/s2-result.html 의 `WHY` · recommend.py `_EXPLAIN_CACHE`).
#   => 한 번의 견적 사이클이 태우는 LLM 호출의 최대치는 **4회**(파싱 1 + 설명 3).
#   per_minute=5  한 사이클(4)을 1분 안에 다 돌려도 걸리지 않는 최소값. 프로바이더 기본
#                 분당 10 의 절반이라, 한 사람이 분당 예산의 절반을 넘게 쥘 수 없다.
#   per_day=40    한 사이클 4회 기준 하루 10 사이클. 프로바이더 일 500 을 혼자 태우려면
#                 최소 13명이 필요해진다 -- **지금은 1명이면 된다는 것이 이번 구멍**이다.
DEFAULT_PER_MINUTE = 5
DEFAULT_PER_DAY = 40

_KST = timezone(timedelta(hours=9))    # llm.py 의 일일 경계와 같은 기준(서울 자정)

_MAX_SUBJECTS = 20000                  # 메모리 상한 -- 넘으면 가장 오래된 축부터 버린다
_HITS: "OrderedDict[str, deque]" = OrderedDict()

_policy_cache: dict = {"at": None, "per_minute": None, "per_day": None, "default": True}
_POLICY_TTL_SEC = 60

_col_cache: dict = {}                  # "table.column" -> (ready: bool, checked_at)
_COL_RECHECK_SEC = 30                  # False 만 다시 잰다(DBA 가 도중에 적용할 수 있다)


# ============================================================================
# 열쇠
# ============================================================================
def new_key() -> str:
    """추측 못 할 열쇠 한 개. `api/visitor.py` 와 같은 생성기를 쓴다."""
    return secrets.token_urlsafe(KEY_BYTES)


def key_from_request(request: Request, q: str | None) -> str | None:
    """요청이 들고 온 열쇠 -- 쿼리 `?k=` 우선, 없으면 `X-Access-Key` 헤더.

    ⚠ 쿼리스트링은 **nginx access log 에 그대로 남는다**(`deploy/nginx-popcorn.conf`).
      사장님이 "링크에 넣는다"고 확정하셨으므로 `?k=`를 지우지 않되, 화면이 XHR 로
      부를 때는 헤더를 쓰면 로그에 남지 않는다 -- 그래서 두 자리를 다 연다.
    """
    v = (q or "").strip()
    if v:
        return v
    v = (request.headers.get(HEADER) or "").strip()
    return v or None


def matches(stored: str | None, provided: str | None) -> bool:
    """상수 시간 대조. 저장된 열쇠가 없으면(NULL) **언제나 거짓** -- 닫힌 행이다."""
    if not stored or not provided:
        return False
    return secrets.compare_digest(str(stored), str(provided))


def column_ready(conn, table: str, column: str = "access_key") -> bool:
    """그 컬럼이 실제로 있는가(0055 적용 여부). True 는 영구 캐시, False 만 재측정."""
    ck = f"{table}.{column}"
    ready, at = _col_cache.get(ck, (False, None))
    if ready:
        return True
    now = datetime.now(timezone.utc)
    if at is not None and (now - at).total_seconds() < _COL_RECHECK_SEC:
        return False
    found = conn.execute(text(
        "SELECT 1 FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"),
        {"t": table, "c": column}).first() is not None
    _col_cache[ck] = (found, now)
    if not found:
        log.warning("[gate] column %s.%s is missing - migration 0055 not applied yet",
                    table, column)
    return found


def gate_unavailable(table: str) -> HTTPException:
    """스키마 미적용을 «그대로» 말한다. 조용히 열지도 닫지도 않는다."""
    return HTTPException(503, {
        "error": "gate_unavailable",
        "table": table,
        "detail": "접근 게이트 스키마 미적용 - 마이그레이션 0055 적용 필요"})


def forbidden(reason: str, detail: str) -> HTTPException:
    """소유자 확인 실패. 횟수 초과(429)와 «다른» 응답이어야 한다."""
    return HTTPException(403, {"error": "forbidden", "reason": reason, "detail": detail})


def require_session_owner(conn, session_id: int, provided: str | None, *,
                          what: str, not_found_detail: str) -> None:
    """이 요청이 그 상담(`consult_sessions`)의 «주인»인가. 아니면 던진다.

    **상담을 재료로 쓰는 경로는 전부 이 함수 하나를 부른다** — 근거 문구 생성
    (`api/recommend.recommend_explain`) · 부품 교체 적용(`api/swap.apply`).
    각자 검사를 베끼면 한쪽만 고쳐지는 날이 온다(CANON §1). 던지는 것:

        503 gate_unavailable   마이그레이션 0055 미적용 — 게이트를 세울 수 없다
        404 not_found_detail   그 session_id 가 없다 (부르는 쪽이 문구를 정한다)
        403 no_access_key      게이트 도입 이전 상담이라 열쇠 자체가 NULL — 아무도 못 연다
        403 access_key_missing / access_key_mismatch
    """
    if not column_ready(conn, "consult_sessions"):
        raise gate_unavailable("consult_sessions")
    row = conn.execute(text(
        "SELECT access_key FROM consult_sessions WHERE session_id = :s"),
        {"s": session_id}).mappings().first()
    if row is None:
        raise HTTPException(404, not_found_detail)
    stored = row["access_key"]
    if not stored:
        log.info("[gate] denied what=%s session=%s: stored key is NULL (pre-gate row)"
                 " provided=%s", what, session_id, "yes" if provided else "no")
        raise forbidden("no_access_key",
                        "게이트 도입 이전 상담이라 열쇠가 없습니다 - 견적을 다시 받아주세요")
    if not matches(stored, provided):
        log.info("[gate] denied what=%s session=%s: key mismatch provided=%s",
                 what, session_id, "yes" if provided else "no")
        raise forbidden("access_key_mismatch" if provided else "access_key_missing",
                        "이 견적의 열쇠가 아닙니다 - 본인 견적 링크로 다시 열어주세요")


# ============================================================================
# 횟수 제한
# ============================================================================
def _policy(conn) -> tuple:
    """(per_minute, per_day, 기본값인가). `rate_limit_policies` 를 60초 캐시한다."""
    now = datetime.now(timezone.utc)
    at = _policy_cache["at"]
    if at is not None and (now - at).total_seconds() < _POLICY_TTL_SEC:
        return _policy_cache["per_minute"], _policy_cache["per_day"], _policy_cache["default"]
    pm, pd, is_default = DEFAULT_PER_MINUTE, DEFAULT_PER_DAY, True
    try:
        r = conn.execute(text(
            "SELECT per_minute, per_day FROM rate_limit_policies WHERE key = :k"),
            {"k": POLICY_KEY}).mappings().first()
        if r is not None:
            # is not None 으로 명시 비교 -- 0 을 "값 없음"으로 오독하는 or-폴백을 피한다
            # (api/llm.py `_check_caps` 가 같은 함정을 같은 방식으로 피한다).
            if r["per_minute"] is not None:
                pm, is_default = int(r["per_minute"]), False
            if r["per_day"] is not None:
                pd, is_default = int(r["per_day"]), False
    except Exception as e:                                    # noqa: BLE001
        # 정책을 못 읽었다고 제한을 «푸는» 것은 조용한 실패다 -- 코드 기본값으로 계속 막는다.
        log.warning("[gate] rate_limit_policies read failed (%s: %s) - using code default",
                    type(e).__name__, e)
    _policy_cache.update({"at": now, "per_minute": pm, "per_day": pd, "default": is_default})
    return pm, pd, is_default


def subject_of(conn, request: Request) -> str:
    """이번 요청을 «누구»로 셀 것인가. 방문자 키를 읽되 **발급하지 않는다**.

    `visitor.resolve(conn, request, None)` -- response 를 넘기지 않으면 쿠키를 심지 않고
    있는 것만 읽는다(그 함수의 docstring 이 그렇게 밝힌다). 쿠키가 없으면 IP 로 센다.

    IP 는 `request.client.host` 를 그대로 쓴다 -- `X-Forwarded-For` 를 여기서 다시 읽지
    않는다. 배포는 uvicorn 을 `--proxy-headers --forwarded-allow-ips=127.0.0.1` 로 띄워
    ProxyHeadersMiddleware 가 이미 검증해 바꿔 둔 값이고, 여기서 헤더를 또 읽으면 그
    검증을 우회해 «클라이언트가 위조한 값을 믿는» 퇴행이 된다(`api/auth.py._client_ip`
    가 같은 이유로 같은 선택을 했다 -- 그 근거를 복제하지 않고 따른다).
    """
    uid = None
    try:
        uid = visitor.resolve(conn, request, None)
    except Exception:                                          # noqa: BLE001
        uid = None
    if uid:
        return "u:%d" % uid
    host = getattr(getattr(request, "client", None), "host", None)
    return "ip:%s" % (host or "unknown")


def _prune(dq: deque, now: datetime) -> None:
    day_lo = now.astimezone(_KST).replace(hour=0, minute=0, second=0, microsecond=0)
    floor = min(day_lo.astimezone(timezone.utc), now - timedelta(minutes=1))
    while dq and dq[0] < floor:
        dq.popleft()


def check_rate(conn, request: Request, *, what: str) -> str:
    """방문자별 호출 횟수 제한. 넘으면 **429**(소유자 확인 실패 403 과 다른 응답).

    통과하면 이번 호출을 «쓴 것으로» 세고 축 이름을 돌려준다. 부르는 쪽은 **실제로 돈이
    나가는 자리 직전**에만 부른다 -- 캐시로 답하는 요청은 비용이 0 이라 세지 않는다.
    """
    per_minute, per_day, is_default = _policy(conn)
    subject = subject_of(conn, request)
    now = datetime.now(timezone.utc)

    dq = _HITS.get(subject)
    if dq is None:
        dq = deque()
        _HITS[subject] = dq
        while len(_HITS) > _MAX_SUBJECTS:
            _HITS.popitem(last=False)     # 가장 오래 안 쓴 축부터 버린다(메모리 상한)
    _HITS.move_to_end(subject)
    _prune(dq, now)

    day_lo = now.astimezone(_KST).replace(
        hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    minute_lo = now - timedelta(minutes=1)
    n_minute = sum(1 for t in dq if t >= minute_lo)
    n_day = sum(1 for t in dq if t >= day_lo)
    note = " (rate_limit_policies not set - using code default)" if is_default else ""

    if n_minute >= per_minute:
        # 창 안에서 «가장 오래된» 호출이 창 밖으로 밀리는 순간이 다시 열리는 시각이다.
        # per_minute 을 0 으로 잡아 두면(정책으로 완전 차단) n_minute 이 0 이라 그 호출이
        # 없다 -- 그때는 창 하나를 통째로 기다리게 한다(음수 인덱스 오사용 방지).
        oldest = dq[-n_minute] if n_minute else None
        retry = 60 if oldest is None else max(1, int(60 - (now - oldest).total_seconds()) + 1)
        log.info("[gate] rate limited: what=%s subject=%s window=minute used=%d limit=%d%s",
                 what, subject, n_minute, per_minute, note)
        raise _too_many("minute", n_minute, per_minute, retry,
                        "방문자별 AI 호출 한도 초과 - 분당 %d회 제한(현재 %d회). %d초 뒤 재시도 가능."
                        % (per_minute, n_minute, retry))
    if n_day >= per_day:
        retry = max(1, int((day_lo + timedelta(days=1) - now).total_seconds()))
        log.info("[gate] rate limited: what=%s subject=%s window=day used=%d limit=%d%s",
                 what, subject, n_day, per_day, note)
        raise _too_many("day", n_day, per_day, retry,
                        "방문자별 AI 호출 한도 초과 - 일 %d회 제한(현재 %d회). 다음 날 재시도 가능."
                        % (per_day, n_day))

    dq.append(now)
    return subject


def _too_many(window: str, used: int, limit: int, retry: int, detail: str) -> HTTPException:
    return HTTPException(429, {
        "error": "rate_limited", "scope": "visitor", "window": window,
        "used": used, "limit": limit, "retry_after_sec": retry, "detail": detail},
        headers={"Retry-After": str(retry)})


def _reset_for_test() -> None:
    """검증용 -- 프로세스 카운터·캐시를 비운다. 운영 경로에서는 부르지 않는다."""
    _HITS.clear()
    _col_cache.clear()
    _policy_cache.update({"at": None})
