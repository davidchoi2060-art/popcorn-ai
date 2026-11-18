"""관리자 재설계 PR-A — 기본 모드 셸(6개 메뉴 묶음) · 환경 표시 · 「오늘 할 일」 (2026-11-01).

근거: Codex 확정안(공유 폴더 `outputs/admin-redesign-20261101/확정안_구현명세.md`).
DB 없이 돈다 — 숫자 원천은 함수 인자로 넣는다.
"""
import re
import unittest
from pathlib import Path

from starlette.requests import Request

from api import admin_ui_home as H
from api import admin_nav
from api.admin_nav import NAV, SIMPLE_EXTRA, SIMPLE_LABELS, SIMPLE_MENU, simple_nav
from api.admin_ui_common import env_label, render

ROOT = Path(__file__).resolve().parents[1]


def request(path="/admin2/", query="", cookie="", host="dev.popcornai.co.kr"):
    return Request(dict(type="http", method="GET", path=path, raw_path=path.encode(),
                        query_string=query.encode(), headers=[(b"cookie", cookie.encode()), (b"host", host.encode())],
                        scheme="https", server=(host, 443), root_path=""))


def nav_hrefs():
    return [h for _t, _i, items in NAV for _l, h, _n in items if h]


GROUPS = ["오늘 할 일", "상품", "상담·주문", "회원", "가격·재고", "AI 관리", "설정"]


class SimpleNavTests(unittest.TestCase):
    def test_groups_in_spec_order(self):
        # 2026-11-18 사장님 지시 — 「회원」 묶음 신설 · 「상담」→「상담·주문」.
        self.assertEqual([g["title"] for g in simple_nav()], GROUPS)

    def test_every_nav_path_appears_exactly_once(self):
        got = [r["href"] for g in simple_nav() for r in g["basic"] + g["advanced"]]
        extras = [h for _l, h in SIMPLE_EXTRA]
        screens = [h for h in got if h not in extras]
        self.assertEqual(sorted(screens), sorted(nav_hrefs() + list(SIMPLE_LABELS)))
        self.assertEqual(len(screens), len(set(screens)))
        for h in nav_hrefs():
            self.assertEqual(got.count(h), 1, h)

    def test_menu_definition_has_no_duplicate_or_unlabeled_path(self):
        mapped = [p for _t, _i, b, a in SIMPLE_MENU for p in b + a]
        self.assertEqual(len(mapped), len(set(mapped)))
        known = set(nav_hrefs()) | set(SIMPLE_LABELS)
        self.assertEqual([p for p in mapped if p not in known], [])
        # 메뉴 전용 라벨은 NAV 에 없는 경로만 — 라벨을 두 벌 두지 않는다.
        self.assertEqual(set(SIMPLE_LABELS) & set(nav_hrefs()), set())
        self.assertEqual(set(SIMPLE_LABELS) - set(mapped), set())

    def test_labels_come_from_nav(self):
        labels = {h: l for _t, _i, items in NAV for l, h, _n in items if h}
        labels.update(SIMPLE_LABELS)
        for g in simple_nav():
            for r in g["basic"] + g["advanced"]:
                if r["href"] in labels:
                    self.assertEqual(r["label"], labels[r["href"]])

    def test_directed_paths_are_basic_in_their_groups(self):
        groups = {g["title"]: g for g in simple_nav()}
        def basic(t): return [r["href"] for r in groups[t]["basic"]]
        def all_(t): return basic(t) + [r["href"] for r in groups[t]["advanced"]]
        self.assertEqual(basic("회원"), ["/admin2/members", "/admin2/member-reviews"])
        for p in ("/admin2/commerce-orders", "/admin2/payment-records", "/admin2/purchase-inquiries"):
            self.assertIn(p, basic("상담·주문"))
        for p in ("/admin2/sale-readiness", "/admin2/new", "/admin2/pc-builder"):
            self.assertIn(p, basic("상품"))
        for p in ("/admin2/pc-batch", "/admin2/pc-media", "/admin2/pc-video"):
            self.assertIn(p, all_("상품"))

    def test_new_admin_paths_all_reachable(self):
        # 폐지한 신 관리자 메뉴가 들고 있던 경로 전부 — 메뉴 통합이 화면을 숨기지 않는다.
        former = ("/admin2/", "/admin2/new", "/admin2/pc-workspace", "/admin2/pc-batch",
                  "/admin2/pc-configurations", "/admin2/pc-media", "/admin2/pc-video",
                  "/admin2/configuration-consultation", "/admin2/pc-builder", "/admin2/part-explanations",
                  "/admin2/products", "/admin2/product-new", "/admin2/catalog-import",
                  "/admin2/ai-device-profiles", "/admin2/asus-campaign", "/admin2/sale-readiness",
                  "/admin2/commerce-orders", "/admin2/purchase-inquiries", "/admin2/retention",
                  "/admin2/payment-records", "/admin2/members", "/admin2/member-reviews",
                  "/admin2/usage-floors", "/admin2/game-copy-review", "/admin2/game-grades",
                  "/admin2/talk-patterns", "/admin2/shop-notices", "/admin2/talk-review",
                  "/admin2/product-fit", "/admin2/activity-logs", "/admin2/price-history",
                  "/admin2/ai-response-log", "/admin2/consult-sessions", "/admin2/mvp3-consults",
                  "/admin2/handoff-log", "/admin2/swap-click-logs", "/admin2/dash")
        got = [r["href"] for g in simple_nav() for r in g["basic"] + g["advanced"]]
        for p in former:
            self.assertEqual(got.count(p), 1, p)

    def test_removed_menu_functions_have_no_references(self):
        self.assertFalse(hasattr(admin_nav, "new_admin" + "_nav"))
        self.assertFalse(hasattr(admin_nav, "workspace" + "_nav"))
        names = ("new_admin" + "_nav", "workspace" + "_nav", "a2-new-" + "entry", "a2-new-" + "secondary")
        hits = []
        for base in ("api", "templates", "tests"):
            for f in (ROOT / base).rglob("*"):
                if f.suffix not in (".py", ".j2", ".js", ".cjs", ".html") or not f.is_file():
                    continue
                text = f.read_text(encoding="utf-8", errors="ignore")
                hits += [f"{f.relative_to(ROOT)}:{n}" for n in names if n in text]
        self.assertEqual(hits, [])

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

    def test_new_admin_entry_is_removed(self):
        # 2026-11-18 — 「신 관리자(작업 화면)」 링크 폐지. 운영자 매뉴얼만 남는다.
        settings = [r["href"] for r in simple_nav()[-1]["advanced"]]
        self.assertNotIn("/admin2/?admin=new", settings)
        self.assertIn("/admin2/manual", settings)
        everything = [r["href"] for g in simple_nav() for r in g["basic"] + g["advanced"]]
        self.assertFalse([h for h in everything if "admin=" in h])


class ShellRenderTests(unittest.TestCase):
    def html(self, path, **kw):
        return render(request(path, **kw), "admin/new_home.html.j2").body.decode()

    def test_default_mode_draws_simple_shell(self):
        html = self.html("/admin2/reviews")
        self.assertIn('data-admin-shell="simple"', html)
        for title in GROUPS:
            self.assertIn(f'title="{title}"', html)
        lnb = html[html.index('id="lnb"'):html.index('id="lnbToggle"')]
        self.assertEqual(lnb.count('aria-current="page"'), 1)
        self.assertIn('class="a2-lnb-mobile-toggle"', html)
        self.assertNotIn('class="a2-new-' + 'entry"', html)

    def test_advanced_section_hidden_unless_current(self):
        html = self.html("/admin2/reviews")
        self.assertIn('data-action="lnb-advanced"', html)
        boxes = re.findall(r'<div class="a2-sn-advb" id="lnbAdv\d+" ?(hidden)?>', html)
        self.assertTrue(boxes)
        self.assertTrue(all(b == "hidden" for b in boxes))
        html2 = self.html("/admin2/ai-device-profiles")
        self.assertTrue(any(b == "" for b in re.findall(r'<div class="a2-sn-advb" id="lnbAdv\d+" ?(hidden)?>', html2)))

    def test_new_mode_draws_the_same_menu(self):
        # 2026-11-18 — ?admin=new · 쿠키 new 여도 좌측 메뉴는 같은 한 벌이다.
        def lnb(h): return h[h.index('id="lnb"'):h.index('id="lnbToggle"')]
        for path in ("/admin2/pc-configurations", "/admin2/members", "/admin2/", "/admin2/sale-price"):
            legacy = self.html(path)
            for kw in ({"query": "admin=new"}, {"cookie": "admin_ui_mode=new"}):
                new = self.html(path, **kw)
                self.assertIn('data-admin-shell="simple"', new)
                self.assertEqual(lnb(new), lnb(legacy), (path, kw))
                self.assertNotIn("admin=new", lnb(new))
                self.assertNotIn("admin=legacy", lnb(new))

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
            self.assertIn(h.split("?")[0], live)
        # 2026-11-18 — 운영 현황 대시보드는 「자주 하는 작업」 링크로 간다.
        self.assertIn(H.OVERVIEW_HREF, [h for _n, _d, h in H.QUICK_LINKS])

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
