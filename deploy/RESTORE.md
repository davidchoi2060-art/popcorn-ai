# DB 복구 절차 (Cloud SQL · PostgreSQL 16)

> 2026-07-27 리허설로 **실제 검증된 절차**다. 장애 상황에서 이 문서만 보고 실행할 수 있게 쓴다.
> 프로젝트 ID·비밀번호는 여기 적지 않는다 — `docs/infra/GCP_SETUP.md`(로컬 전용) 참조.

## 0. 원칙

- **원본을 덮어쓰지 않는다.** `gcloud sql backups restore`는 대상 인스턴스를 **덮어쓴다** —
  장애 원인을 아직 모르는 상태에서 쓰면 증거까지 사라진다.
  대신 **복제본을 만들어 확인한 뒤** 전환한다.
- 운영 인스턴스는 **삭제 보호가 켜져 있다**(`deletionProtectionEnabled=true`). 복제본도
  이 설정을 물려받으므로, 정리할 때 보호를 먼저 꺼야 삭제된다.

## 1. 지금 무엇이 있는지 확인

```bash
gcloud sql backups list --instance=popcorn-db --limit=5
gcloud sql instances describe popcorn-db \
  --format="value(settings.backupConfiguration.enabled,settings.backupConfiguration.pointInTimeRecoveryEnabled,settings.backupConfiguration.transactionLogRetentionDays)"
```

2026-07-27 기준: 자동 백업 **매일 21:00 UTC**(=06:00 KST) · 보관 **7건** ·
**PITR 활성** · 트랜잭션 로그 **7일**. 즉 **최근 7일 안의 임의 시점**으로 되돌릴 수 있다.

## 2. 복제본 만들기 (시점 지정)

되돌릴 시점을 UTC로 정한다. "사고 직전"을 잡는 것이 요령이다.

```bash
gcloud sql instances clone popcorn-db popcorn-db-drill-MMDD \
  --point-in-time="2026-07-27T04:36:09Z"
```

소요: 리허설 실측 **약 4분**. 완료되면 새 공인 IP가 나온다.

## 3. 접속 허용 + 검증

복제본은 승인 네트워크가 비어 있다. 작업 PC IP를 넣는다(유동 IP면 매번 확인).

```bash
gcloud sql instances patch popcorn-db-drill-MMDD --authorized-networks="$(curl -s -4 ifconfig.me)/32" --quiet
```

그다음 **행 수를 현재와 대조**한다. 시점 이후에 생긴 것이 빠져 있어야 정상이다.

```sql
SELECT count(*) FROM products;
SELECT count(*) FROM product_reviews WHERE review_status='대기';
SELECT count(*) FROM orders;
SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty > 0;
SELECT max(updated_at) FROM products;   -- 지정 시점보다 앞서야 한다
```

리허설 실측(04:36 시점 vs 당시 현재): 상품·주문·후보·배치는 **동일**,
제안값 보유 검수 **4 vs 98**(그 사이 수집분 94건이 정확히 빠짐), 검수 대기 **5,890 vs 5,891**.
→ 특정 시점 복구가 실제로 동작함을 확인.

## 4. 전환 (실제 장애일 때만)

검증이 끝나면 애플리케이션 접속 대상을 복제본으로 바꾼다.

1. 서버에서 `/etc/popcorn-ai.env`의 `DATABASE_URL` 호스트를 복제본 IP로 교체
   (권한 `640 root:popcorn` 유지 — 600이면 앱이 못 읽는다)
2. `systemctl restart popcorn-api`
3. `deploy/verify.sh`로 확인
4. 복제본에 **승인 네트워크·백업·삭제 보호**를 원본과 같게 설정한다 — 임시본이 그대로
   운영이 되면 백업 없는 상태로 굴러간다

## 5. 정리 (리허설일 때)

```bash
gcloud sql instances patch popcorn-db-drill-MMDD --no-deletion-protection --quiet
gcloud sql instances delete popcorn-db-drill-MMDD --quiet
gcloud sql instances list          # popcorn-db 하나만 남았는지 확인
```

## 6. 리허설 기록

| 날짜 | 시점 | 소요 | 결과 |
|------|------|------|------|
| 2026-07-27 | 04:36 UTC (1시간 전) | 복제 약 4분 · 전체 약 10분 | 통과 — 시점 이후 변경분만 정확히 누락 |

**다음 리허설 권장 시점**: 스키마 마이그레이션 직후, 또는 분기 1회.
