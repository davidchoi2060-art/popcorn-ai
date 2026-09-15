# -*- coding: utf-8 -*-
"""ADM-GRD-010 상품 매트릭스 관리 — 사전 생성 견적 격자(grid_cells·grid_quotes) 조회 API.

배경 · 저장 구조 = `db/migrations/versions/0092_grid_spec_axis.py`(A-135 스펙축
전환, 0072~0082 가격축 격자는 `grid_cells_legacy_v1`/`grid_quotes_legacy_v1`로
보존만). 배치 도구 = `tools/grid_generate.py`(이 모듈의 담당 밖 — 읽기만 한다).
정의서 = `docs/design/req/req-grid-admin-2026-09-15.md`.

■ 두 축 — 비게임 칸과 게임 칸은 서로 다른 컬럼을 쓴다(0092 CHECK 제약)
  비게임: `tier_key`(FK→spec_tiers T0~T5) + `usage`(6종 문자열)
  게임  : `usage='게임'` 고정 + `game_grade`(FK→game_load_grades E/A/B/C/S/L)
          + `game_resolution`(1080p/1440p/4K). `tier_key`는 게임 칸에서 항상
          NULL이다 — 스펙은 `game_grade_resolution_tiers`를 조인해서 구한다
          (S등급은 GPU/CPU 비대칭이라 단일 tier_key로 못 담는다, 정의서 §④).

■ 쓰기(재생성)는 이번 범위 밖이다 — 만들지 않는다. 화면의 재생성 버튼들은
  API가 없다는 사실을 그대로 disabled로 드러낸다(§화면 정직성 — 거짓 동작 금지).

■ 인증 — 다른 admin_*.py(예: `admin_pool.py`)와 같은 관행. 이 라우터의 prefix가
  `/api/admin`이라 `api/auth.py`의 `auth_middleware`가 세션·기본 인증을 이미
  강제한다(전 `/api/admin/*` 공통, 슬라이스 37). 이 모듈 자체는 별도 인증 코드를
  두지 않는다.

■ `grid_quotes.payload`는 recommend 엔진 응답의 해당 티어 build 전체(JSONB)다.
  이 모듈은 그 중 화면이 쓰는 필드만 추려 낸다 — payload를 그대로 내려주지
  않는 이유는 화면이 서버 내부 구조에 결합되지 않게 하기 위함이다.

■ tier_variant(가성비/추천/고성능) — 칸 하나가 최대 3개 현재본을 가진다
  (0092, 정의서 §⑤-5). `/grid`는 칸당 대표로 "추천"본의 요약만 목록에 얹고
  (표가 3배로 부풀지 않게), `/grid/cells/{id}`는 3종 전부를 내려줘 화면이
  탭으로 전환한다.

■ 칸 상세의 `in_stock`은 **지금 재고를 실조회**한 값이다(payload 저장 시점의
  재고가 아니다) — 견적 생성 뒤 품절될 수 있어, 저장된 값을 그대로 믿으면 이미
  틀린 사실을 말하게 된다.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .db import engine
from .timeutil import iso as _iso   # 시각 표기 단일 원천(슬라이스 62)

router = APIRouter(prefix="/api/admin")

VARIANTS = ["가성비", "추천", "고성능"]
REPRESENTATIVE_VARIANT = "추천"   # 목록 표에 대표로 얹는 본 — 정의서 §⑥-3


def _cell_state(c: dict, last_batch_id) -> str:
    """칸 색상·범례가 쓰는 6버킷 중 하나 — 화면이 각자 다시 판정하면 갈라지므로
    (§단일 원천) 여기 한 곳에서만 정의한다. 대표본(추천) 기준으로 판정한다."""
    if c["intended_empty"]:
        return "intent"
    if c["quote_id"] is None:
        return "missing"
    status = c["status"] or ""
    if "실패" in status:
        return "fail"
    if last_batch_id is not None and c["batch_id"] != last_batch_id:
        return "fail"
    if status == "예산 상한 초과":
        return "over"
    if status == "재고 소진 슬롯 있음":
        return "stock"
    return "ok"


def _cell_label(tier_key, usage, game_grade, game_resolution,
                 tier_names: dict, grade_labels: dict) -> str:
    """칸 표시명 — 비게임은 '팝콘2 · 디자인', 게임은 '게임A등급 · 1440p' 식."""
    if usage == "게임":
        g = grade_labels.get(game_grade, game_grade)
        return f"게임({g}) · {game_resolution}"
    return f"{tier_names.get(tier_key, tier_key)} · {usage}"


@router.get("/grid")
def grid():
    """격자 전체 — 칸 108개(현재 스키마 기준, 지어내지 않는다: 실제로는 매 요청
    grid_cells를 다시 센다) + 각 칸의 대표본("추천") 견적 요약. 플랫폼별로
    가르지 않고 전부 내려준다 — 화면이 플랫폼 토글을 클라이언트에서 필터링한다."""
    with engine.connect() as conn:
        cells = conn.execute(text(
            "SELECT c.cell_id, c.tier_key, c.usage, c.game_grade, c.game_resolution,"
            " c.platform, c.budget_min, c.budget_max, c.intended_empty,"
            " q.quote_id, q.batch_id, q.generated_at, q.total, q.verdict, q.status"
            " FROM grid_cells c"
            " LEFT JOIN grid_quotes q ON q.cell_id = c.cell_id AND q.is_current"
            "   AND q.tier_variant = :rv"
            " ORDER BY c.cell_id"
        ), {"rv": REPRESENTATIVE_VARIANT}).mappings().all()

        tier_rows = conn.execute(text(
            "SELECT tier_key, popcorn_name FROM spec_tiers ORDER BY sort_order"
        )).mappings().all()
        tier_names = {t["tier_key"]: t["popcorn_name"] for t in tier_rows}
        tiers_out = [{"tier_key": t["tier_key"], "name": t["popcorn_name"]}
                     for t in tier_rows]

        grade_rows = conn.execute(text(
            "SELECT grade, label FROM game_load_grades ORDER BY sort_order"
        )).mappings().all()
        grade_labels = {g["grade"]: g["label"] for g in grade_rows}
        grades_out = [{"grade": g["grade"], "label": g["label"]} for g in grade_rows]

        usages = conn.execute(text(
            "SELECT DISTINCT usage FROM grid_cells WHERE usage <> '게임'"
            " ORDER BY usage"
        )).scalars().all()

        target_total = conn.execute(text(
            "SELECT count(*) FROM grid_cells WHERE NOT intended_empty")).scalar_one()
        filled_total = conn.execute(text(
            "SELECT count(*) FROM grid_cells c JOIN grid_quotes q"
            " ON q.cell_id = c.cell_id AND q.is_current AND q.tier_variant = :rv"
            " WHERE NOT c.intended_empty"), {"rv": REPRESENTATIVE_VARIANT}).scalar_one()

        last_batch_id = conn.execute(text(
            "SELECT max(batch_id) FROM grid_quotes")).scalar_one()
        last_batch = None
        if last_batch_id is not None:
            last_batch_at = conn.execute(text(
                "SELECT max(generated_at) FROM grid_quotes WHERE batch_id=:b"),
                {"b": last_batch_id}).scalar_one()
            success_count = conn.execute(text(
                "SELECT count(*) FROM grid_quotes WHERE batch_id=:b"
                " AND tier_variant=:rv"),
                {"b": last_batch_id, "rv": REPRESENTATIVE_VARIANT}).scalar_one()
            last_batch = {
                "batch_id": last_batch_id,
                "generated_at": _iso(last_batch_at),
                "target_count": target_total,
                "success_count": success_count,
                "fail_count": max(0, target_total - success_count),
            }

    return {
        "tiers": tiers_out,
        "game_grades": grades_out,
        "usages": list(usages),
        "cells": [{
            "cell_id": c["cell_id"], "tier_key": c["tier_key"],
            "usage": c["usage"], "game_grade": c["game_grade"],
            "game_resolution": c["game_resolution"],
            "label": _cell_label(c["tier_key"], c["usage"], c["game_grade"],
                                   c["game_resolution"], tier_names, grade_labels),
            "platform": c["platform"], "budget_min": c["budget_min"],
            "budget_max": c["budget_max"], "intended_empty": c["intended_empty"],
            "state": _cell_state(c, last_batch_id),
            "quote": None if c["quote_id"] is None else {
                "quote_id": c["quote_id"], "batch_id": c["batch_id"],
                "generated_at": _iso(c["generated_at"]), "total": c["total"],
                "verdict": c["verdict"], "status": c["status"],
            },
        } for c in cells],
        "target_count": target_total,
        "filled_count": filled_total,
        "last_batch": last_batch,
    }


@router.get("/grid/cells/{cell_id}")
def grid_cell(cell_id: int):
    """칸 상세 — 서랍이 보여주는 것: 3종(가성비/추천/고성능) 현재본의 구성
    (items)·근거(reasons)·판정을 전부 내려준다(0092, 화면이 탭으로 전환).
    게임 칸은 등급에 속한 게임 목록과 스펙(등급×해상도 조인)도 함께 준다."""
    with engine.connect() as conn:
        cell = conn.execute(text(
            "SELECT cell_id, tier_key, usage, game_grade, game_resolution,"
            " platform, budget_min, budget_max, intended_empty"
            " FROM grid_cells WHERE cell_id=:id"), {"id": cell_id}).mappings().first()
        if cell is None:
            raise HTTPException(404, "칸을 찾을 수 없습니다")

        quotes = conn.execute(text(
            "SELECT quote_id, tier_variant, batch_id, generated_at, engine_note,"
            " total, verdict, status, payload FROM grid_quotes"
            " WHERE cell_id=:id AND is_current"), {"id": cell_id}).mappings().all()

        quotes_by_variant = {}
        for q in quotes:
            payload = q["payload"] or {}
            raw_items = payload.get("items") or []
            codes = [it.get("product_code") for it in raw_items if it.get("product_code")]
            stock_by_code = {}
            if codes:
                stock_rows = conn.execute(text(
                    "SELECT product_code, stock_qty FROM products"
                    " WHERE product_code = ANY(:c)"), {"c": codes}).mappings().all()
                stock_by_code = {r["product_code"]: r["stock_qty"] for r in stock_rows}
            items = [{
                "slot": it.get("part_type"),
                "name": it.get("name"),
                "price": it.get("price"),
                "in_stock": stock_by_code.get(it.get("product_code"), 0) > 0,
            } for it in raw_items]
            quotes_by_variant[q["tier_variant"]] = {
                "quote_id": q["quote_id"], "batch_id": q["batch_id"],
                "generated_at": _iso(q["generated_at"]),
                "engine_note": q["engine_note"], "total": q["total"],
                "verdict": q["verdict"], "status": q["status"],
                "items": items, "reasons": payload.get("reasons") or [],
            }
        # 화면이 없음 상태를 지어내지 않도록, 데이터가 없는 variant는 명시적 None
        for v in VARIANTS:
            quotes_by_variant.setdefault(v, None)

        game_info = None
        if cell["usage"] == "게임":
            grade = cell["game_grade"]
            resolution = cell["game_resolution"]
            spec_row = conn.execute(text(
                "SELECT gpu_tier_key, cpu_tier_key_override, note"
                " FROM game_grade_resolution_tiers WHERE grade=:g AND resolution=:r"),
                {"g": grade, "r": resolution}).mappings().first()
            games = conn.execute(text(
                "SELECT g.name FROM game_grade_assignments a"
                " JOIN games g ON g.game_id = a.game_id"
                " WHERE a.grade=:g ORDER BY g.name"), {"g": grade}).scalars().all()
            game_info = {
                "grade": grade, "resolution": resolution,
                "gpu_tier_key": spec_row["gpu_tier_key"] if spec_row else None,
                "cpu_tier_key_override": spec_row["cpu_tier_key_override"] if spec_row else None,
                "note": spec_row["note"] if spec_row else None,
                "games": list(games),
            }

    return {
        "cell_id": cell["cell_id"], "tier_key": cell["tier_key"],
        "usage": cell["usage"], "game_grade": cell["game_grade"],
        "game_resolution": cell["game_resolution"],
        "platform": cell["platform"], "budget_min": cell["budget_min"],
        "budget_max": cell["budget_max"], "intended_empty": cell["intended_empty"],
        "game_info": game_info,
        "quotes": quotes_by_variant,
    }
