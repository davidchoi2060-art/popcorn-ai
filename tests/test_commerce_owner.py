"""Caller-connection ownership checks; fixtures do not prove PostgreSQL/auth E2E."""
import ast
import base64
from copy import deepcopy
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from api import commerce_contract as c
from api import commerce_owner as o

TOKEN = 'A' * 43
BINDING = '577fbb7b-524c-487a-9192-e266272532cb'
OTHER = '387cd4da-bb96-482e-b323-79503361a9f2'
CONFIG = dict(COMMERCE_OWNER_ENABLED='1', COMMERCE_OWNER_SECURE='1',
              COMMERCE_OWNER_TTL_SECONDS='600', COMMERCE_OWNER_ORIGIN='https://shop.example')


def policy():
    return o.OwnerPolicy.from_mapping(CONFIG)


def row(token=TOKEN, **changes):
    identity = dict(kind='guest', user_id=11, owner_hash='b' * 64)
    value = dict(context_id=BINDING, owner_scope=c.fingerprint(identity), owner_identity=identity,
                 credential_hash=o.credential_digest(token), expires_at=1600, created_at=1000,
                 revoked_at=None)
    value.update(changes)
    return value


class Result:
    def __init__(self, value=None): self.value = deepcopy(value)
    def mappings(self): return self
    def first(self): return self.value
    def scalar_one(self): return self.value


class Connection:
    """Small call simulator, no SQL parser or live connection."""
    def __init__(self, data=None, trace=None, readonly=False):
        self.data = data if data is not None else dict(users=[], contexts={}, now=1000)
        self.trace = trace if trace is not None else []
        self.readonly, self.active, self.fail_tag = readonly, True, None

    def in_transaction(self): return self.active
    def rollback(self):
        self.trace.append(('rollback_read', {})); self.active = False

    def execute(self, statement, params):
        sql = str(statement)
        found = re.search(r'/\*commerce_owner:(\w+)\*/', sql)
        if not found: raise AssertionError('unexpected SQL namespace')
        tag = found[1]
        self.trace.append((tag, deepcopy(params)))
        if tag == self.fail_tag:
            raise RuntimeError('fixture-private-sql-token')
        if tag == 'ready': return Result()
        if tag == 'clock': return Result(self.data['now'])
        if tag == 'lookup': return Result(self.data['contexts'].get(params['credential_hash']))
        if self.readonly: raise AssertionError('GET attempted a write')
        if tag == 'insert_user':
            uid = max(self.data['users'], default=0) + 1
            self.data['users'].append(uid)
            return Result(uid)
        if tag == 'insert_context':
            if params['credential_hash'] in self.data['contexts']:
                raise RuntimeError('fixture-unique-hash-collision')
            value = deepcopy(params)
            value['owner_identity'] = json.loads(value['owner_identity'])
            value['revoked_at'] = None
            self.data['contexts'][value['credential_hash']] = value
            return Result()
        raise AssertionError('unexpected SQL operation')


class OwnerTests(unittest.TestCase):
    def assert_error(self, code, fn, *args, **kwargs):
        with self.assertRaises(o.OwnerError) as caught:
            fn(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(TOKEN, str(caught.exception))

    def connection(self, value=None):
        conn = Connection()
        if value is not None:
            conn.data['contexts'][value['credential_hash']] = value
        return conn

    def lookup(self, conn, token=TOKEN, expected=BINDING, now=1000):
        return o.lookup_context(conn, token, expected_binding_id=expected, now=now)

    def test_explicit_policy_has_no_default_and_is_immutable(self):
        p = policy()
        self.assertEqual(p.ttl_seconds, 600)
        self.assertEqual(p.origin, 'https://shop.example')
        with self.assertRaises(AttributeError): p.secure = False

    def test_every_missing_config_field_fails_closed(self):
        for key in CONFIG:
            with self.subTest(key=key):
                values = dict(CONFIG); values.pop(key)
                self.assert_error('owner_configuration_unready', o.OwnerPolicy.from_mapping, values)

    def test_invalid_enable_secure_ttl_and_origin_fail_closed(self):
        for key, values in (
            ('COMMERCE_OWNER_ENABLED', [None, '0', 'yes', True]),
            ('COMMERCE_OWNER_SECURE', [None, 'false', 'yes', True]),
            ('COMMERCE_OWNER_TTL_SECONDS', [None, '', '0', '-1', '1.5', '01', ' 600',
                                            True, '9223372036854775808']),
            ('COMMERCE_OWNER_ORIGIN', [None, 'http://shop.example', 'https://shop.example/',
                                     'https://user@shop.example', 'https://shop.example?x=1',
                                     'https://shop.example#x', 'https://shop.example:0',
                                     'https://SHOP.example', 'https://shop.example:bad'])):
            for value in values:
                with self.subTest(key=key, value=value):
                    config = dict(CONFIG); config[key] = value
                    self.assert_error('owner_configuration_unready', o.OwnerPolicy.from_mapping, config)

    def test_digest_is_domain_separated_and_token_shape_is_strict(self):
        digest = o.credential_digest(TOKEN)
        self.assertRegex(digest, r'^[0-9a-f]{64}$')
        for token in [None, '', 'A'*32, 'A'*42, 'A'*44, 'A'*42+'=', BINDING, 'a'*64, 123]:
            self.assert_error('owner_context_lost', o.credential_digest, token)

    def test_no_cookie_without_expectation_is_unconfirmed_no_lookup_or_write(self):
        conn = Connection()
        self.assertIsNone(self.lookup(conn, None, None))
        self.assertEqual(conn.trace, [])

    def test_lost_cookie_with_expectation_never_issues(self):
        conn = Connection()
        self.assert_error('owner_context_lost', self.lookup, conn, None, BINDING)
        self.assertEqual(conn.data['users'], [])

    def test_verified_cookie_selects_hash_and_returns_stable_identity(self):
        conn = self.connection(row())
        context = self.lookup(conn)
        self.assertEqual(context.owner_identity, row()['owner_identity'])
        self.assertEqual(context.owner_scope, c.fingerprint(context.owner_identity))
        self.assertEqual(context.public(), dict(state='confirmed', binding_id=BINDING))
        self.assertEqual(conn.trace, [('lookup', {'credential_hash': o.credential_digest(TOKEN)})])

    def test_public_binding_is_not_credential(self):
        self.assert_error('owner_context_lost', self.lookup, self.connection(row()), BINDING)

    def test_unknown_cookie_and_expired_or_revoked_context_are_rejected(self):
        self.assert_error('owner_context_lost', self.lookup, Connection())
        for value in [row(expires_at=1000), row(expires_at=999), row(revoked_at=1000)]:
            self.assert_error('owner_context_lost', self.lookup, self.connection(value))

    def test_different_binding_conflicts_without_mutation(self):
        conn = self.connection(row()); before = deepcopy(conn.data)
        self.assert_error('owner_context_changed', self.lookup, conn, TOKEN, OTHER)
        self.assertEqual(conn.data, before)

    def test_expected_null_retains_existing_context_and_expiry(self):
        conn = self.connection(row()); before = deepcopy(conn.data)
        self.assertEqual(self.lookup(conn, TOKEN, None).expires_at, 1600)
        self.assertEqual(conn.data, before)

    def test_owner_scope_and_db_credential_hash_must_match(self):
        conn = self.connection(row(owner_scope='c'*64))
        self.assert_error('owner_context_unavailable', self.lookup, conn)
        value = row(); value['credential_hash'] = 'c'*64
        conn = Connection(); conn.data['contexts'][o.credential_digest(TOKEN)] = value
        self.assert_error('owner_context_unavailable', self.lookup, conn)

    def test_member_shape_cannot_substitute_for_verified_issuer(self):
        identity = dict(kind='member', member_id=11, auth_subject='client-provider-label')
        value = row(owner_identity=identity, owner_scope=c.fingerprint(identity))
        self.assert_error('verified_member_adapter_unready', self.lookup, self.connection(value))

    def test_client_verified_email_and_analytics_id_do_not_become_guest_identity(self):
        for identity in [dict(kind='member', email='dev@example.invalid', verified=True),
                         dict(kind='guest', user_id=11, owner_hash='b'*64, pc_vid='analytics')]:
            value = row(owner_identity=identity)
            self.assert_error('owner_context_unavailable', self.lookup, self.connection(value))

    def test_malformed_identity_and_epoch_fail_closed(self):
        for changes in [dict(expires_at=True), dict(created_at=1001), dict(owner_identity={}),
                        dict(context_id='not-a-uuid')]:
            self.assert_error('owner_context_unavailable', self.lookup, self.connection(row(**changes)))

    def test_guest_creation_uses_new_user_and_independent_random_secrets(self):
        conn = Connection()
        context, token = o.create_guest(conn, policy(), now=1000)
        self.assertEqual(len(base64.urlsafe_b64decode(token+'=')), 32)
        self.assertEqual(context.owner_identity['user_id'], 1)
        self.assertEqual(context.expires_at, 1600)
        self.assertNotEqual(context.owner_identity['owner_hash'], o.credential_digest(token))
        self.assertNotEqual(context.owner_scope, o.credential_digest(token))
        self.assertNotIn(token, json.dumps(conn.data))
        self.assertEqual([x[0] for x in conn.trace], ['insert_user', 'insert_context'])
        self.assertEqual(self.lookup(conn, token, context.context_id).owner_identity, context.owner_identity)

    def test_creation_requires_callers_active_transaction_and_bounded_expiry(self):
        conn = Connection(); conn.active = False
        self.assert_error('owner_transaction_required', o.create_guest, conn, policy(), now=1000)
        self.assertEqual(conn.trace, [])
        self.assert_error('owner_configuration_unready', o.create_guest, Connection(), policy(),
                          now=c.MAX_INTEGER)

    def test_required_schema_is_queried_even_without_cookie_and_errors_propagate(self):
        conn = Connection(); conn.fail_tag = 'ready'
        with self.assertRaises(RuntimeError): o.ensure_ready(conn)
        self.assertEqual(conn.trace[0][0], 'ready')

    def test_helper_has_no_engine_env_transaction_or_network_ownership(self):
        source = Path(o.__file__).read_text(encoding='utf-8')
        tree = ast.parse(source)
        imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertNotIn('db', imports)
        calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)]
        self.assertTrue(set(calls).isdisjoint({'connect', 'begin', 'commit', 'rollback', 'getenv'}))
        self.assertNotIn('visitor', source.split('from . import commerce_contract')[1])


if __name__ == '__main__': unittest.main()
