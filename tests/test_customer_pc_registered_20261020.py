"""부품표가 승인되지 않은 판매 PC 의 몰 등록 구성 읽기 (2026-10-20 대표 「부품표도 채워서 넣어」)."""
import unittest

from api import customer_pc_registered as R

SST = ("윈도우(OS)@@<font color=#D8D8D8><strong>[윈도우]</strong>를 선택하세요.</font> ,@@프로세서(CPU)@@<strong>[인텔]</strong> i3 12세대 12100 [Turbo 4.3GHz]™ ,"
       "@@CPU쿨러@@<strong>[OHs]</strong> CV-420 화이트 ,@@메모리(RAM)@@<strong>[삼성전자]</strong> DDR4 8G PC4-25600 *2개 ,"
       "@@대용량(HDD)@@<font color=#D8D8D8><strong>[하드디스크]</strong>를 선택하세요.</font> ,@@케이스@@[DARKFLASH] DMO11 화이트 ,"
       "@@사은품@@<font color=blue>팝콘피씨 게이밍 장패드</font> ,@@조립비+AS@@제작 및 3년 하드웨어 무상서비스 ,@@")


class Rows(unittest.TestCase):
    def test_parts_in_order_without_unselected_or_gifts(self):
        parts, service = R.rows(SST)
        self.assertEqual([p['slot'] for p in parts], ['CPU', 'RAM', 'COOLER', 'CASE'])
        self.assertEqual(parts[0]['name'], '[인텔] i3 12세대 12100 [Turbo 4.3GHz]')
        self.assertEqual(parts[1]['quantity'], 2)
        self.assertEqual(service, '제작 및 3년 하드웨어 무상서비스')

    def test_same_option_text_gives_same_key(self):
        self.assertEqual(R.key('[삼성전자] DDR4 8G  PC4-25600'), R.key('[삼성전자] DDR4 8G PC4-25600'))

    def test_unreadable_is_empty(self):
        self.assertEqual(R.rows(None), ([], None))
        self.assertEqual(R.rows('그냥 문장'), ([], None))


if __name__ == '__main__':
    unittest.main()
