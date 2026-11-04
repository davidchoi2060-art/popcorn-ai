"use strict";
// ADMIN-ROW19 — AI 사용량·비용 화면(ai_usage_cost.html.j2)의 조회 load()를 «실제 페이지 스크립트» 통째로 실행한다.
// 가짜 DOM·가짜 fetch·가짜 집계만 쓴다(숫자는 전부 테스트용 가짜 자료). 실제 API·DB·LLM 없음.
// 결함: HTTP 200인데 본문이 JSON이 아니거나(HTML·빈 본문) null·false·0 이면
//   handle()이 그대로 넘기고 render()가 !S.data 로 조용히 끝나서
//   ① 첫 조회면 「불러오는 중…」이 영원히 남고 ② 재조회면 이전 집계가 오류 표시 없이 그대로 남는다.
// 기대: 최상위가 객체가 아닌 응답은 형식 오류로 드러내고(조회 실패 + 다시 시도), 다시 시도하면 복구된다.
//       정상 객체(원천 없음·진짜 0·스키마 없음)는 기존대로 그린다. 401·500·네트워크 오류 문구는 그대로.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

const tpl = fs.readFileSync(path.join(__dirname, '../templates/admin/ai_usage_cost.html.j2'), 'utf8');
const m = tpl.match(/\{% block foot_extra %\}\s*\{% raw %\}\s*<script>([\s\S]*?)<\/script>/);
assert.ok(m, 'foot_extra <script> 블록을 찾지 못함');
const script = m[1];

// api/admin_ai_usage.py summary() 반환 객체의 모양만 따른 가짜 자료. 금액·토큰·건수는 지어낸 테스트 값이다.
// 키(기간 today/d7/d30/month · 업체 codex/claude/gemini · 모델명)는 정본 API 계약(PERIODS · PROVIDERS)과 같게 둔다.
// 원천 있음(available)이면 양수 가짜 값 12.34, zero:true면 진짜 0, 원천 없음이면 API처럼 kind 'nosource' + '정보 없음'.
const FAKE_COST = 12.34, FAKE_TOKENS = 1234;
function fakeSummary(opts) {
  const o = Object.assign({ rows: 0, available: false, schemaMissing: false, zero: false }, opts);
  const val = o.available ? (o.zero ? 0 : FAKE_COST) : null;
  const tok = o.available ? (o.zero ? 0 : FAKE_TOKENS) : null;
  return {
    generated_at: '2026-01-01T00:00:00+09:00', period: 'today', period_label: '가짜기간',
    provider: null, model: null,
    periods: [{ key: 'today', label: '오늘' }, { key: 'd7', label: '7일' }, { key: 'd30', label: '30일' }, { key: 'month', label: '이번 달' }],
    filters: {
      providers: [{ key: 'codex', label: 'Codex' }, { key: 'claude', label: 'Claude' }, { key: 'gemini', label: 'Gemini' }],
      models: [{ key: 'gpt-5.6-sol', label: 'Codex · gpt-5.6-sol' }, { key: 'claude-opus-5', label: 'Claude · claude-opus-5' },
               { key: 'gemini-3.7-flash', label: 'Gemini · gemini-3.7-flash' }],
    },
    scope_note: '가짜범위설명',
    source: { api_cost_logs_rows: o.rows, cost_thresholds_rows: 0, built_at: '2026-01-01', decision_at: null,
              weeks_since_build: 1, reason: '가짜원천없음사유' },
    kpis: [o.available
      ? { key: 'today', label: '가짜KPI', kind: 'value', value: val, unit: null, note: '가짜' }
      : { key: 'today', label: '가짜KPI', kind: 'nosource', value: '정보 없음', unit: null, note: '가짜' }],
    gauge: { available: false, pct: null, used_usd: o.available ? val : null, limit_usd: null, note: '가짜게이지' },
    trend: { available: o.available, days: 1, period_label: '가짜기간',
             points: [{ date: '2026-01-01', cost: o.available ? val : null }], note: o.available ? null : '가짜추이없음' },
    breakdowns: {
      provider: { available: o.available, source: '가짜', reason: null,
                  rows: [{ key: 'codex', name: '가짜업체', sub: null, tokens: tok, cost: val }] },
      task: { available: !o.schemaMissing && o.available, schema_missing: o.schemaMissing, source: '가짜',
              reason: o.schemaMissing ? '가짜스키마없음사유' : null, rows: [] },
    },
    claude_code_session: { rows: [], note: '가짜', note2: '가짜' },
    legend: [{ chip: '0', desc: '가짜' }, { chip: '정보 없음', desc: '가짜' }],
  };
}

class El { constructor(id) { this.id = id; this.innerHTML = ''; this.textContent = ''; this.disabled = false; } }
// 실제 Response처럼 clone()·json()을 가진 가짜 응답. 본문은 문자열 그대로 파싱한다.
function res(status, bodyText) {
  const r = { ok: status >= 200 && status < 300, status, json: async () => JSON.parse(bodyText), clone: () => r };
  return r;
}
const okJson = (obj) => res(200, JSON.stringify(obj));

function boot(responses) {
  const els = { auScroll: new El('auScroll'), refreshBtn: new El('refreshBtn'), lastAt: new El('lastAt') };
  els.auScroll.innerHTML = '<div class="loading" id="loading">불러오는 중…</div>';
  const calls = [], unhandled = [], queue = responses.slice();
  let onClick = null;
  const ctx = {
    document: { getElementById: (id) => els[id] || null, addEventListener: (t, fn) => { if (t === 'click') onClick = fn; } },
    fetch: (url) => {
      calls.push(url);
      const next = queue.shift();
      if (!next) return new Promise(() => {});
      return typeof next === 'function' ? next() : Promise.resolve(next);
    },
    console, Promise, Number, String, Date, JSON, Object, Array, Math, Error, TypeError, encodeURIComponent,
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  const onUnh = (e) => unhandled.push(e && e.message ? e.message : String(e));
  process.on('unhandledRejection', onUnh);
  vm.runInContext(script, ctx, { filename: 'ai_usage_cost.html.j2#script' });
  // 위임 클릭: target.closest(sel)이 sel에 맞는 가짜 요소를 돌려준다.
  const click = (action, attrs) => onClick({ target: { closest: (sel) => sel === '[data-action="' + action + '"]'
    ? { getAttribute: (k) => (attrs || {})[k] } : null } });
  return {
    els, calls, unhandled, click,
    settle: async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setImmediate(r)); },
    done: () => process.off('unhandledRejection', onUnh),
  };
}

const html = (p) => p.els.auScroll.innerHTML;
function assertFormatError(p, status) {
  const h = html(p);
  assert.ok(!h.includes('불러오는 중'), '로딩 문구가 남음: ' + h.slice(0, 120));
  assert.ok(h.includes('조회 실패'), '조회 실패 표시 없음: ' + h.slice(0, 120));
  assert.ok(h.includes('응답 형식이 올바르지 않습니다 (HTTP ' + status + ')'), '형식 오류 문구 없음: ' + h.slice(0, 200));
  assert.ok(h.includes('data-action="retry"'), '다시 시도 버튼 없음');
  assert.ok(!h.includes('class="kpis"'), '집계 DOM이 오류와 함께 남음');
  assert.equal(p.els.refreshBtn.disabled, false, '다시 조회 버튼이 비활성으로 남음');
}

const BAD = [
  ['HTML 본문', '<html><body>x</body></html>'],
  ['빈 본문', ''],
  ['null', 'null'],
  ['false', 'false'],
  ['0', '0'],
  ['빈 문자열', '""'],
  ['문자열', '"abc"'],
  ['배열', '[]'],
];

for (const [name, body] of BAD) {
  test('HTTP 200 ' + name + ' → 형식 오류 + 다시 시도(로딩 영구 잔류 없음)', async () => {
    const p = boot([res(200, body)]);
    try {
      await p.settle();
      assertFormatError(p, 200);
      assert.deepEqual(p.unhandled, []);
    } finally { p.done(); }
  });
}

test('정상 집계 → 형식 오류 재조회: 이전 집계를 오류 없이 남기지 않음 → 다시 시도로 복구', async () => {
  const p = boot([okJson(fakeSummary({ rows: 3, available: true })), res(200, 'null'), okJson(fakeSummary({ rows: 3, available: true }))]);
  try {
    await p.settle();
    assert.ok(html(p).includes('class="kpis"'), '첫 정상 집계가 그려지지 않음');
    p.click('refresh');
    await p.settle();
    assertFormatError(p, 200);
    p.click('retry');
    await p.settle();
    assert.ok(html(p).includes('class="kpis"'), '다시 시도 후 복구되지 않음');
    assert.ok(!html(p).includes('조회 실패'));
    assert.equal(p.calls.length, 3);
    assert.equal(p.els.refreshBtn.disabled, false);
  } finally { p.done(); }
});

test('정상 양수 집계(가짜 12.34) → KPI·업체별 금액·토큰 표시, 배너·정보 없음·오류 없음', async () => {
  const p = boot([okJson(fakeSummary({ rows: 3, available: true }))]);
  try {
    await p.settle();
    const h = html(p);
    const kpi = h.slice(h.indexOf('class="kpis"'), h.indexOf('class="gaugebox"'));
    assert.ok(kpi.includes('class="val real">$12.34<'), 'KPI 양수 금액이 실제 값으로 보이지 않음: ' + kpi.slice(0, 300));
    assert.ok(!kpi.includes('정보 없음'), '원천 있는 KPI에 정보 없음이 뜸');
    const brk = h.slice(h.indexOf('class="breakdowns"'), h.indexOf('class="trendbox"'));
    assert.ok(brk.includes('<span class="tok real">1,234</span>'), '업체별 토큰 미표시');
    assert.ok(brk.includes('<span class="cost real">$12.34</span>'), '업체별 금액 미표시');
    assert.ok(h.includes('tbar real'), '추이 막대 미표시');
    assert.ok(!h.includes('srcband'));
    assert.ok(!h.includes('조회 실패'));
    assert.equal(p.els.refreshBtn.disabled, false);
  } finally { p.done(); }
});

test('정상 원천 없음(rows 0) → 기록 없음 배너·정보 없음, 오류 아님', async () => {
  const p = boot([okJson(fakeSummary({ rows: 0, available: false }))]);
  try {
    await p.settle();
    const h = html(p);
    assert.ok(h.includes('srcband'), '원천 없음 배너 없음');
    assert.ok(h.includes('정보 없음'));
    assert.ok(!h.includes('조회 실패'));
    assert.ok(p.els.lastAt.textContent.startsWith('마지막 조회 '));
    assert.equal(p.els.refreshBtn.disabled, false);
  } finally { p.done(); }
});

test('정상 진짜 0(원천 있음) → $0.00 표시, 배너·오류 없음', async () => {
  const p = boot([okJson(fakeSummary({ rows: 5, available: true, zero: true }))]);
  try {
    await p.settle();
    const h = html(p);
    assert.ok(h.includes('class="val real">$0.00<'), '진짜 0이 KPI $0.00 실제 값으로 보이지 않음');
    assert.ok(!h.includes('$12.34'));
    assert.ok(!h.includes('srcband'));
    assert.ok(!h.includes('조회 실패'));
  } finally { p.done(); }
});

test('정상 스키마 없음 → noschema 표시, 오류 아님', async () => {
  const p = boot([okJson(fakeSummary({ rows: 5, available: true, schemaMissing: true }))]);
  try {
    await p.settle();
    const h = html(p);
    assert.ok(h.includes('noschema'));
    assert.ok(h.includes('가짜스키마없음사유'));
    assert.ok(!h.includes('조회 실패'));
  } finally { p.done(); }
});

// 요청 URL을 경로 + 디코딩된 쿼리로 나눈다(인코딩 결과를 문자열로 베끼지 않고 의미로 대조).
function parseCall(u) {
  const url = new URL(u, 'http://fake.invalid');
  return { path: url.pathname, q: Object.fromEntries(url.searchParams) };
}

test('필터 선택 → 쿼리에 period(d7)·provider·model 반영, 전체로 되돌리면 빠짐', async () => {
  const ok = () => okJson(fakeSummary({ rows: 1, available: true }));
  const p = boot([ok(), ok(), ok(), ok(), ok()]);
  try {
    await p.settle();
    let c = parseCall(p.calls[0]);
    assert.equal(c.path, '/api/admin/ai-usage-cost/summary');
    assert.deepEqual(c.q, { period: 'today' });
    p.click('set-period', { 'data-v': 'd7' });
    await p.settle();
    assert.deepEqual(parseCall(p.calls[1]).q, { period: 'd7' });
    p.click('set-prov', { 'data-v': 'gemini' });
    await p.settle();
    assert.deepEqual(parseCall(p.calls[2]).q, { period: 'd7', provider: 'gemini' });
    p.click('set-model', { 'data-v': 'gemini-3.7-flash' });
    await p.settle();
    assert.deepEqual(parseCall(p.calls[3]).q, { period: 'd7', provider: 'gemini', model: 'gemini-3.7-flash' });
    p.click('set-prov', { 'data-v': '' });
    await p.settle();
    assert.deepEqual(parseCall(p.calls[4]).q, { period: 'd7', model: 'gemini-3.7-flash' });
    assert.ok(html(p).includes('class="kpis"'));
  } finally { p.done(); }
});

test('401 → 세션 만료·로그인 링크(형식 오류로 바꾸지 않음)', async () => {
  const p = boot([res(401, '{"detail":"가짜"}')]);
  try {
    await p.settle();
    const h = html(p);
    assert.ok(h.includes('세션 만료'));
    assert.ok(h.includes('/admin2/login'));
    assert.ok(!h.includes('응답 형식이'));
    assert.equal(p.els.refreshBtn.disabled, false);
  } finally { p.done(); }
});

test('500(본문 JSON 아님 포함) → 기존 HTTP 오류 문구, 형식 오류 문구 아님', async () => {
  for (const body of ['{"detail":"가짜"}', '<html>500</html>', 'null']) {
    const p = boot([res(500, body)]);
    try {
      await p.settle();
      const h = html(p);
      assert.ok(h.includes('조회 실패'));
      assert.ok(h.includes('오류 500'), '기존 HTTP 오류 문구가 아님: ' + h.slice(0, 200));
      assert.ok(!h.includes('응답 형식이'));
      assert.ok(h.includes('data-action="retry"'));
      assert.equal(p.els.refreshBtn.disabled, false);
    } finally { p.done(); }
  }
});

test('네트워크 오류 → 기존 문구 + 다시 시도, 이후 정상 복구', async () => {
  const p = boot([() => Promise.reject(new TypeError('Failed to fetch')), okJson(fakeSummary({ rows: 0 }))]);
  try {
    await p.settle();
    assert.ok(html(p).includes('Failed to fetch'));
    assert.equal(p.els.refreshBtn.disabled, false);
    p.click('retry');
    await p.settle();
    assert.ok(html(p).includes('srcband'));
    assert.ok(!html(p).includes('조회 실패'));
  } finally { p.done(); }
});
