# Phoenix 템플릿 지도 — 어디서 무엇을 가져오는가

**원본:** `D:\phoenix_Templet\` · Phoenix **v1.22.0** (Bootstrap 5 관리자 템플릿)
**작성:** 2026-07-30 (슬라이스 101) · 갱신 시점: 템플릿을 교체하거나 자산을 새로 가져올 때

---

## 이 문서를 만든 이유

관리자 화면을 새로 만들 때마다 **옆 화면을 베껴 왔다.** 원본에 무엇이 있는지 몰랐기 때문이다.
그 대가가 실제로 나왔다:

| 사고 | 원인 |
|---|---|
| 세 화면의 디자인이 하나도 안 먹었다 (슬라이스 100) | `assets/css/theme.css`를 참조 — **템플릿엔 있지만 우리 리포엔 없는 파일**. 404 스타일시트를 브라우저가 빈 시트로 만들어 조용히 넘어갔다 |
| 비밀번호 모달이 조용히 열리지 않았다 (슬라이스 100) | lean 화면이 `bootstrap.min.js`를 안 실었는데 `bootstrap.Modal`을 썼다 |
| 한 화면에 다른 화면이 통째로 붙어 있었다 (슬라이스 87·88) | 셸을 손으로 복사하다 생긴 붙여넣기 사고 |

**이 문서는 마크업을 베껴 담지 않는다 — 좌표만 적는다.** 베끼면 그 사본이 또 어긋난다
(슬라이스 89에서 문서 셋이 서로 다른 말을 하던 것과 같은 이유).

---

## 결정 트리 — 무엇이 필요한가에 따라 원본이 다르다

```
새 화면에 셸(좌측 메뉴·상단바)이 필요하다
    -> 템플릿이 아니라 **우리 화면**을 원본으로 쓴다 (activity-logs.html, 575줄 — 가장 작다)
       이유: 템플릿 pages/starter.html은 2,778줄이고 좌측 메뉴가 **Phoenix 데모 메뉴 전체**다.
       우리 셸은 거기서 파생해 메뉴만 우리 29화면으로 갈아낀 것이다.

컴포넌트(표·폼·배지·모달·탭…)의 올바른 마크업이 필요하다
    -> 템플릿 `public/modules/**` 에서 찾는다 (아래 카탈로그)

새 vendor 라이브러리(날짜 선택·차트·에디터…)가 필요하다
    -> **먼저 아래 자산 대조표를 본다.** 우리에게 없으면 템플릿에서 복사해 온다.
       복사하지 않고 참조만 하면 404이고, 브라우저는 조용히 넘어간다.
```

---

## ⚠️ 자산 대조표 — 우리가 가진 것 vs 템플릿에만 있는 것

**이 표를 보지 않고 파일명을 적으면 오늘의 404가 반복된다.**

### CSS (`assets/css/`)

| 파일 | 템플릿 | 우리 | 비고 |
|---|---|---|---|
| `theme.min.css` | ✅ | ✅ | **이것을 쓴다** |
| `user.min.css` | ✅ | ✅ | 우리 규칙이 0개인 빈 파일 — 커스터마이즈 자리 |
| `theme.css` (비압축) | ✅ | ❌ | **참조 금지** — 슬라이스 100의 404 원인 |
| `user.css` (비압축) | ✅ | ❌ | 참조 금지 |
| `theme-rtl*.css` `user-rtl*.css` | ✅ | ❌ | RTL 전용. 우리 29화면이 `<link>`로 참조해 **매번 404가 난다**(무해하지만 소음) |
| `*.css.map` | ✅ | ❌ | 소스맵 — 필요 없다 |

### Vendors (`vendors/`) — 템플릿 41개 중 우리는 10개

**우리에게 있는 것:**
`anchorjs` `bootstrap` `dayjs` `feather-icons` `fontawesome` `is` `list.js` `lodash` `popper` `simplebar`

**템플릿에만 있는 것(쓰려면 복사해 와야 한다):**
`bigpicture` `chart` `choices` `countup` `dhtmlx-gantt` `draggable` `dropzone` `echarts`
`flatpickr` `frappe-gantt` `fullcalendar` `glightbox` `imagesloaded` `isotope-layout`
`isotope-packery` `leaflet`(+markercluster, tilelayer.colorfilter) `lottie` `mapbox-gl`
`nouislider` `overlayscrollbars` `plyr` `prism` `rater-js` `sortablejs` `swiper` `tinymce` `typed.js`

> 쓸 만한 후보 몇 가지: **`flatpickr`**(날짜 선택 — 지금은 `<input type=date>`),
> **`choices`**(검색되는 셀렉트 — 공급처·상품 고르기에 유용),
> **`echarts`**(차트 — 대시보드가 `<canvas data-chart>` 자리를 비워 두고 있다),
> **`dropzone`**(파일 업로드 — 단가표·카탈로그 업로드).
> 도입은 **자산 복사 + 화면에서 `<script>` 로드**까지 해야 끝난다.

---

## 화면 카탈로그 (템플릿 `public/`, HTML 222개)

| 경로 | 개수 | 무엇 |
|---|---|---|
| `modules/components/**` | 30 | **컴포넌트 원본** — 가장 자주 볼 곳 |
| `modules/forms/**` | 16 | 입력 폼 (기본 + 고급) |
| `modules/utilities/**` | 18 | 여백·색·그리드·타이포 유틸리티 클래스 예시 |
| `modules/echarts/**` | 10 | 차트 종류별 예시 |
| `modules/tables/**` | 3 | 표 (기본 · 고급 · 일괄선택) |
| `modules/icons/**` | 3 | feather · font-awesome · unicons |
| `apps/**` | 76 | 완성된 앱 화면(전자상거래·CRM·이메일·칸반 등) — **레이아웃 참고용** |
| `dashboard/**` | 4 | 대시보드 변형 |
| `pages/**` | 34 | 인증·에러·FAQ·랜딩·가격·타임라인·`starter.html` |
| `documentation/**` | 12 | 템플릿 자체 문서 |
| `demo/**` | 10 | 데모 |

### 자주 쓸 컴포넌트 좌표

`public/modules/components/` 아래:

| 필요한 것 | 파일 |
|---|---|
| 배지 (우리가 `badge-phoenix`로 쓰는 것) | `badge.html` |
| 카드 | `card.html` |
| 모달 (비밀번호 변경·중복 확인에 쓴다) | `modal.html` |
| 탭·필터 pill (검수 큐의 사양별 필터) | `navs-and-tabs/navs.html`, `.../tabs.html` |
| 토스트 (우리는 직접 만든 `__t`를 쓴다) | `toast.html` |
| 진행바 (용도 하한의 후보 수 막대) | `progress-bar.html` |
| 아코디언·접기 | `accordion.html`, `collapse.html` |
| 드롭다운 | `dropdown.html` |
| 페이지네이션 (검수 큐·상품 목록) | `pagination.html` |
| 스피너·플레이스홀더 (불러오는 중) | `spinners.html`, `placeholder.html` |
| 아바타 (내 정보의 이니셜 원형) | `avatar.html` |
| 툴팁·팝오버 | `tooltips.html`, `popovers.html` |
| 오프캔버스 (우측 작업 패널) | `offcanvas.html` |

`public/modules/forms/` 아래:

| 필요한 것 | 파일 |
|---|---|
| 기본 입력·라벨 | `basic/form-control.html`, `basic/floating-labels.html` |
| 체크박스·라디오·스위치 (운영 전환 설정) | `basic/checks.html` |
| 셀렉트 | `basic/select.html` · 검색되는 셀렉트는 `advance/advance-select.html` |
| 입력 그룹 (단위 붙은 숫자 — 용도 하한) | `basic/input-group.html` |
| 유효성 표시 | `validation.html` |
| 날짜 선택 | `advance/date-picker.html` (vendor `flatpickr` 필요) |
| 파일 업로드 | `advance/file-uploader.html` (vendor `dropzone` 필요) |
| 단계 마법사 (드라이런 → 확인 → 적용) | `wizard.html` |

`public/modules/tables/`:

| 필요한 것 | 파일 |
|---|---|
| 기본 표 | `basic-tables.html` |
| 정렬·검색·페이지네이션 표 | `advance-tables.html` (vendor `list.js` — 우리에게 있다) |
| 일괄 선택 (검수 큐 일괄 확정) | `bulk-select.html` |

---

## 템플릿의 빌드 시스템은 쓰지 않는다

```
src/pug  src/scss  src/js  +  gulpfile.js  package.json
```

템플릿은 **pug·scss를 gulp로 빌드**하는 구조다. 우리 프로젝트는 **npm·빌드 시스템 금지**이므로
(CLAUDE.md 명령 관례) 이 파이프라인을 도입하지 않는다.

즉 **`public/`(빌드 산출물)에서만 가져온다.** `src/`는 참고 소스로만 본다 —
scss 변수명이 궁금할 때(`src/scss/_variables.scss` 등) 정도다.

테마 색을 바꾸려면 `theme.min.css`를 고치는 대신 **`user.min.css`에 덮어쓰기**를 넣는다
(템플릿을 새 버전으로 교체할 때 우리 변경이 살아남는다).

---

## 우리 화면이 템플릿과 다른 점 (의도된 차이)

| 항목 | 템플릿 | 우리 | 이유 |
|---|---|---|---|
| 좌측 메뉴 | Phoenix 데모 전체(222화면) | 우리 29화면 · 5그룹 | 우리 도메인 |
| 언어 | 영문 | 한국어 (`lang="ko"`) | 운영자가 한국어를 쓴다 |
| 아이콘 | feather 단색 | **Streamline Ultimate Color** + feather 병용 | 2026-07-16 사용자 지시(단색 정책 폐기) |
| 하단 채팅 | 영문 고객지원 데모 | **운영 도우미**(`shared/admin-helper.js`) | 슬라이스 64 — 우리 관리자가 볼 물건이 아니었다 |
| 우측 패널 | Theme Customizer | **운영자 작업 패널**(`shared/admin-panel.js`) | 슬라이스 61 |
| 색·서체 | Phoenix 기본 | Popcorn Light(D-07) 토큰 | `design-system/tokens.css`가 단일 원천 |

**아이콘·채팅·패널은 되돌리지 않는다** — 템플릿에서 새 화면을 가져올 때 그 부분은 우리 것으로 갈아낀다.

---

## 새 관리자 화면을 만드는 절차 (요약)

1. **셸**: `mockups/admin/activity-logs.html`을 복사한다(템플릿이 아니다).
   - `1~264행` = head + 좌측 메뉴 + 상단바 + `<div class="content">`
   - `277행~끝` = `</div>` + 검색 모달 + 셸 스크립트 + 지원 위젯 + `</main>` + vendor·shared 스크립트
   - **`278~327행`은 그 화면 전용 스크립트다** — 새 화면에서는 내 것으로 바꾼다
2. `<title>` · `<body data-screen-id=... data-domain=...>` · 좌측 메뉴의 `nav-link active`를 바꾼다
3. 컴포넌트가 필요하면 위 카탈로그에서 좌표를 찾아 **원본 마크업을 확인하고** 가져온다
4. 새 vendor가 필요하면 **자산 대조표를 보고 복사**한 뒤 `<script>`를 싣는다
5. 회귀 `[30] 화면 자산` 검사가 **참조한 CSS·JS가 실제로 있는지** 확인한다 — 404를 이 검사가 막는다

---

## 정본 관계

- **디자인 토큰**(색·서체·라운드)의 단일 원천은 `design-system/tokens.css`다. 템플릿 CSS가 아니다.
- **화면 ID·도메인** 규약은 `docs/decisions/admin-identity.md`.
- 이 문서는 **"어디에 무엇이 있나"**만 답한다. 규칙은 `CLAUDE.md`, 결정은 `decision-log.md`.
