# -*- coding: utf-8 -*-
"""`game_customer_copy` 검수 통과 문구를 고객 경로에 내주는 **유일한 자리**.

왜 한 곳인가 — 이 게이트(`reviewed_by IS NOT NULL`)가 두 벌로 흩어져 있었다:
  `api/talk_answer.py` 가 LEFT JOIN 뒤 `if r["reviewed_by"]:` 로 걸렀고,
  `api/admin_game_copy.py` 가 같은 조건을 SQL 문자열로 따로 들고 있었다(live 건수 ·
  `customer_gate` 응답 문구). 한쪽만 고치면 다른 쪽이 몰래 낡는다 — 회귀 `[62]` 가
  «검수 안 된 문구가 새지 않는가」를 지금까지는 `talk_answer.py` 소스를 정규식으로
  뒤져 지켰는데, 그 정규식이 지키는 자리 자체가 두 곳이면 하나가 조용히 새도
  잡히지 않는다. 그래서 게이트 문자열의 정의와, 그 문자열로 검수 통과 행을 실제로
  읽어 오는 조회를 **이 파일 하나**로 모은다. 고객 경로(팝콘톡·견적 카드)는 이제
  `load_reviewed_copy` 하나만 부르면 된다 — 게이트를 다시 적지 않는다.

사장님 확정: 86종 검수는 끝났다. **여기서는 건수를 적지 않는다**(CLAUDE.md §데이터
「수를 여기 적지 않는다」 — 문서에 박은 수는 반드시 낡는다). 지금 몇 건이 노출
가능한지는 이 게이트로 직접 세면 안다.

로그는 ASCII 기호만(서버 stdout 이 cp949라 em-dash·화살표가 요청을 500으로 만든다).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import bindparam, text

log = logging.getLogger(__name__)

# ── 게이트 — 유일한 정의. 다른 모듈은 이 상수를 이어 붙이지, 문자열을 다시 적지 않는다.
GATE_SQL = "reviewed_by IS NOT NULL"


@dataclass
class GameCopy:
    """검수를 통과한 견적 근거 한 건. 없는 값은 None — 지어내지 않는다."""
    game_id: int
    name: str
    spec_summary: str | None = None
    why_this_pc: str | None = None
    upgrade_hint: str | None = None
    caution: str | None = None
    source_fields: list[str] | None = None
    source_url: str | None = None
    confidence: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


def load_reviewed_copy(conn, names: list[str]) -> dict[str, GameCopy]:
    """`games.name` 목록 -> 검수 통과 행만, 이름을 키로.

    **미검수·목록에 없는 이름은 키 자체가 없다** — `None` 을 채워 넣지 않는다
    (호출부가 `copies.get(name)` 으로 물어 없으면 "이 게임은 근거가 없다"로 읽게
    한다. 키가 있는데 값이 None 이면 "검수는 됐는데 내용이 비었다"로 오독된다).
    """
    if not names:
        return {}
    rows = conn.execute(text(
        "SELECT g.game_id, g.name,"
        "       c.spec_summary_ko, c.why_this_pc, c.upgrade_hint, c.caution,"
        "       c.source_fields, c.source_url, c.confidence,"
        "       c.reviewed_by, c.reviewed_at"
        "  FROM game_customer_copy c"
        "  JOIN games g USING (game_id)"
        " WHERE g.name IN :names AND c." + GATE_SQL
    ).bindparams(bindparam("names", expanding=True)), {"names": names}).mappings().all()
    out: dict[str, GameCopy] = {}
    for r in rows:
        out[r["name"]] = GameCopy(
            game_id=r["game_id"], name=r["name"],
            spec_summary=r["spec_summary_ko"], why_this_pc=r["why_this_pc"],
            upgrade_hint=r["upgrade_hint"], caution=r["caution"],
            source_fields=list(r["source_fields"] or []),
            source_url=r["source_url"], confidence=r["confidence"],
            reviewed_by=r["reviewed_by"], reviewed_at=r["reviewed_at"])
    return out
