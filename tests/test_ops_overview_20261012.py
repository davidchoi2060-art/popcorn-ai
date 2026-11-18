"""신 관리자 첫 화면 「운영 현황」(2026-10-12 사장님 확정 · 코덱스 대시보드 기획안 v1).

DB 없이 본다 — 원천 조회는 패치하고, 카드 상태 구분 · 링크 · 돌아가기 줄 · 메뉴 자리를 검사한다.
"""
import unittest
from unittest import mock

from starlette.requests import Request

from api import admin_home_overview as OV
from api import admin_ui_home as H
from api.admin_nav import simple_nav
from api.admin_ui_common import admin_mode, render


def request(path='/admin2/', query='', cookie=''):
    return Request(dict(type='http', method='GET', path=path, raw_path=path.encode(),
                        query_string=query.encode(), headers=[(b'cookie', cookie.encode())],
                        scheme='https', server=('admin.example', 443), root_path=''))


WORKLIST = {"items": [
    {"key": "review", "count": 5156, "focus": 120, "focus_label": "판매중·재고 있는 것"},
    {"key": "price", "count": 0, "focus": None, "focus_label": None},
    {"key": "category", "count": 3, "focus": None, "focus_label": None},
    {"key": "price_import", "count": 1, "focus": None, "focus_label": None},
    {"key": "sourcing", "count": 2, "focus": None, "focus_label": None},
]}
DASH = {"flow": {"sessions_today": 4, "sessions_done": 1, "mvp3_inquiries_today": 12,
                 "sessions_scope_note": "시험 운영 기간 제외"}}
MALL = {"last": {"started_at": "2026-10-12T04:00:00+00:00", "ok": False, "changed": 0,
                 "held": 0, "moment_label": "자동 갱신", "fail_reason": "로그인 실패"}}


def fake_build(**over):
    sources = {
        "auto_status": lambda: MALL,
        "quote_quality": lambda: {"stock_drift": 0},
        "_counts": lambda: {"inquiry_wait": 2, "inquiry_doing": 1, "reported": 0, "rules": 7},
        "worklist": lambda: WORKLIST,
        "_releases": lambda: {"before": 3, "changed": 1, "public": 9},
        "dashboard": lambda: DASH,
        "_recent_logs": lambda: [{"at": "10-12 14:05", "kind": "상품", "target": "123",
                                  "action": "수정", "operator": "점검"}],
    }
    sources.update(over)
    with mock.patch("api.admin_dashboard.dashboard", sources["dashboard"]), \
         mock.patch("api.admin_dashboard.quote_quality", sources["quote_quality"]), \
         mock.patch("api.admin_dashboard.worklist", sources["worklist"]), \
         mock.patch("api.admin_mall_price.auto_status", sources["auto_status"]), \
         mock.patch.object(OV, "_counts", sources["_counts"]), \
         mock.patch.object(OV, "_releases", sources["_releases"]), \
         mock.patch.object(OV, "_recent_logs", sources["_recent_logs"]):
        return OV.build()


def boom():
    raise RuntimeError("db down")


class CardStates(unittest.TestCase):
    def test_zero_failure_and_unconnected_are_different(self):
        zero = OV.card("a", "", value=0)
        fail = OV.card("a", "", value=None, err=OV.LOAD_FAILED)
        none = OV.card("a", "", connected=False)
        self.assertEqual((zero["state"], zero["value"]), ("zero", "0"))
        self.assertEqual((fail["state"], fail["value"]), ("error", "—"))
        self.assertEqual((none["state"], none["value"], none["msg"]), ("none", "—", OV.NOT_CONNECTED))

    def test_card_link_carries_overview_marker_once(self):
        self.assertEqual(OV.link("/admin2/reviews"), "/admin2/reviews?from=overview")
        self.assertEqual(OV.link("/admin2/x?status=대기"), "/admin2/x?status=대기&from=overview")
        self.assertEqual(OV.link("/admin2/x?from=overview"), "/admin2/x?from=overview")
        self.assertIsNone(OV.link(None))


class Build(unittest.TestCase):
    def test_sections_and_no_total(self):
        ov = fake_build()
        titles = [c["title"] for c in ov["work"]["cards"]]
        self.assertEqual(titles, ["상담 처리 대기", "후기 검토", "해석 규칙 검토", "상품 사양 검수", "가격 검토 대기"])
        self.assertNotIn("total", ov["work"])
        self.assertEqual(ov["work"]["cards"][0]["value"], "2")        # 대기만 — 목록 필터와 같은 조건
        self.assertEqual(ov["work"]["cards"][1]["state"], "zero")
        self.assertEqual(ov["work"]["cards"][3]["value"], "5,156")

    def test_failed_mall_run_is_flagged(self):
        ov = fake_build()
        mall = ov["status"]["cards"][0]
        self.assertEqual(mall["state"], "warn")
        self.assertIn("로그인 실패", mall["note"])
        self.assertTrue(ov["status"]["has_issue"])

    def test_one_source_failing_keeps_the_rest(self):
        ov = fake_build(worklist=boom, dashboard=boom)
        spec = ov["work"]["cards"][3]
        self.assertEqual((spec["state"], spec["value"], spec["msg"]), ("error", "—", OV.LOAD_FAILED))
        self.assertEqual(ov["work"]["cards"][2]["value"], "7")
        self.assertTrue(all(r["state"] in ("error", "none") for r in ov["flow"]["rows"]))

    def test_handoff_and_attach_are_not_invented(self):
        ov = fake_build()
        handoff = [r for r in ov["flow"]["rows"] if r["title"] == "쇼핑몰 인계"][0]
        self.assertEqual(handoff["state"], "none")
        attach = ov["release"]["cards"][1]
        self.assertEqual(attach["state"], "none")

    def test_shortcuts_hold_the_three_hidden_screens(self):
        hrefs = [s["href"] for s in OV._shortcuts() if s["href"]]
        for path in ("/admin2/build-map", "/admin2/grid", "/admin2/game-matrix", "/admin2/payment-records"):
            self.assertIn(path + "?from=overview", hrefs)


class RecentLogs(unittest.TestCase):
    def test_internal_codes_are_not_shown_as_text(self):
        rows = [{"created_at": None, "target_kind": "zzz", "target_id": "run:4",
                 "action": "mall_price_apply_unknown", "operator": "—"}]
        conn = mock.MagicMock()
        conn.__enter__.return_value.execute.return_value.mappings.return_value.all.return_value = rows
        with mock.patch.object(OV.engine, "connect", return_value=conn):
            out = OV._recent_logs()[0]
        self.assertEqual((out["kind"], out["action"], out["operator"]), ("기타 업무", "기타 처리", "자동 작업"))
        self.assertEqual((out["code"], out["target"]), ("mall_price_apply_unknown", "4회차 실행"))

    def test_mall_price_actions_have_korean_labels(self):
        from api.admin_activity_logs import ACTION_LABELS
        for code in ("mall_price_apply", "mall_price_undo", "ai_integration_limit_clear"):
            self.assertIn(code, ACTION_LABELS)
        self.assertEqual(OV._target("cart"), "장바구니")


class Shell(unittest.TestCase):
    # 2026-11-18 메뉴 통합 — 첫 화면은 「오늘 할 일」 하나다. 운영 현황은 그 안의 링크(?view=overview)로 연다.
    def home_template(self, query='', cookie=''):
        calls = []
        def fake_render(req, template, **kw):
            calls.append(template)
            return 'sentinel'
        with mock.patch.object(H, 'resolve_session', return_value={'id': 1}), \
                mock.patch.object(H, 'render', side_effect=fake_render), \
                mock.patch.object(H, '_safe', return_value=(None, '조회 실패(시험)')), \
                mock.patch.object(OV, 'build', return_value=fake_build()):
            H.home(request('/admin2/', query=query, cookie=cookie))
        return calls

    def test_today_is_the_only_first_screen(self):
        today = simple_nav('/admin2/')[0]
        self.assertEqual((today["title"], today["href"], today["active"]), ("오늘 할 일", "/admin2/", True))
        for query, cookie in (('', ''), ('admin=new', ''), ('', 'admin_ui_mode=new')):
            with self.subTest(query=query, cookie=cookie):
                self.assertEqual(self.home_template(query, cookie), ['admin/home.html.j2'])

    def test_overview_opens_from_today_link(self):
        self.assertEqual(H.OVERVIEW_HREF, '/admin2/?view=overview')
        self.assertIn(H.OVERVIEW_HREF, [h for _n, _d, h in H.QUICK_LINKS])
        for cookie in ('', 'admin_ui_mode=new'):
            self.assertEqual(self.home_template('view=overview', cookie), ['admin/ops_overview.html.j2'])
        # 운영 현황을 열어도 「오늘 할 일」 묶음이 켜진다(첫 화면 경로 그대로).
        self.assertEqual(["오늘 할 일"], [g["title"] for g in simple_nav('/admin2/') if g["active"]])

    def test_mode_query_beats_cookie(self):
        self.assertEqual(admin_mode(request(query='admin=new', cookie='admin_ui_mode=legacy')), 'new')
        self.assertEqual(admin_mode(request(cookie='admin_ui_mode=new')), 'new')
        self.assertEqual(admin_mode(request(query='admin=zzz')), 'legacy')

    def test_page_renders_with_back_to_overview_on_lists(self):
        html = render(request('/admin2/', query='view=overview'), 'admin/ops_overview.html.j2',
                      page_intro=None, ov=fake_build()).body.decode()
        for text in ("운영 현황", "확인이 필요한 상태", "처리할 작업", "고객 공개 전 점검",
                     "고객 이용 흐름", "최근 처리 기록", "자료 바로가기", "아직 집계가 연결되지 않았습니다."):
            self.assertIn(text, html)
        self.assertNotIn("a2BackLink", html)
        self.assertIn('href="/admin2/?view=overview">다시 조회', html)
        self.assertIn('data-admin-shell="simple"', html)
        for cookie in ('', 'admin_ui_mode=new'):
            listing = render(request('/admin2/reviews', query='from=overview', cookie=cookie),
                             'admin/new_home.html.j2').body.decode()
            self.assertIn("운영 현황으로 돌아가기", listing)
            self.assertIn('href="/admin2/?view=overview"', listing)
        plain = render(request('/admin2/reviews', cookie='admin_ui_mode=new'),
                       'admin/new_home.html.j2').body.decode()
        self.assertNotIn("운영 현황으로 돌아가기", plain)

    def test_new_admin_entry_button_is_gone(self):
        for cookie in ('', 'admin_ui_mode=new'):
            html = render(request('/admin2/products', cookie=cookie), 'admin/new_home.html.j2').body.decode()
            self.assertNotIn('href="/admin2/?admin=new"', html)


if __name__ == "__main__":
    unittest.main()
