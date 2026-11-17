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
from tests.popcorn_pc_fake_api import (CHECKED_AT, ip_denied_response, price_response, product,  # noqa: E402
                                       too_many_response)

OFFICE = "198.51.100.7"
HOME = "203.0.113.9"
OTHER = "192.0.2.55"


def noisy_product(pd_no, **overrides):
    """새 응답 항목에, 와서는 안 되는 옛 내부 필드를 일부러 섞는다(합성 값). 중계기는 전부 버려야 한다."""
    return product(pd_no, pd_cost_price="6100", dealer1_price="6500", pd_remain="0",
                   cate1="SECRET-CATE", pd_ment="SECRET-MENT", view_chk="y", **overrides)


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
        self.reply = price_response([noisy_product(124401), noisy_product(124407)])
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

    def test_office_gets_the_new_fields_only(self):
        res = self.call()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.headers["cache-control"], "no-store")
        body = res.json()
        self.assertEqual(sorted(body), ["checked_at", "checked_at_format", "items", "missing", "not_found",
                                        "requested", "source", "status_note", "unrequested_count"])
        self.assertEqual(body["requested"], ["124401", "124407"])
        self.assertEqual((body["checked_at"], body["checked_at_format"]), (CHECKED_AT, "local"))
        self.assertEqual((body["not_found"], body["missing"], body["unrequested_count"]), ([], [], 0))
        item = body["items"][0]
        self.assertEqual(sorted(item), ["found", "lookup", "max_qty", "name", "pd_no", "price", "status", "status_raw"])
        self.assertEqual(item["price"], {"status": "ok", "value": "150000"})
        self.assertEqual((item["status"], item["status_raw"]), ("sold_out", "sold_out"))
        self.assertEqual(item["max_qty"], {"status": "none", "value": None})
        # 내부 가격 열은 없다. 쇼핑몰이 다시 보내더라도 중계기 응답에 실리지 않는다.
        for gone in ("internal", "pd_cost_price", "dealer1_price", "pd_remain", "6100", "6500", "SECRET", "view_chk",
                     "maker", "mileage", "delivery_price"):
            self.assertNotIn(gone, res.text, gone)
        self.assertEqual(Fake.instances[0].urls, [M.build_price_url(("124401", "124407"))])
        self.assertEqual(Fake.instances[0].kwargs, {"max_calls": 1})

    def test_not_found_missing_unrequested_and_item_values_pass_through(self):
        reply = price_response([product(124401, name="<font color=red>[특가]</font> 합성 쿨러", price=0, status="paused", max_qty=2),
                                product(555)], [124407])
        body = self.call(query="pd_no=124401,124407,124409", reply=reply).json()
        self.assertEqual((body["not_found"], body["missing"], body["unrequested_count"]), (["124407"], ["124409"], 1))
        first, second, third = body["items"]
        self.assertEqual(first["name"], "[특가] 합성 쿨러")
        self.assertEqual(first["price"], {"status": "zero", "value": "0"})
        self.assertEqual((first["status"], first["status_raw"]), ("unknown", "paused"))
        self.assertEqual(first["max_qty"], {"status": "ok", "value": 2})
        self.assertEqual((second["found"], second["lookup"]), (False, "not_found"))
        self.assertEqual((third["found"], third["lookup"]), (False, "missing"))
        self.assertNotIn("555", json.dumps(body))

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
        for code in ("ip_not_allowed", "busy", "too_many_items", "ip_rejected", "mall_too_many_items", "bad_shape"):
            self.assertIn(code, html)
        # 2026-11-17 응답 변경: 없는 번호는 not_found 로 온다. 화면은 found 가 아닌 줄을 정보 없음으로 보인다
        self.assertIn("if (!it.found)", html)
        self.assertIn('it.lookup === "not_found"', html)
        # 새 열만 있다. 내부 가격 열은 없다
        heads = re.findall(r"<th(?:\s[^>]*)?>(.*?)</th>", html, re.S)
        self.assertEqual([re.sub(r"<small>.*?</small>", "", h) for h in heads], ["상품번호", "상품명", "가격", "판매 상태", "최대 수량"])
        for gone in ("원가", "딜러가", "시중가", "소비자가", "재고값", "적립금", "배송비", "제조사", "internal", "pd_cost_price", "pd_remain"):
            self.assertNotIn(gone, html, gone)
        # 판매 상태가 우리 판정이 아니라 쇼핑몰 값임을 화면이 말한다(머리글, 안내문, 복사되는 표 머리글)
        self.assertEqual(html.count("쇼핑몰이 준 값 그대로"), 2)
        self.assertIn("이 화면이 판정한 값이 아니다", html)
        self.assertIn("it.status_raw", html)
        self.assertIn("data.checked_at", html)
        self.assertNotIn("new Date()", html)                 # 조회 시각은 쇼핑몰이 준 값만 보인다

    def test_lookup_page_script_parses(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node 없음")
        html = (ROOT / "templates/mall_ai_gateway_lookup.html").read_text(encoding="utf-8")
        script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
        run = subprocess.run([node, "-e", "new Function(require('fs').readFileSync(0, 'utf8'))"],
                             input=script.encode("utf-8"), capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", "replace"))

    def test_export_script_is_bom_utf8_and_read_only(self):
        raw = (ROOT / "tools/mall_price_export.ps1").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "Windows PowerShell 5.1 은 BOM 없는 UTF-8 한글을 깨뜨린다")
        text = raw.decode("utf-8-sig")
        self.assertIn("/api/mall-ai-gateway/price", text)
        self.assertIn("-Method Get", text)
        for word in ("basket", "api_key", "-Method Post", "Invoke-Expression"):
            self.assertNotIn(word, text, word)
        self.assertEqual(set(re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text)), set())

    def test_upstream_failure_returns_code_only(self):
        res = self.call(reply=R(200, b" 10.0.0.1 IP ERROR!", "text/html"))
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.json()["detail"]["code"], "ip_rejected")
        self.assertNotIn("10.0.0.1", res.text)
        # 2026-11-17 부터의 형태: 403/400 JSON error. 쇼핑몰 문구는 중계기 응답에 싣지 않는다.
        old_envelope = R(200, b'{"result":"ok","items":[]}', "application/json")
        for reply, code in ((ip_denied_response(), "ip_rejected"), (too_many_response(), "mall_too_many_items"),
                            (old_envelope, "bad_shape"),
                            (price_response([product(124401)], checked_at="yesterday"), "bad_checked_at"),
                            (R(200, ('{"checked_at":"%s","items":{},"not_found":null}' % CHECKED_AT).encode()), "bad_shape")):
            res = self.call(reply=reply)
            self.assertEqual((res.status_code, res.json()["detail"]["code"]), (502, code))
            self.assertNotIn("허용되지 않은 IP", res.text)
            self.assertEqual(sorted(res.json()["detail"]), ["code", "message"])

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
        self.assertIn("[mall-gw] ok requested=2 not_found=0 missing=0 unrequested=0", text)
        for leak in ("6100", "150000", OFFICE, OTHER, HOME, "합성", "sold_out", CHECKED_AT):
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

    def test_library_has_no_way_to_read_internal_price_fields(self):
        result = M.fetch_prices(["124401"], transport=Fake(price_response([noisy_product(124401)])))
        self.assertFalse(hasattr(result.items["124401"], "internal"))
        self.assertNotIn("6100", json.dumps(result.public()) + repr(result) + json.dumps(result.allowed_raw))
        self.assertEqual(result.dropped_field_count, 6)
        self.assertFalse(hasattr(M, "INTERNAL_PRICE_FIELDS"))
        with self.assertRaises(TypeError):
            M.fetch_prices(["1"], internal_fields=("pd_cost_price",))
        source = (ROOT / "api/mall_ai_gateway.py").read_text(encoding="utf-8")
        self.assertNotIn("internal_fields", source)
        self.assertNotIn("internal_public", source)

    def test_module_has_no_db_or_shell_imports(self):
        tree = ast.parse((ROOT / "api/mall_ai_gateway.py").read_text(encoding="utf-8"))
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse(names & {"sqlalchemy", "psycopg2", "api.db", "api.database", "subprocess", "requests", "httpx"})
        quads = set(re.findall(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", (ROOT / "api/mall_ai_gateway.py").read_text(encoding="utf-8")))
        self.assertEqual(quads - {"127.0.0.1"}, set())     # 허용 IP 는 저장소에 적지 않는다


if __name__ == "__main__":
    unittest.main()
