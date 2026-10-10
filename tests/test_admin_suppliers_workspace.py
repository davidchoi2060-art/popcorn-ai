"""Supplier-only relational fixture. Blocks every connection to the configured DB.

SQLite tests the actual CAS statement/interleavings, not PostgreSQL lock behavior.
The shared production regression suite and api.main are deliberately not imported.
"""
import concurrent.futures
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text

from api import db, auth
from api import admin_suppliers as suppliers
from api import admin_ui_suppliers as ui

sqlite3.register_converter("TIMESTAMP", lambda b: datetime.fromisoformat(b.decode()))


def fixture_engine(path):
    engine = create_engine("sqlite:///" + str(path), native_datetime=True,
                           connect_args={"check_same_thread": False,
                                         "detect_types": sqlite3.PARSE_DECLTYPES, "timeout": 10})
    @event.listens_for(engine, "connect")
    def setup(conn, _):
        conn.create_function("btrim", 1, lambda value: value.strip() if value else value, deterministic=True)
        conn.execute("PRAGMA foreign_keys=ON")
    ddl = [
        "CREATE TABLE suppliers(supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,platform TEXT,brands TEXT,status TEXT NOT NULL DEFAULT '활성',created_at TIMESTAMP DEFAULT '2026-10-01 00:00:00',contact_name TEXT,contact_phone TEXT,order_phone TEXT,contact_raw TEXT,contact_fetched_at TIMESTAMP)",
        "CREATE UNIQUE INDEX ux_suppliers_name ON suppliers(lower(btrim(name)))",
        "CREATE TABLE products(product_code INTEGER PRIMARY KEY,sku TEXT,product_name TEXT)",
        "CREATE TABLE product_supplier_prices(product_code INTEGER REFERENCES products(product_code),supplier_id INTEGER REFERENCES suppliers(supplier_id),cost_price INTEGER NOT NULL,supply_state TEXT,PRIMARY KEY(product_code,supplier_id))",
        "CREATE TABLE supplier_price_files(file_id INTEGER PRIMARY KEY,supplier_id INTEGER REFERENCES suppliers(supplier_id))",
        "CREATE TABLE supplier_presets(preset_id INTEGER PRIMARY KEY,supplier_id INTEGER REFERENCES suppliers(supplier_id))",
        "CREATE TABLE fixture_supplier_logs(id INTEGER PRIMARY KEY,action TEXT,target TEXT,detail TEXT,operator_id INTEGER)",
    ]
    with engine.begin() as c:
        for sql in ddl: c.execute(text(sql))
        c.execute(text("INSERT INTO suppliers(supplier_id,name,platform,brands,status,contact_name,contact_phone,contact_raw,contact_fetched_at) VALUES(101,'Alpha','직거래','Memory','활성','fixture contact','02-0000-0000','private fixture raw','2026-10-01 00:00:00'),(102,'Beta','몰','Board','중지',NULL,NULL,NULL,NULL),(103,'Literal_%','  원래 값  ','Brand','활성',NULL,NULL,NULL,NULL)"))
        c.execute(text("INSERT INTO products VALUES(1001,'F-1','fixture memory'),(1002,'F-2','fixture SSD')"))
        c.execute(text("INSERT INTO product_supplier_prices VALUES(1001,101,100,'가능'),(1002,101,200,'문의'),(1002,102,220,'가능')"))
        c.execute(text("INSERT INTO supplier_price_files VALUES(1,101),(2,102)"))
        c.execute(text("INSERT INTO supplier_presets VALUES(1,101)"))
    return engine


def fixture_operator(cookie):
    if cookie not in ("viewer", "operator", "owner"): return None
    return dict(operator_id=7, name="fixture", email="fixture@example.invalid", role=cookie, status="활성", password_verified=True)


def fixture_log(conn, action, target_id, detail, kind="supplier"):
    # Keep the logging call/actor contract; actual shared logger SQL is outside this fixture.
    assert kind == "supplier"
    conn.execute(text("INSERT INTO fixture_supplier_logs(action,target,detail,operator_id) VALUES(:a,:t,:d,:op)"),
                 dict(a=action,t=target_id,d=json.dumps(detail,ensure_ascii=False),op=auth.current_operator_id()))


def fixture_app(engine):
    app = FastAPI()
    app.middleware("http")(auth.auth_middleware)
    app.include_router(suppliers.router)
    app.include_router(ui.router)
    return app


class SupplierWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="supplier-fixture-")
        self.engine = fixture_engine(Path(self.tmp.name) / "fixture.sqlite")
        self.guards = [patch.object(db.engine,"connect",side_effect=AssertionError("configured DB access forbidden")),
                       patch.object(db.engine,"begin",side_effect=AssertionError("configured DB writes forbidden")),
                       patch.object(suppliers,"engine",self.engine), patch.object(suppliers,"_log",fixture_log),
                       patch.object(auth,"resolve_session",side_effect=fixture_operator)]
        for p in self.guards:p.start()
        self.client=TestClient(fixture_app(self.engine))
        self.client.cookies.set(auth.COOKIE,"operator")

    def tearDown(self):
        self.client.close()
        for p in reversed(self.guards):p.stop()
        self.engine.dispose(); self.tmp.cleanup()

    def snapshot(self, sid=101):
        response=self.client.get(f"/api/admin/suppliers/{sid}/profile")
        self.assertEqual(200,response.status_code)
        return response.json()["edit_snapshot"]

    def editor(self, change, sid=101, expected=None):
        return self.client.patch(f"/api/admin/suppliers/{sid}/editor",json={"expected":expected or self.snapshot(sid),"supplier":change})

    def untouched(self):
        with self.engine.connect() as c:
            return [list(c.execute(text(sql)).all()) for sql in
                    ["SELECT * FROM product_supplier_prices ORDER BY product_code,supplier_id",
                     "SELECT * FROM products ORDER BY product_code",
                     "SELECT * FROM supplier_price_files ORDER BY file_id",
                     "SELECT * FROM supplier_presets ORDER BY preset_id",
                     "SELECT supplier_id,contact_name,contact_phone,order_phone,contact_raw,contact_fetched_at FROM suppliers ORDER BY supplier_id"]]

    def test_legacy_collection_keys_and_ids_unchanged(self):
        j=self.client.get('/api/admin/suppliers').json()
        self.assertEqual(set(j),{"items","total","active","inactive","no_preset_count","empty","note"})
        self.assertEqual((3,2,1,2),tuple(j[k] for k in ('total','active','inactive','no_preset_count')))
        self.assertEqual(set(j['items'][0]),{"id","name","platform","brands","status","created","linked_products","price_files","preset_count"})
        self.assertEqual(101,j['items'][0]['id']);self.assertNotIn('supplier_id',j['items'][0])

    def test_legacy_post_and_full_patch_contract(self):
        r=self.client.post('/api/admin/suppliers',json={'name':'New','platform':'channel','brands':'GPU'})
        self.assertEqual(200,r.status_code);j=r.json();self.assertIn('note',j);sid=j['id']
        r=self.client.patch(f'/api/admin/suppliers/{sid}',json={'name':'New'})
        self.assertEqual(200,r.status_code);self.assertIsNone(r.json()['platform']);self.assertIsNone(r.json()['brands'])
        self.assertEqual('활성',r.json()['status']);self.assertIn('changed',r.json())

    def test_legacy_impact_key_and_meaning(self):
        j=self.client.get('/api/admin/suppliers/101/impact').json()
        self.assertEqual((101,2,1,1),tuple(j[k] for k in ['supplier_id','linked_products','price_files','sole_source_products']))
        self.assertNotIn('id',j)

    def test_directory_filters_literal_search_and_summary(self):
        j=self.client.get('/api/admin/suppliers/directory?status=중지').json()
        self.assertEqual(1,j['total']);self.assertEqual(3,j['summary']['total']);self.assertEqual(102,j['items'][0]['id'])
        for q,sid in [('101',101),('alpha',101),('Memory',101),('직거래',101),('_%',103)]:
            j=self.client.get('/api/admin/suppliers/directory',params={'q':q}).json()
            self.assertEqual([sid],[i['id'] for i in j['items']])
        j=self.client.get('/api/admin/suppliers/directory?q=missing').json()
        self.assertEqual([],j['items']);self.assertFalse(j['empty']);self.assertEqual(3,j['summary']['total'])

    def test_directory_server_pagination_and_out_of_range(self):
        with self.engine.begin() as c:
            for i in range(40):c.execute(text("INSERT INTO suppliers(name,status) VALUES(:n,'활성')"),{'n':f'Paged{i:02}'})
        first=self.client.get('/api/admin/suppliers/directory').json()
        second=self.client.get('/api/admin/suppliers/directory?page=2').json()
        self.assertEqual((43,20,20),(first['total'],len(first['items']),len(second['items'])))
        self.assertFalse({i['id'] for i in first['items']} & {i['id'] for i in second['items']})
        beyond=self.client.get('/api/admin/suppliers/directory?page=9').json()
        self.assertEqual(43,beyond['total']);self.assertEqual([],beyond['items'])

    def test_query_validation(self):
        for params in [{'status':'bad'},{'page':0},{'page':1000001},{'page_size':1000},{'page_size':30},{'q':'x'*101}]:
            self.assertEqual(422,self.client.get('/api/admin/suppliers/directory',params=params).status_code)
        for size in [20,50,100]:
            for url in ['/api/admin/suppliers/directory','/api/admin/suppliers/101/products']:
                r=self.client.get(url,params={'page_size':str(size)})
                self.assertEqual(200,r.status_code);self.assertEqual(size,r.json()['page_size'])

    def test_profile_contact_source_privacy_and_missing(self):
        j=self.client.get('/api/admin/suppliers/101/profile').json()
        self.assertEqual('mall_observation',j['contact']['source']);self.assertTrue(j['contact']['fetched_at'].endswith('+00:00'))
        self.assertNotIn('contact_raw',json.dumps(j));self.assertNotIn('private fixture raw',json.dumps(j))
        j=self.client.get('/api/admin/suppliers/102/profile').json()
        self.assertIsNone(j['contact']['phone']);self.assertEqual('unverified',j['contact']['source'])
        self.assertEqual(404,self.client.get('/api/admin/suppliers/999/profile').status_code)

    def test_products_readonly_and_empty(self):
        saved=self.untouched();j=self.client.get('/api/admin/suppliers/101/products').json()
        self.assertEqual(2,j['total']);self.assertEqual([1001,1002],[i['product_code'] for i in j['items']])
        self.assertEqual(set(j['items'][0]),{'product_code','sku','display_name','supply_state'})
        self.assertEqual([],self.client.get('/api/admin/suppliers/103/products').json()['items'])
        self.assertEqual(404,self.client.get('/api/admin/suppliers/999/products').status_code)
        self.assertEqual(saved,self.untouched())

    def test_products_server_pagination(self):
        with self.engine.begin() as c:
            for code in range(2001,2024):
                c.execute(text("INSERT INTO products VALUES(:code,:sku,NULL)"),{'code':code,'sku':f'Fixture-{code}'})
                c.execute(text("INSERT INTO product_supplier_prices VALUES(:code,101,100,'가능')"),{'code':code})
        first=self.client.get('/api/admin/suppliers/101/products').json()
        last=self.client.get('/api/admin/suppliers/101/products?page=2').json()
        self.assertEqual((25,20,5),(first['total'],len(first['items']),len(last['items'])))
        self.assertFalse({p['product_code'] for p in first['items']} & {p['product_code'] for p in last['items']})
        self.assertEqual('Fixture-2023',last['items'][-1]['display_name'])

    def test_partial_edit_preserves_omitted_and_readonly_values(self):
        saved=self.untouched();r=self.editor({'name':'Alpha revised'})
        self.assertEqual(200,r.status_code);self.assertEqual('직거래',r.json()['platform']);self.assertEqual('Memory',r.json()['brands']);self.assertEqual('활성',r.json()['status'])
        self.assertEqual({'name'},set(r.json()['changed']));self.assertEqual(saved,self.untouched())
        r=self.editor({'status':'중지'},sid=103)
        self.assertEqual(200,r.status_code);self.assertEqual('  원래 값  ',r.json()['platform'])

    def test_explicit_null_clears_only_requested_field(self):
        r=self.editor({'platform':None})
        self.assertEqual(200,r.status_code);self.assertIsNone(r.json()['platform']);self.assertEqual('Memory',r.json()['brands'])

    def test_stale_snapshot_returns_409_and_preserves_data(self):
        expected=self.snapshot();self.assertEqual(200,self.editor({'brands':'New brand'},expected=expected).status_code)
        saved=self.untouched();r=self.editor({'name':'stale edit'},expected=expected)
        self.assertEqual(409,r.status_code);self.assertEqual('stale_supplier',r.json()['detail']['error']);self.assertEqual(saved,self.untouched())
        self.assertEqual('Alpha',self.snapshot()['name'])

    def test_concurrent_same_snapshot_only_one_wins(self):
        expected=self.snapshot();barrier=threading.Barrier(2)
        def meet(conn,cursor,statement,params,context,executemany):
            if statement.startswith('UPDATE suppliers SET') and 'IS NOT DISTINCT FROM' in statement:barrier.wait(timeout=5)
        event.listen(self.engine,'before_cursor_execute',meet)
        def edit(name):
            token=auth._current.set(fixture_operator('operator'))
            try:
                return 200,suppliers.edit_supplier_workspace(101,suppliers.SupplierEditorBody(expected=expected,supplier={'name':name}))['name']
            except HTTPException as e:return e.status_code,e.detail['error']
            finally:auth._current.reset(token)
        try:
            with concurrent.futures.ThreadPoolExecutor(2) as pool:out=list(pool.map(edit,['winner A','winner B']))
        finally:event.remove(self.engine,'before_cursor_execute',meet)
        self.assertEqual([200,409],sorted(x[0] for x in out));self.assertEqual('stale_supplier',next(x[1] for x in out if x[0]==409))
        with self.engine.connect() as c:self.assertEqual(1,c.execute(text('SELECT COUNT(*) FROM fixture_supplier_logs')).scalar())

    def test_compare_guard_catches_change_after_select(self):
        expected=self.snapshot();fired=False
        def interleave(conn,cursor,statement,params,context,executemany):
            nonlocal fired
            if not fired and statement.startswith('UPDATE suppliers SET') and 'IS NOT DISTINCT FROM' in statement:
                fired=True
                with self.engine.begin() as other:other.execute(text("UPDATE suppliers SET brands='external change' WHERE supplier_id=101"))
        event.listen(self.engine,'before_cursor_execute',interleave)
        try:r=self.editor({'name':'late edit'},expected=expected)
        finally:event.remove(self.engine,'before_cursor_execute',interleave)
        self.assertEqual(409,r.status_code);self.assertEqual('external change',self.snapshot()['brands']);self.assertEqual('Alpha',self.snapshot()['name'])

    def test_duplicate_registration_and_editor(self):
        r=self.client.post('/api/admin/suppliers',json={'name':' alpha '})
        self.assertEqual(409,r.status_code);self.assertEqual(101,r.json()['detail']['supplier_id'])
        r=self.editor({'name':' beta '})
        self.assertEqual(409,r.status_code);self.assertEqual('duplicate_name',r.json()['detail']['error'])
        self.assertEqual(102,r.json()['detail']['supplier_id']);self.assertEqual('Alpha',self.snapshot()['name'])

    def test_duplicate_insert_after_precheck_rolls_back_editor(self):
        expected=self.snapshot();fired=False
        def interleave(conn,cursor,statement,params,context,executemany):
            nonlocal fired
            if not fired and statement.startswith('UPDATE suppliers SET') and 'IS NOT DISTINCT FROM' in statement:
                fired=True
                with self.engine.begin() as other:
                    other.execute(text("INSERT INTO suppliers(name,status) VALUES('Late duplicate','활성')"))
        event.listen(self.engine,'before_cursor_execute',interleave)
        try:r=self.editor({'name':'Late duplicate','brands':'should rollback'},expected=expected)
        finally:event.remove(self.engine,'before_cursor_execute',interleave)
        self.assertEqual(409,r.status_code);self.assertIsInstance(r.json()['detail'],str)
        self.assertEqual(expected,self.snapshot())
        with self.engine.connect() as c:self.assertEqual(0,c.execute(text('SELECT COUNT(*) FROM fixture_supplier_logs')).scalar())

    def test_noop_has_no_log(self):
        r=self.editor({});self.assertEqual(200,r.status_code);self.assertEqual({},r.json()['changed']);self.assertEqual('바뀐 값이 없습니다',r.json()['note'])
        with self.engine.connect() as c:self.assertEqual(0,c.execute(text('SELECT COUNT(*) FROM fixture_supplier_logs')).scalar())

    def test_state_roundtrip_keeps_links_contacts_prices(self):
        expected=self.snapshot();saved=self.untouched()
        stopped=self.editor({'status':'중지'},expected=expected);self.assertEqual(200,stopped.status_code)
        r=self.editor({'status':'활성'});self.assertEqual(200,r.status_code)
        self.assertEqual(expected,self.snapshot());self.assertEqual(saved,self.untouched())
        with self.engine.connect() as c:
            rows=c.execute(text('SELECT detail,operator_id FROM fixture_supplier_logs')).all()
        self.assertEqual(2,len(rows));self.assertEqual([7,7],[r[1] for r in rows]);self.assertNotIn('fixture contact',str(rows))

    def test_payload_rejects_unknown_contact_and_missing_snapshot(self):
        expected=self.snapshot()
        for payload in [{'expected':expected,'supplier':{'contact_phone':'x'}},{'supplier':{'name':'x'}},{'expected':{'name':'x'},'supplier':{}}]:
            self.assertEqual(422,self.client.patch('/api/admin/suppliers/101/editor',json=payload).status_code)

    def test_name_lengths_status_and_missing_supplier(self):
        for change in [{'name':''},{'name':'x'*101},{'name':None},{'platform':'x'*51},{'brands':'x'*201},{'status':'bad'},{'status':None}]:
            self.assertEqual(400,self.editor(change).status_code)
        self.assertEqual(404,self.client.patch('/api/admin/suppliers/999/editor',json={'expected':self.snapshot(),'supplier':{'name':'x'}}).status_code)

    def test_middleware_roles_for_legacy_and_new_api(self):
        expected=self.snapshot()
        for role in ['viewer','operator','owner']:
            self.client.cookies.set(auth.COOKIE,role)
            self.assertEqual(200,self.client.get('/api/admin/suppliers/directory').status_code)
            self.assertEqual(role!='viewer',self.client.get('/api/admin/suppliers/101/profile').json()['can_write'])
            expect=403 if role=='viewer' else 200
            self.assertEqual(expect,self.client.patch('/api/admin/suppliers/101/editor',json={'expected':expected,'supplier':{}}).status_code)
            self.assertEqual(expect,self.client.patch('/api/admin/suppliers/101',json=expected).status_code)
        self.client.cookies.clear()
        self.assertEqual(401,self.client.get('/api/admin/suppliers/directory').status_code)
        self.assertEqual(401,self.client.get('/api/admin/suppliers').status_code)
        self.assertEqual(401,self.client.get('/admin2/suppliers').status_code)

    def test_menu_follows_operator_choice_and_is_not_rewritten(self):
        # 2026-10-10 전수 점검: 기존 메뉴에서 공급처를 누르면 메뉴 선택 쿠키가 new 로 바뀌어
        # 그 뒤 모든 화면이 신 관리자 메뉴로 열렸다. 공급처는 기존 메뉴(NAV)에도 있는 화면이라
        # 들어온 메뉴를 그대로 따라야 하고, 선택을 다시 쓰지 않아야 한다.
        r=self.client.get('/admin2/suppliers');html=r.text
        self.assertEqual(200,r.status_code);self.assertIn('class="a2-lnb-grp"',html);self.assertNotIn('a2-new-secondary',html)
        self.assertNotIn('admin_ui_mode','\n'.join(r.headers.get_list('set-cookie')))
        self.client.cookies.set('admin_ui_mode','legacy');r=self.client.get('/admin2/suppliers')
        self.assertIn('class="a2-lnb-grp"',r.text);self.assertNotIn('admin_ui_mode','\n'.join(r.headers.get_list('set-cookie')))
        self.client.cookies.set('admin_ui_mode','new');r=self.client.get('/admin2/suppliers')
        self.assertIn('a2-new-secondary',r.text);self.assertNotIn('admin_ui_mode','\n'.join(r.headers.get_list('set-cookie')))
        self.client.cookies.delete('admin_ui_mode')

    def test_new_page_and_viewer_write_controls(self):
        r=self.client.get('/admin2/suppliers?admin=new');html=r.text
        self.assertEqual(200,r.status_code);self.assertIn('a2-new-secondary',html);self.assertIn('admin_ui_mode=new',r.headers['set-cookie'])
        self.client.cookies.delete('admin_ui_mode')
        self.assertIn('id="sw-new"',html);self.assertIn('data-can-write="true"',html)
        self.assertNotIn('가온컴퍼니',html);self.assertNotIn('시안용',html);self.assertNotIn('가상 데이터',html)
        self.client.cookies.set(auth.COOKIE,'viewer');html=self.client.get('/admin2/suppliers').text
        self.assertNotIn('id="sw-new"',html);self.assertIn('data-can-write="false"',html)


if __name__=='__main__':unittest.main()
