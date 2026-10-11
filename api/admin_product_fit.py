# -*- coding: utf-8 -*-
"""판매 상품 용도 매트릭스 API — `GET /api/admin/product-fit` (2026-09-25 재설계 3단계).

■ 무엇을 하나
  0115 의 평가 결과(product_usage_fit)를 용도·단계 x 가격대 표로 묶어 돌려준다.
  칸마다 조건을 충족하는 **판매 중인 몰 조립PC** 를 모으고, 가장 싼 것을 대표로 둔다.
  한 상품이 여러 칸에 들어간다(같은 PC 가 개발·음악·주식에 다 맞으면 셋 다).

■ 가격은 현재값이다
  `products.sale_price` 가 있으면 그것, 없으면 평가 당시 몰 수집가(`price_src` 로 밝힌다).
  판매가는 마지막 변경 날짜와 경로를 함께 밝힌다(R10 · `price_basis`).
  `products.status` 가 품절·단종·삭제대기면 뺀다. 평가 때 제외한 상품(품절 표시·
  상세 없음·테스트)도 뺀다.

■ 빈칸은 이유를 말한다 (사장님 승인 엑셀과 같은 판정)
  예산 부족       더 비싼 가격대에는 그 단계를 충족하는 상품이 있다
  더 싼 상품으로 충족  더 싼 가격대에만 있다 — 이 가격대에 따로 둘 이유가 없다
  보유 상품 없음   어느 가격대에도 없다 — 상품을 새로 만들지 검토할 자리
"""
from datetime import timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import text

from .db import engine

KST = timezone(timedelta(hours=9))

router = APIRouter(prefix="/api/admin")

# 가격대 — 사장님이 승인한 검토 엑셀(용도x가격 미리보기)과 같은 경계.
BANDS = [
    ("B0", "~90만", 0, 900_000),
    ("B1", "90~130만", 900_000, 1_300_000),
    ("B2", "130~180만", 1_300_000, 1_800_000),
    ("B3", "180~250만", 1_800_000, 2_500_000),
    ("B4", "250~350만", 2_500_000, 3_500_000),
    ("B5", "350~500만", 3_500_000, 5_000_000),
    ("B6", "500만~", 5_000_000, None),
]
DEAD_STATUS = ("품절", "단종", "삭제대기")


def band_of(price):
    if price is None:
        return None
    for key, _lab, lo, hi in BANDS:
        if price >= lo and (hi is None or price < hi):
            return key
    return None


# 2026-10-11 품질관리 R10: 카드가 「현재 판매가」라고 적었는데 그 값은 9/28 쇼핑몰 CSV 적재에서
# 멈춰 있었고, 쇼핑몰 조립PC 가격은 부품값에 따라 계속 움직였다(6개 모두 차이). 값은 그대로 두고
# 그 값이 언제 어디서 온 것인지를 밝힌다. 이력 시각은 서버 UTC 라 한국 날짜로 바꿔 적는다.
PRICE_CONFIRM = "구매할 때 확정"


def price_basis(sale_at, reason):
    """판매가 출처 문구 — 마지막 판매가 변경 날짜와 경로. 이력이 없으면 기준일을 모른다고 적는다."""
    if sale_at is None:
        return "쇼핑몰 판매가(기준일 미확인) · " + PRICE_CONFIRM
    day = sale_at + timedelta(hours=9) if sale_at.tzinfo is None else sale_at.astimezone(KST)
    where = "쇼핑몰 가격" if reason == "csv" else "판매가"
    return f"{day.month}월 {day.day}일 기준 {where} · {PRICE_CONFIRM}"


def load():
    """(levels, products{code: dict}, fits{code: {usage: rank}}) — 판매 가능 상품만."""
    with engine.connect() as conn:
        levels = [dict(r._mapping) for r in conn.execute(text(
            "SELECT usage, level, level_rank, work, conditions FROM product_fit_levels ORDER BY sort_order"))]
        rows = conn.execute(text(
            "SELECT f.product_code, f.crawl_name, f.crawl_price, f.mall_url, f.excluded, f.includes,"
            " f.spec, f.balance, f.dominated_by, f.evaluated_at,"
            " p.sale_price, p.status, p.product_name,"
            " (SELECT h.changed_at FROM product_price_history h WHERE h.product_code = f.product_code"
            "   AND h.field = 'sale' ORDER BY h.changed_at DESC LIMIT 1) AS sale_at,"
            " (SELECT h.reason FROM product_price_history h WHERE h.product_code = f.product_code"
            "   AND h.field = 'sale' ORDER BY h.changed_at DESC LIMIT 1) AS sale_reason"
            " FROM product_fit_products f LEFT JOIN products p ON p.product_code = f.product_code")).all()
        fit_rows = conn.execute(text(
            "SELECT product_code, usage, level, level_rank, blocked FROM product_usage_fit")).all()
    products = {}
    for r in rows:
        m = dict(r._mapping)
        if m["excluded"] or (m["status"] in DEAD_STATUS):
            continue
        live_price = m["sale_price"] is not None
        price = m["sale_price"] if live_price else m["crawl_price"]
        products[m["product_code"]] = {
            "code": m["product_code"], "name": m["crawl_name"], "price": price,
            "price_src": price_basis(m["sale_at"], m["sale_reason"]) if live_price else "몰 수집가(2026-09-25)",
            "status": m["status"], "url": m["mall_url"], "includes": m["includes"],
            "spec": m["spec"], "balance": m["balance"], "dominated_by": m["dominated_by"],
            "band": band_of(price), "fit": {},
        }
    for r in fit_rows:
        p = products.get(r.product_code)
        if p is not None:
            p["fit"][r.usage] = {"level": r.level, "rank": r.level_rank, "blocked": r.blocked}
    return levels, products


def build_cells(levels, products):
    cells = []
    for lv in levels:
        u, rank = lv["usage"], lv["level_rank"]
        ok = [p for p in products.values() if p["fit"].get(u, {}).get("rank", 0) >= rank and p["price"] is not None]
        for key, lab, lo, hi in BANDS:
            hits = sorted((p for p in ok if p["band"] == key), key=lambda p: p["price"])
            cell = {"usage": u, "level": lv["level"], "band": key, "count": len(hits),
                    "codes": [p["code"] for p in hits]}
            if hits:
                cell["rep"] = hits[0]["code"]
            else:
                above = [p["price"] for p in ok if hi is not None and p["price"] >= hi]
                below = [p["price"] for p in ok if p["price"] < lo]
                if above:
                    cell["reason"] = "예산 부족"
                    cell["reason_note"] = f"최저 {min(above):,}원부터"
                elif below:
                    cell["reason"] = "더 싼 상품으로 충족"
                    cell["reason_note"] = f"{max(below):,}원 이하에 있음"
                else:
                    cell["reason"] = "보유 상품 없음"
                    cell["reason_note"] = "이 단계를 충족하는 판매 상품이 없음"
            cells.append(cell)
    return cells


@router.get("/product-fit")
def product_fit():
    levels, products = load()
    return {
        "bands": [{"key": k, "label": lab, "min": lo, "max": hi} for k, lab, lo, hi in BANDS],
        "levels": levels,
        "cells": build_cells(levels, products),
        "products": list(products.values()),
        "live_count": len(products),
    }
