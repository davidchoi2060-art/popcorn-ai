import assert from 'node:assert/strict';
import {readFile, access, readdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {createServer} from 'vite';
import {renderToStaticMarkup} from 'react-dom/server';
import {BUILDER_BASE, CATALOG_URL, BRAND_LOGO_URL, normalizeCatalog} from '../src/paths.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const output = fileURLToPath(new URL('../../../mockups/mvp4/pc-builder/', import.meta.url));
const read = file => readFile(file, 'utf8');
function assetFile(url) {
  assert.ok(url.startsWith(BUILDER_BASE), `Asset escaped builder path: ${url}`);
  const relative = url.slice(BUILDER_BASE.length);
  const result = path.resolve(output, relative);
  assert.ok(result.startsWith(path.resolve(output) + path.sep));
  return result;
}

test('built entry and stylesheet load JS, CSS and fonts from the customer subpath', async () => {
  const html = await read(path.join(output, 'index.html'));
  const entries = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map(match => match[1]);
  assert.ok(entries.some(url => url.endsWith('.js')));
  assert.ok(entries.some(url => url.endsWith('.css')));
  for (const url of entries) await access(assetFile(url));
  const styles = await Promise.all(entries.filter(url => url.endsWith('.css')).map(url => read(assetFile(url))));
  const fonts = styles.flatMap(css => [...css.matchAll(/url\(["']?([^\s)"']+)["']?\)/g)].map(match => match[1])).filter(url => !url.startsWith('data:'));
  assert.ok(fonts.some(url => url.endsWith('.woff2')));
  for (const url of fonts) await access(assetFile(url));
});

test('catalog data is preserved and every normalized product image exists in the static build', async () => {
  const source = JSON.parse(await read(path.join(root, 'public/data/catalog.json')));
  const built = JSON.parse(await read(assetFile(CATALOG_URL)));
  assert.deepEqual(built, source);
  const normalized = normalizeCatalog(built);
  assert.equal(normalized.parts.length, 32);
  for (const [index, part] of normalized.parts.entries()) {
    await access(assetFile(part.image));
    assert.equal(part.id, source.parts[index].id);
    assert.equal(part.price, source.parts[index].price);
    assert.equal(part.unit, source.parts[index].unit);
    assert.equal(part.sourceUrl, source.parts[index].sourceUrl);
  }
  await access(assetFile(BRAND_LOGO_URL));
});

test('catalog and images resolve identically with or without the entry trailing slash', async () => {
  const catalog = normalizeCatalog(JSON.parse(await read(assetFile(CATALOG_URL))));
  for (const entry of ['https://customer.example/mvp4/pc-builder', 'https://customer.example/mvp4/pc-builder/', 'https://customer.example/mvp4/pc-builder/?preview=1']) {
    assert.equal(new URL(CATALOG_URL, entry).pathname, CATALOG_URL);
    for (const part of catalog.parts) assert.equal(new URL(part.image, entry).pathname, part.image);
  }
});

test('customer navigation and builder navigation have separate destinations', async () => {
  const server = await createServer({configFile: path.join(root, 'vite.config.mjs'), root, server: {middlewareMode: true}, appType: 'custom'});
  try {
    const {default: BrandHeader} = await server.ssrLoadModule('/src/BrandHeader.jsx');
    let returnedToBuilder = 0, openedTemporary = 0;
    const element = BrandHeader({onHome: () => returnedToBuilder++, onSaved: () => openedTemporary++});
    const markup = renderToStaticMarkup(element);
    assert.ok(!markup.includes('dev.popcornai.co.kr'));
    assert.match(markup, /href="\/mvp4\/" aria-label="팝콘AI 처음 화면"/);
    assert.match(markup, /href="\/mvp4\/support\.html"/);
    assert.match(markup, /임시 구성함/);
    const elements = [];
    const walk = value => {
      if (Array.isArray(value)) return value.forEach(walk);
      if (!value || typeof value !== 'object' || !value.props) return;
      elements.push(value); walk(value.props.children);
    };
    walk(element);
    const logo = elements.find(el => el.props.className === 'brand-logo-link');
    assert.equal(logo.props.onClick, undefined);
    const builder = elements.find(el => el.props.href === BUILDER_BASE && el.props['aria-current'] === 'page');
    let prevented = false;
    builder.props.onClick({preventDefault: () => {prevented = true;}});
    assert.equal(prevented, true); assert.equal(returnedToBuilder, 1);
    const temporary = elements.find(el => el.type === 'button' && el.props.onClick && el.props.className === 'brand-tool');
    temporary.props.onClick(); assert.equal(openedTemporary, 1);
  } finally { await server.close(); }
});

test('static output contains only the client package and preserves preview boundaries', async () => {
  const names = await readdir(output);
  assert.ok(!names.includes('server') && !names.includes('worker') && !names.includes('.openai'));
  const assets = await readdir(path.join(output, 'assets'));
  const script = (await Promise.all(assets.filter(name => name.endsWith('.js')).map(name => read(path.join(output, 'assets', name))))).join('\n');
  assert.ok(!script.includes('https://dev.popcornai.co.kr'));
  assert.ok(script.includes('구성 미리보기'));
  assert.ok(script.includes('새로고침하면 임시 구성이 사라져요.'));
  assert.ok(script.includes('실제 LLM 연결 전'));
  assert.ok(script.includes('실재고·주문 미연동'));
});
