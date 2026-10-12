# -*- coding: utf-8 -*-
"""고객 화면 부품 정보 빈칸 -- 기존 데이터 -> 팝콘PC 공개 페이지 -> 운영자 확인 (2026-10-12 사장님 지시).

사장님 원문(2026-10-12, 코덱스 24조합 검수 v2 후속):
  > "만약 팝콘PC 웹 크롤링을 해서도 확인이 정 안되면 운영자(사람)가 하게 하도록"

■ 무엇을 다루나 -- 고객 상세(mvp3 「부품 구성과 선택 이유」)의 두 빈칸
  ① 부품 줄 「가격 확인 중」   customer_pc_offer._public_offer 가 근거 없는 판매가를 숨긴 줄
                              (공급처 표에 「가능」 행이 없거나, 판매가가 없거나, 부품 설명이 상품에 안 이어짐)
  ② 「부품 구성 정보는 아직 연결되지 않았어요」  판매중 완제품 PC 인데 공개 구성표(P{상품번호} offer)가 없음

■ 채우는 순서 -- 추측 값으로 채우지 않는다
  1) 기존 데이터   공급처 표(product_supplier_prices) 「가능」 행 + 판매가(products.sale_price). 이미 고객 화면이 쓰는 판정 그대로.
  2) 공개 페이지   팝콘PC 손님용 상품 페이지(/shop/product_detail.html?pd_no=)를 익명 GET 으로 읽는다(api/mall.fetch_prices --
                  보관 견적 쇼핑몰 연결 직전 가격 확인과 같은 함수). «판매중이고 그 가격이 우리 판매가와 같다»면 근거로 남긴다
                  (mall_price_checks · note 「bom-gap: mall on sale」). 다르거나 품절·못 읽음이면 근거로 쓰지 않는다.
  3) 운영자 확인   그래도 안 되는 줄은 관리자 화면(/admin2/customer-bom-gaps)에 「운영자 확인 필요」로 올린다. 운영자가 팝콘PC에서
                  직접 확인하고 «지금 판매가로 살 수 있다»를 확정하면(note 「bom-gap: operator confirmed」) 근거가 된다. 판매가가
                  틀렸으면 상품 관리에서 판매가부터 고친다 -- 이 화면은 판매가를 바꾸지 않는다.
  구성표 미등록(②)은 공개 페이지로 채울 수 없다 -- 구성표는 부품 설명·고객 문구·공개 승인이 함께 있어야 한다(tools/import_pc_configuration_copy).
  그래서 언제나 운영자 확인이다(조립PC 제품군 화면).

■ 근거의 유효 기간 -- EVIDENCE_DAYS
  공개 페이지 확인·운영자 확정은 그 시점의 사실이다. 판매가가 바뀌면(값 불일치) 바로 무효이고, 같아도 EVIDENCE_DAYS 가 지나면
  다시 확인해야 한다. 가장 최근 bom-gap 기록 하나만 본다 -- 뒤에 「품절」로 다시 읽혔으면 앞의 확인은 쓰지 않는다.

■ 고객 화면은 미확인을 그대로 보인다 -- 근거가 없으면 「가격 확인 중」(mockups/mvp3/app.js otherRow·partLinePrice).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from .db import engine
from .product_name import display_name

log = logging.getLogger("customer_bom_gaps")
router = APIRouter()

EVIDENCE_DAYS = 7
NOTE_ON_SALE = "bom-gap: mall on sale"
NOTE_OPERATOR = "bom-gap: operator confirmed"
NOTE_PREFIX = "bom-gap:"
MAX_CHECK = 60                       # 한 번에 공개 페이지를 읽는 부품 수(api/mall 은 동시 4건 -- 남의 서버다)
SOURCE_URL = "https://popcornpc.co.kr/shop/product_detail.html?pd_no=%s"

# 가장 최근 bom-gap 기록이 «지금 판매가로 판매중»을 말하고 유효 기간 안이면 참. customer_pc_offer 가 같은 조각을 쓴다.
EVIDENCE_SQL = f"""EXISTS (SELECT 1 FROM (SELECT c.outcome, c.mall_price, c.checked_at FROM mall_price_checks c
     WHERE c.product_code = p.product_code AND c.note LIKE '{NOTE_PREFIX}%'
     ORDER BY c.checked_at DESC, c.check_id DESC LIMIT 1) last
   WHERE last.outcome = 'same' AND last.mall_price = p.sale_price
     AND last.checked_at > now() - interval '{EVIDENCE_DAYS} days')"""

# 고객 추천에 나오는 판매중 완제품 PC(평가 제외 아님)의 구성표 부품 중, 고객 화면이 가격을 숨기는 부품 -- 부품 단위로 묶는다
# (부품 하나를 고치면 그 부품을 쓰는 PC 가 한꺼번에 풀린다). 숨김 판정은 customer_pc_offer 와 같다.
PRICE_GAPS_SQL = f"""
WITH pool AS (
  SELECT o.configuration_id, CAST(substr(o.offer_id, 2) AS bigint) AS pc_code
    FROM pc_configuration_offers o
    JOIN products pc ON pc.product_code = CAST(substr(o.offer_id, 2) AS bigint) AND pc.status = '판매중'
    JOIN product_fit_products f ON f.product_code = pc.product_code AND f.excluded IS NULL
   WHERE o.offer_id ~ '^P[1-9][0-9]{{0,17}}$'),
parts AS (
  SELECT pp.explanation_code, pp.slot, pool.pc_code
    FROM pool JOIN pc_configuration_parts pp ON pp.configuration_id = pool.configuration_id AND NOT pp.pseudo)
SELECT parts.explanation_code, min(parts.slot) AS slot, e.product_code AS part_code,
       p.product_name, p.sale_price, p.status,
       count(DISTINCT parts.pc_code) AS pc_count,
       (array_agg(DISTINCT parts.pc_code ORDER BY parts.pc_code))[1:5] AS pc_examples,
       (SELECT count(*) FROM product_supplier_prices sp WHERE sp.product_code = p.product_code) AS n_supply,
       (SELECT count(*) FROM product_supplier_prices sp WHERE sp.product_code = p.product_code
           AND sp.supply_state = '가능') AS n_available,
       (p.product_code IS NOT NULL AND {EVIDENCE_SQL}) AS has_evidence
  FROM parts
  LEFT JOIN product_explanations e ON e.source_product_code = parts.explanation_code
  LEFT JOIN products p ON p.product_code = e.product_code
 GROUP BY parts.explanation_code, e.product_code, p.product_code, p.product_name, p.sale_price, p.status
"""

LAST_CHECK_SQL = f"""SELECT DISTINCT ON (product_code) product_code, checked_at, mall_price, our_price, outcome, note
  FROM mall_price_checks WHERE product_code = ANY(:codes) AND note LIKE '{NOTE_PREFIX}%'
 ORDER BY product_code, checked_at DESC, check_id DESC"""

NO_BOM_SQL = """SELECT p.product_code, p.product_name, p.sale_price
  FROM products p JOIN product_fit_products f ON f.product_code = p.product_code AND f.excluded IS NULL
 WHERE p.part_type = 'PC_COMPLETE' AND p.status = '판매중'
   AND NOT EXISTS (SELECT 1 FROM pc_configuration_offers o WHERE o.offer_id = 'P' || p.product_code::text)
 ORDER BY p.sale_price NULLS LAST, p.product_code"""

CAUSE_UNLINKED = "부품 설명이 상품에 이어지지 않음"
CAUSE_NO_PRICE = "판매가 없음"
CAUSE_NO_SUPPLY = "공급처 기록 없음"
CAUSE_SOLDOUT = "공급처 전부 품절"


def cause_of(row: dict) -> str | None:
    """고객 화면이 이 부품 가격을 숨기는 이유. 숨기지 않으면 None."""
    if row.get("part_code") is None:
        return CAUSE_UNLINKED
    price = row.get("sale_price")
    if type(price) is not int or price <= 0:
        return CAUSE_NO_PRICE
    if (row.get("n_available") or 0) > 0 or row.get("has_evidence"):
        return None
    return CAUSE_NO_SUPPLY if not row.get("n_supply") else CAUSE_SOLDOUT


def judge_mall(our_price, mall: dict | None) -> tuple[str, str]:
    """공개 페이지 결과 -> (mall_price_checks.outcome, 상태 문장). 'same' 만 근거가 된다."""
    if not mall or not mall.get("ok") or type(mall.get("price")) is not int or mall["price"] <= 0:
        return "failed", "팝콘PC 페이지에서 가격을 읽지 못했어요"
    if mall.get("soldout"):
        return "stale", "팝콘PC에서도 품절이에요"
    if type(our_price) is not int or mall["price"] != our_price:
        return "held", "팝콘PC 판매가(%s원)가 우리 판매가와 달라요" % format(mall["price"], ",")
    return "same", "팝콘PC에서 판매중 · 같은 가격으로 확인했어요"


def status_of(row: dict, last: dict | None) -> tuple[str, str]:
    """(키, 운영자에게 보일 다음 할 일). 키: confirmed | operator."""
    if row.get("has_evidence"):
        return "confirmed", "확인 근거가 있어 고객 화면에 가격이 보여요"
    c = row["cause"]
    if c == CAUSE_UNLINKED:
        return "operator", "부품 설명 관리에서 이 부품 설명을 판매 상품에 이어 주세요"
    if c == CAUSE_NO_PRICE:
        return "operator", "상품 관리에서 판매가를 정해 주세요"
    if last and last.get("outcome") == "held":
        return "operator", "팝콘PC 판매가와 다릅니다 -- 상품 관리에서 판매가를 확인한 뒤 「확인 완료」를 눌러 주세요"
    if last and last.get("outcome") == "stale":
        return "operator", "팝콘PC에서도 품절입니다 -- 대체 부품·구성 판매 여부를 확인해 주세요"
    return "operator", "팝콘PC에서 직접 확인한 뒤 「확인 완료」를 눌러 주세요(또는 공급처 수집을 다시 돌려 주세요)"


def price_gaps(conn) -> list[dict]:
    rows = [dict(r) for r in conn.execute(text(PRICE_GAPS_SQL)).mappings()]
    out = []
    for r in rows:
        r["cause"] = cause_of(r)
        if r["cause"] is None and not r.get("has_evidence"):
            continue
        if r["cause"] is None:
            r["cause"] = "기존 근거 없음 · 확인 기록으로 표시 중"
        out.append(r)
    codes = [r["part_code"] or r["explanation_code"] for r in out]
    last = {x["product_code"]: dict(x) for x in conn.execute(text(LAST_CHECK_SQL), {"codes": codes}).mappings()} \
        if codes else {}
    for r in out:
        lc = last.get(r["part_code"] or r["explanation_code"])
        r["status"], r["todo"] = status_of(r, lc)
        r["last_check"] = None if lc is None else {
            "checked_at": lc["checked_at"].isoformat(sep=" ", timespec="minutes") if lc.get("checked_at") else None,
            "mall_price": lc.get("mall_price"), "outcome": lc.get("outcome"), "note": lc.get("note")}
        r["name"] = display_name(r.pop("product_name")) if r.get("product_name") else None
    out.sort(key=lambda r: (r["status"] != "operator", -r["pc_count"], r["explanation_code"]))
    return out


def no_bom(conn) -> list[dict]:
    return [{"product_code": r["product_code"], "name": display_name(r["product_name"]), "sale_price": r["sale_price"],
             "status": "operator", "todo": "조립PC 제품군에서 구성표(부품·고객 문구)를 등록하고 공개 승인해 주세요"}
            for r in conn.execute(text(NO_BOM_SQL)).mappings()]


def record(conn, code: int, our_price, mall_price, outcome: str, note: str, moment: str = "manual") -> None:
    conn.execute(text(
        "INSERT INTO mall_price_checks (moment, product_code, our_price, mall_price, diff, outcome, note, source_url)"
        " VALUES (:m, :c, :o, :mp, :d, :out, :n, :u)"),
        {"m": moment, "c": code, "o": our_price, "mp": mall_price,
         "d": (mall_price - our_price) if type(mall_price) is int and type(our_price) is int else None,
         "out": outcome, "n": note[:200], "u": SOURCE_URL % code})


def check_mall(codes: list[int] | None = None, fetch=None) -> dict:
    """2단계 -- 운영자 확인 필요인 부품을 팝콘PC 공개 페이지로 다시 읽고 기록한다. fetch 는 시험용 주입(api.mall.fetch_prices)."""
    if fetch is None:
        from .mall import fetch_prices as fetch
    with engine.connect() as conn:
        gaps = [g for g in price_gaps(conn) if g["status"] == "operator" and g["cause"] != CAUSE_NO_PRICE]
    if codes:
        want = set(codes)
        gaps = [g for g in gaps if (g["part_code"] or g["explanation_code"]) in want]
    gaps = gaps[:MAX_CHECK]
    targets = {g["part_code"] or g["explanation_code"]: g for g in gaps}
    results = fetch(list(targets)) if targets else {}
    summary = {"checked": 0, "confirmed": 0, "operator": 0, "items": []}
    with engine.begin() as conn:
        for code, g in targets.items():
            mall = results.get(code)
            outcome, said = judge_mall(g.get("sale_price"), mall)
            if g["part_code"] is None and outcome == "same":
                outcome, said = "held", "판매 상품에 이어지지 않은 부품이라 근거로 쓰지 않아요"
            note = (NOTE_ON_SALE if outcome == "same" else NOTE_PREFIX + " " + said)
            record(conn, code, g.get("sale_price"), mall.get("price") if mall else None, outcome, note)
            summary["checked"] += 1
            summary["confirmed" if outcome == "same" else "operator"] += 1
            summary["items"].append({"code": code, "outcome": outcome, "said": said})
    log.info("[bom-gaps] mall check: checked=%d confirmed=%d operator=%d",
             summary["checked"], summary["confirmed"], summary["operator"])
    return summary


# ── 관리자 API (/api/admin/* -- 읽기 viewer · 쓰기 operator, api/auth.required_role) ──────────────────────
@router.get("/api/admin/customer-bom-gaps")
def list_gaps(status: str = Query("", pattern="^(|operator|confirmed)$")):
    with engine.connect() as conn:
        parts = price_gaps(conn)
        pcs = no_bom(conn)
    shown = [p for p in parts if not status or p["status"] == status]
    return {"parts": shown, "pcs_without_bom": pcs,
            "counts": {"parts_operator": sum(p["status"] == "operator" for p in parts),
                       "parts_confirmed": sum(p["status"] == "confirmed" for p in parts),
                       "pcs_without_bom": len(pcs)},
            "evidence_days": EVIDENCE_DAYS,
            "note": ("순서: 기존 데이터(공급처 표) -> 팝콘PC 공개 페이지 -> 운영자 확인. 근거가 없는 줄은 고객 화면에 "
                     "「가격 확인 중」으로 보이고, 추측 값으로 채우지 않습니다.")}


class CheckBody(BaseModel):
    codes: list[int] | None = Field(default=None, max_length=MAX_CHECK)


@router.post("/api/admin/customer-bom-gaps/check")
def run_check(body: CheckBody):
    return {"ok": True, **check_mall(body.codes)}


class ConfirmBody(BaseModel):
    price: int = Field(gt=0)
    memo: str = Field(default="", max_length=120)


@router.post("/api/admin/customer-bom-gaps/parts/{part_code}/confirm")
def confirm(part_code: int, body: ConfirmBody):
    """3단계 -- 운영자가 팝콘PC에서 직접 확인했다: «이 부품을 지금 판매가로 살 수 있다». 판매가가 다르면 막는다."""
    from .admin_orders import _log
    with engine.begin() as conn:
        p = conn.execute(text("SELECT product_code, sku, sale_price FROM products WHERE product_code = :c"),
                         {"c": part_code}).mappings().first()
        if p is None:
            raise HTTPException(404, "판매 상품이 아닙니다 -- 부품 설명을 상품에 먼저 이어 주세요")
        if p["sale_price"] != body.price:
            raise HTTPException(409, "입력한 가격이 우리 판매가(%s원)와 다릅니다 -- 상품 관리에서 판매가를 먼저 고쳐 주세요"
                                % format(p["sale_price"] or 0, ","))
        log_id = _log(conn, "customer_bom_gap_confirm", p["sku"] or str(part_code),
                      {"product_code": part_code, "price": body.price, "memo": body.memo}, kind="product")
        record(conn, part_code, p["sale_price"], body.price, "same",
               "%s #%s %s" % (NOTE_OPERATOR, log_id, body.memo))
    return {"ok": True, "log_id": log_id, "valid_days": EVIDENCE_DAYS}
