/* 시각 표기 단일 원천 (슬라이스 100).
 *
 * ■ 왜 만들었나
 * 슬라이스 62가 정한 규약은 **"시각은 절대값으로 주고 표시를 각자 한다"**다.
 * 서버는 타임존이 붙은 ISO(`...+00:00`)를 주고, 그리는 것은 화면 몫이다.
 * 그런데 내 정보 화면(슬라이스 92)이 그 ISO를 **원문 그대로 출력**했다:
 *
 *     마지막 로그인   2026-07-30T04:57:22.084811+00:00
 *
 * 사람이 읽을 수 없고, 더 나쁜 것은 `04:57`이 UTC라 **실제 13:57 KST와 9시간
 * 어긋나 보인다**는 점이다. 운영자는 "새벽에 로그인했나?"라고 읽는다 —
 * 슬라이스 62가 고친 바로 그 종류의 오해다.
 *
 * ■ 왜 공통 모듈인가
 * `fmtT`가 이미 6개 화면에 **각자** 정의돼 있고, 그 정의가 두 갈래로 갈렸다
 * (상대시각 '3분 전' 계열 5개 · 절대시각 'M-DD HH:MM' 1개). 같은 이름이 다른 일을
 * 하는 상태다. 7번째 사본을 만들지 않기 위해 여기 둔다.
 * (기존 6개는 의도적으로 다를 수 있어 건드리지 않았다 — 정리는 별건이다.)
 *
 * ■ 왜 브라우저 지역시각인가
 * `new Date(iso)`는 타임존이 붙은 문자열을 절대시각으로 읽고, `getHours()`는
 * **보는 사람의 지역**으로 돌려준다. 슬라이스 62가 서버에서 KST 문자열을 만드는
 * 방법을 일부러 버렸다 — 값에 지역이 박히면 다른 지역에서 다시 어긋나기 때문이다.
 * 그 판단을 그대로 따른다.
 *
 * 사용: <script src="../shared/fmt-time.js"></script> 뒤에 `PT.full(iso)`
 */
(function () {
  function parse(iso) {
    if (iso === null || iso === undefined || iso === '') return null;
    var d = new Date(iso);
    return isNaN(d.getTime()) ? null : d;      // 못 읽는 값을 'Invalid Date'로 흘리지 않는다
  }
  function p2(n) { return String(n).padStart(2, '0'); }

  var PT = {
    /* 값이 없으면 '—'. **지어내지 않는다** — 빈 자리를 그럴듯한 날짜로 채우지 않는다. */
    NONE: '—',

    /** 2026-07-30 */
    date: function (iso) {
      var d = parse(iso);
      if (!d) return PT.NONE;
      return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate());
    },

    /** 13:57 */
    hm: function (iso) {
      var d = parse(iso);
      if (!d) return PT.NONE;
      return p2(d.getHours()) + ':' + p2(d.getMinutes());
    },

    /** 2026-07-30 13:57 — 연도가 필요한 자리(가입일·승인일) */
    full: function (iso) {
      var d = parse(iso);
      if (!d) return PT.NONE;
      return PT.date(iso) + ' ' + PT.hm(iso);
    },

    /** 07-30 13:57 — 최근 것만 보는 자리(목록) */
    short: function (iso) {
      var d = parse(iso);
      if (!d) return PT.NONE;
      return p2(d.getMonth() + 1) + '-' + p2(d.getDate()) + ' ' + PT.hm(iso);
    },

    /** "3분 전" · "어제 13:57" · 그보다 오래되면 절대시각.
     *  상대시각만 쓰면 "언제였는지"를 잃는다 — 하루가 넘으면 절대값으로 돌아간다. */
    rel: function (iso) {
      var d = parse(iso);
      if (!d) return PT.NONE;
      var s = Math.floor((Date.now() - d.getTime()) / 1000);
      if (s < 0) return PT.full(iso);            // 미래 값은 그대로 보여준다
      if (s < 60) return '방금';
      if (s < 3600) return Math.floor(s / 60) + '분 전';
      if (s < 86400) return Math.floor(s / 3600) + '시간 전';
      if (s < 172800) return '어제 ' + PT.hm(iso);
      return PT.full(iso);
    }
  };

  window.PT = PT;
})();
