"""Serve the committed builder under its customer URL without importing api.main.

These checks cover the built files and Starlette's directory/404 behaviour, not
JavaScript execution, a live API, inventory, or deployment. Run with unittest or
pytest; neither the application lifespan nor a database connection is needed.
"""

from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urljoin, urlsplit

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
MOCKUPS = ROOT / "mockups"
BASE = "/mvp4/pc-builder/"
BUILD = MOCKUPS / "mvp4" / "pc-builder"
# 사이트 공용 스크립트(빌더 묶음 밖) -- 운영 미리보기 로그인 만료 안내(2026-10-29). 묶음 자산 검사에서 빼고
# 공용 경로에서 실제로 내려오는지만 따로 본다.
SHARED_SCRIPTS = ("/mvp4/assets/js/session-expired.js",)


class _EntryAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.styles = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs["src"])
        if tag == "link" and "stylesheet" in attrs.get("rel", "").split():
            self.styles.append(attrs["href"])


class PCBuilderStaticIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Deliberately mount only static files: api.main has unrelated runtime
        # dependencies and must not be imported to validate a built frontend.
        app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        app.mount("/", StaticFiles(directory=MOCKUPS, html=True))
        cls.client = TestClient(app)
        cls.addClassCleanup(cls.client.close)
        cls.index_bytes = (BUILD / "index.html").read_bytes()
        cls.assets = _EntryAssets()
        cls.assets.feed(cls.index_bytes.decode("utf-8"))

    def asset(self, reference, relative_to=BASE):
        """Resolve a browser asset URL and verify a real, local built response."""
        parsed = urlsplit(urljoin("http://testserver" + relative_to, reference))
        self.assertEqual(parsed.netloc, "testserver", reference)
        self.assertTrue(parsed.path.startswith(BASE), reference)
        disk_path = (MOCKUPS / unquote(parsed.path).lstrip("/")).resolve()
        self.assertTrue(disk_path.is_relative_to(BUILD.resolve()), reference)
        self.assertTrue(disk_path.is_file(), reference)
        response = self.client.get(parsed.path, follow_redirects=False)
        self.assertEqual(response.status_code, 200, reference)
        self.assertNotIn("text/html", response.headers.get("content-type", ""), reference)
        self.assertEqual(response.content, disk_path.read_bytes(), reference)
        self.assertTrue(response.content, reference)
        return response

    def test_directory_redirect_and_both_direct_entries_serve_built_index(self):
        redirect = self.client.get(BASE.rstrip("/"), follow_redirects=False)
        self.assertEqual(redirect.status_code, 307)
        self.assertEqual(urlsplit(redirect.headers["location"]).path, BASE)
        for path in (BASE.rstrip("/"), BASE, BASE + "index.html"):
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=True)
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/html", response.headers["content-type"])
                self.assertEqual(response.content, self.index_bytes)

    def test_html_script_and_stylesheet_urls_load_under_builder_subpath(self):
        self.assertTrue(self.assets.scripts, "Built HTML has no script entry")
        self.assertTrue(self.assets.styles, "Built HTML has no stylesheet")
        for script in self.assets.scripts:
            with self.subTest(script=script):
                shared = urlsplit(script).path
                if shared in SHARED_SCRIPTS:
                    response = self.client.get(shared, follow_redirects=False)
                    self.assertEqual(response.status_code, 200, script)
                    self.assertIn("javascript", response.headers["content-type"])
                    continue
                response = self.asset(script)
                self.assertIn("javascript", response.headers["content-type"])
        for style in self.assets.styles:
            with self.subTest(style=style):
                response = self.asset(style)
                self.assertIn("text/css", response.headers["content-type"])

    def test_catalog_and_all_32_product_images_are_served(self):
        response = self.asset(BASE + "data/catalog.json")
        self.assertIn("application/json", response.headers["content-type"])
        parts = response.json()["parts"]
        self.assertEqual(len(parts), 32)
        self.assertEqual(len({part["id"] for part in parts}), 32)
        images = {part["image"] for part in parts}
        self.assertEqual(len(images), 32)
        for image in sorted(images):
            # The catalog records public asset keys. The frontend's separate
            # subpath/browser tests cover their runtime normalization.
            path = image if image.startswith(BASE) else BASE + image.lstrip("/")
            with self.subTest(image=image):
                response = self.asset(path)
                self.assertTrue(response.headers["content-type"].startswith("image/"))

    def test_fonts_referenced_by_built_stylesheets_load(self):
        fonts = set()
        for style in self.assets.styles:
            css = self.asset(style).text
            style_path = urlsplit(urljoin("http://testserver" + BASE, style)).path
            for _, reference in re.findall(r"url\(\s*(['\"]?)(.*?)\1\s*\)", css):
                if urlsplit(reference).path.lower().endswith((".woff", ".woff2")):
                    fonts.add((reference, style_path))
        self.assertTrue(fonts, "Built CSS has no local webfont reference")
        for reference, style_path in sorted(fonts):
            with self.subTest(font=reference):
                response = self.asset(reference, relative_to=style_path)
                self.assertIn(response.content[:4], (b"wOFF", b"wOF2"))

    def test_missing_routes_and_assets_return_404_without_index_fallback(self):
        for path in (
            "does-not-exist",
            "assets/does-not-exist.js",
            "assets/does-not-exist.css",
            "assets/parts/does-not-exist.jpg",
            "data/does-not-exist.json",
            "assets/brand/does-not-exist.woff2",
        ):
            with self.subTest(path=path):
                response = self.client.get(BASE + path, follow_redirects=False)
                self.assertEqual(response.status_code, 404)
                self.assertNotEqual(response.content, self.index_bytes)
                self.assertNotIn("text/html", response.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
