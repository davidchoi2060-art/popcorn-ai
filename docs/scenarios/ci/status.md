# 끝까지 시나리오 진척

측정 2026-10-08 07:23 UTC · 커밋 `1ecf4df` · 대상 CI 와 같은 조건의 일회용 DB(마이그레이션만 · 상품 0건) · 쓰기 허용

**끝까지 되는 시나리오 1/8 · 단계 통과 5/27** (🟢 5 · 🟡 8 · 🔴 14)

판정: 🟢 이번 실행에서 실제 요청이 기대대로 끝남(유일한 통과 근거) · 🟡 경로는 코드에 있으나 이번에 확인 못 함 · 🔴 실제 요청 실패 또는 경로 없음. 정의 `tests/scenarios/definitions.py`.

## ⬜ 추천에서 견적까지 <sub>고객</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 예산 구간 보기 | 🟢 통과 | `GET /api/budget-bands → 200` | 실제 요청 통과 |
| 조건에 맞는 부품으로 조립 가능한지 확인 | 🔴 실패 | `POST /api/candidates/count → 200` | buildable=False (기대 True) · 응답 `{"total": 0, "count": 0, "effects": [{"label": "용도", "value": "게임", "applied": true, "delta": 0, "count_after": 0, "reason": "용도 하한 미달 부품 제외` |
| 견적 받기(용도 게임 · 예산 150만원) | 🔴 실패 | `POST /api/recommend → 500` | HTTP 500 · 응답 `500 UndefinedColumn: column "vram_gb" does not exist` |
| 견적 부품의 가격·재고 다시 확인 | 🟡 미확인 | `POST /api/recommend/revalidate` | 경로는 있음 · 앞 단계가 남긴 값 없음(product_codes) |

## ⬜ 견적을 쇼핑몰 주문으로 넘기기(몰 인계) <sub>고객</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 조건에 맞는 부품으로 조립 가능한지 확인 | 🔴 실패 | `POST /api/candidates/count → 200` | buildable=False (기대 True) · 응답 `{"total": 0, "count": 0, "effects": [{"label": "용도", "value": "게임", "applied": true, "delta": 0, "count_after": 0, "reason": "용도 하한 미달 부품 제외` |
| 견적 받기(용도 게임 · 예산 150만원) | 🔴 실패 | `POST /api/recommend → 500` | HTTP 500 · 응답 `500 UndefinedColumn: column "vram_gb" does not exist` |
| 쇼핑몰 인계 접수 | 🟡 미확인 | `POST /api/handoff` | 경로는 있음 · 앞 단계가 남긴 값 없음(session_id, tier) |
| 인계 내역 조회 | 🟡 미확인 | `GET /api/handoff/HO-0 → 404` | 경로는 응답함(HTTP 404) · 앞 단계가 대상(handoff_no)을 못 만들어 실제 확인 못 함 · 응답 `"인계 기록이 없습니다"` |

## ⬜ 고객 로그인 <sub>고객</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 로그인(가입) | 🔴 실패 | `POST /api/auth/login → 503` | HTTP 503 · 응답 `{"error": "auth_unavailable", "detail": "회원 본인 확인 기능을 준비 중입니다. 현재 로그인·가입을 이용할 수 없습니다."}` |
| 로그인 상태 확인 | 🟡 미확인 | `GET /api/auth/me` | 경로는 있음 · 앞 단계가 남긴 값 없음(member) |
| 내 주문 보기 | 🟡 미확인 | `GET /api/my/orders` | 경로는 있음 · 앞 단계가 남긴 값 없음(member) |

## ⬜ 주문 만들기 <sub>고객</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 조건에 맞는 부품으로 조립 가능한지 확인 | 🔴 실패 | `POST /api/candidates/count → 200` | buildable=False (기대 True) · 응답 `{"total": 0, "count": 0, "effects": [{"label": "용도", "value": "게임", "applied": true, "delta": 0, "count_after": 0, "reason": "용도 하한 미달 부품 제외` |
| 견적 받기(용도 게임 · 예산 150만원) | 🔴 실패 | `POST /api/recommend → 500` | HTTP 500 · 응답 `500 UndefinedColumn: column "vram_gb" does not exist` |
| 주문 생성 | 🟡 미확인 | `POST /api/orders` | 경로는 있음 · 앞 단계가 남긴 값 없음(session_id, tier) |
| 주문 조회 | 🔴 실패 | `GET /api/commerce/orders/ORD-SCENARIO-PROBE → 503` | 대상 없이 두드려도 HTTP 503 — 이 단계는 지금 막혀 있다 · 응답 `{"code": "owner_configuration_unready"}` |

## ⬜ 결제하기 <sub>고객</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 결제 준비(주문 금액 확정) | 🔴 실패 | `—` | HTTP 경로 없음 — api/commerce_writer.py 의 create_draft·prepare 를 부르는 라우트가 없다 |
| 결제 승인 | 🔴 실패 | `—` | HTTP 경로 없음 — commerce_writer 의 dispatch·finalize 를 부르는 라우트가 없다 |
| 내 결제 내역 보기 | 🟡 미확인 | `GET /api/my/payments` | 경로는 있음 · 앞 단계가 남긴 값 없음(order_no, member) |

## ✅ 운영자 주문 관리 <sub>운영자</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 관리자 로그인 | 🟢 통과 | `POST /api/admin/auth/login → 200` | 실제 요청 통과 |
| 커머스 주문 목록 | 🟢 통과 | `GET /api/admin/commerce/orders → 200` | 실제 요청 통과 |
| 결제 내역 목록 | 🟢 통과 | `GET /api/admin/payments → 200` | 실제 요청 통과 |
| 환불 요청 목록 | 🟢 통과 | `GET /api/admin/refunds → 200` | 실제 요청 통과 |

## ⬜ 출고 등록과 배송 조회 <sub>운영자</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 출고 등록 | 🔴 실패 | `POST /api/admin/commerce/orders/ORD-SCENARIO-PROBE/fulfillment → 503` | 대상 없이 두드려도 HTTP 503 — 이 단계는 지금 막혀 있다 · 응답 `{"code": "fulfillment_origin_unconnected"}` |
| 고객이 배송 상태 보기 | 🔴 실패 | `GET /api/commerce/orders/ORD-SCENARIO-PROBE/fulfillment → 503` | 대상 없이 두드려도 HTTP 503 — 이 단계는 지금 막혀 있다 · 응답 `{"code": "owner_configuration_unready"}` |

## ⬜ 반품 <sub>고객 · 운영자</sub>

| 단계 | 판정 | 요청 | 근거 |
|---|---|---|---|
| 고객 반품 접수 | 🔴 실패 | `—` | HTTP 경로 없음 — 실물 반품 접수 라우트가 없다(api/commerce_physical_return_http.py 는 관리자 조회 GET 둘뿐) |
| 회수·입고 처리 | 🔴 실패 | `—` | HTTP 경로 없음 — 회수·입고·실행 라우트가 없다 |
| 운영자 반품 내역 보기 | 🟡 미확인 | `GET /api/admin/commerce/orders/ORD-SCENARIO-PROBE/physical-returns → 404` | 경로는 응답함(HTTP 404) · 앞 단계가 대상(order_no)을 못 만들어 실제 확인 못 함 · 응답 `{"code": "physical_return_not_found"}` |

