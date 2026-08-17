# -*- coding: utf-8 -*-
"""admin_operator_photos -- 운영자 프로필 사진을 담는 자리 (사장님 확정 2026-08-17 · 파일만 · 적용 보류).

■ 사장님이 확정한 넷 (2026-08-17) -- 이 파일이 그중 ①·④를 진다
    ① 사진 저장     **표를 하나 새로 만든다** (admin_operators 에 컬럼 추가가 «아니다»)
    ② 상단바 아바타  사진을 띄운다 (39개 공통 셸 -- 다음 물결)
    ③ 열람 범위     **전 운영자가 서로 본다**
    ④ 크기 상한     **1MB**
  근거·실측은 `docs/design/req/req-my-profile.md` §④-2.

■ ★ 왜 `admin_operators` 에 컬럼을 붙이지 않는가 -- 인증 경로가 그 표를 지난다
  `api/auth.py` `resolve_session()` 은 **모든 `/api/admin/*`·`/admin2/*` 요청**이 지나는
  자리이고 매 요청 `admin_operators` 를 조인한다. 같은 표에 이미지 바이트를 두면
  언젠가 `SELECT *` 한 줄이 **인증 경로에서 이미지까지 함께 읽는다** -- 요청마다,
  전 화면에서. 표를 나누는 이유가 이것 하나다(성능이 아니라 «사고를 못 나게» 하는 것).
  ⚠ 이 판단은 코드가 아니라 스키마가 지켜야 한다. 컬럼이 없으면 실수할 수 없다.

■ ★ 왜 파일시스템이 아니라 DB 인가 (정의서 §저장 위치 판정 -- 세 후보 실측 비교)
  · 배포 서버는 `deploy/popcorn-api.service` 가 `ProtectSystem=strict` +
    `ReadWritePaths=/srv/popcorn-ai/.cache` **한 곳** + `PrivateTmp=true` 다 --
    새 경로를 쓰려면 systemd 유닛을 고쳐야 하고 `/tmp` 는 재시작마다 비워진다.
  · **백업 대상이 DB 뿐이다**(`deploy/RESTORE.md` 전문에 파일·업로드 언급 0건).
    파일로 두면 **사진만 백업 밖에 남는다** -- 자동 백업 7건 + PITR 7일이 안 닿는다.
  · 크기: 운영자 18명 × 1MB = **최대 18MB**. 상품 22,000행대를 담은 DB 에서 무시할 수 있다.
    「이미지가 DB 를 무겁게 한다」는 일반론은 맞지만 **이 규모에서는 성립하지 않는다.**
  외부 저장소는 전례 0건 + 자격증명이 하나 늘어(`.env` 만 허용 · CANON §2-5) 기각.

■ 컬럼 -- 정의서 제안 여섯을 그대로 쓴다(새로 지어내지 않았다)
  · `operator_id`  **PK 이자 FK** -- 1:1 이 스키마로 강제된다. 한 사람 한 장(사장님 확정).
    교체는 UPDATE 다 -- 과거 사진을 쌓지 않는다(§아래 「사진은 원장이 아니다」).
  · `content_type` **서버가 앞머리로 판정한 값**을 넣는다. 클라이언트가 보낸
    `Content-Type` 도, 확장자도 넣지 않는다 -- 지금 `provider` 를 그대로 믿어 신원
    검증이 없는 것과 «같은 부류의 실수»를 반복하지 않는다.
  · `bytes` BYTEA -- 원본 그대로. 재인코딩(EXIF 제거·크기 정규화)은 **하지 않는다**:
    저장소에 이미지 라이브러리가 없고(실측: `requirements.txt` 전수 · `.venv` 에 PIL 미설치)
    사장님이 새 의존성을 늘리지 말라 하셨다. 그 사실은 API 코드 주석에도 남긴다.
  · `byte_size` -- 조회·표시용. **`bytes` 를 읽지 않고** 크기를 알기 위한 자리다.
  · `uploaded_at` -- 교체 시각. **ETag 의 근거**이기도 하다(아래 참조).
  · `uploaded_by` -- 누가 넣었나. 오늘은 언제나 `operator_id` 와 같다(본인만 등록).
    ⚠ **owner 가 남의 사진을 대신 등록·삭제할 수 있는지는 «미정»이다**(정의서 결정대기 ⑤ --
    사장님은 「전 운영자 열람」만 답하셨다). 대행을 **짓지 않았다.** 이 컬럼은 그때를
    위해 미리 만든 것이 아니라, **오늘도 「누가 한 일인가」에 답해야 하기 때문이다** --
    자기 자신이라는 답도 답이다.

■ ★ CHECK 는 «불변식»만 건다 -- 정책값은 걸지 않는다
  · `octet_length(bytes) = byte_size` -- **크기가 거짓말을 못 하게** 한다. 이건 언제나
    참이어야 하는 사실이라 스키마의 일이다.
  · **1MB 상한은 CHECK 로 걸지 «않았다».** 그것은 사장님이 정한 «정책»이고 나중에 올릴 수
    있다(정의서 결정대기 ②: 「값 자체는 나중에 올릴 수 있다」). 스키마에 박으면 값을
    바꿀 때마다 마이그레이션이 필요하고, **같은 수가 코드와 DB 두 곳에 살아 언젠가
    어긋난다** -- 이 저장소가 「문서에 수를 박아」 여러 번 당한 바로 그 병이다.
    단일 원천은 `api/admin_profile_photo.MAX_PHOTO_BYTES` 하나다.
  · **허용 형식 3종도 CHECK 로 걸지 않았다.** 같은 이유다(목록이 두 곳에 살면 한쪽만 고친다).
    판정 원천은 `api/admin_profile_photo._sniff()` 하나다.

■ ★ ON DELETE CASCADE -- 사진은 계정에 딸린 «개인 자료»다
  0051(`admin_operator_devices`)은 CASCADE 없이 참조한다. 여기서 다르게 하는 이유:
  ㉠ 계정을 지웠는데 사진이 남으면 **필요 없어진 개인정보를 계속 보관**하는 것이다 --
     `docs/06_db-erd.md` §3.9 「우리가 갖지 않은 정보는 유출될 수 없다」에 정면으로 어긋난다.
  ㉡ CASCADE 가 없으면 사진이 있는 계정은 **삭제 자체가 FK 로 막힌다.** 슬라이스 78 에서
     실제로 운영자 계정을 지운 전례가 있다 -- 그때 사진이 있었다면 못 지웠다.
  ⚠ `uploaded_by` 는 CASCADE 를 걸지 «않았다». 남이 대신 올린 뒤 그 사람 계정이 지워졌다고
    **사진 자체가 사라지면 안 된다.** 그 자리는 `ON DELETE SET NULL` 이다 -- 「누가 했는지
    모르게 됐다」는 사실을 NULL 이 말한다(`identity_reasons()` 가 승인자 삭제를
    「계정 삭제됨」으로 말하는 것과 같은 결).

■ ★ 사진은 원장이 아니다 -- 삭제하면 «실제로» 지운다 (정의서 판정)
  원장·되돌림 규약(CANON §2-2·2-4)이 지키는 것은 **「사실의 이력」**이다 -- 재고가 어떻게
  움직였는지, 세션이 언제 열려 있었는지. **프로필 사진은 그런 사실이 아니라 본인의 개인
  자료다.** 그래서 이 표에는 `revoked_at`·`deleted_at` 이 «없다» -- 삭제는 DELETE 다.
  **다만 행위는 남긴다**: 「누가 언제 등록·교체·삭제했다」를
  `admin_operator_activity_logs` 에 적는다(`operator_photo_set`·`operator_photo_delete`).
  **비밀번호와 같은 결이다** -- 원문은 안 남기고 `password_set_at` 과 활동 로그는 남는다.
  즉 **자료는 지우고 사실은 남긴다.**

■ ⚠ 인덱스를 따로 만들지 않았다
  조회는 언제나 `WHERE operator_id = :id` 단건이고 그것이 PK 다. 목록 조회 경로가 없다
  (39개 셸이 아바타를 그릴 때도 자기 것 1건 · 남의 것 1건씩 부른다).

■ ⚠⚠ 이 마이그레이션은 파일만 만든다 -- DB 에 적용하지 않는다 (DBA 소관)
  0055~0059 와 같다. 사장님 지시 원문: 「마이그레이션 파일 -- 만들기만 하고 적용하지 마라」.
  적용 전에는 API 4본이 **503 `photo_schema_missing`** 으로 «이유 있는 실패»를 준다 --
  「사진 없음」(404)과 **구분한다**(적용 안 된 것을 「없다」고 말하면 그게 지어낸 사실이다).

■ downgrade -- **비어 있으면 지우고, 사진이 쌓였으면 남긴다**
  0059 가 환율에 쓴 판단을 그대로 적용한다: 「다시 만들 수 있는 값인가」.
  **사진은 사람이 자기 파일에서 올린 것이고 우리에게 재생성 경로가 없다** -- 지우면 끝이다.
  0055(인덱스만 걷음) · 0056(표를 남김) · 0057(지움)이 갈렸던 기준도 이것 하나였다.
  그래서 판단을 사람에게 미루지 않고 **되돌리는 시점의 사실로 스스로 정한다.**

Revision ID: 0060
Revises: 0059
"""
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS admin_operator_photos (
            operator_id  BIGINT      PRIMARY KEY
                         REFERENCES admin_operators (operator_id) ON DELETE CASCADE,
            content_type VARCHAR(32) NOT NULL,
            bytes        BYTEA       NOT NULL,
            byte_size    INTEGER     NOT NULL,
            uploaded_at  TIMESTAMP   NOT NULL DEFAULT now(),
            uploaded_by  BIGINT      REFERENCES admin_operators (operator_id) ON DELETE SET NULL,
            CONSTRAINT ck_admin_operator_photos_size
                CHECK (byte_size > 0 AND byte_size = octet_length(bytes))
        );

        COMMENT ON TABLE admin_operator_photos IS
            '운영자 프로필 사진 1:1 - admin_operators 와 분리한다. resolve_session() 이 매 요청 그 표를 조인하므로 이미지 바이트가 인증 경로에 딸려 오면 안 된다';
        COMMENT ON COLUMN admin_operator_photos.content_type IS
            '서버가 파일 앞머리(magic bytes)로 판정한 값. 클라이언트가 보낸 Content-Type 도 확장자도 믿지 않는다';
        COMMENT ON COLUMN admin_operator_photos.byte_size IS
            'bytes 를 읽지 않고 크기를 알기 위한 자리. CHECK 로 octet_length(bytes) 와 일치가 강제된다';
        COMMENT ON COLUMN admin_operator_photos.uploaded_at IS
            '교체 시각. ETag 의 근거이기도 하다 - 바이트를 읽지 않고 조건부 GET 에 답한다';
        COMMENT ON COLUMN admin_operator_photos.uploaded_by IS
            '누가 넣었나. 오늘은 언제나 operator_id 와 같다(본인만 등록). 그 계정이 지워지면 NULL 이 된다';
    """)


def downgrade() -> None:
    # 판단을 코드에 적는다(위 docstring 참조): 사진이 쌓였으면 남기고, 비어 있으면 지운다.
    # 사진은 사람이 자기 파일에서 올린 것이라 우리에게 재생성 경로가 없다.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM admin_operator_photos) THEN
                DROP TABLE admin_operator_photos;
            ELSE
                RAISE NOTICE 'admin_operator_photos: 등록된 사진이 있어 표를 남깁니다(올린 원본을 다시 만들 수 있는 경로가 없습니다)';
            END IF;
        END $$;
    """)
