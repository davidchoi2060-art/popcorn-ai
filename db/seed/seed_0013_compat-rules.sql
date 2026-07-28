-- ⚠ 낡음 — 이 파일을 새 설치에 쓰지 마라. 정본은 마이그레이션 0019다.
--   여기 `cooler_socket`은 아직 socket/eq인데, 슬라이스 39부터 엔진은
--   socket_list/contains를 쓴다(쿨러는 소켓을 평균 5~6개 지원). 이 정의로 세우면
--   모든 쿨러가 탈락해 견적이 한 건도 안 나온다. 이력 보존용으로만 남긴다.
--
-- seed_0013: 슬라이스 34 — 조립 호환 규칙 7종 (재실행 안전)
-- 현 엔진(recommend._slot_ok)과 **동일한 판정**을 데이터로 표현한다. 규칙을 바꾸면 견적이
-- 바뀌므로, 이 시드는 리팩터링 전후 회귀(945,000/993,000/1,367,000/1,738,000·S1 20)를
-- 보증하는 기준선이다.
-- ref_slot은 탐색 순서(CPU→MB→RAM→GPU→CASE→COOLER→POWER→SSD)에서 slot보다 앞이어야 한다.

INSERT INTO compat_rules (rule_key, slot, field, op, ref_slot, ref_field, label, detail_fmt, sort_order)
SELECT * FROM (VALUES
  ('socket',         'MB',     'socket',           'eq',  'CPU',  'socket',
   'CPU 소켓 규격 일치',        '{r} = {v}',              10),
  ('mem',            'RAM',    'mem_type',         'eq',  'MB',   'mem_type',
   '메모리 규격 일치',          '{v} = {r}',              20),
  ('gpu_len',        'CASE',   'gpu_max_mm',       'gte', 'GPU',  'length_mm',
   '그래픽카드 장착 길이',       'GPU {r}mm ≤ 케이스 {v}mm', 30),
  ('cooler_socket',  'COOLER', 'socket',           'eq',  'CPU',  'socket',
   '쿨러 소켓 지원',            '{v} = {r}',              40),
  ('cooler_tdp',     'COOLER', 'cooler_tdp',       'gte', 'CPU',  'tdp_watt',
   '쿨러 발열(TDP) 통과',       '{v}W ≥ {r}W',            50),
  ('cooler_height',  'COOLER', 'cooler_height_mm', 'lte', 'CASE', 'cooler_height_mm',
   '쿨러 높이 여유',            '쿨러 {v}mm ≤ 케이스 {r}mm', 60),
  ('power',          'POWER',  'rated_watt',       'gte', 'GPU',  'required_power_watt',
   '전원 용량 여유',            '{v}W ≥ 권장 {r}W',        70)
) AS v(rule_key, slot, field, op, ref_slot, ref_field, label, detail_fmt, sort_order)
 WHERE NOT EXISTS (SELECT 1 FROM compat_rules c WHERE c.rule_key = v.rule_key);
