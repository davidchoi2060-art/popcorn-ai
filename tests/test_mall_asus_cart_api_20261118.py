# -*- coding: utf-8 -*-
"""ASUS 완제품 장바구니 서버 경로(api/mall_asus_cart_api.py). 실제 네트워크·DB 는 열지 않는다.

설정 해석 · 꺼짐 404/비활성 · 키 도출 결정성(같은 모델 같은 키, 다른 모델 다른 키) · not_found 거절 ·
sold_out 은 진행+로그 · same_origin · 호출 한도 · 응답 모양 · notice · 쓰기 스위치 · 로그에 값 없음.
"""
import logging
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from fastapi import FastAPI                                          # noqa: E402
from fastapi.testclient import TestClient                            # noqa: E402

from api import access_gate                                          # noqa: E402
from api import mall_ai_api as M                                     # noqa: E402
from api import mall_asus_cart as AC                                 # noqa: E402
from api import mall_asus_cart_api as CART                           # noqa: E402
from tests.popcorn_pc_fake_api import FakeMallApi                   # noqa: E402

REAL_BASKET_TRANSPORT = M.LiveBasketTransport        # setUp 이 가짜로 바꾸기 전의 실제 클래스
SYNTHETIC = {"business": "900000001", "video": "900000002", "local-ai": "900000003"}   # 합성 번호. 실제 상품번호가 아니다
SKUS = ",".join("%s=%s" % kv for kv in SYNTHETIC.items())
SALT = "synthetic-salt-0123456789"
ENV_ON = {CART.ENABLED_ENV: "1", CART.SKUS_ENV: SKUS, CART.MODELS_ON_ENV: "business,video",
          CART.SALT_ENV: SALT, M.BASKET_WRITE_ENV: "1"}
CLIENT_IP = "203.0.113.9"
OTHER_IP = "198.51.100.7"


class FakeResult:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row

    def mappings(self):
        return self

    def scalar(self):
        return None


class FakeConn:
    """users(anon_key -> user_id) 만 답한다. rate_limit_policies 는 없다(코드 기본값)."""

    def __init__(self, visitors):
        self.visitors = visitors

    def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM users" in sql:
            uid = self.visitors.get((params or {}).get("k"))
            return FakeResult((uid,) if uid else None)
        if "rate_limit_policies" in sql:
            return FakeResult(None)
        raise AssertionError("unexpected sql")

    def close(self):
        pass


class FakeEngine:
    def __init__(self, visitors):
        self.visitors = visitors

    def connect(self):
        return FakeConn(self.visitors)


class FakeBasketTransport:
    """LiveBasketTransport 자리. 정한 주소 하나만 받고 가짜 쇼핑몰에 넘긴다."""
    mall = None
    made = []

    def __init__(self, key, lines, **_kw):
        self.expected = M.build_basket_url(M.validate_quote_key(key), M.normalize_basket_lines(lines))
        self.basket_write_allowed = True
        FakeBasketTransport.made.append(self)

    def get(self, url, *, timeout, max_bytes):
        if url != self.expected:
            raise M.MallApiError("basket_write_blocked")
        return FakeBasketTransport.mall.get(url, timeout=timeout, max_bytes=max_bytes)


class Base(unittest.TestCase):
    def setUp(self):
        access_gate._reset_for_test()
        CART._reset_for_test()
        self.mall = FakeMallApi(catalog=SYNTHETIC.values())
        FakeBasketTransport.mall = self.mall
        FakeBasketTransport.made = []
        self.visitors = {"visitor-a": 11, "visitor-b": 12}
        self.env = patch.dict(os.environ, ENV_ON)
        self.env.start()
        self.addCleanup(self.env.stop)
        for target in (patch.object(CART, "engine", FakeEngine(self.visitors)),
                       patch.object(M, "LivePriceTransport", lambda **kw: self.mall),
                       patch.object(M, "LiveBasketTransport", FakeBasketTransport),
                       patch.object(CART._pacer, "_sleep", lambda _s: None)):
            target.start()
            self.addCleanup(target.stop)
        app = FastAPI()
        app.include_router(CART.router)
        self.app = app

    def client(self, ip=CLIENT_IP, cookie="visitor-a"):
        client = TestClient(self.app, client=(ip, 50000), base_url="https://pop.example.test", raise_server_exceptions=False)
        if cookie:
            client.cookies.set("pc_vid", cookie)
        return client

    def add(self, model="business", quantity=1, *, ip=CLIENT_IP, cookie="visitor-a", origin="https://pop.example.test",
            body=None, headers=None):
        hdr = {"Origin": origin} if origin else {}
        hdr.update(headers or {})
        return self.client(ip, cookie).post("/api/customer/asus-cart/add",
                                            json=body if body is not None else {"modelId": model, "quantity": quantity},
                                            headers=hdr)

    def status(self):
        return self.client().get("/api/customer/asus-cart/status")


class Config(unittest.TestCase):
    def test_parse_skus_and_models_on(self):
        self.assertEqual(CART.parse_skus(" business = 900000001 ,, video=900000002 "), {"business": "900000001", "video": "900000002"})
        self.assertEqual(CART.parse_skus(""), {})
        for bad in ("business", "business=", "=1", "business=1,business=2"):
            with self.assertRaises(M.MallApiError) as caught:
                CART.parse_skus(bad)
            self.assertEqual(caught.exception.code, "skus_malformed", bad)
        self.assertEqual(CART.parse_models_on(" business, video "), frozenset({"business", "video"}))
        self.assertEqual(CART.parse_models_on(""), frozenset())
        with self.assertRaises(M.MallApiError) as caught:
            CART.parse_models_on("business,other")
        self.assertEqual(caught.exception.code, "models_on_unknown")

    def test_load_config_reuses_validate_sku_map_and_requires_salt(self):
        cfg = CART.load_config({CART.SKUS_ENV: SKUS, CART.MODELS_ON_ENV: "video", CART.SALT_ENV: SALT})
        self.assertEqual((cfg.error, cfg.skus, cfg.on), (None, SYNTHETIC, frozenset({"video"})))
        self.assertEqual([cfg.reason(m) for m in AC.MODEL_IDS], ["model_off", None, "model_off"])
        part = sorted(AC.component_numbers())[0]
        bad = CART.load_config({CART.SKUS_ENV: "video=%s" % part, CART.SALT_ENV: SALT})
        self.assertEqual((bad.error, bad.reason("video")), ("sku_is_component", "config_error"))
        for raw, code in (("video=abc", "invalid_pd_no"), ("other=900000001", "unknown_model"),
                          ("video=900000001,business=900000001", "sku_duplicate"), ("video", "skus_malformed")):
            self.assertEqual(CART.load_config({CART.SKUS_ENV: raw, CART.SALT_ENV: SALT}).error, code, raw)
        self.assertEqual(CART.load_config({CART.SKUS_ENV: SKUS, CART.MODELS_ON_ENV: "video"}).error, "salt_missing")
        self.assertEqual(CART.load_config({CART.SKUS_ENV: SKUS, CART.SALT_ENV: "short"}).error, "salt_missing")
        missing = CART.load_config({CART.SKUS_ENV: "video=900000002", CART.MODELS_ON_ENV: "business,video", CART.SALT_ENV: SALT})
        self.assertEqual([missing.reason(m) for m in AC.MODEL_IDS], ["sku_missing", None, "model_off"])

    def test_key_is_deterministic_per_visitor_and_model(self):
        a = CART.derive_key(SALT, "u:11", "business")
        self.assertEqual(a, CART.derive_key(SALT, "u:11", "business"))
        self.assertRegex(a, r"^[A-Za-z0-9]{20}$")
        others = {CART.derive_key(SALT, "u:11", "video"), CART.derive_key(SALT, "u:11", "local-ai"),
                  CART.derive_key(SALT, "u:12", "business"), CART.derive_key(SALT, "ip:203.0.113.9", "business"),
                  CART.derive_key("another-salt-0123456789", "u:11", "business")}
        self.assertEqual(len(others), 5)
        self.assertNotIn(a, others)
        self.assertNotIn("u:11", a)

    def test_notice_text_is_one_constant(self):
        self.assertEqual(CART.NOTICE, "쇼핑몰 장바구니에 담았습니다. 브라우저를 닫으면 장바구니가 비워질 수 있으니, "
                                      "이어서 주문하거나 쇼핑몰에 로그인해 주세요.")
        self.assertEqual(CART.NOTICE_SEPARATE, "모델마다 장바구니가 따로 만들어집니다.")
        source = (ROOT / "api/mall_asus_cart_api.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("브라우저를 닫으면 장바구니가 비워질"), 1)


class Status(Base):
    def test_disabled_is_404_for_both_routes(self):
        for value in ("", "0", "true"):
            with patch.dict(os.environ, {CART.ENABLED_ENV: value}):
                self.assertEqual(self.status().status_code, 404, value)
                self.assertEqual(self.add().status_code, 404, value)
        self.assertEqual(self.mall.calls, [])

    def test_status_says_which_models_are_available_and_why(self):
        res = self.status()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["cache-control"], "no-store")
        body = res.json()
        self.assertEqual(sorted(body), ["enabled", "models", "notice", "notice_separate", "origins"])
        self.assertTrue(body["enabled"])
        self.assertEqual(body["models"], {"business": {"available": True, "reason": None},
                                          "video": {"available": True, "reason": None},
                                          "local-ai": {"available": False, "reason": "model_off"}})
        self.assertEqual(body["origins"], [M.ORIGIN])
        self.assertEqual((body["notice"], body["notice_separate"]), (CART.NOTICE, CART.NOTICE_SEPARATE))
        self.assertNotIn("900000001", res.text)     # 상품번호는 화면에 주지 않는다
        self.assertEqual(self.mall.calls, [])

    def test_status_without_numbers_or_switch_or_salt_is_inactive_not_404(self):
        with patch.dict(os.environ, {CART.SKUS_ENV: "video=900000002"}):
            body = self.status().json()
            self.assertEqual((body["enabled"], body["models"]["business"]), (True, {"available": False, "reason": "sku_missing"}))
        with patch.dict(os.environ, {CART.MODELS_ON_ENV: ""}):
            body = self.status().json()
            self.assertFalse(body["enabled"])
            self.assertEqual({v["reason"] for v in body["models"].values()}, {"model_off"})
        with patch.dict(os.environ, {CART.SALT_ENV: ""}):
            body = self.status().json()
            self.assertFalse(body["enabled"])
            self.assertEqual({v["reason"] for v in body["models"].values()}, {"config_error"})
            self.assertEqual(self.add().json(), {"ok": False, "code": "not_configured"})
        self.assertEqual(self.mall.calls, [])


class Add(Base):
    def test_success_shape_key_and_notice(self):
        res = self.add()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.headers["cache-control"], "no-store")
        body = res.json()
        key = CART.derive_key(SALT, "u:11", "business")
        self.assertEqual(body, {"ok": True, "url": M.expected_link(key), "added": [{"pd_no": "900000001", "qty": 1}],
                                "skipped": [], "total": 1, "notice": CART.NOTICE, "notice_separate": CART.NOTICE_SEPARATE})
        self.assertEqual(self.mall.calls[0], M.build_price_url(("900000001",)))
        self.assertEqual(self.mall.basket_calls(), [M.build_basket_url(key, (M.BasketLine("900000001", 1),))])
        self.assertEqual(list(self.mall.baskets), [key])

    def test_same_visitor_same_model_replaces_and_other_model_gets_another_key(self):
        self.add("business")
        self.add("business")
        self.add("video")
        keys = [re.search(r"api_key=([A-Za-z0-9]{20})", u).group(1) for u in self.mall.basket_calls()]
        self.assertEqual(keys[0], keys[1])
        self.assertNotEqual(keys[0], keys[2])
        self.assertEqual(sorted(self.mall.baskets), sorted({keys[0], keys[2]}))
        self.assertEqual(self.mall.baskets[keys[0]], [{"pd_no": 900000001, "qty": 1}])
        self.assertEqual(self.mall.baskets[keys[2]], [{"pd_no": 900000002, "qty": 1}])
        # 다른 방문자(쿠키)는 다른 키. 쿠키가 없으면 접속 IP 축으로 키를 만들고 거절하지 않는다.
        self.add("business", cookie="visitor-b")
        self.add("business", cookie=None)
        self.add("business", cookie=None, ip=OTHER_IP)
        self.assertEqual(len(self.mall.baskets), 5)
        self.assertEqual(len(self.mall.basket_calls()), 6)

    def test_request_validation(self):
        self.assertEqual(self.add("other").json(), {"ok": False, "code": "unknown_model"})
        self.assertEqual(self.add(quantity=2).json(), {"ok": False, "code": "bad_quantity"})
        self.assertEqual(self.add(body={"modelId": "business", "quantity": True}).status_code, 422)
        self.assertEqual(self.add(body={"modelId": "business", "quantity": 1, "pd_no": "1"}).status_code, 422)
        self.assertEqual(self.add(body={"modelId": "business"}).status_code, 422)
        self.assertEqual(self.add("local-ai").json(), {"ok": False, "code": "model_off"})
        self.assertEqual(self.add("local-ai").status_code, 409)
        with patch.dict(os.environ, {CART.SKUS_ENV: "video=900000002"}):
            self.assertEqual(self.add("business").json(), {"ok": False, "code": "sku_missing"})
        self.assertEqual(self.mall.calls, [])

    def test_same_origin_required(self):
        self.assertEqual(self.add(origin="https://evil.example.test").status_code, 403)
        self.assertEqual(self.add(headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.mall.calls, [])
        self.assertEqual(self.add(origin=None).status_code, 200)

    def test_not_found_is_refused_before_basket(self):
        self.mall.catalog.pop(900000001)
        res = self.add("business")
        self.assertEqual((res.status_code, res.json()), (409, {"ok": False, "code": "sku_not_found"}))
        self.assertEqual(len(self.mall.calls), 1)
        self.assertEqual(self.mall.basket_calls(), [])

    def test_sold_out_proceeds_and_is_counted_in_the_log_only(self):
        self.mall.catalog[900000001]["status"] = "sold_out"
        self.mall.catalog[900000002]["status"] = "on_sale"
        with self.assertLogs(CART.log, level="INFO") as logs:
            self.assertTrue(self.add("business").json()["ok"])
            self.assertTrue(self.add("video").json()["ok"])
        text = "\n".join(logs.output)
        self.assertIn("[asus-cart] ok model=business added=1 skipped=0 total=1 sold_out=1", text)
        self.assertIn("[asus-cart] ok model=video added=1 skipped=0 total=1 sold_out=0", text)
        self.assertEqual(len(self.mall.basket_calls()), 2)

    def test_mall_skipping_the_item_is_a_definite_failure(self):
        self.mall.skip.add(900000001)
        res = self.add("business")
        self.assertEqual((res.status_code, res.json()), (409, {"ok": False, "code": "basket_skipped", "outcome_unknown": False}))

    def test_price_and_basket_errors_map_to_codes(self):
        from tests.popcorn_pc_fake_api import ip_denied_response
        with patch.object(M, "LivePriceTransport", lambda **kw: type("T", (), {"basket_write_allowed": False,
                                                                                 "get": lambda s, u, **k: ip_denied_response()})()):
            res = self.add()
        self.assertEqual((res.status_code, res.json()), (502, {"ok": False, "code": "ip_rejected"}))
        self.assertEqual(self.mall.basket_calls(), [])

        def broken(url, **kw):
            raise M.TransportTimeout()

        with patch.object(FakeBasketTransport, "get", lambda s, u, **k: broken(u)):
            res = self.add()
        self.assertEqual((res.status_code, res.json()), (502, {"ok": False, "code": "timeout", "outcome_unknown": True}))
        self.assertTrue(self.add().json()["ok"])    # 다음 클릭은 같은 키로 교체라 그대로 받는다

    def test_write_switch_off_blocks_before_network(self):
        with patch.object(M, "LiveBasketTransport", REAL_BASKET_TRANSPORT), \
                patch.dict(os.environ, {M.BASKET_WRITE_ENV: ""}):
            res = self.add()
        self.assertEqual((res.status_code, res.json()), (503, {"ok": False, "code": "basket_write_blocked", "outcome_unknown": False}))
        self.assertEqual(len(self.mall.calls), 1)       # price 만 나갔다
        self.assertEqual(self.mall.basket_calls(), [])

    def test_rate_limit_per_visitor(self):
        for _ in range(CART.PER_MINUTE):
            self.assertEqual(self.add().status_code, 200)
        res = self.add()
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.json()["detail"]["error"], "rate_limited")
        self.assertIn("Retry-After", res.headers)
        self.assertEqual(self.add(cookie="visitor-b").status_code, 200)       # 다른 방문자는 따로 센다
        self.assertEqual(len(self.mall.basket_calls()), CART.PER_MINUTE + 1)

    def test_upstream_calls_are_spaced_and_single(self):
        waits = []
        with patch.object(CART._pacer, "_sleep", waits.append):
            self.add()
        self.assertEqual(len(waits), 1)                # price 와 basket 사이 한 번
        self.assertGreater(waits[0], 0.9)
        CART._pacer._lock.acquire()
        try:
            res = self.add()
        finally:
            CART._pacer._lock.release()
        self.assertEqual((res.status_code, res.json()["code"]), (409, "busy"))

    def test_logs_hold_model_counts_and_codes_only(self):
        self.mall.catalog[900000001]["name"] = "SECRET-NAME"
        self.mall.catalog[900000001]["price"] = 777777
        with self.assertLogs(level="INFO") as logs:
            self.add()
            self.mall.catalog.pop(900000002)
            self.add("video")
        text = "\n".join(logs.output)
        self.assertTrue(text.isascii(), text)
        key = CART.derive_key(SALT, "u:11", "business")
        for leak in ("SECRET-NAME", "777777", key, "900000001", "visitor-a", "u:11", CLIENT_IP, SALT):
            self.assertNotIn(leak, text, leak)
        self.assertIn("sku not in mall model=video lookup=not_found", text)

    def test_module_keeps_no_values_and_no_db_writes(self):
        source = (ROOT / "api/mall_asus_cart_api.py").read_text(encoding="utf-8")
        code = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith("#"))
        self.assertEqual(len(re.findall(r"basket_write_allowed\s*=\s*True", source)), 0)
        self.assertNotRegex(code, r"\b\d{6,}\b")                        # 상품번호 추정값이 없다
        self.assertNotRegex(code, r"\d{1,3}(?:\.\d{1,3}){3}")           # IP 가 없다
        for word in ("INSERT", "UPDATE", "DELETE", "set_cookie", "payment", "checkout", "order_pay"):
            self.assertNotIn(word, code, word)
        self.assertEqual(AC.ASUS_COMPLETE_SKUS, {})


if __name__ == "__main__":
    unittest.main()
