# Phoenix 템플릿 전수 실사 — 우리는 산 것을 안 쓰고 있다

> 2026-08-05 · 대상 `D:\phoenix_Templet\public` (HTML 222개) ↔ `mockups/admin/` (36화면)
> 사용자 지적으로 시작: "라이선스를 구매한 부트스트랩 UI를 전혀 활용하지 못하는 것 같다."
> **지적이 맞다.** 아래는 증거와 재정립안이다.

---

## 0. 결론 — 숫자 세 개

| | |
|---|---|
| 템플릿 컴포넌트를 **실제로 초기화**하는 우리 화면 | **0개** (36화면 중) |
| `phoenix.js`가 자동으로 붙여 주는 훅 | **28종** — 우리가 선언한 것 **3종**(전부 셸 기본값) |
| 그중 **vendor 추가 없이 지금 바로 쓸 수 있는 것** | **17종** |

**우리는 표·정렬·페이지네이션·일괄선택·트리를 전부 손으로 다시 만들었다.**
그 기능이 이미 `assets/js/phoenix.js`와 `assets/css/theme.min.css` 안에 들어 있고,
**전 페이지에 이미 로드되고 있었다.**

---

## 1. 증거

### 1.1 `data-list`은 35화면에 있지만, 전부 셸 검색창이다

```
mockups/admin/products.html:134
  <div class="search-box navbar-top-search-box" data-list='{"valueNames":["title"]}'>
```

상단 네비게이션의 검색 상자다. **우리 표 어디에도 `data-list`가 없다.**
템플릿의 같은 자리(`modules/tables/advance-tables.html`)는 이렇게 쓴다:

```
data-list='{"valueNames":["name","email","age"],"page":5,"pagination":true}'
```

이 한 줄이 **검색 · 컬럼 정렬 · 페이지네이션**을 준다. 우리는 `btnPrev`/`btnNext`를
손으로 만들고 정렬은 아예 없다.

### 1.2 템플릿 컴포넌트를 쓰는 화면은 `_demo-products.html` 뿐이다

`data-bulk-select` · `echarts` · `wizard` · `accordion` · `list-group`을 검색하면
전부 `_demo-products.html` 한 파일에서만 나온다. 그런데 그 파일은 `CLAUDE.md`가
**"`data-screen-id`가 없는 템플릿 잔재라 화면이 아니다"**라고 적어 둔 파일이다.

**즉 우리가 만든 36화면 중 템플릿 컴포넌트를 쓰는 화면은 없다.**
(예외 하나: `category-mapping.html`의 `nav-underline` 탭 — 2026-08-04에 내가 쓴 것.)

### 1.3 `phoenix.js`는 선언만 하면 알아서 붙인다

```js
querySelectorAll('[data-bulk-select]')        // 일괄 선택
querySelectorAll('[data-list]')               // 검색·정렬·페이지
querySelectorAll('[data-category-filter]')    // 카테고리 필터
querySelectorAll('[data-vertical-category-tab]')
…28종
```

`treeviewInit`도 들어 있고, `theme.min.css`에 `treeview` · `treeview-item` ·
`treeview-badge` · `treeview-icon` 스타일이 전부 있다.

**나는 카테고리 트리를 `<table>`에 `<span style="width:18px">`로 들여쓰기를 흉내 내 만들었다.**
쓸 수 있는 트리 컴포넌트가 이미 우리 저장소 안에 있었다.

---

## 2. 왜 이렇게 됐나 (변명 아니라 원인)

1. **셸만 베끼고 본문은 새로 썼다.** `CLAUDE.md`가 "셸은 `activity-logs.html`에서 가져온다"고
   정해 둔 뒤로, 새 화면마다 셸을 복사하고 **본문은 빈 `<div>`에서 시작**했다.
   템플릿 본문을 열어 본 적이 없다.
2. **API가 이미 페이지네이션을 하고 있었다.** 서버 페이지네이션(A-13 규약) 때문에
   "표는 서버가 준 것만 그린다"로 굳었고, 그래서 `list.js`의 클라이언트 정렬·검색을
   **쓸 수 없다고 지레 판단**했다. 실제로는 **현재 페이지 안의 정렬**만으로도 쓸모가 크고,
   두 방식은 공존한다(템플릿 `e-commerce/admin/products.html`이 그렇게 한다).
3. **지도 문서가 "좌표"만 적고 "무엇이 들어 있는지"를 안 적었다.**
   `docs/design/phoenix-template-map.md`는 어느 폴더에 뭐가 있는지는 적었지만
   **각 컴포넌트가 어떤 기능을 주는지**가 없어서, 필요할 때 찾아갈 이유가 생기지 않았다.

---

## 3. 지금 바로 쓸 수 있는 것 (vendor 추가 0)

우리가 가진 vendor는 10개(`anchorjs bootstrap dayjs feather-icons fontawesome is
list.js lodash popper simplebar`). 아래는 **그 10개만으로 도는 것**이다.

| 훅 / 컴포넌트 | 무엇을 주나 | 우리 어디에 |
|---|---|---|
| **`data-list`** | 검색 · 컬럼 정렬 · 페이지네이션 | **모든 목록 화면**(products · orders · category-mapping …) |
| **`data-bulk-select`** | 전체선택 · 부분선택 · 선택 수 · 일괄 액션바 | category-mapping(손으로 만든 것 교체) · review-queue · price-review |
| **`treeview`** (CSS+JS 보유) | 접히는 계층 트리 + 개수 배지 | **categories.html — 사용자가 지적한 그것** |
| `data-category-filter` · `data-vertical-category-tab` | 카테고리 탭 전환 | 카테고리 탐색 |
| `accordion` · `list-group` · `collapse` | 계층 · 접이식 목록 | 트리 보조 · 필터 사이드바 |
| `nav-underline` tabs | 범위 전환 | 이미 category-mapping에서 사용 중 |
| `data-copy` | 클립보드 복사 | 상품코드 · SKU |
| `data-password` | 비밀번호 표시 토글 | login · my-profile |
| `modal` · `offcanvas` · `toast` | 대화상자 · 패널 · 알림 | 전역(지금은 손으로 만든 토스트) |
| `advance-tables` 마크업 | `class="sort"` 헤더 | 모든 표 |

**참고 화면(그대로 베낄 것):**
```
modules/tables/advance-tables.html      검색+정렬+페이지 표
modules/tables/bulk-select.html         일괄 선택
apps/file-manager/grid-view.html:2442   treeview 마크업 원본
apps/e-commerce/admin/products.html     상품 목록(우리 products.html의 원본이어야 했다)
apps/e-commerce/admin/orders.html       주문 목록
apps/e-commerce/admin/customers.html    회원 목록
apps/e-commerce/landing/products-filter.html  카테고리+필터 사이드바
```

## 4. vendor를 더해야 쓰는 것

| vendor | 훅 | 어디에 쓸 것인가 | 우선순위 |
|---|---|---|---|
| `echarts` | `data-echarts` | 대시보드 추이 · 가격 이력 · 매출 통계 | **높음**(대시보드에 차트가 하나도 없다) |
| `choices` | `data-choices` | 검색 가능한 셀렉트 — 카테고리 선택(29개) · 제조사 · 공급처 | **높음** |
| `flatpickr` | — | 기간 필터(주문 · 가격 이력 · 활동 기록) | 중 |
| `dropzone` | — | CSV 업로드(지금은 기본 file input) | 중 |
| `sortablejs` | `data-sortable` | **카테고리 순서 드래그 정렬** | 중 |
| `countup` | `data-countup` | 대시보드 수치 | 낮음 |
| `nouislider` | `data-nouislider` | 가격대 범위 필터 | 낮음 |
| `tinymce` | `data-tinymce` | 상품 상세 설명 | 낮음(현 범위 밖) |

가져오는 법: `D:\phoenix_Templet\public\vendors\<이름>` → `mockups/admin/vendors/`.
**빌드 시스템은 쓰지 않는다**(기존 결정 유지) — 파일 복사 + `<script>` 한 줄.

---

## 5. 사용자가 지적한 계층 구조 — 지금 무엇이 잘못됐나

### 현재 (잘못)
- `categories.html` — **평면 표**. 들여쓰기를 `<span style="width:18px">`로 흉내.
  클릭해도 아무 일이 없다. 하위로 들어갈 수 없다.
- `category-mapping.html` — 카테고리를 **드롭다운**으로 고른다. 트리가 아니다.
- **두 화면이 갈라져 있다.** "카테고리를 보다가 그 안의 상품을 본다"가 한 화면에 없다.

### 되어야 하는 것 (사용자 기대 = 표준 관리자 UX)
```
┌ 좌: 카테고리 treeview ────┐ ┌ 우: 선택한 카테고리의 상품 ──────────┐
│ ▾ 부품            22,838 │ │ [검색] [부품종류▾] [재고만]  선택 12건 │
│   · CPU              678 │ │ ☑ 코드   상품명        종류  가격  재고│
│   ▾ 쿨링·튜닝      1,668 │ │ ☑ 39948  모니터받침대  미분류 11,000 0│
│     · 시스템팬       913 │ │ □ 54090  마우스패드    미분류 12,700 0│
│   · 케이블·젠더      704 │ │ …                        [◀ 1/8 ▶]   │
└──────────────────────────┘ └───────────────────────────────────────┘
```
- 좌측 노드 클릭 → 우측이 그 카테고리 상품으로 바뀐다(하위 포함 여부 토글)
- 노드에 **개수 배지**(`treeview-badge`) — 이미 CSS에 있다
- 우측은 `data-list`(검색·정렬) + `data-bulk-select`(일괄 이동)
- **한 화면**에서 트리 편집(이름·이동·추가)과 상품 매핑이 다 된다

즉 `categories.html` + `category-mapping.html`을 **하나로 합치는 것**이 맞다.

---

## 6. 전략 재정립

### 6.1 새 화면을 만들 때 (절차 개정)
1. **먼저 템플릿에서 같은 일을 하는 화면을 찾는다.** 위 §3 참고 화면 표를 본다.
   목록이면 `advance-tables`, 선택이면 `bulk-select`, 계층이면 `treeview`.
2. 그 파일을 열어 **본문 마크업을 그대로 가져온다.** 셸은 우리 화면에서 가져온다(기존 규약 유지).
3. `data-*` 훅을 **지우지 않는다.** `phoenix.js`가 그것을 보고 붙인다.
4. 서버 데이터로 채운다. **행 렌더만 우리가 하고, 동작은 컴포넌트에 맡긴다.**

### 6.2 회귀가 지킨다 (새 불변식 제안)
- `[37] 템플릿 활용` — 표가 있는 화면은 `data-list` 또는 서버 페이지네이션 중 하나를
  **반드시** 쓴다(둘 다 없으면 정렬·검색이 없는 표다)
- 선택 체크박스가 있는 화면은 `data-bulk-select`를 쓴다(손으로 만든 전체선택 금지)
- 참조하는 vendor는 실제로 존재한다(기존 `[30] 화면 자산` 확장)

### 6.3 지도 문서 개정
`docs/design/phoenix-template-map.md`에 **§3 표(무엇을 주나)**를 옮겨 넣는다.
"어디에 있나"가 아니라 **"무엇이 필요할 때 무엇을 여나"**로 바꾼다.

---

## 7. 제안 순서

| | 작업 | 크기 | 왜 먼저인가 |
|---|---|---|---|
| **F** | **카테고리 통합 화면**(treeview + bulk-select + data-list) | 중 | 사용자가 지목한 결함. 재료가 이미 다 있다 |
| G | 목록 화면 일괄 개선 — `data-list` 정렬·검색 (products · orders · review-queue …) | 중 | 한 줄씩 추가하면 전 화면이 좋아진다 |
| H | vendor 2종 추가(`echarts` · `choices`) + 대시보드 차트 · 검색 셀렉트 | 중 | 대시보드에 차트가 없다 |
| I | 회귀 `[37]` + 지도 문서 개정 | 소 | 다시 벌어지지 않게 |

**F부터 하는 것을 제안한다** — 지적받은 그 화면이고, 새 의존성 없이 오늘 된다.
