"use strict";
// ADMIN-PART-GRADE-READ-AUDIT — 부품 등급 관리 화면(part_grade.html.j2)의 «실제 페이지 스크립트»를 통째로 실행한다.
// 실제 stripHtml(admin2-text.js 전체)·errText(ui-progress.js 본문에서 그 함수만)를 읽어 쓴다.
// 가짜 DOM·가짜 fetch·가짜 자료만 쓴다. 실제 API·DB·상품·등급 자료·LLM 없음. 쓰기는 가짜 fetch 에만 간다.
//
// 결함 ①(D1·D2): HTTP 200 인데 본문이 깨졌으면
//   - meta {}·[]·"abc"·slots:null 을 「등급을 매길 수 있는 부품 종류가 없습니다」 정상 빈 상태로 그리고 나머지는 「불러오는 중…」에 멈췄다
//   - meta scale 누락은 JS 오류 원문을 띄운 뒤 늦은 칩 응답이 그 오류 상자를 덮었다
//   - engine_reads 가 "false"·1 이면 「엔진 연결됨」으로 뒤집혔다(엔진 미연결 표시가 형식 오류로 바뀜)
//   - 미매김 {}·[]·items 누락은 「매길 항목이 모두 채워졌습니다」 허위 완료, 사다리 items 누락은 「아직 매긴 등급이 없습니다」
//   - 사다리 {} 는 unhandled rejection 으로 사다리·채움 카드가 「불러오는 중…」에 멈췄고, 비JSON 200 미매김도 멈췄다
// 결함 ②(D3·D4·D5b): 갈래별 요청 순번이 없어 같은 쪽 재요청·슬롯 A→B→A·다시 시도 연타에서 늦게 온 이전 응답이 최신 결과를 덮었다.
// 결함 ③(D5): 다시 시도가 실패한 쪽이 아니라 마지막 성공 쪽을 불렀고, 오류 상자 아래 이전 pager 가 남았다.
// 결함 ④(D6): meReady 가 부팅 실패·슬롯 0개 화면을 「불러오는 중…」으로 덮었다.
// 기대: 형식 오류는 기존 「조회 실패」 + 「응답 형식이 올바르지 않습니다 (HTTP 200)」 + 다시 시도. 정상 양수·정상 0·nullable 필드는 그대로.
//   PUT/DELETE 는 공통 handle 을 그대로 쓴다(형식 검사 없음). 권한·쓰기 본문·엔진 미연결 정적 표시 불변.
// 기준 비교: PG_TEMPLATE=<다른 part_grade.html.j2 경로> 로 같은 검사를 그 파일에 돌린다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const TPL = process.env.PG_TEMPLATE || path.join(ROOT, 'templates/admin/part_grade.html.j2');
const tpl = fs.readFileSync(TPL, 'utf8');
const m = tpl.match(/\{% raw %\}\s*<script>([\s\S]*?)<\/script>\s*\{% endraw %\}/);
assert.ok(m, 'foot_extra raw <script> 블록을 찾지 못함');
const SCRIPT = m[1];
assert.ok(!/\{\{|\{%/.test(SCRIPT), 'Jinja 자리표시자가 script 안에 남음');
const UIP = fs.readFileSync(path.join(ROOT, 'mockups/shared/ui-progress.js'), 'utf8');
const TEXTJS = fs.readFileSync(path.join(ROOT, 'mockups/shared/admin2/admin2-text.js'), 'utf8');
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
const SHAPE = '응답 형식이 올바르지 않습니다 (HTTP 200)';

// 페이지 스크립트의 Promise 를 이 realm 의 것과 분리해, 잡히지 않은 거부를 테스트 실패가 아니라 «관찰값»으로 센다.
const UNHANDLED = [];
process.on('unhandledRejection', (e) => UNHANDLED.push(e));

// ── 가짜 DOM: innerHTML 을 넣으면 그 안의 id="…"·data-action(queue-save/skip) 요소를 등록하고 이전 자식은 떼어낸다 ──
function makeDoc() {
  const byId = {}; const actionEls = [];
  class El {
    constructor(id, attrs) {
      this.id = id; this.attrs = Object.assign({}, attrs || {}); this.kids = [];
      this.hidden = 'hidden' in this.attrs; this.disabled = 'disabled' in this.attrs; this.title = this.attrs.title || '';
      this._html = ''; this._text = ''; this.cls = new Set((this.attrs.class || '').split(/\s+/).filter(Boolean));
      this.style = {}; this.value = ''; this.listeners = {};
    }
    set innerHTML(v) { this._detach(); this._html = String(v); this._text = ''; this._scan(); }
    get innerHTML() { return this._html; }
    set textContent(v) { this._detach(); this._text = String(v); this._html = ''; }
    get textContent() { return this._text || this._html.replace(/<[^>]*>/g, ''); }
    get classList() { const s = this.cls; return { add: (c) => s.add(c), remove: (c) => s.delete(c), contains: (c) => s.has(c) }; }
    getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; }
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
    scrollIntoView() {}
    closest(sel) { const mm = /^\[([\w-]+)="([^"]*)"\]$/.exec(sel); return mm && this.attrs[mm[1]] === mm[2] ? this : null; }
    _detach() {
      this.kids.forEach((k) => { k._detach(); if (k.id && byId[k.id] === k) delete byId[k.id]; const i = actionEls.indexOf(k); if (i >= 0) actionEls.splice(i, 1); });
      this.kids = [];
    }
    _scan() {
      const re = /<(\w+)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*\/?>/g; let t;
      while ((t = re.exec(this._html))) {
        const attrs = {}; let a; const are = /([\w-]+)(?:="([^"]*)")?/g;
        while ((a = are.exec(t[2]))) attrs[a[1]] = a[2] == null ? '' : a[2];
        const da = attrs['data-action'];
        if (attrs.id || da === 'queue-save' || da === 'queue-skip') {
          const k = new El(attrs.id || null, attrs); this.kids.push(k);
          if (attrs.id) byId[attrs.id] = k; if (da) actionEls.push(k);
        }
      }
    }
  }
  // 마크업 초기값(템플릿 267~378행과 같은 상태)
  const LOADING = '<div class="pg-loading">불러오는 중…</div>';
  const INIT = { slotBar: '<div class="pg-loading">슬롯 불러오는 중…</div>', noticeBox: '<p>견적 엔진은 아직 이 값을 읽지 않습니다.</p>',
    cardFill: LOADING, cardScale: LOADING, cardView: LOADING, ladderSection: '', ladderBody: LOADING, ladderPager: '',
    ungradedSection: '', ungradedBody: LOADING, ungradedPager: '', gradePanel: '', editFlag: '', panelBody: LOADING };
  Object.keys(INIT).forEach((id) => { const e = new El(id); e._html = INIT[id]; byId[id] = e; });
  byId.editFlag.hidden = true;
  byId.engineBadge = new El('engineBadge', { class: 'pg-badge pg-badge--warn' }); byId.engineBadge._text = '추천에 아직 적용되지 않음';
  byId.engineCaption = new El('engineCaption'); byId.engineCaption._text = '매겨도 지금 견적은 바뀌지 않습니다';
  const listeners = {};
  const document = {
    getElementById: (id) => byId[id] || null,
    addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
    querySelector(sel) { return document.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel) { const want = [...sel.matchAll(/data-action="([^"]+)"/g)].map((x) => x[1]); return actionEls.filter((e) => want.includes(e.attrs['data-action'])); },
  };
  return { document, byId, listeners, El };
}

function makeEnv(opts) {
  opts = opts || {};
  const D = makeDoc(); const els = D.byId; const calls = [];
  function fetch(url, init) {
    let res, rej; const p = new Promise((a, b) => { res = a; rej = b; });
    calls.push({ url: String(url), init: init || {}, resolve: res, reject: rej, settled: false });
    return p;
  }
  function settle(c, r) {
    assert.ok(c, '요청 없음'); assert.ok(!c.settled, '두 번 settle: ' + c.url); c.settled = true;
    if (r === 'net') return c.reject(new TypeError('Failed to fetch'));
    const body = typeof r[1] === 'string' ? r[1] : JSON.stringify(r[1]);
    c.resolve(new Response(body, { status: r[0], headers: { 'content-type': r[2] || 'application/json' } }));
  }
  let meResolve; const meReady = new Promise((r) => { meResolve = r; });
  const ctx = { fetch, Response, console, setTimeout, clearTimeout, Promise, Number, String, Array, Object, Set, isNaN, isFinite, Math, Date, JSON, RegExp, Error, TypeError, encodeURIComponent };
  ctx.document = D.document; ctx.window = ctx;
  ctx.confirm = () => opts.confirm !== false;
  ctx.Admin2Shell = { meReady, canWrite: () => opts.writable !== false };
  vm.createContext(ctx);
  vm.runInContext(TEXTJS, ctx, { filename: 'admin2-text.js' });
  vm.runInContext(ERRTEXT + '\nwindow.popcornProgress={errText:errText};', ctx, { filename: 'ui-progress.errText' });
  vm.runInContext(SCRIPT, ctx, { filename: 'part_grade.inline.js' });
  const flush = async (n = 10) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };
  function click(action, attrs) {
    const ev = { target: new D.El(null, Object.assign({ 'data-action': action }, attrs || {})) };
    (D.listeners.click || []).forEach((fn) => fn(ev));
  }
  const H = (id) => els[id].innerHTML;
  const errOf = (id) => {
    const h = H(id); const t = /pg-errbox-ti">([^<]*)</.exec(h); if (!t) return null;
    return { title: t[1], msg: (/pg-errbox-ds">([^<]*)</.exec(h) || [])[1], retry: (/data-action="([^"]+)"/.exec(h) || [])[1] || null };
  };
  const view = () => ({
    chips: [...H('slotBar').matchAll(/data-slot="([^"]*)"[^>]*><span class="lb">[^<]*<\/span><span class="n num">([^<]*)</g)].map((x) => [x[1], x[2]]),
    slotErr: errOf('slotBar'), slotText: els.slotBar.textContent,
    fill: els.cardFill.textContent.replace(/\s+/g, ' ').trim(),
    viewOn: (/pg-vf-btn on"[^>]*data-view="([^"]*)"/.exec(H('cardView')) || [null, null])[1],
    ladderHidden: els.ladderSection.hidden, ungradedHidden: els.ungradedSection.hidden,
    ladderText: els.ladderBody.textContent, ladderErr: errOf('ladderBody'),
    ladderRows: [...H('ladderBody').matchAll(/class="pg-lrow" data-code="([^"]*)"/g)].map((x) => x[1]),
    ladderPager: els.ladderPager.textContent,
    ungText: els.ungradedBody.textContent, ungErr: errOf('ungradedBody'),
    ungRows: [...H('ungradedBody').matchAll(/class="pg-urow" data-code="([^"]*)"/g)].map((x) => x[1]),
    ungPager: els.ungradedPager.textContent,
    panelText: els.panelBody.textContent, panelErr: errOf('panelBody'),
    panelItem: (/pg-pitem-nm">([^<]*)</.exec(H('panelBody')) || [])[1] || null,
    editFlag: els.editFlag.hidden ? null : els.editFlag.textContent.trim(),
    preview: els.previewBox ? els.previewBox.textContent : null, saved: (/id="savedNoteBox" role="status" aria-live="polite">([^<]*)</.exec(H('panelBody')) || [])[1] || null,
    badge: els.engineBadge.textContent, badgeWarn: els.engineBadge.cls.has('pg-badge--warn'), notice: els.noticeBox.textContent,
  });
  return { els, calls, settle, flush, click, view, meResolve, last: () => calls[calls.length - 1] };
}

// ── 가짜 응답: api/grades.py grades_meta()·list_grades() 반환 모양 그대로, 값은 전부 가짜 ──
const SLOTS = [{ key: 'cpu', label: '가짜CPU' }, { key: 'gpu', label: '가짜GPU' }, { key: 'mb', label: '가짜보드' }];
const META = (o) => Object.assign({ slots: SLOTS, scale: { min: 0, max: 100, note: '가짜척도 **같은 슬롯 안에서만**' },
  basis_required: true, engine_reads: false, engine_note: '가짜엔진노트' }, o || {});
const item = (code, o) => Object.assign({ product_code: code, product_name: '가짜상품' + code, part_type: 'CPU', sale_price: 100000 + code,
  stock_qty: 1, grade: null, basis: null, source: null, graded_at: null, in_pool: true, part_label: '가짜라벨' }, o || {});
function GR(slot, o) {
  o = o || {}; const size = o.size || 40; const items = o.items || []; const total = o.total == null ? items.length : o.total;
  const cov = Object.assign({ total: 50, graded: 2, pool: 20, pool_graded: 2 }, o.coverage || {});
  return { slot, slot_label: '가짜' + slot, page: o.page || 1, size, total, pages: Math.max(1, Math.ceil(total / size)),
    coverage: cov, note: '가짜노트 후보 ' + cov.pool + '개 중 ' + cov.pool_graded + '개', items };
}
const G1 = item(11, { grade: 80, basis: '가짜근거11', source: '가짜출처', graded_at: '2026-11-01T00:00:00Z' });
const G2 = item(12, { grade: 60, basis: '가짜근거12' });
const LADDER = (slot, o) => GR(slot, Object.assign({ items: [G1, G2] }, o || {}));
const UNG = (slot, o) => GR(slot, Object.assign({ items: [item(21), item(22)], size: 30 }, o || {}));
const QUEUE = (slot, it, page) => GR(slot, { items: [it || item(21)], size: 1, total: 2, page: page || 1 });

// 부팅: [meta, 칩×3, ladder, ungraded, queue, ladderTop]
async function boot(o) {
  o = o || {};
  const e = makeEnv(o.env); await e.flush();
  assert.equal(e.calls[0].url, '/api/admin/grades/meta');
  e.settle(e.calls[0], o.meta || [200, META()]); await e.flush();
  return e;
}
function lanes(e, slot) {
  const g = e.calls.filter((c) => c.url.includes('slot=' + slot + '&only=')); const n = g.length;
  return { ladder: g[n - 4], ung: g[n - 3], queue: g[n - 2], top: g[n - 1] };
}
async function chipsOk(e) { for (let i = 1; i <= 3; i++) if (!e.calls[i].settled) e.settle(e.calls[i], [200, GR('x', { coverage: { pool: 7 * i } })]); await e.flush(); }
async function fill(e, slot, o) {
  o = o || {}; const c = lanes(e, slot);
  e.settle(c.ladder, o.ladder || [200, LADDER(slot)]); e.settle(c.ung, o.ung || [200, UNG(slot)]);
  e.settle(c.queue, o.queue || [200, QUEUE(slot)]); e.settle(c.top, o.top || [200, LADDER(slot)]);
  await e.flush(); return c;
}
const LOADING = /불러오는 중/;
const noNewUnhandled = async (n0) => { await new Promise((r) => setTimeout(r, 5)); assert.equal(UNHANDLED.length, n0, '잡히지 않은 거부: ' + UNHANDLED.slice(n0).map(String).join(' | ')); };

// ───────────── 정상 보존 ─────────────
test('정상: 부팅 요청 shape(meta 1 · 칩 size=1 · 첫 슬롯 4 GET) 불변', async () => {
  const e = await boot();
  assert.deepEqual(e.calls.slice(1).map((c) => c.url), [
    '/api/admin/grades?slot=cpu&size=1', '/api/admin/grades?slot=gpu&size=1', '/api/admin/grades?slot=mb&size=1',
    '/api/admin/grades?slot=cpu&only=graded&page=1&size=40', '/api/admin/grades?slot=cpu&only=ungraded&page=1&size=30',
    '/api/admin/grades?slot=cpu&only=ungraded&page=1&size=1', '/api/admin/grades?slot=cpu&only=graded&page=1&size=40']);
  assert.ok(e.calls.every((c) => (c.init.method || 'GET') === 'GET' && c.init.credentials === 'same-origin'));
});

test('정상 양수: 칩·채움 카드·척도·사다리·미매김·패널·미리보기·엔진 미연결 표시', async () => {
  const n0 = UNHANDLED.length;
  const e = await boot(); await chipsOk(e); await fill(e, 'cpu');
  const v = e.view();
  assert.deepEqual(v.chips, [['cpu', '20'], ['gpu', '14'], ['mb', '21']]);
  assert.match(v.fill, /^2 \/ 20\s*가짜노트 후보 20개 중 2개$/);
  assert.match(e.els.cardScale.innerHTML, /0~100[\s\S]*<strong>같은 슬롯 안에서만<\/strong>/);
  assert.deepEqual(v.ladderRows, ['11', '12']); assert.match(v.ladderPager, /전체 2건 중 1 \/ 1페이지/);
  assert.deepEqual(v.ungRows, ['21', '22']); assert.equal(v.panelItem, '가짜상품21');
  e.els.scoreInput.value = '70'; e.els.scoreInput.listeners.input[0]();
  assert.equal(e.view().preview, '지금 서열: 80점(가짜상품11) 아래 · 60점(가짜상품12) 위');
  assert.equal(v.badge, '추천에 아직 적용되지 않음'); assert.equal(v.badgeWarn, true);
  await noNewUnhandled(n0);
});

test('정상: nullable 상품 필드(이름·라벨·가격·근거·출처·날짜·in_pool·grade null)는 형식 오류가 아니다', async () => {
  const nul = { product_name: null, part_label: null, sale_price: null, basis: null, source: null, graded_at: null, in_pool: null, stock_qty: null };
  const e = await boot(); await chipsOk(e);
  await fill(e, 'cpu', { ladder: [200, LADDER('cpu', { items: [item(11, Object.assign({}, nul, { grade: 70 }))] })], ung: [200, UNG('cpu', { items: [item(21, nul)] })], queue: [200, QUEUE('cpu', item(21, nul))] });
  const v = e.view(); assert.deepEqual(v.ladderRows, ['11']); assert.deepEqual(v.ungRows, ['21']); assert.equal(v.ladderErr, null); assert.equal(v.ungErr, null); assert.equal(v.panelErr, null);
  assert.match(v.panelText, /가격 정보 없음/);
});

test('정상 0: 등급 0건 → 사다리 빈 안내·「첫 등급」 미리보기 / 미매김 0건 → 「모두 채워졌습니다」(목록·패널)', async () => {
  const e = await boot(); await chipsOk(e);
  const z = GR('cpu', { items: [], total: 0, coverage: { graded: 0, pool_graded: 0 } });
  await fill(e, 'cpu', { ladder: [200, z], top: [200, z], ung: [200, GR('cpu', { items: [], size: 30 })], queue: [200, GR('cpu', { items: [], size: 1 })] });
  const v = e.view();
  assert.match(v.ladderText, /아직 이 슬롯에 매긴 등급이 없습니다/); assert.equal(v.ladderPager, ''); assert.match(v.fill, /^0 \/ 20/);
  assert.match(v.ungText, /매길 항목이 모두 채워졌습니다/); assert.match(v.panelText, /매길 항목이 모두 채워졌습니다/);
});

test('정상: meta HTTP 401·403·500 비JSON → 기존 오류 상자, 다시 시도 회복', async () => {
  for (const [st, body, ct, title, msg] of [[401, { detail: 'x' }, null, '세션 만료', '관리자 로그인 후 다시 시도합니다.'],
    [403, { detail: '가짜403' }, null, '조회 실패', '가짜403'], [500, '<html>x</html>', 'text/html', '조회 실패', '오류 500']]) {
    const e = await boot({ meta: [st, body, ct] });
    const v = e.view(); assert.equal(v.slotErr.title, title); assert.equal(v.slotErr.msg, msg); assert.equal(e.calls.length, 1);
    if (st === 401) continue;
    e.click('retry-boot'); await e.flush(); e.settle(e.last(), [200, META()]); await e.flush(); await chipsOk(e); await fill(e, 'cpu');
    assert.deepEqual(e.view().ladderRows, ['11', '12']);
  }
});

test('정상: 사다리 500 · 미매김 network · 큐 422 → 각 오류 상자, 다시 시도 회복', async () => {
  const e = await boot(); await chipsOk(e);
  await fill(e, 'cpu', { ladder: [500, { detail: '가짜500' }], ung: 'net', queue: [422, { detail: [{ loc: ['query', 'page'], msg: '가짜' }] }] });
  let v = e.view(); assert.equal(v.ladderErr.msg, '가짜500'); assert.equal(v.ungErr.msg, 'Failed to fetch'); assert.equal(v.panelErr.msg, 'page: 가짜');
  e.click('retry-ladder'); e.click('retry-ungraded'); e.click('retry-queue'); await e.flush();
  const n = e.calls.length;
  assert.deepEqual(e.calls.slice(n - 3).map((c) => c.url), ['/api/admin/grades?slot=cpu&only=graded&page=1&size=40',
    '/api/admin/grades?slot=cpu&only=ungraded&page=1&size=30', '/api/admin/grades?slot=cpu&only=ungraded&page=1&size=1']);
  e.settle(e.calls[n - 3], [200, LADDER('cpu')]); e.settle(e.calls[n - 2], [200, UNG('cpu')]); e.settle(e.calls[n - 1], [200, QUEUE('cpu')]); await e.flush();
  v = e.view(); assert.deepEqual(v.ladderRows, ['11', '12']); assert.deepEqual(v.ungRows, ['21', '22']); assert.equal(v.panelItem, '가짜상품21');
});

test('정상: 보기 필터는 재조회 0 · 슬롯 변경 시 필터/패널 초기화 · A→B 후 A 늦은 응답 무시', async () => {
  const e = await boot(); await chipsOk(e); await fill(e, 'cpu');
  const n0 = e.calls.length;
  e.click('set-view', { 'data-view': 'graded' });
  assert.equal(e.calls.length, n0); assert.equal(e.view().ungradedHidden, true);
  e.click('row-grade', { 'data-code': '22' }); assert.match(e.view().editFlag, /목록에서 고른 상품/);
  const a = lanes(e, 'cpu');
  e.click('select-slot', { 'data-slot': 'gpu' }); await e.flush();
  let v = e.view(); assert.equal(v.viewOn, ''); assert.equal(v.ungradedHidden, false); assert.equal(v.editFlag, null); assert.match(v.panelText, LOADING);
  e.click('select-slot', { 'data-slot': 'cpu' }); e.click('select-slot', { 'data-slot': 'gpu' }); await e.flush();
  await fill(e, 'gpu', { ladder: [200, LADDER('gpu', { items: [item(91, { grade: 50, basis: 'g' })] })] });
  void a; v = e.view(); assert.deepEqual(v.ladderRows, ['91']);
});

test('정상: 열람 권한 → 버튼·입력 disabled, 쓰기 요청 0', async () => {
  const e = await boot({ env: { writable: false } }); await chipsOk(e); await fill(e, 'cpu');
  e.meResolve({ role: 'viewer' }); await e.flush();
  assert.match(e.els.ladderBody.innerHTML, /disabled title="열람 권한/); assert.equal(e.els.scoreInput.disabled, true); assert.equal(e.els.readonlyNote.hidden, false);
  e.click('queue-save'); e.click('row-delete', { 'data-code': '11' }); await e.flush();
  assert.ok(e.calls.every((c) => (c.init.method || 'GET') === 'GET'));
});

test('정상: PUT/DELETE 는 GET 형식 검사를 타지 않는다(가짜 fetch 만 — 저장 note 표시·삭제 후 재조회 불변)', async () => {
  const e = await boot(); await chipsOk(e); await fill(e, 'cpu');
  e.els.scoreInput.value = '55'; e.els.basisInput.value = '가짜근거'; e.click('queue-save'); await e.flush();
  const put = e.last(); assert.equal(put.init.method, 'PUT'); assert.equal(put.url, '/api/admin/grades/21');
  e.settle(put, [200, { ok: true, product_code: 21, grade: 55, note: '가짜저장노트' }]); await e.flush();
  assert.equal(e.calls.slice(-4).every((c) => (c.init.method || 'GET') === 'GET'), true, '저장 후 4갈래 재조회');
  await fill(e, 'cpu'); assert.equal(e.view().saved, '가짜저장노트');
  e.click('row-delete', { 'data-code': '11' }); await e.flush();
  const del = e.last(); assert.equal(del.init.method, 'DELETE');
  e.settle(del, [200, { ok: true, note: '가짜삭제' }]); await e.flush(); await fill(e, 'cpu');
  assert.deepEqual(e.view().ladderRows, ['11', '12']);
});

// ───────────── 결함 ①: 형식 오류 200 ─────────────
const META_BAD = [
  ['{}', {}], ['[]', []], ['"abc"', JSON.stringify('abc')], ['null', 'null'], ['HTML 200', '<html>x</html>', 'text/html'],
  ['slots:null', META({ slots: null })], ['slots:{}', META({ slots: {} })], ['slot key 숫자', META({ slots: [{ key: 1, label: 'x' }] })],
  ['slot null', META({ slots: [null] })], ['scale 누락', META({ scale: undefined })], ['scale.max 문자열', META({ scale: { min: 0, max: '100', note: '' } })],
  ['scale.note 누락', META({ scale: { min: 0, max: 100 } })], ['engine_reads "false"', META({ engine_reads: 'false' })],
  ['engine_reads 1', META({ engine_reads: 1 })], ['engine_reads 누락', META({ engine_reads: undefined })],
];
for (const [name, body, ct] of META_BAD) {
  test(`결함①: meta 200 ${name} → 「조회 실패」+형식 문구+다시 시도, 칩·슬롯 요청 0, 엔진 미연결 표시 유지, 다시 시도 회복`, async () => {
    const n0 = UNHANDLED.length;
    const e = await boot({ meta: [200, body, ct] });
    let v = e.view();
    assert.deepEqual(v.slotErr, { title: '조회 실패', msg: SHAPE, retry: 'retry-boot' });
    assert.doesNotMatch(v.slotText, /부품 종류가 없습니다/);
    assert.equal(e.calls.length, 1, '형식 오류 뒤 칩·슬롯 요청이 나가지 않음');
    assert.equal(v.badge, '추천에 아직 적용되지 않음'); assert.equal(v.badgeWarn, true); assert.match(v.notice, /읽지 않습니다/);
    e.meResolve({ role: 'owner' }); await e.flush();
    assert.doesNotMatch(e.view().ladderText, LOADING, 'meReady 가 실패 화면을 로딩으로 덮지 않음');
    e.click('retry-boot'); await e.flush(); e.settle(e.last(), [200, META()]); await e.flush(); await chipsOk(e); await fill(e, 'cpu');
    v = e.view(); assert.equal(v.slotErr, null); assert.deepEqual(v.ladderRows, ['11', '12']);
    await noNewUnhandled(n0);
  });
}

test('결함①: engine_reads === true(불리언)만 「엔진 연결됨」 — 정상 false 는 미연결 표시 그대로', async () => {
  const t = await boot({ meta: [200, META({ engine_reads: true })] });
  assert.equal(t.view().badge, '엔진 연결됨');
  const f = await boot(); assert.equal(f.view().badge, '추천에 아직 적용되지 않음');
});

const GR_BAD = [
  ['{}', {}], ['[]', []], ['"abc"', JSON.stringify('abc')], ['null', 'null'], ['HTML 200', '<html>x</html>', 'text/html'],
  ['items 누락', (s) => { const p = GR(s); delete p.items; return p; }], ['items null', (s) => Object.assign(GR(s), { items: null })],
  ['items [null]', (s) => Object.assign(GR(s), { items: [null] })], ['product_code 문자열', (s) => Object.assign(GR(s), { items: [item('x')] })],
  ['coverage 누락', (s) => { const p = GR(s); delete p.coverage; return p; }], ['coverage.pool 누락', (s) => Object.assign(GR(s), { coverage: { graded: 0, pool_graded: 0 } })],
  ['coverage.graded 문자열', (s) => GR(s, { coverage: { graded: '2' } })], ['page 누락', (s) => { const p = GR(s); delete p.page; return p; }],
  ['pages 문자열', (s) => Object.assign(GR(s), { pages: '1' })], ['total null', (s) => Object.assign(GR(s), { total: null })],
  ['note 누락', (s) => { const p = GR(s); delete p.note; return p; }],
];
const badBody = (b, s) => (typeof b === 'function' ? b(s) : b);
for (const [name, body, ct] of GR_BAD) {
  test(`결함①: grades 200 ${name} → 사다리·미매김·큐 「조회 실패」+형식 문구(허위 0건/완료·영구 로딩·unhandled 없음), 칩 「조회 실패」, 다시 시도 회복`, async () => {
    const n0 = UNHANDLED.length;
    const e = await boot();
    for (let i = 1; i <= 3; i++) e.settle(e.calls[i], [200, badBody(body, 'x'), ct]);
    await fill(e, 'cpu', { ladder: [200, badBody(body, 'cpu'), ct], ung: [200, badBody(body, 'cpu'), ct], queue: [200, badBody(body, 'cpu'), ct], top: [200, badBody(body, 'cpu'), ct] });
    let v = e.view();
    assert.deepEqual(v.ladderErr, { title: '조회 실패', msg: SHAPE, retry: 'retry-ladder' });
    assert.deepEqual(v.ungErr, { title: '조회 실패', msg: SHAPE, retry: 'retry-ungraded' });
    assert.deepEqual(v.panelErr, { title: '조회 실패', msg: SHAPE, retry: 'retry-queue' });
    assert.doesNotMatch(v.ladderText + v.ungText + v.panelText, /아직 이 슬롯에 매긴 등급이 없습니다|모두 채워졌습니다|불러오는 중/);
    assert.equal(v.fill, '조회 실패'); assert.equal(v.ladderPager, ''); assert.equal(v.ungPager, '');
    assert.deepEqual(v.chips.map((c) => c[1]), ['조회 실패', '조회 실패', '조회 실패']);
    await noNewUnhandled(n0);
    e.click('retry-ladder'); e.click('retry-ungraded'); e.click('retry-queue'); await e.flush();
    const n = e.calls.length; e.settle(e.calls[n - 3], [200, LADDER('cpu')]); e.settle(e.calls[n - 2], [200, UNG('cpu')]); e.settle(e.calls[n - 1], [200, QUEUE('cpu')]); await e.flush();
    v = e.view(); assert.deepEqual(v.ladderRows, ['11', '12']); assert.deepEqual(v.ungRows, ['21', '22']); assert.equal(v.panelItem, '가짜상품21');
  });
}

// ───────────── 결함 ②: 늦게 온 이전 응답 ─────────────
test('결함②: 같은 slot·같은 page — 「다음」 두 번(p2 두 요청), 늦은 첫 요청 실패/성공이 최신 p2 결과를 덮지 않음', async () => {
  for (const late of [[500, { detail: '늦은실패' }], 'net', [200, LADDER('cpu', { total: 80, page: 2, items: [item(19, { grade: 1, basis: 'old' })] })]]) {
    const e = await boot(); await chipsOk(e);
    await fill(e, 'cpu', { ladder: [200, LADDER('cpu', { total: 80 })] });
    e.click('ladder-next'); e.click('ladder-next'); await e.flush();
    const p2 = e.calls.filter((c) => c.url === '/api/admin/grades?slot=cpu&only=graded&page=2&size=40'); assert.equal(p2.length, 2);
    e.settle(p2[1], [200, LADDER('cpu', { total: 80, page: 2, items: [item(13, { grade: 40, basis: 'b' })] })]); await e.flush();
    e.settle(p2[0], late); await e.flush();
    const v = e.view(); assert.equal(v.ladderErr, null); assert.deepEqual(v.ladderRows, ['13']); assert.match(v.ladderPager, /2 \/ 2페이지/);
  }
});

test('결함②: 같은 slot 다른 page — 미매김 p2 진행 중 A→B→A 로 p1 표시 후 늦은 p2 가 덮지 않음', async () => {
  const e = await boot(); await chipsOk(e);
  await fill(e, 'cpu', { ung: [200, UNG('cpu', { total: 60 })] });
  e.click('ungraded-next'); await e.flush(); const p2 = e.last();
  e.click('select-slot', { 'data-slot': 'gpu' }); e.click('select-slot', { 'data-slot': 'cpu' }); await e.flush();
  await fill(e, 'cpu', { ung: [200, UNG('cpu', { total: 60 })] });
  e.settle(p2, [200, UNG('cpu', { total: 60, page: 2, items: [item(31)] })]); await e.flush();
  const v = e.view(); assert.deepEqual(v.ungRows, ['21', '22']); assert.match(v.ungPager, /1 \/ 2페이지/);
});

test('결함②: 슬롯 A→B→A — 첫 A 의 늦은 사다리 실패·큐·미리보기·미매김 응답이 두 번째 A 결과를 덮지 않음', async () => {
  const e = await boot(); await chipsOk(e);
  const a1 = lanes(e, 'cpu');
  e.click('select-slot', { 'data-slot': 'gpu' }); e.click('select-slot', { 'data-slot': 'cpu' }); await e.flush();
  await fill(e, 'cpu');
  e.settle(a1.ladder, [500, { detail: '첫A늦은실패' }]); e.settle(a1.queue, [200, QUEUE('cpu', item(28), 2)]);
  e.settle(a1.ung, [200, UNG('cpu', { items: [item(29)] })]); e.settle(a1.top, [200, GR('cpu', { items: [], coverage: { graded: 0 } })]); await e.flush();
  const v = e.view(); assert.equal(v.ladderErr, null); assert.deepEqual(v.ladderRows, ['11', '12']); assert.equal(v.panelItem, '가짜상품21'); assert.deepEqual(v.ungRows, ['21', '22']);
  e.els.scoreInput.value = '70'; e.els.scoreInput.listeners.input[0]();
  assert.equal(e.view().preview, '지금 서열: 80점(가짜상품11) 아래 · 60점(가짜상품12) 위');
});

test('결함②: 다시 시도 연타 — 앞 요청의 늦은 실패가 뒤 요청 성공을 덮지 않음(사다리·미매김·큐)', async () => {
  const e = await boot(); await chipsOk(e);
  await fill(e, 'cpu', { ladder: [500, { detail: 'x' }], ung: [500, { detail: 'x' }], queue: [500, { detail: 'x' }] });
  for (const [act, ok, key] of [['retry-ladder', LADDER('cpu'), 'ladderRows'], ['retry-ungraded', UNG('cpu'), 'ungRows'], ['retry-queue', QUEUE('cpu'), 'panelItem']]) {
    e.click(act); e.click(act); await e.flush();
    const n = e.calls.length; e.settle(e.calls[n - 1], [200, ok]); await e.flush();
    const before = e.view()[key]; e.settle(e.calls[n - 2], 'net'); await e.flush();
    assert.deepEqual(e.view()[key], before, act);
  }
});

// ───────────── 결함 ③: 다시 시도 = 실패한 쪽 ─────────────
test('결함③: 사다리 p2 실패 → 오류 상자 아래 이전 pager 없음, 다시 시도는 p2', async () => {
  const e = await boot(); await chipsOk(e);
  await fill(e, 'cpu', { ladder: [200, LADDER('cpu', { total: 80 })] });
  e.click('ladder-next'); await e.flush(); e.settle(e.last(), [500, { detail: 'p2실패' }]); await e.flush();
  const v = e.view(); assert.equal(v.ladderErr.msg, 'p2실패'); assert.equal(v.ladderPager, '');
  e.click('retry-ladder'); await e.flush(); assert.equal(e.last().url, '/api/admin/grades?slot=cpu&only=graded&page=2&size=40');
});

test('결함③: 미매김 p2 실패 → pager 없음·다시 시도 p2 / 큐 건너뛰기 p2 실패 → 다시 시도 p2', async () => {
  const e = await boot(); await chipsOk(e);
  await fill(e, 'cpu', { ung: [200, UNG('cpu', { total: 60 })] });
  e.click('ungraded-next'); await e.flush(); e.settle(e.last(), 'net'); await e.flush();
  assert.equal(e.view().ungPager, ''); e.click('retry-ungraded'); await e.flush();
  assert.equal(e.last().url, '/api/admin/grades?slot=cpu&only=ungraded&page=2&size=30');
  e.click('queue-skip'); await e.flush(); assert.match(e.last().url, /only=ungraded&page=2&size=1$/);
  e.settle(e.last(), [500, { detail: 'q' }]); await e.flush(); assert.equal(e.view().panelErr.msg, 'q');
  e.click('retry-queue'); await e.flush(); assert.equal(e.last().url, '/api/admin/grades?slot=cpu&only=ungraded&page=2&size=1');
});

// ───────────── 결함 ④: meReady 가 실패·빈 화면을 로딩으로 덮음 ─────────────
test('결함④: meta 실패 후 meReady → 부팅 실패 문구 유지(「불러오는 중…」 아님)', async () => {
  const e = await boot({ meta: [500, { detail: 'm' }] });
  e.meResolve({ role: 'owner' }); await e.flush();
  const v = e.view(); assert.match(v.ladderText, /슬롯 정보를 불러오지 못해/); assert.match(v.ungText, /슬롯 정보를 불러오지 못해/); assert.equal(v.slotErr.title, '조회 실패');
});

test('결함④: 정상 slots 0개 → 「종류 없음」 빈 상태가 사다리·미매김·패널까지, meReady 뒤에도 로딩 아님', async () => {
  const e = await boot({ meta: [200, META({ slots: [] })] });
  e.meResolve({ role: 'owner' }); await e.flush();
  const v = e.view(); assert.equal(v.slotErr, null); assert.match(v.slotText, /부품 종류가 없습니다/); assert.equal(e.calls.length, 1);
  for (const t of [v.ladderText, v.ungText, v.panelText, v.fill]) assert.doesNotMatch(t, LOADING);
  assert.match(e.els.cardScale.textContent, /^0~100/);
});
