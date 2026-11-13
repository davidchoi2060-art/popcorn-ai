"""pytest 공용 설정 - 개발 PC 밖(클라우드 CI)에서 단위 테스트를 돌릴 때만 작동한다.

두 가지만 한다. 테스트 파일 자체는 건드리지 않는다.

1. 개발 PC 전용 자료(D:/WORK/...)를 읽다가 FileNotFoundError 가 나면, 그 경로가
   이 기계에 «없을 때만» 실패 대신 skip 으로 보고한다. PC 에서는 경로가 있으므로
   아무 일도 하지 않는다 - 거기서 파일이 없으면 여전히 실패다.

2. POPCORN_CI=1 일 때, KNOWN_FAILURES 의 테스트를 xfail(strict) 로 표시한다.
   원인이 밝혀져 있고 담당이 정해진 실패만 여기 둔다. strict 이므로 고쳐져서
   통과하기 시작하면 CI 가 빨개진다 - 그때 이 목록에서 지운다.
   목록에 없는 새 실패는 그대로 실패다.
"""
import os

import pytest

PC_ONLY_ROOT = 'D:/WORK'
PC_ONLY_OUTPUTS = 'D:/WORK/PopcornAI/outputs'

_CRLF_PIN = ('원본 파일 바이트 해시가 개발 PC 의 줄바꿈(CRLF/LF 혼재) 기준으로 고정돼 있다 - '
             '줄바꿈 정리(개선 순서 2번)에서 함께 다룬다')

KNOWN_FAILURES = {
    'tests/test_mall_supplier_write_lock_order.py::MallWriteGuardTests::'
    'test_unowned_top_level_ast_and_original_function_body_are_identical_except_guard': _CRLF_PIN,
    'tests/test_reprice_preview_expected.py::PreviewExpectedTests::'
    'test_full_module_after_exact_u4_removal_equals_accepted_policy_c_source_ast': _CRLF_PIN,
    'tests/test_reprice_write_lock_order.py::RepriceTests::'
    'test_non_owned_AST_original_bodies_after_only_allowed_sites_and_readonly_sources': _CRLF_PIN,
}


def pytest_collection_modifyitems(config, items):
    if os.environ.get('POPCORN_CI') != '1':
        return
    for item in items:
        reason = KNOWN_FAILURES.get(item.nodeid)
        if reason:
            item.add_marker(pytest.mark.xfail(reason=reason, strict=True))


def _pc_only_path(excinfo):
    if excinfo is None or not excinfo.errisinstance(FileNotFoundError):
        return None
    path = str(getattr(excinfo.value, 'filename', '') or '').replace('\\', '/')
    if path.startswith(PC_ONLY_ROOT) and not os.path.isdir(PC_ONLY_ROOT):
        return path
    # 저장소 밖 «동결 산출물»(D:/WORK/PopcornAI/outputs/<작업폴더>/...). 저장소 안 어떤
    # 스크립트도 만들지 않고 버전 관리에도 없다 - 2026-10 커머스 개통 작업 때 손으로 남긴
    # 변경 전 원본이라, 그 작업 폴더가 없는 PC(두 번째 개발 PC 등)에서는 대조 자체가 불가능하다.
    # 작업 폴더가 «있는데» 그 안 파일이 없으면 진짜 결함이므로 그때는 그대로 실패한다.
    marker = PC_ONLY_OUTPUTS + '/'
    if path.startswith(marker):
        workdir = marker + path[len(marker):].split('/', 1)[0]
        if not os.path.isdir(workdir):
            return path
    return None


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    path = _pc_only_path(call.excinfo) if report.failed else None
    if path:
        report.outcome = 'skipped'
        report.longrepr = (str(item.path), item.location[1] or 0, f'개발 PC 전용 자료 없음: {path}')
    return report


# --- 같은 테스트 파일이 두 이름으로 두 번 실행되는 것을 막는다 -------------------------
# tests/ 에는 __init__.py 가 없다. pytest 는 수집한 파일을 «test_x» 로, 다른 테스트가
# `from tests import test_x` 로 부르면 «tests.test_x» 로 올린다 - 같은 파일이 모듈 두 벌이 된다.
# 특히 test_admin_commerce_orders 는 import 시점에 api.auth 대역·audit hook 을 만들고
# api.admin_commerce_orders 를 한 번만 import(캐시)하므로, 두 번째 사본은 첫 사본이 묶어 둔
# auth 와 다른 객체를 쥔다 -> 한 프로세스에 묶어 돌리면 401!=200, `current_operator` 동일성
# 불일치가 난다(파일별로 따로 돌리는 ci_run.py 에서는 사본이 하나라 드러나지 않는다).
# 이미 올라온 쪽 모듈을 그대로 돌려줘 사본을 하나로 만든다. 검사 내용은 바꾸지 않는다.
import importlib.abc
import importlib.util
import sys


class _OneCopyFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('tests.test_'):
            other = fullname[len('tests.'):]
        elif fullname.startswith('test_') and '.' not in fullname:
            other = 'tests.' + fullname
        else:
            return None
        existing = sys.modules.get(other)
        if existing is None or getattr(existing, '__file__', None) is None:
            return None
        return importlib.util.spec_from_loader(fullname, _AliasLoader(existing), origin=existing.__file__)


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, module):
        self._module = module

    def create_module(self, spec):
        return self._module

    def exec_module(self, module):
        return None


if not any(isinstance(f, _OneCopyFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _OneCopyFinder())
