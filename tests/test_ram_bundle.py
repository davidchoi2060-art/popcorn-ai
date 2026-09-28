import unittest
from api.ram_bundle import ram_bundle
from api.catalog_map import extract_specs, extract_from_text


class RamBundleTests(unittest.TestCase):
    def test_order_unit_is_bundle_not_one_dimm(self):
        result=ram_bundle('ESSENCORE DDR5-5600 CL46 32GB [16G x 2]')
        self.assertEqual(result,dict(total_gb=32,module_gb=16,module_count=2))
        self.assertEqual(result['total_gb']*2,64)  # two ordered bundles

    def test_nested_package_and_single_dimm(self):
        self.assertEqual(ram_bundle('FLARE X5 (96GB(48Gx2))')['total_gb'],96)
        self.assertIsNone(ram_bundle('DDR5-5600 (32GB)'))
        self.assertIsNone(ram_bundle('DDR5-5600 32GB [16GB × 4]'))

    def test_both_ingest_routes_use_bundle_total(self):
        name='ESSENCORE KLEVV DDR5-5600 CL46 32GB [16G x 2]'
        a,sa=extract_specs('RAM',{'메모리 용량':'16GB'},['DDR5'],name,'',{})
        b,sb=extract_from_text('RAM','RAM / ESSENCORE KLEVV DDR5-5600 CL46 파인인포 (16GB)',name)
        self.assertEqual(a['capacity_gb'],32)
        self.assertEqual(b['capacity_gb'],32)
        self.assertEqual(sa['capacity_gb'],sb['capacity_gb'])


if __name__=='__main__': unittest.main()
