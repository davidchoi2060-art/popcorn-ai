"""/mvp4 카테고리별 진입 로딩 1안(2026-10-20 대표 선택) — 문구·그림·연결의 소스 계약."""
import json
import pathlib
import re
import unittest

MVP4 = pathlib.Path(__file__).resolve().parents[1] / 'mockups/mvp4'
read = lambda f: (MVP4 / f).read_text(encoding='utf-8')
code = lambda s: re.sub(r'/\*.*?\*/', '', s, flags=re.S)


class PageLoading(unittest.TestCase):
    def test_kinds_and_wording(self):
        src = read('assets/js/page-loading.js')
        for s in ('PC 상품을 불러오고 있어요', 'AI 패키지를 불러오고 있어요', 'AI 슈퍼컴퓨터를 불러오고 있어요', '대화 화면을 준비하고 있어요'):
            self.assertIn(s, src)
        for bad in ('%', '남은 시간', 'setTimeout'):
            self.assertNotIn(bad, code(src))   # 진행률·인위적 대기 없음

    def test_assets_and_provenance(self):
        prov = json.loads(read('assets/images/loading/provenance.json'))
        self.assertIn('0e2aaa75b8b8eb99b44cd1fa32763f7a5047d41f21b404f7b5c4937893be667a', prov['note'])
        for f in ('pc.png', 'super.png', 'chat.png'):
            self.assertTrue((MVP4 / 'assets/images/loading' / f).exists())
            self.assertIn(f, prov['files'])

    def test_reduced_motion(self):
        self.assertIn('prefers-reduced-motion:reduce', read('assets/css/page-loading.css'))

    def test_wired_into_pages(self):
        self.assertIn("P.pageLoading.head('pc')", read('assets/js/design-products.js'))
        self.assertIn("P.pageLoading.head('super')", read('assets/js/supercomputer-list.js'))
        self.assertIn("P.pageLoading.head('super', true)", read('assets/js/ai-package-devices.js'))
        idx = read('index.html')
        self.assertLess(idx.index('page-loading.js'), idx.index('design-products.js'))
        self.assertIn('AI 패키지를 불러오고 있어요', read('ai-packages.html'))
        self.assertIn('page-loading.js', read('supercomputers.html'))


if __name__ == '__main__':
    unittest.main()
