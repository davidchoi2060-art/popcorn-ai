# ASUS AI PC 기획전 v4 + GT502 소재 v5

2026-11-05 · PC2 Claude. 경로는 `mockups/mvp4/` 기준이다.

| 화면 | 경로 |
|---|---|
| 홈 진입 배너 | `index.html` 롤링 배너 7번째 |
| 서브메인 | `asus.html` |
| 상세 3종 | `asus-pc.html?model=business`, `video`, `local-ai` |
| 문의 | `asus-consult.html?model=...` (`model` 없으면 3종 공통 문의) |

화면 값의 단일 원천은 `assets/js/asus-data.js`다. API·DB를 읽지 않는 정적 자료이며 가격은 2026-11-05 조회값이다. 소재 목록은 [ASSETS.md](ASSETS.md)에 있다.

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
