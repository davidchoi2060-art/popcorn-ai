"""운영 시작 체크리스트 — 절차를 문서에서 화면으로 (슬라이스 94).

배경: 빈 상태에서 첫 견적까지의 순서는 `docs/07_운영-시작-순서.md`에 잘 적혀 있다.
문제는 **그게 문서에만 있다는 것**이다. 운영자는 로그인하면 대시보드에 도착하는데,
아무것도 없는 상태에서 무엇부터 해야 하는지 화면이 말해 주지 않았다. 271줄짜리 문서를
따로 읽고 10단계를 외워야 했고, 단계마다 다른 메뉴 그룹으로 점프해야 했다.

슬라이스 93에서 그 대가를 봤다 — 3단계(공급처)가 **실행 자체가 불가능**한 상태로
오래 있었는데 아무도 몰랐다. 문서에만 있으면 그 문서가 틀려도 화면이 알려주지 않는다.

■ 판정은 전부 실데이터로 한다
화면이 "몇 단계까지 됐다"를 스스로 세지 않는다. 각 단계의 완료 여부와 수치는 서버가
DB에서 직접 구한다(화면 정직성 원칙). 그래서 **문서가 낡아도 이 화면은 낡지 않는다.**

■ 슬롯은 엔진과 같은 정의로 센다
`recommend.SLOTS`/`SLOT_TYPES`를 그대로 import한다. part_type으로 세면 쿨러가 갈려
(공랭·수냉이 한 슬롯인데 둘로 세어) AIO가 0인 것을 빈 슬롯으로 오판한다.

■ '다음 할 일'은 하나만 말한다
여덟 개를 나열하면 어디부터인지 여전히 모른다. 미완료 중 **첫 단계 하나**를 지목한다.
"""
from fastapi import APIRouter
from sqlalchemy import text

from .db import engine
from .recommend import SLOTS, SLOT_TYPES
from .taxonomy import SLOT_LABELS as SLOT_KO   # 단일 원천(슬라이스 A)

router = APIRouter(prefix="/api/admin")



def _slot_counts(conn) -> dict:
    """슬롯별 후보 수 — 4중 게이트를 모두 통과하고 재고가 있는 것."""
    rows = conn.execute(text(
        "SELECT part_type, COUNT(*) AS n FROM v_recommendation_candidates"
        " WHERE stock_qty > 0 GROUP BY part_type")).mappings().all()
    by_type = {r["part_type"]: r["n"] for r in rows}
    return {s: sum(by_type.get(t, 0) for t in SLOT_TYPES[s]) for s in SLOTS}


def _steps(conn) -> list:
    one = lambda sql: conn.execute(text(sql)).scalar()

    # 1 — 사람이 들어올 길. 비밀번호가 없으면 승인돼 있어도 못 들어온다(슬라이스 70).
    ops = one("SELECT COUNT(*) FROM admin_operators"
              " WHERE status = '활성' AND password_hash IS NOT NULL") or 0

    # 2 — 마진. 기본값 0%는 '정하라고 비워 둔 값'이지 결정된 값이 아니다.
    margin = one("SELECT margin_rate FROM pricing_settings"
                 " ORDER BY effective_from DESC LIMIT 1")
    fee = one("SELECT card_fee_rate FROM pricing_settings"
              " ORDER BY effective_from DESC LIMIT 1")
    margin_pct = float(margin or 0) * 100

    # 3 — 공급처. 없으면 매입가를 넣을 대상이 없다(슬라이스 93에서 만들 수단을 뚫었다).
    sup = one("SELECT COUNT(*) FROM suppliers WHERE status = '활성'") or 0

    # 4 — 상품. 추천 대상은 core_part뿐이다. 미분류는 넣어도 영원히 후보가 안 된다.
    core = one("SELECT COUNT(*) FROM products WHERE category_group = 'core_part'") or 0

    # 5 — 사양 검수. 필수 사양이 비면 게이트를 통과하지 못한다.
    reviewed = one(
        "SELECT COUNT(*) FROM products p WHERE p.category_group = 'core_part'"
        " AND NOT EXISTS (SELECT 1 FROM product_reviews r"
        "                 WHERE r.product_code = p.product_code"
        "                   AND r.review_status = '대기')") or 0
    pending = one("SELECT COUNT(*) FROM product_reviews WHERE review_status = '대기'") or 0

    # 6 — 판매가. 없으면 후보가 될 수 없다(0017에서 게이트에 들어갔다).
    priced = one("SELECT COUNT(*) FROM products WHERE category_group = 'core_part'"
                 " AND sale_price IS NOT NULL AND sale_price > 0") or 0

    # 7 — 재고. 0이면 추천에서 빠진다.
    stocked = one("SELECT COUNT(*) FROM products WHERE category_group = 'core_part'"
                  " AND stock_qty > 0 AND status = '판매중'") or 0

    # 8 — 슬롯. **하나라도 0이면 견적이 0건이다.** 총량이 아니라 고르기가 기준이다.
    slots = _slot_counts(conn)
    filled = [s for s in SLOTS if slots[s] > 0]
    empty = [s for s in SLOTS if slots[s] == 0]

    return [
        {"no": 1, "key": "operators", "title": "운영자 계정",
         "screen": "operators.html", "screen_label": "시스템 > 운영자 · 권한",
         "done": ops >= 1, "value": f"{ops}명",
         "why": "비밀번호가 발급되지 않으면 승인돼 있어도 로그인할 수 없습니다"},

        {"no": 2, "key": "margin", "title": "마진 정책",
         "screen": "margin-policy.html", "screen_label": "가격 · 매입 > 마진 정책",
         "done": margin_pct > 0,
         "value": f"마진 {margin_pct:.1f}% · 카드수수료 {float(fee or 0) * 100:.1f}%",
         "why": "마진 0%면 판매가 = 매입가라 이익이 없습니다. **상품보다 먼저** 정해야"
                " 합니다 — 나중에 바꾸면 이미 산정된 판매가를 전부 다시 계산해야 합니다"},

        {"no": 3, "key": "suppliers", "title": "공급처",
         "screen": "suppliers.html", "screen_label": "가격 · 매입 > 공급처",
         "done": sup >= 1, "value": f"{sup}곳",
         "why": "매입가는 공급처별로 기록됩니다. 없으면 매입가를 넣을 대상이 없고,"
                " 매입가가 없으면 판매가가 산정되지 않습니다"},

        {"no": 4, "key": "products", "title": "상품 등록",
         "screen": "products.html", "screen_label": "상품 > 상품 관리",
         "done": core >= 1, "value": f"부품 {core:,}건",
         "why": "분류가 '미분류'면 그 상품은 영원히 추천에 들어가지 않습니다 —"
                " 추천 대상은 부품(core_part)뿐입니다"},

        {"no": 5, "key": "specs", "title": "사양 검수",
         "screen": "review-queue.html", "screen_label": "상품 > 상품 검수",
         "done": reviewed >= 1,
         "value": f"검수 통과 {reviewed:,}건 · 대기 {pending:,}건",
         "why": "부품 종류별 필수 사양이 모두 채워져야 추천 후보가 됩니다"},

        {"no": 6, "key": "price", "title": "판매가 산정",
         "screen": "price-import.html", "screen_label": "가격 · 매입 > 단가표 반영",
         "done": priced >= 1, "value": f"{priced:,}건",
         "why": "판매가가 없으면 후보가 될 수 없습니다. 단건이면 상품 상세의"
                " [공급처별 매입가]에서 직접 넣어도 됩니다"},

        {"no": 7, "key": "stock", "title": "재고 입고",
         "screen": "stock-inbound.html", "screen_label": "가격 · 매입 > 재고 입고",
         "done": stocked >= 1, "value": f"{stocked:,}건",
         "why": "재고가 0이면 추천에서 빠집니다"},

        {"no": 8, "key": "slots", "title": "슬롯별 후보 확인",
         "screen": "candidate-pool.html", "screen_label": "추천 설정 > 추천 가능 재고 현황",
         "done": len(empty) == 0, "value": f"8개 중 {len(filled)}개 준비",
         "why": "견적 한 대는 8개 슬롯을 모두 채워야 성립합니다."
                " **한 슬롯이 0이면 전체 견적이 0건입니다** — 총량이 아니라 고르기가 기준입니다",
         "slots": [{"key": s, "label": SLOT_KO[s], "count": slots[s]} for s in SLOTS],
         "empty_slots": [SLOT_KO[s] for s in empty]},
    ]


@router.get("/setup-status")
def setup_status():
    """운영 시작 8단계의 현재 상태. 판정·수치는 전부 DB에서 직접 구한다."""
    with engine.connect() as conn:
        steps = _steps(conn)

    done = [s for s in steps if s["done"]]
    todo = [s for s in steps if not s["done"]]
    # 여덟 개를 나열하면 어디부터인지 여전히 모른다 — 하나만 지목한다.
    nxt = todo[0] if todo else None

    if nxt is None:
        note = ("운영 시작 준비가 끝났습니다 — 8개 슬롯이 모두 채워져 견적이 나옵니다."
                " 이제 슬롯별로 가격대를 넓혀 가성비 · 추천 · 고성능 티어가 서로"
                " 달라지게 하면 됩니다")
    else:
        note = f"{nxt['no']}단계 “{nxt['title']}”부터 하시면 됩니다 — {nxt['screen_label']}"

    return {
        "steps": steps,
        "done_count": len(done), "total": len(steps),
        "complete": nxt is None,
        "next": None if nxt is None else {
            "no": nxt["no"], "key": nxt["key"], "title": nxt["title"],
            "screen": nxt["screen"], "screen_label": nxt["screen_label"],
            "why": nxt["why"]},
        "note": note,
        # 절차 정본은 문서다 — 화면은 그 문서를 대신하지 않고 가리킨다.
        "doc": "docs/07_운영-시작-순서.md",
    }
