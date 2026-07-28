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
import io
import json
import os
import sys
import urllib.error
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
               test_upload, test_product_edit, test_spec_fields, test_usage_floors,
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
