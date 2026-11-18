# -*- coding: utf-8 -*-
"""팝콘PC AI API 메모리 가짜. 소켓을 열지 않는다.

price 는 2026-11-17 실측한 새 응답을 흉내 낸다(checked_at, items, not_found). basket 은 v3 명세 모양
{cart_url, added, skipped, total} 이다(윈윈 답변 2026-11-17 - 실측 예시는 11-21 예정이라 항목 모양은 가정이다).
값은 전부 합성이다.
"""
import json
from urllib.parse import parse_qsl, urlsplit

from api.mall_ai_api import (API_PATH, ORIGIN, BASKET_LINK_PATH, DOC_KEY_LENGTH_ERROR, PRICE_TOO_MANY_ERROR,
                             TransportResponse)

CHECKED_AT = "2026-11-17 14:42:35"          # 실측 형식(시간대 표시 없음)
CHECKED_AT_ISO = "2026-11-17T14:42:35+09:00"    # 명세 형식
IP_DENIED_ERROR = "허용되지 않은 IP"


def json_response(document, status=200):
    return TransportResponse(status=status, body=json.dumps(document, ensure_ascii=False).encode("utf-8"),
                             content_type="application/json")


def product(pd_no, **overrides):
    """새 price 항목. 실측대로 status 는 sold_out, max_qty 는 null 이 기본이다."""
    item = {"pd_no": pd_no, "name": "합성 상품 %s" % pd_no, "price": 150000, "status": "sold_out", "max_qty": None}
    item.update(overrides)
    return item


def price_response(items, not_found=None, checked_at=CHECKED_AT, **extra):
    """정상 price 봉투. not_found 는 없으면 null 이다([] 가 아니다)."""
    document = {"checked_at": checked_at, "items": list(items), "not_found": not_found}
    document.update(extra)
    return json_response(document)


_EXPECTED_LINK = object()


def basket_response(key, added, skipped=(), total=None, link=_EXPECTED_LINK, **extra):
    """v3 basket 봉투. total 은 added 줄 수가 기본이다(뜻은 11-21 실측 뒤 확정). link 는 None 도 그대로 넣는다."""
    document = {"cart_url": "%s%s?api_key=%s" % (ORIGIN, BASKET_LINK_PATH, key) if link is _EXPECTED_LINK else link,
                "added": list(added), "skipped": list(skipped), "total": len(added) if total is None else total}
    document.update(extra)
    return json_response(document)


def ip_denied_response():
    return json_response({"error": IP_DENIED_ERROR}, status=403)


def too_many_response():
    return json_response({"error": PRICE_TOO_MANY_ERROR}, status=400)


class FakeMallApi:
    """price 는 카탈로그를 읽고 basket 은 키마다 목록을 교체한다."""

    basket_write_allowed = True

    def __init__(self, catalog=(), skip=()):
        self.catalog = {int(c): product(int(c)) for c in catalog}
        self.skip = {int(c) for c in skip}       # basket 이 skipped 로 답할 번호(합성)
        self.baskets = {}
        self.calls = []
        self.before_reply = None    # 응답 직전 훅(동시성 시험용)

    def get(self, url, *, timeout, max_bytes):
        self.calls.append(url)
        if self.before_reply:
            self.before_reply(url)
        parts = urlsplit(url)
        assert "%s://%s" % (parts.scheme, parts.netloc) == ORIGIN and parts.path == API_PATH
        query = dict(parse_qsl(parts.query))
        if query["api_id"] == "price":
            return self._price(query)
        if query["api_id"] == "basket":
            return self._basket(query)
        return json_response({"result": "fail"})

    def _price(self, query):
        try:
            codes = list(dict.fromkeys(int(c) for c in query["pd_no"].split(",")))
        except ValueError:
            return price_response([])       # 실측: pd_no=abc 도 200 에 빈 items, not_found null
        if len(codes) > 50:
            return too_many_response()
        absent = [c for c in codes if c not in self.catalog]
        return price_response([self.catalog[c] for c in codes if c in self.catalog], absent or None)

    def _basket(self, query):
        key = query["api_key"]
        if len(key) != 20:
            return json_response({"error": DOC_KEY_LENGTH_ERROR})
        added, skipped = [], []
        for chunk in query["pd_no"].split(","):
            code, _, qty = chunk.partition(":")
            if int(code) in self.skip:
                skipped.append({"pd_no": int(code), "reason": "sold_out"})
            else:
                added.append({"pd_no": int(code), "qty": int(qty or 1)})
        self.baskets[key] = added
        return basket_response(key, added, skipped)

    def basket_calls(self):
        return [u for u in self.calls if "api_id=basket" in u]


class ScriptedTransport:
    """정해 둔 응답을 차례로 돌려준다. 예외면 던진다."""

    def __init__(self, *replies, basket_write_allowed=False):
        self.replies = list(replies)
        self.calls = []
        self.basket_write_allowed = basket_write_allowed

    def get(self, url, *, timeout, max_bytes):
        self.calls.append(url)
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply
