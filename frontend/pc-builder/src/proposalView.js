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
export function applyRule(total, bud) {
  if (!bud || total <= bud) return {canApply: true, blockReason: null};
  return {canApply: false,
          blockReason: `이 구성은 전체 예산 ${won(bud)}보다 ${won(total - bud)} 많아 바로 적용할 수 없어요. 예산을 올리거나 부품을 바꾼 뒤 다시 채워 주세요.`};
}
