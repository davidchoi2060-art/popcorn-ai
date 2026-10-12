# -*- coding: utf-8 -*-
"""고객 추천 = 판매 중인 몰 조립PC 최대 3개 (2026-09-25 재설계 4단계 · 사장님 「최대 2개 · 승인」,
2026-10-11 중헌 님 「스펙트럼을 — 더 고급 사양을」으로 「더 높은 사양」 한 장 추가).

■ 무엇을 하나
  고객의 용도·예산(TalkState)을 받아, 0115 평가(product_usage_fit)에서 그 용도를 충족하는
  **실제 판매 상품**을 고른다. 조합을 만들지 않고 부품을 바꾸지 않는다 — 몰에서 호환성까지
  검증된 구성을 그대로 권한다.

■ 고르는 규칙 (용도마다 최대 2개 · 승인 시안 R01 「알뜰 구성 / 추천 구성」 2026-10-09)
  items 순서가 화면 순서다 — 싼 「알뜰 구성」이 앞(왼쪽), 강조하는 「추천 구성」이 뒤.
  강조 여부는 문구가 아니라 role 로 말한다(value · recommended · reference).
  예산 있음   추천 구성 = 예산 안에서 도달 수준이 가장 높은 상품 중, 다음 수준에 가장 가까운 것
              (다음 수준 조건 중 못 채운 항목 blocked 가 가장 적은 것) — 같으면 최저가
              알뜰 구성 = 예산 안 최저가 상품, 추천 구성보다 싸고 추천 구성이 분명히 나을 때만
              (수준이 낮거나, 다음 수준까지 못 채운 항목이 추천 구성보다 적지 않을 때). 없으면 추천 1장
              ※ 2026-10-10 조정: 예산 안 상품이 모두 같은 수준이면 예전 규칙은 가장 싼 1대만
                남겼다(「영상 편집 300만원」→158만원 1장 · 「배그 200만원」도 같은 1장).
  예산 없음   알뜰 구성 = 최소 수준을 충족하는 최저가
              추천 구성 = 한 단계 위 수준의 최저가(없으면 앞의 1장이 추천 구성)
  예산 안에 없음  추천 카드 없이 「예산 안 상품 없음」 + 조건을 충족하는 최저가 상품 1개를 참고로
              (over_budget=true) — 고객이 얼마부터 되는지 알 수 있게
  고객 공개 승인 우선 (2026-10-09 조정 결정): 위 규칙이 정한 후보 안에서만, 고객 공개 승인된
              구성(부품 사진이 나오는 상품)을 가격보다 먼저 고른다. 수준·예산 판정과 카드 수는
              그대로이고, 승인 후보가 없으면 지금과 같다. 「예산을 넘는 최저가」 참고 카드는
              「얼마부터 되는지」를 말하므로 승인 여부와 무관하게 최저가를 둔다.
              승인 집합은 힌트일 뿐이다 — 실제 공개 판정은 customer_pc_offer 가 매번 한다.
  더 높은 사양  (2026-10-11) 위 카드 뒤에 한 장 — 추천 구성보다 성능 비교값이 PREMIUM_STEP 배 이상
              높거나 수준이 위인 것. 예산 안에 있으면 그중 가장 높은 것, 없으면 예산의 PREMIUM_OVER_X 배
              안에서 가장 싼 것(over_budget). 예산이 없으면 가장 싼 높은 사양. 없으면 붙이지 않는다.
  주고받기     (2026-10-11 · api/reco_explore) 고객이 말한 램·저장공간·그래픽카드·흰색 케이스·저소음·
              모니터 포함을 후보에서 실제로 거르고, 못 거르면 «못 맞춘다»고 밝힌다. 「더 싸게」는 지금
              추천 구성보다 싼 것들로, 「더 좋게」는 지금 추천 구성보다 높은 것들로 같은 규칙을 다시 돈다.
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

from sqlalchemy import text

from .admin_product_fit import load
from .db import engine
from .product_name import card_name, match_storage_shorthand   # 카드 이름에서 광고 문구를 뗀다(원천은 그대로)
from . import reco_explore as X
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
MAX_ITEMS = 3     # 알뜰 · 추천 · 더 높은 사양
# 승인 시안 R01 의 배지 문구와 역할. 화면은 role 로 강조를 정한다(문구로 추측하지 않는다).
TAG_VALUE, TAG_RECOMMENDED, TAG_REFERENCE = "알뜰 구성", "추천 구성", "예산을 넘는 최저가"
# 2026-10-11 중헌 님 「더 고급 사양을 보여준다던지 — 스펙트럼을」: 추천 구성 다음에 한 장 더.
# 고객이 고른 카드를 보관할 때 지금 목록 밖이면(더 싸게·더 좋게로 본 카드) 「고른 구성」으로 남긴다.
TAG_PREMIUM, TAG_CHOSEN = "더 높은 사양", "고른 구성"
ROLE_OF = {TAG_VALUE: "value", TAG_RECOMMENDED: "recommended", TAG_REFERENCE: "reference",
           TAG_PREMIUM: "premium", TAG_CHOSEN: "chosen"}
# 「더 높은 사양」 카드: 추천 구성보다 성능 비교값이 이만큼 높거나 수준이 위여야 한다(같은 PC 를 다시 내밀지 않게).
PREMIUM_STEP = 1.10
# 예산이 있으면 그 안에서 가장 높은 사양을, 없으면 예산의 이 배까지에서 가장 싼 높은 사양을 보여 준다.
PREMIUM_OVER_X = 1.3
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
PUBLIC_SPEC_PART = ("case", "psu")     # card_spec 이 몰 구성 원문에서 더한다


def public_spec(spec):
    """고객에게 보여도 되는 사양만 — 부품 이름과 용량. 평가 점수(cpu_mt·cpu_st·gpu_idx 등)는
    내부 판정 근거라 빼고 서버에만 둔다(협업 6번). MVP3 `live-model.js` 의 publicSpec 과 같은 집합."""
    if isinstance(spec, str):
        return spec
    if not isinstance(spec, dict):
        return None
    return {k: v for k, v in spec.items()
            if (k in PUBLIC_SPEC_TEXT + PUBLIC_SPEC_PART and isinstance(v, str))
            or (k in PUBLIC_SPEC_NUM and type(v) in (int, float) and v >= 0)}


def card_spec(p):
    """카드 사양 = 공개 사양 + 케이스·파워 이름(몰 구성 원문, 2026-10-12 중헌 님 고객단 4번). 못 읽은 줄은 넣지 않는다."""
    spec = public_spec(p.get("spec"))
    extra = {k: v for k, v in (p.get("case_psu") or {}).items() if k in PUBLIC_SPEC_PART and isinstance(v, str) and v}
    if not extra:
        return spec
    return {**(spec if isinstance(spec, dict) else {}), **extra}


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
        "product_code": p["code"], "name": match_storage_shorthand(card_name(p["name"]), p["spec"]),
        "price": p["price"],
        "price_src": p["price_src"], "mall_url": p["url"], "spec": card_spec(p),
        "level": f["level"], "tag": tag, "role": ROLE_OF[tag],
        "over_budget": over, "reasons": reasons,
    }


# 판매 상품코드 -> 그 P 오퍼 구성의 최신 고객 공개 이벤트가 승인인 것. 순서 힌트 전용.
PUBLIC_CODES_SQL = """
    SELECT CAST(substr(o.offer_id, 2) AS bigint) AS product_code
      FROM pc_configuration_offers o
      JOIN LATERAL (SELECT e.action FROM pc_customer_publication_events e
                     WHERE e.configuration_id = o.configuration_id
                     ORDER BY e.event_seq DESC LIMIT 1) last ON true
     WHERE o.offer_id ~ '^P[1-9][0-9]{0,17}$' AND last.action = 'approve'
"""


def public_codes() -> frozenset:
    """고객 공개 승인된 판매 상품코드. 읽지 못하면 빈 집합(지금과 같은 추천) — 사유는 로그로."""
    try:
        with engine.connect() as conn:
            return frozenset(int(r.product_code) for r in conn.execute(text(PUBLIC_CODES_SQL)))
    except Exception:  # noqa: BLE001 - 순서 힌트라 추천을 막지 않는다
        log.exception("[sold_reco] public codes unavailable - no preference applied")
        return frozenset()


def _prefer(cands, preferred):
    """공개 승인 먼저, 그다음 최저가. preferred 가 비면 최저가(기존 규칙)와 같다."""
    return min(cands, key=lambda p: (p["code"] not in preferred, p["price"]))


def pick(usage: str, min_rank: int, budget_won: int | None, bound: str | None,
         levels, products, preferred=frozenset()) -> dict:
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
        base = rank(pool[0])
        first = _prefer([p for p in pool if rank(p) == base], preferred)
        up = [p for p in pool if rank(p) > base]
        if not up:
            return {"items": [_item(first, usage, levels_by, TAG_RECOMMENDED, budget_won, bound)]}
        return {"items": [_item(first, usage, levels_by, TAG_VALUE, budget_won, bound),
                          _item(_prefer(up, preferred), usage, levels_by, TAG_RECOMMENDED, budget_won, bound)]}

    within = [p for p in ok if p["price"] <= budget_won]
    # 예산 안에 없으면 예산이 아무리 낮아도 가장 가까운 PC 한 장을 «예산과 맞지 않음» 안내와 함께 보인다
    # (2026-10-12 사장님 「예산과 안맞으면 예산과 맞지 않음을 그냥 공지하고 추천PC를 제시해」 -- 예산이 최저가의
    # 절반도 안 되면 카드를 빼던 #167 규칙을 걷었다).
    if not within:
        return {"items": [_item(ok[0], usage, levels_by, TAG_REFERENCE, budget_won, bound)],
                "empty_reason": "예산 안 상품 없음",
                "empty_note": f"이 작업은 {ok[0]['price']:,}원부터 가능합니다."}
    top = max(rank(p) for p in within)
    gap = lambda p: len(p["fit"][usage].get("blocked") or [])  # noqa: E731 - 다음 수준까지 못 채운 조건 수
    best = min((p for p in within if rank(p) == top),
               key=lambda p: (p["code"] not in preferred, gap(p), p["price"]))
    rec = _item(best, usage, levels_by, TAG_RECOMMENDED, budget_won, bound)
    # 알뜰 구성은 추천 구성보다 싸고, 추천 구성이 수준이나 다음 수준까지의 거리로 분명히 나을 때만.
    cheaper = [p for p in within if p["price"] < best["price"]
               and (rank(p) < top or gap(p) >= gap(best))]
    if cheaper:
        return {"items": [_item(_prefer(cheaper, preferred), usage, levels_by, TAG_VALUE, budget_won, bound), rec]}
    return {"items": [rec]}


def premium_item(res, usage, min_rank, budget_won, bound, levels, products,
                 preferred=frozenset()) -> dict | None:
    """추천 구성 다음 한 장 — 「더 높은 사양」. 더 높은 것이 없으면 None.

    예산 안 상품이 없어 「예산을 넘는 최저가」 한 장만 있으면 그 카드를 기준으로 삼는다(2026-10-11
    개발 서버 「배그와 롤 150만원」: 한 장만 보여 고를 폭이 없었다). 이때도 예산의 PREMIUM_OVER_X 배 안만.

    예산(이하) 안에 추천 구성보다 분명히 높은 사양이 있으면 그중 가장 높은 것, 없으면 예산의
    PREMIUM_OVER_X 배 안에서 가장 싼 높은 사양(over_budget 으로 표시). 예산이 없으면 가장 싼 높은 사양.
    어느 경우든 공개 승인 구성(사진·소개 글이 있는 것, preferred)을 먼저 고른다 — pick 과 같은 순서 힌트.
    """
    pub = lambda p: p["code"] in preferred  # noqa: E731
    items = res.get("items") or []
    rec = next((i for i in items if i["role"] == "recommended"), None) \
        or next((i for i in items if i["role"] == "reference"), None)
    if rec is None or rec["product_code"] not in products:
        return None
    base = products[rec["product_code"]]
    shown = {i["product_code"] for i in res["items"]}
    rank = lambda p: p["fit"].get(usage, {}).get("rank", 0)  # noqa: E731
    bp = X.perf(base, usage)
    better = [p for p in products.values()
              # 추천 구성보다 낮은 수준은 «더 높은 사양»이 아니다(2026-10-12 사장님 시험: 추천 「사무용 쾌적」 옆
              # 「더 높은 사양」 카드가 「사무용 기본」이었다 -- 그래픽은 높아도 사무용 기준으로는 한 단계 아래).
              if p["code"] not in shown and p["price"] is not None and rank(p) >= max(min_rank, rank(base))
              and p["price"] > base["price"]
              and (rank(p) > rank(base) or X.perf(p, usage) >= bp * PREMIUM_STEP)]
    if not better:
        return None
    if budget_won is not None and bound != "이상":
        within = [p for p in better if p["price"] <= budget_won]
        if within:
            chosen = max(within, key=lambda p: (pub(p), X.perf(p, usage), -p["price"]))
        else:
            above = [p for p in better if p["price"] <= budget_won * PREMIUM_OVER_X]
            if not above:
                return None
            chosen = min(above, key=lambda p: (not pub(p), p["price"]))
    else:
        chosen = min(better, key=lambda p: (not pub(p), p["price"]))
    levels_by = {(l["usage"], l["level"]): l for l in levels}
    return _item(chosen, usage, levels_by, TAG_PREMIUM, budget_won, bound)


def _uhd_rank(levels, usage, r):
    """비게임 용도에서 「4K」라고 하면 그 용도의 4K 작업 수준(product_fit_levels.work)을 최소로."""
    hits = [l["level_rank"] for l in levels if l["usage"] == usage and "4K" in (l.get("work") or "")]
    return max(r, min(hits)) if hits else r


def _heavy_rank(levels, usage, r, heavy):
    """고객이 말한 한 단계 위 작업(reco_explore.HEAVY_WORK) -> 그 단계의 순위를 최소로. 기준표에 없으면 그대로."""
    level = (heavy or {}).get(usage)
    hits = [l["level_rank"] for l in levels if l["usage"] == usage and l["level"] == level]
    return max(r, hits[0]) if hits else r


def _cheapest(usage, min_rank, levels, products, preferred, min_ok) -> dict:
    """조건 안의 실제 최저가 한 장. 「가장 싸게」에 한 단계 위(수백만 원) 구성을 «추천»으로 함께 내밀지
    않는다(2026-10-11 사장님 비교 -- 「개발자용 가장 저렴하게」에 248만원 카드). 더 높은 사양은 아래 빠른
    선택이 연다. 후보가 없으면 pick 의 빈 결과(사유 포함)를 그대로 쓴다."""
    ok = [p for p in products.values() if min_ok(p)]
    if not ok:
        return pick(usage, min_rank, None, None, levels, products, preferred)
    first = min(ok, key=lambda p: (p["price"], p["code"] not in preferred))
    levels_by = {(l["usage"], l["level"]): l for l in levels}
    more = any(p["price"] > first["price"] for p in ok)
    return {"items": [_item(first, usage, levels_by, TAG_VALUE if more else TAG_RECOMMENDED, None, None)]}


def _explore_set(fu, r, state, levels, products, preferred, ex, filters):
    """한 용도의 카드 — 고객 추가 조건(wants)과 「더 싸게/더 좋게」(nav)를 반영한다."""
    min_ok = lambda p: p["price"] is not None and p["fit"].get(fu, {}).get("rank", 0) >= r  # noqa: E731
    kept, applied, unmet = X.apply_filters(list(products.values()), filters, min_ok)
    prods = {p["code"]: p for p in kept}
    budget, bound = state.budget_won, state.budget_bound
    anchor = products.get(ex.get("anchor_code")) if ex.get("anchor_code") is not None else None
    nav, nav_note = ex.get("nav"), None
    res = None
    if nav == X.CHEAPER and (ex.get("cheapest") or anchor is None):
        # 「가장 싸게」(또는 기준 카드 없는 「싸게」) -- 앞 추천 카드와 상관없이 조건 안의 실제 최저가 한 장.
        # 공개 승인 구성은 같은 가격일 때만 앞에 둔다(코덱스 #155 검수 P2-1·P2-2: 승인 우선이 최저가를
        # 밀어내 「가장 싼 쪽」 안내와 카드가 어긋났다). 후보 범위(판매·적합 수준·조건)는 바꾸지 않는다.
        # 「150만원 이상」처럼 하한을 말했으면 그 안에서 가장 싼 것 -- 하한을 넘는 후보가 없을 때만 하한을 푼다
        # (코덱스 #161 검수 경계: 최저가 요청이 예산 하한을 말없이 지웠다). pick 의 「이상」 처리와 같다.
        floor = {c: p for c, p in prods.items() if p["price"] is not None and p["price"] >= budget} \
            if budget is not None and bound == "이상" else {}
        floor_ok = any(min_ok(p) for p in floor.values())
        pool = floor if floor_ok else prods
        res, nav_note = _cheapest(fu, r, levels, pool, preferred, min_ok), X.NOTE_CHEAPEST
        if budget is not None and bound == "이상" and not floor_ok:
            # 하한을 풀었으면 그 사실을 밝힌다(2026-10-12 검수 5812 P2-2 -- 말없이 하한 아래 카드가 나갔다).
            nav_note = X.NOTE_FLOOR_RELAXED
        for it in res["items"]:
            it["over_budget"] = bool(budget is not None and bound != "이상" and it["price"] > budget)
    elif nav == X.CHEAPER and anchor is not None and anchor["price"] is not None:
        below = {c: p for c, p in prods.items() if p["price"] is not None and p["price"] < anchor["price"]}
        if any(min_ok(p) for p in below.values()):
            res = pick(fu, r, anchor["price"] - 1, "이하", levels, below, preferred)
            for it in res["items"]:      # 고객 예산 기준으로 다시 판정한다(방향 이동 기준가가 아니라)
                it["over_budget"] = bool(budget is not None and bound != "이상" and it["price"] > budget)
            nav_note = X.NOTE_CHEAPER
        else:
            nav_note = X.NOTE_CHEAPER_NONE
    elif nav == X.BETTER and anchor is not None and anchor["price"] is not None:
        ap, ar = X.perf(anchor, fu), anchor["fit"].get(fu, {}).get("rank", 0)
        up = {c: p for c, p in prods.items() if c != anchor["code"] and p["price"] is not None
              and p["price"] > anchor["price"]
              and (p["fit"].get(fu, {}).get("rank", 0) > ar or X.perf(p, fu) >= ap * 1.05)}
        if any(min_ok(p) for p in up.values()):
            res = pick(fu, r, None, None, levels, up, preferred)
            for it in res["items"]:
                it["over_budget"] = bool(budget is not None and bound != "이상" and it["price"] > budget)
            nav_note = X.NOTE_BETTER
        else:
            nav_note = X.NOTE_BETTER_NONE
    if res is None:
        res = pick(fu, r, budget, bound, levels, prods, preferred)
    if nav != X.CHEAPER:
        extra = premium_item(res, fu, r, budget if nav != X.BETTER else None,
                             bound if nav != X.BETTER else None, levels, prods, preferred)
        if extra is not None:
            if nav == X.BETTER:
                extra["over_budget"] = bool(budget is not None and bound != "이상" and extra["price"] > budget)
            res["items"].append(extra)
    # 다음 선택지 — 지금 화면의 추천 구성(없으면 마지막 카드)을 기준으로 더 싼 것·더 높은 것이 있나.
    items = res["items"]
    base_item = next((i for i in items if i["role"] in ("recommended", "reference")), items[-1] if items else None)
    base = products.get(base_item["product_code"]) if base_item else None
    has_cheaper = has_better = False
    if base is not None:
        bp = X.perf(base, fu)
        has_cheaper = any(min_ok(p) and p["price"] < base["price"] for p in prods.values())
        has_better = any(min_ok(p) and p["price"] > base["price"] and X.perf(p, fu) >= bp * 1.05
                         for p in prods.values())
    res["explore"] = {"applied": applied, "unmet": unmet, "nav_note": nav_note,
                      "anchor_code": base["code"] if base else None,
                      "has_cheaper": has_cheaper, "has_better": has_better}
    return res


def _resolve_more(ex, products, notes):
    """「램 더 크게」·「저장공간 더 크게」 -> 지금 보신 추천 구성 용량의 두 배 이상(숫자 조건으로 바꾼다)."""
    more = ex.pop("more", None) or []
    if not more:
        return
    anchor = products.get(ex.get("anchor_code")) if ex.get("anchor_code") is not None else None
    sp = anchor.get("spec") if anchor and isinstance(anchor.get("spec"), dict) else None
    if sp is None:
        ex.setdefault("talk_notes", []).append(X.NOTE_MORE_NO_ANCHOR)
        return
    for kind, key, want in (("ram", "ram_gb", "min_ram_gb"), ("ssd", "ssd_gb", "min_ssd_gb")):
        if kind in more and type(sp.get(key)) in (int, float) and sp[key] > 0:
            ex["wants"][want] = int(sp[key] * 2) if kind == "ram" else max(int(sp[key] * 2), 1000)
            notes.append(f"sold: '{kind} more' -> {ex['wants'][want]} from anchor {anchor['code']}")


def eligible_item(state, game_usages, other_usages, code, notes, vocab=None) -> dict | None:
    """보관 확인용 — 이 상품이 판매 중이고 이 상담 용도의 최소 수준을 채우는가(예산·고르기 규칙은 보지 않는다).

    「더 싸게」·「더 좋게」로 본 카드는 다음 조회의 기본 목록에 없을 수 있다. 그래도 같은 판매 원천과
    같은 수준 판정을 통과한 상품만 보관한다 — 관리자 행이나 임의 코드는 여기서도 막힌다.
    """
    levels, products = load()
    p = products.get(code)
    if p is None or p["price"] is None:
        return None
    levels_by = {(l["usage"], l["level"]): l for l in levels}
    for label, fu, r in _targets(state, game_usages, other_usages, levels, vocab, notes):
        if p["fit"].get(fu, {}).get("rank", 0) >= r:
            return _item(p, fu, levels_by, TAG_CHOSEN, state.budget_won, state.budget_bound)
    return None


# ── 부품 바꾸기 (2026-10-11 중헌 님 「제품을 선택하고 부품 변경하는 부분 — 아직 안 된다」) ──
# 고객이 고르는 것은 몰의 완제품 한 대(pd_no)다. 부품 하나를 바꾼 구성은 몰에 상품이 없어 살 수
# 없고, 우리가 값을 매기면 새 가격 계산을 만드는 것이다. 그래서 «부품 바꾸기» = 바꾸려는 부품만
# 다르고 핵심 부품은 같은 **다른 판매 PC** 로 옮기는 것이다. 호환은 몰이 조립·판매하는 구성이라
# 보장되고, 가격은 그 상품의 현재 판매가(load() 와 같은 원천) 그대로다. 보관·쇼핑몰 연결도 그
# 상품번호로 지금 경로를 그대로 탄다.
SWAP_SLOTS = {   # 바꾸는 부품 -> (사양 키, 고객 이름, 그대로 두는 핵심 부품)
    "cpu": ("cpu", "CPU", ("gpu",)),
    "gpu": ("gpu", "그래픽카드", ("cpu",)),
    "ram": ("ram_gb", "메모리", ("cpu", "gpu")),
    "ssd": ("ssd_gb", "저장장치", ("cpu", "gpu")),
}
# 핵심 부품이 아닌 공개 사양 — 이것이 함께 달라지면 숨기지 않고 «함께 바뀌는 것»으로 말한다.
SWAP_ALSO = (("ram_gb", "메모리"), ("ssd_gb", "저장장치"))
MAX_SWAP_OPTIONS = 8


def _swap_val(p, key):
    sp = p.get("spec") if isinstance(p.get("spec"), dict) else {}
    v = sp.get(key)
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v if type(v) in (int, float) and v > 0 else None


def _swap_same(key, a, b) -> bool:
    if a is None or b is None:
        return False
    if isinstance(a, str) or isinstance(b, str):
        return str(a).upper().replace(" ", "") == str(b).upper().replace(" ", "")
    if key == "ssd_gb":   # 960GB 와 1,000GB 는 같은 1TB 다(표기 차이 — reco_explore 의 90% 와 같은 기준)
        return abs(a - b) <= max(a, b) * 0.1
    return a == b


def _swap_label(key, v) -> str:
    if key == "ram_gb":
        return f"{int(v)}GB"
    if key == "ssd_gb":
        return X._gb_label(int(v))
    return str(v)


def part_options(state, game_usages, other_usages, code, slot, notes, vocab=None) -> dict | None:
    """선택한 판매 PC(code)에서 한 부품(slot)만 다른 판매 PC 목록. 이 PC 가 판매 중이 아니거나
    이 상담 용도를 채우지 못하면 None(화면은 다시 조회하라고 말한다).

    후보 = 판매 중 · 이 상담 용도의 최소 수준 충족(eligible_item 과 같은 판정) · 핵심 부품 같음 ·
    바꾸려는 부품 값이 다름. 같은 값이 여러 대면 함께 바뀌는 것이 적은 것 -> 고객 공개 승인 ->
    지금 가격과 가까운 것 한 대만. 목록 순서는 용량은 작은 것부터, CPU·그래픽카드는 싼 것부터.
    """
    key, label, keep = SWAP_SLOTS[slot]
    levels, products = load()
    base = products.get(code)
    if base is None or base["price"] is None:
        return None
    targets = _targets(state, game_usages, other_usages, levels, vocab, notes)
    usage_of = lambda p: next((fu for _, fu, r in targets if p["fit"].get(fu, {}).get("rank", 0) >= r), None)  # noqa: E731
    if usage_of(base) is None:
        return None
    current = _swap_val(base, key)
    preferred = public_codes()
    best = {}
    for p in products.values():
        if p["code"] == code or p["price"] is None or usage_of(p) is None:
            continue
        v = _swap_val(p, key)
        if v is None or _swap_same(key, v, current):
            continue
        if not all(_swap_same(k, _swap_val(p, k), _swap_val(base, k)) for k in keep):
            continue
        also = [(k, lab) for k, lab in SWAP_ALSO if k != key
                and not _swap_same(k, _swap_val(p, k), _swap_val(base, k))]
        group = next((g for g in best if _swap_same(key, g, v)), v)
        rank = (len(also), p["code"] not in preferred, abs(p["price"] - base["price"]), p["code"])
        if group not in best or rank < best[group][0]:
            best[group] = (rank, p, also)
    levels_by = {(l["usage"], l["level"]): l for l in levels}
    options = []
    for v, (_, p, also) in best.items():
        it = _item(p, usage_of(p), levels_by, TAG_CHOSEN, state.budget_won, state.budget_bound)
        it["swap"] = {
            "slot": slot, "value": _swap_label(key, v), "price_diff": p["price"] - base["price"],
            "also": [{"label": lab, "from": _swap_label(k, _swap_val(base, k)) if _swap_val(base, k) is not None else "정보 없음",
                      "to": _swap_label(k, _swap_val(p, k)) if _swap_val(p, k) is not None else "정보 없음"}
                     for k, lab in also],
        }
        options.append((v, it))
    options.sort(key=lambda o: (o[0], o[1]["price"]) if key in ("ram_gb", "ssd_gb") else (o[1]["price"], str(o[0])))
    return {"slot": slot, "label": label, "current": _swap_label(key, current) if current is not None else None,
            "base_code": code, "base_price": base["price"],
            "options": [it for _, it in options[:MAX_SWAP_OPTIONS]]}


def _targets(state, game_usages, other_usages, levels, vocab, notes):
    # 게임 묶음을 맨 앞에 둔다(2026-10-12 사장님 시험 「배그·롤 · 사무용 · 150만원」: 사무용 묶음이 먼저 와서
    # 그래픽카드 없는 오피스 PC 892,800원이 첫 카드가 됐고, 첫 묶음 기준인 「예산 안 게임 PC 없음」 안내도
    # 사라졌다). 게임은 용도 중 가장 높은 사양을 요구하므로 첫 카드·안내 문장은 게임 기준으로 정한다.
    targets = []
    if game_usages:
        targets.append((game_usages[0], "게임", game_min_rank(state.game, levels, vocab, notes)))
    for u in other_usages:
        fu = fit_usage(u)
        if fu is None:
            notes.append(f"sold: usage '{u}' has no fit mapping - skipped")
            continue
        targets.append((u, fu, 1))
    return targets


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


# ── 새로 나온 PC(운영자가 부품을 골라 만든 조립PC · 부품 상품화 5단계) ─────────────────────
# 공개 판정·가격은 api/custom_pc 한 곳, 용도 평가는 api/custom_pc_fit(몰 상품과 같은 기준표)이다.
# 몰 카드(items)와 섞지 않고 set 의 custom_items 로 따로 싣는다 — 몰 상품번호가 없어 보관 견적·쇼핑몰
# 연결 경로를 탈 수 없고, 구매는 「새로 나온 PC」 화면의 구매 상담 신청으로 받는다.
MAX_CUSTOM_ITEMS = 2
CUSTOM_PC_URL = "new-pcs.html#"


def load_custom_pcs(notes) -> list[dict]:
    """고객에게 지금 공개 중인 신규 조립PC + 부품 사양 판독. 읽지 못하면 빈 목록(추천은 그대로)."""
    try:
        from . import custom_pc
        from .custom_pc_fit import spec_from_parts
        with engine.connect() as conn:
            pcs = custom_pc.customer_list(conn)
    except Exception:  # noqa: BLE001 - 추가 카드라 추천을 막지 않는다
        log.exception("[sold_reco] custom pcs unavailable - skipped")
        return []
    return [dict(pc, fit_spec=spec_from_parts(pc["parts"])) for pc in pcs]


def custom_items(pcs, fu, r, levels, budget_won, bound) -> list[dict]:
    """그 용도·최소 수준에 맞는(또는 정보 없음인) 공개 신규 PC — 예산 안만, 최대 MAX_CUSTOM_ITEMS 개."""
    from .custom_pc_fit import NO_INFO, judge, reached
    lv = next((l for l in levels if l["usage"] == fu and l["level_rank"] == r), None)
    rank_of = {l["level"]: l["level_rank"] for l in levels if l["usage"] == fu}
    out = []
    for pc in pcs:
        if pc["price"] is None or (budget_won is not None and bound != "이상" and pc["price"] > budget_won):
            continue
        state = judge(pc["fit_spec"], fu, lv["level"]) if lv else "unknown"
        if state == "short":
            continue
        top = reached(pc["fit_spec"], fu) if state == "fit" else None
        out.append({
            "configuration_id": pc["configuration_id"], "title": pc["title"], "price": pc["price"],
            "price_note": pc["price_note"], "fit": state,
            "level": top, "level_text": f"{fu} {top}" if top else NO_INFO,
            "parts": [{"slot_label": p["slot_label"], "name": p["name"], "quantity": p["quantity"]}
                      for p in pc["parts"] if p["slot"] in ("CPU", "GPU", "RAM", "SSD")],
            "url": CUSTOM_PC_URL + pc["configuration_id"],
            "_rank": rank_of.get(top, 0),
        })
    out.sort(key=lambda x: (x["fit"] != "fit", -x["_rank"], x["price"]))
    for x in out:
        x.pop("_rank")
    return out[:MAX_CUSTOM_ITEMS]


def card_sets(state, game_usages, other_usages, notes, vocab=None, explore=None) -> list[dict]:
    """TalkState -> card_sets(kind='sold'). 한 용도에 한 set, set 마다 상품 최대 3개.

    explore(선택) = {wants, nav, anchor_code, uhd, more} — api/reco_explore 가 읽은 고객 추가 조건.
    이 함수가 wants 를 고치고(「램 더 크게」 -> 숫자) talk_notes 를 덧붙인다. 각 set 의 `explore` 에
    반영한 조건·못 맞춘 조건·다음 선택지 판정이 실린다(화면 문장은 grid_public 이 모은다).
    """
    levels, products = load()
    preferred = public_codes()
    ex = explore if explore is not None else {"wants": {}}
    ex.setdefault("wants", {})
    _resolve_more(ex, products, notes)
    filters = X.build_filters(ex["wants"], products)
    out = []
    seen = set()
    customs = load_custom_pcs(notes)
    for label, fu, r in _targets(state, game_usages, other_usages, levels, vocab, notes):
        if ex["wants"].get("uhd") and fu != "게임":
            r = _uhd_rank(levels, fu, r)
        if fu != "게임":
            r = _heavy_rank(levels, fu, r, ex["wants"].get("heavy"))
        if (fu, r) in seen:
            continue
        seen.add((fu, r))
        res = _explore_set(fu, r, state, levels, products, preferred, ex, filters)
        lv = next((l for l in levels if l["usage"] == fu and l["level_rank"] == r), None)
        out.append({
            "usage": label, "usage_grid": fu, "kind": "sold",
            "min_level": lv["level"] if lv else None,
            "min_level_work": lv["work"] if lv else None,
            "items": res["items"],
            "empty_reason": res.get("empty_reason"), "empty_note": res.get("empty_note"),
            "explore": res["explore"],
            # 옛 화면 경로가 깨지지 않게 — 조합 카드는 없다
            "cards": [], "empty_cells": [], "omitted_variants": [],
            "center_band": None, "center_band_key": None, "bands_considered": [],
            "center_tier": None, "center_tier_key": None, "tiers_considered": [],
        })
        extra = custom_items(customs, fu, r, levels, state.budget_won, state.budget_bound) if customs else []
        if extra:
            out[-1]["custom_items"] = extra
    return out
