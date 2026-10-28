"""Isolated unit tests for the media storage adapter (M1).

Validates:
1. Bucket name normalization, validation, and rejection of invalid formats.
2. get_physical_media_bucket behavior when POPCORN_MEDIA_STORAGE_BUCKET is unset, empty, valid, or malformed.
3. Logical bucket identity verification (is_valid_logical_bucket) ensuring DB audit snapshots remain immutable.
4. Product images (api/product_images.py) fetch routing to physical bucket while enforcing logical asset.bucket.
5. PC media (api/pc_media.py) upload, readback, permission checks, and asset dictionary generation.
6. PC video (api/pc_video.py) source read, video upload read-after-write, and file serving routing.
"""
import hashlib
import io
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException

# Safe dummy PostgreSQL DB URL for importing api modules during isolated mock testing (create_engine is lazy and does not connect on import)
os.environ.setdefault("DATABASE_URL", "postgresql://popcorn_app:dummy_test@127.0.0.1:5432/popcorn_pc")

from api.media_storage import (
    LOGICAL_MEDIA_BUCKET,
    STORAGE_ENV_VAR,
    normalize_bucket_name,
    get_physical_media_bucket,
    is_valid_logical_bucket,
)
import api.product_images as prod_img
import api.pc_media as pc_media
import api.pc_video as pc_video
import api.customer_pc_offer as cust_offer


class TestBucketNormalization(unittest.TestCase):
    def test_valid_bucket_names(self):
        self.assertEqual(normalize_bucket_name("popcorn-ai-product-media-045e861b"), "popcorn-ai-product-media-045e861b")
        self.assertEqual(normalize_bucket_name("popcornai-dev-media-990033290003"), "popcornai-dev-media-990033290003")
        self.assertEqual(normalize_bucket_name("gs://popcornai-dev-media-990033290003"), "popcornai-dev-media-990033290003")
        self.assertEqual(normalize_bucket_name("gs://popcornai-dev-media-990033290003/"), "popcornai-dev-media-990033290003")
        self.assertEqual(normalize_bucket_name("  popcorn-dev-123  "), "popcorn-dev-123")

    def test_invalid_bucket_names_raise_value_error(self):
        invalid_inputs = [
            "",
            "   ",
            "gs://",
            "gs:///",
            "INVALID_UPPERCASE",
            "-leading-hyphen",
            "trailing-hyphen-",
            ".leading-dot",
            "trailing-dot.",
            "has space",
            "has..double.dot",
            "has.-dash.dot",
            "has-.dot.dash",
            "a" * 64,  # too long (>63)
            "ab",       # too short (<3)
        ]
        for bad in invalid_inputs:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    normalize_bucket_name(bad)


class TestPhysicalBucketResolution(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.get(STORAGE_ENV_VAR)

    def tearDown(self):
        if self.orig_env is not None:
            os.environ[STORAGE_ENV_VAR] = self.orig_env
        else:
            os.environ.pop(STORAGE_ENV_VAR, None)

    def test_unset_env_returns_logical_default(self):
        os.environ.pop(STORAGE_ENV_VAR, None)
        self.assertEqual(get_physical_media_bucket(), LOGICAL_MEDIA_BUCKET)

    def test_empty_or_whitespace_env_raises_value_error(self):
        os.environ[STORAGE_ENV_VAR] = ""
        with self.assertRaises(ValueError):
            get_physical_media_bucket()
        os.environ[STORAGE_ENV_VAR] = "   "
        with self.assertRaises(ValueError):
            get_physical_media_bucket()

    def test_configured_valid_env_returns_physical_bucket(self):
        os.environ[STORAGE_ENV_VAR] = "gs://popcornai-dev-media-990033290003"
        self.assertEqual(get_physical_media_bucket(), "popcornai-dev-media-990033290003")

        os.environ[STORAGE_ENV_VAR] = "popcorn-ai-dev-media-custom"
        self.assertEqual(get_physical_media_bucket(), "popcorn-ai-dev-media-custom")

    def test_configured_invalid_env_raises_value_error_without_fallback(self):
        os.environ[STORAGE_ENV_VAR] = "invalid bucket name with spaces!"
        with self.assertRaises(ValueError):
            get_physical_media_bucket()


class TestLogicalBucketValidation(unittest.TestCase):
    def test_logical_bucket_identification(self):
        self.assertTrue(is_valid_logical_bucket(LOGICAL_MEDIA_BUCKET))
        self.assertTrue(is_valid_logical_bucket("popcorn-ai-product-media-045e861b"))
        # Physical bucket name MUST NOT pass as logical bucket
        self.assertFalse(is_valid_logical_bucket("popcornai-dev-media-990033290003"))
        self.assertFalse(is_valid_logical_bucket(None))
        self.assertFalse(is_valid_logical_bucket(""))
        self.assertFalse(is_valid_logical_bucket("other-bucket"))


class TestProductImagesRouting(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.get(STORAGE_ENV_VAR)

    def tearDown(self):
        if self.orig_env is not None:
            os.environ[STORAGE_ENV_VAR] = self.orig_env
        else:
            os.environ.pop(STORAGE_ENV_VAR, None)

    def test_image_key_requires_logical_bucket(self):
        asset_valid = {
            "bucket": LOGICAL_MEDIA_BUCKET,
            "detail_key": "products/1001/0123456789abcdef/detail.png"
        }
        self.assertEqual(prod_img.image_key(asset_valid, 1001, "detail"), "products/1001/0123456789abcdef/detail.png")

        # Even if physical bucket is used, asset['bucket'] in DB must be the logical bucket
        asset_polluted = {
            "bucket": "popcornai-dev-media-990033290003",
            "detail_key": "products/1001/0123456789abcdef/detail.png"
        }
        with self.assertRaises(HTTPException) as cm:
            prod_img.image_key(asset_polluted, 1001, "detail")
        self.assertEqual(cm.exception.status_code, 404)

    def test_fetch_routes_to_physical_bucket(self):
        test_bytes = b"fake-detail-png-bytes"
        expected_sha = hashlib.sha256(test_bytes).hexdigest()
        asset = {
            "bucket": LOGICAL_MEDIA_BUCKET,
            "detail_key": "products/1001/0123456789abcdef/detail.png",
            "detail_sha256": expected_sha
        }

        # 1. Unset env -> physical bucket is default
        os.environ.pop(STORAGE_ENV_VAR, None)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [test_bytes]
        mock_session = MagicMock()
        mock_session.get.return_value.__enter__.return_value = mock_resp

        with patch.object(prod_img, "_session", return_value=mock_session):
            data = prod_img._fetch(asset, asset["detail_key"], "detail")
            self.assertEqual(data, test_bytes)
            requested_url = mock_session.get.call_args[0][0]
            self.assertIn(f"/b/{LOGICAL_MEDIA_BUCKET}/o/", requested_url)

        # 2. Configured env -> physical bucket is new bucket
        os.environ[STORAGE_ENV_VAR] = "gs://popcornai-dev-media-990033290003"
        with patch.object(prod_img, "_session", return_value=mock_session):
            data = prod_img._fetch(asset, asset["detail_key"], "detail")
            self.assertEqual(data, test_bytes)
            requested_url = mock_session.get.call_args[0][0]
            self.assertIn("/b/popcornai-dev-media-990033290003/o/", requested_url)


class TestPCMediaRouting(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.get(STORAGE_ENV_VAR)

    def tearDown(self):
        if self.orig_env is not None:
            os.environ[STORAGE_ENV_VAR] = self.orig_env
        else:
            os.environ.pop(STORAGE_ENV_VAR, None)

    def test_cloud_ready_probes_physical_bucket(self):
        os.environ[STORAGE_ENV_VAR] = "popcornai-dev-media-990033290003"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"permissions": ["storage.objects.create", "storage.objects.get"]}
        mock_session = MagicMock()
        mock_session.credentials = MagicMock()  # not ComputeCredentials
        mock_session.get.return_value = mock_resp

        with patch.object(pc_media, "cloud_session") as mock_cs:
            mock_cs.return_value.__enter__.return_value = mock_session
            self.assertTrue(pc_media._cloud_ready(0))
            requested_url = mock_session.get.call_args[0][0]
            self.assertIn("/b/popcornai-dev-media-990033290003/iam/testPermissions", requested_url)

    def test_upload_writes_to_physical_bucket_and_preserves_logical_asset(self):
        os.environ[STORAGE_ENV_VAR] = "gs://popcornai-dev-media-990033290003"
        job = {"job_id": str(uuid4())}
        raw_bytes = b"fake-pc-representative-png"

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_session = MagicMock()
        mock_session.post.return_value = mock_post_resp

        with patch.object(pc_media, "cloud_session") as mock_cs:
            mock_cs.return_value.__enter__.return_value = mock_session
            asset = pc_media.upload(job, raw_bytes)

            # Check network upload target
            upload_url = mock_session.post.call_args[0][0]
            self.assertIn("/b/popcornai-dev-media-990033290003/o", upload_url)

            # Crucial check: returned asset for DB insertion must specify LOGICAL_MEDIA_BUCKET
            self.assertEqual(asset["bucket"], LOGICAL_MEDIA_BUCKET)
            self.assertEqual(asset["sha256"], hashlib.sha256(raw_bytes).hexdigest())

    def test_image_fetches_from_physical_bucket_and_validates_logical_bucket(self):
        os.environ[STORAGE_ENV_VAR] = "popcornai-dev-media-990033290003"
        job_id = uuid4()
        raw_bytes = b"sample-pc-image"
        expected_sha = hashlib.sha256(raw_bytes).hexdigest()

        # 1. Reject invalid logical bucket in asset
        with patch.object(pc_media.engine, "connect") as mock_conn:
            mock_conn.return_value.__enter__.return_value.execute.return_value.scalar.return_value = {
                "bucket": "polluted-bucket-name",
                "key": f"pc-configurations/{job_id}/representative.png",
                "sha256": expected_sha
            }
            with self.assertRaises(HTTPException) as cm:
                pc_media.image("ident1", job_id)
            self.assertEqual(cm.exception.status_code, 404)

        # 2. Allow valid logical bucket and route fetch to physical bucket
        mock_resp = MagicMock()
        mock_resp.content = raw_bytes
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with patch.object(pc_media.engine, "connect") as mock_conn:
            mock_conn.return_value.__enter__.return_value.execute.return_value.scalar.return_value = {
                "bucket": LOGICAL_MEDIA_BUCKET,
                "key": f"pc-configurations/{job_id}/representative.png",
                "sha256": expected_sha
            }
            with patch.object(pc_media, "cloud_session") as mock_cs:
                mock_cs.return_value.__enter__.return_value = mock_session
                resp = pc_media.image("ident1", job_id)
                self.assertEqual(resp.body, raw_bytes)
                fetch_url = mock_session.get.call_args[0][0]
                self.assertIn("/b/popcornai-dev-media-990033290003/o/", fetch_url)


class TestPCVideoRouting(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.get(STORAGE_ENV_VAR)

    def tearDown(self):
        if self.orig_env is not None:
            os.environ[STORAGE_ENV_VAR] = self.orig_env
        else:
            os.environ.pop(STORAGE_ENV_VAR, None)

    def test_read_source_fetches_from_physical_bucket(self):
        os.environ[STORAGE_ENV_VAR] = "gs://popcornai-dev-media-990033290003"
        job = str(uuid4())
        raw_bytes = b"fake-video-source-image"
        asset = {
            "bucket": LOGICAL_MEDIA_BUCKET,
            "key": f"pc-configurations/{job}/representative.png",
            "sha256": hashlib.sha256(raw_bytes).hexdigest()
        }

        mock_resp = MagicMock()
        mock_resp.content = raw_bytes
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with patch.object(pc_video.media, "cloud_session") as mock_cs:
            mock_cs.return_value.__enter__.return_value = mock_session
            data = pc_video.read_source(asset, job)
            self.assertEqual(data, raw_bytes)
            fetch_url = mock_session.get.call_args[0][0]
            self.assertIn("/b/popcornai-dev-media-990033290003/o/", fetch_url)

    def test_upload_file_writes_and_verifies_physical_bucket(self):
        os.environ[STORAGE_ENV_VAR] = "popcornai-dev-media-990033290003"
        job = str(uuid4())
        raw_video = b"fake-mp4-stream-data"
        expected_sha = hashlib.sha256(raw_video).hexdigest()

        with tempfile.TemporaryDirectory() as td:
            dummy_video = os.path.join(td, "intro.mp4")
            with open(dummy_video, "wb") as f:
                f.write(raw_video)

            mock_post_resp = MagicMock()
            mock_post_resp.status_code = 200
            mock_get_resp = MagicMock()
            mock_get_resp.content = raw_video
            mock_session = MagicMock()
            mock_session.post.return_value = mock_post_resp
            mock_session.get.return_value = mock_get_resp

            with patch.object(pc_video.media, "cloud_session") as mock_cs:
                mock_cs.return_value.__enter__.return_value = mock_session
                from pathlib import Path
                res = pc_video.upload_file(job, "intro.mp4", Path(dummy_video), "video/mp4")

                # Check network endpoints
                upload_url = mock_session.post.call_args[0][0]
                self.assertIn("/b/popcornai-dev-media-990033290003/o", upload_url)
                verify_url = mock_session.get.call_args[0][0]
                self.assertIn("/b/popcornai-dev-media-990033290003/o/", verify_url)

                # Check logical audit bucket preservation
                self.assertEqual(res["bucket"], LOGICAL_MEDIA_BUCKET)
                self.assertEqual(res["sha256"], expected_sha)
                self.assertEqual(res["size"], len(raw_video))


class TestCustomerPCOfferRouting(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.get(STORAGE_ENV_VAR)
        with cust_offer._card_cache_lock:
            cust_offer._card_cache.clear()
            cust_offer._card_cache_size = 0

    def tearDown(self):
        with cust_offer._card_cache_lock:
            cust_offer._card_cache.clear()
            cust_offer._card_cache_size = 0
        if self.orig_env is not None:
            os.environ[STORAGE_ENV_VAR] = self.orig_env
        else:
            os.environ.pop(STORAGE_ENV_VAR, None)

    def test_representative_png_fetches_from_physical_bucket(self):
        os.environ[STORAGE_ENV_VAR] = "gs://popcornai-dev-media-990033290003"
        job_id = str(uuid4())
        raw_bytes = b"fake-customer-pc-png"
        asset = {
            "bucket": LOGICAL_MEDIA_BUCKET,
            "key": f"pc-configurations/{job_id}/representative.png",
            "sha256": hashlib.sha256(raw_bytes).hexdigest()
        }
        mock_resp = MagicMock()
        mock_resp.content = raw_bytes
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with patch.object(pc_media, "cloud_session") as mock_cs:
            mock_cs.return_value.__enter__.return_value = mock_session
            res = cust_offer._representative_png(asset, job_id)
            self.assertEqual(res, raw_bytes)
            req_url = mock_session.get.call_args[0][0]
            self.assertIn("/b/popcornai-dev-media-990033290003/o/", req_url)

    def test_representative_png_rejects_logical_bucket_mismatch(self):
        job_id = str(uuid4())
        asset = {
            "bucket": "polluted-bucket",
            "key": f"pc-configurations/{job_id}/representative.png",
            "sha256": "abc"
        }
        with self.assertRaises(HTTPException) as cm:
            cust_offer._representative_png(asset, job_id)
        self.assertEqual(cm.exception.status_code, 404)

    def test_read_representative_image_cold_cache_regression(self):
        os.environ[STORAGE_ENV_VAR] = "popcornai-dev-media-990033290003"
        job_id = str(uuid4())
        tiny_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
            b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        sha = hashlib.sha256(tiny_png).hexdigest()
        mock_job = {
            "job_id": job_id,
            "asset": {
                "bucket": LOGICAL_MEDIA_BUCKET,
                "key": f"pc-configurations/{job_id}/representative.png",
                "sha256": sha
            }
        }
        mock_item = {"name": "Test PC"}
        mock_request = MagicMock()
        mock_request.headers.get.return_value = None

        mock_resp = MagicMock()
        mock_resp.content = tiny_png
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with patch.object(cust_offer, "_read", return_value=(mock_item, mock_job)), \
             patch.object(pc_media, "cloud_session") as mock_cs:
            mock_cs.return_value.__enter__.return_value = mock_session

            # Cold cache: size='card' calls _representative_png and populates _card_cache
            self.assertNotIn(sha, cust_offer._card_cache)
            resp = cust_offer.read_representative_image(1001, mock_request, size="card")
            self.assertEqual(resp.media_type, "image/webp")
            self.assertIn(sha, cust_offer._card_cache)
            self.assertIn("/b/popcornai-dev-media-990033290003/o/", mock_session.get.call_args[0][0])

            # Warm cache: does not call network again
            mock_session.get.reset_mock()
            resp2 = cust_offer.read_representative_image(1001, mock_request, size="card")
            self.assertEqual(resp2.media_type, "image/webp")
            mock_session.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
