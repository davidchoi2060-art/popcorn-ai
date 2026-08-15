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

## ⚡ 붙이는 법 — 좌표보다 이게 중요하다 (2026-08-05 실측)

> 2026-08-05 실사에서 **템플릿 컴포넌트를 실제로 초기화하는 화면이 0개**인 것이 드러났다.
> 원인 중 하나가 이 문서였다 — "어디에 있나"만 적혀 있고 **"어떻게 붙이나"**가 없었다.
> 전수 실사는 `phoenix-audit-2026-08-05.md`.

### 규칙 0 — 컴포넌트는 선언형이다

`phoenix.js`가 `data-*` 속성을 보고 알아서 붙인다. **JS를 쓰지 마라. 속성을 써라.**

```
data-list  data-bulk-select  data-choices  data-echarts  data-countup
data-flatpickr  data-nouislider  data-sortable  data-copy  data-password  …28종
```

### 규칙 1 — **initXxx는 `docReady` 때 딱 한 번 돈다**

우리 화면은 대부분 fetch 응답으로 표를 **나중에** 그린다. 그 시점엔 DOM이 없으므로
자동 초기화가 닿지 않는다. **렌더 직후 우리가 직접 붙여야 한다.**

전역에 노출된 것은 둘뿐이다:

```js
window.List                  // vendors/list.js
window.phoenix.BulkSelect    // phoenix.js  (window.phoenix = { utils, BulkSelect })
```

`treeviewInit` · `listInit` · `bulkSelectInit` 자체는 노출되지 않는다.

```js
var LIST = null, BULK = null;
function wireComponents(){
  var host = document.getElementById("prodList");
  if(window.List && host){
    if(!LIST){ LIST = new window.List(host, {valueNames:[...]}); }
    else { LIST.reIndex(); }        // list.js 에 destroy 가 없다
  }
  var head = document.getElementById("bulkHead");
  if(window.phoenix && window.phoenix.BulkSelect && head){
    head.checked = false; head.indeterminate = false;
    BULK = new window.phoenix.BulkSelect(head); BULK.init();
  }
}
```

### 규칙 2 — 표에 검색·정렬 붙이기 (`data-list`)

```html
<div id="prodList" data-list='{"valueNames":["code","name","price"]}'>
  <table>
    <thead><tr>
      <th class="sort" data-sort="code">코드</th>
      <th class="sort text-end" data-sort="price">가격</th>
    </tr></thead>
    <tbody class="list" id="prodBody">
      <tr><td class="code">…</td><td class="price text-end">…</td></tr>
    </tbody>
  </table>
</div>
```

- `valueNames` · `data-sort` · `<td class>` **셋이 같은 이름**이어야 한다. 하나만 어긋나도 그 컬럼이 조용히 죽는다.
- `<tbody class="list">` 가 없으면 list.js가 항목을 못 찾는다.
- **서버 페이지네이션과 공존한다.** `page`/`pagination` 옵션을 넣지 마라 — 현재 페이지를 또 쪼갠다.
- **날짜 컬럼엔 `sort`를 붙이지 마라** — 화면이 문자열로 그리면 문자열 정렬이 된다.

### 규칙 3 — 일괄 선택 (`data-bulk-select`)

```html
<input type="checkbox" id="bulkHead"
       data-bulk-select='{"body":"prodBody","actions":"bulk-actions","replacedElement":"bulk-replace"}'>
…
<tr><td><input type="checkbox" data-bulk-select-row='{"code":12345}'></td>…</tr>
```

컴포넌트가 하는 일은 **`actions`/`replacedElement` 의 `d-none` 토글뿐**이다. 다음은 우리 몫:

- **'선택 n건' 카운터가 없다** — `BULK.getSelectedRows().length` 로 직접 센다
- **선택 변경 이벤트가 없다** — tbody 위임으로 직접 듣는다
- **`body` id가 없으면 TypeError로 통째로 죽는다**(null 가드 없음). `actions`/`replacedElement`는 생략해도 안전
- **`deselectAll()` 은 '토글'이다** — 선택이 없을 때 부르면 액션바가 **오히려 나타난다.** 쓰지 말고 직접 클래스를 맞춰라
- `data-bulk-select-row` 값은 `JSON.parse` 된다 — `"2453"` 은 **숫자**가, `"0012"` 는 문자열이 된다. 타입을 고정하려면 객체로 감싸라

### 규칙 4 — 계층 트리 (`treeview`)

CSS(`theme.min.css`)와 JS(`treeviewInit`)가 **이미 우리 저장소에 있다.** 원본 마크업은
`apps/file-manager/grid-view.html:2442`.

```html
<ul class="treeview" id="catTree">
  <li class="treeview-list-item">
    <a data-bs-toggle="collapse" href="#node-1"><p class="treeview-text">
      <span class="fa-solid fa-folder treeview-icon"></span>부품<span class="treeview-badge">13,308</span></p></a>
    <ul class="collapse treeview-list show" id="node-1"> … </ul>
  </li>
  <li class="treeview-list-item">      <!-- 잎 -->
    <div class="treeview-item"><a class="flex-1 ps-2 ms-2" href="#!"><p class="treeview-text">…</p></a></div>
  </li>
</ul>
```

- **접힘/펼침은 100% Bootstrap collapse**다(위임 핸들러라 **동적 DOM에서도 된다**).
- `treeviewInit`이 하는 일은 `.treeview-row` prepend + 줄무늬 계산뿐. 동적 렌더면 그것만 우리가 대신한다.
- **`data-show="true"` 는 treeviewInit이 돌 때만 유효하다.** 동적이면 `class="collapse show"` 를 쓴다.
- **선택 상태 클래스가 없다** — 하이라이트는 우리가 만든다.
- `.treeview-list` 는 CSS가 없는 JS 훅이다. 빼면 조용히 죽는다.
- `treeview-row` 를 마크업에 직접 쓰지 마라(JS가 넣는다 — 동적일 때만 우리가 넣는다).

### 규칙 5 — vendor가 없으면 선언하지 마라

우리 vendor 10개: `anchorjs bootstrap dayjs feather-icons fontawesome is list.js lodash popper simplebar`

`data-choices`·`data-echarts`·`data-flatpickr`·`data-dropzone`·`data-sortable`·`data-countup`·
`data-nouislider`·`data-rater`·`data-calendar` 는 **vendor를 먼저 복사**해야 한다
(`D:\phoenix_Templet\public\vendors\<이름>` → `mockups/admin/vendors/`).
회귀 `[37]`이 "vendor 없는 훅을 선언하지 않는다"를 지킨다.

### 회귀가 지키는 것 — `[37] Phoenix 템플릿을 실제로 쓰는가`

treeview 마크업 · 자손 배지 · `scope=subtree` · `data-list` · 정렬 헤더 · `bulk-select` ·
동적 재부착 · vendor 없는 훅 금지 · **전체선택을 손으로 만든 화면 0개**.

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

## ⚠ 원본 좌표는 **전체 경로로 적는다** (사용자 지시 2026-08-11)

`apps/project-management/project-card-view.html` 처럼 상대 경로만 적으면
**어느 드라이브의 무엇인지** 알 수 없다. 이 저장소는 `E:\DEV\popcorn-ai` 이고
템플릿은 **다른 드라이브**에 있다. 주석·문서·커밋 어디에 적든 이렇게 쓴다:

    D:\phoenix_Templet\public\apps\project-management\project-card-view.html

## ⚠ 조립 호환 조감도(ADM-STD-020)는 **Phoenix 를 쓰지 않는다** (2026-08-11)

예외를 기록해 둔다. 첫 판은 Phoenix 조각(KPI 카드 · 카드뷰 · 리스트뷰)을 조립했는데,
같은 데이터를 네 번 말하면서 정작 「조감도」인 지도가 화면의 1/4 이었다.
**Phoenix 는 CRUD 화면에는 맞지만 「읽는 화면」을 담을 그릇이 없다** — 형식이 내용을 이겼다.

다시 만든 판은 사용자가 Claude 디자인으로 그린 원안을 옮긴 것이다(지도형·진단형·매트릭스형
3안을 탭으로 전환). `_layout.html.j2` 도 상속하지 않고 자체 셸을 그리되, 좌측 메뉴는
정본(`api/admin_nav.py`)을 그대로 싣는다.

  원안 : claude.ai/design · 22248237-152f-4f13-8201-54afca75ebe4 · `조립 호환 조감도.dc.html`

**이것은 규약의 예외이지 폐기가 아니다.** CRUD 화면은 계속 Phoenix 로 간다.
덧붙여 — Phoenix 가 싣고 있는 ECharts 는 full build 라 `graph`·`sankey`·`tree` 를
**전부 지원한다**. 예시 페이지에 없을 뿐이다(2026-08-11 확인).
  D:\phoenix_Templet\public\vendors\echarts\echarts.min.js  (1,029,203 bytes)

## ⭐ 재구축(`/admin2/*`) 화면을 만드는 절차 — 순서가 규약이다

> **사용자 확정 2026-08-09.** 이 순서를 뒤집지 마라.
> 아래 「새 관리자 화면을 만드는 절차」는 **기존 `/admin/*` 정적 화면**용이고,
> 재구축 화면은 이 절차를 쓴다.

```
① 콘텐츠 기획   이 화면이 답해야 할 질문과 담을 항목을 먼저 적는다
② 템플릿 검증   Phoenix 222화면에서 맞는 포맷을 찾는다 (하나로 안 되면 혼합)
③ 화면에 표출   원본 마크업을 그대로 옮기고 제목만 우리 것으로
```

**왜 이 순서인가** — 반대로 하면 **포맷이 내용을 지시한다.** 예쁜 대시보드를 먼저 보면
그 칸을 채우려고 데이터를 만들게 된다. 이 프로젝트가 `26,480` · `호환성 5종` ·
`645,000원`을 달고 있던 이유가 정확히 그것이다. **칸이 있어서 생긴 숫자였다.**

### ② 에서 포맷을 고르는 기준 — **개수가 아니라 도메인이다**

2026-08-09 실수에서 얻었다. 대시보드를 고를 때 **카드 수를 세어** `crm`(8칸)을 추천했다.
우리 항목이 8개라 딱 맞는다는 계산이었다. 사용자는 **「전자상거래」라는 도메인**으로
골랐고 그게 맞았다 — Phoenix 루트 `index.html` 이 곧 Ecommerce Dashboard 였고,
`Top coupons` → 게이트별 사유, `Paying vs non paying` → 견적 성립/불성립,
`Top regions by revenue` → 슬롯별 부품처럼 **패널 성격이 그대로 대응**됐다.

> **칸 수는 맞출 수 있지만 성격은 못 맞춘다.** 도메인이 같은 화면을 먼저 찾고,
> 칸이 남거나 모자란 건 그다음 문제다.

**혼합해도 된다**(사용자 결정). 한 화면으로 안 되면 다른 화면의 패널을 가져와 섞는다 —
같은 Phoenix 컴포넌트라 섞여도 톤이 깨지지 않는다. 다만 **어디서 가져왔는지 좌표를
주석에 남긴다**(아래 매핑표에도 적는다).

### ③ 에서 지키는 것

- **원본 마크업을 그대로 옮긴다.** 값·구조·클래스·차트를 손대지 않는다.
  바꾸는 것은 **자산 경로**(`assets/…` → `/admin/…`)와 **제목**뿐이다.
- **못 채우는 칸을 지우지 않는다** — `[향후 사용예정]` 텍스트로 둔다(사용자 결정).
  **그 칸에 숫자·차트는 남기지 않는다.** 회색 0도 사람은 사실로 읽는다.
- **실데이터 연결 전이면 상단에 「레이아웃 견본」 배너를 단다.** 본문에 템플릿 예시값이
  남아 있기 때문이다. **견본이라고 먼저 밝히면 그 숫자는 거짓말이 아니라 견본이 된다.**
  실데이터를 붙일 때 배너를 걷는다.
- 템플릿에만 있는 자산(vendor·차트 JS·이미지)은 **복사한 뒤** 싣는다. 안 하면 404 인데
  **브라우저는 조용히 넘어간다**(슬라이스 100 에서 세 화면이 스타일 없이 이틀 돌았다).

### 화면 ↔ 원본 매핑 (재구축분)

| 우리 화면 | Phoenix 원본 | 가져온 자산 | 비고 |
|---|---|---|---|
| 대시보드 `/admin2/` | `public/index.html`<br>(Ecommerce Dashboard) | `assets/js/dashboards/ecommerce-dashboard.js` · `vendors/leaflet` 3종 · `assets/img/country/*` | 제목 21곳만 교체. **견본 배너 있음**(실데이터 미연결) |
| 상품 관리 `/admin2/products` | `apps/e-commerce/admin/products.html` | (없음 — 기존 vendor 로 충분) | 2026-08-08 A/B 시험판 승계 |

**LNB 는 템플릿에서 가져오지 않는다** — `api/admin_nav.NAV` 가 단일 원천이고 레이아웃이
서버에서 그린다. Phoenix 의 좌측 메뉴 마크업 구조(`dropdown-indicator`·`parent-wrapper`)만
따르고 내용은 우리 IA(UX-34, 구 UX-14)다.

---

## 새 관리자 화면을 만드는 절차 (요약) — 기존 `/admin/*` 정적 화면용

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
