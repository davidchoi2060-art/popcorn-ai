"""고객 판매 PC 목록(/api/customer/pc-catalog)과 목록에서 고른 PC 보관 경로 (2026-10-19 /mvp4)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException

from api import customer_pc_catalog as C
from api import mvp3_saved_quotes as S


def fit(**ranks):
    return {u: {"level": "L%d" % r, "rank": r} for u, r in ranks.items()}


def product(code, name="골드 [12400F/16G/500GB/RTX5060]", price=1000000, status="판매중", **ranks):
    return {"code": code, "name": name, "price": price, "price_src": "10월 19일 기준 쇼핑몰 가격", "status": status,
            "url": "https://www.popcornpc.co.kr/shop/system_detail.html?pd_no=%d" % code,
            "spec": {"cpu": "i5-12400F", "gpu": "RTX 5060", "ram_gb": 16, "ssd_gb": 500, "cpu_mt": 99, "gpu_idx": 7},
            "case_psu": {}, "fit": fit(**ranks)}


class CategoryTest(unittest.TestCase):
    def test_rules_in_order(self):
        self.assertEqual(C.category_of(product(1, name="오피스 초슬림/미니타워[12100]", 게임=3)), "미니 PC")
        self.assertEqual(C.category_of(product(2, **{"로컬 AI": 2, "게임": 4})), "AI·고성능 PC")
        self.assertEqual(C.category_of(product(3, 영상편집=2, 게임=3)), "디자인·영상")
        self.assertEqual(C.category_of(product(4, 게임=2)), "게이밍 PC")
        self.assertEqual(C.category_of(product(5, 사무용=1, 게임=1)), "사무·업무용")
        self.assertEqual(C.category_of(product(6)), "일반 PC")


class CatalogTest(unittest.TestCase):
    def run_catalog(self, products, public=frozenset(), media=frozenset()):
        with patch.object(C, "load", return_value=([], products)), \
             patch.object(C, "public_codes", return_value=public), \
             patch.object(C, "_media_hints", return_value=media):
            return C.catalog()

    def test_only_on_sale_and_allowlisted_fields(self):
        items = self.run_catalog({1: product(1, 게임=2), 2: product(2, status="품절", 게임=2)}, public={1}, media={1})
        self.assertEqual([i["product_code"] for i in items], [1])
        it = items[0]
        self.assertEqual(set(it), {"product_code", "name", "price", "price_basis", "sale_status", "mall_url", "spec", "fit",
                                   "category", "configuration_public", "photo_hint", "image_url"})
        # 평가 내부 지수는 고객에게 내지 않는다(card_spec 의 public_spec).
        self.assertNotIn("cpu_mt", it["spec"]); self.assertNotIn("gpu_idx", it["spec"])
        self.assertTrue(it["configuration_public"]); self.assertTrue(it["photo_hint"])
        self.assertEqual(it["image_url"], "/api/customer/products/1/representative-image?size=card")

    def test_photo_hint_needs_public_configuration(self):
        it = self.run_catalog({1: product(1, 게임=2)}, public=frozenset(), media={1})[0]
        self.assertFalse(it["photo_hint"])

    def test_missing_price_is_null_not_zero(self):
        it = self.run_catalog({1: product(1, price=None, 게임=2)})[0]
        self.assertIsNone(it["price"])


class SoldItemTest(unittest.TestCase):
    def test_sold_item_only_for_on_sale_with_price(self):
        products = {1: product(1, 게임=2), 2: product(2, status="품절"), 3: product(3, price=None)}
        with patch.object(C, "load", return_value=([], products)):
            self.assertEqual(C.sold_item(1)["product_code"], 1)
            self.assertEqual(C.sold_item(1)["role"], "chosen")
            self.assertIsNone(C.sold_item(2)); self.assertIsNone(C.sold_item(3)); self.assertIsNone(C.sold_item(99))
            self.assertIsNone(C.sold_item("1"))

    def body(self, **kw):
        return S.SaveBody(**{"request_id": UUID(int=1), "product_code": 1, "expected_price": 1000000, "state": {}, **kw})

    def test_saved_quote_without_usages_uses_catalog_item(self):
        state = SimpleNamespace(model_dump=lambda: {"usages": []})
        with patch.object(C, "load", return_value=([], {1: product(1, 게임=2)})), \
             patch.object(S.grid_public, "recommend", side_effect=AssertionError("recommend must not run")):
            out = S.recommended_product(state, self.body())
        self.assertEqual(out["product_code"], 1)
        self.assertEqual(out["price"], 1000000)
        self.assertFalse(out["ai_composed"])

    def test_saved_quote_without_usages_rejects_unsold_or_changed_price(self):
        state = SimpleNamespace(model_dump=lambda: {"usages": []})
        with patch.object(C, "load", return_value=([], {1: product(1, status="품절")})):
            with self.assertRaises(HTTPException) as e:
                S.recommended_product(state, self.body())
            self.assertEqual(e.exception.status_code, 409)
        with patch.object(C, "load", return_value=([], {1: product(1, price=1100000)})):
            with self.assertRaises(HTTPException) as e:
                S.recommended_product(state, self.body())
            self.assertEqual(e.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
