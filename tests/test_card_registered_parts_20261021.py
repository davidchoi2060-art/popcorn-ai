"""/mvp4 목록 카드 부품 구성 — 공개 승인 구성이 없는 판매 PC 도 상세와 같은 몰 등록 구성으로 채운다 (2026-10-21 대표).

목록 카드가 공개 승인 구성(configuration_public) 상품만 구성을 읽어서, 승인 구성이 없는 상품(예: 123380 골드 RTX 3050)은
상세에서는 부품 구성이 보이는데 목록에서는 「상품 사양 요약 · 정확한 부품 구성은 상세에서 확인」만 보였다.
"""
import pathlib
import unittest

JS = pathlib.Path(__file__).resolve().parents[1] / "mockups/mvp4/assets/js"


class CardReadsRegisteredParts(unittest.TestCase):
    def test_scan_does_not_skip_non_public(self):
        s = (JS / "live-cards.js").read_text(encoding="utf-8")
        scan = s[s.index("  function scan()"):s.index("  new MutationObserver")]
        self.assertNotIn("configurationPublic", scan)
        self.assertIn("p.liveDetail !== 'pending'", scan)

    def test_detail_path_falls_back_to_registered(self):
        s = (JS / "live-catalog.js").read_text(encoding="utf-8")
        read = s[s.index("  function readDetail(p)"):]
        self.assertIn("REGISTERED", read)


class CardSpecFollowsTitle(unittest.TestCase):
    """상품명 [CPU/메모리/SSD/그래픽] 이 기준이다(2026-10-21 대표). 몰 구성 「16GB [8G x 2] * 2개」(32GB)여도 제목 16G 를 보인다."""

    def run_cell(self, official, specs, summary=None):
        import json, shutil, subprocess
        if not shutil.which("node"):
            self.skipTest("node 없음")
        s = (JS / "live-cards.js").read_text(encoding="utf-8")
        fn = s[s.index("  var TITLE_RE"):s.index("  function cardB(product)")]
        data = {"specs": [{"label": "메모리", "slot": "RAM", "lines": ["DDR5", "16GB × 2"], "pending": False},
                          {"label": "SSD", "slot": "SSD", "lines": ["1TB"], "pending": False},
                          {"label": "CPU", "slot": "CPU", "lines": ["13500"], "pending": False},
                          {"label": "그래픽", "slot": "GPU", "lines": ["RTX", "3050"], "pending": False}]}
        product = {"officialName": official, "specs": specs, "summarySpecs": summary or []}
        code = fn + ";console.log(JSON.stringify(withTitle(" + json.dumps(product) + "," + json.dumps(data) + ").specs.map(function(c){return c.lines.join(' ')})))"
        return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)

    def test_title_wins_on_ram_mismatch(self):
        cells = self.run_cell("엠에스파워 골드 NO.04 .123380 RTX 3050 [13500/16G/1TB/RTX3050]",
                              [{"slot": "RAM", "value": "DDR5-5600 16GB [8G x 2] * 2개", "quantity": 1}])
        self.assertEqual(cells, ["16GB", "1TB", "13500", "RTX 3050"])

    def test_matching_config_kept(self):
        cells = self.run_cell("[13500/32G/1TB/RTX3050]", [{"slot": "RAM", "value": "DDR5 16GB", "quantity": 2}])
        self.assertEqual(cells[0], "DDR5 16GB × 2")


if __name__ == "__main__":
    unittest.main()
