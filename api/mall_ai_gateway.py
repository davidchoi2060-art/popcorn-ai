# -*- coding: utf-8 -*-
"""팝콘PC(윈윈) price 사무실 조회 중계기 (2026-11-15 사용자 지시).

윈윈 AI API 는 허용된 IP(GCP 개발 서버)에서만 답한다. 사무실 PC와 대표자 PC에서 가격을
보려면 그 서버를 거쳐야 해서 이 경로를 둔다.

    GET /api/mall-ai-gateway/price?pd_no=124401,124407     JSON
    GET /api/mall-ai-gateway/lookup                       사람이 쓰는 조회 화면(표, 엑셀 복사)

■ 무엇을 하고 무엇을 하지 않는가
  읽기 전용이다. price 만 부른다. basket 경로는 없고 만들지 않는다.
  응답은 api/mall_ai_api 의 PriceItem.public 그대로다(2026-11-17 윈윈 응답 변경 뒤):
  상품번호 · 상품명 · 가격 · 판매 상태 · 최대 수량, 그리고 조회 시각과 없는 번호.
  판매 상태는 윈윈이 준 값을 그대로 옮긴다. 이 중계기가 판정한 값이 아니다.
  윈윈이 더는 내부 가격(원가 · 딜러가 · 시중가 · 소비자가 · 재고값)을 주지 않아 그 열은 없앴다.
  그 밖의 필드가 와도 버린다.

■ 세 겹으로 닫혀 있다
  ① MALL_AI_GATEWAY_ENABLED=1 이 아니면 404. 기본은 꺼짐이고 개발 서버에만 켠다.
     운영 서버에 배포돼도 켜지 않으면 아무 일도 하지 않는다.
  ② MALL_AI_GATEWAY_ALLOW_IPS(쉼표 목록)에 있는 IP만 받는다. 목록이 비면 전부 거부한다.
     IP 는 저장소에 적지 않는다. 서버 환경 파일에만 둔다.
  ③ 접속 IP 는 request.client.host 다. uvicorn --proxy-headers 가 신뢰 프록시(127.0.0.1,
     nginx)에서 온 요청만 바꿔 둔 값이다(api/auth.py._client_ip 와 같은 판단). nginx 가
     X-Real-IP 를 $remote_addr 로 덮어쓰므로 두 값이 다르면 거부한다.

■ 윈윈 서버를 지킨다
  윈윈으로 나가는 호출은 프로세스 안에서 한 번에 하나, 간격 1초 이상이다. 겹치면 429.
  재시도하지 않는다. 캐시하지 않는다(가격은 매번 새로 본다).

■ 값은 남기지 않는다
  로그에는 건수와 오류 코드만 남긴다. 상품명·가격·IP 를 찍지 않는다.
  응답에는 Cache-Control: no-store 를 단다.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from api import mall_ai_api as M

log = logging.getLogger("popcorn.mall_ai_gateway")
router = APIRouter()

ENABLED_ENV = "MALL_AI_GATEWAY_ENABLED"
ALLOW_IPS_ENV = "MALL_AI_GATEWAY_ALLOW_IPS"
MIN_INTERVAL_SECONDS = 1.0

_upstream = threading.Lock()
_last_call = {"at": None}


def _enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "").strip() == "1"


def _allowed_ips() -> frozenset:
    found = set()
    for raw in os.environ.get(ALLOW_IPS_ENV, "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            found.add(ipaddress.ip_address(raw))
        except ValueError:
            log.warning("[mall-gw] ignored a malformed allow entry")
    return frozenset(found)


def _client_allowed(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    real = (request.headers.get("x-real-ip") or "").strip()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if real and real != host:
        return False
    return address in _allowed_ips()


def _call_upstream(codes, transport=None):
    if not _upstream.acquire(blocking=False):
        raise HTTPException(429, {"code": "busy", "message": "다른 조회가 진행 중입니다. 잠시 후 다시 조회하십시오."})
    try:
        last = _last_call["at"]
        if last is not None:
            wait = MIN_INTERVAL_SECONDS - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        _last_call["at"] = time.monotonic()
        return M.fetch_prices(codes, transport=transport or M.LivePriceTransport(max_calls=1))
    finally:
        _upstream.release()


def _gate(request: Request) -> None:
    if not _enabled():
        raise HTTPException(404)
    if not _client_allowed(request):
        log.warning("[mall-gw] denied")
        raise HTTPException(403, {"code": "ip_not_allowed", "message": "허용되지 않은 접속 위치입니다."})


_PAGE = Path(__file__).resolve().parents[1] / "templates" / "mall_ai_gateway_lookup.html"
_NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}


@router.get("/api/mall-ai-gateway/lookup", include_in_schema=False)
def gateway_lookup_page(request: Request):
    """사람이 쓰는 조회 화면. 화면 자체에는 값이 없고 같은 출처의 price 경로를 부른다. 같은 문으로 닫는다."""
    _gate(request)
    return HTMLResponse(_PAGE.read_text(encoding="utf-8"), headers=_NO_STORE)


@router.get("/api/mall-ai-gateway/price", include_in_schema=False)
def gateway_price(request: Request, pd_no: str = Query("", max_length=700)):
    _gate(request)
    try:
        if [k for k, _ in request.query_params.multi_items()] != ["pd_no"]:
            raise M.MallApiError("invalid_query")      # 반복·추가 파라미터는 어느 값을 뜻하는지 모호하다
        codes = M.normalize_price_request([part for part in pd_no.split(",")] if pd_no else [])
    except M.MallApiError as exc:
        raise HTTPException(400, {"code": exc.code, "message": "상품번호를 쉼표로 구분해 1~50개 입력하십시오."})
    try:
        result = _call_upstream(codes)
    except M.MallApiError as exc:
        log.warning("[mall-gw] upstream failed code=%s requested=%d", exc.code, len(codes))
        raise HTTPException(502, {"code": exc.code, "message": "윈윈 API 조회에 실패했습니다."})
    items = [result.items[code].public() for code in result.requested]
    log.info("[mall-gw] ok requested=%d not_found=%d missing=%d unrequested=%d",
             len(codes), len(result.not_found), len(result.missing), result.unrequested_count)
    body = {"requested": list(result.requested), "checked_at": result.checked_at,
            "checked_at_format": result.checked_at_format, "not_found": list(result.not_found),
            "missing": list(result.missing), "unrequested_count": result.unrequested_count, "items": items,
            "status_note": "status is the mall's own value, passed through as received",
            "source": "popcornpc ai_api price (read only)"}
    return JSONResponse(body, headers=_NO_STORE)
