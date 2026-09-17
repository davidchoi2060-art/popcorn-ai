"""GPU 카드 «실소비전력»(gpu_power_draw_watt) 신설 + 파워 호환 규칙 재정의.

배경 (2026-09-17 · 사장님 확정 지시)
  팝콘PC 몰에서 실제 조립돼 팔리는 완제PC 234벌을 우리 호환 규칙에 넘겨 채점했더니
  파워 규칙(rule_key='power')에서 **실판매품 9건이 탈락**했다. 우리가 틀렸다.

근본 원인
  `product_specs.required_power_watt` 한 컬럼이 **두 가지 일**을 하고 있었다.
    (1) 용도 하한(usage_floors 6행) = 성능 «등급»  (게임>=550 · 3D>=850 ...)
    (2) 호환 규칙 5번             = 카드의 «실제 전력 요구»
  그래서 RTX 3050 6GB(실TDP 70W) 59건과 RTX 3050 8GB(130W) 47건이 **둘 다 550W**로
  등록돼 있다. 외부 제원상 3050 6GB 의 제조사 최소 권장은 300W 이고, 팝콘PC 가
  500W 파워로 파는 것이 옳다. 규칙이 그걸 막고 있었다.

이 마이그레이션이 하는 일
  (1) `product_specs.gpu_power_draw_watt` 신설 — 카드 자체 소비전력(TDP/TGP/TBP).
      `required_power_watt`(등급)는 **그대로 둔다** — 용도 하한이 계속 쓴다.
  (2) `gpu_power_draw_reference` 신설 — (chipset_key, vram_gb) **복합키** 참조표 62행.
  (3) `compat_rules.ref_offset` · `compat_rules.null_ref_mode` 신설.
  (4) 규칙 5번을 `POWER.rated_watt >= GPU.gpu_power_draw_watt + 200` 으로 갈아탄다.
  (5) 추천 뷰에 새 컬럼을 싣는다(안 실으면 견적이 «조용히» 0건).
  (6) 참조표로 상품값을 백필한다(confirmed_yn=false 관례 · spec_sources='reference').

■ 왜 «기존 gpu_power_reference 확장»이 아니라 «새 표»인가 (판단 근거)
  기존 `gpu_power_reference`(39행)는 PK 가 `chipset_key` **단일키**이고, 담긴 값은
  `recommended_watt` = «시스템 권장 파워»(의도적 상향 등급값, 예: RTX 5090 -> 1000W)다.
  이 표는 `catalog_map.extract_specs()` 가 `required_power_watt`(등급)를 채우는 원천으로
  지금도 살아서 쓰이고 있다 — 그 경로를 깨면 용도 하한이 무너진다.
  새로 넣을 값은 **성격이 다르다**: 카드 소비전력이고, 같은 칩이라도 VRAM 으로 갈린다
  (실측: RTX 4060 Ti 8G=160W/16G=165W · RX 9060 XT 8G=150/16G=160 · RTX 3080 10G=320/12G=350
   · RTX 3050 6G=70/8G=130). 단일 PK 표에 컬럼만 더하면 PK 를 확장해야 하고, 그러면
  «등급» 39행이 전부 (key, NULL) 로 남아 두 의미가 한 표에서 섞인다 — 오늘 사고를 만든
  «한 컬럼이 두 가지 일을 한다»를 표 단위로 되풀이하는 것이다. 그래서 **표를 가른다.**

■ 왜 «+200W» 인가 (그리고 그 한계 — 정직 고지)
  +200W 는 **관측에서 직접 나온 수가 아니다.** 실판매 234벌의 GPU TDP 대비 파워 여유는
  최소 +400W(최소 배수 1.74x)였다 — 팝콘PC 가 애초에 여유 있게 파는 것이라 그 값을
  규칙 하한으로 삼으면 300W + RTX 3050 6GB 같은 «정상 저가형 구성»까지 막는다.
  +200W 는 「실판매를 다 통과시키면서 위험 조합은 잡는」 구간에서 고른 값이고,
  의미상 **GPU 외 시스템 전력(CPU·보드·RAM·드라이브·팬)의 보수적 정액 대체값**이다
  (카탈로그 CPU TDP 실측 489건: median 65W · p90 200W).
  검증 (조사 하네스 · D:/Hermes-Workspace/validate.py):
      +200  -> 실판매 FAIL 0/202 · 위험조합 반대시험 14/14 차단   <= 채택
      +150  -> 위험조합 1건 통과(400W + RTX 5070 250W)
      +250  -> 저가형 2건 과차단(300W + 3050 6GB · 250W + GT 710)
      x2.0  -> 실판매 7건 FAIL(1000W + RTX 5090 을 막는다)
  한계: CPU TDP 350W 급(스레드리퍼 등)에서는 +200 이 모자랄 수 있다. 3항 식
  (GPU + CPU_TDP + 120)이 이론상 더 정확하고 실판매 FAIL 도 0 이지만 규칙 엔진이
  2-슬롯 비교만 한다 — 별도 슬라이스로 분리한다.

■ 이번 범위: **일반 소비자용 GPU 만.**
  워크스테이션 계열(RTX PRO/A 시리즈 · H100)은 `gpu_chipset_key()` 인식률이 낮아
  파서 수정과 함께 다음 작업에서 다룬다. 그 결과 그 라인은 gpu_power_draw_watt 가
  NULL 로 남는데, **NULL 을 불통과로 두면 그 제품군 견적이 통째로 0이 된다** —
  그래서 규칙 5번에 `null_ref_mode='skip'`(판정 불가 = 통과도 탈락도 아님)을 붙인다.
  아래 null_ref_mode 주석 참조.

Revision ID: 0094
Revises: 0093
"""
from alembic import op

revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None


# 카드 실소비전력 근거표 — 일반 소비자용 62행.
# 출처: D:/Hermes-Workspace/gpu_power_draw_table.json (조사 서브에이전트 2026-09-17).
# 1순위였던 제조사 공식 페이지는 그 환경에서 브라우저 렌더링이 타임아웃해 열지 못했고,
# 대신 Wikipedia 의 제조사 제원 표(각 행이 NVIDIA/AMD 공식 제원을 인용)를 기계 추출했다.
# **그래서 전 행 confirmed_yn=false 로 들어간다** — 운영자 눈 교차확인 전에는 참조값이다.
# vram_gb=0 은 «VRAM 무관(칩 단일값)» 을 뜻한다 — NULL 을 쓰면 복합 PK 가 성립하지 않는다.
DRAW_ROWS = [
    # (chipset_key, vram_gb, draw_watt, confidence, source_note)
    ('RTX 5050', 8, 130, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_50_series | NVIDIA 공식 TDP 표'),
    ('RTX 5060', 8, 145, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_50_series | 동상'),
    ('RTX 5060 TI', 8, 180, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_50_series | 8G/16G 동일 180W'),
    ('RTX 5060 TI', 16, 180, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_50_series | 동상'),
    ('RTX 5070', 12, 250, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_50_series | 동상'),
    ('RTX 5070 TI', 16, 300, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_50_series | TechPowerUp GPU DB도 300W 일치'),
    ('RTX 5080', 16, 360, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_50_series | 동상'),
    ('RTX 5090', 32, 575, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_50_series | 동상'),
    ('RTX 4060', 8, 115, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_40_series | AD107-400, 115 W'),
    ('RTX 4060 TI', 8, 160, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_40_series | AD106-350, 160 W'),
    ('RTX 4060 TI', 16, 165, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_40_series | AD106-351, 165 W - 8G와 다르다'),
    ('RTX 4070', 12, 200, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_40_series | 200 W'),
    ('RTX 4070 SUPER', 12, 220, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_40_series | 220 W'),
    ('RTX 4070 TI', 12, 285, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_40_series | 285 W'),
    ('RTX 4070 TI', 16, 285, 'medium', 'https://en.wikipedia.org/wiki/GeForce_RTX_40_series | 16GB 4070 Ti 는 실제로 4070 Ti SUPER(16GB/285W)가 이름 파싱에서 TI 로 떨어진 것으로 보인다. 파싱 검토 필요'),
    ('RTX 4080', 16, 320, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_40_series | 320 W'),
    ('RTX 4080 SUPER', 16, 320, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_40_series | 320 W (4080과 동일)'),
    ('RTX 4090', 24, 450, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_40_series | 450 W'),
    ('RTX 3050', 6, 70, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_30_series | GA107-325 (2024-02-02), 70 W - 보조전원 불필요. 오늘 사고의 그 카드'),
    ('RTX 3050', 8, 130, 'medium', 'https://en.wikipedia.org/wiki/GeForce_RTX_30_series | 초기 8GB(GA106-150)=130 W, 2022-12 리프레시(GA107-350)=115 W. 보수적으로 130 채택 - 운영자 확인 권장'),
    ('RTX 3060', 12, 170, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_30_series | GA106-300, 170 W'),
    ('RTX 3060', 8, 170, 'medium', 'https://en.wikipedia.org/wiki/GeForce_RTX_30_series | 8GB 변형 TDP 를 분리 확인 못함 - 12GB 와 같은 170 보수 적용. 추정'),
    ('RTX 3060 TI', 8, 200, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_30_series | 200 W'),
    ('RTX 3070', 8, 220, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_30_series | 220 W'),
    ('RTX 3070 TI', 8, 290, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_30_series | 290 W'),
    ('RTX 3080', 10, 320, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_30_series | 320 W'),
    ('RTX 3080', 12, 350, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_30_series | 12GB 판은 350 W - 10GB 와 다르다'),
    ('RTX 3090', 24, 350, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_30_series | 350 W'),
    ('RTX 3090 TI', 24, 450, 'high', 'https://en.wikipedia.org/wiki/GeForce_RTX_30_series | 450 W'),
    ('GTX 1630', 4, 75, 'high', 'https://en.wikipedia.org/wiki/GeForce_16_series | 75 W'),
    ('GTX 1650', 4, 80, 'medium', 'https://en.wikipedia.org/wiki/GeForce_16_series | GDDR5/GDDR6판 75 W, TU116-150판 80 W. 보수적으로 80 채택'),
    ('GTX 1650 SUPER', 4, 100, 'high', 'https://en.wikipedia.org/wiki/GeForce_16_series | 100 W'),
    ('GTX 1660', 6, 120, 'high', 'https://en.wikipedia.org/wiki/GeForce_16_series | 120 W'),
    ('GTX 1660 SUPER', 6, 125, 'high', 'https://en.wikipedia.org/wiki/GeForce_16_series | 125 W'),
    ('GTX 1660 TI', 6, 120, 'high', 'https://en.wikipedia.org/wiki/GeForce_16_series | 120 W'),
    ('GTX 1050 TI', 4, 75, 'high', 'https://en.wikipedia.org/wiki/GeForce_10_series | GP107-400, 75 W'),
    ('GT 1030', 2, 30, 'high', 'https://en.wikipedia.org/wiki/GeForce_10_series | GDDR5판 30 W (DDR4판 20 W) - 보수적으로 30'),
    ('GT 1030', 4, 30, 'medium', 'https://en.wikipedia.org/wiki/GeForce_10_series | 4GB 변형은 표에 없음 - 2GB 와 동일 30 적용. 추정'),
    ('GT 730', 0, 49, 'medium', 'https://en.wikipedia.org/wiki/GeForce_700_series | GK208판 23~25 W, GF108(Fermi)판 49 W 두 갈래. 보수적으로 49 - 상품명으로 구분 불가'),
    ('GT 710', 0, 19, 'high', 'https://en.wikipedia.org/wiki/GeForce_700_series | GK208-301, 19 W'),
    ('GT 610', 2, 29, 'low', '(출처 미취득) | GeForce 600 시리즈 문서를 취득하지 않았다. 29W 는 통념값이며 «추정». 카탈로그 1건뿐'),
    ('RX 9060', 8, 132, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_9000_series | 132 W (TBP)'),
    ('RX 9060 XT', 8, 150, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_9000_series | 8GB판 150 W - 16GB 와 다르다'),
    ('RX 9060 XT', 16, 160, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_9000_series | 16GB판 160 W'),
    ('RX 9070', 16, 220, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_9000_series | 220 W TBP'),
    ('RX 9070', 12, 220, 'low', '(공식 라인업 없음) | 12GB RX 9070 은 공식 라인업에 없다 - 상품명 파싱 오류 의심. 미확인, 16GB값 유용'),
    ('RX 9070 XT', 16, 304, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_9000_series | 304 W TBP (AMD 공식값)'),
    ('RX 7600', 8, 165, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_7000_series | 165 W TBP'),
    ('RX 7600 XT', 16, 190, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_7000_series | 190 W TBP'),
    ('RX 7700 XT', 12, 245, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_7000_series | 245 W TBP'),
    ('RX 7800 XT', 16, 263, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_7000_series | 263 W TBP'),
    ('RX 7900 XT', 20, 315, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_7000_series | 315 W TBP'),
    ('RX 7900 XT', 24, 355, 'medium', 'https://en.wikipedia.org/wiki/Radeon_RX_7000_series | 24GB 는 7900 XTX(355W)다 - XTX 의 파싱 누락 의심. 보수적으로 XTX값'),
    ('RX 7900 XTX', 24, 355, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_7000_series | 355 W TBP'),
    ('RX 6400', 4, 53, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_6000_series | 53 W'),
    ('RX 6500 XT', 4, 107, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_6000_series | 4GB 107 W (8GB판 113 W)'),
    ('RX 6600', 8, 132, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_6000_series | 132 W'),
    ('RX 6600 XT', 8, 160, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_6000_series | 160 W'),
    ('RX 6700 XT', 12, 230, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_6000_series | 230 W'),
    ('RX 6750 XT', 12, 250, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_6000_series | 250 W'),
    ('RX 550', 4, 50, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_500_series | 50 W (640SP판 60 W)'),
    ('RX 580', 8, 185, 'high', 'https://en.wikipedia.org/wiki/Radeon_RX_500_series | 185 W'),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ---- (1) 상품 사양 컬럼 ------------------------------------------------
    op.execute("ALTER TABLE product_specs"
               " ADD COLUMN IF NOT EXISTS gpu_power_draw_watt INTEGER")
    op.execute("""
        INSERT INTO spec_field_defs
          (field_key, label, data_type, unit, part_types, required_for,
           is_engine, is_custom, in_ingest, sort_order, note)
        VALUES ('gpu_power_draw_watt', '카드 소비전력', 'INTEGER', 'W',
                '["GPU"]'::jsonb, '[]'::jsonb,
                true, false, true,
                (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM spec_field_defs),
                '카드 자체 소비전력(TDP/TGP/TBP). 시스템 권장 파워(required_power_watt)가 '
                '아니다 - 호환 규칙 power 가 이 값 + 200W 로 파워를 판정한다. '
                '필수 사양으로 잡지 않는다: 필수로 걸면 값 없는 GPU 가 그 즉시 검수 '
                '대기로 떨어져 추천에서 빠진다(0022 전례).')
        ON CONFLICT (field_key) DO NOTHING
    """)

    # ---- (2) (chipset_key, vram_gb) 복합키 참조표 ---------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS gpu_power_draw_reference (
          chipset_key   VARCHAR(40)  NOT NULL,
          vram_gb       INTEGER      NOT NULL DEFAULT 0,
          draw_watt     INTEGER      NOT NULL,
          confidence    VARCHAR(10)  NOT NULL DEFAULT 'medium',
          confirmed_yn  BOOLEAN      NOT NULL DEFAULT false,
          source_note   VARCHAR(300) NOT NULL,
          updated_by    BIGINT REFERENCES admin_operators(operator_id),
          updated_at    TIMESTAMP    NOT NULL DEFAULT now(),
          PRIMARY KEY (chipset_key, vram_gb)
        )
    """)
    for r in DRAW_ROWS:
        conn.exec_driver_sql(
            "INSERT INTO gpu_power_draw_reference"
            " (chipset_key, vram_gb, draw_watt, confidence, source_note)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (chipset_key, vram_gb) DO NOTHING", r)

    # ---- (3) 규칙 스키마 확장 ----------------------------------------------
    # ref_offset: 상대값에 더하는 상수. 엔진은 `v <op> (r + ref_offset)` 로 비교한다.
    #   지금 엔진의 규칙 어휘는 「slot.field <op> ref_slot.ref_field」 2항뿐이라
    #   «+200W» 를 표현할 수 없었다. 새 op 를 만드는 대신(새 연산자는 _cmp·eq 인덱스·
    #   전방검사·화면 표기 네 군데를 동시에 바꿔야 한다) **상대값에 더하는 정수 한 칸**을
    #   둔다 — 기본 0 이라 기존 8개 규칙의 판정은 한 글자도 바뀌지 않는다.
    # null_ref_mode: 상대값(또는 대상값)이 NULL 일 때의 처분.
    #   'block' (기본, 지금까지의 동작) = NULL 불통과. ERD 3.7 계약 그대로.
    #   'skip'                         = **판정 불가**. 통과도 탈락도 아니다 -
    #                                    규칙을 적용하지 않고 화면엔 pass=null 로 남긴다.
    #   왜 필요한가: 새 필드는 이번에 «일반 소비자용 GPU 만» 채운다(사장님 지시 4).
    #   워크스테이션 GPU 는 칩 파서가 대부분을 못 읽어 NULL 로 남는데, NULL 불통과면
    #   그 라인의 견적이 통째로 0건이 된다 - CLAUDE.md 가 경고하는 «조용한 죽음»이다.
    #   또 "값을 모른다"를 "호환되지 않는다"로 말하는 것은 화면 정직성 위반이다
    #   (_rules_for_active 가 재사용 슬롯에 대해 이미 같은 판단을 한다 - 같은 정신).
    op.execute("ALTER TABLE compat_rules"
               " ADD COLUMN IF NOT EXISTS ref_offset INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE compat_rules"
               " ADD COLUMN IF NOT EXISTS null_ref_mode VARCHAR(8) NOT NULL DEFAULT 'block'")

    # ---- (4) 규칙 5번 재정의 ------------------------------------------------
    # detail_fmt 의 {r} 은 **오프셋이 더해진 뒤의 값**을 받는다(엔진이 그렇게 넘긴다) —
    # 고객에게 보이는 자리라 "카드 TDP 숫자를 다 밝히지 않는다"는 사장님 지시 2와 맞는다.
    op.execute("""
        UPDATE compat_rules SET
          ref_field     = 'gpu_power_draw_watt',
          ref_offset    = 200,
          null_ref_mode = 'skip',
          detail_fmt    = '{v}W >= 권장 {r}W',
          updated_at    = now()
        WHERE rule_key = 'power'
    """)

    # ---- (5) 추천 뷰에 신규 컬럼 ------------------------------------------
    # CREATE OR REPLACE VIEW 는 **끝에 컬럼 추가만** 된다(순서 변경·삭제 거부) — 0022 전례.
    # 뷰가 ps.* 가 아니라 컬럼을 일일이 나열하므로, 안 실으면 _load_pool 이 필드를
    # 못 읽고 규칙이 NULL 로 떨어진다.
    op.execute("""
        DO $$
        DECLARE ddl text; pos int;
        BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                      WHERE table_name='v_recommendation_candidates'
                        AND column_name='gpu_power_draw_watt') THEN RETURN; END IF;
          ddl := pg_get_viewdef('v_recommendation_candidates', true);
          pos := position('FROM products p' in ddl);
          EXECUTE 'CREATE OR REPLACE VIEW v_recommendation_candidates AS '
               || substr(ddl, 1, pos - 1) || ', ps.gpu_power_draw_watt ' || substr(ddl, pos);
        END $$;
    """)

    # ---- (6) 참조표 -> 상품 백필 -------------------------------------------
    # 매칭은 (chipset_key, vram_gb) 정확 일치 우선, 없으면 «그 칩의 값이 하나뿐일 때만»
    # VRAM 무시 매칭. 값이 VRAM 으로 갈리는 칩(3050·4060 Ti·9060 XT·3080·7900 XT)에서
    # VRAM 을 모르면 **채우지 않는다(NULL)** - 둘 중 하나를 고르는 건 값을 지어내는 것이다.
    # 칩 키 파싱은 SQL 로 못 한다(api.catalog_map.gpu_chipset_key 가 단일 원천).
    import os as _os
    import sys as _sys
    _root = _os.path.dirname(_os.path.dirname(_os.path.dirname(
        _os.path.dirname(_os.path.abspath(__file__)))))
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    from api.catalog_map import gpu_chipset_key   # noqa: E402  (단일 원천)

    exact, per_chip = {}, {}
    for key, vram, watt, _c, _n in DRAW_ROWS:
        exact[(key, vram)] = watt
        per_chip.setdefault(key, set()).add(watt)
    chip_only = {k: next(iter(v)) for k, v in per_chip.items() if len(v) == 1}

    rows = conn.exec_driver_sql(
        "SELECT p.product_code, p.product_name, ps.vram_gb"
        "  FROM products p JOIN product_specs ps USING (product_code)"
        " WHERE p.part_type = 'GPU'").fetchall()
    n_exact = n_chip = n_skip = 0
    for code, name, vram in rows:
        key = gpu_chipset_key(name or "")
        key = key.upper() if key else None
        watt = exact.get((key, vram if vram is not None else 0)) if key else None
        if watt is not None:
            n_exact += 1
        else:
            watt = chip_only.get(key) if key else None
            if watt is None:
                n_skip += 1
                continue
            n_chip += 1
        conn.exec_driver_sql(
            "UPDATE product_specs SET"
            "   gpu_power_draw_watt = %s,"
            # 정직 표기 계약(seed_0014) — 값마다 출처를 남긴다. 원천값과 같은 얼굴로
            # 보여주면 "근거가 사실"이라는 정체성이 깨진다.
            "   spec_sources = COALESCE(spec_sources, '{}'::jsonb)"
            "                  || '{\"gpu_power_draw_watt\": \"reference\"}'::jsonb,"
            "   updated_at = now()"
            " WHERE product_code = %s", (watt, code))
    print("[0094] gpu_power_draw_watt backfill: exact=%d chip_only=%d skipped_null=%d"
          " of %d GPU rows" % (n_exact, n_chip, n_skip, len(rows)))


def downgrade() -> None:
    # 컬럼은 남긴다 — 지우면 값이 함께 사라진다(0022·0083 규약).
    op.execute("""
        UPDATE compat_rules SET
          ref_field     = 'required_power_watt',
          ref_offset    = 0,
          null_ref_mode = 'block',
          detail_fmt    = '{v}W >= 권장 {r}W'
        WHERE rule_key = 'power'
    """)
    op.execute("DELETE FROM spec_field_defs WHERE field_key = 'gpu_power_draw_watt'")
    op.execute("DROP TABLE IF EXISTS gpu_power_draw_reference")
    op.execute("ALTER TABLE compat_rules DROP COLUMN IF EXISTS null_ref_mode")
    op.execute("ALTER TABLE compat_rules DROP COLUMN IF EXISTS ref_offset")
