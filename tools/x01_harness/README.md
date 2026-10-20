# X01 격리 재현 — AI 슈퍼컴퓨터 «신규 장비 추가» 예외

운영 DB·운영 응답을 쓰지 않는다. 고정 입력(fixture JSON) + 이 저장소의 `/mvp4` 정적 파일만으로 메인 광고·목록·상세를 연다.

```
python tools/x01_harness/build_fixtures.py      # fixtures/C*.json + manifest.json(SHA256)
node tools/x01_harness/run.mjs [출력폴더]        # 기본 tools/x01_harness/out (git 제외)
```

- 응답은 실제 백엔드 함수 `api.customer_supercomputer.item()`이 만든다. Dell 표시 정보는 마이그레이션 0166 값을 그대로 쓴다.
- `input_rows[].detail`·프로필 칸에 직접 적은 값 = 명시 입력. 응답의 `derived`에 든 칸 = 상품명에서 백엔드가 읽은 값(화면에 «상품명 기준»).
- 운영체제는 상품명에서 읽지 않는다(값 없으면 «확인 필요»). 보증·OS 등 확인되지 않은 문구를 지어내지 않는다.
- «비노출»은 reader SQL(`AND p.is_visible`)이 빼는 결과를 흉내 내 목록에서 뺀다 — SQL 조건은 테스트가 소스로 확인한다.
- 가상 상품번호 900001~900004는 실제 상품이 아니다.

| 케이스 | 목적 |
|---|---|
| C01-current | 지금과 같은 Dell 2종 + 표시 정보 있는 타사 |
| C02-other-ranked-first | 타사가 대표 순위 1위 |
| C03-no-ranks / C04-same-ranks | 순위 없음 / 모두 같음 |
| C05-no-dell / C06-dell-hidden / C07-dell-stopped / C08-empty | Dell 없음 · 비노출 · 판매 중지 · 카테고리 비어 있음 |
| C09-one-dell | Dell 모델 하나만 |
| C10-missing-profile | 표시 정보·사진 없는 타사(GB10 이름 · DGX Spark 이름 · 비GB10) |
| C11-price-unknown | 판매가 없음 |

결과: `<출력폴더>/results.json`(커밋·fixture SHA256·케이스별 expect/actual/pass) + 캡처(1440·390·360).
