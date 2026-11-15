# 윈윈 가격 조회 중계기 사용 안내

2026-11-15 · `api/mall_ai_gateway.py`

## 무엇인가

윈윈(팝콘PC) AI API는 허용된 IP에서 온 요청에만 답한다. 그 IP는 GCP 개발 서버다. 사무실 PC나 대표자 PC에서 바로 부르면 `IP ERROR!`가 돌아온다.

이 중계기는 개발 서버에서 윈윈에 가격을 대신 묻고 그 결과를 돌려준다.

```
사무실·집 PC ──HTTPS──▶ dev.popcornai.co.kr (허용 IP만 통과) ──▶ 윈윈 price API
```

- 읽기 전용이다. 가격만 조회한다. 장바구니, 주문, 결제는 할 수 없다.
- 등록된 IP에서만 열린다. 그 밖의 위치에서는 `403`이 돌아온다.
- 원가가 들어 있으니 화면을 외부에 공유하지 않는다.

## 조회 방법

### 조회 화면 (사람이 볼 때)

브라우저에서 연다. 즐겨찾기에 넣어 두면 편하다.

```
https://dev.popcornai.co.kr/api/mall-ai-gateway/lookup
```

1. 상품번호 칸에 번호를 넣는다. 쉼표, 공백, 줄바꿈 어느 것으로 구분해도 된다. 한 번에 50개까지 넣을 수 있다. 엑셀 열을 그대로 붙여 넣어도 된다.
2. `조회`를 누르거나 `Ctrl+Enter`를 누른다.
3. 표에 판매가, 원가, 판매가−원가, 딜러가 1~3, 소비자가, 시중가, 적립금, 배송비, 재고값이 나온다.
4. `표 복사`를 누르면 엑셀에 붙여 넣을 수 있는 형식으로 복사된다.

- 주소 뒤에 `?pd_no=124401,124407`을 붙이면 열자마자 그 번호로 조회한다. 자주 보는 묶음을 즐겨찾기로 만들 때 쓴다.
- 「—」는 윈윈 응답에 값이 없거나 0이거나 비정상인 칸이다.
- 윈윈이 돌려주지 않은 번호는 빨간 줄로 「윈윈 응답에 없는 상품번호」라고 표시한다.

### 브라우저에서 JSON 그대로 보기

```
https://dev.popcornai.co.kr/api/mall-ai-gateway/price?pd_no=124401,124407,124409
```

### PowerShell (Windows)

```powershell
$r = Invoke-RestMethod "https://dev.popcornai.co.kr/api/mall-ai-gateway/price?pd_no=124401,124407"
$r.items | Select-Object pd_no, name, @{n='판매가';e={$_.price.value}}, @{n='원가';e={$_.internal.pd_cost_price.value}}
```

### 엑셀

`데이터` → `웹에서` → 위 주소를 넣는다. 파워 쿼리에서 `items`를 펼친다.

### 파이썬

```python
import json, urllib.request
url = "https://dev.popcornai.co.kr/api/mall-ai-gateway/price?pd_no=124401,124407"
data = json.load(urllib.request.urlopen(url, timeout=10))
for item in data["items"]:
    print(item["pd_no"], item["price"]["value"], item["internal"]["pd_cost_price"]["value"])
```

## 응답

```json
{
  "requested": ["124401"],
  "missing": [],
  "items": [
    {
      "pd_no": "124401",
      "found": true,
      "name": "상품명",
      "maker": "제조사",
      "spec_text": "사양 원문",
      "image_path": "/data/pimg/124/124401.jpg",
      "price": {"status": "ok", "value": "7700"},
      "mileage": {"status": "ok", "value": "10"},
      "delivery_price": {"status": "ok", "value": "4000"},
      "internal": {
        "pd_cost_price": {"status": "ok", "value": "..."},
        "dealer1_price": {"status": "ok", "value": "..."},
        "dealer2_price": {"status": "ok", "value": "..."},
        "dealer3_price": {"status": "ok", "value": "..."},
        "pd_sijung_price": {"status": "ok", "value": "..."},
        "pd_sobija_price": {"status": "ok", "value": "..."},
        "pd_remain": {"status": "zero", "value": "0"}
      }
    }
  ],
  "source": "popcornpc ai_api price (read only)"
}
```

| 항목 | 뜻 |
|---|---|
| `price` | 판매가 |
| `mileage` | 적립금 |
| `delivery_price` | 배송비 |
| `internal.pd_cost_price` | 원가 |
| `internal.dealer1_price` ~ `dealer3_price` | 딜러가 1~3 |
| `internal.pd_sijung_price` | 시중가 |
| `internal.pd_sobija_price` | 소비자가 |
| `internal.pd_remain` | 재고로 보이는 값. 뜻은 윈윈 확인 전이다 |
| `missing` | 윈윈이 돌려주지 않은 상품번호 |

금액은 모두 `{"status", "value"}` 형태다. `value`는 문자열이다.

- `ok`: 정상 금액
- `zero`: 0. 무료라는 뜻인지 문서에 없다
- `missing`: 윈윈 응답에 필드가 없다
- `null`, `invalid`, `negative`, `non_integer`: 비정상 값이라 쓰지 않는다

`image_path`는 상대 경로다. 앞에 붙일 기준 주소는 아직 정하지 않았다.

## 오류

| 상태 | `detail.code` | 원인과 조치 |
|---|---|---|
| 403 | `ip_not_allowed` | 등록되지 않은 위치다. 아래 "IP 추가·변경"을 본다 |
| 400 | `invalid_pd_no`, `too_many_items`, `invalid_query` 등 | 상품번호 형식이 틀렸다. 숫자를 쉼표로 1~50개 넣는다 |
| 429 | `busy` | 다른 조회가 진행 중이다. 1초 뒤 다시 조회한다 |
| 502 | `ip_rejected`, `timeout`, `network` 등 | 윈윈 쪽 문제다. `ip_rejected`면 개발 서버 IP가 윈윈 허용 목록에서 빠진 것이다 |
| 404 | - | 중계기가 꺼져 있다 |

## 사용 규칙

- 조회는 한 번에 하나, 1초 간격이다. 반복 스크립트는 1초 이상 쉬게 한다.
- 결과를 고객 화면, 외부 메신저, 공개 문서에 붙이지 않는다. 원가가 들어 있다.
- 재시도와 캐시는 없다. 매번 윈윈에 새로 묻는다.
- 서버 로그에는 조회 건수와 오류 코드만 남는다. 상품명, 가격, IP는 남지 않는다.

## 관리자용: 켜기, 끄기, IP 변경

설정은 개발 서버의 `/etc/popcorn-ai.env`에 있다. IP는 저장소에 적지 않는다.

```
MALL_AI_GATEWAY_ENABLED=1
MALL_AI_GATEWAY_ALLOW_IPS=<사무실 IP>,<집 IP>
```

바꾼 뒤에는 서비스를 다시 시작해야 반영된다.

```bash
sudo systemctl restart popcorn-api
```

- **끄기:** `MALL_AI_GATEWAY_ENABLED=0`으로 바꾸고 재시작한다. 모든 요청이 404가 된다.
- **IP 추가·변경:** `MALL_AI_GATEWAY_ALLOW_IPS`에 쉼표로 더하고 재시작한다. 내 IP는 `https://www.google.com/search?q=what+is+my+ip`에서 확인할 수 있다.
- **집 인터넷 IP:** 가정용 인터넷 IP는 공유기를 다시 켜거나 통신사 사정으로 바뀔 수 있다. 갑자기 403이 나면 IP부터 확인한다.
- **운영 서버:** 이 값을 넣지 않는다. 운영 서버 IP는 윈윈 허용 목록에 없다고 보고, 원가 조회 경로를 운영에 열 이유가 없다.

## 보안상 알아 둘 것

- 사무실 안에서 같은 공인 IP를 쓰는 모든 기기(손님 와이파이 포함)는 이 주소를 열 수 있다. 막아야 하면 접속 키를 추가해야 한다.
- 접속 IP는 nginx가 넘긴 값으로 판정한다. 요청 헤더를 꾸며 IP를 속이는 경우는 거부하도록 시험했다.
