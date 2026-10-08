"""tests/bundle_run.py 자체 검사 - 진짜 번들 없이 가짜 소스로 runner 가 fail-closed 인지 본다.

자식 프로세스 검사는 Linux 에서만 돈다(runner 가 /proc/self/fd 를 쓴다).
"""
import importlib.util
import json
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
            'refusals': {'selfcheck': [{'event': 'probe'}] * br.SELFCHECK_PROBES, 'tests': []}}
    base.update(over)
    return base


class JudgeTests(unittest.TestCase):
    def test_green_ignores_expected_selfcheck_refusals(self):
        self.assertEqual(br.judge(METHODS, child()), [])

    def test_real_refusal_fails_even_if_test_passed(self):
        refusals = {'selfcheck': [{'event': 'probe'}] * br.SELFCHECK_PROBES, 'tests': [{'event': 'socket.connect'}]}
        self.assertTrue(br.judge(METHODS, child(refusals=refusals)))

    def test_missing_selfcheck_probes_fail(self):
        self.assertTrue(br.judge(METHODS, child(refusals={'selfcheck': [], 'tests': []})))

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
        self.assertEqual(len(result['refusals']['selfcheck']), br.SELFCHECK_PROBES)
        self.assertEqual((tmp / 'work' / 'forbidden' / 'existing.txt').read_text(), 'keep')
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
            'os.symlink': f"os.symlink({str(probe)!r}, os.path.join(str(OUTPUT), 'escape'))",
        }
        for event, stmt in cases.items():
            with self.subTest(event=event):
                body = GOOD_TEST + f'''
        OUTPUT.mkdir(exist_ok=True)
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



@unittest.skipUnless(LINUX, 'bundle_run 은 Linux 전용')
class GuardSymlinkTests(unittest.TestCase):
    """hook 을 걸지 않고 Guard 판정만 직접 부른다 - 이 프로세스에 되돌릴 수 없는 hook 을 남기지 않는다."""

    def setUp(self):
        base = Path(tempfile.mkdtemp(prefix='bundle-guard-'))
        self.addCleanup(lambda: __import__('shutil').rmtree(base, ignore_errors=True))
        self.allowed, self.outside = base / 'allowed', base / 'outside'
        self.allowed.mkdir()
        self.outside.mkdir()
        self.target = self.outside / 'target.txt'
        self.target.write_text('keep')
        self.link = self.allowed / 'link'
        self.link.symlink_to(self.target)
        (self.allowed / 'dangling').symlink_to(self.outside / 'new.txt')
        self.guard = br.Guard([str(self.allowed)])
        self.guard.phase = 'tests'

    def denied(self, event, args):
        with self.assertRaises(PermissionError):
            self.guard(event, args)

    def test_writes_through_symlink_to_outside_are_denied(self):
        import os
        self.denied('open', (str(self.link), 'w', 0))
        self.denied('open', (str(self.link), None, os.O_WRONLY | os.O_TRUNC))
        self.denied('open', (str(self.allowed / 'dangling'), None, os.O_WRONLY | os.O_CREAT))
        self.denied('os.truncate', (str(self.link), 0))
        self.denied('os.chmod', (str(self.link), 0o600, -1))
        self.denied('os.symlink', (str(self.target), str(self.allowed / 'new-link'), -1))
        self.denied('os.link', (str(self.target), str(self.allowed / 'hard'), -1, -1))
        self.assertEqual(self.target.read_text(), 'keep')
        self.assertEqual(len(self.guard.refusals['tests']), 7)

    def test_new_file_and_link_entry_changes_inside_are_allowed(self):
        import os
        self.guard('open', (str(self.allowed / 'new.txt'), None, os.O_WRONLY | os.O_CREAT))
        self.guard('os.rename', (str(self.link), str(self.allowed / 'moved'), -1, -1))
        self.guard('os.remove', (str(self.allowed / 'dangling'), -1))
        self.guard('os.symlink', ('new.txt', str(self.allowed / 'inner-link'), -1))
        self.guard('open', (str(self.target), 'r', 0))
        self.assertEqual(self.guard.refusals['tests'], [])


class PregateTests(unittest.TestCase):
    SHA = 'a' * 40

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='bundle-pregate-'))
        self.addCleanup(lambda: __import__('shutil').rmtree(self.work, ignore_errors=True))
        (self.work / 'src' / 'api').mkdir(parents=True)
        rows = []
        for i in range(br.EXPECT['sources']):
            data = f'x = {i}\n'.encode()
            (self.work / 'src' / 'api' / f'm{i}.py').write_bytes(data)
            rows.append({'path': f'source_candidate/api/m{i}.py', 'sha256': br.sha256(data), 'ok': True,
                         'worktree_equal': True})
        self.valid = {'problems': [], 'bundle_head': self.SHA, 'bundle_sha': self.SHA, 'bundle_root': br.BUNDLE_ROOT,
                      'files_listed': br.EXPECT['files'], 'sources': rows, 'copy_rehash_ok': True,
                      'methods': [{'path': 'tests/t.py', 'class': 'C', 'method': f'test_{i}'}
                                  for i in range(br.EXPECT['methods'])],
                      'pins': {f'p{i}': '1' for i in range(br.EXPECT['pins'])}}

    def run_with(self, verify, raw=None):
        path = self.work / 'verify.json'
        path.write_text(raw if raw is not None else json.dumps(verify), encoding='utf-8')
        calls = []
        original = br.run_child
        br.run_child = lambda *a, **k: calls.append(a) or {}
        try:
            args = br.argparse.Namespace(work=str(self.work), python='/nonexistent/python',
                                         results=str(self.work / 'results.json'), bundle_sha=self.SHA)
            code = br.cmd_run(args)
        finally:
            br.run_child = original
        return code, calls, json.loads((self.work / 'results.json').read_text(encoding='utf-8'))

    def test_valid_verify_passes_gate(self):
        self.assertEqual(br.pregate(self.valid, self.work, self.SHA), [])

    def test_invalid_verify_never_starts_child(self):
        bad_source = [dict(r) for r in self.valid['sources']]
        bad_source[0]['ok'] = False
        cases = {
            'problems': dict(self.valid, problems=['소스 해시 불일치']),
            'problems missing': {k: v for k, v in self.valid.items() if k != 'problems'},
            'sha': dict(self.valid, bundle_head='b' * 40),
            'source not ok': dict(self.valid, sources=bad_source),
            'seventeen methods': dict(self.valid, methods=self.valid['methods'][:17]),
            'fifteen pins': dict(self.valid, pins=dict(list(self.valid['pins'].items())[:15])),
            'copy not rehashed': dict(self.valid, copy_rehash_ok=False),
        }
        for name, verify in cases.items():
            with self.subTest(case=name):
                code, calls, results = self.run_with(verify)
                self.assertEqual((code, len(calls), results['verdict'], results['child_started']), (1, 0, 'red', False))
        code, calls, results = self.run_with(None, raw='{not json')
        self.assertEqual((code, len(calls), results['verdict']), (1, 0, 'red'))

    def test_copy_changed_after_verify_never_starts_child(self):
        (self.work / 'src' / 'api' / 'm0.py').write_bytes(b'tampered\n')
        code, calls, _ = self.run_with(self.valid)
        self.assertEqual((code, len(calls)), (1, 0))

if __name__ == '__main__':
    unittest.main()
