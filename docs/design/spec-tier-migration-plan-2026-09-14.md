# 스펙 티어 이행 설계안 — 게임·영상편집 종합 재설계 (조사자 산출물)

작성일: 2026-09-14 · 근거: A-135(`docs/decisions/decision-log.md` 7278~7324행),
`docs/design/spec-tier-source-2026-09-14.md`(사장님 원본, 이하 "원본 문서").

**이 문서의 위치**: A-135가 "미정 — 구현 착수 전 조사자 산출물 대기"로 남긴 4개 항목의
설계안이다. **DDL을 여기 적지만 아직 실행하지 않았다** — 마이그레이션 파일(0090+)을
만드는 것은 이 산출물을 사장님이 확정한 뒤 별도 작업이다. 이 문서 자체는 DB에 아무것도
쓰지 않았다(읽기 전용 조사).

**확인한 것 vs 지어내지 않은 것**
- DB 실측: `games` 23행 전체, `game_performance` 6행 전체, `product_specs`(GPU
  `vram_gb`/`required_power_watt`, CPU `cpu_cores`, RAM/SSD `capacity_gb` 분포),
  `grid_cells`(112행 스키마·값), `usage_tier_rules`/`usage_alloc`/`ai_workloads` 스키마와
  로더 코드(`api/usage_tier_rules.py`, `api/candidates.py`, `api/recommend.py`,
  `tools/grid_generate.py`, `api/grid_public.py`, `api/grid_workstations.py`,
  `api/admin_game_matrix.py`)를 전부 읽었다.
- 게임 23종 중 **6종만 문서 근거로 확정 배정**했다. 나머지는 "불확실"로 남겼다 —
  근거 없이 등급을 채우면 A-135가 요구한 "지어내지 말 것"을 어긴다.
- GPU 전력(`gpu_watt_min`) 값은 원본 문서가 숫자로 주지 않아서, **원본 문서가 지목한
  대표 GPU 모델명을 재고 `product_specs.required_power_watt`에 대조해 실측**했다(방법론은
  §1-3에 명시). 지어낸 숫자가 아니라 재고 실측치다.

---

## [1] `spec_tiers` — T0~T5 스펙 하한 테이블

### 1-1. 설계 근거 (원본 문서 §2 표 그대로)

| 티어 | popcorn_name(A-135 매핑) | 성격 | GPU(원본 문서 표기) | CPU | RAM | 저장장치 |
|---|---|---|---|---|---|---|
| T0 | 팝콘3 | 사무·웹 | 내장그래픽(별도 그래픽카드 불필요) | 6코어 | 16GB | NVMe 512GB |
| T1 | 팝콘5 | 입문 | RTX 5060 / RX 9060 XT 8GB / Arc B580 | 6–8코어 | 16–32GB | NVMe 1TB |
| T2 | 팝콘7 | 주력 | RTX 5060 Ti 16GB / RTX 5070 12GB / RX 9070 | 8코어 | 32GB | NVMe 1–2TB |
| T3 | 팝콘7+ | 고성능 | RTX 5070 Ti 16GB / RX 9070 XT 16GB | 8–12코어 | 32–64GB | NVMe 2TB |
| T4 | 팝콘9 | 상급 | RTX 5080 16GB | 12–16코어 | 64GB | NVMe 2TB+, 1000W급 |
| T5 | 팝콘X | 워크스테이션 | RTX 5090 32GB(필요시 2장) | 16코어+ | 128GB | NVMe 4TB(3–5GB/s 지속), 1200W+ |

popcorn_name 매핑은 원본이 아니라 **A-135 확정 그대로**(decision-log 7295행) —
"팝콘5+ 는 없어진다", "가격 구간 서열이 아니라 스펙 서열"이라는 경고를 그대로 지켰다.

### 1-2. 각 필드를 어떻게 숫자로 만들었나 — 방법론

원본 문서는 범위("6–8코어", "16–32GB")로 적었다. 컬럼은 **하한 하나만** 가져야 하므로
(usage_tier_rules 와 동일한 "gte" 철학), **각 범위의 최솟값**을 그 티어의 하한으로 썼다.
근거: 이 컬럼은 "이 티어에 들어오려면 최소 이 정도"를 말하는 진입 조건이지, 그 티어의
전형값이 아니다. T1의 CPU를 "8코어"로 넣으면 6코어 CPU를 쓴 실제 T1급 구성이 엔진에서
탈락한다 — 그건 원본 문서가 준 "6–8코어" 범위의 절반을 지어서 버리는 것과 같다.

`gpu_watt_min`은 원본 문서에 숫자가 없다(모델명만 있다). 그래서 원본이 지목한 **대표
GPU 모델명을 재고 DB에서 검색해 `required_power_watt`를 실측**했다(2026-09-14 조회):

| 티어 | 원본 문서 대표 GPU | 재고 실측 `required_power_watt` (표본 n) |
|---|---|---|
| T1 | RTX 5060 / RX 9060 XT 8GB / Arc B580 | 5060=550W(n=85), 9060 XT=550W(n=33). **Arc B580은 재고 GPU 2,488건 중 `required_power_watt`가 전부 NULL — 실측 불가, 지어내지 않음.** |
| T2 | RTX 5060 Ti 16GB / RTX 5070 12GB / RX 9070 | 5060 Ti=600W(n=139, 이 티어의 최저), 5070=650W(n=85), RX 9070=700W(n=16) |
| T3 | RTX 5070 Ti 16GB / RX 9070 XT 16GB | 5070 Ti=750W(n=91), RX 9070 XT=750W(n=36) — 일치 |
| T4 | RTX 5080 16GB | 850W(n=92, 값 하나로 고정) |
| T5 | RTX 5090 32GB | 1000W(n=52, 값 하나로 고정) |

각 티어의 `gpu_watt_min`은 **그 티어 최저 모델의 실측값**으로 잡았다(T2는 5060 Ti의
600W — "이 티어에 들어오는 가장 가벼운 카드도 최소 이만큼은 요구한다"는 하한 철학과 맞음).
T0는 GPU 자체가 없으므로 NULL(§1-3 참조).

**왜 `gpu_watt_min`이 별도 컬럼으로 필요한가 — VRAM만으로는 T3·T4를 못 가른다.**
원본 문서에서 T3과 T4는 **둘 다 VRAM 16GB**다(RTX 5070 Ti/RX 9070 XT 16GB vs RTX 5080
16GB). `gpu_vram_min_gb`만 하한으로 걸면 T4 규칙이 "16GB 이상"이 되어 T3급 카드도
통과해 버린다 — 두 티어가 사실상 같은 필터가 된다. `required_power_watt`가 재고에서
5070 Ti/9070 XT=750W, 5080=850W로 갈라지므로(§표 참조), `gpu_watt_min`을 함께 거는 것이
**우리 재고 스키마 안에서 T3·T4를 실제로 구분할 수 있는 유일한 수단**이다(성능 벤치마크
등급 컬럼이 없다는 것은 `docs/design/prebuilt-grid-benchmark-2026-09-07.md`·
`game_db_load` 계열 문서가 이미 인정한 v1 한계 — "가격을 사양 근사로 사용"과 같은 종류의
타협이다). 이 설계는 그 한계를 인정하고 VRAM+전력 두 축으로 근사한다.

`ssd_min_gb` 값은 원본 "4TB"를 그대로 옮겼는데, 재고 `capacity_gb` 분포에 `3932`와
`4096`이 둘 다 있다(§표 상단 실측). 4000GB로 하한을 걸면 정확히 3932GB 짜리 "4TB" 표기
제품이 하한에 탈락할 수 있다 — 이 불일치는 §1-4에 별도로 남긴다.

### 1-3. T0 GPU 하한 — NULL이냐 0이냐 (원본 문서 "별도 그래픽카드가 불필요")

**NULL로 둔다.** 이유:

1. **0은 "VRAM 0GB인 GPU가 있다"는 거짓 주장이 된다.** T0는 GPU 슬롯 자체가 없어도
   되는 티어다(내장그래픽). `gpu_vram_min_gb = 0`으로 쓰면 "GPU가 있고 그 VRAM이
   0GB 이상이면 통과"라는 규칙이 되어, 실제로는 "GPU가 없어도 된다"는 사실과 다른
   의미가 된다.
2. **`usage_tier_rules.passes()`의 NULL 불통과 원칙과 충돌하지 않는다** —
   `api/usage_tier_rules.py` 96~118행 `passes()`를 실측 확인: `v = part.get(field)`가
   None이면 즉시 `return False`(그 부품이 불통과)다. 이 원칙은 **"부품의 사양 값이
   NULL이면 그 부품을 신뢰 못 한다"**는 뜻이지, "T0 하한 자체가 NULL이면 모든 GPU가
   불통과한다"는 뜻이 아니다. 엔진이 `spec_tiers.gpu_vram_min_gb`(NULL)를 규칙 값
   `val`로 쓰려면 애초에 **"NULL이면 그 슬롯에 규칙을 걸지 않는다"**로 해석해야 한다
   (`usage_tier_rules.for_usage()`가 규칙이 없는 슬롯은 아예 딕셔너리에 안 넣는 것과
   같은 패턴 — 규칙 부재 ≠ 규칙 불통과).
3. **현재 엔진 아키텍처가 GPU 슬롯을 필수로 요구한다는 점은 별개 문제로 남는다.**
   `api/taxonomy.py` `SLOTS = ["CPU","MB","RAM","GPU","CASE","COOLER","POWER","SSD"]`는
   GPU를 견적 필수 8슬롯 중 하나로 고정해 뒀다. `usage_alloc`(0086) 마이그레이션도
   이미 이 충돌을 알고 있다 — "office" 용도 GPU 배분을 `(0.00, 0.15)`로 낮춰만 뒀지
   슬롯 자체를 빼지는 못했다(주석 원문: *"사무 GPU 9%(n=1)·iGPU 97% — GPU 슬롯 필수인
   현 엔진에선 최저가로"*). **T0에 `gpu_vram_min_gb=NULL`을 거는 것과, 엔진이 GPU
   슬롯을 아예 생략하게 만드는 것은 다른 작업이다.** 전자는 이 문서 §1이 하는 일(하한
   테이블 설계)이고, 후자는 `taxonomy.SLOTS`·`recommend._build_set` 수준의 변경이라
   §4(엔진 연결) 논의로 넘긴다 — **범위 밖, 별도 결정 필요**로 명시해 둔다.

### 1-4. DDL — `spec_tiers`

```sql
CREATE TABLE spec_tiers (
    tier_key         VARCHAR(4)   PRIMARY KEY,   -- 'T0'..'T5'
    popcorn_name     VARCHAR(12)  NOT NULL UNIQUE, -- '팝콘3'..'팝콘X' (A-135 매핑, 팝콘5+ 없음)
    label            VARCHAR(20)  NOT NULL,       -- 원본 문서 §2 "성격" 열 그대로
    gpu_vram_min_gb  INTEGER,                     -- NULL = GPU 하한 없음(T0 전용, §1-3 근거)
    gpu_watt_min     INTEGER,                     -- 재고 실측(§1-2 표). T0만 NULL.
    cpu_cores_min    INTEGER      NOT NULL,
    ram_min_gb       INTEGER      NOT NULL,
    ssd_min_gb       INTEGER      NOT NULL,
    sort_order       INTEGER      NOT NULL UNIQUE,
    note             TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_spec_tiers_t0_gpu_null
        CHECK (tier_key <> 'T0' OR (gpu_vram_min_gb IS NULL AND gpu_watt_min IS NULL))
);

COMMENT ON TABLE spec_tiers IS
  '스펙 하한 T0~T5(A-135) — 원본 docs/design/spec-tier-source-2026-09-14.md §2. '
  '가격은 이 하한을 만족하는 조합의 결과이지 사전 정의가 아니다(A-135 뒤집음: 격자 티어는 '
  '더 이상 가격 구간이 아니다). T0.gpu_vram_min_gb=NULL 은 "GPU 규칙 없음"이지 0GB 통과가 아니다.';

COMMENT ON COLUMN spec_tiers.gpu_vram_min_gb IS
  'NULL=이 티어는 GPU VRAM 하한을 걸지 않는다(T0 전용). 0으로 쓰지 않는다 — 0은 '
  '"VRAM 0GB 카드가 있다"는 거짓 주장이 된다(설계 근거 §1-3).';
```

### 1-5. INSERT — `spec_tiers` 6행

```sql
INSERT INTO spec_tiers
  (tier_key, popcorn_name, label, gpu_vram_min_gb, gpu_watt_min, cpu_cores_min, ram_min_gb, ssd_min_gb, sort_order, note)
VALUES
  ('T0', '팝콘3', '사무·웹',
   NULL, NULL, 6, 16, 512, 0,
   '원본 §2: "별도 그래픽카드가 불필요하다". GPU 하한 NULL(§1-3). 현재 엔진(taxonomy.SLOTS)은 '
   'GPU 슬롯을 필수로 요구해 T0 실현에는 별도 엔진 변경이 필요하다(범위 밖, §4 참조).'),
  ('T1', '팝콘5', '입문',
   8, 550, 6, 16, 1000, 1,
   '원본 §2 "RTX 5060/RX 9060 XT 8GB/Arc B580". gpu_watt_min=550W는 5060·9060 XT 재고 실측 '
   '(n=85,33 각각 550W 단일값). Arc B580은 재고 2,488건 중 required_power_watt 전부 NULL — '
   '실측 불가. CPU·RAM 은 원본 범위(6–8코어·16–32GB)의 하한값.'),
  ('T2', '팝콘7', '주력',
   12, 600, 8, 32, 1000, 2,
   '원본 §2 "RTX 5060 Ti 16GB/RTX 5070 12GB/RX 9070". VRAM 하한은 세 모델 중 최소값(5070 '
   '12GB) 채택 — 5060 Ti 16GB·RX 9070 16GB 는 VRAM 이 이미 T2 진입선을 넘는 상위 스펙이라 '
   'value 로 쓰면 티어 진입점을 과대평가한다. gpu_watt_min=600W 는 5060 Ti 실측(n=139, 최저 '
   '전력 모델).'),
  ('T3', '팝콘7+', '고성능',
   16, 750, 8, 32, 2000, 3,
   '원본 §2 "RTX 5070 Ti 16GB/RX 9070 XT 16GB". gpu_watt_min=750W 는 두 모델 실측 일치(n=91, '
   '36). VRAM 16GB 가 T4 와 같은 값이라 gpu_watt_min 이 실질적 구분축이다(§1-2 근거).'),
  ('T4', '팝콘9', '상급',
   16, 850, 12, 64, 2000, 4,
   '원본 §2 "RTX 5080 16GB". gpu_watt_min=850W 재고 실측 고정값(n=92). CPU·RAM 은 원본 범위 '
   '(12–16코어·64GB)의 하한값. AI 목적이면 원본 §2 "AI가 주 목적이면 T4를 건너뛰고 T5로"라는 '
   '경고가 있다 — 이 티어는 게임/영상 축 기준의 하한이다.'),
  ('T5', '팝콘X', '워크스테이션',
   32, 1000, 16, 128, 4000, 5,
   '원본 §2 "RTX 5090 32GB(필요시 2장)". gpu_watt_min=1000W 재고 실측 고정값(n=52). '
   'ssd_min_gb=4000 은 원본 "NVMe 4TB"를 그대로 옮겼으나, 재고 SSD capacity_gb 실측에 3932 '
   'GB 와 4096GB 가 둘 다 있어(§1-2) 4TB 라벨 제품 일부가 4000 하한에 탈락할 수 있다 — '
   '엔진 구현 시 3932 를 포함하려면 하한을 3900 대로 낮추는 결정이 별도 필요(이 문서는 '
   '원본 표기를 지어내지 않고 그대로 옮긴다).');
```

---

## [2] 게임 5등급 매핑 — `game_load_grades` + 등급×해상도→티어 + `games` 23종 분류

### 2-1. `game_load_grades` — 원본 문서 §3 표 그대로

원본은 6가지 열(부하 등급·대표 타이틀·1080p·1440p·4K)이지만, "등급 자체의 정의"와
"등급×해상도→티어 매핑"은 성격이 다른 정보라 테이블을 분리한다(요청 스펙대로
`game_load_grades` + 별도 매핑표).

```sql
CREATE TABLE game_load_grades (
    grade          VARCHAR(1)   PRIMARY KEY,   -- E/A/B/C/S
    label          VARCHAR(40)  NOT NULL,      -- 원본 §3 "부하 등급" 열 그대로
    example_titles TEXT         NOT NULL,       -- 원본 §3 "대표 타이틀" 열 그대로(쉼표 구분)
    note           TEXT,
    sort_order     INTEGER      NOT NULL UNIQUE
);

COMMENT ON TABLE game_load_grades IS
  '게임 부하 등급 E/A/B/C/S(원본 §3) — "게임은 제목별로 나누지 않는다"는 원본 원칙(§1) 그대로, '
  '개별 게임이 아니라 부하 성격으로 묶는다. 대표 타이틀은 예시이지 전체 목록이 아니다.';
```

```sql
INSERT INTO game_load_grades (grade, label, example_titles, note, sort_order) VALUES
  ('E', '경쟁 이스포츠',
   '발로란트, CS2, 리그 오브 레전드, 오버워치, 에이펙스',
   '기준: 60fps 이상·업스케일링 없음(원본 §3 머리말). 1080p 144fps+.', 1),
  ('A', '일반 AAA(래스터)',
   '어쌔신 크리드 섀도우스, 스파이더맨, 호라이즌',
   'VRAM 3단 계단의 기준 등급 — 1080p 8GB·1440p 12GB·4K 16GB(원본 §3 "읽는 기준선").', 2),
  ('B', 'RT 적용 AAA',
   '스타워즈 아웃로스, 몬스터헌터 와일즈',
   '4K는 업스케일링 사실상 필수(원본 §3).', 3),
  ('C', '패스트레이싱·UE5 극한',
   '사이버펑크 2077 RT 오버드라이브, 앨런 웨이크 2, 검은 신화: 오공, 아바타',
   '4K는 프레임 생성 없이 60fps 불가(원본 §3). 업스케일링으로 등급을 낮추는 근거로 쓰기엔 '
   '위험하다는 원본 경고 있음.', 4),
  ('S', 'CPU 바운드 시뮬레이션',
   'MS 플라이트 시뮬레이터, 시티즈: 스카이라인 II, 대규모 전략·경영 시뮬',
   'GPU/CPU 비대칭 편성(원본 §3): GPU 는 T2급, CPU 는 T4급이 정답 — GPU 에 예산을 몰면 '
   '성능이 개선되지 않는다. 해상도별 표가 없다(원본 표에 1080p/1440p/4K 칸이 비어 있음, '
   '아래 매핑표에서 S 는 GPU/CPU 를 분리해 표기).', 5);
```

### 2-2. 등급×해상도 → `spec_tiers.tier_key` 매핑표

**원본 문서는 T1~T5 다섯 단계 체계로 적혀 있다**(원본 §2가 당시엔 T0~T5 6단계였지만
§3의 게임 표는 T1부터 시작 — T0/사무 등급은 게임 축에 해당 사항 없음). A-135 재정의
이후에도 **T0~T5 6단계 tier_key 자체는 이미 §1에서 정의**했으므로, 이 매핑표는 그
tier_key를 그대로 참조하고 원본 §3 표의 값(T1~T5)을 손대지 않고 옮긴다 — "6개 T
순서에 맞게 재량하라"는 지시는 **tier_key 어휘를 새로 만들라는 뜻이 아니라, 이미 있는
T0~T5 중 원본이 준 T1~T5 값을 그대로 채우고 T0(사무)는 게임 축에 해당 없음으로 비워
두라는 뜻**으로 해석했다 — 원본이 준 티어 번호를 위·아래로 옮기면 그게 바로 지어내는
것이기 때문이다.

S등급은 GPU/CPU 티어가 다른 **비대칭 등급**이라 `spec_tiers.tier_key` 하나로 못 담는다
(원본 §3: "GPU는 T2, CPU는 T4급으로 비대칭 편성"). 그래서 매핑표에 `gpu_tier_key`·
`cpu_tier_key_override` 두 컬럼을 둔다 — E/A/B/C는 `cpu_tier_key_override`가 NULL이면
"CPU도 gpu_tier_key와 같다"는 뜻이고, S만 이 컬럼을 채운다.

```sql
CREATE TABLE game_grade_resolution_tiers (
    grade               VARCHAR(1)  NOT NULL REFERENCES game_load_grades(grade),
    resolution          VARCHAR(6)  NOT NULL,   -- '1080p' | '1440p' | '4K'
    gpu_tier_key        VARCHAR(4)  NOT NULL REFERENCES spec_tiers(tier_key),
    cpu_tier_key_override VARCHAR(4) REFERENCES spec_tiers(tier_key),  -- S등급 전용, 그 외 NULL
    note                TEXT,
    PRIMARY KEY (grade, resolution)
);

COMMENT ON TABLE game_grade_resolution_tiers IS
  '게임 부하등급×해상도 → 스펙 티어(원본 §3 표). S등급은 GPU/CPU 비대칭이라 '
  'cpu_tier_key_override 로 별도 표기(원본: GPU T2급/CPU T4급). 나머지 등급은 override NULL '
  '= CPU 도 gpu_tier_key 와 같다.';
```

```sql
INSERT INTO game_grade_resolution_tiers (grade, resolution, gpu_tier_key, cpu_tier_key_override, note) VALUES
  ('E', '1080p', 'T1', NULL, '144fps+ 목표(원본 §3)'),
  ('E', '1440p', 'T1', NULL, '240fps 목표 시 T2 로 올린다(원본 §3 "T1–T2" 병기) — 이 행은 '
                             '기본값 T1, 240fps 목표는 개별 판단으로 T2 승급'),
  ('E', '4K',    'T2', NULL, NULL),
  ('A', '1080p', 'T1', NULL, 'VRAM 8GB(원본 §3)'),
  ('A', '1440p', 'T2', NULL, 'VRAM 12GB(원본 §3)'),
  ('A', '4K',    'T3', NULL, 'VRAM 16GB(원본 §3)'),
  ('B', '1080p', 'T2', NULL, NULL),
  ('B', '1440p', 'T3', NULL, NULL),
  ('B', '4K',    'T4', NULL, '업스케일링 사실상 필수(원본 §3)'),
  ('C', '1080p', 'T3', NULL, NULL),
  ('C', '1440p', 'T4', NULL, NULL),
  ('C', '4K',    'T5', NULL, '프레임 생성 없이는 60fps 불가(원본 §3)'),
  ('S', '1080p', 'T2', 'T4', 'GPU T2급/CPU T4급 비대칭(원본 §3) — 해상도 무관, 단일 사양 '
                             '행을 1080p/1440p/4K 세 해상도에 동일 적용(원본 표에 해상도별 '
                             '구분 없음, 지어내지 않음)'),
  ('S', '1440p', 'T2', 'T4', '위와 동일'),
  ('S', '4K',    'T2', 'T4', '위와 동일');
```

### 2-3. 재고 `games` 23행 매핑 — 확정 6 / 불확실 17

방법: 각 게임의 `rec_gpu`(재고 DB 실측값)를 원본 문서 §3 대표 타이틀 예시·해상도별
VRAM 기준선("8GB=1080p 하한, 12GB=1440p, 16GB=4K/RT")과 대조했다. **원본 §3 대표
타이틀 목록에 이름이 직접 있는 경우만 "확정"으로 표시**했고, 이름이 없으면
`rec_gpu`가 아무리 명확해도 "불확실"로 남겼다 — genre·사양만으로 등급을 추론하는 것은
원본이 명시한 대표 타이틀과 다른 방식의 판단이라 A-135 "지어내지 말 것" 원칙에 어긋난다.

| game_id | name | genre | rec_gpu(재고 실측) | 판정 | 근거 |
|---|---|---|---|---|---|
| 4 | 발로란트 | FPS | GeForce GT 730 / Radeon R7 240 | **E (확정)** | 원본 §3 E등급 대표 타이틀에 "발로란트" 직접 등재 |
| 1 | 리그 오브 레전드 | MOBA | GeForce 560 / Radeon HD 6950 | **E (확정)** | 원본 §3 E등급 대표 타이틀에 "리그 오브 레전드" 직접 등재 |
| 12 | 사이버펑크2077 | 오픈월드RPG | RTX 2060 SUPER / RX 5700 XT / Arc A770 | **C (확정)** | 원본 §3 C등급 대표 타이틀에 "사이버펑크 2077 RT 오버드라이브" 등재. ⚠ 단, `games.rec_gpu`는 RT 오버드라이브 프리셋이 아닌 일반 권장사양 — 원본이 지목한 것은 특정 RT 프리셋이라 **같은 게임이라도 그래픽 옵션에 따라 등급이 달라질 수 있다**(일반 옵션은 A/B급에 더 가까울 수 있음, 원본 텍스트상 게임 자체가 C 대표로 명시됐으므로 C로 확정하되 이 단서를 note에 남긴다) |
| 14 | 몬스터헌터 와일즈 | 액션RPG | RTX 2060 Super(VRAM 8GB) / RX 6600(VRAM 8GB) | **B (확정)** | 원본 §3 B등급 대표 타이틀에 "몬스터헌터 와일즈" 직접 등재 |
| 16 | 검은신화 오공 | 액션RPG | RTX 2060 / RX 5700 XT / Arc A750 | **C (확정)** | 원본 §3 C등급 대표 타이틀에 "검은 신화: 오공" 직접 등재 |
| 5 | 오버워치2 | FPS | GTX 1060/1650 / R9 380 / RX 6400 / Arc A770 | **E (확정)** | 원본 §3 E등급 대표 타이틀에 "오버워치" 등재(원본은 시리즈명, 재고는 "오버워치2" — 같은 프랜차이즈로 판단) |

**불확실 17종** (원본 대표 타이틀 목록에 이름이 없어 등급 미배정 — genre·rec_gpu 참고만 병기):

| game_id | name | genre | rec_gpu(재고) | 참고(등급 배정 아님) |
|---|---|---|---|---|
| 2 | FC온라인 | 스포츠 | GTX 460 / HD 6870 | rec_gpu가 매우 낮아 E급과 유사한 부하로 보이나, 원본은 스포츠 장르 예시가 없다 |
| 3 | 서든어택 | FPS | GeForce 9600GT | FPS 장르지만 원본 대표 타이틀 목록에 없음(구형 게임이라 부하 자체가 원본 체계 밖) |
| 6 | 로스트아크 | MMORPG | GTX 1660 Super / RX 6600 | 원본에 MMORPG 대표 타이틀 없음 |
| 7 | 메이플스토리 | MMORPG | GT 430 / HD 5670 | 위와 동일 |
| 8 | 던전앤파이터 | 액션RPG | GTX 1050 Ti / RX 580 | 원본 액션RPG 예시(몬스터헌터 와일즈=B)와 부하대가 다름, 직접 언급 없음 |
| 9 | 디아블로4 | 액션RPG | GTX 970 / Arc A750 / RX 470 | 원본에 디아블로 시리즈 언급 없음 |
| 10 | 패스 오브 엑자일2 | 액션RPG | RTX 2060 / Arc A770 / RX 5600 XT | 원본에 언급 없음 |
| 11 | 배틀그라운드 | 배틀로얄 | GTX 1060 3GB / RX 580 4GB | 원본에 배틀로얄 장르·타이틀 예시 없음 |
| 13 | 붉은사막 | 오픈월드액션 | RX 6700 XT / RTX 2080 | rec_gpu가 B등급대(RT 적용 AAA)와 근접하나 원본이 이 게임을 직접 언급하지 않음, RT 사용 여부도 불명 |
| 15 | 스텔라 블레이드 | 액션 | RTX 2060 SUPER / RX 5700 XT | rec_gpu가 B/C등급 근처 값이나 원본 미언급 |
| 17 | GTA | 오픈월드액션 | (요구사양 미공개) | rec_gpu 데이터 자체가 없음 — 판정 불가 |
| 18 | 콜 오브 듀티 | FPS | RTX 3060 / RX 6600XT / Arc B580 | 원본 FPS 예시(발로란트·CS2 등)는 전부 이스포츠 경량 타이틀 — 콜 오브 듀티는 그 범주와 다른 부하대이나 원본이 AAA FPS 예시를 별도로 주지 않음 |
| 19 | 아크 서바이벌 | 서바이벌 | RX 6800 / RTX 3080 | rec_gpu가 상당히 높으나(C급 근접) 원본에 서바이벌 장르 예시 없음 |
| 20 | 헬다이버즈2 | 협동슈팅 | RTX 2060 / RX 6600XT | 원본에 언급 없음 |
| 21 | 로블록스 | 샌드박스 | (요구사양 최소치만 공개, rec 없음) | 원본의 5개 등급 어디에도 정확히 맞지 않는 경량 캐주얼 범주 — 원본이 다루지 않음 |
| 22 | 마인크래프트 | 샌드박스 | RTX 2060 / RX 5600 XT / Arc A580 | 기본 실행은 매우 가볍고 셰이더/모드팩은 무거움 — 단일 등급으로 답할 수 없음(원본도 이런 가변 워크로드를 다루지 않음) |
| 23 | 스팀 인디(통칭) | 인디(통칭) | (게임사 특정 없음) | 장르 통칭이라 개별 게임이 아님 — 애초에 등급 매핑 대상이 아니다 |

```sql
CREATE TABLE game_grade_assignments (
    game_id      INTEGER     PRIMARY KEY REFERENCES games(game_id),
    grade        VARCHAR(1)  REFERENCES game_load_grades(grade),  -- NULL = 불확실(미배정)
    is_confirmed BOOLEAN     NOT NULL,
    basis        VARCHAR(20) NOT NULL,  -- 'doc_example_title' | 'uncertain'
    note         TEXT        NOT NULL,
    assigned_date DATE       NOT NULL DEFAULT CURRENT_DATE
);

COMMENT ON TABLE game_grade_assignments IS
  '재고 games 23행 → game_load_grades 매핑. is_confirmed=true 는 원본 문서 §3 대표 '
  '타이틀 목록에 게임명이 직접 등재된 경우만(6건). 나머지 17건은 grade=NULL·'
  'is_confirmed=false·basis=uncertain — genre/rec_gpu 참고값은 note 에만 남기고 '
  '등급을 강제 배정하지 않는다(A-135 "지어내지 말 것", 23개 전부 강제 배정 금지 지시).';
```

```sql
-- 확정 6건
INSERT INTO game_grade_assignments (game_id, grade, is_confirmed, basis, note) VALUES
  (4,  'E', true, 'doc_example_title', '원본 §3 E등급 대표 타이틀에 "발로란트" 직접 등재'),
  (1,  'E', true, 'doc_example_title', '원본 §3 E등급 대표 타이틀에 "리그 오브 레전드" 직접 등재'),
  (5,  'E', true, 'doc_example_title', '원본 §3 E등급 대표 타이틀 "오버워치"(시리즈명) — 재고는 "오버워치2"'),
  (14, 'B', true, 'doc_example_title', '원본 §3 B등급 대표 타이틀에 "몬스터헌터 와일즈" 직접 등재'),
  (12, 'C', true, 'doc_example_title', '원본 §3 C등급 대표 타이틀 "사이버펑크 2077 RT 오버드라이브" 등재. '
                                        '⚠ games.rec_gpu는 일반 권장사양(RTX 2060 SUPER)이라 원본이 '
                                        '지목한 RT 오버드라이브 프리셋과 다르다 — 그래픽 옵션에 따라 '
                                        '실제 요구 등급은 낮아질 수 있음, 게임 자체는 원본 명시 타이틀이라 C 확정'),
  (16, 'C', true, 'doc_example_title', '원본 §3 C등급 대표 타이틀에 "검은 신화: 오공" 직접 등재');

-- 불확실 17건(grade=NULL) — game_id 2,3,6,7,8,9,10,11,13,15,17,18,19,20,21,22,23
INSERT INTO game_grade_assignments (game_id, grade, is_confirmed, basis, note) VALUES
  (2,  NULL, false, 'uncertain', '스포츠 장르, 원본에 스포츠 대표 타이틀 없음. rec_gpu(GTX460/HD6870) 매우 낮음(E급과 유사한 부하로 추정되나 확정 불가)'),
  (3,  NULL, false, 'uncertain', 'FPS 이지만 원본 FPS 예시(발로란트·CS2 등)와 다른 부하대(구형 게임), 미언급'),
  (6,  NULL, false, 'uncertain', 'MMORPG, 원본에 MMORPG 대표 타이틀 없음'),
  (7,  NULL, false, 'uncertain', 'MMORPG, 원본에 MMORPG 대표 타이틀 없음(구형 게임)'),
  (8,  NULL, false, 'uncertain', '액션RPG, 원본 액션RPG 예시(몬스터헌터 와일즈=B)와 부하대 다름, 미언급'),
  (9,  NULL, false, 'uncertain', '액션RPG, 원본에 디아블로 시리즈 언급 없음'),
  (10, NULL, false, 'uncertain', '액션RPG, 원본에 언급 없음'),
  (11, NULL, false, 'uncertain', '배틀로얄, 원본에 배틀로얄 장르·타이틀 예시 없음'),
  (13, NULL, false, 'uncertain', '오픈월드액션, rec_gpu(RTX2080)가 B급대에 근접하나 RT 사용 여부 불명, 원본 미언급'),
  (15, NULL, false, 'uncertain', '액션, rec_gpu(RTX2060S)가 B/C급대 근접값이나 원본 미언급'),
  (17, NULL, false, 'uncertain', '요구사양 미공개(games.rec_gpu 등 전부 NULL) — 판정 불가'),
  (18, NULL, false, 'uncertain', 'FPS 이지만 원본 FPS 예시는 이스포츠 경량 타이틀뿐, AAA FPS 예시 없음'),
  (19, NULL, false, 'uncertain', '서바이벌, rec_gpu(RTX3080)가 상당히 높으나(C급 근접) 원본에 서바이벌 예시 없음'),
  (20, NULL, false, 'uncertain', '협동슈팅, 원본에 언급 없음'),
  (21, NULL, false, 'uncertain', '샌드박스, rec_gpu 데이터 자체 없음(min만 공개) — 원본 5등급 밖의 경량 캐주얼 범주로 추정'),
  (22, NULL, false, 'uncertain', '샌드박스, 기본 실행은 매우 가볍고 셰이더/모드팩은 무거움 — 단일 등급 불가, 원본도 이런 가변 워크로드는 다루지 않음'),
  (23, NULL, false, 'uncertain', '장르 통칭(개별 게임 아님) — 애초에 등급 매핑 대상이 아니다');
```

---

## [3] 영상편집 코덱 4계열 — `video_codec_tiers` + 효과가산

### 3-1. DDL — `video_codec_tiers` (원본 §4 표 그대로)

```sql
CREATE TABLE video_codec_tiers (
    codec_group   INTEGER      NOT NULL,          -- 1~4
    label         VARCHAR(60)  NOT NULL,           -- 원본 §4 "코덱 계열" 열
    resolution    VARCHAR(8)   NOT NULL,           -- '1080p' | '4K' | '6-8K'
    spec_tier_key VARCHAR(4)   NOT NULL REFERENCES spec_tiers(tier_key),
    effect_note   TEXT,                            -- 그 칸 고유의 부가 요건(원본 §4 표 각주)
    note          TEXT,
    PRIMARY KEY (codec_group, resolution)
);

COMMENT ON TABLE video_codec_tiers IS
  '영상편집 코덱 4계열 × 해상도 → 스펙 티어(원본 §4, 컷편집 기준). effect_tier_bump=true '
  '규칙과 함께 읽는다 — 노이즈리덕션/합성/멀티캠/그레이딩이 있으면 이 표의 spec_tier_key '
  '보다 한 티어 위를 적용한다(§3-2).';
```

### 3-2. INSERT — 12행 (4계열 × 3해상도)

```sql
INSERT INTO video_codec_tiers (codec_group, label, resolution, spec_tier_key, effect_note, note) VALUES
  (1, '롱GOP 촬영 코덱(H.264/HEVC)', '1080p',  'T1', NULL,
     '압축률이 높아 디코딩이 무겁다(원본 §4)'),
  (1, '롱GOP 촬영 코덱(H.264/HEVC)', '4K',     'T2', '하드웨어 디코드 필수', NULL),
  (1, '롱GOP 촬영 코덱(H.264/HEVC)', '6-8K',   'T3', '프록시 권장', NULL),

  (2, '10bit 4:2:2 · AV1', '1080p', 'T2', NULL,
     'AV1 하드웨어 디코드 유무가 체감을 가른다(원본 §4)'),
  (2, '10bit 4:2:2 · AV1', '4K',    'T3', NULL, NULL),
  (2, '10bit 4:2:2 · AV1', '6-8K',  'T4', NULL, NULL),

  (3, '중간코덱(ProRes, DNxHR)', '1080p', 'T1', NULL,
     '디코딩은 가볍지만 용량과 대역폭이 크다(원본 §4)'),
  (3, '중간코덱(ProRes, DNxHR)', '4K',    'T2', '고속 NVMe', NULL),
  (3, '중간코덱(ProRes, DNxHR)', '6-8K',  'T4', '3GB/s 지속', NULL),

  (4, 'RAW(BRAW, R3D, ARRIRAW)', '1080p', 'T2', NULL,
     '디베이어 연산이 전부 GPU로 간다(원본 §4)'),
  (4, 'RAW(BRAW, R3D, ARRIRAW)', '4K',    'T4', 'VRAM 16GB+', NULL),
  (4, 'RAW(BRAW, R3D, ARRIRAW)', '6-8K',  'T5', 'VRAM 24GB+ · RAM 128GB',
     '원본 §4 굵게 표기된 최상급 칸 — "T5" 그대로');
```

### 3-3. 효과가산(노이즈리덕션·합성·멀티캠·그레이딩) — 구현 제안

원본 §4 "효과 강도" 문단은 "해당 칸을 한 티어 올린다"고만 말한다(구체 규칙 없음).
이걸 데이터로 표현하는 방법 두 가지를 검토했다.

**방안 A(채택 제안) — 별도 규칙 테이블 + 별표 조인 시점에 +1 tier 연산.**
`video_codec_tiers` 자체에는 BOOLEAN 플래그를 두지 않는다. 이유: `effect_tier_bump`를
`video_codec_tiers` 행에 박으면 "이 코덱×해상도 칸은 항상 효과가산이 켜진 상태"라는
잘못된 의미가 된다 — 원본은 "효과가 있으면"이라는 조건부다(코덱×해상도 자체와는
독립된 축). 대신 규칙을 별도 테이블로 두고, 조회 시점에 티어를 한 칸 올리는 함수를
쓴다.

```sql
CREATE TABLE video_effect_bumps (
    effect_key   VARCHAR(20)  PRIMARY KEY,  -- 'noise_reduction_ai' | 'compositing' | 'multicam' | 'grading_only'
    label        VARCHAR(40)  NOT NULL,
    tier_bump    INTEGER      NOT NULL DEFAULT 1,  -- 원본 "한 티어 올린다" = 1
    note         TEXT         NOT NULL,
    active       BOOLEAN      NOT NULL DEFAULT TRUE
);

COMMENT ON TABLE video_effect_bumps IS
  '영상편집 효과 강도(세 번째 축, 원본 §4) — 코덱×해상도 칸의 spec_tier_key 에 이 '
  'tier_bump 만큼 sort_order 를 더해 실제 적용 티어를 구한다. grading_only 는 원본이 '
  '"본체보다 모니터·모니터링 출력 카드가 우선"이라 명시해 tier_bump=0(본체 승급 아님) '
  '으로 별도 처리.';

INSERT INTO video_effect_bumps (effect_key, label, tier_bump, note) VALUES
  ('noise_reduction_ai', '노이즈 리덕션·AI 기능(자동 자막·매직 마스크·얼굴 보정)', 1,
   '원본 §4: VRAM을 가장 빠르게 소모한다'),
  ('compositing', '합성·모션그래픽(노드/레이어)', 1,
   '원본 §4: VRAM·RAM 동시 요구, 4K 실무 RAM 64GB 권장선의 근거'),
  ('multicam', '멀티캠(동시 디코딩 스트림)', 1,
   '원본 §4: 카메라 대수만큼 미디어 엔진 부하가 곱해진다 — 대수는 이 표가 아니라 '
   '견적 입력값으로 받아야 한다(이 테이블은 "가산 여부"만, "몇 대"는 범위 밖)'),
  ('grading_only', '컬러 그레이딩 전용', 0,
   '원본 §4: "본체보다 색 정확도 모니터·모니터링 출력 카드가 우선순위" — 본체 티어를 '
   '올리는 축이 아니라 모니터/출력장비 예산을 늘리는 축이다. tier_bump=0 은 "이 본체 '
   '조견표에서는 상승 없음"을 명시하는 의도적 값이지 누락이 아니다.');
```

적용 로직(엔진 쪽, 의사코드 — §4에서 더 논의):

```
effective_sort_order = spec_tiers[video_codec_tiers[group,res].spec_tier_key].sort_order
                        + SUM(video_effect_bumps[적용된 effect_key].tier_bump)
effective_tier_key = spec_tiers WHERE sort_order = MIN(effective_sort_order, 5)  -- T5 상한 클램프
```

**왜 컬럼 하나(`effect_tier_bump BOOLEAN`)가 아니라 이 구조인가**: 원본 §4는 효과가
**네 가지이고 동시에 여러 개 겹칠 수 있다**(예: 멀티캠 + 그레이딩을 같이 하는 촬영).
불리언 한 칼럼은 "가산 여부"는 표현해도 "몇 개 겹쳤는지"·"그레이딩은 왜 안 올리는지"를
구분 못 한다. 정수 `tier_bump`를 효과별로 두고 합산하는 편이 원본의 "그레이딩은
예외"라는 조건까지 정확히 반영한다. 다만 이 방안은 `video_codec_tiers` 원본 요구
스펙(요청 문구: "effect_tier_bump BOOLEAN 등으로 표현")과 다르므로, **대안 B(요청
문구 그대로)도 함께 남긴다.**

**방안 B(요청 문구 그대로, 대안) — `video_codec_tiers`에 `effect_tier_bump BOOLEAN`
컬럼을 추가하고, 효과가 있으면 애플리케이션 레벨에서 "그 칸이 아니라 한 단계 위 칸의
행을 대신 조회"하게 만든다.** 더 단순하지만, "효과 종류가 네 가지이고 그레이딩만
예외"라는 원본의 조건부 정보를 이 테이블 하나로는 못 담아 별도 문서/주석 의존이
커진다. **조사자 제안은 방안 A** — 정보 손실이 적고, `usage_tier_rules`가 이미 쓰는
"규칙 테이블 + active 플래그" 패턴과 스타일이 맞다.

---

## [4] 엔진 연결 설계 — 예산 상한 → 스펙 하한, 가격은 결과

### 4-1. 현재 구조 실측 요약

- `grid_generate.py`는 `grid_cells.budget_min/budget_max`를 **엔진에 보낼 예산 상한
  라벨**로 변환해(`_budget_label()`) `/api/recommend`를 호출한다. 엔진(`recommend.py`)은
  `_budget_cap()`으로 **상한만** 해석하고(하한은 모른다 — 0082 머리 주석 실측
  확인), 배치가 응답 `total`을 보고 `total < budget_min`이면 실패 처리한다
  (`judge()` 173~178행). 즉 **지금도 이미 "하한은 배치가 사후 검증"하는 구조**다 —
  스펙 축으로 바뀌어도 이 패턴 자체는 재사용 가능하다.
- `usage_tier_rules`(0085)는 이미 (usage_key, budget_min) → {slot: [(field, op, value)]}
  구조이고 `op`는 gte/lte/in을 지원한다(`api/usage_tier_rules.py` 실측, `for_usage()`·
  `passes()`). **budget_min은 "이 예산 이상에서 이 규칙을 적용"이라는 트리거 키일 뿐,
  값 자체가 가격이 아니다** — 규칙의 본체(`slot/field/op/value`)는 스펙 필드(vram_gb·
  cpu_cores·capacity_gb)를 이미 gte로 표현하고 있다.

### 4-2. `usage_tier_rules` 인프라를 재사용할 수 있는가 — 가능, 조건부

**결론: 재사용 가능하다.** `spec_tiers`의 하한 필드(`gpu_vram_min_gb`,
`cpu_cores_min`, `ram_min_gb`, `ssd_min_gb`)를 `usage_tier_rules` 행으로 그대로
변환할 수 있다 — `slot/field/op/value`가 정확히 같은 어휘다:

```
spec_tiers.gpu_vram_min_gb  →  (slot='GPU', field='vram_gb',     op='gte', value=...)
spec_tiers.gpu_watt_min     →  (slot='GPU', field='required_power_watt', op='gte', value=...)
spec_tiers.cpu_cores_min    →  (slot='CPU', field='cpu_cores',    op='gte', value=...)
spec_tiers.ram_min_gb       →  (slot='RAM', field='capacity_gb',  op='gte', value=...)
spec_tiers.ssd_min_gb       →  (slot='SSD', field='capacity_gb',  op='gte', value=...)
```

**단, `usage_tier_rules`의 트리거 축(`budget_min`)이 지금은 "가격"이지만 새 방식은
"스펙 하한이 먼저"이므로 트리거 축 자체를 바꿔야 한다.** 지금 `for_usage(usage_key, cap)`은
"예산 상한 cap 아래에서 budget_min이 가장 큰 규칙"을 고른다 — **이 함수는 여전히
가격 축으로 규칙을 고른다.** 스펙이 하한이 되는 새 방식에서는 **트리거가 "고객이 고른
용도+등급/코덱"이지 "예산"이 아니다.** 즉:

- 게임: `(grade, resolution)` → `spec_tiers.tier_key`(§2-2 매핑표) → 그 tier_key의
  하한 필드들 → `usage_tier_rules` 형식의 규칙 4~5개.
- 영상편집: `(codec_group, resolution, [effects])` → `spec_tiers.tier_key`(§3-2,
  효과가산 적용 후) → 위와 동일.

이건 `usage_tier_rules` 테이블의 **컬럼 구조는 재사용하되, `for_usage()`가 규칙을
고르는 조회 키(`usage_key, budget_min` → `usage_key, tier_key`)는 바꿔야 한다**는
뜻이다. 새 메커니즘을 통째로 만들 필요는 없다 — **`usage_tier_rules`에
`tier_key VARCHAR(4) REFERENCES spec_tiers(tier_key)` 컬럼을 추가하고, 조회 함수를
`for_usage(usage_key, cap)`에서 `for_tier(usage_key, tier_key)`로 바꾸는 추가/오버로드
방식**을 제안한다. 기존 `budget_min` 트리거 방식(AI 용도·아직 안 건드리는 축)은
남겨 둘 수 있으므로 컬럼을 없애지 않고 **NULL 허용으로 추가**하는 것이 안전하다
(ai_workloads처럼 "건드리지 않는다"고 명시된 영역과의 호환 유지).

```sql
-- 제안 — 기존 usage_tier_rules 테이블에 추가(기존 행은 그대로, tier_key NULL)
ALTER TABLE usage_tier_rules
  ADD COLUMN tier_key VARCHAR(4) REFERENCES spec_tiers(tier_key);
COMMENT ON COLUMN usage_tier_rules.tier_key IS
  '스펙 하한 트리거(A-135 신규) — budget_min 대신 tier_key 로 규칙을 고르는 새 조회 경로. '
  'NULL 인 기존 행(0085~0087, AI 등 미변경 용도)은 그대로 budget_min 트리거를 쓴다. '
  '한 행에 tier_key 와 budget_min 을 동시에 채우지 않는다(트리거 축은 하나만 — CANON §1).';
```

이 접근의 근거: `usage_tier_rules.py`의 `passes()`·`items()`·`summary()`는 이미
`(field, op, value, label)` 튜플만 보고 동작해서 **트리거가 무엇이었는지 전혀 모른다**
— gte/lte/in 판정 로직을 전혀 새로 만들 필요가 없다. 바뀌는 것은 `for_usage()`
하나뿐이고, 그 함수도 새로 만들기보다 **새 함수 `for_tier()`를 나란히 추가**하면
기존 `budget_min` 경로(만약 어딘가 남겨야 한다면)를 깨지 않는다.

**T3/T4 VRAM 동률 문제가 여기서도 반복된다** — `usage_tier_rules` 규칙으로 변환해도
T3(16GB)과 T4(16GB)를 GPU VRAM 하나로는 못 가른다. `gpu_watt_min`(750 vs 850)을
반드시 함께 규칙에 실어야 한다(§1-2 근거 그대로) — 이 컬럼을 빠뜨리면 T3 규칙과 T4
규칙이 사실상 같은 필터가 되어 조용히 하나로 뭉개진다(이 저장소의 반복 사고 패턴 —
"필드 누락 → 조용한 전면 통과/불통과"와 같은 종류).

### 4-3. `grid_cells.budget_min/budget_max`의 의미 전환 — 컬럼 추가 제안(의미 재정의 아님)

**결론: 기존 컬럼의 의미를 바꾸지 않고, 새 컬럼을 추가하는 쪽을 제안한다.**

이유 — 의미를 바꾸면 깨지는 소비처가 이미 4곳 확인됐다:

1. `api/grid_public.py` `_load_tiers()`·`tier_index_for()` — 고객이 "예산 150만원"을
   말했을 때 어느 티어 카드를 보여줄지 `[budget_min, budget_max)` 반열림 구간으로
   고른다. 이건 **"고객이 말한 가격 입력을 격자 칸에 매핑하는" 화면 로직**이라 스펙이
   하한이 되어도 여전히 필요하다 — 고객은 스펙을 말하지 않고 예산이나 용도를 말한다.
2. `api/grid_workstations.py` — `THRESHOLD_TIER = "팝콘 9"`의 `budget_min`을 "AI
   워크스테이션을 보여줄 가격 문턱"으로 읽는다(`SELECT MIN(budget_min) FROM
   grid_cells WHERE tier=:t`). 이것도 고객이 말한 예산과 비교하는 용도라 그대로
   필요하다.
3. `api/admin_grid.py`·`api/admin_game_matrix.py` — 관리자 화면에 칸의 "예산 구간"을
   그대로 보여준다. 스펙 하한 체계에서도 "이 칸은 대략 얼마대"라는 안내 정보 자체는
   여전히 유용하다(사장님이 다른 지시가 없는 한 없앨 이유가 없다).
4. `tools/grid_generate.py` — `_effective_cap()`·`_budget_label()`이 `budget_max`를
   엔진 호출의 상한 라벨로 쓴다. **이 부분만 새 로직으로 완전히 대체돼야 한다** —
   새 배치는 상한을 엔진에 보내는 게 아니라 하한(스펙)을 걸고 최저가를 찾아야 한다.

**따라서 제안:**

- `grid_cells.budget_min/budget_max`는 **그대로 둔다** — 의미는 "고객에게 보여줄
  가격 구간 안내"로 유지하되, 값의 **원천이 바뀐다**: 지금은 사람이 A-129/0082에서
  미리 정한 가격 경계값을 UPDATE로 박아 넣었지만, 새 방식에서는 **배치가 스펙
  하한으로 조립한 결과 가격의 분포를 관측해 사후에 채우는 값**이 된다. 컬럼 이름과
  타입은 그대로 재사용 가능하고(정수, 원 단위), "입력 상한"에서 "결과 관측값"으로
  **역할만 바뀐다** — 이건 스키마 변경이 아니라 그 값을 채우는 배치 로직의 변경이다.
- `grid_cells.tier`(현재 "팝콘 3".."팝콘 X" 문자열)는 **`spec_tiers.popcorn_name`과
  같은 어휘라 그대로 FK로 묶을 수 있다.** 새 컬럼 `grid_cells.tier_key VARCHAR(4)
  REFERENCES spec_tiers(tier_key)`를 추가해, 배치가 "이 칸은 T3 스펙 하한을
  쓴다"는 사실을 명시적으로 갖게 한다(문자열 "팝콘 7+"만으로 연결하면 A-135가 이미
  경고한 "이름은 그대로인데 내부 로직만 바뀐다"는 함정에 다시 빠진다 — tier_key가
  단일 원천, popcorn_name은 표시용 별칭이라는 관계를 스키마로 명시해야 한다).
- 결과 가격을 기록할 자리는 **`grid_cells`가 아니라 이미 있는 `grid_quotes.total`이
  적임**이다(§배치 원장 원칙 — 0072 "UPDATE가 아니라 INSERT"). `grid_cells`는 칸
  정의(좌표)이지 결과 저장소가 아니라는 기존 설계 역할 분리를 유지하는 편이 A-135
  이전 원장 규약과 일치한다. `budget_min/budget_max`를 "결과 관측값"으로 갱신하려면
  **배치가 주기적으로 `grid_quotes.total`의 최근 분포(예: 그 칸 최근 N회 배치의
  min/max)를 `grid_cells`에 되먹임**하는 별도 집계 스텝이 필요하다 — 이건 이 문서의
  범위를 넘는 배치 설계라 **제안만 하고 구현은 별도 작업으로 남긴다.**

```sql
-- 제안 — grid_cells 확장(기존 budget_min/max 컬럼은 유지, 값의 "역할"만 문서상 재정의)
ALTER TABLE grid_cells
  ADD COLUMN tier_key VARCHAR(4) REFERENCES spec_tiers(tier_key);
COMMENT ON COLUMN grid_cells.tier_key IS
  '스펙 하한 트리거(A-135) — 이 칸이 조립 시 적용할 spec_tiers 행. grid_cells.tier '
  '(팝콘 3..팝콘 X 문자열)는 고객에게 보이는 별칭이고 tier_key 가 내부 로직의 단일 원천이다.';
COMMENT ON COLUMN grid_cells.budget_min IS
  '[A-135 이후 역할 전환] 더 이상 배치 입력 상한이 아니다 — tier_key(spec_tiers)의 '
  '하한을 만족하는 조합 중 이 칸에서 최근 관측된 결과가 최저가. 갱신은 배치 후속 '
  '집계 스텝이 담당(이 문서 범위 밖, 별도 설계 필요). 화면(grid_public 등)은 여전히 '
  '이 값을 "가격 구간 안내"로 읽는다 — 소비처를 깨지 않기 위해 컬럼/의미 큰 틀은 유지.';
COMMENT ON COLUMN grid_cells.budget_max IS
  '[A-135 이후 역할 전환] budget_min 과 동일 — 결과 관측 상단. 하한이 곧 하한이라는 '
  '원칙과 참고용 표시 구간이라는 역할이 공존한다(입력 아님).';
```

**정리 — "컬럼 추가만인지, 의미 바꿈인지"에 대한 답**: **둘 다 필요하되 순서가
다르다.** (1) `tier_key` 컬럼은 순수 추가(새 트리거 축, 기존 어떤 것도 안 건드림).
(2) `budget_min/budget_max`는 컬럼을 새로 만들지 않고 **기존 컬럼의 "채우는 방법"을
바꾼다** — 스키마 마이그레이션(ALTER)은 필요 없고, `tools/grid_generate.py`(또는
후속 신설 스크립트)가 이 두 컬럼에 쓰는 로직만 "사전 정의값 UPDATE"에서 "배치 결과
집계값 UPDATE"로 바뀐다. **단 이 역할 전환을 하기 전에 §4-2에서 지적한 4개 소비처
전부(grid_public·grid_workstations·admin_grid·admin_game_matrix)가 "이 값은 이제
결과이지 사전 정의가 아니다"라는 사실을 알고도 안전하게 동작하는지 개별 확인이
필요하다 — 특히 `grid_workstations.py`의 "가격 문턱"으로 쓰는 로직은 그 값이 매
배치마다 바뀔 수 있다는 뜻이 되어, 문턱 자체가 흔들리는 부작용이 생길 수 있다. 이건
구현 전 사장님 확인이 필요한 지점으로 남긴다.**

### 4-4. `grid_generate.py` 교체 로직 개요 (제안, 미구현)

```
for cell in grid_cells (intended_empty=false):
    tier = spec_tiers[cell.tier_key]                       # 하한 조회
    rules = usage_tier_rules.for_tier(cell.usage, tier.tier_key)  # §4-2 신설 함수
    # recommend.py 에 "예산 상한"이 아니라 "이 규칙들을 만족하는 최저가 조합을 찾아라"로 호출
    #  → 기존 recommend.py 의 tier='value'(가격 오름차순 + 첫 성립)에 rules 를
    #    usage_tier_rules 처럼 하드 필터로 얹으면 기존 DFS 를 그대로 재사용할 수 있다.
    #    즉 "가격 상한 없이 스펙 하한만 걸고 오름차순 탐색"은 지금 tier='value' 경로에
    #    cap=None 을 주고 rules 를 얹는 것과 동일한 형태 — recommend.py 자체 구조
    #    변경은 최소화된다(엔진 계약을 격자 사정으로 바꾸지 않는다는 기존 원칙 유지).
    result = recommend(usage=cell.usage, spec_rules=rules, cap=None, order='asc')
    write grid_quotes(total=result.total, ...)              # 원장 INSERT, 기존과 동일
    # 후속 집계 스텝(별도 설계) → grid_cells.budget_min/max 를 관측 결과로 UPDATE
```

이 개요가 §4-2·§4-3에서 결론 낸 두 가지(usage_tier_rules 확장 재사용 + grid_cells
컬럼 추가·역할 전환)를 실제로 어떻게 배선하는지 보여준다. **`recommend.py`의 DFS
자체(`_dfs`, `_order_of`, `_tier_sort`)는 건드리지 않아도 될 가능성이 높다** — "예산
상한 없이 가격 오름차순 + 하드 필터"는 이미 `tier='value'` 경로와 `usage_tier_rules`
하드 필터 조합으로 존재하는 패턴이라, 새 스펙 하한을 `usage_tier_rules` 형식의 규칙
행으로 변환해 넣기만 하면 기존 엔진이 그대로 소비할 가능성이 크다 — **다만 이건
설계 수준의 판단이고 실제로 `recommend.py`를 호출해 확인하지는 않았다(조사자 권한
범위 — 코드 변경·실행 없이 설계만).**

---

## 요약 — 확인법 (A-135 형식 그대로)

- `spec_tiers`·`game_load_grades`·`game_grade_resolution_tiers`·`game_grade_assignments`·
  `video_codec_tiers`·`video_effect_bumps` DDL 6종 — 이 문서 §1~§3.
- `games` 23종 매핑: 확정 6 / 불확실 17 — §2-3 표, `game_grade_assignments` INSERT.
- 엔진 연결: `usage_tier_rules`에 `tier_key` 컬럼 추가로 재사용, `grid_cells`에
  `tier_key` 컬럼 추가 + `budget_min/max` 역할 전환(스키마 불변, 채우는 로직만 교체) —
  §4.
- **미구현 상태다.** 다음 단계는 사장님이 이 설계안(특히 §1-3 NULL 결정, §2-3
  "불확실 17건" 처리 방침, §3-3 방안 A/B 선택, §4-3 "결과 관측 집계" 후속 설계)을
  확정한 뒤 실제 alembic 마이그레이션(0090+)을 만드는 것이다.
