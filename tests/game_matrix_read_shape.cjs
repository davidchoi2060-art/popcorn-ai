"use strict";
// ADMIN-MATRIX-MINIMAL-READ-FIX — 용도별 상품 매트릭스(game_matrix.html.j2)의 «실제 content 마크업 + 실제 페이지 스크립트»를
// 가짜 DOM·가짜 fetch 위에서 통째로 실행한다. 실제 SSR·API·DB·상품·LLM 없음. 수치는 모두 가짜 값(성능값·사양 원천 아님).
//
// 결함 ①(D2): 선택 조회에 요청 순번이 없어 늦게 온 이전 응답(성공·실패)이 최신 선택 화면을 덮었다.
//   탭 전환 중 늦게 온 게임 응답은 AI 탭에 그려져 이름이 "undefined" 로 나왔고, 차단 탭으로 옮겨도 무효화되지 않았다.
// 결함 ②(D1): 한쪽 분류 매핑이 0건이면 cols 를 숨기면서 그 안의 게임/AI 탭까지 숨겨 다른 분류로 갈 길이 없었다.
// 결함 ③(D3): 선택 GET 응답의 selection 이 null·다른 kind·다른 항목·배열 아님이어도 검사 없이 그렸다.
// 결함 ④: 새 항목/탭 요청이 pending 인 동안 이전 항목의 성립 칸·근거 패널이 그대로 남았다.
// 보존: 정상 양수·격자 0·한쪽 매핑 0 배너·미매핑·필터 0건·근거 패널·바깥 클릭 해제·HTML escape·401/500 오류 문구,
//   다시 시도 = 전체 새로고침(D4 정책 불변), 판정 불가 라벨(D5 서버 어휘 불변).
// 기준 비교: GM_TEMPLATE=<다른 game_matrix.html.j2 경로> 로 같은 검사를 그 파일에 돌린다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const TPL = process.env.GM_TEMPLATE || path.join(ROOT, 'templates/admin/game_matrix.html.j2');
const tpl = fs.readFileSync(TPL, 'utf8').replace(/\r\n/g, '\n');
const mc = tpl.match(/\{% block content %\}([\s\S]*?)\{% endblock %\}/);
assert.ok(mc, 'content 블록을 찾지 못함');
const MARKUP = mc[1].replace(/\{#[\s\S]*?#\}/g, '');
assert.ok(!/\{\{|\{%/.test(MARKUP), 'Jinja 자리표시자가 content 마크업에 남음');
const ms = tpl.match(/\{% raw %\}\s*<script>([\s\S]*?)<\/script>\s*\{% endraw %\}/);
assert.ok(ms, 'foot_extra raw <script> 블록을 찾지 못함');
const SCRIPT = ms[1];

// ── 최소 가짜 DOM: 태그/.class/[attr]/[attr="v"] + 자손 결합자, closest, hidden, innerHTML 파서, select.value, 버블링 ──
const VOID = new Set(['input', 'br', 'img', 'meta', 'link', 'hr', 'col', 'source']);
const ENT = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" };
const decode = (s) => s.replace(/&(amp|lt|gt|quot|#39);/g, (m) => ENT[m]);
const encAttr = (s) => s.replace(/[&"]/g, (c) => ({ '&': '&amp;', '"': '&quot;' }[c]));
class Text { constructor(t) { this.nodeType = 3; this.data = t; this.parent = null; } }
class El {
  constructor(tag) { this.nodeType = 1; this.tagName = tag.toUpperCase(); this.attrs = new Map(); this.children = []; this.parent = null; this.listeners = {}; this._value = undefined; }
  getAttribute(n) { return this.attrs.has(n) ? this.attrs.get(n) : null; }
  setAttribute(n, v) { this.attrs.set(n, String(v)); }
  hasAttribute(n) { return this.attrs.has(n); }
  get hidden() { return this.attrs.has('hidden'); }
  set hidden(v) { if (v) this.attrs.set('hidden', ''); else this.attrs.delete('hidden'); }
  get className() { return this.getAttribute('class') || ''; }
  get textContent() { let s = ''; const r = (n) => { for (const c of n.children) { if (c.nodeType === 3) s += decode(c.data); else r(c); } }; r(this); return s; }
  get innerHTML() { return this.children.map(ser).join(''); }
  set innerHTML(html) { for (const c of this.children) c.parent = null; this.children = []; parseInto(this, String(html)); if (this.tagName === 'SELECT') this._value = undefined; }
  get options() { const o = []; walk(this, (e) => { if (e.tagName === 'OPTION') o.push(e); }); return o; }
  get value() {
    if (this.tagName === 'SELECT') {
      const opts = this.options;
      if (this._value === null) return '';
      if (this._value !== undefined && opts.some((o) => o.value === this._value)) return this._value;
      return opts[0] ? opts[0].value : '';
    }
    if (this.tagName === 'OPTION') return this.hasAttribute('value') ? this.getAttribute('value') : this.textContent;
    return this._value == null ? (this.getAttribute('value') || '') : this._value;
  }
  set value(v) { v = String(v); if (this.tagName === 'SELECT') { this._value = this.options.some((o) => o.value === v) ? v : null; return; } this._value = v; }
  matches(sel) { return sel.split(',').some((s) => matchComplex(this, parseSel(s.trim()))); }
  closest(sel) { let n = this; while (n && n.nodeType === 1) { if (n.matches(sel)) return n; n = n.parent; } return null; }
  querySelectorAll(sel) { const out = []; walk(this, (e) => { if (e.matches(sel)) out.push(e); }); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  get visible() { let n = this; while (n && n.nodeType === 1) { if (n.hidden) return false; n = n.parent; } return true; }
}
function walk(root, fn) { for (const c of root.children) if (c.nodeType === 1) { fn(c); walk(c, fn); } }
function ser(n) {
  if (n.nodeType === 3) return n.data;
  const t = n.tagName.toLowerCase(); let a = '';
  for (const [k, v] of n.attrs) a += v === '' && k === 'hidden' ? ' hidden' : ` ${k}="${encAttr(v)}"`;
  return VOID.has(t) ? `<${t}${a}>` : `<${t}${a}>${n.children.map(ser).join('')}</${t}>`;
}
function parseInto(parent, html) {
  const re = /<!--[\s\S]*?-->|<\/([a-zA-Z0-9]+)\s*>|<([a-zA-Z0-9]+)((?:\s+[^\s=>\/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*\/?>|([^<]+)/g;
  let cur = parent, m;
  while ((m = re.exec(html))) {
    if (m[0].startsWith('<!--')) continue;
    if (m[1]) { const t = m[1].toUpperCase(); let n = cur; while (n && n !== parent && n.tagName !== t) n = n.parent; if (n && n !== parent) cur = n.parent; continue; }
    if (m[2]) {
      const el = new El(m[2]); const ar = /([^\s=>\/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g; let a;
      while ((a = ar.exec(m[3] || ''))) el.attrs.set(a[1], decode(a[2] != null ? a[2] : a[3] != null ? a[3] : a[4] != null ? a[4] : ''));
      el.parent = cur; cur.children.push(el);
      if (!VOID.has(m[2].toLowerCase()) && !m[0].endsWith('/>')) cur = el;
      continue;
    }
    if (m[4] != null) { const t = new Text(m[4]); t.parent = cur; cur.children.push(t); }
  }
}
function parseSel(s) {
  return s.split(/\s+/).map((c) => {
    const o = { tag: null, cls: [], attrs: [] }; const re = /^([a-zA-Z0-9*]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g; let m;
    while ((m = re.exec(c))) { if (m[1]) o.tag = m[1].toUpperCase(); else if (m[2]) o.cls.push(m[2]); else o.attrs.push([m[3], m[4]]); }
    return o;
  });
}
function matchCompound(e, c) {
  if (c.tag && c.tag !== '*' && e.tagName !== c.tag) return false;
  const cl = e.className.split(/\s+/);
  return c.cls.every((x) => cl.includes(x)) && c.attrs.every(([k, v]) => e.hasAttribute(k) && (v === undefined || e.getAttribute(k) === v));
}
function matchComplex(e, parts) {
  if (!matchCompound(e, parts[parts.length - 1])) return false;
  let i = parts.length - 2, n = e.parent;
  while (i >= 0 && n && n.nodeType === 1) { if (matchCompound(n, parts[i])) i--; n = n.parent; }
  return i < 0;
}
function makeDocument(html) {
  const doc = { listeners: {} }; const body = new El('body'); parseInto(body, html);
  doc.body = body;
  doc.querySelector = (s) => body.querySelector(s);
  doc.querySelectorAll = (s) => body.querySelectorAll(s);
  doc.addEventListener = (t, f) => (doc.listeners[t] = doc.listeners[t] || []).push(f);
  doc.dispatch = (type, target) => {
    const ev = { type, target, preventDefault() {} };
    let n = target; while (n && n.nodeType === 1) { (n.listeners[type] || []).forEach((f) => f.call(n, ev)); n = n.parent; }
    (doc.listeners[type] || []).forEach((f) => f(ev));
  };
  return doc;
}

// ── 가짜 자료(admin_game_matrix.py game_matrix()/_selection_cells() 반환 키 모양만 따름) ──
function game(id, name, extra) {
  return Object.assign({ game_id: id, name, genre: 'RPG', rec_gpu: 'RTX 4060', min_gpu: 'GTX 1060', rec_ram_gb: 16, min_ram_gb: 8,
    source_url: 'https://example.test/g' + id, checked_date: '2026-10-01', mapped_cells: 3, description: null,
    unjudgeable: false, unjudgeable_reason: null }, extra || {});
}
function wl(id, task, extra) {
  return Object.assign({ workload_id: id, task, model_size: '7B', min_vram_gb: 8, rec_vram_gb: 12, min_ram_gb: 16, recommended_tier: '중급',
    source_url: 'https://example.test/w' + id, checked_date: '2026-10-02', mapped_cells: 2, description: '쉬운 설명',
    unjudgeable: false, unjudgeable_reason: null }, extra || {});
}
function cell(id, total, extra) {
  return Object.assign({ cell_id: id, usage: '게임', platform: 'Intel', band_label: '100만원대', game_grade: 'A', game_resolution: 'QHD',
    match_level: '권장충족', gpu_used: 'RTX 4060', tier_variant: '기본', total, variants: [{ v: 1 }, { v: 2 }] }, extra || {});
}
function base(over) {
  const o = over || {};
  return {
    meta: Object.assign({ checked_date: '2026-10-03T09:00:00', games_total: 3, games_mapped: 2, ai_total: 2, ai_mapped: 1,
      game_map_rows: 5, workload_map_rows: 2, cell_count: 40, ladder_rows: 12 }, o.meta || {}),
    usages: ['게임', '영상편집'], platforms: ['Intel', 'AMD'], game_levels: ['권장충족', '최소충족'], workload_levels: ['권장구성', '최소구성'],
    ladder: { 'RTX 4060': { ladder_score: 7100, vram_gb: 8, source_url: 'https://example.test/ladder', checked_date: '2026-09-30' } },
    games: o.games || [game(1, '게임하나'), game(2, '게임둘'), game(3, '게임셋', { mapped_cells: 0, unjudgeable: true, unjudgeable_reason: '권장 GPU 원천 없음' })],
    workloads: o.workloads || [wl(11, '이미지생성'), wl(12, '음성인식', { mapped_cells: 0, unjudgeable_reason: '사유 있음' })],
    selection: null,
  };
}
function withSel(b, kind, item, cells, unmatched) {
  const u = unmatched || [];
  return Object.assign({}, b, { selection: { kind, item, cells, unmatched: u, unmatched_total: u.length + 5, unmatched_shown: u.length } });
}
const gameSel = (b, idx, cells) => withSel(b, 'game', b.games[idx], cells || [cell(101 + idx * 10, 1200000), cell(102 + idx * 10, 1500000)],
  [Object.assign(cell(900, 900000), { gpu_name: null })]);
const wlSel = (b, idx, cells) => withSel(b, 'workload', b.workloads[idx], cells || [cell(201, 1800000, { usage: 'AI', match_level: '권장구성' })]);

// ── 환경 ──
function makeEnv() {
  const doc = makeDocument(MARKUP); const calls = []; let reloads = 0;
  function fetch(url, init) {
    let res, rej; const p = new Promise((a, b) => { res = a; rej = b; });
    calls.push({ url: String(url), init: init || {}, resolve: res, reject: rej, settled: false });
    return p;
  }
  const ctx = { fetch, document: doc, console, Promise, Number, String, Array, Object, Date, JSON, Error, TypeError, encodeURIComponent,
    location: { reload: () => { reloads++; } } };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(SCRIPT, ctx, { filename: 'game_matrix.inline.js' });
  const flush = async (n = 8) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };
  async function settle(c, status, body) {
    assert.ok(c, '요청 없음'); assert.ok(!c.settled, '두 번 settle: ' + c.url); c.settled = true;
    if (status === 'net') c.reject(new TypeError('Failed to fetch'));
    else {
      const txt = typeof body === 'string' ? body : JSON.stringify(body);
      c.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve().then(() => JSON.parse(txt)) });
    }
    await flush();
  }
  const q = (s) => doc.querySelector(s);
  const B = (k) => q('[data-bind="' + k + '"]');
  const vis = (k) => B(k).visible;
  const txt = (k) => B(k).textContent.replace(/\s+/g, ' ').trim();
  const click = async (el) => { assert.ok(el, '클릭 대상 없음'); doc.dispatch('click', el); await flush(); };
  const mousedown = async (el) => { doc.dispatch('mousedown', el); await flush(); };
  const tab = (t) => q('[data-action="tab"][data-tab="' + t + '"]');
  const pick = (id) => q('[data-action="pick"][data-id="' + id + '"]');
  const cellRow = (id) => q('[data-action="cell"][data-cell-id="' + id + '"]');
  const current = () => { const e = q('[data-action="pick"][aria-current="true"]'); return e ? e.getAttribute('data-id') : null; };
  async function filter(k, v) { const e = B(k); e.value = v; doc.dispatch('change', e); await flush(); }
  const last = () => calls[calls.length - 1];
  const pending = () => calls.filter((c) => !c.settled);
  return { doc, calls, q, B, vis, txt, click, mousedown, tab, pick, cellRow, current, filter, settle, last, pending, flush, reloads: () => reloads };
}
// 부팅: base GET 응답 → (차단 아니면) 첫 게임 선택 GET 이 나간 상태로 돌려준다.
async function boot(b, opt) {
  const E = makeEnv(); await E.flush();
  assert.equal(E.calls.length, 1); assert.equal(E.calls[0].url, '/api/admin/game-matrix');
  assert.equal(E.calls[0].init.credentials, 'same-origin');
  await E.settle(E.calls[0], 200, b);
  if (opt && opt.firstSel) await E.settle(E.calls[1], 200, opt.firstSel);
  return E;
}
const okErr = (E) => !E.vis('load-error') && E.vis('content-area');

// ═════════════ 보존(정상 계약) ═════════════
test('정상 양수: 첫 게임 선택 GET·요약·목록·성립 칸·외 N벌·불성립·미매핑', async () => {
  const b = base(); const E = await boot(b);
  assert.equal(E.calls.length, 2); assert.equal(E.calls[1].url, '/api/admin/game-matrix?game_id=1');
  await E.settle(E.calls[1], 200, gameSel(b, 0));
  assert.ok(okErr(E));
  assert.equal(E.txt('m-games'), '2'); assert.equal(E.txt('m-cells'), '40'); assert.equal(E.txt('tab-games-n'), '3');
  assert.equal(E.current(), '1');
  assert.equal(E.txt('sel-name'), '게임하나');
  assert.match(E.txt('sel-count'), /성립 칸 2개 · 최저가 1,200,000원 \(전체 매핑 3칸\)/);
  assert.ok(E.vis('cells-wrap')); assert.ok(!E.vis('sel-unmapped')); assert.ok(!E.vis('sel-filtered'));
  assert.match(E.txt('cells'), /기본 외 1벌/);
  assert.ok(E.vis('fail-card')); assert.equal(E.txt('fail-count'), '6칸 중 1칸 표시'); assert.match(E.txt('fails'), /GPU 항목 없음.*불성립/);
  assert.equal(E.txt('skip-title'), '미매핑 1건'); assert.match(E.txt('skips'), /게임셋판정 불가 — 권장 GPU 원천 없음/);
  assert.ok(!E.vis('blocked')); assert.ok(E.vis('cols'));
});

test('정상 0: 격자 0 은 「격자 데이터 없음」, 선택 GET 없음', async () => {
  const E = await boot(base({ meta: { cell_count: 0 } }));
  assert.equal(E.calls.length, 1);
  assert.ok(E.vis('blocked')); assert.equal(E.txt('blocked-title'), '격자 데이터 없음'); assert.ok(!E.vis('cols'));
  assert.ok(okErr(E));
});

test('근거 패널: 칸 선택·서열 점수·출처, 같은 칸 다시 누르면 해제, data-keep 유지·바깥 해제', async () => {
  const b = base(); const E = await boot(b, { firstSel: gameSel(b, 0) });
  await E.click(E.cellRow(101));
  assert.ok(E.vis('ev-body')); assert.ok(!E.vis('ev-empty'));
  assert.match(E.txt('ev-body'), /RTX 4060 · ladder_score 7100/); assert.match(E.txt('ev-body'), /게임 요구사양 출처/);
  await E.mousedown(E.cellRow(101)); assert.ok(E.vis('ev-body'), 'data-keep 안쪽 mousedown 은 유지');
  await E.mousedown(E.tab('ai')); assert.ok(E.vis('ev-body'), '탭(data-keep) mousedown 은 유지');
  await E.mousedown(E.q('.gm-kicker')); assert.ok(!E.vis('ev-body'), '바깥 mousedown 은 해제');
  await E.click(E.cellRow(101)); assert.ok(E.vis('ev-body'));
  await E.click(E.cellRow(101)); assert.ok(!E.vis('ev-body'), '같은 칸 다시 누르면 해제');
});

test('필터: 쿼리 전달, 0건 「조회 결과 없음」, 미매핑 항목은 「판정 불가」', async () => {
  const b = base(); const E = await boot(b, { firstSel: gameSel(b, 0) });
  await E.filter('f-usage', '게임');
  assert.equal(E.last().url, '/api/admin/game-matrix?game_id=1&usage=' + encodeURIComponent('게임'));
  await E.settle(E.last(), 200, gameSel(b, 0, []));
  assert.ok(E.vis('sel-filtered')); assert.ok(!E.vis('cells-wrap'));
  await E.click(E.pick(3));
  await E.settle(E.last(), 200, withSel(b, 'game', b.games[2], [], []));
  assert.ok(E.vis('sel-unmapped')); assert.equal(E.txt('sel-unmapped-title'), '판정 불가');
});

test('HTML escape: 이름·사유의 마크업은 텍스트로', async () => {
  const b = base({ games: [game(1, '<img src=x onerror=1>'), game(2, '둘', { mapped_cells: 0, unjudgeable_reason: '<b>r</b>' })] });
  const E = await boot(b, { firstSel: gameSel(b, 0) });
  assert.equal(E.txt('sel-name'), '<img src=x onerror=1>'); assert.equal(E.B('sel-name').querySelector('img'), null);
  assert.equal(E.B('skips').querySelector('b'), null); assert.match(E.txt('skips'), /<b>r<\/b>/);
});

test('오류: base 401 은 로그인, 500 은 「매트릭스 조회 실패」+다시 시도=전체 새로고침(D4 불변)', async () => {
  let E = makeEnv(); await E.flush(); await E.settle(E.calls[0], 401, {});
  assert.equal(E.txt('err-title'), '세션 만료'); assert.ok(E.q('[data-bind="err-actions"] a[href="/admin2/login"]'));
  E = makeEnv(); await E.flush(); await E.settle(E.calls[0], 500, {});
  assert.equal(E.txt('err-title'), '매트릭스 조회 실패'); assert.match(E.txt('err-msg'), /HTTP 500/); assert.ok(!E.vis('content-area'));
  E.q('[data-action="retry"]').listeners.click[0]();
  assert.equal(E.reloads(), 1);
  E = makeEnv(); await E.flush(); await E.settle(E.calls[0], 200, {});
  assert.equal(E.txt('err-title'), '매트릭스 조회 실패', 'base {} 는 기존대로 오류');
});

test('탭 정상: AI 탭은 workload_id 요청, usage 유지·level 초기화, aria-selected', async () => {
  const b = base(); const E = await boot(b, { firstSel: gameSel(b, 0) });
  await E.filter('f-usage', '영상편집'); await E.settle(E.last(), 200, gameSel(b, 0));
  await E.filter('f-level', '권장충족'); await E.settle(E.last(), 200, gameSel(b, 0));
  await E.click(E.tab('ai'));
  assert.equal(E.last().url, '/api/admin/game-matrix?workload_id=11&usage=' + encodeURIComponent('영상편집'));
  assert.equal(E.tab('ai').getAttribute('aria-selected'), 'true'); assert.equal(E.tab('games').getAttribute('aria-selected'), 'false');
  await E.settle(E.last(), 200, wlSel(b, 0));
  assert.equal(E.txt('sel-name'), '이미지생성 · 7B'); assert.ok(okErr(E));
});

// ═════════════ 결함 ②(D1): 한쪽 매핑 0 → 탭 접근 유지 ═════════════
test('D1: 게임 매핑 0·AI 매핑 양수 — 배너는 뜨고 탭은 보이며 AI 로 갈 수 있다', async () => {
  const b = base({ meta: { game_map_rows: 0 } }); const E = await boot(b);
  assert.equal(E.calls.length, 1, '차단 탭에서는 선택 GET 없음');
  assert.ok(E.vis('blocked')); assert.equal(E.txt('blocked-title'), '매핑 미실행'); assert.match(E.txt('blocked-msg'), /게임별 매핑이 0건/);
  assert.ok(!E.q('.gm-list').visible, '차단 탭의 목록은 숨김');
  assert.ok(E.tab('ai').visible, 'AI 작업 탭 버튼이 보여야 함'); assert.ok(E.tab('games').visible);
  await E.click(E.tab('ai'));
  assert.equal(E.last().url, '/api/admin/game-matrix?workload_id=11');
  await E.settle(E.last(), 200, wlSel(b, 0));
  assert.ok(!E.vis('blocked')); assert.ok(E.vis('cols')); assert.equal(E.txt('sel-name'), '이미지생성 · 7B');
  await E.click(E.tab('games'));
  assert.ok(E.vis('blocked')); assert.ok(E.tab('ai').visible, '게임 탭으로 돌아와도 AI 탭 복귀 경로 유지');
});

// ═════════════ 결함 ①(D2): 요청 순번 ═════════════
test('D2: 선택 A 지연 중 B 선택 — 늦은 A 성공은 버림', async () => {
  const b = base(); const E = await boot(b);
  const a = E.calls[1];
  await E.click(E.pick(2)); const bb = E.last();
  await E.settle(bb, 200, gameSel(b, 1));
  await E.settle(a, 200, gameSel(b, 0));
  assert.equal(E.current(), '2'); assert.equal(E.txt('sel-name'), '게임둘');
  assert.ok(E.cellRow(111) && !E.cellRow(101), '중앙 칸은 B 의 것');
});

test('D2: 선택 A 지연 중 B 성공 — 늦은 A 실패(500·네트워크)는 최신 화면을 덮지 않음', async () => {
  for (const fail of [500, 'net']) {
    const b = base(); const E = await boot(b);
    const a = E.calls[1];
    await E.click(E.pick(2)); await E.settle(E.last(), 200, gameSel(b, 1));
    await E.settle(a, fail, {});
    assert.ok(okErr(E), '늦은 이전 실패(' + fail + ')가 오류 패널을 띄우면 안 됨');
    assert.equal(E.txt('sel-name'), '게임둘');
  }
});

test('D2: 최신 요청의 실패는 기존대로 오류 패널', async () => {
  const b = base(); const E = await boot(b);
  await E.settle(E.calls[1], 500, {});
  assert.equal(E.txt('err-title'), '매트릭스 조회 실패'); assert.match(E.txt('err-msg'), /HTTP 500/);
});

test('D2: 게임 지연 중 AI 탭 — 늦은 게임 응답은 버림("undefined" 없음)', async () => {
  const b = base(); const E = await boot(b);
  const g = E.calls[1];
  await E.click(E.tab('ai')); await E.settle(E.last(), 200, wlSel(b, 0));
  await E.settle(g, 200, gameSel(b, 0));
  assert.equal(E.txt('sel-name'), '이미지생성 · 7B'); assert.doesNotMatch(E.txt('sel-name'), /undefined/);
});

test('D2: 게임 지연 중 차단된 AI 탭으로 — 진행 중 요청 무효화', async () => {
  const b = base({ meta: { workload_map_rows: 0 } }); const E = await boot(b);
  const g = E.calls[1];
  await E.click(E.tab('ai'));
  assert.ok(E.vis('blocked'));
  await E.settle(g, 200, gameSel(b, 0));
  assert.equal(E.txt('sel-name'), '—'); assert.ok(!E.vis('cells-wrap'));
  assert.equal(E.tab('ai').getAttribute('aria-selected'), 'true');
  assert.equal(E.calls.length, 2, '차단 탭은 새 선택 GET 을 보내지 않음');
});

test('D2: 차단 탭 전환 뒤 늦은 실패도 버림', async () => {
  const b = base({ meta: { workload_map_rows: 0 } }); const E = await boot(b);
  const g = E.calls[1];
  await E.click(E.tab('ai')); await E.settle(g, 500, {});
  assert.ok(okErr(E)); assert.ok(E.vis('blocked'));
});

// ═════════════ 결함 ④: pending 중 이전 선택·근거 즉시 숨김 ═════════════
test('pending: 새 항목 선택 즉시 이전 칸·근거·이름을 숨김', async () => {
  const b = base(); const E = await boot(b, { firstSel: gameSel(b, 0) });
  await E.click(E.cellRow(101)); assert.ok(E.vis('ev-body'));
  await E.click(E.pick(2));
  assert.equal(E.pending().length, 1);
  assert.ok(!E.vis('ev-body'), '이전 근거 숨김'); assert.ok(E.vis('ev-empty'));
  assert.ok(!E.vis('cells-wrap'), '이전 성립 칸 숨김'); assert.ok(!E.vis('fail-card'));
  assert.equal(E.txt('sel-name'), '—'); assert.equal(E.current(), '2');
  await E.settle(E.last(), 200, gameSel(b, 1));
  assert.equal(E.txt('sel-name'), '게임둘'); assert.ok(E.vis('cells-wrap'));
});

test('pending: 탭 전환 즉시 이전 탭 선택·근거를 숨김', async () => {
  const b = base(); const E = await boot(b, { firstSel: gameSel(b, 0) });
  await E.click(E.cellRow(101));
  await E.click(E.tab('ai'));
  assert.ok(!E.vis('ev-body')); assert.ok(!E.vis('cells-wrap')); assert.equal(E.txt('sel-name'), '—');
});

// ═════════════ 결함 ③(D3): 선택 응답 대상·형식 가드 ═════════════
test('D3 축 배열: 선택 응답 usages 누락 → 반영 전 오류 패널, 다음 탭 클릭에서 미처리 예외 없음(root 재현)', async () => {
  const b = base(); const E = await boot(b);
  const d = gameSel(b, 0); delete d.usages;
  await E.settle(E.calls[1], 200, d);
  assert.ok(E.vis('load-error'), '반영 전에 오류 패널'); assert.equal(E.txt('err-title'), '매트릭스 조회 실패');
  assert.doesNotThrow(() => E.doc.dispatch('click', E.tab('ai')), '탭 클릭이 예외를 던지면 안 됨');
});

test('D3 축 배열 보존: 선택 응답의 정상 빈 배열 넷은 그대로 반영(필터 「전체」만, 탭 전환 정상)', async () => {
  const b = base(); const E = await boot(b);
  const empty = (x) => Object.assign(x, { usages: [], platforms: [], game_levels: [], workload_levels: [] });
  await E.settle(E.calls[1], 200, empty(gameSel(b, 0)));
  assert.ok(okErr(E)); assert.equal(E.txt('sel-name'), '게임하나');
  await E.click(E.tab('ai'));
  assert.ok(okErr(E), '빈 축 배열로 탭 전환해도 오류 아님');
  assert.equal(E.B('f-level').options.length, 1); assert.equal(E.B('f-usage').options.length, 1);
  assert.equal(E.last().url, '/api/admin/game-matrix?workload_id=11');
  await E.settle(E.last(), 200, empty(wlSel(b, 0)));
  assert.ok(okErr(E)); assert.equal(E.txt('sel-name'), '이미지생성 · 7B');
});

test('D3: 선택 응답 selection null·다른 kind·다른 항목·배열 아님은 오류 패널', async () => {
  const cases = {
    'selection null': (b) => b,
    'kind 불일치': (b) => withSel(b, 'workload', b.games[0], [cell(1, 1)]),
    '다른 항목': (b) => gameSel(b, 1),
    'cells 배열 아님': (b) => { const d = gameSel(b, 0); d.selection.cells = {}; return d; },
    'unmatched 누락': (b) => { const d = gameSel(b, 0); delete d.selection.unmatched; return d; },
    'games 배열 아님': (b) => { const d = gameSel(b, 0); d.games = null; return d; },
  };
  for (const k of ['usages', 'platforms', 'game_levels', 'workload_levels']) {
    cases[k + ' 누락'] = (b) => { const d = gameSel(b, 0); delete d[k]; return d; };
    cases[k + ' 배열 아님'] = (b) => { const d = gameSel(b, 0); d[k] = 'x'; return d; };
  }
  for (const [name, mk] of Object.entries(cases)) {
    const b = base(); const E = await boot(b);
    await E.settle(E.calls[1], 200, mk(base()));
    assert.ok(E.vis('load-error'), name + ' → 오류 패널이어야 함');
    assert.equal(E.txt('err-title'), '매트릭스 조회 실패', name);
  }
});
