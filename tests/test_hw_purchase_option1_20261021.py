"""AI 하드웨어 구매 1안 (2026-10-21 대표 승인 「그래 그렇게 작업해서 전달해줘」·「그래.. 이것도.. 전달해」).

① AI 슈퍼컴퓨터 상세: 주 버튼 「팝콘PC몰에서 구매」(고른 모델·수량의 정확한 몰 상품), 보조 「견적에 저장」·「AI로 비교하기」,
   약한 「AI 설치·구축 상담」. ② 몰 이동 전 가격 변동 안내창(돌아가기 / 팝콘PC몰로 이동) -- 일반 PC 에도 같다.
③ 업무형(문서·회의·답변) 구축 과정 뒤·상담 앞 「업무별 PC」 -- 검증 후보만, 없으면 사유와 상담 길(고성능 자동 대체 없음).
④ 내 견적 개별 삭제(숨김 -> 되돌리기로 실제 복원). ⑤ 비교 담기·빼기(종류 구분·중복 방지), 선택 해제.
"""
import json
import pathlib
import re
import shutil
import subprocess
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException
from starlette.requests import Request

from api import customer_supercomputer as sc
from api import mvp3_saved_quotes as m

ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = ROOT / "mockups/mvp4/assets/js"
MALL = "https://www.popcornpc.co.kr/shop/"


def src(name):
    return (JS / name).read_text(encoding="utf-8")


def request(method="DELETE", path="/api/mvp3/saved-quotes/x"):
    return Request({"type": "http", "method": method, "scheme": "https", "server": ("example.invalid", 443),
                    "path": path, "query_string": b"", "headers": [(b"host", b"example.invalid"), (b"x-access-key", b"a" * 64)]})


class Rows:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None
    def one(self): return self.rows[0]
    def all(self): return self.rows


class Engine:
    """SQL 을 적어 두고 정해 둔 행을 돌려준다."""
    def __init__(self, rows=()):
        self.rows = list(rows); self.sql = []
    @contextmanager
    def begin(self): yield self
    connect = begin
    def execute(self, sql, p=None):
        self.sql.append((str(sql), p)); return Rows(self.rows)


class MallUrlServer(unittest.TestCase):
    def test_supercomputer_items_carry_the_exact_mall_page(self):
        self.assertEqual(sc.product_url(129615, "AI_SUPERCOMPUTER") if hasattr(sc, "product_url") else None,
                         MALL + "product_detail.html?pd_no=129615")
        self.assertIn("p.part_type", sc._COLS)
        self.assertIn("'mall_url': product_url(r['product_code'], r.get('part_type'))", (ROOT / "api/customer_supercomputer.py").read_text())

    def test_general_pc_stays_system_detail(self):
        from api.mall_price_reader import product_url
        self.assertEqual(product_url(113835, "PC_COMPLETE"), MALL + "system_detail.html?pd_no=113835")


class DeviceSave(unittest.TestCase):
    def body(self, **kw):
        return m.SaveBody(**{"request_id": UUID(int=7), "product_code": 129614, "expected_price": 14209400, "kind": "ai_device", "sets": 2, **kw})

    def test_pc_fingerprint_unchanged_by_kind(self):
        old = m.SaveBody(request_id=UUID(int=1), product_code=17, expected_price=1, state={"usages": ["게임"]})
        self.assertNotIn('"kind"', m.fingerprint(old) if isinstance(m.fingerprint(old), str) else json.dumps(m.fingerprint(old)))

    def test_device_snapshot_never_rewrites_sale_price_or_asks_contact(self):
        found = {"name": "Dell Pro Max GB10", "model_label": "4TB", "price": 14209400, "sale_state": "on_sale", "memory": "128GB",
                 "storage": "4TB", "accelerator": "NVIDIA GB10", "mall_url": MALL + "product_detail.html?pd_no=129614"}
        with patch.object(m, "engine", Engine()), patch.object(m.customer_supercomputer, "load", return_value={129614: found}), \
             patch.object(m.mall_price_live, "check", side_effect=AssertionError("몰 가격으로 판매가를 고치면 안 된다"), create=True):
            snap = m.device_product(129614, 14209400)
        self.assertEqual(snap["kind"], "ai_device"); self.assertEqual(snap["price_src"], "팝콘AI 표시 금액")
        self.assertFalse(snap["price_confirmed"]); self.assertEqual(snap["mall_url"], found["mall_url"])
        save_src = (ROOT / "api/mvp3_saved_quotes.py").read_text()
        dev = save_src[save_src.index("def device_product"):save_src.index("def _owned")]
        self.assertNotIn("mall_price_live", dev.replace("팝콘PC몰 가격을 읽어 우리 판매가를 고치는 장치(mall_price_live)", ""))
        self.assertIn("if body.purpose == 'keep' and body.kind == 'pc':", save_src)   # 연락처 요구는 일반 PC 보관에만

    def test_stopped_or_unpriced_or_unknown_device_is_refused(self):
        for found in ({}, {129614: {"sale_state": "stopped", "price": None}}, {129614: {"sale_state": "on_sale", "price": None}}):
            with patch.object(m, "engine", Engine()), patch.object(m.customer_supercomputer, "load", return_value=found):
                with self.assertRaises(HTTPException) as e:
                    m.device_product(129614, 1)
                self.assertEqual(e.exception.status_code, 409)


class HideRestore(unittest.TestCase):
    def call(self, fn, rows, qid="11111111-2222-4333-8444-555555555555"):
        eng = Engine(rows)
        with patch.object(m, "engine", eng), patch.object(m.visitor, "resolve", return_value=42), \
             patch.object(m, "with_live_offer", side_effect=lambda q: q):
            out = fn(qid, request(), m.Response())
        return out, eng.sql

    def test_delete_hides_only_this_browsers_row_and_keeps_the_ledger(self):
        out, sql = self.call(m.hide_quote, [{"quote_id": "x"}])
        self.assertEqual(out, {"ok": True, "id": "11111111-2222-4333-8444-555555555555", "hidden": True, "restorable": True})
        stmt, p = sql[-1]
        self.assertTrue(stmt.lstrip().startswith("UPDATE mvp3_saved_recommendations"))
        self.assertNotIn("DELETE", stmt.upper())
        self.assertIn("user_id=:u AND owner_key_hash=:owner", stmt)
        self.assertEqual((p["u"], p["owner"]), (42, m.owner_hash(request())))
        self.assertIn("THEN product_snapshot", stmt)   # 다시 눌러도 같은 결과

    def test_restore_removes_the_mark(self):
        from datetime import datetime, timezone
        row = {"quote_id": "q", "product_snapshot": {"product_code": 1}, "talk_state": {}, "saved_at": datetime.now(timezone.utc)}
        out, sql = self.call(m.restore_quote, [row])
        self.assertIn("product_snapshot - 'hidden_at'", sql[-1][0]); self.assertTrue(out["ok"])

    def test_other_browsers_or_bad_ids_get_404(self):
        for fn in (m.hide_quote, m.restore_quote):
            with self.assertRaises(HTTPException) as e:
                self.call(fn, [])
            self.assertEqual(e.exception.status_code, 404)
            with self.assertRaises(HTTPException) as e:
                self.call(fn, [{"quote_id": "x"}], qid="not-a-uuid")
            self.assertEqual(e.exception.status_code, 404)

    def test_list_skips_hidden(self):
        self.assertIn("AND NOT (product_snapshot ? 'hidden_at')", (ROOT / "api/mvp3_saved_quotes.py").read_text())


def node(code):
    return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)


@unittest.skipUnless(shutil.which("node"), "node 없음")
class MallGuide(unittest.TestCase):
    def test_link_only_to_the_same_product_on_either_mall_path(self):
        cases = [("129615", MALL + "product_detail.html?pd_no=129615"), ("113835", MALL + "system_detail.html?pd_no=113835"),
                 ("129615", MALL + "product_detail.html?pd_no=129614"), ("129615", MALL + "search.html?q=129615"),
                 ("129615", "http://www.popcornpc.co.kr/shop/product_detail.html?pd_no=129615"),
                 ("129615", MALL + "product_detail.html?pd_no=129615#x"), ("129615", None)]
        code = "var window={},document={addEventListener:function(){}};" + src("mall-buy-guide.js") + \
               ";var P=window.PAI;console.log(JSON.stringify(" + json.dumps(cases) + ".map(function(c){return P.mallUrlFor(c[0],c[1]);})))"
        self.assertEqual(node(code), [cases[0][1], cases[1][1], "", "", "", "", ""])

    def test_dialog_words_and_no_form(self):
        s = re.sub(r"</?strong>", "", src("mall-buy-guide.js"))
        for t in ("팝콘PC몰에서 구매를 이어갑니다.", "부품 가격이 수시로 변경되어 표시 금액과 실제 판매 금액이 다를 수 있습니다. 구매 전 팝콘PC몰에서 최종 가격과 구성을 확인해 주세요.",
                  "구매 수량은 팝콘PC몰에서 다시 확인해 주세요.", "돌아가기", "팝콘PC몰로 이동", "가격 확인 필요", "팝콘AI 표시 금액"):
            self.assertIn(t, s)
        code = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
        for banned in ("<form", "<input", "fetch(", "localStorage", "동의"):
            self.assertNotIn(banned, code)


class SupercomputerPanel(unittest.TestCase):
    def test_states_and_secondary_actions(self):
        s = src("supercomputer-detail.js")
        for t in ("팝콘PC몰에서 구매", "견적에 저장", "AI로 비교하기", "AI 설치·구축 상담", "판매 중지", "팝콘PC몰 구매 링크 확인 필요",
                  "저장만으로 상담이 신청되지는 않습니다.", "이미 내 견적에 저장한 구성이에요."):
            self.assertIn(t, s)
        self.assertNotIn("0원", s)


class SavedDeleteAndCompare(unittest.TestCase):
    def test_saved_delete_undo_and_failure(self):
        s = src("live-checkout.js")
        for t in ("data-saved-delete", "내 견적에서 삭제", "되돌리기", "상담·주문 기록은 그대로예요.", "ds-saved-error"):
            self.assertIn(t, s)
        c = src("saved-quotes-client.js")
        self.assertIn("'DELETE'", c); self.assertIn("/restore", c)

    def test_compare_kinds_dedupe_and_unselect(self):
        s = src("design-conversation.js")
        for t in ("data-dc-unselect", "선택 해제", "비교에서 빼기", "data-pa-kind", "AI 장비", "(장비 메모리 · 그래픽카드 전용 메모리와 같은 기준 아님)"):
            self.assertIn(t, s)
        unselect = s[s.index("node.hasAttribute('data-dc-unselect')"):]
        unselect = unselect[:unselect.index("return; }")]
        self.assertIn("model.selected = null", unselect)
        for kept in ("model.draft", "model.conditions", "model.log", "model.compare", "liveTalk", "send("):
            self.assertNotIn(kept, unselect)   # 선택 해제는 선택만 비운다
        carry = src("compare-carry.js")
        self.assertIn("pai-compare-carry-v1", carry)


class TaskPc(unittest.TestCase):
    def test_honest_empty_state_without_layout_examples(self):
        s = re.sub(r"/\*.*?\*/", "", src("ai-task-pc.js"), flags=re.S)   # 머리 주석은 경위 설명이라 뺀다
        self.assertIn("이 업무로 확인을 마친 PC가 아직 없어요.", s)
        for code in ("127316", "129615", "129614"):
            self.assertNotIn(code, s)   # 배치 예시 상품을 후보처럼 내보내지 않는다
        self.assertIsNone(re.search(r"\d{1,3},\d{3}원", s))
        self.assertIn("P.taskPc ? P.taskPc.insert(g.body(), use)", src("ai-local-service.js"))


if __name__ == "__main__":
    unittest.main()
