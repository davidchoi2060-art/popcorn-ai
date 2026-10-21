"""고객 화면 출처(0162) — 화면 머리글 -> 저장 칸 -> 관리자 표시 (2026-10-19)."""
import re
import unittest
from pathlib import Path

from starlette.requests import Request

from api import customer_surface as cs

ROOT = Path(__file__).resolve().parents[1]


def req(*headers):
    return Request({'type': 'http', 'path': '/', 'query_string': b'', 'headers': list(headers)})


class SurfaceOf(unittest.TestCase):
    def test_known_values_only(self):
        self.assertEqual(cs.surface_of(req((b'x-popcorn-surface', b'mvp4'))), 'mvp4')
        self.assertEqual(cs.surface_of(req((b'x-popcorn-surface', b' MVP3 '))), 'mvp3')
        for bad in (b'mvp5', b'', b'mvp3; drop', b'admin2'):
            self.assertIsNone(cs.surface_of(req((b'x-popcorn-surface', bad))))
        self.assertIsNone(cs.surface_of(req()))

    def test_referer_is_not_a_source(self):
        # nginx 가 no-referrer 를 걸어 브라우저는 보내지 않는다 — 와도 쓰지 않는다
        self.assertIsNone(cs.surface_of(req((b'referer', b'https://popcornai.co.kr/mvp4/index.html'))))

    def test_label(self):
        self.assertEqual(cs.label('mvp3'), '기존 화면(mvp3)')
        self.assertEqual(cs.label('mvp4'), '새 메인(mvp4)')
        self.assertEqual(cs.label(None), '알 수 없음')


class ScreensSendTheirOwnName(unittest.TestCase):
    """요청 함수마다 자기 화면 이름을 싣는다 — 남의 이름을 실으면 관리자 표가 거짓을 말한다."""
    FILES = {'mockups/mvp3/api-client.js': 'mvp3', 'mockups/mvp3/new-pcs.js': 'mvp3',
             'mockups/mvp4/assets/js/saved-quotes-client.js': 'mvp4',
             'mockups/mvp4/assets/js/service-adapters.js': 'mvp4'}

    def test_each_wrapper(self):
        for path, name in self.FILES.items():
            src = (ROOT / path).read_text(encoding='utf-8')
            vals = set(re.findall(r"""['"]X-Popcorn-Surface['"]\s*:\s*['"](\w+)['"]""", src))
            self.assertEqual(vals, {name}, path)


class Migration(unittest.TestCase):
    def test_check_matches_helper(self):
        src = (ROOT / 'db/migrations/versions/0162_customer_surface.py').read_text(encoding='utf-8')
        self.assertIn("surface IN ('mvp3', 'mvp4')", src)
        self.assertEqual(cs.SURFACES, ('mvp3', 'mvp4'))


if __name__ == '__main__':
    unittest.main()
