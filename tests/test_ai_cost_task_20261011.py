"""AI 비용 기록의 작업 종류 · 문의 번호 — 2026-10-11 품질관리 F6·F18 회귀 고정 (0141)."""
import inspect
import pathlib
import unittest

from sqlalchemy.exc import ProgrammingError

from api import admin_ai_usage as U, llm, talk, talk_answer

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Res:
    def __init__(self, v=None, rowcount=0): self.v, self.rowcount = v, rowcount
    def scalar_one(self): return self.v


class _Conn:
    def __init__(self, log, fail_first=None):
        self.log, self.fail_first = log, fail_first

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, stmt, params=None):
        self.log.append((str(stmt), params))
        if self.fail_first is not None and len(self.log) == 1:
            raise self.fail_first
        return _Res(7, rowcount=len(params.get("ids", [])) if params else 0)


class _Engine:
    def __init__(self, fail_first=None): self.log, self.fail_first = [], fail_first
    def begin(self): return _Conn(self.log, self.fail_first)


def _swap(mod, eng):
    orig = mod.engine
    mod.engine = eng
    return lambda: setattr(mod, "engine", orig)


ROW = {"p": "claude", "m": "m", "ti": 1, "to": 2, "c": 0.001, "tk": "task.s1_parse"}


class CostLogInsert(unittest.TestCase):
    def test_task_key_is_written(self):
        eng = _Engine()
        undo = _swap(llm, eng)
        try:
            self.assertEqual(llm._insert_cost_log(dict(ROW)), 7)
        finally:
            undo()
        self.assertEqual(len(eng.log), 1)
        self.assertIn("task_key", eng.log[0][0])

    def test_falls_back_when_column_missing(self):
        err = ProgrammingError("INSERT", {}, Exception('column "task_key" does not exist'))
        eng = _Engine(fail_first=err)
        undo = _swap(llm, eng)
        try:
            self.assertEqual(llm._insert_cost_log(dict(ROW)), 7)
        finally:
            undo()
        self.assertEqual(len(eng.log), 2)
        self.assertNotIn("task_key", eng.log[1][0])

    def test_other_errors_are_not_hidden(self):
        err = ProgrammingError("INSERT", {}, Exception('relation "api_cost_logs" does not exist'))
        undo = _swap(llm, _Engine(fail_first=err))
        try:
            with self.assertRaises(ProgrammingError):
                llm._insert_cost_log(dict(ROW))
        finally:
            undo()

    def test_call_one_passes_task_key(self):
        src = inspect.getsource(llm._call_one)
        self.assertIn('"tk": (task_key or None)', src)
        self.assertIn("_insert_cost_log(row)", src)


class HitLink(unittest.TestCase):
    def test_links_only_new_rows(self):
        eng = _Engine()
        undo = _swap(talk, eng)
        try:
            n = talk._link_cost_logs(42, [11, None, 12])
        finally:
            undo()
        self.assertEqual(n, 2)
        sql, params = eng.log[0]
        self.assertIn("hit_id IS NULL", sql)
        self.assertEqual(params, {"h": 42, "ids": [11, 12]})

    def test_nothing_to_link(self):
        eng = _Engine()
        undo = _swap(talk, eng)
        try:
            self.assertEqual(talk._link_cost_logs(None, [1]), 0)
            self.assertEqual(talk._link_cost_logs(5, [None, None]), 0)
        finally:
            undo()
        self.assertEqual(eng.log, [])

    def test_failure_does_not_break_consult(self):
        undo = _swap(talk, _Engine(fail_first=RuntimeError("db down")))
        try:
            self.assertEqual(talk._link_cost_logs(5, [1]), 0)
        finally:
            undo()

    def test_both_paths_are_linked(self):
        self.assertIn("res.log_id = out.log_id", inspect.getsource(talk_answer.answer_path))
        src = inspect.getsource(talk)
        self.assertIn('_link_cost_logs(hit_id, [getattr(result, "log_id", None), getattr(ans, "log_id", None)])', src)


class TaskBreakdown(unittest.TestCase):
    def test_without_columns_stays_schema_missing(self):
        b = U._task_breakdown(False, True, [])
        self.assertTrue(b["schema_missing"])
        self.assertFalse(b["available"])

    def test_rows_by_task_and_untagged(self):
        rows = [{"task_key": "task.s1_parse", "n": 3, "cost": 0.3, "tokens": 300},
                {"task_key": "task.talk_answer", "n": 2, "cost": 0.2, "tokens": 200},
                {"task_key": None, "n": 9, "cost": 1.5, "tokens": 900}]
        b = U._task_breakdown(True, True, rows)
        self.assertTrue(b["available"])
        by = {r["name"]: r for r in b["rows"]}
        self.assertEqual(by["입력 파싱"]["cost"], 0.3)
        self.assertEqual(by["팝콘톡 답변"]["tokens"], 200)
        self.assertEqual(by["운영 도우미"]["cost"], 0.0)
        self.assertEqual(by[U.UNTAGGED_LABEL]["cost"], 1.5)
        self.assertIn("2026-10-11", b["reason"])

    def test_no_records_is_not_zero(self):
        b = U._task_breakdown(True, False, [])
        self.assertFalse(b["available"])
        self.assertTrue(all(r["cost"] is None for r in b["rows"]))


class Migration(unittest.TestCase):
    def test_existing_rows_untouched(self):
        src = (ROOT / "db/migrations/versions/0141_api_cost_log_task.py").read_text()
        self.assertNotIn("UPDATE", src)
        self.assertIn("ADD COLUMN task_key", src)
        self.assertIn("ADD COLUMN hit_id", src)
        self.assertIn("must be preserved", src)


if __name__ == "__main__":
    unittest.main()
