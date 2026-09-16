# 상세 시스템 흐름도 — 고객 대화 입력 ~ 백엔드 DB (mvp2, 2026-09-16)

사용자 관점의 "대화 한 마디"가 화면 → API → DB → 화면으로 어떤 순서·로직으로 도는지,
실제 코드(파일:줄)를 그대로 따라간 것이다. 추측 없음 — 화살표마다 대응 함수가 있다.

---

## 0. 등장인물 (파일 단위)

| 계층 | 파일 | 역할 |
|---|---|---|
| 화면 | `mockups/mvp2/app.js` | 사용자 입력 받기, 대화이력 관리, 카드 렌더 |
| 파서 API | `api/talk.py` (`POST /api/talk/parse`) | 문장 → 조건(constraints) + PC상담 여부 + 답변 |
| LLM 래퍼 | `api/llm.py` | Claude/Codex/Gemini 실제 호출, 캡·폴백 |
| 용도 하한 | `api/usage_floors.py` | 용도 어휘·매칭 정본(usage_floors 테이블) |
| 격자 API | `api/grid_public.py` (`POST /api/grid/recommend`) | 조건 → 실제 견적 카드(3종) |
| DB | Cloud SQL `popcorn_pc` | `usage_floors`, `games`, `game_grade_assignments`, `spec_tiers`, `grid_cells`, `grid_quotes`, `products`, `api_cost_logs` |

---

## 1. 사용자가 문장을 입력하는 순간 (화면)

```
사용자가 입력창에 "200만원대 게임용" 입력 → 전송
  │
  ▼ mockups/mvp2/app.js : submit(text)                              [app.js:233]
     1. text 트림, 비어있으면 중단
     2. showWorkspace() — 환영 화면 숨기고 대화창 표시
     3. addMessage('user', text) — 내 말풍선 즉시 렌더 (서버 응답 기다리지 않음)
     4. history = state.history의 최근 6턴(HISTORY_MAX)만 잘라 담음
        ⚠ 이 시점의 history는 "이번 문장 이전" 것만 — 방금 입력한 문장은 아직 안 들어감
     5. addMessage('assistant', '조건을 읽는 중…') — 로딩 말풍선
     6. setBusy(true) — 전송 버튼 등 비활성화
  │
  ▼ fetch POST /api/talk/parse  { text: "200만원대 게임용", history: [...] }  [app.js:241]
```

---

## 2. 서버: 문장 파싱 (api/talk.py) — LLM 호출 지점

```
POST /api/talk/parse 도착 → parse_talk(body, request)                [talk.py:619]
  │
  ├─ 1) 입력 검사
  │     text 공백이면 400, MAX_TEXT_LEN 넘으면 400 (LLM 호출 전 — 비용 안 씀)
  │
  ├─ 2) 방문자별 호출 횟수 제한 확인 — api/access_gate                [talk.py:634 주석]
  │     소유자 개념 없는 경로라 429만 존재(분당/일당 한도, rate_limit_policies 표)
  │
  ├─ 3) 용도 정본 로드 — _usage_rows()                                [talk.py:262]
  │     UF._rows() 호출 → DB usage_floors 테이블에서 (usage_label, match_terms) 전부 읽음
  │     ⚠ 요청마다 새로 읽는다 — 운영자가 usage_floors 고치면 다음 요청부터 반영
  │
  ├─ 4) 프롬프트 조립 — _build_prompt(text, usage_rows, history)      [talk.py:282]
  │     - 용도 어휘 전부(예: "게임(게임, 고사양 게임 아님...)") 프롬프트에 삽입
  │     - history 있으면 "[지금까지의 대화]" 문단 추가 + "누적 조건 전체를 내라" 지시
  │     - 출력 형식 강제: {"pc":bool, "constraints":[{"l":라벨,"v":값}], "reply":"..."}
  │     - 금지 사항 명시: 부품·가격·후보 수 언급 금지, 없는 조건 지어내기 금지
  │
  ├─ 5) LLM 실제 호출 — llm.call(prompt, task_key="task.s1_parse")    [llm.py:882]
  │     ┌─────────────────────────────────────────────────────────┐
  │     │ a. _resolve_task_default("task.s1_parse")                │
  │     │    → DB ai_task_assignments 테이블 조회 (0행이면 폴백)     │
  │     │    → 코드 기본값 TASK_DEFAULTS["task.s1_parse"]           │
  │     │      = ("claude", "claude-haiku-4-5-20251001")            │
  │     │ b. _check_caps(conn, "claude", ...) — DB 조회 2종          │
  │     │    - rate_limit_policies (분당/일당 호출 수 한도)          │
  │     │    - cost_thresholds (일일 비용 한도, $2 기본값)           │
  │     │    - api_cost_logs 에서 오늘 누적 조회 → 한도 비교         │
  │     │    한도 넘으면 LLMBlockedError → 호출 자체를 안 함         │
  │     │ c. _call_claude(model, prompt, ...) — 진짜 Anthropic API   │
  │     │    ANTHROPIC_API_KEY 로 실제 네트워크 요청                 │
  │     │ d. 응답 텍스트 → api_cost_logs 테이블에 INSERT             │
  │     │    (provider, model, tokens_in, tokens_out, cost_usd)      │
  │     └─────────────────────────────────────────────────────────┘
  │     실패 시: 한도초과=429, 키없음/키오류=502(폴백 시도 후), 완전 실패=502
  │
  ├─ 6) 응답 JSON 파싱 — _extract_json(raw)                          [talk.py:510]
  │     ```json 울타리 제거, 첫 { 부터 마지막 } 까지 파싱
  │
  ├─ 7) PC 상담 여부 판정 — _pc_verdict(obj)                          [talk.py:543]
  │     bool 아니면 무조건 None(모름) — false로 함부로 접지 않음
  │
  ├─ 8) 조건 검증 — _validate(raw_items, usages)                     [talk.py:563]
  │     각 항목에 대해:
  │       - l(라벨)이 LABELS=(예산,용도,선호,부품,플랫폼,제외) 밖 → dropped
  │         ⚠ "게임명"은 이 목록에 없음 — LLM이 뽑아도 여기서 무조건 dropped
  │       - 라벨별 정규화:
  │         · "예산"  → _norm_budget(val) : 정규식으로 "N만원" 추출
  │         · "용도"  → _norm_usage(val, usages) : UF.match() 위임, 정본 1개만 채택
  │         · "선호"  → _norm_from_set(val, PREF_VALUES=(저소음,화이트))
  │                     ⚠ 화이트리스트 밖 값(예: "오버워치")은 여기서 dropped
  │         · "플랫폼"→ PLATFORM_VALUES=(인텔,AMD) 중 첫 값만
  │         · "제외"  → EXCLUDE_VALUES=(모니터 보유,OS 제외,본체만)
  │
  ├─ 9) reply 문장 결정 — _reply_text(obj, pc, kept)                 [talk.py:525]
  │     pc=false면 고정 문구, 아니면 모델이 낸 reply(최대 200자)
  │
  └─ 10) 대화 기록 저장 — talk_intent_hits 테이블 (마스킹 후)          [talk.py:102-121 주석]
        PII 마스킹(mask_pii) → INSERT, 90일 후 자동 삭제(raw_purge_at)

응답: { ok, constraints:[{l,v}], dropped:[{l,v,reason}], pc_related,
        reply, history_used, provider:"claude", model:"...", cost_usd, ... }
```

---

## 3. 화면: 파서 응답 처리 (app.js)

```
app.js submit() 이어서                                                [app.js:243]
  │
  1. thinking.remove() — 로딩 말풍선 제거
  2. pushHistory('user', text) — 이번 문장을 이력에 추가(다음 호출용)
  3. state.constraints = 응답 constraints 로 통째로 교체 (누적 아님 —
     "누적 조건 전체"는 위 4)에서 LLM 프롬프트가 이미 지시해 서버가 합쳐서 냄)
  4. reply 있으면 말풍선 표시 + pushHistory('assistant', reply)
  5. dropped 있으면 "반영하지 못한 조건: ..." 말풍선 표시
     ⚠ "게임명" 관련 dropped는 이 시점엔 없음 — talk.py가 애초에 그 라벨을
        만들지 않으므로 dropped 목록에도 안 나타남(조용히 사라짐)
  6. pc_related===false → 중단(카드로 안 감)
  7. usageOf(constraints) 없으면 → 중단(용도 없으면 격자 호출 안 함)
  8. 있으면 → recommend() 호출
```

---

## 4. 서버: 격자 카드 조회 (api/grid_public.py) — DB 조회 지점

```
POST /api/grid/recommend { constraints: [...] }                       [grid_public.py:500]
  │
  ├─ 1) 예산 파싱 — parse_budget(_pick(cons,"예산"))                  [grid_public.py:135]
  │     "150만원" → (1500000, None) 처럼 (원, bound) 튜플로 변환
  │
  ├─ 2) 용도 판정 — _usage_grid_of(cons)                              [grid_public.py:255]
  │     "용도" 라벨 값을 USAGE_TO_GRID 매핑표로 변환
  │     "게임"/"캐주얼 게임"/"고사양 게임" → 전부 GAME_USAGE("게임")로 합류
  │
  ├─ 3) 플랫폼 판정 — _platform_of(cons)                              [grid_public.py:241]
  │     "플랫폼" 라벨 없으면 "선호" 값에서 AMD/인텔 키워드 탐색, 기본 인텔
  │
  ├─ 4) 분기: usage_grid == "게임" 인 경우 ───────────────────────────
  │     │
  │     ├─ _resolve_game(conn, cons)                                  [grid_public.py:286]
  │     │    │
  │     │    ├─ _find_game_name(conn, cons)                           [grid_public.py:269]
  │     │    │    │
  │     │    │    ├─ DB 조회: SELECT name FROM games  (전체 게임명 목록)
  │     │    │    ├─ 이름을 긴 것부터 정렬(짧은 이름 오매칭 방지)
  │     │    │    └─ GAME_NAME_LABEL_PRIORITY=("게임명","요청","선호") 순서로
  │     │    │       constraints 안에서 그 라벨의 값에 games.name이
  │     │    │       부분 문자열로 들어있는지 검사
  │     │    │       ⚠⚠⚠ 여기가 실패 지점 ⚠⚠⚠
  │     │    │       - "게임명" 라벨: talk.py가 절대 생성 안 함(LABELS에 없음)
  │     │    │       - "요청" 라벨: talk.py LABELS 자체에 존재하지 않는 라벨
  │     │    │                     (grid_public.py 제작자의 잘못된 가정)
  │     │    │       - "선호" 라벨: PREF_VALUES=(저소음,화이트) 화이트리스트라
  │     │    │                     "오버워치" 값 자체가 위 §3-8에서 이미 dropped됨
  │     │    │       → 셋 다 실패 → None 반환
  │     │    │
  │     │    └─ name이 None이면 즉시 반환:
  │     │       { grade:None, needs:["게임명"],
  │     │         note:"게임 용도인데 게임명을 알 수 없어..." }
  │     │
  │     ├─ needs=["게임명"] 이므로 game_grade는 None으로 남음
  │     └─ game_grade is None → _build_game_cards() 호출 자체를 안 함
  │        (grid_public.py:547 `if game_grade is not None:` 조건에서 막힘)
  │        → cards = [] (빈 배열)
  │
  ├─ 4') 분기: usage_grid != "게임" 인 경우 (참고 — 정상 동작 경로) ──
  │     │
  │     ├─ _load_tiers(conn, usage_grid, platform)                    [grid_public.py:160]
  │     │    DB: SELECT tier_key, popcorn_name FROM spec_tiers ORDER BY sort_order
  │     │    DB: SELECT tier_key, budget_min, budget_max FROM grid_cells
  │     │        WHERE usage=:u AND platform=:p  (관측 가격 6개 티어분)
  │     │
  │     ├─ tier_index_for(tiers, budget_won, bound)                   [grid_public.py:191]
  │     │    예산에 가장 가까운 관측 가격의 티어 인덱스 선정
  │     │
  │     └─ _build_nongame_cards(conn, considered, ...)                [grid_public.py:398]
  │          DB: grid_cells LEFT JOIN grid_quotes (is_current=true)
  │              WHERE usage=:u AND platform=:p AND tier_key = ANY(선택된 티어들)
  │          → 티어별로 3종(가성비/추천/고성능) quote row 모음
  │          DB: SELECT product_code, stock_qty FROM products WHERE product_code=ANY(...)
  │              (카드에 들어갈 부품들의 실시간 재고 조회)
  │          → _build_card() 로 카드 조립, quotes:{value,reco,perf} 구조로 반환
  │
  └─ 응답: { cards:[], needs:["게임명"], note:"게임 용도인데...", ... }
           (게임 경로 실패 시 cards는 항상 빈 배열)
```

---

## 5. 화면: 카드 렌더 또는 안내 (app.js)

```
app.js recommend() 이어서                                             [app.js:256]
  │
  1. state.grid = 응답 전체, state.quotes = cards(빈 배열)
  2. needs = ["게임명"]  →  needs.length > 0 이므로:
  3.    g.note 를 그대로 말풍선으로 표시                               [app.js:264]
        "게임 용도인데 게임명을 알 수 없어 등급을 정할 수 없습니다..."
  4.    return — 카드 렌더 코드(conditionsMarkup, recommendationMarkup)에
        도달하지 못하고 함수 종료
  │
  ▼ 사용자에게는: 시스템 디버그 문구가 "팝콘PC AI"의 말인 것처럼 노출됨
     (addMessage가 role='assistant'로 렌더 — 내부 사유 문자열과 고객 응대
      문구를 구분하는 계층이 없음)
```

---

## 6. 두 번째 턴 — "오버워치"라고 답해도 똑같이 실패하는 이유

```
사용자: "오버워치" 입력
  │
  ▼ submit("오버워치") 재실행 — history 에 이전 대화 4줄 포함하여 재호출
  │
  ▼ POST /api/talk/parse — LLM이 문맥상 "오버워치"를 게임명으로 인식은 함
  │   (reply: "고사양 게임 중에서도 오버워치를 하실 생각이군요" — 이건 자유
  │    텍스트라 어디든 넣을 수 있음, LLM의 일반 언어 능력)
  │
  │   하지만 _validate() 는 constraints 항목의 "l"(라벨) 값이 LABELS 안에
  │   있어야만 살아남는다. LLM이 "오버워치"를 다음 중 어디에 넣었든:
  │     - l="게임명" 으로 넣음  → LABELS에 없음 → dropped (talk.py:582)
  │     - l="선호"  으로 넣음  → PREF_VALUES=(저소음,화이트) 밖 → dropped (talk.py:465-467)
  │     - 아예 안 넣음(용도="게임"만 유지) → 애초에 후보조차 없음
  │   결과: constraints 에는 "오버워치"라는 문자열이 어떤 형태로도 남지 않음
  │
  ▼ 이번에도 usage="게임"만 있고 게임명 정보는 소실된 채 grid/recommend 호출
  │
  ▼ _find_game_name() 다시 실패 → needs=["게임명"] 반복
  │
  ▼ 화면에 같은 안내문 재출력 — 사용자 입장에서는 "말해도 안 먹힌다"
```

---

## 7. 결함 정리표

| # | 위치 | 실제 코드 | 문제 |
|---|---|---|---|
| ① | `api/talk.py:209` | `LABELS = ("예산","용도","선호","부품","플랫폼","제외")` | "게임명" 라벨 없음 — LLM이 인식해도 담을 곳이 없음 |
| ② | `api/talk.py:180` | `PREF_VALUES = ("저소음","화이트")` | "선호"의 값이 이 둘로만 제한 — 게임명이 "선호"에 담겨도 걸러짐 |
| ③ | `api/grid_public.py:104` | `GAME_NAME_LABEL_PRIORITY = ("게임명","요청","선호")` | "요청"이라는 라벨은 talk.py 어디에도 정의/생성되지 않음(존재하지 않는 라벨을 최우선으로 찾음) |
| ④ | `mockups/mvp2/app.js:264` | `if(g.note)addMessage('assistant',g.note)` | 서버 내부 디버그 사유 문자열을 그대로 고객 채팅 말풍선에 노출 |

**①②③은 "대화에서 게임명을 뽑아 카드에 반영한다"는 기능이 세 파일 중 어느 하나도
실제로 완성돼 있지 않은 상태** — 설계 의도(주석)는 있지만 구현이 안 맞물려 있다.
④는 별개의 UX 결함(내부 사유를 고객 문구로 오인시킴).

---

## 8. 재구성 시 다뤄야 할 질문 (판단 보류 — 사장님 결정 필요)

1. **"게임명" 라벨을 talk.py에 신설할 것인가?**
   - LLM 프롬프트에 "게임명" 항목 추가 → `_validate`가 그 라벨을 받아들이도록
   - grid_public.py의 `games` 테이블 대조 로직(`_find_game_name`)은 이미 있으므로
     talk.py 쪽만 고치면 연결됨
2. **"요청" 라벨(grid_public.py가 참조하는 존재하지 않는 라벨)을 어떻게 할 것인가?**
   - 신설(고객 원문을 그대로 보존하는 자리)할지, 우선순위에서 제거할지
3. **내부 사유(note)와 고객 응대 문구를 구조적으로 분리할 것인가?**
   - 지금은 `note` 필드 하나가 로그성 설명과 고객 안내를 겸함
4. **라벨 계약(LABELS 등)을 두 파일이 공유하는 단일 원천으로 옮길 것인가?**
   - 지금은 talk.py와 grid_public.py가 각자 라벨 목록을 따로 들고 있어
     한쪽만 고치면 다시 어긋날 수 있음(오늘 사고의 재발 방지 관점)
