# -*- coding: utf-8 -*-
"""요청 · 승인(ADM-SYS-060 · 제안) — 직원 요청/하네스 판단/사장님 결재를 담는 표 셋.

■ 왜 새 표가 필요한가 — 기존 셋으로는 안 된다(요구사항 정의서 §④ 실측)
    admin_operator_activity_logs   append-only 원장이라 「지금 상태」 컬럼이 없다.
                                    상태를 알려면 로그를 되짚어야 한다 — 목록·레인
                                    화면이 매 렌더 그 계산을 다시 해야 해서 못 쓴다.
    dash_memos                     1회 소비형 큐다(used_at/used_count). 상태 축·
                                    스레드(댓글)가 없다 — 성격이 다르다.
    product_reviews                상품 사양 검수 전용. 그리고 **이 표의 반려 방식이
                                    바로 이번에 피해야 할 반례다**(바로 아래 참조).

■ ★ 반려는 「보류 + 텍스트」가 아니라 별도 상태 + 전용 컬럼이다
  `product_reviews`의 반려는 `review_status='보류'` + `detail`에 `[반려 사유: …]`를
  이어붙이는 방식이었다(`api/admin_reviews.py` `_default_reject_reason` 부근). 그 결과
  **반려와 보류를 셀 수 없었고 실제 사용 0건**이었다(요구사항 정의서 §상태값 실측).
  여기서는 `status='반려'`가 독립 값이고 `reject_reason`이 전용 컬럼이다 — 그리고
  아래 CHECK가 **사유 없는 반려를 스키마 수준에서 막는다**(애플리케이션이 막는 것과
  별개로, DB 자체가 그 사실을 지킨다 — `admin_operator_photos`의 `byte_size` CHECK와
  같은 판단: 참이어야 하는 사실은 스키마가 진다).

■ 상태 여덟 — CHECK로 건다(단일 원천은 이 CHECK와 `api/admin_requests.py`의
  `STATUSES` 상수 «둘»이다. `review_status`류는 CHECK가 없어 문서와 실제가 갈리기
  쉬웠다 — 여기서는 상태 자체가 이 화면의 핵심 계약이라 스키마도 함께 지키게
  했다). **새 상태를 늘릴 때는 이 CHECK와 `api/admin_requests.py` 양쪽을 함께
  고친다** — 하나만 고치면 그 순간부터 둘이 갈린다.
    접수 → 검토 → 처리(하네스가 「작은 것」으로 보고 바로 고침) → 완료
                → 결재대기(하네스가 「큰 것」으로 봄) → 승인 → (하네스가 고침) → 완료
                                                    → 반려(사유 필수)
                                                    → 보류

■ 캡처는 세 번째 표로 뺐다 — 정의서는 「표 둘」이라 했지만 「여러 장」이 그 전제를 깬다
  정의서 §④는 요청·댓글 «둘»만 꼽았지만, 같은 절에서 캡처를 **「이미 있는 방식」**
  (`api/admin_profile_photo.py` — `admin_operators`가 아니라 `admin_operator_photos`로
  뺀 이유가 「인증 경로가 매 요청 그 표를 조인하기 때문」)을 그대로 쓰라고 못박았다.
  그 표는 1:1(사람 한 명 = 사진 한 장)이라 PK가 `operator_id` 자체였다. 여기는
  **한 요청에 여러 장**(디자인 원안 「캡처 1 · 캡처 2」)이 붙으므로 1:1로 못 담는다 —
  `admin_requests`에 BYTEA 배열/컬럼을 늘리는 대신, 같은 판단(바이트를 본체 표에서
  뗀다)을 다시 적용해 **자식 표**로 만들었다. 「표 둘」을 어긴 것이 아니라 「여러 장」
  요구를 같은 원칙으로 만족시킨 결과다 — 근거는 제작 보고서에도 남긴다.

■ 캡처 한도는 스키마에 박지 않는다 — 결정 3 은 2026-08-27 사장님이 3MB 로 확정했다
  (1920×1080 화면 캡처가 흔히 1~3MB 라 1MB 에서는 직원이 올리다 막혔다). 그래도 스키마에
  CHECK 로 걸지 않는 판단은 그대로다 — `admin_operator_photos`가 1MB CHECK 를 걸지 않은
  것과 같은 이유(정책값은 나중에 또 바뀔 수 있고, 바뀔 때마다 마이그레이션이 필요해지면
  안 된다). 단일 원천은 `api/admin_requests.py`의 `CAPTURE_MAX_BYTES`(환경변수
  `WORK_REQUEST_CAPTURE_MAX_BYTES`, 기본 3MB) 하나다 — 화면은 `GET /api/admin/requests/meta`
  로 그 값을 받아 말한다. 형식 판정(매직넘버 JPEG/PNG/WebP·SVG 명시 거부)도 같은 이유로
  `_sniff()`(`api/admin_profile_photo.py`)를 그대로 재사용한다 — 새로 궁리하지 않는다.
  ⚠ 「내 정보」 프로필 사진의 1MB 는 별개 정책이라 이 결정과 무관하게 그대로 둔다.

■ target_screen은 라벨을 저장하지 않고 경로(href)만 저장한다
  `api/admin_nav.NAV`가 라벨의 단일 원천이다(CANON §1). 라벨까지 이 표에 저장하면
  나중에 메뉴 라벨이 바뀔 때 이 표의 옛 라벨만 남아 두 표기가 갈린다 — 그래서
  `target_screen_href`만 저장하고, 표시 라벨은 응답을 만들 때마다 NAV에서 새로 찾는다
  (화면이 사라졌으면 href만 보여준다 — 지어내지 않는다).

■ author_kind(댓글 스레드의 화자) — 「하네스」 표시는 owner 세션만 붙일 수 있다
  이 시스템에 「하네스」라는 로그인 주체가 없다(결정 5 「하네스 알림 수단」이 아직
  미정이라 그 정체성 자체가 안 만들어졌다). 운영자 등급이 스스로 「나는 하네스다」라고
  주장하게 두면 신원을 자칭하는 것을 믿는 게 된다(`api/admin_profile_photo.py` 모듈
  docstring이 이미 짚은 실수 — 「클라이언트가 보낸 값을 믿지 않는다」와 같은 결).
  그래서 `author_kind`는 기본적으로 호출자의 실제 등급에서 파생한다(owner→사장님,
  그 외→직원)이고, **owner 세션만** 댓글을 「하네스」로 표시할 수 있다(대개는 owner
  세션으로 동작하는 도구·스크립트가 하네스의 답을 대신 옮기는 경우를 위해서다).
  운영자(직원) 등급은 이 표시를 바꿀 수 없다 — 권한 상승이 아니라 «표시 라벨»
  이지만, 그 라벨조차 자칭하게 두지 않는다.

Revision ID: 0070
Revises: 0069
"""
from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS admin_requests (
            request_id        BIGSERIAL PRIMARY KEY,
            title              VARCHAR(200) NOT NULL,
            body               TEXT NOT NULL,
            target_screen_href VARCHAR(200),
            urgency            VARCHAR(20),
            status             VARCHAR(20) NOT NULL DEFAULT '접수',
            verdict            VARCHAR(10),
            verdict_note       TEXT,
            result_note        TEXT,
            reject_reason      TEXT,
            hold_reason        TEXT,
            created_by         BIGINT NOT NULL REFERENCES admin_operators (operator_id),
            created_at         TIMESTAMP NOT NULL DEFAULT now(),
            updated_at         TIMESTAMP NOT NULL DEFAULT now(),
            decided_by         BIGINT REFERENCES admin_operators (operator_id) ON DELETE SET NULL,
            decided_at         TIMESTAMP,
            resolved_at        TIMESTAMP,
            cancelled_at       TIMESTAMP,
            CONSTRAINT ck_admin_requests_status CHECK (status IN
                ('접수', '검토', '처리', '결재대기', '승인', '반려', '보류', '완료', '취소')),
            CONSTRAINT ck_admin_requests_verdict CHECK (verdict IS NULL OR verdict IN ('작은 것', '큰 것')),
            -- ★ 반려는 사유가 없으면 성립하지 않는다 — 스키마가 그 사실을 진다.
            CONSTRAINT ck_admin_requests_reject_reason
                CHECK (status <> '반려' OR reject_reason IS NOT NULL)
        );
        CREATE INDEX idx_admin_requests_status ON admin_requests (status, updated_at DESC);
        CREATE INDEX idx_admin_requests_creator ON admin_requests (created_by, created_at DESC);

        COMMENT ON TABLE admin_requests IS
            '요청 · 승인(ADM-SYS-060). 직원이 올리고 하네스가 판단하고 사장님이 결재하는 자리 — 「지금 상태」가 있어야 해서 append-only 활동 로그로는 못 담는다';
        COMMENT ON COLUMN admin_requests.target_screen_href IS
            'api/admin_nav.NAV 의 href. 라벨은 저장하지 않는다 — 표시할 때마다 NAV 에서 새로 찾는다(단일 원천이 갈리지 않게)';
        COMMENT ON COLUMN admin_requests.verdict IS
            '하네스 판정 — 작은 것(바로 고침)/큰 것(결재 상신). 그 근거는 verdict_note 에';
        COMMENT ON COLUMN admin_requests.verdict_note IS
            '왜 그렇게 판단했는지 — 이게 없으면 사장님이 결재를 판단할 재료가 없다(요구사항 정의서 §8)';
        COMMENT ON COLUMN admin_requests.result_note IS
            '처리 결과 — 무엇을 고쳤는지 · 배포 여부 · 커밋. 완료로 전이할 때만 채워진다. 실패 사유는 댓글 스레드에 남는다(완료로 만들지 않으므로 이 컬럼은 비워 둔다)';
        COMMENT ON COLUMN admin_requests.reject_reason IS
            '반려 사유 — status=반려 이면 NOT NULL 이 CHECK 로 강제된다. product_reviews 의 반려(보류+텍스트, 실사용 0건)를 반복하지 않는다';

        CREATE TABLE IF NOT EXISTS admin_request_comments (
            comment_id  BIGSERIAL PRIMARY KEY,
            request_id  BIGINT NOT NULL REFERENCES admin_requests (request_id) ON DELETE CASCADE,
            author_id   BIGINT NOT NULL REFERENCES admin_operators (operator_id),
            author_kind VARCHAR(10) NOT NULL DEFAULT '직원',
            body        TEXT NOT NULL,
            created_at  TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT ck_admin_request_comments_kind CHECK (author_kind IN ('직원', '사장님', '하네스'))
        );
        CREATE INDEX idx_admin_request_comments_request
            ON admin_request_comments (request_id, created_at);

        COMMENT ON TABLE admin_request_comments IS
            '요청 스레드 — 직원 · 하네스 · 사장님이 같은 자리에서 주고받는다. author_kind=하네스 표시는 owner 세션만 붙일 수 있다(api/admin_requests.py, 자칭 금지)';

        CREATE TABLE IF NOT EXISTS admin_request_captures (
            capture_id   BIGSERIAL PRIMARY KEY,
            request_id   BIGINT NOT NULL REFERENCES admin_requests (request_id) ON DELETE CASCADE,
            seq          INTEGER NOT NULL,
            content_type VARCHAR(32) NOT NULL,
            bytes        BYTEA NOT NULL,
            byte_size    INTEGER NOT NULL,
            uploaded_at  TIMESTAMP NOT NULL DEFAULT now(),
            uploaded_by  BIGINT REFERENCES admin_operators (operator_id) ON DELETE SET NULL,
            CONSTRAINT ck_admin_request_captures_size
                CHECK (byte_size > 0 AND byte_size = octet_length(bytes))
        );
        CREATE UNIQUE INDEX ux_admin_request_captures_seq
            ON admin_request_captures (request_id, seq);

        COMMENT ON TABLE admin_request_captures IS
            '요청 캡처 — admin_operator_photos 와 같은 원칙(BYTEA, 매직넘버 판정, SVG 거부)을 재사용한다. 1:1이 아니라 1:N 이라 별도 표로 뺐다(한 요청에 여러 장)';
        COMMENT ON COLUMN admin_request_captures.content_type IS
            '서버가 파일 앞머리(magic bytes)로 판정한 값 — api/admin_profile_photo._sniff() 재사용. 클라이언트가 보낸 Content-Type·확장자는 믿지 않는다';
        COMMENT ON COLUMN admin_request_captures.byte_size IS
            'bytes 를 읽지 않고 크기를 알기 위한 자리. CHECK 로 octet_length(bytes) 와 일치가 강제된다';
    """)


def downgrade() -> None:
    # 셋 다 이 화면 전용이라 서로만 참조한다(CASCADE로 이미 얽혀 있다) — 역순으로 지운다.
    # 사진(admin_operator_photos)과 달리 "쌓였으면 남긴다" 판단을 적용하지 않는다:
    # 이 표들은 개인 자료가 아니라 이 화면의 작업 원장이라, 화면 자체를 되돌리는
    # downgrade라면 데이터도 함께 되돌리는 것이 맞다(운영에 실제로 쌓인 뒤 downgrade를
    # 쓸 상황이면 그 판단은 이 마이그레이션이 아니라 그 시점의 사람이 한다).
    op.execute("""
        DROP TABLE IF EXISTS admin_request_captures;
        DROP TABLE IF EXISTS admin_request_comments;
        DROP TABLE IF EXISTS admin_requests;
    """)
