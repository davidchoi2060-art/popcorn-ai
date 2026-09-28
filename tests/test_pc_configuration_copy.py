import copy,hashlib,json,unittest
from api.pc_configuration_copy import explanation_digest,part_needs_review
from api.part_explanations import fingerprint
from tools.import_pc_configuration_copy import prepare,COPY_KEYS

class ConfigurationCopyTests(unittest.TestCase):
    def setUp(self):
        self.e=dict(content={'role':'role','review_issues':[]},source_snapshot={'name':'Part','spec':'DDR5'},source_fingerprint=fingerprint('Part','DDR5'),product_code=1,product_name='Part',spec_source_text='DDR5')
        self.r={k:'copy' for k in COPY_KEYS}
        self.r.update(id='N01',bom_fingerprint=hashlib.sha256(json.dumps((('RAM','1',1),)).encode()).hexdigest(),observed_date='2026-09-28',parts=[dict(code='1',slot='RAM',quantity=1,pseudo=False,role='role')],offers=[dict(id='N01',price=130000,base_price=100000,assembly_fee_added=30000)])
    def test_missing_explanation_stops_import(self):
        with self.assertRaises(AssertionError):prepare([self.r],{})
    def test_bom_quantity_change_requires_new_fingerprint(self):
        self.r['parts'][0]['quantity']=2
        with self.assertRaises(AssertionError):prepare([self.r],{1:self.e})
    def test_assembly_fee_not_added_twice(self):
        self.r['offers'][0]['price']=160000
        with self.assertRaises(AssertionError):prepare([self.r],{1:self.e})
    def test_duplicate_offer_cannot_attach_to_two_boms(self):
        r=copy.deepcopy(self.r);r['id']='N02';r['parts'][0]['quantity']=2
        r['bom_fingerprint']=hashlib.sha256(json.dumps((('RAM','1',2),)).encode()).hexdigest()
        with self.assertRaises(AssertionError):prepare([self.r,r],{1:self.e})
    def test_price_only_changes_do_not_invalidate_copy(self):
        a=prepare([self.r],{1:self.e})[0]
        self.r['offers'][0]['price']+=100;self.r['offers'][0]['base_price']+=100
        b=prepare([self.r],{1:self.e})[0]
        self.assertNotEqual(a['hash'],b['hash']);self.assertEqual(a['copy_hash'],b['copy_hash'])
    def test_changed_explanation_invalidates_affected_bom(self):
        p=prepare([self.r],{1:self.e})[0]['parts'][0]
        self.assertFalse(part_needs_review(p,self.e))
        self.e['content']['role']='new role'
        self.assertTrue(part_needs_review(p,self.e))
    def test_changed_raw_specs_invalidates_even_with_same_copy(self):
        p=prepare([self.r],{1:self.e})[0]['parts'][0]
        self.e['spec_source_text']='DDR4'
        self.assertTrue(part_needs_review(p,self.e))
    def test_assembly_only_without_fictitious_retail_link(self):
        self.e['product_code']=None;self.e['content']['availability_scope']='assembly_only'
        p=prepare([self.r],{1:self.e})[0]['parts'][0]
        self.assertFalse(part_needs_review(p,self.e))
        self.e['content']['review_issues']=['physical revision unknown']
        self.assertTrue(part_needs_review(p,self.e))
    def test_pseudo_is_not_a_retail_part(self):
        self.assertFalse(part_needs_review({'pseudo':True},None))

if __name__=='__main__':unittest.main()
