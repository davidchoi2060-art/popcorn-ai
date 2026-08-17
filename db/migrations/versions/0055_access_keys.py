# -*- coding: utf-8 -*-
"""consult_sessions.access_key / handoffs.access_key -- 「추측 못 할 열쇠」 (2026-08-17 사장님 확정).

■ 왜 필요한가 (실측)
  `POST /api/recommend/explain` 과 `GET /api/handoff/{no}` 는 지금 **인증도 소유자
  검증도 없다.** 그리고 두 자리의 식별자가 **연속 정수**다:
    · `consult_sessions.session_id` -- nextval 시퀀스. 최근 10건이 5872~5881
    · `handoffs.handoff_no`         -- `api/handoff.py` L50-55 가 MAX+1 로 채번(HO-1001,1002,1003)
  즉 남의 번호를 «세어서» 맞힐 수 있고, 맞히면 그 사람의 견적 구성·가격·인계 내역이
  통째로 나온다. 사장님이 확정한 두 가지 -- ①「남의 견적을 못 보게」와
  「인계 기록을 링크로 열되 추측 못 할 열쇠를 링크에 넣는다」 -- 는 **같은 장치**다.
  그래서 표를 둘로 나누지 않고 이 열쇠 하나로 둘 다 푼다.

■ 열쇠를 «담을 자리가 없다»는 것이 이 마이그레이션의 이유다
  두 표 어디에도 추측 불가 토큰·UUID 열이 없다(실측). `constraints`(JSONB)나 `note`(TEXT)
  같은 기존 칸에 끼워 넣는 우회는 **하지 않았다** -- CLAUDE.md §「이 화면 작업은
  재구축이다」가 "합성 키·의미 겹치기·컬럼 재활용으로 표를 안 만들고 우회하는 것은 이
  단계에서 미덕이 아니다"라고 못박았다. 맞는 컬럼을 새로 만든다.

■ 값의 모양 -- 코드가 정한다(여기서 두 번 정의하지 않는다)
  `api/access_gate.new_key()` = `secrets.token_urlsafe(24)` -> 32자 URL-safe(192비트).
  `api/visitor.py` L41 의 방문자 쿠키와 **같은 생성기·같은 길이**다.
  컬럼은 `VARCHAR(64)` -- 지금 값보다 넉넉히 잡아 생성기가 길어져도 스키마를 다시 안 고친다.

■ ⚠ NULL 을 백필하지 않는다 -- NULL = 「링크로 열 수 없는 행」
  기존 `consult_sessions` 5,871건 · `handoffs` 3건에는 열쇠를 채우지 «않는다».
  그 행의 주인은 열쇠를 받은 적이 없다. 무작위 값을 채워도 **아무도 못 여는 것은
  똑같은데**, 표만 보면 「누군가 열쇠를 가진 행」처럼 보인다. CANON §2-3
  「모르는 것을 지어내지 않는다」 · `api/visitor.py` 의 「과거는 소급하지 않는다」와
  같은 판단이다. 코드는 NULL 을 **닫힌 것으로** 읽어 403 을 준다(`api/access_gate.matches`).
  영향: 과거 상담의 S2 「이 구성을 고른 이유」는 더 이상 새로 생성되지 않는다 --
  화면은 엔진이 적어 보낸 고정 문구를 그대로 보여준다(이미 그렇게 동작한다).

■ ⚠ NOT NULL 은 «지금» 걸지 않는다 -- 배포 순서 사고를 만든다
  NOT NULL 을 걸면, 이 마이그레이션이 적용된 시점부터 **열쇠를 안 넣는 옛 코드의
  INSERT 가 전부 실패**한다. 즉 코드 배포 전에 적용하면 견적 생성이 죽는다
  (0054 의 docstring 이 경고한 것과 같은 종류의 순서 문제, 방향만 반대다).
  올바른 순서는 ① 이 마이그레이션 적용 -> ② 열쇠를 쓰는 코드 배포 -> ③ 그 뒤에
  NOT NULL 을 거는 별도 마이그레이션. ③ 은 **여기서 파일로 만들지 않았다** --
  잘못된 시점에 적용되면 장사를 멈추는 파일을 미리 놓아두지 않는다.

■ UNIQUE 인덱스
  열쇠가 겹치면 남의 견적이 열린다. 192비트 난수라 충돌 확률은 사실상 0 이지만,
  「생성기를 잘못 바꾼 날」을 DB가 잡아 주는 값싼 보험이다. NULL 은 UNIQUE 대상이
  아니므로(PostgreSQL 기본) 백필하지 않은 기존 행과 충돌하지 않는다.

■ ⚠⚠ 이 마이그레이션은 파일만 만든다 -- DB 에 적용하지 않는다 (DBA 소관)
  0051~0054 와 같다. 이번 작업 지시서도 "마이그레이션은 파일만, DB 적용은 DBA"를
  명시했다. 검증은 **같은 DDL 을 트랜잭션 안에서 돌리고 ROLLBACK** 하는 방식으로 했고
  (alembic_version 은 0054 그대로, 두 표에 실제 변화 0), 그 결과를 보고에 적었다.

Revision ID: 0055
Revises: 0054
"""
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE consult_sessions ADD COLUMN access_key VARCHAR(64);
        ALTER TABLE handoffs         ADD COLUMN access_key VARCHAR(64);

        CREATE UNIQUE INDEX ux_consult_sessions_access_key
            ON consult_sessions (access_key);
        CREATE UNIQUE INDEX ux_handoffs_access_key
            ON handoffs (access_key);

        COMMENT ON COLUMN consult_sessions.access_key IS
            '견적 열람 열쇠 (api/access_gate.new_key). NULL = 게이트 도입 이전 행 - 링크로 열 수 없음';
        COMMENT ON COLUMN handoffs.access_key IS
            '인계 기록 열람 열쇠 (api/access_gate.new_key). NULL = 게이트 도입 이전 행 - 링크로 열 수 없음';
    """)


def downgrade() -> None:
    # 열쇠는 «지금 살아 있는 링크»다. 컬럼을 지우면 고객이 들고 있는 링크가 전부 죽고,
    # 다시 올려도 같은 값을 복원할 수 없다. 되돌림은 삭제가 아니라는 규약과 같은 이유로
    # **인덱스만 걷고 컬럼은 남긴다**(0054 가 CHECK 만 걷고 컬럼을 남긴 것과 같은 형태).
    op.execute("""
        DROP INDEX IF EXISTS ux_consult_sessions_access_key;
        DROP INDEX IF EXISTS ux_handoffs_access_key;
    """)
