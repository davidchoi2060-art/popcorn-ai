"""고객용 완제품 공개 구성(BOM)과 현재 선택된 대표 사진 (협업 6번 후속, PR #2 댓글 6059286404).

■ 무엇을 하나
  `/api/grid/recommend` 의 sold 상품(product_code)을 받아, 그 상품이 묶인 완제품 구성이
  **발행 승인된 현재본일 때만** 공개 구성을 돌려준다. 판정은 새로 적지 않는다 —
  `customer_sold_offer_read.read_customer_sold_offer`(판매중 · P{code} offer 결합 ·
  `pc_customer_publication.read_current` 승인·현재본)와
  `pc_publication_source_reader.make_source_reader`(부품 설명 승인 + 부품 사진 승인 +
  현재 바이트 해시)를 그대로 부른다.

■ 이 모듈이 더하는 것 둘
  parts[].photo  게이트를 통과한 실부품은 승인된 등록 사진이다 → 기존 공개 이미지 경로.
                 pseudo 부품은 사진이 없다.
  photo          완제품 대표 사진. 발행 승인은 대표 사진을 묶지 않으므로(공개 BOM 모듈이
                 `unresolved` 로 고정한 이유) 여기서 «운영자가 selected 로 고른 ready 현재본»
                 일 때만 연다. visual_basis 가 현재 구성과 다르면 낡은 사진이라 열지 않는다.

■ 공개 아님은 전부 같은 404 — 미승인·철회·근거 변경·판매중 아님·증빙 확인 불가를 구분해
  알려 주지 않는다. 가격·재고는 이 경로가 넘기지 않아 `unknown` 이다(가격은 추천 응답 값).
"""
import hashlib
import os
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import text

from .db import engine
from .customer_sold_offer_read import read_customer_sold_offer
from .pc_publication_source_reader import make_source_reader
from .product_images import MEDIA_BUCKET, read_image
from . import pc_media

router = APIRouter(prefix="/api/customer/pc-offers")

# 부품 사진 권리 근거(`workroom:...@vN:<sha256>`) — 비밀값이 아닌 운영 설정. 없으면 모든
# 구성이 닫힌다(source_reader 가 publication_native_photo_ports_unconnected 로 거부).
RIGHTS_ENV = "POPCORN_PART_PHOTO_RIGHTS_REFERENCE"
MAX_PNG = 20 * 1024 * 1024
NOT_PUBLIC = {"error": "not_public"}
UNRESOLVED = {"state": "unresolved", "url": None, "notice": None}


def _not_public():
    return HTTPException(404, NOT_PUBLIC, headers={"Cache-Control": "no-store"})


def _check_code(product_code: int):
    if type(product_code) is not int or not 0 < product_code <= 2**63 - 1:
        raise HTTPException(422, "customer_product_code_invalid")


def _source_reader():
    return make_source_reader(image_reader=read_image,
                              business_rights_reference=os.environ.get(RIGHTS_ENV, "").strip() or None)


def _public_offer(conn, product_code):
    """같은 스냅샷 안에서 공개 판정 + 부품 사진 + 대표 사진 job. 공개 아니면 None."""
    result = read_customer_sold_offer(conn, product_code, source_reader=_source_reader())
    if result.get("status") != 200:
        return None, None
    offer = result["data"]
    identity = offer["configuration_id"]
    codes = {r["ordinal"]: r["explanation_code"] for r in conn.execute(text(
        "SELECT ordinal, explanation_code FROM pc_configuration_parts"
        " WHERE configuration_id=:id AND NOT pseudo"), {"id": identity}).mappings()}
    for part in offer["parts"]:
        code = None if part["pseudo"] else codes.get(part["ordinal"])
        part["photo"] = ({"state": "approved", "url": f"/api/product-images/{code}/detail"}
                         if type(code) is int else {"state": "none", "url": None})
    job = conn.execute(text(
        "SELECT job_id, visual_basis, asset FROM pc_media_jobs"
        " WHERE configuration_id=:id AND selected AND status='ready'"), {"id": identity}).mappings().first()
    if job and job["asset"] and pc_media.snapshot(conn, identity)["visual_basis"] == job["visual_basis"]:
        offer["photo"] = {"state": "current",
                          "url": f"/api/customer/pc-offers/{product_code}/photo/{job['job_id']}",
                          "notice": job["asset"].get("notice") or pc_media.NOTICE}
    else:
        job = None
        offer["photo"] = dict(UNRESOLVED)
    return offer, job


def _read(product_code):
    """읽기 전용 REPEATABLE READ 한 스냅샷. 끝나면 되돌린다(쓰기가 없다)."""
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        try:
            conn.begin()
            conn.execute(text("/*customer_pc_offer:readonly*/ SET TRANSACTION READ ONLY"))
            return _public_offer(conn, product_code)
        finally:
            conn.rollback()


def _representative_png(asset, job_id):
    key = f"pc-configurations/{job_id}/representative.png"
    if asset.get("bucket") != MEDIA_BUCKET or asset.get("key") != key:
        raise _not_public()
    try:
        with pc_media.cloud_session() as session:
            r = session.get(f"https://storage.googleapis.com/storage/v1/b/{MEDIA_BUCKET}/o/"
                            f"{quote(key, safe='')}?alt=media", timeout=(10, 30))
            r.raise_for_status()
            raw = r.content
        if len(raw) > MAX_PNG or hashlib.sha256(raw).hexdigest() != asset.get("sha256"):
            raise ValueError("checksum")
    except Exception as exc:
        raise HTTPException(503, "image_unavailable") from exc
    return raw


@router.get("/{product_code}")
def read_offer(product_code: int, response: Response):
    _check_code(product_code)
    offer, _ = _read(product_code)
    response.headers["Cache-Control"] = "no-store"
    if offer is None:
        raise _not_public()
    return {"ok": True, "offer": offer}


@router.get("/{product_code}/photo/{job_id}")
def read_photo(product_code: int, job_id: UUID):
    _check_code(product_code)
    offer, job = _read(product_code)
    if offer is None or job is None or str(job["job_id"]) != str(job_id):
        raise _not_public()
    raw = _representative_png(job["asset"], job_id)
    return Response(raw, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300",
                             "ETag": '"' + job["asset"]["sha256"] + '"',
                             "X-Content-Type-Options": "nosniff"})
