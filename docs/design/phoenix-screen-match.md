# 화면별 Phoenix 템플릿 매칭 — 무엇을 어디서 가져올 것인가

**작성:** 2026-08-06 (사용자 지시: "지금 팝콘 AI 화면 UI 들이 정말 맘에 안듭니다")
**원본:** `D:\phoenix_Templet\public` · Phoenix v1.22.0 · HTML 222개
**짝 문서:** `phoenix-template-map.md`(자산 대조표·컴포넌트 좌표) — **먼저 그것을 본다.**
이 문서는 그 위에서 **화면 대 화면**을 잇는다.

---

> # ⚠ 2026-08-06 정정 — 아래 §1의 측정은 **무효다**
>
> 본문 크기를 **정적 마크업**으로 쟀는데, 우리 관리자 화면 다수는 본문을 **JS로 그린다**
> (`#liveRules` · `#host` · `#body` 같은 빈 컨테이너 하나만 마크업에 두고 fetch 뒤 채운다).
> 그래서 "875자짜리 초라한 화면"으로 지목한 것들이 실제로는 충실한 화면이었다.
>
> 브라우저에서 여섯 화면을 직접 열어 확인한 결과:
>
> | 화면 | 마크업 | 실제로 그려지는 것 |
> |---|---|---|
> | `compat-rules` | 1,278자 | 호환 검사 **9종 표** + 부품별 필수 사양 표(배지 포함) + 견적 슬롯 구성 |
> | `usage-floors` | 1,085자 | 용도 **8그룹** × 슬롯별 하한 입력 + '지금 재고에서 통과' 진행바(312/349) + 저장 |
> | `payments` | 1,192자 | KPI 4 + 탭(결제/일 정산) + 기간 필터 + 결제 11행(상태 배지) |
> | `reviews` | 875자 | KPI 4 + 별점 카드 + 구매 인증 배지 + S2 인용/숨김 처리 |
> | `refunds` | 1,173자 | KPI 4 + 목록·상세 2단 + **단계 파이프라인**(1접수 2검토 3수거·처리 4완료) |
> | `suppliers` | 1,069자 | 등록 폼 + 정렬되는 목록 + 매입가 연결·단가표 수 + 수정/중지 |
>
> **비어 보인 것은 화면이 아니라 데이터였다** — 환불 2건 · 후기 4건 · 공급처 4건.
> 행이 적은 화면에 레이아웃을 더 얹으면 더 비어 보인다.
>
> 그래서 **착수 순서 2번(빈 6화면 채우기)은 폐기한다.** 채울 것이 없다.
> 순서 3~6도 같은 잣대로 뽑았으므로 **눈으로 다시 확인하기 전에는 근거가 없다.**
>
> 교훈: 화면이 무엇을 보여주는지는 **열어 봐야 안다.** 이 프로젝트는 이미 같은 것을
> 배웠다 — "브라우저에서 실제로 열어 봐야 보이는 것"(CLAUDE.md, 2026-08-05).

## 1. 왜 초라해 보이는가 — 측정한 사실 (⚠ 위 정정을 먼저 읽을 것)

셸(좌측 메뉴·상단바)을 뺀 **본문**만 재면 이렇다.

| | 우리 | 템플릿 동급 화면 |
|---|---|---|
| 본문 크기 중앙값 | **약 2,500자** | **20,000~80,000자** |
| 가장 작은 화면 | `reviews.html` **875자** · `suppliers.html` 1,069자 · `usage-floors.html` 1,085자 · `refunds.html` 1,173자 · `payments.html` 1,192자 | `refund.html` 13,163자 |
| 차트 | **36화면 중 2** | 대시보드 4종 전부 + 차트 예시 10종 |
| 손으로 그린 시각화 | `price-history` SVG 1건 · `candidate-pool` CSS 막대 1건 | — (전부 echarts) |
| 타임라인 | **0화면** | `pages/timeline.html` · 상세 화면 다수 |
| 아코디언 | **0화면** | 필터·FAQ·상세 |
| 오프캔버스(우측 작업 패널) | **1화면** | 목록·상세의 기본 장치 |
| 일괄 선택 | 4화면 | 목록 화면의 기본 |

**결론: 껍데기는 Phoenix인데 본문은 "필터 한 줄 + 표 한 개"다.** `vendors/`에는
`echarts`·`choices`가 이미 들어와 있는데(12종 보유) 실제로 쓰는 화면이 2~3개뿐이다.
디자인이 나쁜 게 아니라 **화면이 비어 있는 것**이다. 표 하나로 끝나는 화면은
어떤 테마를 입혀도 초라하다.

> ⚠️ **다만 채우기 위해 숫자를 지어내지 않는다.** KPI 타일·차트를 붙이는 것은
> **서버가 이미 주고 있는 값을 제대로 보여주자**는 뜻이다. 서버가 모르는 수를 만들면
> 슬라이스 47·48에서 정한 화면 정직성이 무너진다. 값이 없으면 타일을 만들지 말고,
> 원천이 준비 중이면 그렇게 적는다.

---

## 2. 매칭 원칙 — 한 화면에 하나가 아니다

```
① 골격(레이아웃)   : 화면 전체 구성을 어디서 가져올지. 1개만 고른다.
② 부품(컴포넌트)   : 골격 위에 얹을 조각들. 여러 개 조합한다.
③ 이미 있는 것     : 우리 화면에 이미 있어 재사용할 것(treeview·bulk-select·ui-list).
```

- **셸은 계속 우리 것을 쓴다**(`admin-menu-data.js` 정본). 템플릿 셸을 다시 들여오지 않는다.
- **없는 vendor를 참조하면 404이고 브라우저는 조용히 넘어간다** — 도입은 자산 복사까지 해야 끝난다.
- 우리가 **이미 가진** vendor: `bootstrap` `choices` `dayjs` `echarts` `feather-icons`
  `fontawesome` `is` `list.js` `lodash` `popper` `simplebar` `anchorjs`
- 이 문서가 제안하는 것 중 **없는** vendor: `dropzone`(업로드) · `flatpickr`(날짜) ·
  `sortablejs`(드래그 정렬) · `glightbox`(이미지) · `nouislider`(범위 슬라이더)

---

## 3. 관리자 36화면 매칭

### 3.1 대시보드·현황

| 우리 화면 | 골격(주) | 조합할 것 | 무엇이 달라지나 |
|---|---|---|---|
| `index.html` 대시보드 | `dashboard/crm.html` | `dashboard/project-management.html`(진행률·타임라인) · `modules/echarts/line-charts.html` · `bar-charts.html` | 지금은 KPI 타일 + 표. 상단 KPI행 → 추이 차트 → 처리 대기 큐 3단으로 재구성 |
| `candidate-pool.html` 추천 가능 재고 | `dashboard/crm.html` | **`modules/echarts/bar-charts.html`(슬롯별 후보 수 막대)** · `modules/components/progress-bar.html` | ~~표조차 없는 화면~~ → **정정(2026-08-06):** CSS 누적 막대가 있었다. 문제는 없다는 게 아니라 **막대마다 자기 총계로 100%를 채워** 2,457개짜리와 325개짜리가 같은 너비로 보인 것이다. **작업 완료** — 값 축을 공유하는 echarts 누적 막대로 교체 |
| `ai-cost.html` AI 사용량·비용 | `dashboard/stock.html`(KPI행 + 추이) | `modules/echarts/line-charts.html` | 누적 비용·일별 추이가 표로만 있다 |

### 3.2 상품

| 우리 화면 | 골격(주) | 조합할 것 | 무엇이 달라지나 |
|---|---|---|---|
| `products.html` 상품 관리 | **`apps/e-commerce/admin/products.html`** | `modules/tables/bulk-select.html` · `apps/travel-agency/hotel/admin/room-listing.html`(썸네일+가격+상태 배지 행) | 가장 정확한 1:1 대응. 행에 이미지·상태 배지·재고 뱃지가 들어간 형태 |
| `product-edit.html` 등록·수정 | **`apps/e-commerce/admin/add-product.html`** | `modules/forms/advance/advance-select.html`(choices) · `apps/crm/lead-details.html`(탭 상세) · `dropzone`(이미지) | 지금은 폼 나열. 템플릿은 **좌 본문 / 우 사이드(가격·재고·분류)** 2단 + 섹션 카드 |
| `review-queue.html` 상품 검수 | **`apps/project-management/todo-list.html`** | `apps/crm/deals.html`(필터 아코디언) · 오프캔버스 상세 | **1,450자.** 큐 작업에는 todo-list의 *좌 목록 / 우 상세 패널*이 맞다 — 목록을 떠나지 않고 한 건씩 처리 |
| `categories.html` 카테고리 관리 | (이미 treeview — 유지) | `apps/file-manager/list-view.html`(좌 트리 + 우 목록 + 상단 요약) | 사용자가 좋다고 한 화면. 상단에 분류별 요약 타일만 얹으면 완성 |
| `category-mapping.html` 상품 매핑 | `apps/e-commerce/admin/products.html` | `modules/tables/bulk-select.html` · `apps/crm/lead-details.html`(우측 오프캔버스 이동 패널) | 이동 대상 분류를 **오프캔버스**에서 고르면 목록을 안 떠난다 |
| `spec-fields.html` 사양 항목 정의 | `apps/social/settings.html`(섹션형 설정) | `modules/forms/basic/checks.html` | 21KB로 이미 크다. 섹션 카드로 나누면 읽힌다 |
| `imports.html` 상품 원본 자료 | **`apps/file-manager/list-view.html`** | — | 파일 목록이 파일 관리자 화면과 같은 것을 하고 있다 |
| `csv-upload.html` 일괄 등록 | `apps/e-commerce/admin/add-product.html`의 **dropzone** | `modules/components/progress-bar.html` · 단계 표시 | 드라이런→확인→적용 3단계를 **단계 표시줄**로. 지금은 진행바만 |
| `csv-jobs.html` 일괄 등록 이력 | `apps/crm/reports.html`(필터+표) | **`pages/timeline.html`** | 1,289자. 이력은 표보다 타임라인이 맞다 |

### 3.3 가격·매입

| 우리 화면 | 골격(주) | 조합할 것 | 무엇이 달라지나 |
|---|---|---|---|
| `price-history.html` 가격 이력 | **`apps/stock/stock-details.html`** | `modules/echarts/line-charts.html` | **가장 잘 맞는 짝.** 주가 상세 = 추이 차트 + 이력 표 + 변동 배지. ~~지금은 표만~~ → **정정(2026-08-06):** 손으로 그린 SVG 꺾은선이 있었다(전 화면 중 유일). **작업 완료** — echarts **계단선**으로 교체. 직선 보간은 두 변경 사이에 서서히 변했다고 말하는데 그런 변동은 없었다 |
| `reprice.html` 판매가 재산정 | `apps/crm/report-details.html`(분석+표) | `modules/echarts/bar-charts.html`(오름/내림 분포) | 오름 6,964 · 내림 · 이상치를 **분포 막대**로 보여주면 "적용해도 되나"가 한눈에 |
| `price-review.html` 가격 검토 대기 | `apps/e-commerce/admin/orders.html` | — | 일괄 선택은 **붙이지 않기로 결정됨**(파생 큐 0건) — 규약 유지 |
| `margin-policy.html` 마진 정책 | `apps/social/settings.html` | 카테고리 트리(상속 표시) | 1,531자. 상속(전역→분류)이 보이게 트리로 |
| `price-import.html` 단가표 반영 | (이미 43KB — 가장 완성됨) | `apps/e-commerce/admin/orders.html` 정렬 규칙 | 다른 화면이 이 수준으로 올라와야 한다 |
| `sourcing.html` 매입 견적(용산) | `apps/crm/deals.html` | 오프캔버스 상세 | 2,024자 |
| `stock-inbound.html` 재고 입고 | `apps/e-commerce/admin/orders.html` | — | 일괄 선택 제외 결정 유지(수량이 건마다 다름) |
| `suppliers.html` 공급처 | `pages/members.html` 또는 `apps/e-commerce/admin/customers.html` | 아바타·연락처 카드 | **1,069자.** 공급처는 '사람/조직 목록'이라 members 형태가 맞다 |

### 3.4 추천 엔진

| 우리 화면 | 골격(주) | 조합할 것 | 무엇이 달라지나 |
|---|---|---|---|
| `compat-rules.html` 호환 규칙 | `apps/social/settings.html` | **`modules/components/accordion.html`** · `pages/faq/faq-accordion.html` | **1,278자.** 규칙 9종을 아코디언으로 펼치면 "무엇을 막는 규칙인지"가 읽힌다 |
| `policy-weights.html` 추천 기준 | `apps/social/settings.html` | `modules/components/progress-bar.html`(가중치 시각화) | 2,092자 |
| `usage-floors.html` 용도 하한 | `apps/social/settings.html` | `progress-bar` · `modules/forms/basic/input-group.html`(단위 붙은 숫자) | **1,085자.** 하한이 후보를 얼마나 줄이는지 막대로 |

### 3.5 견적·주문·고객

| 우리 화면 | 골격(주) | 조합할 것 | 무엇이 달라지나 |
|---|---|---|---|
| `orders.html` 주문 관리 | **`apps/e-commerce/admin/orders.html`** | `modules/tables/bulk-select.html` | 이미 일괄선택 있음. 행 아바타·상태 배지 보강 |
| 주문 상세(신설 검토) | **`apps/e-commerce/admin/order-details.html`** | `apps/e-commerce/landing/invoice.html` | 지금 주문 상세가 별도 화면이 아니다 |
| `refunds.html` 환불·클레임 | **`apps/e-commerce/admin/refund.html`** | — | **1,173자 → 템플릿 13,163자.** 환불 금액 계산·요약 블록이 통째로 없다 |
| `payments.html` 결제·정산 | `apps/stock/portfolio.html`(금액 요약+표) | `apps/e-commerce/landing/invoice.html` | **1,192자.** 정산은 '보유/증감' 구조라 portfolio가 맞다 |
| `shipping.html` 배송 관리 | `apps/e-commerce/admin/orders.html` | **`apps/e-commerce/landing/order-tracking.html`(단계 타임라인)** | 배송 단계는 타임라인이 정답 |
| `sessions.html` 견적 상담 기록 | `apps/crm/leads.html` + `lead-details.html` | 오프캔버스 상세 | 상담 = 리드. 구조가 같다 |
| `swap-logs.html` 부품 교체·클릭 | `apps/crm/report-details.html` | `modules/echarts/bar-charts.html` | 어떤 부품이 자주 교체되는지가 요점인데 표만 있다 |
| `reviews.html` 후기 관리 | `apps/e-commerce/admin/customer-details.html`의 후기 카드 | `pages/notifications.html` | **875자 — 가장 빈 화면** |
| `customers.html` 회원 관리 | **`apps/e-commerce/admin/customers.html`** | `customer-details.html`(상세) | 2,234자 |

### 3.6 시스템

| 우리 화면 | 골격(주) | 조합할 것 | 무엇이 달라지나 |
|---|---|---|---|
| `ops-settings.html` 운영 전환 | **`apps/social/settings.html`** | `modules/forms/basic/checks.html`(스위치) | 스위치 5종이 설정 화면 형태로 |
| `operators.html` 운영자·권한 | **`pages/members.html`** | 아바타·역할 배지 | 사람 목록의 표준형 |
| `my-profile.html` 내 정보 | **`apps/social/settings.html`** | `modules/components/avatar.html` | **989자** |
| `activity-logs.html` 작업 기록 | **`pages/timeline.html`** | `apps/crm/reports.html`(필터) | 1,627자. 원장 이력 = 타임라인 |
| `login.html` 로그인 | `pages/authentication/split/sign-in.html` | — | 이미 9,364자로 준수 |

---

## 4. 고객 화면(MVP1) 매칭

| 우리 화면 | 골격(주) | 조합할 것 |
|---|---|---|
| `main-landing.html` · `s0-landing.html` | `pages/landing/default.html` | `apps/e-commerce/landing/homepage.html` |
| `s1-session.html` 대화형 견적 | **`apps/chat.html`**(대화 골격) | `apps/e-commerce/landing/products-filter.html`(좌측 조건 패널) · 오프캔버스 |
| `s2-result.html` 견적 제안서 | **`apps/e-commerce/landing/product-details.html`** | `apps/travel-agency/hotel/customer/hotel-compare.html`(**티어 비교**) · `invoice.html`(구성 내역) |
| `s3-detail.html` 부품 교체 | `apps/e-commerce/landing/products-filter.html` | `product-details.html` |
| `s4-cart.html` 주문 확인 | **`apps/e-commerce/landing/cart.html`** | `checkout.html` · `shipping-info.html` |
| `s5-complete.html` 주문 완료 | **`apps/e-commerce/landing/order-tracking.html`** | — |
| `my-page.html` | `apps/e-commerce/landing/profile.html` | `apps/social/profile.html` |
| `my-orders.html` | `order-tracking.html` | `wishlist.html` |
| `my-payments.html` | `apps/e-commerce/landing/invoice.html` | — |
| `my-review-write.html` | `modules/forms/basic/*` | `rater-js`(별점 — **미보유**) |

> **S2가 가장 중요하다.** "모든 견적에는 이유가 있습니다"를 파는 화면인데,
> 티어 비교는 `hotel-compare.html`이 이미 만들어 둔 형태다(3안 나란히 + 차이 강조).

---

## 5. 착수 순서 — 눈에 띄는 순

효과 대비 비용으로 줄 세운 것이다. **1~3은 새 vendor 없이 오늘 가능하다.**

| 순 | 대상 | 상태 |
|---|---|---|
| 1 | `candidate-pool` · `reprice` · `price-history`에 **echarts** | ✅ **완료**(2026-08-06 · `df7d6d2`). 근거는 "차트가 없어서"가 아니라 정규화 막대가 크기를 감췄고 직선 보간이 없던 중간값을 그렸기 때문 |
| ~~2~~ | ~~빈 6화면 본문 채우기~~ | ❌ **폐기** — 여섯 화면 모두 충실했다. 비어 보인 것은 데이터(환불 2·후기 4·공급처 4) |
| ~~3~~<br>~~4~~<br>~~5~~<br>~~6~~ | ~~타임라인 · 검수 큐 · 상품 등록 · S2~~ | ⏸ **보류** — 폐기된 것과 같은 잣대로 뽑았다. **화면을 직접 열어 본 뒤** 다시 세운다 |

**다음 할 일: 눈으로 하는 전수 감사.** 36화면을 실제로 열어 보고 순서를 다시 만든다.
측정으로 대신하지 않는다 — 이 문서가 그렇게 해서 두 번 틀렸다.

---

## 6. 이 문서를 쓰는 법

1. 화면을 고르고 위 표에서 **골격 1개**를 정한다.
2. 템플릿 파일을 열어 **본문 영역만** 본다 — `<div class="content">` ~ `<footer>` 사이.
   셸은 222개 파일이 전부 같아서, 통째로 보면 모든 화면이 똑같아 보인다.
3. 필요한 vendor가 우리에게 있는지 `phoenix-template-map.md`의 자산 대조표로 확인한다.
   없으면 **복사부터** 한다 — 참조만 하면 404이고 조용히 넘어간다.
4. 마크업 계약(`data-screen-id`·`data-bind`·`data-action`)과 화면 정직성 규칙은 그대로 지킨다.
