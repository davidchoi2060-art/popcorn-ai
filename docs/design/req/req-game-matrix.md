# 게임·AI 연계 매트릭스 — 요구사항 정의서 (⚠ 폐기 2026-09-15)

> **폐기 사유**: A-135(격자를 가격 축에서 스펙 축으로 재정의)로 게임 칸이
> `(game_grade, game_resolution)`으로 직접 정의된다(0091 `game_grade_
> assignments`가 게임→등급을 이미 고정 매핑) — "이 게임이 어느 칸에서
> 성립하는지"를 `game_cell_map` 캐시로 되짚어 계산할 필요가 없어졌다.
> 근거 확인 기능만 `ADM-GRD-010`(상품 매트릭스 관리) 상세 서랍으로 흡수됐다
> (`req-grid-admin-2026-09-15.md` §⑤-6). 이 문서는 역사 기록으로 남긴다 —
> 지우지 않되, 더 이상 구현 대상이 아니다.

**화면 ID**: `ADM-GRD-020` (가칭 — 확정 안 아님, 사장님 확정 필요)
**경로**: `/admin2/game-matrix`
**작성**: 2026-09-08 · 하네스
**선행 문서**: `docs/design/game-quote-mapping-2026-09-07.md`(판정 3경로 설계) ·
`docs/design/prebuilt-grid-benchmark-2026-09-07.md`(격자 구조) ·
`docs/decisions/decision-log.md` A-126(컨셉 전환)
**연관 화면**: `ADM-GRD-010`(격자 관리, `/admin2/grid` — 이미 지어짐, 가격 격자 자체를 본다)

> 이 문서는 요구사항까지만 담는다. 배치·컴포넌트·색은 정하지 않는다
> (CLAUDE.md §화면 작업의 경계). UI 설계는 이 정의서를 입력으로 별도 진행한다.

---

## ① 화면 성격

**조회 화면.** 오늘 새로 만든 `game_cell_map`·`workload_cell_map`(게임·AI 작업이
어느 격자 칸에서 성립하는지 사전 계산해 둔 판정 결과)을 사람이 훑어보는 자리다.
쓰기 기능 없음 — 매핑 재계산은 배치(`tools/game_cell_mapper.py`)가 하고, 이
화면은 그 결과를 확인·감사하는 용도다.

## ② 정의 — 이 화면이 없으면 무엇이 안 되는가

`game_cell_map`·`workload_cell_map`은 지금 SQL 직접 조회로만 볼 수 있다.
운영자가 "오버워치2는 어느 등급부터 되는지", "70B급 LLM은 왜 하나도 매칭이
안 됐는지"를 확인하려면 개발자에게 SQL을 부탁해야 한다. 이 화면이 없으면
①매핑 배치가 제대로 도는지 사람이 확인할 방법이 없고 ②게임·AI 데이터
보강이 필요한 지점(스킵된 게임·작업)을 운영자가 스스로 찾을 방법이 없다.

## ③ 데이터 (실측 근거)

전부 2026-09-08 Cloud SQL(`popcorn_pc`) 실측.

**원천 테이블**
- `games` (23행) — `game_id, name, genre, popularity_rank, official_source_url, min_cpu, min_gpu, min_ram_gb, rec_cpu, rec_gpu, rec_ram_gb, checked_date, note`
- `ai_workloads` (14행) — `workload_id, task, model_size, min_vram_gb, rec_vram_gb, min_ram_gb, recommended_tier, source_url, checked_date, note`
- `game_cell_map` (1,022행) — `game_id, cell_id, match_level('권장충족'|'최소충족'), gpu_used, computed_at` — PK(game_id, cell_id). **원장이 아니라 파생 캐시**(배치 재실행마다 TRUNCATE 후 재계산 — `grid_quotes.is_current`처럼 이력을 쌓지 않는다)
- `workload_cell_map` (420행) — 같은 구조, `match_level('구동가능'|'권장구성')`
- `grid_cells` — 축 3종: `tier`(팝콘3~X, 7단) · `usage`(8종) · `platform`(인텔/AMD)
- `grid_quotes`(`is_current=true`인 것만) — `cell_id, total, verdict, payload` (칸별 현재 견적)
- `gpu_ladder`(34행) — `chipset, ladder_score, vram_gb, source_url, checked_date, note` (판정에 쓰인 GPU 성능 서열 — 근거 추적용)

**실측 현황(2026-09-08 기준, 화면은 이 절대수를 하드코딩하지 않고 매번 조회한다)**
- 게임 23종 중 15종 매핑 성공(1,022행), 8종 스킵 — 스킵 사유 셋: `rec_gpu_parse_failed`(구세대 카드 표기, 5종) · `min_gpu_parse_failed_partial`(부분 매칭 실패, 5종 — 게임별로 min/rec 각각 스킵될 수 있어 8과 합산되지 않음) · `rec_gpu_missing`(원천에 값 없음, 3종)
- AI 작업 14건 중 7건 매핑(420행), 6건 스킵(`zero_matching_cells` — 재고 최고 VRAM으로도 부족, 정상 판정) + 1건(`min_vram_gb_missing`)
- 매핑이 없는 게임/작업의 **스킵 사유**는 `tools/game_cell_mapper.py --dry`의 `SUMMARY_JSON.games.skip_detail`/`ai_workloads.skip_detail`에만 있고 DB 테이블에는 저장되지 않는다 — **화면에 스킵 사유까지 보여주려면 이 배치가 그 결과를 테이블에 남기도록 먼저 바꿔야 한다(④에 하한 명시)**

**신규 API 필요** — 지금 이 데이터를 주는 API는 없다(`ADM-GRD-010`은 격자 자체만 다룬다). 신설 시 아래가 필요:
- `GET /api/admin/game-matrix` — 게임×칸 매트릭스(칸은 tier×usage×platform 70개 중 필터된 일부, 게임은 23종). 응답에 `match_level`·해당 칸 `total`(최저가)·`gpu_used` 포함
- `GET /api/admin/game-matrix/skipped` — 스킵된 게임·작업과 사유(위 하한 해소 후)
- 둘 다 **owner뿐 아니라 조회 권한 전체**가 볼 수 있어야 한다(쓰기가 없으므로 — `ADM-SYS-020` 권한 매트릭스 기준 확인 필요, 미정)

## ④ 기능 (동사로)

- **조회** — 게임 또는 AI 작업을 목록에서 고르면, 그 항목이 성립하는 격자 칸을 보여준다
- **필터** — 용도(8종)·플랫폼(인텔/AMD)·매칭 등급(권장충족/최소충족, 구동가능/권장구성)으로 좁힌다
- **정렬** — 가격 오름차순(가장 싼 성립 칸을 먼저 보여준다 — "이 게임 되는 가장 싼 견적"이 운영자가 가장 자주 물을 질문)
- **근거 확인** — 특정 칸의 판정을 클릭하면 그 판정에 쓰인 GPU 칩셋·`gpu_ladder` 점수·게임 쪽 요구 사양 원문을 함께 보여준다(왜 이 칸이 성립/불성립인지 추적 가능해야 한다 — "모든 견적에는 이유가 있습니다"와 같은 원칙)
- **미매핑 확인** — 스킵된 게임·AI 작업과 사유를 별도로 본다(④ 데이터의 하한 — 배치가 사유를 테이블에 남기도록 먼저 확장해야 가능. **이 하한이 안 풀리면 이 기능은 "없음" 상태로 화면에 명시하고 숫자는 보여주지 않는다** — CLAUDE.md §화면 정직성)

## ⑤ 인터랙션

1. 화면 진입 → 좌측(또는 상단)에 게임 탭 / AI 작업 탭 2분류
2. 게임 탭 선택 → 게임 23종 목록(매핑 성공 15 / 스킵 8이 시각적으로 구분됨 — 빈 값 종류를 섞지 않는다, MAKER-CHECKLIST §1 마지막 항)
3. 게임 하나 클릭 → 그 게임이 성립하는 칸 목록(권장충족/최소충족 구분, 가격순) + 성립하지 않는 나머지 칸은 "불성립" 또는 "판정 불가"(원인이 다르면 라벨도 다르게 — 지어내지 않는다)
4. 칸 하나 클릭(또는 hover) → 근거 패널: 그 칸의 GPU 칩셋명·`ladder_score`·게임의 `rec_gpu`/`min_gpu` 원문·RAM 비교
5. AI 작업 탭도 동일 구조(작업 14건, VRAM 비교가 핵심 근거)
6. 필터(용도·플랫폼·매칭등급) 변경 → 목록 즉시 갱신

## ⑥ 상태·예외

- **매핑 0건(스킵된 게임/작업)**: "매핑 없음" 텍스트 + 사유(하한 해소 시) 또는 "사유 미제공 — 배치 로그만 확인 가능"(하한 미해소 시) — 빈 칸(의도)과 빈 칸(미생성)을 구분해서 표시
- **격자 자체가 비어 있을 때**(`grid_quotes.is_current`가 0건): 매트릭스 전체를 "격자 데이터 없음 — 격자 관리(`ADM-GRD-010`)에서 먼저 생성" 안내로 대체
- **매핑 배치가 아직 한 번도 안 돈 경우**(`game_cell_map`이 테이블은 있으나 0행): "매핑 미실행" 상태
- **권한 없음**: 로그인하지 않은 관리자 접근 시 401(다른 admin2 화면과 동일 가드)
- **AI 작업의 "매칭 0건"은 결함이 아니라 정상 판정일 수 있다** — 재고 최고 VRAM으로 부족한 경우(`zero_matching_cells`)와 데이터 자체가 없는 경우(`min_vram_gb_missing`)를 화면에서 같은 문구로 뭉개지 않는다

---

## 미정 (임의 결정 금지)

- **화면 ID 확정**: `ADM-GRD-020`은 하네스가 그룹 내 다음 번호로 가칭 부여한 것 — 사장님 확정 필요
- **④의 하한**: 스킵 사유를 테이블에 남기도록 `tools/game_cell_mapper.py`를 먼저 확장할지, 1차는 매핑 성공분만 보여주고 스킵 사유는 2차로 미룰지
- **권한 범위**: 조회 전용 화면이라 관리자 전 등급(조회/운영자/관리자) 공통 노출이 맞는지, 아니면 다른 AI 관리 화면처럼 제한할지
