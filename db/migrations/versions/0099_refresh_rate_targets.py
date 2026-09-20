# -*- coding: utf-8 -*-
"""0099: 게임 목표 주사율(고객 기준) 컬럼 + 주사율<->필요 GPU 대응표 신설

■ 왜 기존 rec_target_fps / min_target_fps 를 쓰지 않는가

  기존 두 칸은 **공식 사양표가 말하는 목표**다(스팀/공식 홈페이지 권장사양 원문에서
  기계 추출한 값 - 0097 참조). 대부분 60 이다.
  이번에 들어오는 값은 **실제 고객이 원하는 목표**다(프로 세팅 / 대회 규격 /
  커뮤니티 표준 세팅). 롤은 공식 사양표에 60 이라 적혀 있지만 고객이 원하는 건
  240 이다. 같은 칸에 넣으면 둘 중 하나가 사라진다 -> 칸을 새로 판다.
  기존 컬럼은 하나도 고치지 않는다(추가만).

■ competitive_fps_target 과 typical_monitor_hz 를 왜 분리하는가 (★중요)

  조사에서 나온 핵심 발견: **철권8 · 스트리트파이터6 은 fps 목표가 60 인데
  모니터는 240Hz 가 유리하다.** 두 격투게임 모두 엔진이 60fps 고정이라 프레임을
  더 뽑을 수 없지만, 240Hz 패널은 스캔아웃 지연이 짧아 입력지연이 줄어든다.
  이 둘을 한 칸으로 합치면 "60fps 게임이니 60Hz 모니터면 된다"는 틀린 견적이
  나온다. 그래서 'GPU 가 뽑아야 할 fps'(competitive/comfortable/minimum)와
  '모니터가 가져야 할 Hz'(typical_monitor_hz / esports_standard_hz)를 끝까지
  분리해 둔다.

■ 신뢰도는 왜 또 새 칸인가

  games.confidence  = 공식 사양표 출처 신뢰도 (0073~0097 계열, 86종 전부 채워짐)
  games.community_confidence = 커뮤니티 실사용 보강분 신뢰도 (0098)
  games.refresh_confidence   = 주사율 조사 신뢰도 (이 마이그레이션)
  셋은 서로 다른 조사 건의 신뢰도라 덮으면 앞의 정보가 사라진다.
  값: '확인'(23) | '2차출처'(35) | '추정'(28).
  '추정' 28건은 값을 지어낸 것이 아니라 **장르 기준을 준용**한 것이고
  refresh_selection_note 에 "전용 근거 없음"이 적혀 있다. 지우지 않고 표시해
  싣는다 - 견적 엔진이 신뢰도로 걸러 쓸 수 있게.

■ source_urls: 자식표 대신 jsonb 를 고른 이유

  0097 이 games.source_urls / community_source_urls 를 이미 jsonb 로 두었다.
  주사율만 자식표로 가면 같은 성격의 값이 두 가지 모양으로 흩어진다.
  URL 단위 조인/집계 요구가 아직 없으므로 기존 관례(jsonb)를 따른다.
  selection_note 는 "왜 롤이 240 인가"를 되짚는 유일한 근거라 **반드시** 보관한다
  (refresh_selection_note, text - 자르지 않는다).

■ refresh_gpu_requirement - workload 축이 핵심이다

  같은 FHD 240Hz 라도
    경쟁게임(롤/발로란트/오버워치) -> RTX 5060 Ti 급이면 산다
    AAA 최고옵션               -> RTX 5090 으로도 네이티브 불가, VRR 구간
  이다. 해상도 x 주사율만으로 키를 잡으면 둘 중 하나는 반드시 틀린 답이 된다.
  그래서 PK 에 workload 를 넣는다.

    workload  : 'AAA' | 'COMPETITIVE'
    criterion : 'native_full'(측정 평균 fps >= 목표 Hz)
                'vrr80'      (측정 평균 fps >= 목표 Hz x 0.8, VRR 구간)
                'community'  (커뮤니티 견적 합의 - 경쟁게임 칸의 근거 형태)
  AAA 는 같은 조합에 native_full / vrr80 두 기준이 동시에 존재하므로
  criterion 도 키에 넣는다.

  verdict 는 (해상도, 주사율) 조합의 결론이고 quote_claim 은 그걸 견적서에
  그대로 쓰는 문장이다. 두 값은 조합 단위라 각 행에 같은 값이 반복된다 -
  조회처가 행 하나만 읽고도 문장을 만들 수 있게 하려는 의도적 비정규화다.

  source_urls 는 NOT NULL 이다. 근거 없는 GPU 권장은 견적서에 그대로 나가면
  고객에게 하는 거짓말이 된다 - 적재 도구도 출처 없는 행은 INSERT 하지 않는다.

■ 모니터 주사율 자체는 새로 적재하지 않는다

  product_specs.refresh_hz 가 이미 2,104 행 채워져 있고
  products.spec_source_text 에 '주사율 : N(Hz)' 형태로 2,177 개(83%) 있다.
  이 마이그레이션은 그 값을 건드리지 않는다 - 대응표만 새로 만든다.

■ 하지 않는 것

  기존 컬럼/표 구조 변경 없음. 등급 체계(game_load_grades 계열) 읽지도 쓰지도
  않음. usage_floors / 견적 엔진 / spec_tiers 손대지 않음. 표와 칸만 준비한다.

Revision ID: 0099
Revises: 0098
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0099"
down_revision = "0098"
branch_labels = None
depends_on = None


# games 에 추가할 칸. 전부 nullable - 모르는 건 비워 둔다(지어내지 않는다).
# Column 객체는 한 번 쓰면 재사용할 수 없어(SQLAlchemy 2.x 에서 Column.copy() 제거됨)
# 호출할 때마다 새로 만든다.
def _game_cols():
    return (
        # GPU 가 뽑아야 할 fps
        sa.Column("competitive_fps_target", sa.Integer(),
                  comment="경쟁/랭크 플레이에서 고객이 원하는 fps(프로세팅/대회 기준)"),
        sa.Column("comfortable_fps_target", sa.Integer(),
                  comment="일반 플레이에서 쾌적하다고 보는 fps"),
        sa.Column("minimum_fps_target", sa.Integer(),
                  comment="이 아래로는 플레이가 불편해지는 하한 fps"),
        # 모니터가 가져야 할 Hz - fps 와 별개다(격투게임: fps 60 / 모니터 240)
        sa.Column("typical_monitor_hz", sa.Integer(),
                  comment="이 게임 사용자가 통상 쓰는 모니터 주사율(Hz). fps 목표와 다를 수 있다"),
        sa.Column("esports_standard_hz", sa.Integer(),
                  comment="공식 대회에서 쓰는 모니터 주사율(Hz). 대회 규격이 없으면 NULL"),
        # 근거
        sa.Column("refresh_confidence", sa.String(length=40),
                  comment="주사율 조사 신뢰도: 확인|2차출처|추정. games.confidence(사양 신뢰도)와 별개"),
        sa.Column("refresh_selection_note", sa.Text(),
                  comment="그 값을 고른 이유/충돌 처리 내역. 지우지 않는다"),
        sa.Column("refresh_source_urls", postgresql.JSONB(astext_type=sa.Text()),
                  comment="주사율 근거 URL 배열"),
    )


def upgrade():
    for col in _game_cols():
        op.add_column("games", col)

    op.create_table(
        "refresh_gpu_requirement",
        sa.Column("req_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("resolution", sa.String(length=20), nullable=False,
                  comment="FHD | QHD | 4K"),
        sa.Column("refresh_hz", sa.Integer(), nullable=False),
        sa.Column("workload", sa.String(length=20), nullable=False,
                  comment="AAA | COMPETITIVE - 같은 주사율도 용도로 필요 GPU 가 갈린다"),
        sa.Column("criterion", sa.String(length=20), nullable=False,
                  comment="native_full | vrr80 | community"),
        sa.Column("gpu_tier", sa.String(length=40),
                  comment="필요 GPU 급(내부 등급 표기). 예 60Ti급"),
        sa.Column("gpu_card", sa.String(length=80),
                  comment="기준이 된 단일 카드(측정 기준일 때). 커뮤니티 기준이면 NULL"),
        sa.Column("gpu_cards", postgresql.JSONB(astext_type=sa.Text()),
                  comment="해당 급에 해당하는 카드 목록(커뮤니티 기준일 때)"),
        sa.Column("measured_fps", sa.Numeric(6, 1),
                  comment="그 카드의 측정 평균 fps(톰스하드웨어 라스터 suite)"),
        sa.Column("our_price_krw", sa.Integer(),
                  comment="조사 시점 자사 카탈로그 가격. 없으면 NULL"),
        sa.Column("verdict", sa.String(length=40), nullable=False,
                  comment="AAA_NATIVE_OK | AAA_NATIVE_VRR_ONLY | ESPORTS_ONLY | UPSCALING_REQUIRED"),
        sa.Column("quote_claim", sa.Text(), nullable=False,
                  comment="견적서에 그대로 쓰는 문장"),
        sa.Column("selection_note", sa.Text(),
                  comment="선정 근거/충돌 처리 내역"),
        sa.Column("source_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  comment="근거 URL 배열. 출처 없는 권장은 싣지 않는다"),
        sa.UniqueConstraint("resolution", "refresh_hz", "workload", "criterion",
                            name="uq_refresh_gpu_requirement_key"),
    )
    op.create_index("ix_refresh_gpu_requirement_lookup", "refresh_gpu_requirement",
                    ["resolution", "refresh_hz", "workload"])


def downgrade():
    op.drop_index("ix_refresh_gpu_requirement_lookup",
                  table_name="refresh_gpu_requirement")
    op.drop_table("refresh_gpu_requirement")
    for col in reversed(list(_game_cols())):
        op.drop_column("games", col.name)
