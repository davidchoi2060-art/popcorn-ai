# -*- coding: utf-8 -*-
"""ADM-GRD-010 격자 관리 — 사전 생성 견적 격자(grid_cells·grid_quotes) 조회 API.

배경 · 저장 구조 = `db/migrations/versions/0072_quote_grid.py`. 배치 도구 =
`tools/grid_generate.py`(이 모듈의 담당 밖 — 읽기만 한다).

■ 쓰기(재생성)는 이번 범위 밖이다 — 만들지 않는다. 화면의 재생성 버튼들은
  API가 없다는 사실을 그대로 disabled로 드러낸다(§화면 정직성 — 거짓 동작 금지).

■ 인증 — 다른 admin_*.py(예: `admin_pool.py`)와 같은 관행. 이 라우터의 prefix가
  `/api/admin`이라 `api/auth.py`의 `auth_middleware`가 세션·기본 인증을 이미
  강제한다(전 `/api/admin/*` 공통, 슬라이스 37). 이 모듈 자체는 별도 인증 코드를
  두지 않는다 — `admin_pool.py`도 그렇다(실측: 그 파일에 `current_operator` 호출 0건).

■ `grid_quotes.payload`는 recommend 엔진 응답의 해당 티어 build 전체(JSONB)다
  (`items[].part_type/name/price/product_code`·`reasons`·`budget` 등 —
  `api/recommend.py` `_build()` 반환 구조 실측). 이 모듈은 그 중 화면이 쓰는
  필드만 추려 낸다 — payload를 그대로 내려주지 않는 이유는 화면이 서버 내부
  구조에 결합되지 않게 하기 위함이다.

■ 칸 상세의 `in_stock`은 **지금 재고를 실조회**한 값이다(payload 저장 시점의
  재고가 아니다) — 견적 생성 뒤 품절될 수 있어, 저장된 값을 그대로 믿으면 이미
  틀린 사실을 말하게 된다. 지어낸 값이 아니라 `products.stock_qty`를 그 자리에서
  다시 읽은 값이라는 점을 주석으로 남긴다.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .db import engine
from .timeutil import iso as _iso   # 시각 표기 단일 원천(슬라이스 62) — naive를 UTC로 간주해
                                    # 타임존을 붙인다. 자체 isoformat()을 쓰면 브라우저가
                                    # 로컬 시각으로 오해해 9시간이 어긋난다(회귀가 잡았다).

router = APIRouter(prefix="/api/admin")


def _cell_state(c: dict, last_batch_id) -> str:
    """칸 색상·범례가 쓰는 6버킷 중 하나 — 화면이 각자 다시 판정하면 갈라지므로
    (§단일 원천) 여기 한 곳에서만 정의한다.

    `intent`/`missing`은 grid_cells 자체가 말하는 사실(의도적으로 비움 · 아직
    현재본 없음)이다. 견적이 있으면 우선 `grid_quotes.status`(엔진이 직접
    적은 값)를 따른다. **`fail`은 두 경우를 함께 묶는다** — ① status에 문자
    그대로 '실패'가 있는 경우(지금 배치 도구는 실패를 아예 기록하지 않지만,
    스키마 주석(`0072_quote_grid.py`)이 이 값을 예정해 둬 대비한다) ② 이
    칸의 현재본이 **최신 배치로 갱신되지 못한 경우**(batch_id가 최신과
    다름) — 재생성이 실패해 이전 견적이 그대로 남아 있다는 뜻이라 실질적으로
    같은 사실이다. 이걸 'ok'로 표시하면 "최신 배치가 이 칸을 성공적으로
    채웠다"는 거짓을 말하게 된다."""
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


@router.get("/grid")
def grid():
    """격자 전체 — 칸 112개(현재 스키마 기준, 지어내지 않는다: 실제로는 매 요청
    grid_cells를 다시 센다) + 각 칸의 현재본(is_current) 견적 요약. 플랫폼별로
    가르지 않고 전부 내려준다 — 화면이 플랫폼 토글을 클라이언트에서 필터링한다."""
    with engine.connect() as conn:
        cells = conn.execute(text(
            "SELECT c.cell_id, c.tier, c.usage, c.platform, c.budget_min, c.budget_max,"
            " c.intended_empty, q.quote_id, q.batch_id, q.generated_at, q.total,"
            " q.verdict, q.status"
            " FROM grid_cells c"
            " LEFT JOIN grid_quotes q ON q.cell_id = c.cell_id AND q.is_current"
            " ORDER BY c.cell_id"
        )).mappings().all()

        tiers = conn.execute(text(
            "SELECT tier AS name, budget_min, budget_max FROM grid_cells"
            " GROUP BY tier, budget_min, budget_max ORDER BY budget_min"
        )).mappings().all()
        # 용도(usage)는 별도 순번 컬럼이 없다 — 시드가 지어낸 순서 그대로
        # cell_id 오름차순으로 처음 등장한 순서를 쓴다(0072 시드가 티어마다
        # 같은 용도 순서로 넣었으므로 안정적이다).
        usages = conn.execute(text(
            "SELECT usage FROM grid_cells GROUP BY usage ORDER BY min(cell_id)"
        )).scalars().all()

        target_total = conn.execute(text(
            "SELECT count(*) FROM grid_cells WHERE NOT intended_empty")).scalar_one()
        filled_total = conn.execute(text(
            "SELECT count(*) FROM grid_cells c JOIN grid_quotes q"
            " ON q.cell_id = c.cell_id AND q.is_current"
            " WHERE NOT c.intended_empty")).scalar_one()

        # 배치 도구가 batch_id를 "YYYYMMDD-NN"(0패딩)으로 발급해(tools/grid_generate.py
        # `_next_batch_id`) 문자열 최댓값 = 최신 배치와 같다 — 별도 시각 컬럼 정렬이
        # 필요 없다.
        last_batch_id = conn.execute(text(
            "SELECT max(batch_id) FROM grid_quotes")).scalar_one()
        last_batch = None
        if last_batch_id is not None:
            last_batch_at = conn.execute(text(
                "SELECT max(generated_at) FROM grid_quotes WHERE batch_id=:b"),
                {"b": last_batch_id}).scalar_one()
            # grid_generate.py는 실패한 칸을 grid_quotes에 쓰지 않는다(콘솔 로그만
            # 남긴다) — 그래서 "성공"은 이 배치 ID로 실제 기록된 행 수, "실패"는
            # 배치 대상(intended_empty가 아닌 칸) 중 이 배치로 갱신되지 못한 나머지다.
            success_count = conn.execute(text(
                "SELECT count(*) FROM grid_quotes WHERE batch_id=:b"),
                {"b": last_batch_id}).scalar_one()
            last_batch = {
                "batch_id": last_batch_id,
                "generated_at": _iso(last_batch_at),
                "target_count": target_total,
                "success_count": success_count,
                "fail_count": max(0, target_total - success_count),
            }

    return {
        "tiers": [{"name": t["name"], "budget_min": t["budget_min"],
                   "budget_max": t["budget_max"]} for t in tiers],
        "usages": list(usages),
        "cells": [{
            "cell_id": c["cell_id"], "tier": c["tier"], "usage": c["usage"],
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
    """칸 상세 — 서랍이 보여주는 것: 현재본 견적의 구성(items)·근거(reasons)·
    예산 구간·판정. 현재본이 없으면(빈 칸) `quote: null`을 그대로 내려준다 —
    화면이 빈 상태 문구를 지어내지 않고 이 사실로 판단한다."""
    with engine.connect() as conn:
        cell = conn.execute(text(
            "SELECT cell_id, tier, usage, platform, budget_min, budget_max, intended_empty"
            " FROM grid_cells WHERE cell_id=:id"), {"id": cell_id}).mappings().first()
        if cell is None:
            raise HTTPException(404, "칸을 찾을 수 없습니다")

        quote = conn.execute(text(
            "SELECT quote_id, batch_id, generated_at, engine_note, total, verdict,"
            " status, payload FROM grid_quotes WHERE cell_id=:id AND is_current"),
            {"id": cell_id}).mappings().first()

        quote_out = None
        if quote is not None:
            payload = quote["payload"] or {}
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
                # 실조회 — 위 모듈 docstring 참조(견적 저장 시점이 아니라 지금 값)
                "in_stock": stock_by_code.get(it.get("product_code"), 0) > 0,
            } for it in raw_items]
            quote_out = {
                "quote_id": quote["quote_id"], "batch_id": quote["batch_id"],
                "generated_at": _iso(quote["generated_at"]),
                "engine_note": quote["engine_note"], "total": quote["total"],
                "verdict": quote["verdict"], "status": quote["status"],
                "items": items, "reasons": payload.get("reasons") or [],
            }

    return {
        "cell_id": cell["cell_id"], "tier": cell["tier"], "usage": cell["usage"],
        "platform": cell["platform"], "budget_min": cell["budget_min"],
        "budget_max": cell["budget_max"], "intended_empty": cell["intended_empty"],
        "quote": quote_out,
    }
