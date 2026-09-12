# 용도×티어 구성 규칙 (usage_tier_rules) — 설계 메모 2026-09-12

사장님 확정: "그대로 진행해" (2026-09-12). 근거 자료 = D:/Hermes-Workspace/crawl/analysis.md
(협력사 3사 1,733건 · 표본 n 병기).

## 왜 새 표인가
- `usage_floors` = 용도당 하나의 하한 세트. 티어별 차이(팝콘 5 AI RAM 32 vs X AI RAM 64)를 못 표현.
- `BUDGET_ALLOC` = 전 용도 고정 배분. 시장은 "같은 예산에서 게임은 GPU에, AI는 RAM에" 쓴다.
- 그래서 (usage_key, budget_min) 축을 가진 표가 필요. usage_floors 는 그대로 두고(하한 = 최저선),
  이 표는 **그 위에서 "이 티어에선 이 급을 겨냥한다"**를 말한다.

## 표 정의  usage_tier_rules
  rule_id · usage_key(usage_floors.usage_key와 같은 어휘) · budget_min(원, 이 값 이상 예산에 적용,
  가장 큰 budget_min 하나만 적용) · slot · field · op(gte|lte|eq) · value · label · active · note(근거 n)

  적용 방식(엔진): 용도 매치 + 예산 cap 으로 budget_min ≤ cap 인 규칙 중 **usage_key별·slot별로
  budget_min 이 가장 큰 행**을 고른다 → 그 슬롯 후보를 그 조건으로 거른다(usage_floors.passes 와
  같은 술어). 값 모르면 불통과(NULL 원칙 동일). **걸러서 조합이 안 나오면 이 표만 풀고 근거에
  "시장 표준 구성으로는 조합이 없어 하한만 적용" 을 남긴다**(usage_floors 는 유지).

## 규칙 값 (시장 다수값 · n 병기) — 티어 경계는 0082

### GPU vram_gb (gte) — VRAM 단계가 가격을 결정한다((d)절)
| usage | budget_min | value | 근거 |
|---|---|---|---|
| game, gaming_high, video, ai, design | 1,500,000 (팝콘5) | 8 | 5060/5060Ti 8GB — 팝콘5 57%(n=421) |
| gaming_high, video, ai | 3,000,000 (팝콘7) | 12 | RTX 5070 12GB — 팝콘7 57%(n=290), AI 88%(n=25) |
| gaming_high | 4,000,000 (팝콘7+) | 16 | RTX 5080 53%(n=13) |
| video | 4,000,000 | 16 | 5070Ti 60%(n=41) |
| ai, gaming_high, video | 5,500,000 (팝콘9) | 16 | RTX 5080 84%(n=59), AI 89%(n=38) |
| ai, video, gaming_high | 8,000,000 (팝콘X) | 32 | RTX 5090 72%(n=18), AI 84%(n=13) |
  ⚠ 5090 재고: 판매중·재고>0 14개, 최저 756만 — X(800~1500만) 안에서 성립 가능.

### RAM capacity_gb (gte) — 용도가 RAM 을 가른다((b)절)
| usage | budget_min | value | 근거 |
|---|---|---|---|
| game | 2,200,000 (팝콘5+) | 32 | 온라인게임 5+ 73%(n=15), 7 이상 100% |
| gaming_high | 3,000,000 | 32 | 76%(n=30), 7+ 92%, 9 100% |
| video | 2,200,000 | 32 | 영상편집 5+ 63%(n=33) · 7 96%(n=30) |
| ai | 1,500,000 | 32 | AI 팝콘5 53%(n=13) → 5+ 89%(n=19) → 7 100% |
| ai | 4,000,000 | 64 | AI 7+ 55%(n=20) → 9 97%(n=38) → X 92%(n=13) |
| video | 8,000,000 | 64 | X 영상편집 100%(n=3, 표본 얇음 — 9 는 32GB 81% 이므로 X 만) |
| design | 3,000,000 | 32 | 디자인 7 100%(n=14) |
| dev | 1,500,000 | 32 | 시장 표본 0 — 웹 조사(Medium 2026-04 "32GB 미만 사지 말라") |

### CPU cpu_cores (gte) — 영상편집·AI·디자인 고티어는 다코어((b)절: U7 265K/9900X/U9 285K)
| usage | budget_min | value | 근거 |
|---|---|---|---|
| video, ai, design | 3,000,000 (팝콘7) | 12 | 팝콘7 영상편집 CPU 상위 U7 265KF(20)·R9 9900X(12) |
| video, ai | 5,500,000 (팝콘9) | 20 | U7 270K(20) 23%·U9 285K(24) 13%(n=59) |
| ai | 8,000,000 | 24 | U9 285K 46%(n=13) |
  게임(game·gaming_high)은 코어 규칙 없음 — 시장은 X3D(8코어)를 고른다. 코어 하한을 걸면
  시장 표준(9800X3D)이 탈락한다. **게임 CPU 는 규칙을 두지 않는다.**

### 사무(office) — 규칙 없음. 팝콘 3만 채우고 iGPU 가 74% 인데 우리 엔진은 GPU 슬롯 필수.
  (별도 결정 사항 — 이번 범위 밖. usage_floors 그대로.)

## 배치 재실행 후 확인할 것
- 팝콘 X AI 인텔 카드 GPU 가 RTX 5090 인가(이전 5080)
- 팝콘 9·X 6칸이 용도별로 갈리는가(이전 전부 동일)
- 실패 칸이 생기면 어느 규칙이 조합을 막았나(status='생성 실패' + engine_note)
