# -*- coding: utf-8 -*-
"""팝콘PC AI API 메모리 가짜. 소켓을 열지 않는다. 가이드 문서가 적은 동작만 흉내 낸다."""
import json
from urllib.parse import parse_qsl, urlsplit

from api.mall_ai_api import API_PATH, ORIGIN, BASKET_LINK_PATH, DOC_KEY_LENGTH_ERROR, TransportResponse


def json_response(document, status=200):
    return TransportResponse(status=status, body=json.dumps(document, ensure_ascii=False).encode("utf-8"),
                             content_type="application/json")


def product(pd_no, **overrides):
    item = {"pd_no": pd_no, "pd_name": "합성 상품 %s" % pd_no, "price": 150000, "mileage": 1500,
            "made": "합성 제조사", "pd_spec": "합성 규격", "pd_image_basic": "/data/pimg/1/%s_600.jpg" % pd_no,
            "pd_delivery_price": 3000}
    item.update(overrides)
    return item


class FakeMallApi:
    """price 는 카탈로그를 읽고 basket 은 키마다 목록을 교체한다."""

    basket_write_allowed = True

    def __init__(self, catalog=()):
        self.catalog = {int(c): product(int(c)) for c in catalog}
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
        codes = list(dict.fromkeys(int(c) for c in query["pd_no"].split(",")))[:50]
        return json_response({"result": "ok", "items": [self.catalog[c] for c in codes if c in self.catalog]})

    def _basket(self, query):
        key = query["api_key"]
        if len(key) != 20:
            return json_response({"error": DOC_KEY_LENGTH_ERROR})
        items = []
        for chunk in query["pd_no"].split(","):
            code, _, qty = chunk.partition(":")
            items.append({"pd_no": int(code), "qty": int(qty or 1)})
        self.baskets[key] = items
        return json_response({"result": "ok", "link": "%s%s?api_key=%s" % (ORIGIN, BASKET_LINK_PATH, key),
                              "items": items})

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
