"""상담 답에 인기 자료의 내부 출처 키(steam_api·gametrics)가 고객에게 보이지 않는다 (2026-10-10 전수 점검)."""
import unittest

from api import talk_answer as TA


class PublicSourceLabelTest(unittest.TestCase):
    def test_prompt_line_uses_public_label(self):
        f = TA.GameFacts(name="리그 오브 레전드", pcbang_rank=1, pcbang_share=40.1,
                         snapshot_date="2026-09-17", snapshot_source="gametrics")
        joined = "\n".join(TA._fact_lines(f))
        self.assertIn("게임트릭스 PC방 통계", joined)
        self.assertNotIn("gametrics", joined)

    def test_unknown_or_missing_key_falls_back(self):
        self.assertEqual(TA.public_source_label(None), TA.PUBLIC_SOURCE_FALLBACK)
        self.assertEqual(TA.public_source_label("new_feed_v2"), TA.PUBLIC_SOURCE_FALLBACK)

    def test_scrub_replaces_internal_keys_in_answer(self):
        out = TA.scrub_internal_source_names(
            "17일 기준 1위이며, 출처는 gametrics입니다. 동접은 steam_api 기준, gametrics_secondary 도 참고.")
        for key in TA.PUBLIC_SOURCE_LABELS:
            self.assertNotIn(key, out)
        self.assertIn("게임트릭스 PC방 통계입니다", out)
        self.assertIn("Steam 공개 통계 기준", out)
        self.assertIn("공개된 PC방 통계", out)

    def test_scrub_leaves_other_words(self):
        self.assertEqual(TA.scrub_internal_source_names("Steam 동시접속 1,000명"), "Steam 동시접속 1,000명")


if __name__ == "__main__":
    unittest.main()
