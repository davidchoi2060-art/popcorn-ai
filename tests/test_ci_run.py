"""tests/ci_run.py 의 판정 규칙을 가짜 출력으로 고정한다 - 「아무것도 안 돌았는데 초록」을 막는 장치가 실제로 막는지."""
import unittest

from tests import ci_run

PASS = 'TAP version 13\nok 1 - a\n# tests 3\n# suites 0\n# pass 3\n# fail 0\n# cancelled 0\n# skipped 0\n'
ZERO = 'TAP version 13\n1..0\n# tests 0\n# suites 0\n# pass 0\n# fail 0\n# cancelled 0\n# skipped 0\n'
# 테스트를 하나도 선언하지 않은 node:test 파일 - node --test 가 실제로 내는 모양(파일 자체를 1건 통과로 센다)
EMPTY_FILE = ('TAP version 13\n# Subtest: tests/zz_zero.cjs\nok 1 - tests/zz_zero.cjs\n  ---\n  ...\n1..1\n'
              '# tests 1\n# suites 0\n# pass 1\n# fail 0\n')
FAIL = 'TAP version 13\nnot ok 1 - a\n# tests 2\n# pass 1\n# fail 1\n'


class NodeCountsTests(unittest.TestCase):
    def test_normal_run_passes(self):
        counts, note = ci_run.node_counts(PASS, 0)
        self.assertEqual((counts['passed'], counts['failed'], counts['errors'], note), (3, 0, 0, ''))

    def test_zero_tests_with_exit_0_is_an_error(self):
        counts, note = ci_run.node_counts(ZERO, 0)
        self.assertEqual(counts['errors'], 1)
        self.assertIn('0건', note)

    def test_missing_summary_with_exit_0_is_an_error(self):
        counts, note = ci_run.node_counts('TAP version 13\nok 1 - a\n', 0)
        self.assertEqual(counts['errors'], 1)
        self.assertIn('집계 줄', note)

    def test_empty_output_with_exit_0_is_an_error(self):
        self.assertEqual(ci_run.node_counts('', 0)[0]['errors'], 1)

    def test_node_test_file_declaring_no_tests_is_an_error(self):
        counts, note = ci_run.node_counts(EMPTY_FILE, 0, 'tests/zz_zero.cjs', uses_node_test=True)
        self.assertEqual(counts['errors'], 1)
        self.assertIn('선언된 테스트 0건', note)

    def test_script_file_without_node_test_counts_as_one_run(self):
        counts, note = ci_run.node_counts(EMPTY_FILE, 0, 'tests/zz_zero.cjs', uses_node_test=False)
        self.assertEqual((counts['passed'], counts['errors'], note), (1, 0, ''))

    def test_failures_are_counted_not_hidden(self):
        counts, _ = ci_run.node_counts(FAIL, 1)
        self.assertEqual((counts['passed'], counts['failed']), (1, 1))

    def test_nonzero_exit_without_failures_is_an_error(self):
        self.assertEqual(ci_run.node_counts(PASS, 1)[0]['errors'], 1)


class NodeCollectionTests(unittest.TestCase):
    def test_patterns_are_explicit_not_recursive(self):
        self.assertTrue(all('**' not in p for p in ci_run.NODE_PATTERNS))

    def test_mvp3_consumer_tests_are_collected(self):
        rels = [p.relative_to(ci_run.ROOT).as_posix() for p in ci_run.node_files()]
        self.assertIn('mockups/mvp3/tests/contract.test.cjs', rels)
        self.assertTrue(any(r.startswith('tests/') for r in rels))


if __name__ == '__main__':
    unittest.main()
