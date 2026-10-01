import unittest
from pydantic import ValidationError
from api.admin_pc_batch import BatchSave, grouped


def item(identity='N07'):
    return dict(configuration_id=identity, revision=1, source_basis='a'*64,
                changes=[dict(field='intro', value='실제 구성 설명', reason='쉽게 설명')])


class BatchTests(unittest.TestCase):
    def test_write_scope_and_duplicates(self):
        for field in ('price', 'status', 'recommendation_policy', '_review'):
            bad=item(); bad['changes'][0]['field']=field
            with self.assertRaises(ValidationError):
                BatchSave(items=[bad])
        with self.assertRaises(ValidationError):
            BatchSave(items=[item(),item()])
        bad=item(); bad['changes']*=2
        with self.assertRaises(ValidationError):
            BatchSave(items=[bad])

    def test_bounds_and_basis(self):
        for items in ([], [item(str(i)) for i in range(11)]):
            with self.assertRaises(ValidationError):
                BatchSave(items=items)
        bad=item(); bad['source_basis']='old'
        with self.assertRaises(ValidationError):
            BatchSave(items=[bad])

    def test_shared_parts_count_distinct_products_and_exclude_retired(self):
        def row(identity,status='draft'):
            return dict(configuration_id=identity,status=status,
                        search_parts=[dict(code='1',name='CPU')]*2,review_reasons=['자료 보완'])
        result=grouped([row('a'),row('b'),row('c','retired')])
        self.assertEqual(result['catalog_total'],3)
        self.assertEqual(len(result['items']),2)
        self.assertEqual(result['groups'][0]['ids'],['a','b'])
        self.assertEqual(result['groups'][0]['count'],2)


if __name__=='__main__':
    unittest.main()
