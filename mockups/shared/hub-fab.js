/* 「허브」 FAB 표시 판정 — 고객 목업(mvp1) 공통 · 단일 원천 (2026-08-18 사장님 확정)
 *
 * ■ 무엇을 하나
 * 고객 화면 좌하단의 `<a id="hub-fab" href="index.html">허브</a>` 는 내부 접근 허브
 * (INT-GATE-010 · UX-09 「내부자 전용」)로 가는 단추다. 2026-08-09 고객 경로 개방
 * 뒤로 고객에게도 그대로 보이고 있었다. 이 파일이 **내부자에게만** 그 단추를 켠다.
 *
 *     내부자  =  운영자 로그인 세션이 있음 (`GET /api/admin/auth/me` → authenticated:true)
 *             또는 로컬 접속 (`location.hostname` 이 localhost · 127.0.0.1)
 *     그 외   =  숨김 유지
 *
 * ■ 기본은 숨김, 조건 충족 시 표시
 * 반대로(기본 표시 → 판정 후 숨김) 하면 판정 전 잠깐 보인다. 그래서 HTML 쪽에서 먼저
 * 숨겨 둔다: 앵커에 `hidden` 속성 + 인라인 `display:none`. **둘 다 두는 이유** —
 * 이 앵커들은 인라인 style 에 display 를 갖고 있고, 인라인 선언은 UA 스타일시트의
 * `[hidden]{display:none}` 보다 세다. 즉 `hidden` 만 붙이고 `display:inline-flex` 를
 * 남기면 속성이 무력하다. 그래서 인라인 값을 `none` 으로 두고, 이 파일이 표시할 때
 * `hidden` 을 풀며 `display` 를 원래 값(`inline-flex`)으로 되돌린다.
 * 이 스크립트가 로드되지 않으면(404 등) FAB 는 **그냥 안 보인다** — 실패가 열림이 아니라
 * 닫힘 쪽으로 떨어진다.
 *
 * ■ 판정 결과와 실패를 구분한다
 *   · `/me` 가 200 이지만 `authenticated:false` — 판정 결과(미로그인). 숨김 유지.
 *     (2026-08-18 실측: `/api/admin/auth/` 는 auth_middleware OPEN_PREFIXES 라 무세션도
 *      401 이 아니라 200 + authenticated:false 로 온다. 배포 경로 사정으로 401 이 와도
 *      같은 뜻으로 읽는다.)
 *   · 401 · 응답이 JSON 이 아님(예: nginx 안내 HTML) — 역시 숨김 유지.
 *   · 네트워크 오류 · API 부재(목업 단독 열람 · file://) — 숨김 유지.
 *     ⚠ 이 경우도 콘솔에 아무것도 남기지 않는다. 「실패를 삼키지 않는다」 규약의 예외인데,
 *     이유는 고객 화면 콘솔 에러 0 규약이고, 사용자에게 보여줄 것이 없는 판정이라
 *     (내부자가 아니면 숨김이 정답) 조용히 두는 것이 맞다. 그 사실을 여기 적어 둔다.
 *
 * ■ 화면마다 판정하지 않는다
 * 11개 파일이 각자 fetch 를 들고 있으면 조건이 갈린다. 조건을 바꾸려면 이 파일만 고친다.
 * 요청은 `ui-progress.js` 의 fetch 래퍼를 지나지만 GET + `/auth/me` 는 거기서 quiet 처리라
 * 진행 바가 뜨지 않는다.
 */
(function () {
  var fab = document.getElementById('hub-fab');
  if (!fab) return;

  function show() {
    fab.hidden = false;
    fab.style.display = 'inline-flex';   // 인라인 display:none 을 원래 값으로 되돌린다
  }

  var host = location.hostname;
  if (host === 'localhost' || host === '127.0.0.1') { show(); return; }

  fetch('/api/admin/auth/me', { credentials: 'same-origin' })
    .then(function (r) { return r.ok ? r.json() : null; })   // 401 등 비정상 → null → 숨김 유지
    .then(function (d) { if (d && d.authenticated === true) show(); })
    .catch(function () {
      // 네트워크 오류 · API 부재 · 비JSON 응답 — 숨김 유지가 판정이다.
      // 콘솔에 남기지 않는 이유는 위 헤더 「판정 결과와 실패를 구분한다」 참조.
    });
})();
