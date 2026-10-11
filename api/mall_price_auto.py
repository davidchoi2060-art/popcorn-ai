# -*- coding: utf-8 -*-
"""쇼핑몰 가격 자동 갱신 — 1겹 배치 ② (2026-10-11).

■ 중헌 님 지시
  "팝콘PC 쇼핑몰에 관리자로 로그인해서 하루에 1~2회 가격 업데이트를 하는 기능이 필요함..
   즉, 엑셀 대량 업로드 또는 웹 크롤링을 통한 자동업데이트.."
  엑셀 업로드(①)는 `api/admin_mall_price` 가 맡는다. 이 파일은 사람 없이 도는 쪽이다.

■ 어디서 가격을 읽나 — 두 길, 앞의 것이 되면 그것만 쓴다
  ① 쇼핑몰 관리자 「상품엑셀」 내려받기
     MALL_ADMIN_ID · MALL_ADMIN_PW 로 그 실행에서 로그인하고, MALL_EXPORT_URL 의 파일을
     받아 `mall_price.read_price_file()`(업로드와 같은 해석)로 읽는다. 셋 중 하나라도
     없으면 이 길은 건너뛴다. 한 번 요청으로 전체 가격이 오므로 쇼핑몰에 부담이 가장 적다.
  ② 공개 상품 페이지 (익명)
     완제품 PC(판매중)를 하나씩 `mall_price_reader.read_price()` 로 읽는다. 요청 사이
     1.5초를 둔다(A-18 규약과 같은 간격). 로그인이 필요 없어 설정이 없어도 돈다.
     ①이 설정돼 있는데 실패하면 ②로 내려가지 않고 실패로 끝낸다 — 로그인이 깨진 것을
     조용히 덮지 않는다(실패 사유가 관리자 화면에 남는다).

■ 쿠키를 저장하지 않는다 (A-124 와의 관계)
  A-124(2026-08-29)는 몰 공급처 갱신을 자동으로 돌리지 않기로 했다. 이유는 무인 실행에
  넣어 둔 «세션 쿠키»가 며칠이면 만료되어 조용히 실패하기 때문이었다. 이 수집기는 쿠키를
  어디에도 두지 않는다 — 실행마다 아이디·비밀번호로 새로 로그인하고 그 쿠키는 프로세스
  메모리에서만 산다. 아이디·비밀번호는 서버 환경 파일(/etc/popcorn-ai.env)에서만 읽고
  코드·리포·로그에 남기지 않는다. 공급처 갱신(A-114·A-124) 자체는 이 파일이 바꾸지 않는다.

■ 반영 규칙은 업로드와 같다 (`mall_price.build_plan` · `apply_changes`)
  완제품 PC 만 · 잠긴 판매가 건너뜀 · 30% 넘는 변동은 그 상품만 보류(사람이 업로드로 확인) ·
  실행 기록(mall_price_runs) · 가격 이력(reason=mall_price_auto|manual) · 되돌리기.

■ 실패로 끝내는 경우
  로그인 실패 · 내려받은 파일을 못 읽음 · 읽은 가격 0건 · 공개 페이지 읽기가 절반 넘게 실패.
  어떤 경우든 판매가는 하나도 안 바꾸고 사유를 남긴다.
"""
import html.parser
import http.cookiejar
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from sqlalchemy import text

from . import mall_price as MP
from . import mall_price_reader as R
from .db import engine

log = logging.getLogger(__name__)      # ASCII only (server stdout is cp949)

ENV_ID, ENV_PW, ENV_EXPORT = "MALL_ADMIN_ID", "MALL_ADMIN_PW", "MALL_EXPORT_URL"
ENV_EXPORT_DATA = "MALL_EXPORT_DATA"   # 내려받기가 POST 일 때 보낼 폼 본문(쿼리 문자열 형식)
LOGIN_URL = R.BASE + "/bbs/login.php"
ADMIN_URL = R.BASE + "/adm/"
DELAY = 1.5                            # 공개 페이지 요청 간격(초)
MAX_READS = int(os.environ.get("MALL_PRICE_MAX_READS") or 3000)
FAIL_RATIO = 0.5                       # 공개 페이지 읽기가 이 비율을 넘게 실패하면 실행 실패
STALE_RUNNING = "2 hours"              # 이보다 오래 «실행 중»인 행은 죽은 실행으로 본다


class CollectError(RuntimeError):
    """수집 실패 — 관리자 화면에 그대로 보일 문장."""


def settings() -> dict:
    """설정 이름과 «있는지»만 돌려준다. 값은 절대 돌려주지 않는다."""
    return {"login": bool(os.environ.get(ENV_ID) and os.environ.get(ENV_PW)),
            "export_url": bool(os.environ.get(ENV_EXPORT)),
            "names": [ENV_ID, ENV_PW, ENV_EXPORT, ENV_EXPORT_DATA]}


# ================================================================ ① 관리자 내려받기 ==

class _LoginForm(html.parser.HTMLParser):
    """비밀번호 칸이 있는 첫 form 의 action · 숨은 값 · 아이디/비밀번호 칸 이름."""

    def __init__(self):
        super().__init__()
        self.forms, self._cur = [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._cur = {"action": a.get("action") or "", "fields": {}, "user": None, "pw": None}
            self.forms.append(self._cur)
        elif tag == "input" and self._cur is not None:
            name, typ = a.get("name"), (a.get("type") or "text").lower()
            if not name:
                return
            if typ == "password" and self._cur["pw"] is None:
                self._cur["pw"] = name
            elif typ in ("text", "email") and self._cur["user"] is None:
                self._cur["user"] = name
            elif typ == "hidden":
                self._cur["fields"][name] = a.get("value") or ""

    def handle_endtag(self, tag):
        if tag == "form":
            self._cur = None


def _opener():
    jar = http.cookiejar.CookieJar()            # 메모리에만 — 파일로 저장하지 않는다
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [("User-Agent", R.UA), ("Accept-Language", "ko-KR,ko;q=0.9")]
    return op


def _get(op, url, data=None, timeout=20):
    with op.open(url, data=data, timeout=timeout) as r:
        return r.geturl(), r.read()


def login(op, user: str, pw: str) -> None:
    """쇼핑몰 관리자 로그인. 실패하면 CollectError. 비밀번호는 어디에도 남기지 않는다."""
    try:
        _url, raw = _get(op, LOGIN_URL)
    except Exception as e:                                          # noqa: BLE001
        raise CollectError("쇼핑몰 로그인 화면을 열지 못했습니다 (%s)" % type(e).__name__)
    p = _LoginForm()
    p.feed(raw.decode("cp949", "replace"))
    form = next((f for f in p.forms if f["pw"] and f["user"]), None)
    if form is None:
        raise CollectError("쇼핑몰 로그인 화면에서 아이디·비밀번호 칸을 찾지 못했습니다")
    fields = dict(form["fields"])
    fields[form["user"]], fields[form["pw"]] = user, pw
    action = urllib.parse.urljoin(LOGIN_URL, form["action"] or LOGIN_URL)
    try:
        _get(op, action, urllib.parse.urlencode(fields, encoding="cp949").encode("ascii"))
        final, _raw = _get(op, ADMIN_URL)
    except Exception as e:                                          # noqa: BLE001
        raise CollectError("쇼핑몰 로그인 요청이 실패했습니다 (%s)" % type(e).__name__)
    if "login" in urllib.parse.urlparse(final).path:
        raise CollectError("쇼핑몰 관리자 로그인이 거부됐습니다 (아이디·비밀번호 확인 필요)")


def collect_export() -> tuple[dict, dict]:
    """① 관리자 상품엑셀 -> ({code: price}, 정보). 설정이 없으면 ({}, None)."""
    user, pw, url = (os.environ.get(k) for k in (ENV_ID, ENV_PW, ENV_EXPORT))
    if not (user and pw and url):
        return {}, None
    op = _opener()
    login(op, user, pw)
    data = os.environ.get(ENV_EXPORT_DATA)
    try:
        final, raw = _get(op, urllib.parse.urljoin(R.BASE, url),
                          data.encode("ascii") if data else None, timeout=120)
    except Exception as e:                                          # noqa: BLE001
        raise CollectError("쇼핑몰 상품엑셀을 내려받지 못했습니다 (%s)" % type(e).__name__)
    if "login" in urllib.parse.urlparse(final).path:
        raise CollectError("상품엑셀 내려받기가 로그인 화면으로 돌아갔습니다")
    try:
        got = MP.read_price_file(raw)
    except MP.PriceFileError as e:
        raise CollectError("내려받은 상품엑셀을 읽지 못했습니다: %s" % e)
    return got["prices"], {"source": "export", "rows": got["rows"], "format": got["format"],
                           "bad_rows": got["bad_rows"], "bytes": len(raw)}


# ================================================================ ② 공개 페이지 ==

def targets(conn, *, include_parts=False) -> list[tuple[int, str]]:
    sql = ("SELECT product_code, part_type FROM products WHERE status='판매중'"
           + ("" if include_parts else " AND part_type=:pt") + " ORDER BY product_code LIMIT :n")
    return [(r[0], r[1]) for r in conn.execute(text(sql), {"pt": MP.PC_PART_TYPE, "n": MAX_READS})]


def collect_public(codes, *, sleep=time.sleep, read=None) -> tuple[dict, dict]:
    read = read or R.read_price
    prices, failed, errs = {}, 0, {}
    for i, (code, part_type) in enumerate(codes):
        if i:
            sleep(DELAY)
        got = read(code, part_type)
        if got.get("ok") and got.get("price"):
            prices[code] = int(got["price"])
        else:
            failed += 1
            k = got.get("err") or "?"
            errs[k] = errs.get(k, 0) + 1
    info = {"source": "pages", "asked": len(codes), "read": len(prices), "failed": failed,
            "errors": dict(sorted(errs.items(), key=lambda x: -x[1])[:5])}
    if codes and failed / len(codes) > FAIL_RATIO:
        raise CollectError("공개 상품 페이지 %d건 중 %d건을 읽지 못했습니다" % (len(codes), failed), info)
    return prices, info


# ================================================================ 실행 ==

def running(conn):
    return conn.execute(text(
        "SELECT run_id FROM mall_price_runs WHERE ok IS NULL AND moment IN ('auto','manual')"
        " AND started_at > now() - CAST(:s AS INTERVAL) ORDER BY run_id DESC LIMIT 1"),
        {"s": STALE_RUNNING}).scalar()


class AlreadyRunning(RuntimeError):
    pass


def begin(moment: str, *, operator_id=None) -> int:
    """실행 행을 만든다(겹치면 AlreadyRunning). 수집은 `execute()` 가 한다."""
    if moment not in ("auto", "manual"):
        raise ValueError(moment)
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('mall_price_auto'))"))
        other = running(conn)
        if other:
            raise AlreadyRunning(other)
        src = "export" if settings()["login"] and settings()["export_url"] else "pages"
        return MP.start_run(conn, moment, source=src, operator_id=operator_id)


def execute(run_id: int, moment: str, *, operator_id=None, collect_public_fn=None) -> dict:
    """수집 -> 비교 -> 반영 -> 실행 기록 마감. 예외를 밖으로 던지지 않고 결과를 돌려준다."""
    detail = {}
    try:
        prices, info = collect_export()
        if info is None:
            with engine.connect() as conn:
                codes = targets(conn)
            prices, info = (collect_public_fn or collect_public)(codes)
        detail["collect"] = info
        if not prices:
            raise CollectError("쇼핑몰 가격을 한 건도 읽지 못했습니다")
        with engine.begin() as conn:
            plan = MP.build_plan(conn, prices)
            res = MP.apply_changes(conn, plan["changes"] + plan["locked"], moment=moment,
                                   operator_id=operator_id, run_id=run_id, hold_big=True,
                                   source_url_of=lambda c: R.product_url(c, R.PC_PART_TYPE))
            counts = {"seen": plan["seen"], "matched": plan["matched"], "changed": res["changed"],
                      "up": res["up"], "down": res["down"], "held": res["held"], "locked": res["locked"]}
            detail.update(same=plan["same"], not_found=len(plan["not_found"]), stale=res["stale"],
                          out_of_scope=plan["out_of_scope"])
            MP.finish_run(conn, run_id, ok=True, counts=counts, apply_log_id=res["log_id"], detail=detail)
        log.info("[mall-price-auto] run=%s ok changed=%s held=%s", run_id, res["changed"], res["held"])
        return {"ok": True, "run_id": run_id, **counts}
    except Exception as e:                                          # noqa: BLE001
        if isinstance(e, CollectError):
            reason = e.args[0]
            if len(e.args) > 1:
                detail["collect"] = e.args[1]
        else:
            reason = "처리 중 오류 (%s)" % type(e).__name__
        log.warning("[mall-price-auto] run=%s failed: %s", run_id, type(e).__name__)
        try:
            with engine.begin() as conn:
                MP.finish_run(conn, run_id, ok=False, fail_reason=reason, detail=detail)
        except Exception:                                           # noqa: BLE001
            log.exception("[mall-price-auto] run=%s could not record failure", run_id)
        return {"ok": False, "run_id": run_id, "fail_reason": reason}


def run(moment: str = "auto", *, operator_id=None) -> dict:
    """한 번 돌린다(타이머 · 명령줄)."""
    try:
        run_id = begin(moment, operator_id=operator_id)
    except AlreadyRunning as e:
        return {"ok": False, "run_id": e.args[0], "fail_reason": "이미 실행 중입니다"}
    return execute(run_id, moment, operator_id=operator_id)


def start_background(*, operator_id) -> int:
    """관리자 「지금 실행」 — 실행 행을 만들고 수집은 뒤에서 돌린다(수 분 걸릴 수 있다)."""
    run_id = begin("manual", operator_id=operator_id)
    threading.Thread(target=execute, args=(run_id, "manual"), kwargs={"operator_id": operator_id},
                     name="mall-price-manual-%d" % run_id, daemon=True).start()
    return run_id
