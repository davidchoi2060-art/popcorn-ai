// /mvp4 상품 목록 부품 사진 측정 (2026-10-20 「같은 부품이면 이미 받은 사진을 다시 쓰는가」).
//
// 실제 브라우저(Playwright Chromium)로 공개 사이트를 열고 CDP 네트워크 이벤트를 그대로 센다.
// 「요청이 보였다」와 「바이트가 다시 왔다」를 나눈다 — memory/disk 캐시·304·실제 전송 bytes 를 따로 적는다.
//
//   node tools/perf/mvp4_part_images.mjs [--base https://dev.popcornai.co.kr/mvp4/] [--samples 3]
//        [--override <dir>]   <dir>/live-cards.js 처럼 같은 이름 파일로 /mvp4/assets/js/* 를 바꿔 끼운 «after» 를
//                             배포본 «before» 와 번갈아 잰다(같은 머신·같은 시간대 비교). 없으면 배포본만 잰다.
//        [--profiles pc1440,m390] [--noslow]   빠른 점검용으로 줄인다
//        [--out result.json]
//
// 쓰기 요청은 하지 않는다(GET 만 연다). 로그인·주문·상담 접수 경로는 누르지 않는다.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => (v.startsWith('--') ? a.concat([[v.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : '1']]) : a), []));
const BASE = args.base || 'https://dev.popcornai.co.kr/mvp4/';
const SAMPLES = Number(args.samples || 3);
const OVERRIDE = args.override ? path.resolve(args.override) : null;
const OUT = args.out || `mvp4-part-images-${Date.now()}.json`;
const VARIANTS = OVERRIDE ? ['before', 'after'] : ['deployed'];
const CHROME = process.env.PW_CHROMIUM || undefined;

const PROFILES = {
  'pc1440': { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, isMobile: false, hasTouch: false },
  'm390': { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true },
};
// 느린 네트워크: 다운 1.6Mbps · 업 750kbps · RTT 150ms (Chrome DevTools 「Fast 3G」 수준)
const SLOW = { offline: false, latency: 150, downloadThroughput: 1.6e6 / 8, uploadThroughput: 750e3 / 8 };

function kind(url) {
  const u = new URL(url);
  if (/\/api\/customer\/pc-catalog$/.test(u.pathname)) return 'catalog';
  if (/\/api\/customer\/pc-offers\/\d+$/.test(u.pathname)) return 'offer';
  if (/\/api\/customer\/pc-registered\/\d+$/.test(u.pathname)) return 'registered';
  if (/\/api\/product-images\/\d+\/(detail|thumbnail)$/.test(u.pathname)) return 'part-image';
  if (/\/api\/customer\/products\/\d+\/representative-image/.test(u.pathname)) return 'pc-photo';
  if (u.hostname === 'www.popcornpc.co.kr' && /\/data\/pimg\//.test(u.pathname)) return 'mall-image';
  return 'other';
}

// 페이지 안: 카드마다 첫 부품 사진이 그려진 시각(navigationStart 기준 ms)과 img 노드 수.
const INIT = () => {
  const firstPart = {}, firstPhoto = {}, nodes = { part: 0, photo: 0 }, seenNodes = new WeakSet();
  window.__pm = { firstPart, firstPhoto, nodes, t0: 0 };
  document.addEventListener('load', (e) => {
    const img = e.target;
    if (!img || img.tagName !== 'IMG') return;
    const card = img.closest('[data-card-product]');
    if (!card) return;
    const id = card.getAttribute('data-card-product'), t = performance.now() - window.__pm.t0;
    if (img.matches('[data-cc-part-photo]')) { if (!(id in firstPart)) firstPart[id] = t; }
    else if (img.matches('[data-cc-photo]')) { if (!(id in firstPhoto)) firstPhoto[id] = t; }
  }, true);
  new MutationObserver((list) => {
    for (const m of list) for (const n of m.addedNodes) {
      if (n.nodeType !== 1) continue;
      const imgs = n.matches && n.matches('img') ? [n] : Array.from(n.querySelectorAll ? n.querySelectorAll('img') : []);
      for (const img of imgs) {
        if (seenNodes.has(img)) continue; seenNodes.add(img);
        if (img.matches('[data-cc-part-photo]')) nodes.part++; else if (img.matches('[data-cc-photo]')) nodes.photo++;
      }
    }
  }).observe(document, { childList: true, subtree: true });
};

// 바꿔 끼우기·실패 주입은 CDP Fetch 로 «그 주소만» 가로챈다. Playwright route() 는 컨텍스트 HTTP 캐시를 통째로 꺼서
// 캐시 재사용을 재는 이 측정을 망친다(2026-10-20 가짜 서버로 확인: route 켜면 같은 사진 29종에 요청 47건).
async function attach(page, log, opts = {}) {
  const cdp = await page.context().newCDPSession(page);
  const patterns = [];
  if (opts.variant === 'after') patterns.push({ urlPattern: '*/mvp4/assets/js/*.js*', requestStage: 'Request' });
  if (opts.failFirstImages) patterns.push({ urlPattern: '*/api/product-images/*', requestStage: 'Request' });
  if (patterns.length) {
    const failed = new Set();
    await cdp.send('Fetch.enable', { patterns });
    cdp.on('Fetch.requestPaused', async (e) => {
      const u = e.request.url;
      try {
        if (/\/api\/product-images\//.test(u) && opts.failFirstImages && !failed.has(u)) { failed.add(u); return await cdp.send('Fetch.fulfillRequest', { requestId: e.requestId, responseCode: 503, body: '' }); }
        const name = new URL(u).pathname.split('/').pop(), file = OVERRIDE && path.join(OVERRIDE, name);
        if (/\/mvp4\/assets\/js\//.test(u) && file && fs.existsSync(file)) return await cdp.send('Fetch.fulfillRequest', { requestId: e.requestId, responseCode: 200, responseHeaders: [{ name: 'Content-Type', value: 'application/javascript; charset=utf-8' }, { name: 'Cache-Control', value: 'no-cache' }], body: fs.readFileSync(file).toString('base64') });
        await cdp.send('Fetch.continueRequest', { requestId: e.requestId });
      } catch { /* 페이지가 이미 넘어갔다 */ }
    });
  }
  await cdp.send('Network.enable');
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: false });
  const reqs = new Map();
  cdp.on('Network.requestWillBeSent', (e) => { if (/^https?:/.test(e.request.url)) reqs.set(e.requestId, { url: e.request.url, method: e.request.method, kind: kind(e.request.url), t0: e.timestamp, cache: 'network', status: null, bytes: 0, failed: false, cond: !!(e.request.headers['If-None-Match'] || e.request.headers['if-none-match']) }); });
  cdp.on('Network.requestServedFromCache', (e) => { const r = reqs.get(e.requestId); if (r) r.cache = 'memory-or-disk'; });
  cdp.on('Network.responseReceived', (e) => { const r = reqs.get(e.requestId); if (!r) return; r.status = e.response.status; if (e.response.fromDiskCache) r.cache = 'disk'; if (e.response.fromPrefetchCache) r.cache = 'prefetch'; if (e.response.fromServiceWorker) r.cache = 'sw'; r.size = e.response.encodedDataLength; r.ctype = e.response.mimeType; r.cc = e.response.headers['cache-control'] || e.response.headers['Cache-Control'] || ''; });
  cdp.on('Network.loadingFinished', (e) => { const r = reqs.get(e.requestId); if (!r) return; r.bytes = e.encodedDataLength; r.t1 = e.timestamp; log.push(r); reqs.delete(e.requestId); });
  cdp.on('Network.loadingFailed', (e) => { const r = reqs.get(e.requestId); if (!r) return; r.failed = e.errorText || true; r.t1 = e.timestamp; log.push(r); reqs.delete(e.requestId); });
  // 같은 문서 안 memory cache 재사용은 requestWillBeSent 없이 일어나기도 한다 — 그래서 img 노드 수를 페이지에서 따로 센다.
  return cdp;
}

async function settle(page, ms = 1500) {
  await page.waitForLoadState('load').catch(() => {});
  let last = -1;
  for (let i = 0; i < 80; i++) { // 최대 ~120초: 카드가 「불러오고 있어요」를 벗어나고 요청이 멎을 때까지
    const busy = await page.evaluate(() => document.querySelectorAll('.cc-parts[aria-busy="true"]').length).catch(() => 0);
    const n = await page.evaluate(() => performance.getEntriesByType('resource').length).catch(() => 0);
    // 화면 안 사진만 기다린다 — loading=lazy 인 화면 밖 사진은 스크롤 전에는 complete 가 되지 않는다
    const pending = await page.evaluate(() => Array.from(document.querySelectorAll('img[data-cc-part-photo], img[data-cc-photo]')).filter((i) => { if (i.complete) return false; const r = i.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; }).length).catch(() => 0);
    if (!busy && !pending && n === last) break;
    last = n; await page.waitForTimeout(ms);
  }
}

async function scrollAll(page) {
  const h = await page.evaluate(() => document.documentElement.scrollHeight);
  const vh = page.viewportSize().height;
  for (let y = 0; y <= h; y += Math.round(vh * 0.8)) { await page.evaluate((yy) => window.scrollTo(0, yy), y); await page.waitForTimeout(250); }
  await page.evaluate(() => window.scrollTo(0, 0));
}

function summarize(log, pm) {
  const by = {};
  for (const r of log) {
    const k = r.kind; const s = by[k] || (by[k] = { requests: 0, network: 0, cache: 0, s200: 0, s304: 0, failed: 0, bytes: 0, urls: {} });
    s.requests++; if (r.failed) s.failed++;
    if (r.cache === 'network') s.network++; else s.cache++;
    if (r.status === 200 && r.cache === 'network') s.s200++; if (r.status === 304) s.s304++;
    s.bytes += r.bytes || 0; s.urls[r.url] = (s.urls[r.url] || 0) + 1;
  }
  for (const k of Object.keys(by)) {
    const u = by[k].urls; by[k].unique = Object.keys(u).length; by[k].duplicateRequests = Object.values(u).reduce((a, n) => a + (n - 1), 0);
    by[k].netDuplicateUrls = Object.keys(u).filter((url) => log.filter((r) => r.url === url && r.cache === 'network' && r.status === 200).length > 1).length;
    delete by[k].urls;
  }
  const fp = pm ? Object.values(pm.firstPart).sort((a, b) => a - b) : [];
  const q = (arr, p) => (arr.length ? Math.round(arr[Math.min(arr.length - 1, Math.floor(p * (arr.length - 1)))]) : null);
  return { byKind: by, imgNodes: pm ? pm.nodes : null, cardsWithPartPhoto: fp.length, firstPartPhotoMs: { min: q(fp, 0), median: q(fp, 0.5), p90: q(fp, 0.9), max: q(fp, 1) } };
}

async function newContext(browser, profile, variant) {
  const ctx = await browser.newContext({ ...PROFILES[profile], locale: 'ko-KR', serviceWorkers: 'block' });
  await ctx.addInitScript(INIT);
  return ctx;
}

async function runSample(browser, profile, slow, failFirstImages, variant) {
  const ctx = await newContext(browser, profile, variant);
  const page = await ctx.newPage();
  const steps = {};
  let log = [];
  // 실패 재시도 점검(failFirstImages): 부품 사진마다 첫 시도를 503 으로 돌려준다(이후는 통과)
  const cdp = await attach(page, log, { variant, failFirstImages });
  if (slow) await cdp.send('Network.emulateNetworkConditions', SLOW);
  const step = async (name, fn) => {
    log.length = 0; await page.evaluate(() => { if (window.__pm) { for (const k of Object.keys(window.__pm.firstPart)) delete window.__pm.firstPart[k]; for (const k of Object.keys(window.__pm.firstPhoto)) delete window.__pm.firstPhoto[k]; window.__pm.nodes.part = 0; window.__pm.nodes.photo = 0; window.__pm.t0 = performance.now(); } }).catch(() => {});
    // 한 단계가 실패해도(화면 변경·시간 초과) 나머지 단계와 기록은 남긴다 — 실패는 결과에 그대로 적는다.
    const t0 = Date.now(); let error;
    try { await fn(); await settle(page); } catch (e) { error = String((e && e.message) || e).slice(0, 400); process.stderr.write(`  ${name} 실패: ${error}\n`); }
    const pm = await page.evaluate(() => window.__pm).catch(() => null);
    const extra = await page.evaluate(() => ({ partImgsInDom: document.querySelectorAll('img[data-cc-part-photo]').length, partIconsInDom: document.querySelectorAll('.cc-part-media > .icon, .cc-part-media > svg').length, uniquePartSrc: new Set(Array.from(document.querySelectorAll('img[data-cc-part-photo]')).map((i) => i.getAttribute('src'))).size, cards: document.querySelectorAll('[data-card-product]').length, busy: document.querySelectorAll('.cc-parts[aria-busy="true"]').length })).catch(() => null);
    steps[name] = { error, wallMs: Date.now() - t0, ...summarize([...log], pm), dom: extra, rawRequests: [...log].filter((r) => r.kind !== 'other').map((r) => ({ k: r.kind, url: r.url.replace(/^https?:\/\/[^/]+/, ''), st: r.status, c: r.cache, b: r.bytes, ms: r.t1 && r.t0 ? Math.round((r.t1 - r.t0) * 1000) : null, cond: r.cond, f: r.failed || undefined })) };
  };
  const catalogUrl = new URL('./?screen=catalog', BASE).toString();
  await step('1-first-load-cold', async () => { await page.goto(catalogUrl, { waitUntil: 'domcontentloaded' }); await settle(page); await scrollAll(page); });
  if (failFirstImages) { await ctx.close(); return steps; }
  await step('2-more', async () => { const b = page.locator('[data-dp-more]'); if (await b.count()) { await b.first().click(); await settle(page); await scrollAll(page); } });
  await step('3-sort-price-asc', async () => { await page.selectOption('[data-dp-filter-form] select[name=sort]', 'price-asc'); await settle(page); await scrollAll(page); });
  await step('4-filter-category', async () => { const opts = await page.$$eval('[data-dp-filter-form] select[name=category] option', (o) => o.map((x) => x.value).filter(Boolean)); if (opts.length) { await page.selectOption('[data-dp-filter-form] select[name=category]', opts[0]); await settle(page); await scrollAll(page); } });
  await step('5-reset-filter', async () => { await page.selectOption('[data-dp-filter-form] select[name=category]', ''); await page.selectOption('[data-dp-filter-form] select[name=sort]', 'default'); await settle(page); });
  await step('6-detail', async () => { const a = page.locator('[data-card-product] h2 a').first(); await Promise.all([page.waitForURL(/screen=product/), a.click()]); await settle(page); await scrollAll(page); });
  await step('7-back', async () => { await page.goBack({ waitUntil: 'domcontentloaded' }); await settle(page); await scrollAll(page); });
  await step('8-reload-warm', async () => { await page.goto(catalogUrl, { waitUntil: 'domcontentloaded' }); await settle(page); await scrollAll(page); });
  await ctx.close();
  return steps;
}

// 같은 부품 사진의 변형별 크기(detail PNG vs thumbnail WebP) — 이미지 응답 자체를 직접 받아 잰다.
async function variantSizes(browser, codes) {
  const ctx = await browser.newContext();
  const out = [];
  for (const code of codes) {
    const row = { code };
    for (const v of ['detail', 'thumbnail']) {
      const t0 = Date.now();
      const r = await ctx.request.get(new URL(`/api/product-images/${code}/${v}`, BASE).toString()).catch((e) => ({ status: () => 'ERR ' + e.message, body: async () => Buffer.alloc(0), headers: () => ({}) }));
      const body = await r.body().catch(() => Buffer.alloc(0));
      row[v] = { status: r.status(), bytes: body.length, ms: Date.now() - t0, type: r.headers()['content-type'] || '', cc: r.headers()['cache-control'] || '', etag: r.headers()['etag'] || '' };
      const etag = r.headers()['etag'];
      if (etag) { const t1 = Date.now(); const r2 = await ctx.request.get(new URL(`/api/product-images/${code}/${v}`, BASE).toString(), { headers: { 'If-None-Match': etag } }); row[v].revalidate = { status: r2.status(), ms: Date.now() - t1 }; }
    }
    out.push(row);
  }
  await ctx.close();
  return out;
}

const browser = await chromium.launch({ executablePath: CHROME });
const result = { base: BASE, override: OVERRIDE, variants: VARIANTS, startedAt: new Date().toISOString(), samples: SAMPLES, runs: {} };
const put = (variant, key, v) => { const r = result.runs[variant] || (result.runs[variant] = {}); (r[key] || (r[key] = [])).push(v); };
for (const profile of (args.profiles ? args.profiles.split(',') : Object.keys(PROFILES))) {
  for (const slow of (args.noslow ? [false] : [false, true])) {
    const key = `${profile}${slow ? '-slow' : ''}`;
    const n = slow ? 1 : SAMPLES;
    for (let i = 0; i < n; i++) for (const variant of VARIANTS) { // 번갈아 잰다 — 시간대 차이가 한쪽에만 몰리지 않게
      process.stderr.write(`${variant} ${key} #${i + 1}\n`);
      put(variant, key, await runSample(browser, profile, slow, false, variant));
    }
  }
}
for (const variant of VARIANTS) { process.stderr.write(`${variant} fail-retry\n`); put(variant, 'pc1440-fail-first-image', await runSample(browser, 'pc1440', false, true, variant)); }
const first = (((result.runs[VARIANTS[0]].pc1440 || [])[0] || {})['1-first-load-cold'] || {}).rawRequests || [];
const codes = [...new Set(first.filter((r) => r.k === 'part-image').map((r) => r.url.match(/product-images\/(\d+)\//)[1]))].slice(0, 12);
result.variantSizes = await variantSizes(browser, codes);
await browser.close();
result.finishedAt = new Date().toISOString();
fs.writeFileSync(OUT, JSON.stringify(result, null, 1));
process.stderr.write('wrote ' + OUT + '\n');
