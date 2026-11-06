/* ASUS AI PC 기획전 화면 데이터 어댑터 (2026-11-06, DB 원천 전환).
 *
 * 모델 값(이름·문구·이미지·부품·기획 검토가)은 코드에 없다. GET /api/customer/asus-campaign 으로만 받는다.
 * 실패하면 실패라고 말한다. 대신 보여 줄 옛 값이 이 파일에 없다.
 *
 * 이 파일에 남은 것 = 저장으로 바꾸면 안 되는 고정값.
 *   공통 고지(합계 없음·호환·배송·연출 사진), 기획 검토가 표기, 모델별 색조와 문의 항목 매핑(기존 접수 경로용).
 * plan = 기획 검토가(ASUS 협의 전). 판매가·소비자가 합계가 아니므로 부품 가격과 더하지 않는다. null 은 미정이고 0원이 아니다.
 *
 * 내부 검토 상태와 비고는 관리자·API 원본에 그대로 두고, 고객 화면에는 내보내지 않는다(2026-11-06 사용자 지시).
 * 자료가 어긋난 옵션(state=conflict)과 이름 자체가 내부 안내인 옵션은 표시하지 않는다. 값을 확정처럼 고쳐 쓰지 않는다.
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  var API = '/api/customer/asus-campaign';
  var TIMEOUT_MS = 15000;
  var IMAGE = /^[a-z0-9-]+\.webp$/;

  var THUMB = /^(assets\/images\/parts\/mall-\d+\.webp|assets\/images\/parts\/asus-official-[a-z0-9-]+\.webp|assets\/images\/asus\/gt502-black-cutout\.webp|https:\/\/www\.popcornpc\.co\.kr\/data\/pimg\/\d+\/\d+_600\.jpg)$/;
  var INTERNAL = /공급\s*재?확인|확인\s*필요|확인\s*전|확인하지\s*못|확정\s*불가|미확정|미확인|불일치|서로\s*다릅니다|선정하지\s*않|비교\s*후보/;
  var NEUTRAL = '상담 시 안내';

  // 알려진 3개 모델의 화면 고정값. 값이 아니라 색조와 기존 문의 항목 연결이다.
  var META = {
    business: { tone: 'blue', inquiry: { package: 'business', use: 'documents' } },
    video: { tone: 'violet', inquiry: { package: 'advanced', use: 'image' } },
    'local-ai': { tone: 'teal', inquiry: { package: 'advanced', use: 'code' } }
  };

  function isText(v) { return typeof v === 'string' && v.trim() !== ''; }
  function text(v) { if (!isText(v)) throw new Error('shape'); return v; }
  function optional(v) { return isText(v) ? v : null; }
  function money(v) { return typeof v === 'number' && isFinite(v) && v > 0 ? v : null; }
  function image(v) { if (typeof v !== 'string' || !IMAGE.test(v)) throw new Error('image'); return v; }
  function list(v) { if (!Array.isArray(v)) throw new Error('shape'); return v; }
  function part(parts, label) {
    for (var i = 0; i < parts.length; i += 1) if (parts[i].label === label) return parts[i];
    throw new Error('part');
  }

  // 고객에게 보이는 문구에서 내부 검토 표현을 뺀다. 문장 단위로 지우고, 「후보」라는 말만 남은 곳은 그 말을 지운다.
  function clean(v) {
    if (!isText(v)) return '';
    return v.split(/(?<=[.!?])\s+/).filter(function (s) { return !INTERNAL.test(s); }).join(' ')
      .replace(/\s*후보/g, '').replace(/\s+/g, ' ').trim();
  }
  function shown(v) { return clean(text(v)) || NEUTRAL; }

  // 고객 구성 표 한 줄. 가격·상태·비고는 싣지 않는다.
  function customerOption(o) {
    if (text(o.state) === 'conflict' || INTERNAL.test(text(o.name)) || /미정/.test(o.name)) return null;
    return { name: clean(o.name), image: typeof o.image === 'string' && THUMB.test(o.image) ? o.image : null };
  }

  function normalize(x) {
    var meta = META[x.id];
    if (!meta) throw new Error('model');
    var parts = list(x.parts).map(function (p) {
      return { label: text(p.label), head: shown(p.head), options: list(p.options).map(customerOption).filter(Boolean) };
    });
    var box = part(parts, '케이스'), cooler = part(parts, 'CPU 쿨러');
    return {
      id: x.id, tone: meta.tone, inquiry: meta.inquiry, name: shown(x.name), tagline: shown(x.tagline),
      plan: money(x.plan_review_price), heroImage: image(x.hero_image), heroAlt: clean(text(x.hero_alt)) || 'ASUS 케이스 연출 이미지',
      gpu: shown(x.gpu), vram: shown(x.vram), cpu: shown(x.cpu), ram: shown(x.ram), ssd: shown(x.ssd),
      forWho: list(x.for_who).map(function (w) { return shown(w.text); }),
      whoIcons: list(x.for_who).map(function (w) { return text(w.icon); }),
      uses: list(x.uses).map(function (u) {
        return { title: shown(u.title), text: shown(u.text), example: clean(optional(u.example)) || null, steps: list(u.steps).map(shown), image: image(u.image), alt: clean(text(u.alt)) };
      }),
      prepare: clean(optional(x.prepare)) || null, explain: clean(optional(x.explain)) || null, limit: clean(optional(x.limit)) || null,
      parts: parts, caseName: box.head, coolerName: cooler.head
    };
  }

  var pending = null;

  // 전체 3종을 한 번에 받는다. 받은 값만 A.MODELS 에 넣고, 실패·형식 오류는 그대로 던져 화면이 실패로 그리게 한다.
  function load(force) {
    if (pending && !force) return pending;
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, TIMEOUT_MS);
    A.MODELS = [];
    var mine = pending = fetch(API, { method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json', 'X-Popcorn-Surface': 'mvp4' }, signal: ctrl.signal })
      .then(function (r) {
        return r.json().catch(function () { return null; }).then(function (d) {
          if (!r.ok || !d || d.ok !== true) throw new Error('http ' + r.status);
          return d;
        });
      })
      .then(function (d) {
        var models = list(d.models).map(normalize);
        // 다시 시도가 겹쳤을 때 늦게 온 이전 응답이 새 값을 덮지 않게 한다.
        if (mine === pending) { A.MODELS = models; A.UNAVAILABLE = Array.isArray(d.unavailable) ? d.unavailable : []; }
        return models;
      })
      .then(function (models) { clearTimeout(timer); return models; }, function (e) {
        clearTimeout(timer);
        if (mine === pending) pending = null;
        throw e;
      });
    return mine;
  }

  var A = P.asus = {
    META: META,
    normalize: normalize,
    MODELS: [],
    UNAVAILABLE: [],
    load: load,
    known: function (id) { return Object.prototype.hasOwnProperty.call(META, id); },
    HEADLINE: 'ASUS의 강력한 성능, 나의 AI 작업실.',
    INTRO: '문서 정리부터 영상 편집, 내 PC에서 AI 실행까지.',
    FIELDS: ['내 PC에서 AI 실행', '영상 편집·제작', '반복 업무 줄이기'],
    PROCESS: ['용도 상담', '구성 검토', 'ASUS 가격 확정'],
    PLAN_LABEL: '기획 검토가 · ASUS 협의 전',
    PLAN_NOTE: '아직 판매 가격이 정해지지 않았습니다.',
    PLAN_UNSET: '미정',
    PERFORMANCE: '사용 프로그램과 AI 모델, 설정에 따라 결과가 달라집니다.',
    PHOTO_NOTE: '사용 예시 / 실제 판매 제품과 다를 수 있습니다.',
    CASE_NAME: 'ASUS TUF Gaming GT502 BLACK',
    BUILD_NOTE: '제품 이미지는 연출이며 실제 구성과 다를 수 있습니다.',
    LIGHT_NOTE: '내부 부품 없는 케이스 연출입니다. 푸른 빛은 외부 조명으로, RGB 부품 포함을 뜻하지 않습니다.',
    FOOTNOTE: '디자인 시안 · 제품 이미지는 연출 · 최종 가격 ASUS 협의 후 확정 · Windows 별도',
    DETAIL_FOOTNOTE: '디자인 시안 · 제품 이미지는 연출 · Windows 별도',
    TOTAL_NOTE: '구성과 조립·배송 조건에 따라 금액이 달라 전체 합계를 표시하지 않습니다. 기획 검토가는 부품 합계가 아닙니다.',
    PARTS_NOTE: '한 항목에 제품이 둘 이상이면 그중 하나로 구성합니다. 최종 구성은 상담에서 안내합니다.',
    COMPAT: 'GT502 케이스 규격: 그래픽카드 최대 400mm, 상단 라디에이터 360mm, 파워 최대 200mm.',
    INSTALL: [
      { icon: 'computer-tower', title: '본체 조립·검수', text: '부품 조립과 기본 점검 범위는 상담에서 안내합니다.' },
      { icon: 'gear', title: '프로그램 설치·사용 안내', text: '프로그램 설치와 사용 안내는 별도 문의해 주세요. Windows, AI 프로그램 설치, 문서 검색 설정, 업무 도구 연결, 교육도 별도 문의입니다.' }
    ],
    SALE_NOTES: ['정확한 부품과 호환 범위는 상담에서 안내합니다.', '배송·AS 접수처·지원 기간은 확정된 내용만 표시합니다.'],
    LOADING: '기획전 정보를 불러오는 중입니다.',
    LOAD_FAILED: '기획전 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.',
    find: function (id) {
      for (var i = 0; i < A.MODELS.length; i += 1) if (A.MODELS[i].id === id) return A.MODELS[i];
      return null;
    },
    detailHref: function (id) { return 'asus-pc.html?model=' + encodeURIComponent(id); },
    inquiryHref: function (id) { return 'asus-consult.html?model=' + encodeURIComponent(id); },
    image: function (file) { return 'assets/images/asus/' + file; },
    // 사용 예시는 파일명(DB 값)을 유지한 채 그림을 교체했으므로 주소 버전으로 옛 캐시를 피한다.
    useImage: function (file) { return A.image(file) + '?v=20261106-art1'; },
    won: function (value) { return Number(value).toLocaleString('ko-KR') + '원'; },
    planText: function (m) { return m.plan === null ? A.PLAN_UNSET : A.won(m.plan); }
  };
}());
