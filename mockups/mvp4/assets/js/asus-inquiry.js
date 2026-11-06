/* ASUS 기획전 문의 진입. 기존 AI 문의(ai-inquiry.js)와 접수 경로(service-adapters.js)를 고치지 않고 그대로 쓴다.
 * 이 파일이 하는 일: ① 기존 화면이 읽는 조회값을 선택한 모델에 맞게 채운다 ② 그려진 화면의 선택 안내를 ASUS 구성으로 바꾼다
 * ③ 문의 내용 입력칸에 선택한 구성을 미리 넣는다(고객이 고칠 수 있다). 전송은 하지 않으며 고객이 직접 제출할 때만 일어난다.
 * model이 없으면 3종 공통 문의, 알 수 없는 model이면 다시 선택하게 한다(다른 구성으로 조용히 넘기지 않는다).
 * 구성 값은 서버 응답(A.load)만 쓴다. 불러오지 못해도 문의는 그대로 받되, 사양을 지어내지 않고 그 사실을 안내에 적는다.
 * 접수 내용의 첫 줄은 기존 어댑터가 「[AI 패키지 견적 문의] ...」로 적는다. 그 표기를 바꾸려면 어댑터 수정이 필요해 이번 범위에서 제외했다. */
(function () {
  'use strict';
  var P = window.PAI, h = P.h, A = P.asus;
  var existing = P.pages['ai-consult'];
  var ART_ALT = 'ASUS 기획전 후보 케이스 연출 이미지';

  function photo(src, alt) {
    return '<figure class="az-iq-photo"><img src="' + h(A.image(src)) + '" alt="' + h(alt) + '" width="800" height="800"></figure>';
  }

  // data: 'loading' | 'ready' | 'failed'
  function cardHtml(key, m, data) {
    var fallback = photo('gt502-black-cutout.webp', ART_ALT);
    if (data === 'loading') {
      return fallback + '<div class="iq-package-body"><span class="eyebrow">ASUS 기획전</span><p data-az-load="loading">' + h(A.LOADING) + '</p></div>';
    }
    if (data === 'failed' || (key && !m)) {
      return fallback + '<div class="iq-package-body"><span class="eyebrow">ASUS 기획전</span><p data-az-load="error">구성 정보를 불러오지 못했습니다. 문의는 그대로 보내실 수 있습니다.</p></div>';
    }
    if (!m) {
      return fallback + '<div class="iq-package-body"><span class="eyebrow">ASUS 기획전</span><h2>ASUS PC 3종</h2><ul class="az-iq-specs">' +
        A.MODELS.map(function (x) { return '<li><a href="' + h(A.detailHref(x.id)) + '">' + h(x.name) + '</a></li>'; }).join('') +
        '</ul><p class="az-iq-plan"><small>' + h(A.PLAN_NOTE) + ' ' + h(A.BUILD_NOTE) + '</small></p></div>';
    }
    return photo(m.heroImage, m.heroAlt) +
      '<div class="iq-package-body"><span class="eyebrow">선택한 ASUS 구성</span><h2>' + h(m.name) + '</h2><p>' + h(m.tagline) + '</p>' +
      '<ul class="az-iq-specs"><li>그래픽카드 ' + h(m.gpu) + '</li><li>CPU ' + h(m.cpu) + '</li><li>메모리 ' + h(m.ram) + '</li><li>SSD ' + h(m.ssd) + '</li></ul>' +
      '<p class="az-iq-plan">' + h(A.PLAN_LABEL) + ' ' + h(A.planText(m)) + '<br><small>' + h(A.PLAN_NOTE) + ' ' + h(A.BUILD_NOTE) + '</small></p>' +
      '<a class="text-link" href="' + h(A.detailHref(m.id)) + '">구성 자세히 보기 ' + P.icon('arrow-right') + '</a></div>';
  }

  function decorate(key, m, data) {
    var root = document.getElementById('iq-root');
    if (!root) return;
    var crumb = root.querySelector('.breadcrumb');
    if (crumb) {
      var links = crumb.querySelectorAll('a');
      if (links[1]) { links[1].textContent = 'ASUS 기획전'; links[1].setAttribute('href', 'asus.html'); }
    }
    var eyebrow = root.querySelector('.iq-intro .eyebrow');
    if (eyebrow) eyebrow.textContent = 'ASUS 기획전 · ' + (m ? m.name + ' · ' : '') + 'PC 구성 문의';
    var box = root.querySelector('.iq-aside .iq-package');
    if (box && box.dataset.asus !== data) {
      box.dataset.asus = data;
      box.innerHTML = cardHtml(key, m, data);
    }
  }

  function prefillText(key, m) {
    var what = m ? m.name + ' 구성 문의 (' + m.gpu + ' / ' + m.cpu + ' / ' + m.ram + ' / ' + m.ssd + ')'
      : key ? '선택 구성(' + key + ') 문의' : 'PC 구성 문의';
    return '[ASUS 기획전] ' + what + '\n사용할 프로그램과 하려는 일: ';
  }

  P.pages['ai-consult'] = function () {
    var key = P.qs.get('model');
    if (key && !A.known(key)) {
      return { html: '<div class="az-page"><section class="az-missing az-wrap"><h1>PC를 다시 선택해 주세요.</h1><p>선택한 구성을 찾을 수 없습니다.</p><a class="az-btn az-btn-solid" href="asus.html">ASUS 기획전 보기' + P.icon('arrow-right') + '</a></section></div>', mount: function () { document.title = 'PC 구성 문의 | ASUS 기획전 | 팝콘AI'; } };
    }
    var meta = key ? A.META[key] : null;
    document.body.classList.add('az-consult');
    P.qs.set('package', meta ? meta.inquiry.package : 'business');
    P.qs.set('use', meta ? meta.inquiry.use : 'unsure');
    P.qs.set('intent', 'quote');
    P.qs.set('pc', 'new');
    var view = existing();
    var mount = view.mount;
    view.mount = function () {
      mount();
      var root = document.getElementById('iq-root');
      var data = 'loading';
      var m = null;
      var filled = '';   // 이 파일이 넣은 문구. 고객이 고쳤으면 다시 덮지 않는다.
      function refresh() {
        decorate(key, m, data);
        var area = root.querySelector('textarea[name=request]');
        if (area && data !== 'loading' && (!area.value || area.value === filled)) {
          var next = prefillText(key, m);
          if (area.value !== next) {
            filled = next;
            area.value = next;
            area.dispatchEvent(new Event('input', { bubbles: true }));
          }
        }
        document.title = (m ? m.name + ' ' : '') + 'PC 구성 문의 | ASUS 기획전 | 팝콘AI';
      }
      refresh();
      // 기존 화면은 단계가 바뀔 때 root.innerHTML을 다시 그린다. 직계 자식 변경만 본다(꾸미기가 다시 부르지 않게).
      new MutationObserver(refresh).observe(root, { childList: true });
      A.load().then(function () { m = key ? A.find(key) : null; data = 'ready'; refresh(); }, function () { data = 'failed'; refresh(); });
    };
    return view;
  };
}());
