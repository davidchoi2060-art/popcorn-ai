"""인계 기록 · 유입 성과의 /mvp4 안내 한 줄(2026-10-31 관리자단 개선 PR-3) — DB 없이 확인하는 것.

/mvp4 는 일반 완제품의 「팝콘PC몰에서 바로 구매」가 몰 상품 페이지를 바로 열어 서버에 이동 기록이 남지 않는다(2026-10-20 구매 경로
변경). 두 화면의 이동 수가 /mvp4 에 대해 0 으로 보이는 이유를 서버 문장 하나로 밝힌다. 이 테스트는 ① 문장이 한 곳에서만
정의되어 두 화면이 같은 것을 쓰는지 ② 화면이 그것을 textContent 로만 보이는지 ③ 「/mvp4 는 인계 API 를 부르지 않는다」는
전제가 지금도 사실인지(고객 화면 코드 대조) 본다 — 전제가 바뀌면 이 테스트가 먼저 깨져 문장을 다시 보게 한다.
"""
import pathlib
import re
import unittest

from api import admin_funnel as F
from api import admin_ui_handoff_log as H

ROOT = pathlib.Path(__file__).resolve().parents[1]
MVP4_JS = sorted((ROOT / 'mockups/mvp4').rglob('*.js'))


class OneSentence(unittest.TestCase):
    def test_defined_once_and_used_by_both_screens(self):
        self.assertIs(H.MVP4_HANDOFF_NOTE, F.MVP4_HANDOFF_NOTE)
        self.assertIn(F.MVP4_HANDOFF_NOTE, F.MVP3_BASIS)
        self.assertEqual(F.MVP3_BASIS.count(F.MVP4_HANDOFF_NOTE), 1)
        for word in ('/mvp4', '기록되지 않습니다', '2026-10-20', '보관 견적에서 몰로 넘어간 기록만'):
            self.assertIn(word, F.MVP4_HANDOFF_NOTE)

    def test_handoff_log_data_carries_it(self):
        src = (ROOT / 'api/admin_ui_handoff_log.py').read_text(encoding='utf-8')
        self.assertIn('"notices": [MVP4_HANDOFF_NOTE]', src)
        self.assertIn('from .admin_funnel import MVP4_HANDOFF_NOTE', src)


class ScreensShowItAsText(unittest.TestCase):
    def test_handoff_log_template(self):
        tpl = (ROOT / 'templates/admin/handoff_log.html.j2').read_text(encoding='utf-8')
        self.assertIn('id="hlServerNotice"', tpl)
        self.assertIn('d.notices', tpl)
        self.assertIn("sn.textContent = notes.join(' ')", tpl)
        self.assertNotIn('기록되지 않습니다', tpl)           # 문장을 화면에 박지 않는다 — 서버가 준다

    def test_funnel_template_already_renders_basis_as_text(self):
        tpl = (ROOT / 'templates/admin/funnel.html.j2').read_text(encoding='utf-8')
        self.assertIn('id="fnMvp3Basis"', tpl)
        self.assertIn('li.textContent = t', tpl)
        self.assertNotIn('기록되지 않습니다', tpl)


class CustomerScreenContract(unittest.TestCase):
    """문장의 전제: /mvp4 고객 화면은 인계 API 를 부르지 않고 몰 주소(mall_url)를 바로 연다."""
    def test_mvp4_does_not_call_handoff_api(self):
        self.assertTrue(MVP4_JS, '고객 화면 JS 를 찾지 못했다')
        callers = [p.relative_to(ROOT).as_posix() for p in MVP4_JS
                   if re.search(r"/handoff['\"/]", p.read_text(encoding='utf-8', errors='replace'))]
        self.assertEqual(callers, [], '/mvp4 가 인계 API 를 부르기 시작했다 — MVP4_HANDOFF_NOTE 문장을 다시 써야 한다')

    def test_mvp4_opens_mall_url_directly(self):
        src = (ROOT / 'mockups/mvp4/assets/js/live-catalog.js').read_text(encoding='utf-8')
        self.assertIn('mall_url', src)
        self.assertTrue(any('팝콘PC몰에서 바로 구매' in p.read_text(encoding='utf-8', errors='replace') for p in MVP4_JS),
                        '단추 문구가 바뀌었다 — MVP4_HANDOFF_NOTE 의 단추 이름도 맞춘다')


if __name__ == '__main__':
    unittest.main()
