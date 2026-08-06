/* 관리자 좌측 메뉴의 **단일 원천** (2026-08-05).
 *
 * 왜 옮겼나: 메뉴 마크업이 **36화면에 각각 복제**돼 있었다(합계 672KB, 화면당 ~16KB).
 * 복제본은 이미 갈라져 있었다 — 항목 33개 중
 *   · `ai-cost.html`      → '운영 전환 설정'(ops-settings) 누락
 *   · `policy-weights.html` → '용도 하한'(usage-floors) 누락
 * 그 화면에서는 해당 페이지로 **갈 길이 아예 없었다.** 손으로 서른여섯 벌을 맞추는 한
 * 이런 누락은 계속 생긴다. 부품 어휘(슬라이스 A)·choices(H)·디자인 토큰에서 겪은 그 병이다.
 *
 * 여기만 고치면 전 화면이 함께 바뀐다. 항목을 늘릴 때도 이 파일 한 줄이다.
 *
 * ■ 숫자 배지를 담지 않는다
 *   원래 마크업에는 '상품 검수 9' 같은 숫자가 박혀 있었다. 실제 대기는 5,162였고,
 *   그래서 `admin-panel.js` 의 `clearDummyBadges()` 가 로드 때마다 지우고 있었다.
 *   정본에 담으면 **거짓을 원천에 새기는 것**이라 아예 뺐다. 실수치가 필요하면
 *   서버가 준 값으로 `admin-panel.js` 가 채운다.
 *   'NEW' 는 개수가 아니라 표시라서 남긴다.
 *
 * ■ 구조 (2026-08-05 사용자 결정 — 재정비)
 *   ① **구분선 제목을 없앴다.** 섹션 5개가 각각 그룹 하나만 담고 있어 제목이 두 번
 *      나왔다("가격 · 매입" 섹션 밑에 "가격 · 매입" 그룹, "추천 설정" 밑에 "추천 설정",
 *      "시스템" 밑에 "시스템"). 그룹을 최상위로 올리니 세로 공간이 줄고 이름이 한 번만 뜬다.
 *   ② **환불 · 클레임을 주문 그룹 맨 뒤로.** 예전 순서는 견적 → 주문 → **환불** →
 *      결제 → 배송 → 후기라 **이탈 흐름이 정상 흐름 한가운데** 있었다. 이제 생애주기대로
 *      놓고 이탈은 끝에 둔다(도매꾹은 아예 그룹부터 가른다 —
 *      `docs/research/domeggook-sc-2026-08-05.md`. 우리는 아직 클레임 화면이 하나뿐이라
 *      그룹을 따로 만들지 않았다. 취소·반품·교환이 갈라지면 그때가 분리할 때다).
 *
 * ■ 모양
 *   {href, icon, label}            단독 항목 (대시보드 · 회원 관리)
 *   {id, icon, label, items[]}     펼침 그룹 — id 는 collapse 대상이라 바꾸면 상태 기억이 끊긴다
 *   {section}                      구분선. **지금은 쓰지 않는다** — 렌더러는 계속 지원하므로
 *                                  나중에 그룹이 늘어 묶음이 필요해지면 그때 넣으면 된다.
 */
(function (w) {
  'use strict';

  w.POPCORN_ADMIN_MENU = [
    { href: 'index.html', icon: 'pie-chart', label: '대시보드' },

    { id: 'nv-prd', icon: 'box', label: '상품', items: [
      { href: 'products.html', icon: 'list', label: '상품 관리' },
      { href: 'categories.html', icon: 'folder', label: '카테고리 관리' },
      { href: 'category-mapping.html', icon: 'git-merge', label: '상품 매핑' },
      { href: 'review-queue.html', icon: 'check-circle', label: '상품 검수' },
      { href: 'csv-upload.html', icon: 'upload-cloud', label: '상품 일괄 등록' },
      { href: 'imports.html', icon: 'archive', label: '상품 원본 자료' },
      { href: 'spec-fields.html', icon: 'sliders', label: '사양 항목 정의' }
    ] },

    { id: 'nv-price', icon: 'dollar-sign', label: '가격 · 매입', items: [
      { href: 'suppliers.html', icon: 'truck', label: '공급처' },
      { href: 'price-review.html', icon: 'clock', label: '가격 검토 대기' },
      { href: 'margin-policy.html', icon: 'percent', label: '마진 정책' },
      { href: 'reprice.html', icon: 'refresh-cw', label: '판매가 재산정' },
      { href: 'price-import.html', icon: 'repeat', label: '단가표 반영' },
      { href: 'sourcing.html', icon: 'truck', label: '매입 견적(용산)' },
      { href: 'stock-inbound.html', icon: 'box', label: '재고 입고' },
      { href: 'price-history.html', icon: 'trending-up', label: '가격 이력' }
    ] },

    { id: 'nv-eng', icon: 'cpu', label: '추천 설정', items: [
      { href: 'compat-rules.html', icon: 'shield', label: '조립 호환 규칙 · 필수 사양' },
      { href: 'policy-weights.html', icon: 'sliders', label: '추천 기준 설정' },
      { href: 'usage-floors.html', icon: 'filter', label: '용도 하한' },
      { href: 'candidate-pool.html', icon: 'layers', label: '추천 가능 재고 현황' }
    ] },

    { id: 'nv-order', icon: 'file-text', label: '견적 · 주문', items: [
      { href: 'sessions.html', icon: 'message-square', label: '견적 상담 기록' },
      { href: 'orders.html', icon: 'send', label: '주문 관리' },
      { href: 'payments.html', icon: 'credit-card', label: '결제 · 정산' },
      { href: 'shipping.html', icon: 'truck', label: '배송 관리' },
      { href: 'reviews.html', icon: 'star', label: '후기 관리' },
      { href: 'swap-logs.html', icon: 'repeat', label: '부품 교체 · 클릭 기록' },
      // 이탈 흐름은 정상 흐름 끝에 둔다 — 예전엔 주문 바로 뒤라
      // 결제·배송보다 앞에 있었다
      { href: 'refunds.html', icon: 'corner-up-left', label: '환불 · 클레임' }
    ] },
    { href: 'customers.html', icon: 'users', label: '회원 관리' },

    { id: 'nv-sys', icon: 'settings', label: '시스템', items: [
      { href: 'ops-settings.html', icon: 'repeat', label: '운영 전환 설정', badge: 'NEW' },
      { href: 'ai-cost.html', icon: 'cpu', label: 'AI 사용량 · 비용' },
      { href: 'operators.html', icon: 'users', label: '운영자 · 권한' },
      { href: 'activity-logs.html', icon: 'file-text', label: '작업 기록' },
      { href: 'csv-jobs.html', icon: 'inbox', label: '일괄 등록 이력' }
    ] }
  ];
})(window);
