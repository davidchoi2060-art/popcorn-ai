"""/mvp4 LLM 표시 2안(2026-10-20 대표 선택) — 상단 4메뉴 · 기본 낮은 가격순 · 설치 가능 AI 예시 · 상세 활용 예시 · AI 패키지 아래 판매 제품의 소스 계약."""
import json
import pathlib
import re
import unittest

MVP4 = pathlib.Path(__file__).resolve().parents[1] / 'mockups/mvp4'
read = lambda f: (MVP4 / f).read_text(encoding='utf-8')
code = lambda s: re.sub(r'/\*.*?\*/', '', s, flags=re.S)


class Menu(unittest.TestCase):
    def test_primary_order(self):
        src = code(read('assets/js/header-ui.js'))
        order = [src.index(s) for s in ("navLink('PC 쇼핑'", "navLink('AI 패키지'", "navLink('AI 슈퍼컴퓨터'", "'<span>AI로 PC 찾기</span>'")]
        self.assertEqual(order, sorted(order))
        self.assertIn("page = 'supercomputers'", src)


class DefaultSort(unittest.TestCase):
    def test_list_and_package_default_to_low_price(self):
        for f in ('assets/js/supercomputer-list.js', 'assets/js/ai-package-devices.js'):
            src = code(read(f))
            self.assertIn("DEFAULT_SORT = 'price-asc'", src, f)
            self.assertIn('if (px === null) return 1;', src, f)   # 가격 확인 필요는 뒤로


class LlmExamples(unittest.TestCase):
    def setUp(self):
        self.src = read('assets/js/llm-examples.js')

    def test_wording_and_models(self):
        for s in ('설치 가능 AI 예시', '작은 AI부터 큰 모델까지, <em>내 장비에서.</em>', '어떤 모델이 맞을지 몰라도 괜찮아요.',
                  '모델과 설치 구성은 전문상담사가 함께 맞춰드립니다.', "'Llama 3.1', size: '8B'", "'Qwen3', size: '32B'", "'gpt-oss', size: '20B'", "'gpt-oss', size: '120B'", '실행 도구'):
            self.assertIn(s, self.src)
        self.assertIn('AI의 답변 예시', self.src)
        self.assertIn('질문 예시', self.src)

    def test_no_guarantee_or_stock_claims(self):
        body = code(self.src)
        for bad in ('사전 설치', '설치 완료', '공식 인증', '파트너', '즉시 배송', '재고', '보장', 'Choose your local AI'):
            self.assertNotIn(bad, body)

    def test_only_gb10_gets_models(self):
        self.assertIn('GB10', code(self.src))
        self.assertIn('DGX', code(self.src))

    def test_logos_are_files_with_provenance(self):
        prov = json.loads(read('assets/icons/llm/provenance.json'))
        for f in ('meta.svg', 'qwen.svg', 'ollama.svg'):
            self.assertTrue((MVP4 / 'assets/icons/llm' / f).exists())
            self.assertIn(f, prov['files'])
            self.assertIn(f, self.src)
        self.assertNotIn('openai', [p.stem for p in (MVP4 / 'assets/icons/llm').glob('*.svg')])


class Wiring(unittest.TestCase):
    def test_pages_load_scripts(self):
        for page, script in (('supercomputers.html', 'supercomputer-list.js'), ('supercomputer.html', 'supercomputer-detail.js'), ('ai-packages.html', 'ai-package-devices.js')):
            html = read(page)
            self.assertLess(html.index('llm-examples.js'), html.index(script), page)
            self.assertIn('llm-examples.css', html, page)
        self.assertLess(read('ai-packages.html').index('live-supercomputer.js'), read('ai-packages.html').index('ai-package-devices.js'))

    def test_detail_replaces_abstract_section_and_keeps_consult_links(self):
        src = code(read('assets/js/supercomputer-detail.js'))
        self.assertIn("P.llmExamples.section(p, route('adoption'))", src)
        self.assertIn('data-sc-action="quote"', src)
        self.assertIn('<a href="#sc-usecases">활용 예시</a>', src)


if __name__ == '__main__':
    unittest.main()
