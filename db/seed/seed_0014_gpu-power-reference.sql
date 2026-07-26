-- seed_0014: 슬라이스 39 — GPU 칩셋별 권장 파워 참조표 (재실행 안전)
--
-- 왜 필요한가: 실파일 24,303행에서 GPU 판매중 391건 중 **권장파워가 원천에 9건뿐**이다.
-- 호환 규칙 `POWER.rated_watt >= GPU.required_power_watt`의 한쪽이 비면 조립 안전장치가
-- 391건 중 9건에서만 작동한다. 사용자 결정(2026-07-26): 칩셋별 표준표로 채운다.
--
-- **정직 표기 계약**: 이 값은 원천 데이터가 아니라 참조값이다.
--   · confirmed_yn = false 로 들어간다 — 운영자가 확인해야 true가 된다.
--   · 적재 시 product_specs.spec_sources 에 {"required_power_watt": "reference"} 로 남는다.
--   · 견적 근거 카드는 이 값을 '표준 권장값(확인 대기)'으로 표시해야 한다 —
--     원천값(eav)과 같은 얼굴로 보여주면 "근거가 사실"이라는 정체성이 깨진다.
-- 값의 출처는 제조사 공개 권장 시스템 전력이며 **AI가 제시한 값**이다(모델별 오차 가능).
-- 보수적으로(상향) 잡는다 — 파워 부족 조합을 내보내지 않는 쪽이 신뢰 판매자에 맞다.

INSERT INTO gpu_power_reference (chipset_key, recommended_watt, source_note)
SELECT * FROM (VALUES
  -- NVIDIA RTX 50 (실측 상위: 5060 50건·5060 Ti 45·5070 43·5070 Ti 39·5080 32·5050 24·5090 10)
  ('RTX 5090',      1000, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 5080',       850, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 5070 TI',    750, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 5070',       650, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 5060 TI',    600, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 5060',       550, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 5050',       550, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  -- NVIDIA RTX 40
  ('RTX 4090',       850, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 4080 SUPER', 750, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 4080',       750, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 4070 TI',    700, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 4070',       650, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 4060 TI',    550, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 4060',       550, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  -- NVIDIA RTX 30 / GTX / GT
  ('RTX 3090',       750, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 3080',       750, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 3070',       650, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 3060 TI',    600, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 3060',       550, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RTX 3050',       550, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('GTX 1660 SUPER', 450, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('GTX 1660 TI',    450, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('GTX 1660',       450, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('GTX 1650',       350, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('GT 1030',        300, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('GT 730',         300, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('GT 710',         300, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  -- AMD RX 9000 (실측: 9070 XT 18건·9060 XT 16·9070 4·9060 4)
  ('RX 9070 XT',     750, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RX 9070',        700, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RX 9060 XT',     550, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RX 9060',        500, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  -- AMD RX 7000 / 6000 / 500
  ('RX 7900 XTX',    800, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RX 7900 XT',     750, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RX 7800 XT',     700, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RX 7700 XT',     700, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RX 7600',        550, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RX 6700 XT',     650, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RX 6600',        500, 'AI 제시 표준 권장값 — 운영자 확인 필요'),
  ('RX 580',         500, 'AI 제시 표준 권장값 — 운영자 확인 필요')
) AS v(chipset_key, recommended_watt, source_note)
WHERE NOT EXISTS (SELECT 1 FROM gpu_power_reference g WHERE g.chipset_key = v.chipset_key);

-- 쿨러 소켓 규칙을 다중값으로 교체: COOLER.socket = CPU.socket → socket_list contains CPU.socket
-- (실측: 쿨러는 평균 5~6개 소켓을 지원한다 — 단일값 비교로는 대부분이 불일치로 떨어진다)
UPDATE compat_rules
   SET field = 'socket_list', op = 'contains',
       detail_fmt = '{r} 지원'
 WHERE rule_key = 'cooler_socket';

-- 기존 시드(데모 30종) 쿨러의 socket_list 백필 — 규칙이 socket_list를 보게 됐으므로
-- 단일값 socket을 1개 원소 배열로 승격한다. 없으면 쿨러가 전부 불통과해 견적이 깨진다.
UPDATE product_specs
   SET socket_list = to_jsonb(ARRAY[socket])
 WHERE part_type LIKE 'COOLER%' AND socket IS NOT NULL AND socket_list IS NULL;
