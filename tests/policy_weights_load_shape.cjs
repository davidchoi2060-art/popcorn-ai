"use strict";
// ADMIN-NEXT-READ-AUDIT — 추천 기준 보기(policy_weights.html.j2)의 조회 load()를 «실제 페이지 스크립트» 통째로 실행한다.
// 가짜 DOM·가짜 fetch·가짜 자료만 쓴다(문구·숫자는 전부 테스트용 가짜 값). 실제 API·DB·LLM 없음.
// 결함(수정 전): HTTP 200인데 본문이 JSON이 아니거나 형이 다르면
//   ① null·false·0·HTML·빈 본문 → 「불러오는 중…」이 영원히 남는다
//   ② 문자열·배열·{}·필드 누락 → 없는 자료를 「0건은 오류가 아니라 정상 상태」로 그린다
//   ③ 정상 조회 뒤 재조회가 그런 응답이면 이전 표가 오류 없이 현재값처럼 남는다
// 기대: 형식 오류로 드러내고(조회 실패 + 다시 시도), 다시 시도하면 복구된다.
//       정상 응답(가중치 0행·풀 0 포함)은 기존대로 그린다. 401·500·네트워크 경로는 그대로.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

const tpl = fs.readFileSync(path.join(__dirname, '../templates/admin/policy_weights.html.j2'), 'utf8');
const m = tpl.match(/\{% block foot_extra %\}\s*\{% raw %\}\s*<script>([\s\S]*?)<\/script>/);
assert.ok(m, 'foot_extra <script> 블록을 찾지 못함');
const script = m[1];

// 실제 공용 errText(mockups/shared/ui-progress.js)를 함수 본문만 잘라 쓴다 — fetch 래핑 부분은 실행하지 않는다.
const up = fs.readFileSync(path.join(__dirname, '../mockups/shared/ui-progress.js'), 'utf8');
// 체크아웃 줄바꿈(CRLF/LF)과 무관하게 찾는다.
const em = up.match(/\r?\n( {2}function errText\(j, status, where\) \{[\s\S]*?\r?\n {2}\})\r?\n/);
assert.ok(em, 'ui-progress.js errText 를 찾지 못함');
const ERRTEXT = em[1];

// api/admin_engine_rules.py engine_rules() 반환 모양만 따른 가짜 자료.
function fakeRules(o) {
  o = Object.assign({ weights: 0, pool: 77 }, o || {});
  return {
    compat: { checks: [], slots: [], required: [], note: '가짜', required_note: '가짜' },
    tiers: {
      rules: [
        { tier: 'value', label: '가짜유형A', order: '가짜정렬A', cap: '가짜상한A', note: '가짜노트A', total_handling: '가짜총액A' },
        { tier: 'recommend', label: '가짜유형B', order: '가짜정렬B', cap: '가짜상한B', note: '가짜노트B', total_handling: '가짜총액B' },
        { tier: 'highend', label: '가짜유형C', order: '가짜정렬C', cap: '가짜상한C', note: '가짜노트C', total_handling: '가짜총액C' }],
      tie_break: '가짜동률', performance_proxy: '가짜대리', pool_size: o.pool, highend_cap_x: 9.9,
    },
    budget: {
      alloc: [{ part_type: 'GPU', pct: 40 }, { part_type: 'CPU', pct: 25 }], note: '가짜배분노트',
      tag_scope: [{ tag: '가짜태그', field: 'tag_silent', scope: ['CASE'] }], tag_note: '가짜태그노트',
    },
    pricing: { card_fee_pct: 0 },
    weights: { rows: Array.from({ length: o.weights }, (_, i) => ({ key: '가짜키' + i, weight: 1 })), note: '가짜' },
  };
}

// 실제 DOM처럼 textContent 대입이 innerHTML을 대체한다(이스케이프 포함).
function El(id) {
  let h = '';
  return {
    id, disabled: false,
    get innerHTML() { return h; }, set innerHTML(v) { h = String(v); },
    get textContent() { return h.replace(/<[^>]+>/g, ''); },
    set textContent(v) { h = String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
  };
}
function res(status, bodyText) {
  const r = { ok: status >= 200 && status < 300, status, json: async () => JSON.parse(bodyText), clone: () => r };
  return r;
}
const okJson = (obj) => res(200, JSON.stringify(obj));
const netErr = () => () => Promise.reject(new TypeError('Failed to fetch'));

function boot(responses) {
  const els = { pwScroll: El('pwScroll'), refreshBtn: El('refreshBtn'), poolInfo: El('poolInfo') };
  els.pwScroll.innerHTML = '<div class="loading" id="loading">불러오는 중…</div>';
  els.poolInfo.textContent = '추천 후보 풀 조회 중…';
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
    PW_PART_LABELS: { GPU: '가짜부품G', CPU: '가짜부품C', CASE: '가짜부품K' },
    console, Promise, Number, String, Date, JSON, Object, Array, Math, Error, TypeError,
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(ERRTEXT + '\nwindow.popcornProgress = { errText: errText };', ctx);
  const onUnh = (e) => unhandled.push(e && e.message ? e.message : String(e));
  process.on('unhandledRejection', onUnh);
  vm.runInContext(script, ctx, { filename: 'policy_weights.html.j2#script' });
  const click = (action) => onClick({ target: { closest: (sel) => (sel === '[data-action="' + action + '"]' ? {} : null) } });
  return {
    els, calls, unhandled, click,
    settle: async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setImmediate(r)); },
    done: () => process.off('unhandledRejection', onUnh),
  };
}

const body = (p) => p.els.pwScroll.innerHTML;
const header = (p) => p.els.poolInfo.textContent;
function assertRendered(p, pool) {
  const h = body(p);
  assert.ok(h.includes('가짜정렬A') && h.includes('가짜총액C'), '티어 표가 그려지지 않음: ' + h.slice(0, 120));
  assert.ok(!h.includes('class="errbox"'), '정상 응답인데 오류 상자가 뜸');
  assert.ok(header(p).includes('추천 후보 풀 ' + pool + '개'), '헤더 풀 수 불일치: ' + header(p));
  assert.equal(p.els.refreshBtn.disabled, false, '다시 조회 버튼이 비활성으로 남음');
}
function assertFormatError(p, status) {
  const h = body(p);
  assert.ok(!h.includes('불러오는 중'), '로딩 문구가 남음: ' + h.slice(0, 120));
  assert.ok(h.includes('class="errbox"') && h.includes('조회 실패'), '조회 실패 표시 없음: ' + h.slice(0, 160));
  assert.ok(h.includes('응답 형식이 올바르지 않습니다 (HTTP ' + status + ')'), '형식 오류 문구 없음: ' + h.slice(0, 200));
  assert.ok(h.includes('data-action="retry"'), '다시 시도 버튼 없음');
  assert.ok(!h.includes('정상 상태'), '형식 오류인데 「정상 상태」를 단정함');
  assert.ok(!h.includes('가짜정렬A'), '이전 티어 표가 오류와 함께 남음');
  assert.equal(header(p), '추천 후보 풀 조회 실패', '헤더가 실패로 바뀌지 않음: ' + header(p));
  assert.equal(p.els.refreshBtn.disabled, false, '다시 조회 버튼이 비활성으로 남음');
}

const BAD_TOP = [
  ['HTML 본문', '<!doctype html><html><body>x</body></html>'], ['빈 본문', ''], ['null', 'null'],
  ['false', 'false'], ['0', '0'], ['빈 문자열', '""'], ['문자열', '"abc"'], ['배열', '[]'], ['빈 객체', '{}'],
];
for (const [name, text] of BAD_TOP) {
  test('HTTP 200 ' + name + ' → 형식 오류 + 다시 시도', async () => {
    const p = boot([res(200, text)]);
    try { await p.settle(); assertFormatError(p, 200); assert.deepEqual(p.unhandled, []); } finally { p.done(); }
  });
}

// 필수 형(tiers·budget·weights 객체, tiers.rules·budget.alloc·budget.tag_scope·weights.rows 배열) 누락·잘못된 형
const BAD_SHAPE = [
  ['tiers 누락', (d) => { delete d.tiers; }], ['tiers 배열', (d) => { d.tiers = []; }], ['tiers 문자열', (d) => { d.tiers = 'x'; }],
  ['budget 누락', (d) => { delete d.budget; }], ['budget 배열', (d) => { d.budget = []; }], ['budget null', (d) => { d.budget = null; }],
  ['weights 누락', (d) => { delete d.weights; }], ['weights null', (d) => { d.weights = null; }], ['weights 배열', (d) => { d.weights = []; }],
  ['tiers.rules 누락', (d) => { delete d.tiers.rules; }], ['tiers.rules 객체', (d) => { d.tiers.rules = {}; }],
  ['budget.alloc 누락', (d) => { delete d.budget.alloc; }], ['budget.alloc 문자열', (d) => { d.budget.alloc = 'x'; }],
  ['budget.tag_scope 누락', (d) => { delete d.budget.tag_scope; }], ['budget.tag_scope 객체', (d) => { d.budget.tag_scope = {}; }],
  ['weights.rows 누락', (d) => { delete d.weights.rows; }], ['weights.rows null', (d) => { d.weights.rows = null; }],
  ['weights.rows 객체', (d) => { d.weights.rows = {}; }],
];
for (const [name, mut] of BAD_SHAPE) {
  test('HTTP 200 ' + name + ' → 형식 오류(없는 자료를 0건 정상으로 그리지 않음)', async () => {
    const d = fakeRules(); mut(d);
    const p = boot([okJson(d)]);
    try { await p.settle(); assertFormatError(p, 200); assert.deepEqual(p.unhandled, []); } finally { p.done(); }
  });
}

test('정상 양수(가중치 2행·풀 77) → 티어 표·배분율·헤더 77·배너 2건', async () => {
  const p = boot([okJson(fakeRules({ weights: 2, pool: 77 }))]);
  try {
    await p.settle();
    assertRendered(p, 77);
    assert.ok(body(p).includes('<b>2건</b>'), '가중치 행 수가 배너에 반영되지 않음');
    assert.ok(body(p).includes('가짜부품G'), '배분율 부품 라벨 미표시');
    assert.equal(p.calls[0], '/api/admin/engine-rules');
  } finally { p.done(); }
});

test('정상 빈 상태(가중치 0행·풀 0) → 「0건 정상 상태」 설명 배너, 오류 아님', async () => {
  const p = boot([okJson(fakeRules({ weights: 0, pool: 0 }))]);
  try {
    await p.settle();
    assertRendered(p, 0);
    assert.ok(body(p).includes('0건은 오류가 아니라 지금의 정상 상태입니다'));
  } finally { p.done(); }
});

test('정상 빈 배열(배분율·태그·티어 0개) → 오류 아님', async () => {
  const d = fakeRules(); d.tiers.rules = []; d.budget.alloc = []; d.budget.tag_scope = [];
  const p = boot([okJson(d)]);
  try {
    await p.settle();
    assert.ok(!body(p).includes('class="errbox"'), '빈 배열 정상 응답을 오류로 처리함');
    assert.ok(body(p).includes('pw-tiertable'));
    assert.ok(header(p).includes('추천 후보 풀 77개'));
  } finally { p.done(); }
});

test('401 → 세션 만료 + 로그인 링크(기존 경로)', async () => {
  const p = boot([res(401, JSON.stringify({ detail: '가짜' }))]);
  try {
    await p.settle();
    assert.ok(body(p).includes('세션 만료') && body(p).includes('href="/admin2/login"'));
    assert.ok(!body(p).includes('응답 형식'));
    assert.equal(p.els.refreshBtn.disabled, false);
  } finally { p.done(); }
});

test('500 + detail → 서버 문장 그대로 + 다시 시도(기존 경로)', async () => {
  const p = boot([res(500, JSON.stringify({ detail: '가짜서버오류문장' }))]);
  try {
    await p.settle();
    assert.ok(body(p).includes('추천 기준을 받지 못했습니다 — 가짜서버오류문장'));
    assert.ok(body(p).includes('data-action="retry"'));
    assert.ok(!body(p).includes('응답 형식'));
  } finally { p.done(); }
});

test('502 HTML 본문 → 「오류 502」(기존 경로)', async () => {
  const p = boot([res(502, '<html>bad gateway</html>')]);
  try { await p.settle(); assert.ok(body(p).includes('오류 502')); assert.ok(!body(p).includes('응답 형식')); } finally { p.done(); }
});

test('네트워크 오류 → 사유 표시 + 버튼 재활성(기존 경로)', async () => {
  const p = boot([netErr()]);
  try {
    await p.settle();
    assert.ok(body(p).includes('Failed to fetch') && body(p).includes('data-action="retry"'));
    assert.equal(p.els.refreshBtn.disabled, false);
    assert.deepEqual(p.unhandled, []);
  } finally { p.done(); }
});

for (const [name, mk] of [['HTML', () => res(200, '<html>x</html>')], ['null', () => res(200, 'null')],
  ['문자열', () => res(200, '"abc"')], ['빈 객체', () => res(200, '{}')],
  ['weights 누락', () => { const d = fakeRules(); delete d.weights; return okJson(d); }]]) {
  test('정상 → 다시 조회 ' + name + ' 200 → 이전 표를 남기지 않고 형식 오류 → 다시 시도로 복구', async () => {
    const p = boot([okJson(fakeRules({ pool: 77 })), mk(), okJson(fakeRules({ pool: 5 }))]);
    try {
      await p.settle();
      assertRendered(p, 77);
      p.click('refresh');
      await p.settle();
      assertFormatError(p, 200);
      p.click('retry');
      await p.settle();
      assertRendered(p, 5);
      assert.equal(p.calls.length, 3);
      assert.deepEqual(p.unhandled, []);
    } finally { p.done(); }
  });
}

test('정상 → 다시 조회 500 → 오류로 바뀜 → 다시 조회로 복구', async () => {
  const p = boot([okJson(fakeRules({ pool: 77 })), res(500, '{}'), okJson(fakeRules({ pool: 3 }))]);
  try {
    await p.settle();
    p.click('refresh');
    await p.settle();
    assert.ok(body(p).includes('class="errbox"') && !body(p).includes('가짜정렬A'));
    assert.equal(header(p), '추천 후보 풀 조회 실패');
    p.click('refresh');
    await p.settle();
    assertRendered(p, 3);
  } finally { p.done(); }
});

test('네트워크 오류 → 다시 시도 → 정상 복구', async () => {
  const p = boot([netErr(), okJson(fakeRules({ pool: 9 }))]);
  try { await p.settle(); p.click('retry'); await p.settle(); assertRendered(p, 9); assert.equal(p.calls.length, 2); } finally { p.done(); }
});

test('조회 중에는 다시 조회 버튼이 비활성', async () => {
  const p = boot([]);  // 응답이 오지 않는 조회
  try { await p.settle(); assert.equal(p.els.refreshBtn.disabled, true); } finally { p.done(); }
});
