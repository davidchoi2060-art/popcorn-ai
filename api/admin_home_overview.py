"""신 관리자 첫 화면 「운영 현황」(ADM-DASH-020) — 데이터 모으기. **router 를 갖지 않는다.**

기획 원천: 코덱스 「관리자 대시보드 기획안 v1」(2026-10-12, 공유 폴더
`2026-10-12-1812-관리자대시보드-기획안-v1.md`). 사장님이 2026-10-12 「추천한대로 하자」로
확정 — 대시보드를 **신 관리자 첫 화면**으로 둔다. 구 관리자 모드의 `/admin2/`(1b 카드형,
`admin_ui_home.py`)는 그대로 남는다.

■ 원칙(기획안 §2·§4 그대로)
  · 숫자는 서버 원천에서만 온다. 원천이 없거나 정의가 확정되지 않은 카드는 숫자를 비우고
    「아직 집계가 연결되지 않았습니다」라고 쓴다 — 0 을 쓰지 않는다(0 은 사실 주장이다).
  · 조회 실패 · 집계 미연결 · 정상 0건은 서로 다른 상태다(`state`: ok · zero · error · none).
  · 처리 대기 카드들을 더한 「총 할 일」을 만들지 않는다 — 같은 상품이 여러 카드에 걸린다.
  · 매출 · 금액 카드는 없다. 결제·정산 기록은 「자료 바로가기」의 링크 하나뿐이다.
  · 카드를 누르면 같은 조건의 기존 업무 목록으로 간다. 링크에 `from=overview` 를 붙여
    그 화면 위에 「운영 현황으로 돌아가기」 줄이 나온다(`admin_ui_common.render`).

■ 각 카드의 원천 — 새 집계를 지어내지 않고 각 업무 화면이 이미 쓰는 기준을 그대로 쓴다.
    쇼핑몰 가격 확인 기록   admin_mall_price.auto_status()   (자동 갱신 하루 2회 · 마지막 1회)
    재고 기록 정합          admin_dashboard.quote_quality()  stock_drift
    상담 처리 대기          purchase_inquiries 「대기」 (구매 상담 신청 화면과 같은 시험 제외)
    후기 검토               member_reviews 「신고됨」 (후기 관리 화면의 「신고 처리 대기」와 같은 기준)
    해석 규칙 검토          talk_intents 「대기」 (팝콘톡 응답 패턴 화면의 상태값)
    상품 사양 검수 · 가격 검토 대기 · 그 밖의 작업   admin_dashboard.worklist()
    공개 전 확인할 PC       admin_pc_release.list_releases() 의 release_state
    고객 이용 흐름          admin_dashboard.dashboard() flow (오늘 KST)
    최근 처리 기록          admin_operator_activity_logs 최근 10행
"""
from datetime import datetime

from sqlalchemy import text

from .db import engine
from .timeutil import KST

FROM = "overview"          # 카드 → 목록 링크에 붙는 표식. admin_ui_common.render 가 읽는다.
BACK_HREF = "/admin2/"
BACK_LABEL = "운영 현황으로 돌아가기"

NOT_CONNECTED = "아직 집계가 연결되지 않았습니다."
LOAD_FAILED = "기록을 불러오지 못했습니다. 다시 조회해 주세요."
EMPTY = "해당 조건의 기록이 없습니다."


def link(href: str | None) -> str | None:
    """업무 목록 링크에 `from=overview` 를 붙인다(이미 붙어 있으면 그대로)."""
    if not href:
        return None
    if "from=" in href:
        return href
    return href + ("&" if "?" in href else "?") + "from=" + FROM


def _safe(label: str, fn):
    try:
        return fn(), None
    except Exception as e:  # noqa: BLE001 — 한 원천이 죽어도 첫 화면 전체를 막지 않는다
        print(f"[admin_home_overview] {label} failed: {type(e).__name__}: {e}")
        return None, LOAD_FAILED


def _fmt_time(value) -> str | None:
    if not value:
        return None
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return dt.astimezone(KST).strftime("%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def card(title: str, desc: str, *, value=None, err=None, href=None, scope="", period="",
         basis=None, unit="건", connected=True, warn=False, note=None) -> dict:
    """카드 한 장. 숫자 상태를 넷으로 가른다 — ok · zero · error · none(미연결)."""
    if not connected:
        state, shown, msg = "none", "—", NOT_CONNECTED
    elif err:
        state, shown, msg = "error", "—", err
    elif value is None:
        state, shown, msg = "error", "—", LOAD_FAILED
    elif value == 0 and not warn:
        state, shown, msg = "zero", "0", EMPTY
    else:
        state, shown, msg = ("warn" if warn else "ok"), f"{value:,}", None
    return {"title": title, "desc": desc, "state": state, "value": shown, "unit": unit,
            "msg": msg, "note": note, "href": link(href), "scope": scope, "period": period,
            "basis": basis or "기준 시각 확인 필요"}


# ── 원천 조회 ──────────────────────────────────────────────────────────────

def _counts() -> dict:
    """상담 · 후기 · 해석 규칙 대기 수 — 각 업무 화면의 기준 그대로."""
    from .admin_purchase_inquiries import IS_TEST
    with engine.connect() as conn:
        inquiries = dict(conn.execute(text(
            f"SELECT i.status, COUNT(*) FROM purchase_inquiries i WHERE NOT {IS_TEST}"
            " GROUP BY i.status")).all())
        reported = conn.execute(text(
            "SELECT COUNT(*) FROM member_reviews WHERE status = '신고됨'")).scalar_one()
        rules = conn.execute(text(
            "SELECT COUNT(*) FROM talk_intents WHERE status = '대기'")).scalar_one()
    return {"inquiry_wait": int(inquiries.get("대기", 0)),
            "inquiry_doing": int(inquiries.get("처리 중", 0)),
            "reported": int(reported), "rules": int(rules)}


def _target(raw) -> str:
    """대상 칸 — 쇼핑몰 가격 반영 기록의 내부 표기(run:4 · cart)를 읽을 수 있는 말로 바꾼다."""
    if not raw:
        return "—"
    raw = str(raw)
    if raw.startswith("run:") and raw[4:].isdigit():
        return f"{raw[4:]}회차 실행"
    from .admin_mall_price import MOMENT_KO
    return MOMENT_KO.get(raw, raw)


def _recent_logs(limit: int = 10) -> list:
    from .admin_activity_logs import ACTION_LABELS, KIND_LABELS
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT l.log_id, l.action, l.target_kind, l.target_id, COALESCE(o.name, '—') AS operator,"
            " l.created_at FROM admin_operator_activity_logs l"
            " LEFT JOIN admin_operators o USING (operator_id)"
            " ORDER BY l.log_id DESC LIMIT :n"), {"n": limit}).mappings().all()
    # 화면에 내부 코드(영문)를 그대로 내지 않는다 — 이름표가 없는 동작은 「기타 처리」로 쓰고
    # 원래 코드는 title 로만 남긴다. 담당자가 없는 행은 사람이 아니라 자동 작업이 남긴 기록이다.
    return [{"at": _fmt_time(r["created_at"]) or "—",
             "kind": KIND_LABELS.get(r["target_kind"], "기타 업무"),
             "target": _target(r["target_id"]),
             "action": ACTION_LABELS.get(r["action"], "기타 처리"),
             "code": r["action"],
             "operator": r["operator"] if r["operator"] not in (None, "", "—") else "자동 작업"}
            for r in rows]


def _releases() -> dict:
    from .admin_pc_release import list_releases
    items = list_releases()["items"]
    states = [i.get("release_state") for i in items]
    return {"before": states.count("not_released"), "changed": states.count("hidden"),
            "public": states.count("public")}


# ── 화면 모델 ──────────────────────────────────────────────────────────────

def _status_section(mall, mall_err, quality, quality_err) -> dict:
    if mall is None:
        mall_card = card("쇼핑몰 가격 확인 기록", "최근 가격 확인과 반영 결과를 봅니다.",
                         err=mall_err, href="/admin2/mall-price", scope="자동 갱신", period="최근 1회")
    else:
        last = mall.get("last")
        if not last:
            mall_card = card("쇼핑몰 가격 확인 기록", "최근 가격 확인과 반영 결과를 봅니다.",
                             value=0, href="/admin2/mall-price", scope="자동 갱신 · 직접 실행",
                             period="최근 1회", unit="회")
            mall_card["msg"] = "아직 실행 기록이 없습니다."
        else:
            when = _fmt_time(last.get("started_at"))
            ok = last.get("ok")
            if ok is None:
                label, warn = "실행 중", False
            elif ok:
                label, warn = "완료", False
            else:
                label, warn = "실패", True
            mall_card = card("쇼핑몰 가격 확인 기록", "최근 가격 확인과 반영 결과를 봅니다.",
                             value=last.get("changed") or 0, href="/admin2/mall-price",
                             scope=f"{last.get('moment_label') or '자동 갱신'} · {label}",
                             period="최근 1회", basis=when, warn=warn)
            mall_card["unit"] = "건 반영"
            held = last.get("held")
            note = f"보류 {held:,}건" if held else None
            if ok is False:
                note = "실패 사유: " + (last.get("fail_reason") or "기록되지 않음")
            mall_card["note"] = note
            if mall_card["state"] == "zero":
                mall_card["msg"] = "바뀐 가격이 없습니다."
            elif warn:
                mall_card["msg"] = "실패했습니다. 기록을 확인해 주세요."
    if quality is None:
        stock_card = card("재고 기록 확인", "재고 수량과 입출고 기록이 맞지 않는 상품입니다.",
                          err=quality_err, scope="판매 상품 전체", period="지금")
    else:
        drift = quality.get("stock_drift")
        stock_card = card("재고 기록 확인", "재고 수량과 입출고 기록이 맞지 않는 상품입니다.",
                          value=drift, scope="판매 상품 전체", period="지금",
                          basis="조회 시각 기준", warn=bool(drift))
        stock_card["href"] = None
        stock_card["note"] = "품절은 여기 세지 않습니다. 목록 연결은 확인이 필요합니다."
    cards = [mall_card, stock_card]
    issues = [c for c in cards if c["state"] in ("warn", "error")]
    return {"cards": cards, "has_issue": bool(issues)}


def _work_section(counts, counts_err, wl, wl_err) -> dict:
    c = counts or {}
    inquiry = card("상담 처리 대기", "아직 처리를 시작하지 않은 구매 상담 신청입니다.",
                   value=c.get("inquiry_wait") if counts else None, err=counts_err, href="/admin2/purchase-inquiries?status=대기",
                   scope="시험 신청 제외", period="현재 전체", basis="조회 시각 기준")
    if counts:
        inquiry["note"] = f"처리 중인 신청 {c['inquiry_doing']:,}건은 따로 셉니다."
    reviews = card("후기 검토", "공개 여부를 검토할 후기입니다.",
                   value=c.get("reported") if counts else None, err=counts_err,
                   href="/admin2/member-reviews?state=신고됨",
                   scope="신고된 후기", period="현재 전체", basis="조회 시각 기준")
    rules = card("해석 규칙 검토", "시험 결과를 확인하고 사용 여부를 정할 규칙입니다.",
                 value=c.get("rules") if counts else None, err=counts_err,
                 href="/admin2/talk-patterns?status=대기",
                 scope="대기 상태 규칙", period="현재 전체", basis="조회 시각 기준")

    items = {i["key"]: i for i in (wl or {}).get("items", [])}

    def wl_card(key, title, desc, href, scope):
        src = items.get(key)
        cd = card(title, desc, value=src["count"] if src else None, err=wl_err, href=href,
                  scope=scope, period="현재 전체", basis="조회 시각 기준")
        if src and src.get("focus") is not None and src.get("focus_label"):
            cd["note"] = f"{src['focus_label']} {src['focus']:,}건 포함"
        return cd

    spec = wl_card("review", "상품 사양 검수", "확인이 필요한 상품 사양입니다.",
                   "/admin2/reviews", "검수 대기")
    price = wl_card("price", "가격 검토 대기", "확인 후 반영할 가격 기록입니다.",
                    "/admin2/price-review", "판매가 없는 상품")
    others = [wl_card("category", "상품 분류 매핑", "판매 분류가 없거나 부품 종류가 정해지지 않은 상품입니다.",
                      "/admin2/category-mapping", "분류 대기"),
              wl_card("price_import", "단가표 반영", "아직 다 반영하지 않은 공급처 최신 단가표입니다.",
                      "/admin2/price-import", "공급처별 최신 파일"),
              wl_card("sourcing", "매입 견적", "요청한 뒤 회신을 기다리는 견적입니다.",
                      "/admin2/sourcing", "회신 대기")]
    return {"cards": [inquiry, reviews, rules, spec, price], "others": others}


def _release_section(rel, rel_err) -> dict:
    before = card("공개 전 확인할 PC", "고객에게 공개하기 전에 확인할 PC입니다.",
                  value=rel["before"] if rel else None, err=rel_err, href="/admin2/pc-builder",
                  scope="신규 조립PC 생성에서 만든 제품군", period="현재 전체", basis="조회 시각 기준")
    if rel:
        notes = []
        if rel["changed"]:
            notes.append(f"공개 뒤 구성이 바뀌어 다시 확인할 PC {rel['changed']:,}대")
        notes.append(f"공개 중 {rel['public']:,}대")
        before["note"] = " · ".join(notes)
        before["unit"] = "대"
    attach = card("구성표 연결 확인", "PC에 연결된 구성표를 확인합니다.",
                  connected=False, href="/admin2/pc-configurations",
                  scope="조립PC 제품군", period="현재 전체")
    return {"cards": [before, attach]}


def _flow_section(dash, dash_err) -> dict:
    flow = (dash or {}).get("flow") or {}
    period = "오늘(한국 시각)"
    scope = "모든 고객 화면"
    rows = []

    def row(label, value, href, note=None, connected=True):
        cd = card(label, "", value=value, err=dash_err, href=href, scope=scope, period=period,
                  connected=connected)
        cd["note"] = note
        rows.append(cd)

    row("상담 기록", flow.get("sessions_today") if dash else None, "/admin2/consult-sessions",
        note=flow.get("sessions_scope_note"))
    row("견적 기록", flow.get("sessions_done") if dash else None, "/admin2/consult-sessions",
        note="견적까지 만든 상담입니다. 구매 건수가 아닙니다.")
    row("고객 문의", flow.get("mvp3_inquiries_today") if dash else None, "/admin2/mvp3-consults",
        note="지금 고객 화면과 같은 상담 경로를 쓰는 다른 고객 화면의 문의가 함께 들어 있습니다. 시험 문의는 뺐습니다.")
    row("쇼핑몰 인계", None, "/admin2/handoff-log", connected=False)
    return {"rows": rows, "period": period, "scope": scope}


def _shortcuts() -> list:
    """자료 바로가기 — 신 관리자에서 숨겨 둔 옛 화면 셋과 기록 화면.

    「숨겨 둔 옛 화면 셋」은 코드로 확인했다: `admin_ui_new.settings()` 의 hidden 집합과
    `docs/design/admin-new-transition-20261002.md` 대응표가 「화면 폐기 후보」로 적은
    조립 호환 지도 · 상품 매트릭스 관리 · 용도별 상품 매트릭스다. 화면은 지우지 않고 여기서 연다.
    """
    return [
        {"label": "조립 호환 지도", "href": link("/admin2/build-map"),
         "desc": "부품 사이 호환 관계를 한 장으로 봅니다."},
        {"label": "상품 매트릭스", "href": link("/admin2/grid"),
         "desc": "미리 만든 견적 격자를 봅니다."},
        {"label": "용도별 상품 매트릭스", "href": link("/admin2/game-matrix"),
         "desc": "게임·AI 작업별로 성립하는 격자 칸을 봅니다."},
        {"label": "결제·정산 기록", "href": link("/admin2/payment-records"),
         "desc": "기관에서 확인한 거래를 기록합니다."},
        {"label": "보관 기한 정리 기록", "href": None,
         "desc": "연결 확인 필요"},
    ]


def build() -> dict:
    """첫 화면 전체 모델. 원천마다 따로 조회하고 실패는 그 칸에만 표시한다."""
    from .admin_dashboard import dashboard, quote_quality, worklist
    from .admin_mall_price import auto_status

    mall, mall_err = _safe("mall price auto", auto_status)
    quality, quality_err = _safe("quote quality", quote_quality)
    counts, counts_err = _safe("pending counts", _counts)
    wl, wl_err = _safe("worklist", worklist)
    rel, rel_err = _safe("pc releases", _releases)
    dash, dash_err = _safe("dashboard flow", dashboard)
    logs, logs_err = _safe("recent logs", _recent_logs)

    return {
        "loaded_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "status": _status_section(mall, mall_err, quality, quality_err),
        "work": _work_section(counts, counts_err, wl, wl_err),
        "release": _release_section(rel, rel_err),
        "flow": _flow_section(dash, dash_err),
        "logs": logs or [],
        "logs_err": logs_err,
        "logs_href": link("/admin2/activity-logs"),
        "shortcuts": _shortcuts(),
    }
