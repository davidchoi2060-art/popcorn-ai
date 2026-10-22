"""/mvp4 오픈 전 기본 (2026-10-22 사장님 「진행해」 -- 외부 점검표를 실사이트로 대조한 뒤 맞는 지적만).

  · 공유 미리보기: 공개 화면마다 og:title·og:description·og:image(1200x630) · twitter:card. 결과·검수·이동 화면은 noindex.
  · 하단 사업자 표기: 상호·대표·사업자등록번호·주소·대표번호·개인정보보호책임자(회사정보 확정값 한 곳 = core.js).
  · /robots.txt · /sitemap.xml: 개발 서버(dev·admin 주소, 스위치 없음)는 전부 막는다. 운영에서 SITE_INDEXING=on 일 때만 연다.
"""
import pathlib
import re
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import site_meta

M = pathlib.Path(__file__).resolve().parents[1] / "mockups" / "mvp4"
PUBLIC = ("index", "ai-packages", "ai-company", "ai-service", "supercomputers", "supercomputer", "supercomputer-inquiry",
          "peripherals", "support", "company", "terms", "privacy", "purchase-support", "credits")
NOINDEX = ("ai-detail", "ai-consult", "ai-result", "bridge", "review-flows", "review-ai-consult")


class ShareTags(unittest.TestCase):
    def test_public_pages_have_share_tags(self):
        for name in PUBLIC:
            s = (M / f"{name}.html").read_text(encoding="utf-8")
            for tag in ('property="og:title"', 'property="og:description"', 'property="og:image"',
                        'name="twitter:card" content="summary_large_image"', 'name="description"'):
                self.assertEqual(s.count(tag), 1, (name, tag))
            self.assertIn("https://www.popcornai.co.kr/mvp4/assets/images/og/og-default.jpg", s)
            self.assertNotIn('content="noindex"', s, name)
            self.assertNotEqual(re.search(r"<title>([^<]*)</title>", s).group(1), "팝콘AI", name)

    def test_og_image_is_1200x630(self):
        from PIL import Image
        self.assertEqual(Image.open(M / "assets/images/og/og-default.jpg").size, (1200, 630))
        self.assertTrue((M / "assets/images/og/og-default.provenance.json").exists())

    def test_result_and_review_pages_noindex(self):
        for name in NOINDEX:
            s = (M / f"{name}.html").read_text(encoding="utf-8")
            self.assertIn('name="robots" content="noindex', s, name)
            self.assertNotIn('property="og:', s, name)


class FooterBusiness(unittest.TestCase):
    def test_footer_shows_confirmed_company_values_from_one_place(self):
        core = (M / "assets/js/core.js").read_text(encoding="utf-8")
        info = (M / "assets/js/info-pages.js").read_text(encoding="utf-8")
        for v in ("주식회사 팝콘컴퓨터", "이미숙", "794-81-00671", "서울특별시 용산구 원효로 188, 5층", "02)1644-0249"):
            self.assertIn(v, core)
        for v in ("주식회사 팝콘컴퓨터", "794-81-00671", "원효로 188"):
            self.assertNotIn(v, info)                     # 표 값은 core.js 한 곳(회사정보 화면은 P.COMPANY 를 읽는다)
        self.assertIn("var COMPANY = P.COMPANY;", info)
        self.assertIn("footerBusiness()", core)

        self.assertNotIn("통신판매업", core.split("PAI.COMPANY = {", 1)[1].split("};", 1)[0])   # 확정값 없음 -- 지어내지 않는다

    def test_pages_load_new_core_version(self):
        for p in M.glob("*.html"):
            s = p.read_text(encoding="utf-8")
            if "assets/js/core.js" in s:
                self.assertIn("core.js?v=20261022-biz2", s, p.name)


class Robots(unittest.TestCase):
    def client(self):
        app = FastAPI()
        app.include_router(site_meta.router)
        return TestClient(app)

    def test_closed_by_default_and_on_dev_hosts(self):
        c = self.client()
        for host in ("dev.popcornai.co.kr", "www.popcornai.co.kr", "admin.popcornai.co.kr"):
            r = c.get("/robots.txt", headers={"host": host})
            self.assertEqual(r.text, "User-agent: *\nDisallow: /\n", host)
            self.assertEqual(c.get("/sitemap.xml", headers={"host": host}).status_code, 404)

    def test_open_only_with_switch_on_public_host(self):
        import os
        from unittest import mock
        c = self.client()
        with mock.patch.dict(os.environ, {"SITE_INDEXING": "on"}):
            self.assertIn("Disallow: /\n", c.get("/robots.txt", headers={"host": "dev.popcornai.co.kr"}).text)
            r = c.get("/robots.txt", headers={"host": "www.popcornai.co.kr"})
            self.assertIn("Allow: /mvp4/", r.text)
            self.assertIn("Disallow: /admin2/", r.text)
            self.assertIn("Sitemap: https://www.popcornai.co.kr/sitemap.xml", r.text)
            x = c.get("/sitemap.xml", headers={"host": "www.popcornai.co.kr"}).text
            self.assertIn("<loc>https://www.popcornai.co.kr/mvp4/terms.html</loc>", x)
            self.assertNotIn("review-", x)
            self.assertNotIn("bridge", x)


if __name__ == "__main__":
    unittest.main()


class ScriptsParse(unittest.TestCase):
    """2026-10-22 사고: core.js 문자열 안의 \n 이 실제 줄바꿈으로 들어가 /mvp4 전체가 흰 화면이 됐다(글자만 보는 검사는 못 잡았다).
    mvp4 스크립트 전부를 node --check 로 문법 검사한다(node 가 없는 환경은 건너뛴다)."""

    def test_all_mvp4_scripts_parse(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node 없음")
        bad = []
        for js in sorted((M / "assets" / "js").glob("*.js")):
            r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
            if r.returncode:
                bad.append((js.name, (r.stderr or "").strip().splitlines()[:3]))
        self.assertEqual(bad, [])
