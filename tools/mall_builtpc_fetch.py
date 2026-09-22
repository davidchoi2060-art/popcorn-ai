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


# ================================================================== 파싱 ==
#
# ■ 아래 정규식은 전부 **실측 마크업**에서 나왔다 (2026-09-22, pd_no=98149)
#   화면 사진이나 짐작으로 만든 것이 하나도 없다. 실제 원문(3,985줄)에서 확인한 자리:
#
#     L2005-2007  <span class="name">골드 NO.04.98149 ...</span>
#                 <br/><span style='font-size:15px;'>#게임용 #디자인용 ...</span>
#     L2069-2071  <ul class="price market">
#                   <li>시중가<span>1,830,000</span>원</li>
#                   <li>판매가<span>1,591,800</span>원</li>
#     L2317-2340  <tr><td class='cate'>프로세서(CPU)</td> ...
#                   <input type='hidden' id='pcode' name='pcode2' value='110964'>
#                   <a ... class='selected'> <strong>[인텔]</strong> i5 12세대 12400F ...</a>
#
# ■ 맞춤가는 «원문에 없다» -- 지어내지 않는다
#   L3030 이 `<span class="price" id='total_dealer_price'></span>` 로 **비어** 있다.
#   그 값은 브라우저에서 JS 가 부품별 값을 ajax 로 받아 더해 만든다. 우리는 JS 를
#   돌리지 않으므로 이 도구는 맞춤가를 **None 으로 둔다.** 판매가에 어떤 비율을
#   곱해 넣고 싶은 유혹이 있지만(화면상 약 0.98), 그건 관측이 아니라 추측이다.

_NAME_RE = re.compile(r'<span class="name">\s*(.*?)\s*</span>', re.S)
_TAGS_RE = re.compile(r"<span style='font-size:15px;'>\s*(#[^<]*)</span>")
_PRICE_RE = re.compile(r'<li>(시중가|판매가)<span>([\d,]+)</span>원</li>')
_ROW_RE = re.compile(
    r"<td class='cate'>(?P<cate>[^<]+)</td>.*?"
    r"name='pcode\d+' value='(?P<pcode>\d+)'.*?"
    r"class='selected'[^>]*>(?P<name>.*?)</a>", re.S)


def _clean(t):
    return _WS_RE.sub(" ", _TAG_RE.sub("", t)).strip()


def parse(pd_no, html):
    """공개 상세 페이지에서 «우리 DB 에 없는 것»을 읽는다.

    돌려주는 것: product_code · title · usage_tags · market_price(시중가) ·
    sale_price(판매가) · custom_price(항상 None, 위 주석 참조) · parts(교차 확인용).
    못 읽은 항목은 None/빈 목록이고, **그 사실을 그대로 남긴다.**
    """
    m = _NAME_RE.search(html)
    title = _clean(m.group(1)) if m else None

    m = _TAGS_RE.search(html)
    tags = [t for t in re.split(r"\s+", m.group(1).strip()) if t.startswith("#")] if m else []

    prices = {k: int(v.replace(",", "")) for k, v in _PRICE_RE.findall(html)}

    parts = []
    for r in _ROW_RE.finditer(html):
        parts.append({"cate": _clean(r.group("cate")),
                      "pcode": r.group("pcode"),
                      "name": _clean(r.group("name"))})

    return {
        "product_code": str(pd_no),
        "title": title,
        "usage_tags": tags,
        "market_price": prices.get("시중가"),
        "sale_price": prices.get("판매가"),
        "custom_price": None,        # 원문에 없다 -- JS 계산값
        "parts": parts,
    }


# 실측 원문에서 그대로 떼어낸 조각이다(합성 마크업이 아니다) -- 원천 표기가 바뀌면
# 이 자체 검사가 먼저 깨져서 알려 준다.
_FIXTURE = """
<div class="info">
\t<span class="name">
\t\t골드 NO.04.98149 [인기상품1위]인텔  [12400F/16GB/500GB/RTX5060]\t</span>
\t<br/><span style='font-size:15px;'>#게임용 #디자인용 #사무용 #녹스 #주식용 #인터넷강의 #화상회의</span>
<div class="price_wrap clear">
<ul class="price market">
<li>시중가<span>1,830,000</span>원</li>
<li>판매가<span>1,591,800</span>원</li>
</ul>
</div>
\t<tr >
\t\t<td class='cate'>프로세서(CPU)</td>
\t\t<td class='mg'><img src='/data/pimg/110/110964_300.jpg' height='46'/></td>
\t\t<td class='select'>
\t\t\t<input type='hidden' id='dealer_price' name='dealer_price2' value='0'>
\t\t\t<input type='hidden' id='pcode' name='pcode2' value='110964'>
\t\t\t<div class='select_box'>
\t\t\t\t<a href='#' class='selected' data='/x.jpg' id_no='2' pcg='10011'> <strong>[인텔]</strong> i5 12세대 12400F [Turbo 4.4GHz, 6코어/12쓰레드, VGA 미탑재] </a>
\t\t\t</div>
\t\t</td>
\t</tr>
\t<tr >
\t\t<td class='cate'>케이스</td>
\t\t<td class='select'>
\t\t\t<input type='hidden' id='pcode' name='pcode11' value='121242'>
\t\t\t<a href='#' class='selected' data='/y.jpg' id_no='11' pcg='10219'> <strong>[ABKO]</strong> U30 마린 블랙 </a>
\t\t</td>
\t</tr>
</div>
"""


def selftest():
    got = parse("98149", _FIXTURE)
    fails = []

    def eq(what, a, b):
        if a != b:
            fails.append("%s: %r != %r" % (what, a, b))

    eq("title", got["title"],
       "골드 NO.04.98149 [인기상품1위]인텔 [12400F/16GB/500GB/RTX5060]")
    eq("태그 수", len(got["usage_tags"]), 7)
    eq("첫 태그", got["usage_tags"][0], "#게임용")
    eq("시중가", got["market_price"], 1830000)
    eq("판매가", got["sale_price"], 1591800)
    eq("맞춤가", got["custom_price"], None)
    eq("부품 수", len(got["parts"]), 2)
    eq("부품1 분류", got["parts"][0]["cate"], "프로세서(CPU)")
    eq("부품1 코드", got["parts"][0]["pcode"], "110964")
    eq("부품2 분류", got["parts"][1]["cate"], "케이스")
    eq("부품2 코드", got["parts"][1]["pcode"], "121242")

    for f in fails:
        print("  X %s" % f)
    print("자체 검사: %d개 중 %d개 실패" % (11, len(fails)))
    return 1 if fails else 0


# ================================================================ 목록 탐색 ==
#
# ■ 왜 필요한가 (2026-09-22)
#   상세 페이지를 돌려면 «어떤 상품번호를 돌 것인가»가 먼저다. `--from-db` 가 정답이지만
#   그 경로는 DATABASE_URL 이 있는 자리에서만 돈다 — 서버 러너 계정(ghrunner)은
#   `/etc/popcorn-ai.env` 를 못 읽고(의도된 것), 클라우드 작업창은 5432 에 못 닿는다.
#   그래서 «몰의 공개 목록 페이지에서 상품번호를 읽는» 길을 하나 더 둔다. 여전히 GET 뿐이다.
#
# ■ 남의 주소를 받지 않는다
#   `--links` 로 준 주소가 popcornpc.co.kr 이 아니면 거부한다. 이 도구가 다른 사이트를
#   긁는 데 쓰이지 않게 하는 자물쇠다.

_HOST_OK = ("popcornpc.co.kr",)
_PDNO_RE = re.compile(r"system_detail\.html\?[^\"'<>]*?pd_no=(\d+)")
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"'<>]+)["']""", re.I)


def _same_site(url):
    m = re.match(r"https?://([^/]+)", url)
    host = (m.group(1) if m else "").split(":")[0].lower()
    return any(host == h or host.endswith("." + h) for h in _HOST_OK)


def fetch_url(url):
    """임의의 «우리 몰» 공개 페이지 원문. 캐시하지 않는다(목록은 매일 바뀐다)."""
    if not _same_site(url):
        raise SystemExit("우리 몰 주소가 아닙니다: %s" % url)
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        print("  HTTP %s  %s" % (e.code, url))
        return None
    except Exception as e:                                    # noqa: BLE001
        print("  실패(%s)  %s" % (type(e).__name__, url))
        return None
    finally:
        time.sleep(DELAY)
    return raw.decode("cp949", "replace")


def links(urls, pages=1, probe=False, save_dir=""):
    """목록 페이지에서 완제PC 상품번호를 모은다. (codes, seen_urls, hrefs)

    `{page}` 가 들어 있는 주소는 1..pages 로 펼친다. 같은 번호는 한 번만 담고,
    **발견 순서를 지킨다**(몰이 매긴 정렬을 우리가 뒤섞지 않는다).
    probe 면 그 페이지의 다른 링크도 함께 보고한다 — 목록 주소를 «찾는» 걸음이다.
    """
    codes, seen, visited = [], set(), []
    all_hrefs, href_seen = [], set()
    for base in urls:
        expanded = ([base.replace("{page}", str(i)) for i in range(1, pages + 1)]
                    if "{page}" in base else [base])
        for url in expanded:
            html = fetch_url(url)
            if html is None:
                continue
            visited.append(url)
            if save_dir:
                os.makedirs(save_dir, exist_ok=True)
                fn = os.path.join(save_dir, "list_%02d.html" % len(visited))
                io.open(fn, "w", encoding="utf-8").write(html)
                print("  원문 저장: %s (%d바이트)" % (fn, len(html)))
            found = _PDNO_RE.findall(html)
            fresh = 0
            for c in found:
                if c not in seen:
                    seen.add(c)
                    codes.append(c)
                    fresh += 1
            print("  %s  ->  상품번호 %d개(새로 %d개)" % (url, len(found), fresh))
            if probe:
                hrefs = []
                for h in _HREF_RE.findall(html):
                    if h in href_seen or h.startswith(("#", "javascript:", "mailto:")):
                        continue
                    href_seen.add(h)
                    hrefs.append(h)
                    all_hrefs.append(h)
                print("  -- 링크 후보 %d개(앞 60개만 보임) --" % len(hrefs))
                for h in hrefs[:60]:
                    print("     %s" % h[:160])
    return codes, visited, all_hrefs


# ============================================================ 목록 endpoint ==
#
# ■ 목록은 «페이지 안에» 없다 (2026-09-22 실측, list_01.html)
#   `/shop/system_list.html` 원문에는 상품 카드가 5개뿐이다(최근 본 상품 등).
#   진짜 목록은 화면이 열린 뒤 jQuery 가 불러 채운다:
#
#       $.ajax({ url: "/skin/shop/basic/system_list_include_plist.php",
#                method: "POST",
#                data: { subm, price_op_arr, cpu, ..., page, list_sort_type, view_type } })
#
#   그래서 목록 주소를 아무리 GET 해도 상품번호가 안 나온다. 이 자리를 직접 부른다.
#
# ■ GET 을 먼저 해 본다 -- 규약을 먼저 지키고, 안 되면 그 사실을 적는다
#   이 파일의 규약은 「GET 만 한다」였다(담기·저장·로그인 폼을 누르지 않겠다는 뜻).
#   PHP 가 $_REQUEST 를 읽으면 GET 으로도 같은 목록이 나오므로 **GET 을 먼저** 보낸다.
#   그것이 비면 같은 자리에 POST 로 한 번 더 묻는다 -- **조회 전용 목록이라** 담기·
#   저장·주문과 성격이 다르다(상태를 바꾸지 않는다). 어느 쪽으로 받았는지 보고에 남긴다.

PLIST = BASE + "/skin/shop/basic/system_list_include_plist.php"
_TOTAL_RE = re.compile(r"id=[\"']total_num[\"'][^>]*value=[\"'](\d+)[\"']")


def _plist_once(page, post=False):
    """목록 한 쪽. (html, 방식) -- 못 받으면 (None, 방식)."""
    fields = {"page": str(page), "list_sort_type": "", "view_type": ""}
    body = "&".join("%s=%s" % (k, v) for k, v in fields.items())
    if post:
        req = urllib.request.Request(
            PLIST, data=body.encode("utf-8"),
            headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9",
                     "Content-Type": "application/x-www-form-urlencoded",
                     "X-Requested-With": "XMLHttpRequest",
                     "Referer": BASE + "/shop/system_list.html"})
    else:
        req = urllib.request.Request(
            PLIST + "?" + body,
            headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9",
                     "Referer": BASE + "/shop/system_list.html"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
    except Exception as e:                                    # noqa: BLE001
        print("  %s 쪽%d 실패(%s)" % ("POST" if post else "GET", page, type(e).__name__))
        return None, ("POST" if post else "GET")
    finally:
        time.sleep(DELAY)
    return raw.decode("cp949", "replace"), ("POST" if post else "GET")


def collect_plist(max_pages=50, save_dir=""):
    """목록 endpoint 를 1쪽부터 훑어 상품번호를 모은다. (codes, how, total)

    첫 쪽에서 «어느 방식으로 목록이 오는지»를 정하고(GET 먼저, 비면 POST),
    그다음부터는 그 방식만 쓴다. 새 번호가 하나도 안 나오는 쪽을 만나면 멈춘다 --
    몰이 마지막 쪽을 되풀이해 돌려주는 경우가 있어 쪽 수만 믿지 않는다.
    """
    codes, seen, how, total = [], set(), None, None
    for page in range(1, max_pages + 1):
        if how is None:
            html, _ = _plist_once(page, post=False)
            how = "GET"
            if html is None or not _PDNO_RE.search(html):
                print("  GET 으로는 목록이 비었습니다 -- 같은 자리에 POST 로 다시 묻습니다.")
                html, _ = _plist_once(page, post=True)
                how = "POST"
        else:
            html, _ = _plist_once(page, post=(how == "POST"))
        if html is None:
            break
        if save_dir and page <= 2:
            os.makedirs(save_dir, exist_ok=True)
            io.open(os.path.join(save_dir, "plist_%02d.html" % page),
                    "w", encoding="utf-8").write(html)
        m = _TOTAL_RE.search(html)
        if m and total is None:
            total = int(m.group(1))
        found = _PDNO_RE.findall(html)
        # 한 쪽 안에서도 같은 번호가 여러 번 나온다(카드·썸네일·비교 링크가 각각
        # 같은 상세 주소를 건다 -- 실측 212건이 636번 등장). 담으면서 걸러야 한다.
        fresh = []
        for c in found:
            if c in seen:
                continue
            seen.add(c)
            codes.append(c)
            fresh.append(c)
        print("  %s 쪽%-3d  상품번호 %d개(새로 %d개)%s"
              % (how, page, len(found), len(fresh),
                 "  몰이 말한 전체 %s건" % total if total is not None and page == 1 else ""))
        if not fresh:
            break
    return codes, how, total


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
    ap.add_argument("--links", default="",
                    help="목록 페이지에서 상품번호를 읽는다(쉼표 구분 · {page} 지원)")
    ap.add_argument("--pages", type=int, default=1, help="--links 의 {page} 를 1..N 으로 펼친다")
    ap.add_argument("--probe", action="store_true", help="--links 에서 다른 링크도 함께 보고한다")
    ap.add_argument("--plist", action="store_true",
                    help="몰 목록 endpoint 를 훑어 완제PC 상품번호를 모은다")
    ap.add_argument("--max-pages", type=int, default=50, help="--plist 가 볼 최대 쪽 수")
    ap.add_argument("--save-dir", default="", help="--links 로 받은 목록 원문을 이 폴더에 남긴다")
    ap.add_argument("--links-only", action="store_true",
                    help="상품번호만 모으고 상세 페이지는 받지 않는다")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dump", action="store_true", help="파싱하지 않고 구조만 보고한다")
    ap.add_argument("--raw", default="", help="원문 줄을 그대로 본다(예: 2000-2015,2310-2560)")
    ap.add_argument("--selftest", action="store_true", help="실측 조각으로 파서만 검사한다(네트워크 없음)")
    ap.add_argument("--refetch", action="store_true", help="캐시를 무시하고 다시 받는다")
    ap.add_argument("--cache-only", action="store_true", help="네트워크를 쓰지 않는다")
    ap.add_argument("--out", default="", help="결과 JSON 경로(--dump 에는 쓰지 않는다)")
    a = ap.parse_args()

    if a.selftest:
        raise SystemExit(selftest())

    if a.plist:
        print("목록 endpoint 훑기 · 최대 %d쪽 · 간격 %.1f초" % (a.max_pages, DELAY))
        codes, how, total = collect_plist(a.max_pages, save_dir=a.save_dir)
        print("\n상품번호 %d개 (몰이 말한 전체 %s건 · %s 로 받음)"
              % (len(codes), total if total is not None else "?", how or "?"))
        if a.out:
            io.open(a.out, "w", encoding="utf-8").write(
                json.dumps({"codes": codes, "method": how, "total_reported": total},
                           ensure_ascii=False, indent=1))
            print("기록: %s" % a.out)
        if a.links_only:
            return
    elif a.links:
        urls = [u.strip() for u in a.links.split(",") if u.strip()]
        print("목록 탐색 %d주소 · 쪽 %d · 간격 %.1f초" % (len(urls), a.pages, DELAY))
        codes, visited, hrefs = links(urls, pages=a.pages, probe=a.probe,
                                      save_dir=a.save_dir)
        print("\n상품번호 %d개: %s" % (len(codes), ",".join(codes[:200])))
        if len(codes) > 200:
            print("(앞 200개만 보였습니다)")
        if a.out:
            io.open(a.out, "w", encoding="utf-8").write(
                json.dumps({"codes": codes, "sources": visited, "hrefs": hrefs},
                           ensure_ascii=False, indent=1))
            print("기록: %s" % a.out)
        if a.links_only:
            return
    elif a.codes:
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
    got, failed, rows, fail_streak = [], [], [], 0
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
        if a.save_dir and len(got) <= 5:                      # 확인용 표본만
            os.makedirs(a.save_dir, exist_ok=True)
            io.open(os.path.join(a.save_dir, "detail_%s.html" % code),
                    "w", encoding="utf-8").write(html)
        if a.raw:
            raw_ranges(code, html, a.raw)
        elif a.dump:
            dump(code, html)
        else:
            row = parse(code, html)
            rows.append(row)
            print("  %s%s  %s" % (code, " [캐시]" if cached else "", row["title"]))
            print("      시중가 %s · 판매가 %s · 맞춤가 %s"
                  % (row["market_price"], row["sale_price"],
                     row["custom_price"] if row["custom_price"] is not None else "(원문에 없음)"))
            print("      용도 %s" % (" ".join(row["usage_tags"]) or "(없음)"))
            print("      부품 %d개: %s" % (len(row["parts"]),
                                           ", ".join(p["cate"] for p in row["parts"])))

    print("\n받음 %d건 · 실패 %d건" % (len(got), len(failed)))
    if failed:
        print("실패 목록: %s" % ",".join(failed[:50]))
    if a.out and not (a.dump or a.raw):
        io.open(a.out, "w", encoding="utf-8").write(
            json.dumps({"items": rows, "failed": failed, "cache": CACHE},
                       ensure_ascii=False, indent=1))
        print("기록: %s" % a.out)


if __name__ == "__main__":
    main()
