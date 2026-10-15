"""고객 회원 P3 화면 -- 상단 로그인/마이페이지 · 로그인 창 · 가입 동의 · 로그인 예외 (시안 v1 ①~④, 2026-10-14 사장님 승인).

화면 동작은 로컬 서버(로그인 스위치 켬 · 가짜 키)에 Chrome 을 CDP 로 붙여 PC 1280·휴대폰 390 폭으로 찍어 확인했다
(PR 본문). 여기서는 계약을 고정한다: 꺼져 있으면 아무것도 안 그림 · 문구 · 필수 동의 3개 · 마케팅 없음 · 안전한 DOM.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MVP3 = ROOT / "mockups" / "mvp3"
MEMBER = (MVP3 / "member.js").read_text(encoding="utf-8")
JOIN_JS = (MVP3 / "join.js").read_text(encoding="utf-8")
JOIN = (MVP3 / "join.html").read_text(encoding="utf-8")
CSP = "default-src 'self'; script-src 'self'; style-src 'self'"


class Pages(unittest.TestCase):
    def test_customer_pages_load_member_module_once(self):
        for name in ("talk.html", "index.html", "new-pcs.html"):
            html = (MVP3 / name).read_text(encoding="utf-8")
            self.assertEqual(html.count('src="member.js"'), 1, name)
            self.assertEqual(html.count('href="member.css"'), 1, name)
            self.assertEqual(html.count("</head>"), 1, name)
            self.assertNotIn("\x01", html)
            self.assertIn(CSP, html)

    def test_new_pages_keep_strict_csp_and_no_inline_script(self):
        for name in ("join.html", "terms.html", "privacy.html"):
            html = (MVP3 / name).read_text(encoding="utf-8")
            self.assertIn(CSP, html, name)
            self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)", html), name)
            self.assertIn("form-action 'none'", html)


class MemberModule(unittest.TestCase):
    def test_draws_nothing_unless_server_enabled(self):
        self.assertIn("r.data.enabled !== true", MEMBER)
        self.assertIn("'/api/auth/providers'", MEMBER)

    def test_login_goes_to_same_site_start_with_safe_return(self):
        self.assertIn("'/api/auth/' + key + '/start?return=' + encodeURIComponent(returnPath())", MEMBER)
        self.assertIn("p.startsWith('/mvp3/') ? p : '/mvp3/'", MEMBER)
        for label in ("Google로 계속하기", "카카오로 계속하기", "네이버로 계속하기", "비회원으로 계속 상담하기"):
            self.assertIn(label, MEMBER)

    def test_notice_copy_does_not_guess_the_cause(self):
        self.assertIn("로그인이 취소됐어요", MEMBER)
        self.assertNotIn("일시적인 오류로", MEMBER)                    # Codex 시안 검수
        self.assertIn("현재 로그인할 수 없어요", MEMBER)
        self.assertIn("new Set(['identity_revoked', 'member_inactive'])", MEMBER)
        self.assertIn("history.replaceState", MEMBER)                  # login_error 는 주소에서 지운다

    def test_dom_built_without_html_strings(self):
        for src in (MEMBER, JOIN_JS):
            self.assertNotIn("innerHTML", src)
            self.assertNotIn("insertAdjacentHTML", src)
            self.assertNotIn("document.write", src)

    def test_button_sits_outside_nav_for_full_mobile_menus(self):
        self.assertIn("document.querySelector('.topbar')", MEMBER)
        css = (MVP3 / "member.css").read_text(encoding="utf-8")
        self.assertIn("body .topbar:has(>.mb-nav){flex-wrap:wrap", css)


class JoinPage(unittest.TestCase):
    def test_exactly_three_required_consents_no_marketing(self):
        self.assertEqual(sorted(re.findall(r'data-consent="([a-z0-9]+)"', JOIN)), ["age14", "privacy", "terms"])
        self.assertNotIn("marketing", JOIN)
        self.assertNotIn("마케팅", JOIN)
        for label in ("[필수] 이용약관 동의", "[필수] 개인정보 수집·이용 동의", "[필수] 만 14세 이상입니다", "동의하고 가입하기"):
            self.assertIn(label, JOIN)
        self.assertIn('id="mb-submit" class="primary mb-wide" type="submit" disabled', JOIN)   # 셋 다 체크 전엔 꺼짐

    def test_join_matches_server_consent_keys_and_codes(self):
        from api import customer_auth_issuer as ISS
        self.assertEqual(set(ISS.REQUIRED_CONSENTS), {"terms", "privacy", "age14"})
        for code in ("consent_required", "join_expired", "already_joined", "auth_unavailable"):
            self.assertIn(code, JOIN_JS)
        self.assertIn("'/api/auth/join'", JOIN_JS)
        self.assertIn("startsWith('/mvp3/')", JOIN_JS)                # 돌아갈 곳도 고객 화면 안만

    def test_full_text_links_exist(self):
        for name in ("terms.html", "privacy.html"):
            self.assertIn(f'href="{name}"', JOIN)
            self.assertTrue((MVP3 / name).exists())


if __name__ == "__main__":
    unittest.main()
