# -*- coding: utf-8 -*-
"""ASUS 완제품 3종 장바구니의 서버 연결 지점 (2026-11-09). 라우터가 없고 어디서도 부르지 않는다.

반환값은 `mockups/mvp4/assets/js/asus-cart.js` setAdapter 계약과 같다.
  요청  {modelId, quantity: 1}
  응답  {ok: true, url} | {ok: false, code}

완제품 번호를 받기 전까지 ASUS_COMPLETE_SKUS 는 비어 있고 전부 sku_missing 이다.
구성 부품 번호를 완제품 번호로 쓰지 않는다. 임의 번호도 넣지 않는다.

같은 키는 기존 목록을 교체하므로 모델마다 견적을 나눈다. 세 모델을 한 장바구니에 모으는 동작이 아니다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

from api.mall_ai_api import ORIGIN, BasketCoordinator, MallApiError, normalize_pd_no

MODEL_IDS = ("business", "video", "local-ai")
QUANTITY = 1
ALLOWED_ORIGINS = (ORIGIN,)
ASUS_COMPLETE_SKUS: Mapping[str, str] = {}      # API-004: 완제품 3종 번호 미수령

_CAMPAIGN_DATA = Path(__file__).resolve().parents[1] / "db/migrations/data/asus_campaign_models_20261106.json"


def component_numbers(path: Path = _CAMPAIGN_DATA) -> frozenset[str]:
    """캠페인 자료의 구성 부품 mall_no 전부. 완제품 번호 표에 들어오면 안 되는 값이다."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                if name == "mall_no" and value is not None:
                    found.add(str(value))
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(path.read_text(encoding="utf-8")))
    return frozenset(found)


def validate_sku_map(sku_map: Mapping[str, Any], components: frozenset[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for model, sku in sku_map.items():
        if model not in MODEL_IDS:
            raise MallApiError("unknown_model")
        code = normalize_pd_no(sku)
        if code in components:
            raise MallApiError("sku_is_component")
        if code in result.values():
            raise MallApiError("sku_duplicate")
        result[model] = code
    return result


def add_model_to_cart(request: Mapping[str, Any], *, owner_id: Optional[str] = None,
                      coordinator: Optional[BasketCoordinator] = None,
                      sku_map: Mapping[str, Any] = ASUS_COMPLETE_SKUS,
                      components: Optional[frozenset[str]] = None) -> dict:
    """연결이 없으면 네트워크에 닿지 않고 실패를 돌려준다. 화면은 기존 비활성 상태를 유지한다."""
    if not isinstance(request, Mapping) or set(request) != {"modelId", "quantity"}:
        return {"ok": False, "code": "bad_request"}
    model = request["modelId"]
    if model not in MODEL_IDS:
        return {"ok": False, "code": "unknown_model"}
    if request["quantity"] != QUANTITY or isinstance(request["quantity"], bool):
        return {"ok": False, "code": "bad_quantity"}
    try:
        table = validate_sku_map(sku_map, component_numbers() if components is None else components)
    except MallApiError as exc:
        return {"ok": False, "code": exc.code}
    sku = table.get(model)
    if not sku:
        return {"ok": False, "code": "sku_missing"}
    if coordinator is None or not owner_id:
        return {"ok": False, "code": "not_connected"}
    try:
        receipt = coordinator.replace(owner_id, "asus:%s" % model, [(sku, QUANTITY)])
    except MallApiError as exc:
        return {"ok": False, "code": exc.code}
    return {"ok": True, "url": receipt.link}
