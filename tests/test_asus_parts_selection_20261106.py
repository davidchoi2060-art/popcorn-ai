"""ASUS 고객 구성표: 항목마다 대표 제품 1종(2026-11-06 사용자 지시).

parts[].options 는 비교 후보 목록이다. 그대로 나열하면 GPU 2장 · SSD 3개로 읽힌다. 고객 표는 선정표(BUILD_PICKS)로 만든
build 만 쓰고, 저장값이 선정표와 어긋나면 다른 후보로 넘어가지 않고 중립 문구를 낸다. DB 원본(options)은 그대로다.
"""
import copy
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
SEED = AC.seed_models()
CPU, GPU, VRAM, RAM, SSD, BOARD, PSU, CASE, COOLER, FAN, OS = AC.PART_LABELS

# 사람이 원기획과 대조해 정한 값. 선정표에서 복사하지 않고 따로 적어 둔다.
EXPECTED = {
    "business": {
        CPU: ("Ryzen 9 9900X 멀티팩 정품", "1개"), GPU: ("ASUS PRIME RTX 5070 Ti 16GB 코잇", "1장"),
        RAM: ("삼성 DDR5-5600 64GB [32G×2]", "32GB × 2개 · 합계 64GB"), SSD: ("BIWIN M350 M.2 NVMe 2TB", "1개"),
        BOARD: ("ASUS TUF Gaming B850-PLUS WIFI 인텍", "1개"), PSU: ("ASUS ROG STRIX 850W Platinum 인텍", "1개"),
        CASE: ("ASUS TUF Gaming GT502 BLACK", "1개"), COOLER: ("ASUS PRIME LC 360 ARGB", "1개"),
    },
    "video": {
        CPU: ("Ryzen 9 9950X 벌크", "1개"), GPU: ("ASUS PRIME RTX 5080 16GB", "1장"),
        RAM: ("삼성 DDR5-5600 64GB [32G×2]", "32GB × 2개 · 합계 64GB"), SSD: ("BIWIN M350 M.2 NVMe 2TB", "1개"),
        BOARD: ("ASUS TUF Gaming B850-PLUS WIFI 인텍", "1개"), PSU: ("ASUS TUF Gaming 1000W GOLD", "1개"),
        CASE: ("ASUS TUF Gaming GT502 BLACK", "1개"), COOLER: ("ASUS PRIME LC 360 ARGB", "1개"),
    },
    "local-ai": {
        CPU: ("Ryzen 9 9950X 벌크", "1개"), GPU: ("ASUS TUF RTX 5090 32GB", "1장"),
        RAM: ("삼성 DDR5-5600 128GB [32G×4]", "32GB × 4개 · 합계 128GB"), SSD: ("BIWIN M350 M.2 NVMe 2TB", "1개"),
        BOARD: ("ASUS ProArt X870E-CREATOR WIFI 대원", "1개"), PSU: ("ASUS ROG STRIX 1200W Platinum", "1개"),
        CASE: ("ASUS TUF Gaming GT502 BLACK", "1개"), COOLER: ("ASUS PRIME LC 360 ARGB", "1개"),
    },
}
EXCLUDED = ("OC 16GB", "TeamGroup", "킹스톤", "Crucial", "KLEVV", "B850M", "850G", "미정")


def content(model_id):
    return copy.deepcopy(SEED[model_id]["content"])


def public(model_id, c=None):
    return AC.public_model(model_id, SEED[model_id]["plan_review_price"], c or content(model_id))


def row(model, label):
    return next(r for r in model["build"] if r["label"] == label)


def part(c, label):
    return next(p for p in c["parts"] if p["label"] == label)


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


class Selection(unittest.TestCase):
    def test_exact_product_and_quantity_per_model(self):
        for model_id, expected in EXPECTED.items():
            products = {r["label"]: (r["name"], r["quantity"]) for r in public(model_id)["build"] if r["kind"] == "product"}
            self.assertEqual(products, expected, model_id)

    def test_every_label_appears_once_and_non_parts_are_not_products(self):
        for model_id in EXPECTED:
            build = public(model_id)["build"]
            self.assertEqual(tuple(r["label"] for r in build), AC.PART_LABELS)
            self.assertEqual(sum(r["kind"] == "product" for r in build), 8)
            names = [r["name"] for r in build if r["kind"] == "product"]
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual((row({"build": build}, FAN)["kind"], row({"build": build}, FAN)["name"]), ("notice", "상담 시 안내"))
            self.assertEqual((row({"build": build}, OS)["kind"], row({"build": build}, OS)["name"]), ("notice", "정품 Windows 별도"))
            self.assertEqual(row({"build": build}, VRAM)["kind"], "spec")

    def test_selection_does_not_depend_on_option_order(self):
        # 850G 는 options[0] 이지만 원기획이 「선정 금지」로 적었다.
        self.assertIn("850G", part(content("business"), PSU)["options"][0]["name"])
        for model_id in EXPECTED:
            c = content(model_id)
            for p in c["parts"]:
                p["options"].reverse()
            self.assertEqual(public(model_id, c)["build"], public(model_id)["build"], model_id)

    def test_excluded_candidates_stay_in_db_but_not_in_build(self):
        for model_id in EXPECTED:
            model = public(model_id)
            text = json.dumps(model["build"], ensure_ascii=False)
            for word in EXCLUDED:
                self.assertNotIn(word, text, (model_id, word))
        self.assertEqual(len(part(public("business"), GPU)["options"]), 2)   # API 원본 보존
        self.assertEqual(len(part(public("business"), SSD)["options"]), 3)

    def test_build_has_no_price_state_or_note(self):
        for model_id in EXPECTED:
            for r in public(model_id)["build"]:
                self.assertEqual(set(r), {"label", "kind", "name", "quantity", "image"})
                self.assertNotRegex(r["name"], r"후보|확인|미정|불일치")

    def test_seed_has_every_pick_in_an_allowed_state(self):
        for model_id, picks in AC.BUILD_PICKS.items():
            for label, (head, mall_no, name, _q) in picks.items():
                p = part(SEED[model_id]["content"], label)
                self.assertEqual(p["head"], head)
                match = [o for o in p["options"] if (o["mall_no"], o["name"]) == (mall_no, name)]
                self.assertEqual(len(match), 1, name)
                self.assertNotEqual(match[0]["state"], "conflict")


class Consistency(unittest.TestCase):
    def test_ram_capacity_matches_quantity_and_headline(self):
        for model_id, total in (("business", 64), ("video", 64), ("local-ai", 128)):
            model = public(model_id)
            r = row(model, RAM)
            each, count, shown = re.fullmatch(r"(\d+)GB × (\d+)개 · 합계 (\d+)GB", r["quantity"]).groups()
            self.assertEqual(int(each) * int(count), total)
            self.assertEqual(int(shown), total)
            self.assertIn(f"{total}GB [{each}G×{count}]", r["name"])
            self.assertEqual(model["ram"], f"{total}GB DDR5")

    def test_selected_product_matches_headline(self):
        for model_id in EXPECTED:
            model = public(model_id)
            self.assertIn(model["cpu"], row(model, CPU)["name"])
            self.assertTrue(row(model, GPU)["name"].startswith(model["gpu"]), model_id)
            self.assertNotIn(" OC ", row(model, GPU)["name"])
            self.assertEqual(row(model, VRAM)["name"], model["vram"])
            for word in model["ssd"].split():
                self.assertIn(word, row(model, SSD)["name"])
        self.assertIn("850W", row(public("business"), PSU)["name"])
        self.assertIn("1000W", row(public("video"), PSU)["name"])
        self.assertIn("1200W", row(public("local-ai"), PSU)["name"])
        self.assertIn("B850", row(public("business"), BOARD)["name"])
        self.assertIn("X870E", row(public("local-ai"), BOARD)["name"])

    def test_every_selected_product_has_its_own_photo(self):
        for model_id, picks in AC.BUILD_PICKS.items():
            model = public(model_id)
            for label, (_h, mall_no, name, _q) in picks.items():
                image = row(model, label)["image"]
                self.assertTrue(image, name)
                self.assertEqual(image, AC.part_thumbnail(mall_no, name))
                if not image.startswith("https://"):
                    self.assertTrue((MVP4 / image).is_file(), image)

    def test_customer_adapter_keeps_rows_and_drops_options(self):
        models = normalize([public(m) for m in EXPECTED])
        for m in models:
            self.assertEqual(m["caseName"], "ASUS TUF Gaming GT502 BLACK")
            self.assertEqual(m["coolerName"], "ASUS PRIME LC 360 ARGB")
            self.assertEqual({r["label"]: (r["name"], r["quantity"]) for r in m["parts"] if r["kind"] == "product"}, EXPECTED[m["id"]])
            for r in m["parts"]:
                self.assertEqual(set(r), {"label", "kind", "name", "quantity", "image"})

    def test_screen_code_never_reads_candidate_list(self):
        for name in ("asus-data.js", "asus-pages.js", "asus-inquiry.js", "asus-cart.js"):
            src = (MVP4 / "assets/js" / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\.options\b", src.replace("(parts[].options)", "")), name)


class WrongProductIsNeverForced(unittest.TestCase):
    """저장값이 선정표와 어긋나면 다른 후보를 고르지 않고 중립 문구를 낸다."""

    def assertNeutral(self, model, label):
        r = row(model, label)
        self.assertEqual(r, {"label": label, "kind": "notice", "name": "상담 시 안내", "quantity": None, "image": None})

    def test_pick_removed(self):
        c = content("business")
        p = part(c, PSU)
        p["options"] = [o for o in p["options"] if "Platinum" not in o["name"]]
        self.assertNeutral(public("business", c), PSU)

    def test_pick_renamed_or_number_changed(self):
        c = content("business"); part(c, GPU)["options"][0]["name"] = "ASUS PRIME RTX 5070 Ti 16GB 새상품"
        self.assertNeutral(public("business", c), GPU)
        c = content("business"); part(c, GPU)["options"][0]["mall_no"] = 129630
        self.assertNeutral(public("business", c), GPU)

    def test_pick_marked_conflict_or_separate(self):
        for state in ("conflict", "separate"):
            c = content("local-ai")
            o = next(x for x in part(c, RAM)["options"] if "삼성" in x["name"])
            o.update(state=state, price=None, premium=None)
            self.assertNeutral(public("local-ai", c), RAM)

    def test_head_changed_means_selection_is_stale(self):
        c = content("video"); part(c, GPU)["head"] = "ASUS PRIME RTX 5090 32GB"
        self.assertNeutral(public("video", c), GPU)
        c = content("video"); part(c, VRAM)["head"] = "32GB"
        self.assertNeutral(public("video", c), VRAM)

    def test_new_cheaper_candidate_is_not_shown(self):
        c = content("business")
        part(c, SSD)["options"].insert(0, {"name": "새 SSD 2TB", "state": "candidate", "price": 1000, "premium": None, "note": "", "mall_no": 1})
        self.assertEqual(row(public("business", c), SSD)["name"], "BIWIN M350 M.2 NVMe 2TB")

    def test_adapter_blocks_internal_wording_and_bad_shape(self):
        m = public("business")
        row(m, SSD).update(name="최종 모델 미확정")
        self.assertEqual({k: row({"build": normalize([m])[0]["parts"]}, SSD)[k] for k in ("kind", "name", "quantity", "image")},
                         {"kind": "notice", "name": "상담 시 안내", "quantity": None, "image": None})
        bad = public("business"); del bad["build"]
        with self.assertRaises(AssertionError):
            normalize([bad])
        bad = public("business"); bad["build"][0]["kind"] = "option"
        with self.assertRaises(AssertionError):
            normalize([bad])


class Docs(unittest.TestCase):
    def test_audit_table_lists_every_pick_and_excluded_candidate(self):
        doc = (ROOT / "docs/asus-ai-pc-v4/PARTS-SELECTION.md").read_text(encoding="utf-8")
        for model_id, row_map in EXPECTED.items():
            for name, _q in row_map.values():
                self.assertIn(name, doc, (model_id, name))
        for model in SEED.values():
            for p in model["content"]["parts"]:
                for o in p["options"]:
                    if o["mall_no"]:
                        self.assertIn(str(o["mall_no"]), doc, o["name"])


if __name__ == "__main__":
    unittest.main()
