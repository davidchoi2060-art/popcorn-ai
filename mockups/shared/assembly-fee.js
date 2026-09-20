// 조립공임 — 화면 쪽 단일 원천 (2026-09-20)
//
// 사장님 확정(2회):
//   ① "조립공임 이라고 생각하고 30000원으로 맞추면 됨"
//   ② "공임은 최종 장바구니에서 마지막에 추가하는 것으로"
// → 견적 엔진·격자·회귀의 총액 정의는 그대로 둔다(총액 = 부품 합).
//   화면은 그 옆에 「조립공임 30,000원 별도」를 «말하기만» 한다. 숫자를 더하지 않는다.
//   실제로 더해지는 자리는 장바구니/주문(S4 · api/orders.ASSEMBLY_FEE) 한 곳뿐이다.
//
// ⚠ 왜 이 파일이 있는가 — 같은 30,000 을 화면마다 적으면 언젠가 갈라진다
//   (CLAUDE.md §단일 원천). 값을 쓰는 화면은 **전부 여기서 읽는다**:
//     MVP1  s0-landing · main-landing · s1-session · s2-result · s3-detail · s4-cart
//     MVP2  mvp2/app.js (카드 · 내 견적 패널)
//   s4-cart.html 이 들고 있던 `var ASSEMBLY_FEE=30000;` 리터럴도 이 파일로 옮겼다.
//
// ⚠ 나중에 서버로 옮길 자리 (조사 결과 — 이번 작업 범위 밖, api/ 는 다른 담당)
//   서버에는 이미 값이 두 벌 있다:
//     api/orders.py:29   ASSEMBLY_FEE = 30000        (자체 결제 경로 — 실제로 더하는 곳)
//     api/handoff.py:48  ASSEMBLY_CODE = 92983       (몰 「제작 공임1」 — 금액은 몰이 정한다)
//   화면이 읽을 수 있는 고객단 엔드포인트는 아직 없다. 넣을 자리로는
//     GET /api/ops  (이미 s4-cart 가 부른다 — 필드 `assembly_fee` 한 칸 추가가 가장 싸다)
//   가 현실적이다. 그때 이 파일은 «서버 값이 오면 그것을 쓰고, 없으면 실패를 말한다»로
//   바뀌어야 한다 — 값을 두 벌 두는 상태로 남기지 않는다.
(function (root) {
  'use strict';

  var ASSEMBLY_FEE = 30000;              // 사장님 확정값. 이 저장소의 화면 쪽 유일한 선언.

  function won(n) { return Number(n).toLocaleString('ko-KR') + '원'; }

  // 문구는 CLAUDE.md §문서·화면 어휘 표준 — 평서·간결체, 명사형 항목명.
  var TEXT = {
    // 견적 금액 옆(짧은 자리): 총액에 포함되지 않았음을 먼저 말한다.
    short: function () { return '조립공임 ' + won(ASSEMBLY_FEE) + ' 별도'; },
    // 견적 금액 옆(한 줄 들어가는 자리): 어디서 더해지는지까지 말한다.
    quote: function () {
      return '부품 합계입니다. 조립공임 ' + won(ASSEMBLY_FEE) + '은 주문 단계에서 더해집니다.';
    },
    // 장바구니·주문 화면: 여기서는 실제로 더해진다.
    cart: function () {
      return '조립공임 ' + won(ASSEMBLY_FEE) + '이 총 결제금액에 포함되어 있습니다.';
    }
  };

  function noteText(kind) {
    var f = TEXT[kind] || TEXT.short;
    return f();
  }

  // 마크업에 숫자를 박지 않기 위한 자리 채우기.
  //   <p data-assembly-fee-note="quote"></p>  →  위 문구가 들어간다.
  // 이미 파싱된 요소를 즉시 채우고, DOM 이 더 붙을 수 있으므로 DOMContentLoaded 에서 한 번 더 돈다.
  function applyNotes(scope) {
    var doc = scope || (root.document);
    if (!doc || !doc.querySelectorAll) return 0;
    var els = doc.querySelectorAll('[data-assembly-fee-note]');
    Array.prototype.forEach.call(els, function (el) {
      el.textContent = noteText(el.getAttribute('data-assembly-fee-note'));
    });
    return els.length;
  }

  var api = {
    ASSEMBLY_FEE: ASSEMBLY_FEE,
    won: won,
    noteText: noteText,
    applyNotes: applyNotes
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.PopcornAssemblyFee = api;

  if (root.document) {
    applyNotes();
    root.document.addEventListener('DOMContentLoaded', function () { applyNotes(); });
  }
})(typeof window !== 'undefined' ? window : globalThis);
