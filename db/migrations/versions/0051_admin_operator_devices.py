# -*- coding: utf-8 -*-
"""admin_operator_devices — 관리자 「기기 기억」(비밀번호 생략) + admin_sessions.password_verified.

■ 왜 필요한가 (사장님 지시 2026-08-15, 유휴 8시간·IP 기록과 함께 나온 세 번째 요청)
  사장님 원문: "내 IP는 PC를 다시 켜면 달라지지 않나?" — IP는 회선이 바뀌면 같이
  바뀌어(공유기 재접속·모바일 테더링) "비밀번호 생략"의 기준으로 쓸 수 없다고
  스스로 짚으셨다. 그래서 **IP 기록(감사용)과는 별개로** "이 기기를 기억해서
  비밀번호를 덜 치게" 하는 기능을 요청했다. 세 요청은 서로 다른 것을 한다:
    유휴 8시간   세션이 자주 안 끊기게      (api/auth.py IDLE_MINUTES, 스키마 변경 없음)
    IP 기록      감사 기록                  (admin_sessions.login_ip, 마이그레이션 0049)
    기기 기억    비밀번호를 덜 치게          (이 마이그레이션)

■ 왜 admin_sessions에 얹지 않고 새 표를 만드는가
  admin_sessions의 한 행은 "로그인 한 번"이고 수명은 최대 8시간(ABSOLUTE_HOURS,
  api/auth.py)이다. 기기 기억은 그보다 훨씬 긴 수명(30일, 쓸 때마다 슬라이딩)을
  갖고, 시간이 지나면서 **같은 기기가 여러 세션을 반복해서 만들어낸다**(1 기기 :
  N 세션, N은 그 기기에서 로그인한 횟수). 한 표에 두 생명주기를 담으면:
    · `expires_at` 컬럼이 "이 로그인은 8시간 뒤 끝난다"와 "이 기기는 30일 뒤
      다시 확인해야 한다"라는 서로 다른 두 의미를 동시에 가져야 해서 어느 쪽
      기준으로 유휴·절대 만료를 계산하는지 코드마다 갈릴 위험이 있다.
    · "기기를 잊어버리기"(철회)가 그 기기로 만든 **현재 활성 세션까지** 지워야
      하는지 애매해진다 — 실제로는 아니다(기기를 잊어도 지금 열려 있는 세션은
      그대로 살아 있고, 그 세션이 끝나면 다음부터 비밀번호를 다시 묻는 것뿐이다).
  그래서 세션(짧고 1:1)과 기기(길고 1:N)를 별개 표로 둔다 — CLAUDE.md
  "재구축은 증분이 아니라 재설계다"(P-08)와 "맞는 표를 새로 만든다" 원칙을 따른다.

■ 토큰 저장 방식 — 셀렉터(device_id) + 검증값(token_hash), 평문 저장 없음
  사장님 지시: "쿠키에는 랜덤 토큰, DB 에는 해시만 저장해라 — 평문으로 저장하지
  마라. DB 가 새면 전 기기가 열린다." scrypt(api/passwords.hash_password)는 매번
  다른 salt를 써서 **같은 입력도 호출마다 다른 해시**를 낸다 — 그래서 "해시로
  직접 WHERE 조회"가 불가능하다(비밀번호 로그인이 이메일로 행을 먼저 찾고
  나서 해시를 검증하는 것과 같은 이유). 그래서 쿠키 값을 `device_id:secret`
  둘로 나눈다:
    device_id  32자 hex(secrets.token_hex(16)) — **비밀이 아니다.** DB 조회
               셀렉터일 뿐이고 이것만으로는 로그인할 수 없다(PK로 노출해도
               안전 — api/admin_profile.py 목록 응답에 그대로 낸다).
    secret     64자 hex(secrets.token_hex(32)) — **이것이 진짜 비밀이다.**
               쿠키(HttpOnly)에만 있고 서버는 `token_hash`(scrypt)만 저장한다.
               api/passwords.hash_password/verify_password를 그대로 쓴다(새
               해시 방식을 발명하지 않는다 — 사장님 지시).
  이 방식(selector + verifier)은 "장기 remember-me 토큰" 구현의 표준 패턴이다 —
  admin_sessions.session_id(평문 저장·직접 WHERE 조회)와 다르게 다루는 이유는
  수명 차이다: 세션은 최대 8시간이라 DB 유출 시 노출 창이 짧지만, 기기 토큰은
  30일이라 평문 저장 시 노출 창이 60배 길다.

■ password_verified — admin_sessions에 얹는 컬럼(신설 표가 아니라 기존 표 확장)
  "기기 기억으로 만든 세션인가"는 세션 자체의 성질이라(그 세션이 비밀번호
  확인을 거쳤는지) admin_sessions 쪽에 둔다. **기본값 TRUE**를 쓴다 — 이 컬럼이
  생기기 전 세션은 전부 실제로 login()의 비밀번호 검증을 거쳐 만들어졌으므로
  (기기 기억 로그인 경로 자체가 이 리비전 이전에는 없었다) TRUE가 지어낸 값이
  아니라 **사실**이다(login_ip를 NULL로 둔 것과의 차이 — 거긴 몰라서 NULL,
  여긴 알아서 TRUE). 이후 `/api/admin/auth/device-login`(비밀번호 생략)으로 만든
  세션만 명시적으로 FALSE로 심는다.

■ 다시 확인(reauth) — password_verified=false 인 세션이 «정책 발행급 쓰기»에
  걸리면(api/auth.py auth_middleware, OWNER_WRITE_PREFIXES) `/api/admin/auth/reauth`
  로 비밀번호를 한 번 더 확인해야 하고, 통과하면 그 세션의 password_verified가
  true로 바뀐다(남은 세션 수명 동안 다시 안 묻는다 — 비밀번호로 직접 로그인한
  것과 같은 신뢰 수준이 된다).

■ 계정 정지·비밀번호 변경 시 자동 무효화
  · admin_operator_devices는 정지 계정을 막는 별도 컬럼을 두지 않는다 —
    device-login이 매번 admin_operators.status를 JOIN해서 확인하므로
    (resolve_session이 세션마다 status를 다시 보는 것과 같은 방식) 계정이
    '정지'되는 순간 그 기기의 다음 device-login부터 자동으로 막힌다.
  · 비밀번호를 바꾸면(api/auth.py change_my_password) 그 계정의 기기 기억을
    전부 철회한다 — 다른 세션을 끊는 것과 같은 이유(유출을 의심해 비밀번호를
    바꿨는데 기기 기억이 살아 있으면 훔친 쿠키로 계속 새 세션을 받을 수 있다).
    owner가 임시 비밀번호를 발급할 때(issue_password)도 같다.

■ 번호 — 0051 (head는 0050, `alembic heads` 단일 확인은 DBA 적용 시점에 한다)
"""
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE admin_operator_devices (
          device_id     VARCHAR(32) PRIMARY KEY,
          operator_id   BIGINT NOT NULL REFERENCES admin_operators(operator_id),
          token_hash    VARCHAR(255) NOT NULL,
          user_agent    VARCHAR(300),
          created_at    TIMESTAMP NOT NULL DEFAULT now(),
          last_used_at  TIMESTAMP NOT NULL DEFAULT now(),
          expires_at    TIMESTAMP NOT NULL,
          revoked_at    TIMESTAMP
        );

        CREATE INDEX idx_operator_devices_operator
          ON admin_operator_devices (operator_id, revoked_at);

        -- 기본값 TRUE인 이유는 위 docstring "password_verified" 절 참조 —
        -- 이 컬럼이 생기기 전 세션은 전부 실제로 비밀번호 검증을 거쳤다(사실이지,
        -- 지어낸 값이 아니다). 기존 행을 다시 쓰지 않는 ADD COLUMN이므로 대형
        -- 테이블(admin_sessions)에도 안전한 변경이다(0049 login_ip와 같은 이유).
        ALTER TABLE admin_sessions
          ADD COLUMN IF NOT EXISTS password_verified BOOLEAN NOT NULL DEFAULT true;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE admin_sessions DROP COLUMN IF EXISTS password_verified;
        DROP TABLE IF EXISTS admin_operator_devices;
    """)
