const { chromium } = require('playwright');
(async () => {
  const base = process.argv[2], out = process.argv[3];
  const b = await chromium.launch();
  const res = {};
  for (const [name, w, h, mobile] of [['pc', 1440, 900, false], ['m', 390, 844, true]]) {
    const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1, isMobile: mobile, hasTouch: mobile });
    const p = await ctx.newPage(); const errs = [];
    p.on('pageerror', e => errs.push(String(e))); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    p.on('requestfailed', r => errs.push('FAIL ' + r.url()));
    p.on('response', r => { if (r.status() >= 400) errs.push(r.status() + ' ' + r.url()); });
    await p.goto(base + 'index.html', { waitUntil: 'networkidle' });
    await p.waitForSelector('[data-home-carousel][data-mounted]');
    const root = p.locator('[data-home-carousel]');
    const info = await p.evaluate(() => {
      const r = document.querySelector('[data-home-carousel]');
      return { slides: [...r.querySelectorAll('.hc-slide')].map(s => ({ cls: s.className, label: s.getAttribute('aria-label'), h2: s.querySelector('h2').textContent, img: s.querySelector('.hc-image').getAttribute('src'), links: [...s.querySelectorAll('a')].map(a => a.textContent.trim() + ' -> ' + a.getAttribute('href')) })),
        counter: r.querySelector('.hc-counter').textContent, interval: r.dataset.interval, autoplay: r.dataset.autoplay, selectors: r.querySelectorAll('[data-hc-go]').length };
    });
    res[name] = { info, checks: [] };
    for (let i = 0; i < info.slides.length; i++) {
      await p.click(`[data-hc-go="${i}"]`); await p.waitForTimeout(800);
      await p.mouse.move(0, 0);
      const m = await p.evaluate((i) => {
        const r = document.querySelector('[data-home-carousel]'), s = document.getElementById('hc-slide-' + i), st = r.querySelector('.hc-stage').getBoundingClientRect();
        const img = s.querySelector('.hc-image');
        const over = [...s.querySelectorAll('.hc-copy *, .hc-collections a')].filter(e => e.offsetParent).map(e => e.getBoundingClientRect()).filter(b => b.right > st.right + 1 || b.bottom > st.bottom + 1 || b.left < st.left - 1).length;
        const copy = s.querySelector('.hc-copy').getBoundingClientRect();
        return { active: r.dataset.activeSlide, counter: r.querySelector('.hc-counter').textContent, hidden: s.hidden, overflow: over, copyBottom: Math.round(copy.bottom - st.top), stageH: Math.round(st.height), imgTop: Math.round(img.getBoundingClientRect().top - st.top), imgLoaded: img.complete && img.naturalWidth > 0 };
      }, i);
      res[name].checks.push(m);
      await root.locator('.hc-stage').screenshot({ path: `${out}/${name}-slide${i + 1}.png` });
    }
    // keyboard: focus selector 0 then End → last; Home → first
    await p.focus('[data-hc-go="0"]'); await p.keyboard.press('End'); await p.waitForTimeout(700);
    const kEnd = await p.evaluate(() => document.querySelector('[data-home-carousel]').dataset.activeSlide);
    await p.keyboard.press('ArrowRight'); await p.waitForTimeout(700);
    const kWrap = await p.evaluate(() => document.querySelector('[data-home-carousel]').dataset.activeSlide);
    const toggle = await p.evaluate(() => document.querySelector('[data-hc-toggle]').textContent);
    res[name].keyboard = { end: kEnd, wrapRight: kWrap, toggleAfterManual: toggle };
    await p.screenshot({ path: `${out}/${name}-page.png` });
    res[name].errors = errs;
    await ctx.close();
  }
  // autoplay check on a fresh PC page
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); const p = await ctx.newPage();
  await p.goto(base + 'index.html', { waitUntil: 'networkidle' }); await p.mouse.move(5, 890);
  const seq = []; for (let k = 0; k < 7; k++) { seq.push(await p.evaluate(() => document.querySelector('[data-home-carousel]').dataset.activeSlide)); await p.waitForTimeout(3700); }
  res.autoplay = seq;
  await b.close();
  console.log(JSON.stringify(res, null, 1));
})();
