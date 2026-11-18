# -*- coding: utf-8 -*-
"""ASUS 장바구니 화면 연결(asus-cart-live.js, 2026-11-18). asus-cart.js 와 함께 Node 로 실제 실행한다.

외부 주소 없음 · 꺼짐(404/실패/비활성) 분기는 기존 동작(비활성 + 준비 중 안내) · 성공은 안내 문구 + 새 창 ·
script 태그는 asus 화면 둘에만, 순서와 버전 쿼리 유지.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MVP4 = ROOT / "mockups/mvp4"
CART = (MVP4 / "assets/js/asus-cart.js").read_text(encoding="utf-8")
LIVE = (MVP4 / "assets/js/asus-cart-live.js").read_text(encoding="utf-8")
PAGES = (MVP4 / "assets/js/asus-pages.js").read_text(encoding="utf-8")
ORIGIN = "https://shop.example.test"
NOTICE = "쇼핑몰 장바구니에 담았습니다. 브라우저를 닫으면 장바구니가 비워질 수 있으니, 이어서 주문하거나 쇼핑몰에 로그인해 주세요."
SEPARATE = "모델마다 장바구니가 따로 만들어집니다."

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(process.argv[1]);
const trap = (n) => { throw new Error('forbidden ' + n); };
const fetches = [], assigned = [], opened = [];
function fakeNode() {
  // textContent 를 넣으면 실제 DOM 처럼 자식이 사라진다.
  const n = { _text: '', hidden: false, children: [], href: '', target: '', rel: '', disabled: true,
    setAttribute() {}, appendChild(c) { this.children.push(c); } };
  Object.defineProperty(n, 'textContent', { get() { return this._text; }, set(v) { this._text = v; this.children = []; }, enumerable: true });
  return n;
}
function fakeBox(id) {
  const button = fakeNode(); const note = fakeNode();
  return { getAttribute: () => id, querySelector: (s) => s === 'button' ? button : note, button, note };
}
const boxes = ['business', 'video', 'local-ai'].map(fakeBox);
const windowObj = {
  PAI: { h: (v) => String(v), asus: { known: (id) => ['business', 'video', 'local-ai'].includes(id) } },
  location: { assign: (u) => assigned.push(u) },
  open: (u, t, f) => { opened.push([u, t, f]); return input.popup === false ? null : { opener: 'x' }; }
};
let replies = input.replies;
const ctx = { window: windowObj, URL, Promise, setTimeout, clearTimeout, AbortController, JSON, Object, Array,
  document: { addEventListener() {}, querySelectorAll: () => boxes,
    createElement: (t) => { const n = fakeNode(); n.tag = t; return n; }, createTextNode: (t) => ({ text: t }) },
  fetch: (url, options) => {
    fetches.push({ url, method: options.method, credentials: options.credentials, cache: options.cache,
      headers: options.headers, body: options.body ? JSON.parse(options.body) : null });
    const key = options.method + ' ' + url;
    const r = replies[key];
    if (!r) return Promise.reject(new Error('network'));
    const reply = Array.isArray(r) ? r.shift() : r;
    return Promise.resolve({ status: reply.status, json: () => reply.body === undefined ? Promise.reject(new Error('json')) : Promise.resolve(reply.body) });
  },
  XMLHttpRequest: function () { trap('xhr'); },
  localStorage: new Proxy({}, { get: () => trap('localStorage') }), sessionStorage: new Proxy({}, { get: () => trap('sessionStorage') }) };
vm.runInNewContext(fs.readFileSync(input.cart, 'utf8'), ctx);
vm.runInNewContext(fs.readFileSync(input.live, 'utf8'), ctx);
const C = windowObj.PAI.asusCart;
const tick = () => new Promise((r) => setTimeout(r, 0));
(async () => {
  for (let i = 0; i < 10; i++) await tick();
  C.refresh();
  const out = { connected: C.connected(), fetches: fetches.slice() };
  const snap = () => Object.fromEntries(boxes.map((b) => [b.getAttribute(), { disabled: b.button.disabled, note: b.note.textContent,
    links: b.note.children.filter((c) => c.tag === 'a').map((c) => ({ href: c.href, target: c.target, rel: c.rel, text: c.textContent })) }]));
  out.before = snap();
  out.results = {};
  for (const m of input.adds || []) out.results[m] = await C.add(m);
  C.refresh();
  out.after = snap();
  out.assigned = assigned; out.opened = opened; out.fetches = fetches;
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""

STATUS_OK = {"status": 200, "body": {"enabled": True, "origins": [ORIGIN], "notice": NOTICE, "notice_separate": SEPARATE,
                                     "models": {"business": {"available": True, "reason": None}, "video": {"available": False, "reason": "model_off"},
                                                "local-ai": {"available": False, "reason": "sku_missing"}}}}


def run(replies, adds=(), popup=True):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node 없음")
    payload = {"cart": str(MVP4 / "assets/js/asus-cart.js"), "live": str(MVP4 / "assets/js/asus-cart-live.js"),
               "replies": replies, "adds": list(adds), "popup": popup}
    r = subprocess.run([node, "-e", HARNESS, json.dumps(payload)], capture_output=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr.decode("utf-8", "replace"))
    return json.loads(r.stdout.decode("utf-8"))


class Static(unittest.TestCase):
    def test_live_module_has_no_external_address_and_keeps_old_syntax(self):
        code = re.sub(r"/\*.*?\*/", "", LIVE, flags=re.S)
        for word in ("https://", "http://", "popcornpc", "ai_api", "api_key", "localStorage", "sessionStorage", "innerHTML",
                     "window.location", "const ", "let ", "=>", "`", "class ", "async ", "await "):
            self.assertNotIn(word, code, word)
        self.assertTrue(code.lstrip().startswith("(function () {"))
        self.assertIn("'/api/customer/asus-cart/status'", code)
        self.assertIn("'/api/customer/asus-cart/add'", code)
        self.assertIn("credentials = 'same-origin'", code)
        self.assertEqual(code.count("setAdapter("), 1)

    def test_cart_module_keeps_its_guarantees(self):
        code = re.sub(r"/\*.*?\*/", "", CART, flags=re.S)
        for word in ("fetch(", "XMLHttpRequest", "popcornpc", "https://", "innerHTML"):
            self.assertNotIn(word, code, word)
        self.assertEqual(code.count("window.location.assign"), 1)
        self.assertEqual(code.count("window.open("), 1)
        self.assertIn("'noopener'", code)
        self.assertIn("link.rel = 'noopener noreferrer'", code)

    def test_script_tags_only_on_asus_pages_in_order_with_version(self):
        for name in ("asus.html", "asus-pc.html"):
            html = (MVP4 / name).read_text(encoding="utf-8")
            live = re.findall(r'<script defer src="assets/js/asus-cart-live\.js\?v=(\d{8}-[a-z0-9]+)"></script>', html)
            self.assertEqual(len(live), 1, name)
            self.assertLess(html.index("assets/js/asus-data.js"), html.index("assets/js/asus-cart.js"))
            self.assertLess(html.index("assets/js/asus-cart.js"), html.index("assets/js/asus-cart-live.js"))
            self.assertLess(html.index("assets/js/asus-cart-live.js"), html.index("assets/js/asus-pages.js"))
        for path in MVP4.glob("*.html"):
            if path.name not in ("asus.html", "asus-pc.html"):
                self.assertNotIn("asus-cart-live", path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(PAGES.count("P.asusCart.refresh()"), 2)     # 목록·상세를 그린 뒤 버튼 상태를 다시 받는다


class Behaviour(unittest.TestCase):
    def test_disabled_or_failed_status_keeps_buttons_inactive(self):
        for replies in ({"GET /api/customer/asus-cart/status": {"status": 404, "body": {"detail": "Not Found"}}},
                        {"GET /api/customer/asus-cart/status": {"status": 500}},
                        {},
                        {"GET /api/customer/asus-cart/status": {"status": 200, "body": {"enabled": False, "models": {}}}},
                        {"GET /api/customer/asus-cart/status": {"status": 200, "body": {**STATUS_OK["body"], "origins": ["http://shop.example.test"]}}},
                        {"GET /api/customer/asus-cart/status": {"status": 200, "body": {**STATUS_OK["body"], "models": {
                            "business": {"available": False, "reason": "model_off"}}}}}):
            out = run(replies, adds=["business"])
            self.assertFalse(out["connected"], replies)
            for box in out["before"].values():
                self.assertEqual((box["disabled"], box["note"]), (True, "장바구니 준비 중입니다."), replies)
            self.assertEqual(out["results"]["business"]["ok"], False)
            self.assertEqual(out["assigned"], [])
            self.assertEqual(out["opened"], [])
            self.assertEqual([f["method"] for f in out["fetches"]], ["GET"] if replies else ["GET"])

    def test_status_request_is_same_origin_json(self):
        out = run({"GET /api/customer/asus-cart/status": STATUS_OK})
        f = out["fetches"][0]
        self.assertEqual((f["url"], f["method"], f["credentials"], f["cache"]), ("/api/customer/asus-cart/status", "GET", "same-origin", "no-store"))
        self.assertEqual(f["headers"]["X-Popcorn-Surface"], "mvp4")
        self.assertTrue(out["connected"])
        self.assertEqual(out["before"]["business"], {"disabled": False, "note": "", "links": []})
        self.assertEqual(out["before"]["video"], {"disabled": True, "note": "장바구니 준비 중입니다.", "links": []})
        self.assertEqual(out["before"]["local-ai"], {"disabled": True, "note": "장바구니 준비 중입니다.", "links": []})

    def test_success_shows_notice_and_opens_new_window_without_leaving(self):
        url = ORIGIN + "/shop/order_basket_list.html?api_key=abcde12345abcde12345"
        out = run({"GET /api/customer/asus-cart/status": STATUS_OK,
                   "POST /api/customer/asus-cart/add": {"status": 200, "body": {"ok": True, "url": url, "added": [{"pd_no": "1", "qty": 1}],
                                                                                 "skipped": [], "total": 1, "notice": NOTICE, "notice_separate": SEPARATE}}},
                  adds=["business", "video"])
        post = out["fetches"][1]
        self.assertEqual((post["method"], post["credentials"], post["body"]), ("POST", "same-origin", {"modelId": "business", "quantity": 1}))
        self.assertEqual(post["headers"]["Content-Type"], "application/json")
        self.assertEqual(out["results"]["business"], {"ok": True, "url": url, "notice": NOTICE + " " + SEPARATE})
        self.assertEqual(out["results"]["video"], {"ok": False, "code": "unavailable"})
        self.assertEqual(len(out["fetches"]), 2)        # 비활성 모델은 요청하지 않는다
        self.assertEqual(out["assigned"], [])           # 현재 화면을 떠나지 않는다
        self.assertEqual(out["opened"], [[url, "_blank", "noopener"]])
        box = out["after"]["business"]
        self.assertEqual((box["disabled"], box["note"]), (False, NOTICE + " " + SEPARATE))
        self.assertEqual(box["links"], [{"href": url, "target": "_blank", "rel": "noopener noreferrer", "text": "장바구니 열기"}])

    def test_popup_blocked_still_leaves_the_link(self):
        url = ORIGIN + "/shop/order_basket_list.html?api_key=abcde12345abcde12345"
        out = run({"GET /api/customer/asus-cart/status": STATUS_OK,
                   "POST /api/customer/asus-cart/add": {"status": 200, "body": {"ok": True, "url": url}}}, adds=["business"], popup=False)
        self.assertEqual(out["after"]["business"]["note"], "장바구니에 담았습니다.")
        self.assertEqual(out["after"]["business"]["links"][0]["href"], url)

    def test_failures_keep_the_retry_state_and_never_open(self):
        bad = ORIGIN.replace("shop", "other") + "/x"
        cases = {
            "sku_not_found": {"status": 409, "body": {"ok": False, "code": "sku_not_found"}},
            "rate_limited": {"status": 429, "body": {"detail": {"error": "rate_limited"}}},
            "http_500": {"status": 500},
            "bad_result": {"status": 200, "body": {"ok": True, "url": bad}},
            "cross": {"status": 403, "body": {"detail": "같은 고객 화면에서 저장해 주세요."}},
        }
        expected = {"sku_not_found": "sku_not_found", "rate_limited": "rate_limited", "http_500": "http_500", "bad_result": "bad_result", "cross": "http_403"}
        for name, reply in cases.items():
            out = run({"GET /api/customer/asus-cart/status": STATUS_OK, "POST /api/customer/asus-cart/add": reply}, adds=["business"])
            self.assertEqual(out["results"]["business"], {"ok": False, "code": expected[name]}, name)
            self.assertEqual((out["assigned"], out["opened"]), ([], []), name)
            self.assertEqual(out["after"]["business"]["note"], "장바구니에 담지 못했습니다. 잠시 후 다시 시도해 주세요.", name)
            self.assertFalse(out["after"]["business"]["disabled"], name)


if __name__ == "__main__":
    unittest.main()
