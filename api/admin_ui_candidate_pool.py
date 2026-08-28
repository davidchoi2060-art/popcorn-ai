"""추천 가능 재고 현황(ADM-ENG-030) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

계약 = `docs/design/spec-candidate-pool.md`(사장님 확정 1a, 2026-08-14) ·
`docs/design/req/req-candidate-pool.md`. **조회 전용** — 이 라우트도, 화면도 쓰기 요청을
보내지 않는다. 숫자는 화면의 인라인 스크립트가 브라우저에서 직접
`GET /api/admin/candidate-pool`(`api/admin_pool.py` — 담당 밖, 읽기만 한다)을 불러 그린다.
이 라우트 자신은 페이지 뼈대와 "사유별 갈 화면" 링크표만 내려준다(다른 admin2 화면과
같은 관행 — `admin_ui_build_map.py`·`admin_ui_ops_stage.py` 참고).

`docs/decisions/decision-log.md`(2026-08-14 기록자 실측)가 이미 확인한 대로 화면 ID는
`ADM-ENG-030`이 맞다(반대로 `api/admin_usage_floors.py`가 같은 번호를 오기로 들고 있다는
사실도 그 문서가 지적한다 — 그 파일은 이 작업의 담당이 아니라 고치지 않았다).

■ 사유별 "갈 화면" — 화면이 짓지 않고 정본(`api/admin_nav.NAV`)에서 매 요청 다시 찾는다.
  admin2 에 그 경로가 아직 안 걸려 있으면(2026-08-15 기준: 가격 검토 대기 — 라우트
  파일은 있지만 NAV href 가 아직 None) href 가 없으므로 화면은 자동으로 "없음"으로
  비활성 처리한다 — 스펙의 명시 요구사항("admin2 에 없는 화면은 「없음」으로 비활성한다")
  과 정확히 일치한다. "재고 입고"는 admin_nav.NAV 자체에 항목이 아예 없다(라우트 파일도
  없음 — 의도된 비활성).
  ⚠ **위 두 문장은 2026-08-15 스냅샷이고 둘 다 지금은 낡았다(2026-08-28 정정, CANON
  §5 — 지우지 않고 옆에 남긴다).** 가격 검토 대기는 그날 안에 NAV href 가 채워졌고
  (`admin_nav.py:334`), 재고 입고는 2026-08-18 커밋 `8a31bf0`으로 라우트 파일
  (`api/admin_ui_stock_inbound.py`)과 NAV 연결이 **둘 다** 생겼다. 그런데 이 파일의
  `REASON_TARGET_PATH`(아래)는 그 뒤로 한 번도 안 고쳐져 "재고 없음·매입" 이동 배지가
  10일 넘게 이유 없이 비활성이었다 — 상세 경위는 `REASON_TARGET_PATH` 바로 위 주석.
  `admin_pool.py`가 사유·얇은 카테고리 항목에 함께 주는 `link` 필드는 옛
  `/admin/*.html` 파일명 문자열이라 admin2 경로가 아니고, "구화면으로는 다시 잇지
  않는다"는 결정(`api/admin_nav.py` 모듈 docstring, 2026-08-12)과도 어긋나므로
  그 필드는 쓰지 않는다 — 여기서 만든 `reason_targets_json`으로 대체한다.

  ⚠★ **조회 키는 경로다, 라벨이 아니다(2026-08-15 점검자 지적으로 교체).** 처음엔
  `REASON_TARGET_LABEL`의 라벨 문자열로 `NAV`를 조회했는데, 라벨은 사장님 확정마다
  바뀐다(2026-08-14 하루에만 두 번). `api/admin_ui_swap_click_logs.py`가 바로 이
  방식으로 2026-08-14에 조용히 깨진 전례가 있어(그 파일 docstring 참고, 읽기만 하고
  고치지 않았다) 같은 해법을 옮겼다 — `REASON_TARGET_PATH`(경로)를 조회 키로 쓰고,
  `NAV`는 "그 경로가 지금 실제로 링크돼 있는가"만 확인하는 용도로 남긴다.

■ 사유별 링크에 부품 종류·사유를 필터로 실어 보내는 것(스펙 ②)은 **아직 짓지 않았다**.
  `req-candidate-pool.md` ⑥이 스스로 "지금 API는 목적지 화면에 필터를 전달하는
  파라미터를 주지 않는다 · 필터를 이어 붙이려면 목적지 화면과 별도 합의가 필요하다
  (결정 필요 지점)"이라 명시한 미결 사항이다. `/admin2/reviews`는 `?part_type=`
  딥링크를 실제로 읽지만(`reviews.html.j2` `parseUrlParams`), `candidate-pool` 응답은
  부품 종류를 한글 라벨로만 주어 원본 코드(`part_type`)를 복원하려면 어휘를 다시
  선언해야 하고, "검수 대기"·"후보 미승격" 두 사유를 리뷰 화면의 작업 상태값
  (대기/승인/수정/보류/처리)에 안전하게 대응시킬 근거도 없다 — 잘못 대응시키면
  "필터가 걸렸다"는 화면이 실은 다른 것을 보여주는, 없는 것만 못한 결함이 된다.
  그래서 지금은 사유 없이 화면만 이동한다.
"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_nav import NAV
from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])

# 사유 키 -> "이 사유는 어느 화면에서 고치나"의 표시 라벨. 근거(req-candidate-pool.md
# ④ 실측): "사유별 처리 화면 연결: 사양 미등록→상품 관리, 검수 대기·후보 미승격→상품
# 사양 검수, 가격 검토 대기→가격 검토 대기 화면, 재고 없음→재고 입고 화면(전부 다른
# LNB 그룹)."
REASON_TARGET_LABEL = {
    "no_specs": "상품 관리",
    "need_review": "상품 사양 검수",
    "not_candidate": "상품 사양 검수",
    "no_price": "가격 검토 대기",
    "oos": "재고 입고",
}

# ⚠★ 2026-08-15 점검자 지적으로 교체 — **경로(route path)가 조회 키다. 라벨이 아니다.**
# 예전엔 admin_nav.NAV를 위 REASON_TARGET_LABEL의 **라벨 문자열**로 조회했다. 그런데
# 라벨은 사장님 확정마다 바뀐다 — 실제로 2026-08-14 하루에만 두 번 바뀌었다
# ("추천 기준 설정"->"추천 기준 보기", "미분류"->"기타(ETC)"). 라벨이 다시 바뀌면 이
# 조회는 **오류 없이 조용히** None을 돌려주고, 화면은 "사유별 이동" 링크가 이유 없이
# 비활성으로 빠진다 — 결함처럼 보이지도 않는다. 같은 사고가 이미 한 번 실제로 있었다:
# `api/admin_ui_swap_click_logs.py`(ADM-ORD-030)가 2026-08-14에 겪었다(그 파일 상단
# docstring "■★★ 정책 화면 링크 3종" 참고 — 읽기만 했고 고치지 않았다). 그 화면이 쓴
# 해법을 그대로 따른다: 경로는 각 목적지 화면의 `admin_ui_*.py`에서 `@router.get(...)`
# 선언을 직접 읽어 확인했다(아래 값 옆 근거). admin_nav.py는 여전히 "그 경로가 지금
# NAV 어딘가에 실제로 링크돼 있는가"만 확인하는 용도로 쓴다(읽기만 — 고치지 않는다).
#
# ⚠ 정정(2026-08-28, 제작자 — 매뉴얼 작성 중 발견) — 바로 위 문단("oos"가 이 표에 없는
# 이유)은 **쓰인 시점(2026-08-14/15)엔 사실**이었으나 더는 아니다. **지우지 않고 옆에
# 정정을 남긴다**(CANON §5 — 뒤집힌 근거를 지우지 않는다). `git log --follow` 실측:
# 이 파일은 커밋 82a55a1(2026-08-15 17:46)로 최초 커밋된 뒤 **오늘까지 한 번도 다시
# 고쳐지지 않았다.** 그런데 admin_nav.py는 그 사흘 뒤 커밋 8a31bf0(2026-08-18 12:04
# "재고 입고 메뉴 연결 · 목차 등재")으로 `/admin2/stock-inbound`를 NAV에 실제로
# 연결했다(A-58 해소 — admin_nav.py 그 커밋 메시지·9차 노트 참고). 즉 위 문단이 말하는
# "화면이 아예 없다"는 전제가 2026-08-18부터 거짓이 됐는데, 이 표만 안 따라가 **10일
# 넘게** "재고 없음·매입" 이동 배지가 이유 없이 비활성으로 남았다(그림 C의 21번·그림
# G의 37번 캡처 — 매뉴얼 작성 중 결함으로 지적됨). `api/admin_ui_home.py`의
# `_TARGET_PATH`가 같은 종류의 사고를 11일 동안 겪은 전례가 있다(그 파일 주석 참고 —
# price-import·sourcing 두 화면). **원인도 같다: 경로를 조회 키로 쓰는 이 방식은
# admin_nav 쪽 변화를 스스로 알아채지 못한다 — 사람이 이 표를 다시 훑어야 한다.**
# 아래 `_reason_targets()`가 `NAV`를 정본으로 한 번 더 거르므로, 여기 적은 경로가
# 나중에 메뉴에서 사라지면 자동으로 다시 비활성이 된다 — 지어낸 경로가 화면에 나가지
# 않는다는 안전장치는 그대로 유효하다.
REASON_TARGET_PATH = {
    "no_specs": "/admin2/products",       # api/admin_ui_products.py `@router.get("/products")`
    "need_review": "/admin2/reviews",     # api/admin_ui_reviews.py `@router.get("/reviews")`
    "not_candidate": "/admin2/reviews",   # 위와 같은 화면 — 사유만 다르다
    "no_price": "/admin2/price-review",   # api/admin_ui_price_review.py `@router.get("/admin2/price-review")`
    "oos": "/admin2/stock-inbound",       # api/admin_ui_stock_inbound.py `@router.get("/admin2/stock-inbound")`
                                           # NAV 연결 2026-08-18(8a31bf0) — 위 정정 참고
}


def _reason_targets() -> dict:
    """사유 키 -> {label, href}. href 는 admin_nav.NAV 에 그 **경로**가 실제로 걸려
    있을 때만 채워진다 — 없으면 None(화면이 비활성으로 그린다). 매 요청 NAV 를 다시
    훑어 확인한다(캐시하지 않는다 — admin_nav 가 나중에 그 경로를 신설해도 이 화면이
    코드 수정 없이 따라간다)."""
    live_hrefs = {href for _title, _icon, items in NAV for _label, href, _note in items if href}
    out = {}
    for key, label in REASON_TARGET_LABEL.items():
        path = REASON_TARGET_PATH.get(key)   # "oos"처럼 없으면 None — 화면 자체가 없다는 뜻
        out[key] = {"label": label, "href": path if (path and path in live_hrefs) else None}
    return out


@router.get("/candidate-pool", response_class=HTMLResponse)
def candidate_pool(request: Request) -> HTMLResponse:
    """추천 가능 재고 현황(ADM-ENG-030) — **신설**. 사장님 확정(2026-08-14): 1a.

    1a 구조(스펙 원문) = 상단 카드줄(통과 큰 카드 + 사유 5종 카드) + 배타 안내 띠 +
    부품×사유 본표(+합계 행) + 우측 레일(얇은 카테고리 · 결합 조건 2종 · 사유별 이동) +
    하단 고정 문구. 숫자는 전부 `GET /api/admin/candidate-pool` 응답 그대로이고, 화면이
    직접 계산하는 것은 카테고리별 통과율(=ok/total, 서버가 전체 `rate`를 구하는 것과
    같은 공식) 하나뿐이다 — 그 밖의 집계·판정은 재계산하지 않는다.
    """
    return render(
        request, "admin/candidate_pool.html.j2",
        screen_id="ADM-ENG-030", domain="candidate-pool",
        crumb_group="상품사양관리", crumb_now="추천 가능 재고 현황",
        reason_targets_json=json.dumps(_reason_targets(), ensure_ascii=False),
    )
