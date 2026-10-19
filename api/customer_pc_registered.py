# -*- coding: utf-8 -*-
"""부품표가 공개 승인되지 않은 판매 PC 의 «몰 등록 구성» — /mvp4 상세의 부품 구성 표 (2026-10-20 대표 지시).

■ 왜
  판매 중인 조립PC 211대 중 129대는 승인된 구성(P 오퍼)이 없어 상세가 빈 상자·사진 없음·견적 보관 막힘이었다.
  대표: 「부품표도 채워서 넣어」「사용자에게 반복적인 일을 시키지 마」「판매를 사전에 막지 마 — 금액·사양이 안 맞으면
  상담사가 전화로 조정해 판매한다」. 그래서 몰에 등록된 구성(products.spec_source_text, 「슬롯@@값,@@…」)을 그대로 읽어
  다른 PC 와 같은 «한눈에 보는 부품 구성» 표로 보인다. 화면은 «몰 등록 구성 기준 · 최종 구성은 상담 시 확정»이라고만 밝힌다.

■ 부품 사진·설명
  승인된 구성(공개 승인 79개)의 오퍼 상품에서 «같은 몰 옵션 문구 = 같은 부품»을 배운다: 그 오퍼의 spec_source_text 슬롯 값과
  pc_configuration_parts(같은 슬롯·한 개뿐)를 맞대어 문구 → 부품 설명 코드를 만든다. 같은 문구가 나오면 그 부품의
  승인된 사진(/api/product-images/{code}/detail)과 역할 설명을 붙인다. 못 맞추면 아이콘으로 둔다.

■ 내지 않는 것
  매입가·부품 단가·마진. 미선택 옵션(「…를 선택하세요」)·사은품·배송 문구는 부품이 아니라 뺀다(조립·A/S 문구는 따로 낸다).
"""
from __future__ import annotations

import re
import threading
import time

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import text

from .db import engine
from .html_text import strip_html_display

router = APIRouter()

SLOTS = {"프로세서(CPU)": "CPU", "CPU쿨러": "COOLER", "메모리(RAM)": "RAM", "메인보드": "MB", "그래픽(VGA)": "GPU",
         "초고속(SSD)": "SSD", "대용량(HDD)": "HDD", "케이스": "CASE", "파워": "POWER"}
ORDER = ["CPU", "GPU", "RAM", "SSD", "HDD", "MB", "COOLER", "POWER", "CASE"]
SERVICE_SLOT = "조립비+AS"
_UNSELECTED = re.compile(r"선택하세요|선택안함|선택 안함|해당없음|선택하셔요")
_QTY = re.compile(r"\*\s*(\d+)\s*개")
_TRADEMARK = re.compile(r"[™®]")
_TTL = 600
_cache = {"at": 0.0, "lex": {}, "names": {}}
# 사진을 아직 못 붙인 옵션은 상품 DB 의 같은 부품 상품을 이름으로 찾아 팝콘PC 몰의 그 부품 사진을 쓴다(2026-10-20 대표 「부품 이미지도 만들어」).
PART_TYPES = {"CPU": ["CPU"], "COOLER": ["COOLER_CPU_AIR", "COOLER_CPU_AIO"], "RAM": ["RAM"], "MB": ["MB"], "GPU": ["GPU"],
              "SSD": ["SSD"], "HDD": ["HDD"], "CASE": ["CASE"], "POWER": ["POWER"]}
MALL_IMG = "https://www.popcornpc.co.kr/data/pimg/{d}/{c}_600.jpg"
_lock = threading.Lock()


def split(spec_source_text: str | None) -> list[tuple[str, str]]:
    """몰 구성 원문 → [(슬롯 이름, 값 원문)] (태그 벗김). 못 읽으면 []."""
    if not spec_source_text or "@@" not in spec_source_text:
        return []
    out = []
    for chunk in spec_source_text.split(",@@"):
        if "@@" not in chunk:
            continue
        slot, val = chunk.split("@@", 1)
        slot = re.sub(r"\s+", "", strip_html_display(slot) or "")
        val = re.sub(r"\s+", " ", strip_html_display(val) or "").strip(" ,")
        if slot and val:
            out.append((slot, val))
    return out


def key(val: str) -> str:
    """같은 부품을 찾는 비교 키 — 공백·상표 기호·대소문자 차이만 지운다."""
    return re.sub(r"\s+", "", _TRADEMARK.sub("", val)).lower()


def rows(spec_source_text):
    """부품 행 [{slot, name, quantity, key}] 과 조립·A/S 문구. 미선택 옵션은 뺀다."""
    parts, service = [], None
    for slot, val in split(spec_source_text):
        if slot == SERVICE_SLOT:
            service = val if not _UNSELECTED.search(val) else None
            continue
        pt = SLOTS.get(slot)
        if pt is None or _UNSELECTED.search(val):
            continue
        m = _QTY.search(val)
        name = re.sub(r"\s+", " ", _TRADEMARK.sub("", _QTY.sub(" ", val))).strip(" ,/-")
        if len(name) < 2:
            continue
        parts.append({"slot": pt, "name": name, "quantity": int(m.group(1)) if m else 1, "key": key(_QTY.sub(" ", val))})
    parts.sort(key=lambda p: ORDER.index(p["slot"]) if p["slot"] in ORDER else 99)
    return parts, service


def norm(s: str) -> str:
    """이름 비교용 — 대괄호(제조사·사양 표기)와 기호를 뺀 소문자 글자만."""
    return re.sub(r"[^0-9a-z가-힣]", "", re.sub(r"\[[^\]]*\]", " ", (s or "").lower()))


def names(conn) -> dict:
    """{슬롯: [(상품번호, 비교 이름, 판매중 여부)]} — 부품 상품. 10분 동안 재사용한다."""
    with _lock:
        if time.time() - _cache["at"] < _TTL and _cache["names"]:
            return _cache["names"]
    out = {}
    for code, name, pt, status in conn.execute(text(
            "SELECT product_code, product_name, part_type, status FROM products WHERE part_type = ANY(:t)"),
            {"t": sum(PART_TYPES.values(), [])}):
        slot = next(s for s, ts in PART_TYPES.items() if pt in ts)
        out.setdefault(slot, []).append((code, norm(name), status == "판매중"))
    with _lock:
        _cache["names"] = out
    return out


def by_name(index: dict, slot: str, name: str):
    """옵션 문구의 핵심 모델 이름을 포함하는 부품 상품 — 판매중·짧은 이름을 먼저. 못 찾으면 None."""
    core = norm(name)
    if len(core) < 5:
        return None
    cands = [x for x in index.get(slot, []) if core in x[1]]
    return min(cands, key=lambda x: (not x[2], len(x[1])))[0] if cands else None


def lexicon(conn) -> dict:
    """{(슬롯, 비교 키): 부품 설명 코드} — 공개 승인된 구성의 오퍼 상품 원문과 구성 부품을 맞대어 만든다."""
    now = time.time()
    with _lock:
        if now - _cache["at"] < _TTL:
            return _cache["lex"]
    lex, clash = {}, set()
    offers = conn.execute(text("""
        SELECT o.configuration_id, p.spec_source_text
          FROM pc_configuration_offers o
          JOIN products p ON p.product_code = CAST(substr(o.offer_id, 2) AS bigint)
         WHERE o.offer_id ~ '^P[1-9][0-9]{0,17}$' AND p.spec_source_text IS NOT NULL
           AND (SELECT e.action FROM pc_customer_publication_events e WHERE e.configuration_id = o.configuration_id
                 ORDER BY e.event_seq DESC LIMIT 1) = 'approve'""")).mappings().all()
    parts = {}
    for r in conn.execute(text("SELECT configuration_id, slot, explanation_code FROM pc_configuration_parts WHERE NOT pseudo")).mappings():
        parts.setdefault(r["configuration_id"], {}).setdefault(r["slot"], []).append(r["explanation_code"])
    for o in offers:
        slots = parts.get(o["configuration_id"], {})
        for row in rows(o["spec_source_text"])[0]:
            codes = slots.get(row["slot"]) or []
            if len(set(codes)) != 1:          # 같은 슬롯에 부품이 여럿이면 어느 문구가 어느 부품인지 모른다
                continue
            k = (row["slot"], row["key"])
            if k in lex and lex[k] != codes[0]:
                clash.add(k)
            lex[k] = codes[0]
    for k in clash:                            # 같은 문구가 다른 부품으로 쓰였으면 붙이지 않는다
        lex.pop(k, None)
    with _lock:
        _cache.update(at=now, lex=lex)
    return lex


@router.get("/api/customer/pc-registered/{code}")
def registered(code: int, response: Response):
    with engine.connect() as conn:
        p = conn.execute(text(
            "SELECT product_code, status, spec_source_text FROM products"
            " WHERE product_code = :c AND part_type = 'PC_COMPLETE' AND is_visible"), {"c": code}).mappings().first()
        if p is None:
            raise HTTPException(404, "등록된 PC 구성을 찾을 수 없습니다.")
        parts, service = rows(p["spec_source_text"])
        lex = lexicon(conn)
        codes = [lex.get((x["slot"], x["key"])) for x in parts]
        index = names(conn) if not all(codes) else {}
        mall = [None if c else by_name(index, x["slot"], x["name"]) for x, c in zip(parts, codes)]
        info = {}
        if any(codes):
            for r in conn.execute(text(
                    "SELECT source_product_code AS code, content->'image_asset' IS NOT NULL AS photo,"
                    " content->>'role' AS role, content->>'summary' AS summary"
                    " FROM product_explanations WHERE source_product_code = ANY(:c)"),
                    {"c": [c for c in codes if c]}).mappings():
                info[r["code"]] = r
    out = []
    for x, c, m in zip(parts, codes, mall):
        e = info.get(c) if c else None
        photo = f"/api/product-images/{c}/detail" if e and e["photo"] else None
        if photo is None and m:
            photo = MALL_IMG.format(d=m // 1000, c=m)
        out.append({"slot": x["slot"], "name": x["name"], "quantity": x["quantity"], "photo": photo,
                    "role": (e["role"] or e["summary"]) if e else None})
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True, "product_code": code, "basis": "mall-registered", "service": service, "parts": out}
