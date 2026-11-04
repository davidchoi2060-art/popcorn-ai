"use strict";
// ADMIN-ROW17 — 회원 목록 페이지 보정(members.js loadList)을 «실제 스크립트»로 실행한다.
// 가짜 DOM·가짜 fetch·가짜 주소만 쓴다. 실제 회원·DB·네트워크 없음.
// 결함: 결과 0명 + URL page=5 이면 보정이 건너뛰어져 「5 / 1」, [이전] 활성으로 남았다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../mockups/shared/admin2/members.js'), 'utf8');

const IDS = ['membersWorkspace', 'pageMessage', 'filterForm', 'q', 'via', 'map', 'status', 'sort', 'pageSize',
  'resultCount', 'rows', 'listMessage', 'pageRange', 'prev', 'next', 'pageLabel', 'detail', 'displayTimezone',
  'confirm', 'saveRequest', 'toast', 'reload', 'reset', 'filterToggle', 'filterFields', 'filterLabel',
  'memberMode', 'modeNote'];

class El {
  constructor(id) {
    this.id = id; this.textContent = ''; this.innerHTML = ''; this.hidden = false; this.disabled = false;
    this.value = ''; this.dataset = {}; this.scrollTop = 0; this.attrs = {}; this.open = false;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener() {}
  insertAdjacentHTML(_, html) { this.innerHTML += html; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  requestSubmit() { this.onsubmit && this.onsubmit({ preventDefault() {} }); }
}

function member(id) {
  return { id, name: '가짜' + id, email: `m${id}@example.invalid`, via_code: 'email', map_state: 'none',
    status: 'active', data_origin: 'demo', joined: '2026-09-01T01:00:00+00:00', last: null, last_login_at: null,
    orders: 0, consults: 0, reviews: 0, favs: 0, alerts: 0, requested_at: null, mall_id: null, visitor_linked: false };
}

// total 명이 있는 가짜 검색 API. 요청 page 가 범위 밖이면 서버처럼 빈 items 를 준다.
async function harness({ total, query }) {
  const els = Object.fromEntries(IDS.map(id => [id, new El(id)]));
  els.pageSize.value = '20';
  const calls = [];
  const loc = { href: 'http://fixture.invalid/admin2/members?' + query };
  const fetch = async (url) => {
    calls.push(url);
    const u = new URL(url, 'http://fixture.invalid');
    if (u.pathname === '/api/admin/members/search') {
      const page = Number(u.searchParams.get('page')), size = Number(u.searchParams.get('page_size'));
      const start = (page - 1) * size;
      const items = [];
      for (let i = start; i < Math.min(total, start + size); i++) items.push(member(i + 1));
      return { ok: true, status: 200, json: async () => ({ items, total, page, page_size: size, member_mode: 'own',
        unmapped_via: [], available_filters: { via: ['email'], status: ['active'] }, metric_notes: {} }) };
    }
    const id = Number(u.pathname.split('/').pop());
    return { ok: true, status: 200, json: async () => ({ member: member(id), member_mode: 'own', metric_notes: {} }) };
  };
  const media = { matches: false, addEventListener() {} };
  const ctx = {
    document: { getElementById: id => els[id] || null },
    location: loc,
    history: { replaceState: (_s, _t, next) => { loc.href = String(next); } },
    window: { scrollY: 0, scrollTo() {} },
    matchMedia: () => media,
    requestAnimationFrame: f => f(),
    fetch, URL, URLSearchParams, AbortController, Intl, Promise, JSON, Math, Number, String, Object, Array,
    setTimeout, clearTimeout, console,
  };
  vm.runInNewContext(source, ctx, { filename: 'members.js' });
  for (let i = 0; i < 50; i++) await new Promise(r => setImmediate(r));
  const searches = calls.filter(c => c.startsWith('/api/admin/members/search'));
  return { els, searches, pages: searches.map(c => Number(new URL(c, 'http://x').searchParams.get('page'))),
    urlPage: new URL(loc.href).searchParams.get('page') };
}

test('결과 0명 + page=5 → 1 / 1, 이전·다음 비활성, 보정 조회 1회', async () => {
  const h = await harness({ total: 0, query: 'page=5&via=email' });
  assert.equal(h.els.pageLabel.textContent, '1 / 1');
  assert.equal(h.els.prev.disabled, true);
  assert.equal(h.els.next.disabled, true);
  assert.deepEqual(h.pages, [5, 1]);
  assert.equal(h.urlPage, '1');
  assert.equal(h.els.resultCount.textContent, '검색 결과 0명');
});

test('결과 있음 + 범위 밖 page → 마지막 페이지로 보정(기존 동작 그대로)', async () => {
  const h = await harness({ total: 25, query: 'page=5' });
  assert.equal(h.els.pageLabel.textContent, '2 / 2');
  assert.deepEqual(h.pages, [5, 2]);
  assert.equal(h.els.prev.disabled, false);
  assert.equal(h.els.next.disabled, true);
});

test('범위 안 page 는 추가 조회 없음', async () => {
  for (const [total, query, label] of [[25, 'page=1', '1 / 2'], [25, 'page=2', '2 / 2'], [0, 'page=1', '1 / 1']]) {
    const h = await harness({ total, query });
    assert.equal(h.els.pageLabel.textContent, label, query);
    assert.equal(h.pages.length, 1, query);
  }
});
