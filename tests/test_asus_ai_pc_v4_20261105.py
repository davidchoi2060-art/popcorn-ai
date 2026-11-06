"""ASUS AI PC 기획전 v4 + GT502 소재 v5 정적 계약 (2026-11-05 사용자 승인 범위 · 2026-11-06 DB 원천 전환 반영).

브라우저 없이 데이터·문구의 약속을 고정한다. 모델 값은 이제 초깃값 파일(0178)에 있고 화면 코드에는 없다.
저장·재조회·화면 반영은 tests/test_asus_campaign_20261106.py(격리 스키마)와
tests/scenarios/asus_campaign_browser.cjs(CI 일회용 DB + Chrome)가 확인한다.
"""
import hashlib
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MVP4 = ROOT / "mockups/mvp4"
FILES = [MVP4 / n for n in ("asus.html", "asus-pc.html", "asus-consult.html", "assets/js/asus-data.js", "assets/js/asus-pages.js", "assets/js/asus-inquiry.js", "assets/css/asus.css")]
CODE = (MVP4 / "assets/js/asus-data.js").read_text(encoding="utf-8")
PAGES = (MVP4 / "assets/js/asus-pages.js").read_text(encoding="utf-8")
INQUIRY = (MVP4 / "assets/js/asus-inquiry.js").read_text(encoding="utf-8")
CAROUSEL = (MVP4 / "assets/js/home-carousel.js").read_text(encoding="utf-8")
SEED_FILE = ROOT / "db/migrations/data/asus_campaign_models_20261106.json"
SEED_TEXT = SEED_FILE.read_text(encoding="utf-8")
MODELS = json.loads(SEED_TEXT)["models"]
ALL = "\n".join(f.read_text(encoding="utf-8") for f in FILES) + SEED_TEXT


def part(model, label):
    return next(p for p in MODELS[model]["content"]["parts"] if p["label"] == label)


def options():
    for m in MODELS.values():
        for p in m["content"]["parts"]:
            yield from p["options"]


class AsusContract(unittest.TestCase):
    def test_case_is_gt502_black_and_no_gt302_or_old_reference_price(self):
        for m in MODELS:
            self.assertEqual(part(m, "케이스")["head"], "ASUS TUF Gaming GT502 BLACK")
        for gone in ("GT302", "176,000", "176000", "103,136", "103136"):
            self.assertNotIn(gone, ALL, gone)

    def test_v5_assets_replace_self_made_build_images(self):
        for gone in ("gt502-build-", "gpu-render", "banner-home", "bg-hero"):
            self.assertNotIn(gone, ALL + CAROUSEL, gone)
        for name in ("gt502-black-cutout.webp", "hero-desktop.webp", "hero-mobile.webp"):
            self.assertTrue((MVP4 / "assets/images/asus" / name).is_file(), name)
        self.assertIn("제품 이미지는 연출이며 실제 구성과 다를 수 있습니다.", CODE)
        self.assertIn("제품 이미지는 연출이며 실제 구성과 다를 수 있습니다.", CAROUSEL)
        self.assertNotIn("조립 연출", ALL + CAROUSEL)

    def test_gpu_label_is_one_value_per_model(self):
        self.assertEqual(part("business", "GPU(그래픽카드)")["head"], "ASUS PRIME RTX 5070 Ti 16GB")
        self.assertEqual(part("video", "GPU(그래픽카드)")["head"], "ASUS PRIME RTX 5080 16GB")
        self.assertEqual(part("local-ai", "GPU(그래픽카드)")["head"], "ASUS TUF RTX 5090 32GB")
        oc = next(o for o in part("business", "GPU(그래픽카드)")["options"] if " OC " in o["name"])
        self.assertEqual((oc["name"], oc["state"], oc["price"], oc["premium"], oc["note"]),
                         ("ASUS PRIME RTX 5070 Ti OC 16GB 코잇", "candidate", 2100300, 2047790, "OC 후보. 비OC와 다른 상품입니다."))

    def test_unconfirmed_supply_has_no_price(self):
        for model, label, name in (("video", "GPU(그래픽카드)", "ASUS PRIME RTX 5080 16GB"),
                                   ("local-ai", "GPU(그래픽카드)", "ASUS TUF RTX 5090 32GB"),
                                   ("business", "CPU 쿨러", "ASUS PRIME LC 360 ARGB")):
            o = part(model, label)["options"][0]
            self.assertEqual((o["name"], o["state"], o["price"], o["premium"]), (name, "supply", None, None))

    def test_teamgroup_conflict_is_not_confirmable(self):
        team = [o for o in options() if "TeamGroup" in o["name"]]
        self.assertEqual(len(team), 3)    # 64GB 는 문서·업무 · 영상 각 한 줄, 128GB 는 로컬 AI 한 줄
        self.assertEqual({o["state"] for o in team}, {"conflict"})

    def test_plan_price_label_and_no_summing(self):
        self.assertEqual({k: v["plan_review_price"] for k, v in MODELS.items()},
                         {"business": 3990000, "video": 5990000, "local-ai": 12990000})
        self.assertIn("PLAN_LABEL: '기획 검토가 · ASUS 협의 전'", CODE)
        self.assertNotIn("reduce(", PAGES)
        self.assertNotRegex(PAGES, r"\.price\s*\+|\.plan\s*\+\s*\w+\.")

    def test_required_rows_for_every_model(self):
        for m in MODELS:
            labels = [p["label"] for p in MODELS[m]["content"]["parts"]]
            for label in ("메인보드", "파워(PSU)", "운영체제", "케이스", "CPU 쿨러", "그래픽 메모리", "추가 시스템팬"):
                self.assertIn(label, labels)
            self.assertEqual(part(m, "그래픽 메모리")["options"], [])
            self.assertEqual(part(m, "운영체제")["status"], "separate")

    def test_copy_corrections(self):
        for text in ("문서를 많이 다루는 분", "고객 문의를 담당하는 분", "개인 업무에 AI를 써 보고 싶은 분", "영상 편집자", "강의·인터뷰 제작자", "홍보 이미지 제작자", "로컬 AI 개발용 PC", "모든 AI 모델이 실행되는 것은 아닙니다."):
            self.assertIn(text, SEED_TEXT, text)
        for text in ("사용 프로그램과 AI 모델, 설정에 따라 결과가 달라집니다.", "['용도 상담', '구성 검토', 'ASUS 가격 확정']"):
            self.assertIn(text, CODE, text)
        self.assertGreaterEqual(PAGES.count("PC 구성 문의하기"), 2)
        for banned in ("최적화", "완벽한", "혁신적인", "쾌적하게", "원활하게", "자동화"):
            self.assertNotIn(banned, CODE + PAGES + SEED_TEXT, banned)

    def test_text_is_html_not_clickmap(self):
        self.assertNotIn("<area", ALL)
        self.assertNotIn("usemap", ALL)

    def test_home_slide_keeps_existing_and_links_to_asus(self):
        self.assertIn("{key:'asus',", CAROUSEL)
        self.assertIn("action('ASUS 기획전 보기','asus.html')", CAROUSEL)
        self.assertIn("title:'ASUS의 강력한 성능,<br>나의 AI 작업실.'", CAROUSEL)
        import re
        keys = re.findall(r"\{key:'(\w+)',", CAROUSEL)
        self.assertEqual(keys, ["asus", "showcase", "gaming", "ai", "people", "collection", "supercomputer"])

    def test_inquiry_reuses_existing_flow_without_own_transport(self):
        html = (MVP4 / "asus-consult.html").read_text(encoding="utf-8")
        self.assertIn('data-page="ai-consult"', html)
        for script in ("assets/js/service-adapters.js", "assets/js/ai-inquiry.js", "assets/js/asus-inquiry.js"):
            self.assertIn(script, html)
        self.assertLess(html.index("ai-inquiry.js"), html.index("asus-inquiry.js"))
        for banned in ("fetch(", "XMLHttpRequest", "sendBeacon", ".submit("):
            self.assertNotIn(banned, INQUIRY + PAGES, banned)
        # 어댑터의 요청은 기획전 읽기 GET 하나뿐이다.
        self.assertEqual(CODE.count("fetch("), 1)
        self.assertIn("fetch(API, { method: 'GET'", CODE)
        for banned in ("XMLHttpRequest", "sendBeacon", ".submit(", "'POST'"):
            self.assertNotIn(banned, CODE, banned)

    def test_v5_source_hashes_recorded(self):
        doc = (ROOT / "docs/asus-ai-pc-v4/ASSETS.md").read_text(encoding="utf-8")
        for digest in ("1E4751EDB978744B142F4E94C707233D7C63720DDF9C83F3826B2B3351AE428C", "BA527A3AB78A4A2CD4F7F690DCF6A928CC031032D56242C1CDF9FC9FB18887FB", "35E386B350B310C0911CA7CFBDA3D39FBC61A052F053CEE0BDBFC8FD8E08EA23"):
            self.assertIn(digest, doc)
        for path in sorted((MVP4 / "assets/images/asus").iterdir()):
            self.assertIn(hashlib.sha256(path.read_bytes()).hexdigest().upper(), doc, path.name)


if __name__ == "__main__":
    unittest.main()
