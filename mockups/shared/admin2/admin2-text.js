/* -*- coding: utf-8 -*-
 * admin2 화면 공용 — 상품명·사양 원문에 섞인 HTML 태그를 표시에서만 벗긴다 (2026-08-27).
 *
 * ■ 왜 있는가
 *   products.product_name · spec_source_text 는 몰(원천)에서 그대로 받은 값이다. 몰은
 *   상품명에 <font color=red>…</font> · <P> 같은 HTML 마크업을 섞어 색·줄바꿈을 낸다.
 *   우리 화면은 esc() 로 안전하게 이스케이프해서 보여주므로(XSS 방지 — 정상 동작) 그
 *   마크업이 "글자 그대로" 보인다. 예:
 *     <font color=blue>[B650/DDR5]</font> 가 문자 그대로 화면에 찍힌다
 *   (2026-08-26 사장님 발견, /admin2/category-mapping?scope=violation).
 *
 * ■ 무엇이 바뀌고 무엇이 안 바뀌는가
 *   admin 화면은 원래 원천을 그대로 본다(A-38 ⑤, api/product_name.py) — 마켓 노출을
 *   관리하는 자리라 실제 나가는 제목을 봐야 하기 때문이다. **이 규약은 그대로 둔다.**
 *   판매조건 문구("회원가입 … 2.5%" 같은 할인·쿠폰 안내)는 운영자가 봐야 할 «내용»이라
 *   지우지 않는다. 다만 HTML 태그 자체는 «표시 방식»이지 내용이 아니다 — 그래서 이
 *   파일은 태그·엔티티만 벗기고 글자는 하나도 지우지 않는다(권한 판단 근거는
 *   docs/decisions/decision-log.md 가 아니라 이번 작업 지시 — HTML 태그 정리는 A-38 ⑤의
 *   "원천 그대로" 규약이 다루는 대상이 아니라는 판단. 상세 근거는 이 작업의 제작 보고).
 *
 * ■ 쓰는 자리 — 읽기 전용 표시에만
 *   목록 행 · 상세 제목 · 툴팁 · 안내 문구처럼 **화면에 보여주기만 하는 자리**에 쓴다.
 *   ⚠ 상품명 **편집 입력창의 value=** 에는 쓰지 않는다 — 그 값은 저장하면 그대로
 *   products.product_name 에 돌아간다. 여기서 태그를 벗기면 "고치지 않고 저장"만 눌러도
 *   원천이 조용히 바뀐다(DB 를 고치지 않는다는 이번 작업의 규칙 위반). 편집 화면
 *   (products.html.j2 의 BASIC_FIELDS 입력 분기)은 원본 그대로 둔다.
 *
 * ■ 실측 (2026-08-26~27, products 전체)
 *   product_name 태그 315건 · spec_source_text 344건. 태그 이름은 font · p/P · br ·
 *   strong · em · b, 오탈자 storng 1종. 엔티티는 &#65279;(제로폭 공백) · &#160;(NBSP)
 *   둘뿐 — 그 밖의 엔티티·"<30cm" 류 부등호(부품 스펙) 사용은 두 필드 전체에서 0건이었다
 *   (전수 스캔). 그래서 이 함수는 "글자로 시작하는 태그"만 태그로 본다 — 숫자·한글이
 *   "<" 바로 뒤에 오면 손대지 않는다(부품 스펙의 부등호를 지우지 않기 위해서다). 전량
 *   시뮬레이션으로 빈 이름이 되는 상품 0건 · 태그가 남는 상품 0건을 확인했다(Python
 *   동형 로직 api/html_text.py 로 검증 — 서버에 브라우저가 없어 JS 자체는 이 방식으로
 *   대신 검증했다).
 */
(function () {
  "use strict";

  // p·br 등 블록 태그는 지우면 단어가 붙는다("...BTF]</font><p> [14700KF..." 처럼 앞뒤에
  // 공백이 없는 경우가 실측에 있었다) — 공백으로 바꾼다. font·strong·em·b 등 인라인
  // 태그는 실측상 앞뒤에 이미 공백/괄호가 있어 빈 문자열로 지워도 글자가 안 붙는다.
  var BLOCK_TAGS = /^(p|br|div|tr|td|th|li|h[1-6])$/i;

  // <태그 ...> / </태그> — 태그 이름은 반드시 글자(a-z)로 시작해야 매치된다. "<30cm"·
  // "A<B" 처럼 숫자·한글이 바로 뒤에 오는 부등호는 이 조건에 안 걸려 지워지지 않는다.
  var TAG_RE = /<\/?\s*([a-zA-Z][a-zA-Z0-9]*)\b[^<>]*>/g;
  // 닫는 ">" 없이 원문이 절단된 조각(실측: product_code 109378 — "...</font"로 끝남).
  // 알려진 태그 이름으로 시작할 때만 지운다. 모르는 이름은 그대로 둔다(부등호를 함부로
  // 지우지 않기 위해서).
  var TRAILING_TAG_RE = /<\/?\s*(?:font|p|br|strong|storng|em|b)\b[^<>]*$/i;

  function stripHtml(raw) {
    if (raw === null || raw === undefined) return "";
    var s = String(raw);
    if (s.indexOf("<") === -1 && s.indexOf("&") === -1) return s;

    s = s.replace(TAG_RE, function (whole, tagName) {
      return BLOCK_TAGS.test(tagName) ? " " : "";
    });
    s = s.replace(TRAILING_TAG_RE, " ");

    // 실측된 엔티티만 다룬다 — 광범위한 디코더 대신 실제로 나온 것만 처리해, 예컨대
    // "&lt;br&gt;" 같은 값이 디코드 후 다시 태그로 오인되는 경로를 만들지 않는다.
    s = s.replace(/&#65279;/gi, "").replace(/&#160;|&nbsp;/gi, " ");

    s = s.replace(/\s+/g, " ").trim();
    return s || String(raw);   // 다 지워지면(예상 밖 데이터) 원본을 낸다 — 빈 이름보다 낫다
  }

  window.Admin2Text = { stripHtml: stripHtml };
})();
