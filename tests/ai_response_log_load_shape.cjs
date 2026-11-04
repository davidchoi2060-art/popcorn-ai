"use strict";
// ADMIN-AI-RESPONSE-READ-AUDIT — AI 응답 기록 화면(ai_response_log.html.j2)의 실측 조회 loadMeasured()를
// «실제 페이지 스크립트» 통째로 실행한다. 실제 errText(ui-progress.js 본문에서 그 함수만)를
// 읽어 쓴다. 가짜 DOM·가짜 fetch·가짜 자료만 쓴다. 실제 API·DB·로그·대화·LLM 없음.
//
// 결함 ①(D1·D1b·D4): HTTP 200 인데 본문이 깨졌거나 형이 다르면
//   - {}·[]·"abc"·reasons:null 을 「이 화면의 기록은 0건입니다」 정상 화면으로 그리되 이유 카드·안내를 비웠고
//   - 0·false 면 「불러오는 중…」 에 멈춰 다시 시도 버튼도 없었고
//   - null·HTML·tasks:{}·models:"x"·reasons:[null] 등은 JS 오류 원문을 오류 상자에 띄웠다.
//   소유 GET(api/admin_ai_logs.py)은 항상 items [] · total 0 을 돌려주고 화면은 「0건」을 고정 표시하므로,
//   items 가 비지 않았거나 total 이 0 이 아니면 계약 위반으로 드러낸다(양수 목록 표시 기능 아님).
// 결함 ②(D2): 요청 순번이 없어 늦게 도착한 이전 요청의 정상·500·network 응답이 최신 요청 결과를 덮었다.
// 결함 ③(D3): 대기 중 미리보기 -> 실측 복귀 때 같은 요청을 한 번 더 보내거나(첫 로드),
//   이전 요청 자료를 로딩 표시 없이 새 필터 칩 아래 다시 보였다.
// 기대: 형식 오류는 「조회 실패」 + 「응답 형식이 올바르지 않습니다 (HTTP 200)」 + 다시 시도.
//   정상 0건(빈 tasks·models·reasons·note "" 포함)은 오류가 아니다. filters_echo 는 요구하지 않는다.
//   가장 최근 요청의 응답만 반영하고 그 응답만 로딩을 끝낸다. 대기 중에는 실측 화면을 로딩으로 두고,
//   미리보기 목록·서랍은 건드리지 않으며, 복귀 때 중복 요청을 보내지 않는다.
// 기준 비교: AR_TEMPLATE=<다른 ai_response_log.html.j2 경로> 로 같은 검사를 그 파일에 돌린다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const TPL = process.env.AR_TEMPLATE || path.join(ROOT, 'templates/admin/ai_response_log.html.j2');
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

// ── 가짜 DOM: 이 스크립트가 쓰는 API 만 흉내낸다 ─────────────────────────
class El {
  constructor(id, o) { o = o || {}; this.id = id; this.hidden = false; this._html = ''; this._text = ''; this.attrs = Object.assign({}, o.attrs || {}); this.cls = new Set(); this.style = {}; this.group = !!o.group; }
  set innerHTML(v) { this._html = String(v); this._text = ''; }
  get innerHTML() { return this._html; }
  set textContent(v) { this._text = String(v); this._html = ''; }
  get textContent() { return this._text || this._html.replace(/<[^>]*>/g, ''); }
  getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; }
  get classList() { const s = this.cls; return { toggle: (c, on) => { (on === undefined ? !s.has(c) : on) ? s.add(c) : s.delete(c); }, contains: (c) => s.has(c) }; }
  closest(sel) {
    if (sel === '.filter-group') return this.group ? this : null;
    const mm = /^\[(.+)\]$/.exec(sel); return mm && this.attrs[mm[1]] != null ? this : null;
  }
}
const IDS = ['banner', 'bannerMark', 'bannerTitle', 'bannerDesc', 'modeMeasured', 'modePreview',
  'pillPeriodLabel', 'pillTaskLabel', 'pillTask', 'pillModelLabel', 'pillModel', 'pillFlagged', 'scopeNote',
  'menuPeriod', 'menuTask', 'menuModel', 'tbody', 'scrim', 'drawer',
  'dwTask', 'dwQuestion', 'dwAt', 'dwModel', 'dwLatency', 'dwTokens', 'dwBody', 'dwFoot', 'dwFlagBtn'];

function makeEnv(opts) {
  opts = opts || {};
  const els = {};
  IDS.forEach((id) => { els[id] = new El(id); });
  els.tbody.innerHTML = '<div class="loaderr">불러오는 중…</div>'; // 마크업 초기값
  ['menuPeriod', 'menuTask', 'menuModel', 'scrim', 'drawer'].forEach((k) => { els[k].hidden = true; });
  els.modeMeasured.cls.add('on');
  const listeners = {};
  const document = { getElementById: (id) => els[id] || null, addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); } };
  const calls = [];
  function fetch(url, init) {
    let res, rej; const p = new Promise((a, b) => { res = a; rej = b; });
    calls.push({ url: String(url), init, resolve: res, reject: rej, settled: false });
    return p;
  }
  function settle(c, r) {
    assert.ok(!c.settled, 'double settle'); c.settled = true;
    if (r === 'net') return c.reject(new TypeError('Failed to fetch'));
    const body = typeof r[1] === 'string' ? r[1] : JSON.stringify(r[1]);
    c.resolve(new Response(body, { status: r[0], headers: { 'content-type': r[2] || 'application/json' } }));
  }
  const toasts = [];
  const ctx = { document, fetch, Response, console, setTimeout, clearTimeout, Promise, Number, String, Array, Object, Set, isFinite, isNaN, Math, Date, JSON, RegExp, Error, TypeError, encodeURIComponent };
  ctx.window = ctx;
  ctx.Admin2Shell = { isKeepClick: (t) => !!(t && t.attrs && t.attrs['data-keep'] != null), toast: (msg, k) => toasts.push([msg, k]) };
  vm.createContext(ctx);
  if (!opts.noProgress) vm.runInContext(ERRTEXT + '\nwindow.popcornProgress={errText:errText};', ctx);
  vm.runInContext(SCRIPT, ctx, { filename: 'ai_response_log.inline.js' });
  const flush = async (n = 8) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };
  function fire(type, ev) { (listeners[type] || []).forEach((fn) => fn(ev)); }
  // 실제 위치에서 누른다: 모드 스위치·필터 바·서랍은 data-keep 영역, 행·바깥은 아님
  function click(action, attrs, o) {
    o = o || {}; const a = Object.assign({}, attrs || {});
    if (action) a['data-action'] = action; if (o.keep) a['data-keep'] = '1';
    fire('click', { target: new El(null, { attrs: a, group: !!o.group }) });
  }
  const tb = () => els.tbody.innerHTML;
  const view = () => ({
    loading: /불러오는 중/.test(tb()),
    err: /class="ti">(조회 실패|세션 만료)/.test(tb()),
    errTitle: (/class="ti">(조회 실패|세션 만료)/.exec(tb()) || [])[1] || null,
    errMsg: (/<div class="ds">([^<]*)<\/div><button/.exec(tb()) || [])[1] || null,
    retryBtn: /data-action="retry-measured"/.test(tb()),
    reasons: (tb().match(/class="reason-card"/g) || []).length,
    zeroHead: /이 화면의 기록은 0건입니다/.test(tb()),
    note: (/<div class="precond">([^<]*)<\/div>/.exec(tb()) || [null, null])[1],
    rows: (tb().match(/class="row/g) || []).length,
    previewEmpty: /이 필터에는 예시가 없습니다/.test(tb()),
    scope: els.scopeNote.textContent, bannerPreview: els.banner.cls.has('preview'),
    mode: els.modeMeasured.cls.has('on') ? 'measured' : (els.modePreview.cls.has('on') ? 'preview' : '?'),
    period: els.pillPeriodLabel.textContent, task: els.pillTaskLabel.textContent, model: els.pillModelLabel.textContent,
    menuModelOpts: [...els.menuModel.innerHTML.matchAll(/data-v="([^"]*)"/g)].map((x) => x[1]),
    menuTaskLabels: [...els.menuTask.innerHTML.matchAll(/>([^<]+)<\/div>/g)].map((x) => x[1]),
    drawer: !els.drawer.hidden, scrim: !els.scrim.hidden, dwQuestion: els.dwQuestion.textContent,
    tbody: tb(),
  });
  const ar = () => calls.filter((c) => c.url.startsWith('/api/admin/ai-response-log'));
  return { els, calls, settle, flush, click, fire, view, toasts, ar, at: (i) => ar()[i], last: () => ar()[ar().length - 1] };
}

// ── 가짜 응답: api/admin_ai_logs.py 반환 모양 그대로, 값은 전부 가짜 ──
function ok(tag, o) {
  const reasons = ['api_cost_logs', 'spec_web_suggestions', 'ops_helper_chat', 'llm_calls'].map((k, i) => Object.assign(
    { key: k, name: '가짜갈래' + i + tag, chip: '가짜칩' + i, measured: '가짜측정 ' + i + tag, why: '가짜사유 ' + i },
    k === 'llm_calls' ? { link: '/admin2/talk-review', link_label: '가짜열기' } : {}));
  return Object.assign({ items: [], total: 0,
    tasks: [{ key: 'task.s1_parse', label: '가짜파싱' + tag }, { key: 'task.s2_explain', label: '가짜설명' }, { key: 'task.ops_assist', label: '가짜도우미' }, { key: 'task.spec_fill', label: '가짜채움' }],
    models: ['fake-model-a', 'fake-model-b'],
    filters_echo: { task: null, model: null, period: null, flagged: false },
    reasons, note: '가짜노트' + tag }, o || {});
}
const K = { keep: 1 };
const URL0 = '/api/admin/ai-response-log?period=' + encodeURIComponent('오늘') + '&flagged=0';
const SHAPE = '이유 목록을 받지 못했습니다 — 응답 형식이 올바르지 않습니다 (HTTP 200)';

async function boot(first, opts) {
  const e = makeEnv(opts); await e.flush();
  assert.equal(e.ar().length, 1); assert.equal(e.at(0).url, URL0); assert.equal(e.at(0).init.credentials, 'same-origin');
  assert.equal(e.view().loading, true, '첫 응답 전 로딩');
  if (first) { e.settle(e.at(0), first); await e.flush(); }
  return e;
}
function normal0(v, tag) {
  assert.equal(v.loading, false); assert.equal(v.err, false); assert.equal(v.zeroHead, true);
  if (tag) { assert.equal(v.reasons, 4); assert.equal(v.note, '가짜노트' + tag); }
}
function shapeErr(v) {
  assert.equal(v.loading, false); assert.equal(v.zeroHead, false);
  assert.equal(v.errTitle, '조회 실패'); assert.equal(v.errMsg, SHAPE); assert.equal(v.retryBtn, true);
}

// ── 정상 계약 ────────────────────────────────────────────────────────────
test('정상 0건: 0건 머리말 + 이유 4카드 + note + 서버 작업 라벨·모델 메뉴 + 내부 링크', async () => {
  const e = await boot([200, ok('A')]);
  const v = e.view(); normal0(v, 'A');
  assert.equal(v.scope, '0건 · 전문 열람: 모든 등급');
  assert.deepEqual(v.menuModelOpts, ['', 'fake-model-a', 'fake-model-b']);
  assert.ok(v.menuTaskLabels.includes('가짜파싱A'));
  assert.match(v.tbody, /<a class="reason-link" href="\/admin2\/talk-review">가짜열기<\/a>/);
  assert.equal(v.bannerPreview, false);
});

test('정상 0건: 빈 tasks·models·reasons 와 note "" 는 오류가 아니다(최소 개수 정책 없음) · filters_echo 없어도 정상', async () => {
  const p = ok('A', { tasks: [], models: [], reasons: [], note: '' }); delete p.filters_echo;
  const e = await boot([200, p]);
  const v = e.view(); normal0(v); assert.equal(v.reasons, 0); assert.equal(v.note, '');
});

test('reason.link 가 /admin2/ 밖이면 링크를 만들지 않는다', async () => {
  const p = ok('A'); p.reasons[3].link = 'https://example.invalid/';
  const e = await boot([200, p]);
  assert.doesNotMatch(e.view().tbody, /reason-link/);
});

for (const [st, body, ct, title, msg] of [
  [401, { detail: '가짜401' }, null, '세션 만료', '관리자 로그인 후 다시 조회합니다.'],
  [403, { detail: '가짜403' }, null, '조회 실패', '이유 목록을 받지 못했습니다 — 가짜403'],
  [422, { detail: [{ loc: ['query', 'flagged'], msg: '가짜' }] }, null, '조회 실패', '이유 목록을 받지 못했습니다 — flagged: 가짜'],
  [500, { detail: '가짜500' }, null, '조회 실패', '이유 목록을 받지 못했습니다 — 가짜500'],
  [500, '<html>x</html>', 'text/html', '조회 실패', '이유 목록을 받지 못했습니다 — 오류 500'],
]) {
  test(`HTTP ${st}${ct ? ' 비JSON' : ''}: 오류 상자 「${title}」 + 다시 시도 = 같은 URL 1회 → 회복`, async () => {
    const e = await boot([st, body, ct]);
    let v = e.view(); assert.equal(v.errTitle, title); assert.equal(v.errMsg, msg); assert.equal(v.retryBtn, true);
    e.click('retry-measured'); await e.flush();
    assert.equal(e.ar().length, 2); assert.equal(e.at(1).url, URL0); assert.equal(e.view().loading, true);
    e.settle(e.at(1), [200, ok('R')]); await e.flush();
    normal0(e.view(), 'R');
  });
}

test('popcornProgress 없음 + 500 → 「오류 500」', async () => {
  const e = await boot([500, { detail: 'x' }], { noProgress: 1 });
  assert.equal(e.view().errMsg, '이유 목록을 받지 못했습니다 — 오류 500');
});

test('network 실패 → 「Failed to fetch」, 다시 시도 회복', async () => {
  const e = await boot('net');
  assert.equal(e.view().errMsg, '이유 목록을 받지 못했습니다 — Failed to fetch');
  e.click('retry-measured'); await e.flush(); e.settle(e.at(1), [200, ok('R')]); await e.flush();
  normal0(e.view(), 'R');
});

test('필터 변경 → task·model·period·flagged 질의로 재요청, 대기 중 로딩, 최신 응답으로 회복', async () => {
  const e = await boot([200, ok('A')]);
  e.click('set-period', { 'data-v': '최근 7일' }, K); e.click('set-task', { 'data-v': 'task.s1_parse' }, K);
  e.click('set-model', { 'data-v': 'fake-model-a' }, K); e.click('toggle-flagged', {}, K); await e.flush();
  assert.equal(e.ar().length, 5);
  assert.equal(e.last().url, '/api/admin/ai-response-log?task=task.s1_parse&model=fake-model-a&period=' + encodeURIComponent('최근 7일') + '&flagged=1');
  assert.equal(e.view().loading, true);
  e.settle(e.last(), [200, ok('F')]); await e.flush();
  normal0(e.view(), 'F');
});

test('미리보기: 빨간 배너·예시 7행·서랍 열기/Esc/바깥 클릭 닫기·플래그 메모리 토글(서버 쓰기 0)', async () => {
  const e = await boot([200, ok('A')]);
  e.click('set-mode', { 'data-mode': 'preview' }, K); await e.flush();
  let v = e.view(); assert.equal(v.mode, 'preview'); assert.equal(v.bannerPreview, true); assert.equal(v.rows, 7);
  assert.equal(v.scope, '7건 (예시) · 전문은 자르지 않습니다');
  e.click('open-row', { 'data-idx': '1' }); v = e.view(); assert.equal(v.drawer, true); assert.equal(v.scrim, true);
  e.click('toggle-flag', {}, K); assert.equal(e.toasts.length, 1);
  e.fire('keydown', { key: 'Escape' }); assert.equal(e.view().drawer, false);
  e.click('open-row', { 'data-idx': '0' }); e.click(null, {}); assert.equal(e.view().drawer, false, '바깥 클릭 닫힘');
  e.click('open-row', { 'data-idx': '0' }); e.click('set-mode', { 'data-mode': 'measured' }, K); await e.flush();
  v = e.view(); assert.equal(v.drawer, false); assert.equal(v.scrim, false); normal0(v, 'A');
  assert.equal(e.calls.length, 1, '캐시가 있으면 재요청 없음 · 서버 쓰기 0');
});

// ── 결함 ④(Anti 추가 발견 5): 미리보기 선택 행이 필터·플래그 해제로 목록에서 빠져도 서랍 잔류 ──
// 필터 바는 data-keep 이라 바깥 클릭 닫기가 돌지 않는다. 실제 DOM(drawer·scrim hidden)으로 단정한다.
async function previewOpen(idx) {
  const e = await boot([200, ok('A')]);
  e.click('set-mode', { 'data-mode': 'preview' }, K); e.click('open-row', { 'data-idx': String(idx) });
  assert.equal(e.view().drawer, true); assert.equal(e.view().scrim, true);
  return e;
}
const selRow = (e) => (e.els.tbody.innerHTML.match(/class="row on"/g) || []).length;
for (const [name, act, rows] of [
  ['작업 종류(입력 파싱 행 → 근거 설명)', (e) => e.click('set-task', { 'data-v': 'task.s2_explain' }, K), 3],
  ['모델(haiku 행 → gpt-5.6-sol)', (e) => e.click('set-model', { 'data-v': 'gpt-5.6-sol' }, K), 3],
  ['플래그된 것만(플래그 없는 행)', (e) => e.click('toggle-flagged', {}, K), 1],
]) {
  test(`미리보기 서랍: ${name} 필터로 선택 행이 빠지면 서랍·스크림 숨김`, async () => {
    const e = await previewOpen(1);
    act(e); await e.flush();
    const v = e.view(); assert.equal(v.rows, rows); assert.equal(v.drawer, false); assert.equal(v.scrim, false); assert.equal(selRow(e), 0);
    e.click('open-row', { 'data-idx': '3' }); assert.equal(e.view().drawer, rows === 3, '남은 행은 다시 열 수 있음');
  });
}
test('미리보기 서랍: 플래그된 것만 켠 채 서랍에서 플래그 해제 → 행이 빠지며 서랍·스크림 숨김', async () => {
  const e = await previewOpen(0);
  e.click('toggle-flagged', {}, K); assert.equal(e.view().drawer, true); assert.equal(selRow(e), 1, '선택 행이 보이면 유지');
  e.click('toggle-flag', {}, K); await e.flush();
  const v = e.view(); assert.equal(v.rows, 0); assert.equal(v.previewEmpty, true); assert.equal(v.drawer, false); assert.equal(v.scrim, false);
});
// O7: 서랍의 플래그 토글 뒤 필터 바 건수(scopeNote)가 목록과 어긋났다(「플래그된 것만」 마지막 해제 → 0행인데 「1건」).
const scopeRows = (e) => { const v = e.view(); assert.equal(v.scope, v.rows + '건 (예시) · 전문은 자르지 않습니다', '건수 표시 = 실제 목록 행 수'); return v; };
test('미리보기 건수: 플래그된 것만 켠 채 마지막 플래그 해제 → 목록 0행·「0건 (예시)」·서랍/스크림 숨김', async () => {
  const e = await previewOpen(0);
  e.click('toggle-flagged', {}, K); let v = scopeRows(e); assert.equal(v.rows, 1);
  e.click('toggle-flag', {}, K); await e.flush();
  v = scopeRows(e); assert.equal(v.rows, 0); assert.equal(v.scope, '0건 (예시) · 전문은 자르지 않습니다');
  assert.equal(v.previewEmpty, true); assert.equal(v.drawer, false); assert.equal(v.scrim, false);
  e.click('toggle-flagged', {}, K); v = scopeRows(e); assert.equal(v.rows, 7);
});
test('미리보기 건수: 플래그된 것만 켠 채 다른 행 플래그 → 건수 증가와 목록 일치, 서랍 유지', async () => {
  const e = await previewOpen(1);
  e.click('toggle-flag', {}, K); await e.flush();            // idx1 플래그(전체 보기 중) → 7행 그대로
  scopeRows(e); assert.equal(e.view().drawer, true);
  e.click('toggle-flagged', {}, K); let v = scopeRows(e); assert.equal(v.rows, 2); assert.equal(v.drawer, true);
  e.click('toggle-flag', {}, K); await e.flush();            // idx1 해제 → 1행, 서랍 닫힘
  v = scopeRows(e); assert.equal(v.rows, 1); assert.equal(v.drawer, false); assert.equal(v.scrim, false);
  assert.equal(e.calls.length, 1, '서버 요청·쓰기 0');
});

test('미리보기 서랍: 선택 행이 계속 보이는 필터 변경·플래그 토글은 서랍 유지(기존 동작)', async () => {
  const e = await previewOpen(1);
  e.click('set-task', { 'data-v': 'task.s1_parse' }, K); e.click('set-model', { 'data-v': 'claude-haiku-4-5-20251001' }, K); await e.flush();
  let v = e.view(); assert.equal(v.rows, 2); assert.equal(v.drawer, true); assert.equal(v.scrim, true); assert.equal(selRow(e), 1);
  assert.equal(v.dwQuestion, '배그 롤 돌릴 150만원대 본체 견적 부탁');
  e.click('toggle-flag', {}, K); await e.flush();
  v = e.view(); assert.equal(v.drawer, true); assert.match(e.els.dwFlagBtn.textContent, /플래그 해제/);
  assert.equal(e.calls.length, 1, '서버 요청·쓰기 0');
});

// ── 결함 ①: 형식 오류 ─────────────────────────────────────────────────────
const BAD = [
  ['{}', {}], ['[]', []], ['"abc"', '"abc"'], ['0', '0'], ['false', 'false'], ['null', 'null'],
  ['HTML 200', '<html>x</html>'], ['빈 본문', ''],
  ['reasons:null', ok('A', { reasons: null })], ['reasons:{}', ok('A', { reasons: {} })],
  ['reasons:[null]', ok('A', { reasons: [null] })], ['reasons:[[]]', ok('A', { reasons: [[]] })], ['reasons:["x"]', ok('A', { reasons: ['x'] })],
  ['tasks 누락', ok('A', { tasks: undefined })], ['tasks:{}', ok('A', { tasks: {} })], ['tasks:[null]', ok('A', { tasks: [null] })],
  ['tasks key 숫자', ok('A', { tasks: [{ key: 1, label: 'x' }] })], ['tasks label 누락', ok('A', { tasks: [{ key: 'task.s1_parse' }] })],
  ['models 누락', ok('A', { models: undefined })], ['models:"x"', ok('A', { models: 'x' })], ['models:[1]', ok('A', { models: [1] })],
  ['note 누락', ok('A', { note: undefined })], ['note:null', ok('A', { note: null })], ['note:1', ok('A', { note: 1 })],
  ['items 누락', ok('A', { items: undefined })], ['items:null', ok('A', { items: null })], ['items:{}', ok('A', { items: {} })],
  ['total 누락', ok('A', { total: undefined })], ['total:"0"', ok('A', { total: '0' })],
  ['양수 total 5 + items 1행', ok('A', { total: 5, items: [{ fake: 1 }] })], ['total 0 + items 1행', ok('A', { items: [{ fake: 1 }] })],
  ['total 3 + items []', ok('A', { total: 3 })],
];
for (const [name, body] of BAD) {
  test(`형식 오류 200 ${name} → 조회 실패 + 형식 문구 + 다시 시도(정상 0건·무한 로딩·JS 원문 아님)`, async () => {
    const e = await boot([200, body]);
    shapeErr(e.view());
  });
}

test('형식 오류 후 다시 시도 → 같은 URL 1회 → 정상 회복', async () => {
  const e = await boot([200, {}]);
  shapeErr(e.view());
  e.click('retry-measured'); await e.flush();
  assert.equal(e.ar().length, 2); assert.equal(e.at(1).url, URL0);
  e.settle(e.at(1), [200, ok('R')]); await e.flush(); normal0(e.view(), 'R');
});

test('정상 화면 뒤 필터 변경 응답이 {} → 이유 카드가 비는 정상 화면이 아니라 조회 실패', async () => {
  const e = await boot([200, ok('A')]);
  e.click('set-period', { 'data-v': '최근 7일' }, K); await e.flush(); e.settle(e.at(1), [200, {}]); await e.flush();
  shapeErr(e.view()); assert.equal(e.view().period, '기간: 최근 7일');
});

// ── 결함 ②: 역순 응답 ─────────────────────────────────────────────────────
test('최신(30일) 성공 뒤 늦은 이전(7일) 500 → 무시, 최신 정상 화면 유지', async () => {
  const e = await boot([200, ok('A')]);
  e.click('set-period', { 'data-v': '최근 7일' }, K); e.click('set-period', { 'data-v': '최근 30일' }, K); await e.flush();
  e.settle(e.at(2), [200, ok('C')]); await e.flush(); normal0(e.view(), 'C');
  e.settle(e.at(1), [500, { detail: '가짜500' }]); await e.flush();
  normal0(e.view(), 'C'); assert.equal(e.view().period, '기간: 최근 30일');
});

test('최신 network 실패 뒤 늦은 이전 성공 → 무시, 최신 실패 유지', async () => {
  const e = await boot([200, ok('A')]);
  e.click('set-task', { 'data-v': 'task.s1_parse' }, K); e.click('set-task', { 'data-v': 'task.ops_assist' }, K); await e.flush();
  e.settle(e.at(2), 'net'); await e.flush();
  e.settle(e.at(1), [200, ok('B')]); await e.flush();
  const v = e.view(); assert.equal(v.errMsg, '이유 목록을 받지 못했습니다 — Failed to fetch'); assert.equal(v.task, '작업: 가짜도우미');
});

test('최신 대기 중 늦은 이전 성공·형식 오류 → 무시, 로딩 유지(최신 응답만 로딩 해제)', async () => {
  const e = await boot([200, ok('A')]);
  e.click('set-period', { 'data-v': '최근 7일' }, K); e.click('set-period', { 'data-v': '최근 30일' }, K); await e.flush();
  e.settle(e.at(1), [200, ok('OLD')]); await e.flush(); assert.equal(e.view().loading, true);
  e.click('set-period', { 'data-v': '오늘' }, K); await e.flush();
  e.settle(e.at(2), [200, {}]); await e.flush(); assert.equal(e.view().loading, true);
  e.settle(e.at(3), [200, ok('NEW')]); await e.flush(); normal0(e.view(), 'NEW');
});

// ── 결함 ③: 대기 중 미리보기 전환·복귀 ─────────────────────────────────────
test('첫 응답 대기 중 미리보기 → 실측 복귀: 중복 요청 없음·로딩 유지, 그 응답으로 정상', async () => {
  const e = await boot();
  e.click('set-mode', { 'data-mode': 'preview' }, K); e.click('set-mode', { 'data-mode': 'measured' }, K); await e.flush();
  assert.equal(e.ar().length, 1, '중복 요청 0'); assert.equal(e.view().loading, true); assert.equal(e.view().rows, 0, '예시 행 잔류 0');
  e.settle(e.at(0), [200, ok('A')]); await e.flush(); normal0(e.view(), 'A');
});

test('필터 변경 대기 중 미리보기 → 실측 복귀: 이전 자료 대신 로딩, 재요청 없음, 최신 응답으로 정상', async () => {
  const e = await boot([200, ok('A')]);
  e.click('set-period', { 'data-v': '최근 7일' }, K); await e.flush();
  e.click('set-mode', { 'data-mode': 'preview' }, K); e.click('set-mode', { 'data-mode': 'measured' }, K); await e.flush();
  let v = e.view(); assert.equal(v.loading, true); assert.equal(v.zeroHead, false); assert.equal(v.reasons, 0);
  assert.equal(e.ar().length, 2);
  e.settle(e.at(1), [200, ok('B')]); await e.flush(); normal0(e.view(), 'B');
});

test('오류 뒤 다시 시도 대기 중 미리보기 → 복귀: 이전 오류 재노출 없이 로딩, 중복 요청 없음', async () => {
  const e = await boot([500, { detail: 'x' }]);
  e.click('retry-measured'); await e.flush();
  e.click('set-mode', { 'data-mode': 'preview' }, K); e.click('set-mode', { 'data-mode': 'measured' }, K); await e.flush();
  const v = e.view(); assert.equal(v.loading, true); assert.equal(v.err, false); assert.equal(e.ar().length, 2);
});

test('대기 중 미리보기: 늦은 응답(성공·실패·형식 오류)이 예시 목록·열린 서랍 DOM 을 덮지 않음 · 복귀: 성공은 그 결과, 실패는 기존대로 1회 재조회(이전 오류 재노출 없이 로딩)', async () => {
  const again = (e) => { const v = e.view(); assert.equal(v.loading, true); assert.equal(v.err, false); e.settle(e.at(1), [200, ok('R')]); return e.flush().then(() => normal0(e.view(), 'R')); };
  for (const [r, check] of [[[200, ok('A')], (e) => normal0(e.view(), 'A')], [[500, { detail: '가짜' }], again], [[200, {}], again]]) {
    const e = await boot();
    e.click('set-mode', { 'data-mode': 'preview' }, K); e.click('open-row', { 'data-idx': '0' }); await e.flush();
    // 행 구조·선택·질문 문구를 비교한다(성공 응답이 작업 라벨을 서버 값으로 채우는 것은 기존 동작).
    const shape = () => [...e.els.tbody.innerHTML.matchAll(/<div class="(row[^"]*)" data-action="open-row" data-idx="(\d+)">[\s\S]*?<span class="q">([^<]*)<\/span>/g)].map((x) => x.slice(1).join('|'));
    const before = shape(), q = e.view().dwQuestion;
    assert.equal(before.length, 7);
    e.settle(e.at(0), r); await e.flush();
    const v = e.view(); assert.equal(v.mode, 'preview'); assert.deepEqual(shape(), before); assert.equal(v.drawer, true); assert.equal(v.dwQuestion, q);
    assert.equal(v.loading || v.err || v.zeroHead, false, '실측 화면이 미리보기 자리에 그려지지 않음');
    e.click('set-mode', { 'data-mode': 'measured' }, K); await e.flush();
    assert.equal(e.view().drawer, false);
    assert.equal(e.ar().length, r[0] === 200 && r[1].reasons ? 1 : 2, '성공 캐시면 재요청 0, 실패면 기존대로 복귀 때 1회');
    await check(e);
  }
});
