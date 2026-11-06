# ASUS AI PC 기획전 v4 + GT502 소재 v5

2026-11-05 · PC2 Claude. 경로는 `mockups/mvp4/` 기준이다.

| 화면 | 경로 |
|---|---|
| 홈 진입 배너 | `index.html` 롤링 배너 7번째 |
| 서브메인 | `asus.html` |
| 상세 3종 | `asus-pc.html?model=business`, `video`, `local-ai` |
| 문의 | `asus-consult.html?model=...` (`model` 없으면 3종 공통 문의) |

**2026-11-06부터 모델 값의 원천은 DB(`asus_campaign_models`, 마이그레이션 0178)다.** 고객 화면은 `GET /api/customer/asus-campaign`만 읽고, 관리자는 `/admin2/asus-campaign`에서 고친다. 실패하면 실패라고 표시하며 대신 보여 줄 값이 코드에 없다. `assets/js/asus-data.js`에는 저장으로 바꾸면 안 되는 고정값(공통 고지, 기획 검토가 표기, 상태 이름, 색조, 문의 항목 매핑)만 남았다. 초깃값은 `db/migrations/data/asus_campaign_models_20261106.json`이고 부품 가격은 2026-11-05 조회값이다. 소재 목록은 [ASSETS.md](ASSETS.md)에 있다.

**2026-11-06 표시 기준**: 상세 3종은 금액과 내부 검토 상태를 표시하지 않고 제품명과 확인된 부품 사진만 보여 준다. 내부 표현을 뺀 값은 `asus-data.js` 의 고객 어댑터가 만들며 DB · API · 관리자 값은 그대로다. 목록과 문의의 기획 검토가 표기는 유지한다. 홈 배너 1번은 ASUS이고 6초, 나머지는 3초다.

**2026-11-06 구성표 기준**: 상세 구성 표는 후보 목록(`parts[].options`)이 아니라 항목마다 대표 제품 1종을 고른 `build`만 그린다. 선정과 제외 근거, 남은 미확정 항목은 [PARTS-SELECTION.md](PARTS-SELECTION.md)에 있다.

저장이 닿는 범위: 서브메인 · 상세 · 문의 안내. 닿지 않는 범위: 일반 상품 · 판매가 · 재고 · 추천, 홈 배너, 공통 고지.

개발 DB에는 아직 적용하지 않았다. 적용 전 이 코드가 배포되면 고객 화면은 값 대신 불러오기 실패 안내를 표시하므로, 0178 적용과 코드 배포를 함께 해야 한다.

## 문의 연결

기존 `ai-inquiry.js`와 `service-adapters.js`를 고치지 않고 그대로 쓴다. `asus-inquiry.js`가 조회값을 채우고, 선택 안내를 ASUS 구성으로 바꾸고, 문의 내용칸에 선택 구성을 미리 넣는다. 접수 경로는 기존 `POST /api/mvp3/purchase-inquiries`다.

| 모델 | 기존 항목 매핑 |
|---|---|
| 문서·업무용 | `package=business`, `use=documents` |
| 영상·디자인용 | `package=advanced`, `use=image` |
| 로컬 AI 개발용 | `package=advanced`, `use=code` |

제약: 접수 내용 첫 줄은 기존 어댑터가 `[AI 패키지 견적 문의] 고급형`처럼 적고, 둘째 줄 이후에 `[ASUS 기획전] 모델명`이 온다. 주제는 `기타`로 저장된다. ASUS 전용 주제나 첫 줄은 어댑터·API 변경이 필요해 이번 범위에서 제외했다. 메시지 500자 제한도 기존 그대로라 고객이 내용을 길게 쓰면 뒤가 잘린다.

## 미확정 상태 (이번 작업으로 확정하지 않음)

- 5080, 5090, PRIME LC 360 ARGB 공급
- TeamGroup 메모리 제목·사양 불일치, 파워 세대·케이블
- 시스템팬, 조립·검수비, 배송비, 운영체제, 전체 합계
- 399만·599만·1,299만원은 기획 검토가이며 판매가·합계가 아니다
- 실제 조립 호환, ASUS 사진·상표 외부 사용 승인
