// E2E-02 회귀 — 채우기 제안 탭 3개를 오갈 때 설명·금액이 보고 있는 구성에 맞는가.
import assert from 'node:assert/strict';
import test from 'node:test';
import {applyDecision, budgetStatus, optionView, quoteProblem} from '../src/proposalView.js';

const proposal = {
  budgetTotal: 2000000,
  ai: {status: 'ok'},
  proposal: {
    chosen: 'opt3',
    summary: '1TB 저장공간과 700W 파워로 여유를 둔 구성이에요.',
    slotReasons: {storage: '1TB 로 넉넉해요.', power: '700W 로 여유가 있어요.'},
    constraints: ['케이스 장착 공간은 구매 전 확인이 필요해요.'],
    budgetAdvice: '예산 안에서 저장공간을 늘린 구성이에요.',
    options: [
      {id: 'opt1', kind: 'min', total: 1756600, within: true, changed: ['storage', 'power'], selection: {storage: '128462', power: '128870'}},
      {id: 'opt2', kind: 'preset', total: 2036500, within: false, changed: ['storage'], selection: {storage: '126198', power: '128870'}},
      {id: 'opt3', kind: 'upgrade', total: 1997000, within: true, changed: ['storage', 'power'], selection: {storage: '126198', power: '120917'}},
    ],
  },
};

test('AI 가 고른 탭에만 AI 설명이 붙고, 다른 탭으로 바꾸면 사라진다', () => {
  const chosen = optionView(proposal, 'opt3');
  assert.equal(chosen.isAi, true);
  assert.equal(chosen.summary, proposal.proposal.summary);
  assert.deepEqual(chosen.slotReasons, proposal.proposal.slotReasons);
  assert.equal(chosen.constraints.length, 1);
  assert.equal(chosen.budgetAdvice, proposal.proposal.budgetAdvice);
  for (const id of ['opt1', 'opt2']) {
    const v = optionView(proposal, id);
    assert.equal(v.isAi, false, id);
    assert.equal(v.summary, null, id);
    assert.deepEqual(v.slotReasons, {}, id);
    assert.deepEqual(v.constraints, [], id);
    assert.equal(v.budgetAdvice, null, id);
  }
});

test('탭마다 금액 문장은 그 구성의 서버 합계로 만든다', () => {
  assert.equal(optionView(proposal, 'opt1').budgetLine, '이 구성의 부품 합계 1,756,600원 · 전체 예산 2,000,000원에서 243,400원 남아요.');
  assert.equal(optionView(proposal, 'opt2').budgetLine, '이 구성의 부품 합계 2,036,500원 · 전체 예산 2,000,000원보다 36,500원 많아요.');
  assert.equal(optionView(proposal, 'opt2').over, 36500);
  assert.equal(optionView(proposal, 'opt3').budgetLine, '이 구성의 부품 합계 1,997,000원 · 전체 예산 2,000,000원에서 3,000원 남아요.');
  // opt3 → opt1 → opt2 → opt3 순서로 바꿔도 매번 그 구성 값만
  for (const [id, total] of [['opt3', 1997000], ['opt1', 1756600], ['opt2', 2036500], ['opt3', 1997000]]) {
    const v = optionView(proposal, id);
    assert.equal(v.opt.total, total);
    assert.ok(v.budgetLine.includes(total.toLocaleString('ko-KR')));
    if (id !== 'opt3') assert.ok(!JSON.stringify(v).includes('1TB 저장공간'), id);
  }
});

test('AI 설명이 없거나 예산이 없으면 AI 글·예산 문장을 붙이지 않는다', () => {
  const failed = {...proposal, ai: {status: 'unavailable'}};
  for (const id of ['opt1', 'opt2', 'opt3']) assert.equal(optionView(failed, id).summary, null);
  assert.equal(optionView({...proposal, budgetTotal: null}, 'opt1').budgetLine, null);
});

// 예산 초과 선택(2026-10-25 대표님 정정 「예산초과라도 사용자가 선택할 수 있어야지」) — 예산은 추천·경고 기준이다.
// 예전 E2E-04 의 「초과는 적용 불가」 검사는 이 정책으로 바뀌었다. 초과 구성은 금액·초과액을 보여 주고 고객이 명시 선택하면 적용한다.
// 실제 서버 quote 모양(lines 8줄 · 줄 가격 합 = total · priceKey · compat)
const okQuote = (total, priceKey) => ({total, priceKey, count: 8, compat: {state: 'ok', checks: []},
  lines: Array.from({length: 8}, (_, i) => ({category: 'c' + i, price: i < 7 ? 1000 : total - 7000}))});
const withKeys = p => ({...p, proposal: {...p.proposal, options: p.proposal.options.map(o => ({...o, priceKey: 'k-' + o.id}))}});
const seenOf = v => ({priceKey: v.priceKey, total: v.total});

test('예산 안 구성은 기존처럼 「이 구성 적용하기」로 적용한다', () => {
  const v = optionView(withKeys(proposal), 'opt1');
  assert.equal(v.over, null);
  assert.equal(v.overNote, null);
  assert.equal(v.applyLabel, '이 구성 적용하기');
  assert.deepEqual(applyDecision({seen: seenOf(v), quote: okQuote(1756600, 'k-opt1')}), {action: 'apply', reason: null});
});

test('예산 초과 구성은 금액·초과액을 보여 주고 「초과 금액으로 적용」으로 명시 선택하면 적용한다(예산은 그대로)', () => {
  const low = withKeys({...proposal, budgetTotal: 100000});
  for (const id of ['opt1', 'opt2', 'opt3']) {
    const v = optionView(low, id);
    assert.equal(v.applyLabel, '초과 금액으로 적용', id);
    assert.equal(v.over, v.total - 100000, id);
    assert.ok(v.overNote.includes('예산 칸은 100,000원 그대로') && v.overNote.includes(`초과 금액 ${(v.total - 100000).toLocaleString('ko-KR')}원`), id);
    assert.equal(v.budgetLine, `이 구성의 부품 합계 ${v.total.toLocaleString('ko-KR')}원 · 전체 예산 100,000원보다 ${(v.total - 100000).toLocaleString('ko-KR')}원 많아요.`);
    // 고객이 본 금액과 재조회 금액이 같으면 예산을 넘어도 적용한다 -- 적용 판단은 예산을 받지 않는다
    assert.equal(applyDecision({seen: seenOf(v), quote: okQuote(v.total, 'k-' + id)}).action, 'apply', id);
  }
  // 적용 뒤 요약: 원래 예산 100,000원 기준 초과액을 계속 보여 준다
  assert.deepEqual(budgetStatus(1141800, 100000), {over: 1041800, text: '예산 100,000원보다 1,041,800원 많아요'});
  assert.deepEqual(budgetStatus(1971500, 2000000), {over: null, text: '예산 2,000,000원에서 28,500원 남았어요'});
  assert.equal(budgetStatus(1971500, 0).text, '전체 예산을 정하지 않았어요');
  // 비교 탭의 더 비싼 구성(2,036,500원, 예산 2,000,000원 초과)도 명시 선택 가능
  const v2 = optionView(withKeys(proposal), 'opt2');
  assert.equal(v2.applyLabel, '초과 금액으로 적용');
  assert.equal(v2.over, 36500);
  assert.equal(applyDecision({seen: seenOf(v2), quote: okQuote(2036500, 'k-opt2')}).action, 'apply');
});

test('예산 안이던 구성이 재조회로 예산을 넘으면 새 금액·초과액으로 다시 고르게 하고, 그 금액 그대로면 적용한다', () => {
  const p = withKeys(proposal);
  const v = optionView(p, 'opt1');                                      // 1,756,600원 · 예산 2,000,000원 안
  const q = okQuote(2000100, 'k2');
  assert.equal(applyDecision({seen: seenOf(v), quote: q}).action, 'confirm');
  const re = {...p, priceChanged: {option: 'opt1', priceKey: 'k2', total: 2000100}};
  const v2 = optionView(re, 'opt1');
  assert.equal(v2.repriced, true);
  assert.equal(v2.total, 2000100);
  assert.equal(v2.over, 100);
  assert.equal(v2.applyLabel, '바뀐 가격·초과 금액으로 적용');
  assert.equal(v2.budgetLine, '이 구성의 부품 합계 2,000,100원 · 전체 예산 2,000,000원보다 100원 많아요.');
  assert.equal(applyDecision({seen: seenOf(v2), quote: okQuote(2000100, 'k2')}).action, 'apply');
  // 다시 계산해도 예산 안이면 「바뀐 가격으로 적용」
  assert.equal(optionView({...p, priceChanged: {option: 'opt1', priceKey: 'k2', total: 1760000}}, 'opt1').applyLabel, '바뀐 가격으로 적용');
});

test('다시 확인한 뒤 가격이 또 바뀌면 또 확인받는다(확인은 그때 본 표식·합계에만 묶인다)', () => {
  const p = withKeys(proposal);
  const v2 = optionView({...p, priceChanged: {option: 'opt1', priceKey: 'k2', total: 2000100}}, 'opt1');
  assert.equal(applyDecision({seen: seenOf(v2), quote: okQuote(2000300, 'k3')}).action, 'confirm');   // 또 바뀜
  assert.equal(applyDecision({seen: seenOf(v2), quote: okQuote(2000300, 'k2')}).action, 'confirm');   // 표식은 같아도 합계가 다름
  assert.equal(applyDecision({seen: seenOf(v2), quote: okQuote(2000100, 'k9')}).action, 'confirm');   // 합계는 같아도 표식이 다름
  const v3 = optionView({...p, priceChanged: {option: 'opt1', priceKey: 'k3', total: 2000300}}, 'opt1');
  assert.equal(applyDecision({seen: seenOf(v3), quote: okQuote(2000300, 'k3')}).action, 'apply');
});

test('비교 탭을 바꾸면 다른 탭의 재계산 금액을 쓰지 않는다', () => {
  const p = withKeys({...proposal, priceChanged: {option: 'opt1', priceKey: 'k2', total: 2000100}});
  const other = optionView(p, 'opt3');
  assert.equal(other.repriced, false);
  assert.equal(other.total, 1997000);
  assert.equal(other.priceKey, 'k-opt3');
  assert.equal(other.applyLabel, '이 구성 적용하기');
  assert.equal(applyDecision({seen: seenOf(other), quote: okQuote(1997000, 'k-opt3')}).action, 'apply');
});

test('비예산 실패(호환 불가·판정 미완료·8개 미만·가격 미확정)는 예산 안이어도 막는다', () => {
  const seen = {priceKey: 'k1', total: 1500000};
  const base = okQuote(1500000, 'k1');
  const cases = [
    [{...base, compat: {state: 'fail', checks: ['CPU 소켓 규격 일치']}}, '호환 판정이 맞지 않아'],
    [{...base, compat: {state: 'unknown', checks: []}}, '호환 판정을 끝내지 못해'],
    [{...base, count: 7, lines: [...base.lines.slice(0, 6), {category: 'c6', price: base.lines[6].price + base.lines[7].price}], compat: {state: 'incomplete', checks: []}}, '8개가 모두'],
    [{...base, lines: [...base.lines.slice(0, 7), {category: 'power', price: null}]}, '가격이 확인되지 않은'],
    [{...base, lines: [...base.lines.slice(0, 7), {category: 'power', price: 1.5}]}, '가격이 확인되지 않은'],
    [{...base, total: base.total + 1}, '가격이 확인되지 않은'],                       // 줄 합 ≠ 합계
    [{...base, total: null}, '가격을 확인하지 못해'],
    [{...base, total: Infinity}, '가격을 확인하지 못해'],
    [{...base, total: 2 ** 60}, '가격을 확인하지 못해'],
    [{...base, total: '1500000'}, '가격을 확인하지 못해'],
    [{...base, priceKey: ''}, '가격을 확인하지 못해'],
    [{...base, priceKey: undefined}, '가격을 확인하지 못해'],
    [{...base, lines: undefined}, '가격을 확인하지 못해'],
  ];
  for (const [q, words] of cases) {
    const d = applyDecision({seen, quote: q});
    assert.equal(d.action, 'block', words);
    assert.ok(d.reason.includes(words), d.reason);
  }
  assert.ok(quoteProblem(cases[0][0]).includes('CPU 소켓 규격 일치'));
  assert.equal(quoteProblem(base), null);
});

// 가격 표시 일치(Codex 정적 검토) — 제안 창 행·합계·초과액이 같은 서버 견적을, 적용 뒤 슬롯도 확인한 견적 가격을 쓴다.
test('제안 창 행 가격은 옵션 가격, 다시 계산했으면 그 견적의 줄 가격을 쓴다(행 합 = 합계)', () => {
  const prices = {cpu: 300000, board: 150000, memory: 70000, gpu: 800700, storage: 120000, cooler: 20000, case: 45000, power: 250900};
  const p = {...proposal, proposal: {...proposal.proposal, options: proposal.proposal.options.map(o => o.id === 'opt1' ? {...o, prices} : o)}};
  const v = optionView(p, 'opt1');
  assert.deepEqual(v.prices, prices);
  assert.equal(Object.values(v.prices).reduce((s, n) => s + n, 0), v.total);
  const reprices = {...prices, gpu: 800800};
  const r = optionView({...p, priceChanged: {option: 'opt1', priceKey: 'k2', total: 1756700, prices: reprices}}, 'opt1');
  assert.deepEqual(r.prices, reprices);
  assert.equal(Object.values(r.prices).reduce((s, n) => s + n, 0), r.total);
  assert.equal(optionView(p, 'opt2').prices, null);                    // 서버가 가격을 안 준 옵션은 화면 목록 가격(호출하는 쪽 기본값)
});

test('견적 가격은 그 줄의 부품만 바꾸고 나머지 부품·판매 상태는 그대로 둔다', async () => {
  const {applyQuotePrices} = await import('../src/api.js');
  const catalog = {asOf: '2026-10-23', parts: [
    {id: '113800', price: 174100, usable: true}, {id: '128424', price: 800700, usable: true}, {id: '999', price: 50000, usable: false, excluded: '검수 대기'}]};
  const out = applyQuotePrices(catalog, [{id: '128424', category: 'gpu', price: 800800, updatedAt: '2026-10-25T22:00+09:00'}]);
  assert.deepEqual(out.parts[1], {id: '128424', price: 800800, usable: true, updatedAt: '2026-10-25T22:00+09:00'});
  assert.equal(out.parts[0], catalog.parts[0]);                         // 견적에 없는 부품은 그대로(같은 객체)
  assert.equal(out.parts[2], catalog.parts[2]);
  assert.equal(applyQuotePrices(catalog, [{id: '113800', price: 174100}]), catalog);   // 바뀐 값이 없으면 그대로
  assert.equal(applyQuotePrices(catalog, [{id: '113800', price: null}, {id: '128424', price: 1.5}]), catalog);   // 잘못된 가격은 쓰지 않음
  assert.equal(applyQuotePrices(catalog, []), catalog);
});
