# -*- coding: utf-8 -*-
"""0180 — 11월 몰 새 완제PC 9개 적재 데이터와 마이그레이션 계약.

이 데이터가 틀리면 고객 목록·추천에 «몰에서 파는 것과 다른 구성»이 나온다. 그래서 다음을 고정한다.
  · 0169 와 같은 모양(마이그레이션이 같은 키를 읽는다)
  · 평가가 상품명이 아니라 기본 구성 부품 줄에서 나왔다(이름과 구성이 다른 상품 3개)
  · 평가가 지금 tools/product_fit.py 로 다시 매겨도 같다(기준표를 바꾸면 이 데이터도 다시 만든다)
"""
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "db/migrations/data/new_builtpc_20261120.json"
OLD = ROOT / "db/migrations/data/new_builtpc_20261021.json"
CODES = [130855, 130856, 131542, 131543, 131544, 131545, 131546, 131547, 131676]

sys.path.insert(0, str(ROOT / "tools"))
import product_fit as F  # noqa: E402
import mall_new_builtpc_seed as S  # noqa: E402


def _migration():
    p = ROOT / "db/migrations/versions/0180_new_builtpc_20261120.py"
    spec = importlib.util.spec_from_file_location("m0180", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _data():
    return json.loads(DATA.read_text(encoding="utf-8"))


def _parts(text):
    """spec_source_text -> [(슬롯, 값)]"""
    return [tuple(x.split("@@", 1)) for x in text.split(" ,@@") if x]


class Migration0180(unittest.TestCase):
    def test_revision_follows_head(self):
        m = _migration()
        self.assertEqual((m.revision, m.down_revision), ("0180", "0179"))
        self.assertEqual(m.DATA, DATA)

    def test_does_not_overwrite_existing_rows(self):
        src = (ROOT / "db/migrations/versions/0180_new_builtpc_20261120.py").read_text(encoding="utf-8")
        # 표 셋(products · product_fit_products · product_usage_fit) 모두 기존 행을 둔다
        self.assertEqual(len(re.findall(r"ON CONFLICT \([a-z_, ]+\) DO NOTHING", src)), 3)
        self.assertNotIn("DO UPDATE", src)
        self.assertNotIn("DELETE FROM products", src)


class Data0180(unittest.TestCase):
    def test_same_shape_as_0169(self):
        new, old = _data(), json.loads(OLD.read_text(encoding="utf-8"))
        self.assertEqual(set(new), set(old))
        self.assertEqual(set(new["products"][0]), set(old["products"][0]))
        self.assertEqual(new["evaluated_at"], "2026-11-20")

    def test_exact_codes_and_urls(self):
        prods = _data()["products"]
        self.assertEqual([p["code"] for p in prods], CODES)
        for p in prods:
            self.assertEqual(p["url"], "https://www.popcornpc.co.kr/shop/system_detail.html?pd_no=%d" % p["code"])
            self.assertGreater(p["sale_price"], 0)
            self.assertGreaterEqual(p["market_price"], p["sale_price"])
            self.assertIsNone(p["includes"])

    def test_every_usage_present_once(self):
        for p in _data()["products"]:
            self.assertEqual([f["usage"] for f in p["fit"]], list(F.REQUIREMENTS))

    def test_evaluation_reproduces_from_parts(self):
        """부품 줄만으로 다시 매기면 같은 결과 — 상품명은 평가에 들어가지 않는다."""
        for p in _data()["products"]:
            row = {}
            for slot, val in _parts(p["spec_source_text"]):
                key = S.SLOT.get(slot)
                if key and key not in row:
                    row[key] = val
            sp = F.specs_of(row)
            ev = F.evaluate(sp)
            self.assertEqual([(u, v[0]) for u, v in ev.items()], [(f["usage"], f["level"]) for f in p["fit"]],
                             p["code"])
            self.assertEqual((sp["ram"], sp["ssd"]), (p["spec"]["ram_gb"], p["spec"]["ssd_gb"]), p["code"])

    def test_name_and_parts_disagree_is_recorded(self):
        """몰 상품명은 32G/1TB 인데 구성은 64GB(/2TB) — 평가는 구성을 따르고 차이를 balance 에 남긴다."""
        by = {p["code"]: p for p in _data()["products"]}
        self.assertEqual(by[131545]["spec"]["ram_gb"], 64)
        self.assertIn("상품명은 램 32GB 인데 기본 구성은 64GB", by[131545]["balance"])
        for code in (131546, 131547):
            self.assertEqual((by[code]["spec"]["ram_gb"], by[code]["spec"]["ssd_gb"]), (64, 2000))
            self.assertIn("SSD 1000GB 인데 기본 구성은 2000GB", by[code]["balance"])
        for code in (130855, 130856, 131542, 131543, 131544):
            self.assertIsNone(by[code]["balance"], code)

    def test_campaign_mapped_products(self):
        """기획전 매핑(사장님 승인 11-20): business=131545, video=131544."""
        by = {p["code"]: p for p in _data()["products"]}
        self.assertEqual((by[131545]["spec"]["cpu"], by[131545]["spec"]["gpu"]), ("코어 울트라7 270K Plus", "RTX 5070 Ti"))
        self.assertEqual((by[131544]["spec"]["cpu"], by[131544]["spec"]["gpu"]), ("코어 울트라7 270K Plus", "RTX 5080"))
        self.assertTrue(re.search(r"ROG STRIX B860-G GAMING WIFI", by[131545]["spec_source_text"]))
        self.assertTrue(re.search(r"TUF Gaming Z890-PLUS WIFI", by[131544]["spec_source_text"]))

    def test_low_end_office_has_no_usage(self):
        """131676(애슬론 3000G · 8GB · 128GB)은 사무용 「기본」 조건(CPU 멀티 5,000 · SSD 240GB)에 못 미친다."""
        p = {x["code"]: x for x in _data()["products"]}[131676]
        self.assertEqual(p["spec"]["cpu"], "애슬론 3000G (2코어)")
        self.assertTrue(all(f["level"] is None for f in p["fit"]))
        office = p["fit"][0]
        self.assertEqual(office["usage"], "사무용")
        self.assertIn("SSD 240GB 미만(현재 128GB)", office["blocked"])


if __name__ == "__main__":
    unittest.main()
