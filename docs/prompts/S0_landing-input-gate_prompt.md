# S0. 랜딩 / 입력 게이트 — UI 설계 상세 프롬프트

**화면 ID:** FR-LND-010 · **Screen 키:** `landing` · **컴포넌트:** `Landing`
**정체성:** 신뢰 판매자 · **히어로:** "모든 견적에는 이유가 있습니다."
**디자인 시스템:** Vibrant Horizon (첨부 DESIGN.md 기준) + 기존 Stitch 마크업 계약(STITCH_RULES) 유지
**선행 결정:** ① 대화 입력이 주 / 칩은 가속기 ② 입력창 전면 · 세일즈 하단 ③ 초급/고급 하드분기 삭제(단일 문)

이 프롬프트는 Stitch·v0 등 UI 생성 도구에 그대로 붙여넣어 정적 화면을 만든 뒤, Codex가 로직을 얹는 것을 전제로 한다. 아래 [A] 공통 규칙과 [B] S0 상세를 함께 붙여넣는다.

---

## [A] 공통 규칙 블록 — Vibrant Horizon 갱신본

```
[공통 규칙 — 사용자 화면]
- 한국어 UI. 기술 약어(CPU/GPU/DDR5/NVMe 등)만 영문 허용.
- 서체: 본문·헤드라인은 Inter(라틴·숫자) + Pretendard(한글) 페어링.
  숫자·가격은 Inter tabular. (Inter 단독은 한글 렌더 불량이므로 금지)
- 색·크기·간격은 아래 :root CSS 변수만 사용. 임의 HEX/px 금지, 인라인 스타일 금지.
- 최상위 컨테이너에 data-screen-id, data-domain 부여.
- 동적 텍스트·수치 data-bind, 반복 목록 data-repeat, 버튼·링크 data-action,
  차트 <canvas data-chart>, 예외 UI는 hidden으로 미리 마크업.
- 클래스는 BEM 간소화(블록__요소--상태), 영문 kebab-case.
- 시맨틱 태그(header/nav/main/section/footer/button), 이미지 alt, 입력 label 연결,
  색에만 의존 금지(상태는 텍스트 병기).
- 반응형: 데스크톱 12컬럼 / 모바일 4컬럼, 768px 이하 세로 스택.
- 외부 LLM·API 직접 호출 스크립트 금지, API Key·개인정보 하드코딩 금지.

[디자인 토큰 :root]
--color-background:#f6f5ff;      /* 캔버스 */
--color-surface:#f6f5ff;
--color-surface-card:#ffffff;    /* 전경 카드 */
--color-surface-container:#e3e7ff;
--color-on-surface:#212d51;      /* 본문 텍스트 */
--color-on-surface-variant:#4e5a81; /* 보조 텍스트 */
--color-outline:#6a769e;
--color-outline-variant:#a0acd7;
--color-primary:#005ab3;         /* 주 액션·브랜드 (정본) */
--color-primary-bright:#0082fd;  /* hover·포커스 밝은 액센트 */
--color-on-primary:#eff2ff;
--color-primary-container:#64a1ff;
--color-secondary:#3155b7;       /* 보조 요소 */
--color-tertiary:#853d97;        /* 액센트·구분(근거/커뮤니티 태그 등) */
--color-tertiary-container:#e795f7;
--color-error:#b31b25;           /* 위험·호환 오류 */
--color-on-error:#ffefee;

--font-sans:'Inter','Pretendard','Noto Sans KR',system-ui,sans-serif;
--fs-headline-lg:32px; --lh-headline-lg:40px; --fw-bold:700;
--fs-headline-md:24px; --lh-headline-md:32px; --fw-semibold:600;
--fs-body:16px; --lh-body:24px; --fw-regular:400;
--fs-label:14px; --lh-label:20px; --fw-medium:500;

--radius-sm:0.25rem; --radius:0.5rem; --radius-md:0.75rem;
--radius-lg:1rem; --radius-xl:1.5rem; --radius-full:9999px;
--space-xs:4px; --space-sm:8px; --space-md:16px; --space-lg:24px; --space-xl:32px;

[스타일 원칙]
- 배경은 연한 블루 틴트(#f6f5ff), 카드는 순백(#ffffff)으로 층 분리.
- 그림자는 부드럽고 확산된 앰비언트(딱딱한 테두리 대신 은은한 elevation).
- 버튼·입력·칩 라운드 0.5rem, 카드·모달 1~1.5rem. 칩은 pill(full).
- primary 버튼: 배경 #005ab3, 텍스트 #eff2ff, hover 시 #0082fd.
- 입력 포커스: outline_variant 테두리 + primary 2px 포커스 링.
```

---

## [B] S0 화면 상세 — 랜딩 / 입력 게이트

```
위 [공통 규칙]을 적용해 "메인 랜딩 · 입력 게이트" 화면을 만든다.
data-screen-id="FR-LND-010" data-domain="landing".

핵심 원칙: 이 화면은 세일즈 카피가 아니라 '입력 경험' 자체가 후크다.
히어로+대화 입력창이 첫 화면(above the fold)을 지배하고,
세일즈·설득 요소는 모두 그 아래로 내린다. 초급/고급 분기 카드는 없다(단일 문).

────────────────────────────────────────
1) GNB (header.gnb) — 얇고 절제된 상단 바
────────────────────────────────────────
- 좌측: 브랜드 로고/워드마크 "팝콘PC AI".
- 우측 메뉴: [견적 받기](data-action="scroll-to-input"),
  [로그인/회원가입](data-action="open-auth"),
  [고객문의](data-action="goto-qna"),
  [관리자](data-action="goto-admin"), [DEV](data-action="goto-dev").
- '초급자 모드' '고급자 모드' 메뉴는 넣지 않는다(단일 진입으로 통합됨).
- 스크롤 시 상단 고정(sticky), 배경 순백 + 하단 outline_variant 1px.

────────────────────────────────────────
2) Hero + 대화 입력 게이트 (section.hero) — 화면의 주인공
────────────────────────────────────────
- 중앙 정렬, 상하 넉넉한 여백(--space-xl 이상), 배경 캔버스 틴트.
- H1 headline-lg 700: "모든 견적에는 이유가 있습니다."
- 서브카피 body, on-surface-variant:
  "실재고 안에서, 호환성을 통과한 구성만. 왜 이 부품인지 끝까지 설명합니다."
- 신뢰 마이크로 배지(hero__trust, 가로 배열, tertiary 톤 pill 3개):
  "실재고 검증" · "호환성 5종 통과" · "선정 근거 리포트".

- ★ 대화 입력창(hero__composer) — 크고 눈에 띄게, 히어로 정중앙:
  <label> 숨김 처리 + <textarea class="composer__input"
    placeholder="어떤 PC가 필요하세요?  예) 배그 잘 돌아가는 100만원대"
    rows 1~2, 오토그로우, 라운드 --radius-lg, 카드 배경 #ffffff,
    포커스 시 primary 2px 링>.
  우측 끝 전송 버튼 <button class="btn btn--primary composer__send"
    data-action="start-session" aria-label="견적 시작">→</button>.
  캡션(composer__hint, label, on-surface-variant):
    "입력하시면 실재고에서 후보를 좁혀 드립니다."

- 가속기 칩(hero__chips, 입력창 바로 아래, pill 형태, 다중 아님):
  [게임용] data-action="quick-intent" data-intent="game"
  [사무용] data-intent="office"
  [영상편집] data-intent="edit"
  [인터넷방송] data-intent="stream"
  * 칩 클릭 = 해당 의도를 첫 발화로 세션 시작(입력창에 값 주입 후 start-session).
  * 칩은 어디까지나 빠른 답변 가속기이며, 자유 입력이 주 경로임을 시각적으로도 종속시킨다
    (칩은 입력창보다 작고 낮은 위계).

- 실재고 라이브 신호(hero__live, 입력창 하단 우측, 작게):
  "지금 검증 중인 실재고 " + <span data-bind="live_stock_count">2,480</span> + "대".
  * 첫 화면부터 '재고 기반'이라는 신뢰를 심는 장치. S1의 후보 풀 카운터로 이어진다.

────────────────────────────────────────
(이하 세일즈·설득 요소 — 모두 히어로 아래로)
────────────────────────────────────────

3) How It Works (section.how, 신뢰 프레임으로 재구성)
- H2 headline-md: "감이 아니라, 검증으로 고릅니다."
- 3단계 카드(how__step, data-repeat="steps", surface-card, 라운드 lg):
  ① 실재고 확인 — "품절·단종은 후보에서 즉시 제외"
  ② 호환성 검증 — "소켓·전력·치수 5종 통과만 남김"
  ③ 근거 설명 — "왜 이 부품인지 리포트로 제공"
- 좌→우 진행 화살표. 색에 의존 말고 번호·라벨 병기.

4) 근거 리포트 미리보기 (section.reason-preview) — 차별점 쇼케이스
- H2: "모든 견적에는, 이런 이유가 붙습니다."
- 예시 카드(reason-card, surface-card, 라운드 lg): 부품명 + 선정 사유 더미
  data-repeat="reason_samples":
  "RTX 4060 — 인기게임 1% Low 프레임 방어, 이 예산대 커뮤니티 최다 추천"
  "정격 650W — 이 GPU 기준 정격 마진 30% 확보"
  커뮤니티/벤치 근거 태그는 tertiary 톤 pill로 표기.

5) Spec Preview (section.spec-preview)
- H2: "추천 구성 미리보기".
- 부품 6종 미리보기(parts-list, data-repeat="components": CPU/GPU/RAM/SSD/보드/파워)
  + 예상 금액 <span data-bind="preview_price">1,250,000원</span>.

6) Reviews (section.reviews)
- H2: "사용자 후기". 후기 카드 3개 data-repeat="reviews"(별점+한줄+닉네임 더미).

7) Special Event Banner (section.event-banner)
- 특가·이벤트 롤링 배너 data-repeat="events". tertiary/secondary 액센트.

8) Final CTA (section.final-cta)
- H2: "지금, 이유 있는 견적을 받아보세요."
- 버튼 [견적 시작하기] data-action="scroll-to-input"(히어로 입력창으로 스크롤).
  * 별도 진입 버튼을 새로 만들지 말고 히어로 입력창으로 되돌린다(단일 진입 유지).

9) Footer (footer.footer)
- 서비스/고객지원/회사 링크 + 고객센터 정보. outline_variant 상단 구분선.

────────────────────────────────────────
전환 / 인터랙션
────────────────────────────────────────
- start-session(입력 전송 또는 칩 클릭) → 로딩 레이어 노출 후 S1(대화형 견적 세션)로 전환.
  입력값은 세션의 첫 발화로 그대로 이관(랜딩과 세션이 끊기지 않는 연출).
- open-auth → SSO 인증 모달(auth-modal). 단, 랜딩·세션은 게스트로 진행 가능,
  로그인 강제는 장바구니(S4)에서만.
- scroll-to-input → 히어로 입력창으로 부드럽게 스크롤 + 입력창 포커스.

────────────────────────────────────────
예외 · 상태 UI (hidden 기본, Codex가 토글)
────────────────────────────────────────
- <div class="composer__error" hidden>내용을 입력하거나 위 버튼을 눌러 시작하세요.</div>
- <div class="loading-layer" hidden>실재고에서 후보를 불러오는 중입니다...</div>
- <div class="live-stock--stale" hidden>재고 정보를 갱신하는 중입니다.</div>

────────────────────────────────────────
반응형
────────────────────────────────────────
- 768px 이하: GNB 우측 메뉴 → 햄버거. 히어로 입력창은 폭 100%로 확장,
  가속기 칩은 2열 랩. How/근거/스펙 카드는 세로 스택.
- 히어로는 모바일에서도 above the fold에서 입력창이 반드시 보이도록 여백 축소.

────────────────────────────────────────
산출 후 체크
────────────────────────────────────────
□ data-screen-id="FR-LND-010" data-domain="landing" 부여
□ 대화 입력창(start-session)과 가속기 칩(quick-intent)이 세션 진입으로 연결
□ live_stock_count·preview_price 등 동적값에 data-bind
□ 초급/고급 분기 카드가 없고 단일 진입인가
□ 세일즈 요소가 모두 히어로 아래로 내려갔는가
□ 예외 UI(composer__error/loading-layer)가 hidden으로 포함
□ Inter+Pretendard 페어링, :root 토큰만 사용, 임의 색·인라인 스타일 없음
□ 한국어 통일(약어만 영문)
```

---

## 적용 노트 (기획자·개발자용)

1. **기존 05_design-guide 대비 변경점** — primary가 `#0075d5` → `#005ab3`(정본), 서체 Pretendard 단독 → Inter+Pretendard, 라운드/앰비언트 그림자 도입. 이 프롬프트의 `:root` 블록을 `_publish/assets/css/common.css`에 반영하면 다른 화면도 자동 승계된다. 즉 색·서체는 이 파일이 새 정본이다.
2. **live_stock_count는 연출이 아니라 실데이터로** — 첫 화면 신뢰의 핵심이므로 더미로 두면 안 된다. 관리자 상품 마스터의 `판매중` 집계를 캐시해 바인딩. 갱신 지연 시 `live-stock--stale`로 정직하게 표기.
3. **S1로의 이관 규약** — start-session 시 넘기는 페이로드는 `{ raw_text, quick_intent? }`. S1은 이걸 파서에 태워 제약조건으로 구조화한다(피벗 1의 파서 레이어).
4. **아직 안 정한 것** — 히어로 배경(단색 틴트 vs 은은한 그라디언트/일러스트)과 라이브 재고 신호의 노출 강도. 프리미엄 톤을 더 밀지, 정보 위주로 갈지에 따라 갈린다.
