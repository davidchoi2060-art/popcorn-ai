/* 하단 채팅을 '운영 도우미'로 바꾼다 (슬라이스 64).
 *
 * 원래는 Phoenix 템플릿의 고객지원 데모였다 — "Eric"이라는 담당자가
 * "I can't reorder a product I previously ordered" 같은 쇼핑몰 고객 문의에 답하는
 * 영문 위젯이었다. 우리 관리자 화면에서 운영자가 볼 물건이 아니다.
 *
 * 바꾸는 용도: **운영 중 모르는 것을 물어보는 자리.**
 * "이 상품이 왜 추천에 안 나오죠?" 같은 질문에 답하게 된다.
 *
 * **지금은 답하지 않는다.** LLM 연동은 아직 보류 결정 상태다(별도 승인 필요).
 * 그래서 지어낸 답을 보여주지 않고 "아직 답할 수 없다"고 말한다 —
 * 화면이 할 수 없는 일을 할 수 있는 척하면, 그게 곧 거짓말이 된다.
 * 대신 지금 당장 쓸모 있는 것은 준다: 자주 묻는 것에 대한 **화면 바로가기**.
 */
(function () {
  var KEY = 'popcorn-admin-helper';   // 나눈 이야기(로컬 보관 — 서버로 보내지 않는다)
  var MAX = 30;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[<>&"]/g, function (c) {
      return { '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c];
    });
  }

  /* 운영자가 실제로 막히는 지점들. 답은 '어디로 가면 되는지'까지 준다 —
     이 프로젝트에서 반복된 질문이 "어느 화면에서 확인하죠?"였다. */
  var FAQ = [
    { q: '이 상품이 왜 추천에 안 나오죠?',
      a: '추천에 들어가려면 네 가지를 모두 통과해야 합니다 — 필수 사양이 채워졌고, '
        + '검수가 끝났고, 판매가가 있고, 재고가 남아 있어야 합니다. '
        + '하나라도 비면 후보에서 빠집니다.',
      go: [['상품 검수', 'review-queue.html'], ['후보 풀 현황', 'candidate-pool.html']] },
    { q: '검수 대기가 뭔가요?',
      a: '사양이 비어 있어 추천에 쓸 수 없는 상품입니다. 값을 채우면 그 자리에서 '
        + '게이트를 다시 판정합니다. 전체보다 <b>판매중·재고 있는 것</b>부터 보시면 됩니다.',
      go: [['상품 검수', 'review-queue.html']] },
    { q: '판매가는 어떻게 정해지나요?',
      a: '매입가에 마진 정책을 적용해 산정합니다. 단가표를 반영하면 해당 상품의 '
        + '판매가가 다시 계산되고, 변동이 크면 검토 대기로 올라옵니다.',
      go: [['마진 정책', 'margin-policy.html'], ['가격 검토', 'price-review.html'],
           ['단가표 반영', 'price-import.html']] },
    { q: '재고는 어디서 넣나요?',
      a: '재고 입고 화면에서 넣습니다. 재고가 0이거나 안전재고보다 적은 상품이 '
        + '목록에 올라옵니다.',
      go: [['재고 입고', 'stock-inbound.html']] },
    { q: '잘못 고쳤어요. 되돌릴 수 있나요?',
      a: '작업 기록에서 되돌릴 수 있습니다. 값만 되돌리는 게 아니라 잠금과 게이트 상태까지 '
        + '함께 되돌립니다. 다만 <b>일괄 적재는 되돌릴 수 없습니다</b>.',
      go: [['작업 기록', 'activity-logs.html']] }
  ];

  function log() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || '[]'); } catch (e) { return []; }
  }
  function push(row) {
    var l = log(); l.push(row);
    try { sessionStorage.setItem(KEY, JSON.stringify(l.slice(-MAX))); } catch (e) {}
  }

  function bubble(who, html) {
    var mine = who === 'me';
    return '<div class="d-flex ' + (mine ? 'justify-content-end' : '') + ' mb-2">'
      + '<div class="p-2 px-3 rounded-3 ' + (mine ? 'bg-primary text-white' : 'bg-body-secondary')
      + '" style="max-width:82%;font-size:12.5px;line-height:1.6;">' + html + '</div></div>';
  }

  function chips(list) {
    return '<div class="d-flex flex-wrap gap-1 mt-2">' + list.map(function (g) {
      return '<a href="' + g[1] + '" class="badge badge-phoenix badge-phoenix-primary '
        + 'text-decoration-none">' + esc(g[0]) + ' →</a>';
    }).join('') + '</div>';
  }

  function boot() {
    // 채팅을 여는 플로팅 버튼 라벨("Chat demo"). 컨테이너 밖에 있어 함께 안 바뀐다.
    [].forEach.call(document.querySelectorAll('.btn-support-chat .btn-text'), function (e) {
      e.textContent = '운영 도우미';
    });

    var wrap = document.querySelector('.support-chat-container');
    if (!wrap) return;
    var card = wrap.querySelector('.card') || wrap;

    // ── 머리말 ─────────────────────────────────────────────
    var head = card.querySelector('.card-header');
    if (head) {
      var badge = head.querySelector('.badge');
      if (badge) badge.textContent = '준비 중';
      [].forEach.call(head.querySelectorAll('h5, .fs-9, .fw-bold'), function (e) {
        if (/demo widget|chat demo|support/i.test(e.textContent || '')) {
          e.textContent = '운영 도우미';
        }
      });
    }
    // 점 세 개 메뉴 — 우리가 하지 않는 기능("Report to Admin" 등)은 지운다
    var menu = card.querySelector('.dropdown-menu');
    if (menu) {
      menu.innerHTML = '<a class="dropdown-item" href="#!" data-helper="clear">나눈 이야기 지우기</a>'
        + '<a class="dropdown-item btn-support-chat" href="#!">닫기</a>';
    }

    // ── 본문 ───────────────────────────────────────────────
    var body = card.querySelector('.card-body.chat') || card.querySelector('.card-body');
    if (!body) return;
    var scroll = document.createElement('div');
    scroll.className = 'p-3';
    scroll.style.cssText = 'max-height:22rem;overflow-y:auto;';
    body.innerHTML = '';
    body.appendChild(scroll);

    function say(who, html, save) {
      scroll.insertAdjacentHTML('beforeend', bubble(who, html));
      scroll.scrollTop = scroll.scrollHeight;
      if (save) push([who, html]);
    }

    function intro() {
      say('bot', '운영 중 막히는 게 있으면 물어보세요. '
        + '<b>아직 자동 답변은 준비 중</b>이라, 지금은 자주 묻는 것에 대한 '
        + '바로가기를 드립니다.');
      scroll.insertAdjacentHTML('beforeend',
        '<div class="mb-2">' + FAQ.map(function (f, i) {
          return '<button class="btn btn-sm btn-phoenix-secondary d-block w-100 text-start mb-1 '
            + 'fs-10" data-faq="' + i + '">' + esc(f.q) + '</button>';
        }).join('') + '</div>');
      scroll.scrollTop = scroll.scrollHeight;
    }

    var old = log();
    if (old.length) {
      old.forEach(function (r) { say(r[0], r[1]); });
    } else {
      intro();
    }

    scroll.addEventListener('click', function (e) {
      var b = e.target.closest('[data-faq]');
      if (!b) return;
      var f = FAQ[+b.getAttribute('data-faq')];
      say('me', esc(f.q), true);
      say('bot', f.a + (f.go ? chips(f.go) : ''), true);
    });

    // ── 입력 ───────────────────────────────────────────────
    var input = card.querySelector('.card-footer input[type="text"]');
    if (input) {
      input.placeholder = '궁금한 것을 입력하세요';
      var send = function () {
        var v = (input.value || '').trim();
        if (!v) return;
        input.value = '';
        say('me', esc(v), true);
        /* 지어낸 답을 하지 않는다. 할 수 있는 것과 없는 것을 그대로 말한다. */
        var hit = FAQ.filter(function (f) {
          return f.q.replace(/[?\s]/g, '').indexOf(v.replace(/[?\s]/g, '')) >= 0
            || v.length > 1 && f.q.indexOf(v) >= 0;
        })[0];
        if (hit) {
          say('bot', hit.a + chips(hit.go), true);
        } else {
          say('bot', '아직 자유 질문에는 답할 수 없습니다 — 답변 기능은 준비 중입니다. '
            + '아래 항목 중에 찾으시는 게 있는지 봐 주세요.' + chips(FAQ.map(function (f) {
              return [f.q.slice(0, 14), (f.go && f.go[0] && f.go[0][1]) || '#'];
            })), true);
        }
      };
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); send(); }
      });
      var btn = card.querySelector('.card-footer button[type="submit"], .card-footer .btn-send');
      if (btn) btn.addEventListener('click', function (e) { e.preventDefault(); send(); });
      // 사진·파일 첨부는 지금 받을 곳이 없다 — 누르면 아무 일도 안 일어나느니 감춘다
      [].forEach.call(card.querySelectorAll('.card-footer label, .card-footer .btn-icon'),
        function (e) {
          if (e.querySelector('input[type="file"]') || /paperclip|image/i.test(e.innerHTML)) {
            e.style.display = 'none';
          }
        });
    }

    document.addEventListener('click', function (e) {
      var c = e.target.closest('[data-helper="clear"]');
      if (!c) return;
      e.preventDefault();
      try { sessionStorage.removeItem(KEY); } catch (err) {}
      scroll.innerHTML = '';
      intro();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
