"""test_admin_commerce_orders 의 audit hook 보호 범위가 import 관계와 일치하는지 동작으로 증명한다.

옛 방식은 «직접 import 하는 파일» 목록을 손으로 적어, 그 파일들을 다시 import 하는 테스트
(fulfillment/physical_return main_registration)가 조용히 보호 밖이 됐다. 여기서는 tests/ 소스를
전수로 읽어 이 모듈에 닿는 파일을 독립적으로 구하고, 각 파일 «실행 중»의 판정 함수 결과를 본다.
"""
import ast
from pathlib import Path
import unittest

from tests import test_admin_commerce_orders as orders

TESTS = Path(__file__).resolve().parent
OWN = 'test_admin_commerce_orders'


def _graph():
    stems = {p.stem for p in TESTS.glob('*.py')}
    graph = {}
    for stem in stems:
        deps = set()
        for node in ast.walk(ast.parse((TESTS / (stem + '.py')).read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                names = [a.name.split('.')[-1] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or '').split('.')[-1]] + [a.name for a in node.names]
            else:
                continue
            deps.update(n for n in names if n in stems)
        graph[stem] = deps
    return graph


def _reaching():
    graph = _graph()
    result = {OWN}
    changed = True
    while changed:
        changed = False
        for stem, deps in graph.items():
            if stem not in result and deps & result:
                result.add(stem)
                changed = True
    return result, set(graph)


class GuardScopeTests(unittest.TestCase):
    def nodeid(self, stem):
        return 'tests/%s.py::Case::test_x' % stem

    def test_every_transitive_importer_is_guarded_and_every_other_file_is_not(self):
        reaching, everything = _reaching()
        self.assertIn('test_commerce_fulfillment_main_registration', reaching)
        self.assertIn('test_commerce_physical_return_main_registration', reaching)
        for stem in sorted(everything):
            if stem == Path(__file__).stem:
                continue
            with self.subTest(stem=stem):
                self.assertEqual(orders._guard_armed(self.nodeid(stem)), stem in reaching)

    def test_unknown_or_unreadable_or_absent_current_test_is_guarded(self):
        self.assertTrue(orders._guard_armed(self.nodeid('no_such_file_zz')))
        self.assertTrue(orders._guard_armed(''))
        stem = 'test_admin_activity_log_core'
        orders._REACH_CACHE.pop(stem, None)
        original = orders._imported_stems

        def unreadable(path):
            raise OSError('unreadable')
        orders._imported_stems = unreadable
        try:
            self.assertTrue(orders._guard_armed(self.nodeid(stem)))
        finally:
            orders._imported_stems = original
            orders._REACH_CACHE.pop(stem, None)
        self.assertFalse(orders._guard_armed(self.nodeid(stem)))


if __name__ == '__main__':
    unittest.main()
