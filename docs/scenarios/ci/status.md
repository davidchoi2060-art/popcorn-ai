# 끝까지 시나리오 진척

측정 2026-10-08 08:05 UTC · 커밋 `362963f` · 대상 CI 와 같은 조건의 일회용 DB(마이그레이션만 · 상품 0건) · 쓰기 허용 · 측정자 클라우드 쪽

**끝까지 되는 시나리오 0/8 · 단계 통과 6/33** (🟢 6 · 🟡 13 · 🔴 14) · 가용성 점검 1/1 통과(완료 수에 넣지 않음)

판정: 🟢 이번 실행에서 실제 요청이 기대대로 끝남(유일한 통과 근거) · 🟡 경로는 있으나 이번에 확인 못 함 · 🔴 실제 요청 실패 또는 경로 없음. 정의 `tests/scenarios/definitions.py`.

## ⬜ 추천에서 견적까지 <sub>고객</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 예산 구간 보기 | 🟢 통과 | `GET /api/budget-bands → 200` | 실제 요청 통과 |
| 조건에 맞는 부품으로 조립 가능한지 확인 | 🔴 실패 | `POST /api/candidates/count → 200` | buildable=False (기대 True) · buildable=False, total=0, count=0 |
| 견적 받기(용도 게임 · 예산 150만원) | 🔴 실패 | `POST /api/recommend → 500 (JSON 아님)` | HTTP 500 · 코드 `UndefinedColumn` |
| 견적 부품의 가격·재고 다시 확인 | 🟡 미확인 | `POST /api/recommend/revalidate` | 경로는 있음 · 앞 단계가 남긴 값 없음(product_codes) |

## ⬜ 견적을 쇼핑몰 주문으로 넘기기(몰 인계) <sub>고객</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 조건에 맞는 부품으로 조립 가능한지 확인 | 🔴 실패 | `POST /api/candidates/count → 200` | buildable=False (기대 True) · buildable=False, total=0, count=0 |
| 견적 받기(용도 게임 · 예산 150만원) | 🔴 실패 | `POST /api/recommend → 500 (JSON 아님)` | HTTP 500 · 코드 `UndefinedColumn` |
| 쇼핑몰 인계 접수 | 🟡 미확인 | `POST /api/handoff` | 경로는 있음 · 앞 단계가 남긴 값 없음(session_id, tier) |
| 인계 내역 조회 | 🟡 미확인 | `GET /api/handoff/{handoff_no} → 404` | 경로는 응답함 · 앞 단계가 대상(handoff_no)을 못 만들어 실제 확인 못 함 |

## ⬜ 고객 로그인 <sub>고객</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 로그인(가입) | 🔴 실패 | `POST /api/auth/login → 503` | HTTP 503 · 코드 `auth_unavailable` |
| 로그인 상태 확인 | 🟡 미확인 | `GET /api/auth/me` | 경로는 있음 · 앞 단계가 남긴 값 없음(member) |
| 내 주문 보기 | 🟡 미확인 | `GET /api/my/orders` | 경로는 있음 · 앞 단계가 남긴 값 없음(member) |

## ⬜ 주문 만들기 <sub>고객</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 조건에 맞는 부품으로 조립 가능한지 확인 | 🔴 실패 | `POST /api/candidates/count → 200` | buildable=False (기대 True) · buildable=False, total=0, count=0 |
| 견적 받기(용도 게임 · 예산 150만원) | 🔴 실패 | `POST /api/recommend → 500 (JSON 아님)` | HTTP 500 · 코드 `UndefinedColumn` |
| 주문 생성 | 🟡 미확인 | `POST /api/orders` | 경로는 있음 · 앞 단계가 남긴 값 없음(session_id, tier) |
| 주문 조회 | 🔴 실패 | `GET /api/commerce/orders/{order_no} → 503` | 대상 없이 두드려도 HTTP 503 — 이 단계는 지금 막혀 있다 · 코드 `owner_configuration_unready` |

## ⬜ 결제하기 <sub>고객</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 결제 준비(주문 금액 확정) | 🔴 실패 | `—` | HTTP 경로 없음 — api/commerce_writer.py 의 create_draft·prepare 를 부르는 라우트가 없다 |
| 결제 승인 | 🔴 실패 | `—` | HTTP 경로 없음 — commerce_writer 의 dispatch·finalize 를 부르는 라우트가 없다 |
| 내 결제 내역 보기 | 🟡 미확인 | `GET /api/my/payments` | 경로는 있음 · 앞 단계가 남긴 값 없음(order_no, member) |

## 🔎 운영자 목록 조회 <sub>운영자</sub>

> 목록이 열린다는 것만 증명한다(빈 목록이어도 통과). 주문을 실제로 처리했다는 증거는 아래 「운영자 주문 처리」다. 그래서 「끝까지 되는 시나리오」 수에 넣지 않는다.

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 관리자 로그인 | 🟢 통과 | `POST /api/admin/auth/login → 200` | 실제 요청 통과 |
| 커머스 주문 목록 | 🟢 통과 | `GET /api/admin/commerce/orders → 200` | 실제 요청 통과 |
| 결제 내역 목록 | 🟢 통과 | `GET /api/admin/payments → 200` | 실제 요청 통과 |
| 환불 요청 목록 | 🟢 통과 | `GET /api/admin/refunds → 200` | 실제 요청 통과 |
| 없는 주문 상세는 찾을 수 없음으로 답함 | 🟢 통과 | `GET /api/admin/commerce/orders/ORD-SCENARIO-NONE → 404` | 실제 요청 통과 · 코드 `order_not_found` |

## ⬜ 운영자 주문 처리(실제 대상) <sub>운영자</sub>

> 실제 주문 하나가 출고 등록으로 상태가 바뀌고, 같은 operation_id 의 확정 원결과가 조회되고, 잘못된 출고를 정정할 수 있어야 끝까지다.

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 대상 주문 상세 보기 | 🟡 미확인 | `GET /api/admin/commerce/orders/{order_no}` | 경로는 있음 · 앞 단계가 남긴 값 없음(order_no) |
| 출고 현황과 처리 가능 여부 보기 | 🟡 미확인 | `GET /api/admin/commerce/orders/{order_no}/fulfillment` | 경로는 있음 · 앞 단계가 남긴 값 없음(order_no) |
| 출고 준비 등록 | 🟡 미확인 | `POST /api/admin/commerce/orders/{order_no}/fulfillment` | 경로는 있음 · 앞 단계가 남긴 값 없음(order_no, fulfillment_command) |
| 처리 뒤 주문 상태가 바뀌었는지 확인 | 🟡 미확인 | `GET /api/admin/commerce/orders/{order_no}` | 경로는 있음 · 앞 단계가 남긴 값 없음(order_no, fulfilled) |
| 전송 결과 불명확 시 확정 원결과 조회 | 🟡 미확인 | `GET /api/admin/commerce/orders/{order_no}/fulfillment/operations/{operation_id} → 404` | 경로는 응답함 · 앞 단계가 대상(order_no, fulfilled, operation_id)을 못 만들어 실제 확인 못 함 · 코드 `order_not_found` |
| 잘못 처리한 출고 정정 | 🔴 실패 | `—` | 정책 미정 — 커머스 출고의 undo·cancel·reverse·ref_log_id 계약이 없다(PC 쪽 8번 검토). 실물 반품 재고 복원은 별도 효과이고 금융 환불과 분리한다 |

## ⬜ 고객 배송 조회 <sub>고객</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 고객이 배송 상태 보기 | 🔴 실패 | `GET /api/commerce/orders/{order_no}/fulfillment → 503` | 대상 없이 두드려도 HTTP 503 — 이 단계는 지금 막혀 있다 · 코드 `owner_configuration_unready` |

## ⬜ 반품 <sub>고객 · 운영자</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 고객 반품 접수 | 🔴 실패 | `—` | HTTP 경로 없음 — 실물 반품 접수 라우트가 없다(api/commerce_physical_return_http.py 는 관리자 조회 GET 둘뿐) |
| 회수·입고 처리 | 🔴 실패 | `—` | HTTP 경로 없음 — 회수·입고·실행 라우트가 없다 |
| 운영자 반품 내역 보기 | 🟡 미확인 | `GET /api/admin/commerce/orders/{order_no}/physical-returns → 404` | 경로는 응답함 · 앞 단계가 대상(order_no)을 못 만들어 실제 확인 못 함 · 코드 `physical_return_not_found` |

