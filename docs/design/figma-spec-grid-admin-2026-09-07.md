# Figma 디자인 기획서 — 격자 관리 (ADM-GRD-010)

> 2026-09-07 · 팝콘 AI. Figma에서 이 화면을 짓는 디자이너(또는 Figma AI)를 위한 기획서.
> 원천: `docs/design/brief-grid-admin-2026-09-07.md`(요구) + `docs/design/incoming/dc-grid-admin.html`(승인 시안).
> 이 문서는 **구조·상태·토큰**을 Figma 어휘(Page/Frame/Component/Variant/Auto Layout/Style)로 옮긴 것이다.

---

## 1. 파일 구조 (Figma Pages)

```
📄 Page 1 — 🖥 Screens        완성 화면 프레임들
📄 Page 2 — 🧩 Components     컴포넌트 + Variants
📄 Page 3 — 🎨 Tokens         컬러·타이포·스페이싱 스타일 견본
```

## 2. 프레임 (Page 1 — Screens)

| Frame 이름 | 크기 | 내용 |
|---|---|---|
| `Desktop / 기본` | 1440 × 1024 | 격자 정상 상태 (서랍 닫힘) |
| `Desktop / 서랍 열림` | 1440 × 1024 | 칸 클릭 → 우측 서랍 |
| `Desktop / 빈 상태` | 1440 × 1024 | 배치 0회 — 「배치 기록 없음 — 격자 전체 미생성」+ [첫 배치 실행] |
| `Desktop / 로딩` | 1440 × 1024 | 「격자 로딩 중」스켈레톤 |
| `Desktop / 재생성 진행` | 1440 × 1024 | 진행 바 + 칸 단위 「재생성 중」 |
| `Desktop / 부분 실패` | 1440 × 1024 | 실패 칸 강조 + [실패 칸만 표시] 필터 + [실패 칸 재생성] |
| `Desktop / 오류 500` | 1440 × 1024 | 「격자 조회 실패 (500)」+ 요청 ID + [다시 시도] |
| `Desktop / 세션 만료` | 1440 × 1024 | 「세션 만료 — 로그인 필요」+ [다시 로그인] |
| `Mobile / 기본` | 768 × 1400 | 세로 스택 — 격자는 자기 상자 안 가로 스크롤 |

> ⚠ 본문 영역만 그린다. 좌측 메뉴(LNB)·상단바는 admin2 공용 셸이 감싼다 —
> 프레임 좌측에 212px 자리만 회색 박스로 표시(placeholder)하고 채우지 않는다.

## 3. 레이아웃 골격 (Auto Layout)

```
Screen (Vertical, gap 24, padding 24)
├─ ① SummaryBar (Horizontal, gap 16, Fill width)
│   ├─ Stat: 채워진 칸 N / 전체 M
│   ├─ Stat: 마지막 배치 (시각 · batch_id)
│   ├─ Stat: 배치 상태 (성공 / 부분 실패 N칸)
│   ├─ Spacer (Fill)
│   ├─ Button/Secondary: 실패 칸만 표시
│   └─ Button/Primary: 전체 재생성
├─ ② PlatformToggle (Horizontal, gap 8) — [인텔] [AMD] Segmented
├─ ③ GridTable (본체)
│   ├─ 열 머리: 용도 8 (사무·인터넷 … AI 작업 · 특수형)
│   ├─ 행 머리: 티어 7 (팝콘 3 → 팝콘 X, 위=저가)
│   └─ Cell × 56 (7행 × 8열) ← Component instance
└─ ④ Drawer (Overlay, 우측 고정 420px) — 칸 클릭 시
    ├─ 헤더: 칸 좌표 「팝콘 7 × 고사양게임 × AMD」 + 상태 칩 + 닫기
    ├─ 메타: 생성 시각 · 배치 ID · 예산 구간
    ├─ QuoteTable: 슬롯 8행 (부품명 · 가격) + 총액 + 예산 구간 대비 판정
    ├─ Button/Primary: 이 칸 재생성
    └─ Button/Ghost(disabled): 견적 이력 보기 — 「향후 사용예정」 라벨
```

## 4. 핵심 컴포넌트 (Page 2 — Components)

### 4.1 `GridCell` — Variants가 이 화면의 심장

Property `state` 7종 + Property `platform` 무관(색은 state만 따른다):

| Variant | 배경 | 좌측 상태 텍스트 | 안에 보이는 것 |
|---|---|---|---|
| `state=정상` | success-container | 「정상」 | 총액(예: 1,999,900) + 경과(「3시간 전」) |
| `state=예산상한초과` | 노랑 계열(state-run 10%) | 「예산 상한 초과」 | 총액 + 경과 |
| `state=재고소진` | 노랑 계열 | 「재고 소진」 | 총액 + 경과 + 소진 슬롯 수 |
| `state=생성실패` | error 10% | 「생성 실패」 | 사유 한 줄 |
| `state=재생성중` | container | 「재생성 중 · 약 5초」 | 스피너 |
| `state=빈칸-미생성` | 흰색 + 점선 테두리 | 「미생성」 | — |
| `state=빈칸-의도` | bg색 + 테두리 없음 | 「—」 | 비활성 시각 처리 |

> ⚠ **「빈칸-미생성」과 「빈칸-의도」는 반드시 다른 모양** — 점선 vs 무테두리.
> 같으면 운영자가 미생성을 정상으로 오인한다. (브리프 A-5 경계 명시 사항)
> ⚠ 색만으로 상태를 말하지 않는다 — **상태 텍스트 항상 병기** (색약 배려).

### 4.2 나머지 컴포넌트

| Component | Variants |
|---|---|
| `Button` | Primary / Secondary / Ghost / Danger × default·hover·disabled |
| `StatusChip` | 정상 / 초과 / 소진 / 실패 / 재생성중 / 미생성 (셀과 동일 어휘) |
| `Stat` (요약 바 항목) | 기본 / 경고(부분 실패 시) |
| `SegmentedToggle` | 인텔 선택 / AMD 선택 |
| `QuoteRow` (서랍 슬롯 행) | 기본 / 재고소진(취소선+대안 표시) |
| `Modal/Confirm` | 전체 재생성 확인 — 「되돌릴 수 없음 · 약 6분 소요」 문구 포함 |
| `Toast` | 성공 / 실패 |

## 5. 토큰 → Figma Styles (Page 3)

**Color Styles** (이름 그대로 등록 — 코드 토큰과 1:1):

```
bg           #F0F5F9      card         #FFFFFF      container    #E4ECF4
on           #111827      on-variant   #64748B      outline      #94A3B8
primary      #65A1D4      primary-br   #4A90E2      on-primary   #FFFFFF
error        #C0392B      state-run    #D97706
success      #2F9E6D      success-container #E9F6EF success-dark #1C7A4D
nav          #1E293B      (셸 placeholder 용)
```

**Text Styles** (서체는 전부 Noto Sans KR):

| 이름 | 크기/행간 | 용도 |
|---|---|---|
| `head/screen` | 20/28 Bold | 화면 제목 「격자 관리」 |
| `head/section` | 16/24 Bold | 서랍 헤더 |
| `body` | 14/22 Regular | 기본 |
| `body/strong` | 14/22 Bold | 칸 총액 |
| `caption` | 12/18 Regular | 경과 시간·배치 ID |
| `num` | 14/22 Medium, tabular | 가격 — 자릿수 정렬 |

**Spacing / Radius 변수:** 4 · 8 · 16 · 24 · 32 (px) / radius 4 · 8 · 12 · 16

## 6. 인터랙션 (Prototype 연결)

| 트리거 | 동작 |
|---|---|
| GridCell 클릭 | → `서랍 열림` 프레임 (Smart Animate, 우측 슬라이드 240ms) |
| 서랍 밖 클릭 / 닫기 | → `기본` 프레임. **서랍 안·토글 클릭은 닫히지 않음**(data-keep) |
| [인텔]/[AMD] 토글 | 격자 내용 교체 (Change to — 상태 유지) |
| [전체 재생성] | → Confirm 모달 (「되돌릴 수 없음 · 약 6분」) → 진행 프레임 |
| [이 칸 재생성] | 칸만 `재생성중` variant로 → 완료 시 갱신 |
| 행·열 머리 클릭 | 해당 줄 강조 (필터 아님 — 강조만) |
| [실패 칸만 표시] | 실패 외 칸 dim 처리 |

## 7. 콘텐츠 규칙 (Figma 더미 데이터)

- 가격·건수는 **자릿수만 맞춘 견본** (실값처럼 보이는 수 금지): `9,999,999` 형태 대신 `1,999,900`처럼 현실 자릿수, 단 모든 칸 동일 값 금지 — 티어 오름차순으로 그럴듯하게
- 부품명 최장 55자 케이스 1개 반드시 포함: 「GIGABYTE 지포스 RTX 5060 EAGLE OC D7 8GB 제이씨현」
- 총액 최대 8자리 케이스 1개 (팝콘 X): `49,720,000`
- 입력·셀렉트 기본값 비움 (「선택하세요」)
- 문구는 관리도구 용어 — 서술문·구어체 금지 (「생성 실패」 O / 「만들지 못했어요」 X)

## 8. 하지 말 것

- 다크모드 변형 만들지 않는다 (Popcorn Light 단일)
- 축(티어·용도) 편집 UI 만들지 않는다 — 이 화면은 칸의 내용물만 다룬다
- 견적 부품 수동 교체 UI 만들지 않는다 — 재생성만 존재
- 새 색·새 폰트 만들지 않는다 — §5 스타일 밖 값이 필요하면 「없다」고 보고

---

### 부록 — Figma AI (First Draft)용 요약 프롬프트

> Figma의 AI 생성 기능에 넣을 경우 아래 한 단락 + 위 §3 골격을 함께 붙인다.

```
한국어 관리자 도구 화면 「격자 관리」. 라이트 테마(배경 #F0F5F9, 카드 흰색,
포인트 #65A1D4). 상단 요약 바(채워진 칸 수·마지막 배치·전체 재생성 버튼),
인텔/AMD 세그먼트 토글, 본체는 7행(팝콘 3~팝콘 X)×8열(사무·인터넷~특수형)
격자 테이블 — 각 칸에 상태 텍스트+총액+경과시간. 칸 클릭 시 우측 420px
서랍: 칸 좌표, 견적 8슬롯 표(부품명·가격), 총액, [이 칸 재생성] 버튼.
칸 상태 7종(정상=연초록, 초과/소진=연노랑, 실패=연빨강, 재생성중=스피너,
미생성=점선 테두리, 의도적 빈칸=무테두리)을 색+텍스트로 구분. Noto Sans KR.
```
