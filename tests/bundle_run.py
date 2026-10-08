"""PR #12 합성 CI 번들 전용 runner - GitHub 호스팅 Ubuntu 에서만 쓴다(Linux 전용).

번들(docs/ci-candidate-20261008/)은 PC 쪽이 넘긴 «원문 그대로»의 소스 8개와 메타 6개다.
이 runner 는 그 소스를 저장소의 api/·tools/ 와 섞지 않고, 매니페스트가 정한 unittest
method 18개만 정확히 돌린다. 저장소 단위 테스트(tests/ci_run.py)와는 별개다.

    python tests/bundle_run.py verify --bundle-repo DIR --bundle-sha SHA --work DIR
    python tests/bundle_run.py run    --python VENV_PY --work DIR --results FILE --bundle-sha SHA

verify: 번들 커밋(SHA)의 blob 바이트를 매니페스트와 대조하고, 소스를 work/src 로 복사한다.
        번들 코드는 import 하지도 실행하지도 않는다.
run:    실행 전 관문(verify 결과 · SHA · 복사본 재해시)을 통과해야만 별도 venv 의 파이썬(-I)으로
        자식 프로세스를 띄워 18개를 돌리고 판정한다. 관문에서 막히면 자식을 띄우지 않고 red 로 끝난다.

차단 층(Guard)은 «합성 검사가 실수로 밖에 닿는 사고»를 막는 장치다. 감사 hook 기반이라
네이티브 코드나 악의적인 코드를 막는 보안 sandbox 가 아니다.

초록불 조건: 파일·해시·목록 대조 통과 · 18개 정확 수집 · 18개 각각 통과 · skip/xfail/
xpass/오류/실패 0 · 테스트 중 차단 0(예외를 테스트가 삼켜도 실패) · api/tools 가 번들 소스에서만
import 됨 · OUTPUT 원문 값 일치 후 어댑터 적용 · 16개 핀 실제 버전 일치.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

BUNDLE_ROOT = 'docs/ci-candidate-20261008'
EXPECT = {'files': 14, 'sources': 8, 'methods': 18, 'pins': 16}
# 원문 상수는 고치지 않는다. 값이 이 문자열과 «정확히» 같을 때만 임시 경로로 다시 묶는다.
ADAPTERS = {
    'tests/test_existing_media_pg_capture_plan_integration.py': {
        'OUTPUT': 'D:/WORK/PopcornAI/outputs/existing-media-pg-capture-plan-code-mock-20261008',
    },
}
CHILD_TIMEOUT = 600
MARKER = 'BUNDLE_RUN_RESULT='
WINDOWS_PATH = re.compile(r'^[A-Za-z]:[/\\]')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def inside(path, roots):
    return any(path == r or path.startswith(r + os.sep) for r in roots)


# ---------------------------------------------------------------- verify (번들 실행 없음)

def check_meta(handoff, manifest, requirements_text, pins_json, listed, root=BUNDLE_ROOT, expect=EXPECT):
    """메타 파일끼리·목록끼리 대조한다. 문제 문장 목록을 돌려준다."""
    problems = []
    if handoff.get('bundle_root') != root:
        problems.append(f'handoff bundle_root {handoff.get("bundle_root")!r} != {root!r}')
    files = handoff.get('minimal_transfer_files') or []
    if len(files) != expect['files'] or sorted(files) != sorted(listed):
        problems.append(f'번들 파일 집합 불일치: handoff {len(files)}개, 커밋 {len(listed)}개')
    sources = handoff.get('source_files') or []
    if len(sources) != expect['sources']:
        problems.append(f'소스 {len(sources)}개 (기대 {expect["sources"]})')
    mfiles = {f['path'] for f in manifest.get('files') or []}
    if {s['path'].removeprefix('source_candidate/') for s in sources} != mfiles:
        problems.append('handoff source_files 와 manifest files 경로 불일치')
    methods = manifest.get('methods') or []
    keys = [(m['path'], m['class'], m['method']) for m in methods]
    if methods != handoff.get('expected_methods'):
        problems.append('manifest methods 와 handoff expected_methods 불일치')
    if not (len(keys) == len(set(keys)) == expect['methods']
            == manifest.get('expected_method_count') == handoff.get('expected_method_count')):
        problems.append(f'method {len(keys)}개(중복 제외 {len(set(keys))}) - 기대 {expect["methods"]}')
    reqs = {}
    for line in requirements_text.splitlines():
        if line.strip():
            name, sep, ver = line.strip().partition('==')
            if not sep:
                problems.append(f'requirements_ci.txt 에 == 고정이 아닌 줄: {line!r}')
            reqs[name] = ver
    deps = handoff.get('dependencies') or {}
    if not (reqs == deps == (pins_json.get('versions') or {})) or len(reqs) != expect['pins']:
        problems.append(f'의존 핀 불일치 또는 {len(reqs)}개 (기대 {expect["pins"]})')
    return problems


def check_sources(handoff, manifest, blobs, worktree):
    """커밋 blob 바이트와 작업 트리 바이트를 handoff·manifest 와 대조한다."""
    problems, rows = [], []
    mf = {f['path']: f for f in manifest.get('files') or []}
    for entry in handoff.get('source_files') or []:
        path = entry['path']
        rel = path.removeprefix('source_candidate/')
        data = blobs.get(path)
        m = mf.get(rel, {})
        row = {'path': path, 'sha256': sha256(data) if data is not None else None,
               'bytes': len(data) if data is not None else None,
               'crlf': data.count(b'\r\n') if data is not None else None}
        row['ok'] = (data is not None
                     and row['sha256'] == entry.get('raw_sha256') == m.get('checkout_raw_sha256')
                     and row['bytes'] == entry.get('bytes') == m.get('bytes')
                     and row['crlf'] == m.get('crlf'))
        row['worktree_equal'] = worktree.get(path) == data
        if not row['ok']:
            problems.append(f'소스 해시·크기·CRLF 불일치: {path}')
        if not row['worktree_equal']:
            problems.append(f'작업 트리 바이트가 커밋 blob 과 다름: {path}')
        rows.append(row)
    return problems, rows


def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, check=True).stdout


def cmd_verify(args):
    repo, sha, work = args.bundle_repo, args.bundle_sha, Path(args.work)
    problems = []
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    if head != sha:
        print(f'FAIL 번들 checkout HEAD {head} != 지정 SHA {sha} - 대조하지 않고 멈춘다')
        return 1

    def blob(path):
        return git(repo, 'cat-file', 'blob', f'{sha}:{BUNDLE_ROOT}/{path}')

    listed = [p for p in git(repo, 'ls-tree', '-r', '--name-only', sha, '--', BUNDLE_ROOT).decode().splitlines() if p]
    handoff = json.loads(blob('cloud-handoff.json'))
    manifest = json.loads(blob('bundle_manifest.json'))
    requirements = blob('requirements_ci.txt')
    problems += check_meta(handoff, manifest, requirements.decode('utf-8'),
                           json.loads(blob('runtime-dependency-pins.json')), listed)
    blobs = {s['path']: blob(s['path']) for s in handoff.get('source_files') or []}
    worktree = {}
    for path in blobs:
        f = Path(repo, BUNDLE_ROOT, path)
        worktree[path] = f.read_bytes() if f.is_file() else None
    source_problems, rows = check_sources(handoff, manifest, blobs, worktree)
    problems += source_problems

    # 원문을 blob 바이트 그대로 격리 경로에 복사하고, 복사본을 다시 해시한다.
    src = work / 'src'
    for path, data in blobs.items():
        dest = src / path.removeprefix('source_candidate/')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        if sha256(dest.read_bytes()) != sha256(data):
            problems.append(f'복사본 해시 불일치: {dest}')
    (work / 'requirements_ci.txt').write_bytes(requirements)
    record = {'bundle_head': head, 'bundle_sha': sha, 'bundle_root': BUNDLE_ROOT,
              'files_listed': len(listed), 'sources': rows, 'copy_rehash_ok': not any('복사본' in p for p in problems),
              'methods': manifest.get('methods'), 'pins': handoff.get('dependencies'), 'problems': problems}
    (work / 'verify.json').write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
    for p in problems:
        print(f'FAIL {p}')
    print(f'verify: 파일 {len(listed)} · 소스 {sum(r["ok"] for r in rows)}/{len(rows)} 일치 · '
          f'method {len(manifest.get("methods") or [])} · 핀 {len(handoff.get("dependencies") or {})}')
    return 1 if problems else 0


# ---------------------------------------------------------------- 차단 층 (자식 프로세스 안)

NET_EVENTS = {'socket.connect', 'socket.bind', 'socket.sendto', 'socket.sendmsg', 'socket.getaddrinfo',
              'socket.gethostbyname', 'socket.gethostbyname_ex', 'socket.gethostbyaddr', 'socket.getnameinfo'}
PROC_EVENTS = {'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork',
               'os.forkpty', 'os.startfile', 'pty.spawn'}
# 파일을 바꾸는 이벤트: (경로 인자 위치, dir_fd 인자 위치, 판정 기준)
#   'final' - 그 경로가 가리키는 최종 대상(마지막 요소의 symlink 까지 해석)을 바꾼다
#   'entry' - 디렉터리 항목 자체를 만들거나 지우거나 옮긴다(symlink 를 따라가지 않는다)
FS_EVENTS = {
    'os.mkdir': [(0, 2, 'entry')], 'os.rmdir': [(0, 1, 'entry')], 'os.remove': [(0, 1, 'entry')],
    'os.rename': [(0, 2, 'entry'), (1, 3, 'entry')],
    # 하드 링크는 원본 inode 를 허용 루트 안으로 끌어들인다 - 원본의 최종 대상도 안이어야 한다.
    'os.link': [(0, 2, 'final'), (1, 3, 'entry')],
    'os.symlink': [(1, 2, 'entry')],  # 링크가 가리킬 대상은 _check 에서 따로 본다
    'os.truncate': [(0, None, 'final')], 'os.chmod': [(0, 2, 'final')], 'os.chown': [(0, 3, 'final')],
    'os.utime': [(0, 3, 'final')], 'os.setxattr': [(0, None, 'final')], 'os.removexattr': [(0, None, 'final')],
    'os.mkfifo': [(0, 2, 'entry')], 'os.mknod': [(0, 3, 'entry')],
    'shutil.rmtree': [(0, 1, 'entry')], 'shutil.copyfile': [(1, None, 'final')],
}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


class Guard:
    """sys.addaudithook 으로 거는 사고 방지 층. 한 번 걸면 풀 수 없다. 보안 sandbox 가 아니다.

    phase 가 'selfcheck' 일 때의 거부는 «예상된 거부»로, 'tests' 일 때의 거부는 «실제 거부»로
    따로 기록한다. 실제 거부는 테스트가 예외를 잡아도 runner 가 실패로 판정한다.

    쓰기 대상은 symlink 를 끝까지 따라간 최종 경로로 판정한다(허용 루트 안의 링크가 밖을
    가리켜도 막힌다). 아직 없는 새 파일은 부모를 해석한 경로, 지우기·옮기기는 항목 자체로 본다.
    """

    def __init__(self, write_roots):
        self.roots = [os.path.realpath(r) for r in write_roots]
        self.phase = 'selfcheck'
        self.refusals = {'selfcheck': [], 'tests': []}
        self._local = threading.local()

    @staticmethod
    def _absolute(path, dir_fd):
        if isinstance(path, int):
            return None  # 이미 열린 fd - 여는 시점에 open 이벤트로 검사됐다
        path = os.fsdecode(os.fspath(path))
        if os.path.isabs(path):
            return os.path.normpath(path)
        if isinstance(dir_fd, int) and dir_fd >= 0:
            return os.path.normpath(os.path.join(os.readlink(f'/proc/self/fd/{dir_fd}'), path))
        return os.path.normpath(os.path.join(os.getcwd(), path))

    def _resolve(self, path, dir_fd, how):
        full = self._absolute(path, dir_fd)
        if full is None:
            return None
        if how == 'final':
            return os.path.realpath(full)  # 마지막 요소의 symlink(끊긴 링크 포함)까지 따라간다
        parent, name = os.path.split(full)
        return os.path.join(os.path.realpath(parent), name)

    def _deny(self, event, detail):
        self.refusals[self.phase].append({'event': event, 'detail': detail[:300]})
        raise PermissionError(f'bundle_run blocked {event}: {detail[:200]}')

    def __call__(self, event, args):
        if getattr(self._local, 'busy', False):
            return
        self._local.busy = True
        try:
            self._check(event, args)
        finally:
            self._local.busy = False

    def _check(self, event, args):
        if event in NET_EVENTS:
            self._deny(event, repr(args[1:] if event == 'socket.connect' else args))
        if event in PROC_EVENTS:
            self._deny(event, repr(args)[:300])
        if event == 'open':
            path, mode, flags = (tuple(args) + (None, None, None))[:3]
            writes = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or \
                     (isinstance(flags, int) and bool(flags & WRITE_FLAGS))
            if writes:
                full = self._resolve(path, None, 'final')
                if full is not None and not inside(full, self.roots):
                    self._deny('open(write)', full)
        if event == 'os.symlink':
            link = self._resolve(args[1], args[2] if len(args) > 2 else None, 'entry')
            target = os.fsdecode(os.fspath(args[0]))
            if link is not None:
                target = os.path.realpath(os.path.join(os.path.dirname(link), target))
                if not inside(target, self.roots):
                    self._deny(event, f'{link} -> {target}')
        for pi, fi, how in FS_EVENTS.get(event, ()):
            if pi >= len(args) or args[pi] is None:
                continue
            dir_fd = args[fi] if fi is not None and fi < len(args) else None
            full = self._resolve(args[pi], dir_fd, how)
            if full is not None and not inside(full, self.roots):
                self._deny(event, full)


def prepare_selfcheck(work, inside_dir):
    """자체 점검용 고정물. hook 을 걸기 «전에» 만든다(밖을 가리키는 링크는 hook 이 만들게 두지 않는다)."""
    forbidden = os.path.join(work, 'forbidden')
    os.makedirs(forbidden, exist_ok=True)
    Path(forbidden, 'existing.txt').write_text('keep')
    os.symlink(os.path.join(forbidden, 'existing.txt'), os.path.join(inside_dir, 'link-out'))
    os.symlink(os.path.join(forbidden, 'new.txt'), os.path.join(inside_dir, 'dangling-out'))
    os.symlink(forbidden, os.path.join(inside_dir, 'dir-out'))
    Path(inside_dir, 'probe.txt').write_text('probe')


def selfcheck(guard, work):
    """차단이 실제로 걸리는지 확인한다. 실패 사유 목록(비면 통과)을 돌려준다."""
    import shutil
    import socket
    import tempfile
    forbidden = os.path.join(work, 'forbidden')
    existing = os.path.join(forbidden, 'existing.txt')
    inside_dir = guard.roots[0]
    inside_file = os.path.join(inside_dir, 'probe.txt')
    link_out = os.path.join(inside_dir, 'link-out')
    dangling = os.path.join(inside_dir, 'dangling-out')

    def connect():
        s = socket.socket()
        try:
            s.connect(('127.0.0.1', 9))
        finally:
            s.close()

    expected = [
        ('socket.connect', connect),
        ('socket.getaddrinfo', lambda: socket.getaddrinfo('example.com', 443)),
        ('subprocess.Popen', lambda: subprocess.run(['/bin/true'])),
        ('os.system', lambda: os.system('true')),
        ('open(write)', lambda: open(os.path.join(forbidden, 'w.txt'), 'w')),
        ('open(write)', lambda: os.open(os.path.join(forbidden, 'flags.txt'), os.O_WRONLY | os.O_CREAT)),
        ('os.mkdir', lambda: os.mkdir(os.path.join(forbidden, 'd'))),
        ('os.rename', lambda: os.rename(inside_file, os.path.join(forbidden, 'moved.txt'))),
        ('os.remove', lambda: os.remove(existing)),
        ('shutil.rmtree', lambda: shutil.rmtree(forbidden)),
        # 허용 루트 안의 symlink 가 밖을 가리키는 경우 - 최종 대상으로 판정해야 막힌다
        ('open(write)', lambda: open(link_out, 'w')),
        ('open(write)', lambda: open(link_out, 'a')),
        ('open(write)', lambda: os.open(link_out, os.O_WRONLY | os.O_TRUNC)),
        ('open(write)', lambda: os.open(dangling, os.O_WRONLY | os.O_CREAT)),
        ('open(write)', lambda: open(os.path.join(inside_dir, 'dir-out', 'x.txt'), 'w')),
        ('os.truncate', lambda: os.truncate(link_out, 0)),
        ('os.chmod', lambda: os.chmod(link_out, 0o600)),
        ('shutil.copyfile', lambda: shutil.copyfile(inside_file, link_out)),
        ('os.symlink', lambda: os.symlink(existing, os.path.join(inside_dir, 'new-link'))),
        ('os.link', lambda: os.link(existing, os.path.join(inside_dir, 'hard-link'))),
    ]
    problems = []
    for event, probe in expected:
        before = len(guard.refusals['selfcheck'])
        try:
            probe()
            problems.append(f'자체 점검: {event} 가 막히지 않았다')
        except PermissionError:
            got = guard.refusals['selfcheck'][before:]
            if not got or got[0]['event'] != event:
                problems.append(f'자체 점검: {event} 가 다른 이유로 실패했다 ({got})')
        except Exception as exc:  # noqa: BLE001 - 무엇이든 «막히지 않음» 으로 본다
            problems.append(f'자체 점검: {event} 가 차단 대신 {type(exc).__name__} 로 끝났다')
    # 허용 경로 안의 쓰기·변경은 통과해야 한다(테스트의 합성 임시 파일).
    # 밖을 가리키는 링크라도 «항목 자체»를 옮기고 지우는 것은 대상을 건드리지 않으므로 허용한다.
    before = len(guard.refusals['selfcheck'])
    try:
        with tempfile.TemporaryDirectory(dir=inside_dir) as d:
            fd = os.open(os.path.join(d, 'a'), os.O_WRONLY | os.O_CREAT)
            os.close(fd)
            os.mkdir(os.path.join(d, 'sub'))
            os.rename(os.path.join(d, 'a'), os.path.join(d, 'sub', 'b'))
            os.remove(os.path.join(d, 'sub', 'b'))
        moved = os.path.join(inside_dir, 'link-moved')
        os.rename(link_out, moved)
        os.remove(moved)
        os.remove(dangling)
        os.remove(os.path.join(inside_dir, 'dir-out'))
        os.remove(inside_file)
    except Exception as exc:  # noqa: BLE001
        problems.append(f'자체 점검: 허용 경로 안 쓰기가 실패했다 ({type(exc).__name__}: {exc})')
    if len(guard.refusals['selfcheck']) != before:
        problems.append('자체 점검: 허용 경로 안 쓰기가 거부로 기록됐다')
    if sorted(os.listdir(forbidden)) != ['existing.txt']:
        problems.append(f'자체 점검: 금지 경로가 바뀌었다 {sorted(os.listdir(forbidden))}')
    elif Path(existing).read_bytes() != b'keep' or (os.stat(existing).st_mode & 0o777) == 0o600:
        problems.append('자체 점검: 금지 경로의 파일 내용·권한이 바뀌었다')
    return problems


SELFCHECK_PROBES = 20


# ---------------------------------------------------------------- 자식 프로세스

class Recorder(unittest.TestResult):
    """unittest 결과를 test id 별로 기록한다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows, self._t = {}, {}

    def startTest(self, test):
        super().startTest(test)
        self._t[test.id()] = time.monotonic()

    def _set(self, test, outcome, detail=''):
        tid = test.id()
        if self.rows.get(tid, {}).get('outcome') in ('failed', 'error') and outcome == 'passed':
            return
        self.rows[tid] = {'outcome': outcome, 'detail': detail[-4000:],
                          'seconds': round(time.monotonic() - self._t.get(tid, time.monotonic()), 3)}

    def addSuccess(self, test):
        super().addSuccess(test)
        self._set(test, 'passed')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._set(test, 'failed', self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._set(test, 'error', self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._set(test, 'skipped', reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._set(test, 'xfailed', self._exc_info_to_string(err, test))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._set(test, 'xpassed')

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._set(test, 'failed', self._exc_info_to_string(err, test))


def _flatten(suite):
    for item in suite:
        if hasattr(item, '__iter__'):
            yield from _flatten(item)
        else:
            yield item


def child_main(args):
    src, work = os.path.realpath(args.src), os.path.realpath(args.work)
    out, tmp = os.path.join(work, 'out'), os.path.join(work, 'tmp')
    for d in (out, tmp, os.path.join(work, 'cwd')):
        os.makedirs(d, exist_ok=True)
    prepare_selfcheck(work, out)
    methods = json.loads(Path(args.methods).read_text(encoding='utf-8'))
    adapters = json.loads(Path(args.adapters).read_text(encoding='utf-8'))
    pins = json.loads(Path(args.pins).read_text(encoding='utf-8')) if args.pins else None
    result = {'problems': [], 'adapters': [], 'collected': [], 'rows': {}, 'pins_actual': {},
              'modules': {}, 'counts': {}}
    problems = result['problems']

    # import 루트: 번들 소스 + 표준 라이브러리 + venv site-packages. 저장소 루트는 넣지 않는다(-I 로 실행됨).
    repo_root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path[:] = [src] + [p for p in sys.path if p and not inside(os.path.realpath(p), [repo_root])]
    result['sys_path'] = list(sys.path)
    import tempfile
    tempfile.tempdir = tmp

    if pins is not None:
        from importlib import metadata
        for name, ver in pins.items():
            try:
                actual = metadata.version(name)
            except metadata.PackageNotFoundError:
                actual = None
            result['pins_actual'][name] = actual
            if actual != ver:
                problems.append(f'핀 불일치 {name}: 설치 {actual} != {ver}')

    guard = Guard([out, tmp])
    sys.addaudithook(guard)
    result['selfcheck_problems'] = selfcheck(guard, work)
    problems += result['selfcheck_problems']
    guard.phase = 'tests'
    os.chdir(os.path.join(work, 'cwd'))  # 허용 경로 밖 - 상대 경로 쓰기는 거부된다

    if not result['selfcheck_problems']:
        modules = {}
        for rel in sorted({m['path'] for m in methods}):
            name = 'bundle_tests.' + Path(rel).stem
            try:
                spec = importlib.util.spec_from_file_location(name, os.path.join(src, rel))
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                modules[rel] = mod
            except BaseException as exc:  # noqa: BLE001 - import 실패도 기록하고 실패로 판정
                problems.append(f'import 실패 {rel}: {type(exc).__name__}: {exc}')
        for rel, mod in modules.items():
            want = adapters.get(rel, {})
            for attr, literal in want.items():
                value = getattr(mod, attr, None)
                rec = {'path': rel, 'attr': attr, 'original': None if value is None else str(value),
                       'expected_original': literal, 'applied': False}
                if value is None or str(value) != literal or not isinstance(value, Path):
                    problems.append(f'어댑터 원문 값 불일치 {rel}:{attr} = {value!r}')
                else:
                    target = Path(out, Path(literal.replace('\\', '/')).name)
                    setattr(mod, attr, target)
                    rec.update(adapted=str(target), applied=True)
                result['adapters'].append(rec)
            for attr, value in vars(mod).items():
                if attr not in want and isinstance(value, (str, Path)) and WINDOWS_PATH.match(str(value)):
                    problems.append(f'어댑터 없는 Windows 경로 {rel}:{attr} = {value}')
        expected = [(m['path'], m['class'], m['method']) for m in methods]
        by_id, collected = {}, []
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for rel, mod in modules.items():
            for test in _flatten(loader.loadTestsFromModule(mod)):
                key = (rel, type(test).__name__, getattr(test, '_testMethodName', test.id()))
                collected.append(key)
                by_id[test.id()] = key
                suite.addTest(test)
        result['collected'] = [list(k) for k in collected]
        if sorted(collected) != sorted(expected):
            missing = sorted(set(expected) - set(collected))
            extra = sorted(set(collected) - set(expected))
            problems.append(f'수집 불일치: 수집 {len(collected)} · 기대 {len(expected)} · 누락 {missing} · 추가 {extra}')
        else:
            res = Recorder()
            suite.run(res)
            result['counts'] = {'run': res.testsRun, 'failures': len(res.failures), 'errors': len(res.errors),
                                'skipped': len(res.skipped), 'xfailed': len(res.expectedFailures),
                                'xpassed': len(res.unexpectedSuccesses)}
            result['rows'] = {'::'.join(by_id.get(tid, ('?', '?', tid))): row for tid, row in res.rows.items()}
        for name, mod in list(sys.modules.items()):
            if name in ('api', 'tools') or name.startswith(('api.', 'tools.')):
                where = [getattr(mod, '__file__', None)] + list(getattr(mod, '__path__', []) or [])
                where = [os.path.realpath(w) for w in where if w]
                result['modules'][name] = where
                if not where or not all(inside(w, [src]) for w in where):
                    problems.append(f'번들 소스 밖에서 import 됨: {name} {where}')
        if not result['modules']:
            problems.append('api/tools 모듈이 하나도 import 되지 않았다')

    guard.phase = 'done'
    guard.refusals.setdefault('done', [])
    result['refusals'] = guard.refusals
    sys.stdout.write('\n' + MARKER + json.dumps(result, ensure_ascii=False) + '\n')
    sys.stdout.flush()
    return 0


# ---------------------------------------------------------------- 판정·보고 (부모)

def judge(methods, child):
    """자식 결과를 판정한다. 실패 사유 목록(비면 green)을 돌려준다."""
    reasons = list(child.get('problems') or [])
    expected = ['::'.join((m['path'], m['class'], m['method'])) for m in methods]
    if len(expected) != len(set(expected)):
        reasons.append('기대 method 목록에 중복이 있다')
    rows = child.get('rows') or {}
    counts = child.get('counts') or {}
    if counts.get('run') != len(expected):
        reasons.append(f'실행 {counts.get("run")}건 != 기대 {len(expected)}건')
    for kind in ('failures', 'errors', 'skipped', 'xfailed', 'xpassed'):
        if counts.get(kind):
            reasons.append(f'{kind} {counts[kind]}건')
    for key in expected:
        outcome = (rows.get(key) or {}).get('outcome')
        if outcome != 'passed':
            reasons.append(f'{key}: {outcome or "결과 없음"}')
    expected_refusals = (child.get('refusals') or {}).get('selfcheck') or []
    if len(expected_refusals) != SELFCHECK_PROBES:
        reasons.append(f'자체 점검 예상 거부 {len(expected_refusals)}건 != {SELFCHECK_PROBES}건')
    real = (child.get('refusals') or {}).get('tests') or []
    if real:
        reasons.append(f'테스트 중 차단 {len(real)}건 - 예외가 잡혔더라도 실패로 본다: '
                       + ', '.join(r['event'] for r in real[:5]))
    return sorted(set(reasons), key=reasons.index)


def run_child(python, src, work, methods, adapters, pins, timeout=CHILD_TIMEOUT):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    (work / 'methods.json').write_text(json.dumps(methods), encoding='utf-8')
    (work / 'adapters.json').write_text(json.dumps(adapters), encoding='utf-8')
    cmd = [python, '-I', '-B', '-X', 'utf8', os.path.realpath(__file__), 'child', '--src', str(src),
           '--work', str(work), '--methods', str(work / 'methods.json'), '--adapters', str(work / 'adapters.json')]
    if pins is not None:
        (work / 'pins.json').write_text(json.dumps(pins), encoding='utf-8')
        cmd += ['--pins', str(work / 'pins.json')]
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(work), 'LANG': 'C.UTF-8', 'TMPDIR': str(work / 'tmp')}
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout)
        out, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out, code = f'{exc.stdout or ""}\n시간 초과 {timeout}초', -1
    secs = round(time.monotonic() - started, 1)
    line = next((ln for ln in reversed(out.splitlines()) if ln.startswith(MARKER)), None)
    if line is None:
        child = {'problems': [f'자식 프로세스가 결과를 내지 않았다 (종료 코드 {code})']}
    else:
        child = json.loads(line[len(MARKER):])
        if code != 0:
            child.setdefault('problems', []).append(f'자식 종료 코드 {code}')
    child['seconds'] = secs
    child['log_tail'] = '\n'.join(ln for ln in out.splitlines() if not ln.startswith(MARKER))[-8000:]
    return child


def run_head():
    sha = os.environ.get('GITHUB_SHA')
    if sha:
        return sha
    try:
        return git(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'rev-parse', 'HEAD').decode().strip()
    except Exception:  # noqa: BLE001
        return None


def pregate(verify, work, bundle_sha, expect=EXPECT):
    """자식을 띄우기 전 관문. verify 가 실패했거나 필수 필드가 어긋나면 사유를 돌려준다(비면 통과)."""
    reasons = []
    if not isinstance(verify, dict):
        return ['verify.json 이 객체가 아니다']
    if verify.get('problems') != []:
        reasons.append(f'verify 실패 또는 problems 없음: {verify.get("problems")!r}'[:500])
    if not (verify.get('bundle_head') == verify.get('bundle_sha') == bundle_sha):
        reasons.append(f'bundle SHA 불일치: head {verify.get("bundle_head")} · verify {verify.get("bundle_sha")} · 지정 {bundle_sha}')
    if verify.get('bundle_root') != BUNDLE_ROOT:
        reasons.append(f'bundle_root {verify.get("bundle_root")!r} != {BUNDLE_ROOT!r}')
    if verify.get('files_listed') != expect['files']:
        reasons.append(f'번들 파일 {verify.get("files_listed")}개 (기대 {expect["files"]})')
    sources = verify.get('sources')
    if not isinstance(sources, list) or len(sources) != expect['sources'] \
            or not all(isinstance(r, dict) and r.get('ok') is True and r.get('worktree_equal') is True for r in sources):
        reasons.append('소스 대조 기록이 8/8 일치가 아니다')
    elif verify.get('copy_rehash_ok') is not True:
        reasons.append('복사본 재해시가 통과하지 않았다')
    else:
        # verify 와 run 사이에 복사본이 바뀌지 않았는지 다시 잰다.
        for r in sources:
            f = Path(work, 'src', r['path'].removeprefix('source_candidate/'))
            if not f.is_file() or sha256(f.read_bytes()) != r.get('sha256'):
                reasons.append(f'실행 직전 복사본 해시 불일치: {f}')
    methods = verify.get('methods')
    keys = [(m.get('path'), m.get('class'), m.get('method')) for m in methods] \
        if isinstance(methods, list) and all(isinstance(m, dict) for m in methods) else []
    if len(keys) != expect['methods'] or len(set(keys)) != len(keys) or not all(all(k) for k in keys):
        reasons.append(f'method 목록이 {expect["methods"]}개 고유 항목이 아니다')
    pins = verify.get('pins')
    if not isinstance(pins, dict) or len(pins) != expect['pins']:
        reasons.append(f'핀이 {expect["pins"]}개가 아니다')
    return reasons


def cmd_run(args):
    work = Path(args.work)
    try:
        verify = json.loads((work / 'verify.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        verify = {'problems': [f'verify.json 을 읽지 못했다: {exc}']}
    gate = pregate(verify, work, args.bundle_sha)
    if gate:
        # 관문에서 막히면 번들 코드를 띄우지 않는다.
        child, reasons = {}, ['실행 전 관문 실패 - 자식 프로세스를 띄우지 않았다'] + gate
    else:
        child = run_child(args.python, work / 'src', work / 'run', verify['methods'], ADAPTERS, verify['pins'])
        reasons = judge(verify['methods'], child)
    results = {'verdict': 'green' if not reasons else 'red', 'reasons': reasons, 'child_started': not gate,
               'run_head': run_head(), 'bundle_head': verify.get('bundle_head') if isinstance(verify, dict) else None,
               'bundle_root': verify.get('bundle_root') if isinstance(verify, dict) else None,
               'verify': verify, 'child': child}
    Path(args.results).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
    report(results)
    return 0 if not reasons else 1


def report(results):
    child = results['child']
    verify = results['verify'] if isinstance(results['verify'], dict) else {}
    sources = verify.get('sources') if isinstance(verify.get('sources'), list) else []
    rows = child.get('rows') or {}
    refusals = child.get('refusals') or {}
    lines = [f'## 번들 runner - {results["verdict"]}', '',
             f'run HEAD `{results["run_head"]}` · bundle HEAD `{results["bundle_head"]}` · root `{results["bundle_root"]}`', '',
             f'소스 대조 {sum(bool(isinstance(r, dict) and r.get("ok")) for r in sources)}/{len(sources)} · '
             f'수집 {len(child.get("collected") or [])} · 통과 {sum(r["outcome"] == "passed" for r in rows.values())} · '
             f'자체 점검 예상 거부 {len(refusals.get("selfcheck") or [])} · 테스트 중 거부 {len(refusals.get("tests") or [])}', '']
    for a in child.get('adapters') or []:
        lines.append(f'- 어댑터 `{a["path"]}:{a["attr"]}` `{a["original"]}` -> `{a.get("adapted")}` (적용 {a["applied"]})')
    if results['reasons']:
        lines += ['', '**실패 사유**', *[f'- {r}' for r in results['reasons']]]
    lines += ['', '| method | 결과 | 초 |', '|---|---|---|']
    for key, row in rows.items():
        lines.append(f'| {key} | {row["outcome"]} | {row["seconds"]} |')
    text = '\n'.join(lines)
    print(text)
    if results['reasons'] and child.get('log_tail'):
        print('\n----- child log tail -----\n' + child['log_tail'])
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as fh:
            fh.write(text + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    v = sub.add_parser('verify')
    v.add_argument('--bundle-repo', required=True)
    v.add_argument('--bundle-sha', required=True)
    v.add_argument('--work', required=True)
    r = sub.add_parser('run')
    r.add_argument('--python', required=True)
    r.add_argument('--work', required=True)
    r.add_argument('--results', required=True)
    r.add_argument('--bundle-sha', required=True)
    c = sub.add_parser('child')
    for name in ('--src', '--work', '--methods', '--adapters'):
        c.add_argument(name, required=True)
    c.add_argument('--pins')
    args = parser.parse_args(argv)
    if not sys.platform.startswith('linux'):
        print('bundle_run 은 Linux 전용이다(/proc/self/fd 사용)')
        return 2
    return {'verify': cmd_verify, 'run': cmd_run, 'child': child_main}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
