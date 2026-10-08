"""Isolated ASGI + transaction-call simulation. No database/provider connections."""
import ast
import asyncio
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import hashlib
import importlib
import io
import json
from pathlib import Path
import socket
import sys
import types
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def _deny_external(event, args):
    # Windows asyncio creates its wake-up pipe via the stdlib socketpair
    # fallback. Permit only that exact caller, never general loopback/DB IO.
    fallback = getattr(socket, '_fallback_socketpair', None)
    if (event == 'socket.connect' and fallback is not None
            and sys._getframe(1).f_code is fallback.__code__
            and args[1][0] in ('127.0.0.1', '::1')):
        return
    if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo',
                 'subprocess.Popen', 'os.system'}:
        raise AssertionError('live network/process forbidden by isolated commerce tests')
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        path = str(args[0]).replace('\\', '/').lower().rstrip("'")
        if path.endswith('/.env'):
            raise AssertionError('production environment file forbidden by isolated commerce tests')


# Before importing auth/router: never let api.db load a production .env/engine.
sys.addaudithook(_deny_external)
fake_db = types.ModuleType('api.db')


class BlockedEngine:
    def connect(self): raise AssertionError('unmocked database access')
    def begin(self): raise AssertionError('unmocked database access')


fake_db.engine = BlockedEngine()
previous_db = sys.modules.get('api.db')
sys.modules['api.db'] = fake_db
try:
    auth = importlib.import_module('api.customer_auth')
    routes = importlib.import_module('api.commerce_owner_contexts')
finally:
    # Restore only our stub. Restoring the entire module registry would remove
    # newly imported FastAPI classes and create incompatible class identities.
    if previous_db is None:
        sys.modules.pop('api.db', None)
    else:
        sys.modules['api.db'] = previous_db

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.testclient import TestClient
from api import commerce_owner as o
from tests.test_commerce_owner import Connection, TOKEN, BINDING, OTHER, CONFIG, policy, row

ENDPOINT = '/api/commerce/owner-context'
ORIGIN = 'https://shop.example'
GOOD_HEADERS = {'Origin': ORIGIN, 'Sec-Fetch-Site': 'same-origin'}


# Accepted customer_auth is V3 (474cb43, sha256 below). V3 moved main's member guard out of a
# module-level `member_middleware` into `_needs_member_resolution(path, method)`, used by
# `create_member_middleware(resolver)`; `member_middleware` delegates to that factory product.
# These checks prove the commerce path exceptions are the same ones main accepted (d2c66b3).
ACCEPTED_V3_AUTH_SHA256 = '65df7b64bd07dd877e1f7c9d5e306a89a5829ecb751eb46a73e978fee115eaed'
MAIN_OPEN_PREFIXES = ("/api/auth/", "/shared/", "/design-system/", "/admin2/", "/admin/", "/api/admin/")
# Verbatim guard condition of main's accepted member_middleware (d2c66b3).
MAIN_ACCEPTED_GUARD = compile('''(path != "/api/commerce/owner-context"
        and not (request.method == "GET" and len(path.split("/")) == 5
                 and path.split("/")[:4] == ["", "api", "commerce", "orders"]
                 and path.split("/")[4] != "")
        and not (len(path.split("/")) in (6, 7)
                 and path.split("/")[:4] == ["", "api", "commerce", "orders"]
                 and path.split("/")[4] != ""
                 and path.split("/")[5] == "support"
                 and (len(path.split("/")) == 6 or path.split("/")[6] == ""))
        and not (request.method == "GET" and len(path.split("/")) in (6, 7)
                 and path.split("/")[:4] == ["", "api", "commerce", "orders"]
                 and path.split("/")[4] != ""
                 and path.split("/")[5] == "fulfillment"
                 and (len(path.split("/")) == 6 or path.split("/")[6] == ""))
        and not path.startswith(OPEN_PREFIXES))''', 'main-accepted-member-guard', 'eval')
METHODS = ('GET', 'POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS', 'PATCH')


def _guard_paths():
    paths = ['/api/commerce/owner-context', '/api/commerce/owner-context/', '/api/commerce/orders',
             '/api/commerce/orders/', '/api/commerce/orders/order-1', '/api/commerce/orders/invalid!',
             '/api/commerce/orders/order-1/', '/api/commerce/orders/order-1/confirm',
             '/api/commerce/orders/draft', '/api/my/orders', '/api/my/profile', '/api/auth/login',
             '/api/admin/x', '/admin2/x', '/shared/a.js', '/mvp3/', '/']
    for suffix in ('support', 'fulfillment'):
        paths.extend('/api/commerce/orders/'+value for value in (
            'order-1/'+suffix, 'order-1/'+suffix+'/', 'order-1/'+suffix+'//',
            '/'+suffix, 'order-1/'+suffix+'-extra', 'order-1/'+suffix+'/x'))
    return paths


def _predicate_mismatches(predicate):
    """Every (path, method) where `predicate` disagrees with main's accepted guard."""
    return [(path, method) for path in _guard_paths() for method in METHODS
            if predicate(path, method) != eval(MAIN_ACCEPTED_GUARD, {}, dict(
                path=path, request=SimpleNamespace(method=method), OPEN_PREFIXES=MAIN_OPEN_PREFIXES))]


def _predicate_from_source(source):
    """Compile `_needs_member_resolution` from customer_auth source bytes, isolated from the module."""
    tree = ast.parse(source.decode('utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_needs_member_resolution')
    namespace = {'OPEN_PREFIXES': auth.OPEN_PREFIXES}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'selected-member-predicate', 'exec'), namespace)
    return namespace['_needs_member_resolution']


class Engine:
    """Copies are committed on successful exit, discarded on failure."""
    def __init__(self):
        self.data = dict(users=[], contexts={}, now=1000)
        self.trace = []
        self.fail_tag = self.read_fail_tag = None
        self.fail_commit = False
        self.commits = 0

    def begin(self): return Transaction(self)
    def connect(self): return ReadConnection(self)


class Transaction:
    def __init__(self, engine): self.engine = engine
    def __enter__(self):
        self.engine.trace.append(('begin_write', {}))
        self.conn = Connection(deepcopy(self.engine.data), self.engine.trace)
        self.conn.fail_tag = self.engine.fail_tag
        return self.conn
    def __exit__(self, kind, value, tb):
        if kind is not None or self.engine.fail_commit:
            self.engine.trace.append(('rollback_write', {}))
            if kind is None: raise RuntimeError('fixture-private-commit-token')
            return False
        self.engine.data = deepcopy(self.conn.data)
        self.engine.commits += 1
        self.engine.trace.append(('commit_write', {}))


class ReadConnection:
    def __init__(self, engine): self.engine = engine
    def __enter__(self):
        self.engine.trace.append(('open_read', {}))
        self.conn = Connection(self.engine.data, self.engine.trace, readonly=True)
        self.conn.fail_tag = self.engine.read_fail_tag
        return self.conn
    def __exit__(self, *args): self.engine.trace.append(('close_read', {}))


class OwnerHttpTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()
        self.policy_loader = routes.get_policy
        for target, kwargs in [(routes.get_policy, {'return_value': policy()}),
                               (routes.get_engine, {'return_value': self.engine})]:
            p = patch.object(routes, target.__name__, **kwargs)
            p.start(); self.addCleanup(p.stop)
        self.app = FastAPI(); self.app.include_router(routes.router)
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.addCleanup(self.client.close)

    def seed(self, value=None):
        value = row() if value is None else value
        self.engine.data['contexts'][value['credential_hash']] = value
        self.engine.data['users'] = [11]

    def cookie(self, token=TOKEN): return { 'Cookie': o.COOKIE+'='+token }
    def post(self, expected=None, cookie=None, headers=None, **kwargs):
        h = dict(GOOD_HEADERS)
        if headers is not None: h = headers
        if cookie is not None: h = {**h, **self.cookie(cookie)}
        return self.client.post(ENDPOINT, json={'expected_binding_id': expected}, headers=h, **kwargs)

    def assert_private(self, response, status=200):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.headers.get('cache-control'), 'no-store')
        text = response.text
        for private in [TOKEN, o.credential_digest(TOKEN), 'fixture-private', 'dev@example.invalid']:
            self.assertNotIn(private, text)
        return response.json()

    def assert_no_issue(self, response, status):
        self.assert_private(response, status)
        self.assertNotIn('set-cookie', response.headers)
        self.assertTrue({'insert_user', 'insert_context'}.isdisjoint({t for t, _ in self.engine.trace}))

    def test_unconfirmed_get_checks_schema_and_rolls_back_without_cookie_or_write(self):
        body = self.assert_private(self.client.get(ENDPOINT))
        self.assertEqual(body['context'], {'state': 'unconfirmed', 'binding_id': None})
        self.assertEqual(body['items'], [])
        self.assertEqual([t for t, _ in self.engine.trace],
                         ['open_read', 'ready', 'clock', 'rollback_read', 'close_read'])
        self.assertEqual(self.engine.data['users'], [])

    def test_confirmed_get_is_read_only_and_has_only_public_envelope(self):
        self.seed(); before = deepcopy(self.engine.data)
        response = self.client.get(ENDPOINT, headers=self.cookie(), params={'expected_binding_id': BINDING})
        body = self.assert_private(response)
        self.assertEqual(set(body), {'commerce_version', 'checked_at', 'context', 'items', 'next_cursor'})
        self.assertEqual(body['context'], {'state': 'confirmed', 'binding_id': BINDING})
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(self.engine.data, before)
        self.assertEqual(self.engine.commits, 0)

    def test_old_member_visitor_access_key_and_query_are_not_fallback_credentials(self):
        self.seed()
        response = self.client.get(ENDPOINT+'?k='+TOKEN, headers={
            'X-Access-Key': TOKEN, 'Cookie': 'popcorn_member_session='+TOKEN+'; pc_vid='+TOKEN})
        self.assertEqual(self.assert_private(response)['context']['state'], 'unconfirmed')
        self.assertNotIn('lookup', [t for t, _ in self.engine.trace])

    def test_get_expected_binding_without_cookie_fails_and_creates_nothing(self):
        self.assert_no_issue(self.client.get(ENDPOINT, params={'expected_binding_id': BINDING}), 401)

    def test_get_invalid_duplicate_binding_is_redacted_no_store_before_db(self):
        for query in ['expected_binding_id=private-value',
                      'expected_binding_id='+BINDING+'&expected_binding_id='+OTHER]:
            response = self.client.get(ENDPOINT+'?'+query)
            self.assert_no_issue(response, 422)
            self.assertNotIn('private-value', response.text)
        self.assertEqual(self.engine.trace, [])

    def test_missing_or_invalid_configuration_and_http_transport_are_unavailable_before_db(self):
        with patch.object(routes, 'get_policy', side_effect=o.OwnerError(503, 'owner_configuration_unready')):
            self.assert_no_issue(self.client.get(ENDPOINT), 503)
            self.assert_no_issue(self.post(), 503)
        self.assert_no_issue(self.client.get('http://shop.example'+ENDPOINT), 503)
        self.assertEqual(self.engine.trace, [])

    def test_actual_configuration_loader_has_no_legacy_security_or_period_fallback(self):
        real_loader = self.policy_loader
        with patch.object(routes, 'get_policy', side_effect=real_loader):
            with patch.dict(routes.os.environ, {'COOKIE_SECURE':'1'}, clear=True):
                self.assert_no_issue(self.client.get(ENDPOINT), 503)
            self.assertEqual(self.engine.trace, [])
            with patch.dict(routes.os.environ, CONFIG, clear=True):
                self.assert_private(self.client.get(ENDPOINT))

    def test_anonymous_get_with_missing_schema_is_503_and_never_empty_success(self):
        self.engine.read_fail_tag = 'ready'
        response = self.client.get(ENDPOINT)
        self.assert_no_issue(response, 503)
        self.assertNotIn('context', response.json())

    def test_post_requires_exact_origin_json_and_same_origin_metadata_before_db(self):
        cases = [({}, 403), ({'Origin': 'https://evil.example'}, 403),
                 ({'Origin': ORIGIN, 'Sec-Fetch-Site': 'cross-site'}, 403),
                 ({'Origin': ORIGIN, 'Sec-Fetch-Site': 'same-site'}, 403),
                 ({'Origin': 'https://evil.example', 'Host': 'evil.example'}, 403)]
        for headers, status in cases:
            with self.subTest(headers=headers):
                self.assert_no_issue(self.post(headers=headers), status)
        response = self.client.post(ENDPOINT, content='{}', headers={'Origin': ORIGIN, 'Content-Type':'text/plain'})
        self.assert_no_issue(response, 415)
        self.assertEqual(self.engine.trace, [])

    def test_duplicate_origin_and_fetch_site_are_rejected(self):
        for headers in [[('Origin', ORIGIN), ('Origin', ORIGIN)],
                        [('Origin', ORIGIN), ('Sec-Fetch-Site', 'same-origin'),
                         ('Sec-Fetch-Site', 'same-origin')]]:
            response = self.client.post(ENDPOINT, json={'expected_binding_id': None}, headers=headers)
            self.assert_no_issue(response, 403)
        self.assertEqual(self.engine.trace, [])

    def test_required_nullable_body_and_extra_fields_are_strict_and_redacted(self):
        for body in [{}, [], {'expected_binding_id': 123},
                     {'expected_binding_id': None, 'credential': TOKEN},
                     {'expected_binding_id': None, 'user_id': 11},
                     {'expected_binding_id': None, 'verified': True}]:
            response = self.client.post(ENDPOINT, json=body, headers=GOOD_HEADERS)
            self.assert_no_issue(response, 422)
        for raw in ['{', '{"expected_binding_id":null,"expected_binding_id":null}', ' '*4097]:
            response = self.client.post(ENDPOINT, content=raw, headers={**GOOD_HEADERS,'Content-Type':'application/json'})
            self.assert_no_issue(response, 422)
        self.assertEqual(self.engine.trace, [])

    def test_first_post_creates_guest_independent_of_dev_and_tracking_markers_after_commit(self):
        response = self.client.post(ENDPOINT, json={'expected_binding_id': None},
                                    headers={**GOOD_HEADERS,'Cookie':'popcorn_member_session='+TOKEN+'; pc_vid='+TOKEN})
        body = self.assert_private(response)
        self.assertEqual(body['context']['state'], 'confirmed')
        self.assertEqual(self.engine.commits, 1)
        cookie = response.headers['set-cookie']
        for flag in ['HttpOnly', 'Secure', 'SameSite=lax', 'Path=/', 'Max-Age=600']:
            self.assertIn(flag, cookie)
        self.assertNotIn('Domain=', cookie)
        stored = next(iter(self.engine.data['contexts'].values()))
        self.assertEqual(stored['owner_identity']['kind'], 'guest')
        self.assertEqual(stored['owner_identity']['user_id'], 1)
        self.assertEqual(body['context']['binding_id'], stored['context_id'])
        tags = [t for t, _ in self.engine.trace]
        self.assertLess(tags.index('commit_write'), tags.index('open_read'))
        self.assertEqual(tags.count('lookup'), 1)
        raw = cookie.split(';',1)[0].split('=',1)[1]
        self.assertNotIn(raw, response.text)
        self.assertNotIn(raw, json.dumps(self.engine.trace))

    def test_valid_cookie_with_expected_or_null_keeps_context_without_renewal(self):
        self.seed(); before = deepcopy(self.engine.data)
        for expected in [BINDING, None]:
            response = self.post(expected, TOKEN)
            self.assertEqual(self.assert_private(response)['context']['binding_id'], BINDING)
            self.assertNotIn('set-cookie', response.headers)
            self.assertEqual(self.engine.data, before)
        self.assertTrue({'insert_user','insert_context'}.isdisjoint({t for t,_ in self.engine.trace}))

    def test_unknown_malformed_expired_revoked_cookie_is_not_replaced(self):
        for value, token in [(None, TOKEN), (None, ''), (row(expires_at=1000), TOKEN),
                             (row(revoked_at=1000), TOKEN)]:
            self.engine.data['contexts'] = {}
            self.engine.trace.clear()
            if value: self.seed(value)
            self.assert_no_issue(self.post(None, token), 401)

    def test_expected_cookie_loss_and_binding_conflict_never_issue(self):
        self.assert_no_issue(self.post(BINDING), 401)
        self.seed(); self.assert_no_issue(self.post(OTHER, TOKEN), 409)
        self.assert_no_issue(self.client.get(ENDPOINT, params={'expected_binding_id':OTHER},
                                            headers=self.cookie()), 409)

    def test_insert_failure_and_commit_failure_rollback_user_and_never_set_cookie(self):
        for failure in ['insert_context','commit']:
            self.engine.data = dict(users=[], contexts={}, now=1000); self.engine.trace.clear()
            self.engine.fail_tag = 'insert_context' if failure != 'commit' else None
            self.engine.fail_commit = failure == 'commit'
            response = self.post()
            self.assert_private(response, 503)
            self.assertNotIn('set-cookie', response.headers)
            self.assertEqual(self.engine.data['users'], [])
            self.assertEqual(self.engine.data['contexts'], {})
            self.assertNotIn('open_read', [t for t,_ in self.engine.trace])

    def test_unique_credential_collision_rolls_back_new_user_simulation(self):
        self.seed(); before = deepcopy(self.engine.data)
        with patch.object(o.secrets, 'token_urlsafe', return_value=TOKEN):
            response = self.post()
        self.assert_private(response, 503)
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(self.engine.data, before)

    def test_committed_insert_then_read_failure_never_returns_precommit_confirmation_or_cookie(self):
        self.engine.read_fail_tag = 'lookup'
        response = self.post()
        self.assert_private(response, 503)
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(self.engine.commits, 1)
        self.assertEqual(len(self.engine.data['contexts']), 1)
        self.assertNotIn('context', response.json())

    def test_read_schema_and_lookup_failures_are_503_not_unconfirmed_success(self):
        for failure in ['ready','lookup']:
            self.engine.read_fail_tag = failure; self.seed()
            response = self.client.get(ENDPOINT, headers=self.cookie())
            self.assert_no_issue(response, 503)
            self.assertNotIn('context', response.json())

    def test_expiry_between_commit_and_read_never_confirms_or_issues(self):
        original = self.engine.connect
        def advance():
            self.engine.data['now'] = 1600
            return original()
        with patch.object(self.engine, 'connect', side_effect=advance): response = self.post()
        self.assert_private(response, 401)
        self.assertNotIn('set-cookie', response.headers)

    def test_sensitive_failures_never_print_credentials_or_sql_error_parameters(self):
        self.engine.fail_commit = True
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors): response = self.post()
        self.assert_private(response, 503)
        self.assertNotIn('fixture-private', output.getvalue()+errors.getvalue())

    def test_actual_member_middleware_skips_exact_owner_get_with_valid_member_cookie(self):
        self.seed()
        self.app.middleware('http')(auth.member_middleware)
        with patch.object(auth, 'resolve_session', return_value={'member_id':11}) as resolver, \
                patch.object(auth.RUNTIME_RESOLVER, 'resolve', return_value={'member_id':11}) as runtime:
            response = self.client.get(ENDPOINT, headers={**self.cookie(),
                  'Cookie':o.COOKIE+'='+TOKEN+'; popcorn_member_session=valid-dev-cookie'})
        self.assert_private(response)
        resolver.assert_not_called()
        runtime.assert_not_called()
        self.assertTrue({'insert_user','insert_context'}.isdisjoint({t for t,_ in self.engine.trace}))


class MiddlewareAndSourceTests(unittest.TestCase):
    def test_network_guard_rejects_external_and_general_loopback_connections(self):
        for address in [('127.0.0.1',5432), ('203.0.113.1',443)]:
            with socket.socket() as client:
                with self.assertRaisesRegex(AssertionError,'live network/process forbidden'):
                    client.connect(address)

    def test_commerce_paths_never_reach_the_member_resolver_and_contextvar_restores(self):
        async def check(path, method, fail):
            request = Request({'type':'http','method':method,'path':path,'headers':[],
                               'scheme':'https','server':('shop.example',443),'query_string':b''})
            before = auth._current.get()
            seen = []
            async def next_handler(request):
                seen.append(auth.current_member())
                if fail: raise RuntimeError('fixture downstream error')
                return Response()
            with patch.object(auth.RUNTIME_RESOLVER, '_ready') as ready, \
                    patch.object(auth.RUNTIME_RESOLVER, 'resolve', return_value=None) as resolver:
                if fail:
                    with self.assertRaises(RuntimeError): await auth.member_middleware(request,next_handler)
                else: await auth.member_middleware(request,next_handler)
            ready.assert_not_called(); resolver.assert_not_called()
            self.assertEqual(seen, [None])
            self.assertIs(auth._current.get(), before)
        # /api/auth/ and /api/my/ are V3 "protected" paths (errors become 503); they are not commerce paths.
        for path in _guard_paths():
            if path.startswith(('/api/auth/', auth.GUARDED_PREFIX)): continue
            for method in ('GET','POST'):
                for fail in (False,True):
                    with self.subTest(path=path,method=method,fail=fail):
                        asyncio.run(check(path,method,fail))

    def test_guarded_my_paths_still_consult_the_runtime_resolver(self):
        async def check(path, method):
            request = Request({'type':'http','method':method,'path':path,'headers':[],
                               'scheme':'https','server':('shop.example',443),'query_string':b''})
            async def next_handler(request): raise AssertionError('handler must not run without a member')
            with patch.object(auth.RUNTIME_RESOLVER, '_ready'), \
                    patch.object(auth.RUNTIME_RESOLVER, 'resolve', return_value=None) as resolver:
                response = await auth.member_middleware(request,next_handler)
            self.assertEqual(resolver.call_count, 1)
            self.assertEqual(response.status_code, 401)
        for path in ('/api/my/orders','/api/my/profile'):
            with self.subTest(path=path): asyncio.run(check(path,'GET'))

    def test_v3_member_predicate_equals_main_accepted_guard_on_every_path_and_method(self):
        self.assertEqual(auth.OPEN_PREFIXES, MAIN_OPEN_PREFIXES)
        self.assertEqual(_predicate_mismatches(auth._needs_member_resolution), [])
        self.assertEqual(_predicate_mismatches(_predicate_from_source(Path(auth.__file__).read_bytes())), [])

    def test_predicate_check_fails_when_one_path_segment_or_method_changes(self):
        raw = Path(auth.__file__).read_bytes()
        for old, new in ((b'path.split("/")[5] == "fulfillment"', b'path.split("/")[5] == "fulfilment"'),
                         (b'path.split("/")[5] == "support"', b'path.split("/")[5] == "supports"'),
                         (b'len(path.split("/")) == 5', b'len(path.split("/")) == 6'),
                         (b'and not (method == "GET" and len(path.split("/")) in (6, 7)',
                          b'and not (method == "POST" and len(path.split("/")) in (6, 7)')):
            with self.subTest(change=new.decode()):
                self.assertEqual(raw.count(old), 1)
                self.assertNotEqual(_predicate_mismatches(_predicate_from_source(raw.replace(old,new,1))), [])

    def test_member_middleware_is_the_v3_factory_product_wired_in_main(self):
        self.assertEqual(hashlib.sha256(Path(auth.__file__).read_bytes()).hexdigest(), ACCEPTED_V3_AUTH_SHA256)
        runtime = auth._runtime_middleware
        self.assertEqual(runtime.__qualname__, 'create_member_middleware.<locals>.boundary')
        self.assertIs(dict(zip(runtime.__code__.co_freevars, (c.cell_contents for c in runtime.__closure__)))['resolver'],
                      auth.RUNTIME_RESOLVER)
        member = next(n for n in ast.parse(Path(auth.__file__).read_text(encoding='utf-8')).body
                      if isinstance(n, ast.AsyncFunctionDef) and n.name == 'member_middleware')
        self.assertEqual(ast.dump(member.body[-1]),
                         ast.dump(ast.parse('return await _runtime_middleware(request, call_next)').body[0]))
        main = ast.parse((Path(auth.__file__).parent/'main.py').read_text(encoding='utf-8'))
        imports = [(n.module, a.name) for n in main.body if isinstance(n, ast.ImportFrom) for a in n.names]
        self.assertIn(('customer_auth', 'member_middleware'), imports)
        wired = [ast.unparse(n.value) for n in main.body if isinstance(n, ast.Expr)]
        self.assertIn("app.middleware('http')(member_middleware)", wired)

    def test_runtime_module_exposes_only_two_routes_and_no_legacy_identity_import(self):
        self.assertEqual([(r.path, r.methods) for r in routes.router.routes],
                         [(ENDPOINT, {'GET'}), (ENDPOINT, {'POST'})])
        tree = ast.parse(Path(routes.__file__).read_text(encoding='utf-8'))
        imports = [n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertTrue(set(imports).isdisjoint({'customer_auth','visitor','access_gate','mvp3_saved_quotes'}))
        self.assertEqual(o.COOKIE, '__Host-popcorn_commerce_owner')


if __name__ == '__main__': unittest.main()
