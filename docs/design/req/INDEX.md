# 화면 요구사항 정의서 목차 — LNB 순서

> 사장님이 UI 디자인을 공유하실 때 **다음 차례가 무엇인지 바로 누를 수 있게** 만든 목차다.
> 순서는 좌측 메뉴 정본(`api/admin_nav.py`) 그대로다. 상태는 이 파일이 아니라 실제로
> 재서 안다 — `git status` · `/admin2/*` 라우트 존재 여부.
>
> 상태 표기: **지음** = admin2에 구축됨(라우트가 있다) · **디자인** = 승인 디자인 있음(구축 대기) ·
> **정의서** = 요구사항만 있음 · **없음** = 아직 ·
> **재정의** = 지어졌으나 다시 정의하기로 함 · **셸만** = 새 사이드바에 옛 본문이 붙은 상태 ·
> **구축 중 / 신설 대기** = 승인 디자인을 받아 짓는 중 / 아직 라우트 없음 ·
> **재구축 중 / 재구축 대기** = 이미 지어진 화면을 승인 디자인대로 다시 짓는 중 / 대기 ·
> **수정 완료 · 확인자 재검증 대기** = 라우트·결함 수정은 끝났으나 확인자의 브라우저
> 실측이 아직이라 메뉴에는 연결하지 않은 상태(2026-08-15 추가 — 용도별 최소 사양이
> 첫 사례. 실측 없이 메뉴를 열면 운영자가 눈으로 안 본 화면에 먼저 들어간다).
> **그 첫 사례는 2026-08-16 확인자 재검증 통과 + 메뉴 연결로 「지음」이 됐다** —
> 이 상태어 자체는 폐기가 아니라 다음에 같은 상황이 오면 또 쓴다(CANON §5).
>
> ⚠ **범례에 없는 말을 표에 쓰지 않는다** — 2026-08-14 실측 시점에 표는 「구축 중 ·
> 재구축 대기 · 재구축 중 · 신설 대기」를 쓰는데 범례에는 넷 다 없었다. 상태 어휘가
> 범례 밖으로 자라면 같은 말을 사람마다 다르게 읽는다.
>
> **「셸만」은 완료가 아니다.** 셸 정본화(2026-08-13) 때 본문 재설계를 범위 밖에 뒀기
> 때문에 새 껍데기에 옛 Phoenix 본문이 붙은 화면이 있다.
>
> ⚠ **2026-08-14 정정** — 처음에 넷을 「셸만」으로 일괄 표기했으나 **실측 결과 둘뿐이었다**
> (대시보드 · 상품 관리). **조립 호환 지도와 조립 사양 표준은 Phoenix 더미가 아니라 실 API에
> 완전히 연동된 화면**이다(정의서 작성 중 실호출로 확인). 셸 정본화 보고를 화면별로 확인하지
> 않고 하네스가 넷을 묶어 적은 것이 원인이다 — **상태는 적지 말고 재서 안다**는 규칙을
> 목차 자신이 어겼다.
>
> ⚠ **2026-08-15 발견(03:19) → 그날 안에 해소(11:44, 행 22B) — 그런데 이 발견
> 노트 자신은 안 고쳐진 채 남아 있었다.** 발견 당시 실측:
> `templates/admin/margin_policy.html.j2` · `api/admin_ui_margin_policy.py`
> (라우트 `/admin2/margin-policy`) · `docs/design/req/req-margin-policy.md` ·
> `docs/design/spec-margin-policy.md` 넷 다 존재하는데 이 목차에도
> `api/admin_nav.py`에도 행이 없었다. **커밋 `eaaec25`가 화면 ID `ADM-PRC-020`·
> 그룹 내 순서(010 다음·030 앞)를 정해 22B로 편입했다** — 아래 §5. 판매가 표에
> 있다. **다만 이 발견 노트 자체는 그 뒤로도 지워지지 않아, 한 파일 안에서
> 「없다」와 「22B에 있다」가 동시에 남는 자기모순이 됐다** — 행을 고쳐도 그
> 행을 가리키던 다른 문단이 저절로 안 고쳐진다는 것을 이 목차 스스로 보여준
> 사례다. 지우지 않고 여기서 정정한다(CANON §5 — 폐기된 것은 지우지 말고
> 폐기라고 적는다. 이 노트는 폐기가 아니라 해소된 발견이라 「해소」로 적는다).

> **2026-08-25 기록자 실측 — 정의서 유무 43개 전수 재확인.** `api/admin_ui_*.py`
> (공용 헬퍼 `admin_ui_common.py` 제외) 43개를 화면 ID로 `docs/design/req/*.md`와
> 대조한 결과 **43개 전부 정의서가 있다**(0개 없음). 유일한 예외는 위치뿐이다 — 상품
> 사양 검수(`ADM-PRD-020`)의 정의서는 `docs/design/req/` 안이 아니라 한 단계 위
> `docs/design/req-admin2-reviews-2026-08-13.md`에 있다(`req/` 하위 폴더 관례가 서기
> 전에 쓰여 위치만 다르고 내용은 정상). 이 목차에서 실제로 빠져 있던 것은 **행 자체**
> (팝콘톡 응답 패턴, 위 §7 `28B`로 추가)였지 정의서가 아니었다 — 상세 근거는
> `docs/decisions/admin-identity.md` §「2026-08-25 전 화면 재정렬」.

## 0. 로그인 — LNB 밖

> 로그인 화면은 좌측 메뉴에 없다(실측: `api/admin_nav.py` 전수 검색 "로그인" 0건 —
> 인증 전 화면이라 메뉴 대상이 아니다). 번호 `0`은 목차 맨 앞에 두기 위한 표기일
> 뿐 LNB 순번이 아니다.

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 0 | 로그인 | [req-login.md](req-login.md) | [spec-login.md](../spec-login.md) | **지음**(2026-08-17 정정 — A-56 ⑧이 미뤄 둔 착수를 같은 날 앞당겨 구현했다. `/admin2/login` · **ADM-SYS-021** · `api/admin_ui_login.py` + `templates/admin/login.html.j2`. 게이트 면제는 `api/auth.py` `ADMIN2_OPEN_PATHS`의 **완전 일치 집합**(A-44) — 접두어가 아니다. 기동 시 감사 두 겹(`_audit_admin2_open_paths`·`_audit_admin2_open_routes`)이 이 집합이 넓어지거나 쓰기 경로를 품으면 앱을 세운다. **전환은 같은 커밋**: `admin_ui_common._LOGIN_PAGE`를 `/admin2/login`으로 · `api/main.py`의 `_ADMIN_AUTH_DOOR_SCREENS`에서 `login` 제거(`my-profile`·`operators`는 대체 화면이 없어 남김 — 한 번에 셋을 닫지 않는다). 확인자 검증: 게이트 무회귀 14/14 401 · 승인 디자인 치수 8항목 일치 · 기기 기억 전 흐름(등록→로그인→철회→`no_device`) 실완주 · 숫자 리터럴 0건(세션 규칙은 서버 상수를 렌더에 실어 보냄) · 무세션 `/admin2/reviews` → 401 → 로그인 → 대시보드 → 좌측 메뉴 → 도착. 확인법: `grep -n "ADMIN2_OPEN_PATHS" api/auth.py`) |

## 0B. 내 정보 — LNB 밖

> 이 화면도 좌측 메뉴에 없다(실측: `api/admin_nav.py` 전수 검색 "my-profile"·"내 정보" 0건
> — 자기 계정을 조회·수정하는 화면이라 메뉴 대상이 아니다. 근거는 계약
> `spec-my-profile.md`의 `LNB **없음**` 항목 · 같은 근거로 확인). 번호 `0B`는 로그인(0)과
> 같은 「LNB 밖」 성격이라 그 옆에 붙인 표기이지 LNB 순번이 아니다(22B 등 다른 「B」 표기와
> 같은 관례). **진입점은 상단바 아바타 링크다**(승인 원안·계약 §진입점) — **화면 검증을
> 통과한 뒤에 링크를 단다**는 순서 규약(T-02 ②)이 여전히 걸려 있어, 아래 상태가 「검증 전」인
> 동안은 링크도 없다.
>
> ⇒ **2026-08-20 갱신(지우지 않고 이어 적는다)** — 검증은 이미 통과했다(커밋
> `922e7d0`·`6023cba`·`d4573d2`의 메시지가 확인자 재점검 통과를 근거로 든다). 그런데
> **링크는 여전히 없다**(기록자 `grep -n "my-profile" templates/admin/_admin2_shell.html.j2`
> 확인 — 0건). 즉 「검증 전이라 안 잇는다」던 조건은 더 이상 사실이 아니고, **잇는 일
> 자체가 남아 있을 뿐이다.** 화면 파일이라 기록자는 손대지 않는다.
>
> ⇒ **2026-08-28 갱신(기록자 정정) — 그 「남은 일」이 이미 됐다.** 사장님이 "내정보
> 수정은 어디를 클릭해야 들어갈 수 있지?"라고 물으신 것을 계기로 커밋 `c5d7610`
> (2026-08-21)이 상단바 아바타를 `<span>`에서 실제 링크(`href="/admin2/my-profile"`)로
> 바꿨다. 재확인: `grep -n "my-profile" templates/admin/_admin2_shell.html.j2` → 131·145행
> 실재(0건이 아니다). 그 커밋은 CDP 실클릭으로 `location.pathname`이 실제로
> `/admin2/my-profile`이 되는 것까지 확인했고 회귀 896/896 통과였다.
>
> ⇒ **2026-08-28 갱신(같은 날 두 번째, 기록자) — 구 화면 문이 완전히 닫혔다.**
> `/admin/my-profile.html`도 이제 410이다(구 로그인·구 운영자·권한에 이어 세
> 번째이자 마지막 — `docs/decisions/decision-log.md` **A-117**). 같은 물결에서
> 이 화면(아래 표)이 구 화면에는 있던 「로그인 실패 횟수」(`login_fail_count`)를
> 서버에서 받고도 안 그리던 것도 채웠다. 신원 격자는 `spec-my-profile.md` §㉡의
> **5칸**을 그대로 두고 잠금 배지 옆에 별도로 얹었다 — 격자 칸 수는 안 바뀌었다.

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 0B | 내 정보 | [req-my-profile.md](req-my-profile.md) | [spec-my-profile.md](../spec-my-profile.md) | **지음 · 커밋·배포·링크 연결 완료**(**ADM-SYS-022** · 경로 `/admin2/my-profile` · `api/admin_ui_my_profile.py` + `templates/admin/my_profile.html.j2` + `api/admin_profile_photo.py`. 커밋 `922e7d0`(화면 신설) · `6023cba`(문구 교정 약 90곳) · `d4573d2`(401 구조화)로 서버에 반영됐다(HEAD `ead6dd3` 대조 완료). 2026-08-19 계약자 재점검 결함 셋 중 하나(사진 정책 API 임의 신설)는 같은 날 **A-70**으로 추인 해소, 나머지는 미정 **U-19~U-23**으로 남았다. **회귀 스위트는 이 화면(사진 API)을 다루지 않는다**(coverage gap, 그대로). **2026-08-28 기록자 정정 — 「링크 미연결」은 낡았다.** 상단바 아바타 링크가 커밋 `c5d7610`(2026-08-21)로 이미 연결됐다(위 §0B 안내문 2026-08-28 갱신 참조). **같은 날 두 번째 갱신 — 「로그인 실패 횟수」를 채웠다.** 구 화면(`mockups/admin/my-profile.html:382`)엔 있었는데 이 화면이 서버 값(`login_fail_count`)을 받고도 안 그리고 있었다 — 잠금 배지 옆에 채웠다(신원 격자 5칸은 그대로). 구 화면 문도 같은 날 닫혔다(`/admin/my-profile.html` → 410, `docs/decisions/decision-log.md` **A-117**). 상세는 `HANDOFF.md` 「2026-08-20」) |

## 1. 대시보드

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 1 | **대시보드** | [req-dashboard.md](req-dashboard.md) | `dc-dashboard-3안.html` | **지음**(`/admin2/` · ADM-DASH-010 · UX-22 → 1b 카드 그리드형. **2026-08-28 기록자 정정 — 「재구축 중」은 낡았다.** `templates/admin/home.html.j2` 상단 주석이 2026-08-15에 이미 「재구축」을 완료로 적어 뒀다(Phoenix·Bootstrap·외부 CDN 전부 걷어내고 admin2.css 전용으로 다시 지음). 그 뒤로도 재고 정합 쿼리 성능 개선(`97b878d`)·몰 값 야간 자동 반영(`f20abb1`, 2026-08-27, 대시보드에 그 결과가 뜬다)까지 계속 붙었다 — 공사 중이 아니라 이미 서서 자라는 화면이다. 「레이아웃 견본」 배너 0건, `api/admin_nav.py`에 href 실재. 확인법: `git log --oneline -- templates/admin/home.html.j2`) |

## 2. 상품관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 2 | **상품 분류 관리** | [req-product-category.md](req-product-category.md) | `dc-product-category.html` | **지음** (`/admin2/categories` · ADM-CAT-010) |
| 3 | **상품 관리** | [req-products.md](req-products.md) | `dc-products-3안.html` | **지음**(`/admin2/products` · ADM-PRD-010 · UX-23 → 1a 탭형 서랍. **2026-08-28 기록자 정정 — 「재구축 대기」(=착수 전)는 낡은 정도가 아니라 사실과 반대였다.** 재구축 자체는 커밋 `cbb124c`(2026-08-15, 「상품 관리 화면 재구축(dc-products-3안 1a) + 중복 판정 결함 4건」)로 끝났고, 그 뒤로도 공급처 정보 배선·상품명 HTML 태그 제거(`4eb7adb`, 2026-08-27)까지 계속 기능이 붙었다. 셸 CSS 특정성 사고 방어 수정 — `.pp-btn-line`, 검수 대기 상품 상세 서랍에서만 렌더돼 무증상이었다. 커밋 `77121d6`+`fbb9b61`. 확인법: `git log --oneline -- templates/admin/products.html.j2`) |
| 4 | **상품 분류 매핑** | [req-product-category-map.md](req-product-category-map.md) | `dc-product-category-map.html` | **지음** (`/admin2/category-mapping`) |
| 5 | **상품 일괄 등록** | [req-product-bulk-import.md](req-product-bulk-import.md) | `dc-product-bulk-import.html` | **지음** (`/admin2/catalog-import` · ADM-CSV-010 · UX-21 → 1b · 라우트·템플릿 커밋 `82a55a1` · ⚠⚠ owner 업로드가 영구히 잠기던 결함 수정(셸 스크립트 중복 로드로 `window.Admin2Shell` 인스턴스가 둘 생겨 권한 갱신이 안 됐다, 커밋 `08541f7`) · 확인자 재검증 통과(`script[src]` 정확히 2개 · 잠금 문구 사라짐 · 파일 입력 3개 열림 · `canWrite('owner')===true`) · 메뉴 연결 `9fdae6d`) |
| 6 | **삭제 상품 조회** | [req-product-deleted.md](req-product-deleted.md) | `dc-product-deleted-2안.html` | **지음** (`/admin2/deleted-products` · ADM-DEL-010 · UX-26 → 1b + 빈 상태 1c · 라우트·템플릿 커밋 `82a55a1` · 로딩 표시 CSS 결함 수정(`hidden`인데 `display:flex`였다, 커밋 `107e819`) · 확인자 재검증 통과(화면 수치 ↔ API 응답 전수 대조 일치) · 메뉴 연결 `9fdae6d` · 셸 CSS 특정성 사고 방어 수정 — `.dp-empty-link`(커밋 `77121d6`+`fbb9b61`)) |

## 3. 상품사양관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 7 | **조립 호환 지도** | [req-build-map.md](req-build-map.md) | `dc-build-map-v2.html` | **지음**(`/admin2/build-map` · **ADM-STD-020** · UX-20 → v2 클릭 고정. **2026-08-28 기록자 정정 — 「재구축 대기」는 10일 전에 끝난 일이었다.** `templates/admin/build_map.html.j2`는 2026-08-15 커밋 `6fe0de9`(「결함 2건 수정 후 재실측 통과」)로 v2(대상 유지 hover→click 고정)까지 완성됐고, `api/admin_ui_build_map.py` docstring도 같은 날짜로 "v2 재구축" 완료를 적어 뒀다. UX-20이 요구한 3탭(지도형·진단형·매트릭스형)이 템플릿에 실재한다(`grep -c "지도형\|진단형\|매트릭스형" templates/admin/build_map.html.j2` = 16 — 주석뿐 아니라 tab 버튼·`data-view-panel` 패널까지). 데이터는 `GET /api/admin/std/compat-map` 하나(읽기 전용), 「레이아웃 견본」 배너 0건. `api/admin_nav.py`에도 href가 이미 있다(298행). 이 행을 마지막으로 고친 것은 그보다 «뒤»인 2026-08-25 커밋 `0662d43`인데도 옛 상태말을 그대로 옮겨 적어, 나중에 편집된 문서가 더 낡은 사실을 담고 있었다 — 확인법은 `git log --oneline -- templates/admin/build_map.html.j2`와 `git log -3 -- docs/design/req/INDEX.md`의 날짜 대조) |
| 8 | **조립 사양 표준** | [req-spec-standard.md](req-spec-standard.md) | `dc-spec-standard-2안.html` | **지음**(`/admin2/spec-standard` · ADM-STD-010 · UX-24 → **1a**(결핍 패널 + 표 · 모달 — 처음엔 1b였다가 같은 날 사장님이 배치를 다시 골랐다, `decision-log.md` UX-24). **2026-08-28 기록자 정정 — 「재구축 중」은 낡았다.** `templates/admin/spec_standard.html.j2` 상단 주석이 1a 재구축 완료를 적어 뒀고, 이름·단위·메모 편집 API 후속 반영까지 「검증 통과」로 커밋됐다(`c48623e`, 2026-08-15). 그 뒤 사장님 신고로 팝업 위치 결함도 고쳤다(`b1eb47e`, 2026-08-16) — 그 뒤로 추가 커밋 없이 안정 상태다. ⚠ **코드 자체의 어긋남(문서 아님, 손대지 않고 보고만 한다)**: `api/admin_ui_spec_standard.py`의 라우트 docstring은 아직 「UX-24 → 1b」라고 적혀 있다 — 같은 날 있었던 1b→1a 정교화 «이전» 문구가 안 고쳐진 채 남은 것으로 보인다. 실제 화면·decision-log·이 목차는 셋 다 1a로 일치한다. 확인법: `git log --oneline -- templates/admin/spec_standard.html.j2` · `grep -n "UX-24" api/admin_ui_spec_standard.py`) |
| 9 | **상품 사양 정의** | [req-spec-field-defs.md](req-spec-field-defs.md) | `dc-spec-field-defs-2안.html` | **지음** (`/admin2/spec-field-defs` · ADM-PRD-050 · UX-27 → 1a · 라우트·템플릿 커밋 `82a55a1` · 확인자 재검증 통과(결함 없음) · 메뉴 연결 `9fdae6d`) |
| 10 | **상품 사양 검수** | [req-admin2-reviews-2026-08-13.md](../req-admin2-reviews-2026-08-13.md) | `dc-review-screen.html` | **지음** (`/admin2/reviews`) |
| 11 | **조립 호환 규칙** | [req-compat-rules.md](req-compat-rules.md) · [req-compat-required.md](req-compat-required.md)(「필수 사양 안내」 탭) | `dc-compat-rules-2안.html` | **지음** (`/admin2/compat-rules` · ADM-ENG-010 · UX-28 → 1b · 커밋 `3ffe740` · 메뉴 연결 `68daf6e`. **+2026-08-15: 「필수 사양 안내」 탭 신설**(`spec-compat-required.md` 계약 — 결정 로그 ⑤ 설계 간극을 채움) · 확인자 2차 검증 결함 0 · 커밋 `89019e2`. 메뉴는 안 바뀜 — 기존 화면 안 탭 추가 · 셸 CSS 특정성 사고 방어 수정 — `.cr-btn--ghost`(커밋 `77121d6`+`fbb9b61`)) |
| 12 | **용도별 최소 사양** | [req-usage-floors.md](req-usage-floors.md) | `spec-usage-floors.md`(계약) | **지음** (`/admin2/usage-floors` · ADM-ENG-040 · UX-29 → 두 안 참고 · 헤더·본문이 서로 다른 가로 스크롤 컨테이너였던 결함을 `.uf-tablewrap` 단일 컨테이너 + `.uf-thead` sticky 로 수정(커밋 `917baea`) · **확인자 재검증 통과(2026-08-16)** — 스크롤 전·후 헤더 위치 459.02px 고정·헤더-본문 가로 거리 220px 어긋남 없음 실측 · **메뉴 연결(기록자, 2026-08-16)** — 마지막 미연결이었다. `api/admin_nav.py` `counts()` 로 `todo` 0 확인) |
| 13 | **부품 등급 관리** | [req-part-grade.md](req-part-grade.md) | `spec-part-grade.md`(계약) | **지음** (`/admin2/part-grade` · ADM-ENG-050 · UX-30 → 1a + 1b 우측 입력 · 확인자 검증 통과 · 커밋 `112c5a7` · 메뉴 연결 `7949c98`) |
| 14 | **추천 기준 보기** (구 「추천 기준 설정」) | [req-policy-weights.md](req-policy-weights.md) | `spec-policy-weights.md`(계약) | **지음** (`/admin2/policy-weights` · ADM-ENG-020 · UX-31 → 1a · 조회 전용 · 개명 · 확인자 검증 통과 · 커밋 `3ffe740` · 메뉴 연결 `68daf6e`) |
| 15 | **추천 가능 재고 현황** | [req-candidate-pool.md](req-candidate-pool.md) | `spec-candidate-pool.md`(계약) | **지음** (`/admin2/candidate-pool` · ADM-ENG-030 · UX-32 → 1a · 조회 전용 · 템플릿 커밋 `ec4b7ba` · 라우트 커밋 `82a55a1` · 확인자 재검증 통과(결함 없음) · 메뉴 연결 `9fdae6d`) |
| 16 | **견적 상담 기록** | [req-consult-sessions.md](req-consult-sessions.md) | `spec-consult-sessions.md`(계약) | **지음** (`/admin2/consult-sessions` · ADM-ORD-010 · UX-33 → 1a + 우측 서랍 · 재검증 «결함 0» · 커밋 `d792434` · 메뉴 연결 `68daf6e`) |
| 17 | 부품 교체 · 클릭 기록 | [req-swap-click-logs.md](req-swap-click-logs.md) | `spec-swap-click-logs.md`(계약 · 커밋 `c75656e` 2026-08-14 23:47 — 이 목차의 최종 편집(`08cfe9e` 16:25)보다 먼저 커밋됐는데 반영이 안 됐었다) | **지음** (`/admin2/swap-click-logs` · 라우트·템플릿 커밋 `82a55a1` · 확인자 재검증 통과(결함 없음) · 메뉴 연결 `9fdae6d` · ⚠ **2026-08-16 사장님 육안 신고**로 셸 CSS 특정성 사고 발견 — 「스왑 확정」류 버튼(`.sc-fixbtn`) 4개 글자색이 배경과 같아(대비 1.00:1) 안 보였다. 대비 14.26:1로 수정, 셸 자체도 `:where()`로 근본 처방(커밋 `77121d6`+`fbb9b61`) — **이 사고가 계기가 되어 같은 원인의 결함 9화면에서 추가 발견·동시 수정**(이 목차의 다른 행 참조)) |

## 4. 매입 · 소싱

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 18 | 공급처 | [req-suppliers.md](req-suppliers.md) | `spec-suppliers.md`(계약 · 1b 안) | **지음** (`/admin2/suppliers` · **ADM-SRC-030** · 커밋 `e5572eb` · 확인자 재검증 통과(하네스 통보 2026-08-15 — 커밋 자신은 "제작 완료·검증 중"이라 적었으나 그 뒤 통과) · 메뉴 연결 `6b3d637`) |
| 19 | 매입 견적(용산) | [req-sourcing-quote.md](req-sourcing-quote.md) | `spec-sourcing.md`(계약 · 1a 안) | **지음** (`/admin2/sourcing` · **ADM-SRC-010** · 커밋 `d53732c` · 확인자 재검증 통과(하네스 통보 2026-08-15 — 위와 같은 경위) · 메뉴 연결 `6b3d637` · ⚠ 마이그레이션 `0053_sourcing_confirmed_at`은 스키마만이고 DB 미적용 — 적용 전까지 「오늘 확정 N건」은 `null`+사유 문구로 대신 응답한다) |
| 20 | 단가표 반영 | [req-price-sheet-apply.md](req-price-sheet-apply.md) | `spec-price-import.md`(계약 · 1b 안) | **지음** (`/admin2/price-import` · **ADM-PRC-040** · 커밋 `4b23e78`(라우트·템플릿 함께) — 그 커밋 메시지 자신은 "재검증 진행 중"이라 적었다. **decision-log `T-11`**: 같은 시각 다른 제작자가 배포를 막던 결함 둘(0행 복원 no-op·되돌리기 버튼 소실)을 같은 두 파일에서 고치다 working tree가 겹쳐 이 커밋에 조용히 함께 들어갔다 — A-46이 그 결함을 처음 실행 가능하게 만들어서야 드러난 잠복 결함이었다. 그 뒤 확인자 재검증 통과(하네스 통보 2026-08-15) · 메뉴 연결 `6b3d637`) |
| 20B | 재고 입고 | [req-stock-inbound.md](req-stock-inbound.md) | [spec-stock-inbound.md](../spec-stock-inbound.md)(계약 · 1b 골격 + 1a 「목록에서 바로 확정」 혼합) · [dc-stock-inbound.html](../dc-stock-inbound.html)(원안 · [README](../dc-stock-inbound-README.md)) | **지음** (`/admin2/stock-inbound` · **ADM-SRC-020**(구 화면 ID 유지 — 새 ID 를 주면 한 화면이 두 신원을 갖는다) · **A-58**로 IA 재등재(2026-08-11 제외 근거였던 「재고 원장은 쇼핑몰이 갖는다」가 사실과 달랐다 — 원장은 우리 것이고 추천 후보 조회가 `WHERE stock_qty > 0` 을 붙인다). **확인자 3차 검증 결함 0**: P-9103 라벨·사유 두 문장만 · `blocked` 행(SKU 39948) 정확 · **세 번째 누출 지점**(확정 결과 옆 사유) 해소 — 「한 행이 두 원천으로 말하지 않는다」가 실측으로 지켜짐 · 게이트 카드 이름표 둘 · 안전재고 사실 `title` 보존 · 카탈로그 `has_specs` 실값 · API↔DOM 문자 대조 9건 일치 · 성능 104~104ms · 치수 전 항목 불변 · 쓰기 왕복 1건(상품 20489103 · log_id 9080) 되돌려 원복, 재고 불변식 일치. **회귀 전건 통과(실패 0)** — `REGRESSION_KEEP_SESSIONS` 없이 돌려 평소 건너뛰던 세션 왕복 항목까지 포함. **메뉴 연결(기록자, 2026-08-18)** — 「매입 · 소싱」 그룹 끝. ⚠ 승인 원안의 사이드바는 매입 견적과 단가표 반영 «사이»를 그렸으나 IA 정본(`docs/design/admin-ia-draft-2026-08-09.md` 58줄) 순서를 따랐다 — 근거·되짚는 법은 `api/admin_nav.py` 9차 노트. **화면 커밋 `dbfc5f9`**(라우트·템플릿·`api/admin_stock.py`·원안·계약이 한 커밋). ⚠ **메뉴 연결 커밋의 해시는 적지 않는다** — 이 행을 세운 커밋 자신이라 쓰는 시점에 존재하지 않는다(지어내지 않는다). 찾는 법: `git log --oneline -1 -- docs/design/req/INDEX.md api/admin_nav.py`. **+2026-08-18 2차 물결 — 대기 유형 필터(U-17 → A-68 ㉰) 구현·검증 통과**(커밋 `95acd6b`): 정의서 §⑤ 2번이 요구했으나 계약이 서버 자리를 빠뜨려 «비활성 칩»으로 서 있던 것을 채웠다. 조회 파라미터 `kind`(`all`·`zero`·`low`) + 유형별 건수 `kind_counts` + 기준 문장 `kind_scope`. **기본 `all` 이 필터 도입 전 모집단과 같아** `pending_where()` 무인자 호출(대시보드·매입 견적)은 안 고쳤다. 「안전재고 미달」 정의를 **SQL 표현 하나**로 모아 조회 조건·칩의 수·행 태그가 한 원천에서 나온다(같은 날 3,876행 사고와 **같은 병의 예방**). **확인자 4차 결함 0** — 칩 셋 API↔DOM 일치 · 「누르면 이만큼」 일치 · `hold`×`kind` 조합을 실제로 보류를 걸어 검증(hold_id 8 · P-9103, 해제로 원복 log 9156) · `kind=bogus` → 400 · 치수 불변 · 콘솔 에러 0. **회귀 전건 통과(실패 0)**. 메뉴는 안 바뀜(기존 화면 안 필터 추가)) |

## 5. 판매가

> ⚠ **번호는 `api/admin_nav.py` 순서를 그대로 따르되, 새로 끼워 넣은 화면은 뒤 섹션
> 전체를 밀어 renumbering 하지 않고 `22B`처럼 옆에 붙인다** — 이 목차의 번호를 그대로
> 인용하는 아래 「디자인 원안」·「계약 요약」 두 표를 전부 손대는 것은 이번 작업 범위
> 밖이라 판단해 미뤘다(연쇄 갱신 위험 대비 최소 변경).
>
> **`docs/design/req/req-reprice.md` §②의 판매가 그룹 번호**(010 가격 검토 대기 ·
> 020 마진 정책 · 030 가격 이력 · 040 단가표 일일 반영 · 050 판매가 재산정 ·
> 060 판매가 관리)와 이 표의 번호는 **다른 채번 체계다** — 저건 화면 ID 접두어
> `ADM-PRC-0nn`의 순번이고 이 표는 LNB 노출 순서다. `040`(단가표 일일 반영)은
> 이 표에서는 **20번 "단가표 반영"**(매입·소싱 그룹)과 같은 화면이다 — 그룹이
> 다르게 잡혀 있을 뿐 화면은 하나다.

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 21 | 판매가 관리 | [req-sale-price.md](req-sale-price.md) | `spec-sale-price.md`(계약 · 커밋 `6f75d49` 2026-08-15 01:30 — 이 목차의 최종 편집(`08cfe9e` 16:25)보다 먼저 커밋됐는데 반영이 안 됐었다) | **지음** (`/admin2/sale-price` · 라우트 커밋 `096aec2`(결함 3건 수정 포함) · 템플릿 커밋 `82a55a1` · 확인자 재검증 통과(결함 없음) · 메뉴 연결 `9fdae6d`) |
| 22 | 가격 검토 대기 | [req-price-review-queue.md](req-price-review-queue.md) | `spec-price-review.md`(계약) | **지음** (`/admin2/price-review` · ADM-PRC-010 · 확인자 검증 통과 · 메뉴 연결 `879ee61` · 커밋 `28c49dd`(뒤늦게 반영, 내용 변경 없음 — 이 목차 최종 편집 뒤에 커밋돼 그 사이 "미커밋"으로 남아 있었다. 조사자 목록엔 없던 여덟 번째 사례, 기록자가 같은 검사 중 발견)) |
| 22B | 마진 정책 | [req-margin-policy.md](req-margin-policy.md) | `spec-margin-policy.md`(계약) | **지음** (`/admin2/margin-policy` · ADM-PRC-020 · 확인자 2차 검증 결함 0 · 커밋 `a4d5d44` · 메뉴 연결 `879ee61` · 셸 CSS 특정성 사고로 `.mp-link` 링크색이 본문색으로 보이던 결함 수정(커밋 `77121d6`+`fbb9b61`)) |
| 23 | 가격 이력 | [req-price-history.md](req-price-history.md) · [spec-price-history.md](../spec-price-history.md)(2026-08-15 「(신규)」 표기 정정) | — | **지음** — 구현 `/admin2/price-history`(커밋 `140a5ba`·`77dbbef`·`bdf7e7c`) · 검증 확인자 브라우저 실측 통과 3라운드(①7행 3종 판정·ref_id null 실값·401/400/404 경계·768px ②마이그레이션 0050 「비움」 표시 — DB↔DOM 5행 대조·new_price=0 실데이터로 0과 NULL 구분 확인 ③「부품 종류」 확인 중… 고정 결함 — 10ms 폴링 프레임 단위 캡처로 재발 0·정상 로딩 노출은 유지 확인) · 계약 정정 `8e35508` · 연결 `api/admin_nav.py` `91dd3a1` · 셸 CSS 특정성 사고 방어 수정 — `.ph-move`(커밋 `77121d6`+`fbb9b61`) |
| 23B | 판매가 재산정 | [req-reprice.md](req-reprice.md) | `spec-reprice.md`(계약 · 1a 안, 커밋 `82a55a1`) | **지음** (`/admin2/reprice` · **ADM-PRC-050** — ID·경로 대조 완료(spec-reprice.md가 남겨 둔 "대조 필요"를 이걸로 해소 — `api/admin_ui_reprice.py`의 `APIRouter(prefix="/admin2")` + `@router.get("/reprice")`로 실측). **1a 안 확정**(회차 표 → 범위 → 미리보기 → 실행 한 줄기, 「지난 회차 기록」이 화면의 축이지 경고 배너가 아니다, 2026-08-15 사장님 결정). **확인자 검증 통과(2026-08-15)** — 「지난 회차」 표가 맨 앞·`note` 열 실재·간격 "1분 1.5초" 형식 확인, 금지 문구(「99.99%」·「세 번째도」 등) grep 전수 0건, **apply(7,174건)->undo 왕복 실완주(log_id 7720)로 구 화면의 핵심 결함("새로고침하면 되돌릴 방법이 사라진다") 해소 확인**, 되돌린 뒤 수치 원값과 완전 일치(7,279/6,899/275/105/0), 미로그인 401을 preview·apply·undo·페이지 네 곳 모두 확인(계약 §⑧ "무세션 실측 못 함" 항목 해소), 콘솔 에러 0·404 자원 0·외부 CDN 0. **nav 항목 자체가 없던 유일한 화면**이었는데 이번에 신설 + 메뉴 연결(`api/admin_nav.py` 커밋 `c6d662e` — 「판매가」 그룹 물리적 끝에 배치, 근거는 그 커밋의 6차 노트). ⚠ 남은 결함 하나(마크다운 별표 노출)는 다른 제작자가 수정 중이고 ⓐ류(문구 렌더링)라 연결을 막지 않았다 — **2026-08-28 기록자 정정: 그 결함은 같은 날 안에 해소됐다**(커밋 `635ee75`, 「서버 note 의 마크다운 볼드가 별표 그대로 노출되던 결함 수정」 — `mdBold()`가 `esc()`로 전체 이스케이프한 뒤 `**text**`만 `<strong>`으로 바꾼다. 확인법: `grep -n "function mdBold" templates/admin/reprice.html.j2`). 셸 CSS 특정성 사고로 `.rp-link` 링크색이 본문색으로 보이던 결함 수정(커밋 `77121d6`+`fbb9b61`)) |

## 6. 인계 · 성과

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 24 | 쇼핑몰 동기화 | [req-mall-sync.md](req-mall-sync.md) | `spec-mall-sync.md`(계약 · 커밋 `6f75d49` 2026-08-15 01:30 — 이 목차의 최종 편집(`08cfe9e` 16:25)보다 먼저 커밋됐는데 반영이 안 됐었다) | **지음** (`/admin2/mall-sync` · 라우트 커밋 `0eaa890` · 템플릿 커밋 `82a55a1` · 콘텐츠가 스크롤 수단 없이 잘리던 결함 수정(배너~각주까지 한 덩어리로 스크롤, 커밋 `f3cec63`) · 확인자 재검증 통과 — ⚠ 부작용 하나 남음(표 헤더 sticky 무력화, 작업 #51 · 확인자 판정 「화면 기능은 정상, 배포를 막을 사유 아님」) · 메뉴 연결 `9fdae6d` · ⚠ 셸 CSS 특정성 사고로 「판매가 관리에서 열기 →」 버튼(`.ms-btn-primary`) 글자색이 배경과 같아(대비 1.00:1) 안 보이던 결함 수정(대비 14.26:1, 커밋 `77121d6`+`fbb9b61` — 사장님 신고 원 화면은 swap-click-logs, 이 목차 17행 참조)) |
| 25 | 인계 기록 | [req-handoff-log.md](req-handoff-log.md) | `spec-handoff-log.md`(계약 · 커밋 `6f75d49` 2026-08-15 01:30 — 이 목차의 최종 편집(`08cfe9e` 16:25)보다 먼저 커밋됐는데 반영이 안 됐었다) | **지음** (`/admin2/handoff-log` · 라우트·템플릿 커밋 `82a55a1` · 확인자 재검증 통과(결함 없음) · 메뉴 연결 `9fdae6d` · ⚠ 셸 CSS 특정성 사고로 세션 이동 버튼(`.hl-navbtn`) 글자색이 배경과 같아(대비 1.00:1) 안 보이던 결함 수정(대비 14.26:1, 커밋 `77121d6`+`fbb9b61` — 사장님 신고 원 화면은 swap-click-logs, 이 목차 17행 참조)) |
| 26 | 유입 성과 | [req-funnel-performance.md](req-funnel-performance.md) | `spec-funnel.md`(계약 · 1a 안) | **지음** (경로 `/admin2/funnel-performance` — spec-funnel.md의 「가칭」 그대로 확정 표기를 따른다. **ADM-HND-030 후보 — 화면 ID는 여전히 미배정**(spec-funnel.md 자신이 명시. ID 미정이 메뉴 연결을 막지는 않는다). 커밋 `adb6d4d` · 확인자 재검증 통과(하네스 통보 2026-08-15) · 메뉴 연결 `6b3d637`) |

## 7. AI 관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 27 | **작업 현황판** | [req-dash.md](req-dash.md) | `dc-dash.html` | **지음**(`/admin2/dash` · ADM-AI-010 · UX-25 단일안. **2026-08-28 기록자 정정 — 2026-08-15에 「대기」를 「작업 중」으로 한 번 고쳤는데, 그새 재구축 자체가 끝나 있었다.** 재구축 커밋 `92e60f3`(2026-08-15, 「작업 현황판 재구축 + 팀원 한글 매핑 누락 조기 발견 장치」) 이후로도 흐름 압축·서버측 진행 표시(`e2cac70`, 2026-08-27)까지 계속 붙었다. 확인법: `git log --oneline -- templates/admin/dash.html.j2`) |
| 28 | 웹 사양 채움 | [req-spec-fill.md](req-spec-fill.md)(2026-08-15 전면 재작성 — 구 [방향 제안](../spec-fill-ui-direction-2026-08-13.md) — 폐기) | `spec-spec-fill.md`(계약 · 1a 안) | **지음** (`/admin2/spec-fill` · **ADM-AI-020**. ⚠ admin2 화면 중 유일하게 Phoenix 벤더를 실제 로드하던 화면 — 2026-08-14 18:40 지어짐, 그 4시간59분 뒤 Phoenix 금지 확정. **2026-08-15 승인 디자인(1a·실행 원장 중심) 도착, 재구축** — 실측: `api/admin_ui_spec_fill.py`·`templates/admin/spec_fill.html.j2` 커밋 `04a99dc`(그 커밋 메시지 자신은 당시 "재구축 중(제작 착수, 확인자 검증 전)"이라 적었다). 같은 물결 사장님 확정 셋: ①실행 수단=사람 없이 도는 작업 ②대상 필드=`cooler_tdp` 하나 ⑤승인 경로=이미 개방(커밋 `e84d61f`) — 나머지 ③④⑥은 미정(req-spec-fill.md 참조). **⚠ 「승인 경로 개방」과 「화면 재구축 완료」는 다른 사실이다 — 섞지 않는다.** ⚠⚠ **해소(2026-08-15, 기록자 6차)** — 커밋 `04a99dc`의 1a 버전이 "검증 전인데 메뉴에 이미 노출돼 있다"는 우려를 남겨 뒀었다(admin_nav.py 5차 노트 — 그때는 이 화면의 href를 새로 만들지도 끊지도 않고 범위 밖으로 판단해 하네스 보고에만 남겼다). **그 뒤 확인자 재검증이 통과했다** — `review_pending_empty` 렌더 · DOM 순서 · `scrollLeft` 리셋 셋 다 해소 확인, 47.6%→100%. 메뉴 연결은 이번에 새로 한 것이 없다(기존 href 그대로 — 검증이 뒤늦게 노출을 따라잡았을 뿐이다). 셸 CSS 특정성 사고로 `.sf-src-link` 링크색·밑줄이 함께 죽어 있던 결함 수정(커밋 `77121d6`+`fbb9b61`)) |
| 28B | 팝콘톡 응답 패턴 | [req-talk-patterns.md](req-talk-patterns.md) | `dc-talk-patterns.html`(1b「목록 전면」 확정본) · `dc-talk-patterns-1b.html` | **지음**(2026-08-25 기록자 신규 등재 — 이 목차에 행 자체가 없었다. `/admin2/talk-patterns` · **ADM-TLK-010(가칭)** · 결정 A-95·A-96 · 커밋 `a70c919`(2026-08-22, 라우트·템플릿) · `api/admin_talk_patterns.py`가 실데이터 API를 낸다. **위치는 nav 실제 순서를 따라 28과 29 사이에 끼웠다**(같은 관례를 쓴 20B·22B·23B 참조 — 뒤 섹션 전체 renumbering은 안 한다). 화면 자체의 `screen_id`는 코드가 아직 "가칭"으로 적어 뒀지만(`api/admin_ui_talk_patterns.py` 상단 주석), **라우트·템플릿·메뉴 연결은 이미 끝나 있다**(`api/admin_nav.py`의 `counts()`가 이 항목을 포함해 `total=41 · new=41 · todo=0`을 낸다 — 2026-08-25 재확인). 확인자 검증 여부는 이 목차 갱신 시점 기준 별도 통보 기록을 찾지 못해 **확인 필요**로 남긴다) |
| 29 | **AI 작업 설정** | [req-ai-task-settings.md](req-ai-task-settings.md) | `dc-ai-task-settings.html` | **지음** (`/admin2/ai-task-settings`) |
| 30 | **AI 연동 설정** | [req-ai-integration.md](req-ai-integration.md) | `dc-ai-integration.html` | **지음** (`/admin2/ai-integration`) |
| 31 | **AI 사용량 · 비용** | [req-ai-usage-cost.md](req-ai-usage-cost.md) | `dc-ai-usage-cost.html` | **지음** (`/admin2/ai-usage-cost`) |
| 32 | **AI 응답 기록** | [req-ai-response-log.md](req-ai-response-log.md) | `dc-ai-response-log.html` | **지음** (`/admin2/ai-response-log`) |
| 33 | **운영 도우미 설정** | [req-ops-assistant.md](req-ops-assistant.md) | `dc-ops-assistant.html` | **지음** (`/admin2/ops-assistant`) |

## 8. 시스템

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 34 | **오픈 단계 설정** (구 「운영 전환 설정」) | [req-ops-switch.md](req-ops-switch.md) | `dc-ops-stage.html` | **지음** (`/admin2/ops-settings` · A-34) |
| 35 | **운영자 · 권한** | [req-operators-roles.md](req-operators-roles.md) | `dc-operators-roles.html` | **지음** (`/admin2/operators`) |
| 36 | **작업 기록** | [req-activity-logs.md](req-activity-logs.md) | `dc-activity-logs.html` | **지음** (`/admin2/activity-logs`) |
| 37 | **엑셀 다운로드 관리** | [req-excel-export.md](req-excel-export.md) | `dc-excel-export.html` | **지음** (`/admin2/excel-exports`) |

---

## 디자인 원안 (사장님 확정본)

| # | 화면 | 파일 | 구축 |
|---|------|------|------|
| 2 | 상품 분류 관리 | [dc-product-category.html](../dc-product-category.html) | 지음 |
| 4 | 상품 분류 매핑 | [dc-product-category-map.html](../dc-product-category-map.html) | 지음 |
| 10 | 상품 사양 검수 | [dc-review-screen.html](../dc-review-screen.html) | 지음 |
| 29 | AI 작업 설정 | [dc-ai-task-settings.html](../dc-ai-task-settings.html) | 지음 |
| 30 | AI 연동 설정 | [dc-ai-integration.html](../dc-ai-integration.html) | 지음 |
| 31 | AI 사용량 · 비용 | [dc-ai-usage-cost.html](../dc-ai-usage-cost.html) | 지음 |
| 32 | AI 응답 기록 | [dc-ai-response-log.html](../dc-ai-response-log.html) | 지음 |
| 33 | 운영 도우미 설정 | [dc-ops-assistant.html](../dc-ops-assistant.html) | 지음 |
| 34 | 오픈 단계 설정 | [dc-ops-stage.html](../dc-ops-stage.html) | 지음 |
| 35 | 운영자 · 권한 | [dc-operators-roles.html](../dc-operators-roles.html) | 지음 |
| 36 | 작업 기록 | [dc-activity-logs.html](../dc-activity-logs.html) | 지음 |
| 37 | 엑셀 다운로드 관리 | [dc-excel-export.html](../dc-excel-export.html) | 지음 |
| 7 | 조립 호환 지도 **(v2 · 정본)** | [dc-build-map-v2.html](../dc-build-map-v2.html) | 지음 · UX-20 → 클릭 고정 · 메뉴 연결 (2026-08-28 기록자 정정 — 위 §3 목차와 같은 자기모순. 근거는 그 행 참조) |
| 7 | 조립 호환 조감도 (3안 비교본 — v2로 대체됨) | [dc-build-map-3안.html](../dc-build-map-3안.html) | 참고용 |
| 1 | 대시보드 **(3안 비교본)** | [dc-dashboard-3안.html](../dc-dashboard-3안.html) | 지음 · UX-22 → 1b · 메뉴 연결 (2026-08-28 기록자 정정 — 위 §1 목차와 같은 자기모순. 근거는 그 행 참조) |
| 3 | 상품 관리 **(3안 비교본)** | [dc-products-3안.html](../dc-products-3안.html) | 지음 · UX-23 → 1a · 메뉴 연결 (2026-08-28 기록자 정정 — 위 §2 목차와 같은 자기모순. 근거는 그 행 참조) |
| 5 | 상품 일괄 등록 | [dc-product-bulk-import.html](../dc-product-bulk-import.html) | 지음 · UX-21 → 1b · 메뉴 연결 |
| 6 | 삭제 상품 조회 **(2안 + 빈 상태)** | [dc-product-deleted-2안.html](../dc-product-deleted-2안.html) | 지음 · UX-26 → 1b + 빈 상태 1c · 메뉴 연결 |
| 8 | 조립 사양 표준 **(2안 비교본)** | [dc-spec-standard-2안.html](../dc-spec-standard-2안.html) | 지음 · UX-24 → **1a** · 메뉴 연결 (2026-08-28 기록자 정정 — 위 §3 목차와 같은 자기모순. 근거는 그 행 참조) |
| 9 | 상품 사양 정의 **(2안 비교본)** | [dc-spec-field-defs-2안.html](../dc-spec-field-defs-2안.html) | 지음 · UX-27 → 1a · 메뉴 연결 |
| 11 | 조립 호환 규칙 **(2안 비교본)** | [dc-compat-rules-2안.html](../dc-compat-rules-2안.html) | 지음 |
| 20B | 재고 입고 | [dc-stock-inbound.html](../dc-stock-inbound.html) · [핸드오프 README](../dc-stock-inbound-README.md) | 지음 · 1b 골격 + 1a 목록 확정 혼합 · 확인자 3차 결함 0 · 메뉴 연결(2026-08-18) — ⚠ **이 표에서 원안 파일이 서브에이전트 손으로 받아진 첫 사례**(아래 「계약 요약」 절 정정 참조) |
| 27 | 작업 현황판 **(단일안)** | [dc-dash.html](../dc-dash.html) | 지음 · UX-25 · 메뉴 연결 (2026-08-16 기록자 정정 — 위 §7 목차가 2026-08-15에 이미 「대기 아니라 작업 중」으로 스스로 고쳤는데 이 표만 옛 값 「재구축 대기」를 그대로 들고 있었다. 재확인: `/admin2/dash` curl 200 · `data-screen-id="ADM-AI-010"` 실재 — 라우트가 이미 있으므로 「대기」(라우트 없음)는 아니다. **2026-08-28 재정정** — 「작업 중」도 그새 낡았다. 위 §7 목차와 같은 자기모순, 근거는 그 행 참조) |
| 28B | 팝콘톡 응답 패턴 | [dc-talk-patterns.html](../dc-talk-patterns.html) · [dc-talk-patterns-1b.html](../dc-talk-patterns-1b.html) | 지음 · 1b「목록 전면」 확정(2026-08-22) · 메뉴 연결(2026-08-25 재확인, `api/admin_nav.py counts()` 실행 — `todo=0`에 이미 포함) · **2026-08-25 기록자 신규 등재**(위 §7 목차·이 표 둘 다 행이 없었다) |

### 계약 요약으로 전달된 승인 디자인

**원안은 Claude Design 서버에 있고, 팀에는 계약 요약(`docs/design/spec-*.md`)으로 전달한다.**
`DesignSync` 가 서브에이전트에서 막혀 있어(2026-08-14 확인) 제작자가 원안을 직접 못 받기
때문이다 — **위 `dc-*.html` 과 성격이 다른 것이 아니라 전달 경로만 다르다.** 그 제약이
풀리면 이 표는 위 표로 합쳐진다.

> ⚠ **위 문단의 「막혀 있어」는 2026-08-18 로 낡았다 — 지우지 않고 정정한다(CANON §5).**
> 그날 general-purpose 서브에이전트가 `DesignSync get_file` 로 `재고 입고.dc.html` 을 받아
> `docs/design/dc-stock-inbound.html` 로 저장했다(`truncated:false` · 하네스 확정).
> **새 권한이 아니라, 이미 사장님 확정이던 「제작자·계약자가 원안을 직접 가져온다」가
> 도구 제약으로 성립하지 못하던 것이 성립하게 됐다는 사실 기록**이다(`CLAUDE.md`
> §팀 운용 「못 넘기는 것 — 둘 → 하나」 · 절차는 `docs/design/MAKER-CHECKLIST.md` §1).
> **두 표를 합치는 것은 아직 하지 않았다** — 아래 표의 화면 대부분은 여전히 계약 요약만
> 받은 상태이고, 합치려면 화면마다 원안 파일이 실제로 있는지 재야 한다. **재고 입고가
> 「원안 파일이 저장소에 있는」 첫 사례**라 그 행만 위 표에 세웠다.
> **확인법**: `ls docs/design/dc-*.html` 로 원안 파일이 실재하는 화면을 세고, 위 표와
> 대조한다. 어느 세션에서 `DesignSync` 가 다시 막히면 그때만 하네스 경유로 돌아간다.

| # | 화면 | 계약 요약 | 구축 |
|---|------|----------|------|
| 12 | 용도별 최소 사양 | [spec-usage-floors.md](../spec-usage-floors.md) | 지음 · UX-29 → 두 안 참고 · 메뉴 연결(2026-08-16) |
| 13 | 부품 등급 관리 | [spec-part-grade.md](../spec-part-grade.md) | 지음 · UX-30 → 1a + 1b 우측 입력 · 메뉴 연결 (2026-08-16 기록자 정정 — 위 §2 목차·`api/admin_nav.py`는 이미 「지음」인데 이 표만 「구축 중」이었다. 재확인: `/admin2/part-grade` dev-login curl 200 · 응답 본문에 `data-screen-id="ADM-ENG-050"` 실재) |
| 14 | 추천 기준 보기 | [spec-policy-weights.md](../spec-policy-weights.md) | 지음 · UX-31 → 1a · 조회 전용 · 메뉴 연결 (2026-08-16 기록자 정정 — 위와 같은 자기모순. 재확인: `/admin2/policy-weights` curl 200 · `data-screen-id="ADM-ENG-020"` 실재) |
| 15 | 추천 가능 재고 현황 | [spec-candidate-pool.md](../spec-candidate-pool.md) | 지음 · UX-32 → 1a · 조회 전용 · 메뉴 연결 |
| 16 | 견적 상담 기록 | [spec-consult-sessions.md](../spec-consult-sessions.md) | 지음 · UX-33 → 1a + 우측 서랍 · 메뉴 연결 (2026-08-16 기록자 정정 — 위와 같은 자기모순. 재확인: `/admin2/consult-sessions` curl 200 · `data-screen-id="ADM-ORD-010"` 실재) |
| 17 | 부품 교체 · 클릭 기록 | [spec-swap-click-logs.md](../spec-swap-click-logs.md) | 지음 · 메뉴 연결 (2026-08-15 신규 등재 — 커밋 `c75656e`이 이 목차 최종 편집보다 먼저였는데 빠져 있었다. 그 뒤 확인자 재검증 통과 · 메뉴 연결) |
| 18 | 공급처 | [spec-suppliers.md](../spec-suppliers.md) | 지음 · 1b 안 · 메뉴 연결 |
| 19 | 매입 견적(용산) | [spec-sourcing.md](../spec-sourcing.md) | 지음 · 1a 안 · 메뉴 연결 |
| 20 | 단가표 반영 | [spec-price-import.md](../spec-price-import.md) | 지음 · 1b 안 · 메뉴 연결 |
| 21 | 판매가 관리 | [spec-sale-price.md](../spec-sale-price.md) | 지음 · 메뉴 연결 (2026-08-15 신규 등재 — 커밋 `6f75d49`이 이 목차 최종 편집보다 먼저였는데 빠져 있었다. 그 뒤 확인자 재검증 통과 · 메뉴 연결) |
| 23B | 판매가 재산정 | [spec-reprice.md](../spec-reprice.md) | 지음 · 1a 안 · 검증 통과 · 메뉴 연결(`c6d662e`) |
| 24 | 쇼핑몰 동기화 | [spec-mall-sync.md](../spec-mall-sync.md) | 지음 · 메뉴 연결 (2026-08-15 신규 등재 — 커밋 `6f75d49`이 이 목차 최종 편집보다 먼저였는데 빠져 있었다. 그 뒤 스크롤 결함 수정(커밋 `f3cec63`) · 확인자 재검증 통과 · 메뉴 연결) |
| 25 | 인계 기록 | [spec-handoff-log.md](../spec-handoff-log.md) | 지음 · 메뉴 연결 (2026-08-15 신규 등재 — 커밋 `6f75d49`이 이 목차 최종 편집보다 먼저였는데 빠져 있었다. 그 뒤 확인자 재검증 통과 · 메뉴 연결) |
| 26 | 유입 성과 | [spec-funnel.md](../spec-funnel.md) | 지음 · 1a 안 · 화면 ID 미배정 · 메뉴 연결 |
| 28 | 웹 사양 채움 | [spec-spec-fill.md](../spec-spec-fill.md) | 지음 · 1a 안 · 검증 통과(2026-08-15) · 메뉴 연결(기존 href) |

**7번은 완성본이 아니라 「3안 비교본」이다.** 지도형(1a)·진단형(1b)·매트릭스형(1c) 셋이
한 캔버스에 있다. 사장님이 **셋을 다 탭으로 두고 운영자가 고르게** 하기로 확정했다(UX-20).

**1번도 「3안 비교본」이다.** 큐 목록형(1a)·카드 그리드형(1b)·브리핑형(1c) 셋이 한 캔버스에
있고, 셋은 **「지금 할 일」의 표현 방식만** 다르다. 사장님이 **1b 카드 그리드형**으로 확정했다
(UX-22). 조감도와 달리 여기서는 **하나만 고른다** — 대시보드는 첫 화면이라 선택지를 주면
오히려 판단을 미루게 된다.

> **`UX-26` 은 2026-08-14 결정 로그에 세웠다.** 한때 목차만 이 번호를 인용하고 로그에는
> 항목이 없었다(기록자 실측으로 발견 · 하네스가 기록을 빠뜨린 것). **결정 ID 를 인용하면
> 로그에 그 항목이 서 있는지 함께 확인한다** — 가리키는 곳이 없는 번호는 중복된 번호만큼
> 나쁘다. 둘 다 「믿을 수 없는 인용」이라는 같은 병이다.

## 이 목차를 쓰는 법 (하네스 규약)

사장님이 화면 UI를 공유하실 때마다, 하네스는 **그 화면의 정의서 링크와 다음 차례
두세 개를 함께** 올린다. 사장님이 위로 스크롤해 찾지 않게 하기 위해서다
(2026-08-13 사장님 지시).
