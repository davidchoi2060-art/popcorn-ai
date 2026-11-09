# -*- coding: utf-8 -*-
"""팝콘PC AI API 29개 케이스 (기획서 P01~P12, B01~B12, A01~A03, S01~S02).

전부 메모리 가짜 또는 로컬 차단 시험이다. 모듈 전체에서 소켓 연결을 잡아 0회인지 끝에서 확인한다.
테스트 이름 앞의 ID 는 tools/popcorn_api_runner.py 가 케이스 결과로 묶는 기준이다.
"""
import ast
import contextlib
import hashlib
import io
import json
import logging
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import traceback
import unittest
import urllib.error
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import mall_ai_api as M                                       # noqa: E402
from api import mall_asus_cart as AC                                   # noqa: E402
from api.mall_ai_api import MallApiError, TransportResponse as R       # noqa: E402
from tests.popcorn_pc_fake_api import FakeMallApi, ScriptedTransport, json_response, product  # noqa: E402

CASE_IDS = (["P%02d" % i for i in range(1, 13)] + ["B%02d" % i for i in range(1, 13)]
            + ["A01", "A02", "A03", "S01", "S02"])
KEY = "abcde12345abcde12345"
OTHER_KEY = "zzzzz99999zzzzz99999"
LINK = "https://popcornpc.co.kr/shop/order_basket_list.html?api_key=" + KEY
SYNTHETIC = {"business": "900000001", "video": "900000002", "local-ai": "900000003"}
_net = {"attempts": 0}
_patches = []


def _blocked(*_a, **_k):
    _net["attempts"] += 1
    raise AssertionError("network attempted")


def setUpModule():
    _net["attempts"] = 0
    for target in ("socket.socket.connect", "socket.create_connection", "urllib.request.urlopen"):
        p = patch(target, _blocked)
        p.start()
        _patches.append(p)


def tearDownModule():
    while _patches:
        _patches.pop().stop()
    assert _net["attempts"] == 0, "소켓 연결 시도 %d회" % _net["attempts"]


def ok_price(items):
    return json_response({"result": "ok", "items": items})


def ok_basket(items, link=LINK):
    return json_response({"result": "ok", "link": link, "items": items})


class Base(unittest.TestCase):
    def code_of(self, fn, *args, **kwargs):
        with self.assertRaises(MallApiError) as caught:
            fn(*args, **kwargs)
        return caught.exception.code

    def price(self, reply, codes=("124401",)):
        return M.fetch_prices(codes, transport=ScriptedTransport(reply))

    def basket(self, reply, lines=(("124401", 1),)):
        t = ScriptedTransport(reply, basket_write_allowed=True)
        return M.BasketClient(t).replace(KEY, lines), t


class Price(Base):
    def test_P01_single_item_utf8_and_amount(self):
        t = ScriptedTransport(ok_price([product(124401, pd_name="한글 상품명", price=150000)]))
        result = M.fetch_prices([124401], transport=t)
        item = result.items["124401"]
        self.assertTrue(item.found)
        self.assertEqual(item.name, "한글 상품명")
        self.assertEqual(item.price.usable, Decimal(150000))
        self.assertEqual(t.calls, ["https://popcornpc.co.kr/shop/ai_api.php?api_id=price&pd_no=124401"])

    def test_P02_three_items_any_order_and_missing_identified(self):
        reply = ok_price([product(124409), product(124401)])
        result = M.fetch_prices(["124401", "124407", "124409"], transport=ScriptedTransport(reply))
        self.assertEqual(list(result.items), ["124401", "124407", "124409"])
        self.assertEqual(result.missing, ("124407",))
        self.assertTrue(result.items["124409"].found)

    def test_P03_duplicates_removed_first_order_kept(self):
        fake = FakeMallApi([3, 1, 2])
        result = M.fetch_prices([3, "1", 3, 2, "1"], transport=fake)
        self.assertEqual(result.requested, ("3", "1", "2"))
        self.assertTrue(fake.calls[0].endswith("pd_no=3,1,2"))

    def test_P04_boundary_0_50_51_no_silent_cut(self):
        fake = FakeMallApi(range(1, 52))
        self.assertEqual(self.code_of(M.fetch_prices, [], transport=fake), "empty_request")
        self.assertEqual(self.code_of(M.fetch_prices, range(1, 52), transport=fake), "too_many_items")
        self.assertEqual(fake.calls, [])
        self.assertEqual(len(M.fetch_prices(range(1, 51), transport=fake).items), 50)
        self.assertEqual(len(fake.calls), 1)

    def test_P05_bad_codes_rejected_before_any_request(self):
        fake = FakeMallApi([1])
        bad = ["", " 1", "1 ", "1\n", "0", "-1", "01", "1e5", "1.5", "1,2", "1:2", "1&api_id=basket", "1;drop",
               "١٢", "１２", True, None, 1.0, -1, 0, ["1"], "9" * 13]
        for value in bad:
            self.assertEqual(self.code_of(M.fetch_prices, [value], transport=fake), "invalid_pd_no", repr(value))
        self.assertEqual(self.code_of(M.fetch_prices, "1,2", transport=fake), "invalid_pd_no")
        self.assertEqual(fake.calls, [])

    def test_P06_missing_item_is_explicit_never_zero(self):
        result = self.price(ok_price([]), ("999",))
        self.assertEqual(result.missing, ("999",))
        item = result.items["999"]
        self.assertFalse(item.found)
        self.assertIsNone(item.price.usable)
        self.assertEqual(item.price.status, "missing")
        self.assertEqual(item.public()["price"], {"status": "missing", "value": None})

    def test_P07_amount_classification(self):
        cases = [(None, "null", None), ("abc", "invalid", None), ("", "invalid", None), ("1,000", "invalid", None),
                 (True, "invalid", None), ([1], "invalid", None), (0, "zero", None), ("0", "zero", None),
                 (-1, "negative", None), ("-1", "negative", None), (150000, "ok", Decimal(150000)),
                 ("150000", "ok", Decimal(150000)), (10 ** 13, "invalid", None)]
        for raw, status, usable in cases:
            amount = self.price(ok_price([product(1, price=raw)]), ("1",)).items["1"].price
            self.assertEqual((amount.status, amount.usable), (status, usable), repr(raw))
        body = b'{"result":"ok","items":[{"pd_no":1,"price":0.1,"mileage":1e5,"pd_delivery_price":12345678901.10}]}'
        item = self.price(R(200, body), ("1",)).items["1"]
        self.assertEqual((item.price.status, item.price.value), ("non_integer", Decimal("0.1")))
        self.assertEqual(item.mileage.status, "invalid")
        self.assertEqual(item.delivery_price.value, Decimal("12345678901.10"))
        self.assertIsNone(item.delivery_price.usable)
        no_fields = self.price(ok_price([{"pd_no": 1}]), ("1",)).items["1"]
        self.assertEqual(no_fields.price.status, "missing")
        self.assertEqual(no_fields.delivery_price.status, "missing")

    def test_P08_malformed_bodies_fail_explicitly(self):
        cases = [(b"<html>x</html>", "html_response"), (b"  <!doctype html>", "html_response"), (b"", "empty_body"),
                 (b"  \n", "empty_body"), (b"{bad", "bad_json"), (b'{"result":"ok","items":[NaN]}', "bad_json"),
                 (b'{"result":"ok","result":"ok","items":[]}', "bad_json"), (b"[" * 200000, "bad_json"),
                 (b"\xff\xfe", "bad_encoding"), ('{"a":"한"}'.encode("cp949"), "bad_encoding"),
                 (b"[]", "bad_shape"), (b'{"result":"ok"}', "bad_shape"), (b'{"result":"ok","items":{}}', "bad_shape"),
                 (b'{"result":"ok","items":[1]}', "bad_shape"), (b'{"result":"fail","items":[]}', "bad_result"),
                 (b'{"items":[]}', "bad_result"), (b'{"result":"ok","error":"x","items":[]}', "bad_result"),
                 (b'{"error":"anything"}', "api_error")]
        for body, code in cases:
            self.assertEqual(self.code_of(self.price, R(200, body)), code, body[:40])

    def test_P09_status_timeout_size_limited_and_not_retried(self):
        cases = [(R(301), "redirect"), (R(302), "redirect"), (R(204), "http_status"), (R(404), "http_4xx"),
                 (R(429), "rate_limited"), (R(500), "http_5xx"), (R(503), "http_5xx"),
                 (M.TransportTimeout(), "timeout"), (M.TransportTooLarge(), "response_too_large"),
                 (OSError("boom"), "network"), (R(200, b"x" * 11), "response_too_large")]
        for reply, code in cases:
            t = ScriptedTransport(reply, ok_price([product(1)]))
            limits = M.Limits(max_response_bytes=10)
            self.assertEqual(self.code_of(M.fetch_prices, [1], transport=t, limits=limits), code)
            self.assertEqual(len(t.calls), 1, code)     # 두 번째 응답을 쓰지 않는다

    def test_P10_html_and_url_injection_neutralized(self):
        attack = ('<img src=x onerror=alert(1)><script>steal()</script>규격<b>A</b> &lt;script&gt;x&lt;/script&gt; '
                  '&amp;lt;svg onload=y&amp;gt; <a href="javascript:z">t</a> <img src=x')
        result = self.price(ok_price([product(1, pd_spec=attack, pd_name=attack, made=attack)]), ("1",))
        public = json.dumps(result.items["1"].public(), ensure_ascii=False)
        self.assertNotIn("<", public)
        self.assertNotIn("steal()", public)
        self.assertIn("규격", result.items["1"].spec_text)
        for bad in ["javascript:alert(1)", "data:image/png;base64,AA", "//evil.test/a.jpg", "http://popcornpc.co.kr/a.jpg",
                    "https://evil.test/a.jpg", "https://popcornpc.co.kr@evil.test/a.jpg", "https://u:p@popcornpc.co.kr/a.jpg",
                    "https://popcornpc.co.kr:8443/a.jpg", "https://popcornpc.co.kr/a.svg", "/../../etc/a.jpg", "/a%2e%2e/a.jpg",
                    "\\\\evil\\a.jpg", "/a b.jpg", "/a.jpg?x=1", "https://popcornpc.co.kr/a.jpg#f", 5]:
            item = self.price(ok_price([product(1, pd_image_basic=bad)]), ("1",)).items["1"]
            self.assertEqual((item.image_status, item.image_url, item.image_path), ("rejected", None, None), repr(bad))
        good = self.price(ok_price([product(1, pd_image_basic="https://www.popcornpc.co.kr/data/pimg/1/1_600.jpg")]), ("1",))
        self.assertEqual(good.items["1"].image_status, "absolute")
        relative = self.price(ok_price([product(1, pd_image_basic="data/1_600.jpg")]), ("1",)).items["1"]
        self.assertEqual((relative.image_status, relative.image_url), ("relative", None))

    def test_P11_unknown_fields_hidden_and_foreign_items_rejected(self):
        secret = "SUPPLIER-COST-777"
        result = self.price(ok_price([product(1, cost_price=secret, supplier=secret)]), ("1",))
        self.assertNotIn(secret, json.dumps(result.public(), ensure_ascii=False))
        self.assertNotIn(secret, json.dumps(result.allowed_raw, ensure_ascii=False))
        self.assertNotIn(secret, repr(result))
        self.assertEqual(result.dropped_field_count, 2)
        self.assertEqual(self.code_of(self.price, ok_price([product(1), product(2)]), ("1",)), "unexpected_item")
        self.assertEqual(self.code_of(self.price, ok_price([product(1), product(1)]), ("1",)), "duplicate_item")

    def test_P12_stock_currency_tax_never_inferred(self):
        item = self.price(ok_price([product(1)]), ("1",)).items["1"]
        self.assertEqual(item.sale_state, "unknown")
        self.assertIsNone(item.currency)
        seen = self.price(ok_price([product(1, stock_qty=5, currency="KRW", vat=1)]), ("1",))
        self.assertEqual(dict(seen.observed), {"stock_like": True, "currency_like": True, "tax_like": True})
        self.assertEqual(seen.items["1"].sale_state, "unknown")
        self.assertNotIn("stock_qty", json.dumps(seen.public()))


class Basket(Base):
    def test_B01_single_line_exact_request_and_link(self):
        receipt, t = self.basket(ok_basket([{"pd_no": 124401, "qty": 1}]))
        self.assertEqual(t.calls, ["https://popcornpc.co.kr/shop/ai_api.php?api_id=basket&api_key=%s&pd_no=124401:1" % KEY])
        self.assertEqual(receipt.link, LINK)

    def test_B02_quantity_rules(self):
        self.assertEqual(M.normalize_basket_lines(["5"]), (M.BasketLine("5", 1),))
        self.assertEqual(M.normalize_basket_lines([("5", None)]), (M.BasketLine("5", 1),))
        self.assertEqual(M.normalize_basket_lines([("5", 2), ("6", "3")]), (M.BasketLine("5", 2), M.BasketLine("6", 3)))
        for bad in (0, -1, 1.5, "0", "-1", "1.5", "x", "", " 1", True, 100, [1]):
            self.assertEqual(self.code_of(M.normalize_basket_lines, [("5", bad)]), "invalid_qty", repr(bad))

    def test_B03_key_length_and_charset_rule(self):
        for bad in ("a" * 19, "a" * 21, "", "한" * 20, "a" * 19 + "-", "a" * 19 + "\n", "a" * 19 + "&", None, 12345678901234567890):
            self.assertEqual(self.code_of(M.validate_quote_key, bad), "invalid_key", repr(bad))
        self.assertEqual(M.validate_quote_key("Aa" * 10), "Aa" * 10)
        keys = {M.new_quote_key() for _ in range(200)}
        self.assertEqual(len(keys), 200)
        self.assertTrue(all(re.fullmatch("[1-9][0-9]{19}", k) for k in keys))
        fake = FakeMallApi()
        self.assertEqual(self.code_of(M.BasketClient(fake).replace, "short", [1]), "invalid_key")
        self.assertEqual(fake.calls, [])

    def test_B04_same_key_replaces_list(self):
        fake = FakeMallApi()
        client = M.BasketClient(fake)
        client.replace(KEY, [("1", 2), ("2", 1)])
        client.replace(OTHER_KEY, [("9", 1)])
        client.replace(KEY, [("3", 4)])
        self.assertEqual(fake.baskets[KEY], [{"pd_no": 3, "qty": 4}])
        self.assertEqual(fake.baskets[OTHER_KEY], [{"pd_no": 9, "qty": 1}])

    def test_B05_limit_and_duplicates(self):
        fake = FakeMallApi()
        client = M.BasketClient(fake)
        self.assertEqual(len(client.replace(KEY, range(1, 51)).lines), 50)
        self.assertEqual(self.code_of(client.replace, KEY, range(1, 52)), "too_many_items")
        self.assertEqual(self.code_of(client.replace, KEY, [("1", 1), ("1", 2)]), "duplicate_item")
        self.assertEqual(self.code_of(client.replace, KEY, []), "empty_request")
        self.assertEqual(len(fake.calls), 1)

    def test_B06_keys_isolated_across_users_and_quotes(self):
        fake = FakeMallApi()
        co = M.BasketCoordinator(M.BasketClient(fake))
        a = co.key_for("user-a", "q1")
        self.assertEqual(a, co.key_for("user-a", "q1"))
        b = co.key_for("user-b", "q1")
        c = co.key_for("user-a", "q2")
        self.assertEqual(len({a, b, c}), 3)
        co.replace("user-a", "q1", [("1", 1)])
        co.replace("user-b", "q1", [("2", 1)])
        co.replace("user-a", "q2", [("3", 1)])
        co.replace("user-b", "q1", [("4", 1)])
        self.assertEqual(fake.baskets[a], [{"pd_no": 1, "qty": 1}])
        self.assertEqual(fake.baskets[b], [{"pd_no": 4, "qty": 1}])
        self.assertEqual(self.code_of(co.adopt_key, "user-b", "q9", a), "key_conflict")

    def test_B07_double_click_concurrency_and_late_response(self):
        fake = FakeMallApi()
        co = M.BasketCoordinator(M.BasketClient(fake))
        entered, release = threading.Event(), threading.Event()

        def hold(_url):
            entered.set()
            release.wait(5)

        fake.before_reply = hold
        out = []

        def first():
            try:
                out.append(co.replace("u", "q", [("1", 1)]))
            except MallApiError as exc:
                out.append(exc)

        thread = threading.Thread(target=first)
        thread.start()
        self.assertTrue(entered.wait(5))
        codes = []

        def click():
            try:
                co.replace("u", "q", [("2", 1)])
            except MallApiError as exc:
                codes.append(exc.code)

        clickers = [threading.Thread(target=click) for _ in range(8)]
        for c in clickers:
            c.start()
        for c in clickers:
            c.join()
        self.assertEqual(codes, ["busy"] * 8)
        self.assertEqual(len(fake.calls), 1)
        # 응답 전에 견적을 바꾼다. 늦은 응답은 상태를 덮지 못한다.
        co.invalidate("u", "q")
        self.assertEqual(self.code_of(co.replace, "u", "q", [("2", 1)]), "busy")
        release.set()
        thread.join()
        self.assertEqual(out[0].code, "stale_response")
        self.assertTrue(co.state("u", "q")["outcome_unknown"])
        self.assertIsNone(co.state("u", "q")["receipt"])
        fake.before_reply = None
        receipt = co.replace("u", "q", [("2", 1)], confirm_unknown=True)
        self.assertEqual(co.state("u", "q")["receipt"], receipt)
        self.assertEqual(receipt.lines, (M.BasketLine("2", 1),))

    def test_B08_timeout_or_disconnect_is_unknown_without_retry(self):
        for failure, code in ((M.TransportTimeout(), "timeout"), (ConnectionResetError("x"), "network"),
                              (R(500), "http_5xx"), (R(200, b"<html>"), "html_response")):
            t = ScriptedTransport(failure, ok_basket([{"pd_no": 1, "qty": 1}]), basket_write_allowed=True)
            co = M.BasketCoordinator(M.BasketClient(t))
            with self.assertRaises(MallApiError) as caught:
                co.replace("u", "q", [("1", 1)])
            self.assertEqual(caught.exception.code, code)
            self.assertTrue(caught.exception.outcome_unknown)
            self.assertEqual(len(t.calls), 1)
            self.assertEqual(self.code_of(co.replace, "u", "q", [("1", 1)]), "outcome_unknown_pending")
            self.assertEqual(len(t.calls), 1)
            self.assertIsNone(co.state("u", "q")["receipt"])

    def test_B09_success_with_wrong_content_is_rejected(self):
        lines = [("1", 2)]
        for items in ([{"pd_no": 2, "qty": 2}], [{"pd_no": 1, "qty": 3}], [], [{"pd_no": 1, "qty": 2}, {"pd_no": 2, "qty": 1}],
                      [{"pd_no": 1, "qty": 2}, {"pd_no": 1, "qty": 2}], [{"pd_no": 1}], [{"pd_no": 1, "qty": None}],
                      [{"pd_no": True, "qty": 2}], ["x"]):
            with self.assertRaises(MallApiError) as caught:
                self.basket(ok_basket(items), lines)
            self.assertEqual(caught.exception.code, "basket_mismatch", repr(items))
            self.assertTrue(caught.exception.outcome_unknown)
        self.assertEqual(self.code_of(self.basket, json_response({"result": "ok", "link": LINK}), lines), "bad_shape")
        self.assertEqual(self.code_of(self.basket, ok_basket([{"pd_no": 1, "qty": 2}], LINK.replace(KEY, OTHER_KEY)), lines), "bad_link")
        self.basket(ok_basket([{"pd_no": "1", "qty": "2"}]), lines)

    def test_B10_link_must_match_exactly(self):
        base = "popcornpc.co.kr/shop/order_basket_list.html?api_key=" + KEY
        bad = ["http://" + base, "https://evil.test/shop/order_basket_list.html?api_key=" + KEY,
               "https://popcornpc.co.kr/shop/other.html?api_key=" + KEY, "https://user:pw@" + base,
               "https://popcornpc.co.kr@evil.test/shop/order_basket_list.html?api_key=" + KEY,
               "https://" + base + "&api_key=" + OTHER_KEY, "https://" + base + "#x", "https://popcornpc.co.kr:8443/shop/order_basket_list.html?api_key=" + KEY,
               "/shop/order_basket_list.html?api_key=" + KEY, "//" + base, "https://POPCORNPC.co.kr/shop/order_basket_list.html?api_key=" + KEY,
               "https://www." + base, "javascript:alert(1)", "", None, 7]
        for link in bad:
            with self.assertRaises(MallApiError) as caught:
                self.basket(ok_basket([{"pd_no": 124401, "qty": 1}], link))
            self.assertEqual(caught.exception.code, "bad_link", repr(link))

    def test_B11_production_basket_blocked_before_network(self):
        trap = ScriptedTransport()     # 응답이 없어 부르면 IndexError 가 난다
        self.assertEqual(self.code_of(M.BasketClient(trap).replace, KEY, [1]), "basket_write_blocked")
        self.assertEqual(self.code_of(M.BasketClient().replace, KEY, [1]), "basket_write_blocked")
        opener_calls = []

        class Opener:
            def open(self, *a, **k):
                opener_calls.append(a)
                raise AssertionError("opened")

        live = M.LivePriceTransport(opener=Opener())
        self.assertEqual(self.code_of(M.BasketClient(live).replace, KEY, [1]), "basket_write_blocked")
        api = M.API_URL
        for url in (M.build_basket_url(KEY, (M.BasketLine("1", 1),)), api + "?api_id=price&api_id=basket&pd_no=1",
                    api + "?api_id=basket&api_key=%s&pd_no=1:1" % KEY, api + "?api_id=price&pd_no=1&api_key=" + KEY,
                    api + "?api_id=%62asket&pd_no=1"):
            self.assertEqual(self.code_of(live.get, url, timeout=1, max_bytes=10), "basket_write_blocked", url)
        for url in ("http://popcornpc.co.kr/shop/ai_api.php?api_id=price&pd_no=1", "https://evil.test/?api_id=price&pd_no=1",
                    "https://u:p@popcornpc.co.kr/shop/ai_api.php?api_id=price&pd_no=1", api + "?api_id=price",
                    api + "?api_id=price&pd_no=1:2", api + "?api_id=price&pd_no=1&x=1", api + "?api_id=price&pd_no=1#f",
                    api + "?api_id=price&pd_no=1%2C2", api + "?pd_no=1&api_id=price&pd_no=2", api + "/../x?api_id=price&pd_no=1"):
            self.assertEqual(self.code_of(live.get, url, timeout=1, max_bytes=10), "url_not_allowed", url)
        self.assertEqual(opener_calls, [])
        self.assertEqual(live.calls, 0)

    def test_B12_no_order_or_payment_path_exists(self):
        for path in ("api/mall_ai_api.py", "api/mall_asus_cart.py", "tools/popcorn_api_runner.py"):
            source = (ROOT / path).read_text(encoding="utf-8")
            code = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith("#"))
            for word in ("order_basket_action", "order_pay", "payment", "checkout", "api_id=order", "POST", "buy_btn"):
                self.assertNotIn(word, code, "%s %s" % (path, word))
        self.assertFalse([n for n in dir(M.BasketClient) if re.search("order|pay|checkout", n)])


class Asus(Base):
    def test_A01_missing_mapping_never_uses_components(self):
        self.assertEqual(dict(AC.ASUS_COMPLETE_SKUS), {})
        fake = FakeMallApi()
        co = M.BasketCoordinator(M.BasketClient(fake))
        for model in AC.MODEL_IDS:
            self.assertEqual(AC.add_model_to_cart({"modelId": model, "quantity": 1}, owner_id="u", coordinator=co),
                             {"ok": False, "code": "sku_missing"})
        parts = AC.component_numbers()
        self.assertIn("121803", parts)
        self.assertGreaterEqual(len(parts), 20)
        result = AC.add_model_to_cart({"modelId": "video", "quantity": 1}, owner_id="u", coordinator=co,
                                      sku_map={"video": "121803"}, components=parts)
        self.assertEqual(result, {"ok": False, "code": "sku_is_component"})
        self.assertEqual(fake.calls, [])
        self.assertEqual(AC.add_model_to_cart({"modelId": "video", "quantity": 1}), {"ok": False, "code": "sku_missing"})
        self.assertEqual(AC.add_model_to_cart({"modelId": "video", "quantity": 1}, sku_map=SYNTHETIC),
                         {"ok": False, "code": "not_connected"})

    def test_A02_synthetic_skus_each_one_unit_through_real_cart_js(self):
        fake = FakeMallApi()
        co = M.BasketCoordinator(M.BasketClient(fake))
        replies = {}
        for model in AC.MODEL_IDS:
            replies[model] = AC.add_model_to_cart({"modelId": model, "quantity": 1}, owner_id="synthetic", coordinator=co,
                                                  sku_map=SYNTHETIC)
            self.assertTrue(replies[model]["ok"], replies[model])
        self.assertEqual(len(fake.basket_calls()), 3)
        self.assertEqual(len(fake.baskets), 3)
        expected = sorted([[{"pd_no": int(s), "qty": 1}] for s in SYNTHETIC.values()], key=str)
        self.assertEqual(sorted(fake.baskets.values(), key=str), expected)
        for bad in ({"modelId": "video", "quantity": 2}, {"modelId": "video", "quantity": True},
                    {"modelId": "other", "quantity": 1}, {"modelId": "video"},
                    {"modelId": "video", "quantity": 1, "mall_no": "121803"}):
            self.assertFalse(AC.add_model_to_cart(bad, owner_id="s", coordinator=co, sku_map=SYNTHETIC)["ok"], bad)
        self.assertEqual(len(fake.basket_calls()), 3)
        out = run_cart_js(replies, list(AC.ALLOWED_ORIGINS))
        self.assertEqual(out["calls"], [{"modelId": m, "quantity": 1} for m in AC.MODEL_IDS])
        self.assertEqual(out["assigned"], [replies[m]["url"] for m in AC.MODEL_IDS])

    def test_A03_page_inactive_failure_visible_and_nothing_stored(self):
        mvp4 = ROOT / "mockups/mvp4"
        for path in list(mvp4.glob("*.html")) + list((mvp4 / "assets/js").glob("*.js")):
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("ai_api", text, path.name)
            if path.name != "asus-cart.js":
                self.assertNotRegex(text, r"asusCart\.setAdapter|\.setAdapter\(", path.name)
        out = run_cart_js({"video": {"ok": False, "code": "sku_missing"}}, list(AC.ALLOWED_ORIGINS), models=["video"])
        self.assertFalse(out["results"][0]["ok"])
        self.assertEqual(out["results"][0]["code"], "sku_missing")
        self.assertEqual(out["assigned"], [])
        self.assertIn("장바구니에 담지 못했습니다", out["notes"]["video"])
        self.assertTrue(out["default_disabled"])
        self.assertIn("장바구니 준비 중입니다", out["default_note"])
        cart = (mvp4 / "assets/js/asus-cart.js").read_text(encoding="utf-8")
        self.assertIn("var NOT_READY = '장바구니 준비 중입니다.'", cart)


class Safety(Base):
    def test_S01_secrets_never_reach_logs_errors_or_evidence(self):
        secret_key = "SECRETKEY0123456789X"
        secret_url = "https://popcornpc.co.kr/shop/order_basket_list.html?api_key=" + secret_key
        self.assertNotIn(secret_key, M.mask_url(secret_url))
        self.assertNotIn("user:pw", M.mask_url("https://user:pw@popcornpc.co.kr/a?api_key=x"))
        self.assertNotIn("9191", M.mask_url("https://popcornpc.co.kr/a?phone=9191&api_id=basket"))
        self.assertIn("api_id=basket", M.mask_url(M.API_URL + "?api_id=basket&api_key=" + secret_key))
        self.assertEqual(M.mask_key(secret_key), "***")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        M.log.addHandler(handler)
        M.log.setLevel(logging.DEBUG)
        self.addCleanup(M.log.removeHandler, handler)
        leaks = [secret_key, secret_url, "010-1234-5678", "cost=777"]
        sensitive = "%s %s phone=010-1234-5678 cost=777" % (secret_url, secret_key)
        failures = [ConnectionError(sensitive), urllib.error.URLError(sensitive), R(200, json.dumps({"error": sensitive}).encode()),
                    R(200, json.dumps({"result": "ok", "link": secret_url, "items": []}).encode())]
        for failure in failures:
            t = ScriptedTransport(failure, basket_write_allowed=True)
            try:
                M.BasketClient(t).replace(secret_key, [("1", 1)])
            except MallApiError as exc:
                text = str(exc) + repr(exc) + "".join(traceback.format_exception(exc))
                for leak in leaks:
                    self.assertNotIn(leak, text)
            else:
                self.fail("no error")
        receipt = M.BasketReceipt(key=secret_key, link=secret_url, lines=())
        self.assertNotIn(secret_key, repr(receipt))
        logged = stream.getvalue()
        self.assertIn("basket failed", logged)
        self.assertTrue(logged.isascii())
        for leak in leaks:
            self.assertNotIn(leak, logged)

    def test_S02_defaults_offline_no_routes_no_db(self):
        self.assertEqual(self.code_of(M.fetch_prices, [1]), "offline_blocked")
        self.assertFalse(hasattr(M, "router"))
        self.assertFalse(hasattr(AC, "router"))
        self.assertFalse(M.OfflineTransport.basket_write_allowed)
        self.assertFalse(M.LivePriceTransport.basket_write_allowed)
        forbidden = {"sqlalchemy", "psycopg2", "api.db", "api.database", "fastapi", "subprocess", "requests", "httpx"}
        for path in ("api/mall_ai_api.py", "api/mall_asus_cart.py"):
            tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
            names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            self.assertFalse(names & forbidden, path)
        # 실제 코드에서 쓰기를 켜는 자리는 없다. 가짜만 켠다.
        for path in list((ROOT / "api").glob("*.py")) + list((ROOT / "tools").glob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotRegex(text, r"basket_write_allowed\s*=\s*True", path.name)
        for path in list((ROOT / "api").glob("*.py")):
            if path.name not in ("mall_ai_api.py", "mall_asus_cart.py"):
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("mall_ai_api", text, path.name)
                self.assertNotIn("mall_asus_cart", text, path.name)
        from tools import popcorn_api_runner as runner
        self.assertEqual(runner.build_parser().parse_args([]).mode, "offline")
        self.assertEqual(runner.LIVE_CODES, ("124401", "124407", "124409"))


class LiveTransportLocal(Base):
    """LivePriceTransport 를 가짜 opener 로 실행한다. 소켓은 열지 않는다."""

    class Resp:
        def __init__(self, chunks, status=200):
            self.chunks, self.status = list(chunks), status
            self.headers = {"Content-Type": "application/json; charset=utf-8"}

        def read(self, _n):
            return self.chunks.pop(0) if self.chunks else b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Opener:
        def __init__(self, action):
            self.action, self.requests = action, []

        def open(self, request, timeout):
            self.requests.append(request)
            result = self.action() if callable(self.action) else self.action
            return result

    URL = M.build_price_url(("124401",))

    def test_budget_pacing_and_headers(self):
        sleeps, now = [], [100.0]
        def clock():
            return now[0]
        def sleep(s):
            sleeps.append(s)
            now[0] += s
        opener = self.Opener(lambda: self.Resp([b"{}"]))
        live = M.LivePriceTransport(max_calls=2, opener=opener, clock=clock, sleep=sleep)
        reply = live.get(self.URL, timeout=1, max_bytes=100)
        self.assertEqual((reply.status, reply.content_type), (200, "application/json"))
        live.get(self.URL, timeout=1, max_bytes=100)
        self.assertEqual(sleeps, [1.0])
        self.assertEqual(self.code_of(live.get, self.URL, timeout=1, max_bytes=100), "live_budget_exhausted")
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(opener.requests[0].get_method(), "GET")
        self.assertIsNone(opener.requests[0].get_header("Cookie"))
        with self.assertRaises(ValueError):
            M.LivePriceTransport(max_calls=4)
        self.assertEqual(M.LivePriceTransport(min_interval=0)._min_interval, 1.0)

    def test_redirect_not_followed_and_errors_mapped(self):
        self.assertIsNone(M._NoRedirect().redirect_request(None, None, 302, "x", {}, "https://evil.test/"))
        def raiser(exc):
            def inner():
                raise exc
            return inner
        err = urllib.error.HTTPError(self.URL, 302, "x", {}, io.BytesIO(b"secret"))
        reply = M.LivePriceTransport(opener=self.Opener(raiser(err))).get(self.URL, timeout=1, max_bytes=10)
        self.assertEqual((reply.status, reply.body), (302, b""))
        self.assertEqual(self.code_of(M.fetch_prices, ["124401"], transport=M.LivePriceTransport(opener=self.Opener(raiser(err)))), "redirect")
        for exc in (socket.timeout(), TimeoutError(), urllib.error.URLError(socket.timeout())):
            with self.assertRaises(M.TransportTimeout):
                M.LivePriceTransport(opener=self.Opener(raiser(exc))).get(self.URL, timeout=1, max_bytes=10)
        self.assertEqual(self.code_of(M.LivePriceTransport(opener=self.Opener(raiser(OSError("x")))).get, self.URL, timeout=1, max_bytes=10), "network")

    def test_size_and_total_deadline(self):
        big = self.Opener(lambda: self.Resp([b"a" * 6, b"b" * 6]))
        with self.assertRaises(M.TransportTooLarge):
            M.LivePriceTransport(opener=big).get(self.URL, timeout=1, max_bytes=10)
        ticks = iter([0.0, 0.0, 0.0, 99.0])
        slow = self.Opener(lambda: self.Resp([b"a", b"b"]))
        with self.assertRaises(M.TransportTimeout):
            M.LivePriceTransport(opener=slow, clock=lambda: next(ticks)).get(self.URL, timeout=1, max_bytes=10)

    def test_concurrent_call_blocked(self):
        entered, release = threading.Event(), threading.Event()
        def action():
            entered.set()
            release.wait(5)
            return self.Resp([b"{}"])
        live = M.LivePriceTransport(opener=self.Opener(action))
        thread = threading.Thread(target=live.get, args=(self.URL,), kwargs={"timeout": 1, "max_bytes": 10})
        thread.start()
        self.assertTrue(entered.wait(5))
        self.assertEqual(self.code_of(live.get, self.URL, timeout=1, max_bytes=10), "concurrent_blocked")
        release.set()
        thread.join()
        self.assertEqual(live.calls, 1)


class LiveRunnerLocal(unittest.TestCase):
    """실행기의 live 경로를 가짜 transport 로 끝까지 돈다. 2026-11-09 첫 실호출에서 오류 경로가
    TypeError 로 죽어 진단 메타를 잃었다. 그 경로를 여기서 고정한다."""

    def setUp(self):
        from tools import popcorn_api_runner
        self.runner = popcorn_api_runner
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ledger = str(Path(self.dir.name) / "ledger.json")
        self.out = str(Path(self.dir.name) / "out.json")

    def run_live(self, reply, call="single", **options):
        made = []
        options.setdefault("init_ledger", not Path(self.ledger).exists())

        class Fake:
            basket_write_allowed = False

            def __init__(self, **_k):
                made.append(self)

            def get(self, url, *, timeout, max_bytes):
                self.url = url
                return reply

        with patch.object(self.runner.M, "LivePriceTransport", Fake), contextlib.redirect_stdout(io.StringIO()):
            code = self.runner.run_live(call, self.ledger, self.out, **options)
        return code, made

    def read(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def test_ok_stores_allowed_fields_only(self):
        reply = ok_price([product(124401, cost_price="SECRET-COST", supplier="SECRET-SUP")])
        code, made = self.run_live(reply)
        self.assertEqual(code, 0)
        text = Path(self.out).read_text(encoding="utf-8")
        self.assertNotIn("SECRET", text)
        self.assertEqual(self.read(self.out)["real_basket"], "not_run")
        self.assertEqual(self.read(self.ledger)[0]["outcome"], "ok")
        self.assertEqual(made[0].url, M.build_price_url(("124401",)))

    def test_abnormal_keeps_diagnostics_without_body_and_stops_next_call(self):
        code, _ = self.run_live(R(200, b'{"result":"ok","items":[SECRET-BODY]}', "text/html"))
        self.assertEqual(code, 1)
        entry = self.read(self.ledger)[0]
        self.assertEqual((entry["outcome"], entry["code"], entry["http_status"]), ("error", "bad_json", 200))
        self.assertIn("Expecting value", entry["detail"])
        self.assertTrue(entry["starts_with_brace"])
        self.assertEqual(entry["bytes"], 37)
        self.assertNotIn("SECRET-BODY", Path(self.ledger).read_text(encoding="utf-8") + Path(self.out).read_text(encoding="utf-8"))
        with contextlib.redirect_stderr(io.StringIO()):
            code, made = self.run_live(ok_price([]))
        self.assertEqual(code, 3)
        self.assertEqual(made, [])
        self.assertEqual(len(self.read(self.ledger)), 1)

    def test_transport_failure_keeps_status_none(self):
        code, _ = self.run_live_raises(M.TransportTimeout())
        self.assertEqual(code, 1)
        entry = self.read(self.ledger)[0]
        self.assertEqual((entry["code"], entry["http_status"]), ("timeout", None))

    def run_live_raises(self, failure):
        class Fake:
            basket_write_allowed = False

            def __init__(self, **_k):
                pass

            def get(self, url, *, timeout, max_bytes):
                raise failure

        with patch.object(self.runner.M, "LivePriceTransport", Fake), contextlib.redirect_stdout(io.StringIO()):
            return self.runner.run_live("single", self.ledger, self.out, init_ledger=True), None

    def test_budget_and_arguments(self):
        self.write_ledger([{"seq": n, "outcome": "ok", "epoch": 0} for n in range(1, 11)])
        with contextlib.redirect_stderr(io.StringIO()):
            code, made = self.run_live(ok_price([]))
        self.assertEqual((code, made), (3, []))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.runner.run_live(None, self.ledger, self.out), 2)
            self.assertEqual(self.runner.INTERNAL_RUNNER_LIVE_BUDGET, 10)
            self.assertEqual(M.DOC_MAX_ITEMS, 50)   # 내부 호출 상한과 API 공식 상품 상한은 다른 값이다
            with self.assertRaises(SystemExit):
                self.runner.build_parser().parse_args(["--mode", "basket"])
            with self.assertRaises(SystemExit):
                self.runner.build_parser().parse_args(["--mode", "live", "--call", "basket"])

    def test_interrupted_started_entry_blocks(self):
        self.write_ledger([{"seq": 1, "outcome": "started", "epoch": 0}])
        with contextlib.redirect_stderr(io.StringIO()):
            code, made = self.run_live(ok_price([]))
        self.assertEqual((code, made), (3, []))

    def write_ledger(self, entries):
        Path(self.ledger).write_text(json.dumps(entries), encoding="utf-8")

    def test_ninth_and_tenth_call_allowed_only_up_to_budget(self):
        self.write_ledger([{"seq": n, "outcome": "ok", "epoch": 0} for n in range(1, 10)])
        code, made = self.run_live(ok_price([]))
        self.assertEqual((code, len(made)), (0, 1))
        self.assertEqual(len(self.read(self.ledger)), 10)
        with contextlib.redirect_stderr(io.StringIO()):
            code, made = self.run_live(ok_price([]))
        self.assertEqual((code, made), (3, []))

    def test_resume_appends_with_reason_and_keeps_failed_entries(self):
        first = {"seq": 1, "outcome": "error", "code": "bad_json", "epoch": 0, "note": "keep"}
        self.write_ledger([first])
        for bad in (None, "", "   ", "short"):
            with contextlib.redirect_stderr(io.StringIO()):
                code, made = self.run_live(ok_price([]), resume_reason=bad)
            self.assertEqual((code, made), (3, []))
        code, made = self.run_live(R(200, b"not json at all", "text/html"), resume_reason="API-010 cause check")
        self.assertEqual((code, len(made)), (1, 1))
        entries = self.read(self.ledger)
        self.assertEqual(entries[0], first)
        self.assertEqual(entries[1]["seq"], 2)
        self.assertEqual(entries[1]["resume"], {"reason": "API-010 cause check", "after_seq": 1, "after_code": "bad_json"})

    def test_resume_reason_rejected_when_previous_was_ok(self):
        self.write_ledger([{"seq": 1, "outcome": "ok", "epoch": 0}])
        with contextlib.redirect_stderr(io.StringIO()):
            code, made = self.run_live(ok_price([]), resume_reason="no reason to resume")
        self.assertEqual((code, made), (3, []))

    def test_new_ledger_needs_flag_and_existing_ledger_cannot_be_reinitialised(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code, made = self.run_live(ok_price([]), init_ledger=False)
        self.assertEqual((code, made), (3, []))
        self.assertFalse(Path(self.ledger).exists())
        self.write_ledger([{"seq": 1, "outcome": "error", "epoch": 0}])
        with contextlib.redirect_stderr(io.StringIO()):
            code, made = self.run_live(ok_price([]), init_ledger=True, resume_reason="try to reset the budget")
        self.assertEqual((code, made), (3, []))
        self.assertEqual(len(self.read(self.ledger)), 1)

    def test_removed_or_reordered_entries_block(self):
        self.write_ledger([{"seq": 2, "outcome": "ok", "epoch": 0}])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_live(ok_price([]))

    def test_diagnosis_keeps_no_ip_value_and_withholds_hash(self):
        secret_ip = b"203.0.113.77"
        code, _ = self.run_live(R(200, secret_ip, "text/html"))
        self.assertEqual(code, 1)
        entry = self.read(self.ledger)[0]
        self.assertEqual(entry["diagnosis"]["kind"], "ipv4_only")
        self.assertEqual(entry["diagnosis"]["shape"], "999.9.999.99")
        self.assertNotIn("body_sha256", entry)
        stored = Path(self.ledger).read_text(encoding="utf-8") + Path(self.out).read_text(encoding="utf-8")
        self.assertNotIn(secret_ip.decode(), stored)
        self.assertNotIn(hashlib.sha256(secret_ip).hexdigest(), stored)

    def test_same_body_is_recognised_across_calls(self):
        body = b"plain server words"
        self.write_ledger([{"seq": 1, "outcome": "error", "epoch": 0, "body_sha256": hashlib.sha256(body).hexdigest()}])
        self.run_live(R(200, body, "text/html"), resume_reason="repeat to compare")
        self.assertEqual(self.read(self.ledger)[1]["same_body_as_seq"], [1])

    def test_classifier_failure_does_not_lose_the_record(self):
        with patch.object(self.runner, "classify_body", side_effect=RuntimeError("boom")):
            code, _ = self.run_live(R(200, b"not json", "text/html"))
        self.assertEqual(code, 1)
        entry = self.read(self.ledger)[0]
        self.assertEqual((entry["code"], entry["diagnosis"]["kind"]), ("bad_json", "classifier_error"))

    def test_classify_body_kinds(self):
        table = {
            b"": "empty", b"   ": "empty", b"\xff\xfe": "non_utf8", b"<html>x": "html",
            b'{"result":"ok"}': "json_document", b'{"a":1}{"b":2}': "concatenated_json",
            b"10.1.2.3": "ipv4_only", b" 10.1.2.3\n": "ipv4_only",
            b"10.1.2.3 is here": "ipv4_with_text", b"10.1.2.3 IP ERROR!": "ip_error",
            "허용되지 않은 IP".encode(): "ip_allowlist_error", b"ip not registered": "ip_allowlist_error",
            b"Access Denied": "access_denied", "접근 거부".encode(): "access_denied",
            b"var_dump output": "debug_output", b"hello there": "plain_text_other",
        }
        for body, kind in table.items():
            self.assertEqual(self.runner.classify_body(body)["kind"], kind, body)
        self.assertEqual(self.runner.classify_body(b"999.1.1.1")["ipv4_count"], 0)
        self.assertNotIn("shape", self.runner.classify_body(b"x" * 65))
        self.assertNotIn("10.1.2.3", json.dumps(self.runner.classify_body(b"text 10.1.2.3")))

    def test_ip_error_is_a_fixed_label_only_on_exact_match(self):
        server = {"203.0.113.77"}
        with patch.object(self.runner, "_resolve_server_ips", return_value=server), \
                patch.object(self.runner, "_local_ips", return_value=set()):
            result = self.runner.classify_body(b" 203.0.113.77 IP ERROR!")
        self.assertEqual(result["kind"], "ip_error")
        self.assertEqual(result["shape"], "999.9.999.99_aa_aaaaa!")
        self.assertEqual(result["ipv4_relation"], [{"is_private": True, "matches_mall_server_dns": True,
                                                    "matches_local_interface": False}])
        self.assertEqual(result["leading_whitespace"], 1)
        text = json.dumps(result)
        self.assertNotIn("203.0.113.77", text)
        self.assertNotIn("ERROR", text)
        for near in (b"203.0.113.77 IP ERROR", b"x 203.0.113.77 IP ERROR!", b"203.0.113.77 ip error!",
                     b"203.0.113.77 IP ERROR! hunter2", b"IP ERROR!"):
            self.assertNotEqual(self.runner.classify_body(near)["kind"], "ip_error", near)

    def test_secrets_reach_no_log_evidence_or_classify_result(self):
        secrets = {
            "short_word": "hunter",
            "short_mixed": "hunter2",
            "email": "someone.private@example.com",
            "ipv6": "2001:db8:85a3::8a2e:370:7334",
            "phrase": "open sesame please now",
            "key_alnum": "abcdefghij0123456789",
            "key_digits": "12345678901234567890",
            "korean": "비밀문구 내부값",
        }
        bodies = dict(secrets)
        bodies["with_ipv4"] = "203.0.113.77 hunter2 open sesame"
        for label, secret in bodies.items():
            with self.subTest(label):
                body = secret.encode("utf-8")
                ledger, out = Path(self.dir.name) / (label + ".json"), Path(self.dir.name) / (label + "_out.json")
                self.ledger, self.out = str(ledger), str(out)
                records = []
                handler = logging.Handler()
                handler.emit = lambda record: records.append(record.getMessage())
                logging.getLogger().addHandler(handler)
                self.addCleanup(logging.getLogger().removeHandler, handler)

                class Fake:
                    basket_write_allowed = False

                    def __init__(self, **_k):
                        pass

                    def get(self, url, *, timeout, max_bytes):
                        return R(200, body, "text/html")

                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.object(self.runner.M, "LivePriceTransport", Fake), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = self.runner.run_live("single", self.ledger, self.out, init_ledger=True)
                self.assertEqual(code, 1)
                surfaces = {
                    "ledger": ledger.read_text(encoding="utf-8"), "evidence": out.read_text(encoding="utf-8"),
                    "stdout": stdout.getvalue(), "stderr": stderr.getvalue(), "logs": "\n".join(records),
                    "classify": json.dumps(self.runner.classify_body(body), ensure_ascii=False),
                }
                digest = hashlib.sha256(body).hexdigest()
                pieces = set(re.split(r"\s+", secret)) | {secret, digest}
                for name, stored in surfaces.items():
                    for piece in pieces:
                        self.assertNotIn(piece, stored, name)
                self.assertNotIn("body_sha256\"", surfaces["ledger"])
                self.assertNotIn("text_digits_masked", surfaces["ledger"])

    def test_ip_lookup_failure_does_not_stop_classification(self):
        with patch.object(self.runner.socket, "getaddrinfo", side_effect=OSError("dns")):
            result = self.runner.classify_body(b"10.1.2.3 no")
        self.assertEqual(result["ipv4_relation"][0]["matches_mall_server_dns"], False)

    def test_observed_ip_error_body_has_its_own_code_and_keeps_no_ip(self):
        for body in (b" 203.0.113.77 IP ERROR!", b"203.0.113.77 IP ERROR!\n"):
            with self.assertRaises(MallApiError) as caught:
                M.fetch_prices(["1"], transport=ScriptedTransport(R(200, body, "text/html")))
            self.assertEqual((caught.exception.code, caught.exception.http_status), ("ip_rejected", 200))
            self.assertNotIn("203.0.113.77", repr(caught.exception) + str(caught.exception.detail))
        for near in (b"203.0.113.77 IP ERROR", b"x 203.0.113.77 IP ERROR!", b'203.0.113.77 IP ERROR!{"result":"ok"}'):
            with self.assertRaises(MallApiError) as caught:
                M.fetch_prices(["1"], transport=ScriptedTransport(R(200, near, "text/html")))
            self.assertEqual(caught.exception.code, "bad_json")

    def test_classification_does_not_relax_the_parser(self):
        for body in (b"10.1.2.3", b'10.1.2.3{"result":"ok","items":[]}', b'{"result":"ok","items":[]}{"a":1}'):
            with self.assertRaises(MallApiError) as caught:
                M.fetch_prices(["1"], transport=ScriptedTransport(R(200, body)))
            self.assertEqual(caught.exception.code, "bad_json")

    def test_request_profiles_are_get_only_and_have_no_credentials(self):
        self.assertEqual(sorted(M.REQUEST_PROFILES), ["default", "no_custom_headers"])
        self.assertEqual(M.REQUEST_PROFILES["no_custom_headers"], {})
        for headers in M.REQUEST_PROFILES.values():
            self.assertFalse({k.lower() for k in headers} & {"authorization", "cookie", "x-forwarded-for", "x-real-ip"})
        with self.assertRaises(KeyError):
            M.LivePriceTransport(request_profile="basket")

    def test_error_detail_never_contains_body(self):
        for body in (b'{"a":SECRET}', b'{"a":1} SECRET', b'{"a":"\x01SECRET"}', b'{"a":1,"a":2}'):
            with self.assertRaises(MallApiError) as caught:
                M.fetch_prices(["1"], transport=ScriptedTransport(R(200, body)))
            self.assertEqual(caught.exception.code, "bad_json")
            self.assertTrue(caught.exception.detail)
            self.assertNotIn("SECRET", caught.exception.detail)


class Coverage(unittest.TestCase):
    def test_every_case_id_has_a_test(self):
        names = [n for cls in (Price, Basket, Asus, Safety) for n in dir(cls) if n.startswith("test_")]
        ids = sorted({n.split("_")[1] for n in names})
        self.assertEqual(ids, sorted(CASE_IDS))
        self.assertEqual(len(CASE_IDS), 29)


CART_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(process.argv[1]);
const assigned = [], calls = [], results = [], notes = {};
const trap = (n) => { throw new Error('forbidden ' + n); };
function fakeBox(id) {
  const button = { disabled: true, textContent: '', setAttribute() {} };
  const note = { textContent: '', hidden: false };
  return { getAttribute: () => id, querySelector: (s) => s === 'button' ? button : note, button, note };
}
const boxes = input.models.map(fakeBox);
const windowObj = { PAI: { h: (v) => String(v), asus: { known: (id) => ['business', 'video', 'local-ai'].includes(id) } },
  location: { assign: (u) => assigned.push(u) } };
const ctx = { window: windowObj, URL, Promise, setTimeout, clearTimeout,
  document: { addEventListener() {}, querySelectorAll: () => boxes },
  fetch: () => trap('fetch'), XMLHttpRequest: function () { trap('xhr'); } };
vm.runInNewContext(fs.readFileSync(input.file, 'utf8'), ctx);
const C = windowObj.PAI.asusCart;
C.refresh();
const default_disabled = boxes.every((b) => b.button.disabled);
const default_note = boxes[0].note.textContent;
C.setAdapter({ origins: input.origins, add: (r) => { calls.push(JSON.parse(JSON.stringify(r))); return Promise.resolve(input.replies[r.modelId]); } });
(async () => {
  for (const m of input.models) results.push(await C.add(m));
  boxes.forEach((b) => { notes[b.getAttribute()] = b.note.textContent; });
  process.stdout.write(JSON.stringify({ calls, assigned, results, notes, default_disabled, default_note }));
})().catch((e) => { console.error(e); process.exit(1); });
"""


def run_cart_js(replies, origins, models=None):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node 없음")
    payload = {"file": str(ROOT / "mockups/mvp4/assets/js/asus-cart.js"), "replies": replies,
               "origins": origins, "models": models or list(AC.MODEL_IDS)}
    run = subprocess.run([node, "-e", CART_HARNESS, json.dumps(payload)], capture_output=True, timeout=30)
    if run.returncode:
        raise AssertionError(run.stderr.decode("utf-8", "replace"))
    return json.loads(run.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
