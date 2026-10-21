"""승인 구성이 없는 판매 PC 의 상세 소개 (2026-10-21 대표 「진행해」 · 「DB화」) — 상품명 기준 · 새 사실 없음."""
import pathlib
import unittest

from api import registered_about as A

ROOT = pathlib.Path(__file__).resolve().parents[1]
FITS = [{"usage": "사무용", "level": "쾌적", "rank": 2, "work": "대용량 엑셀"},
        {"usage": "디자인·조판", "level": "쾌적", "rank": 2, "work": "대형 PSD"},
        {"usage": "게임", "level": "캐주얼", "rank": 1, "work": "롤·발로란트"}]


class Build(unittest.TestCase):
    def test_title_spec_is_the_basis(self):
        c = A.build("골드 NO.04 .123380 RTX 3050 [13500/16G/1TB/RTX3050]", {"ram_gb": 32, "ssd_gb": 1000}, FITS)
        self.assertIn("16GB 메모리와 1TB SSD", c["intro"])
        self.assertEqual(c["benefits"][1][0], "16GB, 일반 작업과 게임에 알맞아요")

    def test_mismatched_evaluation_drops_higher_levels(self):
        c = A.build("[13500/16G/1TB/RTX3050]", {"ram_gb": 32, "ssd_gb": 1000}, FITS)
        self.assertNotIn("디자인", c["intro"] + c["scene"])
        same = A.build("[13500/32G/1TB/RTX3050]", {"ram_gb": 32, "ssd_gb": 1000}, FITS)
        self.assertIn("디자인·조판", same["intro"])

    def test_integrated_graphics(self):
        c = A.build("[12100/8G/250GB/UHD 730]", None, [{"usage": "사무용", "level": "기본", "rank": 1, "work": "문서"}])
        self.assertIn("내장 그래픽", c["intro"])
        self.assertEqual(c["benefits"][0][0], "일상 작업을 중심으로 담았어요")

    def test_no_basis_no_copy(self):
        self.assertIsNone(A.build("그냥 PC", None, []))

    def test_fallback_to_evaluation_spec(self):
        c = A.build("QHD 게임 PC 권장", {"cpu": "라이젠7 9700X", "gpu": "RTX 5070", "ram_gb": 32, "ssd_gb": 1000},
                    [{"usage": "게임", "level": "QHD", "rank": 3, "work": "최신 대작 QHD"}])
        self.assertEqual(c["title"], "QHD 게임을 즐기는 PC")
        self.assertIn("32GB 메모리와 1TB SSD", c["intro"])


class Wiring(unittest.TestCase):
    def test_detail_reads_table_and_screen_uses_it(self):
        api = (ROOT / "api/customer_pc_registered.py").read_text(encoding="utf-8")
        self.assertIn("FROM pc_registered_about", api)
        self.assertIn('"description": desc', api)
        js = (ROOT / "mockups/mvp4/assets/js/live-catalog.js").read_text(encoding="utf-8")
        self.assertIn("p.description = body && body.description", js)

    def test_migration_chain(self):
        m = (ROOT / "db/migrations/versions/0172_registered_about.py").read_text(encoding="utf-8")
        self.assertIn('revision = "0172"', m)
        self.assertIn("from api.registered_about import build", m)


class AdminEditor(unittest.TestCase):
    def test_product_fit_page_edits_about(self):
        t = (ROOT / "templates/admin/product_fit.html.j2").read_text(encoding="utf-8")
        self.assertIn("/api/admin/registered-about/", t)
        self.assertIn("method: 'PUT'", t)
