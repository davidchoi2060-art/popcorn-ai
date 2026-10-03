"""Isolated SQLite fixture executes the query logic; no production DB import.

Only PostgreSQL syntax is adapted (ILIKE, TIMESTAMP, JSONB, FOR UPDATE, ::int).
SQLite serializes fixture transactions; actual PostgreSQL lock behavior requires
integration verification. Never import api.main or create a production engine.
"""
import contextlib
import datetime as dt
import json
import re
import sqlite3
import sys
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch


class NeverConnect:
    def connect(self): raise AssertionError('Unpatched DB access')
    def begin(self): raise AssertionError('Unpatched DB access')


if 'api.db' not in sys.modules:
    db_stub = types.ModuleType('api.db')
    db_stub.engine = NeverConnect()
    sys.modules['api.db'] = db_stub

from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import admin_members as members
from api import auth


class Result:
    def __init__(self, cursor):
        self.keys = [d[0] for d in cursor.description] if cursor.description else []
        self.rows = cursor.fetchall() if cursor.description else []
    def mappings(self): return self
    def _map(self, row):
        out = dict(zip(self.keys, row))
        for key, value in list(out.items()):
            if key == 'detail' and value is not None:
                out[key] = json.loads(value)
            elif value and (key.endswith('_at') or key.endswith('_last')):
                out[key] = dt.datetime.fromisoformat(value)
        return out
    def all(self): return [self._map(row) for row in self.rows] if getattr(self, 'as_map', False) else self.rows
    def first(self): return self._map(self.rows[0]) if self.rows and getattr(self, 'as_map', False) else (self.rows[0] if self.rows else None)
    def scalar(self):
        if not self.rows: return None
        return self._map(self.rows[0])[self.keys[0]]
    def scalar_one(self):
        if len(self.rows) != 1: raise AssertionError('Expected one row')
        return self.scalar()


# SQLAlchemy .mappings() controls row shape without replacing the SQL semantics.
def mappings(self): self.as_map = True; return self
Result.mappings = mappings


class Fixture:
    def __init__(self):
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        self.lock = threading.RLock(); self.calls = []; self.isolation = None
        self.clock = dt.datetime(2026, 10, 3, 5)
        self.db.create_function('now', 0, self.now)
        self.db.create_function('GREATEST', -1, lambda *args: max((v for v in args if v is not None), default=None))
        self.db.executescript('''
          CREATE TABLE members(member_id INTEGER PRIMARY KEY,nickname TEXT,email TEXT,joined_via TEXT,created_at TEXT,
            mall_member_id TEXT,mall_map_requested_at TEXT,status TEXT,last_login_at TEXT,user_id INTEGER,
            data_origin TEXT DEFAULT 'real');
          CREATE TABLE orders(member_id INTEGER,created_at TEXT,status TEXT);
          CREATE TABLE consult_sessions(member_id INTEGER,created_at TEXT,data_origin TEXT,user_id INTEGER);
          CREATE TABLE member_reviews(member_id INTEGER,created_at TEXT,status TEXT);
          CREATE TABLE member_favorites(member_id INTEGER,created_at TEXT,price_alert INTEGER);
          CREATE TABLE ops_settings(key TEXT,mode TEXT);
          INSERT INTO ops_settings VALUES('member','own');
          CREATE TABLE admin_operator_activity_logs(log_id INTEGER PRIMARY KEY AUTOINCREMENT,operator_id INTEGER,
            action TEXT,target_kind TEXT,target_id TEXT,detail TEXT);
        ''')
        for i in range(1, 13):
            self.db.execute('INSERT INTO members(member_id,nickname,email,joined_via,created_at,mall_member_id,mall_map_requested_at,status,last_login_at,user_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (i, f'회원{i}', f'member-{i}@example.invalid', ['email','google','kakao','naver'][i%4],
                             '2026-09-01 01:00:00', None, None, 'active', None, 100+i))
        self.db.commit()
    def now(self):
        self.clock += dt.timedelta(microseconds=1)
        return self.clock.isoformat(sep=' ')
    def execute(self, statement, params=None):
        sql = str(statement); self.calls.append((sql, dict(params or {})))
        sql = sql.replace(' ILIKE ', ' LIKE ').replace(' FOR UPDATE', '')
        sql = re.sub(r"TIMESTAMP ('[^']+')", r'\1', sql)
        sql = sql.replace('CAST(:d AS JSONB)', ':d').replace("(detail->>'ref_log_id')::int", "CAST(detail->>'ref_log_id' AS INTEGER)")
        return Result(self.db.execute(sql, params or {}))
    def execution_options(self, **kwargs): self.isolation = kwargs; return self
    def connect(self): return self
    def __enter__(self): self.lock.acquire(); return self
    def __exit__(self, *args): self.lock.release()
    @contextlib.contextmanager
    def begin(self):
        with self.lock:
            try:
                self.db.execute('BEGIN'); yield self; self.db.commit()
            except BaseException:
                self.db.rollback(); raise
    def edit(self, sql, args=()): self.db.execute(sql,args); self.db.commit()


class MemberTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.patch = patch.object(members, 'engine', self.fixture); self.patch.start()
    def tearDown(self): self.patch.stop(); self.fixture.db.close()
    def test_legacy_keys_types_order_and_new_page_equivalence(self):
        old = members.list_members(); new = members.search_members(sort='id_asc',page_size=20)
        self.assertEqual(set(old), {'items','member_mode','unmapped_via'})
        keys={'id','name','email','via','joined','map_state','mall_id','requested_at','orders','consults','reviews','favs','alerts','last','note'}
        self.assertEqual([m['id'] for m in old['items']], list(range(1,13)))
        for a,b in zip(old['items'],new['items']):
            self.assertEqual(set(a),keys); self.assertEqual(a,{k:b[k] for k in keys})
            self.assertIsInstance(a['orders'],int);self.assertIsNone(a['last'])
    def test_search_literal_wildcards_quotes_and_numeric_id(self):
        self.fixture.edit("UPDATE members SET nickname=?,email=? WHERE member_id=1",('정상 %_\\ 이름',"o'hara@example.invalid"))
        for q in ['%','_','\\',"o'hara",'1']:
            result=members.search_members(q=q)
            self.assertEqual([m['id'] for m in result['items']],[1],q)
        self.assertEqual(members.search_members(q="%' OR TRUE--")['total'],0)
        self.assertEqual(members.search_members(q='不存在')['total'],0)
        self.assertEqual(members.search_members(q='9'*100)['total'],0)
        self.assertTrue(all('OR TRUE--' not in sql for sql,_ in self.fixture.calls))

    def test_origin_is_raw_read_only_extended_fact_not_legacy_classification(self):
        origins = ['real', 'demo', None, '<origin & legacy>']
        legacy_before = members.list_members()
        for member_id, origin in enumerate(origins, 1):
            self.fixture.edit('UPDATE members SET data_origin=? WHERE member_id=?', (origin, member_id))
        self.assertEqual(members.list_members(), legacy_before)
        page = members.search_members(sort='id_asc')
        self.assertEqual(page['total'], 12)
        for member_id, origin in enumerate(origins, 1):
            self.assertEqual(page['items'][member_id-1]['data_origin'], origin)
            detail = members.member_detail(member_id)
            self.assertEqual(detail['member']['data_origin'], origin)
            self.assertEqual(detail['member']['status'], 'active')
            self.assertEqual(detail['member']['map_state'], 'none')
        self.assertNotIn('data_origin', page['available_filters'])
    def test_pages_stable_ties_and_out_of_range(self):
        a=members.search_members(page_size=10);b=members.search_members(page=2,page_size=10)
        self.assertEqual([m['id'] for m in a['items']],[12,11,10,9,8,7,6,5,4,3])
        self.assertEqual([m['id'] for m in b['items']],[2,1]);self.assertEqual(b['total'],12)
        self.assertEqual(members.search_members(page=9)['items'],[])
        self.assertEqual(self.fixture.isolation,{'isolation_level':'REPEATABLE READ'})
    def test_mapping_precedence_unknown_filters_and_global_metadata(self):
        self.fixture.edit("UPDATE members SET mall_member_id='MALL-2301',mall_map_requested_at='2026-10-02 00:00:00',joined_via='apple' WHERE member_id=1")
        self.fixture.edit("UPDATE members SET mall_map_requested_at='2026-10-02 00:00:00',status='suspended' WHERE member_id=2")
        self.assertEqual(members.search_members(map_state='mapped')['total'],1)
        self.assertEqual([m['id'] for m in members.search_members(map_state='requested')['items']],[2])
        self.assertEqual(members.search_members(map_state='none')['total'],10)
        r=members.search_members(via='google');self.assertIn('apple',r['unmapped_via'])
        self.assertIn('suspended',r['available_filters']['status'])
        self.assertEqual(members.search_members(status='suspended')['total'],1)
    def test_activity_populations_and_login_separate(self):
        for args in [(1,'2026-08-19 15:57:45','real',101),(1,'2026-10-01 00:00:00','demo',101),
                     (None,'2026-10-01 00:00:00','real',101),(1,'2026-10-02 00:00:00','real',999)]:
            self.fixture.edit('INSERT INTO consult_sessions VALUES(?,?,?,?)',args)
        self.fixture.edit("INSERT INTO orders VALUES(1,'2026-10-02 01:00:00','취소')")
        self.fixture.edit("INSERT INTO member_reviews VALUES(1,'2026-10-02 02:00:00','숨김')")
        self.fixture.edit("INSERT INTO member_favorites VALUES(1,'2026-10-02 03:00:00',1)")
        self.fixture.edit("UPDATE members SET last_login_at='2026-10-03 00:00:00' WHERE member_id=1")
        m=members.member_detail(1)['member']
        self.assertEqual((m['orders'],m['consults'],m['reviews'],m['favs'],m['alerts']),(1,1,1,1,1))
        self.assertEqual(m['last'],'2026-10-02T03:00:00+00:00');self.assertNotEqual(m['last'],m['last_login_at'])
        self.assertEqual(members.search_members(sort='activity_desc')['items'][0]['id'],1)
        self.assertNotIn('user_id',m);self.assertTrue(m['visitor_linked'])
    def test_request_undo_preserve_bodyless_contract(self):
        r=members.map_request(1);self.assertEqual(r['ok'],True);self.assertEqual(r['member_mode'],'own')
        log=self.fixture.execute('SELECT detail FROM admin_operator_activity_logs').mappings().first()['detail']
        self.assertEqual(log['after']['mall_map_requested_at'],r['requested_at'])
        self.assertEqual(members.undo_map_request(r['undo_id']),{'ok':True})
        with self.assertRaises(Exception) as e:members.undo_map_request(r['undo_id'])
        self.assertEqual(e.exception.status_code,409)
    def test_request_guards_and_no_partial_write_if_logger_fails(self):
        with self.assertRaises(Exception) as e:members.map_request(999)
        self.assertEqual(e.exception.status_code,404)
        self.fixture.edit("UPDATE members SET mall_member_id='EXTERNAL' WHERE member_id=1")
        with self.assertRaises(Exception) as e:members.map_request(1)
        self.assertEqual(e.exception.status_code,409)
        with patch.object(members,'_log',side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):members.map_request(2)
        self.assertIsNone(members.member_detail(2)['member']['requested_at'])
    def test_stale_generation_undo_after_refusal_and_new_request(self):
        a=members.map_request(1)
        self.fixture.edit('UPDATE members SET mall_map_requested_at=NULL WHERE member_id=1')
        b=members.map_request(1)
        with self.assertRaises(Exception) as e:members.undo_map_request(a['undo_id'])
        self.assertEqual(e.exception.status_code,409)
        self.assertEqual(members.member_detail(1)['member']['requested_at'],b['requested_at'])
        members.undo_map_request(b['undo_id'])
    def test_timestamp_changed_or_consent_blocks_undo(self):
        a=members.map_request(1)
        self.fixture.edit("UPDATE members SET mall_map_requested_at='2026-10-02 00:00:00' WHERE member_id=1")
        with self.assertRaises(Exception) as e:members.undo_map_request(a['undo_id'])
        self.assertEqual(e.exception.status_code,409)
        self.fixture.edit("UPDATE members SET mall_member_id='MALL-2201' WHERE member_id=1")
        with self.assertRaises(Exception) as e:members.undo_map_request(a['undo_id'])
        self.assertEqual(e.exception.status_code,409)
    def test_legacy_log_latest_identity_guard(self):
        a=members.map_request(1)
        self.fixture.edit('UPDATE admin_operator_activity_logs SET detail=? WHERE log_id=?',(json.dumps({'member_id':1,'before':{'mall_map_requested_at':None}}),a['undo_id']))
        members.undo_map_request(a['undo_id'])
        b=members.map_request(1)
        self.fixture.edit('UPDATE admin_operator_activity_logs SET detail=? WHERE log_id=?',(json.dumps({'member_id':1}),b['undo_id']))
        self.fixture.edit('UPDATE members SET mall_map_requested_at=NULL WHERE member_id=1')
        c=members.map_request(1)
        with self.assertRaises(Exception) as e:members.undo_map_request(b['undo_id'])
        self.assertEqual(e.exception.status_code,409)
        self.assertEqual(members.member_detail(1)['member']['requested_at'],c['requested_at'])
    def test_undo_logger_failure_restores_request_and_keeps_original_log(self):
        a=members.map_request(1)
        with patch.object(members,'_log',side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):members.undo_map_request(a['undo_id'])
        self.assertEqual(members.member_detail(1)['member']['requested_at'],a['requested_at'])
        self.assertEqual(self.fixture.execute('SELECT COUNT(*) FROM admin_operator_activity_logs').scalar(),1)
    def test_serialized_fixture_duplicate_requests_only_one_success(self):
        def attempt():
            try: members.map_request(1);return 200
            except Exception as e:return e.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(sorted(codes),[200,409])


class MemberHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fixture=Fixture();self.patch=patch.object(members,'engine',self.fixture);self.patch.start()
        app=FastAPI();app.include_router(members.router);app.middleware('http')(auth.auth_middleware)
        self.client=TestClient(app)
        self.authPatch=patch.object(auth,'resolve_session',side_effect=lambda cookie:None if cookie=='none' or not cookie else {'operator_id':7,'name':'fixture','role':cookie,'status':'활성'})
        self.authPatch.start()
    def tearDown(self):self.client.close();self.authPatch.stop();self.patch.stop();self.fixture.db.close()
    def call(self,method,path,role='viewer'):
        return self.client.request(method,path,headers={'cookie':f'{auth.COOKIE}={role}'})
    def test_auth_401_403_blocks_before_database(self):
        self.assertEqual(self.call('GET','/api/admin/members/search','none').status_code,401)
        self.assertEqual(self.call('POST','/api/admin/members/1/map-request').status_code,403)
        self.assertEqual(self.fixture.calls,[])
    def test_read_and_write_roles_and_log_actor(self):
        for role in ['viewer','operator','owner']:
            self.assertEqual(self.call('GET','/api/admin/members/search',role).status_code,200)
        r=self.call('POST','/api/admin/members/1/map-request','operator');self.assertEqual(r.status_code,200)
        self.assertEqual(self.fixture.execute('SELECT operator_id FROM admin_operator_activity_logs').scalar(),7)
        self.assertEqual(self.call('POST',f"/api/admin/members/map-request/undo/{r.json()['undo_id']}",'owner').status_code,200)
    def test_route_order_validation_detail_not_found(self):
        for query in ['page=0','page=-1','page_size=11','sort=drop','map_state=invalid','q='+'x'*101]:
            self.assertEqual(self.call('GET','/api/admin/members/search?'+query).status_code,422,query)
        self.assertEqual(self.call('GET','/api/admin/members/0').status_code,422)
        self.assertEqual(self.call('GET','/api/admin/members/999').status_code,404)
        self.assertEqual(self.call('GET','/api/admin/members/1').status_code,200)
        self.assertEqual(self.call('GET','/api/admin/members/search').status_code,200)
        for size in (10,20,50):
            r=self.call('GET',f'/api/admin/members/search?page_size={size}')
            self.assertEqual(r.status_code,200);self.assertEqual(r.json()['page_size'],size)


if __name__=='__main__':unittest.main()
