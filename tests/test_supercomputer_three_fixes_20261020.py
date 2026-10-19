"""/mvp4 AI 슈퍼컴퓨터 3건(2026-10-20 대표 요청) — F04 검색 · F05 상세 메뉴 이동 · X01 광고와 제품군 연결의 소스 계약."""
import pathlib
import re
import unittest

MVP4 = pathlib.Path(__file__).resolve().parents[1] / 'mockups/mvp4'
read = lambda f: (MVP4 / f).read_text(encoding='utf-8')
code = lambda s: re.sub(r'/\*.*?\*/', '', s, flags=re.S)


class F04Search(unittest.TestCase):
    def test_catalog_search_also_finds_ai_devices(self):
        src = read('assets/js/catalog-ai-devices.js')
        self.assertIn('P.designScreens.catalog', src)
        self.assertIn("'supercomputer.html?id='", code(src).replace('"', "'"))
        for field in ('p.officialName', 'p.id', 'p.maker', 'p.modelName', 'p.accelerator'):
            self.assertIn(field, src)
        self.assertNotRegex(code(src), r'1296(14|15)')

    def test_loaded_on_main_before_boot(self):
        index = read('index.html')
        self.assertLess(index.index('live-supercomputer.js'), index.index('catalog-ai-devices.js'))
        self.assertLess(index.index('catalog-ai-devices.js'), index.index('design-boot.js'))


class F05Anchors(unittest.TestCase):
    def test_same_product_hash_change_does_not_reload(self):
        src = code(read('assets/js/supercomputer-detail.js'))
        self.assertIn('if (product && nextId === id && nextQ === q) { toHash(); return; }', src)
        self.assertIn("'.sc-section-nav a, a[href^=\"#sc-\"]'", src)
        self.assertIn('scrollToSection(target)', src)


class X01AdFamily(unittest.TestCase):
    def test_home_ad_models_are_limited_to_the_gb10_family(self):
        src = code(read('assets/js/supercomputer-home.js'))
        self.assertIn("var AD_GROUP = 'dell-pro-max-gb10';", src)
        self.assertIn("p.modelGroup === AD_GROUP && p.saleState !== 'stopped'", src)
        self.assertIn('a.hidden = !list.length', src)          # 제품군이 없으면 대표 버튼을 감춘다


if __name__ == '__main__':
    unittest.main()
