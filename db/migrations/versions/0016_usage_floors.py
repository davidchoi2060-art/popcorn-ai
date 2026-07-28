"""용도별 부품 하한 — 화면이 이미 한 약속을 서버가 이행하게 한다.

S1 화면은 용도 칩에 "저사양 GPU 제외(프레임 미달)" · "램 32GB↑ 우선" · "고성능 GPU 제외"라고
적어 왔지만 **서버는 용도로 아무것도 하지 않았다**. `_apply_one`은 용도를 만나면
"구성 단계(스코어)에서 반영"이라고 답했는데 구성 단계에도 없었다.

그 결과 "롤·배그 하려고요"에 GT710 2GB(2014년 사무용 카드)가 나왔다 — 저소음 태그와
최저가를 정확히 만족한 결과다. 규칙대로 동작했지만 용도를 배신했고,
"모든 견적에는 이유가 있습니다"에 답할 수 없는 구성이 됐다.

compat_rules 전례를 따라 **DB가 단일 원천**이다. 코드에 하한을 박으면 운영자가 못 고친다.

성능 지표(벤치·FPS)는 여전히 없다. GPU는 `required_power_watt`를 계층 근사로 쓴다 —
실측이 단조다(300W 등급 2.8만~19만 · 550W 등급 29.7만~83만 · 750W 등급 105만~256만).
**전력 등급이지 성능 자체가 아니다**. 근거 문구가 그 사실을 먼저 밝힌다.

Revision ID: 0016
Revises: 0015
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


# (usage_key, 라벨, 인식 표현, [(슬롯, 필드, 연산, 값, 라벨, 상세형식)])
# 인식 표현은 **부분 일치**다 — 화면 칩이 '고사양 게임'·'사무·인강'처럼 여러 표기를 쓴다.
# 순서가 중요하다: 먼저 맞는 것이 이긴다(고사양 게임 → 게임보다 앞).
SEED = [
    ("gaming_high", "고사양 게임", ["고사양 게임", "고사양게임", "배그", "AAA"], [
        ("GPU", "required_power_watt", "gte", 550,
         "고사양 게임 GPU 등급", "권장 전원 {v}W (고사양 게임 기준 {r}W 이상)"),
        ("RAM", "capacity_gb", "gte", 16, "고사양 게임 메모리", "{v}GB (기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 500, "고사양 게임 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ]),
    ("ai", "AI 작업", ["AI 작업", "AI에 강한", "머신러닝", "딥러닝"], [
        ("GPU", "required_power_watt", "gte", 650,
         "AI 작업 GPU 등급", "권장 전원 {v}W (AI 작업 기준 {r}W 이상)"),
        ("RAM", "capacity_gb", "gte", 32, "AI 작업 메모리", "{v}GB (기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 1000, "AI 작업 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ]),
    ("stream", "방송·스트리밍", ["방송", "스트리밍"], [
        ("GPU", "required_power_watt", "gte", 550,
         "방송 GPU 등급", "권장 전원 {v}W (방송 기준 {r}W 이상)"),
        ("RAM", "capacity_gb", "gte", 32, "방송 메모리", "{v}GB (인코딩 기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 1000, "방송 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ]),
    ("video", "영상편집", ["영상편집", "영상 편집", "크리에이터", "편집"], [
        ("GPU", "required_power_watt", "gte", 450,
         "영상편집 GPU 등급", "권장 전원 {v}W (영상편집 기준 {r}W 이상)"),
        ("RAM", "capacity_gb", "gte", 32, "영상편집 메모리", "{v}GB (4K 타임라인 기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 1000, "영상편집 저장 용량", "{v}GB (소스 보관 기준 {r}GB 이상)"),
    ]),
    ("game", "게임", ["게임", "롤", "오버워치", "발로란트", "리그오브"], [
        ("GPU", "required_power_watt", "gte", 450,
         "게임 GPU 등급", "권장 전원 {v}W (게임 기준 {r}W 이상)"),
        ("RAM", "capacity_gb", "gte", 16, "게임 메모리", "{v}GB (기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 500, "게임 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ]),
    ("design", "디자인", ["디자인"], [
        ("RAM", "capacity_gb", "gte", 16, "디자인 메모리", "{v}GB (기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 500, "디자인 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ]),
    ("dev", "개발", ["개발"], [
        ("RAM", "capacity_gb", "gte", 16, "개발 메모리", "{v}GB (기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 500, "개발 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ]),
    ("office", "사무·인강", ["사무", "인강", "문서", "웹", "화상회의"], [
        ("RAM", "capacity_gb", "gte", 8, "사무 메모리", "{v}GB (기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 250, "사무 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ]),
]


def upgrade():
    op.create_table(
        "usage_floors",
        sa.Column("floor_id", sa.Integer, primary_key=True),
        sa.Column("usage_key", sa.String(32), nullable=False),
        sa.Column("usage_label", sa.String(64), nullable=False),
        # 이 용도로 인식할 표현들 — 화면 칩 문구가 여러 갈래라 부분 일치로 본다
        sa.Column("match_terms", postgresql.JSONB, nullable=False),
        sa.Column("slot", sa.String(24), nullable=False),
        sa.Column("field", sa.String(48), nullable=False),
        sa.Column("op", sa.String(8), nullable=False),
        sa.Column("value", sa.Integer, nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("detail_fmt", sa.String(160)),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_usage_floors_key", "usage_floors", ["usage_key"])

    conn = op.get_bind()
    order = 0
    for key, label, terms, rules in SEED:
        blob = json.dumps(terms, ensure_ascii=False)
        for slot, field, oper, val, rlabel, fmt in rules:
            conn.execute(sa.text(
                "INSERT INTO usage_floors (usage_key, usage_label, match_terms, slot,"
                " field, op, value, label, detail_fmt, sort_order)"
                " VALUES (:k, :ul, CAST(:t AS JSONB), :s, :f, :o, :v, :l, :d, :so)"),
                {"k": key, "ul": label, "t": blob, "s": slot, "f": field, "o": oper,
                 "v": val, "l": rlabel, "d": fmt, "so": order})
            order += 1


def downgrade():
    op.drop_index("ix_usage_floors_key", table_name="usage_floors")
    op.drop_table("usage_floors")
