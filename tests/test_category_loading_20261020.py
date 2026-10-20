"""카테고리별 로딩 1안 · AI 대화 응답 대기 (2026-10-20 대표 「카테고리별 로딩은 1안으로, AI 대화는 마지막 시안을 작게 해서 애니메이션」)."""
import hashlib
import json
import pathlib
import re
import unittest

MVP4 = pathlib.Path(__file__).resolve().parents[1] / 'mockups/mvp4'
read = lambda f: (MVP4 / f).read_text(encoding='utf-8')


class Loading(unittest.TestCase):
    def test_four_category_texts(self):
        js = read('assets/js/category-loading.js')
        for t in ('PC 상품을 불러오고 있어요', 'AI 패키지를 불러오고 있어요', 'AI 슈퍼컴퓨터를 불러오고 있어요', '대화 화면을 준비하고 있어요'):
            self.assertIn(t, js)
        self.assertNotRegex(re.sub(r'/\*.*?\*/|//[^\n]*', '', js, flags=re.S), r'%|남은 시간|setTimeout')        # 진행률·남은 시간·인위적 대기 없음

    def test_screens_use_it_only_while_loading(self):
        self.assertIn("P.categoryLoading('pc'", read('assets/js/design-products.js'))
        self.assertIn("state === 'loading' && P.categoryLoading", read('assets/js/supercomputer-list.js'))
        self.assertIn("P.categoryLoading('package')", read('assets/js/ai-package-devices.js'))
        self.assertIn("P.categoryLoading('chat'", read('assets/js/design-boot.js'))

    def test_chat_wait_small_and_tied_to_request(self):
        conv = read('assets/js/design-conversation.js')
        self.assertIn("if (model.state === 'loading') return '<div class=\"dc-state-box dc-loading dc-wait\"", conv)
        self.assertIn('답변을 준비하고 있어요', conv)
        self.assertIn('data-dc-action="stop"', conv)
        css = read('assets/css/category-loading.css')
        self.assertIn('width:96px;height:96px', css)
        self.assertIn('width:72px;height:72px', css)
        self.assertIn('prefers-reduced-motion:reduce', css)

    def test_assets_match_sources(self):
        meta = json.loads(read('assets/images/loading/SOURCES.json'))
        for im in meta['images']:
            self.assertEqual(hashlib.sha256((MVP4 / im['file']).read_bytes()).hexdigest(), im['sha256'])

    def test_loaded_before_screens(self):
        for page, screen in (('index.html', 'design-products.js'), ('supercomputers.html', 'supercomputer-list.js'), ('ai-packages.html', 'ai-package-devices.js')):
            html = read(page)
            self.assertLess(html.index('category-loading.js'), html.index(screen), page)


if __name__ == '__main__':
    unittest.main()
