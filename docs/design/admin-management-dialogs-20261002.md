# 관리자 상품·사양 팝업 보완

## 2026-10-02 관리자 팝업 2차 보완
- 범위: 상품 관리(products), 상품 사양 정의(spec-field-defs), 조립 사양 표준(spec-standard), 조립 호환 규칙(compat-rules). 기존 조립PC 팝업 보완에 이어 적용.
- 자산: mockups/shared/admin2/management-dialogs.css. 기존 팔레트 재사용, 네 템플릿에서만 로드. 제목/닫기/하단 동작 고정, 본문 스크롤, 긴 제목/좁은 화면 폼 줄바꿈, zoom 1.15를 보정한 viewport 고정 배치.
- 확인된 결함: 사양 정의 창 전체 스크롤로 하단 버튼이 숨음; 모바일 목록 높이를 기준으로 모달이 650px 화면 밖으로 1259px까지 커짐; 720px 상품 목록 검색 영역이 행 표시 공간을 압축함. 각각 본문 스크롤, viewport 기준 높이, 짧은 화면 검색 영역 자체 스크롤로 수정.
- 운영 검증: 로그인 후 네 창 열기/취소/닫기. 1280x720 상품 상세, 1520x884 사양 표준. 600x650 및 480x650 사양 정의에서 모달 bottom=638.5, footer bottom=637.5; 480px에서 본문 clientWidth=scrollWidth=389로 수평 넘침 없음. 상품 상세 bottom=720 및 footer bottom=720.
- Jinja 네 템플릿 로드, CSS 블록 균형, git diff --check 통과. 배포 36968078717(4574280), 36968379401(b16c6b4), 36968537787(17b9f6c) 성공.
- 상품 저장/스키마 생성/호환 규칙 변경은 실행하지 않음. 호환 규칙 저장 버튼은 기존 서버 API 대기 상태 유지. 분류/매입/권한 등 나머지 팝업 전체 검증 완료라는 의미는 아님.
- 증거: 사용자 작업실 outputs/admin-dialog-review-20261002/spec-definition-small.png, spec-standard-desktop.png, product-drawer.png, compat-drawer.png. 이후 팝업 추가도 같은 원칙 적용; 다른 메뉴는 실제 화면 확인 후 범위를 좁혀 적용.
