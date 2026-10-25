// 자유 입력 카드 회귀 — 주 버튼 문구, 채우기 요청 모양(원문·확인 답·표식), 응답 뒤 표식, 늦게 온 응답 무시.
import assert from 'node:assert/strict';
import test from 'node:test';
import {INTENT_MAX, fillRequest, intentCta, pinsAfter, staleFill} from '../src/intent.js';

test('주 버튼 문구는 빈 구성·일부 선택·완성 구성에 따라 다르고 PC·모바일이 같은 함수를 쓴다', () => {
  assert.equal(intentCta(0), '이 내용으로 PC 추천받기');
  assert.equal(intentCta(3), '선택한 부품 유지하고 추천받기');
  assert.equal(intentCta(7), '선택한 부품 유지하고 추천받기');
  assert.equal(intentCta(8), '유지한 부품 빼고 다시 제안');
  assert.equal(INTENT_MAX, 300);
});

test('채우기 요청은 원문을 그대로, 확인 답과 표식은 따로 싣는다', () => {
  const text = '프리미어로 영상 편집해요.\n본체 100만원';
  const body = fillRequest({selection: {cpu: '1'}, locked: {cpu: true}, mode: 'fill', purpose: 'gaming', budgetTotal: 2000000, text, pins: {budget: text, purpose: null}});
  assert.deepEqual(body, {selection: {cpu: '1'}, locked: {cpu: true}, mode: 'fill', purpose: 'gaming', budgetTotal: 2000000,
    requestText: text, answer: null, budgetPin: text, purposePin: null});
  // 글 없이도 보낼 수 있다(자유 입력은 필수가 아니다)
  assert.equal(fillRequest({text: '', pins: {}}).requestText, null);
  // 확인 답은 원문과 합치지 않는다
  const a = fillRequest({text: '영상 편집용, 전체80', answer: '전체 80만원 이하', pins: {}});
  assert.equal(a.requestText, '영상 편집용, 전체80');
  assert.equal(a.answer, '전체 80만원 이하');
});

test('글 예산 → 제안 닫고 예산 칸 올림 → 재추천: 칸을 바꾸면 표식이 서고, 글이 이기면 표식이 풀린다', () => {
  const text = '본체 100만원, 게임용';
  let pins = {budget: null, purpose: null};
  // ① 첫 추천: 글의 금액이 쓰였다 -> 표식 없음
  pins = pinsAfter({budgetFrom: 'text', purposeFrom: 'text'}, pins, {text});
  assert.deepEqual(pins, {budget: null, purpose: null});
  // ② 예산 칸을 2,000,000 으로 바꿈(App: setPins(s=>({...s,budget:aiText})))
  pins = {...pins, budget: text};
  assert.equal(fillRequest({text, budgetTotal: 2000000, pins}).budgetPin, text);
  // ③ 서버가 칸 값을 따름 -> 표식 유지(다음 재추천에도 같은 글이면 칸 값)
  pins = pinsAfter({budgetFrom: 'field', purposeFrom: 'text'}, pins, {text});
  assert.equal(pins.budget, text);
  // ④ 글의 금액을 고쳐 써서 서버가 글을 따름 -> 표식 해제
  pins = pinsAfter({budgetFrom: 'text', purposeFrom: 'field'}, pins, {text: '본체 150만원, 게임용'});
  assert.equal(pins.budget, null);
});

test('확인 답으로 정해진 예산은 그때의 원문에 묶여, 같은 원문을 다시 보내도 다시 묻지 않는다', () => {
  const pins = pinsAfter({budgetFrom: 'answer', purposeFrom: 'text'}, {budget: null, purpose: 'x'}, {text: '영상 편집용, 전체80'});
  assert.deepEqual(pins, {budget: '영상 편집용, 전체80', purpose: null});
});

test('응답을 기다리는 동안 글·예산·용도나 구성이 바뀌면 늦은 응답은 반영하지 않는다', () => {
  // Codex 재현: 필드 200만원 / 「PC 전체 100만원 게임용」 제출 -> 대기 중 필드 300만원(입력 revision 1 -> 2) -> 늦은 응답 100만원
  assert.match(staleFill({sentKey: 'cpu:1', nowKey: 'cpu:1', sentRev: 1, nowRev: 2}), /바뀐 조건으로 다시 추천받아/);
  assert.match(staleFill({sentKey: 'cpu:1', nowKey: 'cpu:2', sentRev: 1, nowRev: 1}), /구성이 바뀌어/);
  assert.equal(staleFill({sentKey: 'cpu:1', nowKey: 'cpu:1', sentRev: 3, nowRev: 3}), null);
});
