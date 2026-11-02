"""관리자 재설계 PR-A — 기본 모드 셸(6개 메뉴 묶음) · 환경 표시 · 「오늘 할 일」 (2026-11-01).

근거: Codex 확정안(공유 폴더 `outputs/admin-redesign-20261101/확정안_구현명세.md`).
DB 없이 돈다 — 숫자 원천은 함수 인자로 넣는다.
"""
import re
import unittest
from pathlib import Path

from starlette.requests import Request

from api import admin_ui_home as H
from api.admin_nav import NAV, SIMPLE_EXTRA, SIMPLE_MENU, simple_nav
from api.admin_ui_common import env_label, render

ROOT = Path(__file__).resolve().parents[1]


def request(path="/admin2/", query="", cookie="", host="dev.popcornai.co.kr"):
    return Request(dict(type="http", method="GET", path=path, raw_path=path.encode(),
                        query_string=query.encode(), headers=[(b"cookie", cookie.encode()), (b"host", host.encode())],
                        scheme="https", server=(host, 443), root_path=""))


def nav_hrefs():
    return [h for _t, _i, items in NAV for _l, h, _n in items if h]


class SimpleNavTests(unittest.TestCase):
    def test_six_groups_in_spec_order(self):
        self.assertEqual([g["title"] for g in simple_nav()],
                         ["오늘 할 일", "상품", "상담", "가격·재고", "AI 관리", "설정"])

    def test_every_nav_path_appears_exactly_once(self):
        got = [r["href"] for g in simple_nav() for r in g["basic"] + g["advanced"]]
        extras = [h for _l, h in SIMPLE_EXTRA]
        screens = [h for h in got if h not in extras]
        self.assertEqual(sorted(screens), sorted(nav_hrefs()))
        self.assertEqual(len(screens), len(set(screens)))

    def test_labels_come_from_nav(self):
        labels = {h: l for _t, _i, items in NAV for l, h, _n in items if h}
        for g in simple_nav():
            for r in g["basic"] + g["advanced"]:
                if r["href"] in labels:
                    self.assertEqual(r["label"], labels[r["href"]])

    def test_unmapped_nav_path_falls_into_settings_advanced(self):
        mapped = {p for _t, _i, b, a in SIMPLE_MENU for p in b + a}
        leftovers = [h for h in nav_hrefs() if h not in mapped]
        settings = [r["href"] for r in simple_nav()[-1]["advanced"]]
        for h in leftovers:
            self.assertIn(h, settings)

    def test_active_screen_in_advanced_opens_group_and_advanced(self):
        g = next(x for x in simple_nav("/admin2/ai-device-profiles") if x["title"] == "상품")
        self.assertTrue(g["active"])
        self.assertTrue(g["advanced_active"])
        actives = [r for x in simple_nav("/admin2/ai-device-profiles") for r in x["basic"] + x["advanced"] if r["active"]]
        self.assertEqual(len(actives), 1)

    def test_today_group_is_a_link(self):
        today = simple_nav("/admin2/")[0]
        self.assertEqual(today["href"], "/admin2/")
        self.assertTrue(today["active"])

    def test_new_admin_entry_is_kept(self):
        settings = [r["href"] for r in simple_nav()[-1]["advanced"]]
        self.assertIn("/admin2/?admin=new", settings)
        self.assertIn("/admin2/manual", settings)


class ShellRenderTests(unittest.TestCase):
    def html(self, path, **kw):
        return render(request(path, **kw), "admin/new_home.html.j2").body.decode()

    def test_default_mode_draws_simple_shell(self):
        html = self.html("/admin2/reviews")
        self.assertIn('data-admin-shell="simple"', html)
        for title in ("오늘 할 일", "상품", "상담", "가격·재고", "AI 관리", "설정"):
            self.assertIn(f'title="{title}"', html)
        lnb = html[html.index('id="lnb"'):html.index('id="lnbToggle"')]
        self.assertEqual(lnb.count('aria-current="page"'), 1)
        self.assertIn('class="a2-lnb-mobile-toggle"', html)
        self.assertNotIn('class="a2-new-entry"', html)

    def test_advanced_section_hidden_unless_current(self):
        html = self.html("/admin2/reviews")
        self.assertIn('data-action="lnb-advanced"', html)
        boxes = re.findall(r'<div class="a2-sn-advb" id="lnbAdv\d+" ?(hidden)?>', html)
        self.assertTrue(boxes)
        self.assertTrue(all(b == "hidden" for b in boxes))
        html2 = self.html("/admin2/ai-device-profiles")
        self.assertTrue(any(b == "" for b in re.findall(r'<div class="a2-sn-advb" id="lnbAdv\d+" ?(hidden)?>', html2)))

    def test_new_mode_is_unchanged(self):
        html = self.html("/admin2/pc-configurations", cookie="admin_ui_mode=new")
        self.assertNotIn('data-admin-shell="simple"', html)
        self.assertIn('class="a2-new-secondary"', html)

    def test_env_badge(self):
        self.assertIn('class="a2-env" data-env="개발 환경"', self.html("/admin2/reviews"))


class EnvLabelTests(unittest.TestCase):
    def test_hosts(self):
        self.assertEqual(env_label(request(host="dev.popcornai.co.kr")), "개발 환경")
        self.assertEqual(env_label(request(host="admin.popcornai.co.kr")), "운영 환경")
        self.assertEqual(env_label(request(host="127.0.0.1")), "로컬 개발")
        self.assertEqual(env_label(request(host="fixture.invalid")), "")


class TodayRowsTests(unittest.TestCase):
    WL = {"items": [{"key": "price", "count": 0}, {"key": "review", "count": 6374}]}

    def test_states(self):
        rows = {r["key"]: r for r in H._today_rows({"inquiry_wait": 3}, None, self.WL, None)}
        self.assertEqual((rows["inquiry"]["state"], rows["inquiry"]["value"]), ("ok", "3"))
        self.assertEqual((rows["price"]["state"], rows["price"]["value"]), ("zero", "0"))
        self.assertEqual((rows["review"]["state"], rows["review"]["value"]), ("ok", "6,374"))

    def test_failure_is_not_zero(self):
        rows = H._today_rows(None, "상담 신청 대기 조회 실패(X)", None, "지금 할 일 조회 실패(X)")
        for r in rows:
            self.assertEqual(r["state"], "error")
            self.assertEqual(r["value"], "—")
            self.assertTrue(r["reason"])

    def test_links_use_existing_screen_conditions(self):
        hrefs = {r["key"]: r["href"] for r in H._today_rows(None, None, None, None)}
        self.assertEqual(hrefs, {"inquiry": "/admin2/purchase-inquiries?status=대기",
                                 "price": "/admin2/price-review", "review": "/admin2/reviews"})
        live = set(nav_hrefs())
        for h in hrefs.values():
            self.assertIn(h.split("?")[0], live)
        for _n, _d, h in H.QUICK_LINKS:
            self.assertIn(h, live)

    def test_template_order_and_preserved_metrics(self):
        t = (ROOT / "templates/admin/home.html.j2").read_text(encoding="utf-8")
        order = [t.index(s) for s in ("먼저 확인할 일", "자주 하는 작업", "최근 작업", "상태 확인", 'details class="td-more"')]
        self.assertEqual(order, sorted(order))
        more = t[t.index('details class="td-more"'):]
        for kept in ("{{ flow.mvp3_scope }}", "견적 품질 — 누적", "유입 깔때기"):
            self.assertIn(kept, more)
        self.assertNotIn("최근 운영자 활동", t)   # 최근 작업 표 하나로 합쳤다


if __name__ == "__main__":
    unittest.main()


class EveryShellPageHasTitleTests(unittest.TestCase):
    """셸을 상속하는 화면은 탭 제목(block title)을 채운다 — 비면 「팝콘PC 관리자 ·」로 끝난다
    (2026-11-02 Codex 개발 서버 관찰: /admin2/mall-sync)."""

    def test_title_block_present(self):
        import re as _re
        from pathlib import Path as _P
        root = _P(__file__).resolve().parents[1] / "templates/admin"
        missing = []
        for f in sorted(root.glob("*.j2")):
            t = f.read_text(encoding="utf-8")
            if _re.search(r'{%\s*extends\s+["\']admin/_admin2_shell\.html\.j2["\']', t) and \
                    not _re.search(r"{%\s*block\s+title\s*%}\s*\S", t):
                missing.append(f.name)
        self.assertEqual(missing, [])
