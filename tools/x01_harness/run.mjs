// X01 격리 재현 실행 — 네트워크·DB 없이 이 저장소의 /mvp4 정적 파일과 fixture 응답만으로 메인 광고·목록·상세를 연다.
//
//   1) python tools/x01_harness/build_fixtures.py          (fixture JSON + manifest SHA256)
//   2) node tools/x01_harness/run.mjs [출력폴더] [chrome 경로]
//
// 내장 서버(127.0.0.1, 임의 포트)가 /mvp4/* 는 mockups/mvp4 파일로, /api/customer/supercomputers(/{code}) 는 쿠키 x01case 의
// 케이스 fixture 로 답한다. /api/customer/pc-catalog 는 빈 목록, 그 밖의 /api/* 는 404 다(외부로 나가지 않는다).
// 결과: <출력폴더>/results.json (케이스별 expect·actual·pass) + 대표 예외 화면 캡처(PC 1440 · 모바일 390/360).
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn, execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
const MVP4 = path.join(ROOT, 'mockups/mvp4');
const FIX = path.join(HERE, 'fixtures');
const OUT = path.resolve(process.argv[2] || path.join(HERE, 'out'));
const CHROME = process.argv[3] || process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
fs.mkdirSync(OUT, { recursive: true });
const cases = fs.readdirSync(FIX).filter(f => /^C\d+.*\.json$/.test(f)).sort().map(f => JSON.parse(fs.readFileSync(path.join(FIX, f), 'utf-8')));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.gif': 'image/gif' };
const json = (res, code, body) => { res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(body)); };
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  const cookie = Object.fromEntries((req.headers.cookie || '').split(/;\s*/).filter(Boolean).map(c => c.split('=')));
  const fx = cases.find(c => c.case === cookie.x01case);
  if (url.pathname.startsWith('/api/')) {
    if (url.pathname === '/api/customer/supercomputers') return fx ? json(res, 200, fx.list) : json(res, 500, { detail: 'no case' });
    const m = url.pathname.match(/^\/api\/customer\/supercomputers\/(\d+)$/);
    if (m) return fx && fx.detail[m[1]] ? json(res, 200, fx.detail[m[1]]) : json(res, 404, { detail: '이 상품은 AI 슈퍼컴퓨터 목록에 없습니다.' });
    if (url.pathname === '/api/customer/pc-catalog') return json(res, 200, { ok: true, items: [] });
    return json(res, 404, { detail: 'not in harness' });
  }
  let p = url.pathname.replace(/^\/mvp4\/?/, '');
  if (!p) p = 'index.html';
  const file = path.join(MVP4, decodeURIComponent(p));
  if (!file.startsWith(MVP4) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end('not found'); }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
  fs.createReadStream(file).pipe(res);
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const BASE = `http://127.0.0.1:${server.address().port}`;

const sleep = ms => new Promise(r => setTimeout(r, ms));
const port = 9400 + Math.floor(Math.random() * 400), prof = fs.mkdtempSync(path.join(process.env.TEMP || '/tmp', 'x01-'));
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars', `--remote-debugging-port=${port}`, `--user-data-dir=${prof}`, 'about:blank'], { stdio: 'ignore' });
for (let i = 0; i < 60; i++) { try { await fetch(`http://127.0.0.1:${port}/json/version`); break; } catch { await sleep(200); } }
const tab = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(x => x.type === 'page');
const ws = new WebSocket(tab.webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
let id = 0; const pend = new Map(); const logs = [];
ws.onmessage = e => { const m = JSON.parse(e.data); if (pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } else if (m.method === 'Runtime.exceptionThrown') logs.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text); };
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async js => (await send('Runtime.evaluate', { expression: js, returnByValue: true, awaitPromise: true })).result?.result?.value;
const waitFor = async (cond, ms = 15000) => { const end = Date.now() + ms; while (Date.now() < end) { if (await ev(cond)) return true; await sleep(200); } return false; };
await send('Runtime.enable'); await send('Network.enable'); await send('Network.setCacheDisabled', { cacheDisabled: true });
const setCase = c => send('Network.setCookie', { name: 'x01case', value: c, url: BASE });
const viewport = w => send('Emulation.setDeviceMetricsOverride', { width: w, height: w < 768 ? 844 : 1000, deviceScaleFactor: 1, mobile: w < 768 });
const shot = async (name, sel) => {
  let clip;
  if (sel) { const r = await ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});if(!e)return null;e.scrollIntoView({block:'start'});const b=e.getBoundingClientRect();return {x:0,y:b.top+scrollY,w:innerWidth,h:Math.min(b.height,2400)}})()`); if (r) clip = { x: 0, y: r.y, width: r.w, height: r.h, scale: 1 }; }
  await sleep(400);
  const s = await send('Page.captureScreenshot', { format: 'jpeg', quality: 80, captureBeyondViewport: true, ...(clip ? { clip } : {}) });
  const buf = Buffer.from(s.result.data, 'base64'); fs.writeFileSync(path.join(OUT, name + '.jpg'), buf);
  return { file: name + '.jpg', sha256: crypto.createHash('sha256').update(buf).digest('hex') };
};
const idOf = href => href ? Number((href.match(/id=(\d+)/) || [])[1]) || null : null;

const results = [], captures = [];
for (const c of cases) {
  await setCase(c.case); await viewport(1440);
  // 메인 광고
  await send('Page.navigate', { url: `${BASE}/mvp4/` });
  await waitFor(`!!document.querySelector('[data-gb-home-models] a.gb-home-model')`);
  await sleep(300);
  const ad = await ev(`({models:[...document.querySelectorAll('[data-gb-home-models] a.gb-home-model')].map(a=>({href:a.getAttribute('href'),label:a.querySelector('.gb-model-label').textContent,price:a.querySelector('strong').textContent})),
    cta:(()=>{const b=document.querySelector('.gb16-actions [data-gb-home-lead]');return b?{href:b.getAttribute('href'),hidden:b.hidden}:null})(),
    heroName:document.querySelector('.gb16-eyebrow')&&document.querySelector('.gb16-eyebrow').textContent})`);
  const adModels = ad.models.filter(m => /supercomputer\.html/.test(m.href)).map(m => idOf(m.href));
  const adCta = ad.cta && !ad.cta.hidden ? idOf(ad.cta.href) : null;
  // 목록
  await send('Page.navigate', { url: `${BASE}/mvp4/supercomputers.html` });
  await waitFor(`!!document.querySelector('.scl-card, .scl-empty h2:not(:empty)') && !/불러오고/.test(document.body.innerText)`);
  const list = await ev(`[...document.querySelectorAll('[data-scl-item]')].map(a=>Number(a.dataset.sclItem))`);
  const llmBadges = await ev(`[...document.querySelectorAll('.scl-card')].filter(c=>c.querySelector('.llm-badges')).map(c=>Number(c.querySelector('[data-scl-item]').dataset.sclItem))`);
  const prices = await ev(`Object.fromEntries([...document.querySelectorAll('.scl-card')].map(c=>[c.querySelector('[data-scl-item]').dataset.sclItem,c.querySelector('.scl-foot strong').textContent]))`);
  // 타사 상세(기대값이 있는 상품만)
  const details = {};
  for (const code of Object.keys(c.expect.details || {})) {
    await send('Page.navigate', { url: `${BASE}/mvp4/supercomputer.html?id=${code}` });
    await waitFor(`!!document.querySelector('.sc-product-hero, .sc-empty h1')`); await sleep(300);
    details[code] = await ev(`(()=>{const facts=Object.fromEntries([...document.querySelectorAll('.sc-facts>div')].map(d=>[d.querySelector('span').textContent,d.querySelector('strong').textContent]));
      const spec=Object.fromEntries([...document.querySelectorAll('.sc-spec-table div')].map(d=>[d.querySelector('dt').textContent,d.querySelector('dd').textContent]));
      const txt=document.querySelector('.sc-page').innerText;
      return {facts,spec,derivedNote:!!document.querySelector('.sc-facts .sc-derived'),images:[...document.querySelectorAll('.sc-product-photo img, .sc-gallery-thumbs img')].filter(i=>i.src.indexOf('/assets/icons/')<0).length,models:document.querySelectorAll('[name=sc-model]').length,
        llmModels:/Llama|Qwen|gpt-oss/.test((document.querySelector('.llm-use-tabs')||{}).innerText||''),faq:[...document.querySelectorAll('.sc-faq summary')].map(s=>s.textContent),connectivity:!!document.querySelector('.sc-connectivity'),
        dellContent:/gb10-|DGX OS|ConnectX|2TB와 4TB|Dell/.test(txt+[...document.querySelectorAll('img')].map(i=>i.src).join(' '))}})()`);
  }
  // 판정
  const e = c.expect, checks = [];
  const eq = (name, exp, act) => checks.push({ name, expect: exp, actual: act, pass: JSON.stringify(exp) === JSON.stringify(act) });
  // 하단 줄은 2026-10-20 대표 지시로 «판매 중 · 판매가 확인 · 낮은 가격순 2개»다(위 Dell 소개 버튼 ad_cta 는 그대로 Dell 제품군).
  const low = (c.list.items || []).filter(x => x.sale_state === 'on_sale' && x.price > 0)
    .sort((a, b) => a.price - b.price || a.product_code - b.product_code).slice(0, 2).map(x => x.product_code);
  eq('low_models', low, adModels);
  eq('ad_cta', e.ad_cta, adCta);
  eq('low_fallback_to_list', low.length === 0, ad.models.length === 1 && /supercomputers\.html/.test(ad.models[0].href));
  eq('list_ids', [...e.list].sort(), [...list].sort());
  if (e.llm_badges) eq('llm_badges', [...e.llm_badges].sort(), [...llmBadges].sort());
  for (const [code, pr] of Object.entries(e.prices || {})) eq(`price_${code}`, pr, prices[code]);
  for (const [code, d] of Object.entries(e.details || {})) {
    const a = details[code] || {};
    const accel = a.facts ? (a.facts['AI 가속기'] || null) : undefined;
    if ('accelerator' in d) eq(`detail_${code}_accelerator`, d.accelerator, accel);
    if ('processor' in d) eq(`detail_${code}_processor`, d.processor, a.facts && a.facts['프로세서']);
    eq(`detail_${code}_os`, d.os, a.facts && a.facts['운영체제']);
    if ('spec_accelerator' in d) eq(`detail_${code}_spec_accelerator`, d.spec_accelerator, a.spec && a.spec['AI 가속기']);
    if ('derived_note' in d) eq(`detail_${code}_derived_note`, d.derived_note, a.derivedNote);
    eq(`detail_${code}_images`, d.images, a.images);
    eq(`detail_${code}_models`, d.models, a.models);
    eq(`detail_${code}_dell_content`, d.dell_content, a.dellContent);
    if ('llm_models' in d) eq(`detail_${code}_llm_models`, d.llm_models, a.llmModels);
    eq(`detail_${code}_faq_generic`, 3, (a.faq || []).length);
  }
  results.push({ case: c.case, purpose: c.purpose, input_list_ids: c.list.items.map(i => i.product_code), expect: e,
    actual: { ad, adModels, adCta, list, prices, details }, checks, pass: checks.every(x => x.pass) });
}
// 대표 예외 화면 캡처(PC 1440 · 모바일 390/360)
for (const [cs, page, sel] of [['C02-other-ranked-first', '/mvp4/', '#home-supercomputer'], ['C05-no-dell', '/mvp4/', '#home-supercomputer'],
  ['C09-one-dell', '/mvp4/', '#home-supercomputer'], ['C10-missing-profile', '/mvp4/supercomputer.html?id=900001', null], ['C10-missing-profile', '/mvp4/supercomputer.html?id=900003', null]]) {
  for (const w of [1440, 390, 360]) {
    await setCase(cs); await viewport(w);
    await send('Page.navigate', { url: BASE + page });
    await waitFor(sel ? `!!document.querySelector('[data-gb-home-models] a.gb-home-model')` : `!!document.querySelector('.sc-product-hero')`); await sleep(500);
    const name = `${cs}-${page.includes('id=') ? 'detail-' + page.split('id=')[1] : 'home'}-${w}`;
    captures.push({ case: cs, url: BASE + page, viewport: w, at: new Date().toISOString(), ...(await shot(name, sel)) });
  }
}
const commit = (() => { try { return execSync('git rev-parse HEAD', { cwd: ROOT }).toString().trim(); } catch { return null; } })();
const manifest = JSON.parse(fs.readFileSync(path.join(FIX, 'manifest.json'), 'utf-8'));
const report = { generated_at: new Date().toISOString(), commit, fixtures_sha256: manifest, harness: 'tools/x01_harness/run.mjs (no network, no DB)',
  summary: { cases: results.length, passed: results.filter(r => r.pass).length }, results, captures, browser_errors: logs };
fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(report, null, 1));
console.log(JSON.stringify(report.summary), results.filter(r => !r.pass).map(r => [r.case, r.checks.filter(x => !x.pass)]));
ws.close(); chrome.kill(); server.close();
