"""마진 정책(ADM-PRC-020) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

계약: `docs/design/spec-margin-policy.md`(승인 디자인 1a "정책판" — 값 넷을 카드수수료 →
전역 마진 → 분류별 예외 → 배분율 순으로 쌓는다. 예외 편집 서랍만 1b에서 가져온다).
정의서: `docs/design/req/req-margin-policy.md` — 실측 근거 전부가 거기 있다.

■ 쓰기는 이미 있는 API 세 종만 쓴다(새로 만들지 않았다) — 화면은 호출만 한다:
    POST /api/admin/pricing-settings          전역 마진 + 카드수수료 · owner만(PricingBody:
                                               card_fee_rate·margin_rate 둘 다 필수 — 하나만
                                               바꿔도 나머지 하나는 현재값을 그대로 실어 보낸다)
    PUT  /api/admin/categories/{cid}/margin    분류별 예외 · owner+operator(MarginBody:
                                               margin_rate. null = 예외 삭제 → 전역 상속 복귀)
    GET  /api/admin/reprice/preview?scope=     영향 계산 — **이미 저장된 값 기준**(scope=
                                               live/selling/all, dry_run 파라미터 없음)
  읽기 보강: GET /api/admin/categories(트리 + margin_rate·margin_effective·margin_source).

■★★ 상단 붉은 경고 — 코드 재확인(2026-08-15, 이 제작자, 서버 8002 실측 + 전수 grep):
  지금도 사실이다.
    admin_price_review.py:62   proposed = sale_from_purchase(purchase, fee, margin)
    admin_price_import.py:180  new_sale = sale_from_purchase(new_purchase, fee, margin)
  두 곳의 `fee, margin`은 둘 다 `_settings(conn)`(pricing_settings 최신 행 하나만 읽는다 —
  분류 조인 없음)에서 왔다. `rg "resolve_margins|category_margin_policies"`를 두 파일에
  돌리면 admin_price_review.py의 유일한 매치는 9행 **주석**(다른 화면 기능 부재 이유를
  설명하는 산문, "category_margin_policies에 …컬럼 없음")뿐이고 admin_price_import.py는
  매치 0건 — 둘 다 실제로 `resolve_margins`를 부르지 않는다. 저장소 전체에서
  `resolve_margins(`를 실제로 **호출**하는 곳은 `admin_categories.py`(표시)·
  `admin_reprice.py:92`(대량 재산정 — 이 화면이 쓰는 `/reprice/preview`가 바로 이 파일)
  **2곳뿐**이다(`pricing.py`도 매치되지만 그건 함수 정의부라 호출이 아니다).

■★★ 계약이 가정했지만 코드가 다른 곳 둘(신규 발견, 2026-08-15 이 제작자 코드 확인) —
  화면 문구를 계약 그대로 옮기지 않고 이 사실에 맞춰 조정했다:

  ① 분류별 예외 서랍의 "저장하면 이렇게 바뀝니다" 4줄 — **분류로 좁혀 셀 방법이 없다.**
     `GET /api/admin/reprice/preview`(admin_reprice.py)는 scope(live/selling/all) 셋만
     받는다 — `category_id`로 좁히는 파라미터가 없다. `_rows()`가 `p.category_id`를
     SELECT하긴 하지만(마진 조회용), `_classify()`가 만드는 item dict에는 넣지 않고
     `_summary()` 응답에도 분류별 집계가 전혀 없다(코드 전문 확인). 그래서 이 화면은
     분류별 수치를 **지어내지 않고** "이 API로는 분류별로 좁혀 셀 수 없습니다"라고
     정직하게 적는다.
  ② "해당 없음"(공급처 0곳) — 계약은 서버가 이미 이 값을 센다고 가정했지만,
     이 화면이 실제로 쓰는 `/reprice/preview`(admin_reprice.py)는 `product_supplier_prices`를
     전혀 읽지 않는다 — 매입가를 `products.purchase_price`에서 직접 쓴다. "공급처 0곳이면
     안 움직인다"는 조건은 **다른** 재산정 함수(`admin_price_import._reprice`, 개별
     가격검토승인·단가표반영 전용)의 얘기이지 이 화면의 대량 미리보기 얘기가 아니다.
     실측(scope=live, 2026-08-15): target 7279 = up 6899 + down 275 + same 105 + locked 0 —
     이미 완전히 나뉘어 남는 몫이 없다. 그래서 "해당없음"을 0으로 위장하지 않고
     "못 셈"으로 표시한다(화면이 그 이유까지 함께 적는다).

■ 이 파일 전용 읽기 전용 보강 값 둘 — 새 "쓰기 계약"이 아니라 렌더 시점에 한 번 계산해
  템플릿에 얹는다(swap_click_logs.py의 `_policy_links()` 선례를 따른다: 그 파일도 자기
  라우트 안에서 admin_nav.NAV를 직접 훑어 계산한 뒤 `..._json` kwarg로 얹었다):
    _history_summary()  product_price_history의 margin_policy/margin_policy_undo 건수 —
                         "가격 이력"(admin_price_history.py) API는 상품 하나씩만 조회하고
                         전역 집계를 안 준다. db.engine으로 직접 세는 단순 COUNT(*)이고
                         쓰기는 전혀 없다.
    _screen_links()      이 화면이 잇는 5곳(가격 이력·가격 검토 대기·상품 분류 관리·
                         추천 기준 보기·판매가 관리)을 **경로**로 판정한다. 라벨로 찾지
                         않는다 — `admin_ui_swap_click_logs.py`가 라벨 조회로 겪은 사고
                         (화면명이 "추천 기준 설정"→"추천 기준 보기"로 바뀌며 조용히 깨짐)의
                         재발 방지. admin_nav.NAV는 **읽기만** 한다.
    실측(2026-08-15, 이 제작자 재확인 — 같은 날 먼저 적힌 "1곳"은 그새 admin_nav.py
    개정으로 늘었다): 5곳 중 "상품 분류 관리"(/admin2/categories) · "추천 기준 보기"
    (/admin2/policy-weights) **2곳**이 admin_nav.py에 href가 걸려 있다. 나머지 셋
    (가격 이력·가격 검토 대기·판매가 관리)은 라우트 코드(admin_ui_price_history.py 등)는
    이미 있지만 admin_nav.py의 href가 아직 None이라 — 지금은 비활성으로 보이는 것이
    맞다(화면 결함 아님).
    ⚠ 이 수는 계속 늘어난다 — admin_nav.py는 검증 통과 화면마다 href를 계속 연결하는
    중이고(같은 날 안에도 두 차례 늘었다, admin_nav.py 자체 docstring 참조), _screen_links()는
    매 요청마다 admin_nav.NAV를 다시 읽어 판정하므로 **코드는 항상 정확하다.** 낡는 것은
    이 숫자를 박아 둔 주석뿐이다 — 다음에 고칠 사람도 여기 적힌 "2곳"을 베끼지 말고,
    admin_nav.py의 NAV를 그 시점에 직접 세어 적어라.

■ 배분율 — `candidates.BUDGET_ALLOC`(코드 상수, 쓰기 경로 없음)을 그대로 읽는다. 값을
  화면에 베끼지 않고 원본을 import해서 쓴다. 라벨은 `taxonomy.PART_LABELS`(부품 어휘
  단일 원천, `.claude/CANON.md` §1)에서 가져온다 — 두 번째 어휘를 만들지 않는다.

■★ 인증 전제(2026-08-15) — 이 화면은 서버 렌더 시점에 실데이터를 싣는다 — 미들웨어가
  `/admin2/` 를 막는 것이 전제다(`api/auth.py` `auth_middleware`/`_is_gated`). 이 파일
  자신은 로그인을 확인하지 않는다 — 확인하지 않아도 되는 이유가 이 한 줄이다.
"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from .admin_ui_common import render
from .admin_nav import NAV
from .db import engine
from .taxonomy import PART_LABELS
from .candidates import BUDGET_ALLOC

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


# 이 화면이 잇는 곳 — **경로**로만 판정한다(라벨 금지, 근거는 위 모듈 docstring).
# "판매가 관리"는 지시서가 요구한 4곳(가격 이력·가격 검토 대기·상품 분류 관리·
# 추천 기준 보기)에 더해, "이 화면에서 안 하는 것" 목록(정의서 §⑥)이 가리키는
# 다섯 번째 목적지라 같은 방식으로 함께 판정했다(일관성 — 하나만 텍스트로 남기지 않는다).
LINK_TARGETS = {
    "price_history": {"label": "가격 이력", "path": "/admin2/price-history"},
    "price_review": {"label": "가격 검토 대기", "path": "/admin2/price-review"},
    "categories": {"label": "상품 분류 관리", "path": "/admin2/categories"},
    "policy_weights": {"label": "추천 기준 보기", "path": "/admin2/policy-weights"},
    "sale_price": {"label": "판매가 관리", "path": "/admin2/sale-price"},
}


def _screen_links() -> dict:
    """admin_nav.NAV를 "그 경로가 실제로 링크돼 있는가"로만 훑는다(읽기만 — 고치지 않는다)."""
    live_hrefs = {href for _title, _icon, items in NAV for _label, href, _note in items if href}
    out = {}
    for key, t in LINK_TARGETS.items():
        available = t["path"] in live_hrefs
        out[key] = {
            "label": t["label"], "href": t["path"] if available else None,
            "available": available,
            "reason": None if available else "아직 admin2 메뉴에 연결되지 않았습니다",
        }
    return out


def _history_summary(conn) -> dict:
    """margin_policy(가격 검토 승인 + 대량 재산정) / margin_policy_undo(대량 재산정 되돌림)
    건수 — product_price_history 원장에서 직접 센다. 쓰기 없음, 새 API 계약 아님(위 참조)."""
    rows = dict(conn.execute(text(
        "SELECT reason, COUNT(*) FROM product_price_history"
        " WHERE reason IN ('margin_policy', 'margin_policy_undo') GROUP BY reason")).all())
    forward = rows.get("margin_policy", 0)
    reverted = rows.get("margin_policy_undo", 0)
    return {
        "forward": forward,
        "reverted": reverted,
        "pct": round(reverted / forward * 100, 2) if forward else None,
    }


def _budget_chips() -> list:
    """부품별 예산 배분율 — candidates.BUDGET_ALLOC이 정본(코드 상수). 화면에 값을
    베끼지 않고 원본을 그대로 읽어, 라벨만 taxonomy.PART_LABELS(부품 어휘 단일 원천)로
    붙인다."""
    return [{"key": k, "label": PART_LABELS.get(k, k), "pct": v} for k, v in BUDGET_ALLOC.items()]


@router.get("/margin-policy", response_class=HTMLResponse)
def margin_policy(request: Request) -> HTMLResponse:
    with engine.connect() as conn:
        hist = _history_summary(conn)
    return render(request, "admin/margin_policy.html.j2",
                  screen_id="ADM-PRC-020", domain="margin-policy",
                  crumb_group="판매가", crumb_now="마진 정책",
                  links_json=json.dumps(_screen_links(), ensure_ascii=False),
                  history_json=json.dumps(hist, ensure_ascii=False),
                  budget_json=json.dumps(_budget_chips(), ensure_ascii=False))
