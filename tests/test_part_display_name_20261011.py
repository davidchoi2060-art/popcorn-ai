"""상세 구성 부품 이름의 판매조건 꼬리 — 2026-10-11 품질관리 R13(고객1 10번 · 고객3 F9) 회귀 고정.

이름은 품질관리 결과.md 에 적힌 실제 표기를 쓴다. 판매조건은 떼고 유통 형태·수입사는 남긴다.
"""
import unittest

from api.product_name import part_display_name
from api import customer_sold_offer_read as R


class PartDisplayName(unittest.TestCase):
    def test_sale_condition_bracket_removed(self):
        self.assertEqual(part_display_name('MSI 지포스 RTX 5060 벤투스 2X OC D7 8GB [회원가입 -2.5% 현금할인]'),
                         'MSI 지포스 RTX 5060 벤투스 2X OC D7 8GB')
        self.assertEqual(part_display_name('ASUS PRIME B760M-A [회원가입 계좌이체 현금할인 -2.5%] (벌크)'),
                         'ASUS PRIME B760M-A (벌크)')

    def test_single_unsold_removed(self):
        self.assertEqual(part_display_name('삼성 DDR5-5600 16GB - 단품판매불가'), '삼성 DDR5-5600 16GB')
        self.assertEqual(part_display_name('마이크론 P3 1TB (단품판매불가)'), '마이크론 P3 1TB')
        self.assertEqual(part_display_name('마이크론 P3 1TB [단품 판매 불가]'), '마이크론 P3 1TB')

    def test_distribution_info_kept(self):
        for name in ('인텔 코어 i5-14400F [병행] (벌크)', 'ASRock B650M PRO RS [피씨디렉트/제이씨현]',
                     'ASUS ROG STRIX [WHITE EDITION]', 'AMD 라이젠5 7500F (정품)'):
            self.assertEqual(part_display_name(name), name)
        self.assertEqual(part_display_name('128GB [32G x 4][회원가입 계좌이체 -2.5%]'), '128GB [32G x 4]')

    def test_name_that_would_vanish_is_kept(self):
        self.assertEqual(part_display_name('[회원가입 -2.5% 현금할인]'), '[회원가입 -2.5% 현금할인]')
        self.assertIsNone(part_display_name(None))

    def test_public_parts_use_display_name_without_touching_source(self):
        content = {'name': '삼성 DDR5-5600 16GB [회원가입 -2.5% 현금할인] - 단품판매불가',
                   'role': '메모리', 'facts': [{'label': '용량', 'value': '16GB'}]}
        rows = {'E1': {'content': content}}
        out = R._public_parts([{'ordinal': 1, 'pseudo': False, 'explanation_code': 'E1'}], rows)
        self.assertEqual(out[0]['name'], '삼성 DDR5-5600 16GB')
        self.assertEqual(content['name'], '삼성 DDR5-5600 16GB [회원가입 -2.5% 현금할인] - 단품판매불가')


if __name__ == '__main__':
    unittest.main()
