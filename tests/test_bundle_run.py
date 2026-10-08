"""tests/bundle_run.py 자체 검사 - 진짜 번들 없이 가짜 소스로 runner 가 fail-closed 인지 본다.

자식 프로세스 검사는 Linux 에서만 돈다(runner 가 /proc/self/fd 를 쓴다).
"""
import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location('bundle_run', Path(__file__).with_name('bundle_run.py'))
br = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(br)

LINUX = sys.platform.startswith('linux')
SMALL = {'files': 3, 'sources': 1, 'methods': 1, 'pins': 1}
ROOT = 'docs/ci-candidate-20261008'
DATA = b'x = 1\r\n'


def meta():
    method = {'path': 'tests/test_a.py', 'class': 'A', 'method': 'test_a'}
    handoff = {'bundle_root': ROOT,
               'minimal_transfer_files': [f'{ROOT}/source_candidate/api/a.py', f'{ROOT}/cloud-handoff.json',
                                          f'{ROOT}/bundle_manifest.json'],
               'source_files': [{'path': 'source_candidate/api/a.py', 'raw_sha256': br.sha256(DATA), 'bytes': len(DATA)}],
               'expected_methods': [method], 'expected_method_count': 1, 'dependencies': {'fastapi': '1.0'}}
    manifest = {'files': [{'path': 'api/a.py', 'checkout_raw_sha256': br.sha256(DATA), 'bytes': len(DATA), 'crlf': 1}],
                'methods': [dict(method)], 'expected_method_count': 1}
    return handoff, manifest


class MetaTests(unittest.TestCase):
    def check(self, handoff, manifest, reqs='fastapi==1.0\n', pins=None, listed=None):
        listed = handoff['minimal_transfer_files'] if listed is None else listed
        return br.check_meta(handoff, manifest, reqs, {'versions': {'fastapi': '1.0'}} if pins is None else pins,
                             listed, ROOT, SMALL)

    def test_consistent_meta_passes(self):
        self.assertEqual(self.check(*meta()), [])

    def test_extra_committed_file_fails(self):
        h, m = meta()
        self.assertTrue(self.check(h, m, listed=h['minimal_transfer_files'] + [f'{ROOT}/extra.py']))

    def test_method_list_drift_fails(self):
        h, m = meta()
        m['methods'][0]['method'] = 'test_b'
        self.assertTrue(self.check(h, m))

    def test_unpinned_or_mismatched_requirement_fails(self):
        self.assertTrue(self.check(*meta(), reqs='fastapi>=1.0\n'))
        self.assertTrue(self.check(*meta(), pins={'versions': {'fastapi': '2.0'}}))


class SourceTests(unittest.TestCase):
    def test_exact_bytes_pass(self):
        h, m = meta()
        problems, rows = br.check_sources(h, m, {'source_candidate/api/a.py': DATA}, {'source_candidate/api/a.py': DATA})
        self.assertEqual(problems, [])
        self.assertTrue(rows[0]['ok'] and rows[0]['worktree_equal'])

    def test_lf_normalised_blob_fails(self):
        h, m = meta()
        lf = DATA.replace(b'\r\n', b'\n')
        problems, _ = br.check_sources(h, m, {'source_candidate/api/a.py': lf}, {'source_candidate/api/a.py': lf})
        self.assertTrue(problems)

    def test_worktree_differs_from_blob_fails(self):
        h, m = meta()
        problems, _ = br.check_sources(h, m, {'source_candidate/api/a.py': DATA}, {'source_candidate/api/a.py': b''})
        self.assertTrue(problems)


METHODS = [{'path': 'tests/test_fake.py', 'class': 'Fake', 'method': 'test_one'}]


def child(**over):
    base = {'problems': [], 'counts': {'run': 1, 'failures': 0, 'errors': 0, 'skipped': 0, 'xfailed': 0, 'xpassed': 0},
            'rows': {'tests/test_fake.py::Fake::test_one': {'outcome': 'passed'}},
            'refusals': {'selfcheck': [{'event': 'socket.connect'}], 'tests': []}}
    base.update(over)
    return base


class JudgeTests(unittest.TestCase):
    def test_green_ignores_expected_selfcheck_refusals(self):
        self.assertEqual(br.judge(METHODS, child()), [])

    def test_real_refusal_fails_even_if_test_passed(self):
        self.assertTrue(br.judge(METHODS, child(refusals={'selfcheck': [], 'tests': [{'event': 'socket.connect'}]})))

    def test_skip_xfail_missing_and_zero_run_fail(self):
        for over in ({'counts': dict(child()['counts'], skipped=1)},
                     {'counts': dict(child()['counts'], xfailed=1)},
                     {'rows': {}},
                     {'counts': dict(child()['counts'], run=0)},
                     {'problems': ['import 실패']}):
            with self.subTest(over=over):
                self.assertTrue(br.judge(METHODS, child(**over)))


GOOD_TEST = '''
import os, socket, subprocess, tempfile, unittest
from pathlib import Path
import api
from tools import helper
OUTPUT = Path('D:/WORK/fake/outputs/fake-out')

class Fake(unittest.TestCase):
    def test_one(self):
        self.assertEqual((api.VALUE, helper.VALUE), (1, 2))
        OUTPUT.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=OUTPUT, prefix='synthetic-') as d:
            fd = os.open(os.path.join(d, 'x'), os.O_WRONLY | os.O_CREAT)
            os.close(fd)
            os.rename(os.path.join(d, 'x'), os.path.join(d, 'y'))
'''

ASGI_TEST = '''
    def test_asgi(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.get('/ping')(lambda: {'ok': True})
        with TestClient(app) as client:
            self.assertEqual(client.get('/ping').json(), {'ok': True})
'''


@unittest.skipUnless(LINUX, 'bundle_run 은 Linux 전용')
class ChildTests(unittest.TestCase):
    ADAPT = {'tests/test_fake.py': {'OUTPUT': 'D:/WORK/fake/outputs/fake-out'}}

    def run_fake(self, body, methods=None, adapters=None, pins=None):
        tmp = Path(tempfile.mkdtemp(prefix='bundle-run-test-'))
        self.addCleanup(lambda: __import__('shutil').rmtree(tmp, ignore_errors=True))
        src = tmp / 'src'
        (src / 'api').mkdir(parents=True)
        (src / 'tools').mkdir()
        (src / 'tests').mkdir()
        (src / 'api' / '__init__.py').write_text('VALUE = 1\n')
        (src / 'tools' / 'helper.py').write_text('VALUE = 2\n')
        (src / 'tests' / 'test_fake.py').write_text(body)
        methods = METHODS if methods is None else methods
        result = br.run_child(sys.executable, src, tmp / 'work', methods,
                              self.ADAPT if adapters is None else adapters, pins, timeout=120)
        return result, br.judge(methods, result), tmp

    def test_green_path_with_adapter_and_isolated_imports(self):
        result, reasons, tmp = self.run_fake(GOOD_TEST)
        self.assertEqual(reasons, [], result.get('log_tail'))
        self.assertEqual(len(result['refusals']['selfcheck']), 10)
        self.assertEqual(result['refusals']['tests'], [])
        self.assertTrue(result['adapters'][0]['applied'])
        self.assertTrue(result['adapters'][0]['adapted'].startswith(str((tmp / 'work' / 'out').resolve())))
        for name, where in result['modules'].items():
            self.assertTrue(all(w.startswith(str((tmp / 'src').resolve())) for w in where), (name, where))
        self.assertNotIn(str(Path(__file__).resolve().parent.parent), result['sys_path'])

    def test_in_process_asgi_is_not_blocked(self):
        try:
            import fastapi  # noqa: F401
            import httpx  # noqa: F401
        except ImportError:
            self.skipTest('fastapi/httpx 없음')
        methods = METHODS + [{'path': 'tests/test_fake.py', 'class': 'Fake', 'method': 'test_asgi'}]
        result, reasons, _ = self.run_fake(GOOD_TEST + ASGI_TEST, methods=methods)
        self.assertEqual(reasons, [], result.get('log_tail'))

    def test_caught_escape_attempts_still_fail(self):
        probe = Path(tempfile.gettempdir(), 'bundle-run-escape-probe')
        cases = {
            'socket.connect': "s = socket.socket(); s.connect(('127.0.0.1', 9))",
            'subprocess.Popen': "subprocess.run(['/bin/true'])",
            'open(write)': f"os.open({str(probe)!r}, os.O_WRONLY | os.O_CREAT)",
            'os.mkdir': f"os.mkdir({str(probe)!r})",
        }
        for event, stmt in cases.items():
            with self.subTest(event=event):
                body = GOOD_TEST + f'''
        try:
            {stmt}
        except Exception:
            pass
'''
                result, reasons, _ = self.run_fake(body)
                self.assertEqual([r['event'] for r in result['refusals']['tests']], [event])
                self.assertTrue(any('테스트 중 차단' in r for r in reasons), reasons)
                self.assertFalse(probe.exists())

    def test_extra_method_and_skip_fail_closed(self):
        extra = GOOD_TEST + '''
    def test_two(self):
        pass
'''
        _, reasons, _ = self.run_fake(extra)
        self.assertTrue(any('수집 불일치' in r for r in reasons), reasons)
        skipped = GOOD_TEST.replace('    def test_one(self):', "    @unittest.skip('x')\n    def test_one(self):")
        _, reasons, _ = self.run_fake(skipped)
        self.assertTrue(any('skipped' in r for r in reasons), reasons)

    def test_adapter_literal_mismatch_and_unadapted_windows_path_fail(self):
        _, reasons, _ = self.run_fake(GOOD_TEST, adapters={'tests/test_fake.py': {'OUTPUT': 'D:/WORK/other'}})
        self.assertTrue(any('어댑터 원문 값 불일치' in r for r in reasons), reasons)
        _, reasons, _ = self.run_fake(GOOD_TEST, adapters={})
        self.assertTrue(any('어댑터 없는 Windows 경로' in r for r in reasons), reasons)

    def test_import_error_and_pin_mismatch_fail(self):
        _, reasons, _ = self.run_fake('import does_not_exist_xyz\n')
        self.assertTrue(any('import 실패' in r for r in reasons), reasons)
        _, reasons, _ = self.run_fake(GOOD_TEST, pins={'definitely-not-installed-pkg': '1.0'})
        self.assertTrue(any('핀 불일치' in r for r in reasons), reasons)


if __name__ == '__main__':
    unittest.main()
