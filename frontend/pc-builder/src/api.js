// 서버 PC 구성 API(/api/pc-builder/*) — 같은 호스트 경로만 쓴다. 키·비밀값은 화면에 두지 않는다.
// 후보·가격·호환·예산 계산은 서버가 하고, AI 추천도 서버가 고른 후보 안에서만 돌아온다.
export const API_BASE = '/api/pc-builder/';
export const CATEGORY_ORDER = ['cpu', 'board', 'memory', 'gpu', 'storage', 'cooler', 'case', 'power'];
const TIMEOUT_MS = {pool: 15000, quote: 15000, advise: 50000, fill: 55000};

export class ApiError extends Error {
  constructor(kind, message, status = 0, body = null) {
    super(message);
    this.kind = kind;          // 'timeout' | 'network' | 'rate' | 'selection' | 'server'
    this.status = status;
    this.body = body;
  }
}

function detailText(body, fallback) {
  const d = body && body.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d.detail === 'string') return d.detail;
  return fallback;
}

export async function request(path, body, {signal} = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort('timeout'), TIMEOUT_MS[path] || 30000);
  const relay = () => ctrl.abort('cancel');
  if (signal) { if (signal.aborted) relay(); else signal.addEventListener('abort', relay, {once: true}); }
  let res;
  try {
    res = await fetch(API_BASE + path, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Accept': 'application/json', 'X-Popcorn-Surface': 'mvp4', ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
      body: body === undefined ? undefined : JSON.stringify(body), signal: ctrl.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    if (signal?.aborted) throw new ApiError('cancel', '요청을 취소했어요.');
    if (ctrl.signal.aborted) throw new ApiError('timeout', 'AI 응답이 늦어지고 있어요. 잠시 뒤 다시 시도해 주세요.');
    throw new ApiError('network', '서버에 연결하지 못했어요. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.');
  }
  clearTimeout(timer);
  const data = await res.json().catch(() => null);
  if (res.status === 429) throw new ApiError('rate', detailText(data, 'AI 상담 요청이 잠깐 몰렸어요. 잠시 뒤 다시 시도해 주세요.'), 429, data);
  if (res.status === 409 && data && data.error === 'selection') throw new ApiError('selection', data.detail, 409, data);
  if (!res.ok || !data || data.ok !== true) throw new ApiError('server', detailText(data, '서버가 요청을 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.'), res.status, data);
  return data;
}

export const getPool = opts => request('pool', undefined, opts);
export const quote = (body, opts) => request('quote', body, opts);
export const advise = (body, opts) => request('advise', body, opts);
export const fill = (body, opts) => request('fill', body, opts);

// 서버 pc_builder_data.selection_key 와 같은 모양 — 늦게 온 응답이 다른 구성에 적용되지 않게 비교한다.
export function selectionKey(selection) {
  return CATEGORY_ORDER.filter(c => selection[c]).map(c => `${c}:${selection[c]}`).join('|');
}

export function budgetValue(value) {
  const n = Number(value);
  return Number.isFinite(n) && String(value).trim() !== '' ? Math.trunc(n) : null;
}

// 서버가 다시 확인한 판매가·판매 가능 여부를 조사 카탈로그에 덮는다. 서버 응답이 없으면 조사 가격을 그대로 둔다.
// 서버 견적(quote)에 나온 부품만 그 판매가로 맞춘다. 견적은 고른 부품 줄만 오므로 나머지 부품은 그대로 둔다
// (일부 줄로 mergePool 처럼 전체 목록을 덮으면 고르지 않은 부품이 「서버 확인 목록에 없음」이 된다).
export function applyQuotePrices(catalog, lines) {
  if (!catalog || !Array.isArray(lines) || !lines.length) return catalog;
  const by = Object.fromEntries(lines.filter(l => l && Number.isSafeInteger(l.price) && l.price > 0).map(l => [String(l.id), l]));
  let changed = false;
  const parts = catalog.parts.map(p => {
    const l = by[p.id];
    if (!l || l.price === p.price) return p;
    changed = true;
    return {...p, price: l.price, updatedAt: l.updatedAt ?? p.updatedAt};
  });
  return changed ? {...catalog, parts} : catalog;
}

export function mergePool(catalog, pool) {
  if (!pool) return catalog;
  const byId = Object.fromEntries((pool.parts || []).map(p => [p.id, p]));
  return {
    ...catalog,
    server: {loadedAt: pool.loadedAt, priceNote: pool.priceNote, stockNote: pool.stockNote},
    parts: catalog.parts.map(part => {
      const s = byId[part.id];
      if (!s) return {...part, usable: false, excluded: '서버 확인 목록에 없음', snapshotPrice: part.price};
      return {...part, snapshotPrice: part.price, price: s.price ?? part.price, usable: !!s.usable, excluded: s.excluded,
              updatedAt: s.updatedAt, serverFacts: s.facts};
    }),
  };
}
