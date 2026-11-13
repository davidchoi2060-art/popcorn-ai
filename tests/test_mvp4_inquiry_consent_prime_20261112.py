"""mvp4 문의 동의 문구 선호출 (2026-11-12). service-adapters.js 를 Node 로 실제 실행한다(네트워크·DB·브라우저 없음).

결함: 동의 문구 호출이 ai-consult.html 에서만 돌아, asus-consult.html 은 필수 동의 칸이 잠긴 채 남았다.
고침: 화면 이름이 아니라 문서에 [name=privacyConsent] 칸이 나타났는가로 한 번 호출한다.
메뉴: asus-consult.html 에서 header-ui.js 의 syncSelection 이 어느 주 메뉴도 켜지 않는다.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "mockups/mvp4/assets/js"

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [file, pathname, mode] = process.argv.slice(1);
let calls = [], observers = [];
const box = { disabled: true, parentNode: null };
const span = { textContent: '불러오고 있어요.', innerHTML: '', appendChild(n) { this.textContent += n.textContent; } };
box.parentNode = { querySelector: () => span };
let hasBox = mode.indexOf('nobox') < 0 && mode.indexOf('late') < 0;
const fail = mode.indexOf('fail') >= 0;
const win = {};
const ctx = {
  window: win, location: { pathname }, setTimeout, clearTimeout, Promise, JSON, Error, AbortController,
  document: { documentElement: {}, querySelector: (q) => (q === '[name=privacyConsent]' && hasBox ? box : null),
    createTextNode: (t) => ({ textContent: t }), createElement: () => ({ textContent: '' }) },
  MutationObserver: function (cb) { observers.push(cb); this.observe = () => {}; },
  fetch: (url) => { calls.push(url); return fail ? Promise.reject(new Error('x')) : Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true, consent_text: '동의 문구입니다.' }) }); },
};
vm.runInNewContext(fs.readFileSync(file, 'utf8'), ctx);
const tick = () => new Promise((r) => setTimeout(r, 20));
(async () => {
  await tick();
  const out = { afterLoad: calls.length };
  if (mode.indexOf('late') >= 0) { hasBox = true; observers.forEach((o) => o()); await tick(); }
  for (let i = 0; i < 5; i++) { observers.forEach((o) => o()); await tick(); }   // 화면이 계속 바뀌어도
  out.calls = calls.slice();
  out.disabled = box.disabled;
  out.text = span.textContent;
  console.log(JSON.stringify(out));
})();
"""

NAV = r"""
const fs = require('fs'), vm = require('vm');
const [file, pathname, page] = process.argv.slice(1);
const link = (nav, primary) => { const a = { dataset: { nhNav: nav }, attrs: {}, closest: () => primary, removeAttribute(k) { delete this.attrs[k]; }, setAttribute(k, v) { this.attrs[k] = v; } }; return a; };
const links = ['ai', 'chat', 'catalog', 'asus-consult', 'asus-detail'].map((n) => link(n, true));
const noop = () => {};
const el = new Proxy(function () {}, { get: () => el, apply: () => el });
const win = { requestAnimationFrame: noop, addEventListener: noop, PAI: { h: String, qs: new URLSearchParams(), asus: {}, route: String } };
const ctx = { window: win, location: { pathname, search: '' }, URLSearchParams,
  document: { readyState: 'loading', body: { dataset: { page } }, addEventListener: noop, querySelectorAll: (q) => (q === '[data-nh-nav]' ? links : []), querySelector: () => null, getElementById: () => null } };
let src = fs.readFileSync(file, 'utf8');
src = src.replace(/\}\(\)\);?\s*$/, 'window.__sync = syncSelection;}());');
try { vm.runInNewContext(src, ctx); } catch (e) { console.log(JSON.stringify({ err: String(e) })); process.exit(0); }
win.__sync();
console.log(JSON.stringify({ current: links.filter((l) => l.attrs['aria-current']).map((l) => l.dataset.nhNav) }));
"""


def run(script, *args):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node 없음")
    out = subprocess.run([node, "-e", script, "--", *args], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


FORM = "/api/mvp3/purchase-inquiries/form"


class ConsentPrime(unittest.TestCase):
    def go(self, path, mode):
        return run(HARNESS, str(JS / "service-adapters.js"), path, mode)

    def test_asus_consult_loads_consent_once_and_unlocks(self):
        r = self.go("/mvp4/asus-consult.html", "box")
        self.assertEqual(r["calls"], [FORM])
        self.assertFalse(r["disabled"])
        self.assertIn("동의 문구입니다.", r["text"])

    def test_ai_consult_still_works(self):
        r = self.go("/mvp4/ai-consult.html", "box")
        self.assertEqual(r["calls"], [FORM])
        self.assertFalse(r["disabled"])

    def test_form_drawn_later_triggers_load(self):
        r = self.go("/mvp4/asus-consult.html", "late")
        self.assertEqual(r["afterLoad"], 0)
        self.assertEqual(r["calls"], [FORM])
        self.assertFalse(r["disabled"])

    def test_no_consent_box_no_call(self):
        for path in ("/mvp4/support.html", "/mvp4/ai-consult.html"):
            self.assertEqual(self.go(path, "nobox")["calls"], [], path)

    def test_failure_does_not_loop(self):
        r = self.go("/mvp4/asus-consult.html", "box,fail")
        self.assertEqual(len(r["calls"]), 1)
        self.assertTrue(r["disabled"])


class AsusMenu(unittest.TestCase):
    def cur(self, path, page):
        return run(NAV, str(JS / "header-ui.js"), path, page)

    def test_asus_consult_lights_no_menu(self):
        r = self.cur("/mvp4/asus-consult.html", "ai-consult")
        self.assertNotIn("err", r, r)
        self.assertNotIn("ai", r["current"])

    def test_ai_consult_still_lights_ai(self):
        r = self.cur("/mvp4/ai-consult.html", "ai-consult")
        self.assertNotIn("err", r, r)
        self.assertEqual(r["current"], ["ai"])


if __name__ == "__main__":
    unittest.main()
