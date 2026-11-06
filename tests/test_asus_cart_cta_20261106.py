"""ASUS 장바구니 버튼 (2026-11-06). 연결 전에는 아무것도 보내지 않고, adapter 는 mock 으로만 검증한다.

asus-cart.js 를 Node 로 실제 실행한다. 렌더 확인은 공유 폴더 검증자료의 로컬 브라우저 결과를 본다.
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
PAGES = (MVP4 / "assets/js/asus-pages.js").read_text(encoding="utf-8")
DOC = (ROOT / "docs/asus-ai-pc-v4/CART-ADAPTER.md").read_text(encoding="utf-8")

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const trap = (name) => { throw new Error('forbidden ' + name); };
const assigned = [];
class FakeURL extends URL {}
const windowObj = {
  PAI: { h: (v) => String(v), asus: { known: (id) => ['business', 'video', 'local-ai'].includes(id) } },
  location: { assign: (u) => assigned.push(u) },
};
const ctx = { window: windowObj, URL: FakeURL, Promise, setTimeout: (fn, ms) => setTimeout(fn, ms > 1000 ? 20 : ms), clearTimeout,
  document: { addEventListener() {}, querySelectorAll: () => [] },
  fetch: () => trap('fetch'), XMLHttpRequest: function () { trap('xhr'); },
  localStorage: new Proxy({}, { get: () => trap('localStorage') }), sessionStorage: new Proxy({}, { get: () => trap('sessionStorage') }) };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const C = windowObj.PAI.asusCart;
const O = 'https://shop.example.test';
const mock = (add) => C.setAdapter({ origins: [O], add });
(async () => {
  const out = {};
  out.defaultConnected = C.connected();
  out.defaultAdd = await C.add('business');
  const calls = [];
  mock((r) => { calls.push(JSON.parse(JSON.stringify(r))); return Promise.resolve({ ok: true, url: O + '/cart' }); });
  out.unknown = await C.add('other');
  out.success = await C.add('local-ai');
  out.calls = calls.slice();
  out.assigned = assigned.slice();
  let count = 0, release;
  mock(() => { count += 1; return new Promise((r) => { release = r; }); });
  const first = C.add('video');
  out.second = await C.add('video');
  release({ ok: true, url: O + '/cart' });
  await first;
  out.doubleCalls = count;
  assigned.length = 0;
  mock(() => Promise.resolve({ ok: true }));
  out.noUrl = await C.add('video');
  mock(() => Promise.resolve({ ok: true, url: 'https://other.example.test/cart' }));
  out.badOrigin = await C.add('video');
  mock(() => Promise.resolve({ ok: true, url: 'javascript:alert(1)' }));
  out.badScheme = await C.add('video');
  mock(() => Promise.resolve({ ok: false, code: 'sold_out' }));
  out.refused = await C.add('video');
  mock(() => Promise.reject(new Error('x')));
  out.rejected = await C.add('video');
  mock(() => { throw new Error('x'); });
  out.thrown = await C.add('video');
  mock(() => new Promise(() => {}));
  out.timeout = await C.add('video');
  out.assignedAfterFailures = assigned.slice();
  try { C.setAdapter({ add() {} }); out.noOrigins = 'accepted'; } catch (e) { out.noOrigins = 'rejected'; }
  C.setAdapter(null);
  out.reset = await C.add('video');
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""


class Adapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node 없음")
        r = subprocess.run([node, "-e", HARNESS, str(MVP4 / "assets/js/asus-cart.js")], capture_output=True, timeout=30)
        if r.returncode:
            raise AssertionError(r.stderr.decode("utf-8", "replace"))
        cls.out = json.loads(r.stdout.decode("utf-8"))

    def test_default_sends_nothing(self):
        self.assertFalse(self.out["defaultConnected"])
        self.assertEqual(self.out["defaultAdd"], {"ok": False, "code": "not_connected"})

    def test_boundary_is_model_id_and_quantity_one_only(self):
        self.assertEqual(self.out["calls"], [{"modelId": "local-ai", "quantity": 1}])

    def test_unknown_model_never_calls_adapter(self):
        self.assertEqual(self.out["unknown"]["code"], "unknown_model")

    def test_success_moves_only_to_allowed_url(self):
        self.assertTrue(self.out["success"]["ok"])
        self.assertEqual(self.out["assigned"], ["https://shop.example.test/cart"])

    def test_double_click_calls_once(self):
        self.assertEqual(self.out["second"]["code"], "busy")
        self.assertEqual(self.out["doubleCalls"], 1)

    def test_nothing_counts_as_success_without_real_result(self):
        for key in ("noUrl", "badOrigin", "badScheme", "refused", "rejected", "thrown", "timeout"):
            self.assertFalse(self.out[key]["ok"], key)
        self.assertEqual(self.out["timeout"]["code"], "timeout")
        self.assertEqual(self.out["assignedAfterFailures"], [])

    def test_adapter_needs_origins_and_can_be_removed(self):
        self.assertEqual(self.out["noOrigins"], "rejected")
        self.assertEqual(self.out["reset"]["code"], "not_connected")


class Static(unittest.TestCase):
    def test_module_has_no_write_redirect_or_storage_of_its_own(self):
        code = re.sub(r"/\*.*?\*/", "", CART, flags=re.S)
        for word in ("fetch(", "XMLHttpRequest", "sendBeacon", "localStorage", "sessionStorage", "<form", "popcornpc", "mall_no", "plan", "http://", "https://"):
            self.assertNotIn(word, code, word)
        self.assertEqual(code.count("window.location.assign"), 1)

    def test_customer_text_has_no_internal_wording(self):
        shown = re.findall(r"var (?:LABEL|PENDING|NOT_READY|FAILED) = '([^']+)'", CART)
        self.assertEqual(len(shown), 4)
        for word in ("API", "연결", "개발", "adapter", "다음 주", "몰"):
            self.assertNotIn(word, " ".join(shown), word)

    def test_card_primary_is_cart_and_detail_stays_reachable(self):
        card = PAGES[PAGES.index("function card(m)"):PAGES.index("// 불러오는 중")]
        self.assertIn("P.asusCart.html(m.id, m.name)", card)
        self.assertNotIn("자세히 보기", card)
        self.assertGreaterEqual(card.count("A.detailHref(m.id)"), 3)   # 제목 · 사진 · 상품 정보

    def test_detail_keeps_inquiry_and_shows_no_price(self):
        aside = PAGES[PAGES.index('<aside class="az-detail-buy"'):PAGES.index("</aside>")]
        self.assertIn("P.asusCart.html(m.id, m.name)", aside)
        self.assertIn("A.inquiryHref(m.id)", aside)
        self.assertNotIn("plan", aside)

    def test_pages_load_module_before_pages(self):
        for name in ("asus.html", "asus-pc.html"):
            html = (MVP4 / name).read_text(encoding="utf-8")
            self.assertLess(html.index("assets/js/asus-data.js"), html.index("assets/js/asus-cart.js"))
            self.assertLess(html.index("assets/js/asus-cart.js"), html.index("assets/js/asus-pages.js"))

    def test_contract_says_it_is_not_an_api_spec(self):
        self.assertIn("팝콘PC API 명세가 아니다", DOC)
        self.assertIn("다음 주 미완료 목록", DOC)


if __name__ == "__main__":
    unittest.main()
