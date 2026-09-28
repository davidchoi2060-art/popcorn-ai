"""Focused tests: stale sources, publication gates and seed evidence."""
import json
import unittest
from pathlib import Path
from api.part_explanations import can_publish, fingerprint, present

ROOT=Path(__file__).resolve().parents[1]

class ExplanationTests(unittest.TestCase):
    def row(self):
        return dict(source_product_code=1,product_code=1,product_name='Model 1',spec_source_text='DDR5',
                    source_fingerprint=fingerprint('Model 1','DDR5'),status='approved',approved_by=1,
                    approved_at='2026-09-28',sale_status='판매중',sale_price=100,updated_at='2026-09-28',
                    content={'name':'Model 1','review_issues':[]})

    def test_all_gates_required(self):
        self.assertTrue(can_publish(self.row()))
        for field,value in [('status','draft'),('approved_by',None),('approved_at',None),
                            ('sale_status','품절'),('product_code',None),('product_name','Other'),
                            ('spec_source_text','DDR4')]:
            with self.subTest(field=field):
                row=self.row();row[field]=value;self.assertFalse(can_publish(row))
        row=self.row();row['content']['review_issues']=['Conflict'];self.assertFalse(can_publish(row))

    def test_public_price_is_live_and_internal_notes_omitted(self):
        row=self.row();row['sale_price']=32100
        result=present(row)
        self.assertEqual(result['price'],32100);self.assertNotIn('review_issues',result)
        self.assertIn('review_issues',row['content'])

    def test_outer_whitespace_is_not_a_spec_change(self):
        row=self.row();row['source_snapshot']={'name':'Model 1','spec':'DDR5 '}
        row['source_fingerprint']=fingerprint('Model 1','DDR5 ')
        self.assertTrue(can_publish(row))
        row['spec_source_text']='DDR4'
        self.assertFalse(can_publish(row))
        row['source_snapshot']['spec']='DDR4'
        self.assertFalse(can_publish(row))

    def test_seed_provenance_and_distinctness(self):
        d=json.loads((ROOT/'db/migrations/data/part_explanations_20260928.json').read_text(encoding='utf-8'))
        self.assertEqual(len(d['items']),len({r['code'] for r in d['items']}))
        for r in d['items']:
            self.assertEqual(r['fingerprint'],fingerprint(r['snapshot']['name'],r['snapshot']['spec']))
            c=r['content'];ids={s['id'] for s in c['sources']}
            self.assertTrue(c['facts']);self.assertTrue(c['review_issues'])
            self.assertTrue(all(f['source_id'] in ids for f in c['facts']))
        pm=next(r['content'] for r in d['items'] if r['code']==110899)
        self.assertEqual(next(f['value'] for f in pm['facts'] if f['label']=='최대 읽기'),'6,400 MB/s')
        ram=next(r['content'] for r in d['items'] if r['code']==127555)
        self.assertFalse(any(f['label']=='상품 용량' for f in ram['facts']))

if __name__=='__main__':unittest.main()
