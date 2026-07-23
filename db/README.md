# db/ — 팝콘PC AI 데이터베이스 (Cloud SQL PostgreSQL)

**스키마 단일 원천:** `docs/06_db-erd.md` Ver 4.0. 이 폴더는 그 문서의 실행본이다.
**대상:** Cloud SQL PostgreSQL (구글 클라우드, 기구성) · DB명 `popcorn_pc` · 앱 계정 `popcorn_app`
**접속 정보·비밀번호:** `docs/infra/GCP_SETUP.md`(로컬 전용, 커밋 금지) + 비밀번호 관리 도구. **어떤 비밀값도 이 리포에 커밋하지 않는다.**

## 구성

```
db/
├─ alembic.ini                  Alembic 설정 (접속 문자열 없음)
├─ migrations/
│  ├─ env.py                    DATABASE_URL 환경변수로 접속
│  └─ versions/0001_initial_schema.py   ERD 4.0 전체 DDL
└─ seed/seed.sql                목업 더미 데이터 (개발 시드, 빈 DB 전제)
└─ seed/seed_0002_review-queue.sql  검수 큐 슬라이스 패치 (0002 마이그레이션 후 1회, 재실행 안전)
└─ seed/seed_0003_price-import.sql  단가표 슬라이스 패치 (스냅샷·오늘 파일·매핑, 재실행 안전)
└─ seed/seed_0004_candidate-pool.sql  S1 후보 풀 슬라이스 패치 (추천 가능 6종+태그, 재실행 안전)
└─ seed/seed_0005_quote-engine.sql  견적 엔진 슬라이스 패치 (티어 부품 9종, 재실행 안전)
```

## 사용법 (로컬 PC → Cloud SQL)

```bash
# 0) 사전 조건: Cloud SQL 승인된 네트워크에 이 PC 공인 IP 등록 + 비밀번호 확보
# 1) 최초 1회 — DB·계정 생성 (postgres 관리자로)
psql "host=<CLOUD_SQL_IP> port=5432 user=postgres dbname=postgres sslmode=require" <<'SQL'
CREATE DATABASE popcorn_pc;
CREATE USER popcorn_app WITH PASSWORD '<앱전용_비번_별도보관>';
GRANT ALL PRIVILEGES ON DATABASE popcorn_pc TO popcorn_app;
\c popcorn_pc
GRANT ALL ON SCHEMA public TO popcorn_app;
SQL

# 2) 스키마 적용 (popcorn_app으로)
set DATABASE_URL=postgresql+psycopg2://popcorn_app:<비번>@<CLOUD_SQL_IP>:5432/popcorn_pc?sslmode=require
cd db && alembic upgrade head

# 3) 시드 (선택 — 개발 데이터)
psql "host=<CLOUD_SQL_IP> port=5432 user=popcorn_app dbname=popcorn_pc sslmode=require" -f seed/seed.sql

# 롤백: alembic downgrade base  /  SQL 미리보기: alembic upgrade head --sql
```

## 규칙

- 스키마 변경은 **ERD 문서 개정 → 새 마이그레이션 파일** 순서. DDL 직접 수정 금지.
- `DATABASE_URL`은 셸 환경변수 또는 로컬 `.env`(gitignore)로만. 예시는 `.env.example`.
- pg_trgm 확장 필요(마이그레이션이 생성 시도 — Cloud SQL은 기본 허용 목록에 있음).
- Ver 2.0 유지 테이블은 최소 정의로 생성됨(`[V2-min]`) — API 단계에서 필드 확장 시 새 마이그레이션으로.
