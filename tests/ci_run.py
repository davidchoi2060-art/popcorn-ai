"""단위 테스트 전체를 파일마다 따로 돌린다 - CI 와 개발 PC 공용.

왜 파일마다인가: 여러 테스트가 모듈 import 상태·전역 패치를 전제로 짜여 있어
한 프로세스에 모아 돌리면 서로를 깨뜨린다(예: application_module_already_loaded,
Unpatched DB access). 파일 단위로 격리하면 각 파일이 개발 PC 에서 혼자 돌 때와
같은 조건이 된다.

    python tests/ci_run.py            # Python + Node 둘 다
    python tests/ci_run.py --py-only

종료 코드: 실패·수집 오류·시간 초과가 하나라도 있으면 1. 다음도 실패로 본다 -
초록불이 «아무것도 안 돌았다»를 뜻하면 안 되기 때문이다:
  테스트 파일이 하나도 없음 · 파일 하나에서 테스트 0건 수집(pytest 종료 코드 5)
  Python 통과 0건 · node 없음(의존성 누락)
GITHUB_STEP_SUMMARY 가 있으면 파일별 표를 거기에도 쓴다.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / 'tests'
TIMEOUT = 600
KINDS = ('passed', 'failed', 'errors', 'skipped', 'xfailed', 'xpassed')


def run(cmd, env):
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=TIMEOUT)
        out, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out, code = f'{exc.stdout or ""}\n시간 초과 {TIMEOUT}초', -1
    return out, code, time.monotonic() - started


def pytest_counts(out):
    tail = out.strip().splitlines()[-1] if out.strip() else ''
    counts = {k: 0 for k in KINDS}
    for n, kind in re.findall(r'(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)', tail):
        counts['errors' if kind.startswith('error') else kind] += int(n)
    return counts


def run_python(env):
    rows = []
    for path in sorted(TESTS.glob('test_*.py')):
        rel = path.relative_to(ROOT).as_posix()
        out, code, secs = run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                               '--tb=short', '-rfEXs', rel], env)
        counts = pytest_counts(out)
        # conftest 가 «개발 PC 전용 자료 없음» 으로 건너뛴 수 - 건너뜀 안에 묻히지 않게 따로 센다.
        counts['pc_only'] = sum(int(n) for n in re.findall(r'^SKIPPED \[(\d+)\].*개발 PC 전용', out, re.M))
        # 0 만 정상이다. 5(수집된 테스트 0건)도 실패로 본다 - import 가 조용히 비어도 초록이 되지 않게.
        # 그 밖의 코드인데 실패 수가 0이면 수집 오류(의존성 누락 포함)다.
        bad = code != 0 or counts['failed'] or counts['errors'] or counts['xpassed']
        if bad and not (counts['failed'] or counts['errors'] or counts['xpassed']):
            counts['errors'] = 1
            if code == 5:
                out += '\n테스트 0건 수집 - 실패로 처리한다'
        rows.append((rel, counts, secs, out if bad else ''))
    return rows


def run_node(env):
    rows = []
    node = shutil.which('node')
    for path in sorted(TESTS.glob('*.cjs')):
        rel = path.relative_to(ROOT).as_posix()
        counts = {k: 0 for k in KINDS}
        if node is None:
            counts['errors'] = 1
            rows.append((rel, counts, 0.0, 'node 없음 - 의존성 누락으로 실패 처리'))
            continue
        # 리포 규약상 npm 을 쓰지 않는다 - jsdom 같은 외부 패키지가 필요한 파일은 건너뛴다.
        if re.search(r"require\(['\"]jsdom['\"]\)", path.read_text(encoding='utf-8')):
            print(f'SKIP {rel}  (jsdom 필요 - npm 미사용 규약)')
            counts['skipped'] = 1
            rows.append((rel, counts, 0.0, ''))
            continue
        out, code, secs = run([node, '--test', rel], env)
        passed = sum(int(n) for n in re.findall(r'^# pass (\d+)', out, re.M))
        failed = sum(int(n) for n in re.findall(r'^# fail (\d+)', out, re.M))
        counts['passed'], counts['failed'] = passed, failed
        if code != 0 and not failed:
            counts['errors'] = 1
        rows.append((rel, counts, secs, out if code != 0 else ''))
    return rows


def report(rows, problems):
    total = {k: sum(r[1][k] for r in rows) for k in KINDS}
    pc_only = sum(r[1].get('pc_only', 0) for r in rows)
    pc_files = [r[0] for r in rows if r[1].get('pc_only')]
    broken = [r for r in rows if r[1]['failed'] or r[1]['errors'] or r[1]['xpassed']]
    for msg in problems:
        print(f'FAIL {msg}')
    for rel, counts, secs, out in broken:
        print(f'\n===== {rel} =====\n{out.strip()[-6000:]}')
    print('\n' + ' · '.join(f'{k} {total[k]}' for k in KINDS) + f'  ({len(rows)} files)')
    if pc_only:
        print(f'PC only: {pc_only} skipped in {len(pc_files)} files (D:/WORK 자료 없음)')
    for rel, counts, secs, _ in broken:
        print(f'  FAIL {rel}  ' + ' '.join(f'{k}={v}' for k, v in counts.items() if v))

    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        lines = ['## 단위 테스트', '', ' · '.join(f'{k} **{total[k]}**' for k in KINDS), '']
        if pc_only:
            lines += [f'**PC 전용으로 건너뜀 {pc_only}건** ({len(pc_files)}개 파일) - 개발 PC 의 D:/WORK 자료를 읽는 테스트라 '
                      '이 기계에서는 돌지 않는다. 건너뜀 수에 포함돼 있다.', '',
                      *[f'- {f}' for f in pc_files], '']
        lines += ['| 파일 | ' + ' | '.join(KINDS) + ' | 초 |', '|' + '---|' * (len(KINDS) + 2)]
        for rel, counts, secs, _ in rows:
            mark = ' ❌' if (counts['failed'] or counts['errors'] or counts['xpassed']) else ''
            lines.append(f'| {rel}{mark} | ' + ' | '.join(str(counts[k]) for k in KINDS) + f' | {secs:.1f} |')
        with open(summary, 'a', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
    return 1 if broken or problems else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--py-only', action='store_true')
    args = parser.parse_args()
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    rows = run_python(env)
    problems = []
    if not rows:
        problems.append('tests/test_*.py 를 하나도 찾지 못했다')
    elif sum(r[1]['passed'] for r in rows) == 0:
        problems.append('Python 테스트 통과 0건 - 아무것도 돌지 않았다')
    if not args.py_only:
        node_rows = run_node(env)
        if not node_rows:
            problems.append('tests/*.cjs 를 하나도 찾지 못했다')
        rows += node_rows
    return report(rows, problems)


if __name__ == '__main__':
    sys.exit(main())
