"use strict";
// ADMIN-NEXT-READ-AUDIT — 추천 가능 재고 현황(candidate_pool.html.j2)의 조회를 «실제 페이지 스크립트» 통째로 실행한다.
// 가짜 DOM·가짜 fetch·가짜 자료만 쓴다(문구·숫자는 전부 테스트용 가짜 값). 실제 API·DB·LLM 없음.
// 결함(수정 전): HTTP 200인데 본문이 false·0·문자열·배열·{} 이거나 categories·reasons·thin 형이 다르면
//   오류 카드 없이 「판정 대상이 없습니다」「지금 위험 카테고리 없음」과 조회 시각을 정상처럼 그린다.
//   HTML·빈 본문·null 은 실패 카드가 뜨지만 JS 내부 메시지(Unexpected token… / Cannot read…)가 그대로 나왔다.
// 기대: 형식 오류로 드러내고(데이터 조회 실패 + 다시 시도 = 새로고침), 정상 응답(빈 카탈로그 포함)은 기존대로 그린다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

const tpl = fs.readFileSync(path.join(__dirname, '../templates/admin/candidate_pool.html.j2'), 'utf8');
const m = tpl.match(/\{% raw %\}\s*<script>([\s\S]*?)<\/script>\s*\{% endraw %\}/);
assert.ok(m, '{% raw %} <script> 블록을 찾지 못함');
const script = m[1];

// api/admin_pool.py candidate_pool() 반환 모양만 따른 가짜 자료.
const KEYS = ['no_specs', 'need_review', 'not_candidate', 'no_price', 'oos'];
function fakePool(o) {
  o = Object.assign({ empty: false }, o || {});
  const cats = o.empty ? [] : [
    { name: '가짜부품A', total: 10, ok: 7, no_specs: 1, need_review: 1, not_candidate: 0, no_price: 1, oos: 0 },
    { name: '가짜부품B', total: 4, ok: 1, no_specs: 3, need_review: 0, not_candidate: 0, no_price: 0, oos: 0 }];
  const reasons = KEYS.map((k) => ({ key: k, label: '가짜사유' + k, link: 'x', count: cats.reduce((s, c) => s + c[k], 0) }));
  const ok = cats.reduce((s, c) => s + c.ok, 0);
  const thin = cats.filter((c) => c.ok <= 2).map((c) => ({ name: c.name, count: c.ok, why: '가짜얇음', link: 'x' }))
    .concat([{ name: '케이스(화이트 태그)', count: 0, why: '가짜결합1', link: 'x' },
             { name: '750W 이상 파워', count: 0, why: '가짜결합2', link: 'x' }]);
  return { pool_total: ok, core_total: cats.reduce((s, c) => s + c.total, 0), ok_total: ok, rate: 0,
    categories: cats, reasons, reason_total: 0, thin, thin_threshold: 2, note: '가짜서버메모' };
}

function res(status, bodyText) {
  return { ok: status >= 200 && status < 300, status, json: async () => JSON.parse(bodyText) };
}
const okJson = (obj) => res(200, JSON.stringify(obj));

const NAMES = ['asof', 'content-area', 'pass-card', 'pass-v', 'reason-cards', 'band-right', 'grid-body', 'grid-total',
  'thin-threshold', 'thin-body', 'combined-body', 'go-list', 'note-line', 'load-error', 'err-title', 'err-msg', 'err-actions'];

function boot(response) {
  const els = {};
  let retry = null;
  NAMES.forEach((k) => {
    els[k] = {
      innerHTML: '불러오는 중…', textContent: '', title: '', hidden: false, style: { display: '' },
      // err-actions 안의 다시 시도 버튼 — 실제 DOM처럼 마크업에 그 버튼이 있을 때만 찾힌다.
      querySelector: (sel) => (k === 'err-actions' && sel === '[data-action="retry"]' && /data-action="retry"/.test(els[k].innerHTML)
        ? { addEventListener: (t, fn) => { if (t === 'click') retry = fn; } } : null),
    };
  });
  els['load-error'].hidden = true;
  els.asof.style.display = 'none';
  const calls = [], unhandled = [];
  let reloads = 0;
  const ctx = {
    document: { querySelector: (sel) => { const mm = sel.match(/data-bind="([^"]+)"/); return mm ? els[mm[1]] || null : null; } },
    fetch: (url) => { calls.push(url); return typeof response === 'function' ? response() : Promise.resolve(response); },
    REASON_TARGETS: { no_specs: { label: '가짜화면', href: '/admin2/fake' } },
    location: { reload: () => { reloads++; } },
    console, Promise, Number, String, Date, JSON, Object, Array, Math, Error, TypeError,
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  const onUnh = (e) => unhandled.push(e && e.message ? e.message : String(e));
  process.on('unhandledRejection', onUnh);
  vm.runInContext(script, ctx, { filename: 'candidate_pool.html.j2#script' });
  return {
    els, calls, unhandled, reloads: () => reloads, clickRetry: () => retry && retry(),
    settle: async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setImmediate(r)); },
    done: () => process.off('unhandledRejection', onUnh),
  };
}

function assertFormatError(p, status) {
  assert.equal(p.els['load-error'].hidden, false, '오류 카드가 뜨지 않음');
  assert.equal(p.els['content-area'].hidden, true, '집계 영역이 오류와 함께 보임');
  assert.equal(p.els['err-title'].innerHTML, '데이터 조회 실패');
  assert.equal(p.els['err-msg'].innerHTML, '집계를 받지 못했습니다 — 응답 형식이 올바르지 않습니다 (HTTP ' + status + ')');
  assert.ok(/data-action="retry"/.test(p.els['err-actions'].innerHTML), '다시 시도 버튼 없음');
  assert.ok(!p.els['thin-body'].innerHTML.includes('위험 카테고리 없음'), '형식 오류인데 「위험 카테고리 없음」을 단정함');
  assert.ok(!p.els['grid-body'].innerHTML.includes('판정 대상이 없습니다'), '형식 오류인데 「판정 대상 없음」을 그림');
  assert.equal(p.els.asof.style.display, 'none', '형식 오류인데 조회 시각을 표시함');
}

const BAD_TOP = [
  ['HTML 본문', '<!doctype html><html><body>x</body></html>'], ['빈 본문', ''], ['null', 'null'],
  ['false', 'false'], ['0', '0'], ['빈 문자열', '""'], ['문자열', '"abc"'], ['배열', '[]'], ['빈 객체', '{}'],
];
for (const [name, text] of BAD_TOP) {
  test('HTTP 200 ' + name + ' → 형식 오류 + 다시 시도', async () => {
    const p = boot(res(200, text));
    try { await p.settle(); assertFormatError(p, 200); assert.deepEqual(p.unhandled, []); } finally { p.done(); }
  });
}

const BAD_SHAPE = [
  ['categories 누락', (d) => { delete d.categories; }], ['categories 객체', (d) => { d.categories = { a: 1 }; }],
  ['categories null', (d) => { d.categories = null; }],
  ['reasons 누락', (d) => { delete d.reasons; }], ['reasons 객체', (d) => { d.reasons = {}; }],
  ['thin 누락', (d) => { delete d.thin; }], ['thin 문자열', (d) => { d.thin = 'x'; }],
];
for (const [name, mut] of BAD_SHAPE) {
  test('HTTP 200 ' + name + ' → 형식 오류(빈 값을 정상 집계로 그리지 않음)', async () => {
    const d = fakePool(); mut(d);
    const p = boot(okJson(d));
    try { await p.settle(); assertFormatError(p, 200); assert.deepEqual(p.unhandled, []); } finally { p.done(); }
  });
}

test('정상 양수 → 통과 수·본표·얇은 카테고리·결합 조건 분리·조회 시각', async () => {
  const p = boot(okJson(fakePool()));
  try {
    await p.settle();
    assert.equal(p.els['load-error'].hidden, true);
    assert.equal(p.els['pass-v'].innerHTML, '8');
    assert.ok(p.els['grid-body'].innerHTML.includes('가짜부품A') && p.els['grid-body'].innerHTML.includes('70.0%'));
    assert.ok(p.els['thin-body'].innerHTML.includes('가짜부품B'), '얇은 카테고리 미표시');
    assert.ok(!p.els['thin-body'].innerHTML.includes('750W'), '결합 조건이 얇은 카테고리에 섞임');
    assert.ok(p.els['combined-body'].innerHTML.includes('750W 이상 파워'), '결합 조건 미표시');
    assert.ok(p.els['grid-body'].innerHTML.includes('href="/admin2/fake"'), '사유 칸 이동 링크 미표시');
    assert.equal(p.els['note-line'].innerHTML, '가짜서버메모');
    assert.notEqual(p.els.asof.style.display, 'none');
    assert.equal(p.calls[0], '/api/admin/candidate-pool');
  } finally { p.done(); }
});

test('정상 빈 상태(판정 대상 0) → 「판정 대상이 없습니다」, 오류 아님', async () => {
  const p = boot(okJson(fakePool({ empty: true })));
  try {
    await p.settle();
    assert.equal(p.els['load-error'].hidden, true);
    assert.equal(p.els['content-area'].hidden, false);
    assert.equal(p.els['pass-v'].innerHTML, '0');
    assert.ok(p.els['grid-body'].innerHTML.includes('판정 대상이 없습니다'));
  } finally { p.done(); }
});

test('401 → 세션 만료 + 로그인 링크(기존 경로)', async () => {
  const p = boot(res(401, '{}'));
  try {
    await p.settle();
    assert.equal(p.els['err-title'].innerHTML, '세션 만료');
    assert.ok(p.els['err-actions'].innerHTML.includes('/admin2/login'));
  } finally { p.done(); }
});

test('500 → 「HTTP 500」 + 다시 시도(기존 경로)', async () => {
  const p = boot(res(500, JSON.stringify({ detail: '가짜' })));
  try {
    await p.settle();
    assert.equal(p.els['err-msg'].innerHTML, '집계를 받지 못했습니다 — HTTP 500');
    assert.ok(/data-action="retry"/.test(p.els['err-actions'].innerHTML));
  } finally { p.done(); }
});

test('네트워크 오류 → 사유 표시(기존 경로)', async () => {
  const p = boot(() => Promise.reject(new TypeError('Failed to fetch')));
  try {
    await p.settle();
    assert.equal(p.els['err-msg'].innerHTML, '집계를 받지 못했습니다 — Failed to fetch');
    assert.deepEqual(p.unhandled, []);
  } finally { p.done(); }
});

test('형식 오류 → 다시 시도 = 페이지 새로고침(기존 방식 유지)', async () => {
  const p = boot(res(200, '{}'));
  try {
    await p.settle();
    p.clickRetry();
    assert.equal(p.reloads(), 1);
    assert.equal(p.calls.length, 1, '같은 페이지에서 재조회하지 않음(새로고침이 다시 부른다)');
  } finally { p.done(); }
});
