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
  };
}
