"""메인 「전체 카테고리」 이름 = PC 쇼핑 「용도·분류」 (2026-10-29 사장님).

「메인의 전체카테고리 부분의 게이밍PC, 사무용PC -> 아래 용도분류 카테고리와 같이 하되.. 게이밍, 사업.업무용.. 이런식으로」
상단 줄·전체 카테고리 창(header-ui.js)과 메인 용도별 카드(design-home.js)가 같은 이름을 쓰고, 누르면 가는 분류 키는
서버 분류(api/customer_pc_catalog.CATEGORIES)와 같다.
"""
import pathlib
import re
import unittest

from api.customer_pc_catalog import CATEGORIES

JS = pathlib.Path(__file__).resolve().parents[1] / 'mockups/mvp4/assets/js'


def rows(name):
    src = (JS / name).read_text(encoding='utf-8')
    block = src[src.index('var categories = ['):]
    block = block[:block.index('];')]
    return [re.findall(r"'([^']*)'|null", row) for row in re.findall(r"\[([^\[\]]+)\]", block)]


class CategoryLabels(unittest.TestCase):
    LABELS = ['게이밍', '사무·업무용', '디자인·영상', '미니 PC', 'AI·고성능']

    def test_header_uses_usage_names(self):
        labels = [r[0] for r in rows('header-ui.js')]
        self.assertEqual(labels, self.LABELS + ['AI 슈퍼컴퓨터', '주변기기'])
        for old in ('게이밍 PC', '사무용 PC', '작업용 PC', '고성능 PC'):
            self.assertNotIn(old, labels)

    def test_home_cards_use_the_same_names(self):
        self.assertEqual([r[0] for r in rows('design-home.js')], self.LABELS + ['주변기기'])

    def test_links_still_go_to_the_catalog_classification(self):
        for name in ('header-ui.js', 'design-home.js'):
            keys = [r[1] for r in rows(name) if r[1]]
            self.assertEqual(keys, list(CATEGORIES), name)


if __name__ == '__main__':
    unittest.main()
