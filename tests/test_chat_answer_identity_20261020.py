"""/mvp4 AI 대화 답변 -- 상품 동일성·형광펜 카드·복사·접힘 (2026-10-20 대표 승인·P1 신고).

P1 「답변과 추천 상품이 달라」: AI 가 보여 준 PC(agent_cards)가 조건 추천 안에 다 있으면 조건 추천 순서를 그대로 썼고
화면이 앞 3대만 보여, 본문 2·3번(129823·113836)과 오른쪽 2·3번(129832·127317)이 달랐다.
"""
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = ROOT / "mockups/mvp4/assets/js"


def src(name):
    return (JS / name).read_text(encoding="utf-8")


def run_answer(expr: str):
    code = ("global.window=global;window.PAI={catalogProducts:[{id:'98149'},{id:'129823'},{id:'113836'}],"
            "getCatalogProduct:function(id){return this.catalogProducts.find(function(p){return p.id===String(id)})||null}};"
            + src("chat-answer.js") + ";var A=window.PAI.chatAnswer;console.log(JSON.stringify(" + expr + "))")
    return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)


REPLY = ("기준 문장입니다.\n\n- 골드 인텔 [12400F/16GB/500GB/RTX5060] — 1,625,800원\n설명 하나.\n"
         "- [14400F/32G/1TB/RTX5060Ti] — 1,889,500원\n설명 둘.\n"
         "- 오피스 초슬림/미니타워[12400/16G/500G/UHD 730] — 894,500원\n설명 셋.\n\n예산을 알려 주시면 좁혀 드릴게요?")
CARDS = [{"product_code": 98149, "name": "골드 인텔 [12400F/16GB/500GB/RTX5060]"},
         {"product_code": 129823, "name": "[14400F/32G/1TB/RTX5060Ti]"},
         {"product_code": 113836, "name": "오피스 초슬림/미니타워[12400/16G/500G/UHD 730]"}]


class Identity(unittest.TestCase):
    def test_agent_cards_are_the_right_list_without_regrid(self):
        s = src("live-talk.js")
        self.assertIn("agentPicks(res.agent_cards)", s)
        self.assertNotIn("withAgentCards", s)            # 조건 추천 순서로 AI 묶음을 덮던 합치기
        self.assertIn("reply_format: 'marked'", s)
        self.assertNotIn(".slice(0, 300)", s)            # 앞 300자 이력에 상품 참조를 맡기지 않는다
        self.assertIn("commit: function", s)

    def test_screen_follows_answer_set_order_and_sends_sets(self):
        s = src("design-conversation.js")
        self.assertIn("built.set.map(", s)
        self.assertIn("out.answer_sets = sets", s)
        self.assertIn("res.commit()", s)

    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_body_order_is_the_set_and_unmatched_names_are_not_linked(self):
        a = run_answer(f"A.build({json.dumps(REPLY)},{json.dumps(CARDS)},[{{id:'98149'}},{{id:'129832'}},{{id:'129823'}}])")
        self.assertEqual([x["product_code"] for x in a["set"]], [98149, 129823, 113836, 129832])
        self.assertEqual([x["in_body"] for x in a["set"]], [True, True, True, False])
        # 닮은 사양의 다른 상품(129832)은 이름이 달라 본문 카드로 붙지 않는다
        other = run_answer(f"A.build({json.dumps(REPLY)},[{{product_code:129832,name:'[9600X/16G/1TB/RTX5070]'}}],[]).blocks.filter(function(b){{return b.kind==='card'}}).length")
        self.assertEqual(other, 0)

    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_marks_escape_and_strip(self):
        self.assertEqual(run_answer("A.strip('==핵심== 그대로 ==')"), "핵심 그대로 ")
        html = run_answer("A.render({answer:A.build('<img src=x onerror=1> ==강조==',[],[])},{pcHref:String,inCompare:function(){return false}})")
        self.assertNotIn("<img", html)
        self.assertIn("<mark>강조</mark>", html)
        self.assertEqual(run_answer("A.sentences('3.5GHz 입니다. 다음 문장? 끝')"), ["3.5GHz 입니다.", "다음 문장?", "끝"])

    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_memory_conflict_is_flagged_not_corrected(self):
        r = "- [팝콘피씨] [9950X3D/128G/1TB/RTX5090] — 18,432,100원\n라이젠9, 메모리 256GB 구성입니다."
        a = run_answer(f"A.build({json.dumps(r)},[{{product_code:98149,name:'[팝콘피씨] [9950X3D/128G/1TB/RTX5090]'}}],[]).blocks[0]")
        self.assertIn("128G", a["check"]); self.assertIn("256GB", a["check"])
        self.assertIn("메모리 256GB", a["body"][0])


class PartsFolded(unittest.TestCase):
    def test_every_part_row_starts_closed(self):
        self.assertIn("'<details class=\"cf-part\"><summary>", src("configuration-concept.js"))
        self.assertNotIn("(i === 0 ? ' open' : '')", src("configuration-concept.js"))
        self.assertIn("'<details class=\"dp-spec-group\"><summary>", src("design-products.js"))


class Assets(unittest.TestCase):
    def test_pages_load_new_assets(self):
        for page in ("index.html", "review-flows.html"):
            t = (ROOT / "mockups/mvp4" / page).read_text(encoding="utf-8")
            for a in ("chat-answer.css?v=20261020-ans1", "chat-answer.js?v=20261021-wish1", "design-conversation.js?v=20261022-ask1",
                      "live-talk.js?v=20261021-wish1", "configuration-concept.js?v=20261021-cb2"):
                self.assertIn(a, t, page)
            self.assertLess(t.index("chat-answer.js"), t.index("design-conversation.js"))


if __name__ == "__main__":
    unittest.main()
