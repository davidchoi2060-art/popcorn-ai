# 팝콘PC AI API 서버측 클라이언트

2026-11-09 · 원문 `PopcornPC_AI_API_사용_가이드.docx`(SHA256 `86cf99b2…`) · 상태: 라이브러리만 존재, 어디서도 부르지 않는다.

원격 주소는 운영 쇼핑몰이다. 개발 팝콘AI에서 불러도 쓰기 대상은 운영이다.

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

본문은 메모리에서만 분류하고 저장하지 않는다. 남기는 것은 종류, IP 개수와 관계(사설 여부, 몰 DNS 일치, 로컬 일치), 글자 모양이다. 64자 이하 비JSON 문구는 숫자를 가리고 긴 토큰과 글자·숫자 혼합 토큰을 지운 형태로 남긴다. IP가 들어 있으면 해시도 남기지 않는다. 짧은 본문은 해시에서 복원될 수 있어서다.

## 실서버 관측 (API-010)

2026-11-09 현재 이 환경의 호출은 전부 상태 200, `text/html`, `<공인 IPv4> IP ERROR!`를 받는다. 가이드의 "현재 IP 제한 없이"와 다르다. 클라이언트는 이를 `ip_rejected`로 실패 처리한다. 실제 가격은 아직 받은 적이 없다.

## 쓰기 차단

- `BasketClient`는 `basket_write_allowed`가 True인 transport에만 주소를 넘긴다. 이 값을 켠 코드는 테스트의 가짜뿐이다.
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
- `sale_state`는 항상 `unknown`, `currency`는 항상 없음이다. 반환된 상품을 판매 가능으로 판정하지 않는다.
- `pd_name`, `made`, `pd_spec`은 글자로만 남기지만, 화면에 넣을 때는 여전히 글자로 넣는다(`innerHTML` 금지).
- 이미지는 몰 https 절대 주소만 `image_url`로 준다. 상대 경로는 기준 주소가 문서에 없어 `image_path`로만 둔다.
- 응답의 미문서 필드는 값을 버리고 개수와 재고·통화·세금 유사 이름 존재 여부만 남긴다.
- basket 링크는 `https://popcornpc.co.kr/shop/order_basket_list.html?api_key=<요청 키>`와 한 글자라도 다르면 거부한다.
- basket 응답이 불명확하면 `outcome_unknown`이다. 자동 재시도가 없고 사람이 다시 누른 경우에만 `confirm_unknown`으로 보낸다.

## ASUS 연결 전 조건

- `ASUS_COMPLETE_SKUS`는 비어 있다. 완제품 3종 번호를 받기 전까지 전부 `sku_missing`이다.
- 같은 키는 목록을 교체하므로 모델마다 견적을 나눈다. 세 모델을 한 장바구니에 모으려면 다른 설계가 필요하다.
- `BasketCoordinator`는 메모리 상태다. 프로세스가 여러 개면 공용 저장소가 필요하다.
- 공개하려면 서버 경로와 프런트 연결 코드를 새로 만들어야 한다. 이번에는 만들지 않았다.
