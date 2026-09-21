# -*- coding: utf-8 -*-
"""ADM-GRD-020(가칭) 게임·AI 연계 매트릭스 — 조회 API.

요구사항 정본 = `docs/design/req/req-game-matrix.md`. 승인 디자인 원안 =
`docs/design/incoming/dc-game-matrix-admin.html`.

■ 무엇을 읽는가 (전부 실조회 — 이 모듈은 어떤 수도 상수로 갖지 않는다)
  `games` · `ai_workloads` · `game_cell_map` · `workload_cell_map`(0075) ·
  `grid_cells` · `grid_quotes`(is_current) · `gpu_ladder`(0074·0076).

■ 쓰기가 없다 — 매핑 재계산은 배치(`tools/game_cell_mapper.py`)가 한다.
  이 화면은 그 결과를 확인·감사하는 자리다(정의서 §①).

■ ★ 판정을 여기서 다시 하지 않는다 (CLAUDE.md §화면 정직성 — "술어를 다른
  모듈에 다시 적지 않는다")
  성립 여부·매칭 등급은 배치가 이미 판정해 `game_cell_map.match_level` 에 적었다.
  이 모듈은 그 행을 «읽기만» 한다 — 여기서 `ladder_score >= rec_score` 같은 비교를
  다시 적으면 배치와 갈라져, 화면이 배치와 다른 말을 하는 날이 온다
  (`api/admin_pool.py` 가 이미 그렇게 갈라진 전례가 주석에 남아 있다).

  그 대가로 **불성립 칸의 «사유»는 알 수 없다.** 배치는 성립한 칸만 표에 남기고
  왜 떨어졌는지는 `--dry` 의 SUMMARY_JSON 에만 있다(정의서 §③ 마지막 항이 이
  하한을 이미 명시했다). 그래서 불성립 칸에는 사유를 **지어내지 않고** 저장돼
  있지 않다는 사실을 그대로 내려보낸다(`unmatched[].reason_available=false`).

■ 「불성립」과 「판정 불가」는 다른 라벨이다 (정의서 §⑤③·§⑥, 2026-09-09 개정)
  ⚠ 이 절의 옛 버전은 "스킵 사유가 테이블에 없어 모른다"고 적혀 있었다 — 그때는
  사실이었다(배치가 이유를 계산만 하고 저장은 안 했다). 0080 마이그레이션 +
  배치 개정(tools/game_cell_mapper.py)으로 games/ai_workloads.mapping_skip_reason
  에 실제 사유가 저장된다. 이 절을 낡은 채로 두면 화면이 다시 「사유 미제공」
  으로 후퇴한다.
  판정은 **`mapping_skip_reason` 컬럼의 사실**뿐이다 — 여기서 재판정하지 않는다.
    NULL           -> 매핑 성공(성립) 또는 애초에 대상 아님
    rec_gpu_missing / min_vram_gb_missing -> 판정 불가(원천에 값 없음)
    rec_gpu_parse_failed / zero_matching_cells 등 -> 매핑 없음(사유 있음, 아래 참조)
  사람이 읽는 문구는 game_matrix_reasons.py(단일 원천)가 배치와 공유한다.

■ 인증 — 다른 `admin_*.py` 와 같은 관행. 이 라우터의 prefix 가 `/api/admin` 이라
  `api/auth.py` 의 `auth_middleware` 가 세션을 이미 강제한다(전 `/api/admin/*`
  공통, 슬라이스 37). `admin_grid.py`(이웃 화면 ADM-GRD-010)와 동일하게 이 모듈
  자체는 별도 인증 코드를 두지 않는다 — **조회 전용이라 owner 전용이 아니다**
  (정의서 §③ 마지막 항의 「권한 범위」는 미정 항목이라, 여기서 임의로 좁히지
  않고 다른 조회 화면과 같은 가드를 쓴다).
"""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from .db import engine
from .timeutil import iso as _iso   # 시각 표기 단일 원천(슬라이스 62)
from . import game_matrix_reasons as reasons

router = APIRouter(prefix="/api/admin")

# 원안이 정한 표시 상한 — 불성립·판정 불가 칸은 가장 싼 쪽 5칸만 보여준다
# (dc-game-matrix-admin.html "상위 5칸만 표시"). 전체 수는 `unmatched_total` 로
# 함께 내려보내 화면이 「N칸 중 5칸」을 말할 수 있게 한다(§비율에는 표본 병기).
UNMATCHED_LIMIT = 5


def _ladder(conn) -> dict:
    """gpu_ladder 전량 — 근거 패널이 칩셋명으로 찾아 쓴다.

    칸 행마다 서열·출처를 복제해 내려보내는 대신 칩셋 사전 하나로 내려보낸다
    (같은 사실을 두 벌 두지 않는다). `gpu_used` 는 배치가 이 표의 `chipset`
    어휘로 적어 둔 값이라 키가 그대로 맞는다(0074 머리 주석).
    """
    rows = conn.execute(text(
        "SELECT chipset, ladder_score, vram_gb, source_url, checked_date, note"
        " FROM gpu_ladder ORDER BY ladder_score DESC")).mappings().all()
    return {r["chipset"]: {
        "ladder_score": float(r["ladder_score"]),
        "vram_gb": r["vram_gb"],
        "source_url": r["source_url"],
        "checked_date": r["checked_date"],
        "note": r["note"],
    } for r in rows}


def _axes(conn) -> dict:
    """필터 선택지 — 화면이 하드코딩하지 않는다(CLAUDE.md §목록 화면 규약).

    용도(usage)에는 순번 컬럼이 없다 — `admin_grid.py` 와 같은 방식으로
    cell_id 최솟값 순서를 쓴다(같은 격자를 두 화면이 다른 순서로 보이면 안 된다).
    """
    usages = conn.execute(text(
        "SELECT usage FROM grid_cells GROUP BY usage ORDER BY min(cell_id)")).scalars().all()
    platforms = conn.execute(text(
        "SELECT platform FROM grid_cells GROUP BY platform ORDER BY min(cell_id)")).scalars().all()
    # 매칭 등급 어휘도 서버가 준다. 게임(권장충족/최소충족)과 AI 작업(권장구성/
    # 구동가능)이 서로 다른 어휘라 화면에 두 벌 적으면 배치가 어휘를 바꾸는 날
    # 조용히 어긋난다 — 실제로 들어 있는 값만 내려보낸다(매핑이 비면 빈 목록).
    game_levels = conn.execute(text(
        "SELECT match_level FROM game_cell_map GROUP BY match_level"
        " ORDER BY match_level")).scalars().all()
    workload_levels = conn.execute(text(
        "SELECT match_level FROM workload_cell_map GROUP BY match_level"
        " ORDER BY match_level")).scalars().all()
    return {"usages": list(usages), "platforms": list(platforms),
            "game_levels": list(game_levels), "workload_levels": list(workload_levels)}


def _meta(conn) -> dict:
    """상단 요약 — 전부 그 자리에서 센 값이다(문서에 적힌 절대수를 쓰지 않는다)."""
    games_total = conn.execute(text("SELECT count(*) FROM games")).scalar_one()
    ai_total = conn.execute(text("SELECT count(*) FROM ai_workloads")).scalar_one()
    games_mapped = conn.execute(text(
        "SELECT count(DISTINCT game_id) FROM game_cell_map")).scalar_one()
    ai_mapped = conn.execute(text(
        "SELECT count(DISTINCT workload_id) FROM workload_cell_map")).scalar_one()
    # 0109 로 이 두 표의 단위가 «칸»에서 «견적(칸 x 변종)»으로 바뀌었다.
    # 화면 라벨이 말하는 것은 여전히 «칸»이라, 여기서 칸으로 접어 센다 —
    # 행 수를 그대로 내보내면 「매핑 칸」 자리에 최대 3배 부푼 수가 뜬다
    # (아래 cell_count 가 0092 때 같은 이유로 DISTINCT 를 쓰는 것과 같다).
    game_map_rows = conn.execute(text(
        "SELECT count(DISTINCT (game_id, cell_id)) FROM game_cell_map")).scalar_one()
    workload_map_rows = conn.execute(text(
        "SELECT count(DISTINCT (workload_id, cell_id)) FROM workload_cell_map")).scalar_one()
    # 「견적 있는 칸」 — 화면 라벨이 말하는 대로 **칸 수**다. 0092 로 칸 하나가
    # 3종(가성비/추천/고성능) 현재본을 가지므로 행 수를 세면 칸 수의 3배 가까운
    # 값(388)이 「칸 134개」 자리에 뜬다. DISTINCT 로 칸을 센다.
    cell_count = conn.execute(text(
        "SELECT count(DISTINCT cell_id) FROM grid_quotes WHERE is_current")).scalar_one()
    ladder_rows = conn.execute(text("SELECT count(*) FROM gpu_ladder")).scalar_one()
    # 「기준 일시」 = 매핑 캐시가 마지막으로 재계산된 시각. 두 표가 같은 배치에서
    # 함께 쓰이므로 둘 중 늦은 쪽을 쓴다 — 한쪽만 보면 그 표가 비었을 때 null 이 된다.
    computed_at = conn.execute(text(
        "SELECT greatest("
        " (SELECT max(computed_at) FROM game_cell_map),"
        " (SELECT max(computed_at) FROM workload_cell_map))")).scalar_one()
    return {
        "checked_date": _iso(computed_at),
        "games_total": games_total, "games_mapped": games_mapped,
        "ai_total": ai_total, "ai_mapped": ai_mapped,
        "game_map_rows": game_map_rows, "workload_map_rows": workload_map_rows,
        "cell_count": cell_count, "ladder_rows": ladder_rows,
    }


def _games(conn) -> list:
    """게임 전량 — **매핑 0건인 게임도 포함**한다(정의서 §⑤②).

    빼면 "왜 이 게임이 목록에 없지"를 운영자가 확인할 자리가 사라진다. 매핑
    성공/스킵은 `mapped_cells` 와 `unjudgeable` 두 사실로만 가른다.
    """
    rows = conn.execute(text(
        "SELECT g.game_id, g.name, g.genre, g.rec_gpu, g.min_gpu,"
        " g.rec_ram_gb, g.min_ram_gb, g.official_source_url, g.checked_date,"
        " g.description, g.mapping_skip_reason,"
        # 0109 — 표가 «칸 x 변종» 단위다. 화면의 「칸 N개」가 말하는 것은 칸이라
        # DISTINCT 로 접는다(그러지 않으면 한 칸이 최대 3으로 세어진다).
        " count(DISTINCT m.cell_id) AS mapped_cells,"
        " count(m.cell_id) AS mapped_quotes"
        " FROM games g LEFT JOIN game_cell_map m ON m.game_id = g.game_id"
        " GROUP BY g.game_id ORDER BY g.game_id")).mappings().all()
    return [{
        "game_id": r["game_id"], "name": r["name"], "genre": r["genre"],
        "rec_gpu": r["rec_gpu"], "min_gpu": r["min_gpu"],
        "rec_ram_gb": r["rec_ram_gb"], "min_ram_gb": r["min_ram_gb"],
        "source_url": r["official_source_url"], "checked_date": r["checked_date"],
        "mapped_cells": r["mapped_cells"], "mapped_quotes": r["mapped_quotes"],
        "description": r["description"],
        # 사유는 배치(tools/game_cell_mapper.py)가 실제 계산한 값이다(0080) —
        # "rec_gpu가 비었나"만 보던 이전 판정을 대체한다. 원천에 값은 있는데
        # 서열표에 없어 파싱이 실패한 경우(구형 카드)와 값 자체가 없는 경우를
        # 이제 구분해서 말할 수 있다(§단일 원천 — game_matrix_reasons.py).
        "unjudgeable": r["mapping_skip_reason"] is not None,
        "unjudgeable_reason": reasons.label_of(r["mapping_skip_reason"]),
    } for r in rows]


def _workloads(conn) -> list:
    rows = conn.execute(text(
        "SELECT w.workload_id, w.task, w.model_size, w.min_vram_gb, w.rec_vram_gb,"
        " w.min_ram_gb, w.recommended_tier, w.source_url, w.checked_date,"
        " w.description, w.mapping_skip_reason,"
        " count(DISTINCT m.cell_id) AS mapped_cells,"   # 0109 — _games() 와 같은 이유
        " count(m.cell_id) AS mapped_quotes"
        " FROM ai_workloads w"
        " LEFT JOIN workload_cell_map m ON m.workload_id = w.workload_id"
        " GROUP BY w.workload_id ORDER BY w.workload_id")).mappings().all()
    return [{
        "workload_id": r["workload_id"], "task": r["task"],
        "model_size": r["model_size"], "min_vram_gb": r["min_vram_gb"],
        "rec_vram_gb": r["rec_vram_gb"], "min_ram_gb": r["min_ram_gb"],
        "recommended_tier": r["recommended_tier"], "source_url": r["source_url"],
        "checked_date": r["checked_date"], "mapped_cells": r["mapped_cells"],
        "mapped_quotes": r["mapped_quotes"],
        "description": r["description"],
        # games와 같은 방식(0080) — 배치가 실제 계산한 사유를 그대로 노출한다.
        "unjudgeable": r["mapping_skip_reason"] is not None,
        "unjudgeable_reason": reasons.label_of(r["mapping_skip_reason"]),
    } for r in rows]


def _filter_sql(usage, platform):
    """용도·플랫폼 조건을 SQL 조각과 바인드로 만든다.

    `:usage IS NULL OR ...` 대신 조각을 붙이는 이유: 그 형태는 psycopg 가 바인드
    타입을 못 정해 명시 캐스트가 필요해지고, 캐스트 하나가 빠지면 조용히
    전건이 걸러진다. 조건이 둘뿐이라 조각 조립이 더 안전하다.
    """
    where, params = "", {}
    if usage:
        where += " AND c.usage = :usage"
        params["usage"] = usage
    if platform:
        where += " AND c.platform = :platform"
        params["platform"] = platform
    return where, params


def _cell_axis_sql(alias: str = "c") -> str:
    """칸 좌표 컬럼 — 0092 가 `grid_cells.tier` 를 없앴고 0105 가 축을 **예산대**로
    바꿨다. 이 모듈은 오래도록 `c.tier` 를 고른 채로 남아 있어 선택 조회가
    **HTTP 500**(UndefinedColumn)으로 죽고 있었다(2026-09-20 발견).

    좌표를 한 자리에서만 적는다 — 두 쿼리가 서로 다른 컬럼을 고르면 같은 칸이
    두 표에서 다른 이름으로 나온다. 화면이 보여 줄 이름은 `band_label` 이다
    (`admin_grid.py._cell_label()` 과 같은 어휘 — 두 화면이 같은 칸을 같은 말로
    부른다).
    """
    return (f" {alias}.usage, {alias}.platform, {alias}.budget_band_key,"
            f" {alias}.game_grade, {alias}.game_resolution, b.label AS band_label,")


_CELL_AXIS_JOIN = " JOIN grid_budget_bands b ON b.band_key = c.budget_band_key"


def _cell_axis_out(r: dict) -> dict:
    """칸 좌표를 응답 모양으로. `tier` 키는 더 이상 내려보내지 않는다 —
    없는 축을 빈 값으로 흉내 내면 화면이 그 자리를 «값 없음»으로 그린다."""
    return {
        "usage": r["usage"], "platform": r["platform"],
        "budget_band_key": r["budget_band_key"], "band_label": r["band_label"],
        "game_grade": r["game_grade"], "game_resolution": r["game_resolution"],
    }


# 칸 하나가 3종(가성비/추천/고성능) 현재본을 갖는다(0092). 표가 세는 단위는
# «칸»이다 — 칸 하나를 3행으로 펴면 「70칸 성립」이 210행으로 부풀고, 정렬이
# 가격순이라 같은 칸이 표에 흩어져 나온다.
#
# ★ 2026-09-21(0109) 이전에는 그 접기를 **대표 변종 「추천」 하나만 조인**하는
#   방식으로 했다. 그건 틀렸다 — 매핑 표 자체가 변종을 버리고 있던 시절의
#   대응이라, 「추천 변종에서는 안 되지만 고성능 변종에서는 되는 게임」의 칸이
#   화면에서 **가격·GPU 가 엉뚱한 변종의 것**으로 그려졌다(실측 98칸이 변종마다
#   GPU 가 다르다). 이제 매핑이 변종별로 있으므로, 접을 때 **그 칸에서 실제로
#   성립한 변종 중 가장 싼 것**을 대표로 쓴다. 그것이 정의서 §④ 의 질문
#   「이 게임 되는 가장 싼 견적」에 대한 정확한 답이다.
#   성립한 변종 전부는 `variants[]` 로 함께 내려보낸다 — 접되 버리지 않는다.
#
# 불성립 칸에는 성립한 변종이 없다. 그 자리에는 **그 칸의 가장 싼 현재 견적**을
# 보여 준다(어느 변종인지 `tier_variant` 로 밝힌다) — 특정 변종을 대표로 박으면
# 변종이 2벌뿐인 칸(0106 · 14칸)에서 행이 통째로 사라진다.
_CHEAPEST_QUOTE_SQL = (
    " LEFT JOIN LATERAL ("
    "   SELECT q.total, q.tier_variant, q.payload FROM grid_quotes q"
    "    WHERE q.cell_id = c.cell_id AND q.is_current"
    "    ORDER BY q.total ASC NULLS LAST, q.tier_variant LIMIT 1) q ON true")


def _selection_cells(conn, *, kind: str, item_id: int, usage, platform, level) -> dict:
    """고른 항목의 성립 칸 + 불성립·판정 불가 칸.

    성립 여부·등급(`match_level`)·GPU(`gpu_used`)는 **배치가 적은 값 그대로**다
    (이 모듈은 판정을 다시 하지 않는다 — 머리 주석 ★). 정렬은 가격 오름차순
    고정(정의서 §④). 견적가가 없는 칸은 뒤로 보낸다(NULLS LAST).
    """
    if kind == "game":
        map_table, key_col = "game_cell_map", "game_id"
    else:
        map_table, key_col = "workload_cell_map", "workload_id"

    where, params = _filter_sql(usage, platform)
    params["id"] = item_id
    level_sql = ""
    if level:
        level_sql = " AND m.match_level = :level"
        params["level"] = level

    # 성립한 변종을 전부 가져온다(각 변종의 «자기» 견적가·GPU 와 함께).
    # 접기는 파이썬에서 한다 — SQL 안에서 접으면 variants[] 를 잃는다.
    rows = conn.execute(text(
        "SELECT c.cell_id," + _cell_axis_sql() +
        " c.budget_min, c.budget_max,"
        " m.match_level, m.gpu_used, m.tier_variant,"
        " q.total, q.verdict, q.status"
        f" FROM {map_table} m"
        " JOIN grid_cells c ON c.cell_id = m.cell_id" + _CELL_AXIS_JOIN +
        " LEFT JOIN grid_quotes q ON q.cell_id = m.cell_id"
        "   AND q.tier_variant = m.tier_variant AND q.is_current"
        f" WHERE m.{key_col} = :id" + where + level_sql +
        " ORDER BY q.total ASC NULLS LAST, c.cell_id"), params).mappings().all()

    cells, by_cell = [], {}
    for r in rows:
        v = {"tier_variant": r["tier_variant"], "match_level": r["match_level"],
             "gpu_used": r["gpu_used"], "total": r["total"],
             "verdict": r["verdict"], "status": r["status"]}
        cur = by_cell.get(r["cell_id"])
        if cur is None:
            # 행이 이미 가격 오름차순이라 처음 만난 변종이 그 칸의 최저가다.
            cur = {"cell_id": r["cell_id"], **_cell_axis_out(r),
                   "budget_min": r["budget_min"], "budget_max": r["budget_max"],
                   "match_level": r["match_level"], "gpu_used": r["gpu_used"],
                   "tier_variant": r["tier_variant"], "total": r["total"],
                   "verdict": r["verdict"], "status": r["status"],
                   "variants": []}
            by_cell[r["cell_id"]] = cur
            cells.append(cur)
        cur["variants"].append(v)

    # 불성립·판정 불가 — 등급 필터는 걸지 않는다(성립하지 않은 칸에는 등급이 없다).
    # 한 변종이라도 성립하면 그 칸은 「성립」이다 — NOT EXISTS 가 변종을 가리지
    # 않으므로 위 표와 겹치지 않는다.
    un_where, un_params = _filter_sql(usage, platform)
    un_params["id"] = item_id
    unmatched = conn.execute(text(
        "SELECT c.cell_id," + _cell_axis_sql() + " q.total, q.tier_variant,"
        " (SELECT it->>'name'"
        "    FROM jsonb_array_elements(COALESCE(q.payload->'items','[]'::jsonb)) it"
        "   WHERE it->>'part_type' = 'GPU' LIMIT 1) AS gpu_name"
        " FROM grid_cells c" + _CELL_AXIS_JOIN + _CHEAPEST_QUOTE_SQL +
        f" WHERE EXISTS (SELECT 1 FROM grid_quotes q2"
        f"   WHERE q2.cell_id = c.cell_id AND q2.is_current)"
        f"   AND NOT EXISTS (SELECT 1 FROM {map_table} m"
        f"   WHERE m.{key_col} = :id AND m.cell_id = c.cell_id)" + un_where +
        " ORDER BY q.total ASC NULLS LAST, c.cell_id"), un_params).mappings().all()

    return {
        "cells": cells,
        "unmatched": [{
            "cell_id": r["cell_id"], **_cell_axis_out(r),
            "total": r["total"], "tier_variant": r["tier_variant"],
            # 칸 견적에 실제로 담긴 GPU 상품명(원문). 칩셋으로 정규화하지 않는다 —
            # 정규화·판정은 배치 소관이고, 여기서 흉내 내면 원천이 둘이 된다.
            "gpu_name": r["gpu_name"],
        } for r in unmatched[:UNMATCHED_LIMIT]],
        "unmatched_total": len(unmatched),
        "unmatched_shown": min(len(unmatched), UNMATCHED_LIMIT),
        # 사유는 저장돼 있지 않다 — 화면이 그 사실을 그대로 말하게 하는 표식
        "reason_available": False,
    }


@router.get("/game-matrix")
def game_matrix(
    game_id: int | None = Query(None, description="선택한 게임 — 성립 칸 상세를 함께 받는다"),
    workload_id: int | None = Query(None, description="선택한 AI 작업"),
    usage: str | None = Query(None, description="용도 필터(grid_cells.usage)"),
    platform: str | None = Query(None, description="플랫폼 필터(인텔/AMD)"),
    level: str | None = Query(None, description="매칭 등급 필터(match_level 원문)"),
):
    """매트릭스 목록 + (선택 시) 그 항목의 칸 상세.

    `game_id`·`workload_id` 를 둘 다 주면 400 — 화면의 탭은 하나만 활성이므로
    둘이 함께 오는 것은 호출 쪽 오류다. 조용히 한쪽을 고르면 화면이 자기가 고른
    것과 다른 결과를 그린다.
    """
    if game_id is not None and workload_id is not None:
        raise HTTPException(400, "game_id 와 workload_id 는 함께 지정할 수 없습니다")

    with engine.connect() as conn:
        out = {
            "meta": _meta(conn),
            **_axes(conn),
            "ladder": _ladder(conn),
            "games": _games(conn),
            "workloads": _workloads(conn),
            "unmatched_limit": UNMATCHED_LIMIT,
            "selection": None,
        }

        if game_id is not None:
            item = next((g for g in out["games"] if g["game_id"] == game_id), None)
            if item is None:
                raise HTTPException(404, "게임을 찾을 수 없습니다")
            out["selection"] = {"kind": "game", "item": item,
                                **_selection_cells(conn, kind="game", item_id=game_id,
                                                   usage=usage, platform=platform, level=level)}
        elif workload_id is not None:
            item = next((w for w in out["workloads"]
                         if w["workload_id"] == workload_id), None)
            if item is None:
                raise HTTPException(404, "AI 작업을 찾을 수 없습니다")
            out["selection"] = {"kind": "workload", "item": item,
                                **_selection_cells(conn, kind="workload", item_id=workload_id,
                                                   usage=usage, platform=platform, level=level)}

    return out
