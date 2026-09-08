# 디자인 브리프 — 고객 랜딩 + 진열대 (신 컨셉 A-126)

> 2026-09-07 · BRIEF.md 규약(§A+§B). 이 문서 전체를 Claude Design에 붙여 넣는다.
> 두 화면을 한 브리프에 담았다 — 랜딩이 진열대로 흘러가는 한 흐름이라 따로 그리면 어긋난다.

---

# §A-1 화면 브리프 — 고객 랜딩 (개편)

## 무엇

    화면 ID     CUS-LND-020 (기존 main-landing 대체)
    경로        / (고객 첫 화면)
    보는 사람    고객 (비로그인 포함)
    이 화면이 답하는 질문   「여기는 뭘 해주는 곳이고, 나는 어디로 가면 되나?」
    여기서 내리는 결정      고객이 4개 진입로 중 하나를 고른다 (용도/예산/게임/AI작업)

## 컨셉 (A-126 — 화면 문구의 뼈대)

**「팝콘이 매일 검증한 견적 진열대에서, AI가 당신 것을 찾아드립니다」**

- 헤드라인 후보: 「매일 아침, 오늘 팔 수 있는 견적만 진열합니다」
- 서브: 「모든 견적에는 이유가 있습니다」 (기존 히어로 문구 유지 — A-01)
- ⚠ 「AI가 조합해준다」류 문구 금지 — AI는 찾아주는 역할(안내원)이지 조합하지 않는다.
- 차별 한 줄: 경쟁사는 매월, 우리는 **매일** 갱신. (단, 이 문구는 배치 cron이 실제로
  매일 돌기 시작한 뒤에만 켠다 — data-bind로 갱신 시각을 실값 표시)

## 실제 데이터 (2026-09-07 실측)

| 항목 | 원천 | 실측 |
|---|---|---|
| 진열 견적 수 | grid_quotes WHERE is_current | 70 |
| 마지막 검증 시각 | grid_quotes.generated_at 최신 | 「2026-09-07 17:33」 형식 |
| 게임 수 | games (출처 있는 것) | 21 |
| AI 작업 수 | ai_workloads | 14 |
| 티어 | 팝콘 3 / 5 / 5+ / 7 / 7+ / 9 / X | 7단 · 경계 60/100/150/220/300/450만 |
| 용도 | 8종 (사무·인터넷 ~ AI 작업) | 특수형은 비어 있음 — 진입로에서 제외 |

    전 수치는 data-bind — 화면에 박지 않는다. 서버가 준 값만 표시(화면 정직성 규약).

## 구성 요구

    ① 히어로: 헤드라인 + 「오늘 견적 N개 · HH:MM 검증」 (data-bind)
    ② 진입로 4카드:
       용도로 찾기   → 진열대(용도 열 필터)
       예산으로 찾기  → 진열대(티어 행 필터) — 티어 7개를 금액과 함께 표시
       게임으로 찾기  → 게임 선택 → 진열대(그 게임의 권장 칸 강조)
       AI 작업으로   → 작업 선택(LLM 추론 7B~70B / 이미지 / 영상…) → 권장 칸
    ③ 대표 견적 2~3개 미리보기 (조건 명시 — 「게임·150만원 기준」처럼 근거 있는 표시만)
    ④ 신뢰 밴드: 「검증 = 재고 실사 + 호환 규칙 N종 + 예산 정합」 (N도 data-bind)

## 상태

    빈 상태    배치 0회(견적 0개): 매일 갱신 문구를 켜지 않는다. 「진열 준비 중」
    로딩/실패  서버 실패 시 수치 자리를 지어내지 않고 「—」 + 재시도

---

# §A-2 화면 브리프 — 진열대 (신규)

## 무엇

    화면 ID     CUS-SHF-010
    경로        /shelf
    보는 사람    고객
    이 화면이 답하는 질문   「내 예산·용도에 맞는, 오늘 살 수 있는 견적은 무엇인가?」
    여기서 내리는 결정      견적 하나를 골라 상세(부품 구성·근거)로 들어간다

## 구성 요구

    ① 필터 바: 티어(팝콘 3~X, 금액 병기) · 용도(7종 — 특수형 제외) · 플랫폼(인텔/AMD/전체)
       랜딩 진입로에서 온 경우 해당 필터가 미리 선택돼 있다
    ② 견적 카드 그리드: 카드마다 —
       티어명+용도 (「팝콘 7 · 고사양게임」) · 총액 · 핵심 부품 요약(CPU/GPU 한 줄)
       검증 시각 (「오늘 17:33 검증」) · [자세히]
    ③ 카드 클릭 → 견적 상세: 슬롯 8행(부품·가격·이유) · 게임이면 「이 견적으로 되는
       게임」 (game_performance에 데이터 있는 것만 — 없으면 그 줄 자체를 안 그림)
    ④ 상단: 「전체 N개 중 M개 표시」 (서버 페이지네이션 규약)

## 실제 데이터 (실측)

| 항목 | 실측 |
|---|---|
| 카드 수 | 필터 전 70 · 한 칸 1견적 |
| 총액 범위 | 776,100 ~ 4,499,500원 (8자리 대비) |
| 부품명 최장 | 55자 표시 확인 |
| 견적 상세 | payload jsonb — 슬롯·가격·reasons 전부 있음 |

## 상태

    빈 결과    필터 조합에 견적 없음(의도 빈 칸): 「이 조합은 준비하지 않습니다 — 이유」
              (예: 팝콘 3 × AI 작업 — 예산상 성립하지 않는 조합입니다)
    품절 슬롯  견적에 재고 소진 부품이 생긴 경우: 카드에 「재검증 대기」 배지 — 숨기지 않는다

## 하지 말 것 (두 화면 공통)

- 후기·판매량·별점 등 **아직 없는 데이터의 자리를 만들지 않는다**
- 계산기·부품 직접 선택 UI 없음 — 그건 이 컨셉이 아니다 (진열대에서 고른다)
- 다크모드 없음

---

# §B 고정 계약

## B-1 토큰 (고객 화면 — tokens.css :root 그대로)

```css
:root{
  --bg:#F0F5F9; --surface:#F0F5F9; --card:#ffffff; --container:#E4ECF4; --container-low:#EAF2F8;
  --on:#111827; --on-variant:#64748B; --outline:#94A3B8; --outline-variant:#DCE7F2;
  --primary:#65A1D4; --primary-bright:#4A90E2; --on-primary:#ffffff; --primary-container:#DCE7F2;
  --secondary:#5071d5; --tertiary:#6E8FD6; --tertiary-container:#DCE7F2;
  --error:#C0392B; --on-error:#ffffff;
  --success:#2f9e6d; --success-bright:#5fd6a0; --success-dark:#1c7a4d; --success-deep:#0f5132;
  --success-muted:#3d7a5c; --success-ink:#2c4c3c; --success-sage:#7aa891;
  --success-teal:#10a37f; --success-teal-bright:#6ee7d6;
  --success-container:#e9f6ef; --success-container-line:#d4e9dd; --on-success:#ffffff;
  --font:'Noto Sans KR','Pretendard',system-ui,sans-serif;
  --font-head:'Noto Sans KR','Pretendard',system-ui,sans-serif;
  --font-num:'Noto Sans KR','Pretendard',system-ui,sans-serif;
  --r-sm:.25rem; --r:.5rem; --r-md:.75rem; --r-lg:1rem; --r-full:9999px;
  --sp-xs:4px; --sp-sm:8px; --sp-md:16px; --sp-lg:24px; --sp-xl:32px;
  --shadow:0 1px 2px rgba(15,23,42,.06),0 12px 30px rgba(15,23,42,.10);
}
```

> 색·여백·서체는 위 변수만. 임의 HEX·px 금지. 없으면 「없다」고 알려 달라.
> 고객 화면은 초록(--success*)을 검증 통과·안전 의미로 쓸 수 있다(U-01).
> 색만으로 판정을 말하지 않는다 — 항상 텍스트 병기.

## B-2 산출물

    HTML 파일 각 1개 (CSS 인라인) · React/Tailwind/빌드도구/외부 CDN 금지
    서체 var(--font) · 숫자 var(--font-num) · 아이콘 인라인 SVG 또는 자리만

## B-3 마크업 계약

    최상위 data-screen-id="CUS-LND-020" / "CUS-SHF-010" · data-domain="customer"
    서버 값 전부 data-bind · 반복은 data-repeat + 본보기 하나 · 버튼 data-action
    예외 상태 미리 그려 hidden · 768px 세로 스택

## B-4 예시 값

    수치는 자릿수만 현실적으로 (진열 70개·총액 7자리·게임 21종 수준)
    실제 상품명·가격을 지어내 넣지 않는다 — 본보기 표기임이 드러나게
