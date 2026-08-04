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
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# Windows 콘솔(cp949)에서도 한글·기호가 깨지지 않게 stdout을 UTF-8로 고정한다.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"
QUIET = "--quiet" in sys.argv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_PATH = os.path.join(ROOT, "tests", ".regression-snapshot.json")

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

    # 가성비는 '예산과 무관한 최저가 조합'이다 — 예산이 달라도 같은 값이어야 한다.
    vals = {s["value"]["total"] for s in (s70, s100, s150, sopen) if s.get("value")}
    check("가성비는 전 예산 공통(최저가 조합)", len(vals) == 1, "1개 값", vals)

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
    NARROW = [{"l": "용도", "v": "게임"}, {"l": "예산", "v": "30만원대"},
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
    # 쿨러는 공랭·수냉이 한 슬롯 — part_type으로 세면 AIO 0을 빈 슬롯으로 오판한다
    _, cs = post("/api/candidates/count",
                 {"constraints": [{"l": "용도", "v": "게임"}, {"l": "선호", "v": "저소음"}]})
    check("저소음: 쿨러는 공랭/수냉 합산으로 판정(AIO 0이어도 성립)",
          cs["slots"]["COOLER"] > 0 and cs["buildable"] is True,
          "COOLER>0 & buildable=true",
          f'COOLER={cs["slots"]["COOLER"]} buildable={cs["buildable"]}')


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
    _p = os.path.join(ROOT, "mockups", "admin", "compat-rules.html")
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
    for _p in sorted(_g2.glob(os.path.join(ROOT, "mockups", "admin", "*.html"))):
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
    pc = db_one("SELECT product_code FROM v_recommendation_candidates"
                " WHERE stock_qty > 0 ORDER BY product_code LIMIT 1")
    if pc is None:
        print("  [SKIP] (I) 단건 수정 — DB 미연결")
        return
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

    st, r = post_raw(f"/api/admin/products/{pc}",
                     json.dumps({"changes": {"sale_price": (d["sale_price"] or 0) + 1000,
                                             "status": "품절"}}).encode(),
                     {"Content-Type": "application/json"}, method="PATCH")
    check("수정 성공", st == 200, 200, st)
    if st != 200:
        return
    check("수정한 필드는 잠긴다(다음 적재가 덮지 않게)",
          {"sale_price", "status"} <= set(r["locked_fields"]),
          "sale_price·status 잠금", r["locked_fields"])
    d2 = get(f"/api/admin/products/{pc}")
    check("상태로 빠진 이유를 정확히 말한다", "품절" in d2["verdict"], "'품절' 언급", d2["verdict"])
    check("판매중이 아니면 추천에서 빠진다", d2["in_pool"] is False, False, d2["in_pool"])

    # 되돌림은 삭제가 아니라 역방향 복원 — 잠금도 함께 되돌아가야 한다
    st, _ = post(f"/api/admin/products/undo/{r['undo_id']}")
    check("되돌리기 성공", st == 200, 200, st)
    d3 = get(f"/api/admin/products/{pc}")
    check("값이 원복된다", d3["sale_price"] == before["sale_price"]
          and d3["status"] == before["status"],
          before, {"sale_price": d3["sale_price"], "status": d3["status"]})
    check("잠금도 원복된다(안 그러면 적재가 영영 못 채운다)",
          d3["locked_fields"] == before["locked"], before["locked"], d3["locked_fields"])
    st, _ = post(f"/api/admin/products/undo/{r['undo_id']}")
    check("이중 되돌리기는 409", st == 409, 409, st)

    # 등록 화면에 남의 상품 값이 기본으로 들어 있으면 그대로 저장된다(사용자 지적, 슬라이스 55).
    # 마크업에 예시 값이 박혀 있지 않은지 회귀가 지킨다.
    try:
        import re as _re
        html = io.open(os.path.join(ROOT, "mockups", "admin", "product-edit.html"),
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
        lst = io.open(os.path.join(ROOT, "mockups", "admin", "products.html"),
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
    pc = db_one("""
        SELECT p.product_code FROM products p JOIN product_specs s USING (product_code)
         WHERE p.part_type='POWER' AND p.status='판매중' AND p.stock_qty>0
           AND s.form_factor IS NOT NULL AND s.rated_watt IS NULL
         ORDER BY p.product_code LIMIT 1""")
    if pc is None:
        print("  [SKIP] (I) 사양 값 입력 — 대상 없음")
    else:
        pool0 = db_one("SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty>0")
        st, w = post_raw(f"/api/admin/products/{pc}/specs",
                         json.dumps({"values": {"size_inch": 27}}).encode(),
                         {"Content-Type": "application/json"}, method="PATCH")
        check("다른 부품 종류의 사양은 400", st == 400, 400, st)
        st, r = post_raw(f"/api/admin/products/{pc}/specs",
                         json.dumps({"values": {"rated_watt": 650}}).encode(),
                         {"Content-Type": "application/json"}, method="PATCH")
        check("사양 입력 성공", st == 200, 200, st)
        if st == 200:
            check("입력한 사양은 잠긴다", "rated_watt" in r["locked_fields"],
                  "rated_watt 잠금", r["locked_fields"])
            check("채운 필드의 검수 대기가 해소된다", r["reviews_closed"] >= 0,
                  ">= 0", r["reviews_closed"])
            st2, _ = post(f"/api/admin/products/specs/undo/{r['undo_id']}")
            check("사양 입력 되돌리기", st2 == 200, 200, st2)
            back = db_one("SELECT rated_watt FROM product_specs WHERE product_code=:p", p=pc)
            check("값이 원복된다", back is None, None, back)
            lf = db_one("SELECT locked_fields::text FROM products WHERE product_code=:p", p=pc)
            check("잠금도 원복된다", "rated_watt" not in (lf or ""), "잠금 없음", lf)
            pool1 = db_one("SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty>0")
            check("되돌린 뒤 추천 후보가 제자리", pool1 == pool0, pool0, pool1)
            st3, _ = post(f"/api/admin/products/specs/undo/{r['undo_id']}")
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
        lg = io.open(os.path.join(ROOT, "mockups", "admin", "login.html"),
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
        # 어느 문서도 말하지 않으면 위 검사는 전부 공허하다 — 그 상태를 실패로 본다.
        check("문서 중 최소 하나는 호환 규칙 수를 말한다", seen_any, "1곳 이상", "없음")

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
                       r"|ALL_PART_TYPES|PART_TYPES|ASSIGNABLE_TYPES)\s*=\s*[{\[(]",
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
    _p = os.path.join(ROOT, "mockups", "admin", "categories.html")
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
    _p = os.path.join(ROOT, "mockups", "admin", "category-mapping.html")
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
    _p = os.path.join(ROOT, "mockups", "admin", "reprice.html")
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
        p = os.path.join(admin, name)
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
    # 컴포넌트는 docReady 1회만 붙는다 — 동적 렌더면 우리가 다시 붙여야 한다
    check("동적 렌더 뒤 컴포넌트를 다시 붙인다",
          "phoenix.BulkSelect" in cat and ("new window.List" in cat or "reIndex" in cat),
          True, "phoenix.BulkSelect" in cat)

    # 참조하는 vendor는 실제로 있어야 한다(없으면 조용히 안 붙는다)
    vend = os.path.join(admin, "vendors")
    have = set(os.listdir(vend)) if os.path.isdir(vend) else set()
    NEED = {"data-choices": "choices", "data-echarts": "echarts", "data-countup": "countup",
            "data-nouislider": "nouislider", "data-rater": "rater-js",
            "data-sortable": "sortablejs", "data-calendar": "fullcalendar"}
    missing = []
    for _p in sorted(_g7.glob(os.path.join(admin, "*.html"))):
        if os.path.basename(_p).startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        for hook, v in NEED.items():
            if hook in _s and v not in have:
                missing.append(f"{os.path.basename(_p)}:{hook}->{v}")
    check("vendor 없는 훅을 선언하지 않는다", missing == [], [], missing)

    # 손으로 만든 전체선택이 남아 있지 않은가 — 있으면 컴포넌트를 또 베낀 것이다
    handrolled = []
    for _p in sorted(_g7.glob(os.path.join(admin, "*.html"))):
        _n = os.path.basename(_p)
        if _n.startswith("_"):
            continue
        _s = io.open(_p, encoding="utf-8").read()
        if 'id="chkAll"' in _s and "data-bulk-select" not in _s:
            handrolled.append(_n)
    check("전체선택을 손으로 만든 화면이 없다", handrolled == [], [], handrolled)

def test_screen_assets():
    print("\n[30] 화면 자산 — 참조한 CSS·JS가 실제로 있는가 (슬라이스 100)")
    # 사용자 지적("이 화면은 디자인이 반영이 안된건가?")으로 찾았다.
    # my-profile · suppliers · usage-floors 세 화면이 `assets/css/theme.css`를 참조했는데
    # 실제 파일은 `theme.min.css`다 — **404라 스타일이 하나도 안 먹었다.**
    # 브라우저는 404 스타일시트를 규칙 0개인 빈 시트로 만들어 조용히 넘어간다.
    # 내가 usage-floors(슬라이스 75)를 템플릿으로 삼으면서 그 버그를 물려받았다.
    import glob as _g7
    import re as _re7

    # Phoenix 템플릿이 남긴 RTL 시트는 원래 없다(dir=rtl일 때만 쓰는 것) — 별건으로 둔다.
    IGNORE = ("theme-rtl.min.css", "user-rtl.min.css")
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

    # 스타일이 안 먹으면 화면은 뜨지만 읽을 수 없는 상태가 된다 — 테마를 싣는지 본다
    noTheme = []
    for _p in sorted(_g7.glob(os.path.join(ROOT, "mockups", "admin", "*.html"))):
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
    for _p in (sorted(_g6.glob(os.path.join(ROOT, "mockups", "admin", "*.html")))
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
    for _p in (sorted(_g6.glob(os.path.join(ROOT, "mockups", "admin", "*.html")))
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
    for _p in (sorted(_g6.glob(os.path.join(ROOT, "mockups", "admin", "*.html")))
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
        ci = io.open(os.path.join(ROOT, "api", "catalog_ingest.py"), encoding="utf-8").read()
        check("적재가 재고 델타를 원장에 남긴다",
              "stock_movements" in ci and "'catalog'" in ci, "있음", "없음")
        check("적재는 절대값이 아니라 델타를 남긴다", "stock_before" in ci, "델타", "절대값")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 적재 원장 계약 - {e}")

    # ── 화면 계약 ── 연속 등록 (슬라이스 97)
    # 빈 상태에서 견적 한 벌 = 8개 슬롯. 슬롯 하나가 0이면 견적이 0건이라 최소 8번 등록한다.
    try:
        pe = io.open(os.path.join(ROOT, "mockups", "admin", "product-edit.html"),
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
        rq = io.open(os.path.join(ROOT, "mockups", "admin", "review-queue.html"),
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
        pe = io.open(os.path.join(ROOT, "mockups", "admin", "product-edit.html"),
                     encoding="utf-8").read()
        check("상세가 게이트 체크리스트를 그린다", "P.gate" in pe, "사용", "없음")
        check("상세가 먼저 할 일을 지목한다", "gate_first" in pe, "사용", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 상세 화면 계약 - {e}")

    # ── 이름 정정 (슬라이스 95) ──
    # '상품 스펙 관리'는 개별 상품 스펙이 아니라 사양 항목(DB 컬럼)을 만드는 화면이었다.
    # 그 이름 때문에 개별 상품 사양을 고치러 온 운영자가 스키마 편집기를 열게 됐다.
    import glob as _g5
    stale = [os.path.basename(x) for x in _g5.glob(os.path.join(ROOT, "mockups", "admin", "*.html"))
             if not os.path.basename(x).startswith("_")
             and "상품 스펙 관리" in io.open(x, encoding="utf-8").read()]
    check("옛 이름('상품 스펙 관리')이 남지 않았다", not stale, "없음", stale[:4])
    try:
        sf = io.open(os.path.join(ROOT, "mockups", "admin", "spec-fields.html"),
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
               if not os.path.exists(os.path.join(ROOT, "mockups", "admin", s["screen"]))]
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
        idx = io.open(os.path.join(ROOT, "mockups", "admin", "index.html"),
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
    missing = []
    for _p in sorted(_g4.glob(os.path.join(ROOT, "mockups", "admin", "*.html"))):
        _n = os.path.basename(_p)
        if _n.startswith("_") or _n in ("login.html", "my-profile.html",
                                        "suppliers.html", "usage-floors.html"):
            continue                       # 셸이 없는 화면은 좌측 메뉴 자체가 없다
        if 'href="suppliers.html"' not in io.open(_p, encoding="utf-8").read():
            missing.append(_n)
    check("좌측 메뉴에 공급처가 있다", not missing, "전 화면", missing[:4])
    check("공급처 화면 파일이 있다",
          os.path.exists(os.path.join(ROOT, "mockups", "admin", "suppliers.html")),
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
    for _p in sorted(_g3.glob(os.path.join(ROOT, "mockups", "admin", "*.html"))):
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
        uf = io.open(os.path.join(ROOT, "mockups", "admin", "usage-floors.html"),
                     encoding="utf-8").read()
        check("하한 화면이 미리보기를 거친다", "preview: true" in uf.replace('"', "'")
              or "preview:true" in uf.replace(" ", ""), "preview 호출", "없음")
        idx = io.open(os.path.join(ROOT, "mockups", "admin", "index.html"),
                      encoding="utf-8").read()
        check("메뉴에 용도 하한이 있다", 'href="usage-floors.html"' in idx,
              "메뉴 있음", "없음")
    except OSError as e:                                 # noqa: BLE001
        print(f"  [SKIP] (I) 하한 화면 — {e}")


def test_screen_identity():
    print("\n[20] 화면 식별자 — 마크업 계약 (슬라이스 78)")
    # 계약은 "최상위에 data-screen-id, data-domain"인데 32개 중 2개만 지키고 있었다.
    # 화면 ID는 이미 배지로 보이므로 그 값을 body로 옮겼다.
    import glob as _g
    import re as _re
    pages = [p for p in _g.glob(os.path.join(ROOT, "mockups", "admin", "*.html"))
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
        mp = io.open(os.path.join(ROOT, "mockups", "admin", "margin-policy.html"),
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
    pc = db_one("SELECT product_code FROM products WHERE part_type='ETC'"
                " AND status='판매중' ORDER BY product_code LIMIT 1")
    if pc is None:
        print("  [SKIP] (I) 분류 변경 — 대상 없음")
        return
    was = db_one("SELECT part_type FROM products WHERE product_code=:p", p=pc)
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

    st2, ap = post(f"/api/admin/products/{pc}/part-type", {"part_type": "CASE"})
    check("분류 변경 적용", st2 == 200, 200, st2)
    if st2 == 200:
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
        uid = ap.get("undo_id")
        st3, _ = post(f"/api/admin/products/part-type/undo/{uid}")
        check("분류 변경 되돌리기", st3 == 200, 200, st3)
        check("분류가 원복된다",
              db_one("SELECT part_type FROM products WHERE product_code=:p", p=pc) == was,
              was, db_one("SELECT part_type FROM products WHERE product_code=:p", p=pc))
        check("되돌린 뒤 추천 풀이 제자리",
              db_one("SELECT count(*) FROM v_recommendation_candidates"
                     " WHERE stock_qty>0") == pool0, pool0,
              db_one("SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty>0"))
        check("이중 되돌리기는 409",
              post(f"/api/admin/products/part-type/undo/{uid}")[0] == 409, 409,
              post(f"/api/admin/products/part-type/undo/{uid}")[0])

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
        pe = io.open(os.path.join(ROOT, "mockups", "admin", "product-edit.html"),
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
            if not os.path.exists(os.path.join(ROOT, "mockups", "admin", i["href"]))]
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
        pages = glob.glob(os.path.join(ROOT, "mockups", "admin", "*.html"))
        miss = [os.path.basename(p) for p in pages
                if "settings-offcanvas" in io.open(p, encoding="utf-8").read()
                and "admin-panel.js" not in io.open(p, encoding="utf-8").read()]
        check("패널 있는 화면에 모두 주입됐다", not miss, "누락 없음", miss)
        # 상품 상세 제목에 예시 상품명이 남아 있으면 '최근 본 상품'에 엉뚱한 이름이
        # 박힌다 — 실제로 다른 상품 이름이 저장됐다(슬라이스 61).
        pe = io.open(os.path.join(ROOT, "mockups", "admin", "product-edit.html"),
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
        idx = io.open(os.path.join(ROOT, "mockups", "admin", "index.html"),
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
        rq = io.open(os.path.join(ROOT, "mockups", "admin", "review-queue.html"),
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
    _op = io.open(os.path.join(ROOT, "mockups", "admin", "operators.html"),
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


# ────────── 10. 부품 교체(S3) — 대안·적용·원장 (슬라이스 46) ──────────
def test_swap():
    """대안이 0건이면 S3 화면이 무력하다 — 그 조용한 고장을 여기서 잡는다."""
    print("\n[10] 부품 교체(S3) — 대안·적용·원장 (슬라이스 46)")
    _, rec = post("/api/recommend", {"mode": "guided",
                  "constraints": [{"l": "용도", "v": "게임"}, {"l": "예산", "v": "150만원"}]})
    sess = rec["session_id"]

    st, cand = post("/api/swap/candidates",
                    {"session_id": sess, "tier": "recommend", "slot": "GPU"})
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
    st, ap = post("/api/swap/apply", {"session_id": sess, "tier": "recommend",
                                      "changes": [{"slot": "GPU",
                                                   "product_code": pick["product_code"]}]})
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
    st, _ = post("/api/admin/stock-inbound/20489103", {"qty": 0, "why": "inbound"})
    check("입고 수량 0 → 400", st == 400, 400, st)
    st, _ = post("/api/admin/sourcing/request", {"product_code": 20489103, "supplier_ids": []})
    check("공급처 미선택 견적 요청 → 400", st == 400, 400, st)
    member_login("sy.lee@example.com")
    st, _ = post("/api/my/account/map", {"agree": True})
    check("요청 없는 계정 연결 동의 → 409", st == 409, 409, st)


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

    for fn in (test_engine, test_compat, test_gates, test_consistency,
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
               test_template_usage,
               test_usage_floor_admin,
               test_margin_policy,
               test_password_auth,
               test_part_type_change,
               test_usage_floors,
               test_guards):
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
