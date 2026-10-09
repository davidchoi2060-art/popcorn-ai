"""고객 완제품 공개 구성·대표 사진 라우트 (api/customer_pc_offer).

공개 판정 자체(read_customer_sold_offer · source reader)는 각자의 검사가 지킨다.
여기서는 그 판정을 «그대로 따르는지»와 이 모듈이 더하는 부품 사진·대표 사진만 본다.
DB·저장소·네트워크 없음(SQL·세션 MOCK).
"""
import hashlib
import unittest
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import customer_pc_offer as m
from api import part_photo_approval as photo_approval
from tools import approve_pc_publication_bulk as BULK

JOB = UUID(int=7)
PNG = b"\x89PNG\r\n\x1a\nfake"
ASSET = {"bucket": m.MEDIA_BUCKET, "key": f"pc-configurations/{JOB}/representative.png",
         "sha256": hashlib.sha256(PNG).hexdigest(), "notice": m.pc_media.NOTICE}
OFFER = {"configuration_id": "P10", "revision": 3, "offer_id": "P99413", "product_code": 99413,
         "description": {"title": "t", "intro": None, "scene": None, "benefits": [], "checks": [], "faq": []},
         "parts": [{"ordinal": 0, "slot": "CPU", "quantity": 1, "pseudo": False, "name": "cpu",
                    "description": "d", "specs": []},
                   {"ordinal": 1, "slot": "ETC", "quantity": 1, "pseudo": True, "name": None,
                    "description": None, "specs": []}],
         "price": {"state": "unknown", "amount": None}, "stock": {"state": "unknown"},
         "compatibility": {"document_state": "unknown"}, "customer_conditions": {},
         "photo": {"state": "unresolved", "url": None}}


class Rows:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None
    def __iter__(self): return iter(self.rows)


class Conn:
    def __init__(self, job):
        self.job, self.sql, self.options, self.began, self.rolled_back = job, [], {}, False, False

    def execution_options(self, **kw):
        self.options.update(kw); return self

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def begin(self): self.began = True
    def rollback(self): self.rolled_back = True

    def execute(self, statement, params=None):
        q = str(statement); self.sql.append(q)
        if "FROM pc_configuration_parts" in q:
            return Rows([{"ordinal": 0, "explanation_code": 4321}])
        if "FROM pc_media_jobs" in q:
            return Rows([deepcopy(self.job)] if self.job else [])
        return Rows([])


class Engine:
    def __init__(self, conn): self.conn = conn
    def connect(self): return self.conn


class Session:
    def __init__(self, body): self.body = body
    def get(self, url, timeout):
        self.url = url
        return type("R", (), {"content": self.body, "raise_for_status": lambda s: None})()


class CustomerPcOfferTest(unittest.TestCase):
    def setUp(self):
        self.job = {"job_id": JOB, "visual_basis": "v" * 64, "asset": deepcopy(ASSET)}
        self.conn = Conn(self.job)
        self.result = {"status": 200, "data": deepcopy(OFFER)}
        self.visual = "v" * 64
        self.body = PNG
        session = lambda: self._session()  # noqa: E731
        self.patches = [
            patch.object(m, "engine", Engine(self.conn)),
            patch.object(m, "read_customer_sold_offer", side_effect=lambda *a, **k: deepcopy(self.result)),
            patch.object(m.pc_media, "snapshot", side_effect=lambda c, i: {"visual_basis": self.visual}),
            patch.object(m.pc_media, "cloud_session", session),
        ]
        self.mocks = [p.start() for p in self.patches]
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        app = FastAPI(); app.include_router(m.router)
        self.client = TestClient(app)

    @contextmanager
    def _session(self):
        yield Session(self.body)

    def get(self, path):
        return self.client.get("/api/customer/pc-offers" + path)

    def image(self, code=99413, **headers):
        return self.client.get(f"/api/customer/products/{code}/representative-image", headers=headers)

    def test_response_is_ui_item_shape(self):
        r = self.get("/99413")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["cache-control"], "no-store")
        body = r.json()
        self.assertEqual(set(body), {"ok", "product_code", "photo", "public_configuration"})
        self.assertEqual(body["product_code"], 99413)
        self.assertEqual(body["photo"], {"state": "available", "kind": "ai_assembly_example",
                                         "url": "/api/customer/products/99413/representative-image",
                                         "notice": "AI 조립 예시 이미지 · 실제 출고 외형과 다를 수 있음"})
        config = body["public_configuration"]
        # UI 검증기는 공개 BOM 안의 photo 가 정확히 unresolved/null 일 때만 받는다
        self.assertEqual(config["photo"], {"state": "unresolved", "url": None})
        self.assertEqual((config["product_code"], config["offer_id"]), (99413, "P99413"))
        self.assertEqual(config["parts"][0]["photo"], {"state": "approved", "url": "/api/product-images/4321/detail"})
        self.assertEqual(config["parts"][1]["photo"], {"state": "none", "url": None})
        # 가격은 이 경로가 지어내지 않는다
        self.assertEqual(config["price"]["state"], "unknown")
        self.assertIsNone(config["price"]["amount"])

    def test_snapshot_is_repeatable_read_read_only_and_rolled_back(self):
        self.get("/99413")
        self.assertEqual(self.conn.options, {"isolation_level": "REPEATABLE READ"})
        self.assertTrue(self.conn.began)
        self.assertIn("SET TRANSACTION READ ONLY", self.conn.sql[0])
        self.assertTrue(self.conn.rolled_back)
        self.assertFalse(any(q.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in self.conn.sql))

    def test_gate_is_passed_through_unchanged(self):
        self.get("/99413")
        args, kwargs = self.mocks[1].call_args
        self.assertIs(args[0], self.conn)
        self.assertEqual(args[1], 99413)
        self.assertTrue(callable(kwargs["source_reader"]))

    def test_not_public_is_one_indistinguishable_404(self):
        self.result = {"status": 404, "error": "not_public"}
        r = self.get("/99413")
        self.assertEqual((r.status_code, r.json()), (404, {"detail": {"error": "not_public"}}))
        self.assertEqual(r.headers["cache-control"], "no-store")
        # 공개 아니면 부품·대표 사진 조회도 하지 않는다
        self.assertFalse(any("pc_media_jobs" in q or "pc_configuration_parts" in q for q in self.conn.sql))

    def test_invalid_code(self):
        self.assertEqual(self.get("/0").status_code, 422)
        self.assertEqual(self.get("/abc").status_code, 422)
        self.assertEqual(self.image(0).status_code, 422)
        self.mocks[1].assert_not_called()

    def test_stale_missing_or_foreign_notice_photo_is_unavailable(self):
        unavailable = {"state": "unavailable", "url": None}
        self.visual = "w" * 64
        body = self.get("/99413").json()
        self.assertEqual(body["photo"], unavailable)
        self.assertEqual(body["public_configuration"]["photo"], {"state": "unresolved", "url": None})
        self.visual = "v" * 64
        self.conn.job = dict(self.job, asset=dict(ASSET, notice="다른 고지"))
        self.assertEqual(self.get("/99413").json()["photo"], unavailable)
        self.conn.job = None
        self.assertEqual(self.get("/99413").json()["photo"], unavailable)

    def test_image_served_only_for_current_selected_job(self):
        r = self.image()
        self.assertEqual((r.status_code, r.content, r.headers["content-type"]), (200, PNG, "image/png"))
        self.assertEqual(r.headers["cache-control"], "no-cache")
        self.assertEqual(r.headers["etag"], '"' + ASSET["sha256"] + '"')
        self.visual = "w" * 64
        self.assertEqual(self.image().status_code, 404)
        self.visual = "v" * 64
        self.conn.job = None
        self.assertEqual(self.image().status_code, 404)

    def test_image_revalidation_returns_304_without_fetch(self):
        self.body = b"not fetched"
        r = self.image(**{"If-None-Match": '"' + ASSET["sha256"] + '"'})
        self.assertEqual((r.status_code, r.content), (304, b""))

    def test_image_closed_when_offer_not_public(self):
        self.result = {"status": 404, "error": "not_public"}
        self.assertEqual(self.image().status_code, 404)

    def test_image_checksum_mismatch_is_503_not_served(self):
        self.body = PNG + b"x"
        r = self.image()
        self.assertEqual(r.status_code, 503)
        self.assertNotIn(b"PNG", r.content)

    def test_image_wrong_storage_key_is_404(self):
        self.job["asset"]["key"] = "pc-configurations/other/representative.png"
        self.conn.job = self.job
        self.assertEqual(self.image().status_code, 404)

    def test_old_job_photo_route_is_gone(self):
        self.assertEqual(self.get(f"/99413/photo/{JOB}").status_code, 404)

    def test_no_internal_or_llm_fields(self):
        text = self.get("/99413").text
        for word in ("provider", "model\"", "cost", "token", "operator", "publication_basis", "visual_basis", "sha256"):
            self.assertNotIn(word, text)


class PublicItemTest(unittest.TestCase):
    ITEM = {"product_code": 5, "photo": {"state": "available"}, "public_configuration": {"x": 1}}

    def test_public_item_returns_the_two_ui_keys(self):
        with patch.object(m, "_read", return_value=(deepcopy(self.ITEM), None)):
            self.assertEqual(m.public_item(5), {"photo": {"state": "available"}, "public_configuration": {"x": 1}})

    def test_not_public_is_unavailable_and_null(self):
        with patch.object(m, "_read", return_value=(None, None)):
            self.assertEqual(m.public_item(5), {"photo": {"state": "unavailable", "url": None},
                                                "public_configuration": None})

    def test_read_failure_is_unavailable_and_logged(self):
        with patch.object(m, "_read", side_effect=RuntimeError("db down")), \
                self.assertLogs("customer_pc_offer", "ERROR"):
            self.assertEqual(m.public_item(5)["photo"], {"state": "unavailable", "url": None})

    def test_attach_in_place_once_per_code_and_rejects_bad_codes(self):
        products = [{"product_code": 5}, {"product_code": 5}, {"product_code": True}, {"name": "x"}]
        with patch.object(m, "_read", return_value=(deepcopy(self.ITEM), None)) as read:
            m.attach(products)
        read.assert_called_once_with(5)
        self.assertEqual(products[0]["public_configuration"], {"x": 1})
        self.assertIsNot(products[0]["public_configuration"], products[1]["public_configuration"])
        for p in products[2:]:
            self.assertEqual((p["photo"]["state"], p["public_configuration"]), ("unavailable", None))


class RecommendWiringTest(unittest.TestCase):
    def test_recommend_attaches_sold_items_before_return(self):
        import ast, inspect
        from api import grid_public
        tree = ast.parse(inspect.getsource(grid_public.recommend))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "attach"
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == "_PC_OFFER"]
        self.assertEqual(len(calls), 1)
        self.assertIs(grid_public._PC_OFFER, m)


class SourceReaderWiringTest(unittest.TestCase):
    def test_rights_reference_comes_from_environment(self):
        with patch.object(m, "make_source_reader") as make, \
                patch.dict(m.os.environ, {m.RIGHTS_ENV: " workroom:x@v1:" + "a" * 64 + " "}):
            m._source_reader()
        make.assert_called_once_with(image_reader=m.read_image,
                                     business_rights_reference="workroom:x@v1:" + "a" * 64)

    def test_missing_env_uses_repository_file(self):
        # 2026-10-09: 서버에 환경변수가 없어 부품 사진이 전부 닫혔다 — 파일 값으로 열린다.
        with patch.object(m, "make_source_reader") as make, patch.dict(m.os.environ, {}, clear=True):
            m._source_reader()
        self.assertEqual(make.call_args.kwargs["business_rights_reference"], BULK.RIGHTS_ATTESTATION)

    def test_repository_file_matches_bulk_approval_reference_byte_for_byte(self):
        # 승인 도구가 provenance 에 적은 값과 바이트 단위로 같아야 사진이 열린다.
        with patch.dict(m.os.environ, {}, clear=True):
            got = m.rights_reference()
        self.assertEqual(got.encode("utf-8"), BULK.RIGHTS_ATTESTATION.encode("utf-8"))
        self.assertTrue(photo_approval._reference(got, rights=True))

    def test_missing_env_and_file_is_none_fail_closed(self):
        with patch.object(m, "make_source_reader") as make, patch.dict(m.os.environ, {}, clear=True), \
                patch.object(m, "RIGHTS_FILE", m.pathlib.Path("/nonexistent/rights.json")):
            m._source_reader()
        self.assertIsNone(make.call_args.kwargs["business_rights_reference"])

    def test_invalid_file_is_none_fail_closed(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write("not json")
        with patch.dict(m.os.environ, {}, clear=True), patch.object(m, "RIGHTS_FILE", m.pathlib.Path(f.name)):
            self.assertIsNone(m.rights_reference())


if __name__ == "__main__":
    unittest.main()
