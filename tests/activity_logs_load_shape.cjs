"use strict";
// ADMIN-ACTIVITY-LOGS-READ-AUDIT — 작업 기록 화면(activity_logs.html.j2)의 조회 loadPeriod()를
// «실제 페이지 스크립트» 통째로 실행한다. 실제 errText(ui-progress.js 본문에서 그 함수만)를
// 읽어 쓴다. 가짜 DOM·가짜 fetch·가짜 자료만 쓴다. 실제 API·DB·로그 없음.
//
// 결함 ①(D1·D1b·D4): HTTP 200 인데 본문이 깨졌거나 형이 다르면
//   - []·{}·items:null·items 누락을 「전부 표시됨 · 0건」·「이 조건에는 기록이 없습니다」로 그렸고
//   - total 누락이면 3행을 보이며 「0건」, total:"x" 면 「NaN건」이라 말했고
//   - null·HTML·문자열·items:{} 등은 JS 오류 원문을 오류 상자에 띄웠다.
// 결함 ②(D2): 요청 순번이 없어 늦게 도착한 이전 기간의 정상·500·network 응답이 최신 기간
//   화면을 덮었다(기간 버튼은 「오늘」인데 목록은 7일치).
// 결함 ③(D3): 기간을 바꾸면 응답 전까지 새 기간 버튼 아래에 이전 기간 목록·건수가 남았다.
// 기대: 형식 오류는 「조회 실패」 + 「응답 형식이 올바르지 않습니다 (HTTP 200)」 + 다시 시도.
//   정상 0건(total 0·limit 500·items [] — unmapped_* 유무 무관)은 오류가 아니다. 가장 최근
//   요청의 응답만 반영한다. 기간이 바뀔 때만 로딩으로 내리고, 같은 기간 새로고침·다시 시도
//   대기 중에는 기존 자료 표시를 유지한다.
// 기준 비교: AL_TEMPLATE=<다른 activity_logs.html.j2 경로> 로 같은 검사를 그 파일에 돌린다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const TPL = process.env.AL_TEMPLATE || path.join(ROOT, 'templates/admin/activity_logs.html.j2');
const tpl = fs.readFileSync(TPL, 'utf8');
const m = tpl.match(/\{% raw %\}\s*<script>([\s\S]*?)<\/script>\s*\{% endraw %\}/);
assert.ok(m, 'foot_extra raw <script> 블록을 찾지 못함');
const SCRIPT = m[1];
assert.ok(!/\{\{|\{%/.test(SCRIPT), 'Jinja 자리표시자가 script 안에 남음');
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

// 고정 시각: 2026-11-04T16:30:00Z = KST 2026-11-05 01:30 (UTC 날짜와 KST 날짜가 다른 시각)
const FIXED = Date.UTC(2026, 10, 4, 16, 30, 0);
const RealDate = Date;
class FixedDate extends RealDate {
  constructor(...a) { if (a.length) super(...a); else super(FIXED); }
  static now() { return FIXED; }
}

// ── 가짜 DOM: 이 스크립트가 쓰는 API 만 흉내낸다 ─────────────────────────
class El {
  constructor(id) { this.id = id; this.hidden = false; this._html = ''; this._text = ''; this.value = ''; this.attrs = {}; this.cls = new Set(); this.style = {}; this.className = ''; this.scrollLeft = 0; }
  set innerHTML(v) { this._html = String(v); this._text = ''; }
  get innerHTML() { return this._html; }
  set textContent(v) { this._text = String(v); this._html = ''; }
  get textContent() { return this._text || this._html.replace(/<[^>]*>/g, ''); }
  getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  get classList() { const s = this.cls; return { toggle: (c, on) => { (on === undefined ? !s.has(c) : on) ? s.add(c) : s.delete(c); }, contains: (c) => s.has(c) }; }
  closest(sel) { const mm = /^\[(.+)\]$/.exec(sel); return mm && this.attrs[mm[1]] != null ? this : null; }
  addEventListener() {}
  focus() {}
}

const IDS = ['alLoading', 'alErrBox', 'alErrMsg', 'alBody', 'alBanner', 'alBannerMeta', 'alScopeLine',
  'alFOperatorBtn', 'alFOperatorDrop', 'alFOperatorLabel', 'alFKindBtn', 'alFKindDrop', 'alFKindLabel',
  'alFActionBtn', 'alFActionDrop', 'alFActionLabel', 'alFUndoneBtn', 'alFUndoneDrop', 'alFUndoneLabel',
  'alSearchBox', 'alSearch', 'alSearchClear', 'alResetBtn', 'alCountLine', 'alCapChip', 'alFilterNote',
  'alTbody', 'alEmpty', 'alEmptyTitle', 'alEmptyDesc', 'alPageInfo', 'alPagerNums', 'alDrawerWrap',
  'alDKind', 'alDAction', 'alDUndone', 'alDId', 'alDAt', 'alDWho', 'alDTarget', 'alDSummary',
  'alDStateBox', 'alDStateTitle', 'alDStateDesc'];
// 마크업 초기 hidden(템플릿 본문 그대로)
const INIT_HIDDEN = ['alErrBox', 'alBody', 'alBanner', 'alFOperatorDrop', 'alFKindDrop', 'alFActionDrop', 'alFUndoneDrop', 'alEmpty', 'alDrawerWrap'];

function makeEnv(opts) {
  opts = opts || {};
  const els = {};
  IDS.forEach((id) => { els[id] = new El(id); });
  INIT_HIDDEN.forEach((k) => { els[k].hidden = true; });
  const periods = ['today', '7d', '30d', 'all'].map((p) => { const b = new El(null); b.attrs['data-action'] = 'pick-period'; b.attrs['data-period'] = p; return b; });
  const listeners = {};
  const document = {
    activeElement: null,
    getElementById: (id) => els[id] || null,
    querySelectorAll: (sel) => (sel === '.al-period' ? periods : []),
    querySelector: () => null,
    addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
  };
  const calls = [];
  function fetch(url, init) {
    let res, rej; const p = new Promise((a, b) => { res = a; rej = b; });
    calls.push({ url: String(url), init, resolve: res, reject: rej, settled: false });
    return p;
  }
  function settle(c, r) {
    assert.ok(!c.settled, 'double settle ' + c.url); c.settled = true;
    if (r === 'net') return c.reject(new TypeError('Failed to fetch'));
    const body = typeof r[1] === 'string' ? r[1] : JSON.stringify(r[1]);
    c.resolve(new Response(body, { status: r[0], headers: { 'content-type': r[2] || 'application/json' } }));
  }
  const ctx = { document, fetch, Response, console, setTimeout, clearTimeout, Promise, Number, String, Array, Object,
    isFinite, isNaN, Math, Date: FixedDate, JSON, RegExp, Error, TypeError, Intl, navigator: {} };
  ctx.window = ctx;
  ctx.Admin2Shell = { isKeepClick: (t) => !!(t && t.attrs && t.attrs['data-keep'] != null), toast() {} };
  vm.createContext(ctx);
  if (!opts.noProgress) vm.runInContext(ERRTEXT + '\nwindow.popcornProgress={errText:errText};', ctx, { filename: 'ui-progress.errText' });
  vm.runInContext(SCRIPT, ctx, { filename: 'activity_logs.inline.js' });
  const flush = async (n = 8) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };
  function fire(type, target) { (listeners[type] || []).forEach((fn) => fn({ target, key: target && target.key, stopPropagation() {} })); }
  function click(action, attrs) { const t = new El(null); t.attrs['data-action'] = action; Object.assign(t.attrs, attrs || {}); fire('click', t); }
  const view = () => ({
    loading: !els.alLoading.hidden, err: !els.alErrBox.hidden, body: !els.alBody.hidden,
    errMsg: els.alErrMsg.textContent, scope: els.alScopeLine.textContent,
    count: els.alCountLine.textContent, chip: els.alCapChip.textContent, chipWarn: els.alCapChip.cls.has('warn'),
    banner: !els.alBanner.hidden, bannerMeta: els.alBannerMeta.textContent,
    empty: !els.alEmpty.hidden, emptyTitle: els.alEmptyTitle.textContent,
    tbody: els.alTbody.innerHTML, rows: (els.alTbody.innerHTML.match(/class="al-row/g) || []).length,
    ids: [...els.alTbody.innerHTML.matchAll(/data-id="(\d+)"/g)].map((x) => +x[1]),
    periodOn: periods.filter((b) => b.cls.has('on')).map((b) => b.attrs['data-period']),
    opLabel: els.alFOperatorLabel.textContent, pageInfo: els.alPageInfo.textContent,
    drawer: !els.alDrawerWrap.hidden, drawerId: els.alDId.textContent, drawerState: els.alDStateTitle.textContent,
  });
  const al = () => calls.filter((c) => c.url.startsWith('/api/admin/activity-logs'));
  return { els, settle, flush, click, view, al, last: () => al()[al().length - 1] };
}

// ── 가짜 응답 (api/admin_activity_logs.py 267~281 반환 모양 그대로, 값은 전부 가짜) ──
function row(id, o) {
  return Object.assign({ log_id: id, at: '2026-01-02T10:00:00+09:00', operator: '가짜운영자', kind: 'order', kind_label: '주문',
    action_label: '주문 처리', is_undo: false, target: 'FAKE-' + id, summary: '가짜 요약 ' + id, undone: false }, o || {});
}
function ok(tag, o) {
  o = o || {};
  const items = o.items || [
    row(903, { action_label: '주문 처리 되돌림', is_undo: true, summary: '원 기록 #901 되돌림', operator: '가짜운영자' + tag }),
    row(902, { operator: '가짜운영자' + tag }),
    row(901, { undone: true, operator: '가짜운영자' + tag }),
  ];
  const p = { total: o.total != null ? o.total : items.length, limit: 500, items };
  if (!o.noUnmapped) { p.unmapped_kinds = o.uk || []; p.unmapped_actions = o.ua || []; }
  return [200, p];
}
const ZERO = [200, { total: 0, limit: 500, items: [], unmapped_kinds: [], unmapped_actions: [] }];
const FMT_ERR = '응답 형식이 올바르지 않습니다 (HTTP 200)';

async function boot(first, opts) {
  const e = makeEnv(opts); await e.flush();
  assert.equal(e.al().length, 1); assert.equal(e.al()[0].url, '/api/admin/activity-logs');
  assert.equal(e.al()[0].init.credentials, 'same-origin');
  assert.equal(e.view().loading, true, '첫 응답 전 로딩');
  if (first) { e.settle(e.al()[0], first); await e.flush(); }
  return e;
}

// ── 정상 계약 ────────────────────────────────────────────────────────────
test('정상 양수: 본문·3행·되돌림 짝 일치(배너 없음)·전부 표시됨', async () => {
  const e = await boot(ok('A'));
  const v = e.view();
  assert.deepEqual([v.loading, v.err, v.body], [false, false, true]);
  assert.deepEqual(v.ids, [903, 902, 901]);
  assert.equal(v.scope, '원장 조건 내 3건 · 표시 3건');
  assert.equal(v.chip, '전부 표시됨 · 3건'); assert.equal(v.chipWarn, false);
  assert.equal(v.banner, false); assert.deepEqual(v.periodOn, ['all']);
  assert.match(v.tbody, /class="ud undone"/);
});

test('정상 0건(total 0·limit 500·items []) → 정당한 빈 결과, 오류 아님', async () => {
  const e = await boot(ZERO);
  const v = e.view();
  assert.deepEqual([v.loading, v.err, v.body, v.empty], [false, false, true, true]);
  assert.equal(v.emptyTitle, '이 조건에는 기록이 없습니다');
  assert.equal(v.chip, '전부 표시됨 · 0건'); assert.equal(v.scope, '원장 조건 내 0건 · 표시 0건');
});

test('unmapped_kinds/unmapped_actions 는 필수가 아님 — 없어도·값이 있어도 정상 화면 동일', async () => {
  const a = (await boot(ok('A'))).view();
  const b = (await boot(ok('A', { noUnmapped: true }))).view();
  const c = (await boot(ok('A', { uk: ['zz_kind'], ua: ['zz_act'] }))).view();
  for (const v of [b, c]) for (const k of ['err', 'body', 'scope', 'count', 'chip', 'tbody', 'banner']) assert.deepEqual(v[k], a[k], k);
  const z = (await boot([200, { total: 0, limit: 500, items: [] }])).view();
  assert.equal(z.err, false); assert.equal(z.empty, true);
});

test('상한 초과(total > items) → warn 칩 「최근 500건만 표시 — 서버 상한(전체 N건 중)」', async () => {
  const v = (await boot(ok('A', { total: 900 }))).view();
  assert.equal(v.chip, '최근 500건만 표시 — 서버 상한(전체 900건 중)'); assert.equal(v.chipWarn, true);
});

test('서버 undone=false 인데 배치 내 되돌림 증거 → 배너·판정 불가(unknown) 유지', async () => {
  const p = ok('A'); p[1].items[2].undone = false;
  const e = await boot(p);
  const v = e.view();
  assert.equal(v.banner, true); assert.match(v.bannerMeta, /불일치: 1건/); assert.match(v.tbody, /class="ud unknown"/);
  e.click('open-drawer', { 'data-id': '901' }); await e.flush();
  assert.equal(e.view().drawer, true); assert.match(e.view().drawerState, /판정 불가/);
});

test('필터·서랍·페이지: 운영자 필터, 20행 2쪽, 서랍 열기/닫기', async () => {
  const items = Array.from({ length: 20 }, (_, i) => row(1000 - i, { operator: i % 2 ? '가짜B' : '가짜A' }));
  const e = await boot([200, { total: 20, limit: 500, items, unmapped_kinds: [], unmapped_actions: [] }]);
  let v = e.view(); assert.equal(v.rows, 16); assert.equal(v.pageInfo, '1–16 / 20');
  e.click('goto-page', { 'data-p': '1' }); await e.flush();
  v = e.view(); assert.equal(v.rows, 4); assert.equal(v.pageInfo, '17–20 / 20');
  e.click('pick-operator', { 'data-k': '가짜A' }); await e.flush();
  v = e.view(); assert.equal(v.rows, 10); assert.equal(v.opLabel, '운영자: 가짜A'); assert.equal(v.pageInfo, '1–10 / 10');
  e.click('open-drawer', { 'data-id': '1000' }); await e.flush();
  v = e.view(); assert.equal(v.drawer, true); assert.equal(v.drawerId, 'log_id 1000');
  e.click('close-drawer'); await e.flush();
  assert.equal(e.view().drawer, false);
});

test('KST 기간 질의: UTC 와 KST 날짜가 다른 시각에도 서울 날짜로 보냄', async () => {
  const e = await boot(ok('A'));
  const want = { today: '?date_from=2026-11-05&date_to=2026-11-05', '7d': '?date_from=2026-10-30&date_to=2026-11-05', '30d': '?date_from=2026-10-07&date_to=2026-11-05', all: '' };
  for (const p of ['today', '7d', '30d', 'all']) {
    e.click('pick-period', { 'data-period': p }); await e.flush();
    assert.equal(e.last().url, '/api/admin/activity-logs' + want[p], p);
    e.settle(e.last(), ok(p)); await e.flush();
    assert.deepEqual(e.view().periodOn, [p]);
  }
});

for (const st of [401, 403, 500]) {
  test(`HTTP ${st} JSON detail → 오류 상자+서버 문장, 다시 시도=같은 URL 1회 후 회복`, async () => {
    const e = await boot([st, { detail: '가짜 ' + st + ' 문장' }]);
    let v = e.view(); assert.deepEqual([v.loading, v.err, v.body], [false, true, false]);
    assert.equal(v.errMsg, '가짜 ' + st + ' 문장');
    e.click('retry-boot'); await e.flush();
    assert.equal(e.al().length, 2); assert.equal(e.last().url, '/api/admin/activity-logs');
    e.settle(e.last(), ok('A')); await e.flush();
    v = e.view(); assert.deepEqual([v.loading, v.err, v.body], [false, false, true]); assert.equal(v.rows, 3);
  });
}

test('HTTP 500 비JSON → 「오류 500」(popcornProgress 유무 무관) — 형식 오류 문구로 바뀌지 않음', async () => {
  for (const noProgress of [false, true]) {
    const v = (await boot([500, '<html>x</html>', 'text/html'], { noProgress })).view();
    assert.equal(v.err, true); assert.equal(v.errMsg, '오류 500');
  }
});

test('network → 「Failed to fetch」, 다시 시도 회복', async () => {
  const e = await boot('net');
  assert.equal(e.view().errMsg, 'Failed to fetch');
  e.click('retry-boot'); await e.flush();
  e.settle(e.last(), ZERO); await e.flush();
  assert.equal(e.view().body, true); assert.equal(e.view().empty, true);
});

// ── 형식 오류 200 ─────────────────────────────────────────────────────────
const MALFORMED = [
  ['HTML', '<!doctype html>login', 'text/html'], ['빈 본문', ''], ['null', 'null'], ['"abc"', '"abc"'], ['0', '0'], ['false', 'false'],
  ['배열 []', '[]'], ['빈 객체 {}', '{}'],
  ['items:null', { total: 0, limit: 500, items: null }], ['items 누락', { total: 0, limit: 500 }], ['items:{}', { total: 1, limit: 500, items: {} }],
  ['items:[null]', { total: 1, limit: 500, items: [null] }], ['items:[1]', { total: 1, limit: 500, items: [1] }], ['items:[[]]', { total: 1, limit: 500, items: [[]] }],
  ['total 누락', { limit: 500, items: [row(1)] }], ['total:"x"', { total: 'x', limit: 500, items: [] }], ['total:1.5', { total: 1.5, limit: 500, items: [] }],
  ['total < items', { total: 0, limit: 500, items: [row(1)] }], ['total:null', { total: null, limit: 500, items: [] }],
  ['limit 누락', { total: 0, items: [] }], ['limit:0', { total: 0, limit: 0, items: [] }], ['limit:"500"', { total: 0, limit: '500', items: [] }], ['limit:-1', { total: 0, limit: -1, items: [] }],
];
for (const [name, body, ct] of MALFORMED) {
  test(`200 ${name} → 조회 실패 「${FMT_ERR}」 + 다시 시도로 회복`, async () => {
    const e = await boot([200, body, ct]);
    let v = e.view();
    assert.deepEqual([v.loading, v.err, v.body], [false, true, false]);
    assert.equal(v.errMsg, FMT_ERR);
    e.click('retry-boot'); await e.flush();
    e.settle(e.last(), ok('A')); await e.flush();
    v = e.view(); assert.deepEqual([v.err, v.body, v.rows], [false, true, 3]);
  });
}

test('정상 화면 뒤 새로고침 200 {} → 직전 목록을 0건으로 바꾸지 않고 조회 실패', async () => {
  const e = await boot(ok('A'));
  e.click('refresh'); await e.flush(); e.settle(e.last(), [200, '{}']); await e.flush();
  const v = e.view(); assert.equal(v.err, true); assert.equal(v.errMsg, FMT_ERR); assert.equal(v.body, false);
});

// ── 역순 도착 · 기간 전환 ──────────────────────────────────────────────────
test('역순: 7d(느림)→오늘(빠름) — 늦은 7d 응답을 버리고 오늘 화면 유지', async () => {
  const e = await boot(ok('ALL'));
  e.click('pick-period', { 'data-period': '7d' }); const c7 = e.last();
  e.click('pick-period', { 'data-period': 'today' }); const cT = e.last();
  await e.flush();
  e.settle(cT, ok('TODAY')); await e.flush();
  e.settle(c7, ok('7D')); await e.flush();
  const v = e.view();
  assert.deepEqual(v.periodOn, ['today']); assert.match(v.tbody, /가짜운영자TODAY/); assert.doesNotMatch(v.tbody, /7D/);
});

test('역순: 늦은 이전 500 이 최신 정상 화면을 덮지 않음', async () => {
  const e = await boot(ok('ALL'));
  e.click('refresh'); const c1 = e.last();
  e.click('pick-period', { 'data-period': '30d' }); const c2 = e.last();
  await e.flush();
  e.settle(c2, ok('30D')); await e.flush();
  e.settle(c1, [500, { detail: '늦은 오류' }]); await e.flush();
  const v = e.view(); assert.equal(v.err, false); assert.equal(v.body, true); assert.match(v.tbody, /가짜운영자30D/);
});

test('역순: 늦은 이전 network 실패·형식 오류도 버림', async () => {
  for (const late of ['net', [200, '{}']]) {
    const e = await boot(ok('ALL'));
    e.click('pick-period', { 'data-period': '7d' }); const c1 = e.last();
    e.click('pick-period', { 'data-period': 'all' }); const c2 = e.last();
    await e.flush();
    e.settle(c2, ok('ALL2')); await e.flush();
    e.settle(c1, late); await e.flush();
    const v = e.view(); assert.equal(v.err, false); assert.match(v.tbody, /가짜운영자ALL2/);
  }
});

test('역순: 최신 요청이 실패면 늦은 이전 정상 응답이 오류를 지우지 않음', async () => {
  const e = await boot(ok('ALL'));
  e.click('pick-period', { 'data-period': '7d' }); const c1 = e.last();
  e.click('pick-period', { 'data-period': 'today' }); const c2 = e.last();
  await e.flush();
  e.settle(c2, [500, { detail: '최신 오류' }]); await e.flush();
  e.settle(c1, ok('7D')); await e.flush();
  // 오류 상태에서는 본문(기간 버튼 포함)이 숨겨진다 — 오류 문구가 최신 요청 것인지만 본다.
  const v = e.view(); assert.deepEqual([v.err, v.body], [true, false]); assert.equal(v.errMsg, '최신 오류');
  e.click('retry-boot'); await e.flush();
  assert.equal(e.last().url, '/api/admin/activity-logs?date_from=2026-11-05&date_to=2026-11-05', '다시 시도는 최신 기간(오늘)');
});

test('기간 전환 대기 중: 이전 기간 자료·건수를 숨기고 로딩, 서랍 선택 해제', async () => {
  const e = await boot(ok('ALL', { total: 900 }));
  e.click('open-drawer', { 'data-id': '902' }); await e.flush();
  assert.equal(e.view().drawer, true);
  e.click('pick-period', { 'data-period': '7d' }); await e.flush();
  let v = e.view();
  assert.deepEqual([v.loading, v.err, v.body, v.drawer], [true, false, false, false]);
  e.settle(e.last(), ok('7D')); await e.flush();
  v = e.view(); assert.deepEqual(v.periodOn, ['7d']); assert.match(v.tbody, /가짜운영자7D/); assert.equal(v.drawer, false);
});

test('필터 초기화(기간≠전체)는 기간 전환 — 대기 중 로딩, 응답 후 전체 기간·필터 해제', async () => {
  const e = await boot(ok('A'));
  e.click('pick-period', { 'data-period': 'today' }); await e.flush(); e.settle(e.last(), ok('B')); await e.flush();
  e.click('pick-operator', { 'data-k': '가짜운영자B' }); await e.flush();
  e.click('reset-filters'); await e.flush();
  assert.equal(e.view().loading, true); assert.equal(e.last().url, '/api/admin/activity-logs');
  e.settle(e.last(), ok('C')); await e.flush();
  const v = e.view(); assert.equal(v.rows, 3); assert.deepEqual(v.periodOn, ['all']); assert.equal(v.opLabel, '운영자: 전체');
});

test('같은 기간 새로고침 대기 중: 기존 자료 표시 유지(로딩으로 내리지 않음)', async () => {
  // 서랍은 새로고침 버튼(data-keep 밖) 클릭 자체가 기존 바깥 클릭 규칙으로 닫는다 — 여기선 자료만 본다.
  const e = await boot(ok('ALL', { total: 900 }));
  e.click('refresh'); await e.flush();
  const v = e.view();
  assert.deepEqual([v.loading, v.err, v.body], [false, false, true]); assert.match(v.tbody, /가짜운영자ALL/);
  assert.equal(v.chip, '최근 500건만 표시 — 서버 상한(전체 900건 중)');
  e.settle(e.last(), ok('ALL2')); await e.flush();
  assert.match(e.view().tbody, /가짜운영자ALL2/);
});

test('오류 후 같은 기간 다시 시도 대기 중: 기존 UX 유지(직전 정상 자료 재노출)', async () => {
  const e = await boot(ok('ALL'));
  e.click('refresh'); await e.flush();
  e.settle(e.last(), [500, { detail: 'x' }]); await e.flush();
  assert.equal(e.view().err, true);
  e.click('retry-boot'); await e.flush();
  const v = e.view(); assert.deepEqual([v.loading, v.err, v.body], [false, false, true]); assert.match(v.tbody, /가짜운영자ALL/);
});

test('필터는 기간 전환 뒤에도 유지 — 새 자료에 없는 값이면 빈 상태, 초기화로 회복', async () => {
  const e = await boot(ok('A'));
  e.click('pick-operator', { 'data-k': '가짜운영자A' }); await e.flush();
  e.click('pick-period', { 'data-period': '7d' }); await e.flush();
  e.settle(e.last(), ok('B')); await e.flush();
  const v = e.view(); assert.equal(v.empty, true); assert.equal(v.opLabel, '운영자: 가짜운영자A');
});
