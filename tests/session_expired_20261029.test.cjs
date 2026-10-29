// 운영 미리보기 로그인 만료 안내 (mockups/mvp4/assets/js/session-expired.js) -- 2026-10-29.
// 미리보기 주소에서 /api 요청이 「오픈 준비 중」 503 HTML 로 오면 안내를 한 번 띄우고, 다른 경우는 손대지 않는다.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'mockups', 'mvp4', 'assets', 'js', 'session-expired.js'), 'utf8');

function load(hostname, respond) {
  const appended = [];
  const el = () => ({ style: {}, attrs: {}, children: [], setAttribute(k, v) { this.attrs[k] = v; }, appendChild(c) { this.children.push(c); } });
  const calls = [];
  const window = {
    fetch(input) { calls.push(input); return Promise.resolve(respond(input)); },
  };
  const ctx = {
    window, location: { hostname, href: `https://${hostname}/mvp4/` }, URL,
    document: { body: { appendChild: (n) => appended.push(n) }, createElement: el },
  };
  vm.runInNewContext(SRC, ctx);
  return { window, appended, calls };
}
const html503 = { status: 503, headers: { get: () => 'text/html; charset=utf-8' } };
const json200 = { status: 200, headers: { get: () => 'application/json' } };

test('preview host: /api 503 HTML shows the login notice once', async () => {
  const { window, appended } = load('admin.popcornai.co.kr', () => html503);
  const res = await window.fetch('/api/talk/parse', { method: 'POST' });
  assert.strictEqual(res, html503);                       // 응답은 그대로 넘긴다
  await window.fetch('/api/customer/pc-catalog');
  assert.strictEqual(appended.length, 1);                  // 한 번만
  const box = appended[0];
  assert.strictEqual(box.attrs.role, 'alert');
  assert.match(box.children[0].textContent, /미리보기 로그인이 만료되었습니다/);
  assert.strictEqual(box.children[1].href, '/__preview/');
});

test('preview host: normal responses and non-api 503 do nothing', async () => {
  const { window, appended } = load('admin.popcornai.co.kr', (input) => (String(input).includes('/api/') ? json200 : html503));
  await window.fetch('/api/talk/parse');
  await window.fetch('/mvp4/assets/data.json');
  assert.strictEqual(appended.length, 0);
});

test('other hosts keep fetch untouched', async () => {
  for (const host of ['dev.popcornai.co.kr', 'popcornai.co.kr', 'www.popcornai.co.kr']) {
    const { window, appended } = load(host, () => html503);
    await window.fetch('/api/talk/parse');
    assert.strictEqual(appended.length, 0, host);
  }
});
