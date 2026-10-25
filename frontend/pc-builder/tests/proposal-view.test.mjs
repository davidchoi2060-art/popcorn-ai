// E2E-02 회귀 — 채우기 제안 탭 3개를 오갈 때 설명·금액이 보고 있는 구성에 맞는가.
import assert from 'node:assert/strict';
import test from 'node:test';
import {optionView} from '../src/proposalView.js';

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

// E2E-04 회귀 — 예산(고객이 정한 상한)을 넘는 구성은 비교로만 보이고 적용은 막힌다. 버튼과 적용 처리가 같은 판정(applyRule)을 쓴다.
test('예산을 넘는 탭은 적용할 수 없고, 예산 안 탭과 예산이 없을 때는 적용할 수 있다', async () => {
  const {applyRule} = await import('../src/proposalView.js');
  const low = {...proposal, budgetTotal: 100000};
  for (const id of ['opt1', 'opt2', 'opt3']) {
    const v = optionView(low, id);
    assert.equal(v.canApply, false, id);
    assert.ok(v.blockReason.includes('100,000원') && v.blockReason.includes('예산을 올리거나 부품을 바꾼 뒤'), id);
  }
  assert.equal(optionView(low, 'opt1').blockReason, '이 구성은 전체 예산 100,000원보다 1,656,600원 많아 바로 적용할 수 없어요. 예산을 올리거나 부품을 바꾼 뒤 다시 채워 주세요.');
  assert.equal(optionView(proposal, 'opt1').canApply, true);           // 2,000,000원 예산 안
  assert.equal(optionView(proposal, 'opt2').canApply, false);          // 2,036,500원은 예산 초과
  assert.equal(optionView({...proposal, budgetTotal: null}, 'opt2').canApply, true);
  // 적용 직전 다시 계산한 가격이 예산을 넘으면 막는다(처리 함수 쪽)
  assert.equal(applyRule(2000001, 2000000).canApply, false);
  assert.equal(applyRule(2000000, 2000000).canApply, true);
});

test('예산을 올린 뒤 다시 받은 제안은 적용할 수 있다(390 회복 흐름)', () => {
  const raised = {...proposal, budgetTotal: 1500000, proposal: {...proposal.proposal, options: [
    {id: 'opt1', kind: 'min', total: 1491200, within: true, changed: [], selection: {}}]}};
  assert.equal(optionView(raised, 'opt1').canApply, true);
});

test('적용 직전 다시 계산한 합계가 예산을 넘으면 가격 변경 재확인 여부와 관계없이 차단한다', async () => {
  const {applyDecision} = await import('../src/proposalView.js');
  const base = {budget: 1500000, optionPriceKey: 'k1'};
  // 가격이 올라 예산을 넘음 -- 재확인 전·후 모두 차단(확인 버튼을 눌러도 적용되지 않음)
  for (const confirmed of [false, true]) {
    const d = applyDecision({...base, quoteTotal: 1500100, quotePriceKey: 'k2', confirmed});
    assert.equal(d.action, 'block', String(confirmed));
    assert.ok(d.reason.includes('1,500,000원') && d.reason.includes('100원'));
  }
  // 가격 표식은 같아도 합계가 예산 밖이면 차단
  assert.equal(applyDecision({...base, quoteTotal: 1756600, quotePriceKey: 'k1', confirmed: false}).action, 'block');
  // 예산 안: 가격이 바뀌었으면 먼저 재확인, 재확인 뒤 적용
  assert.equal(applyDecision({...base, quoteTotal: 1491200, quotePriceKey: 'k2', confirmed: false}).action, 'confirm');
  assert.equal(applyDecision({...base, quoteTotal: 1491200, quotePriceKey: 'k2', confirmed: true}).action, 'apply');
  // 150만원 / 1,491,200원 정상 적용(390 회복 흐름)
  assert.equal(applyDecision({...base, quoteTotal: 1491200, quotePriceKey: 'k1', confirmed: false}).action, 'apply');
  // 예산 없음: 예산 판정 없이 가격 표식만 본다
  assert.equal(applyDecision({quoteTotal: 9999999, quotePriceKey: 'k1', optionPriceKey: 'k1', budget: null, confirmed: false}).action, 'apply');
});
