"""Customer screens must not be served from a stale browser copy.

`/mvp3/` (the address customers open) is a directory URL: Starlette serves its
index.html without a ".html" path, so the extension check alone left it cacheable.
"""
import ast
import pathlib
import unittest

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _no_cache_static():
    tree = ast.parse((ROOT / "api" / "main.py").read_text(encoding="utf8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "NoCacheStatic")
    ns = {}
    # fastapi.staticfiles re-exports Starlette's; import it directly so tests
    # that stub the fastapi module cannot change what is measured here.
    exec("from starlette.staticfiles import StaticFiles\n" + ast.unparse(cls), ns)
    return ns["NoCacheStatic"]


class NoCacheStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = Starlette(routes=[Mount("/", app=_no_cache_static()(directory=ROOT / "mockups", html=True))])
        cls.client = TestClient(app)

    def test_screen_files_and_directory_index_are_not_cached(self):
        for path in ("/mvp3/", "/mvp3/index.html", "/mvp3/app.js", "/mvp3/styles.css", "/mvp1/"):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.headers.get("cache-control"), "no-cache, no-store, must-revalidate")

    def test_images_keep_default_caching(self):
        r = self.client.get("/mvp3/assets/icons/info.svg")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.headers.get("cache-control"))


if __name__ == "__main__":
    unittest.main()
