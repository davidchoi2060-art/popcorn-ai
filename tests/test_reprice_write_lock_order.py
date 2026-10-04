"""Actual selected route AST and readonly guard; CODE/MOCK, no PG proof."""
import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from typing import Literal
from uuid import uuid4
from unittest.mock import patch
from api import admin_operation_receipt_core as receipt_core

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from api.pricing import formula_text, resolve_margins, sale_from_purchase
from api.pricing_write_guard_core import lock_products, ProductScopeChanged, _LOCK_PRODUCTS_SQL
from api.pricing_policy_guard_core import lock_pricing_policy_shared
from api.reprice_preview_expected import canonical_basis, make_expected, InvalidPreviewBasis, canonical_basis_v2, make_expected_v2
from api.reprice_basis_snapshot import read_basis, InvalidRepriceBasisSnapshot

ROOT = Path(__file__).resolve().parents[1]
POLICY_SHARED_SQL = 'SELECT pg_catalog.pg_advisory_xact_lock_shared(:namespace,:key)'
POLICY_PARAMS = {'namespace':1347375171,'key':1}
APPLY_AST = 'bf365d3dabad42cdda04bce92cebc3534f4a51ddcaa18a451247100268858fc4'
UNDO_AST = '0d270ad9117d5aff4a839a3198623817c0ac7a26c44cb001622a417c5613f49e'
REST_AST = 'de3b18e4d2455cbe0bba1e1debbf779cfb698db3037a6b99cab5b886c8d24252'
READONLY = {
 'api/pricing_write_guard_core.py': 'be068f1bf63421fd71e569a9b9b38fbedb13aa0c002a5973622de5f8e06c3e24',
 'api/pricing.py': '1fd15157b1473f9b440950f5c10f08a38ca15676331a98970894af59837a8604',
 'api/taxonomy.py': 'e0603f0d35b2f2052b9122f54752183984afacbb74a5e906b7de96b12381e1c6',
 'api/admin_price_import.py': '866a727bf0a03639ce47c035cdf0d841a76fa11aa706229fa9a4d7cc875d64be',
 'api/admin_orders.py': '4220be7f057af7e2bc77d287b58b52de5da9f6cdb03a6bfa0e36bd9c99f5913b',
}


def digest(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def assigned(node, name):
    return isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)


TEST_ENVIRONMENT = '3c88fbc4-091a-44ea-bc0f-1192de0ca173'
TEST_CONTEXT = {'contract_version':'admin_operation_v1', 'canonical_version':'reprice_request_v1',
                'actor_id':21, 'environment':TEST_ENVIRONMENT, 'action':'reprice_apply'}


def prepare_test_operation(body, operator):
    with patch.object(receipt_core, 'configured_environment', return_value=TEST_ENVIRONMENT):
        return receipt_core.prepare_reprice_operation(body, operator)


def operation_request_fields(payload):
    command = dict(payload);command.setdefault('note', '')
    if command['scope'] not in ('live','selling','all'):
        command['scope'] = 'all'  # Invalid-scope route tests reject before using this hash.
    return {'operation_id':str(uuid4()), 'operation_context':dict(TEST_CONTEXT),
            'request_fingerprint':receipt_core.request_fingerprint(command)}


def adapt_apply_model(env):
    model = env['ApplyBody']
    if 'operation_id' not in model.model_fields:return
    def request(**fields):
        if not any(k in fields for k in ('operation_id','operation_context','request_fingerprint')):
            fields = fields | operation_request_fields(fields)
        return model(**fields)
    env['ApplyModel'] = model;env['ApplyBody'] = request


def revision_baseline(node, overlay=None):
    """Strip only new v2 snapshot/plan/version rejection sites before U6 checks."""
    out=deepcopy(node);overlay=[] if overlay is None else overlay
    if out.name not in ('preview','apply'):return out
    class Revision(ast.NodeTransformer):
        def visit_If(self,n):
            expected=ast.parse('expected["version"] != "reprice_basis_v2"',mode='eval').body
            if ast.dump(n.test)==ast.dump(expected):
                overlay.append(deepcopy(n));return None
            return self.generic_visit(n)
        def visit_Assign(self,n):
            if assigned(n,'snapshot') or assigned(n,'current_snapshot'):
                if not isinstance(n.value,ast.Call) or not isinstance(n.value.func,ast.Name) or n.value.func.id!='_read_revision_basis':
                    raise AssertionError('exact revision read required')
                overlay.append(deepcopy(n))
                if assigned(n,'snapshot'):
                    scope='scope' if out.name=='preview' else 'body.scope'
                    return ast.parse(f'fee, margin = _settings(conn)\nmmap = _margin_map(conn, margin)\nrows = _rows(conn, {scope})').body
                return ast.parse('current_fee, current_margin = _settings(conn)\ncurrent_mmap = _margin_map(conn, current_margin)\ncurrent_rows = _rows(conn, body.scope)').body
            if (len(n.targets)==1 and isinstance(n.targets[0],ast.Tuple)
                    and [getattr(t,'id',None) for t in n.targets[0].elts] in
                    (['fee','margin','mmap','rows'],['current_fee','current_margin','current_mmap','current_rows'])):
                overlay.append(deepcopy(n));return None
            return self.generic_visit(n)
        def visit_Call(self,n):
            if isinstance(n.func,ast.Name) and n.func.id=='_preview_plan_v2':
                overlay.append(deepcopy(n))
                if len(n.args)!=6 or n.keywords or not isinstance(n.args[-1],ast.Name) or n.args[-1].id not in ('snapshot','current_snapshot'):
                    raise AssertionError('exact v2 plan argument required')
                n.func.id='_preview_plan';n.args.pop()
            return self.generic_visit(n)
    return Revision().visit(out)


def revision_module_baseline(tree, overlay=None):
    out=deepcopy(tree);overlay=[] if overlay is None else overlay;nodes=[]
    for n in out.body:
        if isinstance(n,ast.ImportFrom) and n.module=='reprice_basis_snapshot':
            overlay.append(deepcopy(n));continue
        if isinstance(n,ast.ImportFrom) and n.module=='reprice_preview_expected':
            extra=[a for a in n.names if a.name in ('canonical_basis_v2','make_expected_v2')]
            if extra:overlay.append(ast.ImportFrom(module=n.module,names=deepcopy(extra),level=n.level))
            n.names=[a for a in n.names if a not in extra]
        if isinstance(n,ast.FunctionDef) and n.name in ('_read_revision_basis','_preview_plan_v2'):
            overlay.append(deepcopy(n));continue
        if isinstance(n,ast.ClassDef) and n.name=='PreviewExpected':
            field=next(a for a in n.body if isinstance(a,ast.AnnAssign) and a.target.id=='version')
            if ast.dump(field.annotation)!=ast.dump(ast.parse('Literal["reprice_basis_v1"]',mode='eval').body):
                overlay.append(deepcopy(field));field.annotation=ast.parse('Literal["reprice_basis_v1"]',mode='eval').body
        nodes.append(revision_baseline(n,overlay) if isinstance(n,ast.FunctionDef) else n)
    out.body=nodes;return out


def u6_baseline(node):
    """Strip exact U6 sites, preserving the accepted U4/D business nodes."""
    out = revision_baseline(node)
    if out.name != 'apply' or isinstance(out.body[0], ast.Expr):return out
    if len(out.body) != 8:raise AssertionError('unexpected U6 boundary')
    tx = out.body[5]
    if not isinstance(tx, ast.With) or len(tx.body) != 4:raise AssertionError('unexpected U6 TX')
    branch = tx.body[3]
    if len(branch.body) != 1 or len(branch.orelse) != 1:raise AssertionError('unexpected U6 branches')
    replay, preflight = branch.body[0], branch.orelse[0]
    additions = [out.body[0],out.body[4],tx.items[0].context_expr,*tx.body[1:3],branch.test,
                 *replay.body,*replay.handlers,*preflight.handlers,preflight.orelse[-1],*out.body[-2:],
                 *[h for n in preflight.body if isinstance(n,ast.Try) and len(n.body)==2 for h in n.handlers]]
    if digest(ast.Module(body=additions,type_ignores=[])) != '9f5403ec83df9ec6b8325bb9f4129d93ae022a713bb48c22be3871454459c97b':
        raise AssertionError('U6 guard/receipt/exception sites changed')
    response = deepcopy(preflight.orelse[-5:-1])
    if not assigned(response[-1], 'response_body'):raise AssertionError('exact response assignment required')
    response[-1] = ast.Return(value=response[-1].value)
    tx.items[0].context_expr = ast.parse('engine.begin()').body[0].value
    domain = [n for n in preflight.body if isinstance(n,ast.Try) and len(n.body)==2]
    if len(domain)!=2:raise AssertionError('exact two pure domain boundaries required')
    class DomainRaises(ast.NodeTransformer):
        def visit_Name(self, n):
            return ast.copy_location(ast.Name(id='HTTPException',ctx=n.ctx),n) if n.id=='PrewriteRejected' else n
    original_preflight = []
    for n in preflight.body:
        original_preflight.extend(n.body if n in domain else [n])
    original_preflight = [DomainRaises().visit(n) for n in original_preflight]
    tx.body = tx.body[:1] + original_preflight + preflight.orelse[:-5]
    out.body = ast.parse('_owner()').body + out.body[1:4] + [tx] + response
    if digest(out) != 'dc24a65118b665976c32bd7501992f39cac364bc179986956a10729864ab823b':raise AssertionError('U4/D business changed under U6')
    return out


def u6_module_baseline(tree):
    out = revision_module_baseline(tree);nodes = []
    for n in out.body:
        if isinstance(n, ast.ImportFrom) and n.module == 'admin_operation_receipt_core':
            if digest(n) != 'fd56af94dd41c952bddb1c1e2ee1e7613073bb9733dcc82c0eafa1392570c451':raise AssertionError('U6 imports changed')
            continue
        if isinstance(n, ast.ClassDef) and n.name == 'RepriceOperationContext':
            if digest(n) != 'bec7ee0f41c6b303f31d982e2efe6c2a1edbbfa64417aa6965c952d2a51d63c1':raise AssertionError('U6 context model changed')
            continue
        if isinstance(n, ast.ClassDef) and n.name == 'ApplyBody':
            if digest(n) != '66c68a6bdeaaf1e305d39a0e4b495e2e57761f4494e7fc66af83a4b560916f3b':raise AssertionError('U6 request model changed')
            n = ast.parse("class ApplyBody(BaseModel):\n    scope: str\n    expect_changed: int\n    expected: PreviewExpected\n    note: str = ''").body[0]
        nodes.append(n)
    out.body = nodes
    return out


def undo_freshness_baseline(node):
    """Project only the exact new log fields/preflight; historical hashes stay fixed."""
    out = u6_baseline(node)
    if out.name not in ('apply', 'undo'):
        return out
    body = next(n for n in out.body if isinstance(n, ast.With)).body
    def exact(nodes, wanted):
        if digest(ast.Module(body=nodes, type_ignores=[])) != wanted:
            raise AssertionError('undo freshness addition changed beyond approved nodes')
    if out.name == 'apply':
        additions = [n for n in body if assigned(n, 'after_locks')]
        if not additions:
            return out
        if len(additions) != 1:raise AssertionError('one after lock snapshot expected')
        exact(additions, '2961873f080c91ef5a7601415f3cbd324e648a24e4b9e4fd46d0b8aa859c2d88')
        body.remove(additions[0])
        loop = next(n for n in body if isinstance(n, ast.For))
        append = loop.body[-1]
        exact([append], '93acce48b45dacc1d4888e8d0d1ab0076076ff22964b3b9ac7720065662e116d')
        loop.body[-1] = ast.parse('before.append({"pc": t["product_code"], "sale": t["current"]})').body[0]
    else:
        indices = [i for i,n in enumerate(body) if assigned(n, 'invalid')]
        if not indices:
            return out
        if len(indices) != 1:raise AssertionError('one undo evidence validation expected')
        index = indices[0]
        exact(body[index:index+3], '893c2c952dc1bbd20474041a05541850c3bc93635d27c0dbbd52e6aefda42b41')
        body[index:index+3] = ast.parse('detail = row["detail"] if isinstance(row["detail"], dict) else json.loads(row["detail"])').body
        index = next(i for i,n in enumerate(body) if assigned(n, 'op')) - 1
        exact([body[index]], '2f53b5cf6af8b5b521ac81e82e2ed2223cc223ca19adaeb29e92a126474ab231')
        del body[index]
        preflight = next(n for n in body if isinstance(n, ast.For))
        exact([preflight], 'f6902c31c12c241188ac96140c447161a9b699cc889d8b000638373119ddd284')
        body.remove(preflight)
    return out


def project_after_log_state(state):
    result = deepcopy(state)
    for log in result[-1]:
        if log['action'] == '판매가 재산정':
            for item in log['detail']['before']:
                if set(item) != {'pc','sale','after_sale','after_locked_fields'}:
                    raise AssertionError('exact two new log leaves required')
                del item['after_sale']; del item['after_locked_fields']
    return result


def u4_baseline(node):
    """Remove exact U4 additions, leaving the literal accepted U2/C baseline."""
    out = undo_freshness_baseline(node)
    if out.name == 'preview':
        added = ast.parse('''classification, expected = _preview_plan(rows, scope, fee, margin, mmap)
result = _summary(classification, scope, fee, margin)
result["expected"] = expected
return result''').body
        if [ast.dump(n) for n in out.body[-4:]] != [ast.dump(n) for n in added]:
            raise AssertionError('preview changed beyond exact expected return addition')
        out.body[-4:] = ast.parse('return _summary(_classify(rows, fee, margin, mmap), scope, fee, margin)').body
    elif out.name == 'apply':
        added = ast.parse('''expected = body.expected.model_dump()
if expected["scope"] != body.scope:
    raise HTTPException(409, "미리보기 범위가 다릅니다 — 미리보기를 다시 확인하세요")''').body
        if [ast.dump(n) for n in out.body[2:4]] != [ast.dump(n) for n in added]:
            raise AssertionError('apply expected scope boundary differs')
        del out.body[2:4]
        body = next(n for n in out.body if isinstance(n, ast.With)).body
        for current, original in (
            ('c, initial_expected = _preview_plan(rows, body.scope, fee, margin, mmap)\n_require_expected(initial_expected, expected)',
             'c = _classify(rows, fee, margin, mmap)'),
            ('current_c, current_expected = _preview_plan(current_rows, body.scope, current_fee, current_margin, current_mmap)\n_require_expected(current_expected, expected)',
             'current_c = _classify(current_rows, current_fee, current_margin, current_mmap)')):
            wanted = ast.parse(current).body
            index = next(i for i, n in enumerate(body) if ast.dump(n) == ast.dump(wanted[0]))
            if ast.dump(body[index+1]) != ast.dump(wanted[1]):
                raise AssertionError('expected revalidation missing/moved')
            body[index:index+2] = ast.parse(original).body
    return out


def u4_module_baseline(tree):
    out = u6_module_baseline(tree)
    nodes = []
    for n in out.body:
        if isinstance(n, ast.FunctionDef) and n.name in ('_preview_plan', '_require_expected'):
            continue
        if isinstance(n, ast.ClassDef) and n.name == 'PreviewExpected':
            continue
        if isinstance(n, ast.ImportFrom) and n.module in ('typing', 'reprice_preview_expected'):
            continue
        if isinstance(n, ast.ImportFrom) and n.module == 'pydantic':
            if [a.name for a in n.names] != ['BaseModel', 'ConfigDict', 'Field']:
                raise AssertionError('unexpected pydantic import change')
            n.names = [ast.alias(name='BaseModel')]
        if isinstance(n, ast.ClassDef) and n.name == 'ApplyBody':
            expected = ast.parse('expected: PreviewExpected').body[0]
            matches = [v for v in n.body if ast.dump(v) == ast.dump(expected)]
            if len(matches) != 1:
                raise AssertionError('required expected field missing or altered')
            n.body.remove(matches[0])
        nodes.append(u4_baseline(n) if isinstance(n, ast.FunctionDef) else n)
    out.body = nodes
    return out


def policy_baseline(node):
    """Remove only E's exact first-call insertion for C's original AST baseline."""
    out = deepcopy(node)
    if out.name in ('apply','preview'):
        body = next(n for n in out.body if isinstance(n, ast.With)).body
        wanted = ast.parse('lock_pricing_policy_shared(conn)').body[0]
        if ast.dump(body[0]) != ast.dump(wanted):
            raise AssertionError('policy guard is not the exact first transaction statement')
        del body[0]
    return out


def restored(node):
    """Undo only authorized insertion sites; pre-change literal AST hash required."""
    out = policy_baseline(node)
    body = next(n for n in out.body if isinstance(n, ast.With)).body
    if out.name == 'apply':
        start = next(i for i,n in enumerate(body) if assigned(n, 'selected_rows'))
        end = next(i for i,n in enumerate(body[start:], start) if assigned(n, 'before'))
        del body[start:end]
        index = next(i for i,n in enumerate(body) if assigned(n, 'rows'))
        row_call = body[index].value
        del body[index]
        classification = next(n for n in body if assigned(n, 'c'))
        classification.value.args[0] = row_call
        wanted = APPLY_AST
    else:
        body[:] = [n for n in body if not isinstance(n, ast.Try)]
        for n in ast.walk(out):
            if isinstance(n, ast.Constant) and type(n.value) is str and n.value.startswith('SELECT detail, action FROM admin_operator_activity_logs'):
                n.value = n.value.removesuffix(' FOR UPDATE')
        wanted = UNDO_AST
    if digest(out) != wanted:
        raise AssertionError('original route AST changed beyond authorized guard sites')
    return out


def routes(original=False):
    tree = ast.parse((ROOT / 'api/admin_reprice.py').read_text(encoding='utf-8'))
    nodes = []
    if original:
        tree = u4_module_baseline(tree)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('MAX_APPLY','OUTLIER_X','SCOPES') for t in node.targets):
            nodes.append(deepcopy(node))
        if isinstance(node, ast.FunctionDef):
            n = (restored(node) if node.name in ('apply','undo') else policy_baseline(node)) if original else deepcopy(node)
            n.decorator_list = []
            nodes.append(n)
        if isinstance(node, ast.ClassDef):
            nodes.append(deepcopy(node))
    imported = ast.parse((ROOT / 'api/admin_price_import.py').read_text(encoding='utf-8'))
    nodes += [deepcopy(n) for n in imported.body if isinstance(n, ast.FunctionDef) and n.name == '_settings']
    taxonomy = ast.parse((ROOT / 'api/taxonomy.py').read_text(encoding='utf-8'))
    labels = next(ast.literal_eval(n.value) for n in taxonomy.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'PART_LABELS' for t in n.targets))
    env = dict(json=json, text=text, HTTPException=HTTPException, BaseModel=BaseModel,
               ConfigDict=ConfigDict, Field=Field, Literal=Literal,
               canonical_basis=canonical_basis, make_expected=make_expected, InvalidPreviewBasis=InvalidPreviewBasis,
               canonical_basis_v2=canonical_basis_v2, make_expected_v2=make_expected_v2,
               read_basis=read_basis, InvalidRepriceBasisSnapshot=InvalidRepriceBasisSnapshot,
               formula_text=formula_text, resolve_margins=resolve_margins, sale_from_purchase=sale_from_purchase,
               PART_LABELS=labels, lock_products=lock_products, ProductScopeChanged=ProductScopeChanged,
               lock_pricing_policy_shared=lock_pricing_policy_shared,
               MAX_SAFE_INTEGER=receipt_core.MAX_SAFE_INTEGER, UUID_PATTERN=receipt_core.UUID_PATTERN,
               prepare_reprice_operation=prepare_test_operation, lock_operation=receipt_core.lock_operation,
               lookup_operation=receipt_core.lookup_operation, operation_record=receipt_core.operation_record,
               store_operation=receipt_core.store_operation, ReceiptUnavailable=receipt_core.ReceiptUnavailable,
               OperationConflict=receipt_core.OperationConflict, PrewriteRejected=receipt_core.PrewriteRejected)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(ROOT / 'api/admin_reprice.py'), 'exec'), env)
    adapt_apply_model(env)
    return env


def product(pc, sale, **fields):
    row = dict(product_code=pc, product_name='product ' + str(pc), part_type='GPU', purchase_price=10000,
               sale_price=sale, status='판매중', stock_qty=7, locked_fields=[], category_id=None)
    row.update(fields)
    return row


def expected_snapshot(db, env, scope):
    """Build mock request input without extra SQL/actor calls in lock regressions."""
    rows = [deepcopy(r) for _, r in sorted(db.products.items())
            if r['purchase_price'] is not None and r['purchase_price'] > 0]
    if scope != 'all': rows = [r for r in rows if r['status'] == '판매중']
    if scope == 'live': rows = [r for r in rows if r['stock_qty'] > 0]
    mmap = {cid: m for cid, (m, _) in resolve_margins(db.categories, dict(db.policies), db.margin).items()}
    if '_preview_plan_v2' not in env:return env['_preview_plan'](rows, scope, db.fee, db.margin, mmap)[1]
    snapshot={'product_revisions':{r['product_code']:db.product_revisions[pc] for pc,r in db.products.items() if r in rows},
              'policy_revision':db.policy_revision}
    return env['_preview_plan_v2'](rows,scope,db.fee,db.margin,mmap,snapshot)[1]


class Result:
    def __init__(self, rows): self.rows = deepcopy(rows)
    def mappings(self): return self
    def scalars(self): return self
    def all(self): return deepcopy(self.rows)
    def first(self): return deepcopy(self.rows[0]) if self.rows else None
    def scalar(self): return self.first()
    def one(self):
        if len(self.rows) != 1: raise AssertionError('one row expected')
        return self.first()
    def scalar_one(self):return self.one()
    def __iter__(self): return iter(deepcopy(self.rows))


class Database:
    def __init__(self):
        rows = [product(101,18000), product(102,9000), product(103,10000), product(104,15000),
                product(105,11000), product(106,15000,locked_fields=['sale_price']), product(107,None,purchase_price=None)]
        self.product_revisions,self.policy_revision,self.next_revision={},1,1
        self.products = {r['product_code']:r for r in rows}
        self.fee, self.margin = .02, .03
        self.categories, self.policies, self.histories, self.logs = [], [], [], []
        self.calls, self.events = [], []
        self.after_lock = self.after_log_lock = self.fail = None
        self.lock_result = None
        self.commits = self.rollbacks = self.begins = self.connects = self.actor_calls = 0
        self.owner = True
        self.receipts = {}
        self.isolation_options = []
    @property
    def products(self):return self._products
    @products.setter
    def products(self,values):
        self._products=values
        for code in values:
            if code not in self.product_revisions:
                self.product_revisions[code]=self.next_revision;self.next_revision+=1
    def state(self):
        return deepcopy((self.products,self.fee,self.margin,self.categories,self.policies,self.histories,self.logs))
    def restore(self, state):
        self.products,self.fee,self.margin,self.categories,self.policies,self.histories,self.logs = deepcopy(state)
    def execution_options(self, **options):
        if options != {'isolation_level':'READ COMMITTED'}:raise AssertionError('exact isolation required')
        self.isolation_options.append(options);return self
    def begin(self): self.begins += 1; return Transaction(self, True)
    def connect(self): self.connects += 1; return Transaction(self, False)
    def operator(self): self.events.append(('owner',)); return {'role':'owner' if self.owner else 'staff','operator_id':21}
    def actor(self): self.actor_calls += 1; self.events.append(('actor',)); return 21
    def log(self, conn, action, target, detail, **kwargs):
        op = self.actor()
        self.events.append(('log',action))
        conn.maybe_fail('LOG ' + action, detail)
        log_id = max([99] + [r['log_id'] for r in self.logs]) + 1
        self.logs.append({'log_id':log_id,'operator_id':op,'action':action,'target':target,
                          'detail':deepcopy(detail),'kind':kwargs.get('kind')})
        return log_id


class Transaction:
    def __init__(self, db, writing): self.db,self.writing = db,writing
    def __enter__(self): self.conn = Connection(self.db); self.db.events.append(('begin' if self.writing else 'connect',)); return self.conn
    def __exit__(self, typ, val, trace):
        if self.writing:
            if typ:
                self.db.rollbacks += 1; self.db.restore(self.conn.snapshot)
                self.db.receipts = deepcopy(self.conn.receipt_snapshot)
                self.db.product_revisions,self.db.policy_revision=deepcopy(self.conn.revision_snapshot)
            else: self.db.commits += 1
        return False


class Connection:
    def __init__(self, db):
        self.db,self.snapshot = db,db.state()
        self.receipt_snapshot = deepcopy(db.receipts)
        self.revision_snapshot=deepcopy((db.product_revisions,db.policy_revision))
    def maybe_fail(self,q,params):
        if self.db.fail:
            error = self.db.fail(q,params)
            if error is not None: raise error
    def execute(self, statement, params=None):
        q = str(statement); params = params or {}; d = self.db
        d.calls.append((q,deepcopy(params))); d.events.append(('sql',q))
        self.maybe_fail(q,params)
        if q == POLICY_SHARED_SQL:
            if params != POLICY_PARAMS: raise AssertionError('unexpected policy lock key')
            return Result([])
        if q == receipt_core.OPERATION_LOCK_SQL:
            if params['namespace'] != receipt_core.OPERATION_NAMESPACE:raise AssertionError('operation namespace')
            return Result([])
        if q in (receipt_core.LOOKUP_SQL, receipt_core.OWN_LOOKUP_SQL):
            row = d.receipts.get((params['environment'],params['operation_id']))
            if row is not None and q == receipt_core.OWN_LOOKUP_SQL:
                if row['actor_id'] != params['actor_id'] or row['action'] != params['action']:row = None
            return Result([row] if row else [])
        if q == receipt_core.INSERT_SQL:
            key = (params['environment'],params['operation_id'])
            if key in d.receipts:raise RuntimeError('synthetic unique violation')
            row = deepcopy(params)
            row['result'] = json.loads(row['result']);row['response_body'] = json.loads(row['response_body'])
            receipt_core.operation_record(row);d.receipts[key] = row;return Result([])
        if q == _LOCK_PRODUCTS_SQL:
            if d.after_lock:
                callback,d.after_lock = d.after_lock,None; callback(d)
                self.snapshot = d.state()  # External committed change survives caller rollback.
                self.revision_snapshot=deepcopy((d.product_revisions,d.policy_revision))
            return Result(d.lock_result if d.lock_result is not None else [pc for pc in params['codes'] if pc in d.products])
        if q.lstrip().startswith('WITH scoped_products AS'):
            selected=[dict(r,pricing_basis_revision=d.product_revisions.get(pc)) for pc,r in sorted(d.products.items())
                      if r.get('purchase_price') is not None and (type(r['purchase_price']) is bool or r['purchase_price']>0)]
            selected.sort(key=lambda r:r['product_code'])
            if "p.status = '판매중'" in q:selected=[r for r in selected if r['status']=='판매중']
            if 'p.stock_qty > 0' in q:selected=[r for r in selected if r.get('stock_qty') is not None and r['stock_qty']>0]
            data={'products':selected,'settings':{'card_fee_rate':d.fee,'margin_rate':d.margin},
                  'nodes':sorted(d.categories),'margins':sorted(d.policies),
                  'policy_tokens':[{'singleton':1,'revision':d.policy_revision}]}
            def numeric_json(value):
                if isinstance(value,dict):return '{'+','.join(json.dumps(k)+':'+numeric_json(v) for k,v in value.items())+'}'
                if isinstance(value,(list,tuple)):return '['+','.join(numeric_json(v) for v in value)+']'
                if isinstance(value,Decimal):return str(value)
                return json.dumps(value)
            return Result([numeric_json(data)])
        if q.startswith('SELECT card_fee_rate, margin_rate'):
            return Result([(d.fee,d.margin)])
        if q.startswith('SELECT category_id, parent_id'): return Result(d.categories)
        if q.startswith('SELECT category_id, margin_rate'): return Result(d.policies)
        if q.startswith('SELECT p.product_code'):
            rows = [r for _pc,r in sorted(d.products.items()) if r['purchase_price'] is not None and r['purchase_price'] > 0]
            if "p.status = '판매중'" in q: rows = [r for r in rows if r['status'] == '판매중']
            if 'p.stock_qty > 0' in q: rows = [r for r in rows if r['stock_qty'] > 0]
            return Result(rows)
        if q.startswith('SELECT detail, action FROM admin_operator_activity_logs'):
            if q.endswith('FOR UPDATE') and d.after_log_lock:
                callback,d.after_log_lock = d.after_log_lock,None; callback(d)
                self.snapshot = d.state()
            return Result([{'detail':r['detail'],'action':r['action']} for r in d.logs if r['log_id'] == params['i']])
        if q.startswith('SELECT 1 FROM admin_operator_activity_logs'):
            rows = []
            for r in d.logs:
                try: detail = r['detail'] if type(r['detail']) is dict else json.loads(r['detail'])
                except (TypeError, ValueError): continue
                if type(detail) is dict and str(detail.get('ref_log_id')) == str(params['i']):rows.append(r)
            return Result([(1,)] if rows else [])
        if q.startswith('SELECT sale_price FROM products'):
            return Result([d.products[params['pc']]['sale_price']] if params['pc'] in d.products else [])
        if q.startswith('SELECT sale_price, locked_fields FROM products'):
            return Result([d.products[params['pc']]] if params['pc'] in d.products else [])
        if q.startswith('UPDATE products SET sale_price'):
            if params['pc'] not in d.products: raise AssertionError('unguarded missing product update')
            if d.products[params['pc']]['sale_price'] != params['v']:
                d.product_revisions[params['pc']]=d.next_revision;d.next_revision+=1
            d.products[params['pc']]['sale_price'] = params['v']; return Result([])
        if q.startswith('INSERT INTO product_price_history'):
            d.histories.append({'pc':params['pc'],'old':params['o'],'new':params['n'],'op':params['op'],
                                'reason':'margin_policy_undo' if 'margin_policy_undo' in q else 'margin_policy'})
            return Result([])
        raise AssertionError('unexpected source SQL: ' + q)


class RepriceTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(); self.env = routes()
        self.env.update(engine=self.db, current_operator=self.db.operator, current_operator_id=self.db.actor, _log=self.db.log)
    def apply(self, expected=4, scope='all', note='  note  '):
        basis_scope = scope if scope in self.env['SCOPES'] else 'all'
        token = expected_snapshot(self.db, self.env, basis_scope)
        body = self.env['ApplyBody'](scope=scope,expect_changed=expected,note=note,expected=token)
        return self.env['apply'](body)
    def seed_undo(self, before=None, detail=None):
        if detail is None: detail = {'scope':'all','before':before if before is not None else [{'pc':103,'sale':12000},{'pc':101,'sale':15000}]}
        if type(detail) is dict:
            detail = deepcopy(detail)
            for b in detail.get('before', []):
                b.update(after_sale=self.db.products[b['pc']]['sale_price'],
                         after_locked_fields=deepcopy(self.db.products[b['pc']]['locked_fields']))
        self.db.logs = [{'log_id':99,'action':'판매가 재산정','detail':deepcopy(detail)}]
    def undo(self): return self.env['undo'](SimpleNamespace(log_id=99))
    def writes(self): return [q for q,_p in self.db.calls if q.startswith(('UPDATE ','INSERT ','DELETE ')) and q != receipt_core.INSERT_SQL]
    def guards(self): return [p['codes'] for q,p in self.db.calls if q == _LOCK_PRODUCTS_SQL]
    def error(self, fn, status):
        with self.assertRaises(HTTPException) as caught: fn()
        self.assertEqual(caught.exception.status_code,status)
        self.assertEqual(self.writes(),[])
        return caught.exception

    def test_non_owned_AST_original_bodies_after_only_allowed_sites_and_readonly_sources(self):
        tree = u4_module_baseline(ast.parse((ROOT/'api/admin_reprice.py').read_text(encoding='utf-8')))
        rest = [policy_baseline(n) if isinstance(n,ast.FunctionDef) and n.name == 'preview' else n
                for n in tree.body if not (isinstance(n,ast.FunctionDef) and n.name in ('apply','undo','_selected_reprice_rows'))
                and not (isinstance(n,ast.ImportFrom) and n.module in ('pricing_write_guard_core','pricing_policy_guard_core'))]
        self.assertEqual(digest(ast.Module(body=rest,type_ignores=[])),REST_AST)
        for n in tree.body:
            if isinstance(n,ast.FunctionDef) and n.name in ('apply','undo'): restored(n)
        for name,wanted in READONLY.items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),wanted,name)

    def test_apply_locks_full_selected_ascending_preserves_up_down_write_order_and_current_reads(self):
        result = self.apply()
        self.assertEqual(self.db.calls[0],(POLICY_SHARED_SQL,POLICY_PARAMS))
        self.assertEqual(self.guards(),[[101,102,103,104]])
        self.assertEqual([p['pc'] for q,p in self.db.calls if q.startswith('UPDATE products')],[102,103,101,104])
        guard = next(i for i,(q,p) in enumerate(self.db.calls) if q == _LOCK_PRODUCTS_SQL)
        writes = next(i for i,(q,p) in enumerate(self.db.calls) if q.startswith('UPDATE '))
        self.assertEqual(sum(q.lstrip().startswith('WITH scoped_products AS') for q,p in self.db.calls[guard+1:writes]),1)
        self.assertEqual(sum(q.startswith('SELECT card_fee_rate') for q,p in self.db.calls[guard+1:writes]),0)
        self.assertTrue(all('FROM pricing_settings' in q for q,p in self.db.calls[guard+1:writes] if q.lstrip().startswith('WITH scoped_products AS')))
        self.assertEqual(sum(q.startswith('SELECT category_id') for q,p in self.db.calls[guard+1:writes]),0)
        self.assertTrue(all('FROM categories' in q and 'FROM category_margin_policies' in q for q,p in self.db.calls[guard+1:writes] if q.lstrip().startswith('WITH scoped_products AS')))
        self.assertEqual(result['changed'],4)
        self.assertEqual([h['old'] for h in self.db.histories],[9000,10000,18000,15000])
        self.assertEqual(self.db.logs[-1]['detail']['before'],[
            {'pc':pc,'sale':sale,'after_sale':11000,'after_locked_fields':[]}
            for pc,sale in ((102,9000),(103,10000),(101,18000),(104,15000))])
        actor = next(i for i,e in enumerate(self.db.events) if e[0] == 'actor')
        lock = next(i for i,e in enumerate(self.db.events) if e == ('sql',_LOCK_PRODUCTS_SQL))
        self.assertLess(actor,lock)  # Original post-selection actor lookup retained.
        self.assertEqual(self.db.actor_calls,2)

    def test_cap_selection_dropped_counts_no_unselected_locks_and_original_success_regression(self):
        for cap in (3,20000):
            self.setUp(); self.env['MAX_APPLY'] = cap
            original_db = Database(); original_env = routes(original=True)
            original_env.update(engine=original_db,current_operator=original_db.operator,current_operator_id=original_db.actor,_log=original_db.log,MAX_APPLY=cap)
            old = original_env['apply'](SimpleNamespace(scope='all',expect_changed=4,note='  note  '))
            new = self.apply()
            self.assertEqual({k:new[k] for k in old},old)
            self.assertEqual(set(new),set(old)|{'operation_receipt'})
            self.assertEqual(project_after_log_state(self.db.state()),original_db.state())
            self.assertEqual(self.guards(),[[101,102,103] if cap == 3 else [101,102,103,104]])
            self.assertEqual(new['dropped'],1 if cap == 3 else 0)
            self.assertEqual((new['up'],new['down'],new['locked']),(2,2,1))
            self.assertEqual(self.db.logs[-1]['detail']['margins_used'],{'0.03':6})

    def test_original_initial_permissions_scope_no_targets_preview_count_checks(self):
        self.db.owner = False; self.error(self.apply,403); self.assertEqual(self.db.begins,0)
        self.setUp(); self.error(lambda:self.apply(scope='bad'),400); self.assertEqual(self.db.begins,0)
        self.setUp(); error = self.error(lambda:self.apply(expected=3),409)
        self.assertEqual(error.detail,'미리보기 이후 값이 달라졌습니다 — 다시 확인해 주세요 (미리보기 3건 · 지금 4건)')
        self.assertEqual(self.guards(),[]); self.assertEqual(self.db.actor_calls,0)
        self.setUp(); self.db.products = {105:product(105,11000)}; self.error(lambda:self.apply(expected=0),400)
        self.assertEqual(self.guards(),[])

    def test_preview_adds_only_expected_to_exact_original_response_and_does_not_add_owner_check(self):
        self.db.owner = False
        original_db = Database(); oldenv = routes(original=True); oldenv.update(engine=original_db)
        old = oldenv['preview']('all'); new = self.env['preview']('all')
        self.assertEqual(new.pop('expected'),expected_snapshot(self.db,self.env,'all'))
        self.assertEqual(new,old); self.assertEqual(self.guards(),[]); self.assertEqual(self.db.actor_calls,0)
        self.assertEqual((self.db.begins,self.db.connects),(0,1)); self.assertEqual(self.writes(),[])

    def test_selected_null_sale_actual_before_and_original_note_bound(self):
        self.db.products = {108:product(108,None,purchase_price=12000)}
        result = self.apply(expected=1,note=' x '*200)
        self.assertEqual(result['changed'],1); self.assertEqual(self.guards(),[[108]])
        self.assertEqual(self.db.histories,[{'pc':108,'old':None,'new':13000,'op':21,'reason':'margin_policy'}])
        self.assertEqual(self.db.logs[-1]['detail']['before'],[{'pc':108,'sale':None,'after_sale':13000,'after_locked_fields':[]}])
        self.assertEqual(self.db.logs[-1]['detail']['note'],(' x '*200).strip()[:200])

    def test_disappearing_selected_product_409_before_any_business_write_no_retry(self):
        self.db.after_lock = lambda d:d.products.pop(101)
        self.error(self.apply,409)
        self.assertEqual(self.guards(),[[101,102,103,104]])
        self.assertNotIn(101,self.db.products); self.assertEqual((self.db.commits,self.db.rollbacks),(1,0))
        self.assertEqual(next(iter(self.db.receipts.values()))['state'],'rejected')

    def test_common_guard_strict_missing_extra_order_types_raise409_without_writes(self):
        for observed in ([101,102,103],[101,102,103,104,999],[104,103,102,101],[101,102,103,True],[101,102,103,'104']):
            self.setUp(); self.db.lock_result = observed; self.error(self.apply,409)
            self.assertEqual(len(self.guards()),1)

    def test_each_selected_writing_basis_field_change_rejected_even_same_proposal(self):
        changes = {'purchase_price':10001,'sale_price':9500,'locked_fields':['name'],'status':'품절',
                   'stock_qty':8,'category_id':44,'product_name':'renamed','part_type':'CPU'}
        for field,value in changes.items():
            self.setUp(); self.db.after_lock = lambda d,f=field,v=value:d.products[102].update({f:v})
            error = self.error(self.apply,409)
            self.assertEqual(error.detail,'재산정 대상 또는 계산 근거가 변경되었습니다 — 미리보기를 다시 확인하세요')
            self.assertEqual(self.guards(),[[101,102,103,104]])
            self.assertEqual(self.db.products[102][field],value)

    def test_selected_sale_lock_or_scope_eligibility_loss_rejected(self):
        for field,value in (('locked_fields',['sale_price']),('stock_qty',0),('status','품절')):
            self.setUp(); self.db.after_lock = lambda d,f=field,v=value:d.products[102].update({f:v})
            self.error(lambda:self.apply(scope='live'),409)
            self.assertEqual(len(self.guards()),1)

    def test_fee_default_or_effective_category_margin_changed_even_rounded_sale_unchanged(self):
        for field,value in (('fee',.0201),('margin',.0301)):
            self.setUp(); self.db.after_lock = lambda d,f=field,v=value:setattr(d,f,v)
            self.error(self.apply,409)
        self.setUp(); self.db.categories = [(1,None)]; self.db.policies = [(1,.03)]; self.db.products[102]['category_id'] = 1
        self.db.after_lock = lambda d:setattr(d,'policies',[(1,.0301)])
        self.error(self.apply,409)

    def test_same_total_different_cap_selection_or_order_409_no_late_expansion(self):
        self.env['MAX_APPLY'] = 3
        def change(d):
            d.products[100] = product(100,9000)
            d.products[104]['sale_price'] = 11000
        self.db.after_lock = change; self.error(self.apply,409)
        self.assertEqual(self.guards(),[[101,102,103]])
        self.setUp(); self.db.after_lock = lambda d:d.products[102].update(sale_price=13000)
        self.error(self.apply,409); self.assertEqual(len(self.guards()),1)

    def test_new_or_removed_uncapped_target_changes_expected_count_409(self):
        for change in (lambda d:d.products.update({109:product(109,9000)}),lambda d:d.products[104].update(sale_price=11000)):
            self.setUp(); self.env['MAX_APPLY'] = 3; self.db.after_lock = change
            self.error(self.apply,409); self.assertEqual(self.guards(),[[101,102,103]])

    def test_dropped_row_or_unused_policy_change_now_rejects_full_expected_without_expanding_locks(self):
        self.env['MAX_APPLY'] = 3
        def change(d):
            d.products[104]['sale_price'] = 12500
            d.categories = [(44,None)]; d.policies = [(44,.5)]  # No selected category44.
        self.db.after_lock = change
        self.error(self.apply,409)
        self.assertEqual(self.guards(),[[101,102,103]])
        self.assertEqual(self.db.products[104]['sale_price'],12500)
        self.assertEqual(self.db.policies,[(44,.5)])
        self.assertEqual((self.db.commits,self.db.rollbacks),(1,0))
        self.assertEqual(next(iter(self.db.receipts.values()))['state'],'rejected')

    def test_raw_apply_exceptions_identity_propagates_and_caller_rolls_back_partial_writes(self):
        predicates = [lambda q,p:q == _LOCK_PRODUCTS_SQL,lambda q,p:q.lstrip().startswith('WITH scoped_products AS') and len(self.guards())>0,
                      lambda q,p:q.startswith('UPDATE ') and p['pc']==103,lambda q,p:q.startswith('INSERT INTO product_price_history'),
                      lambda q,p:q.startswith('LOG ')]
        for predicate in predicates:
            self.setUp(); before = self.db.state(); error = RuntimeError('synthetic db failure')
            self.db.fail = lambda q,p,predicate=predicate:error if predicate(q,p) else None
            with self.assertRaises(RuntimeError) as caught:self.apply()
            self.assertIs(caught.exception,error); self.assertEqual(self.db.state(),before)
            self.assertEqual((self.db.commits,self.db.rollbacks),(0,1))
            self.assertLessEqual(len(self.guards()),1)

    def test_undo_original_log_first_then_sorted_products_and_actual_cur_original_order(self):
        self.seed_undo()
        result = self.undo()
        self.assertTrue(self.db.calls[0][0].endswith('FOR UPDATE'))
        self.assertIn('admin_operator_activity_logs',self.db.calls[0][0])
        self.assertEqual(self.guards(),[[101,103]])
        self.assertEqual([p['pc'] for q,p in self.db.calls if q.startswith('UPDATE ')],[103,101])
        self.assertEqual([(h['old'],h['new']) for h in self.db.histories],[(10000,12000),(18000,15000)])
        self.assertEqual(result,{'verdict':'2건의 판매가를 이전 값으로 되돌렸습니다','restored':2})
        self.assertEqual(self.db.logs[-1]['detail'],{'ref_log_id':99,'restored':2})

    def test_repeated_undo_product_codes_lock_once_but_each_original_restore_reads_fresh_cur(self):
        self.seed_undo(before=[{'pc':103,'sale':12000},{'pc':101,'sale':15000},{'pc':103,'sale':10000}])
        self.undo(); self.assertEqual(self.guards(),[[101,103]])
        self.assertEqual([h['pc'] for h in self.db.histories],[103,101,103])
        self.assertEqual([(h['old'],h['new']) for h in self.db.histories],[(10000,12000),(18000,15000),(12000,10000)])

    def test_missing_undo_product_409_entire_operation_no_partial_restore(self):
        self.seed_undo(); self.db.after_lock = lambda d:d.products.pop(101)
        self.error(self.undo,409); self.assertEqual(self.db.histories,[]); self.assertEqual(len(self.db.logs),1)
        self.assertEqual(self.db.products[103]['sale_price'],10000)

    def test_same_undo_one_success_then_exact_duplicate409_original_log_locked_both(self):
        self.seed_undo(); first = self.undo(); start = len(self.db.calls)
        histories = deepcopy(self.db.histories)
        with self.assertRaises(HTTPException) as caught:self.undo()
        self.assertEqual((caught.exception.status_code,caught.exception.detail),(409,'이미 되돌린 기록입니다'))
        self.assertTrue(self.db.calls[start][0].endswith('FOR UPDATE'))
        self.assertEqual(self.db.histories,histories); self.assertEqual(len(self.db.logs),2)
        self.assertEqual((self.db.commits,self.db.rollbacks),(1,1)); self.assertEqual(first['restored'],2)
        self.assertEqual(len(self.guards()),1)

    def test_duplicate_arrives_at_original_log_lock_checked_before_product_scope(self):
        self.seed_undo()
        self.db.after_log_lock = lambda d:d.logs.append({'log_id':100,'action':'판매가 재산정 되돌림','detail':{'ref_log_id':99}})
        error = self.error(self.undo,409)
        self.assertEqual(error.detail,'이미 되돌린 기록입니다'); self.assertEqual(self.guards(),[])
        self.assertEqual(self.db.actor_calls,0)

    def test_undo_original_404_duplicate409_empty400_and_json_detail_support(self):
        self.error(self.undo,404); self.assertEqual(self.guards(),[])
        self.setUp(); self.seed_undo(); self.db.logs[0]['action'] = 'other'; self.error(self.undo,404)
        self.setUp(); self.seed_undo(detail={'before':[]}); self.error(self.undo,400); self.assertEqual(self.guards(),[])
        self.setUp(); self.seed_undo(detail=json.dumps({'before':[{'pc':103,'sale':None,'after_sale':10000,'after_locked_fields':[]}]})); self.undo()
        self.assertIsNone(self.db.products[103]['sale_price']); self.assertEqual(self.db.logs[-1]['target'],'—')

    def test_valid_undo_preserves_original_result_history_and_actor_policy(self):
        self.seed_undo(); before = self.db.state()
        olddb = Database(); olddb.restore(before); oldenv = routes(original=True)
        oldenv.update(engine=olddb,current_operator=olddb.operator,current_operator_id=olddb.actor,_log=olddb.log)
        old = oldenv['undo'](SimpleNamespace(log_id=99)); new = self.undo()
        self.assertEqual(new,old); self.assertEqual(self.db.state(),olddb.state())
        self.assertEqual(self.db.actor_calls,olddb.actor_calls)

    def test_raw_undo_exceptions_propagate_caller_rollback_all_restores_and_logs(self):
        for prefix in ('SELECT detail, action','SELECT sale_price',_LOCK_PRODUCTS_SQL,'UPDATE products','INSERT INTO product_price_history','LOG '):
            self.setUp(); self.seed_undo(); before = self.db.state(); error = RuntimeError('synthetic undo failure')
            self.db.fail = lambda q,p,prefix=prefix:error if q.startswith(prefix) else None
            with self.assertRaises(RuntimeError) as caught:self.undo()
            self.assertIs(caught.exception,error); self.assertEqual(self.db.state(),before)
            self.assertEqual((self.db.commits,self.db.rollbacks),(0,1))

    def test_selected_AST_environment_never_imports_operational_modules_or_owns_other_transactions(self):
        self.apply()
        self.assertNotIn('api.db',self.env); self.assertNotIn('router',self.env)
        self.assertEqual((self.db.begins,self.db.connects),(1,0))
        self.assertFalse(any('product_supplier_prices' in q for q,p in self.db.calls))


if __name__ == '__main__': unittest.main(verbosity=2)
