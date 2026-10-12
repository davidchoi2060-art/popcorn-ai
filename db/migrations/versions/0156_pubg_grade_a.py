# -*- coding: utf-8 -*-
"""배틀그라운드 부하 등급 E -> A (2026-10-12 사장님 시험 「배그만」이 캐주얼 게임으로 읽힘).

■ 무엇이 틀렸나
  0091 이 배틀그라운드를 E(경쟁 이스포츠)로 배정했다. 근거는 «144fps 목표» 문구였다.
  그런데 E 의 다른 게임은 롤·발로란트·서든어택·FC온라인처럼 내장그래픽·입문 그래픽카드로도
  돌아가는 게임이고, 상담 프롬프트는 등급이 E 인 게임을 «캐주얼 게임» 라벨로 가늠한다.
  그래서 「배그만 해요」가 캐주얼 게임 용도로 잡혔다(2026-10-12 사장님 시험).

■ 우리 자료가 이미 «배그는 가볍지 않다»고 말하고 있었다
  · 사장님 확정(2026-08-17) 「배그 = 고사양 게임」 -- usage_floors gaming_high 의 match_terms 에 「배그」(0016).
  · 0105 IGPU_NOTE: pc_tier_ladder L0 not_capable 에 「공식 권장 GTX 1060 3GB -- 내장그래픽으로 부족」.
  · api/sold_reco.py: 2026-10-09 「배그·롤 150만원에 캐주얼 PC」 사고 -- 캐주얼 수준은 배그를 못 돌린다.
  등급 하나만 E 로 남아 이 셋과 어긋나 있었다.

■ 왜 A 인가
  A(일반 AAA) 는 1080p 칸이 E 와 같은 T1 이다 -- FHD 기본 견적은 바뀌지 않는다.
  달라지는 것은 1440p(T1 -> T2)·4K(T2 -> T3) 와, 상담이 등급으로 가늠하는 용도 라벨이다.
  배그 1440p 고주사율은 롤·발로란트 1440p 보다 무겁다 -- T2 가 실제에 가깝다.

■ downgrade -- 0091 의 원래 값(E · 원래 note)으로 되돌린다.

Revision ID: 0156
Revises: 0155
"""
import sqlalchemy as sa
from alembic import op

revision = "0156"
down_revision = "0155"
branch_labels = None
depends_on = None

NAME = "배틀그라운드"
OLD_NOTE = "PUBG 공식 문서 \"144fps 목표\" 문구 직접 확인(game-grades 2차 신규 확정)"
NEW_NOTE = (
    "2026-10-12 E -> A. 공식 권장 GTX 1060 3GB 로 E 의 다른 게임(롤·발로란트 등)보다 무겁고,"
    " E 로 두면 상담이 캐주얼 게임으로 읽었다(사장님 시험 「배그만」). 사장님 확정 2026-08-17"
    " 「배그 = 고사양 게임」과 맞춘다. 이전 근거: " + OLD_NOTE)


def _set(grade: str, note: str, expect: str) -> None:
    conn = op.get_bind()
    gid = conn.execute(sa.text("SELECT game_id FROM games WHERE name = :n"), {"n": NAME}).scalar()
    if gid is None:
        return          # 게임 목록이 없는 빈 DB(시드 전) -- 바꿀 행이 없다
    conn.execute(sa.text(
        "UPDATE game_grade_assignments SET grade = :g, note = :note"
        " WHERE game_id = :gid AND grade = :expect"),
        {"g": grade, "note": note, "gid": gid, "expect": expect})


def upgrade() -> None:
    _set("A", NEW_NOTE, "E")


def downgrade() -> None:
    _set("E", OLD_NOTE, "A")
