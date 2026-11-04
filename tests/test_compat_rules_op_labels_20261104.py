"""ADMIN-ROW04-IN — 호환 규칙 연산 표시가 엔진의 연산과 «층마다» 같은 집합인가 (2026-11-04).

계기: 0160 `case_psu_form` 이 op 'in' 을 쓰는데 `admin_engine_rules.OP_KO` 에 'in' 이 없어
API 가 원문 "in" 을 내보냈고, 조립 호환 규칙 서랍의 연산 select 에는 맞는 옵션이 없어
빈칸이 됐다. 엔진(`recommend._cmp`)은 이미 'in' 을 판정하고 있었다 — 표시만 빠졌다.

무엇을 증명하나 (DB 없이):
  ① 엔진 연산 집합은 `recommend._cmp` 소스(AST)에서 읽는다 — 목록을 여기 다시 적지 않는다.
     그 집합이 OP_KO 에 전부 있다(엔진이 연산을 늘리면 이 테스트가 먼저 실패한다).
  ② 마이그레이션이 compat_rules 에 넣은 op 값도 전부 OP_KO 에 있다.
  ③ 라벨은 서로 모두 다르다 — 특히 'in'(대상이 상대 목록에 속함)과 'contains'(대상 목록이
     상대를 포함)는 방향이 반대라 같은 낱말이면 안 된다.
  ④ OP_KO 의 모든 라벨이 서랍 select(#cr-edit-op)의 option value 로 있다 — 없으면 빈칸이 된다.
  ⑤ engine_rules() 를 메모리 fixture 로 부르면 'in' 규칙이 원문 " in " 없이 라벨로 나오고,
     다른 네 연산의 rule 문자열은 바뀌지 않는다.
  ⑥ 저장은 여전히 잠겨 있다(이번 수정은 읽기 표시만).
"""
import ast
import os
import re
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from api import admin_engine_rules as AER  # noqa: E402
from api import spec_fields as SF  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin" / "compat_rules.html.j2"
MIGRATIONS = ROOT / "db" / "migrations" / "versions"
SLOTS_RE = "CPU|MB|RAM|GPU|CASE|COOLER|POWER|SSD|HDD"


def engine_ops() -> set:
    """recommend._cmp 의 `op == "…"` 비교에서 연산 이름을 읽는다."""
    tree = ast.parse((ROOT / "api" / "recommend.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_cmp")
    ops = set()
    for n in ast.walk(fn):
        if (isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == "op"
                and len(n.ops) == 1 and isinstance(n.ops[0], ast.Eq)
                and isinstance(n.comparators[0], ast.Constant)):
            ops.add(n.comparators[0].value)
    return ops


def migration_ops() -> set:
    """compat_rules 행을 넣거나 고치는 마이그레이션의 op 값.

    두 모양을 읽는다: (rule_key, slot, field, op, …) 튜플·VALUES — slot 이름에 고정해 잡는다 —
    그리고 `op='…'` 대입.
    """
    tup = re.compile(r"\(\s*['\"]\w+['\"]\s*,\s*['\"](?:%s)['\"]\s*,\s*['\"]\w+['\"]\s*,\s*['\"](\w+)['\"]"
                     % SLOTS_RE)
    assign = re.compile(r"\bop\s*=\s*'(\w+)'")
    ops = set()
    for f in sorted(MIGRATIONS.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        if "compat_rules" not in src:
            continue
        ops |= set(tup.findall(src)) | set(assign.findall(src))
    return ops


def select_values() -> list:
    html = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r'<select[^>]*id="cr-edit-op"[^>]*>(.*?)</select>', html, re.S)
    assert m, "서랍 연산 select(#cr-edit-op)를 찾지 못했다"
    return re.findall(r'<option value="([^"]*)"', m.group(1))


RULES = [
    dict(rule_key="socket", slot="MB", field="socket", op="eq", ref_slot="CPU", ref_field="socket"),
    dict(rule_key="gpu_len", slot="CASE", field="gpu_max_mm", op="gte", ref_slot="GPU", ref_field="length_mm"),
    dict(rule_key="cooler_height", slot="COOLER", field="cooler_height_mm", op="lte",
         ref_slot="CASE", ref_field="cooler_height_mm"),
    dict(rule_key="case_board", slot="CASE", field="form_factor_list", op="contains",
         ref_slot="MB", ref_field="form_factor"),
    dict(rule_key="case_psu_form", slot="POWER", field="form_factor", op="in",
         ref_slot="CASE", ref_field="psu_form_factor_list"),
]
for _r in RULES:
    _r.update(label=_r["rule_key"], blocking=True, active=True, part_types=[], ref_offset=0,
              null_ref_mode="fail")


class _Res:
    def __init__(self, rows=None, scalar=None):
        self.rows, self.scalar = rows or [], scalar

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class _Conn:
    def __init__(self):
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, *a, **k):
        sql = str(stmt)
        self.sql.append(sql)
        if "FROM compat_rules" in sql:
            return _Res(RULES)
        if "v_recommendation_candidates" in sql:
            return _Res(scalar=0)
        return _Res([])


class _Engine:
    def __init__(self):
        self.conns = []

    def connect(self):
        c = _Conn()
        self.conns.append(c)
        return c


class CompatOpLabels(unittest.TestCase):
    def test_engine_ops_read_from_source(self):
        ops = engine_ops()
        # 읽기가 조용히 비면 아래 검사가 전부 공허해진다 — 알려진 다섯이 다 잡히는지 먼저 본다
        self.assertTrue({"eq", "gte", "lte", "contains", "in"} <= ops, ops)

    def test_every_engine_op_has_label(self):
        self.assertEqual(engine_ops() - set(AER.OP_KO), set())

    def test_every_migration_op_has_label(self):
        ops = migration_ops()
        self.assertIn("in", ops)        # 0160 case_psu_form
        self.assertIn("contains", ops)  # 0019 case_board 등
        self.assertEqual(ops - set(AER.OP_KO), set())

    def test_labels_are_distinct(self):
        labels = list(AER.OP_KO.values())
        self.assertEqual(len(labels), len(set(labels)), AER.OP_KO)
        self.assertNotEqual(AER.OP_KO["in"], AER.OP_KO["contains"])

    def test_every_label_is_a_drawer_option(self):
        values = select_values()
        self.assertEqual(len(values), len(set(values)), values)
        self.assertEqual(set(AER.OP_KO.values()) - set(values), set())

    def test_engine_rules_renders_label_not_raw_op(self):
        eng = _Engine()
        with mock.patch.object(AER, "engine", eng), \
                mock.patch.object(SF, "required_map", lambda: {}), \
                mock.patch.object(SF, "all_fields", lambda: []), \
                mock.patch.object(SF, "rule_readers", lambda conn: {}):
            out = AER.engine_rules()
        rules = {c["key"]: c["rule"] for c in out["compat"]["checks"]}
        self.assertEqual(rules["case_psu_form"], "POWER.form_factor 속함 CASE.psu_form_factor_list")
        self.assertNotIn(" in ", rules["case_psu_form"])
        # 다른 네 연산은 그대로
        self.assertEqual(rules["socket"], "MB.socket = CPU.socket")
        self.assertEqual(rules["gpu_len"], "CASE.gpu_max_mm ≥ GPU.length_mm")
        self.assertEqual(rules["cooler_height"], "COOLER.cooler_height_mm ≤ CASE.cooler_height_mm")
        self.assertEqual(rules["case_board"], "CASE.form_factor_list 포함 MB.form_factor")
        # 읽기만 — 실행한 SQL 에 쓰기가 없다
        sql = " ".join(s for c in eng.conns for s in c.sql).upper()
        for verb in ("INSERT ", "UPDATE ", "DELETE "):
            self.assertNotIn(verb, sql)

    def test_save_stays_locked(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertRegex(html, r'class="cr-btn cr-btn--locked" disabled')
        self.assertIn("저장 기능이 연결되기 전까지는 저장할 수 없습니다", html)


if __name__ == "__main__":
    unittest.main()
