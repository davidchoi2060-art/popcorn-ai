// 자유 입력 카드 — 주 버튼 문구, 채우기 요청 모양, 「마지막으로 고객이 바꾼 조건」 표식.
// 입력창 글은 지우지 않는다. 글을 쓴 뒤 예산 칸·용도 버튼을 바꾸면 그때의 글을 표식(pin)으로 함께 보내고,
// 서버는 지금 글이 말하는 금액·용도가 표식의 글과 같으면 나중에 바꾼 칸 값을 따른다(글의 금액을 고쳐 쓰면 글이 이긴다).
export const INTENT_MAX = 300;

export function intentCta(count) {
  if (count >= 8) return '유지한 부품 빼고 다시 제안';
  return count > 0 ? '선택한 부품 유지하고 추천받기' : '이 내용으로 PC 추천받기';
}

// answer: 서버 확인 질문에 고른 답. 입력창 원문(text)과 합치지 않고 따로 보낸다(용도·고객 요청은 원문, 예산은 답).
export function fillRequest({selection, locked, mode, purpose, budgetTotal, text, answer = null, pins = {}}) {
  return {selection, locked, mode, purpose, budgetTotal, requestText: text || null, answer: answer || null,
          budgetPin: pins.budget ?? null, purposePin: pins.purpose ?? null};
}

// 응답 뒤 표식 정리 — 글이 이긴 조건은 칸이 글 값으로 바뀌었으니 표식을 지운다.
// 확인 답으로 예산이 정해졌으면(budgetFrom 'answer') 그때의 입력창 글을 그 값에 묶어, 같은 글을 다시 보내도 답한 값이 유지되게 한다.
export function pinsAfter(r, pins, {text = ''} = {}) {
  const next = {...pins};
  if (r.budgetFrom === 'text') next.budget = null;
  else if (r.budgetFrom === 'answer') next.budget = text;
  if (r.purposeFrom === 'text') next.purpose = null;
  return next;
}

// 응답을 받기 전에 구성이나 입력(글·예산·용도)이 바뀌었으면 그 응답은 이전 조건의 것이다 -- 화면 값·표식·제안을 덮지 않는다.
// 바뀐 값은 그대로 두고 다시 요청할 수 있다(입력은 기다리는 동안에도 막지 않는다).
export function staleFill({sentKey, nowKey, sentRev, nowRev}) {
  if (sentKey !== nowKey) return '요청한 뒤 구성이 바뀌어 이 제안은 적용하지 않았어요. 현재 구성으로 다시 채워보세요.';
  if (sentRev !== nowRev) return '요청한 뒤 적어 주신 글이나 예산·용도가 바뀌어 이 응답은 반영하지 않았어요. 바뀐 조건으로 다시 추천받아 주세요.';
  return null;
}
