# ASUS 기획전 장바구니 연결 계약 (내부 제안)

2026-11-06 · 대상 = `mockups/mvp4/assets/js/asus-cart.js`

**이 문서는 화면 쪽 연결 지점의 내부 제안이다. 팝콘PC API 명세가 아니다.** 엔드포인트, 상품번호, 인증 방식, 세션, 성공 응답, 판매가는 아직 받지 못했고 여기 정하지 않는다. 명세를 받으면 이 문서를 그 기준으로 고친다.

2026-11-09 추가: API 가이드를 받아 서버측 클라이언트와 연결 지점을 만들었다. 공개 연결은 하지 않았다. 현황은 `POPCORN-PC-API-CLIENT.md`를 본다.

2026-11-18 추가: 서버 경로와 화면 연결 코드를 만들었다. 아래 「2026-11-18 서버 연결」 절이 현행이다. 설정이 없으면(운영 서버 환경변수) 화면은 연결 전과 똑같이 동작한다.

## 2026-11-18 서버 연결

사장님 결정: 2026-11-23 오픈에 「장바구니에 담기」를 포함한다. 윈윈소프트 답변(2026-11-17)으로 확정된 사실 위에 만들었다.

### 파일

| 파일 | 역할 |
|---|---|
| `api/mall_asus_cart_api.py` | `GET /api/customer/asus-cart/status` · `POST /api/customer/asus-cart/add`. 설정 해석, 키 도출, 가격 조회 1건, basket 호출, 한도 |
| `api/mall_asus_cart.py` | 모델 id ↔ 완제품 번호 표의 검증(`validate_sku_map`: 구성 부품 번호를 완제품 번호로 쓰면 거부). 위 경로가 재사용한다 |
| `api/mall_ai_api.py` | basket v3 응답 해석, `LiveBasketTransport`(실제 쓰기 transport), `CallPacer`(호출 간격) |
| `mockups/mvp4/assets/js/asus-cart-live.js` | 위 두 경로를 `asus-cart.js` 의 `setAdapter` 계약으로 잇는 연결 코드. `asus.html` · `asus-pc.html` 에만 실린다 |
| `mockups/mvp4/assets/js/asus-cart.js` | adapter 에 `available(id)` · `newWindow` 가 더해졌다(아래) |

### 설정 — 전부 서버 환경변수(`/etc/popcorn-ai.env`), 저장소에 값 없음

| 변수 | 뜻 |
|---|---|
| `MALL_ASUS_CART_ENABLED` | `1` 이면 두 경로가 열린다. 없거나 다른 값이면 둘 다 404 → 화면은 연결 전과 같다 |
| `MALL_ASUS_CART_SKUS` | `business=<번호>,video=<번호>,local-ai=<번호>`. 완제품 3종의 쇼핑몰 상품번호(쇼핑몰 등록 뒤 받는다). 구성 부품 번호·중복·모르는 모델 id 가 있으면 설정 오류로 기능 전체가 꺼진다. 번호가 없는 모델은 `sku_missing` 으로 비활성 |
| `MALL_ASUS_CART_MODELS_ON` | 켤 모델 id 목록 `business,video`. 없으면 전부 꺼짐(`model_off`). 판매 상태는 이 설정으로 모델별로 켜고 끈다(사장님 확정). 윈윈의 `status` 는 참고값이다 |
| `MALL_ASUS_CART_KEY_SALT` | 키 도출에 섞는 서버 비밀. 16자 이상. 없으면 `enabled:false`, 담기는 503 `not_configured` |
| `MALL_BASKET_WRITE_ENABLED` | `1` 이어야 `api/mall_ai_api.LiveBasketTransport` 를 만들 수 있다. 없으면 담기가 네트워크 전에 `basket_write_blocked` 로 실패한다 |

**켜는 순서**: ① 쇼핑몰에 완제품 3종 등록 → 상품번호 수령 ② `MALL_ASUS_CART_SKUS` · `MALL_ASUS_CART_KEY_SALT` · `MALL_BASKET_WRITE_ENABLED=1` · `MALL_ASUS_CART_ENABLED=1` 을 넣고 `MALL_ASUS_CART_MODELS_ON` 은 비워 둔 채 재시작 → `status` 가 `enabled:false` 와 모델별 `model_off` 를 주는지 확인 ③ 운영 쇼핑몰 1회 시험(사전 승인) 뒤 `MALL_ASUS_CART_MODELS_ON` 에 팔 모델만 넣고 재시작.
**끄는 법**: 모델 하나만 → `MALL_ASUS_CART_MODELS_ON` 에서 빼고 재시작. 전부 → `MALL_ASUS_CART_ENABLED` 를 지우거나 `0` 으로 두고 재시작(404). 쓰기만 급히 막기 → `MALL_BASKET_WRITE_ENABLED` 를 지운다(가격 조회까지만 나가고 담기는 실패).

### 경로

`GET /api/customer/asus-cart/status` → `{enabled, models: {business|video|local-ai: {available, reason}}, origins, notice, notice_separate}`. `reason` 은 `null` | `model_off` | `sku_missing` | `config_error`. `origins` 는 담은 뒤 열어도 되는 쇼핑몰 출처(화면 코드에 주소가 없다). `Cache-Control: no-store`.

`POST /api/customer/asus-cart/add` 본문 `{modelId, quantity: 1}` → 200 `{ok: true, url, added: [{pd_no, qty}], skipped: [{pd_no, reason}], total, notice, notice_separate}` | `{ok: false, code}`(400 `unknown_model`·`bad_quantity`, 409 `model_off`·`sku_missing`·`sku_not_found`·`basket_skipped`·`busy`, 503 `not_configured`·`basket_write_blocked`, 502 그 밖의 쇼핑몰 오류 코드, 쓰기 뒤 결과 불명이면 `outcome_unknown: true`). 같은 출처가 아니면 403, 한도를 넘으면 429(`detail.error = rate_limited`).

### 키 도출 규칙

`sha256("<salt>|<방문자 축>|<모델 id>")` 의 앞 20자(16진수 = 영숫자 20자). 방문자 축은 `api/access_gate.subject_of` 와 같다 — 방문자 쿠키 `pc_vid` 가 있으면 그 사람(`u:<user_id>`), 없으면 접속 IP(`ip:…`). 쿠키를 새로 심지 않고 거절하지도 않는다. 같은 고객이 같은 모델을 다시 담으면 같은 키 → 쇼핑몰이 기존 목록을 교체한다. 다른 모델은 다른 키 → 모델마다 장바구니가 따로 생긴다. salt 를 바꾸면 모든 키가 바뀐다(기존 장바구니와 끊긴다).

### 담기 흐름과 안전장치

① 같은 출처 검사(`api/mvp3_saved_quotes.same_origin`) ② 방문자 분당 3회·일 30회(`api/access_gate.check_rate`, 정책 키 `visitor.asus_cart`, `rate_limit_policies` 로 조절 가능) ③ 가격 조회 1건: `not_found` 면 `sku_not_found` 로 거절, `sold_out` 이면 서버 로그에 건수로만 남기고 진행 ④ basket GET 1회(재시도 없음, 같은 키 동시 요청은 `busy`) ⑤ 윈윈 호출은 프로세스 안에서 한 번에 하나, 간격 1초(`CallPacer`). 로그에는 모델 id·건수·오류 코드만 남는다(상품명·가격·키·방문자 축 없음).

### 화면

`asus-cart-live.js` 가 `status` 를 한 번 부른다. 404·실패·`enabled:false`·켜진 모델 없음·`origins` 가 정규 https 출처가 아님 → `setAdapter` 를 부르지 않아 **연결 전과 똑같이** 비활성 + 「장바구니 준비 중입니다.」다. 켜져 있으면 `available` 이 아닌 모델만 비활성(같은 안내). 성공하면 현재 화면을 떠나지 않고 서버가 준 `notice` + `notice_separate` 를 버튼 아래에 보이며 `url` 을 새 창(`noopener`)으로 연다. 팝업이 막혀도 「장바구니 열기」 링크(`rel="noopener noreferrer"`)가 남는다. 실패는 기존 문구 그대로다.

`setAdapter` 계약에 더해진 것: `available(id)`(선택, 함수) — false 인 모델은 준비 중과 같이 비활성. `newWindow`(선택, true) — 성공 시 이동 대신 새 창 + 안내. 둘 다 없으면 2026-11-06 동작 그대로다.

### 윈윈 확정 사항 요약(2026-11-17 답변)

- 호출 방식은 기존 그대로(`GET /shop/ai_api.php?api_id=basket&api_key=<영숫자 20자>&pd_no=<번호>:<수량>`). 인증 헤더 없음, IP 로만 제어, 호출 제한 없음.
- 응답은 v3 `{cart_url, added, skipped, total}`. **added/skipped 항목 모양은 아직 실측이 없다**(11-21 실측 예정). 지금은 added `{pd_no, qty}`(qty 생략은 1), skipped `{pd_no, reason}` 또는 번호 하나로 가정했고, 모르는 필드는 버린다. `total` 은 정수로만 받고 뜻(줄 수·수량 합)은 확정하지 않았다.
- 403 은 `{"error":"허용되지 않은 IP"}` JSON → `ip_rejected`. 400 JSON → `mall_request_rejected`(가격 조회와 같은 코드).
- 같은 api_key 로 다시 담으면 기존 목록을 지우고 교체한다 → 모델마다 다른 키.
- `cart_url` 형식은 기존(`order_basket_list.html?api_key=…`)과 같고 브라우저에서 바로 열린다. 키 규칙은 영숫자 20자.
- 비회원 장바구니는 브라우저를 닫으면 사라지고, 바로 로그인·가입하면 유지된다 → 화면 안내 문구(`notice`, 사장님 확인 대상).
- 완제품 3종의 상품번호는 아직 없다 → 코드에 넣지 않고 `MALL_ASUS_CART_SKUS` 로 받는다.

### 11-21 운영 쇼핑몰 시험 때 볼 것

`cart_url` 이 `expected_link(key)` 와 한 글자도 다르지 않은가 · `added` 항목의 키 이름과 `pd_no`/`qty` 타입(문자열인가 숫자인가) · `skipped` 가 빈 배열인가 `null` 인가, 항목 모양과 `reason` 값 · `total` 의 뜻 · 403/400 본문 · 응답 `Content-Type`. 실행기 `tools/popcorn_api_runner.py --api basket` 의 `response_shape` 가 이 모양을 값 없이 기록한다.

## 확정된 것

- 담는 대상은 완제품 3종 중 하나, 각 1대다. 부품 묶음이 아니다.
- 사용자 일정: API를 다음 주에 붙인다.

## 지금 동작 (연결 전 기본값)

- 목록 카드 3개와 상세 3종에 비활성 「장바구니에 담기」와 「장바구니 준비 중입니다.」를 표시한다.
- 네트워크 쓰기, 이동, 브라우저 저장을 하지 않는다.
- 담기 성공을 표시하지 않고, 몰 홈이나 빈 장바구니로 보내지 않으며, 옛 몰 폼을 쓰지 않는다.

## 교체 지점

`asus-cart.js`는 고치지 않고, 연결 코드에서 한 번 부른다.

```js
PAI.asusCart.setAdapter({
  origins: ['<담은 뒤 이동을 허용할 https 출처>'],   // 끝 슬래시 · 경로 · 계정 없는 정규 출처만. 아니면 setAdapter 가 예외를 던진다
  add: function (request) {
    // request = { modelId: 'business' | 'video' | 'local-ai', quantity: 1 }
    // 반환: Promise<{ ok: true, url: '<이동 주소>' } | { ok: false, code: '<사유>' }>
  }
});
```

연결 코드가 맡는 일: 모델 id를 팝콘PC 완제품 번호로 바꾸는 표, API 호출, 인증과 세션. 표는 API 명세를 받은 뒤 만든다. `asus_campaign_models.content`의 부품 `mall_no`와 `plan_review_price`를 담기 값으로 쓰면 안 된다.

## 화면이 보장하는 것 (`asus-cart.js`, 테스트로 고정)

| 상황 | 동작 |
|---|---|
| adapter 없음 | 비활성 + 준비 중 안내. 호출 없음 |
| 알 수 없는 모델 id | 호출 없음 |
| 요청 중 | 그 모델 버튼 비활성 + 「담는 중」. 다시 눌러도 호출은 한 번 |
| `ok: true` + 허용 출처 주소 | 그 주소로 이동. 화면 성공 문구는 없음 (2026-11-18: adapter 가 `newWindow` 면 이동 대신 새 창 + 안내 문구 — 「2026-11-18 서버 연결」 절) |
| `ok: true`인데 주소 없음 · https 아님 · 계정 정보 포함 · 허용 밖 | 실패로 처리 |
| 요청 중 `setAdapter`로 교체 · 해제 | 앞선 응답은 버림. 이동 없음, 현재 상태 변경 없음. 판정은 요청 당시 연결의 출처로 한다 |
| `ok: false` · 오류 · 15초 초과 | 실패 안내 후 다시 누를 수 있음 |
| 시간 초과 뒤 늦은 응답 | 무시 |

## API를 받으면 확인할 것

1. **중복 담기.** 시간 초과는 서버에 담겼는지 모르는 상태다. 사용자가 다시 누르면 2대가 될 수 있다. 멱등 키나 수량 고정 방식이 있는지 확인한다. 답에 따라 시간 초과 안내 문구를 바꾼다.
2. **비회원 · 세션.** 로그인이 필요한지, 도메인이 달라도 세션이 유지되는지. 교차 출처면 CORS와 쿠키 조건도 본다. 화면에서 직접 부를지 서버를 거칠지는 이 답에 달렸다.
3. **성공 응답.** 이동 주소를 주는지, 어느 출처인지.
4. **실패 사유.** 품절, 판매 중지, 인증 실패를 구분해 주는지. 구분된다면 안내 문구를 나눈다. 지금은 한 문구다.
5. **판매 조건.** 3종의 완제품 상품번호와 판매가가 정해졌는지. 지금 화면의 기획 검토가와 담기 금액의 관계를 사용자가 정해야 한다.

## 다음 주 미완료 목록

- [ ] 팝콘PC API 명세 수령(엔드포인트, 인증, 세션, 성공 · 실패 응답)
- [ ] 완제품 3종 상품 등록과 상품번호 수령
- [ ] 위 확인 사항 1~5 답변
- [ ] adapter 구현과 모델 id · 상품번호 표
- [ ] 실제 담기를 시험 계정으로 확인(운영 몰에 쓰는 시험은 사전 승인 필요)
- [ ] 상세 금액 비표시 지시와 담기 금액 표시 방식 재확인
