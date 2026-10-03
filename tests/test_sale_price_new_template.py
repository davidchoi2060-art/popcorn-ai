import unittest
from pathlib import Path
from types import SimpleNamespace
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def render(new):
    env = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=True)
    return env.get_template('admin/sale_price.html.j2').render(
        new_admin=new, request=SimpleNamespace(url=SimpleNamespace(path='/admin2/sale-price')),
        nav=[], nav_counts={}, workspace_nav=[], screen_id='ADM-PRC-060', domain='sale-price',
        crumb_group='판매가', crumb_now='판매가 관리')


class SalePriceNewTemplateTest(unittest.TestCase):
    def test_new_mode_consumes_only_dedicated_workspace_assets(self):
        html = render(True)
        assert 'id="saleNew"' in html
        assert '/shared/admin2/sale-price-new.js' in html
        assert '/shared/admin2/sale-price-new.css' in html
        assert 'id="spDrawer"' not in html
        assert 'function doMatch()' not in html


    def test_legacy_keeps_original_drawer_and_write_handler(self):
        html = render(False)
        assert 'id="spDrawer"' in html
        assert 'function doMatch()' in html
        assert 'function lock_current' not in html
        assert 'id="saleNew"' not in html
        assert '/shared/admin2/sale-price-new.js' not in html
        assert '/shared/admin2/sale-price-new.css' not in html
