# -*- coding: utf-8 -*-
"""쇼핑몰 공개 상품 페이지에서 지금 판매가 하나를 읽는다 (2026-10-11).

두 겹 안전장치의 두 자리가 이 함수를 같이 쓴다.
  · 1겹 자동 갱신 — 관리자 상품엑셀을 못 받았을 때 상품마다 읽는 길(요청 간격을 둔다)
  · 2겹 실시간    — 장바구니에 넣는 순간 · 결제로 넘어가는 순간(짧은 시간 제한)

■ 새로 파싱하지 않는다 — 이미 실측으로 확인된 두 읽기를 그대로 부른다
  완제품 PC  /shop/system_detail.html  `tools/mall_builtpc_fetch.parse()` 의 「판매가」
             (2026-09-22 pd_no=98149 원문에서 뽑은 정규식 · 자체 시험 있음)
  부품       /shop/product_detail.html `api/mall._one()` 의 hidden `price`
             (pd_no 되돌림 검사로 「몰에 없는 상품」과 「0원」을 가른다)

■ 익명으로 읽는다
  고객이 보는 값이 기준이다. 관리자 세션을 실어 보내지 않는다 — 로그인한 화면은
  회원 등급 가격을 보여 줄 수 있다.

못 읽으면 ok=False 와 사유를 돌려준다. **추측하지 않는다.**
"""
import urllib.error
import urllib.request

BASE = "https://www.popcornpc.co.kr"
PC_URL = BASE + "/shop/system_detail.html?pd_no=%s"
PART_URL = BASE + "/shop/product_detail.html?pd_no=%s"
UA = "popcorn-ai/1.0 (+price check)"
PC_PART_TYPE = "PC_COMPLETE"


def product_url(code: int, part_type: str | None) -> str:
    return (PC_URL if part_type == PC_PART_TYPE else PART_URL) % int(code)


def _read_pc(code: int, timeout: float) -> dict:
    from tools.mall_builtpc_fetch import parse            # 실측 정규식의 단일 원천
    url = PC_URL % int(code)
    out = {"product_code": int(code), "ok": False, "price": None, "err": None, "url": url}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Accept-Language": "ko-KR,ko;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("cp949", "replace")
    except urllib.error.HTTPError as e:
        out["err"] = "HTTP %s" % e.code
        return out
    except Exception as e:                                      # noqa: BLE001
        out["err"] = type(e).__name__
        return out
    got = parse(code, html)
    price = got.get("sale_price")
    if not got.get("title") or price is None:
        out["err"] = "판매가를 찾지 못함"
    elif price <= 0:
        out["err"] = "쇼핑몰 가격 0원"
    else:
        out.update(ok=True, price=int(price))
    return out


def _read_part(code: int, timeout: float) -> dict:
    from . import mall
    old = mall.TIMEOUT
    mall.TIMEOUT = timeout
    try:
        r = mall._one(int(code))
    finally:
        mall.TIMEOUT = old
    return {"product_code": int(code), "ok": bool(r["ok"]), "price": r["price"],
            "err": r["err"], "url": PART_URL % int(code), "soldout": r.get("soldout", False)}


def read_price(code: int, part_type: str | None, *, timeout: float = 6.0) -> dict:
    """상품 하나의 쇼핑몰 현재 판매가. {product_code, ok, price, err, url}"""
    if part_type == PC_PART_TYPE:
        return _read_pc(code, timeout)
    return _read_part(code, timeout)
