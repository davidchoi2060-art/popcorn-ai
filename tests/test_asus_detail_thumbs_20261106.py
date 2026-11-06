"""ASUS 상세 표시 정리(2026-11-06 사용자 지시): 금액·내부 상태 비노출, 실제 부품 사진만, 홈 배너 1번 6초.

DB · API 가격 · 관리자 원본은 그대로다. 그래서 고객 어댑터를 Node 로 실제 실행해 나온 값을 본다.
화면 렌더 · 사진 실패 · 실제 시간 측정은 tests/scenarios/asus_campaign_browser.cjs 가 맡는다.
"""
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from api import asus_campaign as AC  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MVP4 = ROOT / "mockups/mvp4"
DATA_JS = MVP4 / "assets/js/asus-data.js"
PAGES = (MVP4 / "assets/js/asus-pages.js").read_text(encoding="utf-8")
CAROUSEL = (MVP4 / "assets/js/home-carousel.js").read_text(encoding="utf-8")
INTERNAL = re.compile(r"공급\s*재?확인|확인\s*필요|확인\s*전|확정\s*불가|미확정|미확인|불일치|후보")
PRICE_WORDS = ("A.won(", "planBlock(m)", "planText(o)", "일반회원가", "프리미엄 표시가", "priceBasis", "PRICE_MEMBER", "가격 미표시")


def public_all(overrides=None):
    out = []
    for model_id, row in AC.seed_models().items():
        content = json.loads(json.dumps(row["content"], ensure_ascii=False))
        if overrides:
            overrides(content)
        out.append(AC.public_model(model_id, row["plan_review_price"], content))
    return out


def normalize(models):
    """브라우저에 전달되는 어댑터(asus-data.js)를 그대로 돌린다."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node 없음")
    code = ("const fs=require('fs'),vm=require('vm');const w={};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),"
            "{window:w,setTimeout,clearTimeout,AbortController,console});"
            "const input=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(input.map(w.PAI.asus.normalize)));")
    r = subprocess.run([node, "-e", code, str(DATA_JS)], input=json.dumps(models, ensure_ascii=False).encode(), capture_output=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr.decode("utf-8", "replace"))
    return json.loads(r.stdout.decode("utf-8"))


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


class CustomerCopy(unittest.TestCase):
    def test_seed_has_no_internal_wording_after_normalize(self):
        for model in normalize(public_all()):
            for s in strings(model):
                self.assertIsNone(INTERNAL.search(s), s)

    def test_admin_saved_internal_wording_does_not_reach_customer(self):
        def dirty(c):
            c["tagline"] = "문서를 찾습니다. 공급 확인 필요."
            for p in c["parts"]:
                if p["label"] == "메인보드":
                    p["head"] = "자료 확인 전 확정 불가"
        for model in normalize(public_all(dirty)):
            self.assertEqual(model["tagline"], "문서를 찾습니다.")
            board = next(p for p in model["parts"] if p["label"] == "메인보드")
            self.assertEqual(board["head"], "상담 시 안내")

    def test_conflict_and_internal_options_are_not_shown_and_nothing_is_confirmed(self):
        models = {m["id"]: m for m in normalize(public_all())}
        names = [o["name"] for m in models.values() for p in m["parts"] for o in p["options"]]
        self.assertFalse([n for n in names if "TeamGroup" in n or "미정" in n])
        fan = next(p for p in models["business"]["parts"] if p["label"] == "추가 시스템팬")
        self.assertEqual((fan["head"], fan["options"]), ("상담 시 안내", []))
        for m in models.values():
            for p in m["parts"]:
                for o in p["options"]:
                    self.assertEqual(set(o), {"name", "image"})

    def test_api_keeps_prices_and_status_for_admin_and_list(self):
        video = next(m for m in public_all() if m["id"] == "video")
        self.assertEqual((video["plan_review_price"], video["gpu_status"]), (5990000, "supply"))
        gpu = next(p for p in video["parts"] if p["label"].startswith("GPU"))
        self.assertIsNone(gpu["options"][0]["price"])


class Thumbnails(unittest.TestCase):
    def test_only_verified_pairs_get_a_photo(self):
        seed = {(o.get("mall_no"), o["name"]) for row in AC.seed_models().values() for p in row["content"]["parts"] for o in p["options"]}
        self.assertLessEqual(AC._THUMB_VERIFIED | {AC._THUMB_CASE}, seed)
        for code in (130847, 130987, 130851, 130703, 127181, 127182):
            self.assertFalse([1 for c, _ in AC._THUMB_VERIFIED if c == code], code)

    def test_case_uses_cutout_and_other_case_name_gets_none(self):
        self.assertEqual(AC.part_thumbnail(126548, "ASUS TUF Gaming GT502 BLACK"), "assets/images/asus/gt502-black-cutout.webp")
        self.assertTrue((MVP4 / AC.GT502_CUTOUT).is_file())
        self.assertIsNone(AC.part_thumbnail(126548, "다른 케이스"))

    def test_renamed_or_unknown_part_gets_no_photo_instead_of_another_model(self):
        self.assertIsNone(AC.part_thumbnail(129630, "ASUS PRIME RTX 5070 Ti 16GB 코잇"))
        self.assertIsNone(AC.part_thumbnail(130847, "ASUS PRIME RTX 5070 Ti 16GB 코잇"))
        self.assertIsNone(AC.part_thumbnail(None, "ASUS PRIME RTX 5080 16GB"))

    def test_mapping_uses_same_number_photo(self):
        self.assertEqual(AC.part_thumbnail(129630, "ASUS PRIME RTX 5070 Ti OC 16GB 코잇"), "https://www.popcornpc.co.kr/data/pimg/129/129630_600.jpg")
        self.assertEqual(AC.part_thumbnail(122148, "ASUS ProArt X870E-CREATOR WIFI 대원"), "assets/images/parts/mall-122148.webp")

    def test_rejected_image_path_becomes_name_only(self):
        models = public_all()
        models[0]["parts"][0]["options"][0]["image"] = "https://evil.example/x.png"
        self.assertIsNone(normalize(models)[0]["parts"][0]["options"][0]["image"])


class DetailScreen(unittest.TestCase):
    def body(self):
        return PAGES[PAGES.index("function partRow"):PAGES.index("function detailPage")]

    def test_detail_renders_no_price(self):
        for word in PRICE_WORDS:
            self.assertNotIn(word, self.body(), word)
        self.assertNotIn("가격", (MVP4 / "asus-pc.html").read_text(encoding="utf-8"))

    def test_thumbnail_failure_removes_image(self):
        self.assertIn("img.addEventListener('error', drop)", self.body())
        self.assertIn("guardThumbs(root)", self.body())

    def test_list_keeps_plan_label(self):
        self.assertIn("specRows(m) + planBlock(m)", PAGES)


class Banner(unittest.TestCase):
    def test_asus_first_six_seconds_others_default(self):
        self.assertEqual(re.findall(r"\{key:'(\w+)',", CAROUSEL)[0], "asus")
        self.assertEqual(re.findall(r"duration:(\d+)", CAROUSEL), ["6000"])
        self.assertIn("var interval=3000", CAROUSEL)
        self.assertIn("Number(panels[index].dataset.hcDuration)||interval", CAROUSEL)
        self.assertNotIn("후보", CAROUSEL)


if __name__ == "__main__":
    unittest.main()
