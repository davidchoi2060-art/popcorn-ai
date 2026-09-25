# -*- coding: utf-8 -*-
"""고객 추천 = 판매 중인 몰 조립PC 최대 2개 (2026-09-25 재설계 4단계 · 사장님 「최대 2개 · 승인」).

■ 무엇을 하나
  고객의 용도·예산(TalkState)을 받아, 0115 평가(product_usage_fit)에서 그 용도를 충족하는
  **실제 판매 상품**을 고른다. 조합을 만들지 않고 부품을 바꾸지 않는다 — 몰에서 호환성까지
  검증된 구성을 그대로 권한다.

■ 고르는 규칙 (용도마다 최대 2개)
  예산 있음   ① 예산 안에서 도달 수준이 가장 높은 상품 중 최저가 — 「예산 안 최고 수준」
              ② 예산 안 최저가 상품(①과 다를 때) — 「가장 저렴한 선택」
                 ①과 같으면 ①과 같은 수준의 다음 최저가 — 「같은 수준 다른 구성」
  예산 없음   ① 최소 수준을 충족하는 최저가  ② 한 단계 위 수준의 최저가
  예산 안에 없음  카드 없이 「예산 안 상품 없음」 + 조건을 충족하는 최저가 상품 1개를 참고로
              (over_budget=true) — 고객이 얼마부터 되는지 알 수 있게
  게임은 해상도가 최소 수준을 정한다(1080p=FHD · 1440p=QHD · 4K=4K, E등급=캐주얼).

■ 가격은 현재값 — `api/admin_product_fit.load()` 와 같은 판정(품절·단종 제외, sale_price 우선).
  관리자 매트릭스와 고객 추천이 같은 원천을 본다(술어를 두 벌 두지 않는다).
"""
from .admin_product_fit import load

# 고객 용도 라벨(usage_floors · usage_label_map) -> 평가 용도. 앞에서부터 먼저 맞는 것.
USAGE_RULES = [
    ("사무형 AI", "사무용"), ("문서 AI", "사무용"),
    ("AI", "로컬 AI"),
    ("게임", "게임"),
    ("주식", "주식·트레이딩"), ("트레이딩", "주식·트레이딩"),
    ("개발", "개발"), ("프로그래밍", "개발"),
    ("디자인", "디자인·조판"), ("사진", "디자인·조판"), ("조판", "디자인·조판"),
    ("영상", "영상편집"), ("방송", "방송·스트리밍"), ("스트리밍", "방송·스트리밍"),
    ("3D", "3D 렌더링"), ("렌더링", "3D 렌더링"),
    ("캐드", "캐드·설계"), ("설계", "캐드·설계"),
    ("음악", "음악 작업"), ("작곡", "음악 작업"),
    ("사무", "사무용"), ("인강", "사무용"), ("인터넷", "사무용"),
]
GAME_RES_RANK = {"1080p": 2, "1440p": 3, "4K": 4}
MAX_ITEMS = 2


def fit_usage(label: str | None) -> str | None:
    for key, u in USAGE_RULES:
        if label and key in label:
            return u
    return None


def _item(p, usage, levels_by, tag, budget_won, bound):
    f = p["fit"][usage]
    lv = levels_by.get((usage, f["level"])) or {}
    over = bool(budget_won is not None and bound != "이상" and p["price"] > budget_won)
    reasons = [f"{usage} {f['level']} — {lv.get('work', '')}"]
    if lv.get("conditions"):
        reasons.append(f"충족 조건: {lv['conditions']}")
    if f.get("blocked"):
        reasons.append("다음 수준까지는: " + ", ".join(f["blocked"][:2]))
    if p.get("includes"):
        reasons.append(f"판매가에 {p['includes']} 포함")
    return {
        "product_code": p["code"], "name": p["name"], "price": p["price"],
        "price_src": p["price_src"], "mall_url": p["url"], "spec": p["spec"],
        "level": f["level"], "tag": tag, "over_budget": over, "reasons": reasons,
    }


def pick(usage: str, min_rank: int, budget_won: int | None, bound: str | None,
         levels, products) -> dict:
    """한 용도 -> {items[≤2], empty_reason, empty_note}."""
    levels_by = {(l["usage"], l["level"]): l for l in levels}
    ok = sorted((p for p in products.values()
                 if p["price"] is not None and p["fit"].get(usage, {}).get("rank", 0) >= min_rank),
                key=lambda p: p["price"])
    rank = lambda p: p["fit"][usage]["rank"]  # noqa: E731
    if not ok:
        return {"items": [], "empty_reason": "보유 상품 없음",
                "empty_note": "이 작업 수준을 충족하는 판매 상품이 아직 없습니다."}

    if budget_won is None or bound == "이상":
        pool = [p for p in ok if budget_won is None or p["price"] >= budget_won] or ok
        first = pool[0]
        up = [p for p in pool if rank(p) > rank(first)]
        items = [_item(first, usage, levels_by, "가장 저렴한 선택", budget_won, bound)]
        if up:
            items.append(_item(up[0], usage, levels_by, "한 단계 위", budget_won, bound))
        return {"items": items[:MAX_ITEMS]}

    within = [p for p in ok if p["price"] <= budget_won]
    if not within:
        return {"items": [_item(ok[0], usage, levels_by, "예산을 넘는 최저가", budget_won, bound)],
                "empty_reason": "예산 안 상품 없음",
                "empty_note": f"이 작업은 {ok[0]['price']:,}원부터 가능합니다."}
    top = max(rank(p) for p in within)
    best = min((p for p in within if rank(p) == top), key=lambda p: p["price"])
    items = [_item(best, usage, levels_by, "예산 안 최고 수준", budget_won, bound)]
    cheap = within[0]
    if cheap is not best:
        items.append(_item(cheap, usage, levels_by, "가장 저렴한 선택", budget_won, bound))
    else:
        same = [p for p in within if rank(p) == top and p is not best]
        if same:
            items.append(_item(same[0], usage, levels_by, "같은 수준 다른 구성", budget_won, bound))
    return {"items": items[:MAX_ITEMS]}


def card_sets(state, game_usages, other_usages, notes) -> list[dict]:
    """TalkState -> card_sets(kind='sold'). 한 용도에 한 set, set 마다 상품 최대 2개."""
    levels, products = load()
    out = []
    targets = []
    for u in other_usages:
        fu = fit_usage(u)
        if fu is None:
            notes.append(f"sold: usage '{u}' has no fit mapping - skipped")
            continue
        targets.append((u, fu, 1))
    if game_usages:
        g = state.game
        res = (g.resolution if g else None) or "1080p"
        r = 1 if (g and g.grade == "E") else GAME_RES_RANK.get(res, 2)
        targets.append((game_usages[0], "게임", r))
    seen = set()
    for label, fu, r in targets:
        if (fu, r) in seen:
            continue
        seen.add((fu, r))
        res = pick(fu, r, state.budget_won, state.budget_bound, levels, products)
        lv = next((l for l in levels if l["usage"] == fu and l["level_rank"] == r), None)
        out.append({
            "usage": label, "usage_grid": fu, "kind": "sold",
            "min_level": lv["level"] if lv else None,
            "min_level_work": lv["work"] if lv else None,
            "items": res["items"],
            "empty_reason": res.get("empty_reason"), "empty_note": res.get("empty_note"),
            # 옛 화면 경로가 깨지지 않게 — 조합 카드는 없다
            "cards": [], "empty_cells": [], "omitted_variants": [],
            "center_band": None, "center_band_key": None, "bands_considered": [],
            "center_tier": None, "center_tier_key": None, "tiers_considered": [],
        })
    return out
