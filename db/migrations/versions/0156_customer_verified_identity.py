"""0156 고객 회원 · 소셜 로그인 저장 구조 (C2) -- 설계 docs/design/customer-social-login-v1.md §4 · ERD §3.11b

2026-10-13 사장님 결정 (나) 「회원만 자체」 + 설계 v1 확정(「제안대로 진행해」). 구글·카카오·네이버 로그인으로만
회원이 된다(비밀번호 없음). 회원 식별은 (issuer_key, subject) 정확 일치 -- 이메일은 조회 키가 아니다.

표 정의는 저장소 밖 C2 스키마 후보(D-C2-SESSION-PROOF-V1-20261007 schema-candidate.txt A~D)를 그대로 따른다 --
이미 있는 저장 읽기 계약(api/customer_auth_sql_read.py SESSION_QUERY · MEMBER_QUERY)이 이 이름·열·시각 형식(epoch 정수)을
조회한다. 거기에 가입 동의(member_consents) · 로그인 시도(oauth_login_attempts) · 동의 전 신원(member_join_pending) ·
견적/문의 회원 귀속 열을 더한다.

이 마이그레이션은 표만 만든다. 로그인은 여전히 닫혀 있다(api/customer_auth.RUNTIME_RESOLVER 그대로 503) --
켜는 것은 P2 의 CUSTOMER_AUTH_ENABLED 스위치와 공급자 키다.

시각: 인증 표는 epoch BIGINT(초). 대조 계약이 정수 시각을 비교하므로 TIMESTAMP 로 바꾸지 않는다.
옛 member_sessions(0008)는 쓰지 않는다(C2 후보 결정 -- 지우지도 않는다).
"""
from alembic import op

revision = "0156"
down_revision = "0155"
branch_labels = None
depends_on = None

_KEY = "char_length({c}) BETWEEN 1 AND 255"          # 크면 잘라 넣지 않고 거절한다(fail closed)
_HASH = "{c} ~ '^[0-9a-f]{{64}}$'"


def upgrade() -> None:
    # A. members -- 기존 행은 채우지 않는다(검증된 연결·가입 때만 채움).
    op.execute("""
        ALTER TABLE members
          ADD COLUMN auth_subject UUID NULL UNIQUE,
          ADD COLUMN auth_revision BIGINT NULL CHECK (auth_revision > 0),
          ADD COLUMN withdrawn_at TIMESTAMP NULL,
          ADD CONSTRAINT ck_members_auth_pair CHECK (
            (auth_subject IS NULL AND auth_revision IS NULL) OR (auth_subject IS NOT NULL AND auth_revision IS NOT NULL))
    """)

    # B. 검증된 신원 -- 회원 1명에 공급자 여럿(연결하기). 정규화 금지(대소문자·공백 그대로).
    op.execute(f"""
        CREATE TABLE member_verified_identities (
          identity_id         BIGSERIAL PRIMARY KEY CHECK (identity_id > 0),
          member_id           BIGINT NOT NULL REFERENCES members(member_id),
          issuer_key          TEXT COLLATE "C" NOT NULL CHECK ({_KEY.format(c='issuer_key')}),
          issuer              TEXT NOT NULL CHECK ({_KEY.format(c='issuer')}),
          subject             TEXT COLLATE "C" NOT NULL CHECK ({_KEY.format(c='subject')}),
          verification_method TEXT NOT NULL CHECK ({_KEY.format(c='verification_method')}),
          registration_ref    TEXT NOT NULL CHECK ({_KEY.format(c='registration_ref')}),
          verified_at_epoch   BIGINT NOT NULL CHECK (verified_at_epoch >= 0),
          revoked_at_epoch    BIGINT NULL CHECK (revoked_at_epoch >= 0),
          UNIQUE (issuer_key, subject),
          UNIQUE (identity_id, member_id)
        )
    """)
    op.execute("CREATE INDEX ix_member_verified_identities_member ON member_verified_identities (member_id)")

    # C. 세션 발급 영수증 -- 서버가 신원을 검증해 발급했다는 기록(P1 대조 대상). 발급 뒤 바뀌지 않는다.
    op.execute(f"""
        CREATE TABLE member_session_issuance_receipts (
          proof_ref                   UUID PRIMARY KEY,
          credential_hash             VARCHAR(64) NOT NULL UNIQUE CHECK ({_HASH.format(c='credential_hash')}),
          member_id                   BIGINT NOT NULL REFERENCES members(member_id),
          verified_identity_id        BIGINT NOT NULL,
          auth_context_id             UUID NOT NULL UNIQUE,
          issued_auth_revision        BIGINT NOT NULL CHECK (issued_auth_revision > 0),
          issued_at_epoch             BIGINT NOT NULL CHECK (issued_at_epoch >= 0),
          expires_at_epoch            BIGINT NOT NULL,
          issuer_key                  TEXT COLLATE "C" NOT NULL,
          issuer                      TEXT NOT NULL,
          subject                     TEXT COLLATE "C" NOT NULL,
          principal_verified_at_epoch BIGINT NOT NULL CHECK (principal_verified_at_epoch >= 0),
          verification_method         TEXT NOT NULL,
          registration_ref            TEXT NOT NULL,
          authority_ref               TEXT NOT NULL CHECK ({_KEY.format(c='authority_ref')}),
          CHECK (expires_at_epoch > issued_at_epoch),
          CHECK (principal_verified_at_epoch <= issued_at_epoch),
          FOREIGN KEY (verified_identity_id, member_id)
            REFERENCES member_verified_identities (identity_id, member_id),
          UNIQUE (proof_ref, credential_hash, member_id, verified_identity_id, auth_context_id,
                  issued_auth_revision, issued_at_epoch, expires_at_epoch)
        )
    """)

    # D. 검증된 세션 -- 쿠키 토큰의 sha256 만 저장. 철회는 revoked_at_epoch 만 바꾼다(지우지 않음).
    op.execute(f"""
        CREATE TABLE member_verified_sessions (
          credential_hash      VARCHAR(64) PRIMARY KEY CHECK ({_HASH.format(c='credential_hash')}),
          member_id            BIGINT NOT NULL REFERENCES members(member_id),
          verified_identity_id BIGINT NOT NULL,
          auth_context_id      UUID NOT NULL UNIQUE,
          issued_auth_revision BIGINT NOT NULL CHECK (issued_auth_revision > 0),
          issued_at_epoch      BIGINT NOT NULL CHECK (issued_at_epoch >= 0),
          expires_at_epoch     BIGINT NOT NULL,
          revoked_at_epoch     BIGINT NULL CHECK (revoked_at_epoch >= 0),
          proof_ref            UUID NOT NULL UNIQUE,
          user_agent           VARCHAR(300) NULL,
          CHECK (expires_at_epoch > issued_at_epoch),
          FOREIGN KEY (verified_identity_id, member_id)
            REFERENCES member_verified_identities (identity_id, member_id),
          FOREIGN KEY (proof_ref, credential_hash, member_id, verified_identity_id, auth_context_id,
                       issued_auth_revision, issued_at_epoch, expires_at_epoch)
            REFERENCES member_session_issuance_receipts (proof_ref, credential_hash, member_id, verified_identity_id,
                       auth_context_id, issued_auth_revision, issued_at_epoch, expires_at_epoch)
        )
    """)
    op.execute("CREATE INDEX ix_member_verified_sessions_member ON member_verified_sessions (member_id, revoked_at_epoch)")

    # 가입 동의 -- 약관 문구 버전을 남긴다. 마케팅 등 선택 동의는 철회할 수 있다.
    op.execute("""
        CREATE TABLE member_consents (
          consent_id         BIGSERIAL PRIMARY KEY,
          member_id          BIGINT NOT NULL REFERENCES members(member_id),
          kind               VARCHAR(20) NOT NULL CHECK (kind IN ('terms','privacy','age14','marketing')),
          version            VARCHAR(40) NOT NULL CHECK (char_length(version) BETWEEN 1 AND 40),
          agreed_at_epoch    BIGINT NOT NULL CHECK (agreed_at_epoch >= 0),
          withdrawn_at_epoch BIGINT NULL CHECK (withdrawn_at_epoch >= 0),
          UNIQUE (member_id, kind, version)
        )
    """)

    # 로그인 시도 -- state · nonce · PKCE. 10분 · 한 번용. state·nonce 는 해시만. 공급자 토큰은 어디에도 두지 않는다.
    op.execute(f"""
        CREATE TABLE oauth_login_attempts (
          attempt_id       UUID PRIMARY KEY,
          provider         VARCHAR(20) NOT NULL CHECK (provider IN ('google','kakao','naver')),
          purpose          VARCHAR(10) NOT NULL DEFAULT 'login' CHECK (purpose IN ('login','link')),
          link_member_id   BIGINT NULL REFERENCES members(member_id),
          state_hash       VARCHAR(64) NOT NULL UNIQUE CHECK ({_HASH.format(c='state_hash')}),
          nonce_hash       VARCHAR(64) NOT NULL CHECK ({_HASH.format(c='nonce_hash')}),
          pkce_verifier    VARCHAR(128) NOT NULL CHECK (char_length(pkce_verifier) BETWEEN 43 AND 128),
          return_path      VARCHAR(300) NOT NULL DEFAULT '/mvp3/',
          created_at_epoch BIGINT NOT NULL CHECK (created_at_epoch >= 0),
          used_at_epoch    BIGINT NULL CHECK (used_at_epoch >= 0),
          CHECK ((purpose = 'link') = (link_member_id IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ix_oauth_login_attempts_created ON oauth_login_attempts (created_at_epoch)")

    # 동의 전 신원 -- 회원이 아니다. 10분 · 한 번용 · 하루 뒤 정리.
    op.execute(f"""
        CREATE TABLE member_join_pending (
          pending_id          UUID PRIMARY KEY,
          token_hash          VARCHAR(64) NOT NULL UNIQUE CHECK ({_HASH.format(c='token_hash')}),
          issuer_key          TEXT COLLATE "C" NOT NULL CHECK ({_KEY.format(c='issuer_key')}),
          issuer              TEXT NOT NULL CHECK ({_KEY.format(c='issuer')}),
          subject             TEXT COLLATE "C" NOT NULL CHECK ({_KEY.format(c='subject')}),
          verification_method TEXT NOT NULL,
          registration_ref    TEXT NOT NULL,
          verified_at_epoch   BIGINT NOT NULL CHECK (verified_at_epoch >= 0),
          display_nickname    VARCHAR(100) NULL,
          display_email       VARCHAR(255) NULL,
          return_path         VARCHAR(300) NOT NULL DEFAULT '/mvp3/',
          created_at_epoch    BIGINT NOT NULL CHECK (created_at_epoch >= 0),
          used_at_epoch       BIGINT NULL CHECK (used_at_epoch >= 0)
        )
    """)
    op.execute("CREATE INDEX ix_member_join_pending_created ON member_join_pending (created_at_epoch)")

    # 비회원 기록의 회원 귀속(설계 §6). handoffs 는 0042 부터 member_id 가 있다.
    op.execute("ALTER TABLE mvp3_saved_recommendations ADD COLUMN member_id BIGINT NULL REFERENCES members(member_id)")
    op.execute("CREATE INDEX ix_mvp3_saved_recommendations_member ON mvp3_saved_recommendations (member_id) WHERE member_id IS NOT NULL")
    op.execute("ALTER TABLE purchase_inquiries ADD COLUMN member_id BIGINT NULL REFERENCES members(member_id)")
    op.execute("CREATE INDEX ix_purchase_inquiries_member ON purchase_inquiries (member_id) WHERE member_id IS NOT NULL")


def downgrade() -> None:
    # 회원·세션·동의 기록이 한 줄이라도 있으면 되돌리지 않는다(기록 보존 -- 0145 와 같은 원칙).
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM member_verified_identities LIMIT 1)
         OR EXISTS (SELECT 1 FROM member_verified_sessions LIMIT 1)
         OR EXISTS (SELECT 1 FROM member_consents LIMIT 1)
         OR EXISTS (SELECT 1 FROM mvp3_saved_recommendations WHERE member_id IS NOT NULL LIMIT 1)
         OR EXISTS (SELECT 1 FROM purchase_inquiries WHERE member_id IS NOT NULL LIMIT 1)
      THEN RAISE EXCEPTION 'customer identity records must be preserved'; END IF; END $$""")
    op.execute("ALTER TABLE purchase_inquiries DROP COLUMN member_id")
    op.execute("ALTER TABLE mvp3_saved_recommendations DROP COLUMN member_id")
    op.execute("DROP TABLE member_join_pending")
    op.execute("DROP TABLE oauth_login_attempts")
    op.execute("DROP TABLE member_consents")
    op.execute("DROP TABLE member_verified_sessions")
    op.execute("DROP TABLE member_session_issuance_receipts")
    op.execute("DROP TABLE member_verified_identities")
    op.execute("ALTER TABLE members DROP CONSTRAINT ck_members_auth_pair, DROP COLUMN withdrawn_at, "
               "DROP COLUMN auth_revision, DROP COLUMN auth_subject")
