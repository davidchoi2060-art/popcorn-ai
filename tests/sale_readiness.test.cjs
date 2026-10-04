/* Regression: stale requests cannot restore green evidence after a new selection or failure. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createController, safeHref, readItem, basisLabel, checkLabel} = require('../mockups/shared/admin-sale-readiness.js');
const item = (id, state = 'basis_met') => ({id, name:'격리 검사 항목 ' + id, code:'', state, state_label:'판매 가능', reasons:[], checks:[{key:'evidence', label:'근거', state:state === 'basis_met' ? 'met' : 'unknown', detail:''}], href:'/admin2/pc-workspace?id=' + id});
function page(scope, items, offset = 0, total = items.length) {
  const counts = {needs_work:0, needs_check:0, basis_met:0, excluded:0};
  items.forEach(row => counts[row.state]++);
  counts.basis_met += total - items.length;
  return {scope, items, counts, total, offset, limit:40, note:'격리 응답'};
}
function deferred() { let resolve, reject; const promise = new Promise((a,b) => {resolve = a; reject = b;}); return {promise, resolve, reject}; }
function queue() { const requests = []; return {requests, get(url) { const request = deferred(); requests.push({url,...request}); return request.promise; }}; }

test('late list response cannot restore the old scope or its selected ready item', async () => {
  const io = queue(), controller = createController(io);
  const old = controller.load(), current = controller.setScope('parts');
  io.requests[1].resolve(page('parts',[item('new','needs_check')]));
  await Promise.resolve();
  assert.match(io.requests[2].url,/\/parts\/new$/);
  io.requests[2].resolve(item('new','needs_check')); await current;
  io.requests[0].resolve(page('configurations',[item('old')])); await old;
  assert.equal(controller.state.scope,'parts'); assert.equal(controller.state.selectedId,'new');
  assert.equal(controller.state.counts.basis_met,0); assert.equal(controller.state.detail.state,'needs_check');
});
test('late detail response cannot replace a different selected identity', async () => {
  const io = queue(), controller = createController(io);
  const load = controller.load(); io.requests[0].resolve(page('configurations',[item('one'),item('two','needs_check')])); await Promise.resolve();
  const select = controller.select('two');
  io.requests[2].resolve(item('two','needs_check')); await select;
  io.requests[1].resolve(item('one')); await load;
  assert.equal(controller.state.selectedId,'two'); assert.equal(controller.state.detail.id,'two');
});
test('list and detail failures clear obsolete counts, selection and ready evidence', async () => {
  let fail = false, failDetail = false;
  const controller = createController({get:async url => {
    if (fail || (failDetail && !url.includes('?'))) throw Object.assign(new Error(),{status:503});
    return url.includes('?') ? page('configurations',[item('one')]) : item('one');
  }});
  await controller.load(); assert.equal(controller.state.counts.basis_met,1);
  fail = true; await controller.load();
  assert.equal(controller.state.status,'error'); assert.equal(controller.state.counts,null); assert.equal(controller.state.detail,null); assert.equal(controller.state.selectedId,null);
  fail = false; failDetail = true; await controller.load();
  assert.equal(controller.state.counts,null); assert.deepEqual(controller.state.items,[]);
  failDetail = false; await controller.load(); assert.equal(controller.state.detail.id,'one');
});
test('debounced search invalidates in-flight evidence immediately and fetches only the latest query', async () => {
  const io = queue(), tasks = new Map(); let next = 0;
  io.schedule = fn => {tasks.set(++next,fn); return next;}; io.cancel = id => tasks.delete(id);
  const controller = createController(io); const old = controller.load();
  controller.search('old search'); controller.search('새 검색');
  assert.equal(tasks.size,1); assert.equal(controller.state.counts,null); assert.equal(controller.state.selectedId,null);
  io.requests[0].resolve(page('configurations',[item('old')])); await old;
  assert.equal(controller.state.status,'loading');
  [...tasks.values()][0](); assert.equal(io.requests.length,2);
  assert.equal(new URL(io.requests[1].url,'https://local.example').searchParams.get('q'),'새 검색');
  io.requests[1].resolve(page('configurations',[])); await Promise.resolve();
  assert.equal(controller.state.status,'ready'); assert.equal(controller.state.total,0); assert.equal(controller.state.detail,null);
});
test('pagination uses server total and clears a selection missing from the next page', async () => {
  const urls = [];
  const controller = createController({get:async url => {
    urls.push(url); if (!url.includes('?')) return item(url.endsWith('two') ? 'two' : 'one');
    const offset = Number(new URL(url,'https://local.example').searchParams.get('offset'));
    return page('configurations',[item(offset ? 'two' : 'one')],offset,41);
  }});
  await controller.load(); await controller.page(1);
  assert.equal(controller.state.offset,40); assert.equal(controller.state.selectedId,'two'); assert.equal(controller.state.detail.id,'two');
  assert.match(urls[2],/offset=40/); const before = urls.length; await controller.page(1); assert.equal(urls.length,before);
  await controller.page(-1); assert.equal(controller.state.selectedId,'one');
});
test('safe resolution links allow existing paths and encoded workspace identity only', () => {
  const origin = 'https://admin.example';
  assert.equal(safeHref('/admin2/pc-workspace?id=a%2Fb&admin=new',origin),'/admin2/pc-workspace?id=a%2Fb&admin=new');
  assert.equal(safeHref('/admin2/reviews?keyword=%3Cimg%3E',origin),'/admin2/reviews?keyword=%3Cimg%3E');
  for (const href of ['javascript:alert(1)','//evil.example/admin2/products','https://evil.example/admin2/products','/admin2/../admin2/products','/admin2/%70roducts','/admin2/products?next=https://evil.example','/admin2/login','/admin2/products#unsafe','/admin2\\products']) assert.equal(safeHref(href,origin),null,href);
});
test('unknown evidence cannot be green and basis labels never imply sale or payment readiness', () => {
  assert.equal(basisLabel('parts'),'추천 근거 충족'); assert.equal(basisLabel('configurations'),'등록 근거 충족'); assert.equal(checkLabel('unknown'),'확인 필요');
  const unknown = item('one'); unknown.checks[0].state = 'unknown'; assert.throws(() => readItem(unknown),/inconsistent basis/);
  unknown.state = 'needs_check'; assert.equal(readItem(unknown).checks[0].state,'unknown');
  unknown.state = 'ready'; assert.throws(() => readItem(unknown),/invalid item/);
});
test('malformed or mismatched response fails closed instead of showing plausible counts', async () => {
  const controller = createController({get:async () => ({...page('parts',[item('one')]),total:3})});
  await controller.load(); assert.equal(controller.state.status,'error'); assert.equal(controller.state.counts,null); assert.deepEqual(controller.state.items,[]);
});
test('deletion on a later page returns to a valid page without preserving a stale selection', async () => {
  const offsets = []; let shrank = false;
  const controller = createController({get:async url => {
    if (!url.includes('?')) return item('one');
    const offset = Number(new URL(url,'https://local.example').searchParams.get('offset')); offsets.push(offset);
    if (offset) { shrank = true; return page('configurations',[],offset,1); }
    return page('configurations',[item('one')],0,shrank ? 1 : 41);
  }});
  await controller.load(); await controller.page(1);
  assert.deepEqual(offsets,[0,40,0]); assert.equal(controller.state.offset,0); assert.equal(controller.state.total,1); assert.equal(controller.state.detail.id,'one');
});
