"""ASUS 사용 예시 9장 (2026-11-06). 코드로 그린 설명 그림이다. 실제 표시는 공유 폴더의 로컬 브라우저 결과를 본다."""
import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASUS = ROOT / "mockups/mvp4/assets/images/asus"
SVG = ROOT / "docs/asus-ai-pc-v4/use-art"
SEED = json.loads((ROOT / "db/migrations/data/asus_campaign_models_20261106.json").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("asus_use_art", ROOT / "tools/asus_use_art.py")
ART = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ART)
TEXT = re.compile(r'<text x="([\d.]+)" y="([\d.]+)" font-size="(\d+)"[^>]*>([^<]*)</text>')


class UseArt(unittest.TestCase):
    def test_every_db_image_name_has_a_scene(self):
        names = {u["image"] for row in SEED["models"].values() for u in row["content"]["uses"]}
        self.assertEqual(names, {n + ".webp" for n in ART.SCENES})
        self.assertEqual(len(names), 9)

    def test_webp_size_and_distinct(self):
        hashes = set()
        for name in ART.SCENES:
            path = ASUS / (name + ".webp")
            with Image.open(path) as im:
                self.assertEqual((im.format, im.size), ("WEBP", (1440, 576)), name)
            hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(len(hashes), 9)

    def test_svg_source_matches_generator(self):
        for name, draw in ART.SCENES.items():
            saved = (SVG / (name + ".svg")).read_text(encoding="utf-8").replace("\r\n", "\n")
            self.assertEqual(saved, draw() + "\n", name)

    def test_scenes_are_vector_only_and_labels_differ(self):
        seen = set()
        for name, draw in ART.SCENES.items():
            svg = draw()
            self.assertNotIn("<image", svg, name)
            self.assertNotIn("href", svg, name)
            title = TEXT.findall(svg)[0][3]
            self.assertNotIn(title, seen)
            seen.add(title)

    def test_no_numbers_or_performance_words(self):
        for name, draw in ART.SCENES.items():
            for _, _, _, label in TEXT.findall(draw()):
                self.assertNotRegex(label, r"\d|%|점수|속도|성능|빠른|배 ", (name, label))

    def test_text_is_large_enough_and_clear_of_badge(self):
        for name, draw in ART.SCENES.items():
            found = TEXT.findall(draw())
            self.assertGreaterEqual(len(found), 2, name)
            for x, y, size, label in found:
                self.assertGreaterEqual(int(size), 50, (name, label))   # 310 폭에서 약 11px
                top = float(y) - int(size)
                self.assertFalse(float(x) < 410 and top < 160, (name, label))   # 「사용 예시」 배지 자리

    def test_screen_uses_versioned_url_and_keeps_notice(self):
        pages = (ROOT / "mockups/mvp4/assets/js/asus-pages.js").read_text(encoding="utf-8")
        data = (ROOT / "mockups/mvp4/assets/js/asus-data.js").read_text(encoding="utf-8")
        self.assertIn("h(A.useImage(u.image))", pages)
        self.assertIn("<figcaption>사용 예시</figcaption>", pages)
        self.assertRegex(data, r"useImage: function \(file\) \{ return A\.image\(file\) \+ '\?v=")
        for page in ("asus-pc.html", "asus.html"):
            self.assertRegex((ROOT / "mockups/mvp4" / page).read_text(encoding="utf-8"), r"asus-pages\.js\?v=20261106-")


if __name__ == "__main__":
    unittest.main()
