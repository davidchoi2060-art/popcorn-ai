'use strict';
/* ASUS 기획전 브라우저 끝단 검증 — 실제 앱 + CI 일회용 DB + Chrome(CDP, 의존성 없음).
 * run_asus_campaign_browser.py 가 부른다. 1440 · 390 각각: 관리자 편집 → 저장 → 재조회 → 고객 표시.
 * 응답을 꾸며 넣는 구간(실패 · 빈 결과 · 미정 가격 · 지연)은 결과에 kind:'intercept' 로 구분한다. 나머지는 kind:'real'.
 * 문의 전송(purchase-inquiries)은 네트워크 단계에서 끊고, 시도가 한 번이라도 있으면 실패로 본다. */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const [BASE, SECRET, OUT] = process.argv.slice(2);
const sessions = JSON.parse(fs.readFileSync(SECRET, 'utf8'));
const results = [];
const CHROME = process.env.CHROME_BIN || ['/usr/bin/google-chrome', 'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function record(name, ok, kind, detail) {
  results.push({ name, ok: !!ok, kind, detail: detail === undefined ? null : detail });
  console.log((ok ? 'PASS ' : 'FAIL ') + '[' + kind + '] ' + name + (detail !== undefined && !ok ? ' :: ' + JSON.stringify(detail) : ''));
}

class Cdp {
  constructor(ws) { this.ws = ws; this.id = 0; this.wait = new Map(); this.handlers = []; }
  static async open(url) {
    const ws = new WebSocket(url);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const c = new Cdp(ws);
    ws.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.id && c.wait.has(d.id)) {
        const { res, rej } = c.wait.get(d.id); c.wait.delete(d.id);
        if (d.error) rej(new Error(JSON.stringify(d.error))); else res(d.result);
      } else if (d.method) c.handlers.forEach((h) => h(d));
    };
    return c;
  }
  send(method, params, sessionId) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params: params || {}, sessionId }));
    return new Promise((res, rej) => this.wait.set(id, { res, rej }));
  }
}

class Page {
  constructor(cdp, sid) {
    this.cdp = cdp; this.sid = sid; this.rules = []; this.exceptions = []; this.inquiryAttempts = 0; this.puts = 0;
    cdp.handlers.push((d) => {
      if (d.sessionId !== sid) return;
      if (d.method === 'Runtime.exceptionThrown') this.exceptions.push(d.params.exceptionDetails.exception ? d.params.exceptionDetails.exception.description : d.params.exceptionDetails.text);
      if (d.method === 'Fetch.requestPaused') this.onPaused(d.params);
      // 미저장 이탈 경고 등 대화상자에 걸려 멈추지 않게 수락하고 수를 남긴다.
      if (d.method === 'Page.javascriptDialogOpening') { this.dialogs = (this.dialogs || 0) + 1; this.send('Page.handleJavaScriptDialog', { accept: true }); }
      if (d.method === 'Network.requestWillBeSent' && d.params.request.method === 'PUT' && d.params.request.url.includes('/api/admin/asus-campaign/')) this.puts += 1;
    });
  }
  send(m, p) { return this.cdp.send(m, p, this.sid); }
  async onPaused(p) {
    const url = p.request.url;
    if (url.includes('purchase-inquiries') && p.request.method !== 'GET') {
      this.inquiryAttempts += 1;
      return this.send('Fetch.failRequest', { requestId: p.requestId, errorReason: 'BlockedByClient' });
    }
    const rule = this.rules.find((r) => url.includes(r.match) && (!r.method || r.method === p.request.method));
    if (!rule) return this.send('Fetch.continueRequest', { requestId: p.requestId });
    if (rule.delay) await sleep(rule.delay);
    if (rule.delay && !rule.status && !rule.abort) return this.send('Fetch.continueRequest', { requestId: p.requestId }).catch(() => {});
    if (rule.abort) return this.send('Fetch.failRequest', { requestId: p.requestId, errorReason: 'ConnectionFailed' });
    return this.send('Fetch.fulfillRequest', { requestId: p.requestId, responseCode: rule.status || 200,
      responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
      body: Buffer.from(JSON.stringify(rule.body || {})).toString('base64') });
  }
  async js(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(expr.slice(0, 120) + ' :: ' + JSON.stringify(r.exceptionDetails.exception || r.exceptionDetails.text));
    return r.result.value;
  }
  async until(expr, ms) {
    const end = Date.now() + (ms || 20000);
    let last;
    while (Date.now() < end) {
      try { last = await this.js(expr); if (last) return last; } catch (e) { last = e.message; }
      await sleep(100);
    }
    throw new Error('timeout: ' + expr + ' last=' + last);
  }
  async go(url) {
    await this.send('Page.navigate', { url: BASE + url });
    await sleep(150);
    await this.until("document.readyState==='complete'");
  }
  async size(w) {
    const h = w > 700 ? 900 : 844;
    await this.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: w < 700 });
  }
  async shot(name) {
    // 관리자 셸은 100vh 안에서 스크롤하므로 전체 캡처를 하면 배치가 벌어진다. 넓은 화면의 관리자는 보이는 영역만 찍는다.
    const wide = await this.js("innerWidth>768&&!!document.querySelector('.a2-shell')");
    const r = await this.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: !wide });
    fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(r.data, 'base64'));
  }
  async login(role) {
    await this.send('Network.deleteCookies', { name: sessions.cookie, url: BASE });
    await this.send('Network.setCookie', { name: sessions.cookie, value: sessions[role], url: BASE, path: '/', httpOnly: true });
  }
  body() { return this.js('document.body.innerText'); }
  noOverflow() { return this.js('document.documentElement.scrollWidth<=window.innerWidth'); }
  // 한국어 라벨로 칸을 찾는다. 사람이 보는 이름 그대로다.
  fieldExpr(label, nth) {
    return `Array.from(document.querySelectorAll('.ac-field')).filter(f=>f.querySelector('label').textContent.startsWith(${JSON.stringify(label)}))[${nth || 0}].querySelector('input,select,textarea')`;
  }
  value(label, nth) { return this.js(this.fieldExpr(label, nth) + '.value'); }
  async set(label, val, nth) {
    await this.js(`(function(){var e=${this.fieldExpr(label, nth)};e.value=${JSON.stringify(String(val))};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  }
  clickText(sel, text) {
    return this.js(`(function(){var b=Array.from(document.querySelectorAll(${JSON.stringify(sel)})).find(x=>x.textContent.trim()===${JSON.stringify(text)});if(!b)throw new Error('no '+${JSON.stringify(text)});b.click();})()`);
  }
  tab(id) { return this.js(`document.querySelector('[data-model="${id}"]').click()`); }
  async formOf(id, nameContains) {
    await this.until(`document.querySelector('[data-model="${id}"]')&&document.querySelector('[data-model="${id}"]').getAttribute('aria-selected')==='true'&&!!document.getElementById('acSave')`);
    if (nameContains) await this.until(`${this.fieldExpr('모델 이름')}.value.includes(${JSON.stringify(nameContains)})`);
  }
}

const ADMIN = '/admin2/asus-campaign';

async function runWidth(page, w) {
  const tag = String(w);
  const tagline = '저장 확인 문구 ' + tag;
  const plan = 5990000 + w;
  await page.size(w);

  // ── 고객: 저장 전 ──
  await page.go('/mvp4/asus.html');
  await page.until("document.querySelectorAll('.az-card').length===3");
  let text = await page.body();
  record(tag + ' 서브메인 3종 + 기획 검토가 표기', text.includes('문서·업무용 PC') && text.includes('3,990,000원') && text.includes('기획 검토가 · ASUS 협의 전') && text.includes('공급 확인 필요'), 'real');
  record(tag + ' 서브메인 0원 없음 · 가로 넘침 없음', !/(^|[^\d,])0원/.test(text) && await page.noOverflow(), 'real');
  await page.shot(tag + '-01-customer-home-before');

  // ── 관리자: 편집 ──
  await page.login('operator');
  await page.go(ADMIN);
  await page.formOf('business');
  record(tag + ' 관리자 첫 화면이 DB 값을 읽음', (await page.value('한 줄 소개')).length > 0 && (await page.value('기획 검토가(원)')) !== '', 'real');
  record(tag + ' 관리자 저장 영향 안내 표시', (await page.body()).includes('바로 반영'), 'real');
  await page.shot(tag + '-02-admin-initial');
  await page.tab('video');
  await page.formOf('video', '영상');
  const beforeVersion = await page.js("document.getElementById('acMsg').textContent");
  await page.set('한 줄 소개', tagline);
  await page.set('기획 검토가(원)', plan);
  await page.set('비고', '공급 재확인 ' + tag);

  // 미저장 가드
  await page.tab('business');
  await page.until("!document.getElementById('acGuard').hidden");
  await page.shot(tag + '-03-admin-unsaved-guard');
  await page.clickText('#acGuard button', '계속 편집');
  record(tag + ' 미저장 가드: 계속 편집하면 입력 유지', (await page.value('한 줄 소개')) === tagline, 'real');

  // 중복 저장 방지: 같은 틱에 두 번 누른다
  const putsBefore = page.puts;
  await page.js("document.getElementById('acSave').click();document.getElementById('acSave').click();");
  await page.until("document.getElementById('acMsg').textContent.includes('저장했습니다')");
  record(tag + ' 두 번 눌러도 PUT 한 번', page.puts - putsBefore === 1, 'real', page.puts - putsBefore);
  record(tag + ' 저장 후 DB 재조회 값이 폼에 표시', (await page.value('한 줄 소개')) === tagline && (await page.value('기획 검토가(원)')) === String(plan), 'real', beforeVersion);
  await page.shot(tag + '-04-admin-saved');

  // 새로 열어도 남아 있는가
  await page.go(ADMIN);
  await page.formOf('business');
  await page.tab('video');
  await page.formOf('video', '영상');
  record(tag + ' 새로고침 후에도 저장값 유지', (await page.value('한 줄 소개')) === tagline, 'real');
  record(tag + ' 관리자 화면 가로 넘침 없음', await page.noOverflow(), 'real');

  // ── 고객: 저장 후 ──
  await page.go('/mvp4/asus-pc.html?model=video');
  await page.until("!!document.querySelector('.az-plan-value')");
  text = await page.body();
  const planText = plan.toLocaleString('ko-KR') + '원';
  record(tag + ' 상세에 저장값 반영', text.includes(tagline) && text.includes(planText) && text.includes('공급 재확인 ' + tag), 'real');
  record(tag + ' 상세 미확정 고지 유지', ['공급 확인 필요', '기획 검토가 · ASUS 협의 전', '전체 합계 미완성', '호환 완료가 아닙니다', '가격 미표시', '자료 확인 전 확정 불가', '별도 문의'].every((x) => text.includes(x)), 'real');
  record(tag + ' 상세 가로 넘침 없음 · 이미지 로드', await page.noOverflow() && await page.until("document.querySelector('.az-detail-art img').complete&&document.querySelector('.az-detail-art img').naturalWidth>0"), 'real');
  await page.shot(tag + '-05-customer-detail-after');
  await page.go('/mvp4/asus.html');
  await page.until("document.querySelectorAll('.az-card').length===3");
  text = await page.body();
  record(tag + ' 서브메인에 저장값 반영, 다른 모델 불변', text.includes(tagline) && text.includes(planText) && text.includes('3,990,000원') && text.includes('12,990,000원'), 'real');
  await page.shot(tag + '-06-customer-home-after');
  await page.go('/mvp4/asus-consult.html?model=video');
  await page.until("document.querySelector('.iq-aside .iq-package')&&document.querySelector('.iq-aside .iq-package').dataset.asus==='ready'");
  text = await page.body();
  record(tag + ' 문의 안내에 저장값 반영', text.includes(planText) && text.includes('영상·디자인용 PC'), 'real');
  await page.shot(tag + '-07-customer-consult');

  // ── 동시 편집 ──
  await page.go(ADMIN);
  await page.formOf('business');
  await page.tab('video');
  await page.formOf('video', '영상');
  await page.set('한 줄 소개', '내 입력 ' + tag);
  // 다른 편집자가 먼저 저장한다(같은 API, 실제 DB).
  await page.js(`(async function(){var d=await (await fetch('/api/admin/asus-campaign/video')).json();d.content.prepare='다른 편집자 ${tag}';var r=await fetch('/api/admin/asus-campaign/video',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:d.version,plan_review_price:d.plan_review_price,content:d.content})});if(!r.ok)throw new Error('other editor '+r.status);})()`);
  await page.js("document.getElementById('acSave').click()");
  await page.until("!document.getElementById('acGuard').hidden&&document.getElementById('acGuard').textContent.includes('먼저 저장')");
  record(tag + ' 동시 편집 409: 입력 유지 · 재저장 차단', (await page.value('한 줄 소개')) === '내 입력 ' + tag && await page.js("document.getElementById('acSave').disabled"), 'real');
  await page.shot(tag + '-08-admin-conflict');
  await page.clickText('#acGuard button', '최신값 불러오기');
  await page.until(`${page.fieldExpr('준비 안내')}.value==='다른 편집자 ${tag}'`);
  record(tag + ' 최신값 불러오면 먼저 저장한 값 표시', (await page.value('한 줄 소개')) === tagline, 'real');

  // ── 입력 오류 ──
  await page.set('한 줄 소개', '<script>alert(1)</script>');
  await page.js("document.getElementById('acSave').click()");
  await page.until("document.getElementById('acMsg').classList.contains('err')");
  record(tag + ' 꺾쇠 입력 거부 · 입력 유지', (await page.value('한 줄 소개')).includes('<script>'), 'real', await page.js("document.getElementById('acMsg').textContent"));
  await page.shot(tag + '-09-admin-validation');
  await page.set('한 줄 소개', tagline);
  await page.set('기획 검토가(원)', '0');
  await page.js("document.getElementById('acSave').click()");
  await page.until("document.getElementById('acMsg').classList.contains('err')&&!document.getElementById('acSave').disabled");
  record(tag + ' 기획 검토가 0 거부', (await page.value('기획 검토가(원)')) === '0', 'real');
  await page.go('/mvp4/asus.html');
  await page.until("document.querySelectorAll('.az-card').length===3");
  text = await page.body();
  record(tag + ' 거부된 값은 고객에게 안 나감', text.includes(planText) && !text.includes('<script>'), 'real');

  // ── 저장 지연 중 편집 잠금 (root 소스검토 2026-11-06) ──
  await page.go(ADMIN);
  await page.formOf('business');
  await page.tab('video');
  await page.formOf('video', '영상');
  const lockedText = '지연 저장 값 ' + tag;
  await page.set('한 줄 소개', lockedText);
  const optionCount = "document.querySelectorAll('[data-option]').length";
  const optionsBefore = await page.js(optionCount);
  page.rules = [{ match: '/api/admin/asus-campaign/video', method: 'PUT', delay: 2000 }];
  await page.js("document.getElementById('acSave').click()");
  await page.until("document.getElementById('acForm').disabled===true");
  // 사람의 입력으로 시도한다: 포커스를 잡아 글자를 넣고, 후보 추가 · 삭제 단추와 탭을 누른다.
  await page.js(page.fieldExpr('한 줄 소개') + '.focus()');
  await page.send('Input.insertText', { text: ' 저장중입력' });
  await page.js("Array.from(document.querySelectorAll('#acForm button')).filter(b=>b.textContent==='후보 추가'||b.textContent==='후보 삭제').slice(0,2).forEach(b=>b.click())");
  await page.tab('business');
  record(tag + ' 저장 중 폼 · 탭 잠금', await page.js("Array.from(document.querySelectorAll('#acForm input,#acForm select,#acForm textarea,#acForm button')).every(e=>e.matches(':disabled'))&&document.querySelector('[data-model=business]').disabled"), 'intercept');
  record(tag + ' 저장 중 입력 · 후보 변경이 먹지 않음', (await page.value('한 줄 소개')) === lockedText && (await page.js(optionCount)) === optionsBefore, 'intercept', await page.value('한 줄 소개'));
  await page.shot(tag + '-14-admin-saving-locked');
  await page.until("document.getElementById('acMsg').textContent.includes('저장했습니다')");
  page.rules = [];
  record(tag + ' 지연 저장 뒤 재조회 값 = 보낸 값', (await page.value('한 줄 소개')) === lockedText && (await page.js("document.getElementById('acForm').disabled")) === false, 'intercept');
  const stored = await page.js("fetch('/api/admin/asus-campaign/video').then(r=>r.json()).then(d=>d.content.tagline)");
  record(tag + ' DB 값에 저장 중 입력이 섞이지 않음', stored === lockedText, 'intercept', stored);
  // 실패로 끝나면 잠금이 풀리고, 칸별 읽기전용은 그대로여야 한다.
  await page.set('한 줄 소개', lockedText + ' 실패');
  page.rules = [{ match: '/api/admin/asus-campaign/video', method: 'PUT', delay: 300, status: 500, body: { detail: '시험 실패' } }];
  await page.js("document.getElementById('acSave').click()");
  await page.until("document.getElementById('acMsg').classList.contains('err')");
  page.rules = [];
  record(tag + ' 저장 실패 후 잠금 해제 · 입력 유지 · 운영체제 상태는 계속 잠김', (await page.value('한 줄 소개')) === lockedText + ' 실패' && !(await page.js(page.fieldExpr('한 줄 소개') + ".matches(':disabled')")) && await page.js("Array.from(document.querySelectorAll('.ac-sub')).find(b=>b.querySelector('h3')&&b.querySelector('h3').textContent==='운영체제').querySelector('select').disabled"), 'intercept');
  await page.set('한 줄 소개', tagline);
  await page.js("document.getElementById('acSave').click()");
  await page.until("document.getElementById('acMsg').textContent.includes('저장했습니다')");

  // ── 늦은 응답 ──
  await page.go(ADMIN);
  await page.formOf('business');
  page.rules = [{ match: '/api/admin/asus-campaign/local-ai', delay: 1500 }];
  await page.tab('local-ai');
  await sleep(100);
  await page.tab('video');
  await page.formOf('video', '영상');
  await sleep(1800);
  record(tag + ' 늦게 온 이전 모델 응답이 현재 모델을 덮지 않음', (await page.value('모델 이름')).includes('영상') && (await page.js("document.querySelector('[data-model=\"video\"]').getAttribute('aria-selected')")) === 'true', 'intercept');
  page.rules = [];

  // ── 관리자 조회 실패 ──
  page.rules = [{ match: '/api/admin/asus-campaign/video', status: 500, body: { detail: '시험 실패' } }];
  await page.tab('business');
  await page.formOf('business');
  await page.tab('video');
  await page.until("!!document.querySelector('#acBody .ac-state.err')");
  record(tag + ' 관리자 조회 실패: 폼 없이 오류 · 다시 시도', !(await page.js("!!document.getElementById('acSave')")), 'intercept');
  await page.shot(tag + '-10-admin-load-failed');
  page.rules = [];
  await page.clickText('#acBody button', '다시 시도');
  await page.formOf('video', '영상');
  record(tag + ' 관리자 다시 시도 후 복구', true, 'intercept');

  // ── 조회 권한 ──
  await page.login('viewer');
  await page.go(ADMIN);
  await page.formOf('business');
  record(tag + ' viewer: 입력 비활성 · 저장 비활성', await page.js("document.getElementById('acSave').disabled&&Array.from(document.querySelectorAll('.ac-field input,.ac-field select,.ac-field textarea')).every(e=>e.disabled)"), 'real');
  const put = await page.js(`(async function(){var d=await (await fetch('/api/admin/asus-campaign/business')).json();return (await fetch('/api/admin/asus-campaign/business',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:d.version,plan_review_price:1,content:d.content})})).status;})()`);
  record(tag + ' viewer: 저장 API 403', put === 403, 'real', put);
  await page.shot(tag + '-11-admin-viewer');
  await page.login('operator');

  // ── 고객 실패 · 빈 결과 · 미정 ──
  page.rules = [{ match: '/api/customer/asus-campaign', status: 503, body: { detail: 'x' } }];
  await page.go('/mvp4/asus.html');
  await page.until("!!document.querySelector('[data-az-load=\"error\"]')");
  text = await page.body();
  record(tag + ' 고객 실패: 오류 표시 · 옛 값 없음', !text.includes('3,990,000') && !text.includes('RTX 5070') && !text.includes('문서·업무용 PC'), 'intercept');
  await page.shot(tag + '-12-customer-failed');
  page.rules = [];
  await page.clickText('[data-az-retry]', '다시 시도');
  await page.until("document.querySelectorAll('.az-card').length===3");
  record(tag + ' 고객 다시 시도 후 표시', true, 'intercept');

  page.rules = [{ match: '/api/customer/asus-campaign', abort: true }];
  await page.go('/mvp4/asus-pc.html?model=video');
  await page.until("!!document.querySelector('[data-az-load=\"error\"]')");
  text = await page.body();
  record(tag + ' 상세 실패: 다른 값으로 대신하지 않음', !text.includes('RTX 5080') && !text.includes('5,990,000'), 'intercept');
  await page.go('/mvp4/asus-consult.html?model=video');
  await page.until("document.querySelector('.iq-aside .iq-package')&&document.querySelector('.iq-aside .iq-package').dataset.asus==='failed'");
  text = await page.body();
  record(tag + ' 문의 화면 실패: 사양 없이 안내', text.includes('구성 정보를 불러오지 못했습니다') && !text.includes('RTX 5080'), 'intercept');

  page.rules = [{ match: '/api/customer/asus-campaign', body: { ok: true, models: [], unavailable: [] } }];
  await page.go('/mvp4/asus.html');
  await page.until("!!document.querySelector('[data-az-load=\"empty\"]')");
  record(tag + ' 고객 빈 결과 안내', (await page.body()).includes('표시할 구성이 없습니다'), 'intercept');

  page.rules = [];
  const live = await page.js("fetch('/api/customer/asus-campaign').then(r=>r.json())");
  const noPlan = JSON.parse(JSON.stringify(live));
  noPlan.models[1].plan_review_price = null;
  page.rules = [{ match: '/api/customer/asus-campaign', body: noPlan }];
  await page.go('/mvp4/asus.html');
  await page.until("document.querySelectorAll('.az-card').length===3");
  text = await page.body();
  record(tag + ' 기획 검토가 미정: 0원 아님', text.includes('미정') && !/(^|[^\d,])0원/.test(text), 'intercept');
  await page.shot(tag + '-13-customer-plan-unset');
  page.rules = [];

  record(tag + ' 알 수 없는 모델은 다른 모델로 넘기지 않음', await (async () => {
    await page.go('/mvp4/asus-pc.html?model=unknown');
    await page.until("!!document.querySelector('.az-missing')");
    return !(await page.body()).includes('RTX');
  })(), 'real');
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'asus-e2e-'));
  const chrome = spawn(CHROME, ['--headless=new', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], { stdio: 'ignore' });
  let code = 1;
  try {
    const portFile = path.join(profile, 'DevToolsActivePort');
    for (let i = 0; i < 100 && !fs.existsSync(portFile); i += 1) await sleep(100);
    await sleep(200);
    const [port, wsPath] = fs.readFileSync(portFile, 'utf8').trim().split('\n');
    const cdp = await Cdp.open('ws://127.0.0.1:' + port + wsPath);
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    const page = new Page(cdp, sessionId);
    await page.send('Page.enable');
    await page.send('Runtime.enable');
    await page.send('Network.enable');
    await page.send('Fetch.enable', { patterns: [{ urlPattern: '*asus-campaign*' }, { urlPattern: '*purchase-inquiries*' }] });

    for (const w of [1440, 390]) {
      try { await runWidth(page, w); } catch (e) { record(w + ' 진행 중단', false, 'real', e.message); await page.shot(w + '-99-aborted').catch(() => {}); }
    }
    record('문의 전송 시도 0건', page.inquiryAttempts === 0, 'real', page.inquiryAttempts);
    record('화면 스크립트 예외 0건', page.exceptions.length === 0, 'real', page.exceptions.slice(0, 5));
    code = results.every((r) => r.ok) ? 0 : 1;
  } catch (e) {
    record('실행기 오류', false, 'real', e.message);
  } finally {
    fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ base: 'CI disposable DB, real uvicorn', results }, null, 1));
    console.log(results.filter((r) => r.ok).length + ' passed, ' + results.filter((r) => !r.ok).length + ' failed');
    chrome.kill();
    await sleep(300);
    fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3 });
  }
  process.exit(code);
})();
