# -*- coding: utf-8 -*-
"""0096: 소프트웨어(프로그램) 카탈로그 표 신설 — software / software_community_spec

■ 왜 games 에 합치지 않고 새 표를 만드나

조사 산출물 `software_catalog.json`(42종)을 기존 `games`(15컬럼)에 얹어 보면
games 에 없는 필드가 12개 필요하다(min_vram_gb·min_storage_gb·min_os·bottleneck·
license_type·vendor 등). 반대로 games 의 genre·popularity_rank·mapping_skip_reason 은
소프트웨어에서 의미가 다르다. 합치면 어느 행에서든 절반이 NULL 인 표가 되고,
그 NULL 이 '해당 없음'인지 '아직 못 찾음'인지 구분할 수 없게 된다.
(근거 상세: D:/Hermes-Workspace/software_schema_proposal.md §2)

조회 패턴도 다르다. 게임은 타이틀 1개 -> 사양 1쌍(1:1)이지만,
소프트웨어는 "영상편집" 한마디에 프리미어·애프터이펙트·포토샵이 같이 걸린다 —
category 단위 집계가 1차 조회다.

단, 컬럼 이름은 games 와 최대한 맞췄다(name·official_source_url·min_cpu·min_gpu·
min_ram_gb·rec_cpu·rec_gpu·rec_ram_gb·checked_date·note·description).
두 표를 같은 방식으로 읽을 수 있게 하기 위해서다.

■ 출처 URL 을 jsonb 로 둔 이유

제안서는 `software_community_source(spec_id, url)` 자식 표와 jsonb 한 컬럼을
둘 다 허용했다. 하네스 확정: 표 3개는 과하므로 jsonb 한 컬럼으로 둔다.
`usage_floors.match_terms` 가 이미 jsonb 라 프로젝트 관례에도 어긋나지 않는다.

■ popularity_note 가 왜 숫자가 아니라 text 인가

`games.popularity_rank` 는 integer 인데 실측 결과 23행 전부 NULL 이었다.
소프트웨어도 이번 조사에서 신뢰할 만한 정량 점유율을 단 한 건도 확보하지 못했다.
숫자 컬럼을 만들어 두면 다음 사람이 근거 없는 숫자를 채워넣는다.
"정량 수치는 확인 못함" 이라는 서술을 그대로 담는 text 가 정직하다.

■ spec_gap_reason 이 왜 필요한가

42종 중 공식 RAM 수치가 아예 없는 것이 15종인데 이유가 제각각이다.
Figma 는 공식이 하드웨어 수치를 아예 공개하지 않는다(영원히 안 채워짐).
Android Studio 는 공식 페이지가 302 리다이렉트였다(재조사하면 채워진다).
구분 없이 NULL 만 남기면 다음 사람이 같은 헛수고를 반복한다.

■ 이 마이그레이션이 하지 않는 것

usage_floors 는 건드리지 않는다. 제안서 §4 의 'usage_floors 에 VRAM 조건 신설'
'개발/방송/음악 usage_key 신설' 은 견적 기획과 함께 결정할 사안이라 이번 범위 밖이다.
이 표는 그 결정의 '근거 데이터'를 담아 두는 자리까지만 한다.

Revision ID: 0096
Revises: 0095
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0096"
down_revision = "0095"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "software",
        sa.Column("software_id", sa.Integer, primary_key=True),
        # -- 정체성 (games 대응: name) --
        sa.Column("name", sa.String(120), nullable=False,
                  comment="한글명. 예 '어도비 프리미어 프로'"),
        sa.Column("name_en", sa.String(160), nullable=True,
                  comment="영문명. 검색/매칭용"),
        sa.Column("category", sa.String(40), nullable=False,
                  comment="사무.문서/영상편집/사진.디자인/3D.설계/개발/AI/방송.스트리밍/음악/사무보조"),
        sa.Column("vendor", sa.String(80), nullable=True),
        sa.Column("official_source_url", sa.Text, nullable=True,
                  comment="공식 요구사양 페이지. 1순위 근거"),
        # -- 최소사양 --
        sa.Column("min_cpu", sa.Text, nullable=True),
        sa.Column("min_gpu", sa.Text, nullable=True),
        sa.Column("min_ram_gb", sa.Integer, nullable=True),
        sa.Column("min_vram_gb", sa.Integer, nullable=True),
        sa.Column("min_storage_gb", sa.Integer, nullable=True),
        sa.Column("min_os", sa.String(120), nullable=True),
        # -- 권장사양 --
        sa.Column("rec_cpu", sa.Text, nullable=True),
        sa.Column("rec_gpu", sa.Text, nullable=True),
        sa.Column("rec_ram_gb", sa.Integer, nullable=True),
        sa.Column("rec_vram_gb", sa.Integer, nullable=True),
        sa.Column("rec_storage_gb", sa.Integer, nullable=True),
        # -- 상담용 --
        sa.Column("description", sa.Text, nullable=True,
                  comment="고객이 읽는 2~3문장 소개"),
        sa.Column("bottleneck", sa.String(16), nullable=True,
                  comment="cpu/gpu/ram/vram/balanced. 조사 분포는 CPU중심 17 / RAM중심 11 / "
                          "VRAM중심 6 / 균형 5 / GPU중심 2 — CPU중심이 최다다. 지금 usage_floors 는 "
                          "GPU 와트와 RAM 위주라 '고클럭 CPU 가 답이고 GPU 는 필요없는' 용도를 "
                          "표현할 수단이 없다. 이 컬럼이 그 근거가 된다."),
        sa.Column("bottleneck_note", sa.Text, nullable=True),
        sa.Column("license_type", sa.String(120), nullable=True,
                  comment="구독형/매입형/무료 등. 실측 최장 43자('무료(Community) + "
                          "유료(Professional/Enterprise)') 라 넉넉히 잡는다"),
        sa.Column("price_note", sa.Text, nullable=True),
        sa.Column("popularity_note", sa.Text, nullable=True,
                  comment="수치가 아니라 서술. 정량 점유율을 확보하지 못했다 - 머리 주석 참조"),
        # -- 데이터 품질 --
        sa.Column("confidence", sa.String(40), nullable=False,
                  comment="'확인' / '추정'"),
        sa.Column("spec_gap_reason", sa.Text, nullable=True,
                  comment="왜 값이 NULL 인지. games.mapping_skip_reason 대응"),
        sa.Column("source_urls", postgresql.JSONB, nullable=True,
                  comment="근거 URL 배열. 표를 더 만들지 않고 jsonb 로 둔다 - 머리 주석 참조"),
        sa.Column("checked_date", sa.Date, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.UniqueConstraint("name", name="software_name_key"),
    )
    op.create_index("ix_software_category", "software", ["category"])
    op.create_index("ix_software_bottleneck", "software", ["bottleneck"])
    op.create_index("ix_software_confidence", "software", ["confidence"])

    # 커뮤니티 권장치는 공식 권장치와 '다른 종류의 근거'다. 같은 행에 섞으면
    # 어느 쪽 근거로 견적이 나갔는지 추적할 수 없어 자식 표로 분리한다.
    #
    # source_type 을 둔 이유: Puget Systems 는 워크스테이션 판매사라 수치가 높게 나온다
    # (프리미어 1080p 최소 RAM 64GB 같은 값). 레딧 실사용자 의견과 같은 무게로 취급하면
    # 과잉 견적이 된다. 출처 종류를 구분해 두면 나중에 가중치를 다르게 줄 수 있다.
    #
    # spec_key 는 '데이터'가 아니라 '멱등 적재용 구조 키'다. 이번 조사는 프로그램당
    # 커뮤니티 종합 1행이라 loader 가 'aggregate' 를 넣는다. 나중에 출처 갈래별로
    # 여러 행을 둘 때 ('reddit' / 'puget' 등) 같은 키로 UPSERT 하면 된다.
    # source_type 을 유니크 키로 쓰지 않은 이유: 이번 데이터에서 값이 없어 NULL 인데
    # Postgres 의 UNIQUE 는 NULL 을 중복으로 보지 않아 재실행 때 행이 늘어난다(멱등성 깨짐).
    op.create_table(
        "software_community_spec",
        sa.Column("spec_id", sa.Integer, primary_key=True),
        sa.Column("software_id", sa.Integer,
                  sa.ForeignKey("software.software_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("spec_key", sa.String(40), nullable=False,
                  server_default="aggregate",
                  comment="멱등 적재용 구조 키. 조사 단위 1건이면 'aggregate'"),
        sa.Column("ram_gb", sa.Integer, nullable=True),
        sa.Column("vram_gb", sa.Integer, nullable=True),
        sa.Column("note", sa.Text, nullable=True,
                  comment="무엇이 어떻게 갈리는지 + 표본 수 병기"),
        sa.Column("source_type", sa.String(24), nullable=True,
                  comment="forum(레딧/퀘이사존) / benchlab(Puget) / blog"),
        sa.Column("sample_size", sa.Integer, nullable=True,
                  comment="참조한 게시물 수"),
        sa.Column("source_urls", postgresql.JSONB, nullable=True),
        sa.UniqueConstraint("software_id", "spec_key",
                            name="software_community_spec_key"),
    )
    op.create_index("ix_software_community_spec_software",
                    "software_community_spec", ["software_id"])


def downgrade():
    op.drop_index("ix_software_community_spec_software",
                  table_name="software_community_spec")
    op.drop_table("software_community_spec")
    op.drop_index("ix_software_confidence", table_name="software")
    op.drop_index("ix_software_bottleneck", table_name="software")
    op.drop_index("ix_software_category", table_name="software")
    op.drop_table("software")
