# 고객용 PC 구성 미리보기

원본 `D:/WORK/PopcornAI/outputs/pc-builder-prototype-20261023`에서 고객 페이지용으로 분리한 React/Vite 소스입니다. 원본 Sites worker와 배포 설정은 포함하지 않습니다.

- 고객 경로: `/mvp4/pc-builder/`
- 빌드 산출물: `mockups/mvp4/pc-builder/` (저장소에 함께 포함)
- 고객 서버는 빌드된 정적 파일을 제공하며 Node.js 런타임이 필요하지 않습니다.
- 부품 상담(`POST /api/pc-builder/advise`)과 나머지 채우기(`POST /api/pc-builder/fill`)는 서버(`api/pc_builder_advisor.py`)가 실제 AI를 부른다(2026-10-25).
  후보·판매가·호환 판정·최소 구성 금액·부족액은 서버(`api/pc_builder_data.py`)가 계산하고, AI는 그 후보 안에서 고르고 이유를 쓴다.
  화면은 LLM 키·제공자를 모른다. 실재고, 주문, 상담 접수 API는 연결하지 않는다.
- 가격은 화면을 열 때 `GET /api/pc-builder/pool`(DB 판매가·판매 상태)로 덮는다. 서버가 응답하지 않으면 조사 가격을 그대로 보여 주고 AI 채우기를 막는다.
- 임시 구성함은 현재 페이지의 메모리에만 남습니다. 새로고침하거나 페이지를 떠나면 사라집니다. 실제 견적 내역과 별도입니다.

개발 환경에서 이 폴더를 기준으로 실행합니다.

```sh
npm ci
npm run build
npm test
```

빌드는 `mockups/mvp4/pc-builder/`만 비우고 다시 만듭니다. 고객 서버에서 `/mvp4/pc-builder`를 끝 슬래시가 있는 경로로 정규화하고, JSON·이미지 누락을 HTML로 대체하지 않아야 합니다. 기존 고객 페이지의 라우팅·접근 정책은 이 모듈에서 바꾸지 않습니다.

`src/paths.js`가 앱과 빌드의 기준 경로를 공유합니다. 카탈로그의 로컬 이미지 경로는 로딩 시 이 기준으로 정규화하고, 원상품 상세 URL은 유지합니다.
