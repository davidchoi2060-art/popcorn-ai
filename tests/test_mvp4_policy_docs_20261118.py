"""이용약관·개인정보처리방침 본문(시행 2026-11-23) -- 2026-11-18 사장님 확정값과 실제 동작의 일치를 지킨다."""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MVP4 = ROOT / "mockups" / "mvp4"
JS = MVP4 / "assets" / "js" / "policy-docs.js"


def load_docs():
    script = ("global.window={PAI:{}};require(%s);process.stdout.write(JSON.stringify(window.PAI.policyDocs));"
              % json.dumps(str(JS)))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


def text_of(doc):
    parts = [doc.get("title", ""), doc.get("meta", "")] + [b.get("text", "") for b in doc.get("intro", [])]
    for s in doc["sections"]:
        parts.append(s["title"])
        for b in s["blocks"]:
            parts.append(b.get("text", ""))
            parts += [i["text"] for i in b.get("items", [])]
            parts += [c for r in b.get("rows", []) for c in r]
    return "\n".join(parts)


class PolicyDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = load_docs()
        cls.terms, cls.privacy = text_of(cls.docs["terms"]), text_of(cls.docs["privacy"])

    def test_both_documents_render_with_unique_section_ids(self):
        for key in ("terms", "privacy"):
            ids = [s["id"] for s in self.docs[key]["sections"]]
            self.assertTrue(ids and len(ids) == len(set(ids)), key)

    def test_no_placeholder_or_draft_marker_left(self):
        for body in (self.terms, self.privacy, JS.read_text(encoding="utf-8")):
            self.assertNotRegex(body, r"[【】]|초안|확인 필요|미정")

    def test_confirmed_values(self):
        for body in (self.terms, self.privacy):
            self.assertIn("2026-11-23", body)
            self.assertIn("02)1644-0249", body)
            self.assertIn("leon2030@kakao.com", body)
        self.assertIn("서울서부지방법원", self.terms)
        self.assertIn("협력사", self.terms)
        self.assertIn("7일 전부터", self.terms)
        self.assertIn("30일 전부터", self.terms)
        self.assertIn("로그인할 때 화면으로 안내", self.terms)
        self.assertNotIn("통신판매업", self.terms + self.privacy)

    def test_privacy_matches_actual_behaviour(self):
        from api import customer_auth_issuer as ISS
        from api import mvp3_contact
        self.assertEqual(ISS.CONSENT_VERSION, "2026-11-23")
        self.assertEqual(ISS.SESSION_DAYS, 14)
        self.assertIn("%d일" % ISS.SESSION_DAYS, self.privacy)
        self.assertEqual(mvp3_contact.KEEP_DAYS, 180)
        self.assertIn("180일", self.privacy)
        for name in ("pc_vid", "popcorn_member_session", "popcorn_oauth_state", "popcorn_join_pending"):
            self.assertIn(name, self.privacy)
        self.assertIn("OpenAI", self.privacy)
        self.assertIn("Anthropic", self.privacy)
        self.assertIn("이메일을 회원 정보로 받지 않", self.privacy)       # #466
        self.assertIn("보호자의 동의", self.privacy)

    def test_pages_load_policy_docs_after_info_pages(self):
        for page in ("terms.html", "privacy.html"):
            html = (MVP4 / page).read_text(encoding="utf-8")
            self.assertLess(html.index("assets/js/info-pages.js"), html.index("assets/js/policy-docs.js"), page)

    def test_company_phone_is_a_call_link(self):
        js = (MVP4 / "assets" / "js" / "info-pages.js").read_text(encoding="utf-8")
        self.assertIn('href="tel:0216440249"', js)


if __name__ == "__main__":
    unittest.main()
