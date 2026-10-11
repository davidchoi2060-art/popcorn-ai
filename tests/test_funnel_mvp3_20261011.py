"""유입 성과에 mvp3(팝콘톡 추천 -> 쇼핑몰 인계) 경로를 넣는다 — 2026-10-11 품질관리 F16·M3."""
import pathlib
import unittest

from api import admin_funnel as F

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Res:
    def __init__(self, scalar=0, rows=None, pairs=None):
        self._s, self._rows, self._pairs = scalar, rows or [], pairs or []
    def scalar_one(self): return self._s
    def mappings(self): return self
    def all(self): return self._rows
    def __iter__(self): return iter(self._pairs)


class _Conn:
    def __init__(self): self.sql = []
    def execute(self, stmt, params=None):
        q = str(stmt); self.sql.append((q, params))
        if 'FROM mvp3_saved_recommendations' in q and 'EXISTS' in q: return _Res(3)
        if 'FROM mvp3_saved_recommendations' in q: return _Res(4)
        if "quote_type = 'mvp3'" in q and 'total_quoted' in q:
            return _Res(rows=[{'handoff_id': 7, 'total_quoted': 1000}, {'handoff_id': 8, 'total_quoted': None}])
        if 'FROM handoff_items' in q: return _Res(pairs=[('확인됨', 1), ('가격변동', 2)])
        raise AssertionError(q)


class Mvp3Block(unittest.TestCase):
    def test_counts_saved_handed_and_lines(self):
        c = _Conn()
        m = F._mvp3_block(c, 'LO', None)
        self.assertEqual((m['saved'], m['saved_handed_off'], m['pct_of_saved']), (4, 3, 75.0))
        self.assertEqual((m['handoff_count'], m['amount_sum']), (2, 1000))
        self.assertEqual(m['lines']['가격변동'], {'n': 2, 'pct': 66.7})
        self.assertEqual(m['lines']['total'], 3)
        self.assertTrue(m['low_sample'])
        saved_sql = c.sql[0][0]
        self.assertIn('r.saved_at >= :_dt_lo', saved_sql)
        self.assertNotIn(':_dt_hi', saved_sql)
        self.assertIn('h.created_at >= :_dt_lo', c.sql[2][0])

    def test_query_only(self):
        src = (ROOT / 'api/admin_funnel.py').read_text(encoding='utf-8')
        for word in ('INSERT', 'UPDATE ', 'DELETE'):
            self.assertNotIn(word, src)

    def test_mvp3_not_counted_as_orphan_and_rendered(self):
        src = (ROOT / 'api/admin_funnel.py').read_text(encoding='utf-8')
        self.assertIn("quote_type IS DISTINCT FROM 'mvp3'", src)
        self.assertIn('"mvp3": mvp3', src)
        tpl = (ROOT / 'templates/admin/funnel.html.j2').read_text(encoding='utf-8')
        self.assertIn('renderMvp3(d);', tpl)
        self.assertIn('id="fnMvp3"', tpl)


if __name__ == '__main__':
    unittest.main()
