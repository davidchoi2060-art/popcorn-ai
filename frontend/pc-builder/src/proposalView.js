// 채우기 제안 창 — 지금 보고 있는 탭(구성)에 맞는 설명·금액만 고른다(2026-10-25 E2E-02).
// AI 글(요약·자리별 이유·제약·예산 안내)은 AI 가 고른 구성에만 붙는다. 다른 탭으로 바꾸면 AI 글은 숨기고,
// 그 탭의 금액 문장은 서버 값(그 구성의 부품 합계 · 전체 예산)으로만 만든다.
const won = n => `${Number(n || 0).toLocaleString('ko-KR')}원`;

export function optionView(proposal, optionId) {
  const pr = proposal.proposal;
  const opt = pr.options.find(o => o.id === optionId) || pr.options[0];
  const isAi = proposal.ai?.status === 'ok' && opt.id === pr.chosen;
  const bud = proposal.budgetTotal;
  const budgetLine = !bud ? null : opt.total <= bud
    ? `이 구성의 부품 합계 ${won(opt.total)} · 전체 예산 ${won(bud)}에서 ${won(bud - opt.total)} 남아요.`
    : `이 구성의 부품 합계 ${won(opt.total)} · 전체 예산 ${won(bud)}보다 ${won(opt.total - bud)} 많아요.`;
  return {
    opt, isAi,
    summary: isAi ? pr.summary || null : null,
    slotReasons: isAi ? pr.slotReasons || {} : {},
    constraints: isAi ? pr.constraints || [] : [],
    budgetAdvice: isAi ? pr.budgetAdvice || null : null,
    budgetLine,
    over: bud && opt.total > bud ? opt.total - bud : null,
    ...applyRule(opt.total, bud),
  };
}

// 적용 가능 여부 -- 예산은 고객이 정한 상한이다(2026-10-25 E2E-04). 예산을 넘는 구성은 비교·대안으로만 보여 주고,
// 예산을 직접 올리거나 부품을 바꾼 뒤 다시 채워 적용한다. 버튼과 적용 처리 함수가 같은 판정을 쓴다.
// 적용 직전 판단 -- 서버 견적(quote)은 예산을 모르는 조회라 서버가 초과를 막아 주지 않는다(Codex 원인 확인).
// 순서: ① 다시 계산한 합계가 예산을 넘으면 가격 변경 재확인 여부와 관계없이 차단 ② 가격 표식이 바뀌었고 아직 재확인 전이면 재확인 ③ 적용.
export function applyDecision({quoteTotal, quotePriceKey, optionPriceKey, budget, confirmed}) {
  const rule = applyRule(quoteTotal, budget);
  if (!rule.canApply) return {action: 'block', reason: rule.blockReason};
  if (!confirmed && quotePriceKey !== optionPriceKey) return {action: 'confirm', reason: null};
  return {action: 'apply', reason: null};
}

export function applyRule(total, bud) {
  if (!bud || total <= bud) return {canApply: true, blockReason: null};
  return {canApply: false,
          blockReason: `이 구성은 전체 예산 ${won(bud)}보다 ${won(total - bud)} 많아 바로 적용할 수 없어요. 예산을 올리거나 부품을 바꾼 뒤 다시 채워 주세요.`};
}
