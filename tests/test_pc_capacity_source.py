import unittest
from tools.build_part_explanations import extract
from api.pc_configuration_parts_edit import capacity

class CapacitySourceTests(unittest.TestCase):
    def test_source_styles_are_capacity_not_speed(self):
        for slot,label,spec,expected in [
            ('SSD','용량','SSD / 용량 : 512(GB) / 읽기속도 : 1,700(MB/s) /',512),
            ('SSD','용량','내장형SSD / 500GB / NVMe 2.0 /',500),
            ('SSD','용량','SSD / 용량 : 2(TB) /',2000),
            ('RAM','상품 용량','DDR4 / DIMM / 용량 : 16(GB) / 패키지 구성 : 1(EA) /',16),
            ('RAM','상품 용량','DDR5 / 32(GB) / 패키지 구성 : 2(EA) /',32),
        ]:
            facts={f['label']:f['value'] for f in extract(slot,spec)}
            self.assertEqual(capacity(facts[label]),expected)
    def test_no_capacity_from_speed_or_cache(self):
        facts=extract('SSD','읽기속도 : 500GB/s / DRAM : 2GB /')
        self.assertFalse(any(f['label']=='용량' for f in facts))

if __name__=='__main__': unittest.main()
