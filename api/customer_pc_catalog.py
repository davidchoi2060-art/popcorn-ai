# -*- coding: utf-8 -*-
"""고객용 판매 PC 목록 — /mvp4 상품 목록·메인의 원천 (2026-10-19 대표 지시 「메인 전면교체 · /mvp4」).

■ 왜 새로 만드나
  고객 화면에 «판매 중인 완제품 PC 전체 목록»을 주는 GET 이 없었다. 상품은 추천 응답(/api/grid/recommend)
  안에서만 나왔다. 승인 메인(v8.1)의 상품 목록·카테고리·대표 상품 줄은 목록이 있어야 그릴 수 있다.
  (v8.1 handoff-v7 §4 「고객 상품 목록 GET 계약은 아직 확정하지 않았다」 — 이 파일이 그 계약이다.)

■ 원천은 추천과 같다 — 술어를 두 벌 두지 않는다
  `admin_product_fit.load()`(추천 풀: product_fit_products · 제외·품절·단종 빼고 · sale_price 우선) 중
  products.status 가 「판매중」인 것만 낸다. 카드 이름·사양은 추천 카드와 같은 함수(card_name · card_spec)다.

■ 내지 않는 것 (allowlist 만 낸다)
  매입가·마진·공급처·부품 개별 단가·평가 내부 지수(cpu_mt·gpu_idx 등)·제외 사유. 부품 구성(BOM)·대표 사진은
  이 목록에 싣지 않는다 — 공개 판정이 상품마다 무겁고(사진 해시 대조), 정본은 상품 하나를 읽는
  `/api/customer/pc-offers/{code}` 와 `/api/customer/products/{code}/representative-image` 다. 목록은
  «공개 승인된 구성이 있다»는 힌트(configuration_public)와 «사진이 준비됐을 수 있다»는 힌트(photo_hint)만 준다.
  힌트가 참이어도 실제 공개 여부는 그 두 경로가 다시 판정한다(404 not_public 이면 고객 화면은 사진·구성 없음으로).

■ 분류(category)는 기획 분류다
  승인 메인의 다섯 카테고리(게이밍 PC · 사무·업무용 · 디자인·영상 · 미니 PC · AI·고성능 PC)를 용도 평가
  (product_usage_fit)와 몰 상품명으로 나눈다. 공식 카테고리·성능 보장이 아니다. 규칙은 `category_of()` 하나다.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Response
from sqlalchemy import text

from .admin_product_fit import load
from .db import engine
from .product_name import card_name, match_storage_shorthand
from .sold_reco import card_spec, public_codes

log = logging.getLogger("customer_pc_catalog")
router = APIRouter()

CATALOG_PATH = "/api/customer/pc-catalog"
IMAGE_URL = "/api/customer/products/{code}/representative-image?size=card"

CATEGORIES = ("게이밍 PC", "사무·업무용", "디자인·영상", "미니 PC", "AI·고성능 PC")
GENERAL = "일반 PC"
_MINI = re.compile(r"미니|슬림|mini", re.I)

# 대표 사진이 준비된 공개 구성(선택된 ready 미디어 작업). 힌트일 뿐 — 실제 판정은 이미지 경로가 한다.
MEDIA_HINT_SQL = """
    SELECT CAST(substr(o.offer_id, 2) AS bigint) AS product_code
      FROM pc_configuration_offers o
      JOIN pc_media_jobs j ON j.configuration_id = o.configuration_id AND j.selected AND j.status = 'ready'
     WHERE o.offer_id ~ '^P[1-9][0-9]{0,17}$'
"""


def _rank(p, usage):
    return int((p.get("fit") or {}).get(usage, {}).get("rank") or 0)


def category_of(p) -> str:
    """승인 메인의 기획 분류 하나. 앞에서부터 먼저 맞는 것.

    미니 PC     몰 상품명에 미니·슬림(형태는 이름만이 말한다)
    AI·고성능   로컬 AI 「쾌적」 이상 또는 3D 렌더링 「쾌적」 이상
    디자인·영상 영상편집 「쾌적」 이상 또는 디자인·조판 「쾌적」 이상
    게이밍 PC   게임 「FHD」 이상
    사무·업무용 사무용 평가가 있는 나머지
    """
    if _MINI.search(p.get("name") or ""):
        return "미니 PC"
    if _rank(p, "로컬 AI") >= 2 or _rank(p, "3D 렌더링") >= 2:
        return "AI·고성능 PC"
    if _rank(p, "영상편집") >= 2 or _rank(p, "디자인·조판") >= 2:
        return "디자인·영상"
    if _rank(p, "게임") >= 2:
        return "게이밍 PC"
    if _rank(p, "사무용") >= 1:
        return "사무·업무용"
    return GENERAL


def _media_hints() -> frozenset:
    try:
        with engine.connect() as conn:
            return frozenset(int(r.product_code) for r in conn.execute(text(MEDIA_HINT_SQL)))
    except Exception:  # noqa: BLE001 - 힌트라 목록을 막지 않는다
        log.exception("[customer_pc_catalog] media hints unavailable")
        return frozenset()


def _price(value):
    return value if type(value) is int and value > 0 else None


def item_of(p, public, media) -> dict:
    code = p["code"]
    spec = card_spec(p)
    return {
        "product_code": code,
        "name": match_storage_shorthand(card_name(p["name"]), p.get("spec")),
        "price": _price(p.get("price")),
        "price_basis": p.get("price_src"),
        "sale_status": p.get("status"),
        "mall_url": p.get("url") if isinstance(p.get("url"), str) and p["url"].startswith("https://") else None,
        "spec": spec if isinstance(spec, dict) else {},
        "fit": {u: f.get("level") for u, f in (p.get("fit") or {}).items() if (f or {}).get("rank")},
        "category": category_of(p),
        "configuration_public": code in public,
        "photo_hint": code in media and code in public,
        "image_url": IMAGE_URL.format(code=code),
    }


def catalog() -> list[dict]:
    _levels, products = load()
    public, media = public_codes(), _media_hints()
    items = [item_of(p, public, media) for p in products.values() if p.get("status") == "판매중"]
    items.sort(key=lambda it: (it["price"] is None, it["price"] or 0, it["product_code"]))
    return items


@router.get(CATALOG_PATH)
def read_catalog(response: Response):
    response.headers["Cache-Control"] = "no-store"
    items = catalog()
    return {"ok": True, "items": items, "count": len(items), "categories": list(CATEGORIES),
            "note": "가격은 쇼핑몰 판매가 기준이며 구매할 때 다시 확인합니다. 분류는 용도 평가로 나눈 안내용입니다."}
