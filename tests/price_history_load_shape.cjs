"use strict";
// ADMIN-PRICE-HISTORY-READ-AUDIT — 가격 이력 화면(price_history.html.j2)의 조회 load()를
// «실제 페이지 스크립트» 통째로 실행한다. 실제 Admin2Text(admin2-text.js)와 실제
// errText(ui-progress.js 본문에서 그 함수만)를 읽어 쓴다. 가짜 DOM·가짜 fetch·가짜 자료만 쓴다.
// 실제 API·DB·가격 없음. 부품 종류 보조 GET(/api/admin/products/{code})도 가짜다.
//
// 결함 ①(D1·D2): HTTP 200 인데 본문이 깨졌거나(HTML·빈 본문·null·false·0·문자열·배열·{})
//   products/items 가 배열이 아니거나 product 가 빠지면
//   - 「불러오는 중…」이 영원히 남거나(오류도 다시 시도도 없음)
//   - 없는 자료를 「정당한 빈 결과(오류가 아닙니다)」로 그렸다.
// 결함 ②(D3): 요청 순번이 없어 늦게 도착한 이전 요청의 정상·500·404 응답이 최신 상품·기간
//   화면을 덮거나, 최신 선택을 풀고 추가 조회를 일으켰다.
// 기대: 형식 오류는 「조회 실패」+다시 시도로 드러내고(404 재시도 분기로 위장하지 않음),
//   가장 최근 load() 의 응답만 반영한다. 정상 0건(product:null, by_supplier·unmapped_reasons·
//   series·note 없음 포함)은 오류가 아니다. 선택 상품 404 는 선택 해제 후 1회 기본 재조회·
//   기간 보존·2차 404 루프 차단을 유지한다.
// 기준 비교: PH_TEMPLATE=<다른 price_history.html.j2 경로> 로 같은 검사를 그 파일에 돌린다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const TPL = process.env.PH_TEMPLATE || path.join(ROOT, 'templates/admin/price_history.html.j2');
const tpl = fs.readFileSync(TPL, 'utf8');
const m = tpl.match(/\{% raw %\}\s*<script>([\s\S]*?)<\/script>\s*\{% endraw %\}/);
assert.ok(m, 'foot_extra raw <script> 블록을 찾지 못함');
const SCRIPT = m[1];
assert.ok(!/\{\{|\{%/.test(SCRIPT), 'Jinja 자리표시자가 script 안에 남음');
const TEXT_JS = fs.readFileSync(path.join(ROOT, 'mockups/shared/admin2/admin2-text.js'), 'utf8');
const UIP = fs.readFileSync(path.join(ROOT, 'mockups/shared/ui-progress.js'), 'utf8');
function extractFn(src, name) {
  const i = src.indexOf('function ' + name + '(');
  assert.ok(i >= 0, name + ' 함수를 찾지 못함');
  let d = 0;
  for (let k = src.indexOf('{', i); k < src.length; k++) {
    if (src[k] === '{') d++;
    else if (src[k] === '}' && --d === 0) return src.slice(i, k + 1);
  }
  throw new Error('함수 끝을 찾지 못함: ' + name);
}
const ERRTEXT = extractFn(UIP, 'errText');

// ── 가짜 DOM: 이 스크립트가 쓰는 API 만 흉내낸다 ─────────────────────────
class El {
  constructor(id) { this.id = id; this.hidden = false; this._html = ''; this._text = ''; this.value = ''; this.attrs = {}; this.cls = new Set(); }
  set innerHTML(v) { this._html = String(v); this._text = ''; }
  get innerHTML() { return this._html; }
  set textContent(v) { this._text = String(v); this._html = ''; }
  get textContent() { return this._text || this._html.replace(/<[^>]*>/g, ''); }
  getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  get classList() { const s = this.cls; return { toggle: (c, on) => (on ? s.add(c) : s.delete(c)), contains: (c) => s.has(c) }; }
  closest(sel) { const mm = /^\[(.+)\]$/.exec(sel); return mm && this.attrs[mm[1]] != null ? this : null; }
  querySelectorAll(sel) {
    if (sel !== '.ph-item') return [];
    const owner = this, out = [];
    const re = /<button type="button" class="ph-item(?: on)?"[^>]*data-code="([^"]*)"/g;
    let r;
    while ((r = re.exec(this._html))) {
      const code = r[1], b = new El(null);
      b.attrs['data-code'] = code;
      Object.defineProperty(b, 'classList', { get() { return { toggle(c, on) {
        if (c !== 'on') return;
        owner._html = owner._html.replace(new RegExp('class="ph-item(?: on)?"([^>]*data-code="' + code + '")'), 'class="ph-item' + (on ? ' on' : '') + '"$1');
      }, contains() { return false; } }; } });
      out.push(b);
    }
    return out;
  }
}

function boot(opts) {
  opts = opts || {};
  const ids = ['phLoading', 'phErrBox', 'phErrMsg', 'phBody', 'phFrom', 'phTo', 'phGlobalSummary', 'phRangeErr', 'phProdCount',
    'phSearch', 'phList', 'phCard', 'phLatestNote', 'phChartWrap', 'phTable', 'phFoot'];
  const els = {};
  ids.forEach((id) => { els[id] = new El(id); });
  els.phErrBox.hidden = true; els.phBody.hidden = true; els.phRangeErr.hidden = true;
  const modeBtns = ['kept', 'all'].map((md) => { const b = new El(null); b.attrs['data-action'] = 'set-mode'; b.attrs['data-mode'] = md; if (md === 'kept') b.cls.add('on'); return b; });
  const listeners = {};
  const document = {
    getElementById(id) {
      if (els[id]) return els[id];
      for (const k of ids) { // 동적 자식(phCardCat) — 부모 innerHTML 안 span 내용을 바꾼다
        const needle = 'id="' + id + '">';
        if (els[k]._html.indexOf(needle) < 0) continue;
        const e = new El(id);
        Object.defineProperty(e, 'textContent', {
          set(v) { const p = els[k]; const s = p._html.indexOf(needle) + needle.length; const end = p._html.indexOf('</span>', s);
            p._html = p._html.slice(0, s) + String(v).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])) + p._html.slice(end); },
          get() { return ''; },
        });
        return e;
      }
      return null;
    },
    querySelectorAll(sel) { return sel === '[data-action="set-mode"]' ? modeBtns : []; },
    addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
  };
  const calls = [];
  const fetch = (url, init) => new Promise((resolve, reject) => { calls.push({ url: String(url), init, resolve, reject, settled: false }); });
  const unhandled = [];
  const ctx = { document, fetch, Response, console, setTimeout, clearTimeout, Promise };
  ctx.window = ctx;
  ctx.PH_REASON_LINKS = { margin_policy: { available: true, href: 'x-review' }, margin_policy_bulk: { available: false, reason: '가짜 미연결' } };
  vm.createContext(ctx);
  vm.runInContext(TEXT_JS, ctx, { filename: 'admin2-text.js' });
  if (!opts.noProgress) vm.runInContext(ERRTEXT + '\nwindow.popcornProgress = { errText: errText };', ctx, { filename: 'ui-progress.errText' });
  vm.runInContext(SCRIPT, ctx, { filename: 'price_history.inline.js' });
  const onRej = (e) => unhandled.push(e);
  process.on('unhandledRejection', onRej);

  const flush = async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setImmediate(r)); };
  function settle(c, r) {
    assert.equal(c.settled, false, '같은 요청을 두 번 응답함: ' + c.url);
    c.settled = true;
    if (r === 'net') return c.reject(new TypeError('Failed to fetch'));
    const body = typeof r[1] === 'string' ? r[1] : JSON.stringify(r[1]);
    c.resolve(new Response(body, { status: r[0], headers: { 'content-type': r[2] || 'application/json' } }));
  }
  function fire(type, target) { (listeners[type] || []).forEach((fn) => fn({ target })); }
  function click(action, attrs) { const t = new El(null); t.attrs['data-action'] = action; Object.assign(t.attrs, attrs || {}); fire('click', t); }
  const phCalls = () => calls.filter((c) => c.url.startsWith('/api/admin/price-history'));
  const ptCalls = () => calls.filter((c) => c.url.startsWith('/api/admin/products/'));
  const view = () => ({
    loading: !els.phLoading.hidden, err: !els.phErrBox.hidden, body: !els.phBody.hidden,
    errMsg: els.phErrMsg.textContent, summary: els.phGlobalSummary.textContent,
    list: els.phList.innerHTML, card: els.phCard.innerHTML, table: els.phTable.innerHTML, chart: els.phChartWrap.innerHTML,
    onCode: (/class="ph-item on"[^>]*data-code="(\d+)"/.exec(els.phList.innerHTML) || [])[1] || null,
    cardCode: (/FAKE-(\d+)/.exec(els.phCard.innerHTML) || [])[1] || null,
    rows: (els.phTable.innerHTML.match(/class="ph-row/g) || []).length,
    modeOn: modeBtns.filter((b) => b.cls.has('on')).map((b) => b.attrs['data-mode']),
  });
  const done = () => { process.off('unhandledRejection', onRej); assert.deepEqual(unhandled, [], '처리되지 않은 Promise 거부'); };
  return { els, calls, phCalls, ptCalls, settle, flush, click, fire, view, done };
}

// ── 가짜 응답 (api/admin_price_history.py 반환 모양 그대로 · 값은 전부 가짜) ─────────
function item(id, at, field, oldp, newp, reason, ref) {
  return { id, at, field, field_label: field === 'sale' ? '판매가' : '매입가', old: oldp, new: newp,
    delta: oldp != null && newp != null ? newp - oldp : null, reason, reason_label: '가짜라벨-' + reason,
    reason_link: 'x', ref_id: ref, supplier: field === 'purchase' ? '가짜공급처' : null };
}
function okPayload(code, items) {
  return {
    products: [{ product_code: 111, sku: 'FAKE-111', name: '가짜상품A', count: 4 }, { product_code: 222, sku: 'FAKE-222', name: '가짜상품B', count: 4 }],
    product: { product_code: code, sku: 'FAKE-' + code, name: '가짜상품' + code, purchase: 800, sale: 1000 },
    items: items || [
      item(code * 10 + 4, '2026-01-04T00:00:00+09:00', 'sale', 1100, 1000, 'margin_policy_undo', null),
      item(code * 10 + 3, '2026-01-03T00:00:00+09:00', 'sale', 1000, 1100, 'margin_policy', null),
      item(code * 10 + 2, '2026-01-02T00:00:00+09:00', 'purchase', 700, 800, 'sourcing', 5),
      item(code * 10 + 1, '2026-01-01T00:00:00+09:00', 'sale', 900, 1000, 'price_import', 9),
    ],
    series: { sale: [], purchase: [] }, by_supplier: [{ supplier: '가짜공급처', points: [] }], note: '가짜 노트', unmapped_reasons: [],
  };
}
const OK = (c) => [200, okPayload(c)];
const ZERO = { products: [], items: [], series: { sale: [], purchase: [] }, product: null, note: '가격 이력이 아직 없습니다.' };
const FMT = '응답 형식이 올바르지 않습니다 (HTTP 200)';

async function start(first, opts) {
  const e = boot(opts);
  await e.flush();
  assert.equal(e.phCalls().length, 1);
  assert.equal(e.phCalls()[0].url, '/api/admin/price-history');
  assert.equal(e.phCalls()[0].init.credentials, 'same-origin');
  if (first) { e.settle(e.phCalls()[0], first); await e.flush(); }
  return e;
}
const state = (v) => [v.loading, v.err, v.body];

// ── 정상 계약 (수정 전후 동일해야 함) ─────────────────────────────────────
test('정상 양수: 요약·목록 선택·카드·kept 짝짓기·모드 전환 재조회 0·부품 종류 보조 GET 1회', async () => {
  const e = await start(OK(111));
  let v = e.view();
  assert.deepEqual(state(v), [false, false, true]);
  assert.match(v.summary, /전체 이력 8건\(상품 2개\)/);
  assert.equal(v.onCode, '111');
  assert.match(v.card, /확인 중…/);
  assert.equal(v.rows, 2, 'kept: margin_policy+undo 짝 제외');
  assert.equal(e.ptCalls().length, 1);
  assert.equal(e.ptCalls()[0].url, '/api/admin/products/111');
  e.settle(e.ptCalls()[0], [200, { cat: '가짜CPU' }]); await e.flush();
  assert.match(e.view().card, /가짜CPU/);
  e.click('set-mode', { 'data-mode': 'all' }); await e.flush();
  v = e.view();
  assert.equal(v.rows, 4); assert.deepEqual(v.modeOn, ['all']);
  assert.match(v.card, /가짜CPU/);
  assert.equal(e.phCalls().length, 1);
  e.done();
});

test('정상 0건: product:null·by_supplier/unmapped_reasons 없음 → 정당한 빈 결과, 보조 GET 0', async () => {
  const e = await start([200, ZERO]);
  const v = e.view();
  assert.deepEqual(state(v), [false, false, true]);
  assert.match(v.table, /가격 이력이 아직 없습니다\./);
  assert.match(v.table, /정당하게 빈 결과/);
  assert.match(v.card, /선택된 상품이 없습니다/);
  assert.match(v.list, /이 기간에 변동이 있던 상품이 없습니다/);
  assert.match(v.summary, /전체 이력 0건\(상품 0개\)/);
  assert.equal(e.ptCalls().length, 0);
  e.done();
});

test('정상 0건: 화면이 읽지 않는 series·note 까지 없어도 오류가 아니다(필수화 0)', async () => {
  const e = await start([200, { products: [], items: [], product: null }]);
  const v = e.view();
  assert.deepEqual(state(v), [false, false, true]);
  assert.match(v.table, /이 기간에는 가격 변동 이력이 없습니다/);
  e.done();
});

test('정상 양수: by_supplier·unmapped_reasons·series·note 가 빠져도 정상 표시', async () => {
  const p = okPayload(111); delete p.by_supplier; delete p.unmapped_reasons; delete p.series; delete p.note;
  const e = await start([200, p]);
  const v = e.view();
  assert.deepEqual(state(v), [false, false, true]);
  assert.equal(v.rows, 2);
  e.done();
});

test('정상 양수: 0원·비움(new null)·이전 값 없음(old null)·현재가 null 을 구분해 표시', async () => {
  const items = [
    item(3, '2026-01-03T00:00:00+09:00', 'sale', 0, null, 'manual', 1),
    item(2, '2026-01-02T00:00:00+09:00', 'sale', 500, 0, 'manual', 1),
    item(1, '2026-01-01T00:00:00+09:00', 'sale', null, 500, 'manual', 1),
  ];
  const p = okPayload(111, items); p.product.sale = null; p.product.purchase = 0;
  const e = await start([200, p]);
  const v = e.view();
  assert.deepEqual(state(v), [false, false, true]);
  assert.equal(v.rows, 3);
  assert.match(v.table, /ph-evt cleared[^>]*>비움</, '비움 배지');
  assert.match(v.table, /ph-evt noprior[^>]*>이전 값 없음</, '이전 값 없음 배지');
  assert.match(v.table, />0원</, '0원은 값');
  assert.match(v.table, /-500원/);
  assert.match(v.table, />설정</);
  assert.match(v.card, /지금 판매가 <b class="num">—<\/b>/);
  assert.match(v.card, /매입가 <b class="num">0원<\/b>/);
  e.done();
});

for (const st of [401, 500]) {
  test(`HTTP ${st} → 조회 실패 + 서버 문장, 다시 시도는 같은 질의 1회 재조회 후 회복`, async () => {
    const e = await start([st, { detail: '가짜 ' + st + ' 문장' }]);
    let v = e.view();
    assert.deepEqual(state(v), [false, true, false]);
    assert.equal(v.errMsg, '가짜 ' + st + ' 문장');
    e.click('retry'); await e.flush();
    assert.equal(e.phCalls().length, 2);
    assert.equal(e.phCalls()[1].url, '/api/admin/price-history');
    assert.deepEqual(state(e.view()), [true, false, false]);
    e.settle(e.phCalls()[1], OK(111)); await e.flush();
    v = e.view();
    assert.deepEqual([v.err, v.body], [false, true]);
    e.done();
  });
}

test('HTTP 500 비JSON 본문 → 「오류 500 — GET /api/admin/price-history」', async () => {
  const e = await start([500, '<html>bad</html>', 'text/html']);
  assert.equal(e.view().errMsg, '오류 500 — GET /api/admin/price-history');
  e.done();
});

test('popcornProgress 가 없으면 「오류 500」 폴백', async () => {
  const e = await start([500, { detail: 'x' }], { noProgress: true });
  assert.equal(e.view().errMsg, '오류 500');
  e.done();
});

test('HTTP 400(기간) → 기존 행동 유지(이번 범위 밖 F3): 조회 실패, 다시 시도는 같은 기간 재전송', async () => {
  const e = await start(OK(111));
  e.els.phFrom.value = '2026-01-01'; e.els.phTo.value = '2026-01-31';
  e.click('apply-range'); await e.flush();
  const q = '/api/admin/price-history?date_from=2026-01-01&date_to=2026-01-31';
  assert.equal(e.phCalls()[1].url, q);
  e.settle(e.phCalls()[1], [400, { detail: '기간은 YYYY-MM-DD 형식으로 입력하세요' }]); await e.flush();
  let v = e.view();
  assert.deepEqual([v.err, v.body], [true, false]);
  assert.match(v.errMsg, /YYYY-MM-DD/);
  e.click('retry'); await e.flush();
  assert.equal(e.phCalls()[2].url, q);
  e.done();
});

test('404(선택 상품) → 선택 해제 후 기본 조회 정확히 1회, 2차 404 는 루프 없이 오류', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  assert.equal(e.phCalls()[1].url, '/api/admin/price-history?product_code=222');
  e.settle(e.phCalls()[1], [404, { detail: '해당 상품의 가격 이력이 없습니다' }]); await e.flush();
  assert.equal(e.phCalls().length, 3);
  assert.equal(e.phCalls()[2].url, '/api/admin/price-history');
  e.settle(e.phCalls()[2], [404, { detail: '해당 상품의 가격 이력이 없습니다' }]); await e.flush();
  assert.equal(e.phCalls().length, 3, '추가 재시도 없음');
  assert.equal(e.view().err, true);
  assert.equal(e.view().errMsg, '해당 상품의 가격 이력이 없습니다');
  e.done();
});

test('404 후 기본 재조회 성공 → 기본 상품으로 회복, 기간 보존', async () => {
  const e = await start(OK(111));
  e.els.phFrom.value = '2026-01-01'; e.click('apply-range'); await e.flush();
  e.settle(e.phCalls()[1], OK(111)); await e.flush();
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  assert.equal(e.phCalls()[2].url, '/api/admin/price-history?product_code=222&date_from=2026-01-01');
  e.settle(e.phCalls()[2], [404, { detail: 'x' }]); await e.flush();
  assert.equal(e.phCalls()[3].url, '/api/admin/price-history?date_from=2026-01-01');
  e.settle(e.phCalls()[3], OK(111)); await e.flush();
  const v = e.view();
  assert.equal(v.body, true);
  assert.equal(v.cardCode, '111');
  e.done();
});

test('product_code 없는 조회의 404 는 재시도하지 않고 오류', async () => {
  const e = await start([404, { detail: '가짜 404' }]);
  assert.equal(e.phCalls().length, 1);
  assert.equal(e.view().err, true);
  e.done();
});

test('network 실패 → 조회 실패(Failed to fetch), 다시 시도 회복', async () => {
  const e = await start('net');
  let v = e.view();
  assert.equal(v.err, true); assert.equal(v.errMsg, 'Failed to fetch');
  e.click('retry'); await e.flush();
  e.settle(e.phCalls()[1], OK(111)); await e.flush();
  v = e.view();
  assert.deepEqual([v.err, v.body], [false, true]);
  e.done();
});

test('kept/all 모드·검색어는 상품 선택·기간 조회·오류 회복 뒤에도 보존', async () => {
  const e = await start(OK(111));
  e.click('set-mode', { 'data-mode': 'all' }); await e.flush();
  e.els.phSearch.value = 'fake-222'; e.fire('input', e.els.phSearch); await e.flush();
  assert.doesNotMatch(e.view().list, /data-code="111"/);
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.settle(e.phCalls()[1], OK(222)); await e.flush();
  let v = e.view();
  assert.equal(v.rows, 4); assert.deepEqual(v.modeOn, ['all']);
  e.els.phFrom.value = '2026-01-01'; e.click('apply-range'); await e.flush();
  e.settle(e.phCalls()[2], [500, { detail: 'x' }]); await e.flush();
  e.click('retry'); await e.flush();
  assert.equal(e.phCalls()[3].url, '/api/admin/price-history?date_from=2026-01-01');
  e.settle(e.phCalls()[3], OK(111)); await e.flush();
  v = e.view();
  assert.equal(v.rows, 4); assert.deepEqual(v.modeOn, ['all']);
  assert.doesNotMatch(v.list, /data-code="111"/, '검색어 보존');
  e.done();
});

test('기간 역전(시작>종료)은 화면에서 막고 조회 0', async () => {
  const e = await start(OK(111));
  e.els.phFrom.value = '2026-02-01'; e.els.phTo.value = '2026-01-01';
  e.click('apply-range'); await e.flush();
  assert.equal(e.phCalls().length, 1);
  assert.equal(e.els.phRangeErr.hidden, false);
  e.done();
});

test('기간 조회는 선택 상품을 해제(product_code 없음)', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.settle(e.phCalls()[1], OK(222)); await e.flush();
  e.els.phTo.value = '2026-01-31'; e.click('apply-range'); await e.flush();
  assert.equal(e.phCalls()[2].url, '/api/admin/price-history?date_to=2026-01-31');
  e.done();
});

for (const [name, r] of [['500', [500, { detail: 'x' }]], ['network', 'net'], ['200 HTML', [200, '<html>', 'text/html']], ['200 null', [200, 'null']], ['200 cat 없음', [200, {}]]]) {
  test(`부품 종류 보조 GET ${name} → 「부품 종류 확인 불가」, 본문 영향 없음`, async () => {
    const e = await start(OK(111));
    e.settle(e.ptCalls()[0], r); await e.flush();
    const v = e.view();
    assert.match(v.card, /부품 종류 확인 불가/);
    assert.deepEqual([v.err, v.body], [false, true]);
    e.done();
  });
}

test('부품 종류 응답이 상품 전환 뒤 늦게 와도 무시(코드 가드)', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.settle(e.phCalls()[1], OK(222)); await e.flush();
  e.settle(e.ptCalls()[0], [200, { cat: '늦은111' }]); await e.flush();
  assert.doesNotMatch(e.view().card, /늦은111/);
  assert.match(e.view().card, /확인 중…/);
  e.done();
});

// ── 결함 ① 형식 오류 → 조회 실패 + 다시 시도 ──────────────────────────────
const BAD = [
  ['HTML', '<!doctype html><html>login</html>', 'text/html'], ['빈 본문', ''], ['null', 'null'], ['false', 'false'], ['0', '0'],
  ['문자열', '"abc"'], ['배열', '[]'], ['빈 객체', '{}'],
  ['products 만', { products: [] }],
  ['product 누락', { products: [], items: [] }],
  ['items null', (() => { const p = okPayload(111); p.items = null; return p; })()],
  ['items 문자열', (() => { const p = okPayload(111); p.items = 'x'; return p; })()],
  ['products 객체', { products: {}, items: [], product: null }],
  ['product 배열', { products: [], items: [], product: [] }],
  ['product 문자열', { products: [], items: [], product: '111' }],
];
for (const [name, body, ct] of BAD) {
  test(`200 ${name} → 조회 실패(형식 오류) + 다시 시도로 회복, 404 재시도·보조 GET 없음`, async () => {
    const e = await start([200, body, ct]);
    let v = e.view();
    assert.deepEqual(state(v), [false, true, false]);
    assert.equal(v.errMsg, FMT);
    assert.equal(e.phCalls().length, 1);
    assert.equal(e.ptCalls().length, 0);
    e.click('retry'); await e.flush();
    assert.equal(e.phCalls().length, 2);
    e.settle(e.phCalls()[1], OK(111)); await e.flush();
    v = e.view();
    assert.deepEqual(state(v), [false, false, true]);
    assert.equal(v.cardCode, '111');
    e.done();
  });
}

test('선택 상품 조회의 200 형식 오류는 404 로 위장되지 않는다(선택 유지·추가 조회 0)', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.settle(e.phCalls()[1], [200, '{}']); await e.flush();
  assert.equal(e.phCalls().length, 2);
  assert.equal(e.view().err, true);
  e.click('retry'); await e.flush();
  assert.equal(e.phCalls()[2].url, '/api/admin/price-history?product_code=222');
  e.done();
});

test('정상 뒤 200 null → 「불러오는 중」 고착이 아니라 조회 실패', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.settle(e.phCalls()[1], [200, 'null']); await e.flush();
  const v = e.view();
  assert.deepEqual(state(v), [false, true, false]);
  assert.equal(v.errMsg, FMT);
  e.done();
});

test('정상 뒤 200 {} → 「정당한 빈 결과」가 아니라 조회 실패', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.settle(e.phCalls()[1], [200, '{}']); await e.flush();
  const v = e.view();
  assert.deepEqual(state(v), [false, true, false]);
  e.done();
});

// ── 결함 ② 응답 역순 → 가장 최근 요청만 반영 ─────────────────────────────
test('역순: 222 선택(느림) → 111 선택(빠름) → 늦은 222 정상 응답은 무시', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.click('select-product', { 'data-code': '111' }); await e.flush();
  e.settle(e.phCalls()[2], OK(111)); await e.flush();
  e.settle(e.phCalls()[1], OK(222)); await e.flush();
  const v = e.view();
  assert.equal(v.cardCode, '111'); assert.equal(v.onCode, '111');
  assert.equal(e.ptCalls().length, 2, '늦은 응답은 보조 GET 도 일으키지 않음');
  e.done();
});

test('역순: 기간 조회(느림) → 초기화(빠름) → 늦은 기간 응답은 무시(입력칸·요약 일치)', async () => {
  const e = await start(OK(111));
  e.els.phFrom.value = '2026-01-01'; e.click('apply-range'); await e.flush();
  e.click('reset-range'); await e.flush();
  assert.equal(e.phCalls()[2].url, '/api/admin/price-history');
  e.settle(e.phCalls()[2], OK(111)); await e.flush();
  const p = okPayload(111); p.products = [{ product_code: 111, sku: 'FAKE-111', name: '기간한정가짜', count: 1 }];
  e.settle(e.phCalls()[1], [200, p]); await e.flush();
  assert.equal(e.els.phFrom.value, '');
  assert.match(e.view().summary, /전체 이력 8건\(상품 2개\)/);
  e.done();
});

test('역순: 늦게 온 이전 요청 500 은 최신 정상 화면을 덮지 않음', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.click('select-product', { 'data-code': '111' }); await e.flush();
  e.settle(e.phCalls()[2], OK(111)); await e.flush();
  e.settle(e.phCalls()[1], [500, { detail: '늦은 실패' }]); await e.flush();
  const v = e.view();
  assert.deepEqual(state(v), [false, false, true]);
  assert.equal(v.cardCode, '111');
  e.done();
});

test('역순: 늦게 온 이전 404 는 최신 선택(333)을 풀지 않고 추가 조회도 없음', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.click('select-product', { 'data-code': '333' }); await e.flush();
  e.settle(e.phCalls()[2], OK(333)); await e.flush();
  e.settle(e.phCalls()[1], [404, { detail: 'x' }]); await e.flush();
  assert.equal(e.phCalls().length, 3);
  assert.equal(e.view().cardCode, '333');
  e.click('set-mode', { 'data-mode': 'all' }); await e.flush();
  assert.equal(e.phCalls().length, 3);
  e.done();
});

test('역순: 최신 요청이 아직 진행 중일 때 이전 응답이 오면 무시하고, 최신 응답이 반영됨', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.click('select-product', { 'data-code': '333' }); await e.flush();
  e.settle(e.phCalls()[1], OK(222)); await e.flush();
  assert.equal(e.view().cardCode, '111', '이전 화면 유지');
  e.settle(e.phCalls()[2], OK(333)); await e.flush();
  assert.equal(e.view().cardCode, '333');
  e.done();
});

test('현재 404 의 자동 기본 재조회 중 사용자가 새 상품을 고르면 그 재조회 응답도 무시', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.settle(e.phCalls()[1], [404, { detail: 'x' }]); await e.flush();
  assert.equal(e.phCalls()[2].url, '/api/admin/price-history');
  e.click('select-product', { 'data-code': '333' }); await e.flush();
  e.settle(e.phCalls()[3], OK(333)); await e.flush();
  e.settle(e.phCalls()[2], OK(111)); await e.flush();
  assert.equal(e.view().cardCode, '333');
  assert.equal(e.phCalls().length, 4);
  e.done();
});

test('늦은 이전 형식 오류 응답도 최신 정상 화면을 덮지 않음', async () => {
  const e = await start(OK(111));
  e.click('select-product', { 'data-code': '222' }); await e.flush();
  e.click('select-product', { 'data-code': '111' }); await e.flush();
  e.settle(e.phCalls()[2], OK(111)); await e.flush();
  e.settle(e.phCalls()[1], [200, 'null']); await e.flush();
  assert.deepEqual(state(e.view()), [false, false, true]);
  e.done();
});
