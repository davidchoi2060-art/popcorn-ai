# -*- coding: utf-8 -*-
"""Expert 모드(「직접 고를게요」) 1단계 서버 연결 — A-71·A-72·A-73(2026-08-19 사장님 확정).

■ 왜 이 파일이 필요한가 (조사자 실측 · decision-log A-71)
  expert 모드는 서버와 한 번도 만난 적이 없다(fetch 0건 · consult_sessions.mode='expert'
  0건). 부품 21개가 화면에 리터럴로 박혀 있고, 화면이 스스로 계산하는 「검증」은
  compat_rules 9행과 대부분 어긋난다(A-72: 소켓·메모리 2행만 개념이 대응, 전력은 자체
  공식, cooler_tdp는 조건 분기 없이 항상 통과, 나머지 쿨러 2행은 대응 로직 자체가 없다
  — 애초에 화면 SLOTS가 7개라 COOLER 자리가 없었다).

  이 파일은 **1단계**만 다룬다 — 부품 목록은 여전히 화면의 리터럴 21개(2단계에서 실재고
  선택 UI로 바뀐다, `docs/design/req/req-expert-part-picker.md` 참조). 1단계가 새로
  여는 것은 ① 슬롯별로 **실재고에서 소수의 후보**를 보여줄 수 있는 읽기 API ② 고객이
  고른 구성을 **서버 규칙 9행 전부**로 판정하고 원장에 남기는 쓰기 API 둘이다.

■ 이 파일이 손대지 않는 것
  `mockups/mvp1/s1-session.html`(다른 제작자가 guided 질문 정리 중, 2026-08-19 기준
  미커밋 작업 있음) · `api/recommend.py`·`api/swap.py`·`api/candidates.py`(엔진 정본 —
  아래에서 **읽기만** 한다) · `api/main.py`(라우터 자동 등록이 `router`(APIRouter)가
  있는 `api/*.py` 를 알아서 싣는다 — 2026-08-13 도입, `main.py` 의 `_discover_routers`
  참조. 그래서 이 파일도 등록 줄을 더할 필요가 없다).

■ 재사용 — 새로 만들지 않고 그대로 부른 것
  `recommend._load_pool`(공유 파일 안이라 `swap._pool_ctx` 경유로 부른다) ·
  `recommend.load_compat_rules` · `recommend.check_rule_fields` ·
  `recommend.build_compat`(8슬롯 전부 찬 구성의 판정) · `swap._valid`(위반 슬롯) ·
  `recommend._build_set`(대안 두 개 — 아래 §대안 설계) · `recommend._explain_spec` ·
  `recommend._pref_tags` · `recommend._companion` · `product_name.display_name` ·
  `access_gate`(열쇠 발급·컬럼 준비 확인) · `visitor.resolve`(방문자 키).
  전부 module-level 함수를 그대로 import 한다 — `swap.py` 가 `recommend.py` 의
  언더스코어 함수를 그대로 가져다 쓰는 것과 같은 이 저장소의 기존 관례다.

■ 대안 설계 — 「고객 구성 대비 더 싼 것 / 더 나은 것」 (A-73)
  검토했지만 안 쓴 방법: `swap._find_chain`(스왑 대안이 쓰는 1슬롯 교체 + 연쇄 해소).
  이건 "슬롯 하나만 바꾼다"는 전제로 설계돼 있어(S3 부품 변경 UX), "완전히 새로운
  8슬롯 대안 두 벌을 만든다"는 이번 목적과 전제가 다르다 — 억지로 맞추면 새 다중 슬롯
  연쇄 해소 로직을 또 짜야 하는데, 그건 사실상 `_build_set`/`_dfs` 를 다시 구현하는
  것과 같다.
  대신 쓴 것: 고객의 현재 합계(`total`)를 예산 상한처럼 넘겨 **이미 있는**
  `_build_set("value", pool, total, rules)` / `_build_set("highend", pool, total, rules)`
  를 그대로 부른다 — `/api/recommend` 가 예산 제약이 있을 때 이미 하는 그 일이다.
    · value   = 그 총액 이하에서 **가장 싼** 전체 유효 구성(엔진 정의 그대로) → "더 싼 것"
    · highend = 그 총액의 1.5배(`HIGHEND_CAP_X`, 엔진 상수 그대로)까지 허용한
                **가장 비싼** 전체 유효 구성 → "더 나은 것"
  둘 다 `_build_set` 내부에서 `build_compat` 를 이미 호출하므로 판정 로직도 새로 안 짠다.
  **못 맞춘 부분(정직 기록)**: `/api/recommend` 의 고성능 티어는 부품별 배분 상한
  (`BUDGET_ALLOC`)으로 한 번 더 좁힌 `hi_pool` 을 쓰는데, 그건 `POST /api/recommend`
  라우트 함수 안의 지역 로직이라 import 로 재사용할 수 없다(private 함수가 아니라
  아예 함수 밖 즉석 코드). 그 필터 없이도 `_build_set` 자신의 총액 상한(1.5배)은
  그대로 걸리므로 "고객 총액 근방에서 고를 수 있는 최고 사양 조합"이라는 뜻은
  달라지지 않는다 — 다만 아주 드물게 한 부품에 예산이 쏠린 대안이 나올 수 있다는
  차이는 있다. 억지로 그 지역 로직을 복제하는 대신 이 차이를 여기 적어 둔다.

■ 판정 — 서버 호환 규칙 9행 전부 (A-72)
  고객이 8슬롯을 전부 채웠으면 `build_compat`·`_valid` 를 **그대로**(수정 없이) 부른다.
  화면이 슬롯을 비운 채 보낼 수 있어(현재 화면의 "(선택 안 함)") 그 경우는 두 함수를
  그대로 못 쓴다 — 둘 다 `chosen[slot]` 이 8자리 전부 dict 라고 전제하고 바로 `.get()`
  을 부르므로 빈 슬롯이 있으면 AttributeError 로 500 이 난다. 그렇다고 빈 자리를 빈
  dict `{}` 로 채워 넘기면 `_cmp` 의 NULL 불통과 규칙이 "미선택"을 "불합격"으로 만든다
  — `CLAUDE.md` 「원천이 아직 답할 수 없는 것은 판정하지 않는다」를 어긴다. 그래서
  아래 `_partial_compat` 하나만 새로 짰다 — 규칙 비교 자체(`_cmp`·`_rule_applies`)는
  recommend.py 것을 그대로 부르고, 이 함수는 "대상이나 비교 대상이 비었으면
  pass=None(검증 보류)"이라는 바깥 테두리만 추가한다.

■ A-03 — 이 파일에 LLM 은 없다
  읽기·쓰기 두 API 모두 결정론이다. 근거 문구가 필요하면 기존 `POST /api/recommend/
  explain` 이 그대로 쓰인다 — 이 파일이 남기는 quote_snapshots 의 JSON 모양이
  `recommend.py` 의 것과 동일해서(`{"parts":..., "compat":..., "reasons":...}`),
  그 엔드포인트가 세션 소유자 확인만 통과하면 별도 연결 없이도 동작한다.
"""
import json
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from . import access_gate
from . import visitor
from .db import engine
from .product_name import display_name
from .recommend import (
    SLOTS, SLOT_TYPES, load_compat_rules, check_rule_fields, build_compat, _build_set,
    _cmp, _rule_applies, _explain_spec, _pref_tags, _companion, HIGHEND_CAP_X,
)
from .swap import _pool_ctx, _valid
from .taxonomy import SLOT_LABELS as SLOT_KO
from .timeutil import now_iso

router = APIRouter(prefix="/api/expert")

# 슬롯당 보여줄 후보 수 — "지금 화면이 슬롯당 3종이니 그 언저리가 자연스럽다"(지시)를
# 따르되, 가격 스펙트럼 하나는 더 보여주는 게 낫다고 판단했다. 근거(2026-08-19 실측,
# v_recommendation_candidates): CPU 가격이 47,200원~18,631,600원인데 25~75%ile 은
# 195,700~619,300원이다 — 즉 최댓값은 낱개 극단치(워크스테이션급 1건)이지 "프리미엄
# 대표 상품"이 아니다. 문자 그대로의 최저/최댓값 2개 + 중앙 1개(=지금 방식과 같은 3개)
# 로는 이 극단치를 피하면서 폭을 보여주기 어렵다. 5개(5~95백분위 구간에서 균등 인덱스)
# 로 "입문~준프리미엄" 스펙트럼을 보여주면서도 여전히 "카탈로그 전체를 검색"하는
# 2단계와는 뚜렷이 다른 소수 목록이다.
EXPERT_SAMPLE_N = 5

# 후보 목록은 자주 안 바뀐다 — showcase(5분)보다는 짧게 잡는다. 이 화면은 고객이 실제로
# "이걸 살지" 고르는 자리라 재고 변화가 showcase(마케팅 미리보기)보다 더 빨리 반영돼야
# 한다는 판단이다.
_SLOT_CACHE: dict = {"at": 0.0, "data": None}
_SLOT_CACHE_TTL = 120.0


def _price_spread_sample(sorted_pool: list, n: int) -> list:
    """가격 오름차순으로 이미 정렬된 목록에서 5~95백분위 구간 n개를 고르게 뽑는다.

    `swap._pool_ctx` 가 만드는 `by_slot[slot]` 은 이미 (sale_price, product_code)
    오름차순이라 여기서 다시 정렬하지 않는다. 위 EXPERT_SAMPLE_N 주석의 근거를 그대로
    쓴다 — 인덱스 0·끝(진짜 최저/최댓값)은 피하고 5%~95% 구간 안에서만 고른다.
    """
    if len(sorted_pool) <= n:
        return list(sorted_pool)
    lo, hi = 0.05, 0.95
    last = len(sorted_pool) - 1
    out, seen = [], set()
    for i in range(n):
        frac = lo if n == 1 else lo + (hi - lo) * i / (n - 1)
        idx = min(last, int(round(frac * last)))
        while idx in seen and idx < last:      # 가격 동률이 몰려 인덱스가 겹치면 옆으로 민다
            idx += 1
        if idx in seen:
            continue
        seen.add(idx)
        out.append(sorted_pool[idx])
    return out


def _sample_slot(by_slot: dict, slot: str, n: int) -> list:
    """이 슬롯이 보여줄 표본. 종류가 하나면 가격 표본, 둘 이상이면 종류별 최소 1개.

    지금 8슬롯 중 COOLER 하나만 part_type 이 둘(공랭·수랭, `taxonomy.SLOT_TYPES`)이다.
    합쳐서 하나로 표본을 뽑으면 후보가 많은 쪽(공랭 150건)에 표본이 몰려 수랭을 원하는
    고객에게 선택지가 0이 될 수 있고, 수랭 전용 규칙(radiator)이 이 화면에서 한 번도
    검증되지 못한다. `SLOT_TYPES`(taxonomy 단일 원천)를 그대로 읽으므로 나중에 슬롯
    구성이 바뀌어도 이 함수를 따로 고칠 필요가 없다.
    """
    pool = by_slot.get(slot) or []
    types = SLOT_TYPES[slot]
    if len(types) <= 1:
        return _price_spread_sample(pool, n)
    groups = [(t, [p for p in pool if p["part_type"] == t]) for t in types]
    groups = [(t, g) for t, g in groups if g]      # 후보가 아예 없는 종류는 뺀다
    if len(groups) <= 1:
        return _price_spread_sample(groups[0][1] if groups else [], n)
    alloc = {t: 1 for t, _ in groups}               # 종류마다 최소 1개
    left = n - len(groups)
    pop_total = sum(len(g) for _, g in groups)
    if left > 0 and pop_total > 0:
        for t, g in groups:
            alloc[t] += int(left * len(g) / pop_total)
        short = n - sum(alloc.values())
        if short > 0:                                # 정수 나눗셈 나머지는 큰 쪽에 몰아준다
            biggest = max(groups, key=lambda x: len(x[1]))[0]
            alloc[biggest] += short
    return [p for t, g in groups for p in _price_spread_sample(g, alloc[t])]


def _expert_item(p: dict) -> dict:
    """후보 한 건의 표시 정보 — `/api/recommend` 의 items[] 항목과 같은 필드 구성.

    `part_type` 은 여기서는 **그 부품의 실제 종류**(예: COOLER_CPU_AIR)를 그대로 둔다 —
    read API 는 슬롯 키 아래 묶여 나가므로(`slots.COOLER.items[]`) 공랭·수랭 구분이
    남아 있는 편이 유용하다. 반대로 쓰기 API(`expert_build`)의 `items[]` 는 슬롯 키로
    덮어써야 한다 — `/api/recommend` 의 `_build_set` 이 `"part_type": s`(슬롯명)를 쓰고,
    S2(`s2-result.html`)의 `PART_KO` 매핑이 슬롯명 기준이라 원부품 종류를 그대로 두면
    "COOLER_CPU_AIR" 이라는 raw 값이 화면에 그대로 노출된다. 그래서 `expert_build` 는
    이 함수의 결과에 `part_type` 만 슬롯명으로 덮어써서 쓴다.
    """
    return {"part_type": p["part_type"], "product_code": p["product_code"], "sku": p["sku"],
            "name": display_name(p["product_name"]), "price": p["sale_price"],
            "maker": p.get("maker"), "spec": _explain_spec(p), "tags": _pref_tags(p)}


@router.get("/slots")
def expert_slots():
    """1단계 읽기 API — 슬롯 8개 각각에 실재고 소수 표본을 준다.

    모집단은 **`v_recommendation_candidates`** 하나뿐이다(`swap._pool_ctx` ->
    `recommend._load_pool` 이 그 뷰를 그대로 읽는다). 이 뷰는 이미 `data_origin='demo'`·
    검수 대기(`review_required_yn`)·`ai_candidate_yn=false`·품절을 제외한 상태라(지시문
    · `docs/design/req/req-expert-part-picker.md` §④ 실측과 동일), 여기서 다시 거르지
    않는다 — `products` 테이블을 직접 읽으면 "화면엔 보였는데 판정에서 튕기는" 상품이
    섞인다(같은 문서가 실측한 RTX 4070 SUPER 사례).

    세션·원장에 아무것도 남기지 않는다(`/api/showcase` 와 같은 성격 — 그냥 둘러보는
    것은 상담이 아니다). 캐시는 프로세스 전역 TTL(위 `_SLOT_CACHE_TTL`).
    """
    now = time.time()
    if _SLOT_CACHE["data"] is not None and now - _SLOT_CACHE["at"] < _SLOT_CACHE_TTL:
        return _SLOT_CACHE["data"] | {"cached": True}

    with engine.connect() as conn:
        _pool, by_slot, _codes = _pool_ctx(conn)

    slots_out = {}
    for slot in SLOTS:
        picks = _sample_slot(by_slot, slot, EXPERT_SAMPLE_N)
        slots_out[slot] = {
            "label": SLOT_KO.get(slot, slot),
            "total_candidates": len(by_slot.get(slot) or []),
            "items": [_expert_item(p) for p in picks],
        }
    data = {"slots": slots_out, "sample_size": EXPERT_SAMPLE_N, "generated_at": now_iso()}
    _SLOT_CACHE.update({"at": now, "data": data})
    return {**data, "cached": False}


class ExpertBuildBody(BaseModel):
    # {"CPU": 12345, "MB": null, ...} — 화면이 "(선택 안 함)"을 자동으로 붙이므로 값이
    # 없거나(0/None) 키 자체가 빠진 슬롯은 전부 "미선택"으로 받아들인다.
    picks: dict[str, int | None] = {}


def _partial_compat(chosen: dict, rules: dict) -> dict:
    """빈 슬롯이 하나라도 있을 때의 판정 — 위 모듈 docstring §판정 참조.

    규칙 비교(`_cmp`·`_rule_applies`)는 recommend.py 것을 그대로 부르고, 이 함수는
    "대상이나 비교 대상 슬롯이 비었으면 이 규칙은 미선택 검증 보류"라는 바깥 테두리만
    더한다. `build_compat`/`_valid` 와 달리 이 함수만 8슬롯이 안 찬 경우에도 죽지 않는다.
    """
    checks, violations = [], []
    for slot in SLOTS:
        for rule in rules.get(slot, ()):
            a, b = chosen[slot], chosen[rule["ref_slot"]]
            if a is None or b is None:
                checks.append({"key": rule["rule_key"], "label": rule["label"], "pass": None,
                               "detail": "미선택 부품이 있어 이 항목은 검증을 보류합니다"})
                continue
            if not _rule_applies(rule, a):
                continue   # 겨냥하지 않은 부품(예: 라디에이터 규칙 vs 공랭) — build_compat과 동일
            v, r = a.get(rule["field"]), b.get(rule["ref_field"])
            ok = _cmp(rule["op"], v, r)
            fmt = rule["detail_fmt"] or "{v} / {r}"
            # 결측 참조 필드(None)가 str()로 들어가 문구에 "None"이 새는 문제 —
            # recommend.py build_compat()과 같은 결함, 같은 처방("—"). 두 파일 다
            # 규칙 9행을 판정하는 자리라 엔진 정본에 새 공용 함수를 늘리지 않고
            # 각자 고친다(판정 _cmp·_rule_applies 는 그대로 recommend.py 것을 쓴다).
            checks.append({"key": rule["rule_key"], "label": rule["label"], "pass": ok,
                           "detail": fmt.replace("{v}", "—" if v is None else str(v))
                                         .replace("{r}", "—" if r is None else str(r))})
            if not ok:
                violations.append(slot)
    gpu, power = chosen.get("GPU"), chosen.get("POWER")
    headroom = (int(power["rated_watt"] / gpu["required_power_watt"] * 100)
                if gpu and power and power.get("rated_watt") and gpu.get("required_power_watt")
                else None)
    return {"power_headroom_pct": headroom, "checks": checks,
            "violations": sorted(set(violations))}


@router.post("/build")
def expert_build(body: ExpertBuildBody, request: Request, response: Response):
    """1단계 쓰기 API — 고른 구성을 서버 규칙 9행으로 판정하고 세 세트로 확정한다.

    응답의 `sets` 는 `/api/recommend` 와 같은 3키(value/recommend/highend)다(A-73) —
    S2(`s2-result.html`)가 `Q.sets.value|recommend|highend` 를 그대로 읽으므로, 여기서
    새 키를 만들면 S2 가 못 그린다.

        sets.recommend  고객이 고른 구성 그대로(서버가 바꾸지 않는다 — 지시문의 절대 규칙).
                        S2 는 탭이 없으면 recommend 를 기본으로 열므로("고른 구성을
                        먼저 보여준다") 여기 배치했다.
        sets.value      서버가 계산한 "더 싼" 대안(고객 총액 이하 최저가 전체 구성).
        sets.highend    서버가 계산한 "더 나은" 대안(고객 총액의 1.5배까지 허용한 최고가
                        전체 구성 — HIGHEND_CAP_X, 엔진 상수 그대로).

    슬롯을 비워 보낼 수 있다 — 그러면 `sets.recommend.complete=false` 이고 `compat.checks`
    는 그 슬롯이 걸린 규칙마다 `pass:null`("검증 보류")을 낸다(§판정). 대안 두 개는
    **완성된 8슬롯 구성만** 만들 수 있으므로, 비었으면 못 만드는 게 아니라 "고객이 아직
    다 안 골랐다"는 사실 자체가 정보다 — `complete`/`empty_slots` 로 명시한다.

    409  expert_pick_unavailable  보낸 product_code 가 지금 후보(v_recommendation_
                                  candidates)에 없다 — 품절이거나 검수로 빠졌다.
    400  slot_mismatch            그 product_code 는 있지만 이 슬롯 종류가 아니다.
    400  알 수 없는 슬롯          picks 의 키가 SLOTS(8개) 밖이다.
    """
    picks = body.picks or {}
    unknown = [k for k in picks if k not in SLOTS]
    if unknown:
        raise HTTPException(400, f"알 수 없는 슬롯: {', '.join(unknown)}")

    with engine.begin() as conn:
        pool, _by_slot, _codes = _pool_ctx(conn)
        live_by_code = {p["product_code"]: p for p in pool}

        chosen: dict = {}
        for slot in SLOTS:
            code = picks.get(slot)
            if not code:                      # None·0·키 없음 = 미선택
                chosen[slot] = None
                continue
            p = live_by_code.get(code)
            if p is None:
                raise HTTPException(409, {
                    "error": "expert_pick_unavailable", "slot": slot, "product_code": code,
                    "detail": "이 부품은 지금 후보 목록에 없어요 - 품절이거나 검수로 빠졌을"
                              " 수 있어요. 새로고침 후 다시 골라 주세요"})
            if p["part_type"] not in SLOT_TYPES[slot]:
                raise HTTPException(400, {
                    "error": "slot_mismatch", "slot": slot, "product_code": code,
                    "detail": f"이 부품은 {SLOT_KO.get(slot, slot)} 자리에 맞지 않아요"})
            chosen[slot] = p

        empty_slots = [s for s in SLOTS if chosen[s] is None]
        rules = load_compat_rules(conn)
        check_rule_fields(pool, rules)         # 규칙 필드 누락은 조용한 전면 불통과 -> 경고로 드러낸다

        if not empty_slots:
            # 8슬롯 전부 찼다 — recommend.py/swap.py 의 판정 함수를 손대지 않고 그대로 쓴다.
            bc = build_compat(chosen, rules)
            compat = {"power_headroom_pct": bc["power_headroom_pct"], "checks": bc["checks"]}
            violations = _valid(chosen, rules)
        else:
            pc = _partial_compat(chosen, rules)
            violations = pc.pop("violations")
            compat = pc

        total = sum(p["sale_price"] for p in chosen.values() if p is not None)
        n_fail = sum(1 for c in compat["checks"] if c["pass"] is False)

        if empty_slots:
            names = " · ".join(SLOT_KO.get(s, s) for s in empty_slots)
            reasons = [f"아직 {len(empty_slots)}개 자리를 고르지 않았어요({names})"
                       " - 나머지도 골라야 최종 판정을 받을 수 있어요."]
        elif n_fail:
            reasons = [f"{n_fail}가지 항목에서 호환 문제가 발견됐어요 - 아래에서 확인해 주세요."]
        else:
            reasons = ["직접 고르신 구성이에요 - 서버가 바꾸지 않고 그대로 보여드립니다.",
                       f"호환 규칙 {len(compat['checks'])}가지를 모두 확인했어요."]

        my_set = {
            "label": "직접 선택한 구성",
            "items": [_expert_item(chosen[s]) | {"part_type": s} for s in SLOTS if chosen[s]],
            "total": total,
            "compat": compat,
            # 예산 자체를 묻지 않는 모드라 상한이 없다 -- verdict="none"은 recommend.py가
            # 숫자 예산이 없을 때 쓰는 것과 같은 뜻(지어낸 상태가 아니다).
            "budget": {"cap": None, "verdict": "none", "over_by": 0},
            "reasons": reasons,
            "complete": not empty_slots,
            "empty_slots": [{"slot": s, "label": SLOT_KO.get(s, s)} for s in empty_slots],
            "violations": violations,
        }

        alt_value = alt_highend = None
        if total > 0:
            alt_value = _build_set("value", pool, total, rules)
            alt_highend = _build_set("highend", pool, total, rules)
            note = f"직접 고른 구성({total:,}원) 대비 서버가 계산한 대안입니다."
            for alt in (alt_value, alt_highend):
                if alt is not None:
                    alt["reasons"] = alt["reasons"] + [note]

        sets = {"recommend": my_set, "value": alt_value, "highend": alt_highend}
        comp = _companion(conn)

        uid = visitor.resolve(conn, request, response)
        gate_on = access_gate.column_ready(conn, "consult_sessions")
        access_key = access_gate.new_key() if gate_on else None
        # constraints 는 NOT NULL 컬럼이다 — expert 는 guided/chat 처럼 예산·용도를 묻지
        # 않으므로 "요청"(원문 요약, VERBATIM — candidates.py 의 처분표: 조건이 아니라
        # 후보 수·필터에 영향 없음) 라벨로 사실만 짧게 남긴다. 지어낸 제약을 넣지 않는다.
        cons_json = json.dumps([{"l": "요청",
                                  "v": f"부품 직접 선택 - {len(SLOTS) - len(empty_slots)}/{len(SLOTS)}슬롯"}])
        params = {"u": uid, "c": cons_json}
        cols, vals = "member_id, mode, constraints, user_id", "NULL, 'expert', CAST(:c AS JSONB), :u"
        if gate_on:
            cols, vals = cols + ", access_key", vals + ", :ak"
            params["ak"] = access_key
        session_id = conn.execute(text(
            f"INSERT INTO consult_sessions ({cols}) VALUES ({vals}) RETURNING session_id"),
            params).scalar()

        for qt, s in sets.items():
            if s is None:
                continue
            conn.execute(text(
                "INSERT INTO quote_snapshots (session_id, quote_type, items, companion, total_amount)"
                " VALUES (:sid, :qt, CAST(:it AS JSONB), CAST(:co AS JSONB), :ta)"),
                {"sid": session_id, "qt": qt,
                 "it": json.dumps({"parts": s["items"], "compat": s["compat"], "reasons": s["reasons"]}),
                 "co": json.dumps({"offered": comp}),
                 "ta": s["total"]})

    return {
        "session_id": session_id, "generated_at": now_iso(), "access_key": access_key,
        # expert 는 guided/chat 처럼 조건으로 후보를 좁히지 않는다(고르는 행위 자체가
        # 좁히기다) — 그래서 passed=total. 지어낸 델타를 만들지 않는다.
        "funnel": {"total": len(pool), "passed": len(pool)},
        "highend_cap_x": HIGHEND_CAP_X,
        "sets": sets, "companion": comp,
    }
