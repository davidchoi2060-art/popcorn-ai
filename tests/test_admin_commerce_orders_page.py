"""Actual page/nav/render/discovery AST with bounded mocks; no main/auth/DB startup."""
import ast
import builtins
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'api/admin_ui_commerce_orders.py'
NAV = ROOT / 'api/admin_nav.py'
NAV_BASELINE_AST_SHA = '8ae6f3af9d0aacaca4f5f735026d4b9ea64bb4d6b1cd6e0d44032f2831a4daa7'
FLOW_SCRIPTS = (
    '<script src="/shared/admin-commerce-fulfillment-transport.js?v=20261006-1"></script>'
    '<script src="/shared/admin-commerce-fulfillment.js?v=20261006-1"></script>'
    '<script src="/shared/admin-commerce-physical-returns-transport.js?v=20261007-return-read-1"></script>'
    '<script src="/shared/admin-commerce-physical-returns.js?v=20261007-return-read-1"></script>'
)
FLOW_MOUNT = ("<script>document.getElementById('commerce-orders').commerceOrderFlows="
              "PopcornPhysicalReturns.mount(document.getElementById('commerce-orders'));</script>")
FLOW_BLOCK = FLOW_SCRIPTS + FLOW_MOUNT
APPROVED_COMMERCE_ASSETS = (
    ('link', '/shared/admin-commerce-orders.css?v=20261006-flows-1'),
    ('link', '/shared/admin-commerce-support.css?v=20261005-1'),
    ('script', '/shared/admin-commerce-orders.js?v=20261006-flows-1'),
    ('script', '/shared/admin-commerce-fulfillment-transport.js?v=20261006-1'),
    ('script', '/shared/admin-commerce-fulfillment.js?v=20261006-1'),
    ('script', '/shared/admin-commerce-physical-returns-transport.js?v=20261007-return-read-1'),
    ('script', '/shared/admin-commerce-physical-returns.js?v=20261007-return-read-1'),
    ('script', '/shared/admin-commerce-orders-transport.js?v=20261005-2'),
    ('script', '/shared/admin-commerce-support.js?v=20261005-1'),
)


def source_tree(path): return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def exec_selected(tree, path, env):
    real_import = builtins.__import__
    def bounded_import(name, *args, **kwargs):
        if name == 'main' or name == 'api' or name.startswith('api.') or name == 'sqlalchemy':
            raise AssertionError('production/business import forbidden: ' + name)
        return real_import(name, *args, **kwargs)
    with patch('builtins.__import__', side_effect=bounded_import):
        exec(compile(tree, str(path), 'exec'), env)
    return env


def navigation():
    env = exec_selected(source_tree(NAV), NAV, {})
    # Manual catalog loading belongs to another module; keep this boundary isolated.
    env['_manual_nav_group'] = lambda path: None
    return env


def renderer(nav):
    path = ROOT / 'api/admin_ui_common.py'
    tree = source_tree(path)
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'render']
    env = dict(Request=Request, HTMLResponse=HTMLResponse,
               templates=Jinja2Templates(directory=str(ROOT / 'templates')),
               nav_for=nav['nav_for'], nav_counts=nav['counts'], new_admin_nav=nav['new_admin_nav'])
    return exec_selected(tree, path, env)['render']


def page(render):
    tree = source_tree(PAGE)
    tree.body = [n for n in tree.body if not isinstance(n, ast.ImportFrom)]
    return exec_selected(tree, PAGE, dict(APIRouter=APIRouter, Request=Request,
                         HTMLResponse=HTMLResponse, render=render))


def request(path='/admin2/commerce-orders', query='', cookie=''):
    return Request(dict(type='http', method='GET', path=path, raw_path=path.encode(),
                        query_string=query.encode(), headers=[(b'cookie', cookie.encode())],
                        scheme='https', server=('fixture.invalid', 443), root_path=''))


def discovery(page_env, failure=False):
    path = ROOT / 'api/main.py'
    tree = source_tree(path)
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_discover_routers']
    imports, locations = [], []
    def inventory(paths):
        locations.append(paths)
        return [SimpleNamespace(name=name) for name in
                ('safe_helper', 'main', 'admin_ui_commerce_orders', '_private')]
    def load(name):
        imports.append(name)
        if failure: raise RuntimeError('bounded discovery failure')
        return SimpleNamespace(router=page_env['router']) if name == 'api.admin_ui_commerce_orders' else SimpleNamespace()
    env = dict(Path=Path, APIRouter=APIRouter, __file__=str(path),
               pkgutil=SimpleNamespace(iter_modules=inventory), importlib=SimpleNamespace(import_module=load))
    exec_selected(tree, path, env)
    return env['_discover_routers'], imports, locations


def approved_page_inverse(test, template, html):
    """Validate the exact accepted overlays before normalizing an in-memory copy."""
    class CommerceAssets(HTMLParser):
        def __init__(self):
            super().__init__(); self.assets = []
        def handle_starttag(self, tag, attrs):
            attribute = {'script': 'src', 'link': 'href'}.get(tag)
            values = [value for name, value in attrs if attribute is not None and name == attribute]
            if values:
                test.assertEqual(len(values), 1, f'duplicate {attribute} attributes')
            value = values[0] if values else None
            if value and value.startswith('/shared/admin-commerce-'):
                self.assets.append((tag, value))

    for label, source in (('template', template.decode('utf-8')), ('rendered', html)):
        parser = CommerceAssets(); parser.feed(source)
        # New cache overlay must be exact before any in-memory historical inverse.
        for _, asset in APPROVED_COMMERCE_ASSETS[5:7]:
            test.assertEqual(source.count(asset), 1,
                             label + ': approved flow block / approved commerce assets: return cache URL exactly once')
        test.assertEqual(source.count(FLOW_BLOCK), 1, label + ': approved flow block exactly once')
        test.assertEqual(source.count('PopcornPhysicalReturns.mount('), 1,
                         label + ': single approved mount')
        test.assertEqual(source.count('commerceOrderFlows='), 1,
                         label + ': single approved flow assignment')
        test.assertEqual(tuple(parser.assets), APPROVED_COMMERCE_ASSETS,
                         label + ': approved commerce assets exact order/count/query')
        test.assertLess(source.index(APPROVED_COMMERCE_ASSETS[2][1]), source.index(FLOW_BLOCK))
        test.assertLess(source.index(FLOW_BLOCK), source.index(APPROVED_COMMERCE_ASSETS[7][1]))

    # Invert only the two positively checked return queries in memory.
    # Historical hashes and all earlier overlay inverses remain unchanged.
    historical_flow_block = FLOW_BLOCK
    for _, asset in APPROVED_COMMERCE_ASSETS[5:7]:
        previous = asset.split('?v=', 1)[0] + '?v=20261006-1'
        template = template.replace(asset.encode(), previous.encode())
        html = html.replace(asset, previous)
        historical_flow_block = historical_flow_block.replace(asset, previous)

    # Historical whole-template bytes, independently checked against each accepted dirty-before.
    before_flows = template.replace(historical_flow_block.encode(), b'').replace(
        b'20261006-flows-1', b'20261006-restoration-1')
    test.assertEqual(hashlib.sha256(before_flows).hexdigest(),
                     '5bbddd9e721cfd89e252ac02f3804fac64556f88586491d5116a5dbb165c77ae')
    before_restoration = before_flows.replace(
        b'admin-commerce-orders.js?v=20261006-restoration-1', b'admin-commerce-orders.js?v=20261005-4'
    ).replace(
        b'admin-commerce-orders.css?v=20261006-restoration-1', b'admin-commerce-orders.css?v=20261005-3'
    )
    test.assertEqual(hashlib.sha256(before_restoration).hexdigest(),
                     'e856172d6c9c578fc239c68e9a3937e1fd4f3c33d0b9e7745a553c4b3ff2cb06')
    normalized = html.replace(historical_flow_block, '').replace(
        'admin-commerce-orders.js?v=20261006-flows-1',
        'admin-commerce-orders.js?v=20261006-restoration-1'
    ).replace(
        'admin-commerce-orders.css?v=20261006-flows-1',
        'admin-commerce-orders.css?v=20261006-restoration-1'
    )
    return normalized.replace('admin-commerce-orders.js?v=20261006-restoration-1',
                              'admin-commerce-orders.js?v=20261005-4').replace(
        'admin-commerce-orders.css?v=20261006-restoration-1',
        'admin-commerce-orders.css?v=20261005-3')


class CommerceOrdersPageTests(unittest.TestCase):
    def test_actual_handler_uses_approved_template_new_mode_and_confirmed_identity_only(self):
        render = Mock(return_value='sentinel'); env = page(render); req = request()
        self.assertEqual(env['commerce_orders_page'](req), 'sentinel')
        render.assert_called_once_with(req, 'admin/commerce_orders.html.j2', screen_id='ADM-ORD-040',
            domain='commerce-orders', crumb_group='신 관리자', crumb_now='주문 운영', admin_mode='new')
    def test_rendered_page_has_one_active_menu_and_shared_breadcrumb(self):
        env = page(renderer(navigation())); response = env['commerce_orders_page'](request())
        html = response.body.decode()
        html = approved_page_inverse(self, (ROOT / 'templates/admin/commerce_orders.html.j2').read_bytes(), html)
        self.assertIn('data-screen-id="ADM-ORD-040"', html)
        self.assertIn('data-domain="commerce-orders" data-admin-mode="new"', html)
        self.assertIn('<span class="a2-crumb">신 관리자</span>', html)
        self.assertIn('<span class="a2-now">주문 운영</span>', html)
        self.assertEqual(html.count('href="/admin2/commerce-orders"'), 1)
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertIn('주문 조회가 연결되지 않았습니다.', html)
        self.assertIn('/shared/admin-commerce-orders.js?v=20261005-4', html)
        self.assertIn('/shared/admin-commerce-orders.css?v=20261005-3', html)
        self.assertIn('/shared/admin-commerce-orders-transport.js?v=20261005-2', html)
        self.assertIn('현재 페이지 주문번호 검색', html)
        self.assertIn('상태별 보기는 현재 페이지에만 적용', html)
        for node in ('aco-refresh', 'aco-prev', 'aco-next'):
            self.assertIn(f'id="{node}" type="button" disabled', html)
        self.assertNotIn('data-order-index=', html)
    def test_approved_page_inverse_rejects_unapproved_asset_versions(self):
        template = (ROOT / 'templates/admin/commerce_orders.html.j2').read_bytes()
        html = page(renderer(navigation()))['commerce_orders_page'](request()).body.decode()
        for _, asset in APPROVED_COMMERCE_ASSETS:
            for target in ('template', 'rendered'):
                with self.subTest(asset=asset, target=target):
                    changed = asset.split('?')[0] + '?v=unapproved'
                    raw = template.replace(asset.encode(), changed.encode()) if target == 'template' else template
                    rendered = html.replace(asset, changed) if target == 'rendered' else html
                    with self.assertRaisesRegex(AssertionError, 'approved flow block|approved commerce assets'):
                        approved_page_inverse(self, raw, rendered)
    def test_approved_page_inverse_rejects_duplicate_flow_block_and_mount(self):
        template = (ROOT / 'templates/admin/commerce_orders.html.j2').read_bytes()
        html = page(renderer(navigation()))['commerce_orders_page'](request()).body.decode()
        for duplicate in (FLOW_BLOCK, FLOW_MOUNT):
            for target in ('template', 'rendered'):
                with self.subTest(duplicate=duplicate, target=target):
                    raw = template.replace(FLOW_BLOCK.encode(), (FLOW_BLOCK + duplicate).encode()) if target == 'template' else template
                    rendered = html.replace(FLOW_BLOCK, FLOW_BLOCK + duplicate) if target == 'rendered' else html
                    with self.assertRaisesRegex(AssertionError, 'approved flow block|single approved mount'):
                        approved_page_inverse(self, raw, rendered)
    def test_approved_page_inverse_rejects_duplicate_src_and_href_attributes(self):
        template = (ROOT / 'templates/admin/commerce_orders.html.j2').read_bytes()
        html = page(renderer(navigation()))['commerce_orders_page'](request()).body.decode()
        for tag, asset in APPROVED_COMMERCE_ASSETS:
            attribute = 'src' if tag == 'script' else 'href'
            unapproved = asset.split('?')[0] + '?v=unapproved'
            original = f'{attribute}="{asset}"'
            for values in ((unapproved, asset), (asset, unapproved)):
                duplicate = ' '.join(f'{attribute}="{value}"' for value in values)
                for target in ('template', 'rendered'):
                    with self.subTest(asset=asset, values=values, target=target):
                        raw = template.replace(original.encode(), duplicate.encode()) if target == 'template' else template
                        rendered = html.replace(original, duplicate) if target == 'rendered' else html
                        with self.assertRaisesRegex(AssertionError, f'duplicate {attribute} attributes'):
                            approved_page_inverse(self, raw, rendered)
    def test_support_assets_are_unique_and_follow_renderer_transport(self):
        html = page(renderer(navigation()))['commerce_orders_page'](request()).body.decode()
        for asset in ('/shared/admin-commerce-support.js?v=20261005-1', '/shared/admin-commerce-support.css?v=20261005-1'):
            self.assertEqual(html.count(asset), 1)
        self.assertLess(html.index('/shared/admin-commerce-orders.js?'), html.index('/shared/admin-commerce-orders-transport.js?'))
        self.assertLess(html.index('/shared/admin-commerce-orders-transport.js?'), html.index('/shared/admin-commerce-support.js?'))
    def test_page_new_profile_overrides_legacy_cookie_and_query_with_no_store(self):
        env = page(renderer(navigation()))
        response = env['commerce_orders_page'](request(query='admin=legacy', cookie='admin_ui_mode=legacy'))
        self.assertIn('data-admin-mode="new"', response.body.decode())
        self.assertIn('admin_ui_mode=new', response.headers['set-cookie'])
        self.assertEqual(response.headers['cache-control'], 'no-cache, no-store, must-revalidate')
        self.assertEqual(response.headers['pragma'], 'no-cache')
    def test_query_values_are_not_injected_as_business_or_customer_context(self):
        env = page(renderer(navigation()))
        html = env['commerce_orders_page'](request(query='order_no=PRIVATE-MARKER&email=PRIVATE-EMAIL')).body.decode()
        self.assertNotIn('PRIVATE-MARKER', html); self.assertNotIn('PRIVATE-EMAIL', html)
    def test_actual_router_is_get_only_and_in_process_asgi_selects_handler(self):
        render = Mock(return_value=HTMLResponse('bounded-render'))
        env = page(render); app = FastAPI(); app.include_router(env['router'])
        self.assertEqual([(r.path, r.methods) for r in env['router'].routes],
                         [('/admin2/commerce-orders', {'GET'})])
        with TestClient(app) as client:
            response = client.get('/admin2/commerce-orders')
            self.assertEqual((response.status_code, response.text), (200, 'bounded-render'))
            self.assertEqual(client.post('/admin2/commerce-orders').status_code, 405)
        self.assertEqual(render.call_count, 1)
    def test_nav_single_new_item_and_exact_active_trailing_slash(self):
        nav = navigation()['new_admin_nav']
        for path in ('/admin2/commerce-orders', '/admin2/commerce-orders/'):
            items = nav(path)
            self.assertEqual([i['label'] for i in items if i['active']], ['주문 운영'])
            self.assertEqual(len([i for i in items if i['href'] == '/admin2/commerce-orders']), 1)
            self.assertEqual(len({i['href'] for i in items}), len(items))
        for path in ('/admin2/commerce-orders-other', '/admin2/commerce-orders/unsafe'):
            self.assertFalse(any(i['active'] for i in nav(path)))
    def test_every_existing_nav_path_and_active_behavior_preserved(self):
        tree = source_tree(NAV)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'new_admin_nav')
        assignment = next(n for n in fn.body if isinstance(n, ast.Assign))
        approved = next(n for n in assignment.value.elts if ast.literal_eval(n)[1] == '/admin2/commerce-orders')
        assignment.value.elts.remove(approved)
        env = exec_selected(tree, NAV, {})
        old = env['new_admin_nav']; current = navigation()['new_admin_nav']
        # Execute the original function for every existing accepted alias, not a copied expected map.
        for _, _, _, paths in ast.literal_eval(assignment.value):
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual([i for i in current(path) if i['href'] != '/admin2/commerce-orders'], old(path))
        digest = hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
        self.assertEqual(digest, NAV_BASELINE_AST_SHA)
    def test_discovery_actual_function_finds_new_page_and_skips_main_private_helper(self):
        env = page(Mock()); discover, imports, locations = discovery(env)
        self.assertEqual(discover(), [('admin_ui_commerce_orders', env['router'])])
        self.assertEqual(imports, ['api.admin_ui_commerce_orders', 'api.safe_helper'])
        self.assertEqual(locations, [[str(ROOT / 'api')]])
        self.assertNotIn('api.main', imports)
    def test_discovery_import_failure_propagates(self):
        discover, imports, _ = discovery(page(Mock()), failure=True)
        with self.assertRaisesRegex(RuntimeError, 'bounded discovery failure'): discover()
        self.assertEqual(imports, ['api.admin_ui_commerce_orders'])
    def test_page_source_has_only_shared_renderer_import_and_no_business_execution(self):
        tree = source_tree(PAGE)
        imports = [(n.level, n.module, [x.name for x in n.names])
                   for n in tree.body if isinstance(n, ast.ImportFrom)]
        self.assertEqual(imports, [(0, 'fastapi', ['APIRouter', 'Request']),
            (0, 'fastapi.responses', ['HTMLResponse']), (1, 'admin_ui_common', ['render'])])
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        self.assertEqual(len(fn.body), 1)
        self.assertIsInstance(fn.body[0], ast.Return)
        self.assertEqual(fn.body[0].value.func.id, 'render')


if __name__ == '__main__': unittest.main()
