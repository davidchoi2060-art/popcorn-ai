# -*- coding: utf-8 -*-
"""몰 완제PC 공개 페이지 수집 -- /shop/system_detail.html?pd_no=

■ 무엇을 가져오려고 만들었나 (2026-09-22)
  완제PC의 **부품 구성**은 이미 우리 DB 안에 있다(`products.spec_source_text`,
  `tools/builtpc_parse.py` 가 슬롯 어휘로 읽는다). 그러니 구성 때문에 몰을 긁을
  이유는 없다. 이 도구가 노리는 것은 DB 에 **없는** 둘뿐이다:

      ① 용도 태그   #게임용 #사무용 #디자인용 ... -- `usage_alloc` 을 용도별로
                    나누려면 "이 완제품이 어떤 용도인가"가 있어야 한다.
                    우리 `products` 에는 완제PC 용도 열이 없다.
      ② 세 가격     시중가 · 판매가 · 맞춤가 -- 우리는 `sale_price` 한 값만 안다.

  ⚠ 이 도구는 **DB 에 아무것도 쓰지 않는다.** 받은 원문을 캐시에 남기고 JSON 으로
  떨구는 것이 전부다. 반영은 사람이 보고 판단한 뒤 별도 경로로 한다(A-18 과 같은
  태도 -- 남의 페이지 값을 정본에 바로 넣지 않는다).

■ 공개 페이지다 -- 쿠키가 필요 없다
  `tools/mall_supplier_fetch.py` 가 다루는 `/adm_cate/` 는 관리자 로그인이 필요하지만
  이 `/shop/system_detail.html` 은 손님이 보는 페이지라 익명 GET 으로 열린다
  (`api/mall.py` 가 이미 같은 계열 `product_detail.html` 을 그렇게 읽는다).
  그래서 이 파일에는 쿠키를 다루는 코드가 **아예 없다.** GET 만 한다 -- 폼 제출·담기·
  저장은 하지 않는다(CLAUDE.md 규약).

■ 어디서 도는가 -- 이 저장소의 클라우드 작업창에서는 몰에 못 닿는다
  에이전트 프록시가 허용 도메인만 통과시키는데 그 설정은 작업창을 새로 열어야
  적용된다(2026-09-22 실측: CONNECT 403). 그래서 **서버 러너**(self-hosted,
  `popcorn-vm`)에서 돌린다 -- `.github/workflows/mall-fetch.yml`, 수동 실행 전용.
  사장님 PC 에서 그냥 돌려도 똑같이 동작한다.

■ 의존성을 일부러 표준 라이브러리로 묶었다
  러너 계정(`ghrunner`)은 `/srv/popcorn-ai/.venv` 를 쓰지 못한다. 수집·덤프 경로는
  `urllib` 만 쓰므로 맨 `python3` 로 돈다. DB 에서 대상을 고르는 `--from-db` 만
  sqlalchemy 를 **그때 가서** import 한다(그 경로는 러너에서 쓰지 않는다).

■ 두 걸음으로 나눈 이유 -- 본 적 없는 마크업에 파서를 쓰지 않는다
  `--dump` 는 원문을 받아 **구조만** 보고한다(제목·세 가격 후보 줄·태그 후보 줄·
  표의 행). 그 보고를 보고 파서를 쓴다. 화면 사진만 보고 선택자를 지어내면
  "지어낸 값"과 같은 병이다. 파싱은 실측 뒤 이 파일에 덧붙인다.

■ 남의 서버다
  요청 간격 1.5초 · 연속 실패 5회면 멈춤 · 받은 원문은 `.cache/mall_builtpc/`
  (gitignore). A-18(다나와 수집)과 같은 수치를 쓴다.

■ 실행
    python3 tools/mall_builtpc_fetch.py --codes 98149 --dump
    python3 tools/mall_builtpc_fetch.py --from-json builtpc.json --limit 50 --out out.json
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("MALL_BUILTPC_CACHE") or os.path.join(ROOT, ".cache", "mall_builtpc")

BASE = "https://popcornpc.co.kr"
URL_TMPL = BASE + "/shop/system_detail.html?pd_no=%s"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      " (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
DELAY = 1.5              # 요청 간격(초) -- A-18 과 동일
MAX_FAIL = 5             # 연속 실패면 멈춘다(차단 의심) -- A-18 과 동일
TIMEOUT = 15


# ================================================================== 수집 ==

def fetch(pd_no, refetch=False, cache_only=False):
    """공개 상세 페이지 원문. (html, from_cache) -- 못 읽으면 (None, False).

    인코딩은 cp949 로 읽는다. 몰 페이지는 euc-kr 이고(api/mall.py 실측 주석 참조)
    cp949 는 그 상위호환이라 확장 완성형이 섞여도 예외로 죽지 않는다.
    """
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "%s.html" % pd_no)
    if os.path.exists(p) and not refetch:
        return io.open(p, encoding="utf-8").read(), True
    if cache_only:
        return None, False
    req = urllib.request.Request(
        URL_TMPL % pd_no,
        headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise RuntimeError("차단 응답 %s -- 수집을 멈춥니다" % e.code)
        return None, False
    except Exception:                                        # noqa: BLE001
        return None, False
    html = raw.decode("cp949", "replace")
    io.open(p, "w", encoding="utf-8").write(html)
    time.sleep(DELAY)
    return html, False


# ============================================================== 구조 덤프 ==

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t ]+")

# 화면 사진에서 읽은 낱말들이다(2026-09-22 사장님이 보내신 pd_no=98149 화면).
# **선택자가 아니라 검색어**로만 쓴다 -- 어느 태그 안에 있는지는 원문을 봐야 안다.
PRICE_WORDS = ("시중가", "판매가", "맞춤가", "정상가", "할인가")
SPEC_WORDS = ("프로세서", "메인보드", "메모리", "그래픽", "SSD", "HDD",
              "케이스", "파워", "쿨러")


def _text_lines(html):
    """태그를 걷어낸 줄 목록. (원문 줄번호, 텍스트) -- 빈 줄은 버린다."""
    out = []
    for i, line in enumerate(html.splitlines(), 1):
        t = _WS_RE.sub(" ", _TAG_RE.sub(" ", line)).strip()
        if t:
            out.append((i, t))
    return out


def dump(pd_no, html, width=200):
    """원문의 «구조»만 보고한다 -- 파서를 쓰기 위한 실측 자료."""
    print("=" * 70)
    print("pd_no=%s  bytes=%d  lines=%d" % (pd_no, len(html), len(html.splitlines())))
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    print("title: %s" % (m.group(1).strip() if m else "(없음)"))

    lines = _text_lines(html)

    print("\n-- 가격 후보 줄 ------------------------------------------------")
    for n, t in lines:
        if any(w in t for w in PRICE_WORDS):
            print("  L%-6d %s" % (n, t[:width]))

    print("\n-- 태그(#) 후보 줄 ---------------------------------------------")
    for n, t in lines:
        if "#" in t:
            print("  L%-6d %s" % (n, t[:width]))

    print("\n-- 사양 표 후보 줄 ---------------------------------------------")
    for n, t in lines:
        if any(w in t for w in SPEC_WORDS):
            print("  L%-6d %s" % (n, t[:width]))

    print("\n-- 원문 조각(가격 낱말 주변 ±6줄, 태그 포함) --------------------")
    raw = html.splitlines()
    shown = set()
    for i, line in enumerate(raw):
        if not any(w in line for w in PRICE_WORDS[:3]):
            continue
        for j in range(max(0, i - 6), min(len(raw), i + 7)):
            if j in shown:
                continue
            shown.add(j)
            print("  R%-6d %s" % (j + 1, raw[j].strip()[:width]))
        print("  ...")
        if len(shown) > 200:                                  # 로그를 덮지 않는다
            print("  (생략 -- 조각이 너무 많습니다)")
            break


def raw_ranges(pd_no, html, spec):
    """원문 줄을 그대로 보여준다 -- `--dump` 로 위치를 잡은 뒤 그 자리를 들여다본다.

    구조 덤프는 태그를 걷어내 «어디에 있나»만 알려준다. 파서를 쓰려면 그 자리의
    실제 마크업(감싸는 태그·class)이 필요하다. 사진이나 짐작으로 선택자를 만들지
    않기 위한 두 번째 걸음이다."""
    lines = html.splitlines()
    print("=" * 70)
    print("pd_no=%s  원문 %d줄" % (pd_no, len(lines)))
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
        else:
            lo = hi = int(part)
        lo, hi = max(1, lo), min(len(lines), hi)
        print("\n-- L%d ~ L%d ------------------------------------------------" % (lo, hi))
        for n in range(lo, hi + 1):
            print("  %-6d %s" % (n, lines[n - 1].rstrip()[:300]))


# ================================================================== 대상 ==

def targets_from_json(path, limit=None):
    """`tools/builtpc_parse.py` 산출 JSON 에서 상품번호를 읽는다."""
    data = json.load(io.open(path, encoding="utf-8"))
    rows = data.get("items") if isinstance(data, dict) else data
    codes = []
    for r in rows or []:
        c = r.get("product_code") if isinstance(r, dict) else None
        if c is not None:
            codes.append(str(c))
    return codes[:limit] if limit else codes


def targets_from_db(limit=None):
    """판매중 완제PC. sqlalchemy 는 **이 경로에서만** 쓴다(러너에서는 안 쓴다)."""
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text
    load_dotenv(os.path.join(ROOT, ".env"))
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL 이 없습니다 -- .env 를 확인하세요.")
    eng = create_engine(url)
    sql = ("SELECT product_code FROM products"
           " WHERE part_type = 'PC_COMPLETE' AND status = '판매중'"
           " ORDER BY product_code")
    if limit:
        sql += " LIMIT %d" % int(limit)
    with eng.connect() as conn:
        return [str(r[0]) for r in conn.execute(text(sql))]


# ================================================================== main ==

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--codes", default="", help="상품번호 쉼표 구분(예: 98149,98150)")
    ap.add_argument("--from-json", default="", help="builtpc_parse.py 산출 JSON 에서 대상을 읽는다")
    ap.add_argument("--from-db", action="store_true", help="판매중 완제PC 를 DB 에서 고른다")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dump", action="store_true", help="파싱하지 않고 구조만 보고한다")
    ap.add_argument("--raw", default="", help="원문 줄을 그대로 본다(예: 2000-2015,2310-2560)")
    ap.add_argument("--refetch", action="store_true", help="캐시를 무시하고 다시 받는다")
    ap.add_argument("--cache-only", action="store_true", help="네트워크를 쓰지 않는다")
    ap.add_argument("--out", default="", help="결과 JSON 경로(--dump 에는 쓰지 않는다)")
    a = ap.parse_args()

    if a.codes:
        codes = [c.strip() for c in a.codes.split(",") if c.strip()]
    elif a.from_json:
        codes = targets_from_json(a.from_json, a.limit)
    elif a.from_db:
        codes = targets_from_db(a.limit)
    else:
        raise SystemExit("--codes / --from-json / --from-db 중 하나를 주세요.")
    if a.limit:
        codes = codes[:a.limit]

    print("대상 %d건 · 간격 %.1f초 · 캐시 %s" % (len(codes), DELAY, CACHE))
    got, failed, fail_streak = [], [], 0
    for code in codes:
        try:
            html, cached = fetch(code, refetch=a.refetch, cache_only=a.cache_only)
        except RuntimeError as e:
            print("중단: %s" % e)
            break
        if not html:
            failed.append(code)
            fail_streak += 1
            print("  %s 실패(%d연속)" % (code, fail_streak))
            if fail_streak >= MAX_FAIL:
                print("연속 실패 %d회 -- 멈춥니다." % MAX_FAIL)
                break
            continue
        fail_streak = 0
        got.append(code)
        if a.raw:
            raw_ranges(code, html, a.raw)
        elif a.dump:
            dump(code, html)
        else:
            print("  %s 받음%s (%d bytes)" % (code, " [캐시]" if cached else "", len(html)))

    print("\n받음 %d건 · 실패 %d건" % (len(got), len(failed)))
    if failed:
        print("실패 목록: %s" % ",".join(failed[:50]))
    if a.out and not a.dump:
        # ⚠ 파싱은 아직 없다 -- 실측(--dump) 뒤에 이 파일에 덧붙인다.
        #    지금 단계에서 out 은 "무엇을 받았나"만 남긴다. 값을 지어내지 않는다.
        io.open(a.out, "w", encoding="utf-8").write(
            json.dumps({"fetched": got, "failed": failed, "cache": CACHE},
                       ensure_ascii=False, indent=1))
        print("기록: %s" % a.out)


if __name__ == "__main__":
    main()
