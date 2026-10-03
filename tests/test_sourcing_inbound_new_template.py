import unittest
from pathlib import Path
from types import SimpleNamespace
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]

def render(page, new):
    return Environment(loader=FileSystemLoader(ROOT/'templates'),autoescape=True).get_template('admin/'+page+'.html.j2').render(
        new_admin=new, request=SimpleNamespace(url=SimpleNamespace(path='/admin2/'+page.replace('_','-'))),nav=[],nav_counts={},workspace_nav=[],screen_id='test',domain='sourcing',crumb_group='매입 · 소싱',crumb_now='시안')

class SourcingInboundNewTemplateTest(unittest.TestCase):
    def test_new_modes_only_load_owned_assets_and_no_legacy_handlers(self):
        for page,stem,marker,old in [('sourcing','sourcing-new','sourcingNew','function doConfirm('),('stock_inbound','stock-inbound-new','stockInboundNew','function confirmInbound(')]:
            with self.subTest(page=page):
                html=render(page,True)
                self.assertIn('id="'+marker+'"',html)
                self.assertIn('/shared/admin2/'+stem+'.css',html)
                self.assertIn('/shared/admin2/'+stem+'.js',html)
                self.assertNotIn(old,html)
                self.assertIn('/shared/admin2/admin2.css',html)

    def test_legacy_original_handlers_preserved_without_new_assets(self):
        for page,stem,old in [('sourcing','sourcing-new','function doConfirm('),('stock_inbound','stock-inbound-new','function confirmInbound(')]:
            with self.subTest(page=page):
                html=render(page,False)
                self.assertIn(old,html)
                self.assertNotIn('/shared/admin2/'+stem+'.js',html)
                self.assertNotIn('/shared/admin2/'+stem+'.css',html)

    def test_partial_semantics_and_scope_do_not_create_backend_or_source_routes(self):
        html=render('stock_inbound',True)
        self.assertIn('id="stockNewHistory"',html)
        self.assertIn('증가분',html)
        self.assertNotIn('/api/admin/stock-inbound/exact',html)
        self.assertIn('id="srcNewSearchForm"',render('sourcing',True))

if __name__=='__main__': unittest.main()
