"""견적 상담 기록 — 상담 한 건에 처리 상태·메모를 남긴다(2026-10-11 품질관리 · 개편 16번 · F8).

DB 없이 확인하는 것: 입력 검사 · 권한 · 표 없을 때 목록이 그대로 나감 · 마이그레이션 사슬 · 화면 연결.
DB 를 거치는 저장은 로컬 Postgres 로 따로 확인했다(PR 본문).
"""
import importlib.util
import pathlib
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api import admin_sessions as AS

ROOT = pathlib.Path(__file__).resolve().parents[1]


class SaveNote(unittest.TestCase):
    def call(self, role='operator', **kw):
        body = dict(status='처리 중', memo='전화함')
        body.update(kw)
        with patch.object(AS, 'current_operator', lambda: {'role': role, 'operator_id': 1}):
            return AS.save_note(1, AS.NoteBody(**body))

    def test_rejects_bad_input_and_viewer(self):
        for kw in ({'status': '보류'}, {'memo': '가' * 1001}):
            with self.subTest(kw=kw), self.assertRaises(HTTPException) as c:
                self.call(**kw)
            self.assertEqual(c.exception.status_code, 400)
        with self.assertRaises(HTTPException) as c:
            self.call(role='viewer')
        self.assertEqual(c.exception.status_code, 403)


def _broken(exc):
    class Broken:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            raise exc
    return Broken()


class LoadNotes(unittest.TestCase):
    def test_missing_table_returns_none(self):
        exc = RuntimeError('relation "consult_session_notes" does not exist')
        with patch.object(AS.engine, 'connect', lambda: _broken(exc)):
            self.assertEqual(AS._load_notes([1, 2]), (None, 'missing'))

    def test_undefined_table_code_is_missing(self):
        class Orig(Exception):
            pgcode = '42P01'
        exc = RuntimeError('x')
        exc.orig = Orig()
        with patch.object(AS.engine, 'connect', lambda: _broken(exc)):
            self.assertEqual(AS._load_notes([1]), (None, 'missing'))

    def test_other_failure_is_not_called_missing(self):
        # 연결 · 권한 실패를 「표가 아직 없다」로 안내하지 않는다(코덱스 검수 #116)
        for exc in (RuntimeError('could not connect to server'),
                    RuntimeError('permission denied for table consult_session_notes')):
            with patch.object(AS.engine, 'connect', lambda: _broken(exc)):
                self.assertEqual(AS._load_notes([1]), (None, 'error'))

    def test_screen_tells_failure_apart(self):
        t = (ROOT / 'templates/admin/consult_sessions.html.j2').read_text(encoding='utf-8')
        self.assertIn("notes_error === 'missing'", t)
        self.assertIn('DB 조회 실패', t)


class Screen(unittest.TestCase):
    def test_drawer_has_note_form(self):
        t = (ROOT / 'templates/admin/consult_sessions.html.j2').read_text(encoding='utf-8')
        for s in ("/note'", 'noteStatus', 'noteMemo', 'notes_ready'):
            self.assertIn(s, t)


class Migration(unittest.TestCase):
    def test_revision(self):
        p = ROOT / 'db/migrations/versions/0152_consult_session_notes.py'
        spec = importlib.util.spec_from_file_location('m0152', p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual(m.revision, '0152')
        self.assertTrue(list((ROOT / 'db/migrations/versions').glob(m.down_revision + '_*.py')))


if __name__ == '__main__':
    unittest.main()
