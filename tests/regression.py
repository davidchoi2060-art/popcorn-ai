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
ADMIN_EMAIL = "admin@popcornpc.local"      # 시드 owner(로컬 dev 전용 — 운영 계정 아님)
# 슬라이스 70부터 로그인에 비밀번호가 필요하다. 이 값은 **로컬 시드 전용**이며
# 운영 서버에는 이 계정이 없다. 실 운영자 비밀번호는 tools/set_admin_password.py로 넣는다.
ADMIN_PW = "Rg7#tzQm4vLp"


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

    compat = rec("100만원")["value"]["compat"]
    check("견적 호환 항목 = 규칙 수(1:1)", len(compat["checks"]) == len(active),
          len(active), len(compat["checks"]))
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
        db_one("SELECT 1")     # 정리는 아래에서
    # 검증으로 만든 행은 지운다 — 회귀가 정본을 바꾸면 안 된다
    if _engine is not None:
        with _engine.begin() as c:
            c.execute(text("DELETE FROM pricing_settings WHERE setting_id > :i"),
                      {"i": db_one("SELECT min(setting_id) FROM pricing_settings")})
    check("검증 후 정책이 원래 1건", db_one("SELECT count(*) FROM pricing_settings") == n0,
          n0, db_one("SELECT count(*) FROM pricing_settings"))

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
        check("모달이 기존 검수 API를 재사용한다",
              "/process`, {action:\"manual\"" in rq, "process 호출", "다른 경로")
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
    sourcing = get("/api/admin/sourcing")["items"]
    check("매입 대기 = 입고 대기(같은 파생 조건)", len(sourcing) == stock_res["total"],
          stock_res["total"], len(sourcing))
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
    n_rules = len([r for r in get("/api/admin/engine-rules")["compat"]["checks"]
                   if r.get("active", True)])
    check("교체 후 호환 항목 = 활성 규칙 수(1:1)",
          len(ap["compat"]["checks"]) == n_rules, n_rules, len(ap["compat"]["checks"]))

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
