import unittest
from copy import deepcopy
from api.pc_catalog_review_snapshot import snapshots, review_snapshot


class ReviewSnapshotTests(unittest.TestCase):
    def parts(self, identity):
        return [dict(slot=s,source_code=c,quantity=q,pseudo=False)
                for s,c,q in snapshots()[identity]['parts']]

    def test_exact_bom_is_only_a_document_match_not_approval(self):
        result=review_snapshot('N02',self.parts('N02'))
        self.assertTrue(result['bom_matches'])
        self.assertFalse(result['approval_basis'])
        self.assertTrue(any(c['status']=='unknown' for c in result['checks']))

    def test_quantity_or_identity_changes_do_not_reuse_current_verdict(self):
        original=self.parts('N02')
        for field,value in [('quantity',2),('source_code','other')]:
            parts=deepcopy(original);parts[0][field]=value
            self.assertFalse(review_snapshot('N02',parts)['bom_matches'])

    def test_existing_research_is_explicitly_historical(self):
        result=review_snapshot('P100866',self.parts('P100866'))
        self.assertTrue(result['historical'])
        self.assertEqual(next(c['status'] for c in result['checks'] if c['code']=='cooler_tdp'),'reference')

    def test_missing_record_has_no_invented_result(self):
        self.assertIsNone(review_snapshot('not-known',[]))

    def test_whitelisted_snapshot_has_no_supplier_or_pricing_payload(self):
        for r in snapshots().values():
            self.assertEqual(set(r),{'observed_at','origin','historical','parts','checks'})
            for c in r['checks']:
                self.assertLessEqual(set(c),{'code','label','status','detail','sources'})
