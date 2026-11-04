"use strict";
// ADMIN-ROW09 — 단가표 화면(price_import.html.j2)의 조회 load()를 «실제 페이지 스크립트» 통째로 실행한다.
// 가짜 DOM·가짜 fetch·가짜 공급처만 쓴다. 실제 API·DB·업로드·가격 없음.
// 결함: HTTP 200인데 본문이 깨졌거나({}·null·JSON 아님) files가 배열이 아니면
//   ① 오류 없이 「파일 없음」 정상 빈 목록처럼 보이거나
//   ② files가 문자열·객체면 pickDefaultSupplier에서 TypeError → 로더가 영원히 돈다.
// 기대: 형식이 틀린 응답은 piError로 드러내고, 로더를 끄고, 이전에 받은 목록을 그대로 둔다.
//       정상 빈 목록({files: []})은 오류가 아니다. 실패 뒤 정상 재조회하면 복구된다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

const tpl = fs.readFileSync(path.join(__dirname, '../templates/admin/price_import.html.j2'), 'utf8');
const m = tpl.match(/\{% block foot_extra %\}\s*<script>([\s\S]*?)<\/script>/);
assert.ok(m, 'foot_extra <script> 블록을 찾지 못함');

const SUPPLIERS = [
  { supplier_id: 7, name: '가짜공급처A', has_preset: true },
  { supplier_id: 8, name: '가짜공급처B', has_preset: true },
];
const script = m[1]
  .replace('{{ suppliers_json | safe }}', JSON.stringify(SUPPLIERS))
  .replace('{{ match_stats_json | safe }}', '{}')
  .replace('{{ recent_json | safe }}', '[]');
assert.ok(!/\{\{|\{%/.test(script), '치환 안 된 Jinja 자리표시자가 남음');

class El {
  constructor(id, hidden) {
    this.id = id; this.hidden = !!hidden; this.textContent = ''; this.innerHTML = '';
    this.className = ''; this.disabled = false; this.title = '';
  }
}

function fakeFile(id, supplierId, label) {
  return {
    file_id: id, supplier_id: supplierId, supplier: '가짜', label, received_at: '2026-11-01T00:00:00+00:00',
    status: '대기', row_count: 3, preset: { summary: '가짜', map_text: '가짜', note: '가짜' },
    same: 1, chg: [], nw: [], stat: [],
  };
}
const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const raw = (status, text) => ({ ok: status >= 200 && status < 300, status, json: async () => JSON.parse(text) });

// responses: load()가 순서대로 받을 가짜 응답(함수면 reject 등 직접 제어).
function boot(responses) {
  const els = {
    piLoading: new El('piLoading', false), piError: new El('piError', true), piLayout: new El('piLayout', true),
    piFileList: new El('piFileList'), piRight: new El('piRight'),
    piUploadBtn: new El('piUploadBtn'), piUploadStatus: new El('piUploadStatus'), piFileInput: new El('piFileInput'),
  };
  const calls = [];
  const unhandled = [];
  const queue = responses.slice();
  const fetch = (url, opts) => {
    calls.push({ url, method: (opts && opts.method) || 'GET' });
    const next = queue.shift();
    if (!next) return new Promise(() => {});
    return typeof next === 'function' ? next() : Promise.resolve(next);
  };
  const listeners = {};
  const ctx = {
    document: {
      getElementById: (id) => els[id] || null,
      addEventListener: (t, fn) => { listeners[t] = fn; },
    },
    fetch, console, Promise, Number, String, Date, JSON, Object, Array, isNaN, setTimeout,
    // 업로드 성공 → load() 재조회 경로에만 쓰인다. 실제 파일·네트워크 없음.
    FormData: class { append() {} },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  const onUnh = (e) => unhandled.push(e && e.message ? e.message : String(e));
  process.on('unhandledRejection', onUnh);
  vm.runInContext(script, ctx, { filename: 'price_import.html.j2#script' });
  return {
    els, calls, unhandled,
    settle: async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setImmediate(r)); },
    done: () => process.off('unhandledRejection', onUnh),
    // 화면에서 load()를 다시 부르는 실제 경로는 업로드 성공뿐이다(onFileChosen → load()).
    // 그 경로를 가짜 change 이벤트로 일으켜 재조회를 시험한다.
    upload: () => listeners.change({ target: { id: 'piFileInput', files: [{ name: 'x.xlsx' }], value: '' } }),
  };
}

function visible(els) {
  return {
    loading: !els.piLoading.hidden, error: els.piError.hidden ? null : els.piError.textContent,
    layout: !els.piLayout.hidden, list: els.piFileList.innerHTML,
  };
}

test('정상 응답 — 파일 있는 목록은 목록을 그린다', async () => {
  const h = boot([ok({ fee_rate: 0.03, margin_rate: 0.1, files: [fakeFile(1, 7, '가짜A_1101.xlsx')] })]);
  await h.settle(); h.done();
  const v = visible(h.els);
  assert.equal(v.loading, false); assert.equal(v.error, null); assert.equal(v.layout, true);
  assert.match(v.list, /가짜A_1101\.xlsx/);
  assert.deepEqual(h.unhandled, []);
});

test('정상 빈 목록 {files: []} — 오류가 아니라 「아직 올라온 파일이 없습니다」', async () => {
  const h = boot([ok({ fee_rate: 0.03, margin_rate: 0.1, files: [] })]);
  await h.settle(); h.done();
  const v = visible(h.els);
  assert.equal(v.loading, false); assert.equal(v.error, null); assert.equal(v.layout, true);
  assert.match(v.list, /아직 올라온 파일이 없습니다/);
  assert.deepEqual(h.unhandled, []);
});

const BAD = [
  ['JSON 아님(HTML 본문)', () => raw(200, '<html>proxy</html>')],
  ['빈 객체 {}', () => ok({})],
  ['null 본문', () => ok(null)],
  ['files 누락', () => ok({ fee_rate: 0.03, margin_rate: 0.1 })],
  ['files 문자열', () => ok({ fee_rate: 0.03, margin_rate: 0.1, files: 'broken' })],
  ['files 객체', () => ok({ fee_rate: 0.03, margin_rate: 0.1, files: { a: 1 } })],
];

for (const [name, bad] of BAD) {
  test(`HTTP 200 형식 오류(${name}) — 빈 목록으로 위장하지 않고 오류 표시·로더 종료`, async () => {
    const h = boot([bad()]);
    await h.settle(); h.done();
    const v = visible(h.els);
    assert.deepEqual(h.unhandled, [], 'TypeError/unhandled rejection 없어야 함');
    assert.equal(v.loading, false, '로더가 꺼져야 함');
    assert.ok(v.error, '오류 문구가 보여야 함');
    assert.match(v.error, /200/, 'HTTP 상태를 알려야 함');
    assert.equal(v.layout, false, '목록 레이아웃은 숨겨야 함(파일 없음으로 오인 방지)');
  });

  test(`형식 오류(${name}) 뒤 재조회 — 이전 목록 보존, 이후 정상 응답이면 복구`, async () => {
    const good = ok({ fee_rate: 0.03, margin_rate: 0.1, files: [fakeFile(1, 7, '가짜A_1101.xlsx')] });
    const good2 = ok({ fee_rate: 0.03, margin_rate: 0.1, files: [fakeFile(2, 8, '가짜B_1102.xlsx')] });
    const uploadOk = ok({ supplier: '가짜공급처A', supplier_id: 7, file_name: 'x.xlsx', row_count: 3 });
    // 1) 정상 → 2) 업로드 성공 → 형식 오류 재조회 → 3) 업로드 성공 → 정상 재조회
    const h = boot([good, uploadOk, bad(), uploadOk, good2]);
    await h.settle();
    assert.match(visible(h.els).list, /가짜A_1101\.xlsx/);

    h.upload(); await h.settle();
    let v = visible(h.els);
    assert.deepEqual(h.unhandled, []);
    assert.equal(v.loading, false); assert.ok(v.error); assert.equal(v.layout, false);
    // 숨겨진 목록 영역에는 직전 정상 목록이 그대로 남아 있다(지우거나 빈 목록으로 덮지 않음).
    assert.match(v.list, /가짜A_1101\.xlsx/);

    h.upload(); await h.settle(); h.done();
    v = visible(h.els);
    assert.deepEqual(h.unhandled, []);
    assert.equal(v.loading, false); assert.equal(v.error, null); assert.equal(v.layout, true);
    assert.match(v.list, /가짜B_1102\.xlsx/);
    assert.deepEqual(h.calls.map((c) => c.method), ['GET', 'POST', 'GET', 'POST', 'GET']);
  });
}

test('기존 오류 경로 보존 — 401 세션 만료 문구', async () => {
  const h = boot([raw(401, '{"detail":"x"}')]);
  await h.settle(); h.done();
  const v = visible(h.els);
  assert.equal(v.loading, false); assert.equal(v.layout, false);
  assert.equal(v.error, '세션이 만료됐습니다 — 다시 로그인해 주세요.');
});

test('기존 오류 경로 보존 — 500은 서버 detail 문구', async () => {
  const h = boot([raw(500, '{"detail":"가짜 서버 오류"}')]);
  await h.settle(); h.done();
  const v = visible(h.els);
  assert.equal(v.loading, false); assert.equal(v.layout, false);
  assert.equal(v.error, '가짜 서버 오류');
});

test('기존 오류 경로 보존 — 네트워크 실패', async () => {
  const h = boot([() => Promise.reject(new Error('Failed to fetch'))]);
  await h.settle(); h.done();
  const v = visible(h.els);
  assert.equal(v.loading, false); assert.equal(v.layout, false);
  assert.equal(v.error, '연결 실패 — Failed to fetch');
});
