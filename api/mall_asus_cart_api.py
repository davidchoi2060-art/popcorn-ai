# -*- coding: utf-8 -*-
"""ASUS 기획전 완제품 3종 「장바구니에 담기」 서버 경로 (2026-11-18, 사장님 결정: 2026-11-23 오픈 포함).

    GET  /api/customer/asus-cart/status      {enabled, models:{<id>:{available, reason}}, origins, notice, notice_separate}
    POST /api/customer/asus-cart/add         {modelId, quantity: 1} -> {ok: true, url, added, skipped, total, notice, notice_separate}
                                                                   | {ok: false, code}

화면(mockups/mvp4/assets/js/asus-cart-live.js)이 이 둘을 asus-cart.js 의 setAdapter 계약으로 잇는다.

■ 설정은 전부 서버 환경변수다. 저장소에 값이 없다(공개 저장소 - 상품번호·비밀값을 적지 않는다).
    MALL_ASUS_CART_ENABLED=1        없으면 두 경로 모두 404. 기본 꺼짐.
    MALL_ASUS_CART_SKUS             "business=<번호>,video=<번호>,local-ai=<번호>". 완제품의 쇼핑몰 상품번호.
                                    구성 부품 번호를 넣으면 거부한다(api/mall_asus_cart.validate_sku_map).
    MALL_ASUS_CART_MODELS_ON        켤 모델 id 목록 "business,video". 없으면 전부 꺼짐(판매 상태는 우리 설정이다 - 사장님 확정).
    MALL_ASUS_CART_KEY_SALT         키 도출에 섞는 서버 비밀(16자 이상). 없으면 기능이 꺼진다(enabled:false, 담기 503).
    MALL_BASKET_WRITE_ENABLED=1     api/mall_ai_api.LiveBasketTransport 를 만들 수 있게 하는 스위치. 없으면 담기가
                                    basket_write_blocked 로 실패한다(네트워크에 닿기 전).

■ 키 규칙 - 「방문자 + 모델」 로 결정적으로 도출한다
    sha256(salt | 방문자 축 | 모델 id) 의 앞 20자(16진수 = 영숫자 20자, 윈윈 키 규칙 그대로).
    같은 고객이 같은 모델을 다시 담으면 같은 키라 기존 목록을 교체한다(윈윈: 같은 키는 교체). 다른 모델은
    다른 키다 - 세 모델을 한 장바구니에 모으지 않는다(윈윈 확정). 방문자 축은 api/access_gate.subject_of 와
    같다(방문자 쿠키 pc_vid 가 있으면 그 사람, 없으면 접속 IP). 쿠키를 새로 심지 않고 거절하지도 않는다.

■ 담기 전에 가격 조회를 한 번 한다
    그 상품번호 1개를 price 로 조회해 not_found 면 거절(sku_not_found). sold_out 은 윈윈의 참고값이라 막지 않고
    서버 로그에 건수로만 남긴다(사장님 확정: 판매 상태는 우리 설정으로 켜고 끈다).

■ 한도
    방문자 분당 PER_MINUTE 회(api/access_gate.check_rate, 정책 키 visitor.asus_cart). 윈윈 호출은 프로세스 안에서
    한 번에 하나, 간격 1초(api/mall_ai_api.CallPacer). 같은 키의 동시 담기는 busy.

■ 로그에는 모델 id·건수·오류 코드만 남긴다. 상품명·가격·키·방문자 축은 남기지 않는다. ASCII 만 쓴다.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from api import mall_ai_api as M
from api import mall_asus_cart as AC

from . import access_gate
from .db import engine
from .mvp3_saved_quotes import same_origin

log = logging.getLogger("popcorn.mall_asus_cart_api")
router = APIRouter()

ENABLED_ENV = "MALL_ASUS_CART_ENABLED"
SKUS_ENV = "MALL_ASUS_CART_SKUS"
MODELS_ON_ENV = "MALL_ASUS_CART_MODELS_ON"
SALT_ENV = "MALL_ASUS_CART_KEY_SALT"
SALT_MIN_CHARS = 16
KEY_LENGTH = M.DOC_KEY_LENGTH

POLICY_KEY = "visitor.asus_cart"
PER_MINUTE = 3
PER_DAY = 30
LIMIT_MESSAGES = {"minute": "장바구니 담기 요청이 잦습니다. {retry_after_sec}초 뒤 다시 시도해 주세요.",
                  "day": "오늘 장바구니 담기 한도에 닿았습니다. 내일 다시 시도해 주세요."}

# 사장님 확인 대상 문구. 화면이 그대로 보여 준다 - 바꿀 때 여기만 고친다.
NOTICE = "쇼핑몰 장바구니에 담았습니다. 브라우저를 닫으면 장바구니가 비워질 수 있으니, 이어서 주문하거나 쇼핑몰에 로그인해 주세요."
NOTICE_SEPARATE = "모델마다 장바구니가 따로 만들어집니다."

_NO_STORE = {"Cache-Control": "no-store"}
_pacer = M.CallPacer()
_inflight: set[str] = set()
_inflight_lock = threading.Lock()


# ---------------------------------------------------------------- 설정

@dataclass(frozen=True)
class Config:
    skus: dict            # 모델 id -> 쇼핑몰 상품번호(검증 통과)
    on: frozenset         # 켠 모델 id
    salt: str
    error: Optional[str] = None     # 설정 오류 코드. 있으면 기능 전체가 꺼진다

    def reason(self, model: str) -> Optional[str]:
        """None 이면 담을 수 있다. 아니면 화면이 비활성으로 보일 이유다."""
        if self.error:
            return "config_error"
        if model not in self.on:
            return "model_off"
        if model not in self.skus:
            return "sku_missing"
        return None


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "").strip() == "1"


@lru_cache(maxsize=1)
def _components() -> frozenset:
    return AC.component_numbers()


def parse_skus(raw: str) -> dict:
    """"business=1,video=2" 를 {모델: 번호} 로. 빈 항목은 넘기고 모양이 틀리면 skus_malformed."""
    table: dict = {}
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        model, sep, sku = chunk.partition("=")
        model, sku = model.strip(), sku.strip()
        if not sep or not model or not sku or model in table:
            raise M.MallApiError("skus_malformed")
        table[model] = sku
    return table


def parse_models_on(raw: str) -> frozenset:
    found = set()
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk not in AC.MODEL_IDS:
            raise M.MallApiError("models_on_unknown")
        found.add(chunk)
    return frozenset(found)


def load_config(environ=None) -> Config:
    env = os.environ if environ is None else environ
    salt = (env.get(SALT_ENV) or "").strip()
    try:
        skus = AC.validate_sku_map(parse_skus(env.get(SKUS_ENV, "")), _components())
        on = parse_models_on(env.get(MODELS_ON_ENV, ""))
    except M.MallApiError as exc:
        log.warning("[asus-cart] config rejected code=%s", exc.code)
        return Config({}, frozenset(), "", error=exc.code)
    if len(salt) < SALT_MIN_CHARS:
        return Config(skus, on, "", error="salt_missing")
    return Config(skus, on, salt)


def derive_key(salt: str, subject: str, model: str) -> str:
    """방문자 축 + 모델 -> 영숫자 20자. 같은 입력은 같은 키(교체), 다른 모델은 다른 키."""
    digest = hashlib.sha256(("%s|%s|%s" % (salt, subject, model)).encode("utf-8")).hexdigest()
    return M.validate_quote_key(digest[:KEY_LENGTH])


# ---------------------------------------------------------------- 공통

class AddBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modelId: StrictStr
    quantity: StrictInt


def _fail(status: int, code: str, **extra) -> JSONResponse:
    return JSONResponse({"ok": False, "code": code, **extra}, status_code=status, headers=_NO_STORE)


@contextmanager
def _db():
    """DB 가 없어도 담기는 막지 않는다(방문자 축은 IP 로, 한도 정책은 코드 기본값으로 떨어진다)."""
    try:
        conn = engine.connect()
    except Exception:       # noqa: BLE001
        yield None
        return
    try:
        yield conn
    finally:
        conn.close()


def _models_view(cfg: Config) -> dict:
    return {model: {"available": cfg.reason(model) is None, "reason": cfg.reason(model)} for model in AC.MODEL_IDS}


# ---------------------------------------------------------------- 경로

@router.get("/api/customer/asus-cart/status")
def asus_cart_status(request: Request):
    if not enabled():
        raise HTTPException(404)
    cfg = load_config()
    models = _models_view(cfg)
    body = {"enabled": cfg.error is None and any(v["available"] for v in models.values()), "models": models,
            "origins": list(AC.ALLOWED_ORIGINS), "notice": NOTICE, "notice_separate": NOTICE_SEPARATE}
    return JSONResponse(body, headers=_NO_STORE)


@router.post("/api/customer/asus-cart/add")
def asus_cart_add(body: AddBody, request: Request):
    if not enabled():
        raise HTTPException(404)
    same_origin(request)
    cfg = load_config()
    if cfg.error:
        return _fail(503, "not_configured")
    model = body.modelId
    if model not in AC.MODEL_IDS:
        return _fail(400, "unknown_model")
    if body.quantity != AC.QUANTITY:
        return _fail(400, "bad_quantity")
    reason = cfg.reason(model)
    if reason:
        return _fail(409, reason)
    sku = cfg.skus[model]
    with _db() as conn:
        subject = access_gate.check_rate(conn, request, what="asus.cart", policy_key=POLICY_KEY,
                                         default_per_minute=PER_MINUTE, default_per_day=PER_DAY, messages=LIMIT_MESSAGES)
    key = derive_key(cfg.salt, subject, model)
    lines = ((sku, AC.QUANTITY),)

    # 1) 가격 조회 1건. not_found 는 거절, sold_out 은 건수만 남기고 진행한다.
    try:
        price = _pacer.run(lambda: M.fetch_prices([sku], transport=M.LivePriceTransport(max_calls=1)))
    except M.MallApiError as exc:
        log.warning("[asus-cart] price failed model=%s code=%s", model, exc.code)
        return _fail(409 if exc.code == "busy" else 502, exc.code)
    item = price.items[sku]
    if not item.found:
        log.warning("[asus-cart] sku not in mall model=%s lookup=%s", model, item.lookup)
        return _fail(409, "sku_not_found")
    sold_out = 1 if item.status == "sold_out" else 0

    # 2) 담기. 같은 키의 동시 요청은 하나만 나간다. 재시도는 없다.
    with _inflight_lock:
        if key in _inflight:
            return _fail(409, "busy")
        _inflight.add(key)
    try:
        transport = M.LiveBasketTransport(key, lines)
        receipt = _pacer.run(lambda: M.BasketClient(transport).replace(key, lines))
    except M.MallApiError as exc:
        log.warning("[asus-cart] basket failed model=%s code=%s unknown=%s sold_out=%d",
                    model, exc.code, exc.outcome_unknown, sold_out)
        status = 503 if exc.code == "basket_write_blocked" else 409 if exc.code in ("busy", "basket_skipped") else 502
        return _fail(status, exc.code, outcome_unknown=exc.outcome_unknown)
    finally:
        with _inflight_lock:
            _inflight.discard(key)
    log.info("[asus-cart] ok model=%s added=%d skipped=%d total=%d sold_out=%d",
             model, len(receipt.added), len(receipt.skipped), receipt.total, sold_out)
    return JSONResponse({"ok": True, **receipt.public(), "notice": NOTICE, "notice_separate": NOTICE_SEPARATE},
                        headers=_NO_STORE)


def _reset_for_test() -> None:
    """검증용. 운영 경로에서는 부르지 않는다."""
    _pacer.reset()
    with _inflight_lock:
        _inflight.clear()
    _components.cache_clear()
