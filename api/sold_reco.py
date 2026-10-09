# -*- coding: utf-8 -*-
"""고객 추천 = 판매 중인 몰 조립PC 최대 2개 (2026-09-25 재설계 4단계 · 사장님 「최대 2개 · 승인」).

■ 무엇을 하나
  고객의 용도·예산(TalkState)을 받아, 0115 평가(product_usage_fit)에서 그 용도를 충족하는
  **실제 판매 상품**을 고른다. 조합을 만들지 않고 부품을 바꾸지 않는다 — 몰에서 호환성까지
  검증된 구성을 그대로 권한다.

■ 고르는 규칙 (용도마다 최대 2개 · 승인 시안 R01 「알뜰 구성 / 추천 구성」 2026-10-09)
  items 순서가 화면 순서다 — 싼 「알뜰 구성」이 앞(왼쪽), 강조하는 「추천 구성」이 뒤.
  강조 여부는 문구가 아니라 role 로 말한다(value · recommended · reference).
  예산 있음   추천 구성 = 예산 안에서 도달 수준이 가장 높은 상품 중 최저가
              알뜰 구성 = 예산 안 최저가 상품, 추천 구성보다 쌀 때만(같으면 추천 1장)
  예산 없음   알뜰 구성 = 최소 수준을 충족하는 최저가
              추천 구성 = 한 단계 위 수준의 최저가(없으면 앞의 1장이 추천 구성)
  예산 안에 없음  추천 카드 없이 「예산 안 상품 없음」 + 조건을 충족하는 최저가 상품 1개를 참고로
              (over_budget=true) — 고객이 얼마부터 되는지 알 수 있게
  게임은 해상도가 최소 수준을 정한다(1080p=FHD · 1440p=QHD · 4K=4K).
  캐주얼(rank 1)은 고객이 말한 게임 «전부»가 캐주얼 수준의 대상 게임(product_fit_levels.work
  에 적힌 게임)일 때만 쓴다 — 하나라도 밖이면 가장 까다로운 쪽을 따라 해상도 수준으로 간다.
  등급(E)으로 정하지 않는 이유: E 에는 롤과 배그가 함께 있는데 캐주얼 수준은 배그를 못 돌린다
  (2026-10-09 실사고 — 배그·롤 150만원에 캐주얼 PC 1,199,600원이 추천됐다).

■ 가격은 현재값 — `api/admin_product_fit.load()` 와 같은 판정(품절·단종 제외, sale_price 우선).
  관리자 매트릭스와 고객 추천이 같은 원천을 본다(술어를 두 벌 두지 않는다).
"""
import logging
import re

from .admin_product_fit import load
from .talk_schema import match_game

log = logging.getLogger("sold_reco")

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
# 승인 시안 R01 의 배지 문구와 역할. 화면은 role 로 강조를 정한다(문구로 추측하지 않는다).
TAG_VALUE, TAG_RECOMMENDED, TAG_REFERENCE = "알뜰 구성", "추천 구성", "예산을 넘는 최저가"
ROLE_OF = {TAG_VALUE: "value", TAG_RECOMMENDED: "recommended", TAG_REFERENCE: "reference"}
MAX_UPGRADE_HINTS = 2

# 「다음 수준」 안내 — 고객 문구는 Codex 확정본 그대로(PR #2 댓글 6057234341, 2026-10-08).
# blocked 원문은 tools/product_fit.check() 가 COND_KO 의 고정 틀로만 만든다. 그 틀 전체와
# 일치할 때만 종류가 확정된 것으로 본다(부분 문자열로 추측하지 않는다). 「미확인」 행은
# 값을 몰라 부족한지 알 수 없으므로 안내하지 않는다. CPU 게임 등급은 확정 문구가 없어 뺀다.
_DEFICIT = r" [\d,.]+(?:GB)? 미만(?:\(현재 [\d,.]+(?:GB)?\))?"
UPGRADE_HINTS = [
    (re.compile("CPU 멀티 지수" + _DEFICIT),
     "다음 수준을 고려한다면 여러 작업을 함께 처리할 수 있는 CPU 성능을 높여 보세요."),
    (re.compile("CPU 싱글 지수" + _DEFICIT),
     "다음 수준을 고려한다면 CPU의 단일 작업 처리 성능을 높여 보세요."),
    (re.compile("그래픽 지수" + _DEFICIT),
     "다음 수준을 고려한다면 그래픽 처리 성능을 높여 보세요."),
    (re.compile("그래픽 메모리" + _DEFICIT),
     "다음 수준을 고려한다면 그래픽 메모리 용량이 더 큰 구성을 살펴보세요."),
    (re.compile("램" + _DEFICIT),
     "다음 수준을 고려한다면 메모리 용량을 늘려 보세요."),
    (re.compile("SSD" + _DEFICIT),
     "다음 수준을 고려한다면 SSD 저장 용량을 늘려 보세요."),
    (re.compile("외장 그래픽 없음"),
     "다음 수준을 고려한다면 별도 그래픽카드가 있는 구성을 살펴보세요."),
    (re.compile("엔비디아 그래픽 아님"),
     "다음 수준은 NVIDIA 그래픽카드가 필요한 조건입니다."),
]


def upgrade_hints(blocked) -> list[str]:
    """blocked 원문 -> 고객 안내 문장(종류별 한 번, 최대 2개). 종류를 확정 못 한 행은 로그로만."""
    out, skipped = [], []
    for raw in blocked or []:
        hint = next((h for rx, h in UPGRADE_HINTS
                     if isinstance(raw, str) and rx.fullmatch(raw)), None)
        if hint is None:
            skipped.append(raw)
        elif hint not in out:
            out.append(hint)
    if skipped:
        log.info("[sold_reco] upgrade hint omitted for unmapped blocked: %r", skipped)
    return out[:MAX_UPGRADE_HINTS]
PUBLIC_SPEC_TEXT = ("cpu", "gpu")
PUBLIC_SPEC_NUM = ("ram_gb", "ssd_gb", "vram_gb")


def public_spec(spec):
    """고객에게 보여도 되는 사양만 — 부품 이름과 용량. 평가 점수(cpu_mt·cpu_st·gpu_idx 등)는
    내부 판정 근거라 빼고 서버에만 둔다(협업 6번). MVP3 `live-model.js` 의 publicSpec 과 같은 집합."""
    if isinstance(spec, str):
        return spec
    if not isinstance(spec, dict):
        return None
    return {k: v for k, v in spec.items()
            if (k in PUBLIC_SPEC_TEXT and isinstance(v, str))
            or (k in PUBLIC_SPEC_NUM and type(v) in (int, float) and v >= 0)}


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
    # 수준 조건(lv["conditions"])과 blocked 원문은 내부 지수·기준값을 담아 고객 응답에
    # 싣지 않는다(협업 6번). 원천은 관리자 매트릭스가 그대로 쓴다.
    reasons.extend(upgrade_hints(f.get("blocked")))
    if p.get("includes"):
        reasons.append(f"판매가에 {p['includes']} 포함")
    return {
        "product_code": p["code"], "name": p["name"], "price": p["price"],
        "price_src": p["price_src"], "mall_url": p["url"], "spec": public_spec(p["spec"]),
        "level": f["level"], "tag": tag, "role": ROLE_OF[tag],
        "over_budget": over, "reasons": reasons,
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
        if not up:
            return {"items": [_item(first, usage, levels_by, TAG_RECOMMENDED, budget_won, bound)]}
        return {"items": [_item(first, usage, levels_by, TAG_VALUE, budget_won, bound),
                          _item(up[0], usage, levels_by, TAG_RECOMMENDED, budget_won, bound)]}

    within = [p for p in ok if p["price"] <= budget_won]
    if not within:
        return {"items": [_item(ok[0], usage, levels_by, TAG_REFERENCE, budget_won, bound)],
                "empty_reason": "예산 안 상품 없음",
                "empty_note": f"이 작업은 {ok[0]['price']:,}원부터 가능합니다."}
    top = max(rank(p) for p in within)
    best = min((p for p in within if rank(p) == top), key=lambda p: p["price"])
    rec = _item(best, usage, levels_by, TAG_RECOMMENDED, budget_won, bound)
    cheap = within[0]
    if cheap["price"] < best["price"]:
        return {"items": [_item(cheap, usage, levels_by, TAG_VALUE, budget_won, bound), rec]}
    return {"items": [rec]}


def _casual_games(levels, vocab, notes) -> set[str]:
    """캐주얼 수준(게임 rank 1)이 대상으로 적은 게임 -> games.name 집합.

    원천은 product_fit_levels.work("롤·발로란트·피파·메이플 FHD") 하나다 — 목록을 코드에 다시
    적지 않는다. 게임명으로 못 읽은 토큰은 집합에 넣지 않는다(넓히지 않는 쪽이 안전하다).
    """
    lv = next((l for l in levels if l["usage"] == "게임" and l["level_rank"] == 1), None)
    if lv is None or not lv.get("work") or vocab is None:
        return set()
    out = set()
    for tok in re.split(r"[·,/]", lv["work"]):
        tok = re.sub(r"\s*(FHD|QHD|4K|1080p|1440p)\s*$", "", tok.strip(), flags=re.I).strip()
        if not tok:
            continue
        name = match_game(tok, vocab)
        if name:
            out.add(name)
        else:
            notes.append(f"sold: casual level game '{tok}' not matched - not counted as casual")
    return out


def game_min_rank(g, levels, vocab, notes) -> int:
    """게임 최소 수준 rank — 고객이 말한 게임 중 가장 까다로운 쪽이 정한다.

    캐주얼(1)은 게임명이 하나 이상 있고 «전부» 캐주얼 대상 게임이며 해상도가 1080p 일 때만.
    그 밖은 해상도 수준(FHD 2 · QHD 3 · 4K 4)이다 — 용도 최소 수준 밑으로 내려가지 않는다.
    """
    res = (g.resolution if g else None) or "1080p"
    r = GAME_RES_RANK.get(res, 2)
    names = list(g.names) if g else []
    if not names or res != "1080p":
        return r
    casual = _casual_games(levels, vocab, notes)
    matched = [match_game(n, vocab) if vocab is not None else None for n in names]
    if casual and all(m in casual for m in matched):
        return 1
    return r


def card_sets(state, game_usages, other_usages, notes, vocab=None) -> list[dict]:
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
        targets.append((game_usages[0], "게임", game_min_rank(state.game, levels, vocab, notes)))
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
