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


if __name__ == "__main__":
    unittest.main()
