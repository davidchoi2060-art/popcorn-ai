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


def _field(html: str, name: str):
    for pat in (_HIDDEN, _HIDDEN_R):
        m = re.search(pat % re.escape(name), html)
        if m:
            return m.group(1)
    return None


def _one(code: int) -> dict:
    """상품 하나의 몰 가격. 못 읽으면 price=None 으로 돌려준다 — **추측하지 않는다.**"""
    out = {"product_code": code, "price": None, "dealer_price": None, "ok": False, "err": None}
    try:
        req = urllib.request.Request(DETAIL % code, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            html = r.read().decode("utf-8", "ignore")
        # **「몰에 없는 상품」과 「0원인 상품」은 다르다.**
        #   2026-08-11: `data_origin='demo'` 인 8자리 코드(시연용 가짜 상품)로 요청하면
        #   페이지는 200 으로 열리는데 pd_no 폼이 없거나 가격이 비어 나온다.
        #   이걸 0원으로 받아 15만원짜리 부품 둘을 공짜로 넘길 뻔했다.
        #   pd_no 가 되돌아오는지로 「그 상품 페이지가 맞는지」부터 확인한다.
        back = _field(html, "pd_no")
        if back is None or back.strip() != str(code):
            out["err"] = "몰에 없는 상품"
            return out
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
    """상품코드 목록 → {code: {price, dealer_price, ok, err}}

    **부분 실패를 통째 실패로 만들지 않는다.** 8개 중 1개를 못 읽어도 나머지는 쓴다.
    못 읽은 건은 `ok=False` 로 남고, 호출부가 「확인 못 함」으로 고객에게 알린다.
    """
    codes = [int(c) for c in dict.fromkeys(codes) if c]      # 중복 제거 · 순서 유지
    if not codes:
        return {}
    with _cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        return {r["product_code"]: r for r in ex.map(_one, codes)}
