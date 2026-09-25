# -*- coding: utf-8 -*-
"""판매 상품 용도 매트릭스 API — `GET /api/admin/product-fit` (2026-09-25 재설계 3단계).

■ 무엇을 하나
  0115 의 평가 결과(product_usage_fit)를 용도·단계 x 가격대 표로 묶어 돌려준다.
  칸마다 조건을 충족하는 **판매 중인 몰 조립PC** 를 모으고, 가장 싼 것을 대표로 둔다.
  한 상품이 여러 칸에 들어간다(같은 PC 가 개발·음악·주식에 다 맞으면 셋 다).

■ 가격은 현재값이다
  `products.sale_price` 가 있으면 그것, 없으면 평가 당시 몰 수집가(`price_src` 로 밝힌다).
  `products.status` 가 품절·단종·삭제대기면 뺀다. 평가 때 제외한 상품(품절 표시·
  상세 없음·테스트)도 뺀다.

■ 빈칸은 이유를 말한다 (사장님 승인 엑셀과 같은 판정)
  예산 부족       더 비싼 가격대에는 그 단계를 충족하는 상품이 있다
  더 싼 상품으로 충족  더 싼 가격대에만 있다 — 이 가격대에 따로 둘 이유가 없다
  보유 상품 없음   어느 가격대에도 없다 — 상품을 새로 만들지 검토할 자리
"""
from fastapi import APIRouter
from sqlalchemy import text

from .db import engine

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


def load():
    """(levels, products{code: dict}, fits{code: {usage: rank}}) — 판매 가능 상품만."""
    with engine.connect() as conn:
        levels = [dict(r._mapping) for r in conn.execute(text(
            "SELECT usage, level, level_rank, work, conditions FROM product_fit_levels ORDER BY sort_order"))]
        rows = conn.execute(text(
            "SELECT f.product_code, f.crawl_name, f.crawl_price, f.mall_url, f.excluded, f.includes,"
            " f.spec, f.balance, f.dominated_by, f.evaluated_at,"
            " p.sale_price, p.status, p.product_name"
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
            "price_src": "현재 판매가" if live_price else "몰 수집가(2026-09-25)",
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
