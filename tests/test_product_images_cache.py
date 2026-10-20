"""부품 표시 사진 라우트(api/product_images) — 재검증·바이트 캐시 (2026-10-20 「같은 부품 사진을 다시 받지 않게」).

지키는 것:
  · 공개 판정(product_explanations 조회)은 캐시와 무관하게 매 요청 한다 — 사진이 내려가면 캐시에 있어도 404.
  · detail 재검증(If-None-Match)은 기록된 해시로 바로 304 를 준다(저장소를 읽지 않는다). ETag 값은 전과 같다.
  · 같은 키는 저장소에서 한 번만 읽는다. 사진을 바꾸면 키(버전 폴더)가 바뀌어 새로 읽는다.
DB·저장소·네트워크 없음(MOCK).
"""
import hashlib
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import product_images as m

PNG = b"\x89PNG\r\n\x1a\nfake-detail"
WEBP = b"RIFF\x00\x00\x00\x00WEBPfake-thumb"
CODE = 4321


def asset(version="0123456789abcdef", data=PNG):
    return {"bucket": m.MEDIA_BUCKET, "detail_key": f"products/{CODE}/{version}/detail.png",
            "thumbnail_key": f"products/{CODE}/{version}/thumb.webp", "detail_sha256": hashlib.sha256(data).hexdigest()}


class Conn:
    def __init__(self, box): self.box = box
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *_a, **_k): self.box["queries"] += 1; return self
    def scalar(self): return self.box["asset"]


class Engine:
    def __init__(self, box): self.box = box
    def connect(self): return Conn(self.box)


class ProductImageCacheTest(unittest.TestCase):
    def setUp(self):
        m._bytes_cache.clear(); m._bytes_cache_size = 0
        self.box = {"asset": asset(), "queries": 0}
        self.fetched = []
        def fetch(a, key, variant):
            self.fetched.append(key)
            return PNG if variant == "detail" else WEBP
        app = FastAPI(); app.include_router(m.router)
        self.client = TestClient(app)
        self.patches = [patch.object(m, "engine", Engine(self.box)), patch.object(m, "_fetch", side_effect=fetch)]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in self.patches: p.stop()

    def test_detail_etag_is_unchanged_and_revalidates_without_storage(self):
        r = self.client.get(f"/api/product-images/{CODE}/detail")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, PNG)
        self.assertEqual(r.headers["etag"], '"' + hashlib.sha256(PNG).hexdigest() + '"')
        self.assertEqual(r.headers["cache-control"], "public, max-age=3600")
        m._bytes_cache.clear(); self.fetched.clear()
        r2 = self.client.get(f"/api/product-images/{CODE}/detail", headers={"If-None-Match": r.headers["etag"]})
        self.assertEqual(r2.status_code, 304)
        self.assertEqual(self.fetched, [])  # 저장소를 읽지 않았다
        self.assertEqual(self.box["queries"], 2)  # 공개 판정은 두 번 다 했다

    def test_same_key_reads_storage_once(self):
        for _ in range(3):
            self.assertEqual(self.client.get(f"/api/product-images/{CODE}/thumbnail").content, WEBP)
        self.assertEqual(self.fetched, [f"products/{CODE}/0123456789abcdef/thumb.webp"])

    def test_withdrawn_photo_is_404_even_when_cached(self):
        self.assertEqual(self.client.get(f"/api/product-images/{CODE}/detail").status_code, 200)
        self.box["asset"] = None
        self.assertEqual(self.client.get(f"/api/product-images/{CODE}/detail").status_code, 404)

    def test_replaced_photo_has_new_key_and_new_etag(self):
        first = self.client.get(f"/api/product-images/{CODE}/thumbnail").headers["etag"]
        self.box["asset"] = asset("fedcba9876543210", PNG + b"v2")
        r = self.client.get(f"/api/product-images/{CODE}/thumbnail", headers={"If-None-Match": first})
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.headers["etag"], first)
        self.assertEqual(len(self.fetched), 2)

    def test_thumbnail_and_detail_etags_differ(self):
        d = self.client.get(f"/api/product-images/{CODE}/detail").headers["etag"]
        t = self.client.get(f"/api/product-images/{CODE}/thumbnail").headers["etag"]
        self.assertNotEqual(d, t)

    def test_asset_without_recorded_hash_falls_back_to_content_hash(self):
        a = asset(); a.pop("detail_sha256"); self.box["asset"] = a
        r = self.client.get(f"/api/product-images/{CODE}/thumbnail")
        self.assertEqual(r.headers["etag"], '"' + hashlib.sha256(WEBP).hexdigest() + '"')
        self.assertEqual(self.client.get(f"/api/product-images/{CODE}/thumbnail", headers={"If-None-Match": r.headers["etag"]}).status_code, 304)

    def test_foreign_key_is_rejected_before_cache(self):
        a = asset(); a["thumbnail_key"] = "products/9999/0123456789abcdef/thumb.webp"; self.box["asset"] = a
        self.assertEqual(self.client.get(f"/api/product-images/{CODE}/thumbnail").status_code, 404)
        self.assertEqual(self.fetched, [])

    def test_cache_is_bounded(self):
        with patch.object(m, "BYTES_CACHE_LIMIT", 40):
            m._remember("a", b"x" * 9); m._remember("b", b"y" * 9); m._remember("c", b"z" * 9)
            m._remember("d", b"w" * 9); m._remember("e", b"v" * 9)
            self.assertLessEqual(m._bytes_cache_size, 40)
            self.assertNotIn("a", m._bytes_cache)
            m._remember("big", b"q" * 11)  # 한도의 1/4 넘는 것은 담지 않는다
            self.assertNotIn("big", m._bytes_cache)


if __name__ == "__main__":
    unittest.main()
