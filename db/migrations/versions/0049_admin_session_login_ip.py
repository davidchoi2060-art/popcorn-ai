# -*- coding: utf-8 -*-
"""admin_sessions.login_ip — 관리자 로그인 접속 IP를 남길 자리 ("기록만 먼저, 차단은 나중").

■ 왜 필요한가 — 담을 자리가 없어 기록이 지금은 「0건」이 아니라 「불가능」이었다
  사장님이 관리자 접근 IP 제한을 지시했고, 순서를 "기록만 먼저, 차단은 나중"으로
  정했다. 그런데 조사자 실측(2026-08-14) 결과 지금은 담을 자리 자체가 없다:
    · public 스키마 전 테이블에 ip/inet/cidr 컬럼 0개(이름에 'ip'가 들어간 7건은
      전부 chipset·shipping 오탐)
    · admin_sessions 컬럼: session_id·operator_id·created_at·last_seen_at·
      expires_at·revoked_at·user_agent — IP 없음(user_agent는 1169/1169 전량
      채워져 있다)
    · admin_operator_activity_logs 컬럼: log_id·operator_id·action·target_kind·
      target_id·detail(jsonb)·created_at — IP 없음
    · 앱에서 request.client.host를 읽는 곳은 api/auth.py:415(dev-login의 로컬
      여부 판정용) 단 한 곳뿐이고, 그 값을 저장하지 않는다
  이 마이그레이션은 **자리만** 만든다. 그 자리에 실제로 값을 채우는 코드
  (api/auth.py의 로그인 경로)는 이번 범위 밖이다 — 순서는 ①이 파일 ②DBA 적용
  ③코드이고, 코드가 컬럼보다 먼저 들어가면 로그인이 막힌다.

  같은 날 templates/admin/operators_roles.html.j2가 디자인 원안의 "접근 IP 허용"
  탭을 "향후 사용예정"으로 비워 둔 이유도 이것과 같다(그 화면의 실측 메모: "api/
  전체에 cidr·ip_allow·allowlist류 코드가 0건"). 그 탭은 이 기록이 쌓인 뒤
  "이 IP들을 허용 목록에 넣자"를 사람이 판단하는 자리가 될 것이고, 이 마이그레이션은
  그 판단의 재료(과거 로그인 IP)를 쌓기 시작하는 첫 벽돌이다.

■ 어느 표에 넣는가 — admin_sessions (admin_operator_activity_logs가 아니다)
  admin_sessions는 "한 번의 로그인, 한 곳에서"에 정확히 대응한다 — 행 하나가
  세션 하나, 세션 하나가 로그인 한 번이다. 세션 생성 시점(created_at)에 이미
  user_agent를 같은 순간·같은 이유로 남기고 있다(api/auth.py의 세션 생성 호출부 —
  dev-login 예시로 실측). login_ip는 그 user_agent와 짝을 이루는 "이 로그인이
  어디·무엇에서 왔는가"의 나머지 반쪽이다.
  admin_operator_activity_logs는 "무엇을 했는가"(상품 수정·가격 변경 등 업무
  동작)의 원장이라 로그인이라는 행위 자체를 담는 자리가 아니다. 거기 얹으면
  "로그인이라는 행위의 IP"와 "업무 동작의 IP"가 한 원장에 섞여, 나중에 허용
  목록 판단에 쓸 "로그인 IP만"을 뽑으려면 action 종류를 다시 걸러야 한다.
  admin_sessions에 두면 그 구분이 필요 없다 — 세션 행 자체가 이미 로그인 단위다.

■ 타입 — inet (varchar가 아니다)
  · IPv4·IPv6를 둘 다 네이티브로 담는다. 로컬 접속이 '::1'로 들어오는 것을
    실측했다 — varchar도 문자열로는 저장되지만 검증도 CIDR 연산도 못 한다.
  · 나중에 허용 목록을 CIDR 대역으로 둘 계획이다(디자인 원안의 state.ips가 이미
    CIDR 문자열 예시를 쓰고 있다). inet이면 `<<`/`<<=` 같은 네이티브 포함 연산자를
    그대로 쓸 수 있다 — varchar면 애플리케이션 코드에서 매번 파싱해야 한다.
  · 잘못된 문자열은 insert 시점에 타입 자체가 막는다(varchar는 아무 문자열이나
    받아 검증을 애플리케이션에 미룬다).
  · SQLAlchemy·기존 코드 관례와 충돌 여부 확인: 이 저장소는 SQLAlchemy의
    Column/ORM 선언을 한 곳도 쓰지 않는다(grep 확인 — api/ 전체에
    declarative_base·`Column(` 0건). 마이그레이션은 전부 op.execute()의 원문
    DDL이고, 쿼리는 전부 sqlalchemy.text()다(예: api/auth.py). 즉 "SQLAlchemy
    타입 시스템과의 정합"이라는 제약 자체가 이 저장소엔 없어 inet을 원문 SQL에
    쓰는 데 장애가 없다. 드라이버는 postgresql+psycopg2(.env 확인)이고,
    psycopg2는 전용 어댑터(psycopg2.extras.register_ipaddress, 이 저장소는
    쓰지 않음)를 등록하지 않는 한 inet 값을 그대로 python str로 돌려준다 —
    기존 조회 코드(.mappings() 등)가 다루는 방식과 다르지 않다.

■ NULL 허용 · 기본값 없음
  기존 admin_sessions 1169행은 이 컬럼이 생기기 전에 로그인했다 — 어디서
  왔는지 우리는 모른다. 모르는 것을 아는 척 채우지 않는다(더미 IP·'0.0.0.0'
  금지 — CANON "모르는 것을 지어내지 않는다"). ADD COLUMN에 DEFAULT를 주지
  않으므로 기존 행은 전부 NULL이고, PostgreSQL은 이 경우 테이블을 다시 쓰지
  않는다(메타데이터만 갱신 — 대형 테이블에도 안전한 변경).

■ 번호 — 0049 (결번 0047을 채우지 않는다)
  head는 0048이고 0047은 결번이다(0046→0048 직접 연결, `alembic history`로
  확인). 0048의 docstring이 이미 이 함정을 한 번 겪었다: "0048 고정, A는 0046,
  B는 0047"이라는 배정은 세 제작자가 동시에 화면을 짓는 동안 **파일명 충돌만**
  막기 위한 것이었을 뿐이고, 실제 0047 마이그레이션은 끝내 만들어지지 않았다.
  0048은 그 빈 번호를 채우는 대신, 그 시점의 실제 head를 가리키는 쪽을
  택했다("존재 여부를 모르는 리비전을 가리키면 alembic이 통째로 멈춘다").
  이번에도 같은 이유로 0047을 재사용하지 않는다 — 그 번호는 이미 한 번 다른
  작업자의 화면용으로 배정된 이력이 있어, 지금 전혀 다른 내용(세션 컬럼)으로
  채우면 그 배정을 기억하는 사람에게 혼동을 준다. 대신 **확인된 실제 head
  (0048) 다음 번호**를 그대로 쓴다 — 파일명 순서와 체인 순서가 항상 같게
  유지되고, `alembic heads`는 이 파일 추가 뒤에도 하나여야 한다(아래 확인 참조).

Revision ID: 0049
Revises: 0048
"""
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL = ① 이 컬럼이 생기기 전에 로그인한 과거 세션(1169행 전량 해당) 또는
    #        ② 아직 이 자리에 값을 채우는 코드가 없다(이번 마이그레이션은 자리만
    #           만든다 — api/auth.py 연결은 별도 작업, DBA 적용 이후 순서대로).
    # 기본값을 두지 않는다 — 모르는 과거 접속지를 아는 척 채우지 않기 위해서다.
    op.execute(
        "ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS login_ip INET"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE admin_sessions DROP COLUMN IF EXISTS login_ip"
    )
