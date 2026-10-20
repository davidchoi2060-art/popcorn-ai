"""상담 AI 가 이름으로 가리킨 판매 PC를 그대로 찾는다 -- 2026-10-20 대표 신고.

신고: AI 가 추천한 「골드 [14400F/16G/1TB/RTX5060]」은 팝콘PC 의 「골드 NO.04.102112 [화이트상품 1위][14400F/16G/1TB/RTX5060]」
인데, 「이 제품을 팝콘피씨에서 보여줘」에 「판매 목록에서 확인되지 않는다」며 골드 인텔 [12400F/16GB/500GB/RTX5060] 을 냈다.
공개 목록(/api/customer/pc-catalog, 2026-10-20 실측)에서 102112 는 판매중 1,915,500원 · 몰 pd_no=102112 로 실재했다.
원인: 상담 AI 에 이름으로 찾는 도구가 없어 용도 조건으로 다시 찾았고, 그 결과 3장 안에 없으면 「없다」고 말했다.
아래 상품 값은 그날 공개 목록의 이름·가격을 옮긴 것이다(AI 응답은 흉내 낸다 -- 실제 공급자 호출 없음).
"""
import contextlib
import json
import unittest
from unittest.mock import patch

from api import llm, talk_agent as AG, talk_tools as TT
from api.talk_schema import Vocab


def _p(code, name, price, cpu, gpu, ram, ssd, status="판매중"):
    return {"code": code, "name": name, "price": price, "status": status,
            "url": f"https://www.popcornpc.co.kr/shop/system_detail.html?pd_no={code}",
            "spec": {"cpu": cpu, "gpu": gpu, "ram_gb": ram, "ssd_gb": ssd}}


PRODUCTS = {p["code"]: p for p in (
    _p(102112, "골드 NO.04.102112  [화이트상품 1위][14400F/16G/1TB/RTX5060]", 1_915_500, "i5-14400F", "RTX 5060", 16, 1000),
    _p(98149, "골드 NO.04.98149 [인기상품1위]인텔  [12400F/16GB/500GB/RTX5060]", 1_625_800, "i5-12400F", "RTX 5060", 16, 500),
    _p(90926, "골드 NO.04.90926MW [14400F/16G/250GB/RTX5060]", 1_915_700, "i5-14400F", "RTX 5060", 16, 256),
    _p(109637, "골드 NO.04.109637W [B760/DDR5] RGB 화이트 [14400F/16G/500GB/RTX5060]", 2_115_700, "i5-14400F", "RTX 5060", 16, 500),
    _p(129823, "견적왕 추천PC NO.04.129823 [14400F/32G/1TB/RTX5060Ti]", 1_889_500, "i5-14400F", "RTX 5060 Ti 8GB", 32, 1000),
    _p(97000, "다이아 NO.05.97000 [B760/DDR5][인기상품3위]  [14세대 판매 1위] [고사양게이밍 3위][14400F/32G/1TB/RTX5060Ti]",
       2_313_600, "i5-14400F", "RTX 5060 Ti 8GB", 32, 1000),
)}


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Conn:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        return self

    def all(self):
        return self.rows


class _Engine:
    def __init__(self, rows=()):
        self.rows = rows

    def connect(self):
        return _Conn(self.rows)


def _stack(products=PRODUCTS, off_rows=()):
    from api import sold_reco as SOLD
    st = contextlib.ExitStack()
    st.enter_context(patch.object(SOLD, "load", lambda: ([], products)))
    st.enter_context(patch.object(SOLD, "card_spec", lambda p: p["spec"]))
    st.enter_context(patch.object(TT, "engine", _Engine(off_rows)))
    return st


def _codes(res, book):
    return [book.items[i["ref"]]["product_code"] for i in res.get("items") or [] if "ref" in i]


class Lookup(unittest.TestCase):
    def _find(self, name, **kw):
        book = TT.FactBook()
        with _stack(**kw):
            res = TT.find_pc_by_name({"name": name}, book)
        return res, book

    def test_reported_sentence_finds_the_same_gold_pc(self):
        res, book = self._find("골드 [14400F/16G/1TB/RTX5060] 이제품을 팝콘피씨에서 보여줘")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(_codes(res, book), [102112])
        item = res["items"][0]
        self.assertEqual((item["match"], item["name"], item["price"]), ("exact", "골드 [14400F/16G/1TB/RTX5060]", 1_915_500))
        self.assertEqual(item["mall_url"], "https://www.popcornpc.co.kr/shop/system_detail.html?pd_no=102112")
        self.assertEqual((item["spec"]["cpu"], item["spec"]["ssd_gb"]), ("i5-14400F", 1000))
        self.assertIn(1_915_500, book.prices)                    # 그 가격을 말해도 된다

    def test_full_mall_name_and_spacing_and_units_reach_the_same_pc(self):
        for q in ("골드 NO.04.102112 [화이트상품 1위][14400F/16G/1TB/RTX5060]",
                  "골드[14400F/16GB/1TB/RTX 5060]",
                  "골드 [14400f / 16g / 1tb / rtx5060] 있어요?"):
            res, book = self._find(q)
            self.assertEqual((res["status"], _codes(res, book)), ("ok", [102112]), q)

    def test_mall_number_is_matched_through_the_mall_name_not_as_db_id(self):
        res, book = self._find("NO.04.102112 보여줘")
        self.assertEqual((_codes(res, book), res["items"][0]["match"]), ([102112], "mall_no"))
        # 몰 이름에 그 번호가 없으면 같은 숫자의 상품코드라도 찾지 않는다
        other = {102112: dict(PRODUCTS[102112], name="골드 [14400F/16G/1TB/RTX5060]", url=None)}
        res, _ = self._find("NO.04.102112", products=other)
        self.assertEqual(res["status"], "empty")

    def test_other_spec_is_never_the_named_pc(self):
        res, book = self._find("골드 [14400F/16G/1TB/RTX5060]")
        self.assertNotIn(98149, _codes(res, book))              # 12400F/500GB 는 원래 요청 상품이 아니다
        self.assertNotIn(90926, _codes(res, book))              # 256GB 도 아니다

    def test_spec_only_match_is_labelled_and_separate(self):
        res, book = self._find("실버 [14400F/16G/1TB/RTX5060]")  # 이름(실버)이 다르면 같은 상품이라 하지 않는다
        self.assertEqual(res["status"], "ok")
        self.assertEqual([i["match"] for i in res["items"]], ["spec"])
        self.assertIn("단정하지", res["note"])
        # 이름 없는 대괄호뿐인 판매 이름은 같은 이름으로 치지 않는다
        res, book = self._find("다이아 [14400F/32G/1TB/RTX5060Ti]")
        self.assertTrue(all(i["match"] == "spec" for i in res["items"]))

    def test_not_on_sale_and_missing_are_told_apart(self):
        sold_out = {k: v for k, v in PRODUCTS.items() if k != 102112}
        rows = [_Row(product_code=102112, crawl_name=PRODUCTS[102112]["name"], mall_url=PRODUCTS[102112]["url"],
                     excluded=False, status="품절")]
        res, _ = self._find("골드 [14400F/16G/1TB/RTX5060]", products=sold_out, off_rows=rows)
        self.assertEqual(res["status"], "not_on_sale")
        self.assertEqual((res["items"][0]["sale_status"], res["items"][0]["name"]), ("품절", "골드 [14400F/16G/1TB/RTX5060]"))
        self.assertNotIn("ref", res["items"][0])               # 판매하지 않는 PC는 카드로 보여 줄 수 없다
        res, _ = self._find("플래티넘 [9800X3D/64G/4TB/RTX5090]")
        self.assertEqual(res["status"], "empty")

    def test_status_must_be_on_sale(self):
        stopped = {102112: dict(PRODUCTS[102112], status="판매중지")}
        res, _ = self._find("골드 [14400F/16G/1TB/RTX5060]", products=stopped)
        self.assertEqual(res["status"], "empty")

    def test_bad_args(self):
        self.assertEqual(TT.find_pc_by_name({"name": ""}, TT.FactBook())["status"], "invalid")
        self.assertEqual(TT.find_pc_by_name({"name": 3}, TT.FactBook())["status"], "invalid")

    def test_tool_is_offered_and_runnable(self):
        names = [d["name"] for d in TT.definitions(["게임"], ["1080p"])]
        self.assertIn("find_pc_by_name", names)
        self.assertIs(TT.EXECUTORS["find_pc_by_name"], TT.find_pc_by_name)


VOCAB = Vocab(usages=[("게임", []), ("사무·인강", [])])


def _turn(text="", calls=()):
    return llm.ToolTurn(provider="codex", model="m", text=text, tool_calls=list(calls), raw={},
                        tokens_in=1, tokens_out=1, cached_in=0, cost_usd=0.0, elapsed_sec=0.1,
                        log_id=1, cost_logged=True, stop="completed")


class Turn(unittest.TestCase):
    def _run(self, script, text, prev_state=None):
        sent = []

        def fake_call(msgs, tools, **kw):
            sent.append(kw["system"])
            return script.pop(0)
        with _stack(), patch.object(AG, "engine", _Engine()), patch.object(AG, "load_vocab", lambda c: VOCAB), \
                patch.object(AG.llm, "call_tools", fake_call):
            out = AG.run_turn(text, [], prev_state=prev_state)
        return out, sent

    def test_named_pc_is_given_to_ai_before_tools(self):
        out, sent = self._run([_turn(calls=[{"id": "s", "name": "show_pcs", "args": {"refs": ["P1"]}}]),
                               _turn("말씀하신 골드 [14400F/16G/1TB/RTX5060]은 지금 1,915,500원에 판매 중이에요.")],
                              "골드 [14400F/16G/1TB/RTX5060] 이제품을 팝콘피씨에서 보여줘")
        ctx = json.loads(sent[0].split("\n")[-1])
        self.assertEqual(ctx["named_pcs"]["items"][0]["ref"], "P1")
        self.assertEqual([c["product_code"] for c in out["cards"]], [102112])
        self.assertIn("1,915,500원", out["reply"])

    def test_named_pc_card_is_kept_even_if_ai_shows_only_alternatives(self):
        # AI 가 조건으로 다시 찾아 다른 PC만 골라도, 손님이 이름으로 말한 판매 PC가 맨 앞 카드다.
        from api import grid_public as GP
        other = {"product_code": 98149, "name": "골드 인텔 [12400F/16GB/500GB/RTX5060]", "price": 1_625_800,
                 "spec": {}, "level": None}
        reco = {"card_sets": [{"usage": "게임", "items": [other]}], "anchor_code": 98149}
        script = [_turn(calls=[{"id": "f", "name": "find_pcs", "args": {"usages": ["게임"]}}]),
                  _turn(calls=[{"id": "s", "name": "show_pcs", "args": {"refs": ["P2"]}}]),
                  _turn("비슷한 PC를 보여 드려요.")]
        with patch.object(GP, "recommend", lambda b: reco):
            out, _ = self._run(script, "골드 [14400F/16G/1TB/RTX5060] 보여줘")
        self.assertEqual([c["product_code"] for c in out["cards"]], [102112, 98149])

    def test_plain_turn_does_not_read_catalog(self):
        from api import sold_reco as SOLD
        with patch.object(SOLD, "load", side_effect=AssertionError("read")):
            self.assertEqual(TT.named_pcs("게임용 PC 150만원 추천해줘", TT.FactBook()), [])

    def test_as_parse_keeps_named_card_without_find_pcs(self):
        fake = {"ok": True, "status": "ok", "reply": "보여 드려요.", "notes": [], "state": None, "nav": None,
                "units": None, "cards": [{"product_code": 102112, "name": "골드 [14400F/16G/1TB/RTX5060]", "price": 1_915_500}]}
        with patch.object(AG, "run_turn", lambda *a, **k: fake):
            r = AG.as_parse("골드 [14400F/16G/1TB/RTX5060] 보여줘", [], {"usages": ["게임"]}, None)
        self.assertFalse(r["explain_only"])
        self.assertEqual(r["state"], {"usages": ["게임"]})
        self.assertEqual([c["product_code"] for c in r["agent_cards"]], [102112])

    def test_prompt_rules(self):
        self.assertIn("find_pc_by_name 으로 그 PC를 찾는다", AG.SYSTEM)
        self.assertIn("다른 사양(CPU·저장공간)의 PC를 손님이 말한 PC처럼 말하지 않는다", AG.SYSTEM)


if __name__ == "__main__":
    unittest.main()
