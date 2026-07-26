# -*- coding: utf-8 -*-
"""팝콘PC AI 통합 회귀 세트 — 슬라이스 1~35의 기검증 수치를 실행 가능하게 묶는다.

실행: .venv/Scripts/python tests/regression.py        (API 서버가 8000에 떠 있어야 함)
      .venv/Scripts/python tests/regression.py --quiet  (실패만 출력)

**두 종류를 구분한다 — 이 구분이 회귀 세트의 수명을 결정한다.**
  ① 고정 기대값(FIXED): 현재 dev 재고 스냅샷에서만 성립하는 수치(945,000 등).
     재고·가격을 의도적으로 바꾸면 여기도 함께 갱신한다. 갱신할 때는 decision-log에
     "왜 바뀌었는지"를 남긴다 — 값만 고치면 회귀 세트가 거짓 안심이 된다.
  ② 불변식(INVARIANT): 데이터가 어떻게 누적돼도 성립해야 하는 관계(정합·원장 짝·배타 버킷).
     이게 깨지면 데이터가 아니라 **코드가 잘못된 것**이다.

의존성 없음(stdlib만) — 프로젝트에 테스트 프레임워크를 도입하지 않는다는 선택이다.
목업=스펙 단계에서는 "브라우저 손검증 + 이 스크립트"가 검증 수단이다.
"""
import io
import json
import sys
import urllib.error
import urllib.request

# Windows 콘솔(cp949)에서도 한글·기호가 깨지지 않게 stdout을 UTF-8로 고정한다.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"
QUIET = "--quiet" in sys.argv

# ① 고정 기대값 — 현재 재고 스냅샷 기준(슬라이스 34~35 시점)
# 슬라이스 39(2026-07-26) 전량 갱신 — 실파일 24,303행 적재로 후보 풀이 20 → 3,046이 됐다.
# 이전 값(945,000·993,000·1,367,000·1,149,000·1,738,000·S1 20)은 시드 30종 시절 스냅샷이다.
FIXED = {
    "pool_size": 3_087,                 # S1 후보 카운터 = 추천 뷰 ∧ 재고>0
    "value_total": 289_700,             # 가성비(전 예산 공통 — 최저가 조합)
    "recommend_70": 699_900,            # 시드 시절엔 70만원 견적 자체가 불성립이었다
    "recommend_100": 1_000_000,         # 슬라이스 40에서 해소(노드 상한 상향)
    "recommend_150": 1_500_000,
    "recommend_open": 2_144_900,        # "200만원 이상" = 캡 미적용·중간 순위
    "highend_total": 30_250_600,        # 서버용 RAM(512GB ECC 2,779만원)이 실제로 카탈로그에 있다
    "compat_checks": 8,                 # 활성 규칙 수 — 슬라이스 43에서 8번째 추가
                                        # (CASE.form_factor_list contains MB.form_factor)
    "review_pending": 6_490,            # 슬라이스 42 재파싱 회수 후(적재 직후 7,415)
}

# 슬라이스 39의 '알려진 한계'는 슬라이스 40에서 해소됐다: 예산 100만원 추천이 안 나온 원인은
# 탐색 전략이 아니라 **노드 상한값**이었다(100,000 → 682,419노드면 답이 있다. 탐색은 싸다 —
# 100,007노드가 0.02초). 상한을 2,000,000으로 올려 1,000,000원 구성이 나온다.
# 이 이력을 남겨두는 이유: 같은 증상(견적 '불가')을 다시 만나면 데이터가 아니라 상한을 먼저 본다.

results = []


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
ADMIN_EMAIL = "admin@popcornpc.local"      # 시드 owner — dev 어댑터로 로그인


def _headers(json_body=False):
    h = {"Content-Type": "application/json"} if json_body else {}
    if SESSION:
        h["Cookie"] = "; ".join(SESSION.values())
    return h


def get(path):
    req = urllib.request.Request(BASE + path, headers=_headers())
    with urllib.request.urlopen(req) as r:
        return json.load(r)


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
    return post("/api/admin/auth/login", {"email": ADMIN_EMAIL, "provider": "dev"})


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
    check("S1 후보 카운터", c["total"] == FIXED["pool_size"],
          FIXED["pool_size"], c["total"], "FIXED")

    s100 = rec("100만원")
    check("가성비 총액", s100["value"]["total"] == FIXED["value_total"],
          FIXED["value_total"], s100["value"]["total"], "FIXED")
    check("추천 총액(100만)",
          (s100.get("recommend") or {}).get("total") == FIXED["recommend_100"],
          FIXED["recommend_100"], (s100.get("recommend") or {}).get("total"), "FIXED")
    check("고성능 총액", s100["highend"]["total"] == FIXED["highend_total"],
          FIXED["highend_total"], s100["highend"]["total"], "FIXED")

    s150 = rec("150만원")
    check("추천 총액(150만)", s150["recommend"]["total"] == FIXED["recommend_150"],
          FIXED["recommend_150"], s150["recommend"]["total"], "FIXED")

    sopen = rec("200만원 이상")
    check("추천 총액(캡 없음)", sopen["recommend"]["total"] == FIXED["recommend_open"],
          FIXED["recommend_open"], sopen["recommend"]["total"], "FIXED")

    # 시드 30종 시절에는 70만원이 견적 불성립이었다 — 실카탈로그에서는 성립한다(의도된 변경)
    s70 = rec("70만원")
    check("추천 총액(70만)", (s70.get("recommend") or {}).get("total") == FIXED["recommend_70"],
          FIXED["recommend_70"], (s70.get("recommend") or {}).get("total"), "FIXED")

    # 재현성 — 같은 입력 3회 = 같은 결과
    totals = {rec("100만원")["value"]["total"] for _ in range(3)}
    check("재현성(A-02): 3회 호출 동일", len(totals) == 1, "1개 값", totals)

    # 예산 준수 / 초과 정직 표기
    check("가성비는 예산 안", s100["value"]["budget"]["verdict"] == "within",
          "within", s100["value"]["budget"]["verdict"])
    check("고성능 초과는 'over'로 정직 표기", s100["highend"]["budget"]["verdict"] == "over",
          "over", s100["highend"]["budget"]["verdict"])


# ───────────────────────── 2. 호환 규칙 (DB 단일 원천) ─────────────────────────
def test_compat():
    print("\n[2] 호환 규칙 — compat_rules 단일 원천 (슬라이스 34)")
    rules = get("/api/admin/engine-rules")["compat"]["checks"]
    active = [r for r in rules if r.get("active", True)]
    check("활성 규칙 수", len(active) == FIXED["compat_checks"],
          FIXED["compat_checks"], len(active), "FIXED")

    compat = rec("100만원")["value"]["compat"]
    check("견적 호환 항목 = 규칙 수(1:1)", len(compat["checks"]) == len(active),
          len(active), len(compat["checks"]))
    check("호환 검사 전부 통과", all(c["pass"] for c in compat["checks"]),
          "전 항목 pass", [c["key"] for c in compat["checks"] if not c["pass"]])
    check("전원 여유율 100% 이상", (compat["power_headroom_pct"] or 0) >= 100,
          ">= 100", compat["power_headroom_pct"])


# ──────────────────────── 3. 4중 게이트 (추천 풀 진입) ────────────────────────
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
    rv = get("/api/admin/reviews")
    check("검수 대기", dash["review"] == rv["total"], rv["total"], dash["review"])
    check("검수 대기 규모(적재 결과)", rv["total"] == FIXED["review_pending"],
          FIXED["review_pending"], rv["total"], "FIXED")
    check("가격 검토", dash["price"] == len(get("/api/admin/price-review")["items"]),
          len(get("/api/admin/price-review")["items"]), dash["price"])
    stock = get("/api/admin/stock-inbound")["items"]
    check("입고 대기", dash["inbound"] == len(stock), len(stock), dash["inbound"])
    sourcing = get("/api/admin/sourcing")["items"]
    check("매입 대기 = 입고 대기(같은 파생 조건)", len(sourcing) == len(stock),
          len(stock), len(sourcing))
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

    logs = get("/api/admin/activity-logs")
    undo_rows = [i for i in logs["items"] if i["is_undo"]]
    undone_rows = [i for i in logs["items"] if i["undone"]]
    check("되돌림 행 수 = 되돌려진 원본 수(1:1)", len(undo_rows) == len(undone_rows),
          len(undo_rows), len(undone_rows))


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
    mine_nos = {o["no"] for o in mine}
    check("회원 경계: 타인 주문 미포함",
          not (mine_nos & {o["no"] for o in other}), "교집합 없음",
          mine_nos & {o["no"] for o in other})
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
    check("신규 가입 회원 → 빈 주문 목록", fresh == [], [], fresh)
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

    order_body = {"session_id": 1, "tier": "value", "periph": [],
                  "member": {"nick": "회귀", "email": "ops-regress@popcornpc.local"},
                  "shipping": {"name": "회귀", "phone": "010-0000-0000", "addr": "서울"}}
    undo_ids = []
    try:
        # ① 상호 제약: 환불만 '자체'로 요청해도 결제가 쇼핑몰이면 서버가 보정한다
        st, d = post("/api/admin/ops-settings", {"modes": {"pay": "mall"}})
        undo_ids.append(d.get("undo_id"))
        check("결제 전환 시 정산도 함께 이동(정산은 결제를 따른다)",
              d.get("changed", {}).get("settle", {}).get("to") == "mall",
              "settle=mall", d.get("changed"))
        st, d2 = post("/api/admin/ops-settings", {"modes": {"refund": "own"}})
        if d2.get("undo_id"):
            undo_ids.append(d2["undo_id"])
        check("쇼핑몰 결제 상태에서 환불 '자체'는 보정된다",
              d2.get("modes", {}).get("refund") == "mall", "refund=mall", d2.get("modes"))

        # ② 스위치가 주문 흐름을 실제로 막는가
        st, r = post("/api/orders", order_body)
        detail = r.get("detail") if isinstance(r, dict) else None
        err = detail.get("error") if isinstance(detail, dict) else None
        check("쇼핑몰 결제 모드에서 자체 주문 409", st == 409 and err == "pay_mode_mall",
              "409 pay_mode_mall", f"{st} {err}")
    finally:
        for lid in reversed([i for i in undo_ids if i]):
            post(f"/api/admin/ops-settings/undo/{lid}")

    after = get("/api/admin/ops-settings")["modes"]
    check("되돌리기로 원상 복구", after == base, base, after)

    # ③ 원복 상태에서는 결제 게이트를 통과한다(이후 실패 사유는 견적·재고여야 한다)
    st, r = post("/api/orders", order_body)
    detail = r.get("detail") if isinstance(r, dict) else None
    err = detail.get("error") if isinstance(detail, dict) else None
    check("원복 후 결제 게이트 통과", err != "pay_mode_mall", "pay_mode_mall 아님", err)


def test_guards():
    print("\n[7] 가드 — 상태 전이·권한 (슬라이스 7·11·19·30·35)")
    member_login("mj.kim@example.com")        # 가드도 세션 주체로 확인(슬라이스 38)
    st, _ = post("/api/my/reviews", {"item_id": 999999,
                                     "rating": 5, "body": "존재하지 않는 라인 테스트입니다"})
    check("없는 주문 라인 후기 → 404", st == 404, 404, st)
    st, _ = post("/api/my/reviews", {"item_id": 12,
                                     "rating": 5, "body": "타인 주문 라인 테스트입니다"})
    check("타인 주문 라인 후기 → 403", st == 403, 403, st)
    st, _ = post("/api/admin/stock-inbound/20489103", {"qty": 0, "why": "inbound"})
    check("입고 수량 0 → 400", st == 400, 400, st)
    st, _ = post("/api/admin/sourcing/request", {"product_code": 20489103, "supplier_ids": []})
    check("공급처 미선택 견적 요청 → 400", st == 400, 400, st)
    member_login("sy.lee@example.com")
    st, _ = post("/api/my/account/map", {"agree": True})
    check("요청 없는 계정 연결 동의 → 409", st == 409, 409, st)


def main():
    print("=" * 74)
    print("팝콘PC AI 통합 회귀 세트 — (F)=고정 기대값 / (I)=불변식")
    print("=" * 74)
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

    for fn in (test_engine, test_compat, test_gates, test_consistency,
               test_ledgers, test_customer, test_auth, test_ops, test_guards):
        try:
            fn()
        except Exception as e:
            check(f"{fn.__name__} 실행 중 예외", False, "정상 실행", repr(e))

    fails = [r for r in results if not r["ok"]]
    fixed_fails = [r for r in fails if r["kind"] == "FIXED"]
    print("\n" + "=" * 74)
    print(f"합계 {len(results)}건 · 통과 {len(results) - len(fails)}건 · 실패 {len(fails)}건")
    if fails:
        print("\n실패 목록:")
        for r in fails:
            print(f"  - ({r['kind']}) {r['name']}: 기대 {r['expect']} / 실제 {r['got']}")
        if fixed_fails:
            print("\n※ 고정 기대값(FIXED) 실패는 재고·가격이 의도적으로 바뀐 것일 수 있습니다.")
            print("  의도된 변경이면 FIXED 값을 갱신하고 decision-log에 사유를 남기세요.")
        if len(fails) > len(fixed_fails):
            print("\n※ 불변식(INVARIANT) 실패는 데이터가 아니라 코드 문제입니다 — 먼저 고치세요.")
    else:
        print("전 항목 통과 — 엔진·게이트·정합·원장·고객 계약·가드 정상")
    print("=" * 74)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
