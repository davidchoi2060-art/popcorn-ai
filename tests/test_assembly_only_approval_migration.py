"""0136: assembly-only parts (no retail product row) can carry part/photo approval.

Default: capture checks only. The PostgreSQL case is opt-in and runs the original
0130/0131 SQL, then 0136, then the real approval cores on a throwaway schema:
  ASSEMBLY_APPROVAL_TEST_PG_DSN=postgresql+psycopg2://.../<disposable db> \
  python -m pytest tests/test_assembly_only_approval_migration.py
Creates and drops only its own assembly_verify_<uuid> schema.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
import uuid

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / 'db/migrations/versions'
DSN = os.environ.get('ASSEMBLY_APPROVAL_TEST_PG_DSN')
PNG = b'\x89PNG\r\n\x1a\nassembly-only-detail'
RIGHTS = 'workroom:MOCK-company-sales-attestation@v1:' + 'b' * 64


def migration(name):
    spec = importlib.util.spec_from_file_location('_migration_' + name.split('_')[0], VERSIONS / name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.module = migration('0136_assembly_only_part_approval.py')

    def test_revision_chain_and_downgrade_refused(self):
        self.assertEqual((self.module.revision, self.module.down_revision), ('0136', '0135'))
        with self.assertRaises(RuntimeError): self.module.downgrade()

    def test_only_assembly_only_rows_skip_retail_checks(self):
        sql = self.module.UPGRADE_SQL
        self.assertEqual(sql.count("assembly:=e.product_code IS NULL AND e.content->>'availability_scope' IS NOT DISTINCT FROM 'assembly_only'"), 2)
        self.assertEqual(sql.count("(NOT assembly AND (e.product_code IS NULL OR p.product_code IS NULL OR p.status IS DISTINCT FROM '판매중'))"), 2)
        self.assertIn("snapshot->'content'->>'availability_scope' IS NOT DISTINCT FROM 'assembly_only'", sql)
        # Rights/provenance, immutability and same-TX checks are kept verbatim.
        for kept in ("'^workroom:[^[:space:]]+@v[1-9][0-9]*:[a-f0-9]{64}$'", "'Photo approval history is immutable'",
                     "'Part approval history is immutable'", 'x.write_txid=txid_current()',
                     "'Part revoke must reset its own native metadata'", "asset->>'detail_key' IS DISTINCT FROM prefix||'detail.png'"):
            self.assertIn(kept, sql)
        for absent in ('DROP TABLE', 'DROP TRIGGER', 'SECURITY DEFINER', 'GRANT ', 'DELETE FROM', 'UPDATE __S__'):
            self.assertNotIn(absent, sql)


@unittest.skipUnless(DSN, 'opt-in: ASSEMBLY_APPROVAL_TEST_PG_DSN')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool
        spec = importlib.util.spec_from_file_location('_assembly_fixture', ROOT / 'tests/test_part_explanation_approval.py')
        cls.fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.fixture)
        cls.previous = {k: v for k, v in sys.modules.items() if k.startswith(cls.fixture.PACKAGE)}
        cls.core, cls.part, cls.copy = cls.fixture.load_sources()
        cls.fixture.selected('product_images', 'api/product_images.py', (), ('MEDIA_BUCKET',))
        spec = importlib.util.spec_from_file_location(cls.fixture.PACKAGE + '.part_photo_approval', ROOT / 'api/part_photo_approval.py')
        cls.photo = importlib.util.module_from_spec(spec); sys.modules[spec.name] = cls.photo; spec.loader.exec_module(cls.photo)
        cls.schema = 'assembly_verify_' + uuid.uuid4().hex
        cls.engine = create_engine(DSN, poolclass=NullPool)
        cls.run_sql('CREATE SCHEMA ' + cls.schema)

    @classmethod
    def tearDownClass(cls):
        cls.run_sql('DROP SCHEMA ' + cls.schema + ' CASCADE')
        cls.engine.dispose()
        for k in list(sys.modules):
            if k.startswith(cls.fixture.PACKAGE): del sys.modules[k]
        sys.modules.update(cls.previous)

    @classmethod
    def run_sql(cls, sql, **params):
        from sqlalchemy import text
        with cls.engine.begin() as conn:
            result = conn.execute(text(sql), params)
            return result.all() if result.returns_rows else None

    def connect(self):
        from sqlalchemy import text
        conn = self.engine.connect()
        conn.execute(text('SET search_path TO ' + self.schema))
        conn.commit()
        return conn

    def setUp(self):
        from sqlalchemy import text
        s = self.schema
        self.run_sql(f'DROP SCHEMA {s} CASCADE'); self.run_sql(f'CREATE SCHEMA {s}')
        self.run_sql(f'''CREATE TABLE {s}.admin_operators(operator_id BIGINT PRIMARY KEY, role TEXT, status TEXT);
            CREATE TABLE {s}.products(product_code BIGINT PRIMARY KEY, product_name TEXT, spec_source_text TEXT,
                status TEXT, sale_price NUMERIC);
            CREATE TABLE {s}.product_explanations(source_product_code BIGINT PRIMARY KEY,
                product_code BIGINT REFERENCES {s}.products(product_code) ON DELETE SET NULL,
                content JSONB NOT NULL, source_snapshot JSONB, source_fingerprint TEXT, status TEXT NOT NULL,
                approved_by INTEGER REFERENCES {s}.admin_operators(operator_id), approved_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
            INSERT INTO {s}.admin_operators VALUES (7,'operator','활성');
            INSERT INTO {s}.products VALUES (101,'CPU 11','AM5','판매중',100);''')
        quoted = '"' + s + '"'
        for name in ('0130_part_explanation_approval.py', '0131_part_photo_approval.py', '0136_assembly_only_part_approval.py'):
            self.run_sql(migration(name).UPGRADE_SQL.replace('__S__', quoted))
        prefix = 'products/{code}/' + 'a' * 16 + '/'
        for code, linked, content in ((127201, None, dict(availability_scope='assembly_only')),
                                      (127209, None, dict()), (11, 101, dict())):
            p = prefix.format(code=code)
            content = dict(content, name=f'part {code}', slot='CPU', facts=[], review_issues=[],
                           image_url=f'https://merchant.example/{code}.png', image_asset=dict(
                               bucket='popcorn-ai-product-media-045e861b', sha256='a' * 64,
                               detail_sha256=hashlib.sha256(PNG).hexdigest(), original_key=p + 'original.png',
                               detail_key=p + 'detail.png', thumbnail_key=p + 'thumb.webp', original_size=[20, 20],
                               detail_size=[16, 16], crop_box=[2, 2, 18, 18], crop_mode='uniform_margin',
                               prepared_at='2020-01-01T00:00:00+00:00'))
            name, spec = (f'CPU {code}', 'AM5') if linked else (f'part {code}', 'LGA1851')
            self.run_sql(f'''INSERT INTO {s}.product_explanations(source_product_code,product_code,content,
                source_snapshot,source_fingerprint,status) VALUES(:code,:linked,CAST(:content AS jsonb),
                CAST(:snapshot AS jsonb),:fp,'draft')''', code=code, linked=linked,
                content=json.dumps(content, ensure_ascii=False),
                snapshot=json.dumps(dict(name=name, spec=spec), ensure_ascii=False), fp=self.part.fingerprint(name, spec))
        self.actor = dict(operator_id=7, role='operator', status='활성')

    def approve_part(self, code):
        conn = self.connect()
        try:
            with conn.begin():
                current = self.core.read_current(conn, code)
                return self.core.approve(conn, code, expected_seq=current['event_seq'], expected_basis=current['basis'],
                                         request_id=str(uuid.uuid4()), note='조립 전용 부품 설명 확인', actor=deepcopy(self.actor))
        finally:
            conn.close()

    def approve_photo(self, code, rights=RIGHTS):
        def provenance(conn, *, row, expected_basis):
            asset = row['content']['image_asset']
            return self.photo.PhotoProvenance(row['source_product_code'], row['product_code'], expected_basis,
                                              self.photo.SCOPE, f"gcs:{asset['bucket']}/{asset['detail_key']}", rights)
        ports = dict(provenance_reader=provenance, image_reader=lambda asset, c, variant: PNG,
                     business_rights_reference=rights)
        conn = self.connect()
        try:
            with conn.begin():
                current = self.photo.read_current(conn, code, **ports)
                return self.photo.approve(conn, code, expected_seq=current['event_seq'], expected_basis=current['basis'],
                                          request_id=str(uuid.uuid4()), note='권리 확인서 기준 등록 사진',
                                          actor=deepcopy(self.actor), **ports)
        finally:
            conn.close()

    def count(self, table, code):
        return self.run_sql(f'SELECT count(*) FROM {self.schema}.{table} WHERE source_product_code=:c', c=code)[0][0]

    def test_assembly_only_part_and_photo_approval_commit_with_history(self):
        part = self.approve_part(127201)
        self.assertTrue(part['current']['allowed']); self.assertIsNone(part['event']['snapshot']['product_code'])
        photo = self.approve_photo(127201)
        self.assertTrue(photo['current']['allowed'])
        self.assertEqual((self.count('part_explanation_approval_events', 127201),
                          self.count('part_photo_approval_events', 127201)), (1, 1))
        row = self.run_sql(f'SELECT status,approved_by FROM {self.schema}.product_explanations WHERE source_product_code=127201')[0]
        self.assertEqual(tuple(row), ('approved', 7))

    def test_retail_linked_part_is_unchanged(self):
        self.assertTrue(self.approve_part(11)['current']['allowed'])
        self.assertTrue(self.approve_photo(11)['current']['allowed'])

    def test_unmarked_unlinked_part_and_bad_rights_still_refused(self):
        with self.assertRaises(HTTPException) as caught: self.approve_part(127209)
        self.assertEqual(caught.exception.detail, 'part_approval_unlinked')
        with self.assertRaises(HTTPException): self.approve_photo(127209)
        with self.assertRaises(HTTPException): self.approve_photo(127201, rights='https://merchant.example/rights')
        self.assertEqual(self.count('part_explanation_approval_events', 127209), 0)
        self.assertEqual(self.count('part_photo_approval_events', 127201), 0)

    def test_database_guard_rejects_null_product_snapshot_for_unmarked_row(self):
        from sqlalchemy.exc import DBAPIError
        s = self.schema
        snapshot = dict(source_product_code=127209, product_code=None, content=dict(name='x'), source_snapshot={},
                        source_fingerprint='a' * 64, status='approved', approved_by=7, approved_at='2020-01-01T00:00:00+00:00',
                        updated_at='2020-01-01T00:00:00+00:00', product_name=None, spec_source_text=None,
                        sale_status=None, sale_price=None)
        with self.assertRaises(DBAPIError):
            self.run_sql(f'''INSERT INTO {s}.part_explanation_approval_events(source_product_code,event_seq,request_id,
                request_digest,action,operator_id,note,approval_basis,snapshot,metadata_reset)
                VALUES(127209,1,:uid,:h,'approve',7,'x',:h,CAST(:snap AS jsonb),false)''',
                uid=str(uuid.uuid4()), h='a' * 64, snap=json.dumps(snapshot))


if __name__ == '__main__':
    unittest.main()
