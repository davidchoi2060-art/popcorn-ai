# 설계 — 팝콘톡 상담 재설계: 「키워드 추출」에서 「격자 안내」로 (A-137 후보)

작성 2026-09-16 · 사장님 방향 확정("그렇게 설계해줘") · 세부 3항목 확정(§6)
전제 조사: `docs/design/flow-mvp2-talk-to-grid-2026-09-16.md`(현행 흐름·결함 4곳)

---

## 1. 무엇을 바꾸는가 (한 줄)

AI 의 역할을 **「문장에서 키워드를 뽑는 추출기」** 에서 **「고객 말을 듣고 격자의 어느 칸인지
가리키는 안내자」** 로 바꾼다. 서버는 그 좌표가 격자 어휘 안에 있는지만 확인하고 카드를 꺼낸다.

## 2. 왜 바꾸는가

현행(`api/talk.py` → `api/grid_public.py`)은 AI 출력 어휘(예산·용도·선호·부품·플랫폼·제외)와
격자가 실제로 필요로 하는 좌표(티어·등급·해상도)가 **서로 다른 언어**라, 그 사이를 서버가
문자열 매칭으로 잇는다. 그 틈에서 게임명이 사라졌고(결함 ①②③), 고객은 "오버워치"라고 세 번
말해도 같은 안내를 받았다. 키워드가 정확히 나와야만 동작하는 구조는 "뭔 말인지 알아듣고
원하는 구성을 찾아내는" 상담이 될 수 없다(사장님 지적 2026-09-16).

## 3. 지키는 결정 (바뀌지 않는 것)

- **A-03**: AI 는 견적을 만들지 않는다. 부품·가격은 격자(결정론 엔진이 미리 계산)가 정한다.
  AI 가 정하는 것은 **「어느 칸인가」** 뿐이다.
- **A-02 결정론**: 같은 좌표 → 같은 카드. AI 의 판단은 좌표 선택에서 끝난다.
- **화면 정직성**: 숫자·후보 수·가격·판정은 전부 서버 값. AI 가 추정한 것은 「추정」이라 표시한다.
- **출력 어휘는 닫혀 있다**: 자유 텍스트가 아니라 격자 좌표(아래 §4)만 낸다. 다만 그 어휘가
  키워드가 아니라 **좌표** 로 바뀐다.
- **정본은 DB**: AI 에게 주는 격자 설명서는 코드에 박지 않고 매 요청 `spec_tiers`·
  `game_load_grades`·`game_grade_assignments`·`games`·`usage_floors` 에서 읽어 만든다
  (현행 `_usage_rows()` 가 이미 그렇게 한다 — 범위만 넓힌다).

## 4. AI 가 내는 것 — 「격자 좌표」 스키마

DB 실측(2026-09-16) 어휘 그대로다. 지어낸 값은 없다.

```json
{
  "pc": true,
  "state": {
    "usages":     ["게임", "영상편집"],          // usage_floors.usage_label 중 0~N개
    "budget_won": 2000000,                    // 원 단위 정수 | null
    "budget_bound": null,                     // "이상" | "이하" | null
    "platform":   null,                       // "인텔" | "AMD" | null
    "tier_key":   null,                       // 비게임 힌트. spec_tiers.tier_key(T0~T5) | null
    "game": {                                 // usages 에 게임 계열이 있을 때만
      "names":      ["오버워치"],               // 고객이 말한 게임명 원문(0~N)
      "grade":      "E",                      // game_load_grades.grade (E/A/B/C/S/L) | null
      "grade_src":  "catalog",                // "catalog"(우리 목록) | "ai_estimate" | null
      "resolution": "1080p"                   // "1080p"|"1440p"|"4K" | null
    },
    "exclude":    [],                         // EXCLUDE_VALUES 그대로
    "prefs":      []                          // PREF_VALUES 그대로
  },
  "missing":  ["game.resolution"],            // 카드를 내기 위해 아직 비어 있는 좌표
  "evidence": ["'오버워치'는 E등급(경쟁 이스포츠) 대표 게임"],   // 판단 근거(로그·표시용)
  "reply":    "모니터는 어떤 걸 쓰세요? 해상도에 따라 구성이 달라져요."
}
```

**state 는 누적 상태다.** 화면이 이전 state 를 그대로 다시 보내고, AI 는 「이전 state + 이번
문장」 → 「새 state」 를 낸다. 현행처럼 constraints 배열을 매 턴 통째로 재구성하는 것과 같은
원리이나, 담는 것이 키워드가 아니라 좌표다.

## 5. 서버 검증 규칙 (AI 출력을 그대로 믿지 않는다)

| 필드 | 검증 | 실패 시 |
|---|---|---|
| `usages[]` | 각 값 ∈ `usage_floors.usage_label` | 밖의 값은 `dropped` 에 사유와 함께 |
| `tier_key` | ∈ `spec_tiers.tier_key` | null 로 접고 dropped |
| `game.grade` | ∈ `game_load_grades.grade` | null 로 접고 dropped |
| `game.grade_src` | names 중 하나라도 `games` 에 있고 `game_grade_assignments` 에 등급이 있으면 서버가 **catalog 로 덮어쓴다**(AI 가 ai_estimate 라 해도). 목록에 없을 때만 ai_estimate 인정 | — |
| `game.resolution` | ∈ {1080p, 1440p, 4K} | null |
| `budget_won` | 정수 · 0 초과 | null |
| `platform` | ∈ {인텔, AMD} | null |

**등급의 정본은 여전히 DB 다.** AI 가 "배그는 A등급" 이라 해도 `game_grade_assignments` 가
E 라면 E 다. AI 추정은 **우리 목록에 없는 게임에만** 허용된다(§6 ②).

## 6. 확정된 정책 3항목 (2026-09-16 사장님)

| # | 상황 | 확정 | 구현 |
|---|---|---|---|
| ① | 용도가 둘 이상 | **카드 두 벌을 모두 보여준다** | `usages[]` 각각에 대해 격자 조회 → 응답 `card_sets[]`(용도별 묶음). 화면은 용도 탭 또는 구획으로 나눠 렌더 |
| ② | 목록에 없는 게임 | **추정 등급으로 바로 카드, 화면에 「AI 추정」 표시** | `grade_src="ai_estimate"` 이면 카드에 배지 + 문구 「이 게임은 AI 가 ○등급으로 추정했습니다」. 추정 기록은 `talk_game_estimates`(신설, §8)에 남겨 사람이 확정하면 `games`·`game_grade_assignments` 에 편입 |
| ③ | 해상도를 모름 | **모니터 얘기가 나오면 반영, 아니면 1080p 기본** | AI 는 문장에 모니터·해상도·주사율 언급이 있을 때만 `resolution` 을 채운다. null 이면 서버가 1080p 로 카드를 내되 `assumed:["resolution=1080p"]` 로 표시 → 화면이 「1080p 기준 · 바꾸기」 |

`missing` 에서 해상도는 빠진다(③). 카드를 막는 `missing` 은 **용도 없음** 하나뿐이다 —
게임 용도인데 게임명도 등급도 없으면 AI 가 `reply` 로 되묻되(자연어), 서버는 `missing:["game.grade"]`
로 카드를 내지 않는다.

## 7. 한 턴의 흐름 (재설계 후)

```
화면  POST /api/talk/parse { text, state(이전), history }
        │
서버  ① 격자 설명서 조립 (매 요청 DB)
        │   spec_tiers 6행 → "팝콘1(T0): GPU 하한 없음·6코어·16GB·512GB … 팝콘X(T5): 1000W…"
        │   game_load_grades 6행 + example_titles → "E 경쟁 이스포츠: 발로란트·LoL·오버워치…"
        │   game_grade_assignments JOIN games → 확정 22종 목록
        │   usage_floors.usage_label + match_terms → 용도 어휘
        │
      ② 프롬프트 = 설명서 + 이전 state + 이력 + 이번 문장 + 출력 스키마(§4)
      ③ llm.call(task_key="task.s1_parse")            ← 변경 없음(래퍼·캡·비용 기록 그대로)
      ④ JSON 파싱 → §5 검증 → state 확정, dropped 수집
      ⑤ 게임명이 games 에 있으면 grade 를 DB 값으로 덮어씀 (grade_src=catalog)
      ⑥ 응답 { state, missing, dropped, evidence, reply, assumed }
        │
화면  state 저장(다음 턴에 되돌려 보냄) · reply 말풍선
      missing 비었으면 →
        │
      POST /api/grid/recommend { state }                 ← 입력 계약이 constraints → state 로
        │
서버  usages[] 마다:
        비게임 → tier_key 있으면 그 칸 중심, 없으면 budget 으로 tier_index_for (현행)
        게임   → (grade, resolution|1080p, platform) 로 칸 1개 (현행 _build_game_cards)
      → { card_sets:[{usage, cards[3종]}], assumed[], ai_estimated[] }
        │
화면  용도별 카드 묶음 렌더 · 「AI 추정」·「1080p 기준」 배지
```

**되묻기는 AI 만 한다.** 서버 내부 사유(`note`)는 고객 말풍선에 싣지 않는다 — 결함 ④ 해소.
서버가 카드를 못 낼 때 화면에 보이는 문장은 언제나 AI 의 `reply` 다.

## 8. 바뀌는 파일과 이유

| 파일 | 변경 | 근거 |
|---|---|---|
| `api/talk.py` | 프롬프트(격자 설명서 포함) · 출력 스키마(§4) · 검증(§5) · `state` 입출력 | 좌표 언어로 전환 |
| `api/talk_schema.py` (신설) | `State` pydantic 모델 + 좌표 어휘 로더(DB) — **talk.py 와 grid_public.py 가 함께 import** | 라벨 계약이 두 파일에 두 벌 있던 병(결함 ③)의 구조적 해소. 단일 원천 |
| `api/grid_public.py` | 입력을 `state` 로 · `usages[]` 반복 → `card_sets[]` · `_find_game_name`/`GAME_NAME_LABEL_PRIORITY` 삭제(AI 가 이미 좌표를 줌) · `assumed`/`ai_estimated` 응답 | §6 ①②③ |
| `db/migrations/0093_talk_game_estimates.py` (신설) | `talk_game_estimates(estimate_id, game_name_raw, grade, evidence, visitor_key, created_at, resolved_game_id NULL)` | §6 ② — 추정을 흘리지 않고 모아 사람이 확정. 원장·되돌림 규약대로 삭제 없이 `resolved_game_id` 로 편입 표시 |
| `mockups/mvp2/app.js` | `state` 보관·회신 · `card_sets` 렌더(용도별) · 배지 2종 · `note` 말풍선 제거 | 화면 계약 |
| `tests/regression.py` | ① AI 출력 어휘 ⊆ DB 어휘 ② grade_src=catalog 일 때 grade == DB 값 ③ `note` 가 고객 응답에 없음 ④ card_sets 수 == usages 수 | 회귀 |

**건드리지 않는 것**: `api/llm.py`(래퍼·캡·비용) · `api/recommend.py`(엔진) · `tools/grid_generate.py`
(배치) · `grid_cells`/`grid_quotes` 스키마 · 관리자 화면.

## 9. 프롬프트 골격 (제작자가 채운다 — 어휘는 DB 에서)

```
당신은 PC 견적 상담원이다. 고객 말을 듣고 아래 격자의 어느 칸인지 판단한다.
견적·부품·가격은 말하지 않는다(다른 시스템이 한다).

[격자 — 성능 티어]            ← spec_tiers 에서 생성
팝콘1(T0) … 팝콘X(T5): 각 GPU/CPU/RAM/SSD 하한

[격자 — 게임 부하 등급]        ← game_load_grades + example_titles
E 경쟁 이스포츠(발로란트·LoL·오버워치…) / A … / L 경량 캐주얼(메이플·로블록스…)

[우리가 등급을 확정한 게임]     ← game_grade_assignments JOIN games
오버워치=E, 배틀그라운드=E, 사이버펑크2077=C …  (22종)
목록에 없는 게임은 위 등급 설명으로 추정하고 grade_src="ai_estimate" 로 표시한다.

[용도]                        ← usage_floors
게임 / 고사양 게임 / 캐주얼 게임 / 사무·인강 / 영상편집 / 디자인 / 3D 그래픽 / AI 작업 / 주식·트레이딩

[이전까지 파악한 상태]  {state JSON}
[대화 이력]            …
[이번 문장]            "…"

[규칙]
- state 는 누적이다. 이번 문장이 바꾼 것만 고치고 나머지는 유지한다.
- 용도가 여럿이면 usages 에 전부 넣는다.
- 해상도는 모니터·해상도·주사율 언급이 있을 때만 채운다. 없으면 null.
- 카드를 내기에 아직 모자란 좌표를 missing 에 적고, reply 로 그중 하나만 자연스럽게 묻는다.
- 문장에 없는 것을 만들지 않는다. 판단 근거를 evidence 에 한 줄씩 적는다.

[출력] JSON 하나 — §4 스키마
```

## 10. 검증 계획 (확인자)

- 대화 시나리오 8종을 curl 로 돌려 **state 좌표가 DB 어휘 안** 인지, **grade 가 DB 확정값과
  일치** 하는지(catalog), **목록 밖 게임에서만 ai_estimate** 가 나오는지 실측
  - "롤이랑 발로란트만 해요" → 게임·E·catalog
  - "요즘 대작 다 돌리고 싶어요" → 게임·grade 추정(C 또는 B)·ai_estimate·names 빈 배열
  - "영상편집인데 4K 작업 많아요" → 영상편집·tier_key T3 이상 힌트
  - "게임도 하고 편집도 해요" → usages 2개 → card_sets 2개
  - "오버워치, 모니터 144Hz 1440p" → 게임·E·1440p
  - "오버워치" 만 → 게임·E·resolution null → 서버 1080p assumed
  - "예산 150 으로 줄일게요"(이전 state 있음) → budget 만 바뀌고 나머지 유지
  - "날씨 어때요" → pc=false
- 결함 ④: 응답에 서버 내부 사유 문자열이 고객 `reply` 로 나가지 않는지
- 비용: 프롬프트가 격자 설명서만큼 길어진다 — 토큰 수 실측해 `cost_thresholds` 기본값과 대조

## 11. 미정 (이번 설계에서 정하지 않음 — 사장님)

- `talk_game_estimates` 를 사람이 확정하는 **관리자 화면** 은 이번 범위 밖(정의서 별도).
  당장은 표에 쌓이기만 한다.
- 비게임 `tier_key` 힌트를 AI 가 낼 때 **예산과 충돌**하면(예: "4K 편집" → T3 인데 예산 80만)
  어느 쪽을 중심으로 할지 — 현행 `tier_index_for` 는 예산 우선. 이번엔 **예산 우선 유지**하고
  `evidence` 에 충돌을 적는다. 바꾸려면 결정 필요.
