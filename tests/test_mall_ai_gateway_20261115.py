# -*- coding: utf-8 -*-
"""사무실 조회 중계기(api/mall_ai_gateway.py). 실제 네트워크는 열지 않는다."""
import ast
import json
import logging
import os
import re
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI                                         # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402

from api import mall_ai_api as M                                     # noqa: E402
from api import mall_ai_gateway as G                                 # noqa: E402
from api.mall_ai_api import TransportResponse as R                   # noqa: E402
from tests.popcorn_pc_fake_api import json_response, product        # noqa: E402

OFFICE = "198.51.100.7"
HOME = "203.0.113.9"
OTHER = "192.0.2.55"


def internal_product(pd_no):
    return product(pd_no, pd_cost_price="6100", dealer1_price="6500", dealer2_price="6600", dealer3_price="6700",
                   pd_sijung_price="9000", pd_sobija_price="9900", pd_remain="0",
                   cate1="SECRET-CATE", pd_ment="SECRET-MENT", view_chk="y")


class Fake:
    """LivePriceTransport 자리에 들어간다. 받은 주소와 호출 수를 남긴다."""
    instances = []

    def __init__(self, reply=None, **kwargs):
        self.kwargs = kwargs
        self.urls = []
        self.reply = reply
        Fake.instances.append(self)

    basket_write_allowed = False

    def get(self, url, *, timeout, max_bytes):
        self.urls.append(url)
        return self.reply


class Gateway(unittest.TestCase):
    def setUp(self):
        Fake.instances = []
        G._last_call["at"] = None
        self.env = patch.dict(os.environ, {G.ENABLED_ENV: "1", G.ALLOW_IPS_ENV: " %s, %s ,bad-entry" % (OFFICE, HOME)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.reply = json_response({"result": "ok", "items": [internal_product(124401), internal_product(124407)]})
        sleep = patch.object(G.time, "sleep", lambda _s: None)
        sleep.start()
        self.addCleanup(sleep.stop)
        app = FastAPI()
        app.include_router(G.router)
        self.app = app

    def call(self, ip=OFFICE, query="pd_no=124401,124407", real_ip="same", reply="default", method="get"):
        reply = self.reply if reply == "default" else reply
        client = TestClient(self.app, client=(ip, 50000))
        headers = {}
        if real_ip == "same":
            headers["X-Real-IP"] = ip
        elif real_ip:
            headers["X-Real-IP"] = real_ip
        live = patch.object(M, "LivePriceTransport", lambda **kw: Fake(reply, **kw))
        with live:
            return getattr(client, method)("/api/mall-ai-gateway/price?" + query, headers=headers)

    def test_office_gets_documented_and_internal_fields_only(self):
        res = self.call()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.headers["cache-control"], "no-store")
        body = res.json()
        self.assertEqual(body["requested"], ["124401", "124407"])
        item = body["items"][0]
        self.assertEqual(item["price"], {"status": "ok", "value": "150000"})
        self.assertEqual(item["internal"]["pd_cost_price"], {"status": "ok", "value": "6100"})
        self.assertEqual(item["internal"]["pd_remain"], {"status": "zero", "value": "0"})
        self.assertEqual(sorted(item["internal"]), sorted(M.INTERNAL_PRICE_FIELDS))
        self.assertNotIn("SECRET", res.text)
        self.assertNotIn("view_chk", res.text)
        self.assertEqual(Fake.instances[0].urls, [M.build_price_url(("124401", "124407"))])
        self.assertEqual(Fake.instances[0].kwargs, {"max_calls": 1})

    def test_home_ip_is_allowed_too(self):
        self.assertEqual(self.call(ip=HOME).status_code, 200)

    def test_disabled_is_404_even_for_office(self):
        for value in ("", "0", "true", "yes"):
            with patch.dict(os.environ, {G.ENABLED_ENV: value}):
                self.assertEqual(self.call().status_code, 404, value)
        self.assertEqual(Fake.instances, [])

    def test_other_ip_spoofed_header_and_empty_list_are_refused_before_upstream(self):
        self.assertEqual(self.call(ip=OTHER).status_code, 403)
        self.assertEqual(self.call(ip=OTHER, real_ip=OFFICE).status_code, 403)
        self.assertEqual(self.call(ip=OFFICE, real_ip=OTHER).status_code, 403)
        self.assertEqual(self.call(ip="testclient", real_ip=None).status_code, 403)
        with patch.dict(os.environ, {G.ALLOW_IPS_ENV: ""}):
            self.assertEqual(self.call().status_code, 403)
        with patch.dict(os.environ, {G.ALLOW_IPS_ENV: "bad-entry"}):
            self.assertEqual(self.call().status_code, 403)
        self.assertEqual(Fake.instances, [])

    def test_bad_requests_never_reach_upstream(self):
        for query in ("", "pd_no=", "pd_no=abc", "pd_no=0", "pd_no=" + ",".join(str(i) for i in range(1, 52)),
                      "pd_no=1;2", "pd_no=1%2C2&pd_no=3"):
            res = self.call(query=query)
            self.assertIn(res.status_code, (400, 422), query)
        self.assertEqual(Fake.instances, [])

    def test_only_get_and_no_basket_path(self):
        self.assertEqual(self.call(method="post").status_code, 405)
        paths = [r.path for r in G.router.routes]
        self.assertEqual(sorted(paths), ["/api/mall-ai-gateway/lookup", "/api/mall-ai-gateway/price"])
        self.assertEqual({m for r in G.router.routes for m in r.methods}, {"GET"})
        source = (ROOT / "api/mall_ai_gateway.py").read_text(encoding="utf-8")
        code = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith("#"))
        for word in ("BasketClient", "build_basket_url", "basket_write_allowed", "api_key", "order", "payment"):
            self.assertNotIn(word, code, word)

    def page(self, ip=OFFICE, real_ip="same"):
        client = TestClient(self.app, client=(ip, 50000))
        headers = {"X-Real-IP": ip if real_ip == "same" else real_ip} if real_ip else {}
        return client.get("/api/mall-ai-gateway/lookup", headers=headers)

    def test_lookup_page_uses_the_same_gate(self):
        res = self.page()
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.headers["content-type"])
        self.assertEqual(res.headers["cache-control"], "no-store")
        self.assertIn('data-screen-id="MALL-GW-010"', res.text)
        self.assertEqual(self.page(ip=HOME).status_code, 200)
        self.assertEqual(self.page(ip=OTHER).status_code, 403)
        self.assertEqual(self.page(ip=OTHER, real_ip=OFFICE).status_code, 403)
        with patch.dict(os.environ, {G.ENABLED_ENV: "0"}):
            self.assertEqual(self.page().status_code, 404)
        self.assertEqual(Fake.instances, [])        # 화면을 여는 것만으로는 윈윈을 부르지 않는다

    def test_lookup_page_is_self_contained_and_builds_text_safely(self):
        html = (ROOT / "templates/mall_ai_gateway_lookup.html").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", html))   # 외부 자원 0
        self.assertNotIn("innerHTML", html)                  # 윈윈 문자열은 textContent 로만 넣는다
        self.assertNotIn("localStorage", html)
        self.assertIn('"/api/mall-ai-gateway/price?pd_no="', html)
        for word in ("basket", "api_key", "POST"):
            self.assertNotIn(word, html, word)
        quads = set(re.findall(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", html))
        self.assertEqual(quads, set())
        for code in ("ip_not_allowed", "busy", "too_many_items", "ip_rejected"):
            self.assertIn(code, html)

    def test_upstream_failure_returns_code_only(self):
        res = self.call(reply=R(200, b" 10.0.0.1 IP ERROR!", "text/html"))
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.json()["detail"]["code"], "ip_rejected")
        self.assertNotIn("10.0.0.1", res.text)

    def test_logs_hold_no_values(self):
        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        logging.getLogger().setLevel(logging.INFO)
        self.call()
        self.call(ip=OTHER)
        text = "\n".join(records)
        self.assertIn("[mall-gw] ok requested=2", text)
        for leak in ("6100", "150000", OFFICE, OTHER, HOME, "합성"):
            self.assertNotIn(leak, text)

    def test_overlap_is_429_and_calls_are_spaced(self):
        waits = []
        G._upstream.acquire()
        try:
            self.assertEqual(self.call().status_code, 429)
        finally:
            G._upstream.release()
        self.assertEqual(Fake.instances, [])
        with patch.object(G.time, "sleep", waits.append):
            self.call()
            self.call()
        self.assertEqual(len(waits), 1)
        self.assertGreater(waits[0], 0.9)

    def test_library_default_still_reads_no_internal_fields(self):
        result = M.fetch_prices(["124401"], transport=Fake(json_response({"result": "ok", "items": [internal_product(124401)]})))
        self.assertEqual(result.items["124401"].internal, {})
        self.assertNotIn("6100", json.dumps(result.public()))
        self.assertNotIn("internal", result.items["124401"].public())
        with self.assertRaises(ValueError):
            M.fetch_prices(["1"], internal_fields=("pd_ment",))
        with self.assertRaises(ValueError):
            M.fetch_prices(["1"], internal_fields=("pd_cost_price", "pd_cost_price"))

    def test_module_has_no_db_or_shell_imports(self):
        tree = ast.parse((ROOT / "api/mall_ai_gateway.py").read_text(encoding="utf-8"))
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse(names & {"sqlalchemy", "psycopg2", "api.db", "api.database", "subprocess", "requests", "httpx"})
        quads = set(re.findall(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", (ROOT / "api/mall_ai_gateway.py").read_text(encoding="utf-8")))
        self.assertEqual(quads - {"127.0.0.1"}, set())     # 허용 IP 는 저장소에 적지 않는다


if __name__ == "__main__":
    unittest.main()
