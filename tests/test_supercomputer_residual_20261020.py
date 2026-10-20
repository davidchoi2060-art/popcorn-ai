"""/mvp4 AI 슈퍼컴퓨터 잔여 3건 + X01 격리 재현(2026-10-20 대표 요청) — R01 검색 범위 · R02 모델 변경 · R03 목록 복귀 · X01 fixture."""
import hashlib
import json
import os
import pathlib
import re
import unittest

os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg2://x:x@127.0.0.1:1/x')
from api import customer_supercomputer as SC  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
MVP4 = ROOT / 'mockups/mvp4'
read = lambda f: (MVP4 / f).read_text(encoding='utf-8')
code = lambda s: re.sub(r'/\*.*?\*/', '', s, flags=re.S)


class R01SearchScope(unittest.TestCase):
    def test_counts_are_split_and_not_generic(self):
        src = read('assets/js/catalog-ai-devices.js')
        self.assertIn('조립PC ', src)
        self.assertIn('조립PC에서는', src)
        self.assertIn('조립PC와 AI 슈퍼컴퓨터 모두에서', src)
        self.assertIn('아래 조립PC 목록에만 적용돼요', src)
        self.assertIn("sale !== 'all' && p.saleState === 'stopped'", code(src))


class R02ModelChange(unittest.TestCase):
    def test_keeps_section_and_ignores_late_responses(self):
        src = code(read('assets/js/supercomputer-detail.js'))
        self.assertIn('seq !== loadSeq', src)
        self.assertIn('afterModelChange', src)
        self.assertIn('.sc-product-hero', src)
        self.assertIn('settle(toHash, seq)', src)   # 늦은 배치 변화에도 구획 유지(2026-10-20)


class R03ListReturn(unittest.TestCase):
    def test_restores_filter_and_card_position(self):
        src = code(read('assets/js/supercomputer-list.js'))
        for s in ('filterOpen', 'cardTop', "scrollRestoration = 'manual'", 'ResizeObserver', "'touchstart'"):
            self.assertIn(s, src)


class X01Backend(unittest.TestCase):
    def test_reader_only_returns_visible_products(self):
        self.assertIn('AND p.is_visible', (ROOT / 'api/customer_supercomputer.py').read_text(encoding='utf-8'))

    def test_os_is_never_derived_from_name(self):
        auto = SC.derive('ASUS Ascent GX10 GB10 (128GB, M.2 4TB)', 'ASUS')
        self.assertIsNone(auto.get('os'))

    def test_fixture_manifest_matches(self):
        d = ROOT / 'tools/x01_harness/fixtures'
        man = json.loads((d / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(man), 11)
        for name, sha in man.items():
            self.assertEqual(hashlib.sha256((d / name).read_bytes()).hexdigest(), sha, name)


if __name__ == '__main__':
    unittest.main()
