/* /mvp4 «설치 가능 AI 예시» — 대표 선택 2안(2026-10-20 「상품 목록에는 LLM 로고랑 모델·버전을 붙이고, 상세는 활용 예시가 쉽게 보이게」).
 *
 * - 근거: Ollama 공개 시험(https://ollama.com/blog/nvidia-spark-performance) — NVIDIA GB10(DGX Spark, 128GB)에서
 *   gpt-oss 20B·120B, Llama 3.1 8B, Qwen3 32B 를 실행했다. 그래서 GB10 장비에만 모델 예시를 붙인다(공급 제품별 실측 아님).
 *   다른 장비에는 모델 이름 없이 활용 예시만 보여 주고, 맞는 모델은 전문상담사가 함께 맞춘다.
 * - Ollama 는 모델이 아니라 실행 도구로 따로 적는다.
 * - 로고: assets/icons/llm/*.svg (출처는 같은 폴더 provenance.json). gpt-oss 로고는 OpenAI 마크 약관 동의 전이라 글자로만 적는다.
 * - 설치 완료·사전 설치·공식 인증·제휴·속도/정확도 보장 문구를 만들지 않는다. 질문→답변은 «예시»로 밝힌다.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P || P.llmExamples) return;
  var h = P.h, icon = P.icon, LOGO = 'assets/icons/llm/';
  var MODELS = {
    llama: { name: 'Llama 3.1', size: '8B', maker: 'Meta', logo: 'meta.svg' },
    qwen: { name: 'Qwen3', size: '32B', maker: 'Alibaba Cloud', logo: 'qwen.svg' },
    oss20: { name: 'gpt-oss', size: '20B', maker: 'OpenAI', logo: null },
    oss120: { name: 'gpt-oss', size: '120B', maker: 'OpenAI', logo: null }
  };
  // 상세 «활용 예시» — 시안 순서(빠른 일상 · 문서·개발 · 대형 모델), 처음 선택은 가운데(문서·개발).
  var USES = [
    { key: 'daily', model: 'llama', title: '빠른 일상 작업', tasks: '메일 초안 · 짧은 요약 · 메모 정리',
      text: '작은 모델이라 가볍게 쓰기 좋아요. 짧은 글을 요약하거나 메일·메모 초안을 만들 때 활용할 수 있어요.',
      ask: '이 회의 메모로 고객 안내 메일 초안 써줘', file: '회의_메모.txt',
      answer: ['안내 메일 초안을 정리합니다.', ['다음 주 화요일 설치 일정을 안내드립니다.', '설치 전 준비하실 자료를 함께 보내드립니다.', '변경이 필요하시면 회신 부탁드립니다.']], next: null },
    { key: 'docs', model: 'qwen', title: '문서·개발 작업', tasks: '보고서 정리 · 글쓰기 · 코드 초안',
      text: '다양한 문서와 코드를 이해하고, 아이디어를 정리하거나 초안을 작성하는 데 활용할 수 있는 모델입니다.',
      ask: '이 보고서의 핵심을 정리해줘', file: '분기_사업_보고서.pdf',
      answer: ['핵심 요약과 다음 할 일을 정리합니다.', ['이번 분기 매출은 전 분기 대비 증가했습니다.', '주요 성장 요인은 A 제품군의 판매 확대입니다.', '다음 분기에는 B 시장 진출을 우선 검토하는 것이 좋겠습니다.']],
      next: ['B 시장 관련 추가 리서치 진행', 'A 제품군 마케팅 전략안 초안 작성'] },
    { key: 'large', model: 'oss120', title: '대형 모델 활용', tasks: '긴 문서 분석 · 단계별 검토 · 코드 검토',
      text: '큰 모델이라 긴 자료를 읽고 여러 단계로 따져 보는 일에 활용할 수 있어요. 더 많은 메모리를 씁니다.',
      ask: '이 계약서 초안에서 확인할 조항을 정리해줘', file: '계약서_초안.docx',
      answer: ['확인이 필요한 조항을 정리합니다.', ['납품 기한과 지연 시 조치 조항을 확인하세요.', '유지보수 범위와 기간이 명확한지 살펴보세요.', '자료 보관·파기 기준을 함께 확인하세요.']], next: null }
  ];
  var DEFAULT_USE = 'docs';
  // GB10 가속기(이름에서 읽은 값 포함) 또는 DGX Spark 기반 장비만 모델 예시 대상.
  function eligible(p) { return !!p && /\bGB10\b/i.test([p.accelerator, p.name, p.officialName].join(' ')) || (!!p && /DGX\s*Spark/i.test(String(p.name))); }
  function mark(m, size) {
    var x = MODELS[m];
    return x.logo ? '<img class="llm-logo" src="' + LOGO + x.logo + '" alt="" width="' + size + '" height="' + size + '">' : '<span class="llm-logo llm-logo-text" aria-hidden="true">oss</span>';
  }
  // 상품 카드: 사양 아래 «설치 가능 AI 예시» + 모델·버전(읽을 수 있는 글자) + 실행 도구 Ollama.
  function badges(p) {
    if (!eligible(p)) return '';
    return '<div class="llm-badges"><div class="llm-badges-models"><p class="llm-badges-title">설치 가능 AI 예시</p><ul>' + ['qwen', 'oss20', 'llama'].map(function (k) {
      var m = MODELS[k];
      return '<li title="' + h(m.maker + ' ' + m.name + ' ' + m.size) + '">' + mark(k, 26) + '<span>' + h(m.name) + '<b>' + h(m.size) + '</b></span></li>';
    }).join('') + '</ul></div><div class="llm-badges-tool"><p class="llm-badges-title">실행 도구</p><span><img class="llm-logo" src="' + LOGO + 'ollama.svg" alt="" width="26" height="26">Ollama</span></div></div>';
  }
  function panel(u, withModel) {
    var m = MODELS[u.model];
    return '<div class="llm-use-panel" role="tabpanel" id="llm-panel-' + u.key + '" aria-labelledby="llm-tab-' + u.key + '"' + (u.key === DEFAULT_USE ? '' : ' hidden') + '>' +
      '<div class="llm-use-about">' + (withModel ? '<div class="llm-use-name">' + mark(u.model, 56) + '<div><strong>' + h(m.name + ' ' + m.size) + '</strong><span>' + h(u.tasks) + '</span></div></div>' : '<div class="llm-use-name"><div><strong>' + h(u.title) + '</strong><span>' + h(u.tasks) + '</span></div></div>') +
      '<p>' + h(u.text) + '</p></div>' +
      '<div class="llm-use-demo"><div class="llm-ask"><small>질문 예시</small><p>' + h(u.ask) + '</p><span class="llm-file">' + icon('file-text') + h(u.file) + '</span></div>' +
      '<span class="llm-arrow" aria-hidden="true">' + icon('arrow-right') + '</span>' +
      '<div class="llm-answer"><small>AI의 답변 예시</small><strong>' + h(u.answer[0]) + '</strong><ul>' + u.answer[1].map(function (t) { return '<li>' + h(t) + '</li>'; }).join('') + '</ul>' +
      (u.next ? '<strong class="llm-next">다음 할 일</strong><ol>' + u.next.map(function (t) { return '<li>' + h(t) + '</li>'; }).join('') + '</ol>' : '') + '</div></div></div>';
  }
  // 상세 «활용 예시» 구획(예전 YOUR AI, ON YOUR DESK 자리). consultHref = 기존 AI 설치 상담 주소(바꾸지 않는다).
  function section(p, consultHref) {
    var withModel = eligible(p);
    return '<section class="sc-section llm-uses" id="sc-usecases" aria-labelledby="llm-uses-title"><div class="llm-uses-heading"><span class="sc-eyebrow">' + (withModel ? '설치 가능 AI 예시' : 'AI 활용 예시') + '</span>' +
      '<h2 id="llm-uses-title">작은 AI부터 큰 모델까지, <em>내 장비에서.</em></h2><p class="llm-uses-sub">어떤 모델이 맞을지 몰라도 괜찮아요.</p><p class="llm-uses-copy">' + (withModel ? '용도별 모델 예시를 눌러 어떤 일에 쓰는지 살펴보세요.' : '용도를 눌러 어떤 일에 쓰는지 살펴보세요. 이 장비에 맞는 모델은 전문상담사가 함께 확인해 드려요.') + '</p></div>' +
      '<div class="llm-use-tabs" role="tablist" aria-label="' + (withModel ? '모델 예시 고르기' : '활용 예시 고르기') + '">' + USES.map(function (u) {
        var on = u.key === DEFAULT_USE, m = MODELS[u.model];
        return '<button type="button" role="tab" id="llm-tab-' + u.key + '" aria-controls="llm-panel-' + u.key + '" aria-selected="' + on + '" tabindex="' + (on ? '0' : '-1') + '" data-llm-use="' + u.key + '">' + (withModel ? mark(u.model, 40) : '') + '<span><strong>' + h(u.title) + '</strong>' + (withModel ? '<small>' + h(m.name + ' ' + m.size) + '</small>' : '<small>' + h(u.tasks) + '</small>') + '</span></button>';
      }).join('') + '</div>' + USES.map(function (u) { return panel(u, withModel); }).join('') +
      '<p class="llm-uses-note">예시 화면이에요. 실제 답변과 응답 속도, 필요한 설정은 모델과 사용 환경에 따라 달라요.</p>' +
      '<div class="llm-consult">' + icon('chat-circle') + '<div><strong>모델과 설치 구성은 전문상담사가 함께 맞춰드립니다.</strong><p>어떤 모델이 적합할지, 내 환경에서 어떻게 사용할지 상담을 통해 안내해드려요.</p></div><a class="btn btn-primary" data-sc-action="adoption" href="' + h(consultHref) + '">내 업무로 상담하기 ' + icon('arrow-right') + '</a></div></section>';
  }
  // 탭: 누르기·방향키·Home/End (WAI-ARIA tabs). 보던 탭은 다시 그려도 지킨다.
  var current = DEFAULT_USE;
  function bind(root) {
    var tabs = [].slice.call((root || document).querySelectorAll('[data-llm-use]'));
    if (!tabs.length) return;
    function select(key, focus) {
      current = key;
      tabs.forEach(function (t) {
        var on = t.dataset.llmUse === key;
        t.setAttribute('aria-selected', on); t.tabIndex = on ? 0 : -1;
        var pane = document.getElementById(t.getAttribute('aria-controls')); if (pane) pane.hidden = !on;
        if (on && focus) t.focus();
      });
    }
    tabs.forEach(function (t, i) {
      t.addEventListener('click', function () { select(t.dataset.llmUse); });
      t.addEventListener('keydown', function (e) {
        var n = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
        if (n === undefined) return;
        e.preventDefault(); select(tabs[(n + tabs.length) % tabs.length].dataset.llmUse, true);
      });
    });
    select(current);
  }
  P.llmExamples = { eligible: eligible, badges: badges, section: section, bind: bind, models: MODELS, uses: USES };
}());
