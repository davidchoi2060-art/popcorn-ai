# 팝콘PC AI API 서버측 클라이언트

2026-11-09 · 원문 `PopcornPC_AI_API_사용_가이드.docx`(SHA256 `86cf99b2…`) · 상태: 라이브러리만 존재, 어디서도 부르지 않는다.

원격 주소는 운영 쇼핑몰이다. 개발 팝콘AI에서 불러도 쓰기 대상은 운영이다.

> **2026-11-17 price 응답이 바뀌었다.** 아래 「2026-11-17 응답 변경」 절이 현행이다. 그 밖의 절에서 price 응답을 말하는 부분 중 낡은 곳에는 「(낡음 2026-11-17)」 표시를 달았다.
>
> **2026-11-18 basket 응답 해석을 v3 모양으로 바꿨고 실제 쓰기 transport 와 ASUS 장바구니 경로를 만들었다.** 아래 「2026-11-18 basket v3」 절이 현행이다. 옛 basket 서술(`result="ok"`, `link`, `items`)은 낡았다. 상태 줄 「라이브러리만 존재, 어디서도 부르지 않는다」도 낡았다 — `api/mall_ai_gateway.py`(price)와 `api/mall_asus_cart_api.py`(price + basket)가 부른다.

## 2026-11-18 basket v3

윈윈 답변(2026-11-17): 호출 방식은 그대로(`GET /shop/ai_api.php?api_id=basket&api_key=<영숫자 20자>&pd_no=<번호>:<수량>,…`), 응답은 v3 `{cart_url, added, skipped, total}`. 실측 예시는 2026-11-21 예정이라 **항목 모양은 가정이다.**

| 키 | 받는 모양 | 없거나 틀리면 |
|---|---|---|
| `cart_url` | 문자열. `https://popcornpc.co.kr/shop/order_basket_list.html?api_key=<요청 키>` 와 한 글자도 다르면 거부 | 없으면 `bad_shape`(detail `cart_url`), 다르면 `bad_link`(결과 불명) |
| `added` | 배열. 항목은 `{pd_no, qty}`(가정 — `qty` 생략은 1) 또는 번호 하나. 모르는 필드는 버리고 `dropped_field_count` 에 센다 | `bad_shape`(detail `added`) |
| `skipped` | 배열 또는 `null`. 항목은 `{pd_no, reason}`(가정 — `reason` 은 글자로만 64자) 또는 번호 하나 | `bad_shape`(detail `skipped`) |
| `total` | 0 이상 정수. 뜻(줄 수인지 수량 합인지)은 확정하지 않았다 — 그대로 옮긴다 | `bad_shape`(detail `total`) |

판정: 요청한 줄이 전부 `added` 에 같은 수량으로 있어야 성공이다(`BasketReceipt.added/skipped/total/public()`). 요청한 번호가 `skipped` 에 있으면 `basket_skipped` — 담기지 않은 것이 확정이라 `outcome_unknown` 이 아니다. 같은 번호가 양쪽에 있으면 `inconsistent_response`(불명). 그 밖의 불일치는 `basket_mismatch`(불명). 200 인데 `error` 키가 있으면 `api_error`(키 길이 문구면 `api_key_length`). 403/400 의 JSON `error` 는 price 와 같은 코드(`ip_rejected`, `mall_too_many_items`, `mall_request_rejected`)이고 서버가 거절한 것이라 불명이 아니다. JSON `error` 가 없는 4xx 는 그대로 `http_4xx`(불명).

### 실제 쓰기 transport — `LiveBasketTransport`

환경변수 `MALL_BASKET_WRITE_ENABLED=1` 이 없으면 만들 수 없다(`basket_write_blocked`). 만들 때 받은 키와 줄로 주소 하나를 정하고 그 주소만, 정확히 한 번만 보낸다. `basket_write_allowed` 는 인스턴스에만 켜고 클래스 값은 False 다. 재시도가 없다. 이제 `basket_write_allowed = True` 를 적는 자리는 둘이다 — 실행기의 승인 1회 시험용 transport와 이 클래스(`tests/test_popcorn_pc_api_20261109.py` S02 가 센다).

### 호출 간격 — `CallPacer`

프로세스 안에서 윈윈 호출을 한 번에 하나, 간격 1초 이상으로 띄운다. 겹치면 `busy` 를 던지고 기다리지 않는다. `api/mall_ai_gateway.py` 의 `_upstream`/`_last_call` 과 같은 장치를 한 벌로 뺀 것이다(중계기는 그대로 자기 장치를 쓴다).

### ASUS 장바구니 경로

`api/mall_asus_cart_api.py` · 설정과 흐름은 `CART-ADAPTER.md` 「2026-11-18 서버 연결」에 적었다.

## 2026-11-17 응답 변경

호출 방식(`GET /shop/ai_api.php?api_id=price&pd_no=1,2,3`)은 그대로다. 인증 헤더와 키는 없다. 허용된 IP만 통과한다. 바뀐 것은 응답이다.

### 새 응답 모양 (실측)

정상은 HTTP 200, `application/json`이다. 봉투에 `result` 키가 없다.

```json
{
  "checked_at": "2026-11-17 14:42:35",
  "items": [
    {"pd_no": 124401, "name": "상품명", "price": 7700, "status": "sold_out", "max_qty": null}
  ],
  "not_found": [999999999]
}
```

| 경우 | 응답 |
|---|---|
| 허용되지 않은 IP | HTTP 403 `{"error":"허용되지 않은 IP"}`. 예전에는 200 `text/html` `<IP> IP ERROR!`였다 |
| 상품번호 50개 초과 | HTTP 400 `{"error":"상품번호가 50개를 넘음"}` |
| 숫자가 아닌 `pd_no` | HTTP 200, `items`는 빈 배열, `not_found`는 `null` |

### 명세와 다른 점 (2026-11-17 실측)

| 항목 | 명세 | 실측 | 클라이언트 처리 |
|---|---|---|---|
| `status` | `on_sale` 등 | 모든 상품이 `sold_out` (윈윈 쪽 결함으로 추정) | 값을 그대로 옮긴다. 판매 가능 여부를 판정하지 않는다 |
| `max_qty` | 수량 | 모든 상품이 `null` | `none`으로 표시한다 |
| `not_found` | 배열 | 없는 번호가 없으면 `[]`가 아니라 `null` | `null`과 배열을 모두 받는다 |
| `checked_at` | `+09:00` ISO 형식 | `YYYY-MM-DD HH:MM:SS` (시간대 표시 없음) | 두 형식을 모두 받는다 |
| `name` | 상품명 | HTML 태그(`<font color=…>` 등)와 판촉 문구가 섞여 온다 | 태그만 벗기고 판촉 문구는 그대로 둔다 |
| `price` | 금액 | 0인 상품이 있다 | `zero`로 분류한다. 무료로 확정하지 않는다 |

### 공개 필드

`PriceResult.public()`:

| 필드 | 뜻 |
|---|---|
| `requested` | 요청한 상품번호(중복 제거, 요청 순서) |
| `checked_at`, `checked_at_format` | 쇼핑몰이 준 조회 시각 문자열 그대로와 그 형식(`local` 또는 `iso_offset`) |
| `not_found` | 쇼핑몰이 `not_found`로 답한 번호 중 요청한 것 |
| `missing` | 요청했는데 `items`에도 `not_found`에도 없는 번호 |
| `items` | 요청 순서대로 한 줄씩. 없는 번호도 줄이 있다 |
| `unrequested_count` | 요청하지 않았는데 온 번호 수. 값은 버린다 |
| `dropped_field_count`, `observed` | 허용 필드 밖의 필드 수와 재고·통화·세금 유사 이름 존재 여부 |

`PriceItem.public()`:

| 필드 | 뜻 |
|---|---|
| `pd_no` | 상품번호 문자열 |
| `found`, `lookup` | `lookup`은 `found`, `not_found`, `missing` 중 하나 |
| `name` | HTML을 벗긴 상품명. 없으면 `null` |
| `price` | `{"status", "value"}`. 상태는 아래 「값 처리 규칙」과 같다 |
| `status`, `status_raw` | `status`는 `on_sale`, `sold_out`, `unknown` 중 하나. `status_raw`는 쇼핑몰이 준 글자(64자까지, 글자로만) |
| `max_qty` | `{"status", "value"}`. 상태는 `none`(null), `ok`(양의 정수), `missing`(필드 없음), `invalid` |

없어진 공개 필드: `maker`, `spec_text`, `image_status`, `image_url`, `image_path`, `mileage`, `delivery_price`, `sale_state`, `currency`, `internal`. 없어진 상수와 함수: `INTERNAL_PRICE_FIELDS`, `fetch_prices(internal_fields=…)`, `classify_image`.

### 오류 코드

| 코드 | 뜻 |
|---|---|
| `ip_rejected` | 403에 JSON `error`, 또는 예전 형태(`<IP> IP ERROR!`, 상태 200 또는 403) |
| `mall_too_many_items` | 400에 JSON `error`가 실측 문구와 같다 |
| `mall_request_rejected` | 400에 그 밖의 JSON `error` |
| `http_4xx` | 그 밖의 4xx. 403과 400도 JSON `error`가 없으면 여기다 |
| `bad_shape` | `items`가 배열이 아니다, `not_found`가 없거나 배열·null이 아니다, 항목이나 번호 모양이 틀렸다. `detail`에 `items` 또는 `not_found`가 적힌다 |
| `bad_checked_at` | `checked_at`이 없거나 두 형식 어느 쪽도 아니다 |
| `inconsistent_response` | 같은 번호가 `items`와 `not_found`에 함께 있다 |
| `duplicate_item` | 요청한 번호가 `items`에 두 번 있다 |
| `api_error` | 200인데 `error` 키가 있다 |

`unexpected_item`은 없어졌다. 요청하지 않은 번호는 오류가 아니라 버리고 `unrequested_count`에 센다. `redirect`, `rate_limited`, `http_5xx`, `http_status`, `timeout`, `network`, `response_too_large`, `empty_body`, `bad_encoding`, `html_response`, `bad_json`은 그대로다.

### 그대로인 것

- (낡음 2026-11-18: basket 응답 해석은 v3 로 바꿨다 — 「2026-11-18 basket v3」.) basket 응답 해석(`result="ok"`, 링크 대조, `outcome_unknown`)은 바꾸지 않았다. basket 응답이 함께 바뀌었는지는 확인하지 않았다.
- `LivePriceTransport`는 400과 403일 때만 오류 본문을 읽는다. 그 밖의 오류 상태는 예전처럼 본문을 버린다.
- 로그에는 건수와 오류 코드만 남는다. 상품명, 가격, 조회 시각, 쇼핑몰 오류 문구는 남기지 않는다.
- 실행기의 basket 시험은 직전 price에 `missing`과 `not_found`가 모두 비어 있을 때만 나간다.

## 파일

| 파일 | 역할 |
|---|---|
| `api/mall_ai_api.py` | price 조회, basket 요청과 응답 검증, transport, 마스킹. 라우터 없음 |
| `api/mall_asus_cart.py` | ASUS 모델 id를 완제품 번호로 바꾸는 연결 지점. `asus-cart.js` setAdapter 계약과 같은 값을 돌려준다. 라우터 없음 |
| `tools/popcorn_api_runner.py` | 시험 실행기. 기본 offline, live 는 price 만 |
| `tests/popcorn_pc_fake_api.py` | 메모리 가짜 API |
| `tests/test_popcorn_pc_api_20261109.py` | 29개 케이스와 실행기·transport 시험 |

## 실행

```bash
python tools/popcorn_api_runner.py --out result.json
```

live 는 문서 예시 3개 상품, 기록부 기준 누적 10회, 호출 간 1초 이상이다. 10회는 사용자 작업용 내부 상한(`INTERNAL_RUNNER_LIVE_BUDGET`)이고 API 공식 제한이 아니다. 공식 제한은 호출당 상품 50개다.

직전 호출이 정상이 아니면 실행기가 거부한다. 이어 가려면 `--resume-reason "사유"`를 준다. 사유는 같은 기록부 항목에 남고 앞선 항목은 고치지 않는다. 기록부를 고쳐 이 거부를 넘기지 않는다.

새 기록부는 `--init-ledger`로만 만든다. 다만 실행기는 다른 경로의 기록부를 알 수 없으므로, 새 경로로 예산을 다시 시작하지 않는 것은 운영 규칙이다.

## 비정상 응답 진단

본문은 메모리에서만 분류하고 저장하지 않는다. 남기는 것은 고정 종류, 고정 키워드 묶음, IP 개수와 관계(사설 여부, 몰 DNS 일치, 로컬 일치), 글자 모양이다. 본문의 단어는 어떤 형태로도 남기지 않는다. 관측된 문구는 전체가 정확히 일치할 때만 고정 라벨 `ip_error`로 적는다. 64자 이하 본문과 IP가 든 본문은 해시도 남기지 않는다. 해시에서 복원될 수 있어서다.

## 실서버 관측 (API-010)

(낡음 2026-11-17: 허용되지 않은 IP는 이제 HTTP 403 JSON으로 온다. 예전 형태도 계속 `ip_rejected`로 처리한다. 「2026-11-17 응답 변경」을 본다.)

2026-11-09 현재 이 환경의 호출은 전부 상태 200, `text/html`, `<공인 IPv4> IP ERROR!`를 받는다. 가이드의 "현재 IP 제한 없이"와 다르다. 클라이언트는 이를 `ip_rejected`로 실패 처리한다. 실제 가격은 아직 받은 적이 없다.

## 쓰기 차단

- `BasketClient`는 `basket_write_allowed`가 True인 transport에만 주소를 넘긴다. 이 값을 켜는 곳은 테스트의 가짜, 실행기의 `--api basket`(사용자 승인 1회 시험, 2026-11-11), 그리고 환경변수 스위치 뒤의 `LiveBasketTransport`(2026-11-18)다. (낡음 2026-11-18: 「`api/` 안에는 없다」)
- `LivePriceTransport`는 `assert_price_only_url`을 지나지 않은 주소를 내보내지 않는다.
- 실제 쓰기를 열려면 샌드박스 확인과 별도 승인이 먼저다(이슈 API-001).

## 제한값의 근거

| 값 | 근거 |
|---|---|
| 상품 50개, 키 20자리, 수량 생략 1, 같은 키 교체 | 문서 |
| 시간 제한 6초, 응답 2MB, 수량 99, 금액 10^12, 문자 길이 | 내부 방어값. API 공식 보장이 아니다 |
| 키 받는 규칙 영숫자, 생성 규칙 숫자 20자리 | 내부 규칙. 문자 집합은 문서에 없다(API-008) |

## 값 처리 규칙

- 금액 상태는 `ok | zero | missing | null | invalid | negative | non_integer`다. `ok`만 금액으로 쓴다. 0을 무료로 확정하지 않는다.
- (낡음 2026-11-17: `sale_state`와 `currency` 필드는 없어졌다. 지금은 쇼핑몰의 `status`를 그대로 옮긴다. 반환된 상품을 판매 가능으로 판정하지 않는 것은 그대로다.) `sale_state`는 항상 `unknown`, `currency`는 항상 없음이다. 반환된 상품을 판매 가능으로 판정하지 않는다.
- (낡음 2026-11-17: 지금 글자로 남기는 필드는 `name`과 `status_raw`다. `innerHTML` 금지는 그대로다.) `pd_name`, `made`, `pd_spec`은 글자로만 남기지만, 화면에 넣을 때는 여전히 글자로 넣는다(`innerHTML` 금지).
- (낡음 2026-11-17: 새 응답에 이미지 필드가 없어 이 처리를 없앴다.) 이미지는 몰 https 절대 주소만 `image_url`로 준다. 상대 경로는 기준 주소가 문서에 없어 `image_path`로만 둔다.
- 응답의 미문서 필드는 값을 버리고 개수와 재고·통화·세금 유사 이름 존재 여부만 남긴다.
- basket 링크(`cart_url`)는 `https://popcornpc.co.kr/shop/order_basket_list.html?api_key=<요청 키>`와 한 글자라도 다르면 거부한다.
- basket 응답이 불명확하면 `outcome_unknown`이다. 자동 재시도가 없고 사람이 다시 누른 경우에만 `confirm_unknown`으로 보낸다.

## ASUS 연결 전 조건

- `ASUS_COMPLETE_SKUS`는 비어 있다. 완제품 3종 번호는 코드가 아니라 서버 환경변수 `MALL_ASUS_CART_SKUS` 로 받는다(2026-11-18).
- 같은 키는 목록을 교체하므로 모델마다 키를 나눈다. 세 모델을 한 장바구니에 모으지 않는다(윈윈 확정).
- `BasketCoordinator`는 메모리 상태다. ASUS 경로는 키를 방문자+모델로 결정적으로 도출하므로 이 조정자를 쓰지 않고, 같은 키의 동시 요청만 프로세스 안에서 막는다.
- (낡음 2026-11-18) 공개하려면 서버 경로와 프런트 연결 코드를 새로 만들어야 한다. → `api/mall_asus_cart_api.py` · `mockups/mvp4/assets/js/asus-cart-live.js` 로 만들었다. 설정이 없으면 404 라 화면은 연결 전과 같다.
