"""찜목록 저장소(mockups/mvp4/assets/js/wish-store.js) — 화면 연결 전 준비 (2026-10-21 대표 확정 「찜하기·찜목록」).

브라우저 없이 node 에서 localStorage·sessionStorage·이벤트를 흉내 내 실제로 돌려 본다(함수 이름만 찾는 검사가 아니다).
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "mockups/mvp4/assets/js/wish-store.js").read_text(encoding="utf-8")

SHIM = r"""
function store(mode) { var m = {}; return {
  getItem: function (k) { return Object.prototype.hasOwnProperty.call(m, k) ? m[k] : null; },
  setItem: function (k, v) { if (mode === 'throw') throw new Error('quota'); if (mode === 'drop') return; m[k] = String(v); },
  removeItem: function (k) { delete m[k]; }, _m: m }; }
function makeWindow(local, session) {
  var L = {}; var w = { localStorage: local, sessionStorage: session || store(),
    addEventListener: function (t, f) { (L[t] = L[t] || []).push(f); },
    removeEventListener: function (t, f) { L[t] = (L[t] || []).filter(function (g) { return g !== f; }); },
    dispatchEvent: function (e) { (L[e.type] || []).slice().forEach(function (f) { f(e); }); return true; } };
  return w; }
global.CustomEvent = function (type, init) { this.type = type; this.detail = init && init.detail; };
function load(w) { var window = w; eval(SRC); return w.PAI.wishlist; }
"""


def run(body):
    code = "var SRC = " + json.dumps(SRC) + ";" + SHIM + "var out = (function(){" + body + "})(); console.log(JSON.stringify(out));"
    return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)


@unittest.skipUnless(shutil.which("node"), "node 없음")
class WishStoreTest(unittest.TestCase):
    def test_add_toggle_remove_and_dedupe(self):
        out = run("""var W = load(makeWindow(store()));
          var a = W.add('pc', 100866), b = W.add('pc', '100866'), c = W.add('ai_device', 7);
          var t = W.toggle('pc', 100866);
          return [a.ok, b.already, c.count, t.wished, W.has('pc', 100866), W.count(), W.remove('pc', 1).already];""")
        self.assertEqual(out, [True, True, 2, False, False, 1, True])

    def test_rejects_invalid(self):
        out = run("""var W = load(makeWindow(store()));
          return [W.add('cpu', 1).reason, W.add('pc', 'abc').reason, W.add('pc', '1;2').ok, W.count()];""")
        self.assertEqual(out, ["invalid", "invalid", False, 0])

    def test_no_cap(self):
        out = run("""var W = load(makeWindow(store())); for (var i = 1; i <= 40; i++) W.add('pc', i); return W.count();""")
        self.assertEqual(out, 40)

    def test_storage_failure_is_not_success(self):
        out = run("""var T = load(makeWindow(store('throw'))), D = load(makeWindow(store('drop')));
          return [T.add('pc', 1), D.add('pc', 1), T.available(), D.count()];""")
        self.assertEqual(out[0], {"ok": False, "reason": "storage"})
        self.assertEqual(out[1], {"ok": False, "reason": "storage"})
        self.assertEqual(out[2:], [False, 0])

    def test_change_events_same_and_other_tab(self):
        out = run("""var shared = store(), w1 = makeWindow(shared), w2 = makeWindow(shared);
          var A = load(w1), B = load(w2), seen1 = [], seen2 = [];
          A.onChange(function (l) { seen1.push(l.length); }); var off = B.onChange(function (l) { seen2.push(l.length); });
          A.add('pc', 5);
          w2.dispatchEvent({ type: 'storage', key: 'pai-wish-v1' });   // 다른 탭에서 브라우저가 보내는 이벤트
          w2.dispatchEvent({ type: 'storage', key: 'something-else' });
          off(); w2.dispatchEvent({ type: 'storage', key: 'pai-wish-v1' });
          return [seen1, seen2, B.has('pc', 5)];""")
        self.assertEqual(out, [[1], [1], True])

    def test_migrate_once_from_real_compare_only(self):
        out = run("""var now = Date.now(), local = store(), session = store();
          local.setItem('pai-compare-carry-v1', JSON.stringify([{kind:'pc', id:'11', at: now}, {kind:'pc', id:'99', at: now - 31*60*1000}]));
          session.setItem('pai-finder-chat-v1', JSON.stringify({ selected: {id: '77'}, ids: ['1','2','3'],
            compare: [{kind:'pc', id:'11'}, {kind:'ai_device', id:'4'}] }));
          var W = load(makeWindow(local, session)), first = W.migrate();
          W.remove('pc', 11); var second = W.migrate();
          return [first.moved, second.already, W.list().map(function (x) { return x.kind + ':' + x.id; })];""")
        self.assertEqual(out, [2, True, ["ai_device:4"]])

    def test_list_newest_first(self):
        out = run("""var W = load(makeWindow(store())), t = Date.now; var n = 1000;
          Date.now = function () { return n++; }; W.add('pc', 1); W.add('pc', 2); Date.now = t;
          return W.list().map(function (x) { return x.id; });""")
        self.assertEqual(out, ["2", "1"])

    def test_no_network_or_llm(self):
        for word in ("fetch(", "XMLHttpRequest", "sendBeacon", "/api/"):
            self.assertNotIn(word, SRC)


if __name__ == "__main__":
    unittest.main()
