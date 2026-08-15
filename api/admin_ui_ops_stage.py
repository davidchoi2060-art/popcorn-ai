"""오픈 단계 설정(ADM-OPS-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

화면 자체는 `docs/design/dc-ops-stage.html`(사장님 Claude Design 승인 원안)을
`templates/admin/ops_stage.html.j2`로 옮긴 것이다. 요구사항 정의서:
`docs/design/req/req-ops-switch.md`. 재정의 근거: `docs/decisions/decision-log.md` A-34
(원래 A-33으로 기록됐다가 번호 충돌로 A-34로 이동 — 내용은 동일).

■★ 데이터 API — 새로 만들지 않았다. `api/admin_ops.py`(기존, ADM-SYS-010 docstring이
  남아 있으나 실제로는 이 화면이 쓴다 — 아래 "알려진 오기" 참고)가 이미 구현·배선돼
  있던 것을 그대로 소비한다.

      GET  /api/admin/ops-settings              모드 5종 · 이력 20건 · 프리셋 3종 · effects 7행
      POST /api/admin/ops-settings               {modes:{...}} 부분 갱신 (owner)
      POST /api/admin/ops-settings/undo/{log_id}  before 스냅샷 복원 (owner)

  화면(`ops_stage.html.j2`)이 브라우저에서 직접 이 세 엔드포인트를 부른다 — 이 라우트
  자신은 페이지 뼈대만 내려준다(다른 admin2 화면과 같은 관행, `product_category_map.py`
  참고). `api/admin_ops.py`는 이 작업의 담당 파일이 아니므로 고치지 않았다.

■★ 축별 판정(동작 중/잠듦/미구현)·단계 배정(MVP2/MVP3)·"동작 중이 되려면" 문구는
  **API가 없다.** `docs/design/req/req-ops-switch.md` 비범위 절이 스스로 명시한다 —
  "축별 상태를 자동 판정하는 구체적 알고리즘·구현 수단은 설계 영역"이라 요구사항
  단계에서도 확정하지 않았다. 이 화면이 프런트엔드 하나만 짓는 범위에서 실제 코드
  정적 분석 엔진을 새로 세우는 것은 명백히 범위 밖이다.

  그래서 아래 AXIS_META는 **정적 스냅샷**이다 — 서버가 매 요청 다시 판정하는 값이
  아니라, 사장님이 승인한 원안(`dc-ops-stage.html`의 `AXES` 상수, 2026-08-13
  16:10 확정)과 요구사항 정의서 ④절(코드 줄 인용 포함)을 그대로 옮긴 것이다.
  **코드가 바뀌어도 이 표는 자동으로 따라오지 않는다** — 화면에도 이 사실을
  "판정 근거일"로 노출한다(VERDICT_AT/VERDICT_SOURCE). 재실측이 필요하면 이 딕셔너리를
  손으로 다시 대조해야 한다 — 이 화면 자신이 "요구사항 정의서 ⑥ 자동 판정" 원칙을
  완전히 충족하지 못한다는 뜻이고, 그 사실을 숨기지 않는다(제작 보고서에도 남긴다).

  refund 축은 요구사항 정의서 "결정이 필요한 지점 1"이 미결로 남긴 항목이다(잠듦 vs
  동작 중). **승인된 디자인(`dc-ops-stage.html`)이 "동작 중"으로 확정해 놓았다** —
  범례 문구 "환불은 문구만 갈리지만 소비는 되므로 여기에 셉니다"가 그 근거다. 이
  화면은 그 이후 확정판인 디자인을 따른다(요구사항 정의서의 잠정 문안이 아니라).

■★ 구축 축(8그룹 37항목)은 새로 세지 않는다. `admin_ui_common.render()`가 좌측
  메뉴에 쓰려고 이미 주입하는 `nav`(= `admin_nav.nav_for()`)·`nav_counts`
  (= `admin_nav.counts()`)를 본문에서 한 번 더 읽을 뿐이다 — 정본은 여전히
  `api/admin_nav.py` 하나이고, 이 화면은 그 결과를 두 번째로 렌더링만 한다.

■★ "이 화면 자신도 미구축입니다"(사실 카드) 문구는 살아 있는 값으로 판정한다
  (`_self_built()`) — `admin_nav.NAV`에서 "오픈 단계 설정" 항목의 href 유무를 직접
  읽는다. 문서에 고정 문장으로 박으면(harness가 나중에 메뉴 링크를 붙이는 순간)
  바로 낡는다 — CLAUDE.md가 반복해서 지적하는 병이다.

■ 좌측 메뉴(LNB) 참고 — `api/admin_nav.py`의 "오픈 단계 설정" 항목은 이 라우트가
  만들어진 시점에도 여전히 `href=None`(신설 예정)이다. 그 파일은 이 작업의 담당
  범위 밖이라 고치지 않았다(지시서: "메뉴 링크는 내가 따로 붙인다") — href를
  `/admin2/ops-settings`로 올려야 LNB에서 이 화면으로 갈 수 있다.
"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_nav import NAV
from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])

# 전환 축 5종의 단계 배정 — 요구사항 정의서 ④3부, A-34 본문 근거와 함께 확정된 값
# (정황상 대응이 아니라 "확정"으로 적힌 유일한 단계 매핑이다). 구축 축(37항목)의
# 단계는 반대로 아직 미정이라 여기 없다 — 임의로 채우지 않는다(아래 HINTS_BY_STAGE
# 참고 · 요구사항 정의서 "결정이 필요한 지점 7·8").
STAGE_LABEL = {"mvp2": "MVP2", "mvp3": "MVP3"}

# 판정 스냅샷 근거 — 자동 판정이 아니라는 사실 자체를 화면에 노출한다.
VERDICT_AT = "2026-08-13"
VERDICT_SOURCE = ("docs/design/dc-ops-stage.html(AXES 상수, 사장님 승인)"
                   " · docs/design/req/req-ops-switch.md ④절(코드 줄 인용)")

# 축별 정적 판정표 — 값(own/mall)·시각(updated_at)만 GET /api/admin/ops-settings의
# 실시간 값을 쓰고, 이 아래는 전부 스냅샷이다(위 docstring 참고).
AXIS_META = {
    "pay": {
        "name": "결제", "stage": "mvp2", "verdict": "live",
        "summary": "주문과 인계를 배타적으로 여닫습니다 — 고객 장바구니가 이 값을 실시간으로 따릅니다.",
        "verdict_title": "동작 중 — 값이 바뀌면 서버 처리가 실제로 갈립니다",
        "verdict_desc": ("주문(orders.py)과 인계(handoff.py)가 각각 이 값을 확인해 반대 모드면"
                          " 409를 돌려줍니다. 고객 화면도 GET /api/ops로 읽어 버튼 문구와"
                          " 호출 대상을 바꿉니다."),
        "verdict_src": "api/orders.py L71-74 · api/handoff.py L65-69 · mockups/mvp1/s4-cart.html L242·416·432·478",
        "need": "",
        "own_label": "자체 결제", "own_desc": "POST /api/orders 가 열리고 인계는 409로 막힙니다",
        "mall_label": "쇼핑몰 인계", "mall_desc": "POST /api/handoff 가 열리고 자체 결제는 409로 막힙니다",
        "effect_match": ["S4 결제 화면", "주문 생성 API", "재고 예약(hold)"],
    },
    "refund": {
        "name": "환불", "stage": "mvp2", "verdict": "live",
        "summary": "값에 따라 고객·운영자 안내 문구가 갈립니다 — 처리(상태 전이·재고 복귀)는 동일합니다.",
        "verdict_title": "동작 중 — 단, 갈리는 것은 문구까지입니다",
        "verdict_desc": ("my_orders.py가 orders.ops_snapshot의 값을 읽어 refunds.refund_mode에"
                          " 저장하고, 완료된 MVP1 고객 화면(my-orders.html)이 값에 따라 다른"
                          " 안내 문장을 보여줍니다. 처리 모듈(admin_refunds.py)은 \"문구 분기,"
                          " 전이 동일\"이라고 스스로 명시합니다. 적용 대상은 자체 결제로 만들어진"
                          " 과거 주문 20건뿐입니다."),
        "verdict_src": "api/my_orders.py L73·L107 · mockups/mvp1/my-orders.html L146-149 · admin_refunds.py docstring L6",
        "need": "",
        "own_label": "자체 환불", "own_desc": "수거 접수·PG 환불 예약으로 문구가 바뀝니다",
        "mall_label": "쇼핑몰 환불", "mall_desc": "쇼핑몰 인계 처리 기록으로 문구가 바뀝니다",
        "effect_match": ["환불 접수"],
    },
    "settle": {
        "name": "정산", "stage": "mvp3", "verdict": "dormant",
        "summary": "서버가 결제(pay)와 같은 값으로 강제 보정합니다 — 따로 고를 수 없습니다.",
        "verdict_title": "잠듦 — 축은 살아 있지만 이 단계에서 쓰지 않습니다",
        "verdict_desc": ("_enforce()가 pay와 항상 같도록 붙잡습니다. 정산 마감 기능"
                          "(admin_payments.py)은 이미 있지만 이 값이 아니라 payments.pay_mode를"
                          " 승계해 자기 모드를 정합니다."),
        "verdict_src": "admin_ops.py L52-54 · admin_payments.py L11 주석",
        "need": "admin_payments.py의 정산 마감이 payments.pay_mode 대신(또는 함께) ops_settings.settle을 읽도록 연결돼야 합니다.",
        "own_label": "자체 정산", "own_desc": "정산을 우리가 계산합니다",
        "mall_label": "쇼핑몰 정산", "mall_desc": "정산은 팝콘PC 쪽에서 처리합니다",
        "effect_match": ["정산 마감"],
    },
    "ship": {
        "name": "배송", "stage": "mvp2", "verdict": "missing",
        "summary": "값은 저장되지만 읽어서 처리를 가르는 코드가 없습니다.",
        "verdict_title": "미구현 — 스위치는 있는데 읽는 코드가 아직 없습니다",
        "verdict_desc": ("admin_orders.py가 주문 스냅샷의 ship 값을 shipments.ship_mode에"
                          " 저장하기는 하지만, 그 컬럼을 읽어 배송 처리를 분기하는 코드가"
                          " 0건입니다. 배송사는 CJ대한통운으로 항상 고정돼 있습니다."),
        "verdict_src": "api/admin_orders.py L181-185(저장만) · 소비 코드 0건",
        "need": "배송 처리 코드가 shipments.ship_mode를 읽어 자체/인계를 분기해야 합니다. 배송사 고정값도 함께 풀려야 합니다.",
        "own_label": "자체 배송", "own_desc": "배송 상태를 우리가 관리합니다",
        "mall_label": "쇼핑몰 배송", "mall_desc": "배송은 팝콘PC 쪽에서 관리합니다",
        "effect_match": ["배송 추적"],
    },
    "member": {
        "name": "회원·가입", "stage": "mvp2", "verdict": "missing",
        "summary": "응답에 값을 실어 보낼 뿐 매핑 동작을 바꾸지 않습니다.",
        "verdict_title": "미구현 — 유일한 소비처가 동결된 구 화면입니다",
        "verdict_desc": ("admin_members.py가 값을 읽어 member_mode로 응답에 싣지만, 매핑 요청은"
                          " 운영 모드와 무관하게 허용된다고 모듈 자신이 명시합니다. 그 값을"
                          " 실제로 쓰는 곳은 동결된 구 admin 화면(customers.html)뿐입니다."),
        "verdict_src": "api/admin_members.py L66·L98 · mockups/admin/customers.html L291(P-09 동결)",
        "need": "회원 매핑·가입 흐름이 이 값을 읽어 자체/쇼핑몰 경로를 가르도록 구현돼야 합니다.",
        "own_label": "자체 회원", "own_desc": "회원을 우리가 관리합니다",
        "mall_label": "쇼핑몰 회원", "mall_desc": "회원은 팝콘PC 계정을 씁니다",
        "effect_match": ["가입 흐름"],
    },
}

# 구축 축 26개 미구축 항목의 단계는 요구사항 정의서 자신도 "미정"으로 남겼다
# (결정이 필요한 지점 7·8). 여기서는 그 문서가 "정황상 대응 · 확정 아님"으로 적은
# 항목만 옮긴다 — 숫자(5·4·4)는 `api/admin_nav.py` 모듈 docstring L17의 실제 주석
# ("뺐다 (22) 주문 5 · 클레임 4 · 배송·판매 설정 4 · 매출·세무 4 · 고객 4 · 재고 입고 1")을
# 그대로 옮긴 것이다 — 이 항목들은 2026-08-11 IA 축소로 지금 NAV에 아예 없다(37항목
# 안에 포함되지 않는다).
HINTS_BY_STAGE = {
    "mvp1": [],
    "mvp2": [
        {"name": "주문 관리 5항목",
         "desc": ("A-34 본문의 \"주문\"에 대응하는 것으로 읽힙니다 — 2026-08-11에 IA에서"
                   " 빠진 22항목 안에 있고 지금 admin_nav.py에는 항목 자체가 없습니다.")},
        {"name": "클레임(환불·취소) 4항목",
         "desc": "같은 근거로 \"취소\"에 대응하는 것으로 읽힙니다. 확정이 아니라 정황상 대응입니다."},
    ],
    "mvp3": [
        {"name": "매출 · 세무 4항목",
         "desc": "UX-34의 \"수수료\"가 가리키는 옛 정산 그룹으로 읽힙니다 — 역시 admin_nav.py 밖이고 확정이 아닙니다."},
    ],
}


def _self_built() -> bool:
    """"오픈 단계 설정" 항목이 지금 admin_nav.NAV에서 구축됨으로 잡히는가 — 실측."""
    for _title, _icon, items in NAV:
        for label, href, _note in items:
            if label == "오픈 단계 설정":
                return bool(href)
    return False


@router.get("/ops-settings", response_class=HTMLResponse)
def ops_stage(request: Request) -> HTMLResponse:
    """오픈 단계 설정(ADM-OPS-010).

    전환 축 5종(모드·갱신 시각·이력·프리셋·서버측 예상 영향)은 화면이 브라우저에서
    `GET/POST /api/admin/ops-settings`를 직접 불러 그린다 — 이 라우트는 페이지 뼈대와
    정적 판정 스냅샷(AXIS_META)만 내려준다.
    """
    return render(
        request, "admin/ops_stage.html.j2",
        screen_id="ADM-OPS-010", domain="ops_stage",
        crumb_group="시스템", crumb_now="오픈 단계 설정",
        axis_meta_json=json.dumps(AXIS_META, ensure_ascii=False),
        stage_label_json=json.dumps(STAGE_LABEL, ensure_ascii=False),
        hints_by_stage=HINTS_BY_STAGE,
        verdict_at=VERDICT_AT, verdict_source=VERDICT_SOURCE,
        self_built=_self_built(),
    )
