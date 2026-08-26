# -*- coding: utf-8 -*-
"""팝콘PC AI 통합 회귀 세트 — 슬라이스 1~35의 기검증 수치를 실행 가능하게 묶는다.

실행: .venv/Scripts/python tests/regression.py        (API 서버가 8000에 떠 있어야 함)
      .venv/Scripts/python tests/regression.py --quiet  (실패만 출력)

**전량 불변식(INVARIANT)이다 — 고정 기대값(FIXED)은 폐지했다 (A-13, 2026-07-27).**
  왜: 베타 운영 중 실주문 1건이 부품 8개 재고를 줄이자 고정값 5개가 동시에 깨졌다.
  그때마다 손으로 숫자를 맞추면 회귀는 '거짓 안심'이 된다 — 코드가 틀려도 값만 고치게 된다.

  대신 원칙은 하나다: **같은 사실을 두 경로로 구해 일치를 본다.**
    · API가 말하는 수 ↔ DB가 세는 수 (원천 대조)
    · 응답 내부의 정합 (부품 가격 합 = 총액, 규칙 수 = 판정 수)
    · 데이터가 어떻게 누적돼도 성립해야 하는 관계 (티어 서열·예산 준수·원장 짝)
  이게 깨지면 데이터가 아니라 **코드가 잘못된 것**이다.

  절대값이 사라지며 잃는 것: "가중치를 잘못 바꿔 추천 총액이 조용히 달라지는" 변화는
  관계식만으로 못 잡는다. 그래서 주요 수치를 스냅샷에 적어두고 **바뀌면 알린다**
  (drift 참조). 알림은 실패로 세지 않는다 — 재고가 움직이면 값도 움직이는 게 정상이다.

DB 대조는 프로젝트 .venv의 SQLAlchemy를 쓴다(DATABASE_URL, 로컬 전용). DB에 닿지 못하면
해당 검사만 건너뛰고 그 사실을 알린다 — 조용히 통과시키지 않는다.
목업=스펙 단계에서는 "브라우저 손검증 + 이 스크립트"가 검증 수단이다.
"""
import glob
import io
import json
import math
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

# Windows 콘솔(cp949)에서도 한글·기호가 깨지지 않게 stdout을 UTF-8로 고정한다.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 기준 URL. 기본은 8000 이지만 **다른 세션이 그 포트를 잡고 있을 수 있다** —
# 그때 회귀를 그대로 돌리면 남의(그리고 대개 낡은) 서버를 검사하면서 내 코드를 판정한다.
# 오늘 실제로 그렇게 돼서, 방금 넣은 필드가 "없다"고 나왔다(서버가 옛 코드였다).
#   REGRESSION_BASE=http://127.0.0.1:8001 .venv/Scripts/python tests/regression.py
BASE = os.environ.get("REGRESSION_BASE", "http://localhost:8000")
QUIET = "--quiet" in sys.argv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_PATH = os.path.join(ROOT, "tests", ".regression-snapshot.json")

# ── 구 관리자 화면의 두 거처 (2026-08-17 동결 이동) ─────────────────────────────
# admin2 대체가 없는 8화면(customers·my-profile·orders·payments·refunds·reviews·
# shipping·stock-inbound)만 `mockups/admin/` 에 남고, 나머지 29화면 + `_demo-products.html`
# 은 `_legacy/admin-phoenix/` 로 옮겨졌다(git mv — P-09 「파일은 지우지 않는다」 유지).
#
#   admin_html(name)   옛 마크업의 «성질»을 재는 단건 검사가 파일을 따라가는 경로.
#                      파일이 어디 있든 검사 수가 줄지 않는다 — 파일이 없어져
#                      [SKIP]/실패로 조용히 빠지는 것이 가장 위험하다(§회귀 세트).
#   admin_htmls()      동결 구 화면 «전체»(남은 8 + _legacy). 전수 마크업 감사용.
#
# ⚠ 서빙·화면 수를 재는 검사([30] 자산 실재 · [31] 화면 수)는 이 둘을 쓰면 안 된다 —
#   그 검사들의 모집단은 「지금 mockups/ 아래 있는 것」이다.
LEGACY_ADMIN = os.path.join(ROOT, "_legacy", "admin-phoenix")


def admin_html(name):
    p = os.path.join(ROOT, "mockups", "admin", name)
    return p if os.path.exists(p) else os.path.join(LEGACY_ADMIN, name)


def admin_htmls():
    return (sorted(glob.glob(os.path.join(ROOT, "mockups", "admin", "*.html")))
            + sorted(glob.glob(os.path.join(LEGACY_ADMIN, "*.html"))))

# 슬라이스 39의 '알려진 한계'는 슬라이스 40에서 해소됐다: 예산 100만원 추천이 안 나온 원인은
# 탐색 전략이 아니라 **노드 상한값**이었다(100,000 → 682,419노드면 답이 있다. 탐색은 싸다 —
# 100,007노드가 0.02초). 상한을 2,000,000으로 올려 1,000,000원 구성이 나온다.
# 이 이력을 남겨두는 이유: 같은 증상(견적 '불가')을 다시 만나면 데이터가 아니라 상한을 먼저 본다.

results = []

# ── DB 원천 대조 (A-13) ────────────────────────────────────────────────────────
# API가 말하는 수를 DB가 세는 수와 맞춘다. 절대값을 박는 대신 원천에 물어보는 것이
# 재고가 움직여도 성립하는 유일한 방법이다.
_engine = None
_db_why = ""
try:
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text
    load_dotenv(os.path.join(ROOT, ".env"))
    _engine = create_engine(os.environ["DATABASE_URL"])
    with _engine.connect() as _c:
        _c.execute(text("SELECT 1"))
except Exception as _e:                                  # noqa: BLE001
    _engine, _db_why = None, f"{type(_e).__name__}: {_e}"


def db_one(sql, **p):
    """DB에서 직접 센 값. DB에 닿지 못하면 None(호출부가 건너뛰고 사유를 알린다)."""
    if _engine is None:
        return None
    with _engine.connect() as c:
        return c.execute(text(sql), p).scalar()


def db_exec(sql, **p):
    """검사가 남긴 흔적을 치울 때만 쓴다(슬라이스 78·93).

    **정본을 건드리는 용도가 아니다.** 회귀는 쓰기 경로를 가드로만 확인한다는 원칙
    (슬라이스 50 전례)은 그대로다 — 이 헬퍼는 검사가 스스로 만든 행을 되돌리기 위한 것이다.
    """
    if _engine is None:
        return None
    with _engine.begin() as c:
        c.execute(text(sql), p)


def _uq(s):
    import urllib.parse
    return urllib.parse.quote(s)


def db_all(sql, **p):
    """행 목록(dict). DB에 닿지 못하면 빈 목록."""
    if _engine is None:
        return []
    with _engine.connect() as c:
        return [dict(r) for r in c.execute(text(sql), p).mappings().all()]


# 슬롯 → 그 슬롯이 받는 부품 종류. **엔진 것을 그대로 읽는다** — 여기에 베껴 두면
# 언젠가 어긋나고, 그때 회귀는 엔진이 아니라 자기 사본을 지키게 된다.
try:
    sys.path.insert(0, ROOT)
    from api.recommend import SLOT_TYPES as _ST
    SLOT_TYPES_DB = {s: list(ts) for s, ts in _ST.items()}
except Exception:                                        # noqa: BLE001
    SLOT_TYPES_DB = {}


# ── 값 변화 알림 (실패 아님) ───────────────────────────────────────────────────
# 관계식만으로는 "가중치를 잘못 건드려 추천 총액이 조용히 달라지는" 변화를 못 잡는다.
# 그래서 주요 수치를 적어두고 바뀌면 보고한다. 재고가 움직이면 값도 움직이는 게 정상이므로
# **실패로 세지 않는다** — 사람이 보고 "이건 내가 바꾼 게 아닌데?"를 판단하라는 신호다.
_snap_old, _snap_new, _drifts = {}, {}, []
try:
    with io.open(SNAP_PATH, encoding="utf-8") as _f:
        _snap_old = json.load(_f)
except Exception:                                        # noqa: BLE001
    _snap_old = {}


def drift(key, value):
    _snap_new[key] = value
    if key in _snap_old and _snap_old[key] != value:
        _drifts.append((key, _snap_old[key], value))
    return value


# ── 자기 은폐 방지 (C안, 2026-08-15, 하네스 판단 — 최소 구현) ───────────────────
# 46158 사고: 검사가 정본 상품을 고쳤는데 되돌리기가 안 됐고, 그 상품이 다음 회차
# 선택자의 시작 조건(status='판매중' 등)에서 빠져나가 **검사 자신의 시야에서
# 사라졌다.** try/finally(같은 날 앞서 추가)가 원인 대부분(undo 누락)을 줄였지만,
# "finally조차 못 도는" 잔여 위험은 남는다 — 그리고 그 잔여 위험은 이론이 아니라
# 오늘 밤 이 저장소에서 서버가 세 번 죽으며 실제로 일어났다(T-05).
#
# 막는 법은 하나뿐이다 — 지난 회차가 고른 대상이 **지금도 이 검사의 시작 조건을
# 만족하는지**를 다음 회차가 직접 확인하고, 아니면 조용히 다음 상품으로 넘어가지
# 않고 실패로 찍는다. 「이 검사가 남긴 흔적」과 「운영자가 정당히 건드린 값」은
# **구분하지 않는다** — 구분하려 들면 복잡해지고 아무도 안 믿는 검사가 된다
# (하네스 판단). 오탐이 나면 실패 메시지의 해소법대로 스냅샷 키를 지우고 다시
# 돌리면 된다 — 조용한 은폐보다 시끄러운 오탐이 낫다(이 서버는 개발/스테이징,
# I-01 — 시끄러워도 되는 곳이다).
def _selftest_no_orphan(key, still_ok_sql, state_sql, own_edit_fields=None):
    """이 검사가 지난 회차에 고른 대상(product_code)이 지금도 건강한지 본다.

    새 표를 만들지 않는다 — 이미 있는 `tests/.regression-snapshot.json`
    (`_snap_old`/`_snap_new`) 을 그대로 쓴다. 키가 없으면(첫 실행 · 스냅샷
    파일이 gitignore라 없는 환경) 조용히 통과한다 — 죽지 않는다.

    `own_edit_fields`(선택, 예: {"sale_price","status"}) — 이 회귀 «자신»이 수정 중
    잠그는 필드 이름 집합. 2026-08-24 오탐(구형 부품 100건 AI 후보 제외 후속) 후속 개선 —
    지난 회차 대상이 `ai_candidate_yn` 잠금으로 정당히 제외됐는데(운영자 조치),
    `still_ok_sql`은 그 사정을 모르고 실패로만 찍어 "검사 자신이 되돌리기를 놓쳤나"를
    사람이 매번 DB를 손으로 파서 가려야 했다. `state_sql`이 함께 주는 `locked_fields`와
    `own_edit_fields`가 겹치면 "이 검사 자신이 잠근 필드가 아직 남아 있다" = 되돌리기
    누락 의심, 안 겹치면 "다른 필드로 제외됐다" = 운영자 조치 가능성이 높다는 실마리를
    메시지에 덧붙인다. **판정 자체(FAIL 여부)는 바꾸지 않는다** — 안 겹쳐도 여전히
    FAIL이다. 조용히 통과시키면 이 검사가 막던 진짜 사고(46158 — 되돌리기 누락이
    검사 자신의 시야에서 사라짐)를 놓칠 수 있어서다("조용한 은폐보다 시끄러운 오탐이
    낫다" — 위 자기 은폐 방지 절 그대로). 인자를 안 주는 호출부는 진단 문구만 안 붙을
    뿐 이전과 동작이 같다.
    """
    last_pc = _snap_old.get(key)
    if last_pc is None or _engine is None:
        return
    ok = db_one(still_ok_sql, p=last_pc)
    state = None if ok else db_all(state_sql, p=last_pc)
    diag = ""
    if not ok and own_edit_fields and state:
        locked = set((state[0] or {}).get("locked_fields") or [])
        overlap = locked & set(own_edit_fields)
        fields_txt = "·".join(sorted(own_edit_fields))
        verdict_txt = ("남아 있음 — 이 검사 자신의 되돌리기 누락 의심"
                       if overlap else
                       "없음 — 다른 필드로 제외됨(운영자 조치일 가능성)")
        diag = f" [진단: 이 검사가 잠그는 필드({fields_txt})가 locked_fields에 {verdict_txt}]"
    check(f"자기 은폐 확인({key}) — 지난 회차 대상 product_code={last_pc}이 지금도 정상" + diag,
          bool(ok), "이 검사의 시작 조건을 계속 만족함",
          "유지됨" if ok else {
              "product_code": last_pc,
              "지금 상태": state[0] if state else "상품이 없거나 조회 실패",
              "해소법": f"운영자가 정당히 바꾼 값이면 tests/.regression-snapshot.json에서"
                       f" '{key}' 키를 지우고 다시 돌리세요"})


def _selftest_remember(key, pc):
    """이번 회차가 고른 대상을 다음 회차가 볼 수 있게 남긴다(성공/실패와 무관하게 —
    선택한 순간 기록해야 다음 회차가 '그 상품에 무슨 일이 있었는지'를 잴 수 있다)."""
    if pc is not None:
        _snap_new[key] = pc


def check(name, ok, expect=None, got=None, kind="INVARIANT"):
    results.append({"name": name, "ok": bool(ok), "expect": expect, "got": got, "kind": kind})
    if not QUIET or not ok:
        mark = "PASS" if ok else "FAIL"
        line = f"  [{mark}] ({kind[0]}) {name}"
        if not ok:
            line += f"\n         기대: {expect}\n         실제: {got}"
        print(line)


# 관리자 API는 슬라이스 37부터 세션 쿠키를 요구한다(로그인 없이 돌리면 전부 401).
# http.cookiejar는 dotless 호스트('localhost')에 '.local'을 붙여 쿠키를 되돌려주지 않으므로
# 세션 쿠키를 직접 들고 다닌다 — 브라우저 동작과 같고, 무엇을 보내는지가 코드에 보인다.
# 관리자(37)·고객(38) 세션은 쿠키 이름이 달라 동시에 들고 다닐 수 있다.
SESSION = {}                                # 쿠키명 -> "name=value"
COOKIE_NAMES = ("popcorn_admin_session", "popcorn_member_session")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@popcornpc.local")
# 비밀번호는 **여기 적지 않는다.** `.env`(gitignore) 또는 환경변수에서 읽는다.
#
# 왜 고쳤나(슬라이스 85): 이 자리에 값이 그대로 박혀 있었고, 주석은 "로컬 시드 전용이며
# 운영 서버에는 이 계정이 없다"고 적혀 있었다. **그 전제가 틀렸다.** 로컬과 베타는
# 같은 Cloud SQL을 본다 — `admin@popcornpc.local`은 베타에서도 owner·활성이고
# 실제로 로그인 기록이 있다. 게다가 이 리포는 공개고, 베타는 Basic Auth를 걷어낸 뒤
# 누구나 로그인 화면에 닿는다. 즉 리포를 읽은 사람이 owner로 들어올 수 있었다.
#
# "테스트용"이라는 이름표는 그 값이 실제로 무엇을 여는지 바꾸지 않는다.
ADMIN_PW = os.environ.get("ADMIN_PW", "")


# 회귀가 만드는 상담·견적은 실제 원장이 아니라 **테스트 표식**을 달고 들어가야 한다
# (2026-08-20 사장님 확정) — 이 스크립트가 두드리는 BASE(기본 localhost:8000)의 로컬
# API는 배포 서버와 **같은 Cloud SQL**을 본다(`.env`의 DATABASE_URL 공유). 표식이
# 없던 시절 조사자 실측: consult_sessions 6,893건 중 6,732건(97.7%)이 회귀였다.
#
# 헤더 이름은 `api/recommend.py`의 `TEST_HEADER`(값 "X-Popcorn-Test")와 반드시
# 같아야 한다 — 이 스크립트는 stdlib만 쓰는 원칙이라(아래 `_mp()` 주석 참조) 그
# 모듈을 import하지 않고 문자열을 그대로 맞춘다. 서버는 이 헤더 + `.env`의
# `POPCORN_TEST_HEADER_ENABLED` + **localhost 요청**이 전부 맞을 때만
# `consult_sessions.data_origin='test'`로 찍는다(`api/recommend._resolve_data_origin`
# · `api/expert.py`가 그대로 재사용). 이 스크립트는 항상 로컬 API를 두드리므로
# (BASE 기본값이 localhost) 스위치만 켜져 있으면 게이트를 통과한다.
#
# 세션을 만들지 않는 엔드포인트(로그인·목록 조회 등)에도 똑같이 싣는다 — 굳이
# 가려서 붙이면 "이 호출부는 깜빡했다"가 반복된다(§상단 원칙). 서버는 이 헤더를
# `/api/recommend`·`/api/expert/build`의 세션 INSERT 자리에서만 해석하고 나머지
# 엔드포인트는 무시하므로 부작용이 없다.
TEST_HEADER = "X-Popcorn-Test"


def _headers(json_body=False):
    h = {"Content-Type": "application/json"} if json_body else {}
    h[TEST_HEADER] = "1"
    if SESSION:
        h["Cookie"] = "; ".join(SESSION.values())
    return h


def get(path):
    req = urllib.request.Request(BASE + path, headers=_headers())
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def get_html(path):
    """렌더된 HTML 을 받는다 — **재구축 화면(`/admin2/*`) 검사의 유일한 길**.

    기존 마크업 검사는 `mockups/admin/*.html` 을 **파일로 직접 읽는다.** 그 화면들은
    완결된 정적 파일이라 그게 가능했다. 재구축 화면은 Jinja2 템플릿이라 파일에는
    `{% extends %}` 조각만 있고 **완성된 HTML 은 서버가 렌더한 뒤에만 존재한다.**
    그래서 파일이 아니라 **응답**을 읽는다.

    반환은 `(status, html)`. 200 이 아니어도 예외를 던지지 않는다 — 상태 자체가
    검사 대상이다.
    """
    req = urllib.request.Request(BASE + path, headers=_headers())
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception:
            return e.code, ""


def post(path, body=None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body or {}).encode(), method="POST",
        headers=_headers(True))
    try:
        with urllib.request.urlopen(req) as r:
            _capture(r)
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None


def _capture(resp):
    """Set-Cookie에서 세션 쿠키를 집어 이후 요청에 붙인다(관리자·고객 각각)."""
    for raw in resp.headers.get_all("Set-Cookie") or []:
        for name in COOKIE_NAMES:
            if raw.startswith(name + "="):
                SESSION[name] = raw.split(";")[0]


def anon_status(path, body=None):
    """세션 쿠키를 붙이지 않고 호출 — 인증 게이트가 실제로 막는지 확인하는 용도."""
    req = urllib.request.Request(
        BASE + path,
        data=None if body is None else json.dumps(body).encode(),
        method="GET" if body is None else "POST",
        headers={} if body is None else {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def login():
    if not ADMIN_PW:
        print("\n  ADMIN_PW가 없습니다 — `.env`에 `ADMIN_PW=...`를 넣으세요"
              " (리포에는 적지 않습니다).\n"
              "  비밀번호 발급·변경: .venv/Scripts/python tools/set_admin_password.py"
              f" {ADMIN_EMAIL}\n")
        sys.exit(2)
    return post("/api/admin/auth/login",
                {"email": ADMIN_EMAIL, "password": ADMIN_PW, "provider": "dev"})


def member_login(email, nickname=None):
    """고객 로그인 = 가입(승인 게이트 없음 — 슬라이스 38). 세션을 갈아탄다."""
    return post("/api/auth/login", {"email": email, "nickname": nickname, "provider": "dev"})


def rec(budget):
    _, d = post("/api/recommend", {"mode": "guided",
                                   "constraints": [{"l": "용도", "v": "게임"},
                                                   {"l": "예산", "v": budget}]})
    return (d or {}).get("sets", d or {})


# ─────────────────────────────── 1. 결정론 엔진 ───────────────────────────────
def test_engine():
    print("\n[1] 결정론 엔진 (슬라이스 4·5·8·34)")
    _, c = post("/api/candidates/count", {"constraints": []})
    drift("pool_size", c["total"])
    # 후보 풀은 절대값이 아니라 **DB가 세는 수와 같은지**로 본다(A-13).
    pool_db = db_one("SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty > 0")
    if pool_db is None:
        print("  [SKIP] (I) S1 후보 카운터 = DB 실측 — DB 미연결: " + _db_why)
    else:
        check("S1 후보 카운터 = DB 실측(추천 뷰 ∧ 재고>0)", c["total"] == pool_db,
              pool_db, c["total"])
    check("제약 없으면 total == count", c["total"] == c["count"], c["total"], c["count"])
    check("후보 풀이 비어 있지 않다", c["total"] > 0, "> 0", c["total"])

    s100, s150, s70 = rec("100만원"), rec("150만원"), rec("70만원")
    sopen = rec("200만원 이상")
    for lab, s in (("70만", s70), ("100만", s100), ("150만", s150), ("캡없음", sopen)):
        for tier in ("value", "recommend", "highend"):
            st = s.get(tier)
            if not st:
                continue
            drift(f"{tier}_{lab}", st["total"])
            # ★ 구성 내부 정합 — 부품 가격의 합이 곧 총액이다. 가장 강한 관계식이다.
            check(f"[{lab}·{tier}] 부품 가격 합 = 총액",
                  sum(i["price"] for i in st["items"]) == st["total"],
                  sum(i["price"] for i in st["items"]), st["total"])
            check(f"[{lab}·{tier}] 슬롯 8개 구성", len(st["items"]) == 8, 8, len(st["items"]))

    # 티어 서열 — 가성비 <= 추천 <= 고성능. 재고가 어떻게 바뀌어도 성립해야 한다.
    for lab, s in (("70만", s70), ("100만", s100), ("150만", s150), ("캡없음", sopen)):
        v, r, h = (s.get("value") or {}).get("total"), \
                  (s.get("recommend") or {}).get("total"), \
                  (s.get("highend") or {}).get("total")
        if v and r:
            check(f"[{lab}] 가성비 <= 추천", v <= r, f"{v} <= {r}", f"{v} vs {r}")
        if r and h:
            check(f"[{lab}] 추천 <= 고성능", r <= h, f"{r} <= {h}", f"{r} vs {h}")

    # 가성비는 '예산과 무관한 가격 오름차순 첫 성립 조합'이다 — 예산이 달라도 같은 값이어야
    # 한다. ⚠ 라벨 정정(2026-08-24, 로직은 그대로): 「최저가 조합」은 이 검사가 실제로
    # 증명하는 것(총액이 예산과 무관하게 같은 값으로 수렴하는 수치 불변식)과 다른 이름이었다
    # — recommend.py의 가성비 티어는 전역 최저가 탐색이 아니라 가격 오름차순으로 훑다 예산
    # 안에서 처음 성립하는 조합을 쓴다. 검사 자체(len(vals)==1)는 그대로 옳다.
    vals = {s["value"]["total"] for s in (s70, s100, s150, sopen) if s.get("value")}
    check("가성비는 전 예산 공통(가격 오름차순 첫 성립 조합)", len(vals) == 1, "1개 값", vals)

    # 추천은 예산을 채운다 — 상한 이내이면서 상한의 90% 이상. (캡 없음은 상한이 없어 제외)
    for lab, s in (("70만", s70), ("100만", s100), ("150만", s150)):
        r = s.get("recommend")
        if not r:
            continue
        cap = r["budget"]["cap"]
        check(f"[{lab}] 추천은 예산 이내", r["total"] <= cap, f"<= {cap}", r["total"])
        check(f"[{lab}] 추천은 예산을 채운다(>=90%)", r["total"] >= cap * 0.9,
              f">= {int(cap * 0.9)}", r["total"])
    check("캡 없음 추천 >= 150만 추천",
          sopen["recommend"]["total"] >= s150["recommend"]["total"],
          f">= {s150['recommend']['total']}", sopen["recommend"]["total"])

    # 재현성 — 같은 입력 3회 = 같은 결과
    totals = {rec("100만원")["value"]["total"] for _ in range(3)}
    check("재현성(A-02): 3회 호출 동일", len(totals) == 1, "1개 값", totals)

    # 예산 준수 / 초과 정직 표기
    check("가성비는 예산 안", s100["value"]["budget"]["verdict"] == "within",
          "within", s100["value"]["budget"]["verdict"])
    check("고성능 초과는 'over'로 정직 표기", s100["highend"]["budget"]["verdict"] == "over",
          "over", s100["highend"]["budget"]["verdict"])
    # verdict는 말이 아니라 수치와 맞아야 한다 — over면 over_by가 정확히 초과분이다.
    hb = s100["highend"]["budget"]
    check("over_by = 총액 - 상한", hb["over_by"] == s100["highend"]["total"] - hb["cap"],
          s100["highend"]["total"] - hb["cap"], hb["over_by"])
    vb = s100["value"]["budget"]
    check("within이면 over_by = 0", vb["over_by"] == 0, 0, vb["over_by"])

    # ── 화면 정직성(슬라이스 48): 후보 수가 0이 아니어도 슬롯이 비면 견적은 불성립이다.
    # 화면은 이 판정을 서버에서만 받아야 한다 — 예전엔 후보 수>0이면 무조건
    # "3구성을 만들 수 있어요"라고 말해 거짓이 됐다.
    #
    # ⚠ 예산대 「30만원대」→「70만원대」교체(2026-08-24, 구형 부품 100건 AI 후보 제외 후속 —
    # 사장님 확정 · DBA 실측). 지키려는 것은 count==0이 아니라 **count>0인데도
    # buildable=false인 간극**이다 — count가 아예 0이면 "후보가 없으니 조립도 안 된다"는
    # 당연한 사실만 확인하게 되어, 슬라이스 48이 잡은 화면 거짓말(카운터>0을 보고 "3구성
    # 가능"이라 말한 버그)을 더는 재현하지 못한다. 「30만원대」의 count>0은 이번에 뺀 구형
    # 저가 CPU 7건(셀러론 G5905·펜티엄 G6400 등 — 게임 용도는 CPU 하한이 없어 가격만으로
    # 통과)에 전적으로 기대고 있었다. 그 CPU가 빠지자 count=0으로 떨어져 간극 자체가
    # 사라졌다(DBA 실측: 제외 전 count=7 buildable=False → 제외 후 count=0 buildable=False,
    # 둘 다 GPU·쿨러·파워 슬롯이 비어 있었다 — 즉 buildable=False라는 판정 자체는 옳았고
    # CPU 제외로 바뀐 게 아니다).
    # GPU·COOLER·POWER가 비는 이유는 CPU 재고와 무관하다 — 실측(읽기 전용 조회):
    # 현재 재고에서 GPU·POWER·COOLER_CPU_AIR·COOLER_CPU_AIO 중 tag_silent=true인 상품이
    # **0건**이다(가격 무관, 카탈로그 전체). 그래서 예산대를 20만원대~200만원 이상까지
    # 올려도 이 세 슬롯은 계속 비어 buildable=False가 그대로 유지되고, count만 CPU·
    # 메인보드 후보가 늘며 여유를 얻는다(70만원대 실측: count=71, CPU 13 + MB 58). 낱개
    # 상품 몇 건이 더 빠져도 0이 되지 않을 여유이면서, 같은 파일이 추천·고성능 비교에
    # 100만·150만원을 "보통" 구간으로 쓰는 것과 견줘 여전히 타이트한 게임 예산이다.
    # (GPU·파워·쿨러 중 하나라도 저소음 태그가 붙으면 이 값도 다시 손볼 대상이다 —
    # 그건 이 검사의 실패가 아니라 카탈로그가 실제로 좋아졌다는 신호다.)
    NARROW = [{"l": "용도", "v": "게임"}, {"l": "예산", "v": "70만원대"},
              {"l": "선호", "v": "저소음"}]
    _, cn = post("/api/candidates/count", {"constraints": NARROW})
    check("좁은 조건: 후보가 남아도 buildable=false",
          cn["count"] > 0 and cn["buildable"] is False, "count>0 & buildable=false",
          f'count={cn["count"]} buildable={cn["buildable"]}')
    check("빈 슬롯을 이름으로 알린다",
          bool(cn["empty_slots"]) and all(s.get("label") for s in cn["empty_slots"]),
          "슬롯 라벨 1개 이상", cn["empty_slots"])
    check("verdict가 불성립을 말한다", "만들 수 없" in cn["verdict"],
          "불성립 문구", cn["verdict"])
    _, rn = post("/api/recommend", {"mode": "guided", "constraints": NARROW})
    check("buildable=false면 추천도 전 티어 불성립(카운터와 엔진이 같은 말을 한다)",
          all(v is None for v in (rn.get("sets") or {}).values()), "전 티어 None",
          {k: (v or {}).get("total") for k, v in (rn.get("sets") or {}).items()})
    _, cw = post("/api/candidates/count", {"constraints": []})
    check("제약 없음이면 buildable=true",
          cw["buildable"] is True and not cw["empty_slots"], "true / 빈 슬롯 없음",
          f'{cw["buildable"]} {cw["empty_slots"]}')
    check("견적 슬롯 8개를 모두 센다", len(cw["slots"]) == 8, 8, len(cw["slots"]))
    # 쿨러는 공랭·수냉이 한 슬롯 — part_type으로 세면 AIO 0을 빈 슬롯으로 오판한다.
    #
    # **표본에 묶지 않는다**(2026-08-11 개정): 예전엔 「저소음」으로 검사했는데,
    # 저소음 쿨러 중 후보 자격을 갖춘 것이 **시연용 가짜 상품 하나뿐**이었다.
    # 0043 이 demo 를 걷어내자 슬롯이 0 이 되어 이 검사가 깨졌다 — 검사가 잘못된 게 아니라
    # **데모가 떠받치던 성립이 드러난 것**이다. 특정 태그가 아니라 **관계**로 본다:
    #   COOLER 슬롯 수 = AIR 후보 + AIO 후보 (합산이지 어느 한쪽이 아니다)
    _, cw2 = post("/api/candidates/count", {"constraints": []})
    _rows = db_all(
        "SELECT part_type, COUNT(*) AS n FROM v_recommendation_candidates"
        " WHERE stock_qty>0 AND part_type IN ('COOLER_CPU_AIR','COOLER_CPU_AIO')"
        " GROUP BY 1")
    if _rows:                                    # DB 에 못 닿으면 건너뛴다
        want = sum(r["n"] for r in _rows)
        check("쿨러 슬롯 = 공랭 + 수랭 합산(어느 한쪽이 0이어도 슬롯은 산다)",
              cw2["slots"]["COOLER"] == want, want, cw2["slots"]["COOLER"])

    # 저소음 견적이 성립하는가는 **재고 사실**이다 — 실패가 아니라 값 변화로 남긴다.
    _, cs = post("/api/candidates/count",
                 {"constraints": [{"l": "용도", "v": "게임"}, {"l": "선호", "v": "저소음"}]})
    drift("저소음_쿨러_후보", cs["slots"]["COOLER"])
    if cs["slots"]["COOLER"] > 0:
        check("저소음 조건에서도 쿨러 슬롯이 산다",
              cs["buildable"] is True, "buildable=true", cs["buildable"])


# ────── 45. 전 티어 불가 판정 — 고성능 상한(1.5배)까지 실제로 탐색했는가 (사장님 지시, 2026-08-24) ──────
# 발단: 가성비(value) 티어가 예산 안에서 불가능하면, 캐스케이드가 추천·고성능도 시도조차
# 않고 세 티어 전부 null로 응답하는 결함이 있었다. 추천은 가성비와 같은 예산 상한을 쓰므로
# 그 단정이 맞지만, 고성능은 상한이 예산의 HIGHEND_CAP_X배(응답의 `highend_cap_x`, 지금
# 1.5)라 가성비가 못 들어가는 예산에서도 성립할 수 있다. 조사자 실측(2026-07-23~2026-08-24):
# 가성비 실패 264건 중 162건(61.4%)에서 고성능형이 실제로 성립했고, 그 간극에서 실제 고객
# 19명이 "견적 불가"를 들었다.
#
# 이 검사가 확인하는 것은 "가성비가 실패하면 고성능도 실패해야 한다/말아야 한다"는 값이
# 아니라 **"고성능이 null이라면 그 판정이 실제 탐색의 결과였는가"**다. 지금 결함은 탐색을
# 안 하고 "없다"고 말한 것 — `search_exhausted.highend`(2026-08-24 오전 신설)가 그 둘을
# 가른다: 상한에 닿아 "못 찾았다"(True)와 "확정적으로 없다"(False)는 다른 사실이다.
#
# 예산을 하드코딩하지 않는다(2026-08-24 같은 날 「30만원대」검사가 구형 부품 제외로
# 무의미해진 전례가 있다 — CLAUDE.md §화면 정직성 참조). 대신 서버가 실측한 "최저 성립
# 예산"(`/api/candidates/count`의 `budget_min_total` — 예산 상한 없이 가성비 티어를 돌려
# 실제 성공한 값을 만원 단위로 이진 탐색해 좁힌 것, `api/candidates.py` `_min_feasible_
# budget`)을 경계로 쓴다. 그 값을 M이라 하면, 예산을 ceil(M/highend_cap_x)만원까지 낮추면
# 가성비는 못 들어가지만(예산 < M) 고성능의 상한(예산 × highend_cap_x)은 M에 닿는다 — 즉
# "가성비를 성립시킨 바로 그 조합"이 고성능 상한 안에도 이미 들어간다는 뜻이다. 그 상태에서
# 고성능이 null이면, 새 조합을 못 찾은 게 아니라 **이미 존재가 증명된 조합조차 못 찾은 것**
# 이므로 exhausted=True(탐색은 했지만 못 찾음)여야지 exhausted=False(확정적으로 없음)일
# 수는 없다. 카탈로그가 바뀌면 M도 같이 바뀌므로 경계도 매 실행 다시 잰다 — 숫자를 이
# 파일에 박지 않는다.
#
# 용도는 셋을 고른다(전부 돌리면 회귀가 느려진다 — 근거는 제작 보고): GPU 하한이 서로
# 다른 "고사양 게임"(550W)·"게임"(450W, 사장님이 든 원 사례) + GPU 하한이 아예 없는
# "사무·인강"(램·SSD만) — 성격이 다른 용도에서도 같은 결함이 재현되는지, 그리고 GPU
# 비용이 지배하지 않는 용도에서도 경계 논리가 성립하는지를 함께 본다.
def test_tier_cascade_exhaustive():
    print("\n[45] 전 티어 불가 판정 — 고성능 상한(1.5배)까지 실제로 탐색했는가 (사장님 지시)")
    USAGES = ["고사양 게임", "게임", "사무·인강"]
    # 5만원 — "이 예산으로는 절대 성립할 수 없다"를 확정하는 용도일 뿐, 실제 하한이 아니다.
    # 부품 8슬롯(CPU·MB·RAM·GPU·CASE·COOLER·POWER·SSD) 최저가 합이 5만원 아래일 수 없어
    # 카탈로그가 바뀌어도 안전하다 — over_budget=True를 얻어 budget_min_total을 계산시키는
    # 트리거일 뿐, 이 값에서 경계를 계산하지 않는다(경계는 아래 M에서 서버가 실측한다).
    PROBE_BUDGET = "5만원"
    for usage in USAGES:
        _st, cnt = post("/api/candidates/count",
                        {"constraints": [{"l": "용도", "v": usage},
                                         {"l": "예산", "v": PROBE_BUDGET}]})
        cnt = cnt or {}
        M = cnt.get("budget_min_total")
        if M is None or cnt.get("empty_slots"):
            print(f"  [SKIP] (I) [{usage}] 최저 성립 예산을 못 구했다 — "
                  f"budget_min_total={M} empty_slots={cnt.get('empty_slots')}"
                  " (카탈로그에 이 용도 후보가 없거나 전제가 깨졌다 — DB 미연결일 수도 있다)")
            continue

        _st, probe = post("/api/recommend", {"mode": "guided",
                          "constraints": [{"l": "용도", "v": usage},
                                          {"l": "예산", "v": PROBE_BUDGET}]})
        x = (probe or {}).get("highend_cap_x")
        if not x or x <= 1:
            print(f"  [SKIP] (I) [{usage}] highend_cap_x를 응답에서 못 읽었다 — {x!r}")
            continue

        m_man = M // 10_000
        gap_man = math.ceil(m_man / x)
        while gap_man * x * 10_000 < M - 1e-6:   # 부동소수 경계 방어 — M에 못 미치면 한 단위 올린다
            gap_man += 1
        if gap_man >= m_man or gap_man < 1:
            print(f"  [SKIP] (I) [{usage}] 경계 구간이 없다(M={M:,}원, highend_cap_x={x}) "
                  "— 최저 성립가가 너무 낮아 1.5배 간극이 안 생긴다")
            continue

        _st, d = post("/api/recommend", {"mode": "guided",
                      "constraints": [{"l": "용도", "v": usage},
                                       {"l": "예산", "v": f"{gap_man}만원"}]})
        d = d or {}
        sets = d.get("sets") or {}
        ex = d.get("search_exhausted") or {}

        check(f"[{usage}] search_exhausted가 티어 3개를 bool로 밝힌다",
              {"value", "recommend", "highend"} <= set(ex)
              and all(isinstance(ex.get(k), bool) for k in ("value", "recommend", "highend")),
              "value·recommend·highend 3개 bool", ex)

        # 전제 확인 — 이 경계가 실제로 "가성비는 확정 실패"인지 먼저 본다. 아니면 아래
        # 핵심 검사가 무엇을 증명하는지 알 수 없다(M이 안 좁혀졌을 가능성 — 그래도 아래
        # 핵심 검사 자체는 여전히 유효하다: 더 낮은 예산에서 성립했다면 그 조합은 고성능
        # 상한 안에는 당연히 들어간다).
        check(f"[{usage}] 경계 예산({gap_man}만원 < 최저 성립가 {M:,}원)에서 가성비는 불성립",
              sets.get("value") is None,
              "value=None", (sets.get("value") or {}).get("total"))

        # ★ 핵심 검사 — gap_man × highend_cap_x(x) >= M이므로, 가성비를 성립시킨 바로 그
        # 조합이 고성능의 상한 안에도 이미 들어간다(더 비싼 조합을 새로 찾을 필요조차 없이
        # 존재가 증명된 조합이다). 그런데도 null이면 "확정적으로 없다"(exhausted=False)일
        # 수 없다 — 최소한 "상한에 닿아 못 찾았다"(exhausted=True)여야 한다. 시도조차 안
        # 하고 "없다"고 말하는 것이 지금 결함이다.
        highend = sets.get("highend")
        cap_reach = gap_man * x * 10_000
        check(f"[{usage}] 가성비가 막혀도 고성능은 자기 상한"
              f"({gap_man}만원×{x}={cap_reach:,.0f}원 >= 최저 성립가 {M:,}원)으로 실제 탐색한다",
              highend is not None or ex.get("highend") is True,
              "고성능 성립 또는 search_exhausted.highend=True",
              (f"highend=null search_exhausted.highend={ex.get('highend')}"
               " — [처방] 가성비 실패 시 고성능을 함께 단정하지 말고, 고성능 자신의 상한"
               "(cap × highend_cap_x)으로 독립 탐색했는지 recommend.py 캐스케이드를 확인하라"
               if highend is None else
               f"highend={highend.get('total')} (성립)"))


# ─────────────── 11. 카탈로그 업로드 적재 (슬라이스 50) ───────────────
# 이 슬라이스에서 실제로 겪은 사고를 회귀로 고정한다:
#   · EAV 없이 마스터만 올리면 기존 사양이 지워져 추천 후보가 무너졌다(후보 -1 · 검수 +169).
#   · 드라이런 없이 적용하거나 다른 파일을 확정하는 경로가 열려 있으면 안 된다.
CSV_HEAD = ("자체상품코드,상품명,카테고리1,카테고리2,카테고리3,상태값,매입가,일반회원,"
            "시중가,공급처,스펙,제조사,모델명,다나와No")


def _mp(fields: dict, files: dict) -> tuple[bytes, dict]:
    """multipart/form-data 본문 — stdlib만 쓰는 이 스크립트의 원칙을 유지한다."""
    b = "----pcregress" + str(abs(hash(repr(fields) + repr(list(files)))))
    out = []
    for k, v in fields.items():
        out.append(f"--{b}\r\nContent-Disposition: form-data; "
                   f'name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (fn, raw) in files.items():
        out.append(f"--{b}\r\nContent-Disposition: form-data; "
                   f'name="{k}"; filename="{fn}"\r\n'
                   "Content-Type: text/csv\r\n\r\n".encode() + raw + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), {"Content-Type": "multipart/form-data; boundary=" + b}


def post_raw(path, data, headers, method="POST"):
    h = dict(headers)
    h[TEST_HEADER] = "1"          # _headers()와 같은 표식 — 정의·근거는 그 위 주석
    if SESSION:
        h["Cookie"] = "; ".join(SESSION.values())
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:                                # noqa: BLE001
            return e.code, {}


def test_upload():
    print("\n[11] 카탈로그 업로드 적재 — 드라이런·가드·사양 보존 (슬라이스 50)")
    # 컬럼이 어긋난 파일은 절반 넣지 않고 거부한다
    st, _ = post_raw("/api/admin/catalog-import/dryrun",
                     *_mp({"origin": "real"}, {"master": ("bad.csv", b"a,b\n1,2\n")}))
    check("컬럼 불일치 파일은 400", st == 400, 400, st)
    st, _ = post_raw("/api/admin/catalog-import/dryrun",
                     *_mp({"origin": "mars"},
                          {"master": ("x.csv", (CSV_HEAD + "\n").encode())}))
    check("잘못된 origin은 400", st == 400, 400, st)
    # EAV는 두 파일이 짝이다 — 하나만 올리면 조용히 무시하지 않고 거부한다
    st, _ = post_raw("/api/admin/catalog-import/dryrun",
                     *_mp({"origin": "real"},
                          {"master": ("x.csv", (CSV_HEAD + "\n").encode()),
                           "db_products": ("p.csv", b"product_id\n1\n")}))
    check("EAV 한쪽만 올리면 400", st == 400, 400, st)

    # ⚠ 회귀는 **적용하지 않는다.** 처음엔 apply까지 돌렸는데 매 실행이 정본 상품 하나를
    # 테스트 값으로 덮었다(시드 P-1001이 ETC·매입가 1000원으로 강등됐고 손으로 복구했다).
    # 검증 수단이 검증 대상을 오염시키면 안 된다 — 드라이런까지만 보고, 적용은 가드만 본다.
    row = db_one("SELECT product_code FROM v_recommendation_candidates"
                 " WHERE stock_qty > 0 AND part_type = 'CPU' ORDER BY product_code LIMIT 1")
    if row is None:
        print("  [SKIP] (I) 드라이런 영향 예측 — DB 미연결 또는 CPU 후보 없음")
        return
    name = db_one("SELECT product_name FROM products WHERE product_code = :p", p=row)
    # 카테고리를 매핑되지 않는 값으로 준다 → 이 상품은 'ETC'로 강등되어 후보에서 빠진다.
    # 드라이런이 **그 사실을 미리 알리는가**가 이 검사의 핵심이다(슬라이스 50에서
    # 이 경고가 없었다면 후보가 조용히 무너졌다).
    csv_body = (CSV_HEAD + "\n"
                + f'{row},"{(name or "").replace(chr(34), "")}",'
                  'PC/주요부품,CPU,인텔,판매중,1000,2000,3000,회귀,,테스트,회귀모델,\n')
    st, dry = post_raw("/api/admin/catalog-import/dryrun",
                       *_mp({"origin": "real"},
                            {"master": ("regress.csv", csv_body.encode("utf-8"))}))
    check("드라이런 성공", st == 200, 200, st)
    if st != 200:
        return
    check("드라이런은 영향(신규/갱신/후보 진입·이탈)을 알린다",
          all(k in dry["impact"] for k in ("new", "update", "pool_in", "pool_out")),
          "impact 4종", list(dry.get("impact", {})))
    check("드라이런은 되돌릴 수 없다는 사실을 밝힌다",
          "되돌리기는 없습니다" in dry["warning"], "경고 문구", dry["warning"][:40])
    check("기존 상품은 갱신으로 센다", dry["impact"]["update"] == 1 and dry["impact"]["new"] == 0,
          "update=1 new=0", dry["impact"])
    check("분류가 어긋나 후보에서 빠지는 것을 미리 알린다",
          dry["impact"]["pool_out"] == 1, 1, dry["impact"]["pool_out"])
    check("검수 새로 회부 수는 중복을 뺀 실측이다",
          dry["impact"]["review_new"] <= dry["impact"]["review_planned"],
          f'<= {dry["impact"]["review_planned"]}', dry["impact"]["review_new"])
    # 드라이런이 본 것과 다른 건수로는 적용되지 않는다 (여기서 멈춘다 — DB를 바꾸지 않는다)
    st, _ = post_raw("/api/admin/catalog-import/apply",
                     *_mp({"staging_id": dry["staging_id"],
                           "expect_ok": str(dry["summary"]["ok"] + 1)}, {}))
    check("건수가 다르면 적용 거부(409)", st == 409, 409, st)
    st, _ = post_raw("/api/admin/catalog-import/apply",
                     *_mp({"staging_id": "nonexistent0000", "expect_ok": "1"}, {}))
    check("없는 업로드 적용은 404", st == 404, 404, st)

    # ── 외부 사양 제안(다나와) — 슬라이스 51
    # 수집 값은 정본에 바로 들어가지 않고 제안으로만 올라간다. 그 계약을 고정한다.
    sug = db_one("SELECT count(*) FROM product_reviews"
                 " WHERE review_status='대기' AND suggested_value IS NOT NULL")
    if sug is None:
        print("  [SKIP] (I) 외부 제안 계약 — DB 미연결")
    else:
        # 제안이 붙어도 origin_value는 비어 있어야 한다 = 일괄 확정 대상이 아니다(사람 확인 강제)
        auto = db_one("SELECT count(*) FROM product_reviews"
                      " WHERE review_status='대기' AND suggested_value IS NOT NULL"
                      "   AND origin_value IS NOT NULL AND review_type='low_confidence'")
        check("외부 제안은 일괄 확정 대상이 아니다(사람 확인 강제)", auto == 0, 0, auto)
        # 제안이 정본을 앞질러 들어가지 않았는가 — 제안이 있는 필드가 이미 채워져 있으면 모순
        leaked = db_one("""
            SELECT count(*) FROM product_reviews r JOIN product_specs s USING (product_code)
             WHERE r.review_status='대기' AND r.suggested_value IS NOT NULL
               AND ((r.field_name='form_factor_list' AND s.form_factor_list IS NOT NULL)
                 OR (r.field_name='gpu_max_mm' AND s.gpu_max_mm IS NOT NULL)
                 OR (r.field_name='cooler_height_mm' AND s.cooler_height_mm IS NOT NULL))""")
        check("제안값이 승인 없이 정본에 들어가지 않았다", leaked == 0, 0, leaked)
    # 목록형 사양도 승인할 수 있어야 한다(JSONB) — 빠져 있어 케이스 규격을 확정 못 했다
    rules = get("/api/admin/reviews?size=1")
    check("검수 응답이 제안 출처를 밝힌다",
          "queue" in rules and all("suggest_source" in i for i in rules["items"][:1] or [{}]),
          "suggest_source 포함", list((rules["items"] or [{}])[0])[:12])

    # ── 적재 분류 판정 (슬라이스 51)
    # 오분류를 걸러내되 **진짜 부품을 떨어뜨리지 않는 것**이 훨씬 중요하다.
    # 규칙이 넓어지면 멀쩡한 수랭 쿨러·랙마운트 케이스·모듈러 파워가 추천에서 사라진다.
    try:
        sys.path.insert(0, ROOT)
        from api.catalog_map import map_part_type
        CLS = [
            # (라벨, l2, l3, 원문, core_part여야 하는가) — 쿨러는 l3로 공랭/수냉을 가른다
            ("시스템 팬", "CPU쿨러", "공랭쿨러",
             "ARCTIC / 시스템/케이스용 / 시스템 쿨러 / 3000 RPM", False),
            ("수랭 CPU쿨러", "CPU쿨러", "수냉쿨러",
             "샤칸 / 시스템쿨러 / 수랭 / 팬 크기 : 120(mm)", True),
            ("라이저 케이블", "케이스(CASE)", "", "PC내부 전원.튜닝케이블 / 라이저 케이블", False),
            ("랙마운트 케이스", "케이스(CASE)", "",
             "2MONS / 서버, 허브랙 / 랙마운트(3U) / CPU쿨러장착높이 : 110(mm)", True),
            ("SSD 자리의 램", "고속저장(SSD)", "",
             "비즈텍 / 데스크탑 / DDR4 / 16(GB) / 2666(MHz) / CL19 19 19 43", False),
            ("진짜 SSD", "고속저장(SSD)", "",
             "SSD / 제조회사 : 삼성전자 / 디스크 타입 : M.2 (2280)", True),
            ("모듈러 파워", "파워(POWER)", "",
             "리안리 / M ATX,SFX / 정격출력 : 750(W) / 케이블연결 : 풀모듈러", True),
            ("HDMI 케이블", "메인보드(M/B)", "", "케이블/AV(영상.음성)통합관련 / HDMI 케이블", False),
        ]
        bad = []
        for lab, l2, l3, raw, want in CLS:
            _pt, grp, _why = map_part_type("PC/주요부품", l2, l3, lab, raw)
            if (grp == "core_part") != want:
                bad.append(f"{lab}->{grp}")
        check("적재 분류: 비부품은 거르고 진짜 부품은 지킨다", not bad, "전 8종 정확", bad)
    except Exception as e:                               # noqa: BLE001
        print(f"  [SKIP] (I) 적재 분류 판정 — {e}")

    # 검수 큐 정합 — 이미 값이 채워진 항목이 '대기'로 남아 있으면 큐가 부풀어 보인다
    stale = db_one("""
        SELECT count(*) FROM product_reviews r JOIN product_specs s USING (product_code)
         WHERE r.review_status = '대기' AND r.review_type = 'spec_missing'
           AND ((r.field_name = 'socket' AND s.socket IS NOT NULL)
             OR (r.field_name = 'form_factor' AND s.form_factor IS NOT NULL)
             OR (r.field_name = 'mem_type' AND s.mem_type IS NOT NULL)
             OR (r.field_name = 'rated_watt' AND s.rated_watt IS NOT NULL)
             OR (r.field_name = 'cooler_tdp' AND s.cooler_tdp IS NOT NULL))""")
    if stale is None:
        print("  [SKIP] (I) 검수 큐 정합 — DB 미연결")
    else:
        check("검수 대기에 이미 채워진 필드가 없다(tools/prune_reviews.py)",
              stale == 0, 0, stale)


# ───────────────────────── 2. 호환 규칙 (DB 단일 원천) ─────────────────────────
def test_compat():
    print("\n[2] 호환 규칙 — compat_rules 단일 원천 (슬라이스 34)")
    rules = get("/api/admin/engine-rules")["compat"]["checks"]
    active = [r for r in rules if r.get("active", True)]
    drift("compat_rules_active", len(active))
    # 규칙 수도 절대값이 아니라 DB 원천과 대조한다(A-13) — 규칙이 조용히 사라지면 잡힌다.
    rules_db = db_one("SELECT count(*) FROM compat_rules WHERE active")
    if rules_db is None:
        print("  [SKIP] (I) 활성 규칙 수 = DB 실측 — DB 미연결")
    else:
        check("활성 규칙 수 = DB 실측", len(active) == rules_db, rules_db, len(active))
    check("활성 규칙이 하나 이상", len(active) > 0, "> 0", len(active))

    # 규칙은 **빈 DB에서도 서야 한다**(슬라이스 81). 0005는 테이블만 만들고 규칙은
    # 개발 시드(더미 상품·주문과 한 묶음)에만 있었다 — 새로 세운 서버는 규칙이 0이었고,
    # 엔진은 실패하지 않고 조용히 전부 통과시킨다(규칙 없는 슬롯 = 독립).
    # 부트스트랩 마이그레이션이 전 규칙을 덮는지 여기서 지킨다.
    # 빈 DB로 세워도 규칙이 서는가 — 규칙이 마이그레이션 이력에 있어야 한다.
    # (0019가 기본 8종을 넣고, 이후 규칙은 각자의 마이그레이션이 넣는다. 어디에 있든
    #  `alembic upgrade head`만으로 재현되면 된다 — 특정 파일을 고집하지 않는다.)
    try:
        _dir = os.path.join(ROOT, "db", "migrations", "versions")
        _src = "".join(io.open(os.path.join(_dir, f), encoding="utf-8").read()
                       for f in os.listdir(_dir) if f.endswith(".py"))
        gap = sorted(r["key"] for r in active if f"'{r['key']}'" not in _src
                     and f'"{r["key"]}"' not in _src)
        check("활성 규칙은 전부 마이그레이션 이력에 있다", not gap, "누락 없음", gap)
    except Exception as e:                               # noqa: BLE001
        print(f"  [SKIP] (I) 부트스트랩 규칙 대조 — {e}")

    # 규칙이 **한 부품 종류를 통째로 죽이고 있지 않은가**(슬라이스 82 실사고).
    # cooler_height(공랭용)가 슬롯 단위로 걸려 수랭 49개 전부가 NULL 불통과로 탈락했다.
    # 실패도 경고도 없이 사라져서, 화면은 "수랭 재고 239개"라고 말하고 있었다.
    # 규칙이 겨냥한 종류에서 그 필드가 100% 비어 있으면 그 종류는 절대 못 뽑힌다.
    if _engine is None:
        print("  [SKIP] (I) 규칙 전멸 탐지 — DB 미연결")
    else:
        wiped = []
        for r in db_all(
                "SELECT rule_key, slot, field, part_types FROM compat_rules WHERE active"):
            pts = r["part_types"] or SLOT_TYPES_DB.get(r["slot"], [])
            for pt in pts:
                n = db_one("SELECT count(*) FROM v_recommendation_candidates"
                           " WHERE stock_qty>0 AND part_type=:p", p=pt)
                if not n:
                    continue
                have = db_one(f"SELECT count({r['field']}) FROM v_recommendation_candidates"
                              " WHERE stock_qty>0 AND part_type=:p", p=pt)
                if have == 0:
                    wiped.append(f"{r['rule_key']}→{pt}({n}개 전멸)")
        check("규칙이 특정 부품 종류를 전멸시키지 않는다", not wiped, "전멸 없음", wiped)

    # 탐색 가속 인덱스가 **결과를 바꾸지 않는가**(슬라이스 82-B 실사고).
    # build_search_index는 "이 규칙은 슬롯 전체에 걸린다"를 전제로 분기를 자른다.
    # 수랭 전용 규칙을 그대로 넣었더니, 수랭 최대 열이 비어 있는 케이스를 "붙을 쿨러가
    # 없다"며 잘라내 **공랭 구성까지** 더 비싼 케이스로 밀렸다(가성비 316,400 -> 323,800).
    # 규칙이 막은 게 아니라 탐색이 유효한 구성을 못 찾은 것이라 설명조차 할 수 없었다.
    # 인덱스를 끄고 돌린 결과와 같아야 한다 — 다르면 자르기가 결과를 바꾸고 있다.
    try:
        sys.path.insert(0, ROOT)
        from api import recommend as _R
        with _R.engine.begin() as _c:
            _pool, _rules = _R._load_pool(_c), _R.load_compat_rules(_c)
        _cap = _R._budget_cap("150만원")
        _real = _R._build_set("value", _pool, _cap, _rules)
        _orig = _R.build_search_index
        try:
            _R.build_search_index = lambda sp, rl: {"eq": {}, "fwd": []}
            _plain = _R._build_set("value", _pool, _cap, _rules)
        finally:
            _R.build_search_index = _orig
        check("탐색 인덱스가 결과를 바꾸지 않는다",
              (_real or {}).get("total") == (_plain or {}).get("total"),
              (_plain or {}).get("total"), (_real or {}).get("total"))
    except Exception as e:                               # noqa: BLE001
        print(f"  [SKIP] (I) 탐색 인덱스 동등성 — {e}")

    # 화면 계약 — compat-rules.html이 연출을 다시 들이지 않는가(슬라이스 82).
    # 이 화면은 실재하지 않는 규칙 6종(R-01~R-06)과 필드({igpu}·{m2_slots}·{pcie_power}·
    # {slot_width}·{efficiency}·{speed_mts}), 'v5 → v6 발행' 버전 체계,
    # '예상 24,912 → 약 24,7xx'를 사실처럼 보여주고 있었다. 슬라이스 76에서 마진 정책·
    # 가중치에 한 정리를 이 화면만 빠뜨렸다 — 되돌아오지 않게 마크업으로 고정한다.
    _p = admin_html("compat-rules.html")
    _t = io.open(_p, encoding="utf-8").read()
    for bad in ('"R-01"', "{igpu}", "{m2_slots}", "{pcie_power}", "{slot_width}",
                "{speed_mts}", "v6 발행", "24,912"):
        check(f"compat-rules에 연출 잔재 없음: {bad}", bad not in _t, "없음", "발견")
    check("compat-rules는 서버의 필수 사양을 읽는다", "compat.required" in _t,
          "d.compat.required 사용", "없음")
    check("compat-rules는 불러오기 실패를 알린다", "불러오지 못했습니다" in _t,
          "실패 안내 있음", "없음")

    # 화면 구조 전수 감사 — 붙여넣기 사고가 남기는 흔적(슬라이스 87·88 실사고).
    #
    # 재고 입고에 다른 화면의 목록 카드가, 사양 항목 정의에 상품 관리 화면의 스크립트가
    # 통째로 붙어 있었다. 눈에 보인 증상은 "하단 글자가 겹친다" 하나뿐이었지만
    # 실제로는 네 가지가 함께 어긋나 있었다. 정적으로 전부 잡는다.
    #
    #   A 푸터 중복      position-absolute라 같은 자리에 겹쳐 찍힌다
    #   B id 중복        getElementById는 첫 번째만 준다 — 나머지는 빈 채로 남는다
    #   D 끊긴 참조      JS가 부르는 id가 마크업에 없다 → 그 기능이 조용히 죽는다
    #   E 태그 불균형    짝 없는 닫는 태그
    #
    # 오탐을 두 군데서 뺀다: 빈 목록용 `<td colspan>` 행은 데이터 열이 아니고,
    # `el.id = "x"`로 JS가 만드는 요소는 '없는 것'이 아니다.
    import glob as _g2
    import re as _re2
    from collections import Counter as _C
    from html.parser import HTMLParser as _HP

    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
             "meta", "param", "source", "track", "wbr"}

    class _S(_HP):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack, self.stray, self.ids, self.foot, self.insc = [], [], [], 0, 0

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "script":
                self.insc += 1
            if self.insc:
                return
            if a.get("id"):
                self.ids.append(a["id"])
            if tag == "footer" and "position-absolute" in (a.get("class") or ""):
                self.foot += 1
            if tag not in _VOID:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag == "script":
                self.insc = max(0, self.insc - 1)
                return
            if self.insc or tag in _VOID:
                return
            for k in range(len(self.stack) - 1, -1, -1):
                if self.stack[k] == tag:
                    del self.stack[k:]
                    return
            self.stray.append(tag)

    _bad = []
    for _p in admin_htmls():
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        _st = _S()
        _st.feed(_s)
        _js = chr(10).join(_re2.findall(r"<script\b[^>]*>(.*?)</script>", _s, _re2.S))
        if _st.foot > 1:
            _bad.append(f"{_n}: 푸터 {_st.foot}개")
        for _k, _v in _C(_st.ids).items():
            if _v > 1:
                _bad.append(f"{_n}: id={_k} {_v}개")
        _made = (set(_re2.findall(r'id="([^"{$]+)"', _js))
                 | set(_re2.findall(r'\.id\s*=\s*"([^"]+)"', _js)))
        for _b in sorted(set(_re2.findall(r'getElementById\("([^"]+)"\)', _js))
                         - set(_st.ids) - _made):
            if "$" not in _b and "+" not in _b:
                _bad.append(f"{_n}: JS가 #{_b}를 부르는데 없다")
        if _st.stray:
            _bad.append(f"{_n}: 짝 없는 닫는 태그 {_C(_st.stray).most_common(2)}")
    check("관리자 화면 구조 감사(푸터·id 중복·끊긴 참조·태그)", not _bad, "이상 없음", _bad)

    compat = rec("100만원")["value"]["compat"]
    keys = {c["key"] for c in compat["checks"]}
    akeys = {r["key"] for r in active}
    # 1:1은 **적용 부품이 지정되지 않은 규칙**에서만 성립한다. 종류를 좁힌 규칙은 어떤
    # 부품이 뽑혔느냐에 따라 빠질 수 있다(수랭 구성엔 '쿨러 높이 여유'가 없는 게 정상).
    # 개수를 맞추는 검사는 티어가 수랭을 고르는 순간 무작위로 실패한다.
    always = {r["key"] for r in active if not (r.get("part_types") or [])}
    check("근거는 활성 규칙에서만 나온다", keys <= akeys, "부분집합", sorted(keys - akeys))
    check("적용 부품 제한 없는 규칙은 근거에 전부 있다", always <= keys,
          "누락 없음", sorted(always - keys))
    check("호환 검사 전부 통과", all(c["pass"] for c in compat["checks"]),
          "전 항목 pass", [c["key"] for c in compat["checks"] if not c["pass"]])
    check("전원 여유율 100% 이상", (compat["power_headroom_pct"] or 0) >= 100,
          ">= 100", compat["power_headroom_pct"])


# ──────────────────────── 3. 4중 게이트 (추천 풀 진입) ────────────────────────
def test_product_edit():
    print("\n[12] 단건 상품 수정 — 잠금·원장·되돌리기 (슬라이스 53)")
    # ⚠ 정본(data_origin='real') 상품을 쓴다 — data_origin='demo' 필터는 «측정 후»
    # 넣지 않기로 했다(2026-08-15, 46158 사고 조사 후속). 사양 입력·분류 변경 검사와
    # 달리 이건 "데모 표본이 부족해서"가 아니라 **구조적으로 데모로는 못 한다**:
    # v_recommendation_candidates 뷰 정의(WHERE 절)에
    #   p.data_origin::text IS DISTINCT FROM 'demo'::character varying::text
    # 가 박혀 있어 데모 상품은 원천적으로 이 뷰에 안 잡힌다(실측 — pg_get_viewdef).
    # admin_products.get_product의 in_pool도, api/recommend._load_pool(실제 견적 엔진)도
    # 같은 뷰를 본다 — **데모 상품은 편집 전에도 이미 in_pool=False**라는 뜻이다.
    # 그러면 아래 "판매중이 아니면 추천에서 빠진다"(True→False 전이) 검사가 데모로는
    # 편집과 무관하게 항상 통과해 **아무것도 검증하지 못한 채 통과한 것처럼 보인다**
    # (그게 SKIP보다 나쁘다는 지시를 받았다). 데이터를 더 만들어도 못 고치는 종류라
    # DBA에게 넘기지 않는다 — 뷰의 이 배제 자체가 의도된 설계이기 때문이다(데모가 실제
    # 고객 견적에 절대 섞이지 않게 하는 장치, CLAUDE.md "데모/실데이터는 data_origin으로
    # 구분"과 정확히 같은 취지). 그래서 이 선택자는 그대로 두고, 위험 구간만 줄인다:
    # 수정 성공 → 확인 → 되돌리기를 try/finally로 감싸 그 사이 무엇이 터져도 되돌리기가
    # 반드시 시도되게 하고, 되돌린 뒤 DB로 직접 재확인한다(test_stock_ledger와 같은 결).
    # 46158은 이 보장이 없어서 191번째 사이클(활동 로그 log_id 4965, 190회는 정상
    # 맞물렸다)에서 undo 없이 끊긴 채 8일간 방치됐다 — 그리고 그 순간 v_recommendation_
    # candidates에서도 빠져 아래 선택자(ORDER BY product_code LIMIT 1)가 조용히 다음
    # 상품으로 넘어가는 바람에 "회귀 자신이 만든 피해가 회귀 자신의 시야에서 사라지는"
    # 자기 은폐가 겹쳤다. try/finally는 그 첫 번째 원인(undo 누락)을 막는다.
    #
    # 두 번째 원인(선택자가 피해 상품을 다시 안 본다)은 **C안**으로 막는다(하네스 판단,
    # 2026-08-15) — try/finally도 못 도는 잔여 위험(서버 프로세스가 죽는 경우 등)이
    # 이론이 아니라 오늘 밤 세 번 실재했다(T-05). _selftest_no_orphan 참조.
    # own_edit_fields — 아래 "수정 → 되돌리기" 블록의 실제 changes(sale_price·status)와
    # 맞춰 둔다(줄번호 대신 심볼로 확인: grep -n '"changes": {"sale_price"'). 어긋나면
    # 진단 문구가 거짓말을 한다.
    _selftest_no_orphan(
        "last_target_product_edit",
        "SELECT 1 FROM v_recommendation_candidates WHERE product_code=:p AND stock_qty > 0",
        "SELECT status, stock_qty, sale_price, locked_fields"
        " FROM products WHERE product_code=:p",
        own_edit_fields={"sale_price", "status"})
    pc = db_one("SELECT product_code FROM v_recommendation_candidates"
                " WHERE stock_qty > 0 ORDER BY product_code LIMIT 1")
    if pc is None:
        print("  [SKIP] (I) 단건 수정 — DB 미연결")
        return
    _selftest_remember("last_target_product_edit", pc)
    d = get(f"/api/admin/products/{pc}")
    check("상세는 추천 여부를 문장으로 밝힌다", bool(d.get("verdict")), "verdict", d.get("verdict"))
    check("상세에 수정 가능 필드 목록이 있다", bool(d.get("editable")), "editable", d.get("editable"))
    before = {"sale_price": d["sale_price"], "status": d["status"],
              "locked": list(d["locked_fields"])}

    # 가드: 허용 범위·화이트리스트 밖은 막는다 — 정본 수치가 흔들리면 견적이 통째로 흔들린다
    st, _ = post_raw(f"/api/admin/products/{pc}",
                     json.dumps({"changes": {"stock_qty": -1}}).encode(),
                     {"Content-Type": "application/json"}, method="PATCH")
    check("음수 재고는 400", st == 400, 400, st)
    st, _ = post_raw(f"/api/admin/products/{pc}",
                     json.dumps({"changes": {"part_type": "CPU"}}).encode(),
                     {"Content-Type": "application/json"}, method="PATCH")
    check("수정 불가 필드는 400", st == 400, 400, st)

    # ── 수정 → 되돌리기: try/finally로 감싼다(2026-08-15, 46158 재발 방지) ─────────
    # 이 사이(원래는 check 3회)에 예외가 나면 main()의 함수 단위 예외 처리가 그걸
    # 삼키고 다음 테스트로 넘어가 되돌리기가 영영 실행되지 않는다 — 그게 46158에서
    # 실제로 벌어진 일이다. finally는 그 무엇이 터져도 되돌리기를 반드시 시도한다.
    undo_id = None
    try:
        st, r = post_raw(f"/api/admin/products/{pc}",
                         json.dumps({"changes": {"sale_price": (d["sale_price"] or 0) + 1000,
                                                 "status": "품절"}}).encode(),
                         {"Content-Type": "application/json"}, method="PATCH")
        check("수정 성공", st == 200, 200, st)
        if st == 200:
            undo_id = (r or {}).get("undo_id")
            check("수정한 필드는 잠긴다(다음 적재가 덮지 않게)",
                  {"sale_price", "status"} <= set(r["locked_fields"]),
                  "sale_price·status 잠금", r["locked_fields"])
            d2 = get(f"/api/admin/products/{pc}")
            check("상태로 빠진 이유를 정확히 말한다", "품절" in d2["verdict"],
                  "'품절' 언급", d2["verdict"])
            check("판매중이 아니면 추천에서 빠진다", d2["in_pool"] is False, False, d2["in_pool"])
    finally:
        if undo_id is not None:
            try:
                st, _ = post(f"/api/admin/products/undo/{undo_id}")
            except Exception as e:                           # noqa: BLE001
                check("되돌리기 성공(예외 없이 응답한다)", False, "정상 응답", repr(e))
                st = None
            else:
                check("되돌리기 성공(try 중 예외가 나도 finally에서 반드시 시도)",
                      st == 200, 200, st)
            # DB로 직접 재확인 — API가 200을 말해도 실제로 안 바뀌었을 수 있다.
            # 되돌림은 삭제가 아니라 역방향 복원 — 잠금도 함께 되돌아가야 한다.
            now_price = db_one("SELECT sale_price FROM products WHERE product_code=:p", p=pc)
            now_status = db_one("SELECT status FROM products WHERE product_code=:p", p=pc)
            now_locked = db_one("SELECT locked_fields FROM products WHERE product_code=:p", p=pc)
            check("값이 원복된다(DB 직접 재확인)",
                  now_price == before["sale_price"] and now_status == before["status"],
                  before, {"sale_price": now_price, "status": now_status})
            check("잠금도 원복된다(DB 직접 재확인 — 안 그러면 적재가 영영 못 채운다)",
                  now_locked == before["locked"], before["locked"], now_locked)
            if st == 200:
                st2, _ = post(f"/api/admin/products/undo/{undo_id}")
                check("이중 되돌리기는 409", st2 == 409, 409, st2)

    # 등록 화면에 남의 상품 값이 기본으로 들어 있으면 그대로 저장된다(사용자 지적, 슬라이스 55).
    # 마크업에 예시 값이 박혀 있지 않은지 회귀가 지킨다.
    try:
        import re as _re
        html = io.open(admin_html("product-edit.html"),
                       encoding="utf-8").read()
        vals = _re.findall(r'<label class="form-label[^>]*>(상품명|재고 수량|판매가\(원\))</label>'
                           r'<input[^>]*value="([^"]*)"', html)
        dirty = [(lb, v) for lb, v in vals if v.strip()]
        check("등록 폼 입력칸에 예시 값이 박혀 있지 않다", not dirty, "전부 빈 value", dirty)
        # 보기와 고치기가 분리돼 있는가(슬라이스 55) — 보려고 들어갔다 잘못 저장하면
        # locked_fields가 걸려 다음 적재가 그 값을 못 덮는다.
        check("상세는 읽기 전용으로 열린다(?edit=1일 때만 편집)",
              'var EDIT = _q.get("edit") === "1";' in html, "EDIT 기본 false",
              'EDIT' in html)
        check("읽기 모드에서 저장 버튼은 편집 전환만 한다",
              "if(!EDIT){ EDIT = true; paint(); return; }" in html, "전환 분기 존재", False)
        check("저장하면 읽기 모드로 돌아간다(연속 오조작 방지)",
              "EDIT=false;               // 저장했으면 읽기로" in html, "복귀 분기 존재", False)
        lst = io.open(admin_html("products.html"),
                      encoding="utf-8").read()
        check("목록의 행 버튼은 [수정]이고 편집 모드로 간다",
              "&edit=1\">수정</a>" in lst, "[수정] + edit=1",
              "상세</a>" in lst and "미변경")
    except FileNotFoundError:
        print("  [SKIP] (I) 등록 폼 예시 값 — 파일 없음")
    check("없는 상품 조회는 404",
          anon_admin_status(f"/api/admin/products/999999999") in (404, 401), "404", "—")


def anon_admin_status(path):
    """세션을 붙이고 상태코드만 본다(위 검사의 보조)."""
    req = urllib.request.Request(BASE + path, headers=_headers())
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_spec_fields():
    print("\n[13] 사양 항목 정의 — 메타가 코드 상수를 대신한다 (슬라이스 56)")
    d = get("/api/admin/spec-fields")
    check("사양 항목 목록을 준다", bool(d["items"]), "1개 이상", len(d["items"]))
    keys = {f["field_key"] for f in d["items"]}

    # 메타가 코드 상수와 어긋나면 적재·검수·판정이 조용히 달라진다.
    # 상수를 메타로 옮긴 것이 이 슬라이스의 핵심이므로, 둘이 같은지를 회귀가 지킨다.
    try:
        sys.path.insert(0, ROOT)
        from api import spec_fields as SF
        from api.admin_products import REQUIRED_SPEC_FIELDS
        from api.admin_reviews import FIELD_CAST
        from api.catalog_ingest import SPEC_COLS
        SF.reload()
        check("메타 spec_cols == 적재 SPEC_COLS",
              sorted(SF.spec_cols()) == sorted(SPEC_COLS),
              sorted(SPEC_COLS), sorted(SF.spec_cols()))
        rm = SF.required_map()
        bad = [pt for pt in REQUIRED_SPEC_FIELDS
               if sorted(REQUIRED_SPEC_FIELDS[pt]) != sorted(rm.get(pt, []))]
        check("메타 required_map == 필수 사양 정의", not bad, "전 종류 일치", bad)
        # **적재도 같은 원천을 봐야 한다**(슬라이스 84 실사고). 적재는 상수를, 검수·수정은
        # 메타를 보고 있었다 — 주변기기가 상수에 없어서, 같은 모니터가 적재로 들어오면
        # 통과하고 상세에서 한 번 고치면 그 순간 제안 풀에서 빠졌다.
        from api.catalog_ingest import _required_for
        split = [pt for pt in set(list(REQUIRED_SPEC_FIELDS) + list(rm))
                 if sorted(_required_for(pt)) != sorted(rm.get(pt, []))]
        check("적재의 필수 판정 = 메타", not split, "전 종류 일치", split)
        # 주변기기는 견적 슬롯 밖이고 제안 코드가 NULL을 견딘다 — 필수로 걸면
        # 근거 없이 제안을 막는다(모니터 556개가 그랬다).
        peri = [pt for pt in ("MONITOR", "KEYBOARD", "MOUSE", "HEADSET", "SPEAKER", "WEBCAM")
                if rm.get(pt)]
        check("주변기기에는 필수 사양이 걸려 있지 않다", not peri, "없음", peri)
        fc = SF.field_cast()
        badc = [k for k in FIELD_CAST if FIELD_CAST[k] != fc.get(k)]
        check("메타 field_cast == 검수 승인 캐스트", not badc, "전 필드 일치", badc)
    except Exception as e:                               # noqa: BLE001
        print(f"  [SKIP] (I) 메타↔상수 대조 — {e}")

    # 엔진이 읽는 필드는 추천 뷰에 실려 있어야 한다. 빠지면 값은 있는데 판정이 못 본다.
    eng = [f["field_key"] for f in d["items"] if f["is_engine"]]
    if _engine is None:
        print("  [SKIP] (I) 엔진 필드 = 뷰 컬럼 — DB 미연결")
    else:
        missing = [k for k in eng if db_one(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name='v_recommendation_candidates' AND column_name=:k", k=k) == 0]
        check("엔진 사양은 모두 추천 뷰에 실려 있다", not missing, "누락 없음", missing)
        # 메타에 있는 필드는 실제 컬럼이어야 한다(반대도 마찬가지 — 유령 항목 금지)
        ghost = [k for k in keys if db_one(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name='product_specs' AND column_name=:k", k=k) == 0]
        check("메타의 모든 항목에 실제 컬럼이 있다", not ghost, "유령 없음", ghost)

    # 화면에서 만든 항목은 **코드 이력에도 있어야 한다**(슬라이스 81).
    # cpu_gpu 전례: 운영자가 베타 서버에서 항목을 만들었는데 앱이 리포 폴더에 쓸 수 없어
    # 마이그레이션 파일이 안 남았다. 컬럼·메타는 커밋된 뒤라 변경은 살아 있는데 이력만
    # 없는 상태로 하루가 갔고, 그때 복구했다면 그 컬럼은 사라졌을 것이다.
    # 이 불변식이 그 상태를 다음 회귀에서 바로 잡는다.
    check("화면에서 만든 사양 항목에 마이그레이션 이력이 있다",
          d.get("unrecorded") == [], [], d.get("unrecorded"))

    # 부품 축 — 이 화면의 숫자는 전부 서버가 준다(슬라이스 83).
    # 예전 '채워진 값'은 분모가 전 상품 22,841이라 "CPU가 준비됐는가"에 답하지 못했다.
    parts = d.get("parts") or []
    check("부품 축을 서버가 준다", len(parts) >= 10, ">= 10", len(parts))
    core = [p for p in parts if p.get("group") == "core"]
    check("견적 대상 부품이 구분된다", len(core) == 10, 10, len(core))
    # 충족 수는 분모(판매중·재고)를 넘을 수 없다 — 넘으면 분모·분자가 다른 모집단이다
    bad = [f"{p['part_type']}.{f['field_key']}" for p in parts for f in p["fields"]
           if f["filled"] > p["live"]]
    check("충족 수 <= 판매중·재고 수", not bad, "초과 없음", bad)
    # 필수 여부와 메타가 어긋나면 화면이 "빠집니다"를 잘못 말한다
    rm = {f["field_key"]: (f["required_for"] or []) for f in d["items"]}
    mism = [f"{p['part_type']}.{f['field_key']}" for p in parts for f in p["fields"]
            if f["required"] != (p["part_type"] in rm.get(f["field_key"], []))]
    check("부품 축의 필수 표시 = 메타", not mism, "일치", mism)
    if _engine is not None:
        pt0 = next((p for p in core if p["live"]), None)
        if pt0:
            live_db = db_one("SELECT count(*) FROM products WHERE part_type=:p"
                             " AND status='판매중' AND stock_qty>0", p=pt0["part_type"])
            check(f"부품 축 분모 = DB 실측({pt0['part_type']})",
                  pt0["live"] == live_db, live_db, pt0["live"])
    # 두 화면이 같은 답을 해야 한다 — '이 값을 읽는 규칙'은 한 곳에서 계산한다
    er = get("/api/admin/engine-rules")["compat"]["required"]
    er_map = {(g["part_type"], f["key"]): f["used_by"] for g in er for f in g["fields"]}
    diff = [f"{k[0]}.{k[1]}" for k, v in er_map.items()
            if any(f["field_key"] == k[1] and f.get("used_by") != v
                   for p in parts if p["part_type"] == k[0] for f in p["fields"])]
    check("스펙 관리와 호환 규칙 화면이 같은 '읽는 규칙'을 말한다", not diff, "일치", diff)

    # 사양 값 입력 — 화면에서 만든 항목에 값을 넣을 길이 있어야 한다(슬라이스 57).
    # 검수 큐는 '검수 행이 있는 필드'만 다루므로 새 항목은 영영 비어 있게 된다.
    #
    # ⚠ 정본(data_origin='real') 상품을 쓴다 — data_origin='demo' 필터는 «측정 후»
    # 넣지 않기로 했다(2026-08-15, 46158 사고 조사 후속). 실측: 데모 POWER 상품은
    # 3건뿐이고 셋 다 이미 rated_watt가 채워져 있다(form_factor 있음·rated_watt 없음인
    # 표본이 데모엔 0건) — 이 검사가 정확히 필요로 하는 "채울 빈칸"이 데모엔 없다.
    # 필터를 걸면 이 검사는 매번 조용히 SKIP되는데, 그건 정본을 건드리는 것보다
    # 나쁘다(아무것도 검증하지 않으면서 통과한 것처럼 보인다) — 그래서 필터는 걸지
    # 않고 DBA에게 필요한 데모 표본(POWER · form_factor 있음 · rated_watt 없음)을
    # 보고한다. 대신 위험 구간을 줄인다: PATCH → 되돌리기를 try/finally로 감싸 그
    # 사이 무엇이 터져도 되돌리기가 반드시 시도되게 하고, 되돌린 뒤 DB로 직접
    # 재확인한다(test_stock_ledger와 같은 결 — 46158은 이 보장 없이 8일 방치됐다).
    # + C안(하네스 판단, 2026-08-15): 지난 회차 대상이 지금도 건강한지 먼저 본다 —
    # try/finally도 못 도는 잔여 위험(서버가 죽는 등, 오늘 밤 세 번 실재 — T-05)의
    # 유일한 방어다.
    _selftest_no_orphan(
        "last_target_spec_fields",
        "SELECT 1 FROM products p JOIN product_specs s USING (product_code)"
        " WHERE p.product_code=:p AND p.part_type='POWER' AND p.status='판매중'"
        "   AND p.stock_qty>0 AND s.form_factor IS NOT NULL AND s.rated_watt IS NULL",
        "SELECT p.status, p.stock_qty, p.locked_fields, s.rated_watt, s.form_factor"
        "  FROM products p JOIN product_specs s USING (product_code) WHERE p.product_code=:p")
    pc = db_one("""
        SELECT p.product_code FROM products p JOIN product_specs s USING (product_code)
         WHERE p.part_type='POWER' AND p.status='판매중' AND p.stock_qty>0
           AND s.form_factor IS NOT NULL AND s.rated_watt IS NULL
         ORDER BY p.product_code LIMIT 1""")
    if pc is None:
        print("  [SKIP] (I) 사양 값 입력 — 대상 없음")
    else:
        _selftest_remember("last_target_spec_fields", pc)
        pool0 = db_one("SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty>0")
        st, w = post_raw(f"/api/admin/products/{pc}/specs",
                         json.dumps({"values": {"size_inch": 27}}).encode(),
                         {"Content-Type": "application/json"}, method="PATCH")
        check("다른 부품 종류의 사양은 400", st == 400, 400, st)

        # ── PATCH → 되돌리기: try/finally로 감싼다(2026-08-15, 46158 재발 방지) ──
        undo_id = None
        try:
            st, r = post_raw(f"/api/admin/products/{pc}/specs",
                             json.dumps({"values": {"rated_watt": 650}}).encode(),
                             {"Content-Type": "application/json"}, method="PATCH")
            check("사양 입력 성공", st == 200, 200, st)
            if st == 200:
                undo_id = (r or {}).get("undo_id")
                check("입력한 사양은 잠긴다", "rated_watt" in r["locked_fields"],
                      "rated_watt 잠금", r["locked_fields"])
                check("채운 필드의 검수 대기가 해소된다", r["reviews_closed"] >= 0,
                      ">= 0", r["reviews_closed"])
        finally:
            if undo_id is not None:
                try:
                    st2, _ = post(f"/api/admin/products/specs/undo/{undo_id}")
                except Exception as e:                       # noqa: BLE001
                    check("사양 입력 되돌리기(예외 없이 응답한다)", False, "정상 응답", repr(e))
                    st2 = None
                else:
                    check("사양 입력 되돌리기(try 중 예외가 나도 finally에서 반드시 시도)",
                          st2 == 200, 200, st2)
                # DB로 직접 재확인 — API가 200을 말해도 실제로 안 바뀌었을 수 있다
                back = db_one("SELECT rated_watt FROM product_specs WHERE product_code=:p", p=pc)
                check("값이 원복된다(DB 직접 재확인)", back is None, None, back)
                lf = db_one("SELECT locked_fields::text FROM products WHERE product_code=:p", p=pc)
                check("잠금도 원복된다(DB 직접 재확인)", "rated_watt" not in (lf or ""), "잠금 없음", lf)
                pool1 = db_one("SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty>0")
                check("되돌린 뒤 추천 후보가 제자리(DB 직접 재확인)", pool1 == pool0, pool0, pool1)
                if st2 == 200:
                    st3, _ = post(f"/api/admin/products/specs/undo/{undo_id}")
                    check("사양 이중 되돌리기는 409", st3 == 409, 409, st3)
    _spec_field_guards()


def test_pool_gate():
    print("\n[15] 후보 게이트 — 팔 수 없는 부품은 견적에 못 들어온다 (슬라이스 62)")
    # '4중 게이트(사양·검수·가격·재고)'라고 적어 두고 뷰는 가격을 보지 않았다.
    # 판매가 NULL인 상품 하나가 후보에 들어와 예산 비교가 TypeError를 냈고
    # **견적 API 전체가 500**이 됐다. 조용히 줄어드는 게 아니라 화면이 통째로 죽는다.
    n = db_one("SELECT count(*) FROM v_recommendation_candidates WHERE sale_price IS NULL")
    check("후보 풀에 판매가 없는 부품이 없다", n == 0, 0, n)
    n2 = db_one("SELECT count(*) FROM v_recommendation_candidates"
                " WHERE stock_qty > 0 AND sale_price IS NULL")
    check("재고 있는 후보는 전부 가격이 있다", n2 == 0, 0, n2)
    # 게이트를 우회해 값이 없는 부품이 생겨도 엔진이 죽지 않아야 한다(이중 방어)
    try:
        src = io.open(os.path.join(ROOT, "api", "recommend.py"), encoding="utf-8").read()
        check("엔진 풀 로드가 가격을 다시 확인한다",
              "sale_price IS NOT NULL" in src, "방어 조건 있음", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 엔진 방어 — {e}")

    # 시각은 타임존을 달고 나가야 한다(슬라이스 62). DB는 UTC로 돌고 컬럼은
    # timestamp without time zone이라, 그냥 isoformat()하면 타임존 없는 문자열이 된다.
    # 브라우저의 new Date()는 그걸 **로컬 시각으로 해석**해 UTC 07:27이 서울 07:27로
    # 찍혔다 — 실제로는 16:27이라 9시간이 어긋났다(사용자 보고).
    log = get("/api/admin/activity-logs?size=1")
    rows = log.get("items") or log.get("logs") or []
    if rows:
        at = rows[0].get("at") or rows[0].get("created_at")
        check("작업 기록 시각에 타임존이 붙어 있다",
              bool(at) and ("+" in at[10:] or at.endswith("Z")), "+00:00 또는 Z", at)
        try:
            from datetime import datetime as _dt, timedelta as _td, timezone as _tz
            d = _dt.fromisoformat(at)
            check("작업 기록 시각이 지금과 가깝다(시계 어긋남 없음)",
                  abs((_dt.now(_tz.utc) - d).total_seconds()) < 86400,
                  "24시간 이내", str(d))
        except ValueError as e:                          # noqa: BLE001
            check("작업 기록 시각을 파싱할 수 있다", False, "ISO 형식", f"{at} ({e})")
    # 코드에 타임존 없는 isoformat()이 남아 있으면 같은 사고가 반복된다
    bad = []
    for f in glob.glob(os.path.join(ROOT, "api", "*.py")):
        if os.path.basename(f) == "timeutil.py":
            continue
        if ".isoformat()" in io.open(f, encoding="utf-8").read():
            bad.append(os.path.basename(f))
    check("API에 타임존 없는 isoformat()이 없다", not bad, "전부 iso() 사용", bad)


def test_password_auth():
    print("\n[17] 관리자 비밀번호 인증 — Basic Auth를 걷을 근거 (슬라이스 70)")
    # 예전에는 이메일만 맞으면 들어왔다(dev 어댑터). nginx Basic Auth가 유일한 방벽이라
    # 그걸 걷으면 승인된 관리자 이메일을 아는 사람은 누구나 들어왔다.
    # **이 항목이 통과해야 Basic Auth를 걷을 수 있다.**
    st, d = post("/api/admin/auth/login", {"email": ADMIN_EMAIL})
    check("비밀번호 없이는 못 들어온다", st == 401, 401, st)
    st, d = post("/api/admin/auth/login",
                 {"email": ADMIN_EMAIL, "password": "definitely-wrong-9999"})
    check("틀린 비밀번호는 401", st == 401, 401, st)
    if st == 401 and isinstance((d or {}).get("detail"), dict):
        # 어느 쪽이 틀렸는지 말하면 계정 존재 여부가 새어 나간다
        m = d["detail"].get("message") or ""
        check("어느 쪽이 틀렸는지 말하지 않는다",
              "이메일 또는 비밀번호" in m, "모호한 문구", m[:40])

    # 비밀번호가 없는 계정은 자동 발급되지 않는다 — 자동 발급은 곧 뒷문이다
    noped = db_one("SELECT email FROM admin_operators WHERE password_hash IS NULL"
                   " AND status='활성' LIMIT 1")
    if noped:
        st2, d2 = post("/api/admin/auth/login",
                       {"email": noped, "password": "whatever-12345!"})
        check("비밀번호 미설정 계정은 403", st2 == 403, 403, st2)
        check("미설정 계정이 자동으로 만들어지지 않는다",
              db_one("SELECT password_hash FROM admin_operators"
                     " WHERE lower(email)=:e", e=noped.lower()) is None,
              None, "생성됨")

    # 해시만 저장된다 — DB가 새도 비밀번호는 새지 않는다
    h = db_one("SELECT password_hash FROM admin_operators WHERE lower(email)=:e",
               e=ADMIN_EMAIL.lower())
    check("비밀번호는 scrypt 해시로 저장된다",
          bool(h) and h.startswith("scrypt$"), "scrypt$...", (h or "")[:16])
    check("저장값에 원문이 없다", bool(h) and ADMIN_PW not in h, "원문 없음", "원문 포함")

    try:
        sys.path.insert(0, ROOT)
        from api.passwords import strength_problem, verify_password
        check("빈 비밀번호는 통과하지 못한다", not verify_password("", h), False, True)
        check("약한 비밀번호는 거부된다",
              all(strength_problem(p) for p in ("short1!", "aaaaaaaaaaaa", "12345678901")),
              "전부 거부", "일부 통과")
        check("긴 무작위 비밀번호는 통과", strength_problem("Vq7#mzLp2rTx") is None,
              None, strength_problem("Vq7#mzLp2rTx"))
    except Exception as e:                               # noqa: BLE001
        print(f"  [SKIP] (I) 비밀번호 모듈 — {e}")

    # 잠금 판정은 DB가 한다 — 파이썬 datetime.now()(KST)와 DB now()(UTC)를 비교하면
    # 9시간 어긋나 잠금이 통째로 무시된다(슬라이스 62와 같은 부류의 사고)
    try:
        src = io.open(os.path.join(ROOT, "api", "auth.py"), encoding="utf-8").read()
        check("잠금 판정을 DB가 한다", "locked_until > now()" in src,
              "SQL 판정", "파이썬 비교")
        check("실패 기록이 롤백되지 않는다", "with engine.begin() as conn2" in src,
              "별도 트랜잭션", "같은 트랜잭션")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 잠금 계약 — {e}")

    # 화면이 비밀번호를 받는가
    try:
        lg = io.open(admin_html("login.html"),
                     encoding="utf-8").read()
        check("로그인 화면에 비밀번호 칸이 있다",
              'id="password"' in lg and "password: document" in lg.replace('"', '"'),
              "입력+전송", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 로그인 화면 — {e}")


def test_doc_counts():
    """[31] 문서 정합 — 문서가 말하는 수 = 실제 (슬라이스 103)

    2026-07-30 HANDOFF를 갱신하다 **문서의 수가 실제와 어긋난 것을 셋 찾았다**:
    관리자 화면 31(실제 33) · 호환 규칙 8종(실제 9종) · 존재하지도 않는 `sale_prices`
    테이블을 근거로 적힌 backlog 항목.

    `CLAUDE.md`는 **매 턴 컨텍스트에 로드된다** — 거기 적힌 수가 틀리면 그 세션 내내 틀린
    전제로 일한다. 그래서 이 수들은 산문이 아니라 **검사되는 불변식**으로 둔다.
    (원칙은 색 토큰 때와 같다: 값을 문서에 다시 적지 말거나, 적었으면 대조하거나.)
    """
    print("\n[31] 문서 정합 — 문서가 말하는 수 = 실제 (슬라이스 103)")
    import glob as _g7
    import re as _re7

    real_screens = len([p for p in _g7.glob(os.path.join(ROOT, "mockups", "admin", "*.html"))
                        if "data-screen-id" in io.open(p, encoding="utf-8").read()])
    real_html = len(_g7.glob(os.path.join(ROOT, "mockups", "admin", "*.html")))
    check("관리자 화면 수를 실제로 센다", real_screens > 0, "> 0", real_screens)

    for doc in ("CLAUDE.md", "HANDOFF.md"):
        s = io.open(os.path.join(ROOT, doc), encoding="utf-8").read()
        said = [int(m) for m in _re7.findall(r"`mockups/admin/`\s*\*\*(\d+)화면", s)]
        check(f"{doc}가 말하는 관리자 화면 수 = 실제",
              said == [] or all(n == real_screens for n in said),
              real_screens, said)
        said_html = [int(m) for m in _re7.findall(r"`\.html`\s*(\d+)개", s)]
        check(f"{doc}가 말하는 .html 파일 수 = 실제",
              said_html == [] or all(n == real_html for n in said_html),
              real_html, said_html)

    rules_db = db_one("SELECT count(*) FROM compat_rules WHERE active")
    if rules_db is None:
        print("  [SKIP] (I) 문서의 호환 규칙 수 = DB 실측 — DB 미연결")
    else:
        # 표 칸(`| 활성 호환 규칙 | **9종** |`)과 산문을 둘 다 잡는다. 처음엔 산문만 잡는
        # 정규식을 썼더니 HANDOFF의 표를 못 봐 `said == []`로 **공허하게 통과**했다 —
        # 아무것도 검사하지 않는 검사가 가장 나쁘다(있으면 안심하는데 지키는 게 없다).
        seen_any = False
        for doc in ("CLAUDE.md", "HANDOFF.md"):
            s = io.open(os.path.join(ROOT, doc), encoding="utf-8").read()
            said = [int(m) for m in _re7.findall(r"호환 규칙[^\n]{0,12}?\*\*(\d+)종", s)]
            seen_any = seen_any or bool(said)
            check(f"{doc}가 말하는 호환 규칙 수 = DB 실측",
                  said == [] or all(n == rules_db for n in said), rules_db, said)
        # 정책 개정(2026-08-12 사용자 결정): **낡는 수는 문서에 적지 않는다** — CLAUDE.md 의
        # 규칙 수 셋이 전부 틀린 채 발견된 날이다. 이 수를 말하는 정본은 이제
        # scripts/state.py 이고, DB 를 직접 읽으므로 어긋날 수가 없다.
        # 「최소 한 문서는 말한다」는 그 정책과 충돌해 폐기한다. 공허-통과 우려는
        # 아래로 대신한다: ① 문서가 굳이 적으면 맞아야 한다(위 검사 유지)
        # ② state.py 가 이 수를 실제로 잰다 — 아무도 안 재는 상태를 막는다.
        sp = io.open(os.path.join(ROOT, "scripts", "state.py"), encoding="utf-8").read()
        check("호환 규칙 수는 state.py 가 DB에서 잰다(문서 대신)",
              "compat_rules" in sp and "WHERE active" in sp, "compat_rules 조회", "없음")

    # 없는 테이블을 근거로 적지 않는다 — 이전 판의 backlog가 `sale_prices`를 들고 있었다.
    if _engine is None:
        print("  [SKIP] (I) 문서가 실재하는 테이블만 가리킨다 — DB 미연결")
    else:
        tables = {r["table_name"] for r in db_all(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
        ghosts = []
        for doc in ("CLAUDE.md", "HANDOFF.md"):
            s = io.open(os.path.join(ROOT, doc), encoding="utf-8").read()
            # 백틱 안의 snake_case 중 **테이블 이름으로 알려진 것만** 본다.
            # 아무 snake_case나 테이블로 오해하면 오탐이 쏟아지고, 회귀가 자기 소음에
            # 묻히면 아무도 안 본다.
            for m in set(_re7.findall(r"`([a-z][a-z0-9_]{4,})`", s)):
                if m in _KNOWN_TABLE_WORDS and m not in tables:
                    ghosts.append(f"{doc}:{m}")
        check("문서가 없는 테이블을 근거로 적지 않는다", not ghosts, "없음", sorted(ghosts))


# 문서가 '테이블'이라 부르며 적을 법한 이름만 본다 — 아무 snake_case나 테이블로 오해하면
# 오탐이 쏟아진다(회귀가 자기 소음에 묻히면 아무도 안 본다).
_KNOWN_TABLE_WORDS = {
    "sale_prices", "product_prices", "stock_movements", "compat_rules", "usage_floors",
    "pricing_settings", "product_reviews", "product_specs", "admin_operators",
    "admin_sessions", "spec_field_defs", "promo_click_logs", "consult_sessions",
    "supplier_prices", "product_supplier_prices", "price_history", "product_price_history",
}


def test_taxonomy_single_source():
    """[32] 부품 어휘 단일 원천 — 정의는 taxonomy.py에만 있다 (슬라이스 A)

    2026-08-04 기존 임대 관리자를 실사하다 그쪽 `베스트7주력부품`이 부품 분류 트리를
    약어로 복제한 **두 번째 트리**인 것을 봤다. 같은 CPU가 어느 트리에 들어가는지가
    담당자 기분에 달려 있었다. 그래서 우리 코드를 세어 보니 **같은 병이 이미 있었다**:

        SLOT_KO      admin_setup · admin_swap_logs · candidates · swap   네 벌
        라벨 맵      PART_TYPE_LABELS · PART_KO · SLOT_KO   세 어휘 여섯 곳
        코어 집합    admin_pool.CORE_TYPES · admin_products.CORE_PARTS   두 벌
        슬롯표       recommend.SLOT_TYPES · candidates.QUOTE_SLOTS       두 벌

    그리고 **두 곳이 이미 어긋나 있었다** — swap.py만 SSD를 "저장장치"로 표시했고
    (부품 교체 안내에서만 다른 말이 나갔다), PART_TYPE_LABELS만 수랭을 "수냉"으로 썼다
    (자기 안에서도 공"랭"/수"냉"으로 어긋나 있었다).

    **정의를 여러 벌 두면 어긋난다.** 카테고리 트리를 이 위에 얹으면 복제본이 하나 더
    는다. 그래서 taxonomy.py로 모으고, 여기서 그 상태를 지킨다.
    """
    print("\n[32] 부품 어휘 단일 원천 — 정의는 taxonomy.py에만 있다 (슬라이스 A)")
    import re as _re8

    from api import taxonomy as _T
    from api.admin_products import PART_TYPE_LABELS as _PTL, CORE_PARTS as _CP
    from api.admin_engine_rules import PART_KO as _PK
    from api.admin_setup import SLOT_KO as _SA
    from api.admin_swap_logs import SLOT_KO as _SB
    from api.candidates import SLOT_KO as _SC, QUOTE_SLOTS as _QS, _floor_slot as _fs
    from api.swap import SLOT_KO as _SD
    from api.recommend import SLOTS as _SL, SLOT_TYPES as _ST

    # 1) 같은 객체를 보고 있는가 — 복사본이면 언제든 다시 어긋난다
    check("SLOT_KO 네 곳이 같은 객체", _SA is _SB is _SC is _SD is _T.SLOT_LABELS,
       "taxonomy.SLOT_LABELS", "복사본 존재")
    check("part_type 라벨 맵이 같은 객체", _PTL is _PK is _T.PART_LABELS,
       "taxonomy.PART_LABELS", "복사본 존재")
    check("슬롯표가 같은 객체", _QS is _ST is _T.QUOTE_SLOTS,
       "taxonomy.QUOTE_SLOTS", "복사본 존재")
    check("코어 집합이 한 벌", _CP == set(_T.CORE_TYPES), True, _CP == set(_T.CORE_TYPES))
    check("슬롯 목록·하한 슬롯이 단일 원천", _SL is _T.SLOTS and _fs is _T.slot_of,
       True, _SL is _T.SLOTS and _fs is _T.slot_of)

    # 2) 어긋났던 두 라벨이 실제로 고쳐졌는가 (되돌아가면 여기서 잡힌다)
    check("SSD 라벨은 'SSD' — swap만 '저장장치'였다", _T.SLOT_LABELS["SSD"] == "SSD",
          "SSD", _T.SLOT_LABELS["SSD"])
    _cool = (_T.PART_LABELS["COOLER_CPU_AIR"], _T.PART_LABELS["COOLER_CPU_AIO"])
    check("공랭/수랭 표기가 서로 맞는다", _cool == ("CPU쿨러(공랭)", "CPU쿨러(수랭)"),
          ("CPU쿨러(공랭)", "CPU쿨러(수랭)"), _cool)

    # 3) taxonomy.py 밖에서 다시 정의하지 않는가 — 소스를 스캔한다.
    #    이 검사가 없으면 다음 사람이 조용히 일곱 번째 복제본을 만든다.
    api_dir = os.path.join(ROOT, "api")
    dup = []
    # 이름을 넉넉히 잡는다 — 처음엔 PART_LABEL(단수)·ALL_PART_TYPES를 빠뜨려
    # 복제본 세 벌을 놓쳤다. 검사가 좁으면 없는 안심을 준다.
    PAT = _re8.compile(r"^\s*(SLOT_KO|SLOT_LABELS?|PART_KO|PART_TYPE_LABELS?|PART_LABELS?"
                       r"|CORE_TYPES|CORE_PARTS|QUOTE_SLOTS|SLOT_TYPES|SLOTS"
                       r"|ALL_PART_TYPES|PART_TYPES|ASSIGNABLE_TYPES"
                       r"|DISPLAY_LABELS|DISPLAY_MEMBERS|DISPLAY_TYPES)\s*=\s*[{\[(]",
                       _re8.M)
    for fn in sorted(os.listdir(api_dir)):
        if not fn.endswith(".py") or fn == "taxonomy.py":
            continue
        for m in PAT.finditer(io.open(os.path.join(api_dir, fn), encoding="utf-8").read()):
            dup.append(f"{fn}:{m.group(1)}")
    check("taxonomy.py 밖에서 부품 어휘를 정의하지 않는다", dup == [], [], dup)

    # 4) part_type 상수 = DB 실측 (문서 정합과 같은 사상 — 상수도 낡는다)
    if _engine is not None:
        with _engine.connect() as c:
            live = {r[0] for r in c.execute(text(
                "SELECT DISTINCT part_type FROM products WHERE part_type IS NOT NULL"))}
        _unknown = sorted(live - set(_T.PART_TYPES))
        check("taxonomy.PART_TYPES ⊇ DB 실측 part_type", _unknown == [], [], _unknown)

    # 5) 슬롯표가 실제 part_type만 가리키는가 (오타 하나면 그 슬롯이 통째로 전멸한다)
    bad = sorted({t for ts in _T.QUOTE_SLOTS.values() for t in ts} - set(_T.PART_TYPES))
    check("슬롯표가 가리키는 part_type이 전부 실재", bad == [], [], bad)
    check("슬롯 목록 = 슬롯표 키", sorted(_T.SLOTS) == sorted(_T.QUOTE_SLOTS),
          sorted(_T.QUOTE_SLOTS), sorted(_T.SLOTS))

    # 6) 표시 축(운영자가 고르는 종류)은 **파생**이지 두 번째 정의가 아니다.
    #    사용자 결정(2026-08-05): 화면에서 CPU쿨러 공랭·수랭을 하나로 본다 → 16종.
    #    **엔진의 part_type 은 17종 그대로여야 한다** — 여기가 무너지면
    #    radiator_rows(수랭 589건)가 적용 대상을 잃고 케이스 수납 판정이 사라진다.
    #    2026-08-05: 완성품 축 2종(PC_COMPLETE·BAREBONE)이 늘어 17 → 19 가 됐다.
    #    **수가 늘어난 것 자체는 문제가 아니다** — 지켜야 하는 것은 쿨러 쌍이 갈린 채로
    #    남아 있는 것과, 늘어난 값이 엔진 뷰에 새어 들어가지 않는 것이다(아래 7번).
    check("part_type 은 19종 (조립 10 + 주변기기 6 + 완성품 2 + 미분류)",
          len(_T.PART_TYPES) == 19, 19, len(_T.PART_TYPES))
    check("표시 종류는 18종 (쿨러만 하나로 접힌다)", len(_T.DISPLAY_TYPES) == 18,
          18, len(_T.DISPLAY_TYPES))
    check("완성품은 어느 견적 슬롯에도 없다",
          not any(t in v for v in _T.QUOTE_SLOTS.values() for t in _T.BUILT_TYPES),
          "슬롯 없음",
          [t for v in _T.QUOTE_SLOTS.values() for t in _T.BUILT_TYPES if t in v])
    check("완성품은 핵심 부품이 아니다",
          not any(t in _T.CORE_TYPES for t in _T.BUILT_TYPES), "제외",
          [t for t in _T.BUILT_TYPES if t in _T.CORE_TYPES])
    check("표시 축이 part_type 을 하나도 빠뜨리지 않는다",
          {t for ts in _T.DISPLAY_MEMBERS.values() for t in ts} == set(_T.PART_TYPES),
          "전부 포함",
          sorted(set(_T.PART_TYPES) - {t for ts in _T.DISPLAY_MEMBERS.values() for t in ts}))
    check("표시 'COOLER' = 공랭 + 수랭",
          _T.expand_display("COOLER") == ("COOLER_CPU_AIR", "COOLER_CPU_AIO"),
          ("COOLER_CPU_AIR", "COOLER_CPU_AIO"), _T.expand_display("COOLER"))
    # 라벨을 두 번 적지 않았는가 — 슬롯 라벨과 같은 객체에서 왔어야 한다.
    check("쿨러 표시 라벨 = 슬롯 라벨(같은 원천)",
          _T.DISPLAY_LABELS["COOLER"] == _T.SLOT_LABELS["COOLER"],
          _T.SLOT_LABELS["COOLER"], _T.DISPLAY_LABELS["COOLER"])
    # 쿨러 말고는 접히지 않는다 — 접기 규칙이 번지면 다른 종류가 조용히 합쳐진다.
    _folded = sorted(k for k, v in _T.DISPLAY_MEMBERS.items() if len(v) > 1)
    check("접히는 것은 쿨러뿐", _folded == ["COOLER"], ["COOLER"], _folded)

    # 2단 선택(2026-08-07) — 고르는 자리는 표시 축을 그대로 쓰되, 접히는 종류는
    # 두 번째 칸으로 묻는다. **화면은 무엇이 접히는지 몰라야 한다** — `options` 유무만 본다.
    _tree = _T.choice_tree(_T.CORE_TYPES)
    _keys = [e["key"] for e in _tree]
    check("등록 선택지 = 표시 축(쿨러가 한 칸)",
          _keys.count("COOLER") == 1 and "COOLER_CPU_AIO" not in _keys,
          "COOLER 한 칸", _keys)
    _cool_e = [e for e in _tree if e["key"] == "COOLER"][0]
    check("쿨러만 두 번째 칸을 갖는다",
          [e["key"] for e in _tree if e.get("options")] == ["COOLER"],
          ["COOLER"], [e["key"] for e in _tree if e.get("options")])
    check("두 번째 칸 = 공랭 · 수랭 (part_type 코드)",
          [o["key"] for o in _cool_e["options"]] == ["COOLER_CPU_AIR", "COOLER_CPU_AIO"],
          ["COOLER_CPU_AIR", "COOLER_CPU_AIO"], [o["key"] for o in _cool_e["options"]])
    check("두 번째 칸 라벨은 냉각 방식만 말한다",
          [o["label"] for o in _cool_e["options"]] == ["공랭", "수랭"],
          ["공랭", "수랭"], [o["label"] for o in _cool_e["options"]])
    # 접힌 키는 **저장 가능한 값이 아니다** — 화면이 그대로 보내면 서버가 막아야 한다.
    check("접힌 키 COOLER 는 part_type 이 아니다",
          "COOLER" not in _T.PART_TYPES, "part_type 아님", "COOLER 가 part_type 에 있음")
    # 화면은 세 자리에서 셀렉트를 채운다(단가표發 등록 · 수정 · 단건 등록).
    # 셋 다 **같은 원천**(part_choices/all_choices)을 써야 한다 — 하나라도 옛 라벨 경로로
    # 남으면 그 자리에서만 쿨러가 갈라진다(단일 원천 규율).
    _pe = pathlib.Path(admin_html("product-edit.html")).read_text(encoding="utf-8")
    check("상품 등록·수정 화면에 옛 라벨 선택지 경로가 남지 않았다",
          "part_labels" not in _pe, "없음", "part_labels 사용처가 남아 있음")
    check("분류 셀렉트를 채우는 자리가 전부 choices 원천",
          _pe.count("part_choices") + _pe.count("all_choices") >= 3,
          ">=3", _pe.count("part_choices") + _pe.count("all_choices"))
    # 되돌림은 **서버가 말한 현재 값**을 쓴다 — 화면의 cur 는 저장 직후 재도색 전 창에서
    # 낡는다. 실제로 "공랭을 저장하고 수랭을 보여주는" 화면을 재현했다(2026-08-07).
    check("분류 변경 취소는 서버 답으로 되돌린다", "srvFrom" in _pe,
          "srvFrom 사용", "화면의 cur 로 되돌리고 있음")

    # 7) **엔진이 읽는 두 뷰는 화이트리스트다** — 새 part_type 이 늘어도 새어 들어가면 안 된다.
    #    완제품 PC 축(2026-08-05)을 넣기 **전에** 이 검사를 먼저 걸었다. 축을 늘리는 일은
    #    "추천에 안 들어간다"를 말로 보장할 수 없고, 뷰가 실제로 막는지 봐야 한다.
    #    두 뷰 모두 `category_group` 과 `part_type` 을 **둘 다** 화이트리스트로 건다(실측).
    if _engine is not None:
        with _engine.connect() as c:
            _leak = c.execute(text(
                "SELECT count(*) FROM v_recommendation_candidates"
                " WHERE part_type NOT IN ('CPU','GPU','MB','RAM','SSD','HDD','POWER','CASE',"
                "                         'COOLER_CPU_AIR','COOLER_CPU_AIO')")).scalar()
            check("추천 후보에 조립 부품 아닌 종류가 없다", _leak == 0, 0, _leak)
            _leak2 = c.execute(text(
                "SELECT count(*) FROM v_companion_candidates"
                " WHERE part_type NOT IN ('MONITOR','KEYBOARD','MOUSE','HEADSET',"
                "                         'SPEAKER','WEBCAM')")).scalar()
            check("주변기기 후보에 주변기기 아닌 종류가 없다", _leak2 == 0, 0, _leak2)
            # 완제품·베어본은 어느 후보에도 없어야 한다(축이 생긴 뒤에도)
            _pc = c.execute(text(
                "SELECT (SELECT count(*) FROM v_recommendation_candidates"
                "          WHERE part_type IN ('PC_COMPLETE','BAREBONE'))"
                "     + (SELECT count(*) FROM v_companion_candidates"
                "          WHERE part_type IN ('PC_COMPLETE','BAREBONE'))")).scalar()
            check("완제품·베어본은 어느 후보에도 없다", _pc == 0, 0, _pc)
            # **적재가 되돌리면 여기서 잡는다.** `part_type` 은 적재마다 다시 계산되는
            # 파생값인데 완제품은 원천 분류 토큰을 잴 근거가 없어(원천 CSV 부재 ·
            # product_imports 0행) `catalog_map` 에 분기를 넣지 못했다. 배정 근거는
            # 운영자가 갈라 놓은 판매 분류이고, 그 둘이 어긋나면 되돌아간 것이다.
            _drift = c.execute(text(
                "SELECT count(*) FROM products p JOIN categories ct USING (category_id)"
                " WHERE ct.name IN ('완제품 PC','미니PC·베어본') AND p.part_type = 'ETC'")).scalar()
            check("완제품 분류인데 ETC 로 되돌아간 상품이 없다", _drift == 0, 0, _drift)

            # ── 등급 축 (0032 · 재설계안 §3-①) ────────────────────────────
            # **엔진은 아직 등급을 읽지 않는다.** 축만 만들고 값이 찬 뒤에 연결한다 —
            # 지금 연결하면 등급 없는 부품이 전부 0점이 되거나 등급 있는 소수만
            # 추천되거나 둘 중 하나이고, 둘 다 지금보다 나쁘다. 완제품 축과 같은 순서로
            # **배제 불변식을 먼저 건다.** 연결하는 슬라이스가 이 검사를 의도적으로
            # 고치게 되고, 그때 비로소 "이제 읽는다"가 기록으로 남는다.
            _eng = pathlib.Path(ROOT, "api")
            _readers = []
            for _f in ("recommend.py", "candidates.py", "swap.py", "pricing.py"):
                _t = pathlib.Path(_eng, _f)
                if _t.exists() and "part_grades" in _t.read_text(encoding="utf-8"):
                    _readers.append(_f)
            check("엔진이 아직 등급을 읽지 않는다", _readers == [], [], _readers)
            # 추천 뷰도 마찬가지 — 뷰에 들어가면 엔진이 조용히 읽게 된다.
            _vg = c.execute(text(
                "SELECT count(*) FROM pg_views WHERE viewname IN"
                " ('v_recommendation_candidates','v_companion_candidates')"
                " AND definition ILIKE '%part_grades%'")).scalar()
            check("추천 뷰에 등급이 들어가 있지 않다", _vg == 0, 0, _vg)

            # 근거 없는 등급은 **스키마가** 막는다 — 규율이 아니라 구조로 강제한다.
            # (지어낸 태그를 금지한 것과 같은 규칙. 정체성이 걸린 자리다.)
            _nn = c.execute(text(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name='part_grades' AND column_name='basis'"
                "   AND is_nullable='NO'")).scalar()
            check("등급의 근거 칸은 NOT NULL 이다", _nn == 1, 1, _nn)
            _ck = c.execute(text(
                "SELECT count(*) FROM pg_constraint WHERE conrelid='part_grades'::regclass"
                " AND contype='c' AND pg_get_constraintdef(oid) ILIKE '%btrim(basis)%'")).scalar()
            check("근거가 공백만이어도 막는다", _ck == 1, 1, _ck)
            # 등급은 조립 부품에만 매긴다 — 주변기기·완제품은 비교 축이 다르다.
            _bad = c.execute(text(
                "SELECT count(*) FROM part_grades g JOIN products p USING (product_code)"
                " WHERE p.part_type NOT IN ('CPU','GPU','MB','RAM','SSD','HDD','POWER','CASE',"
                "                           'COOLER_CPU_AIR','COOLER_CPU_AIO')")).scalar()
            check("조립 부품 아닌 것에 등급이 없다", _bad == 0, 0, _bad)

            # 등급판 화면 계약 — 브라우저 없이 마크업으로 본다
            _gb = pathlib.Path(admin_html("grade-board.html")).read_text(encoding="utf-8")
            # **엔진이 안 읽는다는 사실을 화면이 먼저 말한다.** 안 그러면 운영자는
            # "저장했는데 견적이 안 바뀐다"를 결함으로 신고한다(화면 정직성).
            check("등급판이 '엔진이 아직 안 읽는다'를 화면에 적는다",
                  "engineNote" in _gb and "engine_note" in _gb, True,
                  "engineNote" in _gb and "engine_note" in _gb)
            # 슬롯 선택지는 서버가 준다 — 화면이 부품 어휘를 지어내지 않는다.
            check("등급판이 슬롯을 서버에서 받는다",
                  "grades/meta" in _gb, True, "grades/meta" in _gb)
            # **오류 문구는 공용 헬퍼가 만든다.** 화면이 따로 만들면 진행 바와
            # 서로 다른 말을 한다. 인자 순서도 고정한다 — (json, status) 다.
            check("등급판이 공용 오류 문구를 쓴다",
                  "popcornProgress.errText(j, status)" in _gb, True,
                  "popcornProgress.errText(j, status)" in _gb)
            # 셸을 베낄 때 원본 화면의 스크립트가 따라오면 같은 id 를 두 곳이 만진다
            # (실제로 용도 하한의 스크립트가 딸려 와 상태 배지를 덮어썼다).
            check("등급판에 다른 화면의 스크립트가 섞이지 않았다",
                  "floors" not in _gb, True, "floors" not in _gb)

            # ── 교체율 (재설계안 §1-① · 2026-08-07) ──────────────────────
            # **분모가 없으면 건수는 뜻을 갖지 못한다.** 분모는 견적 스냅샷이다 —
            # `recommendation_items` 는 0행이고 엔진이 쓰지 않는다(실측).
            # 그쪽을 분모로 삼으면 0으로 나누거나 전 슬롯이 0%가 된다.
            _api_sw = pathlib.Path(ROOT, "api", "admin_swap_logs.py").read_text(encoding="utf-8")
            check("교체율 분모가 견적 스냅샷이다",
                  "quote_snapshots" in _api_sw, True, "quote_snapshots" in _api_sw)
            # **주석까지 잡지 않는다** — 왜 안 쓰는지 적은 설명이 검사에 걸린다
            # (이 프로젝트에서 세 번 겪었다). 실제 사용처인 SQL 만 본다.
            _nl = chr(10)
            _sw_sql = _nl.join(l for l in _api_sw.split(_nl)
                               if not l.strip().startswith("#"))
            check("교체율이 죽은 표(recommendation_items)를 분모로 쓰지 않는다",
                  "FROM recommendation_items" not in _sw_sql, True,
                  "FROM recommendation_items" not in _sw_sql)
            # 스냅샷 형식이 둘이다(지금 {parts:[...]} · 옛 [ ... ] 1행). 하나만 보면
            # 그 행들이 조용히 분모에서 빠진다.
            check("교체율이 스냅샷 두 형식을 모두 센다",
                  "jsonb_typeof" in _api_sw, True, "jsonb_typeof" in _api_sw)
            # **결과 축이 정책 축으로 돌아가는 화살표.** 이 링크가 없으면 기록이
            # 기록으로만 남는다 — 재설계안이 지목한 열린 루프가 그대로다.
            check("교체율이 고칠 화면을 지목한다",
                  "usage-floors.html" in _api_sw and "policy-weights.html" in _api_sw
                  and "grade-board.html" in _api_sw, True,
                  [x for x in ("usage-floors.html", "policy-weights.html", "grade-board.html")
                   if x not in _api_sw])
            _sw = pathlib.Path(admin_html("swap-logs.html")).read_text(encoding="utf-8")
            check("교체 화면이 판정 문구를 서버에서 받는다",
                  "r.reading" in _sw and "r.fix" in _sw, True,
                  "r.reading" in _sw and "r.fix" in _sw)

            # ── 실패를 삼키지 않는다 — 오류 문구 (2026-08-07 사용자 신고) ──────
            # "관리자 화면 상단에 계속 ! 오류 409" — **어느 요청인지 아무도 몰랐다.**
            # 422 의 `detail` 배열을 못 읽어 "오류 422" 만 뜨던 것과 같은 병이다.
            _up = pathlib.Path(ROOT, "mockups", "shared", "ui-progress.js").read_text(encoding="utf-8")
            # ① 응답 본문의 **맨 위**도 본다 — `{"error": ...}` 로 오는 것들이 있다.
            # 2026-08-15: 이 검사가 문자열 리터럴 "j.error || j.message"(고정 순서) 하나만
            # 찾고 있었다. 같은 날 다른 제작자가 사람이 읽는 우선순위를 바로잡으며(message/
            # note 문장이 있는데도 error 코드가 뜨던 병 — 위 docstring §142행대 참조)
            # 순서를 `j.message || j.note || j.error`로 고쳤다. **동작은 그대로인데(셋 다
            # 여전히 읽는다) 검사만 형태(문자열 순서)로 실패했다** — 이 저장소의 알려진
            # 병(작업 #44 "회귀가 «이름/형태»로 «동작»을 추정한다", #43과 같은 부류).
            # 그래서 순서에 매이지 않고, "본문 맨 위" 폴백을 만드는 실제 문장
            # (`var top = j && ...;`)을 정규식으로 찾아 **그 문장이 error·message·note
            # 세 키를 전부 읽는지**(집합 비교 — 순서 무관)를 본다. `d.*`(중첩 detail
            # 객체용 별도 변수 `inner`, 131행대)는 다른 문장이라 `j.` 접두를 요구하는 이
            # 정규식에 안 걸린다 — 섞이면 안 되는 다른 폴백 경로라 의도적으로 배제했다.
            _top_m = _re8.search(r"var\s+top\s*=\s*[^;]*;", _up)
            _top_src = _top_m.group(0) if _top_m else ""
            _top_keys = set(_re8.findall(r"\bj\.(message|note|error)\b", _top_src))
            check("오류 문구가 본문 맨 위에서 error·message·note 를 전부 읽는다(순서 무관)",
                  _top_keys == {"message", "note", "error"},
                  {"message", "note", "error"},
                  _top_keys if _top_src else "'var top = j && ...;' 문장을 못 찾음(변수명이 바뀌었을 수 있다)")
            # ② 읽을 문장이 없으면 **무엇이 실패했는지라도** 말한다. 상태 코드만 띄우면
            #    운영자도 개발자도 추측만 하게 된다.
            check("읽을 문장이 없으면 실패한 요청을 밝힌다",
                  'where ? " — " + where' in _up, True, 'where ? " — " + where' in _up)
            check("진행 바가 실패한 요청을 함께 넘긴다",
                  'errText(j, res.status, method + " " + path(url))' in _up, True,
                  'errText(j, res.status, method + " " + path(url))' in _up)


def test_categories():
    """[33] 카테고리 트리 — 판매 축은 엔진과 분리돼 있다 (슬라이스 B)

    `categories`는 **판매 탐색 축**이고 `part_type`은 **엔진 축**이다. 기존 임대 관리자는
    이 둘을 한 트리에 섞어 대분류 20개가 상품분류·완제품유형·마케팅노출·내부업무·폐기를
    동시에 뜻하게 됐고, 미매핑 1,458건(판매중 325건)이 조용히 쌓였다.

    **가장 중요한 계약: 운영자가 카테고리를 옮겨도 견적 결과가 변하면 안 된다**(A-02).
    그래서 엔진 모듈이 이 표를 참조하지 않는지 소스로 확인한다 — 한 번이라도 참조하면
    "카테고리를 정리했더니 견적이 달라졌다"가 생기고, 그때는 원인을 찾을 수 없다.
    """
    print("\n[33] 카테고리 트리 — 판매 축은 엔진과 분리돼 있다 (슬라이스 B)")
    import re as _re9

    # 1) 엔진은 categories를 모른다 — 이 검사가 이 슬라이스의 핵심이다.
    ENGINE = ("recommend.py", "candidates.py", "swap.py", "usage_floors.py", "taxonomy.py")
    touch = []
    for fn in ENGINE:
        _p = os.path.join(ROOT, "api", fn)
        if not os.path.exists(_p):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        # 주석·docstring의 언급은 봐주고 **코드에서 표를 읽는 것**만 잡는다.
        code = _re9.sub(r'"""[\s\S]*?"""', "", _s)
        code = _re9.sub(r"#.*", "", code)
        if _re9.search(r"\bcategories\b|\bcategory_id\b", code):
            touch.append(fn)
    check("엔진 모듈이 categories를 읽지 않는다", touch == [], [], touch)

    d = get("/api/admin/categories")          # get()은 본문만 돌려준다(상태코드 없음)
    items = (d or {}).get("items") or []
    check("카테고리 목록을 준다", isinstance(items, list), "list", type(items).__name__)
    check("카테고리가 있다", len(items) > 0, "> 0", len(items))

    ids = {c["category_id"] for c in items}

    # 2) 트리가 트리인가 — 부모가 실재하고 고리가 없다
    orphan = sorted(c["category_id"] for c in items
                    if c["parent_id"] is not None and c["parent_id"] not in ids)
    check("부모가 없는 카테고리가 없다", orphan == [], [], orphan)

    parent = {c["category_id"]: c["parent_id"] for c in items}
    looped = []
    for cid in ids:
        seen, cur = set(), cid
        while cur is not None:
            if cur in seen:
                looped.append(cid)
                break
            seen.add(cur)
            cur = parent.get(cur)
    check("트리에 순환이 없다", looped == [], [], sorted(looped))

    # 3) 형제 이름 중복 없음(부분 유니크 인덱스가 지키는 것을 응답으로도 확인)
    pairs = [(c["parent_id"], c["name"]) for c in items]
    dup = sorted({p for p in pairs if pairs.count(p) > 1})
    check("같은 자리에 같은 이름이 없다", dup == [], [], dup)

    # 4) 서버가 세는 수 = DB가 세는 수 (화면이 숫자를 지어내지 않게)
    if _engine is not None:
        with _engine.connect() as c:
            live = dict(c.execute(text(
                "SELECT category_id, count(*) FROM products"
                " WHERE category_id IS NOT NULL GROUP BY 1")).all())
            unmapped = c.execute(text(
                "SELECT count(*) FROM products WHERE category_id IS NULL")).scalar()
            viol = c.execute(text(
                "SELECT count(*) FROM products p JOIN categories c USING (category_id)"
                " WHERE c.allowed_part_types IS NOT NULL"
                "   AND NOT (c.allowed_part_types @> to_jsonb(p.part_type))")).scalar()
        bad = [c["category_id"] for c in items
               if c["product_count"] != live.get(c["category_id"], 0)]
        check("카테고리별 상품 수 = DB 실측", bad == [], [], bad)
        check("미매핑 수 = DB 실측", d.get("unmapped") == unmapped, unmapped, d.get("unmapped"))
        said_viol = sum(c.get("violations", 0) for c in items)
        check("허용 종류 위반 수 = DB 실측", said_viol == viol, viol, said_viol)

    # 5) 가드 — 쓰기 경로는 거부만 확인한다(회귀는 정본을 바꾸지 않는다)
    st, _ = post("/api/admin/categories", {"name": "   "})
    check("빈 이름은 400", st == 400, 400, st)
    st, _ = post("/api/admin/categories", {"name": "회귀시험", "allowed_part_types": ["NOPE"]})
    check("없는 부품 종류는 400", st == 400, 400, st)
    st, _ = post("/api/admin/categories", {"name": "회귀시험", "parent_id": 99999999})
    check("없는 상위는 404", st == 404, 404, st)
    if items:
        st, _ = post("/api/admin/categories", {"name": items[0]["name"],
                                               "parent_id": items[0]["parent_id"]})
        check("같은 자리 동명은 409", st == 409, 409, st)
        # 상품이 걸린 카테고리는 지울 수 없다 — 지우면 그 상품들이 조용히 미매핑이 된다
        withp = next((c for c in items if c["product_count"] > 0), None)
        if withp:
            st, _ = post_raw("/api/admin/categories/%d" % withp["category_id"],
                             None, {}, method="DELETE")
            check("상품이 있는 카테고리 삭제는 409", st == 409, 409, st)
    st, _ = post_raw("/api/admin/categories/99999999",
                     json.dumps({"name": "x"}).encode(),
                     {"Content-Type": "application/json"}, method="PATCH")
    check("없는 카테고리 수정은 404", st == 404, 404, st)

    # 6) 화면 계약 — 마크업이 서버 값을 쓰는가(브라우저 없이)
    _p = admin_html("categories.html")
    if os.path.exists(_p):
        _h = io.open(_p, encoding="utf-8").read()
        check("화면이 ADM-CAT-010이다", 'data-screen-id="ADM-CAT-010"' in _h, True,
              'data-screen-id="ADM-CAT-010"' in _h)
        check("화면이 /api/admin/categories를 부른다", "/api/admin/categories" in _h, True,
              "/api/admin/categories" in _h)
        # 숫자를 마크업에 박아두지 않는다 — 요약 칸은 전부 자리표시자로 시작해야 한다
        holder = _re9.search(r'id="mMapped"[^>]*>([^<]*)<', _h)
        check("매핑 수가 마크업에 박혀 있지 않다",
              bool(holder) and not _re9.search(r"\d", holder.group(1)),
              "숫자 없음", holder.group(1) if holder else "(없음)")

def test_category_mapping():
    """[34] 상품 카테고리 매핑 — 남은 일을 화면이 먼저 말한다 (슬라이스 C)

    슬라이스 B가 part_type 17종을 1단으로 깔아 전량 매핑됐지만, **`미분류` 하나에
    5,148건(재고>0 2,415건)이 몰려 있다.** 그 안에는 케이블·마우스패드·캡처보드·확장카드·
    시스템팬·그래픽카드 지지대, 그리고 PC와 무관한 "한경희 미니 건조기"까지 들어 있다.

    기존 임대 관리자는 미매핑 1,458건을 별도 화면에 두고 방치했다. 여기서는 **서버가
    일이 있는 곳을 가리키고**(`open_at`) 화면이 거기로 연다 — 기본 탭이 늘 비어 있으면
    운영자는 할 일이 없다고 읽는다.

    쓰기 경로는 **가드만** 확인한다(회귀는 정본을 바꾸지 않는다 — 슬라이스 50 전례).
    """
    print(chr(10) + "[34] 상품 카테고리 매핑 — 남은 일을 화면이 먼저 말한다 (슬라이스 C)")
    import re as _re10

    d = get("/api/admin/category-mapping?scope=all&size=1")
    counts = (d or {}).get("counts") or {}
    check("범위별 건수를 준다",
          all(k in counts for k in ("unmapped", "violation", "unclassified", "all_products")),
          "unmapped·violation·unclassified·all_products", sorted(counts))

    # 서버가 가리키는 곳이 실제로 비어 있지 않은가 — 빈 화면으로 열면 안 된다
    open_at = (d or {}).get("open_at")
    size_of = {"unmapped": counts.get("unmapped"), "violation": counts.get("violation"),
               "unclassified": counts.get("unclassified"), "all": counts.get("all_products")}
    check("open_at이 가리키는 범위에 실제로 일이 있다",
          open_at == "all" or (size_of.get(open_at) or 0) > 0,
          "> 0", {open_at: size_of.get(open_at)})

    if _engine is not None:
        with _engine.connect() as c:
            live = c.execute(text(
                "SELECT count(*) FILTER (WHERE category_id IS NULL) u,"
                "       count(*) FILTER (WHERE part_type = 'ETC') e,"
                "       count(*) a FROM products")).one()
        check("미매핑 수 = DB 실측", counts.get("unmapped") == live[0], live[0],
              counts.get("unmapped"))
        check("미분류 수 = DB 실측", counts.get("unclassified") == live[1], live[1],
              counts.get("unclassified"))
        check("전체 수 = DB 실측", counts.get("all_products") == live[2], live[2],
              counts.get("all_products"))

    # **탭이 말하는 수 = 그 탭을 눌렀을 때 나오는 수.**
    # 예전엔 'unclassified' 가 서버 범위가 아니라 화면이 카테고리 id로 치환하는 값이었고,
    # 그 id는 "allowed_part_types 가 정확히 ['ETC']인 첫 카테고리"였다. 미분류를 갈라내며
    # 그 조건에 맞는 카테고리가 13개가 되자 탭은 5,148을 말하고 목록은 1,668을 보여줬다.
    for _sc, _k in (("unmapped", "unmapped"), ("violation", "violation"),
                    ("unclassified", "unclassified"), ("all", "all_products")):
        _d = get("/api/admin/category-mapping?scope=%s&size=1" % _sc)
        check("탭 '%s' 의 수 = 그 범위의 실제 건수" % _sc,
              _d.get("total") == counts.get(_k), counts.get(_k), _d.get("total"))

    # **두 화면이 같은 부품 종류 목록을 본다.**
    # 사용자 지적(2026-08-05): 카테고리 관리는 17종을 한글로 보여주는데 상품 매핑은
    # `CASE`·`MB`·`GPU` 같은 **영문 키**를 보여줬다. 매핑 API 가 part_types 를 주지 않아
    # 화면이 ① 현재 페이지 상품과 ② 카테고리의 allowed_part_types 에서 조립했기 때문이다
    # (②에는 라벨이 없다). 탭을 바꾸면 목록도 달라졌다.
    # CLAUDE.md 가 슬라이스 66에 적어 둔 함정을 되풀이한 것이다 —
    # "목록 필터 선택지는 서버가 준다. 화면이 현재 페이지에서 뽑으면 그 페이지에 없는 값은
    #  아예 안 나온다."
    cat_pt = [(x["key"], x["label"]) for x in (get("/api/admin/categories") or {}).get("part_types", [])]
    map_pt = [(x["key"], x["label"]) for x in (d or {}).get("part_types", [])]
    check("매핑 API 가 부품 종류 목록을 준다", len(map_pt) > 0, "> 0", len(map_pt))
    # 개수만 보고하면 "17 대 17"이 되어 무엇이 다른지 알 수 없다 — 다른 항목을 보여준다.
    _diff = sorted(set(cat_pt) ^ set(map_pt))[:4]
    check("두 화면의 부품 종류 목록이 같다", cat_pt == map_pt,
          "동일", _diff or ("순서 다름" if sorted(cat_pt) == sorted(map_pt) else "다름"))
    # 탭이 바뀌어도 목록은 그대로여야 한다(조립하던 시절엔 탭마다 달랐다)
    _drift = []
    for _sc in ("unmapped", "violation", "unclassified"):
        _o = get("/api/admin/category-mapping?scope=%s&size=1" % _sc)
        if [(x["key"], x["label"]) for x in (_o or {}).get("part_types", [])] != map_pt:
            _drift.append(_sc)
    check("탭이 바뀌어도 부품 종류 목록이 같다", _drift == [], [], _drift)

    # 표시 축이 화면까지 살아 왔는가 — 16종이고 쿨러가 하나여야 한다(2026-08-05).
    # 2026-08-05 완성품 축 2종이 늘어 16 -> 18. 매핑 화면은 **완제품도 걸러 볼 수 있어야**
    # 하므로 표시 축 전체를 그대로 받는다(taxonomy.DISPLAY_LABELS 와 같은 수).
    check("화면이 받는 부품 종류는 18종", len(map_pt) == 18, 18, len(map_pt))
    check("쿨러가 한 줄로 온다", ("COOLER", "CPU쿨러") in map_pt,
          ("COOLER", "CPU쿨러"), [x for x in map_pt if x[0].startswith("COOLER")])

    # **필터가 실제로 두 종류를 함께 잡는가.** 여기가 핵심이다 —
    # 'COOLER'를 그대로 `part_type =` 에 넣으면 그런 값은 없어서 조용히 0건이 된다.
    # 화면엔 선택지가 멀쩡히 보이는데 고르면 빈 목록이 나오는 형태의 고장이다.
    _cool = get("/api/admin/category-mapping?scope=all&part_type=COOLER&size=1")
    _got = (_cool or {}).get("total")
    if _engine is not None:
        with _engine.connect() as c:
            _want = c.execute(text(
                "SELECT count(*) FROM products WHERE part_type IN"
                " ('COOLER_CPU_AIR','COOLER_CPU_AIO')")).scalar()
        check("쿨러 필터 = 공랭 + 수랭 실측", _got == _want, _want, _got)
    else:
        check("쿨러 필터가 0건이 아니다", bool(_got), "> 0", _got)

    # 판매 트리에서도 쿨러는 한 노드다(0029). 두 개로 되돌아가면 여기서 잡힌다.
    _cats = (get("/api/admin/categories") or {}).get("items", [])
    _cool_nodes = [c["name"] for c in _cats
                   if any(str(t).startswith("COOLER_")
                          for t in (c.get("allowed_part_types") or []))]
    check("판매 트리의 쿨러 노드는 하나", len(_cool_nodes) == 1, 1, _cool_nodes)

    # 목록은 서버 페이지네이션이다 — 전 행을 보내면 안 된다(22,838건)
    d2 = get("/api/admin/category-mapping?scope=all&size=10&page=2")
    check("페이지 크기를 지킨다", len(d2.get("items") or []) <= 10, "<= 10",
          len(d2.get("items") or []))
    check("전체 건수를 함께 준다", (d2.get("total") or 0) >= len(d2.get("items") or []),
          ">= 표시 건수", d2.get("total"))
    check("쪽수를 계산해 준다", (d2.get("pages") or 0) > 1, "> 1", d2.get("pages"))
    check("2쪽은 1쪽과 다른 상품이다",
          {i["product_code"] for i in (d2.get("items") or [])}
          != {i["product_code"] for i in (get("/api/admin/category-mapping?scope=all&size=10")
                                          .get("items") or [])},
          "다름", "같음")

    # 가드
    st, _ = post("/api/admin/category-mapping/move", {"product_codes": [], "category_id": 1})
    check("빈 선택은 400", st == 400, 400, st)
    st, _ = post("/api/admin/category-mapping/move",
                 {"product_codes": [1], "category_id": 99999999})
    check("없는 카테고리는 404", st == 404, 404, st)
    st, _ = post("/api/admin/category-mapping/move",
                 {"product_codes": [999999999], "category_id":
                  (d.get("categories") or [{}])[0].get("category_id") or 1})
    check("없는 상품은 404", st == 404, 404, st)
    st, _ = post("/api/admin/category-mapping/undo", {"log_id": 999999999})
    check("없는 이동 기록 되돌리기는 404", st == 404, 404, st)
    try:
        get("/api/admin/category-mapping?scope=nope")
        check("알 수 없는 범위는 400", False, 400, 200)
    except urllib.error.HTTPError as e:
        check("알 수 없는 범위는 400", e.code == 400, 400, e.code)

    # 화면 계약
    _p = admin_html("category-mapping.html")
    if os.path.exists(_p):
        _h = io.open(_p, encoding="utf-8").read()
        check("화면이 ADM-CAT-020이다", 'data-screen-id="ADM-CAT-020"' in _h, True,
              'data-screen-id="ADM-CAT-020"' in _h)
        check("화면이 서버가 가리킨 곳으로 연다", "open_at" in _h, True, "open_at" in _h)
        check("일괄 이동에 되돌리기가 있다", "category-mapping/undo" in _h, True,
              "category-mapping/undo" in _h)
        # 상한을 화면이 숨기지 않는다
        check("한 번에 옮길 상한을 화면이 말한다", "max_move" in _h, True, "max_move" in _h)
        holder = _re10.search(r'id="cUncls"[^>]*>([^<]*)<', _h)
        check("미분류 수가 마크업에 박혀 있지 않다",
              bool(holder) and not _re10.search(r"[0-9]", holder.group(1)),
              "숫자 없음", holder.group(1) if holder else "(없음)")

def test_category_isolation():
    """[35] 카테고리를 옮겨도 견적은 그대로다 — 실측 (슬라이스 D)

    `[33]`은 **소스를 읽어** 엔진이 categories를 참조하지 않는지 본다. 그건 정적 검사라
    간접 경로(뷰·조인·다른 모듈 경유)를 놓칠 수 있다. 여기서는 **실제로 옮겨 보고
    같은 견적이 나오는지** 확인한다.

      ① 견적을 낸다 → 부품 구성과 총액을 기억한다
      ② 그 견적에 실제로 들어간 부품들을 새 카테고리로 옮긴다
      ③ 같은 입력으로 다시 견적을 낸다 → **부품·총액이 한 글자도 달라지면 안 된다**
      ④ 되돌리고 시험 카테고리를 지운다

    ②가 중요하다 — 견적과 무관한 상품을 옮기면 이 검사는 아무것도 지키지 않는다.

    회귀는 정본을 바꾸지 않는다는 규칙(슬라이스 50)의 예외다. 용도 하한 검사(슬라이스 75)와
    같은 형태로, **바꾼 것을 반드시 되돌리고 되돌아왔는지까지 확인한다.**
    """
    print(chr(10) + "[35] 카테고리를 옮겨도 견적은 그대로다 — 실측 (슬라이스 D)")

    def fingerprint(sets):
        """견적의 지문 — 티어별 (부품 코드 목록, 총액)."""
        out = {}
        for k, v in (sets or {}).items():
            if not isinstance(v, dict):
                continue
            parts = v.get("items") or []
            out[k] = (tuple(sorted(p.get("product_code") for p in parts)), v.get("total"))
        return out

    before = fingerprint(rec("150만원"))
    check("견적이 나온다(비교할 것이 있다)", len(before) > 0, "> 0 티어", len(before))
    codes = sorted({c for v in before.values() for c in v[0] if c is not None})
    check("견적에 실제 부품이 들어 있다", len(codes) > 0, "> 0", len(codes))
    if not codes:
        return

    st, made = post("/api/admin/categories",
                    {"name": "__회귀_격리시험", "sort_order": 999})
    check("시험 카테고리를 만든다", st == 200, 200, st)
    cid = (made or {}).get("category_id")
    if not cid:
        return

    log_id = None
    try:
        st, mv = post("/api/admin/category-mapping/move",
                      {"product_codes": codes, "category_id": cid})
        check("견적에 쓰인 부품을 옮긴다", st == 200, 200, st)
        log_id = (mv or {}).get("log_id")
        check("옮긴 수가 견적 부품 수와 맞는다", (mv or {}).get("moved") == len(codes),
              len(codes), (mv or {}).get("moved"))

        after = fingerprint(rec("150만원"))
        check("카테고리를 옮겨도 견적 구성이 같다",
              {k: v[0] for k, v in after.items()} == {k: v[0] for k, v in before.items()},
              "동일", "다름")
        check("카테고리를 옮겨도 총액이 같다",
              {k: v[1] for k, v in after.items()} == {k: v[1] for k, v in before.items()},
              {k: v[1] for k, v in before.items()},
              {k: v[1] for k, v in after.items()})
    finally:
        # 되돌린다 — 검사가 흔적을 남기면 안 된다(슬라이스 78 전례).
        if log_id:
            st, _ = post("/api/admin/category-mapping/undo", {"log_id": log_id})
            check("이동을 되돌린다", st == 200, 200, st)
        st, _ = post_raw("/api/admin/categories/%d" % cid, None, {}, method="DELETE")
        check("시험 카테고리를 지운다(=상품이 남아 있지 않다)", st == 200, 200, st)

    restored = fingerprint(rec("150만원"))
    check("원복 뒤 견적도 처음과 같다", restored == before, "동일", "다름")

    # 대시보드·작업 패널이 카테고리 잔여를 말하는가 — 별도 화면에 숨겨 두지 않는다
    dash = get("/api/admin/dashboard")
    wl = get("/api/admin/worklist")
    pend = (dash or {}).get("pending") or {}
    check("대시보드가 미매핑·미분류를 센다",
          "unmapped" in pend and "unclassified" in pend,
          "unmapped·unclassified", sorted(pend))
    cat_item = next((i for i in (wl or {}).get("items") or []
                     if i.get("key") == "category"), None)
    check("작업 패널에 카테고리 매핑이 있다", cat_item is not None, "있음", "없음")
    if cat_item:
        check("작업 패널 수 = 대시보드 수",
              cat_item["count"] == pend["unmapped"] + pend["unclassified"],
              pend["unmapped"] + pend["unclassified"], cat_item["count"])
        check("작업 패널이 매핑 화면으로 보낸다",
              cat_item.get("href") == "category-mapping.html",
              "category-mapping.html", cat_item.get("href"))

    if _engine is not None:
        with _engine.connect() as c:
            live = c.execute(text(
                "SELECT count(*) FILTER (WHERE category_id IS NULL),"
                "       count(*) FILTER (WHERE part_type='ETC') FROM products")).one()
        check("대시보드 미매핑 = DB 실측", pend["unmapped"] == live[0], live[0], pend["unmapped"])
        check("대시보드 미분류 = DB 실측", pend["unclassified"] == live[1], live[1],
              pend["unclassified"])

def test_reprice():
    """[36] 판매가 재산정 — 오름과 내림을 합치지 않는다 (슬라이스 E)

    마진 정책은 화면에서 고칠 수 있었지만 **이미 매겨진 판매가를 정책에 맞출 길이 없었다.**
    기존 `_reprice`는 공급처 단가 변동용이라 `product_supplier_prices` 행이 없으면 아무것도
    하지 않는데, 매입가가 있는 18,748건 중 **18,743건이 그 행이 없다.**

    ■ 실측이 설계를 바꿨다
    처음엔 "정책과 다른 것 N건"으로 낼 생각이었다. 재 보니 18,540건에 총액 -2.4억이었고,
    나눠 보니 서로 다른 셋이 섞여 있었다: 정책 미달(대부분·올라간다) · 역마진 1,008건 ·
    배수 2.0 이상 이상치 206건(최대 20,000배 — 매입 45,000 / 판매 9억).
    **합치면 9억짜리 이상치 한 건이 나머지 18,539건의 인상분을 덮는다.**
    그래서 오름·내림을 갈라서 내고, 이상치와 역마진을 따로 센다.

    쓰기 경로(apply)는 **가드만** 확인한다 — 실행하면 실제 판매가 수천 건이 움직인다
    (슬라이스 50 전례: 회귀가 정본을 오염시키면 안 된다). apply·undo의 정상 동작은
    슬라이스 E에서 22,838건 스냅샷 대조로 한 번 검증했다(전량 원복 확인).
    """
    print(chr(10) + "[36] 판매가 재산정 — 오름과 내림을 합치지 않는다 (슬라이스 E)")

    d = get("/api/admin/reprice/preview?scope=live")
    check("미리보기를 준다", isinstance(d, dict) and "changed" in d, "changed 포함", sorted(d))
    check("공식을 문장으로 밝힌다", "매입가" in (d.get("formula") or ""), "공식 문장",
          d.get("formula"))

    # 오름·내림이 갈라져 있는가 — 이 슬라이스의 핵심
    for k in ("up_count", "down_count", "up_sum", "down_sum", "outlier_count",
              "negative_count", "locked_count"):
        check(f"{k}를 따로 낸다", k in d, "있음", "없음")
    check("변동 = 오름 + 내림",
          d.get("changed") == d.get("up_count", 0) + d.get("down_count", 0),
          d.get("up_count", 0) + d.get("down_count", 0), d.get("changed"))
    check("오름 합계는 음수가 아니다", (d.get("up_sum") or 0) >= 0, ">= 0", d.get("up_sum"))
    check("내림 합계는 양수가 아니다", (d.get("down_sum") or 0) <= 0, "<= 0", d.get("down_sum"))
    check("대상 = 오름+내림+그대로+잠김",
          d.get("target") == d.get("up_count", 0) + d.get("down_count", 0)
          + d.get("same", 0) + d.get("locked_count", 0),
          d.get("target"),
          d.get("up_count", 0) + d.get("down_count", 0) + d.get("same", 0)
          + d.get("locked_count", 0))

    # 공식이 단일 원천인가 — 엔진 규칙 화면이 말하는 예시와 같은 값이어야 한다
    er = get("/api/admin/engine-rules")
    pr = ((er or {}).get("pricing") or {})
    if pr.get("example"):
        from api.pricing import sale_from_purchase
        want = sale_from_purchase(pr["example"]["purchase"],
                                  d.get("card_fee_rate"), d.get("margin_rate"))
        check("두 화면이 같은 공식을 쓴다", pr["example"]["sale"] == want, want,
              pr["example"]["sale"])

    # 서버가 세는 수 = DB가 세는 수
    if _engine is not None:
        from api.pricing import sale_from_purchase as _sfp
        with _engine.connect() as c:
            fee, margin = [float(x) for x in c.execute(text(
                "SELECT card_fee_rate, margin_rate FROM pricing_settings"
                " ORDER BY effective_from DESC LIMIT 1")).one()]
            rows = c.execute(text(
                "SELECT purchase_price, sale_price, locked_fields FROM products"
                " WHERE purchase_price IS NOT NULL AND purchase_price > 0"
                "   AND status='판매중' AND stock_qty>0")).all()
        up = down = same = locked = 0
        up_sum = down_sum = 0
        for pur, sale, lock in rows:
            new = _sfp(pur, fee, margin)
            if "sale_price" in (lock or []):
                if new != sale:
                    locked += 1
                continue
            if new == sale:
                same += 1
            elif sale is None or new > sale:
                up += 1
                up_sum += (new - sale) if sale is not None else 0
            else:
                down += 1
                down_sum += new - sale
        check("오름 수 = DB 실측", d.get("up_count") == up, up, d.get("up_count"))
        check("내림 수 = DB 실측", d.get("down_count") == down, down, d.get("down_count"))
        # **합계도 대조한다** — 부호만 보면 오름에 내림을 섞어도 양수라 통과한다.
        # 이 슬라이스가 막으려는 것이 정확히 그 섞임이므로 값으로 잡는다.
        check("오름 합계 = DB 실측", d.get("up_sum") == up_sum, up_sum, d.get("up_sum"))
        check("내림 합계 = DB 실측", d.get("down_sum") == down_sum, down_sum, d.get("down_sum"))
        check("그대로 수 = DB 실측", d.get("same") == same, same, d.get("same"))
        check("잠긴 판매가는 변동에 세지 않는다", d.get("locked_count") == locked, locked,
              d.get("locked_count"))

    # 정책 비율이 저장되면서 조용히 반올림되지 않는가 (슬라이스 E 실사고)
    # 2.585%를 넣었더니 NUMERIC(5,4) 때문에 0.0259가 되어 화면이 "2.59%"라고 말했다.
    # API는 200을 돌려줬고 아무도 오류를 보지 못했다 — **사용자가 정한 값이 시스템 안에서
    # 다른 값이 된 채로 남았다.** 0028에서 자릿수를 넓혔고, 여기서 그 상태를 지킨다.
    if _engine is not None:
        with _engine.connect() as c:
            scale = c.execute(text(
                "SELECT numeric_scale FROM information_schema.columns"
                " WHERE table_name='pricing_settings' AND column_name='card_fee_rate'")).scalar()
            stored = float(c.execute(text(
                "SELECT card_fee_rate FROM pricing_settings"
                " ORDER BY effective_from DESC LIMIT 1")).scalar())
        check("수수료 자릿수가 충분하다(소수 6자리)", (scale or 0) >= 6, ">= 6", scale)
        # 화면이 말하는 값 = DB가 든 값 (표시 반올림이 값을 감추지 않는다)
        said = (pr or {}).get("card_fee_rate")
        if said is not None:
            check("화면이 말하는 수수료 = DB 실값", round(float(said), 6) == round(stored, 6),
                  stored, said)
        said_pct = (pr or {}).get("card_fee_pct")
        if said_pct is not None:
            check("퍼센트 표시가 실값과 어긋나지 않는다",
                  abs(said_pct - stored * 100) < 0.0005, round(stored * 100, 3), said_pct)

    # 가드 — 실행하지 않는다
    try:
        get("/api/admin/reprice/preview?scope=nope")
        check("알 수 없는 범위는 400", False, 400, 200)
    except urllib.error.HTTPError as e:
        check("알 수 없는 범위는 400", e.code == 400, 400, e.code)
    st, _ = post("/api/admin/reprice/apply", {"scope": "nope", "expect_changed": 1})
    check("반영도 알 수 없는 범위는 400", st == 400, 400, st)
    st, r = post("/api/admin/reprice/apply", {"scope": "live", "expect_changed": -1})
    check("미리보기 확인값이 다르면 409", st == 409, 409, st)
    st, _ = post("/api/admin/reprice/undo", {"log_id": 999999999})
    check("없는 재산정 기록 되돌리기는 404", st == 404, 404, st)

    # 화면 계약
    _p = admin_html("reprice.html")
    if os.path.exists(_p):
        _h = io.open(_p, encoding="utf-8").read()
        check("화면이 ADM-PRC-050이다", 'data-screen-id="ADM-PRC-050"' in _h, True,
              'data-screen-id="ADM-PRC-050"' in _h)
        check("화면이 미리보기를 거친다", "reprice/preview" in _h, True,
              "reprice/preview" in _h)
        check("화면이 확인값을 되돌려 보낸다", "expect_changed" in _h, True,
              "expect_changed" in _h)
        check("화면에 되돌리기가 있다", "reprice/undo" in _h, True, "reprice/undo" in _h)
        # 오름·내림을 합친 단일 합계를 화면이 만들지 않는다
        check("화면이 오름·내림을 따로 그린다",
              "mUpSum" in _h and "mDownSum" in _h, True,
              "mUpSum" in _h and "mDownSum" in _h)

def test_category_margin():
    """[40] 마진 정책이 판매 분류 노드에 걸린다 (2026-08-05)

    예전엔 `category_margin_policies`가 `category VARCHAR` 자유 문자열 키에 **0행**이었고,
    저장 API를 부르는 화면이 하나도 없었다 — 표만 있고 아무 데도 이어지지 않은 죽은
    테이블이었다. `margin-policy.html`은 그걸 읽어 빈 표를 그리고 있었다.

    **왜 part_type이 아니라 노드인가**: 트리는 이미 갈라져서 34노드 중 13개가 `ETC`
    하나를 공유한다(케이블·젠더 704 · 쿨링·튜닝 1,668 · 완제품 PC 318 · 소프트웨어 20).
    part_type에 걸면 완제품 PC와 케이블이 같은 마진을 받는다.

    **저장된 판매가를 그 자리에서 바꾸지 않는다** — 다음 재산정에서 쓰인다. 그래서
    분류를 옮겼는데 값이 말없이 달라지는 사고가 없다. 회귀는 정본을 쓰지 않으므로
    (슬라이스 50 전례) 여기서 마진을 걸지 않는다 — **가드와 읽기만** 본다.
    """
    print(chr(10) + "[40] 마진 정책이 판매 분류 노드에 걸린다")
    import re as _re14
    from api.pricing import resolve_margins as _rm

    # 1) 상속 규칙을 순수 함수로 직접 검사한다 — 트리를 지어내 경계까지 본다.
    #    (DB를 타면 '지금 정책이 없어서' 통과하는 거짓 안심이 된다)
    NODES = [(1, None), (2, 1), (3, 2), (9, None)]      # 1 > 2 > 3, 9는 별개
    r = _rm(NODES, {1: 0.10, 3: 0.05}, 0.12)
    check("자기 노드에 걸린 값이 이긴다", r[3] == (0.05, 3), (0.05, 3), r[3])
    check("없으면 조상을 따른다", r[2] == (0.10, 1), (0.10, 1), r[2])
    check("조상에도 없으면 전역", r[9] == (0.12, None), (0.12, None), r[9])
    # 순환·고아에서 멈추지 않는가 — 여기서 무한 루프면 가격 화면이 통째로 죽는다
    r2 = _rm([(1, 2), (2, 1), (7, 99)], {}, 0.12)
    check("순환이어도 멈추지 않고 전역", r2[1] == (0.12, None), (0.12, None), r2.get(1))
    check("부모가 없는 노드도 전역", r2[7] == (0.12, None), (0.12, None), r2.get(7))

    # 2) 상속을 **한 곳에서만** 계산하는가. 화면이나 다른 모듈이 다시 구현하면 갈라진다.
    _dupes = []
    for _dir, _ext in ((os.path.join(ROOT, "api"), ".py"),
                       (os.path.join(ROOT, "mockups", "admin"), ".html"),
                       (LEGACY_ADMIN, ".html")):
        for _fn in sorted(os.listdir(_dir)):
            if not _fn.endswith(_ext) or _fn == "pricing.py":
                continue
            _s = io.open(os.path.join(_dir, _fn), encoding="utf-8").read()
            # 부모를 거슬러 올라가며 마진을 찾는 코드의 지문
            if _re14.search(r"parent_id", _s) and _re14.search(r"margin", _s) \
               and _re14.search(r"while|for\s*\(", _s) \
               and "resolve_margins" not in _s and "margin_effective" not in _s:
                _dupes.append(_fn)
    check("마진 상속을 pricing.py 밖에서 다시 구현하지 않는다", _dupes == [], [], _dupes)

    # 3) 응답이 세 값을 **구분해서** 준다. 적용값만 주면 운영자는 이 노드에 값이
    #    걸린 줄 알고, 지우려 해도 지울 게 없다(상속이면 조상에 걸려 있다).
    d = get("/api/admin/categories") or {}
    items = d.get("items") or []
    check("카테고리 응답이 비어 있지 않다", len(items) > 0, "> 0", len(items))
    _keys = all(("margin_rate" in x and "margin_effective" in x and "margin_source" in x)
                for x in items)
    check("노드마다 직접값·적용값·출처를 준다", _keys, True, _keys)
    check("전역 기본 마진을 함께 준다", isinstance(d.get("default_margin"), (int, float)),
          "숫자", type(d.get("default_margin")).__name__)
    # 적용값은 전역이거나 어딘가에 걸린 값이다 — 지어낸 수가 섞이면 안 된다
    _own = {x["category_id"]: x["margin_rate"] for x in items if x["margin_rate"] is not None}
    _allowed = set(_own.values()) | {d.get("default_margin")}
    _odd = [x["name"] for x in items if x["margin_effective"] not in _allowed]
    check("적용 마진은 전역이거나 걸린 값이다", _odd == [], [], _odd[:5])
    # 직접 건 값이 없는 노드는 출처가 '이 분류'일 수 없다
    _lie = [x["name"] for x in items
            if x["margin_rate"] is None and x["margin_source"] == "이 분류"]
    check("걸리지 않은 노드가 '이 분류'라 말하지 않는다", _lie == [], [], _lie)

    # 4) 쓰기 가드만 확인한다 — 값을 걸지 않는다(회귀는 정본을 쓰지 않는다).
    _cid = items[0]["category_id"]
    _J = {"Content-Type": "application/json"}

    def _put(path, body):
        return post_raw(path, json.dumps(body).encode(), _J, method="PUT")

    st, _ = _put("/api/admin/categories/%d/margin" % _cid, {"margin_rate": 1.5})
    check("마진 1 이상은 막는다", st == 400, 400, st)
    st, _ = _put("/api/admin/categories/%d/margin" % _cid, {"margin_rate": -0.1})
    check("음수 마진은 막는다", st == 400, 400, st)
    st, _ = _put("/api/admin/categories/999999/margin", {"margin_rate": 0.1})
    check("없는 카테고리는 404", st == 404, 404, st)

    # 5) 재산정이 마진을 **정말 상품별로** 쓰는가.
    #    지금 DB엔 정책이 0행이라 아래 API 검사만 두면 마진이 하나뿐이어서
    #    **무엇을 해도 통과한다**(공허한 검사 — 이 프로젝트에서 세 번 겪었다).
    #    그래서 분류가 다른 가짜 행 두 개를 만들어 계산 함수를 직접 두드린다.
    from api.admin_reprice import _classify as _cls
    _rows2 = [{"product_code": "A", "product_name": "가", "part_type": "GPU",
               "purchase_price": 100000, "sale_price": None, "status": "판매중",
               "stock_qty": 1, "locked_fields": None, "category_id": 4},
              {"product_code": "B", "product_name": "나", "part_type": "GPU",
               "purchase_price": 100000, "sale_price": None, "status": "판매중",
               "stock_qty": 1, "locked_fields": None, "category_id": 5}]
    _c = _cls(_rows2, 0.02585, 0.12, {4: 0.30})       # 4번만 30%, 5번은 전역 12%
    _by = {i["product_code"]: i for i in _c["up"]}
    check("분류가 다르면 산정가도 다르다",
          _by["A"]["proposed"] != _by["B"]["proposed"],
          "다름", (_by["A"]["proposed"], _by["B"]["proposed"]))
    check("분류에 걸린 마진이 그대로 쓰인다", _by["A"]["margin_rate"] == 0.30,
          0.30, _by["A"]["margin_rate"])
    check("걸리지 않은 분류는 전역", _by["B"]["margin_rate"] == 0.12,
          0.12, _by["B"]["margin_rate"])
    check("쓰인 마진 2종을 보고한다", sorted(_c["margins_used"]) == [0.12, 0.30],
          [0.12, 0.30], sorted(_c["margins_used"]))

    # 그리고 API 쪽 정합 — 합계가 대상 수와 맞아야 한다.
    p = get("/api/admin/reprice/preview?scope=live") or {}
    _used = p.get("margins_used") or []
    check("재산정이 쓰인 마진을 보고한다", len(_used) > 0, "> 0", len(_used))
    _sum = sum(u["count"] for u in _used)
    check("마진별 건수 합 = 대상 건수", _sum == p.get("target"), p.get("target"), _sum)
    check("마진이 하나면 varies=False",
          p.get("margin_varies") == (len(_used) > 1), len(_used) > 1, p.get("margin_varies"))

    # 6) 화면이 서버 값을 그대로 쓰는가(상속을 다시 계산하지 않는다)
    _h = io.open(admin_html("categories.html"),
                 encoding="utf-8").read()
    check("화면이 적용 마진을 서버에서 받는다", "margin_effective" in _h, True,
          "margin_effective" in _h)
    check("화면이 출처를 함께 보여준다", "margin_source" in _h, True, "margin_source" in _h)
    check("화면에 마진 저장 경로가 있다", "/margin" in _h, True, "/margin" in _h)


def test_template_usage():
    """[37] Phoenix 템플릿을 실제로 쓰는가 (슬라이스 F)

    2026-08-05 사용자 지적: "라이선스를 구매한 부트스트랩 UI를 전혀 활용하지 못하는 것 같다."
    실사해 보니 맞았다 — **템플릿 컴포넌트를 실제로 초기화하는 화면이 0개**였다.
    `data-list`는 35화면에 있었지만 전부 셸 상단 검색창이었고, `data-bulk-select`·echarts·
    wizard·accordion은 `_demo-products.html`(템플릿 잔재라 화면이 아닌 파일)에만 있었다.

    가장 아팠던 것: `phoenix.js`에 `treeviewInit`이 있고 `theme.min.css`에 treeview 스타일이
    전부 있는데, 카테고리 트리를 `<table>`에 `<span style="width:18px">`로 들여쓰기를 흉내 내
    만들고 있었다. **쓸 수 있는 트리가 이미 저장소 안에 있었다.**

    여기서 지키는 것: 손으로 다시 만들지 않는다. 자세한 실사는
    `docs/design/phoenix-audit-2026-08-05.md`.
    """
    print(chr(10) + "[37] Phoenix 템플릿을 실제로 쓰는가 (슬라이스 F)")
    import glob as _g7
    import re as _re11

    admin = os.path.join(ROOT, "mockups", "admin")
    def read(name):
        p = admin_html(name)
        return io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    cat = read("categories.html")
    check("카테고리 화면이 treeview 마크업을 쓴다",
          'class="mb-0 treeview"' in cat or 'class="treeview"' in cat, True,
          "treeview" in cat)
    check("트리가 손으로 만든 들여쓰기가 아니다",
          "treeview-list-item" in cat and 'style="display:inline-block;width:' not in cat,
          True, "treeview-list-item" in cat)
    check("트리 노드에 개수 배지가 있다", "treeview-badge" in cat, True, "treeview-badge" in cat)
    # 상위 노드는 직접 상품이 0건인 게 보통이다 — 배지가 직접 수면 13,308건짜리가 "0"으로 보인다
    check("배지가 자손 합계를 쓴다", "subtree_count" in cat, True, "subtree_count" in cat)
    check("상위 노드를 누르면 하위까지 본다(scope=subtree)", "subtree" in cat, True,
          "subtree" in cat)
    check("표에 data-list(검색·정렬)를 건다", 'id="prodList" data-list=' in cat, True,
          'id="prodList" data-list=' in cat)
    # class="sort" 와 class="sort text-end" 를 모두 센다 — 앞의 것만 세면 4개로 보인다
    _nsort = len(_re11.findall(r'class="sort[ "]', cat))
    check("정렬 헤더가 있다", _nsort >= 5, ">= 5", _nsort)
    check("일괄 선택은 Phoenix bulk-select를 쓴다",
          "data-bulk-select=" in cat and "data-bulk-select-row=" in cat, True,
          "data-bulk-select=" in cat)
    # 컴포넌트는 docReady 1회만 붙는다 — 동적 렌더면 우리가 다시 붙여야 한다.
    # 표는 공용 헬퍼(shared/ui-list.js)가, 선택은 phoenix.BulkSelect 가 맡는다.
    check("동적 렌더 뒤 컴포넌트를 다시 붙인다",
          "phoenix.BulkSelect" in cat and "popcornList.wire" in cat,
          True, "popcornList.wire" in cat)

    # 참조하는 vendor는 실제로 있어야 한다(없으면 조용히 안 붙는다)
    vend = os.path.join(admin, "vendors")
    have = set(os.listdir(vend)) if os.path.isdir(vend) else set()
    NEED = {"data-choices": "choices", "data-echarts": "echarts", "data-countup": "countup",
            "data-nouislider": "nouislider", "data-rater": "rater-js",
            "data-sortable": "sortablejs", "data-calendar": "fullcalendar"}
    missing = []
    for _p in admin_htmls():
        if os.path.basename(_p).startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        for hook, v in NEED.items():
            if hook in _s and v not in have:
                missing.append(f"{os.path.basename(_p)}:{hook}->{v}")
    check("vendor 없는 훅을 선언하지 않는다", missing == [], [], missing)

    # 정렬 표는 **공용 헬퍼**를 써야 한다.
    #
    # 슬라이스 G에서 열두 화면이 유령 List 인스턴스를 각자 막게 했더니 해법이 두 갈래
    # (cloneNode 파 6 · removeAttribute 파 8)로 갈라졌고 정렬 비교 함수도 다섯 벌이 됐다.
    # 슬라이스 A(부품 어휘)·H(choices)에서 겪은 그 병이다. 이제 `shared/ui-list.js` 하나가
    # 유령 차단 · 정렬 복원 · 금액 수치 비교 · vendor 지연을 전부 맡는다.
    #
    # 헬퍼가 푸는 문제(전부 브라우저 실측):
    #   · listInit(docReady)이 만든 유령이 th 를 물어 클릭 한 번에 두 번 뒤집힌다
    #   · data-list 를 떼면 정렬 커서 CSS 가 사라진다(.table-list 짝이 필요)
    #   · naturalSort("239,000원","1,299,000원") = +2 — 콤마 때문에 거꾸로다
    #   · reIndex 는 정렬을 다시 걸지 않아 화살표만 남아 거짓말한다
    helper = os.path.join(ROOT, "mockups", "shared", "ui-list.js")
    check("표 공용 헬퍼가 있다", os.path.exists(helper), True, os.path.exists(helper))
    if os.path.exists(helper):
        h = io.open(helper, encoding="utf-8").read()
        for need, why in (("popcornList", "전역 이름"),
                          ("cloneNode", "유령 핸들러 떼기"),
                          ("table-list", "정렬 커서 CSS 유지"),
                          ("activeSort", "reIndex 뒤 정렬 복원"),
                          ("toNum", "콤마 금액 수치 비교")):
            check("헬퍼가 %s 를 담당한다" % why, need in h, need, need in h)

    direct, own_sort, no_helper = [], [], []
    for _p in admin_htmls():
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        if not _re11.search(r'class="sort[ "]', _s):
            continue                                   # 정렬 표가 없는 화면은 대상 아님
        if "popcornList.wire" not in _s:
            no_helper.append(_n)
            continue
        if "new window.List" in _s or "new List(" in _s:
            direct.append(_n)                          # 헬퍼를 우회하면 다시 갈라진다
        # 비교 함수는 **헬퍼에 넘기는 경우만** 허용한다. 헬퍼 기본값으로 재현할 수 없는
        # 도메인 규칙이 있다(예: 가격 이력의 '356,000 → 352,000' 은 **차액**으로 정렬해야
        # 한다 — 앞의 수도 뒤의 수도 아니다). 그런 것을 금지하면 화면이 거짓 정렬을 낸다.
        # 막아야 할 것은 **헬퍼를 우회해 자기 배선을 다시 만드는 것**이다.
        if (_re11.search(r'function\s+\w*[Ss]ort\w*\s*\(\s*a\s*,\s*b\s*,', _s)
                and 'sortFunction' not in _s):
            own_sort.append(_n)                        # 헬퍼에 넘기지 않는 비교 함수
        if "shared/ui-list.js" not in _s:
            no_helper.append(_n + ":스크립트미로드")
    check("정렬 표가 공용 헬퍼를 쓴다", no_helper == [], [], no_helper)
    check("화면이 List를 직접 만들지 않는다", direct == [], [], direct)
    check("비교 함수를 헬퍼를 우회해 쓰지 않는다", own_sort == [], [], own_sort)
    # 특례가 몇 개인지 눈에 보이게 둔다 — 늘면 헬퍼 기본값을 고칠 때가 된 것이다.
    special = [os.path.basename(_p) for _p in admin_htmls()
               if "sortFunction" in io.open(_p, encoding="utf-8").read()]
    drift("custom_sortfn_screens", len(special))

    # 손으로 만든 전체선택이 남아 있지 않은가 — 있으면 컴포넌트를 또 베낀 것이다
    handrolled = []
    for _p in admin_htmls():
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        if 'id="chkAll"' in _s and "data-bulk-select" not in _s:
            handrolled.append(_n)
    check("전체선택을 손으로 만든 화면이 없다", handrolled == [], [], handrolled)

    # 몇 개 화면이 실제로 템플릿 표를 쓰는가 — 늘어나는 것이 정상이다(줄면 되돌린 것이다)
    using = [os.path.basename(_p) for _p in admin_htmls()
             if not os.path.basename(_p).startswith("_")
             and "popcornList.wire" in io.open(_p, encoding="utf-8").read()]
    check("템플릿 표를 쓰는 화면 수", len(using) >= 12, ">= 12", len(using))
    drift("template_list_screens", len(using))

def test_charts_and_choices():
    """[38] 차트·검색 셀렉트 — 산 것을 더 쓴다 (슬라이스 H)

    2026-08-05 실사에서 대시보드에 차트가 **하나도 없고**, 제조사 셀렉트에 옵션이
    **620개**나 되는데 검색이 없다는 것이 드러났다. vendor 두 개(`echarts`·`choices`)를
    복사해 붙였다.

    ■ 차트도 숫자를 지어내지 않는다
    `phoenix.js` 의 `basicEchartsInit` 은 `data-echarts` 를 훑어 **2022년 날짜가 박힌
    데모 기본값**을 씌운다. 그래서 쓰지 않고 `window.echarts.init` 을 직접 부른다.
    원천이 없으면 차트를 그리지 않고 그렇게 말한다(0건 항목은 막대를 만들지 않는다).

    ■ choices 는 공용 헬퍼 하나로 붙인다
    슬라이스 G에서 같은 문제에 열두 화면이 제각각 대응해 해법이 두 갈래로 갈라졌다.
    이번에는 `mockups/shared/ui-choices.js` 한 곳에 둔다. 회귀가 그 상태를 지킨다.
    """
    print(chr(10) + "[38] 차트·검색 셀렉트 — 산 것을 더 쓴다 (슬라이스 H)")
    import glob as _g8
    import re as _re12

    admin = os.path.join(ROOT, "mockups", "admin")
    vend = os.path.join(admin, "vendors")
    have = set(os.listdir(vend)) if os.path.isdir(vend) else set()
    for v in ("echarts", "choices"):
        check("vendor %s 가 실제로 있다" % v, v in have, v, sorted(have))

    idx = io.open(admin_html("index.html"), encoding="utf-8").read()
    check("대시보드가 echarts vendor를 싣는다", "vendors/echarts/echarts.min.js" in idx, True,
          "vendors/echarts" in idx)
    for cid in ("chPool", "chOrders", "chPending"):
        check("대시보드에 %s 자리가 있다" % cid, ('id="%s"' % cid) in idx, True,
              ('id="%s"' % cid) in idx)
    # 데모 기본값을 씌우는 자동 초기화는 쓰지 않는다(2022년 날짜가 박혀 있다)
    # 주석에서 언급하는 것과 **속성으로 선언하는 것**은 다르다 — 속성만 본다.
    _attr = _re12.search(r'data-echarts\s*=', idx)
    check("data-echarts 자동 초기화를 쓰지 않는다", _attr is None, "선언 없음",
          _attr.group(0) if _attr else "없음")
    check("차트를 서버 응답으로 그린다", "window.paintCharts" in idx and "d.flow" in idx,
          True, "window.paintCharts" in idx)
    # 차트 자리에 숫자를 박아두지 않는다 — 서버가 주기 전에는 '—'
    for cid in ("chPoolNote", "chOrdNote"):
        m = _re12.search(r'id="%s"[^>]*>([^<]*)<' % cid, idx)
        check("%s 가 자리표시자로 시작한다" % cid,
              bool(m) and not _re12.search(r"[0-9]", m.group(1)),
              "숫자 없음", m.group(1) if m else "(없음)")

    # ── 차트 색은 토큰에서 온다 (전수 감사 2026-08-06) ──────────────────
    # 주문 상태 파이가 itemStyle 을 주지 않아 **echarts 기본 팔레트**로 떨어져 있었다:
    #   #5470c6  #91cc75  #fac858  #ee6666  #73c0de  #3ba272
    #             ↑초록                                ↑초록
    # 초록 없음(U-01)과 "임의 HEX 금지"를 동시에 어겼는데 아무도 막지 못했다 —
    # 마크업이 아니라 런타임 옵션이라서다. 정적으로 잡히는 것만 여기서 잡는다.
    chart_files = [os.path.join(admin, n) for n in
                   ("index.html", "candidate-pool.html", "reprice.html",
                    "price-history.html")]
    chart_files.append(os.path.join(ROOT, "mockups", "shared", "ui-chart.js"))

    # ① 색 토큰 이름이 실제로 해석되는 것인가.
    #    phoenix.utils.getColor 로 브라우저에서 실측한 목록이다. 여기 없는 이름을 쓰면
    #    조용히 폴백 HEX 로 떨어진다 — `body-tertiary` 12곳이 그랬다(감사에서 교체).
    #    새 이름을 쓰려면 **브라우저에서 확인하고** 이 목록에 넣는다.
    KNOWN_TOKENS = {
        "primary", "info", "warning", "danger", "secondary",
        "primary-light", "info-light", "warning-light", "danger-light",
        "primary-dark", "info-dark",
        "secondary-bg", "tertiary-bg", "border-color", "body-highlight-bg",
        "light-text-emphasis", "body-color", "tertiary-color", "quaternary-color",
        "gray-500", "gray-600", "gray-700",
    }
    bad_token = []
    for _f in chart_files:
        if not os.path.exists(_f):
            continue
        _s = io.open(_f, encoding="utf-8").read()
        for _m in _re12.finditer(r'\bC\(\s*"([a-z0-9-]+)"', _s):
            if _m.group(1) not in KNOWN_TOKENS:
                bad_token.append(os.path.basename(_f) + ":" + _m.group(1))
    check("차트가 해석되는 색 토큰만 쓴다", bad_token == [], [], sorted(set(bad_token)))

    # ② 초록은 쓰지 않는다(U-01 미정). success 토큰은 존재하지만 #25b003 초록이다.
    green = []
    for _f in chart_files:
        if not os.path.exists(_f):
            continue
        _s = io.open(_f, encoding="utf-8").read()
        if _re12.search(r'\bC\(\s*"success"', _s):
            green.append(os.path.basename(_f))
    check("차트가 success(초록) 토큰을 쓰지 않는다", green == [], [], green)

    # ③ 차트 series 는 색을 스스로 정한다 — 안 정하면 기본 팔레트로 떨어진다.
    #    series 리터럴 안에 itemStyle 이나 lineStyle 이 있어야 한다.
    no_color = []
    for _f in chart_files:
        if not os.path.exists(_f) or _f.endswith("ui-chart.js"):
            continue
        _s = io.open(_f, encoding="utf-8").read()
        for _m in _re12.finditer(r'type\s*:\s*"(pie|bar|line)"', _s):
            _seg = _s[_m.start():_m.start() + 600]
            if "itemStyle" not in _seg and "lineStyle" not in _seg:
                no_color.append("%s:%s" % (os.path.basename(_f), _m.group(1)))
    check("차트 series 가 색을 스스로 정한다(기본 팔레트 금지)",
          no_color == [], [], sorted(set(no_color)))

    # choices — 공용 헬퍼 하나만 있고, 화면은 그것을 쓴다
    helper = os.path.join(ROOT, "mockups", "shared", "ui-choices.js")
    check("공용 헬퍼가 있다", os.path.exists(helper), True, os.path.exists(helper))
    if os.path.exists(helper):
        h = io.open(helper, encoding="utf-8").read()
        check("헬퍼가 popcornChoices를 내놓는다", "popcornChoices" in h, True,
              "popcornChoices" in h)
        # 감싼 것을 풀지 않고 옵션을 갈면 UI와 값이 어긋난다 — refill 이 그 순서를 지킨다
        check("헬퍼가 풀기→채우기→감싸기를 묶어 준다",
              "function refill" in h and "unwrap" in h, True, "refill" in h)

    # 화면이 Choices 를 직접 new 하지 않는다(헬퍼를 우회하면 다시 갈라진다)
    direct = []
    for _p in admin_htmls():
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        if "new window.Choices" in _s or "new Choices(" in _s:
            direct.append(_n)
    check("화면이 Choices를 직접 만들지 않는다(헬퍼를 쓴다)", direct == [], [], direct)

    # 검색을 붙인 화면은 vendor·헬퍼를 함께 실어야 한다(하나만 빠지면 조용히 평범한 셀렉트가 된다)
    broken = []
    for _p in admin_htmls():
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        if "popcornChoices" not in _s:
            continue
        miss = [x for x in ("vendors/choices/choices.min.js",
                            "vendors/choices/choices.min.css",
                            "shared/ui-choices.js") if x not in _s]
        if miss:
            broken.append(_n + ":" + ",".join(miss))
    check("검색 셀렉트 화면이 vendor·CSS·헬퍼를 다 싣는다", broken == [], [], broken)

    using = [os.path.basename(_p) for _p in admin_htmls()
             if "popcornChoices" in io.open(_p, encoding="utf-8").read()]
    check("검색 셀렉트를 쓰는 화면이 있다", len(using) >= 3, ">= 3", len(using))
    drift("choices_screens", len(using))

def test_no_fabricated_data():
    """[39] 서버가 없으면 지어내지 않는다 (더미 폴백 제거 1·2차)

    2026-08-05 사용자 지시로 화면의 더미 폴백을 걷어냈다. 그전에는 서버에 못 닿으면
    화면이 **없는 상품·주문·사람·금액을 사실처럼** 보여줬다 — 배지가 '더미 데이터'라고
    밝혀도 큼직한 "24,912개"는 사람이 사실로 읽는다.

    이 프로젝트는 이미 같은 판단을 내렸다: 좌측 메뉴 배지가 마크업 더미로
    '상품 검수 9'라고 말했는데 실제는 5,162였고, 그래서 `admin-panel.js` 의
    `clearDummyBadges()` 가 배지를 지운다. 본문에도 같은 논리를 적용한 것이다.

    배지 어휘(HANDOFF 규약 2026-08-05 개정):
        `실데이터 · Cloud SQL` / `연결 안 됨`(원천은 있는데 못 불러옴) /
        `원천 준비 중`(저장 경로 자체가 없음).   ~~`더미 데이터`~~ 는 폐기.
    """
    print(chr(10) + "[39] 서버가 없으면 지어내지 않는다 (더미 폴백 제거)")
    import glob as _g9
    import re as _re13

    admin = os.path.join(ROOT, "mockups", "admin")

    def screens():
        for _p in admin_htmls():
            _n = os.path.basename(_p)
            if _n.startswith("_") or _n == "login.html":
                continue
            yield _n, io.open(_p, encoding="utf-8").read()

    # ① 폐기한 배지 문구가 남아 있지 않은가.
    #    **주석은 봐준다** — 지운 내역을 설명하는 주석까지 잡으면 기록을 못 남긴다.
    #    검사 대상은 화면이 사용자에게 *말하는 것*이다.
    def strip_comments(x):
        x = _re13.sub(r"<!--[\s\S]*?-->", "", x)
        x = _re13.sub(r"/\*[\s\S]*?\*/", "", x)
        x = _re13.sub(r"(?m)^\s*//.*$", "", x)
        return _re13.sub(r"(?m)\s+//[^\"']*$", "", x)

    said_dummy = [n for n, s_ in screens() if "더미 데이터" in strip_comments(s_)]
    check("'더미 데이터' 배지를 쓰는 화면이 없다", said_dummy == [], [], said_dummy)

    # ② 지어낸 알림이 남아 있지 않은가 — 알림 API 자체가 없다
    noti = [n for n, s_ in screens() if "notification-card" in s_]
    check("셸에 지어낸 알림이 없다", noti == [], [], noti)

    # ③ 마크업 <tbody> 에 사실로 읽힐 행이 박혀 있지 않은가.
    #    자리표시자('—', '불러오는 중…', '서버에 …')만 허용한다.
    OK = ("—", "불러오는 중", "서버에", "연결", "표시됩니다", "없습니다", "준비 중")
    hard = []
    for n, s_ in screens():
        body = _re13.sub(r"<script[\s\S]*?</script>", "", s_)
        # 범례표(`data-legend`)는 데이터가 아니라 화면이 스스로 하는 설명이다 — 건너뛴다.
        body = _re13.sub(r"<table[^>]*\bdata-legend\b[\s\S]*?</table>", "", body)
        for tb in _re13.findall(r"<tbody[^>]*>([\s\S]*?)</tbody>", body):
            for tr in _re13.findall(r"<tr[\s\S]*?</tr>", tb):
                txt = _re13.sub(r"<[^>]+>", " ", tr)
                txt = _re13.sub(r"\s+", " ", txt).strip()
                if not txt:
                    continue
                if any(k in txt for k in OK):
                    continue
                hard.append(n + ": " + txt[:40])
    check("마크업 표에 지어낸 행이 없다", hard == [], [], hard[:6])

    # ④ 화면이 스스로 세는 큰 수를 마크업에 박아두지 않는다.
    #    콤마가 들어간 4자리 이상 숫자는 서버가 주는 값이지 화면이 아는 값이 아니다.
    #    (버전·연도·전화번호 오탐을 피하려 콤마 형식만 본다)
    #
    # ⚠ **이 검사는 2026-08-17까지 한 건도 못 잡았다** — 무엇을 세는지와 무엇을 증명하는지가
    #    달랐던 `[26]`·`[42]`와 같은 계열이다(§회귀 세트). 정규식이 `>\s*1,705,000\s*<`,
    #    즉 **숫자가 태그 사이의 «전부»일 때만** 봤다. 실제 마크업은 거의 언제나
    #    `>1,705,000원<`·`>2,480대<`처럼 단위가 붙어 있어 **「원·대·개·종」 한 글자만 붙으면
    #    그대로 통과**했다. 증명해야 하는 것은 "숫자만 든 텍스트 노드가 없다"가 아니라
    #    **"화면이 말하는 글에 서버만 알 수 있는 수가 없다"**이므로, 태그를 걷어낸
    #    **본문 텍스트 전체**에서 찾는다(속성값은 사람에게 안 보이므로 대상이 아니다 —
    #    태그를 지우면 함께 빠진다).
    def baked_numbers(src):
        body = _re13.sub(r"<script[\s\S]*?</script>", " ", src)
        body = _re13.sub(r"<style[\s\S]*?</style>", " ", body)
        body = _re13.sub(r"<!--[\s\S]*?-->", " ", body)         # 주석 속 설명은 봐준다
        body = _re13.sub(r"<[^>]+>", " ", body)                 # 사람이 읽는 글만 남긴다
        return _re13.findall(r"[0-9]{1,3}(?:,[0-9]{3})+", body)

    # ── 유예를 다루는 법 (2026-08-17 사장님 결정 「고객 화면만 먼저 고친다」) ────────
    #
    # 넓힌 검사가 «지금 고치지 않기로 한 것»까지 잡는다. 그렇다고 검사를 **좁히지 않는다**
    # — 좁히는 순간 이 검사는 다시 거짓 안심이 된다(바로 위 ⚠ 가 그 이야기다).
    # 대신 유예분을 전부 찾아낸 채로 아래 **세 장치**에 묶어 둔다. 근거 없는 화이트리스트가
    # 아니라, 스스로 낡으면 실패하는 목록이다.
    #
    #   ① 값까지 고정한다   지금 박혀 있는 수를 한 자리까지 적는다. 유예 파일에 **새 수가
    #                       늘면 실패**한다 — 예외가 조용히 자라지 못한다.
    #   ② 낡으면 실패한다   고정한 수가 사라졌는데 목록에 남아 있으면 실패한다
    #                       ("고쳤으면 예외도 지워라"). 예외가 원인보다 오래 살지 못한다.
    #   ③ 기한이 있다       기한을 넘기면 유예가 통째로 **실패로 바뀐다.** 이 저장소는
    #                       「나중에」가 낡아 사고가 된 전례가 많다(CLAUDE.md 곳곳) —
    #                       날짜가 지나면 사람이 다시 판단하게 만든다.
    #
    # 기한을 미루려면 «왜 아직 유예인가»를 여기 적고 날짜를 옮긴다(그 자체가 기록이다).
    import datetime as _dt13
    BAKED_EXPIRES = "2026-09-30"
    _baked_expired = _dt13.date.today().isoformat() > BAKED_EXPIRES

    def baked_split(found_by_file, defer, label):
        """유예 목록을 적용하되 «숨기지 않는다» — 막을 것 · 자란 것 · 낡은 것으로 가른다."""
        blocking, grew, stale = [], [], []
        for fn, vals in found_by_file.items():
            if fn not in defer or _baked_expired:
                blocking += [fn + ":" + v for v in vals]
                continue
            pinned = set(defer[fn][0])
            grew += [fn + ":" + v for v in vals if v not in pinned]     # ①
        for fn, (pinned, _why) in defer.items():                        # ②
            gone = [v for v in pinned if v not in found_by_file.get(fn, [])]
            if gone:
                stale.append(fn + ": " + ",".join(gone))
        check(label + " 유예 목록이 자라지 않는다", grew == [], [], sorted(set(grew))[:8])
        check(label + " 유예 목록에 낡은 항목이 없다 (고쳤으면 예외도 지운다)",
              stale == [], [], stale)
        # 유예분은 «조용히» 넘어가지 않는다 — 돌릴 때마다 눈에 보이게 적는다
        if defer and not _baked_expired:
            for fn, (pinned, why) in sorted(defer.items()):
                print("         [유예 ~%s] %s: %s — %s"
                      % (BAKED_EXPIRES, fn, ",".join(pinned), why))
        return blocking

    def baked_by_file(pairs):
        out = {}
        for fn, src in pairs:
            found = sorted(set(baked_numbers(src)))
            if found:
                out[fn] = found
        return out

    check("유예 기한이 남아 있다 (넘기면 유예가 전부 실패가 된다)",
          not _baked_expired, "오늘 <= " + BAKED_EXPIRES, _dt13.date.today().isoformat())

    # 구 `/admin/*.html` 은 **백업용 동결**이다(P-09 · CLAUDE.md §관리자 화면 규약):
    # 수정 금지 · 링크 금지 · 사용자 안내 금지. 고객이 보는 화면이 아니고, 필요한 기능은
    # admin2 에 «새로 짓는» 것이지 여기를 고치는 것이 아니다. 그래서 유예한다 —
    # 다만 동결이 곧 면제는 아니므로, 파일이 지워지거나 admin2 로 옮겨지면 ②가 알린다.
    BAKED_ADMIN_DEFER = {
        "candidate-pool.html": (
            ["2,457"],
            "구 /admin/*.html 백업용 동결(P-09) — 고치는 대신 admin2 에 새로 짓는다. "
            "이 파일이 사라지거나 admin2 로 옮겨지면 이 항목도 지운다."),
    }
    baked = baked_split(baked_by_file(screens()), BAKED_ADMIN_DEFER, "관리자 화면")
    check("마크업에 콤마 숫자를 박아두지 않는다", baked == [], [], sorted(set(baked))[:8])

    # **고객 화면도 같은 규칙이다.** `[39]` 가 오래 `mockups/admin` 만 봤고, 그 사이
    # 고객 화면에 20곳이 남아 있었다(감사 2026-08-06). 지금은 대부분 런타임에 덮이지만
    # **서버가 실패하면 그 수들이 사실처럼 남는다** — 첫 화면일수록 위험하다.
    # `vslot-demo` 는 규약 데모라 화면이 아니다(제외).
    #
    # **MY 화면 둘은 유예다** (2026-08-17 사장님 결정 「고객 화면만 먼저 고친다」).
    # 범위 축소로 «제거될» 화면이라 지금 고치는 것은 지워질 코드를 다듬는 일이다
    # (HANDOFF §2 — 회원 원장은 쇼핑몰이 갖는다). 유예 장치 셋은 위 `baked_split` 에 있다.
    BAKED_CX_DEFER = {
        # 파일: (지금 박혀 있는 수, 왜 지금 고치지 않는가 · 무엇이 해소인가)
        # my-page.html의 "812,000" 항목은 2026-08-20 주문·후기를 /api/my/* 실조회로
        # 바꾸며 마크업에서 사라졌다 — 유예 대상이 없어져 항목을 지운다(위 baked_split
        # ②가 "낡은 항목"으로 잡던 바로 그 사례).
        "my-payments.html": (
            ["1,735,000", "3,831,000"],
            "범위 축소로 제거될 화면 — 회원 원장은 쇼핑몰이 갖는다(HANDOFF §2). "
            "화면이 지워지면 이 항목도 함께 지운다."),
    }
    cx_pairs = []
    for _p3 in sorted(_g9.glob(os.path.join(ROOT, "mockups", "mvp1", "*.html"))):
        _n3 = os.path.basename(_p3)
        if _n3 == "vslot-demo.html":
            continue
        cx_pairs.append((_n3, io.open(_p3, encoding="utf-8").read()))

    baked_cx = baked_split(baked_by_file(cx_pairs), BAKED_CX_DEFER, "고객 화면")
    check("고객 화면 마크업에도 콤마 숫자를 박아두지 않는다",
          baked_cx == [], [], sorted(set(baked_cx))[:8])
    drift("baked_numbers_deferred",
          sum(len(v[0]) for v in BAKED_CX_DEFER.values())
          + sum(len(v[0]) for v in BAKED_ADMIN_DEFER.values()))

    # ⑤ 서버가 준 값만 쓴다는 계약이 살아 있는가 — 실패 시 이유를 말하는 화면 수
    honest = [n for n, s_ in screens()
              if ("연결 안 됨" in s_ or "원천 준비 중" in s_
                  or "서버에 연결" in s_)]
    check("실패를 사실대로 말하는 화면이 있다", len(honest) >= 20, ">= 20", len(honest))
    drift("honest_fallback_screens", len(honest))

def test_screen_assets():
    print("\n[30] 화면 자산 — 참조한 CSS·JS가 실제로 있는가 (슬라이스 100)")
    # 사용자 지적("이 화면은 디자인이 반영이 안된건가?")으로 찾았다.
    # my-profile · suppliers · usage-floors 세 화면이 `assets/css/theme.css`를 참조했는데
    # 실제 파일은 `theme.min.css`다 — **404라 스타일이 하나도 안 먹었다.**
    # 브라우저는 404 스타일시트를 규칙 0개인 빈 시트로 만들어 조용히 넘어간다.
    # 내가 usage-floors(슬라이스 75)를 템플릿으로 삼으면서 그 버그를 물려받았다.
    import glob as _g7
    import re as _re7

    # **예전엔 RTL 시트를 예외로 뒀다** — "dir=rtl일 때만 쓰는 것"이라 여겼기 때문이다.
    # 2026-08-05 브라우저에서 열어 보니 **틀렸다**: 평범한 <link>라 브라우저가 항상
    # 받아오고 항상 404였다(36화면 × 2). Phoenix는 LTR/RTL 두 벌을 다 싣고 쓰지 않는
    # 쪽을 *불러온 뒤* disable 하는 구조인데, 우리는 RTL 시트를 가져오지 않았다.
    # 그 소음이 **진짜 404를 가린다** — 이 검사가 태어난 이유가 바로 그것이었다.
    # 지금은 링크·전환 스크립트·설정 토글을 전부 걷어냈으므로 예외를 없앤다.
    IGNORE = ()
    missing = []
    for _p in (sorted(_g7.glob(os.path.join(ROOT, "mockups", "admin", "*.html")))
               + sorted(_g7.glob(os.path.join(ROOT, "mockups", "mvp1", "*.html")))):
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        base = os.path.dirname(_p)
        _s = io.open(_p, encoding="utf-8").read()
        for m in _re7.finditer(r'(?:href|src)="([^"?:#]+\.(?:css|js))"', _s):
            rel = m.group(1)
            if rel.startswith(("http", "//")) or os.path.basename(rel) in IGNORE:
                continue
            if not os.path.exists(os.path.normpath(os.path.join(base, rel))):
                missing.append(f"{_n} -> {rel}")
    check("화면이 참조하는 CSS·JS가 실제로 있다", not missing, "전부 존재", missing[:5])

    # ── 브라우저에서 실제로 열어 잡은 것들 (2026-08-05) ────────────────
    _screens = [(_p, io.open(_p, encoding="utf-8").read())
                for _p in admin_htmls()
                if not os.path.basename(_p).startswith("_")]

    # ① RTL 잔재가 돌아오지 않는가. 링크만 지우면 인라인 스크립트가 null 에
    #    setAttribute 를 걸어 **TypeError** 가 난다(실제로 그렇게 됐다) — 셋을 함께 본다.
    _rtl = [os.path.basename(p) for p, s in _screens
            if "rtl.min.css" in s or "phoenixIsRTL" in s or "style-rtl" in s]
    check("RTL 잔재가 없다(링크·전환 스크립트·설정 토글)", _rtl == [], [], _rtl[:5])

    # ② 아이콘 하나 때문에 외부 폰트 CDN을 받지 않는다.
    #    글리프 7종을 쓰려고 37화면이 unicons 를 통째로 받고 있었다 — 망이 막히면 사라진다.
    _uni = [os.path.basename(p) for p, s in _screens
            if "unicons.iconscout.com" in s or "uil-" in s]
    check("unicons(외부 아이콘 CDN)를 쓰지 않는다", _uni == [], [], _uni[:5])

    # ③ **feather 를 싣지 않는 화면**은 `_map.json` 에 있는 이름만 쓸 수 있다.
    #    su-icons 는 매핑이 없으면 그냥 지나치므로 아이콘이 **조용히 사라진다**.
    _mp = json.load(io.open(os.path.join(ROOT, "mockups", "shared", "icons", "su",
                                         "_map.json"), encoding="utf-8"))
    _keys = set(_mp) if isinstance(_mp, dict) else set(_mp)
    _ghost_icon = []
    for p, s in _screens:
        if "feather.min.js" in s:
            continue
        for nm in sorted(set(_re7.findall(r'data-feather="([a-z-]+)"', s))):
            if ("ft-" + nm) not in _keys:
                _ghost_icon.append(os.path.basename(p) + ":" + nm)
    check("feather 없는 화면은 매핑된 아이콘만 쓴다", _ghost_icon == [], [], _ghost_icon[:5])

    # **Material Symbols 리거처는 매핑이 없으면 이름이 글자로 남는다.**
    # su-icons 의 MS 맵이 유일한 원천이다(`_map.json` 은 파일 목록이라 이름을 못 준다).
    # 2026-08-06 감사에서 8종이 화면에 글자로 떠 있었다 — 버튼에 "play_circle 작동 방식 보기".
    _su = io.open(os.path.join(ROOT, "mockups", "shared", "su-icons.js"),
                  encoding="utf-8").read()
    _ms_raw = _re7.search(r"var MS=(\{.*?\});", _su, _re7.DOTALL)
    _ms_keys = set(json.loads(_ms_raw.group(1))) if _ms_raw else set()
    check("su-icons 의 MS 맵을 읽을 수 있다", len(_ms_keys) > 0, "> 0", len(_ms_keys))

    _all_screens = list(_screens)
    for _p2 in sorted(_g7.glob(os.path.join(ROOT, "mockups", "mvp1", "*.html"))):
        if os.path.basename(_p2) != "vslot-demo.html":
            _all_screens.append((_p2, io.open(_p2, encoding="utf-8").read()))

    _raw_lig = []
    for _p2, _s2 in _all_screens:
        # **스와퍼와 같은 조건으로 찾는다.** 예전엔 `class="msym"` 만 봤는데,
        # 인라인 style 로 Material Symbols 를 지정한 span 이 6종 더 있었고 그것들이
        # 화면에 글자로 떠 있었다(s0 의 'devices' 등). 검사가 좁으면 결함을 가린다.
        for _m2 in _re7.finditer(
                r'<(?:span|i)\b([^>]*(?:msym|material-symbols|Material Symbols)[^>]*)>'
                r'([a-z0-9_]+)</(?:span|i)>', _s2):
            if _m2.group(2) not in _ms_keys:
                _raw_lig.append(os.path.basename(_p2) + ":" + _m2.group(2))
    check("아이콘 이름이 글자로 남지 않는다(msym 매핑)",
          _raw_lig == [], [], sorted(set(_raw_lig))[:6])

    # ④ 유령 List 를 막는 순서. `ui-list.js` 의 sweep 은 docReady 에 돌아
    #    `phoenix.js` 의 listInit 보다 **먼저** [data-list] 를 걷어내야 한다.
    #    뒤에 오면 list.js 가 0건 표에서 예외를 던지고(36화면에서 실제로 터졌다),
    #    이 프로젝트는 uncaught 예외가 뒤따르는 초기화를 죽이는 사고를 이미 겪었다.
    _ui = io.open(os.path.join(ROOT, "mockups", "shared", "ui-list.js"),
                  encoding="utf-8").read()
    check("ui-list.js 가 로드 시 유령을 걷어낸다",
          "function sweep" in _ui and "DOMContentLoaded" in _ui, True,
          "function sweep" in _ui and "DOMContentLoaded" in _ui)
    # **셸 검색창은 대상이 아니다.** 그것도 `data-list` 지만 실제 항목(바로가기 5개)이
    # 있어 정상 초기화된다 — 예외를 던지는 것은 fetch 뒤에 채우는 **빈 표**뿐이다.
    # 처음엔 `data-list` 있는 화면 전부를 요구했다가 23화면을 오탐으로 잡았다.
    _own_list = _re7.compile(r'<[^>]*\bdata-list=(?:(?!>)[^>])*>')
    _order = []
    for p, s in _screens:
        mine = [m.group(0) for m in _own_list.finditer(s) if "search-box" not in m.group(0)]
        if not mine:
            continue                      # 셸 검색창만 있는 화면 — 헬퍼가 필요 없다
        a, b = s.find("ui-list.js"), s.find("phoenix.js")
        if a < 0 or b < 0 or a > b:
            _order.append(os.path.basename(p))
    check("표를 가진 화면은 ui-list.js 를 phoenix.js 보다 먼저 싣는다",
          _order == [], [], _order[:5])

    # ⑦ **디자인 토큰을 쓰면 토큰 파일을 실어야 한다** (2026-08-05 사용자 신고).
    #    `design-system/tokens.css` 는 "단일 원천"으로 만들어 두고 **아무 화면도
    #    불러오지 않고 있었다** — 서버가 `mockups/` 만 마운트해 닿을 길이 없었다.
    #    그래서 `var(--font-num, monospace)` 가 전부 폴백으로 떨어져 숫자가 브라우저
    #    기본 고정폭(Windows: Courier New)으로 그려졌다. 판매가 재산정 화면의
    #    "글자 간격이 이상하다"가 그 증상이다. 토큰을 쓰면서 안 싣는 화면을 막는다.
    _tokenless = []
    for p, s in _screens:
        if "var(--font-num" not in s and "var(--font-head" not in s:
            continue
        if "design-system/tokens.css" not in s:
            _tokenless.append(os.path.basename(p))
    check("토큰을 쓰는 화면은 tokens.css 를 싣는다", _tokenless == [], [], _tokenless[:5])
    check("tokens.css 가 --font-num 을 정의한다",
          "--font-num:" in io.open(os.path.join(ROOT, "design-system", "tokens.css"),
                                   encoding="utf-8").read(), True, "정의 없음")
    # 서버가 그 폴더를 실제로 내주는가 — 링크만 있고 404면 조용히 폴백으로 돌아간다
    _main = io.open(os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read()
    check("서버가 design-system 을 서빙한다", '"/design-system"' in _main, True,
          "마운트 없음")

    # ⑧ choices 드롭다운이 셀렉트 폭에 갇히지 않는가.
    #    Phoenix 가 항목을 1rem !important 로 키우는데 vendor 는 목록 폭을 컨트롤에
    #    맞춰(width:100%) 좁은 셀렉트에서 **단어 중간이 끊겼다**('그래픽카/드').
    _uc = io.open(os.path.join(ROOT, "mockups", "shared", "ui-choices.js"),
                  encoding="utf-8").read()
    # ⑩ 메뉴 정본이 온전한가 (2026-08-05).
    #    항목 34개 = 옮기기 전 36화면의 **합집합** 33 + 부품 등급판(2026-08-07).
    #    줄어들면 어딘가로 가는 길이 막힌다 — 화면을 늘릴 때 이 수도 함께 올린다.
    _md = io.open(os.path.join(ROOT, "mockups", "shared", "admin-menu-data.js"),
                  encoding="utf-8").read()
    _hrefs = _re7.findall(r"href:\s*'([^']+)'", _md)
    check("메뉴 항목이 34개다", len(_hrefs) == 34, 34, len(_hrefs))
    check("메뉴가 가리키는 화면이 실제로 있다",
          all(os.path.exists(admin_html(h)) for h in _hrefs),
          "전부 존재",
          [h for h in _hrefs if not os.path.exists(admin_html(h))][:3])
    # 숫자 배지를 정본에 담지 않는다 — 담으면 거짓을 원천에 새긴다(실제 대기는 5,162였다)
    _numbadge = _re7.findall(r"badge:\s*'(\d+)'", _md)
    check("메뉴 정본에 지어낸 숫자 배지가 없다", _numbadge == [], [], _numbadge)
    # 데이터가 먼저 실려야 그린다
    _ord = []
    for _p, _s in _screens:
        if "admin-menu.js" not in _s:
            continue
        a, b = _s.find("admin-menu-data.js"), _s.find("admin-menu.js")
        if a < 0 or a > b:
            _ord.append(os.path.basename(_p))
    check("메뉴 데이터를 admin-menu.js 보다 먼저 싣는다", _ord == [], [], _ord[:4])

    check("ui-choices 가 목록 폭을 보정한다",
          "max-content" in _uc and "nowrap" in _uc, True,
          "max-content" in _uc and "nowrap" in _uc)

    # ⑪ 목록 화면의 **표 열 수가 서로 맞는가** (2026-08-05 · UI 개편).
    #    체크박스 열을 넣으면서 colgroup·thead·행·빈 상태 colspan 이 어긋나기 쉽다.
    #    어긋나면 표가 조용히 뒤틀린다 — 브라우저는 오류를 내지 않는다.
    for _n in ("products.html", "orders.html", "category-mapping.html"):
        _s = io.open(admin_html(_n), encoding="utf-8").read()
        _cg = _re7.search(r"<colgroup>(.*?)</colgroup>", _s, _re7.S)
        if not _cg:
            continue
        _ncol = _cg.group(1).count("<col")
        _i, _j = _s.find("<thead"), _s.find("</thead>")
        _nth = len(_re7.findall(r"<th[ >]", _s[_i:_j]))
        _spans = set(int(x) for x in _re7.findall(r'colspan="(\d+)"', _s))
        check("%s 열 수가 맞는다(colgroup=thead)" % _n, _ncol == _nth,
              _ncol, _nth)
        check("%s 빈 상태 colspan 이 열 수와 같다" % _n, _spans <= {_nth},
              _nth, sorted(_spans))
        # **행 템플릿의 <td> 수도 같아야 한다.** 여기까지 안 세면 열을 뺄 때 행만 남아
        # 표가 한 칸씩 밀린다 — 2026-08-07 에 공급처·상품번호 열을 빼면서 손으로 셌다.
        # **colspan 이 있는 행은 빼야 한다** — 빈 상태·불러오는 중 행은 한 칸짜리다.
        # (처음에 첫 `<tr>` 만 봤더니 orders.html 의 빈 상태 행을 데이터 행으로 오인해
        #  멀쩡한 화면을 실패로 만들었다. 검사가 틀리면 진짜 결함을 가린다.)
        _bodies = [t for t in _re7.findall(r"`<tr>(.*?)</tr>`", _s, _re7.S)
                   if "colspan" not in t]
        for _k, _t in enumerate(_bodies):
            _ntd = len(_re7.findall(r"<td[ >]", _t))
            check("%s 행 <td> 수가 열 수와 같다%s"
                  % (_n, "" if len(_bodies) == 1 else " (%d번째)" % (_k + 1)),
                  _ntd == _nth, _nth, _ntd)

    # ⑫ 일괄 선택은 **아무 일도 못 하는 체크박스가 아니다** — 실제 동작이 붙어 있어야 한다.
    _pl = io.open(admin_html("products.html"),
                  encoding="utf-8").read()
    check("상품 목록에 일괄 선택이 있다", "data-bulk-select=" in _pl, True,
          "data-bulk-select=" in _pl)
    check("일괄 선택에 실제 동작이 붙어 있다", "/products/bulk-status" in _pl, True,
          "/products/bulk-status" in _pl)

    # **일괄 선택은 장식이 아니다** (2026-08-05 규칙).
    # 체크박스만 붙이면 아무 일도 못 하는 버튼이 된다. 그래서 `data-bulk-select` 를
    # 쓰는 화면은 **일괄 엔드포인트를 부르는 코드가 있어야 한다.**
    # 실제로 두 화면은 이 기준으로 **붙이지 않기로** 했다:
    #   · 가격 검토 대기 — 큐가 파생이고 지금 0건이다(판매가 없는 4건은 전부 검수 미통과라
    #     검수 큐 소관). 누를 것이 없다.
    #   · 재고 입고 — 목록 15,273건은 '입고 대상 상품'이고 입고 수량은 **상품마다 다르다.**
    #     하나의 수량을 일괄 적용하면 거의 항상 틀린다.
    _decor = []
    for _p2, _s2 in _screens:
        if "data-bulk-select=" not in _s2:
            continue
        if not _re7.search(r'/(bulk-status|bulk-advance|category-mapping/move)', _s2):
            _decor.append(os.path.basename(_p2))
    check("일괄 선택이 있는 화면은 일괄 동작도 있다", _decor == [], [], _decor)
    # 상태 선택지를 화면이 지어내지 않는다(서버 product-meta.status_options)
    check("일괄 상태 선택지를 서버에서 받는다", "fillBulkStatus(m.status_options)" in _pl,
          True, "fillBulkStatus(m.status_options)" in _pl)

    # ⑬ 주문 목록 일괄 처리 (2026-08-05).
    #    주문은 **원장**이라 상태 기계를 두 벌로 두면 이력이 서로 다른 말을 한다.
    #    단건과 일괄이 `_advance_one` 하나를 쓰는지, 되돌리기를 새로 만들지 않았는지 본다.
    _ao = io.open(os.path.join(ROOT, "api", "admin_orders.py"), encoding="utf-8").read()
    check("주문 전이가 한 함수에 모여 있다", _ao.count("def _advance_one") == 1, 1,
          _ao.count("def _advance_one"))
    check("단건 처리가 그 함수를 쓴다", "return _advance_one(conn, o, order_no" in _ao,
          True, "return _advance_one(conn, o, order_no" in _ao)
    check("일괄 처리도 그 함수를 쓴다", "_advance_one(conn, o, o[" in _ao, True,
          "_advance_one(conn, o, o[" in _ao)
    # 되돌리기를 두 벌로 만들지 않았다 — 일괄은 건마다 order_advance 로그를 남긴다
    check("주문 되돌리기 구현은 하나뿐",
          _ao.count('log["action"] != "order_advance"') == 1, 1,
          _ao.count('log["action"] != "order_advance"'))
    _oh = io.open(os.path.join(ROOT, "mockups", "admin", "orders.html"),
                  encoding="utf-8").read()
    check("주문 목록에 일괄 선택이 있다", "data-bulk-select=" in _oh, True,
          "data-bulk-select=" in _oh)
    check("주문 일괄 선택에 실제 동작이 붙어 있다", "/orders/bulk-advance" in _oh, True,
          "/orders/bulk-advance" in _oh)
    # **건너뛴 것을 숨기지 않는다** — 왜 빠졌는지 화면이 말해야 한다
    check("건너뛴 주문의 사유를 화면이 말한다", "건너뛴 주문" in _oh, True,
          "건너뛴 주문" in _oh)

    # ⑭ 기간 필터 (2026-08-05).
    #    주문·가격 이력·활동 기록·결제에 기간으로 거를 방법이 **화면에도 서버에도 없었다.**
    #    핵심은 **9시간**이다: 컬럼은 UTC naive 인데 운영자는 서울 날짜로 생각한다.
    #    변환을 화면이 하기 시작하면 함정이 화면 수만큼 생기므로 서버 한 곳에서만 한다.
    from api.timeutil import kst_day_range as _kdr
    _lo, _hi = _kdr("2026-08-06", "2026-08-06")
    check("서울 하루 = UTC 15:00~15:00",
          (str(_lo), str(_hi)) == ("2026-08-05 15:00:00", "2026-08-06 15:00:00"),
          "2026-08-05 15:00 ~ 2026-08-06 15:00", (str(_lo), str(_hi)))
    # 끝날을 반개구간으로 두지 않으면 그날 낮 데이터가 통째로 빠진다
    check("끝날은 다음날 00:00 미만(그날 전체 포함)",
          (_hi - _lo).total_seconds() == 86400, 86400, (_hi - _lo).total_seconds())
    for _bad, _why in ((("2026-08-07", "2026-08-01"), "뒤집힌 범위"),
                       (("2026/08/07", None), "잘못된 형식")):
        try:
            _kdr(*_bad)
            check("기간 가드: %s" % _why, False, "ValueError", "통과해 버림")
        except ValueError as _e:
            check("기간 가드: %s" % _why, "%" not in str(_e), "사람이 읽는 문장", str(_e)[:40])

    # 변환은 한 곳에서만 — 화면이 시간대를 계산하면 안 된다
    _tz = [os.path.basename(p2) for p2, s2 in _screens
           if "getTimezoneOffset" in s2 or "9 * 60 * 60" in s2]
    check("화면이 시간대를 직접 계산하지 않는다", _tz == [], [], _tz)

    # 서버가 파라미터를 실제로 받는가(받기만 하고 안 걸면 아무 효과 없는 필터다)
    for _m, _col in (("admin_orders", "o.created_at"), ("admin_activity_logs", "l.created_at"),
                     ("admin_payments", "p.paid_at"), ("admin_price_history", "h.changed_at")):
        _src = io.open(os.path.join(ROOT, "api", _m + ".py"), encoding="utf-8").read()
        check("%s 가 기간을 받는다" % _m, "date_from" in _src, True, "date_from" in _src)
        check("%s 가 기간을 실제로 건다" % _m, "_RANGE" in _src and 'range_sql("%s"' % _col in _src,
              True, "_RANGE" in _src)

    # 화면은 헬퍼를 **자기보다 먼저** 실어야 한다(인라인 스크립트가 그것을 쓴다)
    _ord = []
    for _p2, _s2 in _screens:
        if "popcornDate.qs" not in _s2:
            continue
        _a, _b = _s2.find("ui-daterange.js"), _s2.find("popcornDate.qs")
        if _a < 0 or _a > _b:
            _ord.append(os.path.basename(_p2))
    check("기간 헬퍼를 쓰기 전에 싣는다", _ord == [], [], _ord)

    # ⑨ **디자인 토큰을 화면이 다시 정의하지 않는다** (2026-08-05).
    #    `vslot-demo.html` 이 tokens.css 값을 인라인으로 베껴 두고 있었고,
    #    그 사본은 **이미 정본과 어긋나 있었다** — `--font-head` 에서 'Noto Sans KR' 이
    #    빠져 있었다. 부품 어휘(슬라이스 A)·choices(H)에서 겪은 그 병이다.
    #    값을 두 벌 두면 언젠가 갈라지고, 갈라진 뒤에는 어느 쪽이 맞는지 알 수 없다.
    _tok_src = io.open(os.path.join(ROOT, "design-system", "tokens.css"),
                       encoding="utf-8").read()
    #    **`templates/` 도 훑는다** (2026-08-12 · ⑤ 와 같은 사각지대였다).
    #    `dash`·`build_map` 이 `--card` 를 자기 `:root` 에 다시 정의하고 있었는데
    #    이 검사가 목업만 보고 있어 통과했다. 대상 밖이면 검사는 없는 것과 같다.
    _canon = set(_re7.findall(r"(--[a-z-]+)\s*:", _tok_src))
    _copies = []
    for _p in (sorted(_g7.glob(os.path.join(ROOT, "mockups", "**", "*.html"), recursive=True))
               + sorted(_g7.glob(os.path.join(ROOT, "templates", "**", "*.j2"), recursive=True))):
        _s = io.open(_p, encoding="utf-8").read()
        # 화면이 정의하는 커스텀 속성 중 정본에 있는 이름을 다시 정의하는가
        #
        # 2026-08-15 (작업 #43 — 회귀 자기 검토): `part_grade.html.j2` 가
        # `--primary` 를 재정의한다고 잡혔는데 **실측해 보니 거짓 경보(㉮)였다.**
        # 원인은 `[^;]+` 가 CSS 문법을 모르고 텍스트만 본다는 것 — 이 파일엔
        # `.pg-mini--primary:disabled{color:#f0ece2;...}` 처럼 BEM 수식자
        # (`--primary`) 뒤에 가상클래스 `:disabled{` 가 바로 붙는 선택자가 있고,
        # 예전 정규식은 `--primary:disabled{color:#f0ece2` 를 "값" 으로 삼켜
        # 그 뒤의 세미콜론까지 진짜 커스텀 속성 선언(`--primary: 값;`)으로
        # 오인했다. 파일에는 `:root` 블록도, `--primary` 를 실제 속성으로 쓰는
        # 곳도 없다(확인: grep으로 `:root` 0건).
        #
        # 고친 것: 값 부분에서 `{`·`}` 를 금지했다(`[^;{}]+`) — 진짜 속성값은
        # 중괄호를 포함하지 않고, `X--이름:가상클래스{...}` 형태의 선택자만
        # 중괄호를 포함하므로 이 한 글자 차이로 구분된다.
        #
        # 검증(반대 방향 포함, 4가지):
        #   · part_grade.html.j2 그대로              -> 이제 매치 없음 (거짓 경보 해소)
        #   · `.card--card:hover{color:red;}` (같은 부류 변형) -> 매치 없음
        #   · `:root{--card:#fff;}` (2026-08-12 dash·build_map 실제 사고 재현) -> 여전히 매치
        #   · `:root{ --font-num : "Courier New", monospace ; }` (2026-08-05 실제 사고 재현) -> 여전히 매치
        # 즉 **옛 결함(값에 중괄호가 없는 진짜 재정의)은 그대로 잡고, 이번
        # 거짓 경보(값에 중괄호가 낀 선택자 오인식)만 없앴다** — 검사를 약하게
        # 만든 것이 아니라 오탐 원인 한 가지를 좁혀 없앤 것이다.
        _defs = set(_re7.findall(r"(--[a-z-]+)\s*:\s*[^;{}]+;", _s)) & _canon
        if _defs:
            _copies.append(os.path.basename(_p) + ":" + ",".join(sorted(_defs)[:3]))
    check("화면이 디자인 토큰을 다시 정의하지 않는다", _copies == [], [], _copies[:4])

    # ⑤ 폰트를 남의 서버에서 받지 않는다 (2026-08-05).
    #    망이 막히거나 그쪽이 죽으면 글꼴이 통째로 바뀐다. 아이콘은 이미 로컬이었다.
    #
    #    **`templates/` 를 함께 훑는다** (2026-08-12). 이 검사는 `mockups/**` 만 보고 있어서
    #    `/admin2/*` 서버 렌더 화면 둘이 **구글 폰트 CDN 을 부르는 채로 통과**했다.
    #    검사가 있었는데 대상 밖이라 한 번도 안 걸린 것이다 — **통과는 증거가 아니다.**
    #    화면은 이제 두 곳에 산다(목업 + Jinja 템플릿). 한 곳만 보면 새로 짓는 쪽이 샌다.
    _screens = sorted(_g7.glob(os.path.join(ROOT, "mockups", "**", "*.html"), recursive=True)) \
        + sorted(_g7.glob(os.path.join(ROOT, "templates", "**", "*.j2"), recursive=True))
    _all = [(q, io.open(q, encoding="utf-8").read()) for q in _screens]
    check("화면 파일을 목업·템플릿 양쪽에서 훑었다", len(_all) > 40, "40건 초과", len(_all))
    _cdn = [os.path.relpath(p, ROOT) for p, s in _all
            if "fonts.googleapis.com" in s or "fonts.gstatic.com" in s or "jsdelivr" in s]
    check("외부 폰트 CDN을 부르는 화면이 없다", _cdn == [], [], _cdn[:5])

    _fdir = os.path.join(ROOT, "mockups", "shared", "fonts")
    _need = ("fonts.css", "PretendardVariable.woff2", "Inter.woff2",
             "HankenGrotesk.woff2", "JetBrainsMono.woff2")
    _gone = [f for f in _need if not os.path.exists(os.path.join(_fdir, f))]
    check("로컬 폰트 파일이 실제로 있다", _gone == [], [], _gone)

    # OFL 은 **재배포 시 라이선스 동봉이 조건**이다 — 폰트를 우리 서버에서 내주는 순간
    # 재배포다. 아이콘(Streamline)에 출처 표기를 붙인 것과 같은 이유.
    _ofl = sorted(f for f in os.listdir(_fdir) if f.startswith("OFL-"))
    check("OFL 라이선스 원문을 함께 둔다", len(_ofl) >= 4, ">= 4", len(_ofl))

    # 폰트를 쓰던 화면은 로컬 시트를 링크해야 한다 — 안 그러면 시스템 글꼴로 조용히 바뀐다.
    #
    # 2026-08-13 admin2 셸 상속(`{% extends %}`) 도입 이후 이 검사가 두 가지를 오탐했다
    # (제작팀 B 실측 — `ai_integration.html.j2`·`ai_usage_cost.html.j2`·`reviews.html.j2`
    # 셋이 걸렸는데 셋 다 화면은 멀쩡했다):
    #   ① 실제 폰트 링크(`<link … fonts.css>`)는 부모 `_admin2_shell.html.j2` 가 담당하는데,
    #      이 검사는 **자식 파일의 원문 텍스트만** 보고 "링크가 없다"고 판정했다.
    #   ② Jinja 주석(`{# … #}`) 안의 설계 근거 서술("Pretendard 로 대체했다" 같은 메모)을
    #      실제 CSS 참조로 오인해 "이 화면은 폰트를 쓴다"는 판정부터 잘못 냈다 — 렌더되면
    #      주석은 사라지므로 판정 재료가 아니다.
    #   실측(curl)으로 세 화면 모두 `/shared/fonts/fonts.css` 200 을 받고 있었다.
    #
    # 고친 것: (a) 주석을 지우고 본다. (b) `.j2` 는 `{% extends %}` 를 따라가 **조상까지
    # 합친 텍스트**로 링크 유무를 본다 — 실제 렌더 결과의 <head> 가 그 합집합이기 때문이다.
    # **여전히 파일을 읽는 정적 검사다**(서버 없이도 돈다) — 대안으로 실제 렌더 결과를
    # `get_html()`([41]의 선례)로 받아 검사하는 방법도 있지만, 그러려면 템플릿마다
    # "어느 URL이 이 파일을 렌더하는가"를 새로 매핑해야 한다(정본 없음 — 만들면 그 목록이
    # 또 낡는다). 정적 상속 추적이 지금은 더 안전하다.
    # **다음에 또 낡을 지점**: 상속이 2단 이상(셸이 다른 셸을 상속) 되면 `_ancestor_text`
    # 는 이미 재귀라 그대로 따라가지만, `{% extends %}` 문법 자체가 바뀌거나(예: 매크로로
    # 대체) 템플릿 루트(`TEMPLATES_DIR`, `api/admin_ui_common.py`)가 `templates/` 밖으로
    # 옮겨지면 이 정규식·경로 계산을 다시 봐야 한다.
    _EXTENDS_RE = _re7.compile(r'\{%-?\s*extends\s+["\']([^"\']+)["\']\s*-?%\}')
    _COMMENT_RE = _re7.compile(r'\{#.*?#\}', _re7.DOTALL)

    def _strip_comments(text):
        return _COMMENT_RE.sub('', text)

    def _ancestor_text(path, seen=None):
        """`{% extends %}` 로 이어진 조상 템플릿까지 주석을 뺀 원문을 이어 붙인다."""
        seen = seen if seen is not None else set()
        if path in seen or not os.path.exists(path):
            return ""
        seen.add(path)
        nc = _strip_comments(io.open(path, encoding="utf-8").read())
        m = _EXTENDS_RE.search(nc)
        if not m:
            return nc
        parent = os.path.normpath(os.path.join(ROOT, "templates", m.group(1)))
        return nc + "\n" + _ancestor_text(parent, seen)

    _nolink = []
    for p, s in _all:
        s_nc = _strip_comments(s)
        if not ("Pretendard" in s_nc or "Hanken" in s_nc):
            continue
        combined = _ancestor_text(p) if p.endswith(".j2") else s_nc
        if "shared/fonts/fonts.css" not in combined:
            _nolink.append(os.path.relpath(p, ROOT))
    check("폰트를 쓰는 화면이 로컬 시트를 링크한다", _nolink == [], [], _nolink[:5])

    # ⑥ Material Symbols 폰트를 뗐으므로, 매핑이 없는 글리프는 **글자가 그대로 뜬다**
    #    (예전엔 웹폰트가 가려 줬다). su-icons 의 MS 맵이 전부 덮는지 본다.
    _su = io.open(os.path.join(ROOT, "mockups", "shared", "su-icons.js"),
                  encoding="utf-8").read()
    _msmap = set(_re7.findall(r'"([a-z_0-9]+)":\s*"(?:ms|ft)-', _su))
    _raw = []
    for p, s in _all:
        for m in _re7.finditer(
                r'class="[^"]*material-symbols-outlined[^"]*"[^>]*>([^<]*)<', s):
            g = m.group(1).strip()
            if g and g not in _msmap:
                _raw.append(os.path.basename(p) + ":" + g)
    check("material-symbols 글리프가 전부 매핑돼 있다", _raw == [], [], _raw[:5])

    # 스타일이 안 먹으면 화면은 뜨지만 읽을 수 없는 상태가 된다 — 테마를 싣는지 본다
    noTheme = []
    for _p in admin_htmls():
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        if "theme.min.css" not in _s:
            noTheme.append(_n)
    check("모든 관리자 화면이 테마를 싣는다", not noTheme, "전부", noTheme[:5])


def test_password_policy():
    print("\n[29] 비밀번호 변경 — 규칙을 먼저 말하고 입력을 가린다 (슬라이스 100)")
    # 예전 비밀번호 변경은 `prompt()` 2연타였다. 문제 셋:
    #   (1) 브라우저 prompt는 마스킹이 없어 입력이 화면에 그대로 보인다(어깨너머 노출)
    #   (2) 강도 규칙을 거절당한 뒤에야 알았다 — 그리고 화면은 "8자 이상"이라 적었는데
    #       서버는 10자를 요구했다. **화면이 규칙을 틀리게 말하고 있었다.**
    #   (3) 새 비밀번호를 한 번만 받아 오타를 잡을 수 없었다
    d = get("/api/admin/auth/password-policy")
    check("강도 규칙을 서버가 준다",
          isinstance(d, dict) and d.get("rules"), "rules 있음", d)
    if not isinstance(d, dict) or not d.get("rules"):
        return

    # 판정과 설명이 같은 원천이어야 한다 — 화면이 베끼면 MIN_LENGTH를 올린 날 거짓이 된다
    try:
        sys.path.insert(0, ROOT)
        from api.passwords import MIN_LENGTH, strength_problem
        check("규칙이 알려주는 길이 = 실제 판정 길이",
              d.get("min_length") == MIN_LENGTH, MIN_LENGTH, d.get("min_length"))
        # 규칙 문구가 실제 판정과 어긋나지 않는가 — 길이 경계로 확인한다
        short = "Aa1!" + "b" * (MIN_LENGTH - 5)
        check("경계보다 짧으면 실제로 거절된다",
              strength_problem(short) is not None, "거절", "통과")
        okpw = "Vq7#mzLp2rTx"
        check("규칙을 지킨 값은 통과한다", strength_problem(okpw) is None,
              None, strength_problem(okpw))
    except Exception as e:                               # noqa: BLE001
        print(f"  [SKIP] (I) 강도 판정 모듈 - {e}")

    # 규칙 설명에 원문·해시가 섞여 나가지 않는다
    blob = json.dumps(d, ensure_ascii=False)
    check("규칙 응답에 해시 형식이 없다", "scrypt$" not in blob, "없음", "포함")

    # ── 화면 계약 ──
    try:
        mp = io.open(os.path.join(ROOT, "mockups", "admin", "my-profile.html"),
                     encoding="utf-8").read()
        # prompt는 입력이 화면에 그대로 보인다 — 비밀번호를 받는 데 쓰지 않는다
        body = mp.split("</script>")
        live = "".join(x for x in body if "openPwModal" in x or "pw-cur" in x)
        check("비밀번호를 prompt로 받지 않는다",
              "prompt(" not in live.replace("prompt() 2연타를 모달로", ""),
              "모달", "prompt 사용")
        check("비밀번호 칸이 type=password다", live.count('type="password"') >= 3,
              "3칸 이상", live.count('type="password"'))
        # 규칙을 화면에 베껴 쓰면 서버가 바뀔 때 거짓이 된다
        check("규칙을 서버에서 받아 보여준다", "/auth/password-policy" in mp, "호출", "없음")
        check("규칙을 못 받으면 지어내지 않는다",
              "규칙을 불러오지 못했습니다" in mp, "정직 표기", "없음")
        # 오타 때문에 서버까지 왕복하지 않는다
        check("새 비밀번호를 두 번 받아 대조한다", "pw-new2" in mp, "있음", "없음")
        # 바꾸면 다른 세션이 끊긴다(슬라이스 70) — 그 사실을 미리 말한다
        check("세션 해제를 미리 알린다", "다른 기기의 로그인이 모두 해제" in mp, "있음", "없음")
        # 이 화면은 lean 셸이라 bootstrap을 안 싣고 있었다 — 모달이 조용히 죽었다
        check("모달에 필요한 bootstrap을 싣는다",
              "vendors/bootstrap/bootstrap.min.js" in mp, "있음", "없음")
        check("bootstrap이 없으면 그 사실을 말한다",
              'typeof bootstrap === "undefined"' in mp, "가드 있음", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 비밀번호 모달 계약 - {e}")


def test_session_revoke():
    print("\n[28] 다른 기기에서 로그아웃 (슬라이스 100)")
    # 화면이 "열려 있는 세션 21개"라고 정직하게 말하면서 **끊을 수단을 주지 않았다.**
    # 공용 PC에서 로그인한 것을 알아차려도 할 수 있는 게 없었다.
    d = get("/api/admin/my-profile/sessions")
    check("내 세션 목록을 읽는다", isinstance(d, dict) and "items" in d, "items 있음", d)
    if not isinstance(d, dict) or "items" not in d:
        return
    cur = [i for i in d["items"] if i.get("current")]
    check("현재 기기가 정확히 하나로 표시된다", len(cur) == 1, 1, len(cur))
    check("다른 기기 수 = 전체 - 현재",
          d.get("others") == d.get("total") - 1, d.get("total") - 1, d.get("others"))
    # **세션 식별자를 내보내면 그 값이 곧 로그인 자격이다.**
    leaked = sorted({k for i in d["items"] for k in i
                     if "session" in k.lower() or k.lower() == "id"})
    check("세션 식별자를 화면에 내보내지 않는다", not leaked, "없음", leaked)

    src = db_one("SELECT count(*) FROM admin_sessions s"
                 " JOIN admin_operators o USING (operator_id)"
                 " WHERE lower(o.email) = :e AND s.revoked_at IS NULL"
                 "   AND s.expires_at > now()", e=ADMIN_EMAIL.lower())
    if src is not None:
        check("세션 수 = DB가 세는 수", d.get("total") == src, src, d.get("total"))

    # ── 이 왕복은 **사람의 브라우저 세션을 끊는다** ─────────────────────────
    # revoke-others 는 같은 운영자의 다른 세션을 전부 철회한다. 회귀는 시드 owner 로
    # 로그인하므로, 그 계정으로 브라우저에 로그인해 둔 사람은 회귀가 돌 때마다 쫓겨난다.
    #
    # 사용자 신고(2026-08-06) "서버를 재기동하면 계속 로그인을 해야 한다" — **재기동 탓이
    # 아니었다.** 세션은 `admin_sessions` 테이블에 있고 인증이 매 요청 DB를 조회하므로
    # 재기동으로 죽지 않는다. 끊고 있던 것은 이 검사였다.
    #
    # 그래서 끄는 길을 둔다(`REGRESSION_KEEP_SESSIONS=1`). **조용히 건너뛰지는 않는다** —
    # 건너뛴 검사는 거짓 안심이고, 이 프로젝트는 DB 에 못 닿을 때도 그 사실을 말한다.
    # 화면을 붙들고 작업하는 동안만 켜고, 평소에는 끈 채로 둔다.
    if os.environ.get("REGRESSION_KEEP_SESSIONS"):
        print("  [건너뜀] 다른 기기 로그아웃 왕복 6건 — REGRESSION_KEEP_SESSIONS 가 켜져 있습니다.")
        print("           사람의 브라우저 세션을 지키려고 뺀 것입니다. 이 항목은 검증되지 않았습니다.")
    else:
        # 왕복 — 세션 두 개를 더 만들고 끊는다. 현재 세션은 살아 있어야 한다.
        extra = []
        for _ in range(2):
            st, _b = post("/api/admin/auth/login",
                          {"email": ADMIN_EMAIL, "password": ADMIN_PW})
            extra.append(st)
        check("검사용 세션을 만들었다", extra == [200, 200], [200, 200], extra)
        # 위 로그인이 SESSION 쿠키를 갈아치웠으므로 지금 쿠키가 현재 세션이다
        before = get("/api/admin/my-profile/sessions").get("total")
        st, r = post("/api/admin/my-profile/sessions/revoke-others")
        check("다른 기기 로그아웃이 된다", st == 200, 200, st)
        check("현재 세션은 남는다", r.get("remaining") == 1, 1, r.get("remaining"))
        check("끊은 수 = 있던 수 - 1",
              r.get("revoked") == (before or 0) - 1, (before or 0) - 1, r.get("revoked"))
        # 현재 쿠키가 아직 통해야 한다 — 자기 세션을 끊으면 그 자리에서 쫓겨난다
        still = get("/api/admin/my-profile")
        check("끊은 뒤에도 현재 세션으로 조회된다",
              isinstance(still, dict) and still.get("id") is not None, "조회됨", still)
        # 삭제가 아니라 철회다 — 행이 남아 "언제 열려 있었나"를 잃지 않는다
        rev = db_one("SELECT count(*) FROM admin_sessions s"
                     " JOIN admin_operators o USING (operator_id)"
                     " WHERE lower(o.email) = :e AND s.revoked_at IS NOT NULL",
                     e=ADMIN_EMAIL.lower())
        if rev is not None:
            check("철회는 삭제가 아니다(행이 남는다)", rev > 0, "1건 이상", rev)
        check("작업 기록에 남는다",
              (db_one("SELECT count(*) FROM admin_operator_activity_logs"
                      " WHERE action = 'session_revoke_others'") or 0) > 0,
              "1건 이상", 0)

    # ── 화면 계약 ──
    try:
        mp = io.open(os.path.join(ROOT, "mockups", "admin", "my-profile.html"),
                     encoding="utf-8").read()
        check("다른 기기 로그아웃 버튼이 있다", "revokeOthers" in mp, "있음", "없음")
        # 세션이 하나뿐이면 할 일이 없다 — 버튼이 자리를 차지하지 않아야 한다
        check("세션이 하나면 버튼을 내지 않는다", "live_sessions > 1" in mp, "분기 있음", "없음")
        # 누르고 나서 알면 늦다 · 되돌릴 수 없다는 사실을 먼저 말한다
        check("누르기 전에 영향을 먼저 묻는다",
              "/my-profile/sessions" in mp and "confirm(" in mp, "확인 있음", "없음")
        check("되돌릴 수 없다고 밝힌다", "되돌릴 수 없습니다" in mp, "있음", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 내 정보 화면 계약 - {e}")


def test_time_display():
    print("\n[27] 시각 표기 — 화면이 ISO 원문을 내보내지 않는다 (슬라이스 100)")
    # 슬라이스 62가 정한 규약: 서버는 타임존 붙은 절대시각을 주고 **표시는 화면이 한다.**
    # 그런데 내 정보 화면(슬라이스 92)이 ISO를 원문 그대로 출력했다 —
    #     마지막 로그인   2026-07-30T04:57:22.084811+00:00
    # 사람이 못 읽고, 더 나쁜 것은 04:57(UTC)이 실제 13:57(KST)와 9시간 어긋나 보인다는 것이다.
    # 운영자는 "새벽에 로그인했나?"로 읽는다.
    import glob as _g6
    import re as _re6

    # 서버가 ISO로 돌려주는 필드 이름 — 이 값이 포맷 없이 화면에 나가면 원문이 그대로 보인다
    ISO_FIELDS = ("joined", "approved_at", "last_login", "password_set_at", "created",
                  "created_at", "updated_at", "received_at", "reviewed_at",
                  "effective_from", "expires_at", "last_seen_at")
    # 포맷을 거쳤다는 흔적 — 화면마다 이름이 다르므로(fmtT·fmt·relTime·PT) 넓게 본다
    FMT = _re6.compile(r"(PT\.|fmtT\s*\(|fmt\w*\s*\(|relTime\s*\(|new Date\s*\(|toLocale)")

    raw = []
    for _p in (admin_htmls()
               + sorted(_g6.glob(os.path.join(ROOT, "mockups", "mvp1", "*.html")))):
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        for f in ISO_FIELDS:
            # `\b`가 없으면 `joined`가 `joinedLabel`에도 걸려 오탐이 된다
            NL = chr(10)          # 이스케이프가 전달 중 풀리는 것을 피한다
            for m in _re6.finditer(r"[\w$]+\.(" + f + r")" + chr(92) + "b", _s):
                ls = _s.rfind(NL, 0, m.start()) + 1
                le = _s.find(NL, m.end())
                line = _s[ls:le if le > 0 else len(_s)]
                if FMT.search(line):
                    continue
                raw.append(f"{_n}:{_s[:m.start()].count(chr(10)) + 1} {f}")
    check("화면이 ISO 원문을 그대로 출력하지 않는다", not raw, "없음", raw[:5])

    # 공통 포맷 모듈이 있어야 7번째 사본이 생기지 않는다.
    # (fmtT가 이미 6개 화면에 각자 정의돼 두 갈래로 갈려 있었다)
    fp = os.path.join(ROOT, "mockups", "shared", "fmt-time.js")
    check("시각 표기 공통 모듈이 있다", os.path.exists(fp), "있음", "없음")
    if os.path.exists(fp):
        ft = io.open(fp, encoding="utf-8").read()
        # 못 읽는 값을 'Invalid Date'로 흘리지 않는다 — 화면에 그 글자가 뜨면 그것도 거짓이다
        check("잘못된 값을 Invalid Date로 흘리지 않는다", "isNaN" in ft, "가드 있음", "없음")
        # 값이 없으면 지어내지 않는다
        check("값이 없으면 '—'로 둔다", "NONE" in ft and "'—'" in ft, "있음", "없음")

    # 하드코딩된 날짜를 기본값으로 쓰지 않는다 —
    # my-page가 `m.joined || '2026-07-16'`으로 없는 가입일을 지어내고 있었다
    hard = []
    for _p in (admin_htmls()
               + sorted(_g6.glob(os.path.join(ROOT, "mockups", "mvp1", "*.html")))):
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        for m in _re6.finditer(r"\|\|\s*['\"]20\d\d-\d\d-\d\d", _s):
            hard.append(f"{_n}:{_s[:m.start()].count(chr(10)) + 1}")
    check("하드코딩된 날짜를 기본값으로 쓰지 않는다", not hard, "없음", hard[:4])

    # 화면이 그 모듈을 실제로 싣는가 — 안 실으면 PT가 undefined라 렌더가 죽는다
    missing = []
    for _p in (admin_htmls()
               + sorted(_g6.glob(os.path.join(ROOT, "mockups", "mvp1", "*.html")))):
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        if "PT." in _s and "fmt-time.js" not in _s:
            missing.append(_n)
    check("PT를 쓰는 화면은 모듈을 싣는다", not missing, "전부", missing[:4])


def test_stock_ledger():
    print("\n[26] 재고 원장 · 연속 등록 (슬라이스 97)")
    # 상품 상세에서 stock_qty를 고칠 수 있는데 stock_movements에 아무것도 남지 않았다.
    # 재고 입고(ADM-SRC-020)는 원장 계약대로 남기는데 이 경로만 건너뛰었다.
    # 사용 기록은 0건이었지만 **등록 직후 재고를 넣는 가장 자연스러운 경로가 여기다** —
    # 쓰기 시작하면 "수량만 고치면 어디서 왔는지 알 수 없다"(슬라이스 69)가 된다.
    pc = db_one("SELECT product_code FROM products WHERE data_origin='demo'"
                " AND category_group='core_part' ORDER BY product_code LIMIT 1")
    if pc is None:
        print("  [SKIP] (I) 데모 상품 표본 없음")
        return
    before = db_one("SELECT stock_qty FROM products WHERE product_code=:i", i=pc)
    mv0 = db_one("SELECT count(*) FROM stock_movements WHERE product_code=:i", i=pc)
    if before is None:
        print("  [SKIP] (I) 재고 조회 실패")
        return

    st, d = post_raw(f"/api/admin/products/{pc}",
                     json.dumps({"changes": {"stock_qty": before + 7}}).encode(),
                     {"Content-Type": "application/json"}, method="PATCH")
    check("상세에서 재고를 고칠 수 있다", st == 200, 200, st)
    undo_id = (d or {}).get("undo_id")
    check("재고를 고치면 원장에 남는다",
          db_one("SELECT count(*) FROM stock_movements WHERE product_code=:i", i=pc) == mv0 + 1,
          mv0 + 1, db_one("SELECT count(*) FROM stock_movements WHERE product_code=:i", i=pc))
    check("원장 종류는 adjust다(입고가 아니라 사람의 보정)",
          db_one("SELECT movement_type FROM stock_movements WHERE product_code=:i"
                 " ORDER BY movement_id DESC LIMIT 1", i=pc) == "adjust",
          "adjust", db_one("SELECT movement_type FROM stock_movements WHERE product_code=:i"
                           " ORDER BY movement_id DESC LIMIT 1", i=pc))
    check("증감분이 원장에 정확히 적힌다",
          db_one("SELECT qty_delta FROM stock_movements WHERE product_code=:i"
                 " ORDER BY movement_id DESC LIMIT 1", i=pc) == 7,
          7, db_one("SELECT qty_delta FROM stock_movements WHERE product_code=:i"
                    " ORDER BY movement_id DESC LIMIT 1", i=pc))

    if undo_id:
        st2, _ = post(f"/api/admin/products/undo/{undo_id}")
        check("되돌리기가 된다", st2 == 200, 200, st2)
        # 되돌림은 삭제가 아니라 역방향 행이다 — 원래 행을 지우면
        # "재고가 늘었다가 줄었다"는 사실이 사라진다
        check("되돌리면 상쇄 행이 쌓인다(원래 행을 지우지 않는다)",
              db_one("SELECT count(*) FROM stock_movements WHERE product_code=:i", i=pc)
              == mv0 + 2, mv0 + 2,
              db_one("SELECT count(*) FROM stock_movements WHERE product_code=:i", i=pc))
        check("상쇄 행은 역방향이다",
              db_one("SELECT qty_delta FROM stock_movements WHERE product_code=:i"
                     " ORDER BY movement_id DESC LIMIT 1", i=pc) == -7,
              -7, db_one("SELECT qty_delta FROM stock_movements WHERE product_code=:i"
                         " ORDER BY movement_id DESC LIMIT 1", i=pc))
        check("재고가 원래 값으로 돌아온다",
              db_one("SELECT stock_qty FROM products WHERE product_code=:i", i=pc) == before,
              before, db_one("SELECT stock_qty FROM products WHERE product_code=:i", i=pc))

    # 검사가 만든 원장 행·로그는 치운다.
    # 원장 규약("지우지 않는다")은 **실제 운영 행위**에 적용된다 — 검사가 만든 것은
    # 슬라이스 78이 말한 '검사 잔재'이므로 남기지 않는다(안 치우면 실행마다 2행씩 쌓인다).
    db_exec("DELETE FROM stock_movements WHERE product_code=:i AND movement_type='adjust'"
            " AND ref_kind='manual' AND abs(qty_delta)=7"
            " AND created_at > now() - interval '5 minutes'", i=pc)
    db_exec("DELETE FROM admin_operator_activity_logs"
            " WHERE action IN ('product_edit','product_edit_undo')"
            "   AND target_id = (SELECT sku FROM products WHERE product_code=:i)"
            "   AND created_at > now() - interval '5 minutes'", i=pc)
    check("검사가 원장을 원래대로 되돌렸다",
          db_one("SELECT count(*) FROM stock_movements WHERE product_code=:i", i=pc) == mv0,
          mv0, db_one("SELECT count(*) FROM stock_movements WHERE product_code=:i", i=pc))
    check("검사가 재고를 원래대로 되돌렸다",
          db_one("SELECT stock_qty FROM products WHERE product_code=:i", i=pc) == before,
          before, db_one("SELECT stock_qty FROM products WHERE product_code=:i", i=pc))

    # ── 재고 = 원장 합 (슬라이스 98) ──
    # 적재가 stock_qty를 직접 넣으면서 원장을 안 남겨 7,547건이 원장 밖에 있었다.
    # `stock_movements` 합으로 재고를 검증할 수 없다는 뜻이었다.
    # 0026이 기초 재고(opening)로 기준선을 긋고, catalog_ingest가 앞으로 델타를 남긴다.
    #
    # **이 불변식이 이 슬라이스의 본체다.** 어긋나면 재고를 원장 밖에서 바꾼 경로가
    # 새로 생겼다는 뜻이다 — 그 경로를 찾아 원장을 남기게 고쳐야 한다(값을 맞추지 말고).
    off = db_one("SELECT count(*) FROM products p"
                 " LEFT JOIN (SELECT product_code, SUM(qty_delta) sd"
                 "              FROM stock_movements GROUP BY product_code) m"
                 "        ON m.product_code = p.product_code"
                 " WHERE p.stock_qty <> COALESCE(m.sd, 0)")
    if off is not None:
        check("재고 = 원장 합 (전 상품)", off == 0, 0, off)
    orphan = db_one("SELECT count(*) FROM products p WHERE p.stock_qty > 0"
                    "   AND NOT EXISTS (SELECT 1 FROM stock_movements m"
                    "                    WHERE m.product_code = p.product_code)")
    if orphan is not None:
        check("재고가 있으면 원장이 있다", orphan == 0, 0, orphan)
    # 기초 재고는 입고를 주장하지 않는다 — 과거 입고 시점을 모르기 때문이다.
    # 이 행이 inbound로 섞이면 "언제 들어왔는지 안다"는 거짓이 된다.
    bad_open = db_one("SELECT count(*) FROM stock_movements"
                      " WHERE ref_kind = 'opening' AND movement_type <> 'adjust'")
    if bad_open is not None:
        check("기초 재고는 입고를 주장하지 않는다", bad_open == 0, 0, bad_open)
    # 적재가 원장을 남기는 코드가 살아 있는가 — 지워지면 다시 7,547건이 쌓인다
    try:
        import re as _re16
        ci = io.open(os.path.join(ROOT, "api", "catalog_ingest.py"), encoding="utf-8").read()
        check("적재가 재고 델타를 원장에 남긴다",
              "stock_movements" in ci and "'catalog'" in ci, "있음", "없음")
        # 2026-08-15 (작업 #44 — 회귀가 «이름»으로 «동작»을 추정하는지 재검토):
        # 예전엔 `"stock_before" in ci` — 파일 어딘가에 이 **이름**이 있는지만
        # 봤다(바로 위 §왕복 절 주석이 스스로 "회귀 [26]이 이 리터럴이 있는지로
        # 판정한다"고 적어 둔 그 검사 — 자백이 있었다).
        #
        # 무엇을 놓치는지 실측(반대 방향 검증, 3가지 — 아래는 스크립트로 재현):
        #   · 현재 코드(`"q": a - b`, a=신규 b=이전)         -> 옛 검사 PASS, 새 검사 PASS
        #   · 절대값으로 되돌아간 옛 결함(`"q": a`)            -> 옛 검사 **PASS(오탐!)**, 새 검사 FAIL
        #   · 뺄셈 순서가 뒤집힌 부호 버그(`"q": b - a`)       -> 옛 검사 **PASS(오탐!)**, 새 검사 FAIL
        # `stock_before` 라는 글자는 델타 계산이 사라지거나 부호가 뒤집혀도
        # `if a == b:` 비교 등 다른 자리에 계속 남는다 — 옛 검사는 그 두 사고를
        # **하나도 못 잡는다.** 슬라이스 98이 겪은 사고(원장에 절대값이 쌓여
        # `SUM(qty_delta)`가 실제 재고와 어긋나는 것)가 재발해도 이 파일 안에서는
        # 이 검사가 유일한 방어선이다 — 회귀는 apply를 실행하지 않으므로([11]
        # 참조, 정본 오염 방지) 실제 DB 왕복으로는 못 잡고, 사고가 real apply로
        # 이미 벌어진 뒤 "재고 = 원장 합"(위 §3290행대)으로만 사후 발견된다.
        #
        # 고친 것: ① `stock_before.get(...)` 결과를 받는 변수를 실제로 찾고,
        # ② `stock_movements` INSERT의 `:q`(= qty_delta) 자리 식이 **그 변수를
        # 정확히 빼는 항으로 삼는 뺄셈**(신규값 - 이전값 순서)인지 함께 본다.
        # 전후 값의 변수명이 바뀌어도(리팩터링) 구조가 같으면 계속 통과한다.
        # 한계(고의로 남김): `delta = a - b`처럼 뺄셈을 중간 변수에 먼저 담고
        # `"q": delta`로 참조하면 이 검사는 못 찾는다 — 그런 리팩터링을 하면
        # FAIL로 드러나므로(조용히 통과하는 것보다 낫다) 그때 이 정규식을 같이 고친다.
        _before_m = _re16.search(r"([A-Za-z_]\w*)\s*=\s*stock_before\.get\(", ci)
        _q_m = _re16.search(
            r'"q"\s*:\s*\(?\s*([A-Za-z_]\w*)\s*-\s*([A-Za-z_]\w*)\s*\)?\s*,', ci)
        _delta_ok = (bool(_before_m) and bool(_q_m)
                     and _q_m.group(1) != _q_m.group(2)
                     and _q_m.group(2) == _before_m.group(1))
        check("적재는 절대값이 아니라 델타를 남긴다(뺄셈식 실측 — 신규값-이전값 순서)",
              _delta_ok, "이전재고 변수를 신규값에서 빼는 식",
              {"이전재고 변수": _before_m.group(1) if _before_m else None,
               "q 식": (_q_m.group(0).rstrip(", ") if _q_m else None)})
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 적재 원장 계약 - {e}")

    # ── 화면 계약 ── 연속 등록 (슬라이스 97)
    # 빈 상태에서 견적 한 벌 = 8개 슬롯. 슬롯 하나가 0이면 견적이 0건이라 최소 8번 등록한다.
    try:
        pe = io.open(admin_html("product-edit.html"),
                     encoding="utf-8").read()
        check("저장하고 다음 상품 버튼이 있다",
              'id="saveNext"' in pe or '.id = "saveNext"' in pe, "있음", "없음")
        check("등록 후 같은 화면에 남는 분기가 있다", "__saveNext" in pe, "있음", "없음")
        # 등록만 8번 하고 사양·매입가·재고를 잊으면 슬롯은 여전히 0이다
        check("이번에 등록한 것을 링크로 남긴다",
              'id="regTrail"' in pe or '.id = "regTrail"' in pe, "있음", "없음")
        # 앞 상품의 값이 남아 그대로 저장되면 슬라이스 55가 잡은 '남의 값' 사고가 된다
        check("다음 입력을 위해 이름·제조사를 비운다",
              'fieldByLabel("상품명")' in pe and 'mkEl.value = ""' in pe, "비움", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 등록 화면 계약 - {e}")


def test_review_flow():
    print("\n[25] 검수 큐 흐름 — 연속 입력과 정직한 진행 표시 (슬라이스 96)")
    # 899건(판매중.재고)을 사람이 손으로 넣어야 하는데, 화면이 두 가지를 잘못하고 있었다.
    d = get("/api/admin/reviews?page=1&size=100&sellable=1")
    check("검수 큐를 읽는다", isinstance(d, dict) and "items" in d, "items 있음", type(d).__name__)
    if not isinstance(d, dict) or "items" not in d:
        return

    # ① 남은 수는 **서버가 준 값**이다. 예전 화면은 현재 페이지 길이(최대 100)를
    #    '남은 N건'으로 띄웠다 — 실제 899건이 남았는데 화면은 100이라 말했고,
    #    같은 화면 아래에는 정직한 총계가 있어 한 화면이 두 말을 했다.
    check("남은 수를 서버가 준다", d.get("remaining") == d.get("total"),
          d.get("total"), d.get("remaining"))
    check("남은 수는 페이지 길이와 다를 수 있다",
          d.get("remaining") is not None, "값 있음", None)
    src = db_one("SELECT count(*) FROM product_reviews r JOIN products p USING (product_code)"
                 " WHERE r.review_status='대기' AND p.status='판매중' AND p.stock_qty>0")
    if src is not None:
        check("남은 수 = DB가 세는 수(판매중.재고)", d.get("remaining") == src, src, d.get("remaining"))

    # ② '오늘 처리'는 서버 집계다. JS 변수였을 때는 새로고침하면 0이 됐다 —
    #    라벨이 '오늘'인데 실제로는 '이 페이지를 연 뒤'였다.
    check("오늘 처리 수를 서버가 준다", d.get("my_today") is not None, "값 있음", None)
    # 서울 자정 기준이어야 한다. UTC 자정(=09:00 KST)을 쓰면 오전 8시에 0으로 보인다.
    seoul = db_one("SELECT count(*) FROM product_reviews pr"
                   " WHERE pr.reviewed_by = (SELECT operator_id FROM admin_operators"
                   "                          WHERE lower(email)=:e)"
                   "   AND pr.reviewed_at >= (date_trunc('day',"
                   "         now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')"
                   "         AT TIME ZONE 'UTC'", e=ADMIN_EMAIL.lower())
    if seoul is not None:
        check("오늘 처리는 서울 자정 기준", d.get("my_today") == seoul, seoul, d.get("my_today"))

    # 사양별로 좁히면 남은 수도 그 사양 기준이어야 한다 — 분모가 안 따라오면
    # '307건 중 12번째'가 '100건 중 12번째'가 된다
    f = db_one("SELECT r.field_name FROM product_reviews r JOIN products p USING (product_code)"
               " WHERE r.review_status='대기' AND p.status='판매중' AND p.stock_qty>0"
               " GROUP BY r.field_name ORDER BY count(*) DESC LIMIT 1")
    if f:
        fd = get(f"/api/admin/reviews?page=1&size=100&sellable=1&field={_uq(f)}")
        check("사양으로 좁히면 남은 수도 좁혀진다",
              fd.get("remaining") == fd.get("total") and fd.get("remaining") <= d.get("remaining"),
              f"<= {d.get('remaining')}", fd.get("remaining"))
        check("서버가 어떤 사양으로 좁혔는지 되돌려 말한다", fd.get("field") == f, f, fd.get("field"))

    # ── 화면 계약 ──
    try:
        rq = io.open(admin_html("review-queue.html"),
                     encoding="utf-8").read()
        # 830건을 손으로 넣는데 저장하면 모달이 닫히고 끝이었다 — 왕복이 830번이다
        check("저장하고 다음 버튼이 있다", 'id="fixNext"' in rq, "있음", "없음")
        check("다음 항목을 여는 분기가 있다", "goNext" in rq, "있음", "없음")
        check("몇 번째인지 표시한다", 'id="fixPos"' in rq, "있음", "없음")
        # 큰 숫자가 서버 값을 쓰는가 — 페이지 길이로 되돌아가면 다시 거짓말한다
        check("남은 수에 서버 값을 쓴다", "SRV.remaining" in rq, "사용", "없음")
        check("오늘 처리에 서버 값을 쓴다", "SRV.my_today" in rq, "사용", "없음")
        check("페이지가 전체보다 작으면 밝힌다", 'id="pageNote"' in rq, "있음", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 검수 화면 계약 - {e}")


def test_product_gate():
    print("\n[24] 상품 게이트 체크리스트 · 사양 항목 정의 이름 정정 (슬라이스 95)")
    # 왜 필요했나: `verdict`는 elif 사슬이라 **막힌 이유 하나만** 말한다. 실측 사례 —
    # 미분류·사양없음·검수·품절·재고0 다섯이 막힌 상품에 verdict는 '품절'만 말했다.
    # 운영자가 품절을 풀어도 미분류라 영원히 후보가 안 된다. 남은 것을 전부 말해야 한다.
    pc = db_one("SELECT product_code FROM v_recommendation_candidates"
                " WHERE stock_qty > 0 LIMIT 1")
    if pc is None:
        print("  [SKIP] (I) 후보 표본 없음")
        return
    d = get(f"/api/admin/products/{pc}")
    check("통과 상품은 게이트가 전부 통과", d.get("gate_blocked") == [], [], d.get("gate_blocked"))
    check("통과 상품은 다음 할 일이 없다", d.get("gate_first") is None, None, d.get("gate_first"))
    check("게이트 항목은 6개", len(d.get("gate") or []) == 6, 6, len(d.get("gate") or []))

    # 게이트 통과 여부와 실제 후보 여부가 일치해야 한다 —
    # 어긋나면 화면이 "다 됐다"고 말하는데 견적에 안 나오는 상태가 된다
    check("게이트 전부 통과 = in_pool", bool(d.get("in_pool")) is (not d.get("gate_blocked")),
          d.get("in_pool"), not d.get("gate_blocked"))

    # 여러 게이트가 동시에 막힌 상품 — 두더지잡기가 실제로 일어나는 경우
    bad = db_one("SELECT product_code FROM products"
                 " WHERE sale_price IS NULL AND stock_qty = 0"
                 "   AND category_group = 'core_part' LIMIT 1")
    if bad is not None:
        b = get(f"/api/admin/products/{bad}")
        blocked = b.get("gate_blocked") or []
        check("여러 개가 막히면 전부 말한다", len(blocked) >= 2, "2개 이상", blocked)
        check("판매가·재고가 막힌 것으로 잡힌다",
              "price" in blocked and "stock" in blocked, "둘 다", blocked)
        # 순서가 의미를 갖는다 — 첫 번째는 게이트 배열 순서상 가장 앞의 미통과 항목
        first_key = [g["key"] for g in b["gate"] if not g["ok"]][0]
        check("먼저 할 일은 목록 순서상 첫 미통과 항목",
              (b.get("gate_first") or {}).get("key") == first_key,
              first_key, (b.get("gate_first") or {}).get("key"))
        check("남은 수와 목록 길이가 일치",
              str(len(blocked)) in (b.get("gate_note") or ""),
              f"{len(blocked)}가지", b.get("gate_note"))
        # 라벨에 가운뎃점이 있으면 항목 구분자와 섞여 개수를 잘못 읽게 된다
        check("게이트 라벨에 항목 구분자가 없다",
              not any(" · " in g["label"] for g in b["gate"]),
              "없음", [g["label"] for g in b["gate"] if " · " in g["label"]])

    # ── 화면 계약 ──
    try:
        pe = io.open(admin_html("product-edit.html"),
                     encoding="utf-8").read()
        check("상세가 게이트 체크리스트를 그린다", "P.gate" in pe, "사용", "없음")
        check("상세가 먼저 할 일을 지목한다", "gate_first" in pe, "사용", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 상세 화면 계약 - {e}")

    # ── 이름 정정 (슬라이스 95) ──
    # '상품 스펙 관리'는 개별 상품 스펙이 아니라 사양 항목(DB 컬럼)을 만드는 화면이었다.
    # 그 이름 때문에 개별 상품 사양을 고치러 온 운영자가 스키마 편집기를 열게 됐다.
    import glob as _g5
    stale = [os.path.basename(x) for x in admin_htmls()
             if not os.path.basename(x).startswith("_")
             and "상품 스펙 관리" in io.open(x, encoding="utf-8").read()]
    check("옛 이름('상품 스펙 관리')이 남지 않았다", not stale, "없음", stale[:4])
    try:
        sf = io.open(admin_html("spec-fields.html"),
                     encoding="utf-8").read()
        check("사양 항목 정의로 이름이 바뀌었다", "사양 항목 정의" in sf, "있음", "없음")
        # 이름을 바꿔도 잘못 오는 사람이 있다 — 갈 곳을 알려준다
        check("개별 상품 사양은 여기가 아니라고 밝힌다",
              "개별 상품의 사양 값을 넣는 곳이 아닙니다" in sf, "안내 있음", "없음")
        check("갈 곳을 링크로 준다",
              'href="products.html"' in sf and 'href="review-queue.html"' in sf,
              "두 링크", "부족")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 사양 항목 정의 화면 - {e}")


def test_setup_status():
    print("\n[23] 운영 시작 체크리스트 — 절차를 문서에서 화면으로 (슬라이스 94)")
    # 절차가 문서에만 있으면 그 문서가 낡아도 아무도 모른다 — 슬라이스 93에서
    # 3단계(공급처)가 실행 불가능한 채로 오래 있었던 것이 그 증거다.
    d = get("/api/admin/setup-status")
    check("운영 시작 상태를 읽는다", isinstance(d, dict) and "steps" in d, "steps 있음", d)
    if not isinstance(d, dict) or "steps" not in d:
        return

    steps = d["steps"]
    check("8단계를 모두 판정한다", len(steps) == 8, 8, len(steps))
    check("단계 번호가 1~8로 이어진다", [s["no"] for s in steps] == list(range(1, 9)),
          list(range(1, 9)), [s["no"] for s in steps])
    check("완료 수 = 실제 done 수",
          d.get("done_count") == len([s for s in steps if s["done"]]),
          len([s for s in steps if s["done"]]), d.get("done_count"))
    check("complete = 미완료가 없을 때만",
          d.get("complete") == all(s["done"] for s in steps),
          all(s["done"] for s in steps), d.get("complete"))
    # 여덟 개를 나열하면 어디부터인지 모른다 — 하나만 지목해야 한다
    todo = [s for s in steps if not s["done"]]
    if todo:
        check("다음 할 일은 미완료 중 첫 단계 하나",
              (d.get("next") or {}).get("no") == todo[0]["no"],
              todo[0]["no"], (d.get("next") or {}).get("no"))
    else:
        check("전부 끝나면 다음 할 일이 없다", d.get("next") is None, None, d.get("next"))

    # 각 단계가 실제로 갈 수 있는 화면을 가리키는가 —
    # 슬라이스 93의 공급처처럼 '문서에는 있는데 화면이 없는' 단계를 막는다
    missing = [s["screen"] for s in steps
               if not os.path.exists(admin_html(s["screen"]))]
    check("모든 단계가 실제 있는 화면을 가리킨다", not missing, "전부 존재", missing)

    # ── 슬롯은 엔진과 같은 정의로 센다 ──
    slot_step = [s for s in steps if s["key"] == "slots"][0]
    check("슬롯 8개를 센다", len(slot_step.get("slots") or []) == 8, 8,
          len(slot_step.get("slots") or []))
    check("빈 슬롯 목록이 실제 0인 슬롯과 일치",
          sorted(slot_step["empty_slots"])
          == sorted([x["label"] for x in slot_step["slots"] if x["count"] == 0]),
          "일치", "불일치")
    check("슬롯 단계 완료 = 빈 슬롯 없음",
          slot_step["done"] == (len(slot_step["empty_slots"]) == 0),
          len(slot_step["empty_slots"]) == 0, slot_step["done"])
    # 쿨러는 공랭·수냉이 한 슬롯이다. part_type으로 세면 AIO 0을 빈 슬롯으로 오판한다.
    cooler = [x for x in slot_step["slots"] if x["key"] == "COOLER"][0]["count"]
    src_cooler = db_one("SELECT COUNT(*) FROM v_recommendation_candidates"
                        " WHERE stock_qty > 0 AND part_type IN"
                        " ('COOLER_CPU_AIR','COOLER_CPU_AIO')")
    if src_cooler is not None:
        check("쿨러 슬롯 = 공랭 + 수냉 (DB 대조)", cooler == src_cooler, src_cooler, cooler)

    # ── 화면 계약 ──
    try:
        idx = io.open(admin_html("index.html"),
                      encoding="utf-8").read()
        check("대시보드에 체크리스트 자리가 있다", 'id="setupHost"' in idx, "있음", "없음")
        check("대시보드가 setup-status를 부른다",
              "/api/admin/setup-status" in idx, "호출", "없음")
        # 완료되면 접힌다 — 끝난 뒤에도 자리를 차지하면 대시보드가 가려진다
        check("완료 시 한 줄로 접는 분기가 있다", "d.complete" in idx, "분기 있음", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 대시보드 계약 - {e}")


def _sup(body, sid=None, method="POST"):
    path = "/api/admin/suppliers" + (f"/{sid}" if sid else "")
    return post_raw(path, json.dumps(body).encode(),
                    {"Content-Type": "application/json"}, method=method)


def test_suppliers():
    print("\n[22] 공급처 — 빈 상태에서 막혀 있던 길 (슬라이스 93)")
    # 배경: `INSERT INTO suppliers`가 개발용 시드에만 있어, 정직하게 빈 DB로 시작하면
    # 공급처를 만들 수단이 아예 없었다 → 매입가 대상 없음 → 판매가 없음 → 후보 0 → 견적 0건.
    d = get("/api/admin/suppliers")
    check("공급처 목록을 읽는다", isinstance(d, dict) and "items" in d, "items 있음", d)
    if not isinstance(d, dict) or "items" not in d:
        return

    # 화면이 세지 않는다 — 빈 상태 판정도 서버가 준다
    check("빈 상태 판정을 서버가 준다",
          d.get("empty") == (d.get("active") == 0), "active==0과 일치", d.get("empty"))
    check("활성 수 = 실제 활성 항목 수",
          d.get("active") == len([i for i in d["items"] if i["status"] == "활성"]),
          d.get("active"), len([i for i in d["items"] if i["status"] == "활성"]))
    check("전체 수 = 항목 수", d.get("total") == len(d["items"]),
          d.get("total"), len(d["items"]))
    src_total = db_one("SELECT COUNT(*) FROM suppliers")
    if src_total is not None:                       # DB와 두 경로 대조
        check("API 전체 수 = DB가 세는 수", d.get("total") == src_total,
              src_total, d.get("total"))

    # ── 상품 상세의 공급처 셀렉트 (2026-08-05 사용자 신고) ──────────────
    # "상품 등록하고 공급처 추가 시 매입가 입력시 오류".
    # 원인 둘이 겹쳐 있었다:
    #   ① 목록 API 는 `id` 로 주는데(슬라이스 93에서 admin_suppliers.py 로 옮기며
    #      키가 바뀌었다) 화면은 `s.supplier_id` 를 읽어 `value="undefined"` →
    #      `+value` 가 NaN → JSON 에서 null → **저장할 때마다 422**.
    #   ② `cost_price` 는 NOT NULL 인데 API 는 None 을 받고 입력창은 "비워 두면
    #      가격 미확인"이라 안내했다 → 비우면 **500**.
    # 그런데 화면이 `if(!res.ok) return;` 으로 실패를 삼켜, 저장을 눌러도 **아무 일도
    # 일어나지 않았다.** 그게 이 버그를 오래 숨겼다.
    if d["items"]:
        check("공급처 목록 항목이 id 를 준다", "id" in d["items"][0],
              "id", sorted(d["items"][0]))
    _pe = io.open(admin_html("product-edit.html"),
                  encoding="utf-8").read()
    # 화면이 목록에서 **서버가 주는 키**를 읽는가
    check("상품 상세가 공급처 id 로 셀렉트를 만든다", "s.id != null" in _pe, True,
          "s.id != null" in _pe)
    # 지킬 수 없는 약속을 다시 적지 않는다
    check("'비워 두면 가격 미확인' 안내가 없다", "비워 두면 가격 미확인" not in _pe,
          True, "비워 두면 가격 미확인" not in _pe)
    # 실패를 삼키지 않는가 — 이 한 줄이 돌아오면 같은 일이 되풀이된다
    # **주석은 봐준다** — 고친 내역을 설명하는 주석까지 잡으면 기록을 못 남긴다.
    # (회귀 [39]에서 이미 한 번 겪은 실수다.) 검사 대상은 실제로 도는 코드다.
    import re as _re15
    _pe_code = _re15.sub(r"(?m)//.*$", "", _re15.sub(r"/\*[\s\S]*?\*/", "", _pe))
    _swallow = _pe_code.count("if(!res.ok) return;")
    # 사양 저장 한 곳은 공용 진행 바가 실패를 말하므로 의도된 것이다(주석에 근거 있음).
    check("공급처 저장 실패를 화면이 삼키지 않는다", _swallow <= 1, "<= 1", _swallow)

    # 서버 가드 — **쓰기는 하지 않는다**(회귀는 정본을 쓰지 않는다, 슬라이스 50).
    _pc = db_one("SELECT product_code FROM products ORDER BY product_code LIMIT 1")
    _sid = d["items"][0]["id"] if d["items"] else None
    if _pc is not None and _sid is not None:
        _J = {"Content-Type": "application/json"}
        st, r = post_raw("/api/admin/products/%s/suppliers" % _pc,
                         json.dumps({"supplier_id": _sid, "cost_price": None}).encode(), _J)
        check("매입가를 비우면 500 이 아니라 400", st == 400, 400, st)
        st, r = post_raw("/api/admin/products/%s/suppliers" % _pc,
                         json.dumps({"supplier_id": _sid, "cost_price": -1}).encode(), _J)
        check("음수 매입가는 400", st == 400, 400, st)
        st, r = post_raw("/api/admin/products/%s/suppliers" % _pc,
                         json.dumps({"supplier_id": 99999999, "cost_price": 1000}).encode(), _J)
        check("없는 공급처는 400", st == 400, 400, st)

    NAME = "회귀검사-공급처-임시"
    # 앞선 실패가 남긴 것이 있으면 먼저 치운다(검사는 멱등이어야 한다)
    db_exec("DELETE FROM admin_operator_activity_logs WHERE target_id = :n", n=NAME)
    db_exec("DELETE FROM suppliers WHERE name = :n", n=NAME)

    st, made = _sup({"name": NAME, "platform": "회귀", "brands": "TEST"})
    check("공급처를 만들 수 있다", st == 200, 200, st)
    sid = (made or {}).get("id")

    # ── 가드 ──
    st2, _ = _sup({"name": "  " + NAME.lower() + "  "})
    check("같은 이름은 대소문자·공백을 무시하고 막는다", st2 == 409, 409, st2)
    check("중복 시도로 행이 늘지 않았다",
          db_one("SELECT COUNT(*) FROM suppliers WHERE lower(btrim(name))=lower(:n)",
                 n=NAME) == 1, 1,
          db_one("SELECT COUNT(*) FROM suppliers WHERE lower(btrim(name))=lower(:n)", n=NAME))
    check("빈 이름은 400", _sup({"name": "   "})[0] == 400, 400, _sup({"name": "  "})[0])
    check("없는 상태값은 400", _sup({"name": NAME + "2", "status": "삭제"})[0] == 400,
          400, _sup({"name": NAME + "3", "status": "삭제"})[0])
    # 모르는 필드를 조용히 무시하면 보낸 쪽이 성공했다고 믿는다(슬라이스 58과 같은 부류)
    check("모르는 필드는 거절한다", _sup({"name": NAME + "4", "supplier_id": 9})[0] == 422,
          422, _sup({"name": NAME + "5", "supplier_id": 9})[0])

    if sid:
        # ── 중지 전에 영향을 먼저 말한다 ──
        im = get(f"/api/admin/suppliers/{sid}/impact")
        check("중지 영향을 미리 알려준다",
              isinstance(im, dict) and "linked_products" in im and im.get("note"),
              "영향+문구", im)
        st3, out = _sup({"name": NAME, "status": "중지"}, sid, "PATCH")
        check("중지는 상태 전이로 한다", st3 == 200
              and db_one("SELECT status FROM suppliers WHERE supplier_id=:i", i=sid) == "중지",
              "중지", db_one("SELECT status FROM suppliers WHERE supplier_id=:i", i=sid))
        # 삭제가 아니라 상태 전이 — 행은 남아 있어야 한다(참조 테이블 6개)
        check("중지해도 행은 남는다",
              db_one("SELECT COUNT(*) FROM suppliers WHERE supplier_id=:i", i=sid) == 1,
              1, db_one("SELECT COUNT(*) FROM suppliers WHERE supplier_id=:i", i=sid))
        check("중지가 활성 수에서 빠진다",
              get("/api/admin/suppliers").get("active")
              == len([i for i in get("/api/admin/suppliers")["items"]
                      if i["status"] == "활성"]), "일치", "불일치")
        check("작업 기록에 남는다",
              (db_one("SELECT COUNT(*) FROM admin_operator_activity_logs"
                      " WHERE action IN ('supplier_create','supplier_update')"
                      " AND target_id = :n", n=NAME) or 0) >= 2, "2건 이상", 0)

    # 검사는 흔적을 남기지 않는다(슬라이스 78)
    db_exec("DELETE FROM admin_operator_activity_logs WHERE target_id = :n", n=NAME)
    db_exec("DELETE FROM suppliers WHERE name LIKE :n", n=NAME + "%")
    check("검사가 만든 공급처를 치웠다",
          db_one("SELECT COUNT(*) FROM suppliers WHERE name LIKE :n", n=NAME + "%") == 0,
          0, db_one("SELECT COUNT(*) FROM suppliers WHERE name LIKE :n", n=NAME + "%"))

    # ── 화면 계약 ──
    import glob as _g4
    # 메뉴는 이제 **화면마다 박혀 있지 않다** — `shared/admin-menu-data.js` 한 곳이
    # 원천이고 `admin-menu.js` 가 그린다(2026-08-05). 예전엔 36화면에 복제돼 있었고
    # 그 복제본이 이미 갈라져서 ai-cost 엔 운영 전환 설정이, policy-weights 엔
    # 용도 하한이 **빠져 있었다**. 그래서 검사도 정본 한 곳을 본다.
    _menu = io.open(os.path.join(ROOT, "mockups", "shared", "admin-menu-data.js"),
                    encoding="utf-8").read()
    check("좌측 메뉴에 공급처가 있다", "'suppliers.html'" in _menu, "메뉴 있음",
          "없음")
    # 화면이 메뉴를 다시 박아 두지 않는가 — 두 벌이 되면 또 갈라진다
    _inline = []
    for _p in admin_htmls():
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        _i = _s.find('id="navbarVerticalNav">')
        if _i < 0:
            continue
        if _s[_i + len('id="navbarVerticalNav">'):].lstrip().startswith("<li"):
            _inline.append(_n)
    check("화면이 메뉴 마크업을 다시 품지 않는다", _inline == [], [], _inline[:4])
    check("공급처 화면 파일이 있다",
          os.path.exists(admin_html("suppliers.html")),
          "있음", "없음")


def _patch_me(body):
    return post_raw("/api/admin/my-profile", json.dumps(body).encode(),
                    {"Content-Type": "application/json"}, method="PATCH")


def test_my_profile():
    print("\n[21] 내 정보 — 자기 것만, 그것도 일부만 고친다 (슬라이스 92)")
    d = get("/api/admin/my-profile")
    check("내 정보를 읽는다", bool(d and d.get("id")), "id 있음", d)
    if not (d and d.get("id")):
        return
    me_id, me_name = d["id"], d["name"]

    # 서버가 무엇을 고칠 수 있는지 알려준다 — 화면이 스스로 정하면 서버와 어긋난다
    check("고칠 수 있는 필드를 서버가 말한다",
          sorted(d.get("editable") or []) == ["duty", "name", "phone"],
          ["duty", "name", "phone"], d.get("editable"))
    # 비밀번호는 어떤 형태로도 응답에 실리지 않는다
    check("응답에 비밀번호가 없다",
          not any("password" in k and k != "has_password"
                  and k != "password_set_at" and k != "must_change_password"
                  for k in d), "해시 없음", [k for k in d if "password" in k])

    # ── 빈 값에 이유를 적는다 (슬라이스 100 · 4/4) ──
    # `—` 하나로 덮으면 **서로 다른 세 사실이 같아 보인다**: 시드가 만든 계정 ·
    # 부트스트랩 자동 승인 · 승인 대기. 판정은 서버가 하고 화면은 받아 적는다 —
    # 화면이 빈 값을 보고 이유를 추측하면 그게 지어낸 근거다(화면 정직성).
    check("로그인 방식은 값이 없어도 이유를 말한다",
          bool(d.get("provider_label")), "빈 문자 아님", d.get("provider_label"))
    check("데이터 필드에 표시용 '—'를 담지 않는다",
          d.get("provider") != "—", "원본 값 또는 null", d.get("provider"))
    # dev 어댑터는 `"@" in email`만 본다 — 이 관계는 실 OAuth가 붙어도 참이다.
    check("dev 어댑터를 검증됐다고 말하지 않는다",
          not (d.get("provider") == "dev" and d.get("provider_verified")),
          "dev면 verified 거짓", d.get("provider_verified"))
    check("검증되지 않았다면 그 사실을 문장으로 말한다",
          bool(d.get("provider_note")) or bool(d.get("provider_verified")),
          "note 있음", d.get("provider_note"))

    _ap = db_all("SELECT approved_at, approved_by, status FROM admin_operators"
                 " WHERE operator_id = :i", i=me_id)
    if not _ap:
        print("  [SKIP] (I) 승인 이유 = DB 실측 — DB 미연결")
    else:
        has_at = _ap[0]["approved_at"] is not None
        check("승인 시각의 유무를 서버와 DB가 같이 본다",
              bool(d.get("approved_at")) == has_at, has_at, bool(d.get("approved_at")))
        # 유무와 이유는 **배타**다. 둘 다 비면 화면에 남는 것은 `—` 하나뿐이다.
        check("승인 시각이 없으면 왜 없는지 말한다",
              bool(d.get("approved_none_reason")) == (not has_at),
              not has_at, bool(d.get("approved_none_reason")))
        check("승인 시각이 있으면 누가 승인했는지 말한다",
              bool(d.get("approved_note")) == has_at, has_at, bool(d.get("approved_note")))
        check("승인자와 부재 이유를 동시에 말하지 않는다",
              not (d.get("approved_note") and d.get("approved_none_reason")), "하나만",
              [d.get("approved_note"), d.get("approved_none_reason")])
        if has_at and _ap[0]["approved_by"] is None:
            # 사람이 승인한 것처럼 보이게 두지 않는다 — 승인 게이트의 의미가 흐려진다.
            check("부트스트랩 자동 승인임을 밝힌다",
                  "부트스트랩" in (d.get("approved_note") or ""),
                  "부트스트랩 언급", d.get("approved_note"))

    # 내 세션은 계정 하나뿐이라 HTTP로는 한 분기만 지나간다. 나머지 분기는 **판정 함수를
    # 직접** 검사한다 — 부작용이 없는 순수 함수이고, 로그인을 더 만들면 세션 잔재가 남는다
    # (슬라이스 78: 검증이 흔적을 남긴다).
    from api.admin_profile import identity_reasons as _ir
    _CASES = (
        ("시드 계정", dict(provider=None, approved_at=None, approved_by=None,
                        status="활성", approver=None), "시드", None),
        ("부트스트랩 자동 승인", dict(provider="dev", approved_at="X", approved_by=None,
                             status="활성", approver=None), None, "부트스트랩"),
        ("사람이 승인", dict(provider="dev", approved_at="X", approved_by=4,
                        status="활성", approver="홍길동"), None, "홍길동"),
        ("승인자 계정이 지워짐", dict(provider="dev", approved_at="X", approved_by=4,
                            status="활성", approver=None), None, "남아 있지 않아"),
        ("승인 대기", dict(provider="dev", approved_at=None, approved_by=None,
                       status="대기", approver=None), "대기", None),
        ("승인 전 정지", dict(provider="google", approved_at=None, approved_by=None,
                         status="정지", approver=None), "정지", None),
    )
    for _why, _row, _want_none, _want_note in _CASES:
        _d = _ir(_row)
        # 배타 — 둘 다 비면 화면에 남는 것은 `—` 하나뿐이고, 셋이 같아 보인다.
        check(f"이유가 정확히 하나다({_why})",
              bool(_d["approved_note"]) != bool(_d["approved_none_reason"]),
              "하나만", [_d["approved_note"], _d["approved_none_reason"]])
        if _want_none:
            check(f"부재 이유가 사실을 가리킨다({_why})",
                  _want_none in (_d["approved_none_reason"] or ""),
                  _want_none, _d["approved_none_reason"])
        if _want_note:
            check(f"승인 경위를 밝힌다({_why})",
                  _want_note in (_d["approved_note"] or ""),
                  _want_note, _d["approved_note"])
        check(f"로그인 방식에 빈 값이 없다({_why})",
              bool(_d["provider_label"]) and bool(_d["provider_note"]),
              "label·note 있음", [_d["provider_label"], _d["provider_note"]])
    # 실 OAuth가 붙기 전에는 어떤 제공자도 검증되지 않는다 — 'google'이라 적혀 있어도
    # 클라이언트가 보낸 값일 뿐이다(auth.py는 provider를 본문에서 그대로 받는다).
    check("검증하지 않은 제공자를 검증됐다고 말하지 않는다",
          not any(_ir(dict(provider=p, approved_at="X", approved_by=1, status="활성",
                           approver="x"))["provider_verified"]
                  for p in ("dev", "google", "kakao", None)),
          "전부 verified 거짓", "검증됐다고 말하는 제공자가 있다")

    _pp = io.open(os.path.join(ROOT, "mockups", "admin", "my-profile.html"),
                  encoding="utf-8").read()
    check("화면이 서버가 준 이유를 쓴다",
          "provider_label" in _pp and "approved_none_reason" in _pp,
          "두 필드 사용", [f for f in ("provider_label", "approved_none_reason")
                        if f not in _pp])
    check("화면이 로그인 방식을 원본 값으로 적지 않는다",
          "dash(d.provider)" not in _pp, "provider_label 사용", "dash(d.provider) 잔존")

    # ── 권한 상승 차단 ── 등급이 아니라 필드가 막는다
    role_before = db_one("SELECT role FROM admin_operators WHERE operator_id=:i", i=me_id)
    st2, _ = _patch_me({"name": me_name, "role": "owner"})
    check("권한을 함께 보내면 거절한다(조용히 무시하지 않는다)",
          st2 in (400, 422), "400/422", st2)
    check("거절된 요청이 권한을 바꾸지 않았다",
          db_one("SELECT role FROM admin_operators WHERE operator_id=:i", i=me_id)
          == role_before, role_before,
          db_one("SELECT role FROM admin_operators WHERE operator_id=:i", i=me_id))

    email_before = db_one("SELECT email FROM admin_operators WHERE operator_id=:i", i=me_id)
    st3, _ = _patch_me({"name": me_name, "email": "hijack@example.com"})
    check("이메일을 함께 보내면 거절한다", st3 in (400, 422), "400/422", st3)
    check("거절된 요청이 이메일을 바꾸지 않았다",
          db_one("SELECT email FROM admin_operators WHERE operator_id=:i", i=me_id)
          == email_before, email_before,
          db_one("SELECT email FROM admin_operators WHERE operator_id=:i", i=me_id))

    st4, _ = _patch_me({"name": "   "})
    check("빈 이름은 거절한다", st4 == 400, 400, st4)
    check("이름은 여전히 그대로다",
          db_one("SELECT name FROM admin_operators WHERE operator_id=:i", i=me_id)
          == me_name, me_name,
          db_one("SELECT name FROM admin_operators WHERE operator_id=:i", i=me_id))

    # ── 왕복: 고쳤다가 되돌린다 ──
    # 검사는 흔적을 남기지 않는다(슬라이스 78). 직무를 잠시 바꿨다가 반드시 복구한다.
    duty_before = db_one("SELECT duty FROM admin_operators WHERE operator_id=:i", i=me_id)
    probe = "회귀검사-임시"
    st5, d5 = _patch_me({"name": me_name, "duty": probe})
    check("직무를 고칠 수 있다", st5 == 200, 200, st5)
    check("고친 값이 DB에 남는다",
          db_one("SELECT duty FROM admin_operators WHERE operator_id=:i", i=me_id) == probe,
          probe, db_one("SELECT duty FROM admin_operators WHERE operator_id=:i", i=me_id))
    check("무엇이 바뀌었는지 응답이 말한다",
          "duty" in (d5 or {}).get("changed", {}), "duty 포함", (d5 or {}).get("changed"))
    # 원장에 남는가 — 쓰기는 작업 기록을 남긴다(원장 규약)
    check("작업 기록에 남는다",
          (db_one("SELECT COUNT(*) FROM admin_operator_activity_logs"
                  " WHERE action='operator_self_update' AND operator_id=:i", i=me_id) or 0) > 0,
          "1건 이상", 0)

    # 같은 값을 다시 보내면 원장을 늘리지 않는다 — '고쳤다'는 거짓 기록이 된다
    n_before = db_one("SELECT COUNT(*) FROM admin_operator_activity_logs"
                      " WHERE action='operator_self_update' AND operator_id=:i", i=me_id)
    _patch_me({"name": me_name, "duty": probe})
    check("바뀐 게 없으면 기록을 남기지 않는다",
          db_one("SELECT COUNT(*) FROM admin_operator_activity_logs"
                 " WHERE action='operator_self_update' AND operator_id=:i", i=me_id)
          == n_before, n_before,
          db_one("SELECT COUNT(*) FROM admin_operator_activity_logs"
                 " WHERE action='operator_self_update' AND operator_id=:i", i=me_id))

    # 복구 — 검사가 흔적을 남기지 않는다
    _patch_me({"name": me_name, "duty": duty_before})
    check("검사가 원래 값을 되돌려 놓았다",
          db_one("SELECT duty FROM admin_operators WHERE operator_id=:i", i=me_id)
          == duty_before, duty_before,
          db_one("SELECT duty FROM admin_operators WHERE operator_id=:i", i=me_id))

    # ── 화면 계약 ── 프로필 메뉴가 없는 곳을 가리키지 않는다
    import glob as _g3
    dead = []
    for _p in admin_htmls():
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        for ln in io.open(_p, encoding="utf-8").read().split("\n"):
            if 'href="#!"' in ln and ("내 정보" in ln or "대시보드" in ln):
                dead.append(_n + ": " + ("내 정보" if "내 정보" in ln else "대시보드"))
    check("프로필 메뉴에 죽은 링크가 없다", not dead, "없음", dead[:4])
    check("내 정보 화면 파일이 있다",
          os.path.exists(os.path.join(ROOT, "mockups", "admin", "my-profile.html")),
          "있음", "없음")


def test_usage_floor_admin():
    print("\n[19] 용도 하한 관리 — 값을 고칠 화면이 있는가 (슬라이스 75)")
    # 하한은 슬라이스 58에서 만들었지만 **고칠 화면이 없었다.** 값은 실측으로 정한
    # 그대로였고 운영자는 그게 무엇인지도 볼 수 없었다.
    d = get("/api/admin/usage-floors")
    check("용도별 하한을 준다", bool(d.get("groups")), "1개 이상", len(d.get("groups") or []))
    items = [i for g in (d.get("groups") or []) for i in g["items"]]
    check("각 하한이 실측 통과 수를 함께 준다",
          all(i.get("pass_count") is not None and i.get("slot_total") is not None
              for i in items), "전부 있음",
          [i["floor_id"] for i in items if i.get("pass_count") is None])
    # 화면이 세지 않는다 — 서버가 센 수와 DB가 센 수가 같아야 한다
    gpu = next((i for i in items if i["field"] == "required_power_watt"), None)
    if gpu:
        real = db_one("SELECT count(*) FROM v_recommendation_candidates"
                      " WHERE stock_qty>0 AND part_type='GPU'"
                      "   AND required_power_watt >= :v", v=gpu["value"])
        check("통과 수가 DB 실집계와 같다", gpu["pass_count"] == real, real,
              gpu["pass_count"])

    fid = items[0]["floor_id"] if items else None
    if fid:
        was = items[0]["value"]
        # 미리보기는 DB를 바꾸지 않아야 한다 — 바꾸면 '확인 후 적용'이 거짓말이 된다
        st, pv = post(f"/api/admin/usage-floors/{fid}", {"value": was + 200, "preview": True})
        check("미리보기가 영향을 준다",
              st == 200 and (pv or {}).get("impact", {}).get("pass_after") is not None,
              200, st)
        check("미리보기는 DB를 바꾸지 않는다",
              db_one("SELECT value FROM usage_floors WHERE floor_id=:i", i=fid) == was,
              was, db_one("SELECT value FROM usage_floors WHERE floor_id=:i", i=fid))
        check("음수 하한은 400",
              post(f"/api/admin/usage-floors/{fid}", {"value": -1})[0] == 400, 400,
              post(f"/api/admin/usage-floors/{fid}", {"value": -1})[0])
        check("없는 하한은 404",
              post("/api/admin/usage-floors/99999", {"value": 100})[0] == 404, 404,
              post("/api/admin/usage-floors/99999", {"value": 100})[0])

        # 바꾸면 **견적에 즉시 반영**되어야 한다(캐시를 비우지 않으면 옛 값이 남는다)
        st2, _ = post(f"/api/admin/usage-floors/{fid}", {"value": was + 50})
        if st2 == 200:
            _s, q = post("/api/recommend", {"mode": "chat", "constraints": [
                {"l": "예산", "v": "120만원"}, {"l": "용도", "v": "고사양 게임"}]})
            got = {i["slot"]: i["value"] for i in
                   ((q or {}).get("usage_floors") or {}).get("items") or []}
            check("바꾼 하한이 견적에 바로 반영된다",
                  got.get(items[0]["slot"]) == was + 50, was + 50,
                  got.get(items[0]["slot"]))
            post(f"/api/admin/usage-floors/{fid}", {"value": was})     # 원복
            check("원복된다",
                  db_one("SELECT value FROM usage_floors WHERE floor_id=:i", i=fid) == was,
                  was, db_one("SELECT value FROM usage_floors WHERE floor_id=:i", i=fid))

    try:
        uf = io.open(admin_html("usage-floors.html"),
                     encoding="utf-8").read()
        check("하한 화면이 미리보기를 거친다", "preview: true" in uf.replace('"', "'")
              or "preview:true" in uf.replace(" ", ""), "preview 호출", "없음")
        idx = io.open(os.path.join(ROOT, "mockups", "shared", "admin-menu-data.js"),
                      encoding="utf-8").read()
        check("메뉴에 용도 하한이 있다", "'usage-floors.html'" in idx,
              "메뉴 있음", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 하한 화면 — {e}")


def test_screen_identity():
    print("\n[20] 화면 식별자 — 마크업 계약 (슬라이스 78)")
    # 계약은 "최상위에 data-screen-id, data-domain"인데 32개 중 2개만 지키고 있었다.
    # 화면 ID는 이미 배지로 보이므로 그 값을 body로 옮겼다.
    import glob as _g
    import re as _re
    pages = [p for p in admin_htmls()
             if not os.path.basename(p).startswith("_")]
    miss_sid, miss_dom, seen = [], [], {}
    for p in pages:
        n = os.path.basename(p)
        t = io.open(p, encoding="utf-8").read()
        m = _re.search(r'data-screen-id="([^"]+)"', t)
        d = _re.search(r'data-domain="([^"]+)"', t)
        if not m:
            miss_sid.append(n)
        else:
            seen.setdefault(m.group(1), []).append(n)
        if not d:
            miss_dom.append(n)
    check("모든 관리자 화면에 data-screen-id가 있다", not miss_sid, "누락 없음", miss_sid)
    check("모든 관리자 화면에 data-domain이 있다", not miss_dom, "누락 없음", miss_dom)
    # 같은 ID를 두 화면이 쓰면 화면을 특정할 수 없다 — 실제로 충돌이 있었다
    # (용도 하한이 추천 가능 재고 현황의 ADM-ENG-030을 쓰고 있었다)
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    check("화면 ID가 중복되지 않는다", not dup, "중복 없음", dup)


def test_margin_policy():
    print("\n[18] 마진 정책 — 고치면 실제로 저장되는가 (슬라이스 74)")
    # "수정해도 변경이 안 된다"는 보고. 확인해 보니 저장 기능이 아예 없었다 —
    # 화면은 SCREEN='margin'인데 그 분기가 없어 표가 마크업 더미였고 쓰기 API도 없었다.
    d = get("/api/admin/engine-rules")
    p = d.get("pricing") or {}
    check("현재 가격 정책을 서버가 준다",
          p.get("card_fee_pct") is not None and p.get("margin_pct") is not None,
          "수수료·마진 있음", sorted(p))
    fee0 = db_one("SELECT card_fee_rate FROM pricing_settings"
                  " ORDER BY effective_from DESC LIMIT 1")
    n0 = db_one("SELECT count(*) FROM pricing_settings")
    # **검사가 만든 행만** 지우기 위해 기준점을 잡는다(아래 정리 참조).
    # 예전에는 min(setting_id)를 기준으로 그 위를 전부 지웠다 — 그러면 운영자가 정한
    # 정책까지 사라진다. 실제로 마진 12%를 저장한 직후 이 검사가 그것을 지울 상태였다.
    max0 = db_one("SELECT max(setting_id) FROM pricing_settings")
    log0 = db_one("SELECT COALESCE(max(log_id), 0) FROM admin_operator_activity_logs"
                  " WHERE action = 'pricing_settings'")

    # 같은 값을 다시 넣으면 이력이 쌓이지 않아야 한다(부동소수점 비교가 헐거우면 쌓인다)
    st, _ = post("/api/admin/pricing-settings",
                 {"card_fee_rate": float(fee0), "margin_rate": float(
                     db_one("SELECT margin_rate FROM pricing_settings"
                            " ORDER BY effective_from DESC LIMIT 1"))})
    check("같은 값 재저장은 400", st == 400, 400, st)
    check("거부됐으면 이력이 늘지 않는다",
          db_one("SELECT count(*) FROM pricing_settings") == n0, n0,
          db_one("SELECT count(*) FROM pricing_settings"))

    # 비율은 0~1이다. 13을 넣으면 1300%가 되어 가격이 폭주한다.
    for bad in (1.5, -0.1):
        st2, _ = post("/api/admin/pricing-settings",
                      {"card_fee_rate": bad, "margin_rate": 0.1})
        check(f"범위 밖({bad})은 400", st2 == 400, 400, st2)

    st3, ap = post("/api/admin/pricing-settings",
                   {"card_fee_rate": 0.022, "margin_rate": 0.135})
    check("정책 변경 저장", st3 == 200, 200, st3)
    if st3 == 200:
        # pricing_settings는 이력 테이블 — 고치는 게 아니라 새 행을 넣는다
        check("새 버전으로 쌓인다(덮어쓰지 않는다)",
              db_one("SELECT count(*) FROM pricing_settings") == n0 + 1, n0 + 1,
              db_one("SELECT count(*) FROM pricing_settings"))
        # 바꿔도 기존 판매가는 움직이지 않는다 — 그 사실을 응답이 말해야 한다
        check("기존 판매가가 안 바뀐다는 것을 알린다",
              "바뀌지 않습니다" in (ap.get("note") or ""), "안내 있음", ap.get("note"))
    # 검증으로 만든 것만 지운다 — 회귀가 정본을 바꾸면 안 된다(슬라이스 50 원칙).
    #
    # 예전 코드는 `setting_id > min(setting_id)`로 지웠다. 정책 이력이 1건뿐일 때는
    # 우연히 맞았지만, **운영자가 마진을 정하는 순간부터 그 정책을 지운다.**
    # 실제로 2026-07-30 마진 12%를 저장한 직후 이 검사가 그것을 삭제할 상태였고,
    # 앞선 실행이 남긴 로그(#2107 "0% -> 13.5%")는 행 없이 로그만 남아
    # **원장이 거짓을 말하는 상태**를 만들었다.
    #
    # 그래서 두 가지를 바꿨다:
    #   ① 기준을 max0으로 — 검사 시작 시점보다 뒤에 생긴 행만 지운다
    #   ② 로그도 함께 지운다 — 행만 지우면 작업 기록이 없는 변경을 말하게 된다
    if _engine is not None and max0 is not None:
        with _engine.begin() as c:
            c.execute(text(
                "DELETE FROM admin_operator_activity_logs"
                " WHERE action = 'pricing_settings' AND log_id > :lg"),
                {"lg": log0 or 0})
            c.execute(text("DELETE FROM pricing_settings WHERE setting_id > :i"),
                      {"i": max0})
    check("검증 후 정책 이력이 원래대로", db_one("SELECT count(*) FROM pricing_settings") == n0,
          n0, db_one("SELECT count(*) FROM pricing_settings"))
    check("검증 후 최신 정책이 그대로",
          db_one("SELECT max(setting_id) FROM pricing_settings") == max0,
          max0, db_one("SELECT max(setting_id) FROM pricing_settings"))
    # 행 없는 정책 로그가 남아 있으면 원장이 거짓을 말한다
    check("정책 로그 수 = 정책 행이 설명되는 범위",
          (db_one("SELECT count(*) FROM admin_operator_activity_logs"
                  " WHERE action='pricing_settings' AND log_id > :lg", lg=log0 or 0) or 0) == 0,
          0, db_one("SELECT count(*) FROM admin_operator_activity_logs"
                    " WHERE action='pricing_settings' AND log_id > :lg", lg=log0 or 0))

    try:
        mp = io.open(admin_html("margin-policy.html"),
                     encoding="utf-8").read()
        check("마진 화면에 margin 분기가 있다", 'SCREEN === "margin"' in mp,
              "분기 있음", "없음")
        check("마진 화면이 저장을 호출한다", "/api/admin/pricing-settings" in mp,
              "저장 호출", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 마진 화면 — {e}")


def test_part_type_change():
    print("\n[16] 분류 변경 — 바꾸기 전에 영향을 먼저 말한다 (슬라이스 67)")
    # 규약은 "상세에서 분류는 고치지 않는다"였다. 그런데 적재가 잘못 넣은 분류를
    # 바로잡을 길이 없어 그 상품들이 영영 추천에서 빠졌다. 열되, 눈 감고 바꾸게 하지
    # 않는다 — 분류가 바뀌면 필수 사양이 통째로 바뀌고 추천 슬롯도 달라진다.
    #
    # ⚠ 정본(data_origin='real') 상품을 쓴다 — data_origin='demo' 필터는 «측정 후»
    # 넣지 않기로 했다(2026-08-15, 46158 사고 조사 후속). 실측: 이 조건(part_type='ETC'
    # AND status='판매중')을 만족하는 데모 상품이 **0건**이다 — 데모 ETC 상품 6건이
    # 전부 '품절'이다. 필터를 걸면 이 검사는 매번 조용히 SKIP되는데, 그건 정본을
    # 건드리는 것보다 나쁘다(아무것도 검증하지 않으면서 통과한 것처럼 보인다) — 그래서
    # 필터는 걸지 않고 DBA에게 데모 표본(ETC · 판매중)을 보고한다. 대신 위험 구간을
    # 줄인다: 적용 → 가드 확인 → 되돌리기를 try/finally로 감싸 그 사이 무엇이 터져도
    # 되돌리기가 반드시 시도되게 하고, 되돌린 뒤 DB로 직접 재확인한다(test_stock_ledger와
    # 같은 결 — 46158은 이 보장 없이 8일 방치됐다).
    # + C안(하네스 판단, 2026-08-15): 지난 회차 대상이 지금도 건강한지 먼저 본다 —
    # try/finally도 못 도는 잔여 위험(서버가 죽는 등, 오늘 밤 세 번 실재 — T-05)의
    # 유일한 방어다. 이 함수가 «가장» 필요하다 — demo 필터를 못 넣어 정본을 계속 쓴다.
    _selftest_no_orphan(
        "last_target_part_type_change",
        "SELECT 1 FROM products WHERE product_code=:p AND part_type='ETC'"
        " AND status='판매중'",
        "SELECT part_type, status, locked_fields FROM products WHERE product_code=:p")
    pc = db_one("SELECT product_code FROM products WHERE part_type='ETC'"
                " AND status='판매중' ORDER BY product_code LIMIT 1")
    if pc is None:
        print("  [SKIP] (I) 분류 변경 — 대상 없음")
        return
    _selftest_remember("last_target_part_type_change", pc)
    was = db_one("SELECT part_type FROM products WHERE product_code=:p", p=pc)
    locked_before = db_one("SELECT locked_fields FROM products WHERE product_code=:p", p=pc)
    pool0 = db_one("SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty>0")

    st, prev = post(f"/api/admin/products/{pc}/part-type",
                    {"part_type": "CASE", "preview": True})
    check("미리보기가 영향을 준다", st == 200 and bool(prev and prev.get("impact")),
          200, st)
    # 미리보기는 **DB를 바꾸지 않아야 한다** — 바꾸면 '확인 후 적용'이 거짓말이 된다
    check("미리보기는 DB를 바꾸지 않는다",
          db_one("SELECT part_type FROM products WHERE product_code=:p", p=pc) == was,
          was, db_one("SELECT part_type FROM products WHERE product_code=:p", p=pc))
    if prev and prev.get("impact"):
        i = prev["impact"]
        check("영향에 필수 사양 변화가 있다",
              "required_add" in i and "missing_after" in i, "필드 있음", sorted(i))

    # ── 적용 → 되돌리기: try/finally로 감싼다(2026-08-15, 46158 재발 방지) ─────────
    # 원래 이 사이엔 check 4회 + POST 2회가 더 있었다 — 46158에서 정확히 이런 구간의
    # 예외가 undo를 건너뛰게 했다. finally는 그 무엇이 터져도 되돌리기를 반드시 시도한다.
    uid = None
    try:
        st2, ap = post(f"/api/admin/products/{pc}/part-type", {"part_type": "CASE"})
        check("분류 변경 적용", st2 == 200, 200, st2)
        if st2 == 200:
            uid = (ap or {}).get("undo_id")
            check("products와 product_specs의 분류가 같다",
                  db_one("SELECT part_type FROM products WHERE product_code=:p", p=pc)
                  == (db_one("SELECT part_type FROM product_specs WHERE product_code=:p", p=pc)
                      or "CASE"),
                  "일치", "다름")
            check("같은 분류로 또 바꾸면 400",
                  post(f"/api/admin/products/{pc}/part-type", {"part_type": "CASE"})[0] == 400,
                  400, post(f"/api/admin/products/{pc}/part-type", {"part_type": "CASE"})[0])
            check("없는 분류는 400",
                  post(f"/api/admin/products/{pc}/part-type", {"part_type": "ZZZ"})[0] == 400,
                  400, post(f"/api/admin/products/{pc}/part-type", {"part_type": "ZZZ"})[0])
            # ── 잠금 확대(2026-08-16) — ㉢ change_part_type이 잠금을 걸어야 다음
            # 재적재가 이 분류·게이트 판정을 되돌리지 못한다(0031/123034 실사고와 같은
            # 모양). 응답과 DB를 둘 다 본다 — 응답만 보면 "말은 그런데 실제로는 안
            # 걸림"을 놓친다.
            want_locked = {"part_type", "category_group", "ai_candidate_yn",
                           "review_required_yn"}
            check("분류 변경이 응답에서 4개 필드를 잠갔다고 밝힌다",
                  want_locked <= set((ap or {}).get("locked_fields") or []),
                  sorted(want_locked), (ap or {}).get("locked_fields"))
            locked_after_apply = db_one(
                "SELECT locked_fields FROM products WHERE product_code=:p", p=pc)
            check("분류 변경이 DB에 실제로 4개 필드를 잠갔다(DB 직접 재확인)",
                  want_locked <= set(locked_after_apply or []),
                  sorted(want_locked), locked_after_apply)
    finally:
        if uid is not None:
            try:
                st3, _ = post(f"/api/admin/products/part-type/undo/{uid}")
            except Exception as e:                           # noqa: BLE001
                check("분류 변경 되돌리기(예외 없이 응답한다)", False, "정상 응답", repr(e))
                st3 = None
            else:
                check("분류 변경 되돌리기(try 중 예외가 나도 finally에서 반드시 시도)",
                      st3 == 200, 200, st3)
            # DB로 직접 재확인 — undo 응답이 200이라 말해도 실제로 안 바뀌었을 수 있다
            now_pt = db_one("SELECT part_type FROM products WHERE product_code=:p", p=pc)
            check("분류가 원복된다(DB 직접 재확인)", now_pt == was, was, now_pt)
            now_pool = db_one("SELECT count(*) FROM v_recommendation_candidates"
                              " WHERE stock_qty>0")
            check("되돌린 뒤 추천 풀이 제자리(DB 직접 재확인)", now_pool == pool0, pool0, now_pool)
            # 잠금도 원복돼야 한다 — 값만 되돌리고 잠금이 남으면 적재가 영영 못 채운다
            # (CLAUDE.md §관리자 화면 규약, 슬라이스 53의 되돌리기 원칙과 동일).
            now_locked = db_one(
                "SELECT locked_fields FROM products WHERE product_code=:p", p=pc)
            check("분류 변경 되돌리기가 잠금도 원복한다(DB 직접 재확인)",
                  now_locked == locked_before, locked_before, now_locked)
            if st3 == 200:
                st4, _ = post(f"/api/admin/products/part-type/undo/{uid}")
                check("이중 되돌리기는 409", st4 == 409, 409, st4)

    # ── 중복 등록 확인 (슬라이스 68) ────────────────────────────────
    # 기존 danawa.title_similarity는 이 용도에 못 쓴다: 모델명 토큰이 겹치면 점수를
    # 끌어올려 MP600 PRO NH와 XT를 1.000으로 본다. 중복 판정은 **다른 점을 지우지
    # 않아야** 한다. 임계값은 실카탈로그 3,889쌍 실측으로 0.97(상위 6.5%).
    try:
        sys.path.insert(0, ROOT)
        from api import dedupe
        cases = [
            ("커세어 CORSAIR MP600 PRO NH M.2 NVMe (8TB)",
             "커세어 CORSAIR MP600 PRO XT M.2 NVMe (8TB)", False),
            ("갤럭시 BOY 지포스 RTX 3050 EX BLACK D6 6GB DVI",
             "갤럭시 BOY 지포스 RTX 3050 EX OC D6 8GB", False),
            ("중고 삼성전자 970 EVO M.2 2280 (250GB)",
             "삼성전자 970 EVO M.2 2280 (250GB) 정품", True),
        ]
        bad = []
        for a, b, want in cases:
            got = dedupe.score(a, b) >= dedupe.SIMILAR_THRESHOLD
            if got != want:
                bad.append(f"{a[:24]} vs {b[:24]}: {dedupe.score(a, b)}")
        check("중복 판정이 다른 상품을 같다고 하지 않는다", not bad, "전 케이스 일치", bad)
        check("수치가 다르면 점수를 깎는다",
              dedupe.score("RTX 3050 D6 6GB", "RTX 3050 D6 8GB") < 0.8,
              "< 0.8", dedupe.score("RTX 3050 D6 6GB", "RTX 3050 D6 8GB"))
    except Exception as e:                               # noqa: BLE001
        print(f"  [SKIP] (I) 중복 판정 — {e}")

    name = db_one("SELECT product_name FROM products WHERE part_type='GPU'"
                  " ORDER BY product_code LIMIT 1")
    if name:
        n0 = db_one("SELECT count(*) FROM products")
        st, d = post("/api/admin/products", {"name": name, "part_label": "그래픽카드"})
        check("같은 이름 등록은 409로 되묻는다", st == 409, 409, st)
        # **되물었으면 등록되지 않아야 한다** — 물어보고 만들어버리면 확인이 무의미하다
        check("되묻는 동안 등록되지 않는다", db_one("SELECT count(*) FROM products") == n0,
              n0, db_one("SELECT count(*) FROM products"))
        if st == 409 and isinstance(d.get("detail"), dict):
            check("닮은 상품 목록을 함께 준다", bool(d["detail"].get("items")),
                  "1개 이상", len(d["detail"].get("items") or []))
        sim = get("/api/admin/product-similar?name="
                  + urllib.parse.quote(name) + "&part_type=GPU")
        check("유사 조회와 등록이 같은 잣대를 쓴다",
              bool(sim.get("items")) and sim.get("threshold") == 0.97,
              "0.97 · 결과 있음", sim.get("threshold"))

    # ── 중복 편입·삭제 (슬라이스 69) ────────────────────────────────
    # 삭제는 마지막 수단이다. products를 참조하는 테이블이 15개고, 주문에 걸린 상품을
    # 지우면 **과거 주문서가 깨진다**(실측 33종). 그래서 편입을 먼저 권하고,
    # 주문 이력이 있으면 삭제를 거부한다.
    ordered = db_one("SELECT product_code FROM order_items"
                     " WHERE product_code IS NOT NULL LIMIT 1")
    if ordered:
        st, d = post_raw(f"/api/admin/products/{ordered}", b"", {}, method="DELETE")
        check("주문 이력이 있는 상품은 삭제 거부", st == 409, 409, st)
        if st == 409 and isinstance((d or {}).get("detail"), dict):
            check("거부 사유를 밝힌다",
                  (d["detail"].get("error") == "has_history"), "has_history",
                  d["detail"].get("error"))
        # 거부했으면 **정말로 남아 있어야** 한다
        check("거부된 상품이 그대로 있다",
              db_one("SELECT count(*) FROM products WHERE product_code=:p",
                     p=ordered) == 1, 1,
              db_one("SELECT count(*) FROM products WHERE product_code=:p", p=ordered))
    # 편입 가드 — 자기 자신과는 합칠 수 없다
    any_pc = db_one("SELECT product_code FROM products ORDER BY product_code LIMIT 1")
    if any_pc:
        st2, _ = post(f"/api/admin/products/{any_pc}/merge", {"into": any_pc})
        check("자기 자신과 편입은 400", st2 == 400, 400, st2)
        st3, _ = post(f"/api/admin/products/{any_pc}/merge", {"into": 99999999})
        check("없는 상품으로 편입은 404", st3 == 404, 404, st3)
        # 미리보기는 DB를 바꾸지 않아야 한다
        other = db_one("SELECT product_code FROM products WHERE product_code<>:p"
                       " ORDER BY product_code LIMIT 1", p=any_pc)
        if other:
            was = db_one("SELECT status FROM products WHERE product_code=:p", p=any_pc)
            post(f"/api/admin/products/{any_pc}/merge",
                 {"into": other, "preview": True})
            check("편입 미리보기는 DB를 바꾸지 않는다",
                  db_one("SELECT status FROM products WHERE product_code=:p",
                         p=any_pc) == was, was,
                  db_one("SELECT status FROM products WHERE product_code=:p", p=any_pc))

    # 공급처 매입가 — 표가 마크업 하드코딩이라 신규 등록 화면에도 남의 값이 떴다
    sup = get("/api/admin/suppliers")
    check("공급처 선택지를 서버가 준다", bool(sup.get("items")), "1개 이상",
          len(sup.get("items") or []))
    try:
        pe = io.open(admin_html("product-edit.html"),
                     encoding="utf-8").read()
        # 공급처 표(tbody#supRows)만 본다 — 상단 알림 더미와 코드 주석까지 잡으면 오탐이다
        i = pe.find('id="supRows"')
        body = pe[i:pe.find("</tbody>", i)] if i >= 0 else ""
        check("공급처 표에 예시 매입가가 없다",
              bool(body) and "원</td>" not in body, "서버 렌더", body[:60])
        check("분류 변경이 미리보기를 거친다", "preview:true" in pe.replace(" ", ""),
              "preview 호출", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 상세 화면 계약 — {e}")


def test_usage_floors():
    print("\n[14] 용도 하한 — 화면이 한 약속을 서버가 지키는가 (슬라이스 58)")
    # 화면은 오래전부터 "저사양 GPU 제외(프레임 미달)"라고 적어 왔는데 서버는 용도로
    # 아무것도 하지 않았다. 그 결과 '고사양 게임'에 GT710 2GB가 나왔다.
    C = [{"l": "예산", "v": "120만원"}, {"l": "용도", "v": "고사양 게임"}]
    _st, d = post("/api/recommend", {"mode": "chat", "constraints": C})
    d = d or {}

    fl = (d.get("usage_floors") or {}).get("items") or []
    check("용도 하한을 응답이 밝힌다", bool(fl), "1개 이상", len(fl))
    floors = {f["slot"]: f["value"] for f in fl}

    # ① 모든 티어의 부품이 하한을 실제로 만족하는가 — 이것이 이 슬라이스의 계약이다
    for tier, s in (d.get("sets") or {}).items():
        if not s:
            continue
        for it in s["items"]:
            need = floors.get(it["part_type"])
            if need is None:
                continue
            got = db_one(
                "SELECT CASE WHEN :pt='GPU' THEN required_power_watt ELSE capacity_gb END"
                " FROM v_recommendation_candidates WHERE product_code=:pc",
                pt=it["part_type"], pc=it["product_code"])
            check(f"{tier}·{it['part_type']}가 용도 하한을 만족", got is not None and got >= need,
                  f">= {need}", got)

    # ② 하한이 없는 용도는 하한을 만들어내지 않는다(지어내기 금지)
    _st2, d2 = post("/api/recommend", {"mode": "chat", "constraints": [
        {"l": "예산", "v": "120만원"}, {"l": "용도", "v": "기타"}]})
    d2 = d2 or {}
    check("정의 없는 용도엔 하한을 지어내지 않는다",
          not ((d2.get("usage_floors") or {}).get("items")), "빈 목록",
          (d2.get("usage_floors") or {}).get("items"))

    # ③ 후보 카운터와 견적이 같은 하한을 쓴다 — 다르면 화면이 딴 말을 하게 된다
    _st3, cnt = post("/api/candidates/count", {"constraints": C})
    cnt = cnt or {"effects": []}
    eff = next((e for e in cnt["effects"] if e["label"] == "용도"), None)
    check("후보 카운터도 용도를 실제로 적용한다", bool(eff and eff["applied"]),
          "applied=True", eff and eff["applied"])

    # ④ 고성능은 예산 무시가 아니라 배수 상한을 받는다 — 램 하나에 예산의 776%를 쓴 전례
    x = d.get("highend_cap_x")
    hi = (d.get("sets") or {}).get("highend")
    if hi and x:
        check("고성능 총액 <= 예산 x 배수", hi["total"] <= 1_200_000 * x,
              f"<= {int(1_200_000 * x):,}", hi["total"])

    # ⑤ 노트북 전용 메모리(SO-DIMM)는 데스크톱 견적에 들어오지 않는다 — 조립 불가 조합
    nb = db_one("SELECT count(*) FROM v_recommendation_candidates c JOIN products p"
                " USING (product_code) WHERE c.part_type='RAM' AND c.stock_qty>0"
                " AND p.spec_source_text ~ 'SO ?DIMM'")
    check("노트북 메모리가 후보 풀에 없다", nb == 0, 0, nb)

    # ⑥ 티어 선택이 화면 왕복에도 유지되는가 (사용자 보고 — S3에서 돌아오면 추천형으로
    # 리셋돼, 고성능형을 고른 줄 알고 누른 [장바구니 담기]가 다른 구성으로 넘어갔다).
    # 마크업 계약이라 브라우저 없이 확인한다: 저장된 선택을 복원하는 코드가 있는가.
    s2 = os.path.join(ROOT, "mockups", "mvp1", "s2-result.html")
    try:
        html = io.open(s2, encoding="utf-8").read()
        check("S2가 저장된 티어를 복원한다",
              "(saved&&Q.sets[saved])?saved" in html.replace(" ", ""),
              "saved 복원 분기", "없음")
        check("S2가 탭 클릭 즉시 티어를 저장한다",
              html.count("popcorn-quote-tier") >= 3, ">= 3회 참조",
              html.count("popcorn-quote-tier"))
        s1 = io.open(os.path.join(ROOT, "mockups", "mvp1", "s1-session.html"),
                     encoding="utf-8").read()
        check("새 견적은 이전 티어 선택을 지운다",
              "removeItem('popcorn-quote-tier')" in s1.replace('"', "'"),
              "removeItem 있음", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 티어 전달 계약 — {e}")

    # ⑦ 숫자 상한이 없는 예산('200만원 이상'·'AI 추천 예산')도 견적이어야 한다.
    # 실제 사고: cap=null을 화면이 toLocaleString()에 넘겨 TypeError로 죽었고,
    # 그 뒤 스크립트가 통째로 멈춰 고른 티어가 저장되지 않았다 — 고성능형을 골라도
    # 장바구니엔 추천형이 담겼다. 화면이 죽는 것보다 나쁜 건 죽은 줄 모르고 결제까지 가는 것.
    _s4, nc = post("/api/recommend", {"mode": "chat", "constraints": [
        {"l": "예산", "v": "AI 추천 예산"}, {"l": "용도", "v": "고사양 게임"}]})
    nc = nc or {}
    hs = (nc.get("sets") or {}).get("highend")
    rs = (nc.get("sets") or {}).get("recommend")
    if hs and rs:
        check("상한 없는 예산에도 고성능이 나온다", hs["budget"]["cap"] is None,
              None, hs["budget"]["cap"])
        # 상한이 없다고 무한정 비싸지면 안 된다 — 추천 구성이 기준선이다
        check("상한 없는 예산의 고성능 <= 추천 x 배수",
              hs["total"] <= rs["total"] * nc.get("highend_cap_x", 1.5),
              f"<= {int(rs['total'] * nc.get('highend_cap_x', 1.5)):,}", hs["total"])
        check("기준선을 근거로 밝힌다",
              any("정하지 않으" in r for r in hs.get("reasons") or []),
              "기준선 문구 있음", hs.get("reasons"))
    # 화면이 cap=null을 무방비로 포맷하지 않는가 (죽으면 그 뒤가 전부 멈춘다)
    try:
        html = io.open(s2, encoding="utf-8").read().replace(" ", "")
        check("S2가 cap=null을 방어한다", "s.budget.cap!=null" in html,
              "null 가드 있음", "없음")
    except OSError:
        pass

    # ⑧ 첫 화면(main-landing·S0)이 말하는 수 — 고객이 가장 먼저 보는 화면이 근거 없는
    # 수를 말하면 "모든 견적에는 이유가 있습니다"가 첫 줄에서 무너진다. 실제로 재고
    # 26,480개(어느 값과도 불일치)·호환성 5종(실제 8종)·RTX 4060 Ti 645,000원
    # (실제 428,000원)을 말하고 있었고, 두 화면 다 API를 한 번도 부르지 않았다.
    sc = get("/api/showcase")
    check("showcase 후보 수 = S1 카운터와 같은 정의",
          sc["pool"] == db_one("SELECT count(*) FROM v_recommendation_candidates"
                               " WHERE stock_qty>0"),
          db_one("SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty>0"),
          sc["pool"])
    check("showcase 규칙 수 = 활성 호환 규칙",
          sc["rules"] == db_one("SELECT count(*) FROM compat_rules WHERE active"),
          db_one("SELECT count(*) FROM compat_rules WHERE active"), sc["rules"])
    # **'통과'와 함께 말하는 숫자는 등록 수가 아니라 적용 수다** (사용자 결정 2026-08-08 · A안).
    # 쿨러 높이(공랭 전용)와 라디에이터(수랭 전용)는 배타적이라 한 구성엔 하나만 걸린다 —
    # 어떤 구성도 등록 9종을 다 통과하지 않는다. 첫 화면이 9라고 하면 S2·S3 는 같은 견적을
    # 8이라 말하고, 두 화면이 어긋난다('호환성 5종'과 같은 종류의 거짓, 방향만 반대).
    check("showcase 가 적용 규칙 수를 준다", sc.get("rules_applied") is not None,
          "있음", sc.get("rules_applied"))
    check("적용 수 <= 등록 수", (sc.get("rules_applied") or 0) <= sc["rules"],
          "<= %s" % sc["rules"], sc.get("rules_applied"))
    # **실제 견적이 돌린 검사 수와 같아야 한다** — 이 한 줄이 두 화면을 붙들어 둔다.
    _q = post("/api/recommend", {"mode": "guided",
                                 "constraints": [{"l": "용도", "v": "게임"},
                                                 {"l": "예산", "v": "150만원"}]})[1]
    _tiers = (_q or {}).get("sets") or {}
    _counts = sorted({len(v["compat"]["checks"]) for v in _tiers.values()
                      if isinstance(v, dict) and v.get("compat")})
    check("적용 수 = 실제 견적이 돌린 검사 수",
          _counts != [] and all(c == sc.get("rules_applied") for c in _counts),
          sc.get("rules_applied"), _counts)

    pk = sc.get("pick")
    check("showcase가 대표 구성을 준다", bool(pk and pk["items"]), "구성 있음", bool(pk))
    if pk:
        check("showcase 부품 합 = 총액",
              sum(i["price"] for i in pk["items"]) == pk["total"],
              pk["total"], sum(i["price"] for i in pk["items"]))
        # 가격은 DB 원천과 같아야 한다 — 화면이 지어낸 수를 보여주던 자리다
        wrong = [i["part_type"] for i in pk["items"] if db_one(
            "SELECT sale_price FROM v_recommendation_candidates WHERE product_code=:p",
            p=i["product_code"]) != i["price"]]
        check("showcase 가격 = DB 원천", not wrong, "전 부품 일치", wrong)
        oos = [i["part_type"] for i in pk["items"] if (db_one(
            "SELECT stock_qty FROM v_recommendation_candidates WHERE product_code=:p",
            p=i["product_code"]) or 0) <= 0]
        check("showcase 구성은 재고가 있다", not oos, "전 부품 재고>0", oos)
        # 실제 견적을 보여주더라도 **지금 살 수 있는 것**이어야 한다(슬라이스 60).
        # 과거 스냅샷을 그대로 내걸면 품절 부품이 '검증 통과 견적'으로 나간다.
        check("showcase 구성이 견적 슬롯을 다 채운다", len(pk["items"]) == 8, 8,
              len(pk["items"]))
        bad_slot = [i["part_type"] for i in pk["items"]
                    if i["part_type"] not in ("CPU", "MB", "RAM", "GPU",
                                              "CASE", "COOLER", "POWER", "SSD")]
        # 뷰는 COOLER_CPU_AIR/AIO로 나누지만 화면은 견적 API의 슬롯명(COOLER)을 쓴다.
        # 되돌리지 않으면 'COOLER_CPU_AIR'이 고객 화면에 그대로 찍힌다.
        check("showcase 슬롯명이 견적 API와 같다", not bad_slot, "슬롯명 정규화", bad_slot)
        if sc.get("source") == "recent":
            check("실제 견적이면 생성 시각을 준다", bool(pk.get("at")), "at 있음", pk.get("at"))
    # 랜딩이 상담 세션을 남기지 않는가 — 방문마다 쌓이면 원장이 오염된다
    n0 = db_one("SELECT count(*) FROM consult_sessions")
    get("/api/showcase")
    check("showcase는 상담 세션을 만들지 않는다",
          db_one("SELECT count(*) FROM consult_sessions") == n0, n0,
          db_one("SELECT count(*) FROM consult_sessions"))
    # 첫 화면 마크업이 서버 값을 받을 자리를 갖고 있는가
    for page, binds in (("main-landing.html", ("showcase_total", "showcase_items")),
                        ("s0-landing.html", ("live_stock_count", "showcase_total"))):
        try:
            h = io.open(os.path.join(ROOT, "mockups", "mvp1", page), encoding="utf-8").read()
            miss = [b for b in binds if b not in h]
            check(f"{page}가 서버 값을 받는다", not miss and "/api/showcase" in h,
                  "바인드+fetch 있음", miss or "fetch 없음")
        except OSError as e:                             # noqa: BLE001
            print(f"  [SKIP] (I) {page} — {e}")

    # ⑨ 운영자 작업 패널 (슬라이스 61) — 오른쪽 자리가 Theme Customizer(영문 · RTL ·
    # 레이아웃 변경)였다. 운영자가 얻는 건 없고 잘못 누르면 화면이 바뀌는 자리였다.
    wl = get("/api/admin/worklist")
    dash = get("/api/admin/dashboard")
    wm = {i["key"]: i["count"] for i in wl["items"]}
    # 같은 것을 두 번 세면 두 화면이 다른 수를 말한다 — 원천이 하나여야 한다
    diff = [k for k in ("review", "price", "inbound", "refund")
            if dash["pending"][k] != wm.get(k)]
    check("작업 패널 = 대시보드와 같은 집계", not diff, "전 항목 일치", diff)
    check("작업 패널 후보 수 = 대시보드", wl["pool"] == dash["flow"]["pool_ok"],
          dash["flow"]["pool_ok"], wl["pool"])
    # 링크가 실제 화면을 가리키는가 — 깨진 바로가기는 없느니만 못하다
    dead = [i["href"] for i in wl["items"]
            if not os.path.exists(admin_html(i["href"]))]
    check("작업 패널 바로가기가 실재한다", not dead, "전 경로 존재", dead)
    # 검수는 '판매중·재고 있는 것'이 실제 작업 목록이다(전체를 다 훑을 수는 없다)
    rv = next((i for i in wl["items"] if i["key"] == "review"), None)
    if rv:
        check("검수 항목이 실제 작업 대상을 따로 센다",
              rv["focus"] is not None and rv["focus"] <= rv["count"],
              f"<= {rv['count']}", rv["focus"])
    try:
        js = io.open(os.path.join(ROOT, "mockups", "shared", "admin-panel.js"),
                     encoding="utf-8").read()
        check("패널이 서버 값만 쓴다", "/api/admin/worklist" in js, "worklist fetch", "없음")
        pages = admin_htmls()
        miss = [os.path.basename(p) for p in pages
                if "settings-offcanvas" in io.open(p, encoding="utf-8").read()
                and "admin-panel.js" not in io.open(p, encoding="utf-8").read()]
        check("패널 있는 화면에 모두 주입됐다", not miss, "누락 없음", miss)
        # 상품 상세 제목에 예시 상품명이 남아 있으면 '최근 본 상품'에 엉뚱한 이름이
        # 박힌다 — 실제로 다른 상품 이름이 저장됐다(슬라이스 61).
        pe = io.open(admin_html("product-edit.html"),
                     encoding="utf-8").read()
        head = pe[pe.find('id="ptitle"'):pe.find('id="ptitle"') + 200]
        check("상품 상세 제목에 예시 상품명이 없다", "이엠텍" not in head, "비어 있음", head[:60])
        # 메뉴 배지가 마크업 더미를 그대로 쓰고 있었다(상품 검수 9 <-> 실제 5,162).
        # 서버 값으로 갈아끼우고, 원천 없는 배지는 지우고, 주기적으로 다시 읽는다.
        for need, why in (("paintBadges", "배지 갱신"), ("clearDummyBadges", "더미 제거"),
                          ("setInterval", "주기 갱신"), ("korean", "한글화")):
            check(f"패널 스크립트에 {why}가 있다", need in js, need, "없음")
        # 메뉴 배지가 가리키는 화면은 worklist가 다 덮어야 한다 — 안 덮이면 그 배지는
        # 지어낸 수로 남는다
        hrefs = {i["href"] for i in wl["items"]}
        idx = io.open(admin_html("index.html"),
                      encoding="utf-8").read()
        import re as _re
        badged = set(_re.findall(r'href="([a-z-]+\.html)"[^>]*>(?:(?!</a>).)*?class="badge',
                                 idx, _re.S))
        # NEW 배지처럼 숫자가 아닌 것은 대상이 아니다
        num = {h for h in badged if _re.search(
            r'href="' + _re.escape(h) + r'"(?:(?!</a>).)*?class="badge[^"]*"[^>]*>\s*[\d,]+\s*<',
            idx, _re.S)}
        uncovered = sorted(num - hrefs)
        check("숫자 배지가 달린 메뉴는 worklist가 덮는다", not uncovered, "전부 덮음", uncovered)
        # 좌측 메뉴는 아코디언이었다 — 하나를 열면 나머지가 닫혀, 그룹을 오갈 때마다
        # 다시 펼쳐야 했다. 기본은 전부 펼침이고, 운영자가 접은 것만 접힌 채로 둔다.
        mjs = io.open(os.path.join(ROOT, "mockups", "shared", "admin-menu.js"),
                      encoding="utf-8").read()
        check("메뉴가 아코디언을 해제한다",
              "removeAttribute('data-bs-parent')" in mjs, "해제 있음", "없음")
        check("메뉴 접힘 상태를 기억한다",
              "hidden.bs.collapse" in mjs and "shown.bs.collapse" in mjs,
              "두 이벤트 모두", "누락")
        mmiss = [os.path.basename(p) for p in pages
                 if "navbar-vertical" in io.open(p, encoding="utf-8").read()
                 and "admin-menu.js" not in io.open(p, encoding="utf-8").read()]
        check("메뉴 스크립트가 전 화면에 주입됐다", not mmiss, "누락 없음", mmiss)

        # 검수 [직접 수정]은 브라우저 기본 prompt()였다 — 값 하나만 묻는 회색 상자에
        # 상품이 무엇인지도 다른 사양이 어떤지도 없었다(사용자 지적). 맥락 없는 판단은
        # 오판을 부른다. 모달로 바꾸되 **새 API를 만들지 않는다**(기존 process 재사용).
        rq = io.open(admin_html("review-queue.html"),
                     encoding="utf-8").read()
        check("검수 직접 수정이 prompt()를 쓰지 않는다",
              "prompt(`${q.name}\\n${FIELD_KO" not in rq, "모달 사용", "prompt 잔존")
        check("검수 직접 수정 모달이 있다", "openFixModal" in rq, "openFixModal", "없음")
        # 쓰기는 여전히 기존 process 하나로만 간다(읽기용 siblings 조회는 별개다).
        check("모달이 기존 검수 API를 재사용한다",
              "/process`" in rq and 'action:"manual"' in rq, "process 호출", "다른 경로")
        # 같은 모델 함께 적용 — 서버가 찾아 주고 사람이 고른다(슬라이스 85)
        check("함께 적용은 사람이 고른 것만 보낸다",
              "fix-sib" in rq and "also:also" in rq, "체크 목록 사용", "없음")
        # 하단 채팅은 Phoenix 고객지원 데모였다("Eric" · 영문 문의 목록)
        hjs = io.open(os.path.join(ROOT, "mockups", "shared", "admin-helper.js"),
                      encoding="utf-8").read()
        check("운영 도우미가 답을 지어내지 않는다",
              "준비 중" in hjs, "준비 중 표기", "없음")
        hmiss = [os.path.basename(p) for p in pages
                 if "support-chat-container" in io.open(p, encoding="utf-8").read()
                 and "admin-helper.js" not in io.open(p, encoding="utf-8").read()]
        check("도우미 스크립트가 채팅 있는 화면에 모두 주입됐다", not hmiss, "누락 없음", hmiss)
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 작업 패널 주입 — {e}")


def _spec_field_guards():
    # 가드 — 잘못된 항목이 스키마를 오염시키면 되돌리기 어렵다
    for body, label, want in (
        ({"field_key": "Bad-Key", "label": "x", "data_type": "INTEGER"}, "이름 규칙", 400),
        ({"field_key": "socket", "label": "x", "data_type": "VARCHAR"}, "중복", 409),
        ({"field_key": "select", "label": "x", "data_type": "VARCHAR"}, "예약어", 400),
        ({"field_key": "zz_tmp", "label": "x", "data_type": "FLOAT"}, "자료형", 400),
        ({"field_key": "zz_tmp", "label": "x", "data_type": "INTEGER",
          "part_types": ["CASE"], "required_for": ["GPU"]}, "적용 밖 필수", 400),
    ):
        st, _ = post("/api/admin/spec-fields", body)
        check(f"사양 항목 가드: {label}", st == want, want, st)


def test_gates():
    print("\n[3] 4중 게이트 — 사양·검수·가격·재고 (슬라이스 23·24·25)")
    pool = get("/api/admin/candidate-pool")
    check("ok 합계 = S1 카운터(같은 집합)", pool["ok_total"] == pool["pool_total"],
          pool["pool_total"], pool["ok_total"])
    total_buckets = sum(
        c["ok"] + c["need_review"] + c["not_candidate"] + c["no_price"] + c["oos"] + c["no_specs"]
        for c in pool["categories"])
    check("카테고리 배타 버킷 합 = 카테고리 총계", total_buckets == pool["core_total"],
          pool["core_total"], total_buckets)
    check("ok + 제외 사유 합 = 핵심 부품 수",
          pool["ok_total"] + pool["reason_total"] == pool["core_total"],
          pool["core_total"], pool["ok_total"] + pool["reason_total"])
    check("사양 미등록 0건(슬라이스 24에서 해소)",
          next(r["count"] for r in pool["reasons"] if r["key"] == "no_specs") == 0,
          0, next(r["count"] for r in pool["reasons"] if r["key"] == "no_specs"))


# ───────────────────── 4. 화면 간 정합 (대시보드 = 각 화면) ─────────────────────
def test_consistency():
    print("\n[4] 화면 간 정합 — 대시보드는 각 화면과 같은 기준 (슬라이스 28·33·35)")
    dash = get("/api/admin/dashboard")["pending"]
    # 슬라이스 39: 검수 큐가 서버 페이지네이션이 되어 items는 한 페이지뿐이다 —
    # 정합은 **전체 건수(total)** 로 비교해야 한다(페이지 길이와 비교하면 항상 어긋난다).

    # 슬라이스 45: 적재 이력 — 화면이 사실을 말하는지(불변식)
    jobs = get("/api/admin/import-jobs")
    s = jobs["summary"]
    check("적재 배치 원장 존재", s["batches"] >= 1 and len(jobs["items"]) >= 1,
          ">=1건", s["batches"])
    check("카탈로그 = 실데이터 + 데모", s["catalog"] == s["real"] + s["demo"],
          s["real"] + s["demo"], s["catalog"])
    bad = [b for b in jobs["items"] if b["ok"] + b["error"] > b["total"]]
    check("배치별 적재+거부 <= 원본 행수", not bad, "초과 없음", bad[:2])

    rv = get("/api/admin/reviews")
    check("검수 대기", dash["review"] == rv["total"], rv["total"], dash["review"])
    drift("review_pending", rv["total"])
    # 검수 대기는 products 플래그가 아니라 **검수 행의 상태**다(admin_reviews와 같은 정의).
    rv_db = db_one("SELECT count(*) FROM product_reviews r JOIN products p USING (product_code)"
                   " WHERE r.review_status = '대기'")
    if rv_db is None:
        print("  [SKIP] (I) 검수 대기 = DB 실측 — DB 미연결")
    else:
        check("검수 대기 = DB 실측", rv["total"] == rv_db, rv_db, rv["total"])
    check("가격 검토", dash["price"] == len(get("/api/admin/price-review")["items"]),
          len(get("/api/admin/price-review")["items"]), dash["price"])
    # 입고 목록은 서버 페이지네이션이다(슬라이스 54) — 대시보드가 세는 것은 전체이므로
    # 한 페이지 길이가 아니라 total과 맞춰야 한다. 페이지 길이로 비교하면 화면이
    # "50건"이라고 말하는 동안 대시보드는 15,259를 말하는 모순을 못 잡는다.
    stock_res = get("/api/admin/stock-inbound?page=1&size=50")
    check("입고 대기 = 대시보드 집계", dash["inbound"] == stock_res["total"],
          stock_res["total"], dash["inbound"])
    check("입고 목록은 한 페이지만 보낸다(전량 전송 금지)",
          len(stock_res["items"]) <= stock_res["size"],
          f'<= {stock_res["size"]}', len(stock_res["items"]))
    check("검색어 없이는 직접 등록 후보를 보내지 않는다",
          stock_res["catalog"] == [], "빈 목록", len(stock_res["catalog"]))
    src = get("/api/admin/sourcing")
    # 두 화면이 같은 파생 조건을 쓴다 — 이제 둘 다 페이지라서 **total끼리** 대조한다
    # (예전엔 sourcing이 전 행을 보내 len(items)와 비교했다: 15,261건 · 3.6MB).
    check("매입 대기 = 입고 대기(같은 파생 조건)", src["total"] == stock_res["total"],
          stock_res["total"], src["total"])
    check("매입 견적 목록은 한 페이지만 보낸다(전량 전송 금지)",
          len(src["items"]) <= src["size"], f'<= {src["size"]}', len(src["items"]))
    # 검색이 실제로 좁히는가 — 화면 상단 검색이 서버까지 가는지 확인한다
    narrowed = get("/api/admin/sourcing?q=" + _uq("삼성"))
    check("매입 견적 검색이 서버에서 좁힌다", narrowed["total"] < src["total"],
          f'< {src["total"]}', narrowed["total"])
    none = get("/api/admin/sourcing?q=" + _uq("ZZ존재하지않는상품ZZ"))
    check("없는 검색어는 0건", none["total"] == 0, 0, none["total"])
    active_rf = [r for r in get("/api/admin/refunds")["items"]
                 if r["status"] in ("접수", "검토", "수거·처리")]
    check("활성 환불", dash["refund"] == len(active_rf), len(active_rf), dash["refund"])
    flow = get("/api/admin/dashboard")["flow"]
    check("추천 풀", flow["pool_ok"] == get("/api/admin/candidate-pool")["ok_total"],
          get("/api/admin/candidate-pool")["ok_total"], flow["pool_ok"])
    check("오늘 상담", flow["sessions_today"] == get("/api/admin/sessions")["today"],
          get("/api/admin/sessions")["today"], flow["sessions_today"])


# ────────────────────────── 5. 원장 불변식 (커머스) ──────────────────────────
def test_ledgers():
    print("\n[5] 원장 불변식 — 정산·재고·가격 (슬라이스 13·23·27)")
    pay = get("/api/admin/payments")
    for s in pay["settles"]:
        if s["state"] == "마감":
            check(f"정산 {s['date']}: 순액 = 총액 − 수수료",
                  s["net"] == s["gross"] - s["fee"],
                  s["gross"] - s["fee"], s["net"])
    closed = [s for s in pay["settles"] if s["state"] == "마감"]
    check("마감 정산 존재(잔류 데이터 확인)", len(closed) >= 1, ">= 1건", len(closed))

    hist = get("/api/admin/price-history")
    undone = [h for h in hist["items"] if "되돌림" in h["reason_label"]]
    check("가격 되돌림은 삭제가 아니라 역방향 행", len(undone) >= 1, ">= 1건", len(undone))
    for h in hist["items"]:
        if h["field"] == "purchase" and h["old"] is not None:
            check("매입가 이력에 old/new 모두 기록", h["new"] is not None,
                  "new 존재", h)
            break

    # ── 가격 = 원장 마지막 값 (2026-08-15) ──────────────────────────────────────
    # 재고는 원장 전체를 SUM해 맞추는 불변식이 있고(슬라이스 98, 아래 "[26] 재고
    # 원장") 회귀가 전 상품에서 검사한다. 가격은 지금까지 그 대응이 없었다 —
    # 위 두 검사는 "이력이 도착하는가"만 보고 "지금 값과 이력이 맞는가"는 한
    # 번도 보지 않았다. 그래서 "PATCH가 가격 이력을 안 남긴다" 결함이 사장님이
    # 직접 겪으실 때까지 안 잡혔다 — 재고였다면 회귀가 즉시 잡았을 것이다.
    # ERD §6 3원칙 3항: "모든 가격 변경은 product_price_history에 reason·ref_id와
    # 함께 기록한다"(docs/06_db-erd.md:580).
    #
    # 불변식: **이력이 있는 상품**에서 products의 현재가 = 그 상품의 마지막
    # new_price(field별로 따로 — sale/purchase). 이력이 아예 없는 상품은 여기서
    # 다루지 않는다 — "적재가 이력을 안 남긴다"는 별개 문제이고 바로 아래 코드
    # 존재 검사가 다룬다.
    #
    # ⚠ 기대값을 0으로 박지 않는다(고정 기대값(FIXED)은 폐지 — A-13, 2026-07-27).
    # 지금 이미 실측 드리프트가 있다 — product_code 119253(하네스가 PATCH로
    # 되돌릴 때 이력 미기록 버그가 살아 있던 흔적, 지금은 고쳐짐) · 46158(이
    # 회귀 자신이 남긴 잔재 — [12] test_product_edit의 product_edit/undo 쌍이
    # 191회 중 마지막 1회를 undo 없이 끊었다). 0을 박으면 이 검사가 심는 순간부터
    # 실패한다. 대신 **스냅샷보다 늘면 실패**(새로 새는 경로가 생겼다는 뜻) ·
    # **줄면 알림**(정리됐다는 뜻 — 재고의 drift()처럼 실패로 세지 않는다).
    # 재고와 달리 가격은 정상적으로 늘어날 이유가 없는 신호라 "늘면 실패"를
    # 더한다. 스냅샷(gitignore)에 키가 없는 첫 실행은 지금 값을 기준선으로
    # 채택하고 통과시킨다 — 그 파일이 없는 환경에서도 죽지 않는다.
    if _engine is None:
        print("  [SKIP] (I) 가격 원장 드리프트 — DB 미연결")
    else:
        for _field, _col in (("sale", "sale_price"), ("purchase", "purchase_price")):
            _rows = db_all(f"""
                SELECT p.product_code AS pc
                  FROM products p
                  JOIN LATERAL (
                         SELECT new_price FROM product_price_history
                          WHERE product_code = p.product_code AND field = :f
                          ORDER BY changed_at DESC, history_id DESC LIMIT 1
                       ) h ON TRUE
                 WHERE p.{_col} IS DISTINCT FROM h.new_price
                 ORDER BY p.product_code
            """, f=_field)
            codes = [r["pc"] for r in _rows]
            key = f"price_drift_{_field}"
            drift(key, len(codes))            # 스냅샷 기록 + 방향 무관 알림([값 변화])
            base = _snap_old.get(key)
            check(f"가격 원장 드리프트({_field}) — 스냅샷보다 늘지 않는다",
                  True if base is None else len(codes) <= base,
                  "기준선 없음(최초 기록)" if base is None else f"<= {base}건(스냅샷)",
                  {"count": len(codes), "product_code": codes[:30]})
            if codes:
                print(f"  [정보] 가격 드리프트({_field}) product_code: {codes[:30]}")

    # 적재가 가격 이력을 남기는 코드가 살아 있는가 — 재고 검사([26] :3172-3176)를
    # 본뜬다. ⚠ 2026-08-15 실측 당시 api/catalog_ingest.py는 이 표를 0건
    # 참조했다(다른 제작자가 같은 시각에 이 파일을 고치는 중이었다 — 그가
    # 끝나면 통과한다. 이 회귀 파일은 그 파일을 고치지 않는다).
    try:
        import re as _reL
        ci = io.open(os.path.join(ROOT, "api", "catalog_ingest.py"), encoding="utf-8").read()
        check("적재가 가격 변경을 이력에 남긴다(ERD §6 3원칙 3항)",
              "product_price_history" in ci and "'csv'" in ci, "있음", "없음")
        _m = _reL.search(r"INSERT INTO product_price_history[\s\S]{0,300}", ci)
        check("적재의 가격 이력에 ref_id가 있다(어느 적재에서 왔는지 추적)",
              bool(_m) and "ref_id" in _m.group(0), "있음", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 적재 가격 이력 계약 - {e}")

    logs = get("/api/admin/activity-logs")
    undo_rows = [i for i in logs["items"] if i["is_undo"]]
    undone_rows = [i for i in logs["items"] if i["undone"]]
    # 1:1은 **전체**에서 성립하는 관계다. 목록은 페이지라서 원본이 창 밖으로 밀리면
    # 145 대 144처럼 하나씩 어긋난다 — 실제로 그렇게 터졌다(2026-07-29). 페이지 안에서
    # 개수를 맞추는 검사는 로그가 쌓일 때마다 무작위로 실패한다. 원장 전체로 본다.
    if _engine is None:
        print("  [SKIP] (I) 되돌림 1:1 — DB 미연결")
    else:
        n_undo = db_one("SELECT count(*) FROM admin_operator_activity_logs"
                        " WHERE detail ? 'ref_log_id'")
        n_orig = db_one("SELECT count(DISTINCT (detail->>'ref_log_id')::bigint)"
                        " FROM admin_operator_activity_logs WHERE detail ? 'ref_log_id'")
        check("되돌림 행 수 = 되돌려진 원본 수(1:1)", n_undo == n_orig, n_orig, n_undo)
        # 페이지 쪽은 개수가 아니라 **근거**를 본다: '되돌려짐' 배지가 붙은 행은
        # 실제로 그것을 가리키는 되돌림 행이 있어야 한다(창 밖에 있어도 상관없다).
        phantom = [i["log_id"] for i in undone_rows if db_one(
            "SELECT count(*) FROM admin_operator_activity_logs"
            " WHERE (detail->>'ref_log_id')::bigint = :k", k=i["log_id"]) == 0]
        check("'되돌려짐' 배지에 근거가 있다", not phantom, "근거 없는 배지 없음", phantom)
    check("되돌림 행은 _undo 액션으로 식별된다", all(i["is_undo"] for i in undo_rows),
          "전부 _undo", [i["log_id"] for i in undo_rows if not i["is_undo"]])


def _order_nos(items):
    """/api/my/orders 응답에서 **주문**의 "no"만 고른다 — 인계(kind=="handoff")는 뺀다.

    2026-08-24: 그 API가 orders·handoffs를 kind로 구분해 시각순 한 목록으로 합쳐
    주기 시작했다(api/my_orders.py). 인계 번호는 `HO-1001` 꼴이라 `sorted()`가
    `ORD-...`보다 **먼저** 뽑는다(`H` < `O`) — 필터 없이 `sorted(mine_nos)[0]`을
    쓰면 인계 번호가 걸려, 주문 전용 API(`/api/my/refunds`)가 404(주문 없음)를
    내고 "타인 주문 환불 접수 → 403" 기대가 어긋난다. kind가 없는 응답(구버전
    서버·다른 배포 시점)은 전부 주문으로 본다(하위 호환).
    """
    return {o["no"] for o in items if o.get("kind", "order") == "order"}


# ──────────────────── 6. 고객 축 계약 (구매 인증·회원 경계) ────────────────────
def test_customer():
    print("\n[6] 고객 축 계약 — 회원 경계·구매 인증 (슬라이스 10·12·30·38)")
    # 슬라이스 38: 회원 경계는 **세션**이 정한다(?email= 은 더 이상 받지 않는다).
    check("미인증 회원 API 401", anon_status("/api/my/orders") == 401,
          401, anon_status("/api/my/orders"))

    member_login("mj.kim@example.com")
    mine = get("/api/my/orders")["items"]
    pays = get("/api/my/payments")["items"]
    acct = get("/api/my/account")
    member_login("sy.lee@example.com")
    other = get("/api/my/orders")["items"]
    # kind로 주문만 고른다(_order_nos, 2026-08-24) — 이 아래 두 검사는 이름 그대로
    # "타인 주문" 경계만 겨눈다. 인계(HO-…)는 환불 접수 대상이 아니다(결제를 안
    # 받았다) — 섞이면 sorted()가 HO-를 먼저 집어 환불 검사가 404로 어긋난다.
    mine_nos = _order_nos(mine)
    other_nos = _order_nos(other)
    check("회원 경계: 타인 주문 미포함",
          not (mine_nos & other_nos), "교집합 없음",
          mine_nos & other_nos)
    # 다른 회원 세션으로 타인 주문의 환불을 접수할 수 없다(경계가 세션으로 강제되는가)
    if mine_nos:
        st, _ = post("/api/my/refunds",
                     {"order_no": sorted(mine_nos)[0], "reason_type": "단순 변심"})
        check("타인 주문 환불 접수 → 403", st == 403, 403, st)
    else:
        check("타인 주문 환불 접수 → 403", False, "주문 1건 이상 필요", "mj.kim 주문 없음")

    # 신규 이메일 로그인 = 가입(승인 게이트 없음) → 주문은 당연히 0건
    member_login("regress-guest@popcornpc.local", "회귀게스트")
    fresh = get("/api/my/orders")["items"]
    # "주문 목록"이라는 이름 그대로 주문만 본다 — 지금은 신규 계정에 이어지는 인계가
    # 0건이라 fresh == [] 도 우연히 통과하지만(2026-08-24 실측, my_orders.py 참조),
    # 그 우연에 기대지 않는다. kind로 걸러 인계가 섞여도 이 검사가 지어내지 않은
    # 이유로 깨지지 않게 한다.
    fresh_orders = [o for o in fresh if o.get("kind", "order") == "order"]
    check("신규 가입 회원 → 빈 주문 목록", fresh_orders == [], [], fresh_orders)
    me = get("/api/auth/me")
    check("고객 세션 me", bool(me["authenticated"])
          and me["member"]["email"] == "regress-guest@popcornpc.local",
          "regress-guest 세션", me.get("member"))

    check("결제 원장은 전 행(승인·환불 각 한 줄)",
          any(p["status"] == "환불" for p in pays) and any(p["status"] == "승인" for p in pays),
          "승인·환불 모두 존재", {p["status"] for p in pays})
    check("고객 응답에 pg_ref 미포함(미노출 계약)",
          all("pg_ref" not in p for p in pays), "pg_ref 키 없음",
          [k for p in pays for k in p if k == "pg_ref"])
    check("후기는 구매 인증(완료 주문) 라인만",
          all(r["order_no"] for r in acct["reviewable"]), "전 항목 주문 연결", acct["reviewable"])

    # 로그아웃하면 즉시 닫힌다(철회 기록 — 세션 행은 남는다)
    post("/api/auth/logout")
    SESSION.pop("popcorn_member_session", None)
    check("로그아웃 후 회원 API 401", anon_status("/api/my/orders") == 401,
          401, anon_status("/api/my/orders"))


# ────────────────────────── 7. 가드 (권한·상태 전이) ──────────────────────────
# ──────────────────────── 8. 관리자 인증 · 승인 게이트 (슬라이스 37) ────────────────────────
def test_auth():
    print("\n[8] 관리자 인증 · 승인 게이트 (슬라이스 37)")
    check("미인증 관리자 API 401", anon_status("/api/admin/products") == 401,
          401, anon_status("/api/admin/products"))
    anon_cust = anon_status("/api/candidates/count", {"constraints": []})
    check("미인증도 고객 API는 열림", anon_cust == 200, 200, anon_cust)

    d = get("/api/admin/auth/me")
    check("세션 확인 me", bool(d["authenticated"]) and d["operator"]["role"] == "owner",
          "owner 세션", d.get("operator"))

    ops = get("/api/admin/operators")
    me = [o for o in ops["items"] if o["is_me"]]
    check("운영자 목록에 본인 표시", len(me) == 1, 1, len(me))
    check("본인 라이브 세션 1개 이상", bool(me) and me[0]["live_sessions"] >= 1,
          ">=1", me[0]["live_sessions"] if me else None)

    # ── 운영자·권한(ADM-SYS-020)도 내 정보와 **같은 판정**을 쓴다 (슬라이스 102) ──
    # 이 화면은 `o.approver || '—'`로 세 사실을 같아 보이게 했고(부트스트랩 자동 승인 ·
    # 승인자 계정 삭제 · 미승인), 신청 배지는 `dev`를 "dev 인증"으로 내보내 **있지도 않은
    # 인증을 단언**했다. 판정은 `identity_reasons` 하나로 모았다.
    _it = ops["items"]
    check("모든 계정에 로그인 방식 이유가 있다",
          all(o.get("provider_label") and o.get("provider_note") for o in _it),
          "전 항목", [o["id"] for o in _it
                    if not (o.get("provider_label") and o.get("provider_note"))])
    check("모든 계정에 승인 라벨이 있다",
          all(o.get("approved_short") for o in _it),
          "전 항목", [o["id"] for o in _it if not o.get("approved_short")])
    check("데이터 필드에 표시용 '—'를 담지 않는다",
          not any(o.get("provider") == "—" for o in _it),
          "0건", [o["id"] for o in _it if o.get("provider") == "—"])
    check("승인 경위와 부재 이유는 배타다",
          all(bool(o.get("approved_note")) != bool(o.get("approved_none_reason"))
              for o in _it), "전 항목 하나만",
          [o["id"] for o in _it
           if bool(o.get("approved_note")) == bool(o.get("approved_none_reason"))])
    # 같은 사실을 두 경로로 센다(A-13) — 화면이 부르는 라벨 수 = DB 실측
    _boot_db = db_one("SELECT count(*) FROM admin_operators"
                      " WHERE approved_at IS NOT NULL AND approved_by IS NULL")
    _none_db = db_one("SELECT count(*) FROM admin_operators WHERE approved_at IS NULL")
    if _boot_db is None:
        print("  [SKIP] (I) 승인 라벨 = DB 실측 — DB 미연결")
    else:
        check("부트스트랩 자동 승인 수 = DB 실측",
              len([o for o in _it if o["approved_short"] == "부트스트랩(자동)"]) == _boot_db,
              _boot_db, len([o for o in _it if o["approved_short"] == "부트스트랩(자동)"]))
        check("미승인 계정 수 = DB 실측",
              len([o for o in _it if o["approved_short"] == "승인 안 됨"]) == _none_db,
              _none_db, len([o for o in _it if o["approved_short"] == "승인 안 됨"]))

    # ── 승인 대기 안내문 ── **승인 판단의 근거이므로 서버가 말한다**
    # 예전 문구는 "직원이 회사 계정으로 본인 확인을 마친 신청입니다"였다. dev 어댑터에서는
    # 본인 확인이 일어나지 않으므로 owner를 잘못된 전제로 승인하게 만들고 있었다.
    check("승인 대기 안내문을 서버가 준다",
          bool(ops.get("pending_note")), "문구 있음", ops.get("pending_note"))
    from api.admin_operators import _pending_note as _pn
    from api.admin_profile import PROVIDER_KO as _PK
    _P = lambda **k: dict(dict(provider="dev", approved_at=None, approved_by=None,
                               status="대기", approver=None), **k)
    check("검증되지 않은 신청이 있으면 그 사실을 먼저 말한다",
          "검증되지 않은" in _pn([_P()]), "미검증 언급", _pn([_P()]))
    check("대기가 없으면 없다고 말한다",
          "없습니다" in _pn([_P(status="활성")]), "0건 문구", _pn([_P(status="활성")]))
    # 검증됐다고 말하는 분기는 **오늘 도달할 수 없다**(어떤 provider도 verified가 아니다).
    # 그래서 값이 아니라 **관계**를 지킨다: 검증된 제공자가 생기면 문구가 바뀐다.
    # 실 OAuth를 붙일 때 손댈 자리가 PROVIDER_KO 하나임을 이 검사가 증명한다.
    _PK["_regress_verified"] = ("검증됨(검사용)", True, "검사가 넣은 항목입니다")
    try:
        _after = _pn([_P(provider="_regress_verified")])
        check("검증된 제공자가 생기면 안내문이 바뀐다",
              "검증되지 않은" not in _after and "본인 확인" in _after,
              "본인 확인 문구", _after)
    finally:
        _PK.pop("_regress_verified", None)
    check("검사가 제공자 목록을 되돌려 놓았다",
          "_regress_verified" not in _PK, "없음", sorted(_PK))

    # ── 화면 계약 ── 되돌아오면 안 되는 문구들
    _op = io.open(admin_html("operators.html"),
                  encoding="utf-8").read()
    check("화면이 '있지도 않은 인증'을 단언하지 않는다",
          "esc(o.provider) + ' 인증'" not in _op, "제거됨", "잔존")
    check("화면이 승인자를 '—'로 뭉개지 않는다",
          "o.approver || '—'" not in _op, "제거됨", "잔존")
    check("화면이 본인 확인 문구를 하드코딩하지 않는다",
          "pending_note" in _op and "'직원이 회사 계정으로 본인 확인을 마친" not in _op,
          "서버 문구 사용", "하드코딩 잔존")

    # 승인 게이트 — 신규 신청은 '대기'이며 그 상태로는 세션이 발급되지 않는다.
    # 계정은 원장이므로 지우지 않는다 → 2회차 실행은 '정지 잔류'를 확인하는 경로로 간다
    # (분기마다 검사 2건씩 — 합계는 실행 횟수와 무관하게 같다).
    applicant = "regress-applicant@popcornpc.local"
    prev = [o for o in ops["items"] if o["email"] == applicant]
    if prev:
        check("이전 실행의 신청 계정이 정지 상태로 남음", prev[0]["status"] == "정지",
              "정지", prev[0]["status"])
        st, _ = post("/api/admin/auth/login", {"email": applicant, "provider": "dev"})
        check("정지 계정 로그인 차단", st == 403, 403, st)
        new_id = prev[0]["id"]
    else:
        st, r = post("/api/admin/auth/login",
                     {"email": applicant, "name": "회귀신청자", "provider": "dev",
                      "duty": "회귀 세트 검증용"})
        check("신규 신청은 대기", r.get("state") == "pending", "pending", r.get("state"))
        new_id = r["operator"]["id"]
        st, _ = post("/api/admin/auth/login", {"email": applicant, "provider": "dev"})
        check("대기 계정 재로그인도 대기", st == 200, 200, st)

    st, r = post("/api/admin/operators/%d/approve" % new_id, {"role": "viewer"})
    check("승인 → 활성", st == 200 and r.get("status") == "활성", "활성", r)
    st, r = post("/api/admin/operators/%d/role" % new_id, {"role": "operator"})
    check("권한 변경", st == 200 and r.get("role") == "operator", "operator", r)
    st, r = post("/api/admin/operators/%d/suspend" % new_id)
    check("정지 + 세션 무효화", st == 200 and r.get("status") == "정지", "정지", r)

    # 자기 계정 보호 — 관리자가 스스로 잠기는 것을 막는다
    my_id = me[0]["id"] if me else 1
    st, _ = post("/api/admin/operators/%d/suspend" % my_id)
    check("자기 계정 정지 차단", st == 409, 409, st)
    st, _ = post("/api/admin/operators/%d/role" % my_id, {"role": "viewer"})
    check("자기 계정 강등 차단", st == 409, 409, st)

    # 마지막 관리자 보호 — 활성 owner가 1명뿐이면 정지 불가(자기 정지 차단과 별개 규칙)
    owners = [o for o in get("/api/admin/operators")["items"]
              if o["role"] == "owner" and o["status"] == "활성"]
    check("활성 관리자 1명 이상 유지", len(owners) >= 1, ">=1", len(owners))

    # 승인·권한·정지가 감사 로그에 남는다(주체 = 로그인 운영자)
    logs = get("/api/admin/activity-logs")
    acts = [l for l in logs["items"] if str(l.get("kind_raw", l.get("kind", ""))) == "operator"]
    check("운영자 관리 행위가 작업 기록에 남음", len(acts) >= 3, ">=3건", len(acts))


# ────────────── 9. 운영 전환 설정 (슬라이스 44) ──────────────
def test_ops():
    """이 설정은 주문 흐름을 실제로 바꾼다 — 바꾸고, 막히는지 보고, 반드시 원복한다.

    원복까지가 이 테스트의 일부다. 중간에 실패해도 finally로 되돌린다 — 회귀가
    운영 모드를 망친 상태로 남기면 그 뒤 테스트와 실제 화면이 전부 어긋난다.
    """
    print("\n[9] 운영 전환 설정 — 스위치가 흐름을 바꾸는가 (슬라이스 44)")
    base = get("/api/admin/ops-settings")["modes"]
    check("운영 모드 5종 존재", set(base) == {"member", "pay", "settle", "ship", "refund"},
          "5종", sorted(base))

    # **기준 상태를 가정하지 않는다** (2026-08-12). 이 검사는 「기본 = 자체 결제」를
    # 박아 두고 있었는데, 범위 확정으로 운영 기준이 쇼핑몰 인계(pay=mall)가 되자
    # 두 건이 깨졌다 — 스위치가 어느 쪽이든 성립하는 관계로 고친다(A-13 원칙:
    # 값이 아니라 관계를 검사한다).
    order_body = {"session_id": 1, "tier": "value", "periph": [],
                  "member": {"nick": "회귀", "email": "ops-regress@popcornpc.local"},
                  "shipping": {"name": "회귀", "phone": "010-0000-0000", "addr": "서울"}}
    opp = "own" if base["pay"] == "mall" else "mall"

    def gate_err():
        st, r = post("/api/orders", order_body)
        detail = r.get("detail") if isinstance(r, dict) else None
        return st, (detail.get("error") if isinstance(detail, dict) else None)

    def mall_checks(undo_ids):
        """pay=mall 인 순간에만 성립하는 둘 — 환불 보정 · 자체 주문 차단."""
        st, d2 = post("/api/admin/ops-settings", {"modes": {"refund": "own"}})
        if d2.get("undo_id"):
            undo_ids.append(d2["undo_id"])
        check("쇼핑몰 결제 상태에서 환불 '자체'는 보정된다",
              d2.get("modes", {}).get("refund") == "mall", "refund=mall", d2.get("modes"))
        st, err = gate_err()
        check("쇼핑몰 결제 모드에서 자체 주문 409", st == 409 and err == "pay_mode_mall",
              "409 pay_mode_mall", f"{st} {err}")

    undo_ids = []
    try:
        if base["pay"] == "mall":
            mall_checks(undo_ids)                    # 기준이 이미 mall — 그대로 검사
        st, d = post("/api/admin/ops-settings", {"modes": {"pay": opp}})
        undo_ids.append(d.get("undo_id"))
        check("결제 전환 시 정산도 함께 이동(정산은 결제를 따른다)",
              d.get("changed", {}).get("settle", {}).get("to") == opp,
              "settle=" + opp, d.get("changed"))
        if opp == "mall":
            mall_checks(undo_ids)                    # 기준이 own — 전환해 놓고 검사
    finally:
        for lid in reversed([i for i in undo_ids if i]):
            post(f"/api/admin/ops-settings/undo/{lid}")

    after = get("/api/admin/ops-settings")["modes"]
    check("되돌리기로 원상 복구", after == base, base, after)

    # ③ 원복 후 게이트는 **기준 상태의 규칙**을 따라야 한다 — 통과가 아니라 일치가 불변식이다
    st, err = gate_err()
    if base["pay"] == "mall":
        check("원복 후 게이트가 기준 상태(쇼핑몰 인계)를 지킨다",
              err == "pay_mode_mall", "pay_mode_mall", err)
    else:
        check("원복 후 결제 게이트 통과", err != "pay_mode_mall", "pay_mode_mall 아님", err)


# ────────── 10. 부품 교체(S3) — 대안·적용·원장 (슬라이스 46) ──────────
def test_swap():
    """대안이 0건이면 S3 화면이 무력하다 — 그 조용한 고장을 여기서 잡는다."""
    print("\n[10] 부품 교체(S3) — 대안·적용·원장 (슬라이스 46)")
    _, rec = post("/api/recommend", {"mode": "guided",
                  "constraints": [{"l": "용도", "v": "게임"}, {"l": "예산", "v": "150만원"}]})
    sess = rec["session_id"]

    # 접근 게이트(0055) — `candidates`도 그 상담의 주인인지 검사한다. 열쇠는 바로 위
    # `POST /api/recommend` 응답이 준 것 하나뿐이다. 아래 `apply`와 같은 이유이고
    # 같은 열쇠다 — **회귀를 통과시키려고 맞추는 값이 아니라, 열쇠를 실어 보내는 것이
    # 「옳은 호출」이라서 고친다.** 안 실으면 403(access_key_missing)이라 이 검사는
    # 「대안이 0건이다」가 아니라 「호출이 틀렸다」를 보고하는 셈이 된다.
    st, cand = post("/api/swap/candidates",
                    {"session_id": sess, "tier": "recommend", "slot": "GPU",
                     "access_key": rec.get("access_key")})
    slots = cand.get("slots", {})
    total_alts = sum(len(v.get("alternatives") or []) for v in slots.values())
    check("스왑 대안이 존재한다(슬롯 합)", total_alts > 0, "> 0", total_alts)
    empty_slots = [k for k, v in slots.items() if not (v.get("alternatives") or [])]
    check("전 슬롯 동시 0건이 아니다(규칙 필드 누락 신호)",
          len(empty_slots) < len(slots), f"< {len(slots)}개 슬롯", empty_slots)

    gpu = slots.get("GPU", {}).get("alternatives") or []
    if not gpu:
        check("GPU 대안 존재", False, "> 0", 0)
        return
    pick = next((a for a in gpu if not a.get("chain")), gpu[0])

    before = get("/api/admin/swap-logs")["total"]
    # 접근 게이트(0055) — 이 경로는 원장에 쓰는 자리라 「그 상담의 주인인가」를 서버가
    # 검사한다. 열쇠는 위 `POST /api/recommend` 응답이 준 것 하나뿐이다. 넣지 않으면
    # 403(access_key_missing)이라 «옳은 호출»이 되지 않는다 — 값을 맞추는 게 아니라
    # 호출을 맞추는 것이다. 0055 미적용 DB 에서는 서버가 열쇠를 null 로 주고 503 을 낸다.
    ak = rec.get("access_key")
    st, ap = post("/api/swap/apply", {"session_id": sess, "tier": "recommend",
                                      "access_key": ak,
                                      "changes": [{"slot": "GPU",
                                                   "product_code": pick["product_code"]}]})
    if st == 503:
        check("스왑 적용 성공", False, 200,
              "503 gate_unavailable - 마이그레이션 0055 미적용(access_key 컬럼 없음)")
        return
    check("스왑 적용 성공", st == 200, 200, st)
    if st != 200:
        return
    check("적용 결과가 호환 전부 통과",
          all(c["pass"] for c in ap["compat"]["checks"]), "전부 통과",
          [c["key"] for c in ap["compat"]["checks"] if not c["pass"]])
    # 1:1이 아니라 관계로 본다 — 적용 부품을 좁힌 규칙은 어떤 부품이 뽑혔느냐에 따라
    # 빠진다(수랭 구성엔 '쿨러 높이 여유'가, 공랭 구성엔 '라디에이터 장착'이 없는 게 정상).
    _act = [r for r in get("/api/admin/engine-rules")["compat"]["checks"]
            if r.get("active", True)]
    _keys = {c["key"] for c in ap["compat"]["checks"]}
    _always = {r["key"] for r in _act if not (r.get("part_types") or [])}
    check("교체 후 근거는 활성 규칙에서만 나온다",
          _keys <= {r["key"] for r in _act}, "부분집합",
          sorted(_keys - {r["key"] for r in _act}))
    check("교체 후 적용 부품 제한 없는 규칙은 전부 있다", _always <= _keys,
          "누락 없음", sorted(_always - _keys))

    after = get("/api/admin/swap-logs")
    check("교체가 원장에 남는다", after["total"] == before + 1, before + 1, after["total"])
    top = after["recent"][0] if after["recent"] else {}
    check("기록에 슬롯·전후 SKU가 남는다",
          top.get("slot") == "GPU" and top.get("to_sku") == pick["sku"],
          f"GPU/{pick['sku']}", f"{top.get('slot')}/{top.get('to_sku')}")
    # 근거 클릭은 슬라이스 49부터 실제로 쌓인다(그 전엔 '원천 준비 중'이었다).
    # 절대값 대신 응답 내부 정합을 본다 — 0건이어도 수천 건이어도 성립해야 한다.
    ck = after["clicks"]
    check("클릭 empty는 count와 일치한다", ck["empty"] == (ck["count"] == 0),
          f'empty=={ck["count"] == 0}', ck["empty"])
    check("클릭 식별/미식별 합 = 총계",
          ck["identified"] + ck["unidentified"] == ck["count"],
          ck["count"], ck["identified"] + ck["unidentified"])
    check("클릭 상위 집계가 총계를 넘지 않는다",
          sum(t["n"] for t in ck.get("top", [])) <= ck["count"],
          f'<= {ck["count"]}', sum(t["n"] for t in ck.get("top", [])))
    check("클릭 영역은 상태를 문장으로 밝힌다", bool(ck["reason"]), "사유 있음", ck["reason"])
    # 실제로 쌓이는가 — 한 건 넣고 총계가 정확히 1 늘어야 한다(수집 경로가 살아 있다는 증거)
    pc = pick["product_code"]
    st_c, _ = post("/api/promo-click", {"product_code": pc})
    check("근거 클릭 수집 경로가 살아 있다", st_c == 200, 200, st_c)
    ck2 = get("/api/admin/swap-logs")["clicks"]
    check("클릭 1건이 총계에 정확히 반영된다", ck2["count"] == ck["count"] + 1,
          ck["count"] + 1, ck2["count"])
    st_bad, _ = post("/api/promo-click", {"product_code": 999_999_999})
    check("없는 상품 클릭은 404", st_bad == 404, 404, st_bad)


def test_guards():
    print("\n[7] 가드 — 상태 전이·권한 (슬라이스 7·11·19·30·35)")
    member_login("mj.kim@example.com")        # 가드도 세션 주체로 확인(슬라이스 38)
    st, _ = post("/api/my/reviews", {"item_id": 999999,
                                     "rating": 5, "body": "존재하지 않는 라인 테스트입니다"})
    check("없는 주문 라인 후기 → 404", st == 404, 404, st)
    st, _ = post("/api/my/reviews", {"item_id": 12,
                                     "rating": 5, "body": "타인 주문 라인 테스트입니다"})
    check("타인 주문 라인 후기 → 403", st == 403, 403, st)
    # ── 개발 전용 dev-login 은 **열려 있으면 누구나 관리자가 된다** (2026-08-11)
    #    스위치가 꺼져 있으면 404, 켜져 있어도 localhost 밖이면 403이어야 한다.
    #    회귀는 로컬에서 도니 "켜졌으면 동작"까지만 확인하고, **운영 확인은 배포 문서가 맡는다**
    #    (`.env` 에 UI_CHECK_DEV_LOGIN 이 없어야 한다).
    import os as _os
    _on = _os.environ.get("UI_CHECK_DEV_LOGIN", "").strip() in ("1", "true", "True", "yes")
    st, body = get_html("/api/admin/auth/dev-login")
    if _on:
        check("dev-login 켜짐 → 로컬에서 세션이 심긴다", st == 200, 200, st)
        check("dev-login 이 비밀번호를 응답에 담지 않는다",
              "password" not in str(body).lower() and "pw" not in str(body).lower(),
              "없음", "있음")
    else:
        check("dev-login 꺼짐 → 404", st == 404, 404, st)

    st, _ = post("/api/admin/stock-inbound/20489103", {"qty": 0, "why": "inbound"})
    check("입고 수량 0 → 400", st == 400, 400, st)
    st, _ = post("/api/admin/sourcing/request", {"product_code": 20489103, "supplier_ids": []})
    check("공급처 미선택 견적 요청 → 400", st == 400, 400, st)
    member_login("sy.lee@example.com")
    st, _ = post("/api/my/account/map", {"agree": True})
    check("요청 없는 계정 연결 동의 → 409", st == 409, 409, st)


def test_std_schema():
    """[43] 조립 보증 표준 스키마 `std` — **`public` 을 건드리지 않는다** (2026-08-10)

    ■ 왜 이 검사가 필요한가
      사용자 원칙: *"기존 DB 테이블을 건드리지 말고 신규 테이블을 생성"* ·
      *"신규 DB 로 가지 맙시다."* 그래서 같은 DB 안의 별도 스키마 `std` 에 지었다.
      **그 경계가 지켜지는지는 사람이 기억할 일이 아니라 검사가 지킬 일이다.**
      실제로 0035 에서 내가 `product_specs` 에 컬럼 26개를 붙였다가 되돌렸다.

    ■ 관계로 본다
      고정 건수를 적지 않는다. `std.part_specs` 는 계속 늘고 `public` 은 그대로여야 한다.
    """
    print("\n[43] 조립 보증 표준 스키마 std — public 무손 (P-08)")
    if _engine is None:
        check("[43] std 스키마", True, "DB 미접속 — 건너뜀", "건너뜀", kind="SKIP")
        return

    with _engine.connect() as c:
        # ① `public.product_specs` 에 표준 항목이 새어 들어오지 않았다
        std_only = [r[0] for r in c.execute(text(
            "SELECT field_key FROM std.spec_defs")).all()]
        pub_cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name='product_specs'")).all()}
        leaked = sorted(set(std_only) & pub_cols - {
            # 개념이 겹치는 기존 항목은 원래 public 에 있던 것이다(이관 대상)
            "socket", "socket_list", "chipset", "mem_type", "tdp_watt", "rated_watt",
            "required_power_watt", "length_mm", "gpu_max_mm", "cooler_height_mm",
            "cooler_tdp", "radiator_rows", "radiator_max_rows", "form_factor",
            "form_factor_list", "interface", "capacity_gb", "clock_mhz", "pcie_gen",
            "size_inch"})
        check("[43] 신설 표준 항목이 public 에 새지 않았다", not leaked, "없음", leaked)

        # ② 값마다 근거가 있다 — 근거 없는 값은 지어낸 값과 구별되지 않는다
        n = c.execute(text("SELECT COUNT(*) FROM std.part_specs")).scalar()
        bad = c.execute(text(
            "SELECT COUNT(*) FROM std.part_specs"
            " WHERE source_ref IS NULL OR source_ref = ''")).scalar()
        check(f"[43] 값 {n}건 전부 근거(source_ref) 보유", bad == 0, 0, bad)

        # ③ 사람이 고친 값은 잠겨 있다 — 안 잠그면 다음 파싱이 덮어쓴다
        unlocked = c.execute(text(
            "SELECT COUNT(*) FROM std.part_specs WHERE source='human' AND NOT locked")).scalar()
        check("[43] human 출처는 전부 잠김", unlocked == 0, 0, unlocked)

        # ④ 정의 없는 필드가 값 테이블에 없다(FK 가 막지만 계약을 명시한다)
        orphan = c.execute(text(
            "SELECT COUNT(*) FROM std.part_specs s"
            " WHERE NOT EXISTS (SELECT 1 FROM std.spec_defs d WHERE d.field_key=s.field_key)")).scalar()
        check("[43] 정의 없는 필드의 값 없음", orphan == 0, 0, orphan)

        # ⑤ **필수 승격은 항목별로 한다** — 한꺼번에 올리면 추천 후보가 0이 된다
        req = c.execute(text(
            "SELECT COUNT(*) FROM std.spec_defs WHERE required_for <> '[]'::jsonb")).scalar()
        pool = c.execute(text(
            "SELECT COUNT(*) FROM v_recommendation_candidates WHERE stock_qty>0")).scalar()
        check(f"[43] 필수 지정 {req}개인데 추천 후보가 비지 않았다", pool > 0, "> 0", pool)

        # ⑥ 사양 하나가 **여러 쌍에 걸칠 수 있어야** 한다 — 조감도가 드러낸 결함이다.
        #    `height_mm` 은 RAM(D3 쿨러 간섭)과 GPU(B2 케이스 여유) 양쪽에 쓰이는데
        #    단수 `compat_pair` 로는 한쪽만 적혀 판정 지도가 틀렸다(0038 에서 목록으로 바꿨다).
        multi = c.execute(text(
            "SELECT COUNT(*) FROM std.spec_defs"
            " WHERE jsonb_array_length(compat_pairs) > 1")).scalar()
        check("[43] 여러 쌍에 걸친 사양을 표현할 수 있다", multi > 0, "> 0", multi)

        # ⑦ **막는 항목은 양쪽에 사양이 있어야 판정된다.** 한쪽만 있으면 영원히 못 막는다.
        #    (케이스에 GPU 최대 높이가 없어 B2 가 반쪽이었다 — 0038 에서 채웠다)
        lonely = [r[0] for r in c.execute(text("""
            SELECT pair FROM (
              SELECT p.pair, COUNT(DISTINCT t.part) AS parts
              FROM std.spec_defs d,
                   LATERAL jsonb_array_elements_text(d.compat_pairs) AS p(pair),
                   LATERAL jsonb_array_elements_text(d.part_types) AS t(part)
              WHERE d.is_blocking GROUP BY 1) x
            WHERE parts < 2 ORDER BY 1""")).all()]
        check("[43] 막는 관계는 부품 둘 이상이 얽힌다", not lonely, "없음", lonely)

        # ⑧ **관계 정본이 엔진과 어긋나지 않는다.** `std.compat_pairs.rule_key` 가
        #    가리키는 규칙이 `public.compat_rules` 에 실제로 살아 있어야 한다 —
        #    어긋나면 화면이 "검사 중"이라 말하는데 엔진은 검사하지 않는다.
        ghost_rules = [r[0] for r in c.execute(text(
            "SELECT p.rule_key FROM std.compat_pairs p"
            " WHERE p.rule_key IS NOT NULL AND NOT EXISTS ("
            "   SELECT 1 FROM compat_rules r WHERE r.rule_key = p.rule_key AND r.active)"
            " ORDER BY 1")).all()]
        check("[43] 관계가 가리키는 규칙이 엔진에 실재한다", not ghost_rules, "없음", ghost_rules)

        # ⑨ 검사 중인 규칙은 **전부** 관계에 매여 있다 — 지도에서 빠진 규칙이 없어야 한다
        orphan_rules = [r[0] for r in c.execute(text(
            "SELECT r.rule_key FROM compat_rules r WHERE r.active AND NOT EXISTS ("
            "   SELECT 1 FROM std.compat_pairs p WHERE p.rule_key = r.rule_key)"
            " ORDER BY 1")).all()]
        check("[43] 엔진 규칙이 전부 지도에 있다", not orphan_rules, "없음", orphan_rules)

        # ⑩ 표준이 겨냥한 부품 종류가 실재한다(오타로 죽은 항목을 만들지 않는다)
        types = {r[0] for r in c.execute(text(
            "SELECT DISTINCT part_type FROM products")).all()}
        ghost = sorted({p for r in c.execute(text("SELECT part_types FROM std.spec_defs")).all()
                        for p in list(r[0] or []) if p not in types})
        check("[43] 표준의 적용 대상이 전부 실재하는 부품 종류", not ghost, "없음", ghost)

    # ⑪ 조감도(ADM-STD-020)가 기대는 API 계약 — 화면 셋이 같은 값을 각자 파생하지
    #    않도록 **상태를 서버가 준다.** 그 값이 근거 플래그와 어긋나면 세 안이 동시에
    #    거짓말을 한다. 관계식으로 본다(고정 기대값을 두지 않는다).
    m = get("/api/admin/std/compat-map")
    wrong = [p["pair_key"] for p in m["pairs"]
             if p["status"] != ("out" if not p["in_scope"] else
                                "checking" if p["rule_active"] else
                                "norule" if p["ready"] else "missing")]
    check("[43] compat-map status 가 근거 플래그와 일치", not wrong, "없음", wrong)

    # 상태는 넷 중 하나뿐이고, 합은 관계 총수와 같다 — 어느 관계도 분류에서 새지 않는다
    buckets = {k: len([p for p in m["pairs"] if p["status"] == k])
               for k in ("checking", "norule", "missing", "out")}
    check("[43] 상태 4분류 합 = 관계 총수",
          sum(buckets.values()) == m["summary"]["pairs_total"],
          m["summary"]["pairs_total"], sum(buckets.values()))
    check("[43] 검사 중 수 = summary.pairs_checked",
          buckets["checking"] == m["summary"]["pairs_checked"],
          m["summary"]["pairs_checked"], buckets["checking"])

    # 지도에 서는 노드는 **전부 이름을 받는다.** 하나라도 빠지면 화면이 영문 키를 노출한다
    nodes = {x for p in m["pairs"] for x in (p["left_part"], p["right_part"])}
    unnamed = sorted(n for n in nodes if not m["part_labels"].get(n))
    check("[43] 지도 노드가 전부 이름을 받는다", not unnamed, "없음", unnamed)
    check("[43] 부품 카드에 한글 이름이 있다",
          all(p.get("name") for p in m["parts"]), "전부 있음",
          [p["part_type"] for p in m["parts"] if not p.get("name")] or "-")

    # ⑫ 데이터를 못 받았을 때 **돌아갈 길**이 화면 안에 있다.
    #    2026-08-11 이 화면은 세션이 끊긴 채 사용자에게 갔고, 머리말에 «HTTP 401» 만
    #    찍혀 운영자가 할 수 있는 것이 없었다. 오류를 표시하는 것과 조치를 주는 것은 다르다.
    _, bm = get_html("/admin2/build-map")
    # 로그인 경로는 `/admin2/login` 이다(2026-08-17 전환 — admin_ui_common._LOGIN_PAGE 와
    # 같은 목적지). 옛 `/admin/login.html` 은 이제 410 이라, 그리로 보내는 안내는
    # «돌아갈 길»이 아니다 — 구화면 이동(2026-08-17)이 이 화면의 낙오 링크를 함께 고쳤다.
    for token, why in (("/admin2/login", "로그인 경로"),
                       ("세션 만료", "401 안내 문구"),
                       ("data-action=\"retry\"", "재시도 버튼")):
        check(f"[43] 조감도 조회 실패 안내 — {why}", token in bm, "있음", "없음")


def test_display_name():
    """[42] 견적 표시용 상품명 — 판매조건 꼬리가 고객에게 새지 않는다 (A-38 ⑤ · 2026-08-10)

    ■ 왜 검사가 필요한가
      `products.product_name` 은 마켓에 내보내는 **판매용 제목**이라 "… 회원가입 계좌이체
      맞춤할인 2.5%" 같은 꼬리가 붙는다(전체 22,840건 중 868건). 견적은 "왜 이 부품인가"를
      말하는 자리라 그 꼬리가 근거를 묻는다. 파생은 `api/product_name.display_name` 하나가
      하고, **고객 응답을 만드는 자리마다** 불러야 한다 — 한 군데만 빠뜨려도 그 화면에서
      조용히 광고가 샌다(500이 아니라 '이름이 좀 지저분함'으로 보인다).

    ■ 관계로 본다
      고정 건수를 적지 않는다. **원천에 꼬리가 있는 상품이 응답에 나타나면, 그 응답의
      이름에는 꼬리가 없어야 한다** — 원천이 바뀌어도 성립하는 관계다.

    ■ 예외는 하나이고 그것도 관계로 고정한다
      자른 뒤 이름이 없어지는 상품(원천이 통째로 광고)은 자르지 않는다. 빈 이름을
      내미느니 광고를 내미는 게 낫다. 그런 상품은 **검수로 풀 문제**라 여기서는
      '예외가 늘지 않았는지'만 본다.
    """
    print("\n[42] 견적 표시용 상품명 — 판매조건 꼬리 차단 (A-38 ⑤)")
    sys.path.insert(0, ROOT)
    from api.product_name import display_name

    # ① 배출 지점 전수 — `"name":` 자리에 원천을 파생 없이 넣으면 그 화면에서만 광고가 샌다.
    #    관통 검사(④)만으로는 못 잡는다: 그 견적에 꼬리 달린 부품이 우연히 안 뽑히면
    #    조용히 통과한다(실제로 150만원 견적 24행에 한 건도 없었다). 관계로 고정한다 —
    #    **고객 모듈에서 product_name 을 name 으로 내보내는 줄은 전부 display_name 을 거친다.**
    leaky = []
    for fn in ("recommend.py", "swap.py", "orders.py"):
        for i, ln in enumerate(open(os.path.join(ROOT, "api", fn),
                                    encoding="utf-8").read().splitlines(), 1):
            if '"name":' in ln and "product_name" in ln and "display_name" not in ln:
                leaky.append(f"{fn}:{i}")
    check("[42] 고객 모듈의 name 배출이 전부 파생을 거친다", not leaky, "없음", leaky)

    # ① 단일 원천 — 파생을 다른 곳에서 또 구현하지 않는다
    dup = []
    for fn in ("recommend.py", "swap.py", "orders.py", "candidates.py"):
        p = os.path.join(ROOT, "api", fn)
        if not os.path.exists(p):
            continue
        src = open(p, encoding="utf-8").read()
        if "회원가입" in src:
            dup.append(fn)
    check("[42] 파생 규칙이 product_name.py 밖에 없다", not dup, "없음", ", ".join(dup) or "-")

    # ② 규칙 자체 — 부품 정보는 지우지 않는다
    check("[42] 판매조건 꼬리를 걷는다",
          display_name("인텔 코어i3 12세대 12100F (벌크) 회원가입 계좌이체 맞춤할인 2.5%")
          == "인텔 코어i3 12세대 12100F (벌크)", "꼬리 제거", "미제거")
    check("[42] 유통 형태는 보존한다((정품)·(벌크)·(멀티팩))",
          display_name("AMD 라이젠7 9700X (멀티팩(정품))") == "AMD 라이젠7 9700X (멀티팩(정품))",
          "원본 유지", "훼손")
    check("[42] 잘라서 이름이 없어지면 자르지 않는다",
          display_name("회원가입 계좌이체 맞춤할인 2.5%") == "회원가입 계좌이체 맞춤할인 2.5%",
          "원본 유지", "빈 이름")
    check("[42] None·빈 문자열에 죽지 않는다",
          display_name(None) is None and display_name("") == "", "그대로", "예외")

    # ③ 원천 전량 — 파생 결과에 꼬리가 남지 않는다(예외 제외)
    kept = db_one("SELECT COUNT(*) FROM products WHERE product_name LIKE '%회원가입%'")
    if kept is None:
        check("[42] 원천 대조", True, "DB 미접속 — 건너뜀", "건너뜀", kind="SKIP")
    else:
        rows = []
        with _engine.connect() as c:
            rows = [r[0] for r in c.execute(text(
                "SELECT product_name FROM products WHERE product_name LIKE '%회원가입%'")).all()]
        leaked = [n for n in rows if "회원가입" in display_name(n) and display_name(n) != n]
        check(f"[42] 원천 {len(rows)}건 파생 후 꼬리 잔존 없음", not leaked, 0, len(leaked))
        exempt = [n for n in rows if display_name(n) == n]
        # 2026-08-16: 오늘부터 꼬리가 대괄호로 감싸이며(`[회원가입 …]`) 예외 판정이 뚫렸다.
        # "원천이 통째로 광고"인 예외는 이제 "회원가입"으로 시작하거나 "[회원가입"으로
        # 시작하거나 둘 다다 — 문자열 시작 형태가 아니라 **판정 근거(못 잘랐다는 사실)**가
        # 예외인지를 정하므로, 여기서는 두 형태 모두 정당한 예외로 받는다.
        check(f"[42] 자를 수 없는 예외 {len(exempt)}건 — 전부 원천이 통째로 광고",
              all(n.startswith(("회원가입", "[회원가입")) for n in exempt), "전부",
              [n[:20] for n in exempt if not n.startswith(("회원가입", "[회원가입"))])

    # ④ 파생이 못 푸는 결함은 **게이트가 막는다** — 이름 없는 부품이 견적에 들어가면
    #    고객은 무엇을 사는지 알 수 없다. 123034(원천이 통째로 광고)를 검수 회부해 뺐고,
    #    같은 것이 다음 적재로 또 들어오면 여기서 잡힌다. 고정 건수가 아니라 관계다.
    #
    #    2026-08-16: 게이트가 `LIKE '회원가입%'`(문자열이 그 낱말로 **시작**해야 매치)였는데,
    #    오늘부터 새 형태는 `[회원가입…]`(대괄호로 시작)이라 이 게이트가 841건을 전부
    #    놓쳤다. `%회원가입%`로 넓히되, "문자열 시작"이라는 형태 판정 대신
    #    **display_name() 이 실제로 못 자르는지**(원본과 동일하게 돌아오는지)를 직접
    #    본다 — 정상적으로 잘리는 후보(대부분)까지 걸리면 안 되기 때문이다.
    cand_ad = db_all("SELECT product_code, product_name FROM v_recommendation_candidates"
                      " WHERE product_name LIKE '%회원가입%'")
    if _engine is None:
        check("[42] 이름 없는 후보 검사", True, "DB 미접속 — 건너뜀", "건너뜀", kind="SKIP")
    else:
        uncuttable = [r["product_code"] for r in cand_ad
                      if display_name(r["product_name"]) == r["product_name"]]
        check(f"[42] 이름이 통째로 판매조건인 추천 후보 없음 (원천에 꼬리 있는 후보 {len(cand_ad)}건 대조)",
              not uncuttable, 0, uncuttable)

    # ④' (신설, 2026-08-16) — 「지웠는데 껍데기가 남았다」를 직접 본다.
    #    이번 사고의 본질은 완전 실패(③·④가 본다)가 아니라 **부분 실패**였다: 여는
    #    대괄호가 "회원가입" 앞에 있어 매치 밖으로 새고, 잘린 결과가 `…파워 [` 처럼
    #    대괄호 하나만 매달린 채 나갔다. 그런 잔해를 보는 검사가 기존에 하나도 없었다
    #    (③은 "회원가입"이 남았는지만 보고, ④는 완전 미절단만 본다). 후보 뷰
    #    **전체**(추천 + 주변기기)를 대상으로, 파생 후 대괄호가 홀로 남거나 개수가
    #    어긋나는지를 관계로 본다 — 고정 건수가 아니다.
    residue_rows = db_all(
        "SELECT product_code, product_name FROM v_recommendation_candidates"
        " WHERE product_name LIKE '%회원가입%'"
        " UNION"
        " SELECT product_code, product_name FROM v_companion_candidates"
        " WHERE product_name LIKE '%회원가입%'")
    if _engine is None:
        check("[42] 후보 뷰 파생 잔해 검사", True, "DB 미접속 — 건너뜀", "건너뜀", kind="SKIP")
    else:
        def _has_residue(n):
            d = display_name(n)
            # 홀로 남은 여는 대괄호(오늘의 실제 증상) + 일반적인 대괄호 개수 불일치(안전망).
            # 닫는 대괄호로 끝나는 것은 걸지 않는다 — `[32G x 4]`처럼 정당한 대괄호도
            # 흔히 그렇게 끝난다(개수가 맞으면 정당한 것으로 본다).
            return ("회원가입" in d) or d.rstrip().endswith("[") \
                or (d.count("[") != d.count("]"))
        residue = [r["product_code"] for r in residue_rows if _has_residue(r["product_name"])]
        check(f"[42] 추천·주변기기 후보 {len(residue_rows)}건, 파생 후 대괄호·꼬리 잔해 없음",
              not residue, 0, residue)

    # ⑤ 관통 — 고객 응답(견적·대안·연쇄)에 꼬리가 없다
    TAILS = ("회원가입", "맞춤할인", "현금할인", "할인쿠폰")
    _, rec = post("/api/recommend", {"mode": "guided",
                  "constraints": [{"l": "용도", "v": "게임"}, {"l": "예산", "v": "150만원"}]})
    names = [(t, it["name"]) for t, s in (rec.get("sets") or {}).items()
             for it in (s or {}).get("items") or []]
    # 접근 게이트(0055) — 열쇠를 실어야 대안이 내려온다. 안 실으면 403이라 아래
    # 표본이 견적 24건만 남아, 「이름에 꼬리가 없다」 검사가 **거의 헛돌게 된다**
    # (실측: 열쇠 없이 24건 vs 열쇠 있으면 2,587건). 바로 다음 검사가 그 헛돎을 잡는다.
    st, cand = post("/api/swap/candidates",
                    {"session_id": rec["session_id"], "tier": "recommend",
                     "access_key": rec.get("access_key")})
    for slot, v in (cand.get("slots") or {}).items():
        for a in v.get("alternatives") or []:
            names.append((slot, a["name"]))
            for ch in a.get("chain") or []:
                names.append((slot, ch["to"]["name"]))
                names.append((slot, ch["from"]["name"]))
    # 이름이 통째로 광고인 상품은 여기서 세지 않는다 — 그건 ④가 게이트로 잡는 다른 결함이다.
    # 둘을 섞으면 실패 메시지가 "파생이 샜다"인지 "게이트가 뚫렸다"인지 구분되지 않는다.
    # 2026-08-16: 그 예외 형태가 "회원가입"으로 시작하는 것 말고 "[회원가입"으로 시작하는
    # 것도 생겼다(위 ③·④와 같은 이유) — 여기서도 같이 받아야 같은 상품이 두 검사에서
    # 서로 다른 이름(파생 실패/게이트 뚫림)으로 중복 보고되지 않는다.
    leak = [(s, n) for s, n in names
            if any(t in n for t in TAILS) and not n.startswith(("회원가입", "[회원가입"))]
    check(f"[42] 고객 응답 이름 {len(names)}건에 판매조건 꼬리 없음",
          not leak, 0, leak[:3])
    check("[42] 응답 표본이 비어 있지 않다(검사가 헛돌지 않는다)",
          len(names) > 100, "> 100건", len(names))


def test_rebuild_screens():
    """[41] 재구축 화면(`/admin2/*`) 계약 — **렌더 결과**를 검사한다 (P-08 · 2026-08-10)

    ■ 왜 새 그룹인가
      기존 마크업 검사는 `mockups/admin/*.html` 을 **파일로 읽는다.** 재구축 화면은
      Jinja2 라 파일에는 `{% extends %}` 조각만 있고 **완성 HTML 은 서버가 렌더한 뒤에만
      존재한다.** 즉 기존 방식으로는 재구축 화면을 **한 줄도 못 지킨다** — 화면이
      쌓이기 전에 옮기지 않으면 검증 없는 화면이 늘어난다.

    ■ 여기서 지키는 것은 **계약**이지 수치가 아니다
      화면 수치는 JS 가 API 를 불러 그린다. 정적 HTML 에는 없다.
      수치 대조는 브라우저 검증의 몫이고(P-08 §검증), 회귀는 **구조 계약**을 본다.
    """
    print(chr(10) + "[41] 재구축 화면 계약 — 렌더 결과를 검사한다")

    import re as _re41
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from api.admin_nav import NAV, counts as nav_counts, nav_for

    # "/admin2/" 의 화면 ID는 ADM-DASH-010 이다 — decision-log UX-22(2026-08-14)가
    # "구 NEW-DASH-010 정정(유래가 불확실한 폐기 개념의 잔재였다)"이라고 명시했다.
    # 실제 화면(api/admin_ui_home.py)도 ADM-DASH-010 이다. 여기 있던 NEW-DASH-010은
    # 그 정정을 반영하지 못한 낡은 기대값이었다(2026-08-15 회귀 감사에서 발견).
    SCREENS = [("/admin2/", "ADM-DASH-010"), ("/admin2/products", "ADM-PRD-010"),
               ("/admin2/spec-standard", "ADM-STD-010"),
               ("/admin2/build-map", "ADM-STD-020")]

    for path, screen_id in SCREENS:
        st, html = get_html(path)
        check(f"[41] {path} 200", st == 200, 200, st)
        if st != 200:
            continue

        # ① 화면 정체성 — 규약(`data-screen-id`/`data-domain`)이 렌더 결과에 있어야 한다
        check(f"[41] {path} data-screen-id={screen_id}",
              f'data-screen-id="{screen_id}"' in html, screen_id, "없음")
        check(f"[41] {path} data-domain 있음", "data-domain=" in html, "있음", "없음")

        # ② **admin-menu.js 를 싣지 않는다** — 실으면 서버가 그린 LNB 를 지우고
        #    옛 6그룹으로 덮어쓴다. 주석으로만 막아 두면 다음 사람이 다시 넣는다.
        check(f"[41] {path} admin-menu.js 미로드",
              "/shared/admin-menu.js" not in html, "미로드", "로드됨")

        # ③ Phoenix 데모 잔재가 없다 — 기존 36화면에 남아 있던 것들
        for leak in ("Purchase template", "Demo widget", "Ask us anything"):
            check(f"[41] {path} 데모 잔재 없음 ({leak})", leak not in html, "없음", "있음")

        # ④ 참조한 자산이 실재한다 — 404 를 브라우저는 **조용히 넘어간다**
        #    (슬라이스 100: theme.css 를 참조한 세 화면이 스타일 없이 이틀 돌았다)
        refs = set(_re41.findall(r'(?:src|href)="(/(?:admin|shared|design-system)/[^"?#]+)"', html))
        missing = []
        for ref in sorted(refs):
            if ref.startswith("/admin/"):
                p = pathlib.Path(ROOT, "mockups", "admin", ref[len("/admin/"):])
            elif ref.startswith("/shared/"):
                p = pathlib.Path(ROOT, "mockups", "shared", ref[len("/shared/"):])
            else:
                p = pathlib.Path(ROOT, "design-system", ref[len("/design-system/"):])
            if not p.exists():
                missing.append(ref)
        check(f"[41] {path} 참조 자산 실재 ({len(refs)}개)",
              not missing, "전부 있음", ", ".join(missing[:3]) or "-")

        # ⑤ LNB 는 IA(admin_nav.NAV)와 같아야 한다 — 화면이 메뉴를 다시 품지 않는다.
        #   **셈은 마크업에 묶지 않는다.** 지킬 계약은 «IA 전체가 나온다»이지 클래스명이
        #   아니다. 전체 화면 셸(ADM-STD-020)은 Phoenix 레이아웃을 상속하지 않아
        #   `nav-link-text` 가 없다 — 그때 0을 세고 실패하면 검사가 사실이 아니라
        #   구현 방식을 지키는 것이 된다.
        #
        #   2026-08-13 셸 정본화로 그룹 헤더 클래스가 `lnb-g` → `a2-lnb-g` 로 바뀌었는데
        #   이 검사는 옛 이름을 그대로 찾아 그룹 헤더 8개를 통째로 못 세고 45 대신 37을
        #   냈다(제작팀 B 실측 — `a2-lnb-g` 8건 매치=그룹 수와 일치, `lnb-g` 0건). 게다가
        #   링크 셈이 **문서 전체**에서 `<a href="…" class="…">` 를 찾고 있어서, 상품 관리
        #   화면은 39(11 대신 13 링크)가 나왔다 — LNB 밖 "상품 단건 등록" 버튼과 목록 행을
        #   그리는 JS 템플릿 리터럴(`<a href="…?code=${p.product_code}" class="name …">`,
        #   서버 렌더 시점엔 아직 문자열이라 그대로 남아 있다)이 같은 정규식에 걸렸다.
        #   **원인은 검사의 기대값(45)이 아니라 검사가 셈을 문서 전체에서 한 것이었다** —
        #   그래서 화면 콘텐츠에 링크가 늘 때마다 이 검사는 다시 낡을 소지가 있었다.
        #
        #   고친 것: (a) 셈을 **`<nav id="lnb">…</nav>` 안쪽으로 한정**해 화면 본문의
        #   링크를 원천 차단한다. (b) 그룹 헤더는 **클래스명이 아니라
        #   `data-action="lnb-group"`** (admin2-shell.js 가 아코디언 토글을 붙잡는 훅)로
        #   센다 — CSS 클래스는 이름만 바꿔도 조용히 깨지지만, 이 속성이 바뀌면 메뉴가
        #   안 접혀 눈에 바로 띈다. (c) 링크는 `class=` 인접을 요구하지 않고 `<a href="`
        #   자체만 센다 — 속성 순서가 바뀌어도 안 흔들린다.
        #   **그래도 여전히 마크업을 정규식으로 센다** — `_admin2_shell.html.j2` 가
        #   `<nav>` 를 더 쓰거나 LNB 의 `id="lnb"` 를 바꾸면 이 판정도 다시 낡는다
        #   (그때는 `nav_m is None` 이 되어 items=0 으로 요란하게 실패한다 — 조용히
        #   넘어가지는 않는다).
        nav_m = _re41.search(r'<nav\b[^>]*\bid="lnb"[^>]*>(.*?)</nav>', html, _re41.DOTALL)
        nav_html = nav_m.group(1) if nav_m else ""
        items = (len(_re41.findall(r'<span class="nav-link-text">', html))     # Phoenix 레이아웃(구 _layout.html.j2)
                 or (len(_re41.findall(r'data-action="lnb-group"', nav_html))  # 자체 셸 — 그룹 헤더(JS 훅)
                     + len(_re41.findall(r'class="off"', nav_html))            #          준비 중
                     + len(_re41.findall(r'<a\s+href="', nav_html))))          #          링크 있는 항목

        # ⚠ 2026-08-25 정정 — `want` 를 `NAV` 고정식에서 **`nav_for()` 실제 반환 구조**로
        #   바꿨다(기대 49 / 실제 92, 4건 실패로 발견). 옛 식 `nav_counts()["total"] +
        #   len(NAV)`(41 항목 + 8 그룹)은 `NAV` 리스트 하나만 셌는데, 템플릿이 실제로
        #   그리는 것은 `NAV` 가 아니라 `render()`(api/admin_ui_common.py)가 건네는
        #   `nav_for(request.url.path)` 다 — 그리고 `nav_for()` 는 「운영자 매뉴얼」
        #   합성 그룹 하나를 그 뒤에 더 붙인다(`admin_nav._manual_nav_group()`,
        #   2026-08-25 신설). 그룹도 항목도 실제로 더 그려지는데 기대값은 그 사실을
        #   몰랐다 — **검사가 낡은 것이지 화면이 틀린 게 아니었다.**
        #   고친 원칙: 마크업을 다시 세지 않고 **`nav_for()` 가 돌려주는 구조를 그대로
        #   센다** — 템플릿이 `{% for g in nav %}…{% for it in g.items %}` 로 그 구조를
        #   그대로 그리므로(그룹 1개당 `data-action="lnb-group"` 1개, 항목 1개당
        #   `<a href=` 또는 `class="off"` 1개 — 위 `items` 계산과 같은 분기), 그룹 수 +
        #   전 그룹 항목 수 합이 렌더 결과와 정확히 같다. **숫자를 다시 박지 않는다** —
        #   매뉴얼 그룹은 `NAV` 의 41화면을 "그룹명 · 화면명"으로 그대로 편 것 + "전체
        #   목차" 1행이라, `NAV` 가 늘면 매뉴얼 그룹 항목 수도 같이 는다(지금 매뉴얼
        #   조각은 1개뿐이지만 그 수는 `<a href=`/`class="off"` 어느 쪽으로 세든 항목
        #   1개는 1개다 — 조각이 41개로 늘어도 이 합계식은 그대로 성립한다).
        groups = nav_for(path)
        want = len(groups) + sum(len(g["items"]) for g in groups)
        check(f"[41] {path} LNB 항목 수 = IA", items == want, want, items)

    # ⑥ 견본 배너와 실데이터 배지가 **한 화면에 같이 있으면 안 된다**
    #    반쪽 상태를 뭉뚱그리면 예시값이 우리 것으로 읽힌다(2026-08-09 실사고).
    st, html = get_html("/admin2/")
    if st == 200:
        sample = "레이아웃 견본" in html
        live = "실데이터 · Cloud SQL" in html
        check("[41] 견본 배너와 실데이터 배지 공존 금지",
              not (sample and live), "둘 중 하나", "둘 다 있음")

    # ⑦ NAV 자체의 무결성 — 링크 없는 항목은 '준비 중'이어야 하고, 중복 라벨이 없어야 한다
    labels = [it[0] for _t, _ic, items in NAV for it in items]
    dup = sorted({x for x in labels if labels.count(x) > 1})
    check("[41] NAV 라벨 중복 없음", not dup, "없음", ", ".join(dup) or "-")

    # `old` 폐지(2026-08-12 전면 재구축 확정) — 합계식도 두 항이다
    c = nav_counts()
    check("[41] NAV 합계 = new+todo",
          c["total"] == c["new"] + c["todo"],
          c["total"], c["new"] + c["todo"])


def test_lock_scope():
    """[44] 잠금 범위 확대 — 사양·분류·검수 플래그까지 (2026-08-16 사장님 지시)

    **왜 새 함수인가.** 이전에는 잠금(`locked_fields`)이 지키는 것이 매입가·판매가
    둘뿐이었다 — 같은 UPSERT의 나머지 14개 컬럼은 무조건 EXCLUDED였다. 실사고 둘:
    `0031_built_pc_axis.py`가 완제품·베어본을 ETC에서 올려놓은 뒤 2026-08-15 몰
    적재(job 25, 24,721행)가 340건을 다시 ETC로 되돌렸고, 상품 123034는 검수로
    회부된 채(review_id=8193, 대기)인데 적재가 review_required_yn을 재계산해
    후보로 되돌렸다.

    **왜 이 방식인가 — apply_plan()을 실행하지 않는다.** "회귀는 정본을 쓰지
    않는다"(슬라이스 50 — 업로드 dryrun 검사가 apply까지 돌려 시드 상품 하나를
    테스트 값으로 덮은 전례)는 폐기할 수 없는 규약이다. 그래서 세 갈래로 나눠
    **쓰기 없이** 검증한다:
      ① 정적 SQL 검사 — UPSERT 문자열 자체에 잠금 가드가 있는지(문자열만 본다.
         DB에도 닿지 않는다)
      ② EXPLAIN — 고친 SQL이 실제 스키마에 문법적으로 맞는지. `EXPLAIN`(ANALYZE
         아님)은 계획만 세우고 **실행하지 않는다** — Postgres 문서 그대로, 데이터를
         전혀 건드리지 않는다. 그래도 트랜잭션을 열고 명시적으로 rollback한다(안전벨트).
      ③ `build_plan()` 순수 함수 검사 — 이 함수는 **DB를 건드리지 않는다**
         (모듈 docstring이 이미 그렇게 선언하고 있다). 합성 입력을 직접 만들어 호출하고
         반환된 계획(딕셔너리)만 본다 — 실제 DB에 쓰는 건 apply_plan()이고 여기서는
         한 번도 부르지 않는다.
      ③-b 실제 DB의 잠금 데이터(388개 상품 · 562건, 실측)를 **읽기만** 해서
         (`read_refs()`는 SELECT뿐이다) 진짜 사양명·part_type으로 합성 CSV 행을
         만들고, 거기에 "현재 값과 확실히 다른" 더미 EAV 값을 주입해 build_plan을
         두 번(잠금 있음/없음) 돌려 비교한다. **DB에는 여전히 아무것도 쓰지 않는다**
         — build_plan은 순수 함수이고 이 검사는 apply_plan을 부르지 않는다.
    """
    print("\n[44] 잠금 범위 확대 — 사양·분류·검수 플래그까지 (2026-08-16)")
    import re as _re44

    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from api import catalog_ingest as ci
    except Exception as e:                               # noqa: BLE001
        print(f"  [SKIP] (I) 잠금 범위 — api.catalog_ingest import 실패: {e}")
        return

    # ── ① 정적 SQL 검사 — 문자열만 본다, DB 미접속이어도 항상 돈다 ──────────────
    sql = ci.UPSERT_PRODUCTS_SQL
    for col in ci.LOCK_AWARE_PRODUCT_COLS:
        guarded = _re44.search(
            r"\b" + _re44.escape(col) + r"\s*=\s*CASE WHEN products\.locked_fields \? '"
            + _re44.escape(col) + "'", sql) is not None
        check(f"[44] products UPSERT가 {col} 잠금을 확인한다(정적 SQL 검사)", guarded,
              "CASE WHEN 가드 있음", "없음 — 이 컬럼은 잠겨도 재적재가 덮는다")
    n_guards = len(_re44.findall(r"CASE WHEN products\.locked_fields \?", sql))
    check("[44] 잠금 가드 수 = LOCK_AWARE_PRODUCT_COLS 수"
          "(어긋나면 목록에 없는 컬럼이 가드를 갖고 있거나 그 반대다)",
          n_guards == len(ci.LOCK_AWARE_PRODUCT_COLS),
          len(ci.LOCK_AWARE_PRODUCT_COLS), n_guards)
    # stock_qty·status는 **의도적으로** 잠금 밖이다(재고·판매상태는 몰의 실시간 값을
    # 옮겨 적은 것이라 영구히 얼리면 없는 물건을 팔거나 재입고를 계속 감춘다 — 근거는
    # UPSERT_PRODUCTS_SQL 모듈 상수 주석). 그 결정이 조용히 뒤집히는지(가드가 생겼다
    # 없어졌다 하는지) 이 검사가 지킨다 — 실패하면 코드가 결정과 달라졌다는 뜻이다.
    check("[44] stock_qty는 의도적으로 잠금 대상 밖이다(무조건 EXCLUDED — 재고는 원장 소관)",
          "stock_qty = EXCLUDED.stock_qty" in sql, "무조건 갱신", "가드가 생겼다")
    check("[44] status는 의도적으로 잠금 대상 밖이다(무조건 EXCLUDED — 몰의 실시간 판매상태)",
          _re44.search(r"\bstatus = EXCLUDED\.status\b", sql) is not None,
          "무조건 갱신", "가드가 생겼다")

    # ── ② EXPLAIN — SQL이 실제 스키마에 문법적으로 맞는가 (쓰기 없음) ───────────
    if _engine is None:
        print("  [SKIP] (I) [44] UPSERT SQL 파싱(EXPLAIN) — DB 미연결: " + _db_why)
    else:
        prod_params = {"pc": -1, "sku": "회귀", "name": "회귀", "maker": None, "model": None,
                       "pt": "ETC", "grp": "etc", "status": "판매중", "ai": False, "rev": True,
                       "pp": None, "sp2": None, "mp": None, "sup": None, "dan": None,
                       "stock": 0, "spec_text": None, "origin": "real"}
        spec_params = {"pc": -1, "pt": "CPU", "sources": "{}"}
        spec_params.update({c: None for c in ci.SPEC_COLS})
        with _engine.connect() as c:
            err1 = err2 = None
            tx = c.begin()
            try:
                c.execute(text("EXPLAIN " + ci.UPSERT_PRODUCTS_SQL), prod_params)
            except Exception as e:                       # noqa: BLE001
                err1 = repr(e)
            finally:
                tx.rollback()          # EXPLAIN은 쓰지 않지만 안전벨트로 명시 롤백
            check("[44] products UPSERT가 실제 스키마에 문법적으로 맞는다(EXPLAIN, 쓰기 없음)",
                  err1 is None, "EXPLAIN 성공", err1 or "—")

            tx2 = c.begin()
            try:
                c.execute(text("EXPLAIN " + ci.UPSERT_SPECS_SQL), spec_params)
            except Exception as e:                       # noqa: BLE001
                err2 = repr(e)
            finally:
                tx2.rollback()
            check("[44] product_specs UPSERT가 실제 스키마에 문법적으로 맞는다(EXPLAIN, 쓰기 없음)",
                  err2 is None, "EXPLAIN 성공", err2 or "—")

    # ── ③ build_plan 순수 함수 검사 — DB에 한 번도 쓰지 않는다 ──────────────────
    def _row(code, name, l2):
        return {"자체상품코드": str(code), "상품명": name, "카테고리1": "PC/주요부품",
                "카테고리2": l2, "카테고리3": "인텔", "상태값": "판매중", "매입가": "10000",
                "일반회원": "20000", "시중가": "30000", "공급처": "회귀", "스펙": "",
                "제조사": "테스트", "모델명": "회귀모델", "다나와No": ""}

    # 회귀 전용 가짜 코드 — DB에 없는 값이라 실제 상품과 절대 겹치지 않는다
    A, B, C = 919990001, 919990002, 919990003
    rows = [_row(A, "회귀 잠금 A", "프로세서(CPU)"), _row(B, "회귀 잠금 B", "프로세서(CPU)"),
            _row(C, "회귀 잠금 C", "프로세서(CPU)")]
    kvs = {str(A): {"소켓 형태": "AM5"}, str(B): {"소켓 형태": "AM5"},
           str(C): {"소켓 형태": "AM5"}}
    # A=검수 승인 경로 표기('specs.'접두어) · B=사양 PATCH 경로 표기(맨 이름) · C=잠금 없음(대조군)
    refs = {"gpu_ref": {}, "dan_owner": {}, "existing": {},
            "locked": {A: ["specs.socket"], B: ["socket"]}}
    plan = ci.build_plan(rows, kvs, {}, refs, "real")
    sp = {s["pc"]: s for s in plan["specs"]}
    check("[44] build_plan — CSV에 값이 있어도 'specs.'접두어로 잠긴 사양은 계획에 안 오른다"
          "(검수 승인 경로 표기)",
          sp.get(A, {}).get("socket") is None, None, sp.get(A, {}).get("socket"))
    check("[44] build_plan — CSV에 값이 있어도 맨 이름으로 잠긴 사양은 계획에 안 오른다"
          "(사양 PATCH 경로 표기)",
          sp.get(B, {}).get("socket") is None, None, sp.get(B, {}).get("socket"))
    check("[44] build_plan — 대조군: 잠기지 않았으면 그대로 뽑힌다"
          "(위 두 결과가 억지로 None인 게 아님을 증명)",
          sp.get(C, {}).get("socket") == "AM5", "AM5", sp.get(C, {}).get("socket"))

    # ── ③-b 실제 DB의 잠금 388건을 대상으로 대규모 대조 — 읽기만 한다 ───────────
    # docs/상품다운_2026-08-15_병합_24721.csv 자체는 EAV가 없어(파일 실측) 대부분
    # 필드가 애초에 안 뽑힌다(위험이 우연히 0으로 나와 "보호됐다"는 착시를 준다).
    # 그래서 실제 잠긴 상품의 진짜 part_type·상품명을 그대로 쓰되, 그 종류가 실제로
    # 읽는 EAV 키에 "지금 값과 다른 게 확실한" 더미 값을 주입해 진짜 충돌을 강제로
    # 만든다. 이러면 "잠금이 없었다면 정말 덮였을 것"만 골라 그 보호 여부를 잰다.
    if _engine is None:
        print("  [SKIP] (I) [44] 실제 잠금 데이터 대조 — DB 미연결: " + _db_why)
        return
    KV_KEY = {
        ("CPU", "tdp_watt"): ("열 설계 전력(TDP)", "999"),
        ("CPU", "socket"): ("소켓 형태", "ZZ9999"),
        ("RAM", "capacity_gb"): ("메모리 용량", "999(GB)"),
        ("RAM", "clock_mhz"): ("동작 클럭", "9999"),
        ("GPU", "length_mm"): ("길이", "999"),
        ("GPU", "required_power_watt"): ("권장파워", "9999"),
        ("POWER", "rated_watt"): ("정격출력", "9999"),
        ("CASE", "gpu_max_mm"): ("VGA장착길이", "999"),
        ("CASE", "cooler_height_mm"): ("CPU쿨러장착높이", "999"),
        ("COOLER_CPU_AIR", "cooler_height_mm"): ("높이", "999"),
        ("COOLER_CPU_AIR", "cooler_tdp"): ("TDP", "9999"),
        ("COOLER_CPU_AIO", "cooler_tdp"): ("TDP", "9999"),
        ("SSD", "capacity_gb"): ("용량", "9999(GB)"),
        ("HDD", "capacity_gb"): ("용량", "9999(GB)"),
        ("MONITOR", "refresh_hz"): ("주사율", "999"),
        ("MONITOR", "resolution"): ("해상도", "ZZZ해상도"),
        ("MONITOR", "panel"): ("패널", "ZZZ패널"),
    }
    PT_TO_L2 = {"CPU": "프로세서(CPU)", "MB": "메인보드(M\\B)", "RAM": "메모리(RAM)",
                "GPU": "그래픽카드(VGA)", "POWER": "파워(POWER)", "CASE": "케이스(CASE)",
                "SSD": "고속저장(SSD)", "HDD": "저장장치(HDD)"}

    with _engine.connect() as conn:
        refs_real = ci.read_refs(conn)
        locked_rows = conn.execute(text(
            "SELECT product_code, part_type, product_name FROM products"
            " WHERE jsonb_array_length(locked_fields) > 0")).mappings().all()

    spec_col_set = set(ci.SPEC_COLS)
    targets = []
    for r in locked_rows:
        pc, pt, name = r["product_code"], r["part_type"], r["product_name"]
        for f in (refs_real["locked"].get(pc) or []):
            bare = f[len("specs."):] if f.startswith("specs.") else f
            if bare in spec_col_set and (pt, bare) in KV_KEY:
                targets.append((pc, pt, name, bare))

    if not targets:
        print("  [SKIP] (I) [44] 실제 잠금 데이터 대조 — 강제 충돌시킬 대상 없음"
              "(잠긴 사양이 없거나 전부 KV_KEY 밖의 필드)")
        return

    rows2, kvs2 = [], {}
    for pc, pt, name, field in targets:
        skey = str(pc)
        l2 = PT_TO_L2.get(pt, "")
        rows2.append({"자체상품코드": skey, "상품명": name or f"상품{pc}",
                      "카테고리1": "PC/주요부품" if l2 else "기타", "카테고리2": l2,
                      "카테고리3": "", "상태값": "판매중", "매입가": "1000",
                      "일반회원": "2000", "시중가": "3000", "공급처": "회귀검증",
                      "스펙": "", "제조사": "", "모델명": "", "다나와No": ""})
        key, dummy = KV_KEY[(pt, field)]
        kvs2.setdefault(skey, {})[key] = dummy

    plan_prot = ci.build_plan(rows2, kvs2, {}, refs_real, "real")
    refs_unlocked = dict(refs_real)
    refs_unlocked["locked"] = {}
    plan_unprot = ci.build_plan(rows2, kvs2, {}, refs_unlocked, "real")
    sp_prot = {s["pc"]: s for s in plan_prot["specs"]}
    sp_unprot = {s["pc"]: s for s in plan_unprot["specs"]}

    would_overwrite, protected_ok, leaked = 0, 0, []
    for pc, pt, name, field in targets:
        unprot_val = (sp_unprot.get(pc) or {}).get(field)
        if unprot_val is None:
            continue                    # 이 상품은 이번 합성 CSV로 분류가 안 살았거나 추출 실패 — 대상 밖
        would_overwrite += 1
        prot_val = (sp_prot.get(pc) or {}).get(field)
        if prot_val is None:
            protected_ok += 1
        else:
            leaked.append({"product_code": pc, "field": field, "part_type": pt,
                          "protected_value": prot_val})
    check(f"[44] 실제 잠금 상품 중 강제 충돌시킨 {would_overwrite}건이 전부 보호된다"
          "(잠금 없었으면 실제로 덮였을 값을 만들어 확인 — DB에는 안 씀)",
          would_overwrite > 0 and leaked == [], "0건 누락", leaked[:5] or f"충돌 대상 {would_overwrite}건")
    check("[44] 이 검사가 실제로 뭔가를 시험했다(충돌 0건이면 위 결과가 무의미하다)",
          would_overwrite > 0, "> 0", would_overwrite)


# ─────────────────────── [46]~[50] 검사 공백 메우기 (2026-08-25) ───────────────────────
# 오늘 고친 다섯(팀원 한글명 배너·모델 필터 정본화·한도 되돌리기·공급처 122곳·배분
# 상한 정직화)에 자동 검사가 하나도 없었다(확인자 실측). 값이 아니라 **관계**를 본다
# (A-13 그대로) — 개수를 박지 않고, 두 경로가 같은지·서버가 지어내지 않는지를 본다.


def test_dash_team_ko():
    """[46] 작업 현황판 — 팀원 한글명이 다 있는가 (2026-08-25 신설)

    `.claude/agents/*.md`가 팀원 정본이고 `api/dash.py`의 TEAM_KO는 표시용 사본이다
    (그 파일 docstring이 이미 "정본이 아니라 표시용"이라 밝힌다). 사본이라 낡을 수
    있다 — archivist·designchecker가 3주 가까이, 그다음 pathfinder가 또 같은 방식으로
    TEAM_KO에서 빠진 채 방치됐다(2026-08-15·2026-08-25 두 차례, api/dash.py 주석 실측).
    **같은 유형의 결함이 이미 두 번**이라 회귀에 고정한다 — 셋째 팀원이 또 빠지면
    이 검사가 잡는다.
    """
    print("\n[46] 작업 현황판 — 팀원 한글명 전수 (2026-08-25 신설)")
    agent_files = sorted(glob.glob(os.path.join(ROOT, ".claude", "agents", "*.md")))
    agent_names = sorted(os.path.splitext(os.path.basename(p))[0] for p in agent_files)
    check("[46] .claude/agents/*.md 팀원 정의 파일을 찾았다(0건이면 아래 비교가 무의미)",
          len(agent_names) > 0, "> 0", len(agent_names))
    if not agent_names:
        return

    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from api.dash import TEAM_KO

    missing = [n for n in agent_names if n not in TEAM_KO]
    check(f"[46] TEAM_KO가 정의된 팀원 {len(agent_names)}명({', '.join(agent_names)})을"
          " 전부 덮는다 — 빠지면 팀원 카드가 영문 이름 그대로 노출된다",
          not missing, "누락 없음", missing)

    # ── 자기검증: 이 비교 로직이 실제로 결함을 잡는지 — TEAM_KO **사본**에서 하나를
    # 지우고 같은 비교를 다시 돌린다. api/dash.py 파일 자체는 건드리지 않는다.
    victim = agent_names[-1]
    fake_team_ko = {k: v for k, v in TEAM_KO.items() if k != victim}
    sim_missing = [n for n in agent_names if n not in fake_team_ko]
    check(f"[46] 자기검증 — TEAM_KO 사본에서 '{victim}'을 지우면 이 비교가 실제로 잡는다"
          "(오늘 pathfinder 누락과 같은 상황을 재현 — api/dash.py는 건드리지 않음)",
          sim_missing == [victim], [victim], sim_missing)

    # ── 화면(GET /api/admin/dash/state)도 같은 판정을 서버 응답에 싣는다(조기경보 필드,
    # 2026-08-15 신설) — 정적 비교와 서버 판정 두 경로가 같은 결론을 내는지 본다.
    d = get("/api/admin/dash/state")
    check("[46] /api/admin/dash/state 응답에 team_unmapped 필드가 있다",
          isinstance(d, dict) and "team_unmapped" in d,
          "필드 있음", sorted(d.keys()) if isinstance(d, dict) else d)
    if isinstance(d, dict) and "team_unmapped" in d:
        check("[46] 서버가 판정한 team_unmapped가 정적 비교(TEAM_KO 누락)와 일치한다",
              sorted(d["team_unmapped"]) == sorted(missing), sorted(missing),
              sorted(d["team_unmapped"]))

    # ── 화면이 누락을 배너로 알리는 경로 — 정적 마크업 계약(브라우저 없이 검사) ──
    dash_tmpl = os.path.join(ROOT, "templates", "admin", "dash.html.j2")
    if os.path.exists(dash_tmpl):
        tmpl = io.open(dash_tmpl, encoding="utf-8").read()
        check("[46] 현황판에 팀원 한글명 누락 배너 마크업이 있다(hidden으로 미리 존재)",
              'data-bind="team-unmapped-banner"' in tmpl, "있음", "없음")
        check("[46] 배너가 서버 team_unmapped를 그대로 읽는다(화면이 지어내지 않는다)",
              "renderTeamUnmapped(d.team_unmapped)" in tmpl, "있음", "없음")
    else:
        check("[46] templates/admin/dash.html.j2 가 있다", False, "파일 있음", "없음")


def test_ai_response_log_models():
    """[47] AI 응답 기록 — 모델 필터가 api/llm.py PROVIDERS 정본을 읽는가 (2026-08-25 신설)

    화면의 「모델」 필터가 실측 모드에서도 클라이언트 미리보기 예시 배열에서만 옵션을
    뽑고 있었다(claude-opus-4-8·gemini-2.5-pro·gpt-5-codex — 전부 폐기된 세대, 실제
    로그가 쌓여도 그 이름으로 거르면 영원히 0건). 2026-08-25 정정으로
    `GET /api/admin/ai-response-log`가 `models`를 `api/llm.py`의 `PROVIDERS[...].pricing`
    키에서 직접 계산해 내려준다(api/admin_ai_logs.py). **개수를 박지 않는다** — 모델이
    늘거나 세대가 갈리면 이 검사가 스스로 새 기대값을 계산한다. 두 곳(API 응답 ↔
    PROVIDERS)이 같은지만 본다.
    """
    print("\n[47] AI 응답 기록 — 모델 필터 정본화 (2026-08-25 신설)")
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from api.llm import PROVIDERS as LLM_PROVIDERS

    expected = sorted({m for spec in LLM_PROVIDERS.values() for m in spec.pricing})
    check("[47] api/llm.py PROVIDERS에 모델이 실제로 있다(0건이면 아래 비교가 무의미)",
          len(expected) > 0, "> 0", len(expected))

    d = get("/api/admin/ai-response-log")
    got = sorted(d.get("models") or [])
    check("[47] AI 응답 기록의 모델 필터 목록 = api/llm.py PROVIDERS 단가표 키"
          "(개수를 박지 않는다 — 두 경로가 같은지만 본다)",
          got == expected, expected, got)

    # ── 자기검증 — 2026-08-25 발견 전까지 실제로 노출되던 폐기 모델명 3종은 지금
    # PROVIDERS가 주는 값과 다르다(같으면 위 비교가 그 결함을 못 잡는다는 뜻). ──
    stale = sorted(["claude-opus-4-8", "gemini-2.5-pro", "gpt-5-codex"])
    check("[47] 자기검증 — 2026-08-25 이전 폐기 모델명 3종은 지금 정본과 다르다"
          "(같았다면 위 비교가 그 결함을 구분하지 못했다는 뜻)",
          stale != expected, "다름(검사가 구분함)", stale if stale == expected else "다름")

    # ── 화면(측정 모드)이 서버 값을 읽는다 — 정적 계약(브라우저 없이 검사) ──
    tmpl_path = os.path.join(ROOT, "templates", "admin", "ai_response_log.html.j2")
    if os.path.exists(tmpl_path):
        tmpl = io.open(tmpl_path, encoding="utf-8").read()
        check("[47] 실측 모드의 모델 목록이 서버 값(S.server.models)을 읽는다"
              "(미리보기 예시 배열 S.demo가 아니다)",
              "S.server && S.server.models" in tmpl, "있음", "없음")
    else:
        check("[47] templates/admin/ai_response_log.html.j2 가 있다", False, "파일 있음", "없음")

    # ── 화면이 실제로 렌더되는가 — 서버 렌더 결과([41]과 같은 방식) ──
    st, html = get_html("/admin2/ai-response-log")
    check("[47] /admin2/ai-response-log 200", st == 200, 200, st)
    if st == 200:
        check("[47] data-screen-id=ADM-AI-060", 'data-screen-id="ADM-AI-060"' in html,
              True, 'data-screen-id="ADM-AI-060"' in html)


def test_ai_integration_limit_clear():
    """[48] AI 연동 설정 — 한도 되돌리기 왕복 (2026-08-25 신설)

    `DELETE /api/admin/ai-integration/limits/{provider}`가 2026-08-25 신설됐다
    (api/admin_ai_integration.py "■ 한도를 «미설정»으로 되돌리기" 참고) — 그 전에는
    POST로 한 번 세운 한도를 다시 미설정으로 되돌릴 방법이 코드 어디에도 없었다.
    한도를 세우고 → 지우고 → 실제로 null이 되는지 왕복으로 확인한다. 검사가 만든
    상태는 검사가 되돌린다(try/finally) — 이 프로바이더가 검사 시작 전에 미설정이면
    지운 상태가 곧 원상태라 되돌리기가 필요 없고, 무언가 설정돼 있었으면 그 값 그대로
    복원한다.
    """
    print("\n[48] AI 연동 설정 — 한도 되돌리기 왕복 (2026-08-25 신설)")
    PROVIDER = "codex"
    J = {"Content-Type": "application/json"}

    before_status = get("/api/admin/ai-integration/status")
    prov = next((p for p in (before_status or {}).get("providers", [])
                 if p["key"] == PROVIDER), None)
    check(f"[48] status 응답에 '{PROVIDER}' 프로바이더가 있다", prov is not None,
          PROVIDER, prov)
    if prov is None:
        return
    before = prov["limit"]

    def _restore():
        if before.get("daily_usd") is not None:
            restore_body = {"daily_usd": before["daily_usd"],
                             "per_minute": before.get("per_minute"),
                             "per_day": before.get("per_day"),
                             "action": before.get("action"),
                             "sub": {k: v for k, v in (before.get("sub") or {}).items()
                                     if v is not None}}
            post_raw(f"/api/admin/ai-integration/limits/{PROVIDER}",
                     json.dumps(restore_body).encode(), J)
        # else: 검사 시작 전부터 미설정이었다 — try 블록의 DELETE가 이미 그 상태를
        # 재현했으므로 되돌릴 것이 없다(POST는 daily_usd<=0을 거절해 "미설정"을
        # 직접 만들 방법이 없다 — 그래서 지운 상태가 곧 원상태다).

    try:
        st1, out1 = post_raw(
            f"/api/admin/ai-integration/limits/{PROVIDER}",
            json.dumps({"daily_usd": 5.0, "per_minute": 7, "per_day": 77,
                        "action": "warn", "sub": {}}).encode(), J)
        check("[48] 한도를 세울 수 있다(POST)", st1 == 200, 200, st1)
        check("[48] 세운 값이 응답에 그대로 실린다(daily_usd=5.0 — 검사가 실제로"
              " 상태를 바꿨는지 확인, 아니면 아래 DELETE 검사가 무의미하다)",
              (out1 or {}).get("limit", {}).get("daily_usd") == 5.0,
              5.0, (out1 or {}).get("limit", {}).get("daily_usd"))

        st2, out2 = post_raw(f"/api/admin/ai-integration/limits/{PROVIDER}",
                              None, {}, method="DELETE")
        check("[48] 한도를 지울 수 있다(DELETE)", st2 == 200, 200, st2)
        after = (out2 or {}).get("limit") or {}
        check("[48] 지운 뒤 daily_usd가 null이다(«유지»가 아니라 실제로 미설정으로"
              " 되돌아간다)", after.get("daily_usd") is None, None, after.get("daily_usd"))
        check("[48] 지운 뒤 per_minute·per_day·action도 전부 null이다",
              after.get("per_minute") is None and after.get("per_day") is None
              and after.get("action") is None,
              "전부 null", {"per_minute": after.get("per_minute"),
                           "per_day": after.get("per_day"),
                           "action": after.get("action")})
        check("[48] 작업별 부분 한도(sub)도 전부 null이다",
              bool(after.get("sub")) and all(v is None for v in after["sub"].values()),
              "전부 null", after.get("sub"))

        # ── 원천 대조 — API 말과 실제 저장이 같은지, DB에도 정말 행이 없는지 ──
        cnt = db_one("SELECT COUNT(*) FROM cost_thresholds WHERE key = :k OR key LIKE :pfx",
                     k=PROVIDER, pfx=f"{PROVIDER}:%")
        if cnt is None:
            print("  [SKIP] (I) [48] DB 원천 대조 — DB 미연결: " + _db_why)
        else:
            check("[48] cost_thresholds에 이 프로바이더 행이 실제로 없다(DB 원천 대조)",
                  cnt == 0, 0, cnt)
            cnt2 = db_one("SELECT COUNT(*) FROM rate_limit_policies WHERE key = :k", k=PROVIDER)
            check("[48] rate_limit_policies에도 행이 없다(DB 원천 대조)", cnt2 == 0, 0, cnt2)

        # ── 멱등성 — 이미 미설정인데 다시 지워도 실패하지 않는다 ──
        st3, out3 = post_raw(f"/api/admin/ai-integration/limits/{PROVIDER}",
                              None, {}, method="DELETE")
        check("[48] 이미 미설정인데 다시 지워도 실패하지 않는다(멱등)", st3 == 200, 200, st3)
        check("[48] 멱등 응답의 changed가 비어 있다", (out3 or {}).get("changed") == {},
              {}, (out3 or {}).get("changed"))
    finally:
        _restore()

    final = get("/api/admin/ai-integration/status")
    fprov = next((p for p in (final or {}).get("providers", [])
                  if p["key"] == PROVIDER), None)
    check("[48] 검사가 끝난 뒤 원래 상태로 되돌렸다(daily_usd 기준 — 검사가 흔적을"
          " 남기지 않는다)",
          (fprov or {}).get("limit", {}).get("daily_usd") == before.get("daily_usd"),
          before.get("daily_usd"), (fprov or {}).get("limit", {}).get("daily_usd"))

    # ── 화면이 실제로 렌더되는가 — 서버 렌더 결과([41]과 같은 방식) ──
    st, html = get_html("/admin2/ai-integration")
    check("[48] /admin2/ai-integration 200", st == 200, 200, st)
    if st == 200:
        check("[48] data-screen-id=ADM-AI-040", 'data-screen-id="ADM-AI-040"' in html,
              True, 'data-screen-id="ADM-AI-040"' in html)


def test_supplier_scale():
    """[49] 공급처 화면 — 규모(122곳) 전수 대조 (2026-08-25 신설)

    공급처 회귀([22] test_suppliers)가 5곳일 때 만들어졌다. 지금은 122곳이다(사장님이
    새로 대거 등록 — docs/open-items.md 실측). total==len(items)는 [22]가 이미 본다 —
    이 검사가 새로 보는 것은 **행 하나하나의 「연결 상품」·「단가표 파일」·「파서
    프리셋」이 화면이 지어낸 값이 아니라 서버가 실제로 센 값인지**를 122행 «전수»로
    대조하는 것이다(표본 아님). `admin_suppliers.py`의 상관 서브쿼리(`_SELECT_BODY`)와
    **다른 SQL 형태**(JOIN + GROUP BY)로 독립 계산해 같은 값이 나오는지 본다 — 같은
    SQL을 그대로 베끼면 "그 SQL이 자기 자신과 같다"는 말밖에 안 된다.
    """
    print("\n[49] 공급처 화면 — 규모 전수 대조 (2026-08-25 신설)")
    d = get("/api/admin/suppliers")
    check("[49] 공급처 목록을 읽는다", isinstance(d, dict) and "items" in d, "items 있음", d)
    if not isinstance(d, dict) or "items" not in d:
        return
    items = d["items"]

    total_db = db_one("SELECT COUNT(*) FROM suppliers")
    if total_db is None:
        print("  [SKIP] (I) [49] 공급처 전수 대조 — DB 미연결: " + _db_why)
        return

    check("[49] API total = DB 전체 행 수", d.get("total") == total_db, total_db, d.get("total"))
    check("[49] items 배열 길이 = total(응답이 스스로 자르지 않는다 — 페이지네이션 없음)",
          len(items) == d.get("total"), d.get("total"), len(items))
    # "5곳일 때만 검증됐다"의 다음 규모를 실제로 넘는지 — 하드코딩한 "122"가 아니라
    # 그때의 상한을 넘는지만 본다(수가 더 늘어도 이 검사는 낡지 않는다).
    check("[49] 이전에 검증됐던 규모(5곳)를 실제로 넘는 규모에서 대조했다",
          total_db > 5, "> 5", total_db)

    rows = db_all(
        "SELECT s.supplier_id,"
        " COUNT(DISTINCT p.psp_id) AS linked,"
        " COUNT(DISTINCT f.file_id) AS files,"
        " COUNT(DISTINCT pr.preset_id) AS presets"
        " FROM suppliers s"
        " LEFT JOIN product_supplier_prices p ON p.supplier_id = s.supplier_id"
        " LEFT JOIN supplier_price_files f ON f.supplier_id = s.supplier_id"
        " LEFT JOIN supplier_presets pr ON pr.supplier_id = s.supplier_id"
        " GROUP BY s.supplier_id")
    by_id = {r["supplier_id"]: r for r in rows}

    missing, bad_linked, bad_files, bad_presets = [], [], [], []
    for it in items:
        r = by_id.get(it["id"])
        if r is None:
            missing.append(it["id"])
            continue
        if it["linked_products"] != r["linked"]:
            bad_linked.append({"id": it["id"], "화면": it["linked_products"], "DB재계산": r["linked"]})
        if it["price_files"] != r["files"]:
            bad_files.append({"id": it["id"], "화면": it["price_files"], "DB재계산": r["files"]})
        if it["preset_count"] != r["presets"]:
            bad_presets.append({"id": it["id"], "화면": it["preset_count"], "DB재계산": r["presets"]})

    check(f"[49] 공급처 {len(items)}곳 전수 — 없는 id 없음(DB와 API의 모집단이 같다)",
          not missing, "없음", missing[:5])
    check(f"[49] 공급처 {len(items)}곳 전수 — 「연결 상품」이 서버가 센 값이다"
          "(화면이 지어내지 않는다, 독립 JOIN 재계산과 전수 일치)",
          not bad_linked, "전부 일치", bad_linked[:5])
    check(f"[49] 공급처 {len(items)}곳 전수 — 「단가표 파일」도 서버가 센 값이다",
          not bad_files, "전부 일치", bad_files[:5])
    check(f"[49] 공급처 {len(items)}곳 전수 — 「파서 프리셋」도 서버가 센 값이다",
          not bad_presets, "전부 일치", bad_presets[:5])

    # ── 자기검증 — 위 대조가 실제로 어긋남을 잡는지, 응답 사본 하나를 일부러
    # 어긋내고 같은 비교를 돌려 본다(API에도 DB에도 쓰지 않는다) ──
    if items:
        victim = dict(items[0])
        victim["linked_products"] = (victim["linked_products"] or 0) + 1
        r = by_id.get(victim["id"])
        broke = r is not None and victim["linked_products"] != r["linked"]
        check("[49] 자기검증 — 「연결 상품」을 +1 어긋낸 사본은 이 비교에 걸린다"
              "(화면이 진짜 숫자를 지어냈다면 이렇게 잡힌다는 뜻)",
              broke, True, broke)

    # ── admin2 화면이 실제로 전부 그린다 — 클라이언트가 자르지 않는다 ──
    st, html = get_html("/admin2/suppliers")
    check("[49] /admin2/suppliers 200", st == 200, 200, st)
    if st == 200:
        check("[49] data-screen-id=ADM-SRC-030", 'data-screen-id="ADM-SRC-030"' in html,
              True, 'data-screen-id="ADM-SRC-030"' in html)
        check("[49] 목록 렌더가 항목을 자르지 않는다(전체를 그대로 그린다 — slice 없음)",
              "S.data.items.map(rowHtml)" in html and ".slice(" not in html,
              "전체 렌더·slice 없음",
              {"map 있음": "S.data.items.map(rowHtml)" in html, "slice 있음": ".slice(" in html})


def test_alloc_capped_uncapped():
    """[50] 견적 배분 상한 — 상한을 푼 경우 「유지」라고 거짓말하지 않는가 (2026-08-25 신설)

    `api/recommend.py`의 `_build_highend()`가 `hi_alloc = cap is not None`으로 고쳐졌다
    (2026-08-24, "최고 사양 문구 정직화 후속") — cap이 없으면(‘200만원 이상’ 등) 배분
    상한 자체를 걸 근거가 없으므로 고성능형 reasons가 "부품별 배분 상한은 유지"라고
    말하면 안 된다. **같은 날(2026-08-25) `api/expert.py`는 다른 제작자가 고치는
    중이다**(`:590~593`, docs/open-items.md 3절) — 이 검사는 그 파일을 건드리지 않고
    `api/recommend.py` 경로(`/api/recommend`, 이미 고쳐짐)만 본다.
    """
    print("\n[50] 견적 배분 상한 — 상한 해제 시 '유지' 주장 금지 (2026-08-25 신설)")
    sopen = rec("200만원 이상")
    h = sopen.get("highend")
    check("[50] 상한 없는 예산('200만원 이상')으로 고성능형을 지을 수 있다"
          "(못 지으면 아래 문구 검사가 무의미)", bool(h), "구성 있음", h)
    if not h:
        return
    check("[50] 이 시나리오가 실제로 cap=None을 탔다(검사가 실제로 상한없음 경로를 검증)",
          h["budget"]["cap"] is None, None, h["budget"]["cap"])

    reasons_text = " / ".join(h.get("reasons") or [])
    check("[50] cap=None인데 '부품별 배분 상한은 유지'라고 말하지 않는다"
          "(말하면 거짓 — 배분 상한을 걸 기준 자체가 없다)",
          "부품별 배분 상한은 유지" not in reasons_text, "미포함", reasons_text)
    check("[50] 대신 '해제'로 정직하게 표기한다",
          "부품별 배분 상한으로는 조합이 없어 해제" in reasons_text, "포함", reasons_text)

    # ── 정적 소스 검사 — 이 판정이 실제로 cap 유무로 갈리는 코드인가(고정값으로
    # 되돌아가면 이 줄들이 사라진다). api/expert.py는 건드리지 않으므로 api/recommend.py만.
    rec_src = io.open(os.path.join(ROOT, "api", "recommend.py"), encoding="utf-8").read()
    check("[50] api/recommend.py의 판정이 'cap is not None'으로 걸려 있다"
          "(고정값(True)으로 되돌아가면 이 줄이 사라진다)",
          "hi_alloc = cap is not None" in rec_src, "있음", "없음")
    check("[50] 배분 상한 실패 시 common 폴백 호출은 명시적으로 alloc_capped=False를"
          " 넘긴다(폴백인데 '유지'라 말하면 자기모순 — CLAUDE.md 실사고 205건, 14.2%)",
          rec_src.count("alloc_capped=False") >= 2, ">= 2", rec_src.count("alloc_capped=False"))


def main():
    print("=" * 74)
    print("팝콘PC AI 통합 회귀 세트 — 전량 불변식(I). 절대값 대신 관계·원천 대조 (A-13)")
    print("=" * 74)
    if _engine is None:
        print("\n⚠ DB에 연결하지 못했습니다 — 원천 대조 항목을 건너뜁니다.")
        print("  " + _db_why)
    try:
        get("/api/health")
    except Exception as e:
        print(f"\n서버에 연결할 수 없습니다({BASE}). API를 먼저 띄우세요.\n  {e}")
        return 2

    # 관리자 인증(슬라이스 37) — 로그인 없이는 관리자 항목 전부가 401이 된다
    try:
        st, d = login()
    except Exception as e:
        print("\n관리자 로그인 실패: " + repr(e))
        return 2
    if (d or {}).get("state") != "active":
        print("\n관리자 로그인이 활성 세션을 만들지 못했습니다: " + repr(d))
        print("  시드 owner(" + ADMIN_EMAIL + ")가 '활성' 상태인지 확인하세요.")
        return 2
    print("\n로그인: " + str(d["operator"].get("name")) + " · 권한 " + d["operator"]["role"])

    for fn in (test_engine, test_tier_cascade_exhaustive, test_compat, test_gates, test_consistency,
               test_ledgers, test_customer, test_auth, test_ops, test_swap,
               test_upload, test_product_edit, test_spec_fields, test_pool_gate,
               test_screen_identity,
               test_my_profile,
               test_suppliers,
               test_setup_status,
               test_product_gate,
               test_review_flow,
               test_stock_ledger,
               test_time_display,
               test_session_revoke,
               test_password_policy,
               test_screen_assets,
               test_doc_counts,
               test_taxonomy_single_source,
               test_categories,
               test_category_mapping,
               test_category_isolation,
               test_reprice,
               test_category_margin,
               test_template_usage,
               test_charts_and_choices,
               test_no_fabricated_data,
               test_usage_floor_admin,
               test_margin_policy,
               test_password_auth,
               test_part_type_change,
               test_usage_floors,
               test_guards,
               test_rebuild_screens,
               test_display_name,
               test_std_schema,
               test_lock_scope,
               test_dash_team_ko,
               test_ai_response_log_models,
               test_ai_integration_limit_clear,
               test_supplier_scale,
               test_alloc_capped_uncapped):
        try:
            fn()
        except Exception as e:
            check(f"{fn.__name__} 실행 중 예외", False, "정상 실행", repr(e))

    fails = [r for r in results if not r["ok"]]
    print("\n" + "=" * 74)
    print(f"합계 {len(results)}건 · 통과 {len(results) - len(fails)}건 · 실패 {len(fails)}건")
    if fails:
        print("\n실패 목록:")
        for r in fails:
            print(f"  - {r['name']}: 기대 {r['expect']} / 실제 {r['got']}")
        print("\n※ 전부 불변식입니다 — 데이터가 아니라 코드 문제입니다. 값을 맞추지 말고 고치세요.")
    else:
        print("전 항목 통과 — 엔진·게이트·정합·원장·고객 계약·가드 정상")

    # 값 변화는 실패가 아니라 알림이다(A-13). 재고가 움직이면 값도 움직인다.
    if _drifts:
        print("\n[값 변화] 실패 아님 — 재고·가격이 움직였는지, 내가 코드를 바꿨는지 확인하세요.")
        for k, old, new in _drifts:
            fmt = (lambda x: f"{x:,}") if isinstance(old, int) else str
            print(f"  · {k}: {fmt(old)} -> {fmt(new)}")
    try:
        with io.open(SNAP_PATH, "w", encoding="utf-8", newline="") as f:
            json.dump(_snap_new, f, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception as e:                               # noqa: BLE001
        print(f"\n(스냅샷 기록 실패: {e})")
    print("=" * 74)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
