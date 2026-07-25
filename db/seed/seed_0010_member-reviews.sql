-- seed_0010: 슬라이스 19 — 후기 관리(ADM-CUS-020) 신고됨 상태 재현 (재실행 안전)
-- 기존 시드 2건은 전부 '게시'라 신고 처리(숨김/게시 유지) 액션을 실데이터로 시연 불가 — 1건 보강.
-- 구매 인증 강제(order_item_id NOT NULL): item 11 = ORD-84213(김민준) 통합 구성 라인(실재).
-- moderation_note는 v1에서 "신고 접수 메모 겸 처리 사유" 겸용 — 신고 수신함(신고자·사유·건수)
-- 컬럼화는 ERD 개정 사안으로 이관.

INSERT INTO member_reviews (member_id, order_item_id, rating, body, status, cite_s2, moderation_note, created_at)
SELECT 1, 11, 1,
       '배송이 늦었습니다. 제품 문제는 아니지만 별점은 못 드리겠네요.',
       '신고됨', false,
       '신고 접수: 상품 품질과 무관한 배송 불만 — 노출 유지/숨김 판단 필요',
       now() - interval '13 days'
 WHERE NOT EXISTS (SELECT 1 FROM member_reviews WHERE member_id=1 AND order_item_id=11);
