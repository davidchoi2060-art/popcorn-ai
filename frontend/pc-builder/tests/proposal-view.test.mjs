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
