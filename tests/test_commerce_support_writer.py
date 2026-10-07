"""Caller-TX/SQL and pure support regression; NOT native PostgreSQL evidence."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import unittest
from uuid import UUID

from api import commerce_contract as c
from api import commerce_owner as owner
from api import commerce_support_core as s
from api import commerce_support_writer as w

ROOT = Path(__file__).resolve().parents[1]
NO = 'support-fixture'
CONTEXT = str(UUID(int=900))
TOKEN = 'a' * 43
IDENTITY = dict(kind='guest', user_id=17, owner_hash='a' * 64)
SCOPE = c.fingerprint(IDENTITY)
ADMIN = dict(operator_id=21, role='operator', status='활성')


def command(action='create_inquiry', *, op=1, case=None, revision=0, body='문의 사실', reply=None):
    result = dict(operation_id=str(UUID(int=op)), action=action, case_id=case,
                  expected_revision=revision)
    result['reply_event_id' if action == 'publish_customer_reply' else 'body'] = (
        reply if action == 'publish_customer_reply' else body)
    return result


class Result:
    def __init__(self, rows=(), scalar=None, rowcount=1):
        self.rows, self.scalar, self.rowcount = deepcopy(list(rows)), scalar, rowcount
    def mappings(self): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None
    def scalar_one(self): return self.scalar


class Connection:
    """Limited statement dispatch; does not execute/emulate PostgreSQL triggers."""
    def __init__(self):
        self.txid, self.active, self.nested, self.options = 100, True, False, {}
        self.aborted, self.trace, self.fail_tag = False, [], None
        self.now, self.after_tag = 100, None
        self.context = dict(context_id=CONTEXT, owner_scope=SCOPE, owner_identity=IDENTITY,
                            credential_hash=owner.credential_digest(TOKEN), expires_at=1000,
                            revoked_at=None, created_at=1)
        self.data = dict(cases={}, events={}, order=dict(order_no=NO, order_id=10,
                         context_id=CONTEXT, owner_identity=deepcopy(IDENTITY), owner_scope=SCOPE,
                         order_write_txid=7))
        self.saved = deepcopy(self.data)
    def in_transaction(self): return self.active
    def in_nested_transaction(self): return self.nested
    def get_execution_options(self): return self.options
    def commit_simulation(self):
        if self.aborted: raise RuntimeError('aborted TX simulation')
        self.saved = deepcopy(self.data); self.txid += 1
    def rollback_simulation(self):
        self.data = deepcopy(self.saved); self.aborted = False; self.txid += 1
    def execute(self, statement, params=None):
        sql, p = str(statement), params or {}
        match = re.search(r'/\*(commerce_support|commerce_owner):(\w+)\*/', sql)
        if not match: raise AssertionError('non-support SQL')
        domain, tag = match.groups()
        self.trace.append((domain, tag, sql, deepcopy(p)))
        if tag == 'abort':
            self.aborted = True; raise RuntimeError('forced TX abort simulation')
        if self.aborted: raise RuntimeError('TX aborted')
        if tag == self.fail_tag: raise RuntimeError('private-fixture SQL failure')
        if self.after_tag: self.after_tag(tag)
        d = self.data
        if domain == 'commerce_owner':
            if tag == 'ready': return Result()
            if tag == 'clock': return Result(scalar=self.now)
            if tag == 'lookup': return Result([self.context] if p['credential_hash'] == self.context['credential_hash'] else [])
            raise AssertionError('unhandled owner SQL')
        if tag in ('operation_lock', 'readonly'): return Result()
        if tag == 'clock': return Result(scalar=self.now)
        if tag == 'txid': return Result(scalar=self.txid)
        if tag in ('scope', 'scope_lock'):
            row = d['order']
            match = row['order_no'] == p['no']
            if 'context' in p:
                match = match and row['context_id'] == p['context'] and row['owner_scope'] == p['scope'] and row['owner_identity'] == json.loads(p['identity'])
            return Result([row] if match else [])
        if tag == 'operation':
            row = d['events'].get(p['op']); return Result([row] if row else [])
        if tag in ('case', 'case_lock'):
            row = d['cases'].get(p['case'])
            valid = row and row['order_id'] == p['oid'] and ("origin='customer'" not in sql or row['origin'] == 'customer')
            return Result([row] if valid else [])
        if tag == 'insert_case':
            if p['case_id'] in d['cases']: raise RuntimeError('unique case')
            d['cases'][p['case_id']] = {k:deepcopy(p[k]) for k in w.CASE_COLUMNS.split(',')}; return Result()
        if tag == 'update_case':
            row = d['cases'][p['case_id']]
            if row['admin_revision'] != p['old_revision']: return Result(rowcount=0)
            row.update({k:deepcopy(p[k]) for k in ('state','admin_revision','public_revision','updated_at','public_updated_at','write_txid')})
            return Result()
        if tag == 'insert_event':
            if p['op'] in d['events']: raise RuntimeError('unique operation')
            d['events'][p['op']] = dict(event_id=p['event'], operation_id=p['op'], case_id=p['case'],
                order_id=p['oid'], owner_scope=p['scope'], actor=json.loads(p['actor']), action=p['action'],
                visible=p['visible'], body=p['body'], reply_event_id=p['reply'], request=json.loads(p['request']),
                request_hash=p['request_hash'], result=json.loads(p['result']), result_hash=p['result_hash'],
                admin_revision=p['admin_revision'], public_revision=p['public_revision'], recorded_at=p['now'],
                write_txid=p['txid'], commit_id=p['commit'])
            return Result()
        if tag in ('draft', 'case_proof'):
            rows = [x for x in d['events'].values() if x['order_id'] == p['oid'] and x['case_id'] == p['case']]
            if tag == 'draft': rows = [x for x in rows if x['event_id'] == p['event']]
            else:
                col = 'public_revision' if 'public_revision=:revision' in sql else 'admin_revision'
                rows = [x for x in rows if x[col] == p['revision'] and ('visible=true' not in sql or x['visible'])]
            return Result(rows)
        if tag == 'case_page':
            rows = sorted([x for x in d['cases'].values() if x['order_id'] == p['oid'] and
                          ("origin='customer'" not in sql or x['origin'] == 'customer')], key=lambda x:x['case_id'])
            upper = p['upper'] or (rows[-1]['case_id'] if rows else None)
            return Result([x | dict(upper_id=upper) for x in rows if x['case_id'] <= upper and
                          (p['after'] is None or x['case_id'] > p['after'])][:p['bound']])
        if tag == 'event_page':
            col = 'public_revision' if 'ORDER BY public_revision' in sql else 'admin_revision'
            rows = sorted([x for x in d['events'].values() if x['order_id'] == p['oid'] and x['case_id'] == p['case'] and
                ('visible=true' not in sql or x['visible']) and x[col] is not None and x[col] <= p['upper'] and
                (p['after'] is None or x[col] > p['after'])], key=lambda x:x[col])
            return Result(rows[:p['bound']])
        raise AssertionError('unhandled support SQL ' + tag)


def authorize(conn, audience='customer', principal=None):
    def grant(*, order_no, action, now):
        base = dict(audience=audience, order_no=order_no, checked_at=now,
                    permission='commerce.support.' + action, allowed=True)
        if audience == 'customer':
            ctx = owner.lookup_context(conn, TOKEN, expected_binding_id=CONTEXT, now=now)
            return base | dict(source='commerce_owner.lookup_context', context=ctx)
        return base | dict(source='api.auth.current_operator', principal=deepcopy(principal or ADMIN))
    return grant


class SupportWriterTests(unittest.TestCase):
    def setUp(self): self.conn = Connection()
    def apply(self, cmd, audience='customer', *, commit=True, grant=None):
        pending = w.apply(self.conn, NO, cmd, audience=audience, now=self.conn.now,
                          authorize=grant or authorize(self.conn, audience))
        if commit: self.conn.commit_simulation(); self.conn.now += 1
        return pending
    def create(self, op=1, audience='customer'):
        action = 'create_inquiry' if audience == 'customer' else 'record_external_contact'
        self.apply(command(action, op=op), audience)
        return self.conn.data['events'][str(UUID(int=op))]['case_id']
    def read(self, audience='customer', **kw):
        return w.read(self.conn, NO, audience=audience, now=self.conn.now,
                      authorize=authorize(self.conn, audience), **kw)
    def error(self, code, fn):
        with self.assertRaises(s.SupportError) as hit: fn()
        self.assertEqual(code, hit.exception.code)
    def test_create_is_pending_and_same_tx_read_cannot_confirm(self):
        pending = self.apply(command(), commit=False)
        self.assertEqual('pending_commit', pending['state'])
        self.error('support_record_unconfirmed', lambda:self.read(operation_id=command()['operation_id'],request_hash=pending['request_hash']))
        self.conn.commit_simulation()
        got = self.read(operation_id=command()['operation_id'],request_hash=pending['request_hash'])
        self.assertEqual('confirmed', got['state']); self.assertEqual('not_attempted',got['operation_result']['result']['delivery'])
    def test_exact_replay_preserves_uuid_case_commit_and_old_result_after_reopen(self):
        case = self.create(); close = command('close',op=2,case=case,revision=1,body='운영 종결 사유')
        receipt = self.apply(close,'admin')
        original = deepcopy(self.conn.data['events'][close['operation_id']])
        self.apply(command('reopen',op=3,case=case,revision=2,body='추가 질문'))
        before = deepcopy(self.conn.data)
        replay = self.apply(close,'admin')
        self.assertTrue(replay['replay']); self.assertEqual(before,self.conn.data)
        got = self.read('admin',operation_id=close['operation_id'],request_hash=receipt['request_hash'])
        self.assertEqual('closed',got['operation_result']['result']['state'])
        self.assertEqual('open',got['current_case']['state'])
        self.assertEqual(original,self.conn.data['events'][close['operation_id']])
    def test_duplicate_create_does_not_allocate_another_case(self):
        self.create(); before = deepcopy(self.conn.data)
        self.assertTrue(self.apply(command())['replay']); self.assertEqual(before,self.conn.data)
    def test_same_uuid_body_target_action_revision_or_actor_conflicts(self):
        case = self.create()
        changes = [command(body='changed'),command('append_customer_message',case=case,revision=1),
                   command(revision=1), command('record_external_contact')]
        for cmd in changes:
            with self.subTest(cmd=cmd):
                self.conn.rollback_simulation()
                self.error('support_operation_conflict' if cmd['expected_revision']==0 or cmd['case_id'] else 'support_revision_conflict',
                           lambda:self.apply(cmd,'admin' if cmd['action']=='record_external_contact' else 'customer'))
        self.conn.rollback_simulation()
        actor = dict(ADMIN,operator_id=22)
        ext = command('record_external_contact',op=2);self.apply(ext,'admin')
        self.error('support_operation_conflict',lambda:self.apply(ext,'admin',grant=authorize(self.conn,'admin',actor)))
    def test_new_uuid_stale_revision_fails_without_partial_update(self):
        case = self.create(); before = deepcopy(self.conn.data)
        self.error('support_revision_conflict',lambda:self.apply(command('append_customer_message',op=2,case=case,revision=0)))
        self.assertTrue(self.conn.aborted); self.conn.rollback_simulation(); self.assertEqual(before,self.conn.data)
    def test_closed_requires_explicit_reopen_and_note_cannot_close(self):
        case = self.create();self.apply(command('close',op=2,case=case,revision=1),'admin')
        self.error('support_state_conflict',lambda:self.apply(command('append_customer_message',op=3,case=case,revision=2)))
        self.conn.rollback_simulation()
        self.apply(command('internal_note',op=4,case=case,revision=2),'admin')
        self.assertEqual('closed',self.read()['cases'][0]['state'])
        self.apply(command('reopen',op=5,case=case,revision=2))
        self.assertEqual('open',self.read()['cases'][0]['state'])
    def test_internal_notes_and_drafts_do_not_leak_public_revision_time_or_body(self):
        case = self.create(); before = self.read()
        self.apply(command('internal_note',op=2,case=case,revision=1,body='PRIVATE internal'),'admin')
        self.apply(command('record_reply',op=3,case=case,revision=2,body='PRIVATE draft'),'admin')
        after = self.read(); before.pop('checked_at');after.pop('checked_at')
        self.assertEqual(before,after)
        self.assertEqual(1,len(self.read(case_id=case)['events']))
        self.assertEqual(3,len(self.read('admin',case_id=case)['events']))
        text = json.dumps(self.read(case_id=case),ensure_ascii=False)
        for forbidden in ('PRIVATE','owner_scope','operator_id','admin_revision','reply_event_id'):
            self.assertNotIn(forbidden,text)
    def test_customer_cas_uses_public_revision_even_after_private_notes(self):
        case = self.create();self.apply(command('internal_note',op=2,case=case,revision=1),'admin')
        self.apply(command('append_customer_message',op=3,case=case,revision=1))
        row = self.conn.data['cases'][case]
        self.assertEqual((3,2),(row['admin_revision'],row['public_revision']))
    def test_explicit_publication_requires_exact_same_case_committed_reply_draft(self):
        case = self.create();self.apply(command('record_reply',op=2,case=case,revision=1,body='게시할 답변'),'admin')
        draft = self.conn.data['events'][str(UUID(int=2))]
        self.apply(command('publish_customer_reply',op=3,case=case,revision=2,reply=draft['event_id']),'admin')
        events = self.read(case_id=case)['events']
        self.assertEqual(['create_inquiry','publish_customer_reply'],[e['action'] for e in events])
        self.assertEqual('게시할 답변',events[-1]['body']);self.assertFalse(draft['visible'])
    def test_internal_note_cannot_be_published_and_wrong_case_draft_not_found(self):
        case = self.create();self.apply(command('internal_note',op=2,case=case,revision=1),'admin')
        note = self.conn.data['events'][str(UUID(int=2))]
        self.error('support_publication_forbidden',lambda:self.apply(command('publish_customer_reply',op=3,case=case,revision=2,reply=note['event_id']),'admin'))
        self.conn.rollback_simulation();other=self.create(op=4)
        self.apply(command('record_reply',op=5,case=other,revision=1),'admin')
        draft = self.conn.data['events'][str(UUID(int=5))]
        self.error('support_reply_not_found',lambda:self.apply(command('publish_customer_reply',op=6,case=case,revision=2,reply=draft['event_id']),'admin'))
    def test_external_case_entirely_private_and_cannot_be_published(self):
        case = self.create(audience='admin');self.assertEqual([],self.read()['cases'])
        self.error('support_case_not_found',lambda:self.read(case_id=case))
        self.apply(command('record_reply',op=2,case=case,revision=1),'admin')
        draft = self.conn.data['events'][str(UUID(int=2))]
        self.error('support_publication_forbidden',lambda:self.apply(command('publish_customer_reply',op=3,case=case,revision=2,reply=draft['event_id']),'admin'))
    def test_scope_precedes_support_body_and_operation_lookup_for_foreign_or_missing(self):
        case = self.create()
        for change in ('foreign','missing'):
            with self.subTest(change=change):
                self.conn.rollback_simulation();self.conn.trace.clear()
                self.conn.data['order']['context_id'] = str(UUID(int=901)) if change=='foreign' else CONTEXT
                if change=='missing':self.conn.data['order']['order_no']='missing'
                self.error('order_not_found',lambda:self.read(operation_id=command()['operation_id'],request_hash='a'*64))
                self.assertFalse(any(x[1] in ('operation','case','case_page','event_page') for x in self.conn.trace))
    def test_actual_owner_lookup_rejects_expired_revoked_changed_binding_and_member(self):
        for key,value,code in [('expires_at',100,'owner_context_lost'),('revoked_at',1,'owner_context_lost'),
                                ('context_id',str(UUID(int=902)),'owner_context_changed')]:
            with self.subTest(key=key):
                conn=Connection();conn.context[key]=value
                with self.assertRaises(owner.OwnerError) as hit: w.read(conn,NO,audience='customer',now=100,authorize=authorize(conn))
                self.assertEqual(code,hit.exception.code)
        conn=Connection();member=dict(kind='member',member_id=18,auth_subject='verified-shape-only')
        conn.context.update(owner_identity=member,owner_scope=c.fingerprint(member))
        with self.assertRaises(owner.OwnerError) as hit:
            w.read(conn,NO,audience='customer',now=100,authorize=authorize(conn))
        self.assertEqual('verified_member_adapter_unready',hit.exception.code)
        self.assertFalse(any(x[1]=='scope' for x in conn.trace))
    def test_viewer_and_native_principal_types_reject_write_before_scope(self):
        for principal in [dict(ADMIN,role='viewer'),dict(ADMIN,operator_id=True),dict(ADMIN,operator_id='21'),dict(ADMIN,status='정지')]:
            with self.subTest(principal=principal):
                conn=Connection()
                with self.assertRaises(s.SupportError) as hit:
                    w.apply(conn,NO,command('record_external_contact'),audience='admin',now=100,authorize=authorize(conn,'admin',principal))
                self.assertEqual(403,hit.exception.status);self.assertFalse(any(x[1]=='scope' for x in conn.trace))
    def test_read_grant_cannot_authorize_writes_or_swap_actor_mid_operation(self):
        valid=authorize(self.conn,'admin')
        def read_only(**kw): return valid(**kw) | dict(permission='commerce.order.read')
        self.error('support_authorization_required',lambda:self.apply(command('record_external_contact'),'admin',grant=read_only))
        self.conn.rollback_simulation();count=0
        def swapped(**kw):
            nonlocal count
            count+=1
            return valid(**kw) if count==1 else valid(**kw) | dict(principal=dict(ADMIN,operator_id=22))
        self.error('support_authorization_changed',lambda:self.apply(command('record_external_contact'),'admin',grant=swapped))
        self.conn.rollback_simulation();self.assertEqual({},self.conn.data['cases'])
    def test_caller_transaction_nested_autocommit_and_txid_switch_fail_closed(self):
        for attribute,value in [('active',False),('nested',True),('options',{'isolation_level':'AUTOCOMMIT'})]:
            with self.subTest(attribute=attribute):
                conn=Connection();setattr(conn,attribute,value)
                with self.assertRaises(s.SupportError):w.apply(conn,NO,command(),audience='customer',now=100,authorize=authorize(conn))
                self.assertEqual([],conn.trace)
        calls=0
        def change(tag):
            nonlocal calls
            if tag=='txid':
                calls+=1
                if calls==2:self.conn.txid+=1
        self.conn.after_tag=change
        self.error('support_transaction_changed',lambda:self.apply(command()))
        self.assertTrue(self.conn.aborted)
    def test_failed_event_insert_aborts_case_write_and_requires_whole_rollback(self):
        before=deepcopy(self.conn.data);self.conn.fail_tag='insert_event'
        self.error('support_store_unavailable',lambda:self.apply(command()))
        self.assertTrue(self.conn.aborted)
        with self.assertRaises(RuntimeError):self.conn.commit_simulation()
        self.conn.rollback_simulation();self.assertEqual(before,self.conn.data)
    def test_rowcount_cas_race_after_locked_read_aborts_whole_transaction(self):
        case=self.create();before=deepcopy(self.conn.data)
        def race(tag):
            if tag=='update_case':self.conn.data['cases'][case]['admin_revision']+=1
        self.conn.after_tag=race
        self.error('support_revision_conflict',lambda:self.apply(command('append_customer_message',op=2,case=case,revision=1)))
        self.assertTrue(self.conn.aborted);self.conn.rollback_simulation();self.assertEqual(before,self.conn.data)
    def test_uncommitted_reply_draft_cannot_publish_in_same_caller_tx(self):
        case=self.create();self.apply(command('record_reply',op=2,case=case,revision=1),'admin',commit=False)
        draft=self.conn.data['events'][str(UUID(int=2))]
        self.error('support_record_unconfirmed',lambda:self.apply(command('publish_customer_reply',op=3,case=case,revision=2,reply=draft['event_id']),'admin'))
        self.conn.rollback_simulation();self.assertEqual(1,len(self.conn.data['events']))
    def test_forged_grant_source_clock_allowed_and_order_are_rejected(self):
        valid=authorize(self.conn,'admin')
        for changes in [dict(source='browser'),dict(checked_at=True),dict(allowed=1),dict(order_no='other'),dict(audience='customer')]:
            with self.subTest(changes=changes):
                self.conn.rollback_simulation()
                self.error('support_authorization_required',lambda:self.apply(command('record_external_contact'),'admin',grant=lambda **kw:valid(**kw)|changes))
    def test_operation_recovery_requires_current_action_permission_after_role_downgrade(self):
        self.create(audience='admin');record=next(iter(self.conn.data['events'].values()))
        with self.assertRaises(s.SupportError) as hit:
            w.read(self.conn,NO,audience='admin',now=self.conn.now,authorize=authorize(self.conn,'admin',dict(ADMIN,role='viewer')),
                   operation_id=record['operation_id'],request_hash=record['request_hash'])
        self.assertEqual(403,hit.exception.status)
    def test_corrupt_case_native_scope_revisions_and_public_timestamp_fail_closed(self):
        case=self.create();original=deepcopy(self.conn.data)
        for key,value in [('owner_scope','b'*64),('admin_revision',True),('public_revision',None),
                          ('public_updated_at',0),('write_txid','7'),('origin','internal')]:
            with self.subTest(key=key):
                self.conn.data=deepcopy(original);self.conn.data['cases'][case][key]=value
                # Admin sees all origins; customer correctly filters private origins.
                self.error('support_record_unavailable',lambda:self.read('admin'))
    def test_native_original_order_identity_and_txid_fail_before_support_reads(self):
        for key,value in [('order_id',True),('order_id','10'),('owner_scope','b'*64),('order_write_txid','7')]:
            with self.subTest(key=key):
                conn=Connection();conn.data['order'][key]=value
                with self.assertRaises(s.SupportError) as hit:
                    w.read(conn,NO,audience='admin',now=100,authorize=authorize(conn,'admin'))
                self.assertEqual('support_order_unavailable',hit.exception.code)
                self.assertFalse(any(x[1]=='case_page' for x in conn.trace))
    def test_corrupted_native_event_identity_hash_body_or_result_is_unavailable(self):
        self.create();original=deepcopy(self.conn.data)
        for field,value in [('write_txid','100'),('visible',1),('body','changed'),('request_hash','b'*64),
                            ('admin_revision',True),('result_hash','c'*64),('order_id',11)]:
            with self.subTest(field=field):
                self.conn.data=deepcopy(original);self.conn.data['events'][command()['operation_id']][field]=value
                self.error('support_record_unavailable',lambda:self.read(case_id=next(iter(self.conn.data['cases']))))
    def test_missing_or_mismatched_current_case_event_proof_not_empty_success(self):
        case=self.create();self.conn.data['cases'][case]['state']='closed'
        self.error('support_record_unavailable',lambda:self.read())
        self.conn.data['cases'][case]['state']='open';self.conn.data['events'].clear()
        self.error('support_record_unavailable',lambda:self.read())
    def test_operation_not_found_is_absence_not_declined_and_hash_mismatch_conflict(self):
        self.create()
        self.error('support_operation_not_found',lambda:self.read(operation_id=str(UUID(int=99)),request_hash='a'*64))
        self.error('support_operation_conflict',lambda:self.read(operation_id=command()['operation_id'],request_hash='b'*64))
    def test_cases_and_events_pages_are_bounded_ordered_and_cursors_scope_bound(self):
        for i in range(1,5):self.create(op=i)
        first=self.read(limit=2);second=self.read(limit=2,cursor=first['next_cursor'])
        ids=[r['case_id'] for r in first['cases']+second['cases']]
        self.assertEqual(sorted(self.conn.data['cases']),ids);self.assertIsNone(second['next_cursor'])
        self.error('invalid_support_cursor',lambda:self.read('admin',cursor=first['next_cursor']))
        case=ids[0]
        for i in range(5,8):self.apply(command('append_customer_message',op=i,case=case,revision=i-4))
        first=self.read(case_id=case,limit=2);second=self.read(case_id=case,limit=2,cursor=first['next_cursor'])
        self.assertEqual([1,2,3,4],[e['revision'] for e in first['events']+second['events']])
        self.error('invalid_support_cursor',lambda:self.read(case_id=ids[1],cursor=first['next_cursor']))
    def test_page_insertion_is_not_claimed_as_global_snapshot_and_never_duplicates(self):
        for i in range(1,4):self.create(op=i)
        first=self.read(limit=1);self.create(op=4)
        second=self.read(limit=50,cursor=first['next_cursor'])
        all_ids=[r['case_id'] for r in first['cases']+second['cases']]
        self.assertEqual(len(all_ids),len(set(all_ids)))
    def test_limits_modes_and_cursor_noncanonical_values_reject(self):
        for kw in [dict(limit=True),dict(limit=51),dict(case_id=str(UUID(int=1)),operation_id=str(UUID(int=2))),
                   dict(cursor='bad='),dict(request_hash='a'*64),dict(operation_id=str(UUID(int=2)))]:
            with self.subTest(kw=kw):
                with self.assertRaises(s.SupportError):self.read(**kw)
    def test_plain_text_unknown_fields_and_client_claims_are_rejected(self):
        for body in ['', '  ','<script>bad</script>','bad\x00text','a'*(s.MAX_BODY+1)]:
            with self.subTest(body=body[:20]):self.error('invalid_support_body',lambda:s.command(command(body=body),'customer'))
        for key in ('role','actor','email','visible','delivered','owner_scope','occurred_at'):
            with self.subTest(key=key):self.error('invalid_support_request',lambda:s.command(command() | {key:'client'},'customer'))
    def test_sql_writes_are_plain_support_only_and_new_namespace_is_distinct(self):
        case=self.create();self.apply(command('internal_note',op=2,case=case,revision=1),'admin')
        writes=[sql for _,_,sql,_ in self.conn.trace if re.match(r'/\*[^*]+\*/\s*(INSERT|UPDATE|DELETE)\b',sql)]
        self.assertTrue(writes)
        for sql in writes:
            self.assertRegex(sql,r'(INSERT INTO|UPDATE) commerce_support_(cases|events)')
            self.assertNotIn('ON CONFLICT',sql);self.assertNotIn('SAVEPOINT',sql)
        source=(ROOT/'api/commerce_support_writer.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        forbidden={'commit','rollback','begin','begin_nested','notify_harness','lock_products'}
        self.assertFalse(any(isinstance(n,ast.Call) and ((isinstance(n.func,ast.Attribute) and n.func.attr in forbidden) or
                         (isinstance(n.func,ast.Name) and n.func.id in forbidden)) for n in ast.walk(tree)))
        self.assertNotIn(w.OPERATION_NAMESPACE,(1347375171,1347375186))
        lock=next(x for x in self.conn.trace if x[1]=='operation_lock')
        self.assertEqual(w.OPERATION_NAMESPACE,lock[3]['namespace'])
    def test_migration_source_has_two_tables_scoped_fks_checks_immutability_and_no_apply(self):
        path=ROOT/'db/migrations/versions/0128_commerce_support.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        constants={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                   and isinstance(n.targets[0],ast.Name) and isinstance(n.value,(ast.Constant,ast.Tuple))}
        self.assertEqual(('0128','0127'),(constants['revision'],constants['down_revision']))
        sql=constants['UPGRADE_SQL'];self.assertEqual(2,len(re.findall(r'CREATE TABLE',sql)))
        for required in ('REFERENCES __S__.commerce_order_details(order_id)','FOREIGN KEY(order_id,case_id,reply_event_id)',
                         'BEFORE INSERT OR UPDATE OR DELETE','DEFERRABLE INITIALLY DEFERRED','Support events are immutable',
                         'Support cases are preserved','commerce_support_public_sequence','IS NOT DISTINCT FROM',"delivery' IS NOT DISTINCT FROM 'not_attempted'"):
            self.assertIn(required,sql)
        self.assertNotRegex(sql,r'\b(ALTER|INSERT INTO|UPDATE|DELETE FROM) __S__\.(orders|products|payments|commerce_payment_operations|commerce_shipments)\b')
        self.assertFalse(any(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) for n in tree.body))


if __name__ == '__main__':
    unittest.main()
