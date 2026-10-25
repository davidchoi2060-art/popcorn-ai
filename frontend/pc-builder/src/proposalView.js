// 채우기 제안 창 — 지금 보고 있는 탭(구성)에 맞는 설명·금액만 고른다(2026-10-25 E2E-02).
// AI 글(요약·자리별 이유·제약·예산 안내)은 AI 가 고른 구성에만 붙는다. 다른 탭으로 바꾸면 AI 글은 숨기고,
// 그 탭의 금액 문장은 서버 값(그 구성의 부품 합계 · 전체 예산)으로만 만든다.
// 예산은 추천·경고 기준이다(2026-10-25 대표님 정정 「예산초과라도 사용자가 선택할 수 있어야지」). 예산을 넘는 구성도
// 고객이 「초과 금액으로 적용」을 눌러 직접 고르면 적용한다. 예산 칸은 그대로 두고 초과 금액을 계속 보여 준다.
const won = n => `${Number(n || 0).toLocaleString('ko-KR')}원`;

export function optionView(proposal, optionId) {
  const pr = proposal.proposal;
  const opt = pr.options.find(o => o.id === optionId) || pr.options[0];
  const isAi = proposal.ai?.status === 'ok' && opt.id === pr.chosen;
  const bud = proposal.budgetTotal;
  // 적용 직전 서버가 다시 계산한 견적이 이 탭의 것이면 그 값이 고객이 보는 금액이다(버튼·예산 문구·합계·적용 판단이 같은 값을 본다).
  const repriced = proposal.priceChanged && proposal.priceChanged.option === opt.id ? proposal.priceChanged : null;
  const total = repriced ? repriced.total : opt.total;
  const priceKey = repriced ? repriced.priceKey : opt.priceKey;
  // 행에 쓰는 부품별 가격(자리 → 원): 다시 계산했으면 그 견적의 줄, 아니면 제안 때 서버가 준 옵션 가격 -- 행 합 = 합계
  const prices = repriced ? repriced.prices || null : opt.prices || null;
  const over = bud && total > bud ? total - bud : null;
  const budgetLine = !bud ? null : total <= bud
    ? `이 구성의 부품 합계 ${won(total)} · 전체 예산 ${won(bud)}에서 ${won(bud - total)} 남아요.`
    : `이 구성의 부품 합계 ${won(total)} · 전체 예산 ${won(bud)}보다 ${won(total - bud)} 많아요.`;
  return {
    opt, isAi, total, priceKey, prices, repriced: !!repriced, over,
    summary: isAi ? pr.summary || null : null,
    slotReasons: isAi ? pr.slotReasons || {} : {},
    constraints: isAi ? pr.constraints || [] : [],
    budgetAdvice: isAi ? pr.budgetAdvice || null : null,
    budgetLine,
    overNote: over ? `「초과 금액으로 적용」을 누르면 이 구성으로 바꾸고, 예산 칸은 ${won(bud)} 그대로 두어 초과 금액 ${won(over)}을 요약에서 계속 보여 드려요.` : null,
    applyLabel: over ? (repriced ? '바뀐 가격·초과 금액으로 적용' : '초과 금액으로 적용') : (repriced ? '바뀐 가격으로 적용' : '이 구성 적용하기'),
  };
}

// 적용 직전 판단 -- 서버가 다시 계산한 견적(quote)으로 정한다. 예산은 판단에 쓰지 않는다(경고 기준).
// ① 비예산 제약(호환 불가·판정 미완료·8개 미만·가격 불명)은 막는다. quote 는 호환 실패도 결과로 돌려주므로 여기서 본다.
// ② 고객이 본 금액(seen: 그 탭의 가격 표식·합계)과 견적이 다르면 새 금액을 보여 주고 다시 고르게 한다.
//    확인은 그때 본 표식·합계에만 묶인다 -- 다시 확인한 뒤 가격이 또 바뀌면 또 확인받는다.
// ③ 같으면 적용한다(예산을 넘어도 고객이 그 금액을 보고 고른 것이다).
export function applyDecision({seen, quote}) {
  const problem = quoteProblem(quote);
  if (problem) return {action: 'block', reason: problem};
  if (quote.priceKey !== seen.priceKey || quote.total !== seen.total) return {action: 'confirm', reason: null};
  return {action: 'apply', reason: null};
}

const safeWon = n => Number.isSafeInteger(n) && n > 0;

export function quoteProblem(q) {
  // 가격 미확정: 합계·가격 표식·부품 줄이 없거나, 줄 가격이 양의 정수가 아니거나, 줄 합이 합계와 다르면 적용하지 않는다
  const lines = Array.isArray(q?.lines) ? q.lines : null;
  if (!q || !safeWon(q.total) || typeof q.priceKey !== 'string' || !q.priceKey || !lines) return '가격을 확인하지 못해 적용하지 않았어요. 잠시 뒤 다시 시도해 주세요.';
  if (lines.some(l => !safeWon(l?.price)) || lines.reduce((s, l) => s + l.price, 0) !== q.total) return '가격이 확인되지 않은 부품이 있어 적용하지 않았어요. 다시 채워 주세요.';
  if (q.count !== 8 || lines.length !== 8) return '부품 8개가 모두 확인되지 않아 적용하지 않았어요. 다시 채워 주세요.';
  const c = q.compat || {};
  if (c.state === 'fail') return `서버 호환 판정이 맞지 않아 적용하지 않았어요${c.checks?.length ? `(${c.checks.join(' · ')})` : ''}. 다시 채워 주세요.`;
  if (c.state !== 'ok') return '서버 호환 판정을 끝내지 못해 적용하지 않았어요. 다시 채워 주세요.';
  return null;
}

// 요약·최종 구성에서 보이는 예산 문장 -- 초과 구성을 적용해도 예산과 초과 금액을 계속 보여 준다.
export function budgetStatus(total, budget) {
  if (!(budget > 0)) return {over: null, text: '전체 예산을 정하지 않았어요'};
  if (total <= budget) return {over: null, text: `예산 ${won(budget)}에서 ${won(budget - total)} 남았어요`};
  return {over: total - budget, text: `예산 ${won(budget)}보다 ${won(total - budget)} 많아요`};
}
