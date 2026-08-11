"""운영자 좌측 메뉴(LNB) — **새 IA 의 단일 원천** (UX-14 · 2026-08-09).

전체 화면 표와 판정 근거는 `docs/design/admin-ia-draft-2026-08-09.md` 가 원천이고,
**여기는 그 표를 코드로 옮긴 것**이다. 둘이 어긋나면 문서가 맞다.

■ 왜 JS 가 아니라 Python 인가
  기존 시스템은 `mockups/shared/admin-menu-data.js` 를 브라우저가 읽어 런타임에 그린다.
  그 방식은 "그리는 시점"이 어긋나 아이콘이 안 붙는 사고를 냈고, 무엇보다 **화면이
  서버 렌더가 되면 메뉴만 클라이언트에 남을 이유가 없다.** 레이아웃이 서버에서 한 벌로
  그리면 그리는 시점 문제가 구조적으로 사라진다.
  → 새 레이아웃은 `admin-menu.js` 를 로드하지 않는다. 로드하면 이 메뉴를 덮어쓴다.

■ `new` / `old` 두 주소를 갖는 이유 — LNB 가 첫날부터 쓸모 있게
  52화면 중 지금 재구축된 것은 둘뿐이다(대시보드·상품 관리). 나머지를 죽은 링크로 두면
  새 메뉴는 구경거리일 뿐이다. 그래서 항목마다:

      new  재구축된 화면 경로(`/admin2/...`)   — 있으면 이걸 쓴다
      old  기존 화면 경로(`/admin/*.html`)     — 아직 안 지었으면 이걸 쓴다
      (둘 다 없으면) 신설 예정 — 링크 없이 '준비 중'으로 표시

  **새 구조로 기존 화면을 쓰다가, 화면이 하나씩 서면 링크가 옮겨간다.**
  기존 37화면은 그대로 살아 있으므로(병행 신축) 이게 가능하다.

■ 이름은 문서를 따른다
  「상품 매핑」→ 상품 분류 매핑, 「사양 항목 정의」→ 상품 사양 정의,
  「상품 검수」→ 상품 사양 검수, 「용도 하한」→ 용도별 최소 사양,
  「부품 등급판」→ 부품 등급 관리. 테이블·API 식별자는 안 바꾼다 — 화면 라벨만이다.

■ 숫자 배지를 여기 담지 않는다
  기존 메뉴가 '상품 검수 9' 같은 수를 마크업에 박아 두었다가 실제(5,162)와 어긋났고,
  `clearDummyBadges()` 가 로드마다 지우고 있었다. 정본에 담으면 **거짓을 원천에 새기는
  것**이다. 실수치가 필요하면 서버 응답으로 채운다.
"""

# 그룹: (제목, 아이콘, [항목])
# 항목: (라벨, new, old, 비고)  — new/old 가 None 이면 없음
NAV = [
    ("대시보드", "pie-chart", [
        ("대시보드", "/admin2/", "/admin/index.html", None),
    ]),

    ("상품관리", "box", [
        ("상품 분류 관리", None, "/admin/categories.html", None),
        ("상품 관리", "/admin2/products", "/admin/products.html", None),
        ("상품 분류 매핑", None, "/admin/category-mapping.html", None),
        ("상품 일괄 등록", None, "/admin/csv-upload.html", "이력·오류건 통합 예정"),
        ("삭제 상품 조회", None, None, "신설"),
    ]),

    # 도매꾹에 대응물이 통째로 없는 축. 파는 일이 아니라 **추천되게 하는 일**이다.
    ("상품사양관리", "sliders", [
        ("조립 호환 지도", "/admin2/build-map", None, "신설 · 관계 22쌍 한 장"),
        ("조립 사양 표준", "/admin2/spec-standard", None, "신설 · 사람이 항목을 늘린다"),
        ("상품 사양 정의", None, "/admin/spec-fields.html", None),
        ("상품 사양 검수", None, "/admin/review-queue.html", None),
        ("조립 호환 규칙", None, "/admin/compat-rules.html", None),
        ("용도별 최소 사양", None, "/admin/usage-floors.html", None),
        ("부품 등급 관리", None, "/admin/grade-board.html", None),
        ("추천 기준 설정", None, "/admin/policy-weights.html", None),
        ("추천 가능 재고 현황", None, "/admin/candidate-pool.html", None),
        ("견적 상담 기록", None, "/admin/sessions.html", None),
        ("부품 교체 · 클릭 기록", None, "/admin/swap-logs.html", None),
    ]),

    # 도매꾹은 공급사라 **살 일이 없다** — 이 축도 우리 것이다.
    ("매입 · 재고", "truck", [
        ("공급처", None, "/admin/suppliers.html", None),
        ("매입 견적(용산)", None, "/admin/sourcing.html", None),
        ("단가표 반영", None, "/admin/price-import.html", None),
        ("재고 입고", None, "/admin/stock-inbound.html", None),
    ]),

    ("판매가", "dollar-sign", [
        ("판매가 관리", None, "/admin/margin-policy.html", "재산정 통합 예정"),
        ("가격 검토 대기", None, "/admin/price-review.html", None),
        ("가격 이력", None, "/admin/price-history.html", None),
    ]),

    # 도매꾹처럼 단계별로 가른다 — 그 단계에 필요한 열만 준다.
    # 아직 한 화면(orders.html)이라 다섯이 같은 곳을 가리킨다.
    ("주문", "send", [
        ("전체 주문", None, "/admin/orders.html", None),
        ("결제 대기", None, "/admin/orders.html", "분할 예정"),
        ("발주 · 발송", None, "/admin/orders.html", "분할 예정"),
        ("배송 현황", None, "/admin/shipping.html", None),
        ("구매 확정", None, "/admin/orders.html", "분할 예정"),
    ]),

    # 이탈 흐름은 정상 흐름과 **그룹부터** 가른다.
    ("클레임", "corner-up-left", [
        ("취소 요청", None, "/admin/refunds.html", "분할 예정"),
        ("취소", None, "/admin/refunds.html", "분할 예정"),
        ("반품", None, "/admin/refunds.html", "분할 예정"),
        ("교환", None, "/admin/refunds.html", "분할 예정"),
    ]),

    # 도매꾹의 「정산」이 아니다 — 우리는 플랫폼이자 판매자라 정산받을 상대가 없다.
    ("매출 · 세무", "trending-up", [
        ("매출 집계", None, "/admin/payments.html", None),
        ("수익 분석", None, None, "신설 — 원가·마진·실수익"),
        ("세금계산서", None, None, "신설"),
        ("부가세 신고자료", None, None, "신설"),
    ]),

    ("고객", "users", [
        ("회원 관리", None, "/admin/customers.html", None),
        ("문의 관리", None, None, "신설 — 테이블도 없다"),
        ("후기 관리", None, "/admin/reviews.html", None),
        ("구매제한 ID", None, None, "신설"),
    ]),

    ("배송 · 판매 설정", "settings", [
        ("출고지 · 반품지", None, None, "신설"),
        ("추가 배송비", None, None, "신설"),
        ("휴무 기간", None, None, "신설"),
        ("상품 공지", None, None, "신설"),
    ]),

    ("AI 관리", "cpu", [
        ("AI 작업 설정", None, None, "신설 — 작업↔모델 · 폴백"),
        ("AI 연동 설정", None, None, "신설 — 키는 서버 env"),
        ("AI 사용량 · 비용", None, "/admin/ai-cost.html", None),
        ("AI 응답 기록", None, None, "신설"),
        ("운영 도우미 설정", None, None, "신설 — 처음엔 조회 전용"),
    ]),

    ("시스템", "server", [
        ("운영 전환 설정", None, "/admin/ops-settings.html", None),
        ("운영자 · 권한", None, "/admin/operators.html", None),
        ("작업 기록", None, "/admin/activity-logs.html", None),
        ("엑셀 다운로드 관리", None, None, "신설 — 비동기 큐"),
    ]),
]


def nav_for(current_path: str = "") -> list:
    """템플릿이 쓰기 좋은 형태로 편다.

    `state` 세 가지 — 화면이 어디까지 왔는지를 메뉴가 정직하게 말한다:
      new   재구축 완료. `/admin2/` 로 간다. **링크는 이것만 붙는다**
      old   기존 화면(`/admin/*.html`)은 있으나 재구축 전. 링크 없음
      todo  아무 데도 없다. 링크 없음

    ■ 기존 화면으로 링크하지 않는다 (사용자 결정 2026-08-11)
      전에는 `href = new or old` 였다. 재구축된 화면이 둘뿐일 때 나머지를 죽은 링크로
      두면 새 메뉴가 구경거리가 되니, 기존 37화면으로 이어 두자는 판단이었다.

      **뒤집는다.** 사용자 지시: *"확정된 화면만 링크를 붙이되, admin2 로 모두 붙여
      나갑시다."* 새 메뉴가 옛 시스템으로 데려가면 **어디까지 지었는지가 흐려진다** —
      운영자는 자기가 신·구 어느 쪽에 있는지 모른 채 일하게 된다. 지금 이 프로젝트가
      고치고 있는 병이 바로 그것(화면이 사실을 흐리는 것)이다.

      `old` 정보는 지운 게 아니라 **`state` 로 남긴다.** 「기존 화면은 있다」와
      「아무 데도 없다」는 다른 사실이고, 재구축 순서를 정할 때 그 차이가 근거가 된다.
      기존 화면은 계속 `/admin/*.html` 에서 직접 열 수 있다(병행 신축).
    """
    out = []
    for title, icon, items in NAV:
        rows = []
        for label, new, old, note in items:
            href = new           # `old` 로는 잇지 않는다 — 위 결정
            state = "new" if new else ("old" if old else "todo")
            rows.append({
                "label": label, "href": href, "state": state, "note": note,
                "active": bool(href) and current_path.rstrip("/") == href.rstrip("/"),
            })
        out.append({
            "title": title, "icon": icon, "items": rows,
            "done": sum(1 for r in rows if r["state"] == "new"),
            "total": len(rows),
            "active": any(r["active"] for r in rows),
        })
    return out


def counts() -> dict:
    """진척 — 화면이 지어내지 않게 여기서 센다."""
    total = sum(len(i) for _t, _ic, i in NAV)
    new = sum(1 for _t, _ic, items in NAV for _l, n, _o, _nt in items if n)
    old = sum(1 for _t, _ic, items in NAV for _l, n, o, _nt in items if not n and o)
    return {"groups": len(NAV), "total": total, "new": new,
            "old": old, "todo": total - new - old}
