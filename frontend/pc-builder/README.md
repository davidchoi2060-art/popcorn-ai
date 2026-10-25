# 고객용 PC 구성 미리보기

원본 `D:/WORK/PopcornAI/outputs/pc-builder-prototype-20261023`에서 고객 페이지용으로 분리한 React/Vite 소스입니다. 원본 Sites worker와 배포 설정은 포함하지 않습니다.

- 고객 경로: `/mvp4/pc-builder/`
- 빌드 산출물: `mockups/mvp4/pc-builder/` (저장소에 함께 포함)
- 고객 서버는 빌드된 정적 파일을 제공하며 Node.js 런타임이 필요하지 않습니다.
- 부품 상담과 채우기는 규칙형 예시입니다. 외부 LLM, 실재고, 주문, 상담 접수 API는 연결하지 않습니다.
- 임시 구성함은 현재 페이지의 메모리에만 남습니다. 새로고침하거나 페이지를 떠나면 사라집니다. 실제 견적 내역과 별도입니다.

개발 환경에서 이 폴더를 기준으로 실행합니다.

```sh
npm ci
npm run build
npm test
```

빌드는 `mockups/mvp4/pc-builder/`만 비우고 다시 만듭니다. 고객 서버에서 `/mvp4/pc-builder`를 끝 슬래시가 있는 경로로 정규화하고, JSON·이미지 누락을 HTML로 대체하지 않아야 합니다. 기존 고객 페이지의 라우팅·접근 정책은 이 모듈에서 바꾸지 않습니다.

`src/paths.js`가 앱과 빌드의 기준 경로를 공유합니다. 카탈로그의 로컬 이미지 경로는 로딩 시 이 기준으로 정규화하고, 원상품 상세 URL은 유지합니다.
