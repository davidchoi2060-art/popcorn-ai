"""판매가 재산정 (ADM-PRC-050) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

계약: `docs/design/spec-reprice.md`(사장님 확정 **1a안** — 회차 표 -> 범위 -> 미리보기 ->
실행이 한 줄기로 내려온다. 위험 갈래는 우측). 정의서: `docs/design/req/req-reprice.md`.
원문(Claude Design)은 하네스만 연다 — 이 화면은 계약 요약 텍스트로 지었다.

■★★ 화면의 «축»이 바뀌었다 — 사장님이 빼기로 확정한 것 (계약 §맨 앞에 무엇을 둘까)
  디자인 원안은 "지난 재산정 99.99%가 되돌려졌다 — 세 번째도 같아지지 않게"라는 붉은
  경고를 맨 앞에 세웠는데, 조사자 실측(2026-08-15)이 그 전제를 뒤집었다:
      회차 1  apply 2026-08-04 14:22:02.300119 -> undo 14:23:03.795455  간격 61.50초
              note "슬라이스 E 검증"
      회차 2  apply 2026-08-05 14:50:28.210853 -> undo 14:51:35.827765  간격 67.62초
              note "점검 반영"
  둘 다 **검증 작업**이었다(사고가 아니다) — 사유가 없는 게 아니라 note에 이미 적혀
  있었다. 그래서 경고 배너 대신 「지난 회차」 표를 맨 앞에 둔다 — note 열과 되돌림까지의
  간격이 "이건 검증이었다"를 스스로 말한다. 「99.99%」도 부정확했다 — 안 되돌려진 것처럼
  보인 2건은 「가격 검토 대기」(price_review_decide)가 만든 별개 행이다(reason 문자열
  공유 — ref_id로만 구분됨, 이 화면 소관 밖).

■ 회차 원장은 전용 표가 없다 — admin_operator_activity_logs가 원천이다(계약 §실측이
  채운 것 — 62개 base table 전수 확인 결과). action='판매가 재산정'(apply) /
  '판매가 재산정 되돌림'(undo) 로그를 되돌림의 detail->>'ref_log_id'로 짝짓는다(undo가
  받는 키와 동일). **화면 라우트가 렌더 시점에 계산한다**(admin_ui_margin_policy.
  _history_summary() · admin_ui_swap_click_logs._policy_links() 선례를 따른다 — 쓰기는
  전혀 없다). product_price_history.changed_at으로 «추정»하지 않는다 — 활동 로그가
  정본이다(둘이 마이크로초까지 일치함을 조사자가 확인했다 — 추정이 필요 없다).

■ 쓰기는 이미 있는 API 세 종만 쓴다(새로 만들지 않았다 — **`api/admin_reprice.py`는
  손대지 않는다**) — 화면은 호출만 한다:
    GET  /api/admin/reprice/preview?scope=   영향 계산 — **저장된 정책으로 실제 계산**한다
                                              (마진 정책 화면의 미리보기와 달리 이건 진짜다)
    POST /api/admin/reprice/apply            실행 · owner만. body: scope·expect_changed
                                              (직전 preview 응답 값을 그대로 재전송 — 화면이
                                              따로 고르게 하지 않는다) · note(선택)
    POST /api/admin/reprice/undo             되돌림 · owner만. body: log_id 하나로 그 회차
                                              전체를 되돌린다 · 이중 되돌림은 409

■ 상한(MAX_APPLY=20,000) 초과는 **거부가 아니다** — 앞 20,000건만 반영하고 apply 응답의
  `dropped`로 알린다(HTTP 200). 비교 대상은 `target`이 아니라 **`changed`(오름+내림)**다 —
  지금은 live 7,174 · selling 7,269 · all 18,425로 셋 다 상한 미만이라 실제로 걸리지
  않지만, 값을 하드코딩하지 않고 매 미리보기 응답의 `max_apply`·`changed`로 화면이 직접
  판단해 넘으면 실행 전에 미리 알린다.

■ 이 화면 전용 읽기 전용 보강 값 — 렌더 시점에 계산해 템플릿에 얹는다(쓰기 없음):
    _rounds()        위 회차 원장 복원. 최근 N건(기본 50)만 반환한다 — 재산정은 드문
                      운영이라 무제한 반환의 위험이 실질적으로 없지만 상한은 그래도 둔다.
    _screen_links()   이 화면이 잇는 곳을 **경로**로만 판정한다(라벨 금지 —
                      admin_ui_swap_click_logs.py가 라벨 조회로 겪은 사고의 재발 방지,
                      admin_ui_margin_policy.py와 같은 근거). admin_nav.NAV는 읽기만 한다.
                      실측(2026-08-15, 이 제작자): 대상 4곳 전부 admin_nav.py에 href가
                      아직 없다("마진 정책"은 라벨조차 NAV에 없고, 나머지 셋은 라우트
                      파일은 있지만 href가 None) — 그래서 지금은 4곳 다 비활성으로 보이는
                      것이 맞다(화면 결함 아님, T-02 조건 — href 연결은 검증 통과 후).

■ 판단한 것(계약이 명시하지 않아 이 제작자가 정함, 검증 대상):
    · 범위 라디오 3개의 캡션("판매중 · 재고 있음"·"판매중 전체"·"전체")은
      `admin_reprice.SCOPES`의 값을 그대로 옮겨 적었다(닫힌 3종 상수 — 코드에서 실측 확인,
      바뀌면 이 화면도 갱신해야 한다). 서버가 미리보기 응답으로 주는 `scope_label`은
      **미리본 그 범위 하나에만** 붙어 있어, 아직 미리보지 않은 나머지 두 라디오의 캡션을
      서버에서 미리 받을 방법이 없다 — margin_policy.html.j2도 같은 이유로 같은 문자열을
      이미 하드코딩해 썼다(그 파일 579·606행, 선례 확인).
    · 「단가표 일일 반영」(ADM-PRC-040)은 `_screen_links()`에 넣지 않았다 — 나머지
      넷과 달리 **admin2 라우트 자체가 아직 없다**(`admin_ui_price_import.py` 없음,
      구 화면 `/admin/price-import.html`만 존재). 없는 경로를 넣으면 언젠가 admin_nav.py가
      다른 문자열로 그 화면을 연결해도 이 화면은 영영 못 알아챈다 — 화면 안내 문구로만
      고정 노출한다(계약 §⑨ 크로스 레퍼런스, 링크 아님).
    · 회차 표의 "되돌리기"는 두 번 눌러야 실행된다(1차 클릭 = 확인 문구로 전환, 2차 클릭
      = 실행) — 네이티브 `confirm()` 창 대신 인앱 확인(margin_policy 서랍의 삭제 확인과
      같은 결 — 그 파일도 네이티브 confirm을 쓰지 않는다).
    · 실행·되돌리기 성공 후 페이지를 새로고침한다(`location.reload()`) — 회차 목록은
      별도 JSON API가 없고 "화면 라우트가 렌더 시점에 계산"하는 값이므로, 최신 상태를
      반영하는 가장 정직한 방법은 그 시점을 다시 만드는 것이다(부분 갱신은 서버 계산
      로직을 클라이언트가 흉내 내야 해 값이 갈릴 위험이 있다).
    · 미리보기의 `examples`(상위 6건씩 — up/down/outlier/negative/locked)를 화면에
      노출한다 — 서버가 이미 계산해 주는 값이고, "이상치 206건"처럼 총 건수만 보면
      무엇이 바뀌는지 알 수 없다(계약 §⑤ "총 건수만 보면 안 보인다" 근거 그대로).

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
from .timeutil import iso

router = APIRouter(prefix="/admin2", tags=["admin-ui"])

ROUND_LIMIT = 50  # 최근 N회차만 낸다 — 재산정은 드문 운영이라 실질적 제약은 아니다(§docstring)

# 이 화면이 잇는 곳 — **경로**로만 판정한다(라벨 금지). "단가표 일일 반영"은 admin2
# 라우트 자체가 없어 여기 넣지 않는다(§docstring "판단한 것").
LINK_TARGETS = {
    "margin_policy": {"label": "마진 정책", "path": "/admin2/margin-policy"},
    "price_review": {"label": "가격 검토 대기", "path": "/admin2/price-review"},
    "sale_price": {"label": "판매가 관리", "path": "/admin2/sale-price"},
    "price_history": {"label": "가격 이력", "path": "/admin2/price-history"},
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


def _detail(row) -> dict:
    d = row["detail"]
    if isinstance(d, dict):
        return d
    return json.loads(d) if d else {}


def _rounds(conn, limit: int = ROUND_LIMIT) -> list:
    """지난 재산정 회차 — 전용 표가 없어 admin_operator_activity_logs가 원천이다(위 모듈
    docstring 근거). action='판매가 재산정'(apply)과 '판매가 재산정 되돌림'(undo)을
    되돌림의 detail->>'ref_log_id'로 짝짓는다. before(상품별 이전 값 배열 — 수천 건일
    수 있다)는 응답에 싣지 않는다 — 이 화면은 "언제·누가·몇 건·왜·되돌렸나"만 보여준다."""
    rows = conn.execute(text(
        "SELECT l.log_id, l.action, l.detail, l.created_at,"
        "       COALESCE(o.name, '—') AS operator"
        "  FROM admin_operator_activity_logs l"
        "  LEFT JOIN admin_operators o USING (operator_id)"
        " WHERE l.action IN ('판매가 재산정', '판매가 재산정 되돌림')"
        " ORDER BY l.log_id ASC")).mappings().all()

    applies: list = []
    undo_by_ref: dict = {}
    for r in rows:
        d = _detail(r)
        if r["action"] == "판매가 재산정":
            applies.append((r, d))
        else:  # 판매가 재산정 되돌림
            ref = d.get("ref_log_id")
            if ref is not None:
                undo_by_ref[int(ref)] = (r, d)

    out = []
    for i, (r, d) in enumerate(applies, start=1):
        pair = undo_by_ref.get(r["log_id"])
        undo_r, undo_d = pair if pair else (None, None)
        interval = None
        if undo_r is not None:
            interval = (undo_r["created_at"] - r["created_at"]).total_seconds()
        out.append({
            "round_no": i,
            "log_id": r["log_id"],
            "at": iso(r["created_at"]),
            "operator": r["operator"],
            "scope": d.get("scope"),
            "scope_label": d.get("scope_label") or d.get("scope") or "—",
            "changed": d.get("changed"),
            "up": d.get("up"),
            "down": d.get("down"),
            "margin_rate": d.get("margin_rate"),
            "card_fee_rate": d.get("card_fee_rate"),
            # 분류별 예외가 섞여 있었으면 단일 margin_rate로는 그 회차를 온전히 설명하지
            # 못한다(지금은 category_margin_policies가 0건이라 관측되지 않지만, 화면은
            # 나중에 예외가 생겨도 정직해야 한다) — 회차 표가 "분류마다 다름"을 밝힌다.
            "margins_used": d.get("margins_used") or {},
            "note": (d.get("note") or "").strip(),
            "undone": undo_r is not None,
            "undo_at": iso(undo_r["created_at"]) if undo_r is not None else None,
            "undo_operator": undo_r["operator"] if undo_r is not None else None,
            "interval_seconds": interval,
            "restored": undo_d.get("restored") if undo_d else None,
        })
    out.reverse()  # 최근 회차가 위로
    return out[:limit]


@router.get("/reprice", response_class=HTMLResponse)
def reprice(request: Request) -> HTMLResponse:
    with engine.connect() as conn:
        rounds = _rounds(conn)
    return render(request, "admin/reprice.html.j2",
                  screen_id="ADM-PRC-050", domain="reprice",
                  crumb_group="판매가", crumb_now="판매가 재산정",
                  links_json=json.dumps(_screen_links(), ensure_ascii=False),
                  rounds_json=json.dumps(rounds, ensure_ascii=False))
