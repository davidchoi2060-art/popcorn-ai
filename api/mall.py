# -*- coding: utf-8 -*-
"""팝콘PC 쇼핑몰(윈윈소프트) 조회 — **임시 구현**

■ 이건 갈아 끼울 자리다
  윈윈소프트에 API 5종을 요청해 두었다(`docs/design/winwin-api-request-2026-08-11.md`).
  1순위가 「상품 벌크 조회」이고, 그게 나오면 `fetch_prices()` 의 **속만 바꾸면 된다.**
  호출부(`api/handoff.py`)는 손대지 않는다 — 그러라고 함수 하나로 가둬 놨다.

■ 지금은 상품 상세 페이지를 읽는다
  공개 페이지에 대한 GET 뿐이다. 폼 제출·담기·저장은 하지 않는다.
  상세 페이지의 `product_detail` 폼에 숨은 값이 그대로 들어 있다(2026-08-11 실측):

      pd_no · price · dealer_price · mileage · flag · barogume · returnUrl

  `pd_no` 는 우리 `products.product_code` 와 **같은 값**이다(실측 확인).

■ 느리다는 것을 숨기지 않는다
  한 건에 한 번의 왕복이라 부품 8개면 8번이다. 그래서 **동시에 몇 개씩** 가져오되
  상대 서버를 두들기지 않도록 제한을 둔다. 이 느림이 곧 API 요청의 근거다.
"""
import concurrent.futures as _cf
import re
import urllib.request

BASE = "https://popcornpc.co.kr"
DETAIL = BASE + "/shop/product_detail.html?pd_no=%s"
TIMEOUT = 6           # 초 — 견적 확정 직전이라 오래 끌 수 없다
WORKERS = 4           # 동시 요청 — 남의 서버다. 늘리지 않는다
UA = "popcorn-ai/1.0 (+price re-check before handoff)"

_HIDDEN = r'name=["\']%s["\'][^>]*value=["\']([^"\']*)["\']'
_HIDDEN_R = r'value=["\']([^"\']*)["\'][^>]*name=["\']%s["\']'

# 품절 표시 — 2026-08-20 실측(pd_no 127897·129334, 검증자 지목분).
# 정상 판매 상품(예: pd_no 92983)의 같은 자리는
#   <a ... class="btn buy_btn">구매하기</a> / class="btn basket_btn">장바구니</a>
# 이고, 품절이면 그 자리가 통째로 이걸로 바뀐다:
#   <a class="btn soldout soldout1"><span>품절</span> 상품입니다.</a>
# ⚠ 「품절」 단어만 찾으면 오탐이다 — 이 페이지들은 상품 상태와 무관하게 하단
#   배송정책 문구에 "일시품절, 제조사 상품수급 문제…" 를 **항상** 싣는다(정상
#   판매 상품 92983 페이지에도 있음, 실측 확인). 그래서 버튼 class(`btn soldout`)와
#   그 안의 문구(「품절 … 상품입니다」)를 **함께** 요구해 그 한 자리만 겨냥한다.
_SOLDOUT_RE = re.compile(
    r'class="btn\s+soldout[^"]*"[^>]*>\s*<span>\s*품절\s*</span>\s*상품입니다')


def _field(html: str, name: str):
    for pat in (_HIDDEN, _HIDDEN_R):
        m = re.search(pat % re.escape(name), html)
        if m:
            return m.group(1)
    return None


def _one(code: int) -> dict:
    """상품 하나의 몰 가격. 못 읽으면 price=None 으로 돌려준다 — **추측하지 않는다.**

    ■ 2026-08-20 추가 — `soldout` 필드
      같은 상세 페이지를 이미 읽고 있으니 그 안의 품절 표시도 함께 읽는다.
      **기존 계약은 그대로 둔다** — `ok`/`price`를 읽는 기존 호출부가 있어서
      필드를 덧붙이기만 한다. 실측(127897·129334, 검증자 지목분): 몰이 품절이어도
      `price` hidden 필드에는 마지막 판매가가 그대로 남아 있다 — 그래서 `ok=True`·
      `price=<값>` 인 채로 `soldout=True` 가 함께 온다. 「가격은 맞는데 못 산다」를
      가격 유무만으로는 알 수 없는 이유가 이거다.

      인코딩: 이 페이지는 `euc-kr`(meta charset·응답 헤더 Content-Type 둘 다 실측
      확인). 아래 가격 hidden 필드 추출은 그대로 utf-8 로 읽는다 — 값이 숫자뿐이라
      ASCII 영역만 쓰고, ASCII 는 utf-8·euc-kr 어느 쪽으로 디코딩해도 같은 문자가
      나와 지장이 없었다(그래서 그 경로는 건드리지 않았다). 그러나 한글 품절
      문구는 다르다 — 원문 바이트를 utf-8 로 읽으면 깨져서 「품절」과 같은 문자열이
      **전혀 매치되지 않는다**(실측: utf-8 디코딩 결과에서 검색 시 -1). 그래서
      원문 바이트를 **`cp949`로 따로 한 번 더** 디코딩해 그 문구를 찾는다 — cp949 는
      euc-kr 의 상위호환이라 이 페이지(euc-kr)를 그대로 읽으면서도, 표준 `euc-kr`
      코덱보다 관대해(확장 완성형 포함) 디코딩 예외로 죽을 일이 적다.
    """
    out = {"product_code": code, "price": None, "dealer_price": None, "ok": False, "err": None,
           "soldout": False}
    try:
        req = urllib.request.Request(DETAIL % code, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
        html = raw.decode("utf-8", "ignore")
        # **「몰에 없는 상품」과 「0원인 상품」은 다르다.**
        #   2026-08-11: `data_origin='demo'` 인 8자리 코드(시연용 가짜 상품)로 요청하면
        #   페이지는 200 으로 열리는데 pd_no 폼이 없거나 가격이 비어 나온다.
        #   이걸 0원으로 받아 15만원짜리 부품 둘을 공짜로 넘길 뻔했다.
        #   pd_no 가 되돌아오는지로 「그 상품 페이지가 맞는지」부터 확인한다.
        back = _field(html, "pd_no")
        if back is None or back.strip() != str(code):
            out["err"] = "몰에 없는 상품"
            return out
        # 품절 판정 — 이 페이지가 맞는 상품임을 확인한 뒤에 본다(가격 필드 성패와 무관하게
        # 남긴다 — 가격을 못 읽어도 품절 여부 자체는 다음 코드가 판단 재료로 쓸 수 있다).
        try:
            html_kr = raw.decode("cp949", "replace")
        except Exception:                                     # noqa: BLE001 — 방어적 폴백
            html_kr = ""
        if _SOLDOUT_RE.search(html_kr):
            out["soldout"] = True
        p = _field(html, "price")
        if p is None or not p.strip().isdigit():
            out["err"] = "가격 필드 없음"
            return out
        p = int(p)
        if p <= 0:
            out["err"] = "몰 가격 0원"      # 팔 수 없는 값이다 — 성공으로 치지 않는다
            return out
        out["price"] = p
        d = _field(html, "dealer_price")
        out["dealer_price"] = int(d) if d and d.strip().isdigit() else None
        out["ok"] = True
    except Exception as e:                                   # noqa: BLE001
        out["err"] = type(e).__name__
    return out


def fetch_prices(codes) -> dict:
    """상품코드 목록 → {code: {price, dealer_price, ok, err, soldout}}

    **부분 실패를 통째 실패로 만들지 않는다.** 8개 중 1개를 못 읽어도 나머지는 쓴다.
    못 읽은 건은 `ok=False` 로 남고, 호출부가 「확인 못 함」으로 고객에게 알린다.

    `soldout`(2026-08-20 추가)은 **`ok`/`price` 와 별개**다 — 몰이 품절이어도 가격
    hidden 필드는 대개 살아 있어 `ok=True`·`price=<마지막 판매가>` 인 채로
    `soldout=True` 가 온다(실측 `_one()` 참조). 기존 호출부가 `ok`/`price` 만
    읽어도 동작은 그대로다 — 계약을 깨지 않고 필드만 더했다.
    """
    codes = [int(c) for c in dict.fromkeys(codes) if c]      # 중복 제거 · 순서 유지
    if not codes:
        return {}
    with _cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        return {r["product_code"]: r for r in ex.map(_one, codes)}
