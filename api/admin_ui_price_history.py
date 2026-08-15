"""가격 이력(ADM-PRC-030) 페이지 라우트 — `api/main.py`가 자동으로 싣는다
(§discovery, `api/` 평면에 둔다 — 하위 폴더는 자동 등록이 훑지 않는다).

**조회 전용.** 계약 `docs/design/spec-price-history.md`(사장님 확정 **1a** "상품 목록 + 추이",
2026-08-15. 1b "사유 축 피드 + 서랍"은 탈락). 원문(Claude Design)은 하네스만 연다
(`docs/design/MAKER-CHECKLIST.md` §1) — 이 화면은 계약 요약 텍스트만으로 지었다(로컬
원안 dc-*.html 없음 · 치수 대조 대상 아님).

화면 ID 대조: `docs/design/req/INDEX.md`에는 ID 열이 없어 대조 불가(정의서 링크만 있음,
23행 "가격 이력"). 대신 `docs/decisions/admin-identity.md` 140행이 "가격 이력(ADM-PRC-030)"
으로 지시서와 일치함을 확인했다 — 어긋남 없음.

■ 데이터 — 새로 만들지 않았다(담당 파일 밖, 실측만 했다: `api/admin_price_history.py`).
  정본: `GET /api/admin/price-history?product_code=&date_from=&date_to=`. 한 번 호출로
  좌측 상품 목록(`products[]`, 이미 **그 기간 기준으로 계산됨** — 계약 "기간을 바꾸면
  좌측 상품 목록도 다시 계산된다"를 서버가 이미 만족한다)과 선택 상품의 전체 이력
  (`items[]`)·현재가(`product`)를 함께 받는다. 날짜 형식 오류는 400, 지정한 상품에
  그 기간 이력이 없으면 404, **그 기간에 아무 상품도 이력이 없으면 200 + 빈 배열**
  (코드로 확인함 — `prods`가 비면 빈 구조로 200 반환, "가격 이력이 아직 없습니다").

  이 라우트는 그 API를 직접 부르지 않는다 — 다른 admin2 화면과 같은 관행대로 화면의
  인라인 스크립트가 브라우저에서 직접 불러 그린다. 여기서는 페이지 뼈대와 "사유별
  이동 링크" 해석 결과만 내려준다.

■★★ REASON_KO 번역 누락 — **화면에서 메우지 않는다** (2026-08-15 점검자 실측 반영,
  같은 날 안에 해소됨 — 아래 타임라인)
  착수 시점 실측(읽기 전용, 직접 DB 대조): `api/admin_price_history.py`의 `REASON_KO`에
  `margin_policy_undo`가 빠져 있었다 — **전체 28,993행 중 14,478행(49.9%)이 이
  사유코드**라 화면의 절반이 영문 원본 코드를 그대로 보여줄 뻔했다.

  이 파일은 **담당 밖이라 고치지 않았다**(다른 제작자가 같은 물결에서 처리 중 —
  활동 기록·가격 이력·회원 세 화면이 같은 번역 누락을 물려받았다는 점검 보고).
  화면에 자체 번역표를 만들어 메우지도 않았다 — 두 곳이 같은 일을 하면 나중에 한쪽만
  고쳐져 어긋난다(`compat_rules.html.j2`의 클라이언트 `OP_KO` 보정이 이미 그렇게 죽은
  코드가 된 전례). 대신 템플릿의 `reasonCell()`이 **서버가 준 `reason_label`을 그대로
  쓰고**, `reason_label === reason`(서버의 폴백이 원본 코드를 그대로 라벨 자리에 돌려주는
  경우)이면 **"번역 미비" 태그**를 붙여 코드 원문을 그대로, 그러나 그것이 미번역임이
  드러나게 보여준다. 지어낸 한글 라벨을 대신 넣지 않는다.

  ⚠ **재확인(같은 날, 제작 종료 직전): 다른 제작자가 `api/admin_price_history.py`의
  `REASON_KO`에 `margin_policy_undo`(→ "가격 검토 승인 되돌림")를 채워 넣었다** —
  파일을 다시 읽어 확인(28~36행), 실서버로 재조회(product_code=20481001·20489102)
  해서도 이제 `reason_label`이 정상 한글로 온다. **이 화면의 방어 로직은 남겨 둔다** —
  지금 안 걸린다고 지워버리면, 나중에 새 사유 코드가 생기거나 번역이 다시 빠졌을 때
  또 조용히 영문 코드를 노출한다. "지금 안 쓰인다"와 "필요 없다"는 다르다.

  ⚠ 이 REASON_KO 번역 누락과, 아래 §이동 링크의 "경로 해석"은 **다른 문제다.** 번역
  누락은 "무엇이라 부르나"(라벨 문구)의 문제고, 이동 링크는 "어디로 보내나"(경로)의
  문제다 — 후자는 REASON_KO가 완전해도 admin2로는 원래 못 쓴다(그 튜플의 두 번째 값이
  전부 구화면 `*.html` 상대경로다). 그래서 REASON_TARGETS는 라벨을 담지 않는다
  (사유가 "무엇을 뜻하는지"를 다시 번역하지 않는다 — 오직 "그 사유는 어느 admin2
  화면을 가리키는가"만 담는다. 이것도 "표"이지만 REASON_KO와 같은 종류의 표가 아니다:
  REASON_KO는 (지금은) 7개 사유 → 한글 문구 사전이고, 이건 7개 사유 → admin2 화면
  목적지 사전이다 — 서버가 애초에 admin2 목적지를 준 적이 없어 겹치는 자리가 없다).

  ⚠⚠ 2026-08-15 재확인 — 위 "사유 하나 → 목적지 하나"는 **더 이상 전부 사실이 아니다.**
  margin_policy·margin_policy_undo는 reason 코드 하나가 서로 다른 두 화면(개별 승인 ·
  대량 재산정)에서 오고, 목적지도 둘이 달라야 한다(아래 §이동 링크의 재확인 참조).
  그래서 이 두 reason만 REASON_TARGETS에서 **키를 둘로 나눴다**(margin_policy /
  margin_policy_bulk, margin_policy_undo / margin_policy_bulk_undo) — reason 코드
  자체를 두 종류로 만든 게 아니다(`items[].reason`은 여전히 DB 원문 그대로 7종뿐이다).
  나머지 5종은 여전히 "사유 하나 → 목적지 하나"다.

  실측(읽기 전용, product_price_history 전수, 착수 시점):
      margin_policy        14,480행 (14,478행 되돌려짐 — 아래 페어링 실측)
      margin_policy_undo   14,478행 — 착수 시점엔 REASON_KO 누락(현재는 해소, 위 참조)
      price_import             16행 (16행 전량 되돌려짐)
      price_import_undo        16행
      sourcing                  2행 (되돌려진 적 없음)
      manual                     1행 (되돌려진 적 없음)
      csv                        0행 (스키마 주석엔 있으나 현재 데이터에 없음)
  reason 값 전수가 이 7종 밖으로 나간 적은 없다(DISTINCT reason 대조 완료).

■★★ 사유별 이동 링크 — **경로로 판정한다. 라벨로 판정하지 않는다**
  (`admin_ui_swap_click_logs.py`의 사고 — 라벨 리네임으로 조회가 조용히 깨진 전례 —
  와 같은 이유·같은 방식. 그 파일이 남긴 교훈: "라벨은 조회 키가 될 수 없다".)

  계약 §사유별 이동 링크의 표(사유 → 가리키는 화면)를 코드로 옮기되, **목적지 경로는
  admin_nav.py의 라벨을 조회 키로 쓰지 않는다.** 대신:
    ① 그 목적지 화면의 실제 라우트 파일(`admin_ui_*.py`)이 존재하면, 그 파일의
       `@router.get(...)`을 직접 읽어 확인한 **경로 문자열**을 코드에 둔다(swap_click_logs
       의 POLICY_TARGETS와 같은 방식).
    ② admin_nav.NAV를 매 요청 다시 훑어 그 경로가 **실제로 링크돼 있는지**(href가 있는지)
       만 확인한다 — 라벨이 나중에 바뀌어도 이 조회는 안 깨진다.
    ③ 목적지 화면의 라우트 파일 자체가 아직 없으면(코드로 확인: 없음) 판정할 경로가
       없으므로 항상 비활성이다 — 이 셋은 라벨로도 경로로도 조회하지 않는다(추측 경로를
       박아두지 않는다. 화면이 생기면 이 표에 실측 경로를 추가해야 한다).

  실측(2026-08-15, 전부 `api/` 평면의 `admin_ui_*.py` 파일 존재 여부 + 그 파일 안의
  `@router.get(...)` 선언을 직접 읽어 확인 — `rg -l "response_class=HTMLResponse\\|@router.get" api/admin_ui_*.py` 로 27개 화면 전수 대조):

      manual  -> 작업 기록        /admin2/activity-logs   api/admin_ui_activity_logs.py 있음
                                    · admin_nav.py에 href 있음(연결됨) -> **이동 가능**
      csv     -> 상품 일괄 등록   /admin2/catalog-import  api/admin_ui_catalog_import.py 있음
                                    · admin_nav.py의 "상품 일괄 등록" 항목은 아직 href=None
                                      (그 화면 자체는 떠 있으나 LNB에 아직 안 걸림)
                                      -> **비활성**(경로는 있지만 NAV에 안 걸림)
      price_import,
      price_import_undo -> 단가표 반영        라우트 파일 없음(전수 확인) -> **비활성**
      margin_policy,
      margin_policy_undo -> 가격 검토 대기    /admin2/price-review  api/admin_ui_price_review.py 있음
                             ⚠ 재확인(2026-08-15, 확인자 결함 보고로 드러남): 착수 시점엔
                             라우트 파일이 없어 target_path를 None으로 뒀는데, 같은 날
                             다른 제작자가 `admin_ui_price_review.py`(ADM-PRC-010)를 지어
                             `/admin2/price-review`가 실재하게 됐다. `admin_ui_candidate_pool.py`
                             의 `no_price` 매핑도 이미 같은 경로를 가리키고 있었다(그쪽은
                             정확했음) — 이 파일만 target_path가 None인 채 남아 있었다.
                             target_path를 실측 경로로 채웠다(아래 REASON_TARGETS)
                             · admin_nav.py의 "가격 검토 대기" 항목은 이 시점 아직 href=None
                               -> **비활성**(경로는 있지만 NAV에 안 걸림 — csv와 같은 상태.
                               NAV가 연결되면 이 함수는 코드 수정 없이 다음 요청부터 활성화된다)

      ⚠⚠ 재확인(같은 날, 계약자가 새 결함으로 잡음) — 위 매핑은 **개별 승인**에만 맞다.
      margin_policy·margin_policy_undo는 **한 reason 코드가 두 화면에서 온다**
      (`api/admin_price_history.py` 실측, REASON_KO_BULK 참조): 개별 승인
      (`admin_price_review.py`, ref_id = 그 결정의 활동로그 log_id)과 대량 재산정
      (`admin_reprice.py` `/reprice/apply`·`/reprice/undo`, ref_id 컬럼 자체가 INSERT에
      없어 항상 NULL). 실측(전수): margin_policy 14,480건 중 ref_id 있는 건 **2건**뿐이고
      **14,478건(99.99%)이 대량 재산정**이다 — 그런데 이 표는 reason 코드 하나에 목적지
      하나만 담을 수 있어, 고치지 않으면 대량 재산정 14,478건도 "가격 검토 대기"로
      이동 가능하다고 잘못 안내하게 된다(실제로는 개별 승인 화면이 아니다).
      그래서 ref_id가 없는 경우를 위한 **별도 키**를 아래 REASON_TARGETS에 추가했다
      (margin_policy_bulk · margin_policy_bulk_undo — reason 코드 자체가 아니라, 서버
      `api/admin_price_history.py`가 ref_id로 가른 결과를 템플릿이 고르는 조회 키다.
      `templates/admin/price_history.html.j2`의 `moveCell()` 참조). 목적지는:

      margin_policy_bulk,
      margin_policy_bulk_undo -> 판매가 재산정   라우트 파일 없음(2026-08-15 확인자 실측
                             "라우트 0건") -> **비활성**(target_path=None이 맞다 — 지시
                             그대로 따름). ⚠ 다만 코드로 추가 확인한 사실을 남긴다:
                             `/admin2/margin-policy`(마진 정책, api/admin_ui_margin_policy.py,
                             같은 날 다른 제작자가 지음)가 같은 대량 재산정 기능
                             (`admin_reprice.py`)을 이미 쓰고 있다 — 단 `GET /reprice/preview`
                             (읽기 전용 미리보기)만 부르고, 이 14,478건을 실제로 만드는
                             `POST /reprice/apply`·`/reprice/undo`는 admin2 어느 화면에서도
                             아직 호출되지 않는다(전수 grep 확인). "판매가 재산정"이라는
                             이름의 화면은 없다는 지시가 틀리지 않았지만, **가장 가까운
                             화면은 이미 있다**는 사실은 다음 판단을 위해 남겨 둔다 —
                             target_path를 그리로 바꿀지는 이 정도 뜻의 결정이라 내 권한
                             밖이라 임의로 바꾸지 않았다(아래 보고 참조).
      sourcing -> 매입 견적(용산)             라우트 파일 없음(전수 확인) -> **비활성**

  비활성 사유 문구는 계약이 못박은 그대로: 「X」 화면은 아직 admin2 에 없습니다 —
  구화면으로는 잇지 않습니다.

■ 경로 — `/admin2/price-history`(계약이 "관례상"이라 적어 확정을 요구한 자리 — 다른
  admin2 화면과 같은 kebab-case 관례를 따랐다. 확정이 필요하면 보고).

■ 권한 — 조회는 로그인만 되면 등급 무관(viewer 이상, `api/auth.py`의
  OWNER_WRITE_PREFIXES에 `/api/admin/price-history`가 없음을 확인). 쓰기 버튼이
  하나도 없다 — 이 화면은 "왜 이 가격인가"의 근거 원장이지 가격을 고치는 자리가
  아니다(계약 §이 화면의 정체). 값 정정은 판매가 관리·상품 관리 소관.
"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render
from .admin_nav import NAV

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


# 계약 §사유별 이동 링크 — 사유 코드 -> 목적지 화면(admin2 라벨 + 실제 경로).
#
# ⚠ 이것은 REASON_KO(사유 -> 한글 문구) 번역표가 **아니다.** 사유가 "무엇을 뜻하는지"는
# 여기서 다시 정의하지 않는다(서버가 준 reason_label을 그대로 쓴다 — 템플릿 참조).
# 여기 담는 것은 오직 "그 사유는 어느 admin2 화면으로 이동해야 하는가"뿐이다.
#
# target_path는 목적지 화면의 실제 @router.get(...) 선언을 직접 읽어 확인한 값만 적는다
# (없는 화면은 추측 경로를 적지 않고 None으로 둔다 — 화면이 생기면 그때 실측해 채운다).
#
# ⚠⚠ margin_policy·margin_policy_undo만 예외: 키가 raw reason 코드가 아니다(위 모듈
# docstring 재확인 참조). `_bulk`가 없는 두 키는 **개별 승인**(ref_id 있음) 전용이고,
# `_bulk` 두 키는 **대량 재산정**(ref_id NULL, 전체의 99.99%) 전용이다 — 어느 쪽인지는
# `templates/admin/price_history.html.j2`의 `moveCell()`이 그 행의 `ref_id`를 보고
# 요청 시점에 고른다(서버는 두 버킷을 미리 계산만 해 둔다 · 새 텍스트를 만들지 않는다).
REASON_TARGETS = {
    "price_import": {"target_label": "단가표 반영", "target_path": None},
    "price_import_undo": {"target_label": "단가표 반영", "target_path": None},
    "margin_policy": {"target_label": "가격 검토 대기",
                       "target_path": "/admin2/price-review"},  # api/admin_ui_price_review.py 실측 — 개별 승인(ref_id 있음)만
    "margin_policy_undo": {"target_label": "가격 검토 대기",
                            "target_path": "/admin2/price-review"},  # 〃
    "margin_policy_bulk": {"target_label": "판매가 재산정", "target_path": None},
    # ↑ 대량 재산정(ref_id NULL) 전용. 2026-08-15 확인자 실측 "라우트 0건"을 그대로 따름
    # — 다만 `/admin2/margin-policy`(api/admin_ui_margin_policy.py)가 같은 대량 재산정
    # 기능(admin_reprice.py)을 이미 쓴다는 사실은 확인했다(위 모듈 docstring §이동 링크
    # 재확인 참조). 그 화면은 `/reprice/preview`(미리보기)만 부르고 이 14,478건을 실제로
    # 만드는 `/reprice/apply`·`/reprice/undo`는 아직 어디서도 안 불린다 — "판매가 재산정"
    # 화면이 없다는 확인자 판단과 다르지 않다고 판단해 target_path는 바꾸지 않았다.
    "margin_policy_bulk_undo": {"target_label": "판매가 재산정", "target_path": None},  # 〃
    "manual": {"target_label": "작업 기록",
               "target_path": "/admin2/activity-logs"},  # api/admin_ui_activity_logs.py 실측
    "sourcing": {"target_label": "매입 견적(용산)", "target_path": None},
    "csv": {"target_label": "상품 일괄 등록",
            "target_path": "/admin2/catalog-import"},  # api/admin_ui_catalog_import.py 실측(연결 전)
}


def _reason_links() -> dict:
    """사유 코드 -> {label, href, available, reason}. admin_nav.NAV를 매 요청 다시 훑어
    "그 경로가 지금 실제로 링크돼 있는가"만 확인한다(라벨 조회 금지 — 위 모듈 docstring
    참조). href가 나중에 채워지면 이 함수는 코드 수정 없이 다음 요청부터 바로 활성 링크를
    낸다."""
    live_hrefs = {href for _title, _icon, items in NAV for _label, href, _note in items if href}
    out = {}
    for key, t in REASON_TARGETS.items():
        available = t["target_path"] is not None and t["target_path"] in live_hrefs
        out[key] = {
            "label": t["target_label"],
            "href": t["target_path"] if available else None,
            "available": available,
            "reason": None if available else
                      f'「{t["target_label"]}」 화면은 아직 admin2 에 없습니다 — 구화면으로는 잇지 않습니다',
        }
    return out


@router.get("/price-history", response_class=HTMLResponse)
def price_history(request: Request) -> HTMLResponse:
    """가격 이력(ADM-PRC-030). 조회 전용 — 쓰기 API를 하나도 부르지 않는다.

    `GET /api/admin/price-history`(담당 밖, 읽기만 함) 한 번으로 좌측 상품 목록 +
    선택 상품의 전체 이력이 온다. 여기서는 사유별 이동 링크 실측 결과
    (`reason_links_json`, 경로 기반 — 위 모듈 docstring 참조)만 추가로 실어 보낸다.

    "지금 값에 기여한 이력만 / 되돌림 포함 전체" 토글과 되돌림 건수는 **서버가 준
    원본 사실(`items[]`의 reason·old·new·changed_at)에서 화면이 매 렌더 다시 계산**한다
    (별도 API 없이) — 사유가 `_undo`로 끝나는 항목을 그 앞의 미매칭 원본 사유와
    시간순으로 짝지어(같은 상품·같은 field 안에서) 양쪽을 "되돌려짐"으로 표시한다.
    이 짝짓기 알고리즘은 실제 DB 전수(28,993행)로 검증했다 — margin_policy 14,480건
    중 14,478건, price_import 16건 중 16건이 정확히 이 방식으로 되돌려짐과 일치했다
    (제작 보고서 참조). 하드코딩된 건수는 없다 — 매 렌더 서버 응답에서 다시 센다.
    """
    return render(request, "admin/price_history.html.j2",
                  screen_id="ADM-PRC-030", domain="price-history",
                  crumb_group="판매가", crumb_now="가격 이력",
                  reason_links_json=json.dumps(_reason_links(), ensure_ascii=False))
