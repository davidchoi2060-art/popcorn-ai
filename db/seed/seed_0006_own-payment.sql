-- seed_0006_own-payment.sql — 운영 모드 A-10 전환 2단계 승격 (2026-07-24)
-- 전제: seed.sql~0005 적용된 DB. 재실행 안전.
--
-- 목적: S4 자체 결제 경로 개통 — 결제·정산만 자체(own)로 전환(정합 규칙 ①: settle은 pay를 따름).
--   ops_snapshot 감사 정합: POST /api/orders는 DB ops_settings 5키를 그대로 스냅샷한다.
-- 부작용(의도됨): S4 기본 경로가 자체 결제로(LIVE는 GET /api/ops 동기화). 배송·환불은 여전히 mall.

BEGIN;

UPDATE ops_settings SET mode='own', updated_at=now()
 WHERE key IN ('pay','settle') AND mode <> 'own';

INSERT INTO ops_settings_history (changes, version, changed_by, reason)
SELECT '{"pay":"mall→own","settle":"mall→own"}'::jsonb, 2, 1,
       'A-10 전환 2단계: 자체 결제 경로 개통 (슬라이스 6)'
 WHERE NOT EXISTS (SELECT 1 FROM ops_settings_history WHERE version=2);

COMMIT;
