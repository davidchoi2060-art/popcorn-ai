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

■ 2026-09-16 승인 디자인(dc-grid-admin-2026-09-16.html) 반영 — `/grid` 응답에
  다섯 필드 추가(기존 필드는 손대지 않았다):
  · `tiers[].floor`      스펙 티어 행 머리의 하한 요약 문자열(`spec_tiers` 실컬럼
                         조합, `_tier_floor_text()`) — 원안이 TIERS 배열의 하드코딩
                         `floor` 텍스트로 보여주던 것을 서버 값으로 대체.
  · `game_grades[].game_count`  등급별 배정 게임 수(`game_grade_assignments`
                         실카운트) — 원안 GRADES 배열의 `games.length`를 대체.
  · `cells[].game_gpu_tier_key` / `cells[].game_cpu_tier_key_override`
                         게임 칸의 GPU/CPU 스펙 티어(`game_grade_resolution_tiers`
                         조인) — 목록 표에서 S등급 칸을 GPU/CPU 분리 표기하려면
                         상세 조회 전에도 이 값이 필요하다(원안 §④ isSplit 분기).
  · `cells[].variants_present`  이 칸에 실제로 존재하는 tier_variant 목록(부분
                         집합일 수 있다 — 배치 실패로 3종 중 일부만 있을 수 있음).
                         목록 칸의 점 3개(`d1`/`d2`/`d3`)가 지어낸 값이 아니라
                         이 배열의 존재 여부를 그대로 그리게 한다.
  · `unassigned_games`   `game_grade_assignments.grade IS NULL`인 게임(GTA 1건)
                         — 정의서 §⑦ 참고 정보, 강제 아님.
  · `game_info.grade_label` / `game_info.grade_note`(`/grid/cells/{id}`)
                         등급 자체의 명칭·판정 사유(`game_load_grades` 조인) —
                         기존엔 등급×해상도의 note만 있었고 "왜 이 등급인가"라는
                         등급 레벨 근거가 빠져 있었다(원안 §165-174 게임 서랍).
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .db import engine
from .timeutil import iso as _iso   # 시각 표기 단일 원천(슬라이스 62)

router = APIRouter(prefix="/api/admin")

VARIANTS = ["가성비", "추천", "고성능"]
REPRESENTATIVE_VARIANT = "추천"   # 목록 표에 대표로 얹는 본 — 정의서 §⑥-3

# ── 칸 취급 상태 (0110 · 사장님 확정 ⑥) ────────────────────────────────
# 옛 `intended_empty`(boolean)는 「시장에도 없다」와 「표본이 없어 모른다」를
# 구분하지 못했고, 134칸 전부 false 인 채 **쓰는 코드가 없었다**(읽기만).
# 이제 4값이고 화면이 셋을 갈라 보여 준다 — 「칸 없음」이 왜 없는지를 말한다.
STATE_ACTIVE = "취급함"
# 화면 색·범례가 쓰는 버킷으로 옮긴다. `_cell_state` 가 유일한 판정 자리다.
HANDLING_STATE_BUCKET = {
    "일부러 비움": "intent_none",     # 시장 표본은 있으나 우리가 그 구간을 취급하지 않는다
    "모름": "intent_unknown",         # 시장 표본이 0이라 판단 근거가 없다
    "채울 예정": "intent_planned",    # 취급하기로 했으나 아직 견적이 없다
}


def _cell_state(c: dict, last_batch_id) -> str:
    """칸 색상·범례가 쓰는 6버킷 중 하나 — 화면이 각자 다시 판정하면 갈라지므로
    (§단일 원천) 여기 한 곳에서만 정의한다. 대표본(추천) 기준으로 판정한다."""
    # 0110 — handling_state 4값. 「취급함」이 아닌 칸은 견적이 없는 것이 정상이고,
    # 그 사유(일부러 비움 / 모름 / 채울 예정)를 화면이 그대로 말해야 한다.
    # 옛 boolean(intended_empty)은 셋을 「intent」 한 버킷으로 뭉개 «칸 없음»으로
    # 보이게 했다 — 사장님 지적의 직접 원인이다.
    st = c["handling_state"]
    if st != STATE_ACTIVE:
        return HANDLING_STATE_BUCKET[st]
    if c["quote_id"] is None:
        return "missing"
    status = c["status"] or ""
    if "실패" in status:
        return "fail"
    if last_batch_id is not None and c["batch_id"] != last_batch_id:
        return "fail"
    if status == "예산 상한 초과":
        return "over"
    # 0110 — 「하한 미달」은 「상한 초과」와 다른 사실이다. 그 칸의 견적이 자기 구간
    # 이름보다 싸다는 뜻이고, 원인은 «그 하한으로는 그 값까지 못 올라간다»(부품 풀
    # 상한에 걸린다)이지 예산을 넘긴 것이 아니다. 같은 색으로 칠하면 화면이 거짓말한다.
    if status == "구간 하한 미달":
        return "under"
    if status == "재고 소진 슬롯 있음":
        return "stock"
    return "ok"


def _cell_label(usage, band_label, game_grade, game_resolution,
                 grade_labels: dict) -> str:
    """칸 표시명 — 비게임은 '디자인 · 실무 주력', 게임은 '게임(경쟁 이스포츠) · 1080p · FHD 고주사율'.

    0105 — 비게임 축에서 tier_key 가 사라졌으므로 팝콘 브랜드명을 쓰지 않는다.
    칸을 가르는 것은 용도와 **예산대**다.
    """
    if usage == "게임":
        g = grade_labels.get(game_grade, game_grade)
        return f"게임({g}) · {game_resolution} · {band_label}"
    return f"{usage} · {band_label}"


def _tier_floor_text(row: dict) -> str:
    """스펙 티어 행 머리에 쓰는 하한 요약 — spec_tiers 실컬럼만 쓴다(지어내지 않는다).
    T0는 gpu_vram_min_gb/gpu_watt_min이 실제로 NULL(0091 CHECK 제약)이라 'GPU 하한 없음'."""
    gpu = f"VRAM {row['gpu_vram_min_gb']}GB" if row["gpu_vram_min_gb"] is not None else "GPU 하한 없음"
    return f"{gpu} · {row['cpu_cores_min']}코어 · RAM {row['ram_min_gb']}GB · SSD {row['ssd_min_gb']}GB"


@router.get("/grid")
def grid():
    """격자 전체 — 칸 108개(현재 스키마 기준, 지어내지 않는다: 실제로는 매 요청
    grid_cells를 다시 센다) + 각 칸의 대표본("추천") 견적 요약. 플랫폼별로
    가르지 않고 전부 내려준다 — 화면이 플랫폼 토글을 클라이언트에서 필터링한다."""
    with engine.connect() as conn:
        cells = conn.execute(text(
            "SELECT c.cell_id, c.usage, c.budget_band_key, c.game_grade, c.game_resolution,"
            " c.platform, c.quote_low, c.quote_high, c.band_note,"
            " c.handling_state, c.handling_note,"
            " b.label AS band_label, b.budget_min_won, b.budget_max_won,"
            " b.sample_n AS band_sample_n, b.gpu_required, b.sort_order AS band_sort,"
            " q.quote_id, q.batch_id, q.generated_at, q.total, q.verdict, q.status,"
            " t.gpu_tier_key AS game_gpu_tier_key,"
            " t.cpu_tier_key_override AS game_cpu_tier_key_override"
            " FROM grid_cells c"
            " JOIN grid_budget_bands b ON b.band_key = c.budget_band_key"
            " LEFT JOIN grid_quotes q ON q.cell_id = c.cell_id AND q.is_current"
            "   AND q.tier_variant = :rv"
            " LEFT JOIN game_grade_resolution_tiers t"
            "   ON t.grade = c.game_grade AND t.resolution = c.game_resolution"
            " ORDER BY c.usage, b.sort_order, c.cell_id"
        ), {"rv": REPRESENTATIVE_VARIANT}).mappings().all()

        # 칸별 3종(가성비/추천/고성능) 존재 여부 — 목록 표의 점 3개가 쓴다.
        # 대표본(추천) 외 나머지 두 종은 여기서만 "있다/없다"를 판정하고 상세는 내려주지
        # 않는다(상세는 /grid/cells/{id}가 전담 — 목록 응답을 3배로 부풀리지 않는다).
        variant_rows = conn.execute(text(
            "SELECT cell_id, tier_variant FROM grid_quotes WHERE is_current"
        )).all()
        variants_by_cell: dict[int, set] = {}
        for row_cell_id, row_variant in variant_rows:
            variants_by_cell.setdefault(row_cell_id, set()).add(row_variant)

        tier_rows = conn.execute(text(
            "SELECT tier_key, popcorn_name, gpu_vram_min_gb, cpu_cores_min,"
            " ram_min_gb, ssd_min_gb FROM spec_tiers ORDER BY sort_order"
        )).mappings().all()
        tier_names = {t["tier_key"]: t["popcorn_name"] for t in tier_rows}
        tiers_out = [{"tier_key": t["tier_key"], "name": t["popcorn_name"],
                      "floor": _tier_floor_text(t)} for t in tier_rows]

        # 예산대 축(0105) — 행 머리가 쓴다. 근거(source)·표본 수를 그대로 내려준다:
        # 운영자가 "왜 이 구간인가"를 화면에서 바로 볼 수 있어야 한다.
        band_rows = conn.execute(text(
            "SELECT band_key, axis, label, budget_min_won, budget_max_won, budget_label,"
            " gpu_required, sample_n, source FROM grid_budget_bands ORDER BY sort_order"
        )).mappings().all()
        bands_out = [dict(b) for b in band_rows]

        # 등급별 배정 게임 수 — 행 머리의 "배정 N종"(실카운트, game_grade_assignments).
        grade_counts = dict(conn.execute(text(
            "SELECT grade, count(*) FROM game_grade_assignments"
            " WHERE grade IS NOT NULL GROUP BY grade"
        )).all())
        grade_rows = conn.execute(text(
            "SELECT grade, label FROM game_load_grades ORDER BY sort_order"
        )).mappings().all()
        grade_labels = {g["grade"]: g["label"] for g in grade_rows}
        grades_out = [{"grade": g["grade"], "label": g["label"],
                       "game_count": grade_counts.get(g["grade"], 0)} for g in grade_rows]

        usages = conn.execute(text(
            "SELECT DISTINCT usage FROM grid_cells WHERE usage <> '게임'"
            " ORDER BY usage"
        )).scalars().all()

        # 용도별로 «발행하지 않는» 구성과 그 사유(0106). 운영자가 «왜 이 용도만
        # 카드가 둘인가»를 화면에서 바로 볼 수 있어야 한다 — 고객 문구
        # (reason_public)와 근거(reason_source)를 둘 다 내려준다.
        omission_rows = conn.execute(text(
            "SELECT usage, tier_variant, reason_public, reason_source, decided_by,"
            " decided_at FROM grid_variant_omissions ORDER BY usage, tier_variant"
        )).mappings().all()
        omissions_out = [{**dict(o), "decided_at": _iso(o["decided_at"])}
                         for o in omission_rows]
        omitted_by_usage: dict[str, set] = {}
        for o in omission_rows:
            omitted_by_usage.setdefault(o["usage"], set()).add(o["tier_variant"])

        # 미배정 게임(grade IS NULL) — 등급 격자에 나타나지 않는 게임을 참고로 노출
        # (정의서 §⑦ · GTA 1건, 강제 아님 — 실제로 있으면 그대로 보여준다).
        unassigned_games = conn.execute(text(
            "SELECT g.name, a.note FROM game_grade_assignments a"
            " JOIN games g ON g.game_id = a.game_id"
            " WHERE a.grade IS NULL ORDER BY g.name"
        )).mappings().all()

        target_total = conn.execute(text(
            "SELECT count(*) FROM grid_cells WHERE handling_state = :st"),
            {"st": STATE_ACTIVE}).scalar_one()
        filled_total = conn.execute(text(
            "SELECT count(*) FROM grid_cells c JOIN grid_quotes q"
            " ON q.cell_id = c.cell_id AND q.is_current AND q.tier_variant = :rv"
            " WHERE c.handling_state = :st"),
            {"rv": REPRESENTATIVE_VARIANT, "st": STATE_ACTIVE}).scalar_one()

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
        "bands": bands_out,
        "game_grades": grades_out,
        "usages": list(usages),
        "variant_omissions": omissions_out,
        "unassigned_games": [{"name": g["name"], "note": g["note"]} for g in unassigned_games],
        "cells": [{
            "cell_id": c["cell_id"], "tier_key": None,       # 0105 로 축에서 사라짐(하위호환 키)
            "usage": c["usage"], "game_grade": c["game_grade"],
            "game_resolution": c["game_resolution"],
            "budget_band_key": c["budget_band_key"], "band_label": c["band_label"],
            "band_range": {"min": c["budget_min_won"], "max": c["budget_max_won"]},
            "band_sample_n": c["band_sample_n"], "band_note": c["band_note"],
            "gpu_required": c["gpu_required"],
            "label": _cell_label(c["usage"], c["band_label"], c["game_grade"],
                                   c["game_resolution"], grade_labels),
            "platform": c["platform"], "quote_low": c["quote_low"],
            "quote_high": c["quote_high"],
            "handling_state": c["handling_state"],
            "handling_note": c["handling_note"],
            "state": _cell_state(c, last_batch_id),
            "game_gpu_tier_key": c["game_gpu_tier_key"],
            "game_cpu_tier_key_override": c["game_cpu_tier_key_override"],
            "variants_present": sorted(variants_by_cell.get(c["cell_id"], set()),
                                        key=VARIANTS.index),
            # 이 칸이 «만들지 않기로 한» 구성(0106) — variants_present 에서 빠진
            # 이유가 «배치 실패»인지 «발행 안 함»인지를 화면이 구분할 수 있게 한다.
            "variants_omitted": sorted(omitted_by_usage.get(c["usage"], set()),
                                        key=VARIANTS.index),
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
            "SELECT c.cell_id, c.usage, c.budget_band_key, c.game_grade, c.game_resolution,"
            " c.platform, c.quote_low, c.quote_high, c.band_note,"
            " c.handling_state, c.handling_note,"
            " b.label AS band_label, b.budget_min_won, b.budget_max_won, b.budget_label,"
            " b.gpu_required, b.sample_n AS band_sample_n, b.source AS band_source"
            " FROM grid_cells c JOIN grid_budget_bands b ON b.band_key = c.budget_band_key"
            " WHERE c.cell_id=:id"), {"id": cell_id}).mappings().first()
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

        # 이 용도가 «발행하지 않는» 구성과 사유(0106) — None 인 variant 가
        # «실패»인지 «만들지 않기로 한 것»인지를 서랍이 말할 수 있게 한다.
        omissions = [dict(o) for o in conn.execute(text(
            "SELECT tier_variant, reason_public, reason_source, decided_by"
            " FROM grid_variant_omissions WHERE usage=:u ORDER BY tier_variant"),
            {"u": cell["usage"]}).mappings().all()]

        game_info = None
        if cell["usage"] == "게임":
            grade = cell["game_grade"]
            resolution = cell["game_resolution"]
            spec_row = conn.execute(text(
                "SELECT gpu_tier_key, cpu_tier_key_override, note"
                " FROM game_grade_resolution_tiers WHERE grade=:g AND resolution=:r"),
                {"g": grade, "r": resolution}).mappings().first()
            grade_row = conn.execute(text(
                "SELECT label, note FROM game_load_grades WHERE grade=:g"),
                {"g": grade}).mappings().first()
            games = conn.execute(text(
                "SELECT g.name FROM game_grade_assignments a"
                " JOIN games g ON g.game_id = a.game_id"
                " WHERE a.grade=:g ORDER BY g.name"), {"g": grade}).scalars().all()
            game_info = {
                "grade": grade, "resolution": resolution,
                "gpu_tier_key": spec_row["gpu_tier_key"] if spec_row else None,
                "cpu_tier_key_override": spec_row["cpu_tier_key_override"] if spec_row else None,
                "note": spec_row["note"] if spec_row else None,
                "grade_label": grade_row["label"] if grade_row else None,
                "grade_note": grade_row["note"] if grade_row else None,
                "games": list(games),
            }

    return {
        "cell_id": cell["cell_id"], "tier_key": None,     # 0105 로 축에서 사라짐(하위호환 키)
        "usage": cell["usage"], "game_grade": cell["game_grade"],
        "game_resolution": cell["game_resolution"],
        "budget_band_key": cell["budget_band_key"], "band_label": cell["band_label"],
        "band_range": {"min": cell["budget_min_won"], "max": cell["budget_max_won"]},
        "band_budget_label": cell["budget_label"],
        "band_sample_n": cell["band_sample_n"], "band_source": cell["band_source"],
        "band_note": cell["band_note"], "gpu_required": cell["gpu_required"],
        "platform": cell["platform"], "quote_low": cell["quote_low"],
        "quote_high": cell["quote_high"],
        "handling_state": cell["handling_state"],
        "handling_note": cell["handling_note"],
        "game_info": game_info,
        "variant_omissions": omissions,
        "quotes": quotes_by_variant,
    }
