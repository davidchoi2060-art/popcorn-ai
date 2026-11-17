"""미디어 저장소 분리 — 복제 증명(replica manifest)·재고 목록·영수증 3종.

논리 버킷 이름은 DB 기록에 그대로 남고 실제 저장 버킷만 배포 설정이 고른다. 옛 버킷에 올린
객체를 새 버킷에서 다시 확인할 때는 «해시로 고정된 배포 산출물»만 근거가 된다 — 요청이
건넨 값이나 "가장 최근 세대"로 대신하지 않는다. 증명이 없으면 거부한다(다른 버킷으로
넘어가지 않는다).
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from api import media_storage
from api.media_storage import LOGICAL_BUCKET, ReplicaBinding, StorageConfigurationError
from api.pc_existing_media_import import (
    BUCKET, Conflict, GcsObjects, LogicalStorageReceipt, ObjectReceipt, PhysicalObjectReceipt,
    ReplicaReceipt, _receipt_valid, validated_asset,
)

PHYSICAL = "fixture-replica-media-bucket"          # 가짜 이름 — 실제 버킷이 아니다
JOB = "11111111-2222-4333-8444-555555555555"
KEY = f"pc-configurations/{JOB}/representative.png"
RAW = b"\x89PNG\r\n\x1a\n" + b"fixture-image-bytes"
SHA = hashlib.sha256(RAW).hexdigest()
ENV_KEYS = ("POPCORN_MEDIA_STORAGE_BUCKET", "POPCORN_MEDIA_BUCKET",
            "POPCORN_MEDIA_REPLICA_MANIFEST", "POPCORN_MEDIA_REPLICA_MANIFEST_SHA256")


def _manifest(**overrides):
    data = dict(schema=media_storage.SCHEMA, logical_bucket=LOGICAL_BUCKET, source_bucket=LOGICAL_BUCKET,
                destination_bucket=PHYSICAL, verified_at="2026-11-01T00:00:00Z",
                objects=[dict(key=KEY, source_generation="111", destination_generation="222",
                              sha256=SHA, size=len(RAW), content_type="image/png")])
    data.update(overrides)
    return data


class _Env(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        self.temp = tempfile.TemporaryDirectory(prefix="media-replica-fixture-")
        self.addCleanup(self.temp.cleanup)

    def physical(self):
        os.environ["POPCORN_MEDIA_STORAGE_BUCKET"] = PHYSICAL

    def install(self, data=None, raw=None, pin=None):
        raw = json.dumps(_manifest() if data is None else data).encode("utf-8") if raw is None else raw
        path = Path(self.temp.name) / "replica.json"
        path.write_bytes(raw)
        os.environ["POPCORN_MEDIA_REPLICA_MANIFEST"] = str(path)
        os.environ["POPCORN_MEDIA_REPLICA_MANIFEST_SHA256"] = pin or hashlib.sha256(raw).hexdigest()
        return path

    def lookup(self, **overrides):
        args = dict(logical_bucket=LOGICAL_BUCKET, key=KEY, source_generation="111", sha256=SHA,
                    size=len(RAW), content_type="image/png")
        args.update(overrides)
        return media_storage.replica_binding(**args)

    def refused(self, reason, **overrides):
        with self.assertRaises(StorageConfigurationError) as caught:
            self.lookup(**overrides)
        self.assertEqual(str(caught.exception), reason)


class ReplicaBindingTests(_Env):
    def test_exact_binding_is_returned_with_the_manifest_pin(self):
        self.physical()
        self.install()
        binding = self.lookup()
        self.assertEqual((binding.source_bucket, binding.destination_bucket), (LOGICAL_BUCKET, PHYSICAL))
        self.assertEqual((binding.source_generation, binding.destination_generation), ("111", "222"))
        self.assertEqual(binding.manifest_sha256, os.environ["POPCORN_MEDIA_REPLICA_MANIFEST_SHA256"])
        self.assertIs(media_storage.verify_binding(binding), binding)

    def test_no_replica_when_storage_is_the_logical_bucket(self):
        self.install()
        self.refused("invalid_replica_lookup")

    def test_lookup_arguments_are_validated_before_reading_anything(self):
        self.physical()
        for override in (dict(source_generation="0"), dict(source_generation=111), dict(sha256="x"),
                         dict(size=0), dict(size=str(len(RAW))), dict(content_type="")):
            with self.subTest(override=override):
                self.refused("invalid_replica_lookup", **override)

    def test_unconfigured_manifest_is_refused(self):
        self.physical()
        self.refused("replica_manifest_unconfigured")
        os.environ["POPCORN_MEDIA_REPLICA_MANIFEST"] = "relative/replica.json"
        os.environ["POPCORN_MEDIA_REPLICA_MANIFEST_SHA256"] = "a" * 64
        self.refused("replica_manifest_unconfigured")
        self.install(pin="not-a-hash")
        self.refused("replica_manifest_unconfigured")

    def test_manifest_bytes_must_match_the_pin(self):
        self.physical()
        path = self.install()
        path.write_bytes(path.read_bytes() + b" ")
        self.refused("replica_manifest_hash_mismatch")

    def test_missing_or_unparsable_manifest_is_refused(self):
        self.physical()
        self.install().unlink()
        self.refused("replica_manifest_unreadable")
        self.install(raw=b"{not json")
        self.refused("replica_manifest_unreadable")
        self.install(raw=b'{"schema": 1, "schema": 2}')
        self.refused("duplicate_manifest_json_key")

    def test_manifest_contract_is_exact(self):
        self.physical()
        for name, data in (
                ("schema", _manifest(schema="popcorn-media-replica-v0")),
                ("destination", _manifest(destination_bucket="another-fixture-bucket")),
                ("source", _manifest(source_bucket=PHYSICAL)),
                ("extra key", dict(_manifest(), note="x")),
                ("objects type", _manifest(objects={}))):
            with self.subTest(case=name):
                self.install(data)
                self.refused("replica_manifest_contract_mismatch")
        self.install(_manifest(verified_at="2026-11-01T00:00:00"))
        self.refused("replica_manifest_timestamp_invalid")

    def test_object_rows_are_validated_and_never_guessed(self):
        self.physical()
        row = _manifest()["objects"][0]
        self.install(_manifest(objects=[dict(row, destination_generation="latest")]))
        self.refused("replica_manifest_object_invalid")
        self.install(_manifest(objects=[row, dict(row, destination_generation="333")]))
        self.refused("replica_manifest_duplicate_binding")
        self.install(_manifest(objects=[dict(row, sha256="b" * 64)]))
        self.refused("replica_manifest_content_mismatch")
        self.install(_manifest(objects=[dict(row, source_generation="999")]))
        self.refused("replica_manifest_binding_missing")

    def test_binding_is_rechecked_against_the_current_manifest(self):
        self.physical()
        self.install()
        binding = self.lookup()
        row = _manifest()["objects"][0]
        self.install(_manifest(objects=[dict(row, destination_generation="333")]))
        with self.assertRaises(StorageConfigurationError) as caught:
            media_storage.verify_binding(binding)
        self.assertEqual(str(caught.exception), "replica_binding_changed")
        with self.assertRaises(StorageConfigurationError):
            media_storage.verify_binding(asdict(binding))


class InventoryTests(_Env):
    def test_logical_storage_accepts_legacy_rows_without_a_bucket(self):
        rows = [dict(name="products/1/a.png"), dict(name="products/1/b.png", bucket=LOGICAL_BUCKET)]
        self.assertEqual(set(media_storage.inventory_objects(rows)), {"products/1/a.png", "products/1/b.png"})

    def test_physical_storage_requires_every_row_to_name_that_bucket(self):
        self.physical()
        good = [dict(name="products/1/a.png", bucket=PHYSICAL)]
        self.assertEqual(media_storage.inventory_objects(good)["products/1/a.png"], good[0])
        for name, rows in (("no bucket", [dict(name="products/1/a.png")]),
                           ("old bucket", [dict(name="products/1/a.png", bucket=LOGICAL_BUCKET)]),
                           ("duplicate", good + good),
                           ("bad key", [dict(name="../a.png", bucket=PHYSICAL)]),
                           ("not a list", {"products/1/a.png": {}}),
                           ("not a row", ["products/1/a.png"])):
            with self.subTest(case=name), self.assertRaises(StorageConfigurationError):
                media_storage.inventory_objects(rows)


class ReceiptTests(_Env):
    def logical(self, **overrides):
        values = dict(bucket=BUCKET, key=KEY, sha256=SHA, size=len(RAW), generation="123")
        values.update(overrides)
        return ObjectReceipt(**values)

    def test_logical_bucket_is_the_shared_identity(self):
        self.assertEqual(BUCKET, LOGICAL_BUCKET)

    def test_plain_receipt_only_when_storage_is_the_logical_bucket(self):
        receipt = self.logical()
        self.assertTrue(_receipt_valid(receipt, JOB, RAW))
        self.assertEqual(validated_asset(receipt, JOB, RAW, "notice"), dict(asdict(receipt), notice="notice"))
        self.physical()
        self.assertFalse(_receipt_valid(receipt, JOB, RAW))
        with self.assertRaises(Conflict):
            validated_asset(receipt, JOB, RAW, "notice")

    def test_new_registration_records_logical_identity_and_storage_bucket(self):
        self.physical()
        physical = PhysicalObjectReceipt(PHYSICAL, KEY, SHA, len(RAW), "123")
        receipt = GcsObjects._new_receipt(physical)
        self.assertIsInstance(receipt, LogicalStorageReceipt)
        asset = validated_asset(receipt, JOB, RAW, "notice")
        self.assertEqual(asset, dict(bucket=BUCKET, key=KEY, sha256=SHA, size=len(RAW), generation="123",
                                     storage_bucket=PHYSICAL, notice="notice"))
        for name, bad in (
                ("other bucket", LogicalStorageReceipt(receipt.logical,
                    PhysicalObjectReceipt("another-fixture-bucket", KEY, SHA, len(RAW), "123"))),
                ("generation differs", LogicalStorageReceipt(receipt.logical,
                    PhysicalObjectReceipt(PHYSICAL, KEY, SHA, len(RAW), "124"))),
                ("bytes differ", LogicalStorageReceipt(self.logical(sha256="b" * 64),
                    PhysicalObjectReceipt(PHYSICAL, KEY, "b" * 64, len(RAW), "123"))),
                ("dict", asdict(receipt))):
            with self.subTest(case=name):
                self.assertFalse(_receipt_valid(bad, JOB, RAW))

    def test_logical_storage_receipt_is_refused_without_a_separate_bucket(self):
        physical = PhysicalObjectReceipt(BUCKET, KEY, SHA, len(RAW), "123")
        self.assertIsInstance(GcsObjects._new_receipt(physical), ObjectReceipt)
        self.assertFalse(_receipt_valid(LogicalStorageReceipt(self.logical(), physical), JOB, RAW))

    def test_replica_receipt_keeps_the_original_asset_byte_for_byte(self):
        self.physical()
        self.install()
        binding = media_storage.replica_binding(BUCKET, KEY, "111", SHA, len(RAW), "image/png")
        source = self.logical(generation="111")
        physical = PhysicalObjectReceipt(PHYSICAL, KEY, SHA, len(RAW), "222")
        receipt = ReplicaReceipt(source, physical, binding)
        self.assertTrue(_receipt_valid(receipt, JOB, RAW))
        # 옛 자산 기록과 한 글자도 달라지지 않는다 — storage_bucket 을 덧붙이지 않는다.
        self.assertEqual(validated_asset(receipt, JOB, RAW, "notice"), dict(asdict(source), notice="notice"))
        stale = PhysicalObjectReceipt(PHYSICAL, KEY, SHA, len(RAW), "111")
        self.assertFalse(_receipt_valid(ReplicaReceipt(source, stale, binding), JOB, RAW))
        self.assertFalse(_receipt_valid(ReplicaReceipt(self.logical(generation="112"), physical, binding), JOB, RAW))

    def test_replica_receipt_is_refused_once_the_manifest_is_gone(self):
        self.physical()
        self.install()
        binding = media_storage.replica_binding(BUCKET, KEY, "111", SHA, len(RAW), "image/png")
        receipt = ReplicaReceipt(self.logical(generation="111"),
                                 PhysicalObjectReceipt(PHYSICAL, KEY, SHA, len(RAW), "222"), binding)
        os.environ.pop("POPCORN_MEDIA_REPLICA_MANIFEST")
        self.assertFalse(_receipt_valid(receipt, JOB, RAW))

    def test_existing_object_without_a_manifest_is_a_conflict_before_any_network(self):
        # 실제 버킷이 논리 버킷과 다른데 증명이 없으면 재검증은 거부된다(개발 서버가 이 상태다).
        self.physical()
        objects = GcsObjects(lambda: self.fail("network must not be reached"))
        with self.assertRaises(Conflict):
            objects.verify_existing(JOB, RAW, "111")
        with self.assertRaises(Conflict):
            objects.verify_existing(JOB, RAW, "111", storage_bucket="another-fixture-bucket")


if __name__ == "__main__":
    unittest.main()
