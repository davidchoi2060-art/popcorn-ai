"""사무용 «기본» 램 기준 8GB -> 16GB (2026-10-13 사장님 「R03은 16GB로 해」).

기준이 세 군데에 있다 -- 코드 기준표(tools/product_fit.REQUIREMENTS: 신규 조립PC 평가), DB 기준표 문장
(product_fit_levels: 상담 설명), 몰 PC 평가(product_usage_fit: 고객 카드). 0157 이 DB 둘을, 이 PR 이 코드를 맞춘다.
개발 DB 에서 0157 upgrade -> downgrade 를 한 트랜잭션으로 돌리고 ROLLBACK 한 기록은 PR 본문에 있다.
"""
import importlib.util
import json
import unittest
from pathlib import Path

from api import custom_pc_fit as F
from tools.product_fit import REQUIREMENTS

ROOT = Path(__file__).resolve().parent.parent
MIG = ROOT / "db" / "migrations" / "versions" / "0157_office_basic_ram_16gb.py"


def _mig():
    spec = importlib.util.spec_from_file_location("m0157", MIG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def office_parts(ram="DDR4 8GB", qty=1):
    return [dict(slot="CPU", name="인텔 코어 i3-12100", quantity=1), dict(slot="RAM", name=ram, quantity=qty),
            dict(slot="SSD", name="NVMe 256GB", quantity=1)]


class OfficeRam16Tests(unittest.TestCase):
    def test_code_table_office_basic_needs_16gb(self):
        basic = next(s for s in REQUIREMENTS["사무용"] if s[0] == "기본")
        self.assertEqual(basic[2]["ram"], 16)
        self.assertEqual(next(s for s in REQUIREMENTS["사무용"] if s[0] == "쾌적")[2]["ram"], 16)   # 쾌적은 그대로

    def test_new_custom_pc_with_8gb_is_not_office_basic(self):
        self.assertEqual(F.judge(F.spec_from_parts(office_parts()), "사무용", "기본"), "short")
        self.assertEqual(F.judge(F.spec_from_parts(office_parts("DDR4 8GB", 2)), "사무용", "기본"), "fit")

    def test_migration_chain_and_text_match_code(self):
        m = _mig()
        self.assertEqual((m.revision, m.down_revision), ("0157", "0156"))
        self.assertEqual(m.MIN_RAM, next(s for s in REQUIREMENTS["사무용"] if s[0] == "기본")[2]["ram"])
        self.assertEqual((m.OLD_COND, m.NEW_COND), ("램 8GB 이상", "램 16GB 이상"))
        self.assertEqual(sorted(p.name for p in MIG.parent.glob("0157_*.py")), [MIG.name])

    def test_downgrade_source_has_the_rows_upgrade_moves(self):
        d = json.loads((ROOT / "db" / "migrations" / "data" / "product_fit_20260925.json").read_text(encoding="utf-8"))
        office_basic_8 = [p for p in d["products"] for f in p["fit"]
                          if f["usage"] == "사무용" and f["level"] == "기본"
                          and isinstance(p["spec"].get("ram_gb"), (int, float)) and p["spec"]["ram_gb"] < 16]
        self.assertEqual(len(office_basic_8), 18)     # 개발 DB 실측 upgrade 18행과 같다 -> downgrade 가 전부 되살린다


if __name__ == "__main__":
    unittest.main()
