"""고객용 완제품 공개 구성(BOM)과 현재 선택된 대표 사진 (협업 6번 후속, PR #2 댓글 6059286404·6059699260).

■ 무엇을 하나
  `/api/grid/recommend` 의 sold 상품(product_code)을 받아, 그 상품이 묶인 완제품 구성이
  **발행 승인된 현재본일 때만** 공개 구성을 돌려준다. 판정은 새로 적지 않는다 —
  `customer_sold_offer_read.read_customer_sold_offer`(판매중 · P{code} offer 결합 ·
  `pc_customer_publication.read_current` 승인·현재본)와
  `pc_publication_source_reader.make_source_reader`(부품 설명 승인 + 부품 사진 승인 +
  현재 바이트 해시)를 그대로 부른다.

■ 응답 모양 = 통합 UI 가 추천 items[] 한 건에서 읽는 두 키 그대로
  public_configuration  공개 BOM. 그 안의 photo 는 계약대로 늘 `unresolved` 다 —
                        발행 승인은 대표 사진을 묶지 않는다(UI 검증기가 이 값만 받는다).
                        parts[].photo 는 승인된 부품 등록 사진(추가 필드, UI 는 쓰지 않는다).
  photo                 완제품 대표 사진(SKU 단위). «운영자가 selected 로 고른 ready 현재본»
                        이고 visual_basis 가 지금 구성과 같고 고지문이 정본일 때만
                        `available`, 아니면 `unavailable`. URL 은 SKU 로만 고정한다 —
                        `/api/customer/products/{code}/representative-image`.

■ 공개 아님은 전부 같은 404 — 미승인·철회·근거 변경·판매중 아님·증빙 확인 불가를 구분해
  알려 주지 않는다. 가격·재고는 이 경로가 넘기지 않아 `unknown` 이다(가격은 추천 응답 값).
"""
import hashlib
import json
import logging
import os
import pathlib
import re
import threading
from collections import OrderedDict
from copy import deepcopy
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import text

from .db import engine
from .customer_sold_offer_read import read_customer_sold_offer
from .pc_publication_source_reader import make_source_reader
from .product_images import MEDIA_BUCKET, read_image
from . import pc_media

log = logging.getLogger("customer_pc_offer")
router = APIRouter()
OFFER_PATH = "/api/customer/pc-offers/{product_code}"
IMAGE_PATH = "/api/customer/products/{product_code}/representative-image"

# 부품 사진 권리 근거(`workroom:...@vN:<sha256>`) — 비밀값이 아닌 운영 설정. 환경변수가
# 있으면 그 값, 없으면 저장소 설정 파일(RIGHTS_FILE)의 값을 쓴다. 둘 다 없으면 모든 구성이
# 닫힌다(source_reader 가 publication_native_photo_ports_unconnected 로 거부).
# 2026-10-09 실사고: 서버에 환경변수가 없어 고객 화면의 부품 사진이 전부 사라졌다.
RIGHTS_ENV = "POPCORN_PART_PHOTO_RIGHTS_REFERENCE"
RIGHTS_FILE = pathlib.Path(__file__).resolve().parent.parent / "docs" / "rights" / "part-photo-rights-reference.json"
MAX_PNG = 20 * 1024 * 1024
NOT_PUBLIC = {"error": "not_public"}
UNAVAILABLE = {"state": "unavailable", "url": None}
KIND = "ai_assembly_example"


def _not_public():
    return HTTPException(404, NOT_PUBLIC, headers={"Cache-Control": "no-store"})


def _check_code(product_code: int):
    if type(product_code) is not int or not 0 < product_code <= 2**63 - 1:
        raise HTTPException(422, "customer_product_code_invalid")


def rights_reference():
    """환경변수 우선, 없으면 저장소 설정 파일. 읽지 못하면 None(닫힘) — 사유는 로그로."""
    env = os.environ.get(RIGHTS_ENV, "").strip()
    if env:
        return env
    try:
        value = json.loads(RIGHTS_FILE.read_text(encoding="utf-8")).get("rights_reference")
    except (OSError, ValueError, AttributeError) as e:
        log.warning("part photo rights reference unreadable: %s", type(e).__name__)
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


# 2026-10-09: 부품 사진 승인이 생기자 추천·저장 견적 한 번마다 공개 판정이 부품 사진 원본(PNG)을
# 저장소에서 순서대로 전부 내려받아 60초를 넘겼다(상품 2개 x 실부품 수). 바이트는 asset 의
# detail_sha256 로 read_image 가 검증하므로 같은 (상품, 키, 해시)면 내용이 같다 — 프로세스 안에
# 검증된 바이트만 담아 두고, 예산을 넘으면 오래된 것부터 버린다. 실패는 담지 않는다.
IMAGE_CACHE_BYTES = 128 * 1024 * 1024
_image_cache = OrderedDict()
_image_cache_size = 0
_image_cache_lock = threading.Lock()


def _image_key(asset, code, variant):
    if variant != "detail" or type(asset) is not dict:
        return None
    sha, key = asset.get("detail_sha256"), asset.get("detail_key")
    if not (isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{64}", sha) and isinstance(key, str)):
        return None
    return (code, asset.get("bucket"), key, sha)


def cached_read_image(asset, code, variant):
    """read_image 와 같은 계약. 검증을 통과한 detail 바이트만 재사용한다."""
    global _image_cache_size
    key = _image_key(asset, code, variant)
    if key is not None:
        with _image_cache_lock:
            data = _image_cache.get(key)
            if data is not None:
                _image_cache.move_to_end(key)
                return data
    data = read_image(asset, code, variant)
    if key is not None and hashlib.sha256(data).hexdigest() == key[3] and len(data) <= IMAGE_CACHE_BYTES:
        with _image_cache_lock:
            if key not in _image_cache:
                _image_cache[key] = data
                _image_cache_size += len(data)
            while _image_cache_size > IMAGE_CACHE_BYTES:
                _, old = _image_cache.popitem(last=False)
                _image_cache_size -= len(old)
    return data


def _source_reader():
    return make_source_reader(image_reader=cached_read_image, business_rights_reference=rights_reference())


def _public_offer(conn, product_code):
    """같은 스냅샷 안에서 공개 판정 + 부품 사진 + 대표 사진 job. 공개 아니면 (None, None)."""
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
    # 고지문은 사진에 박힌 문구다 — 정본과 다르면 UI 가 받을 수 없으니 열지 않는다.
    if (job and job["asset"] and (job["asset"].get("notice") or pc_media.NOTICE) == pc_media.NOTICE
            and pc_media.snapshot(conn, identity)["visual_basis"] == job["visual_basis"]):
        photo = {"state": "available", "kind": KIND,
                 "url": IMAGE_PATH.format(product_code=product_code), "notice": pc_media.NOTICE}
    else:
        job, photo = None, dict(UNAVAILABLE)
    # 공개 BOM 의 photo 는 손대지 않는다(read_customer_sold_offer 가 unresolved 로 고정).
    return {"product_code": product_code, "photo": photo, "public_configuration": offer}, job


def _read(product_code):
    """읽기 전용 REPEATABLE READ 한 스냅샷. 끝나면 되돌린다(쓰기가 없다)."""
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        try:
            conn.begin()
            conn.execute(text("/*customer_pc_offer:readonly*/ SET TRANSACTION READ ONLY"))
            return _public_offer(conn, product_code)
        finally:
            conn.rollback()


def public_item(product_code):
    """추천 항목·저장 견적에 싣는 두 키. 공개가 아니거나 읽다 실패하면 unavailable/None.

    추천·저장 견적 응답 전체를 깨뜨리지 않으려고 여기서 실패를 받되, 로그에는 남긴다.
    None 인 public_configuration 은 UI 검증기가 null 로 받는다(구성 상세 없음).
    """
    try:
        item, _ = _read(product_code)
    except Exception:  # noqa: BLE001 - 카드 응답을 지키고 사유는 로그로
        log.exception("public_item failed product_code=%s", product_code)
        item = None
    if item is None:
        return {"photo": dict(UNAVAILABLE), "public_configuration": None}
    return {"photo": item["photo"], "public_configuration": item["public_configuration"]}


def attach(products):
    """dict 목록(product_code 보유)에 photo·public_configuration 을 제자리에서 싣는다.
    같은 상품은 한 번만 판정한다."""
    seen = {}
    for product in products:
        code = product.get("product_code")
        if type(code) is not int or not 0 < code <= 2**63 - 1:
            product.update(photo=dict(UNAVAILABLE), public_configuration=None)
            continue
        if code not in seen:
            seen[code] = public_item(code)
        product.update(deepcopy(seen[code]))
    return products


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


@router.get(OFFER_PATH)
def read_offer(product_code: int, response: Response):
    _check_code(product_code)
    item, _ = _read(product_code)
    response.headers["Cache-Control"] = "no-store"
    if item is None:
        raise _not_public()
    return {"ok": True, **item}


@router.get(IMAGE_PATH)
def read_representative_image(product_code: int, request: Request):
    """URL 에 job 이 없다 — 매 요청 공개 판정을 다시 하고 지금 선택된 현재본만 준다.
    사진이 바뀌어도 URL 이 같으므로 no-cache + ETag(sha256) 로 재검증하게 한다."""
    _check_code(product_code)
    item, job = _read(product_code)
    if item is None or job is None:
        raise _not_public()
    etag = '"' + str(job["asset"].get("sha256")) + '"'
    headers = {"Cache-Control": "no-cache", "ETag": etag, "X-Content-Type-Options": "nosniff"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    raw = _representative_png(job["asset"], job["job_id"])
    return Response(raw, media_type="image/png", headers=headers)
