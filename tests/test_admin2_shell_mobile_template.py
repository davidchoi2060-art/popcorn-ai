"""Actual Jinja shell and navigation AST only; no main/auth/DB or operating HTTP."""
import ast
from pathlib import Path
import unittest
from html.parser import HTMLParser
from types import SimpleNamespace
from jinja2 import Environment, FileSystemLoader
ROOT=Path(__file__).resolve().parents[1]
class DOM(HTMLParser):
    def __init__(self): super().__init__(); self.nodes=[]
    def handle_starttag(self,tag,attrs): self.nodes.append((tag,dict(attrs)))
    def byid(self,id): return [attrs for tag,attrs in self.nodes if attrs.get('id')==id]
    def links(self,href): return [a for tag,a in self.nodes if tag=='a' and a.get('href')==href]
def navigation():
    # 2026-11-18 메뉴 통합 — 셸은 모드와 무관하게 단일 메뉴(simple_nav)를 그린다.
    tree=ast.parse((ROOT/'api/admin_nav.py').read_text(encoding='utf-8'))
    names={'NAV','SIMPLE_MENU','SIMPLE_EXTRA','SIMPLE_LABELS','nav_for_screens','simple_nav','_same_path'}
    tree.body=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name in names) or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets))]
    env={};exec(compile(tree,'bounded-nav','exec'),env)
    return env
def render(new=True,path='/admin2/commerce-orders',page=None,simple=True):
    env=Environment(loader=FileSystemLoader(str(ROOT/'templates')),autoescape=True)
    if page: template=env.get_template('admin/'+page)
    else: template=env.from_string('{% extends "admin/_admin2_shell.html.j2" %}{% block header_extra %}<button id="fixtureHeaderAction" data-action="fixture-header">실제 추가 위젯 자리</button>{% endblock %}{% block content %}<main><input id="fixtureBody"></main>{% endblock %}')
    nav=navigation()
    extra={'simple_nav':nav['simple_nav']} if simple else {}
    return template.render(new_admin=new,nav=nav['nav_for_screens'](path),screen_id='FIXTURE',domain='commerce',crumb_group='주문',crumb_now='주문 운영',request=SimpleNamespace(url=SimpleNamespace(path=path)),initial_q='',initial_bucket='all',**extra)
def dom(html):
    p=DOM();p.feed(html);return p
class MobileShellTemplateTests(unittest.TestCase):
    def test_new_disclosure_has_unique_real_controls_and_visible_label(self):
        for new in (True,False):
            d=dom(render(new));self.assertEqual(len(d.byid('lnbMobileToggle')),1)
        d=dom(render());self.assertEqual(len(d.byid('lnbMobileToggle')),1);a=d.byid('lnbMobileToggle')[0];self.assertEqual(a['type'],'button');self.assertNotIn('disabled',a);self.assertEqual(a['aria-controls'],'lnbMenu');self.assertEqual(a['aria-expanded'],'false');self.assertEqual(a['aria-label'],'메뉴 열기');self.assertEqual(len(d.byid('lnbMenu')),1)
    def test_fallback_markup_without_single_menu_keeps_only_original_trigger(self):
        d=dom(render(False,simple=False));self.assertEqual(d.byid('lnbMobileToggle'),[]);self.assertEqual(len(d.byid('lnbToggle')),1);self.assertTrue(any(a.get('data-action')=='lnb-group' for t,a in d.nodes))
    def test_actual_header_context_and_original_hub_profile_contracts(self):
        for new in [False,True]:
            d=dom(render(new));self.assertEqual(len(d.byid('roleBox')),1);self.assertEqual(len(d.byid('fixtureHeaderAction')),1);hub=d.links('/mvp1/index.html')[0];self.assertEqual(hub['target'],'_blank');self.assertEqual(hub['rel'],'noopener');self.assertEqual(hub['data-keep'],'1');profile=d.links('/admin2/my-profile')[0];self.assertNotIn('target',profile);self.assertNotIn('data-keep',profile);self.assertEqual(profile['aria-label'],'내 정보');self.assertEqual(d.byid('lnb')[0]['data-keep'],'1')
    def test_links_match_single_navigation_in_both_modes(self):
        groups=navigation()['simple_nav']('/admin2/commerce-orders')
        expected=[r for g in groups for r in g['basic']+g['advanced']]
        self.assertIn('/admin2/commerce-orders',[r['href'] for r in expected])
        for new in (True,False):
            d=dom(render(new))
            for item in expected:
                links=d.links(item['href']);self.assertEqual(len(links),1,item['href'])
                self.assertEqual(links[0].get('aria-current')=='page',item['active'])
            self.assertEqual(sum(1 for t,a in d.nodes if a.get('aria-current')=='page'),1)
    def test_actual_orders_template_preserves_body_and_shared_assets(self):
        s=render(page='commerce_orders.html.j2');d=dom(s);self.assertEqual(len(d.byid('commerce-orders')),1);self.assertIn('admin-commerce-support.js',s);self.assertIn('admin2-shell.js?v=20261011-intro',s);self.assertIn('admin2.css?v=20261011-intro',s)
    def test_direct_shell_caller_static_census_without_business_imports(self):
        # Inherited shell blocks only; do not execute page business code/context.
        names=[]
        for p in (ROOT/'templates/admin').glob('*.j2'):
            tree=Environment().parse(p.read_text(encoding='utf-8-sig'))
            from jinja2.nodes import Extends,Const
            if any(isinstance(n.template,Const) and n.template.value=='admin/_admin2_shell.html.j2' for n in tree.find_all(Extends)): names.append(p.name)
        self.assertGreaterEqual(len(names),63)
        self.assertIn('reviews.html.j2',names);self.assertIn('stock_inbound.html.j2',names)
    def test_new_css_scope_restores_hub_without_changing_original_hidden_rule(self):
        s=(ROOT/'mockups/shared/admin2/admin2.css').read_text(encoding='utf-8');self.assertIn('.a2-hd .a2-hub{display:none}',s);self.assertIn('body[data-admin-mode=new] .a2-hd .a2-hub{display:inline-flex}',s);self.assertIn('--a2-zoom: 1.15',s);self.assertNotIn('.a2-hd{display:none}',s)
if __name__=='__main__': unittest.main()
