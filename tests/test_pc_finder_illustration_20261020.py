"""AI로 PC 찾기 시작 화면 그림 3안 (2026-10-20 대표 「3번이 좋네.. 기존 문구랑 입력창은 그대로 두고」)."""
import hashlib
import json
import pathlib
import unittest

MVP4 = pathlib.Path(__file__).resolve().parents[1] / 'mockups/mvp4'


class Illustration(unittest.TestCase):
    def test_decorative_image_in_welcome_only(self):
        js = (MVP4 / 'assets/js/design-conversation.js').read_text(encoding='utf-8')
        self.assertIn('<img class="dc-welcome-art" src="assets/images/pc-finder-core-v3.webp" width="618" height="496" alt="" aria-hidden="true"', js)
        for kept in ('어떤 PC가 필요하세요?', '하고 싶은 일부터 편하게 이야기해 주세요.', "'용도와 예산을 편하게 알려주세요.'", '/ 10,000자 · Shift+Enter 줄바꿈'):
            self.assertIn(kept, js)
        css = (MVP4 / 'assets/css/design-conversation.css').read_text(encoding='utf-8')
        self.assertIn('pointer-events:none', css[css.index('.dc-welcome>.dc-welcome-art'):])

    def test_asset_matches_provenance(self):
        meta = json.loads((MVP4 / 'assets/images/pc-finder-core-v3.provenance.json').read_text(encoding='utf-8'))
        data = (MVP4 / meta['file']).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), meta['sha256'])


if __name__ == '__main__':
    unittest.main()
