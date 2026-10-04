"""ADM-SRC-010 매입 견적 — 안전재고 미달 자동 등록 → 견적 요청 → 회신 기록 → 매입 확정.

대기 목록은 **저장하지 않고 파생**한다(ERD §3.9): `stock_qty=0 ∨ stock_qty < safety_stock`.
별도 큐 테이블을 두면 재고가 변할 때마다 동기화해야 하고, 그 동기화가 곧 버그다.
저장하는 것은 **운영자가 실제로 한 행위**뿐 — 견적 요청(quote 생성)·회신 기록·확정.

정직 3건:
  ① **회신은 자동 수신이 아니라 운영자 대행 입력**이다(공급처 회신은 전화·메일로 온다).
     외부 연동이 없으므로 우리가 가짜 회신을 만들지 않는다.
  ② 견적 '요청 발송'도 실제 메일·API 전송이 아니라 **요청 기록**이다(발송 연동 이관).
  ③ 확정은 **가격 결정**이며 재고는 늘지 않는다 — 수량이 들어오는 사건은 입고(T10) 소관.
     확정 후 그 상품은 입고 대기(ADM-SRC-020)에 이미 있다(재고 미달 상태이므로).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from datetime import datetime

from .timeutil import iso, KST, kst_day_range
from .admin_orders import _log
from .auth import current_operator_id
from .admin_price_import import _reprice, _settings
from .admin_products import PART_TYPE_LABELS
# 대기 조건 정본 = admin_stock.pending_where() — 아래 _WHERE 주석 참조.
# 순환 없음: admin_stock 은 admin_orders·admin_products·auth·db·timeutil 만 가져온다.
from .admin_stock import pending_where
from .db import engine
from .sourcing_confirm_core import confirm_quote_tx as _confirm_quote_core
from .pricing_write_guard_core import lock_products, ProductScopeChanged

router = APIRouter(prefix="/api/admin")

# 대기 사유 파생 — 입고 화면(admin_stock)과 같은 조건을 쓴다(기준이 갈리면 숫자가 갈린다)
#
# **서버 페이지네이션이다**(슬라이스 86). 예전에는 조건에 맞는 전 행을 돌려줬고,
# 실측 15,261건 · 3.6MB였다 — 화면이 열리는 데 몇 초가 걸렸고 그 뒤로도 브라우저가
# 그 표를 통째로 그려야 했다. 목록은 전부 서버 페이지네이션이라는 규약(슬라이스 54)에서
# 이 화면만 빠져 있었다.
# 대기 조건(앞 두 줄)은 **admin_stock.pending_where() 가 정본**이다 — 여기 SQL 을 다시
# 적으면 갈라진다(2026-08-17 보류 도입 때 실제로 stock-inbound 만 1건 줄었다).
# 기본값 exclude: 매입 견적은 「이 상품을 사 오려면 얼마인가」를 공급처에 묻는 자리인데,
# 입고를 보류한 상품은 지금 들여오지 않기로 한 것이라 견적을 물을 대상이 아니다.
# (확정해도 재고는 늘지 않고 곧장 입고 대기로 넘어가는데 — 이 파일 머리말 §③ —
#  그 입고가 보류돼 있으면 견적 요청이 갈 곳 없는 일이 된다.)
# 검색·분류 조건은 이 파일 소관이므로 그대로 둔다.
_WHERE = f"""
    FROM products p
    WHERE {pending_where()}
      AND (:q = '' OR p.product_name ILIKE :like OR p.sku ILIKE :like
           OR CAST(p.product_code AS TEXT) = :q)
      AND (:part_type = '' OR p.part_type = :part_type)
"""
_PENDING = """
    SELECT p.product_code, p.sku, p.product_name, p.part_type, p.stock_qty, p.safety_stock,
           p.purchase_price
""" + _WHERE + """
    ORDER BY p.stock_qty, p.product_code
    LIMIT :size OFFSET :offset
"""
# 대기 요약 배너(ADM-SRC-010 계약 §②)가 "이 중 진행 중인 견적이 있는 상품은 {n}건"을
# 말하려면 **현재 페이지가 아니라 전체 대기 모집단**에서 활성 견적(요청·회신)이 있는
# distinct 상품 수가 필요하다 — 기존 코드는 그 페이지의 상품에 대해서만 견적을 읽었다
# (아래 sourcing() 주석 "이 페이지의 상품에 대해서만"). _WHERE를 그대로 서브쿼리로
# 재사용해 큐 정의를 두 곳에 다시 적지 않는다(같은 것을 두 벌 두지 않는다).
_IN_PROGRESS = ("SELECT COUNT(*) FROM ("
                "SELECT DISTINCT q.product_code FROM product_sourcing_quotes q"
                " WHERE q.status IN ('요청','회신')"
                " AND q.product_code IN (SELECT p.product_code" + _WHERE + ")"
                ") t")


def _why(r) -> str:
    if r["stock_qty"] == 0:
        return "재고 0 — 자동 등록"
    return f"재고 {r['stock_qty']} → 안전재고 {r['safety_stock']} 미달 — 자동 등록"


_confirmed_at_col_ready: bool | None = None    # 프로세스 수명 동안 캐싱 — auth.py의 _schema_ready()와 같은 이유


def _confirmed_at_ready() -> bool:
    """마이그레이션 0053(product_sourcing_quotes.confirmed_at)이 이 DB에 실제로 적용됐는가.

    결함 수정(확인자 실측 2026-08-15): 헤더 「오늘 확정 {n}건」이 지금까지 `created_at`
    (견적을 처음 "요청"한 날짜)으로 세고 있었다. 요청 → 회신 대기 → 확정까지 며칠
    걸리는 것이 이 화면의 **정상 흐름**이라 그 컬럼으로 세면 거의 항상 0이 된다 —
    실측: 상품 39948·45551을 오늘(2026-08-15) 실제로 확정했는데(활동 로그
    `sourcing_confirm` 2건, 07:09·07:22) `created_at::date=오늘`인 요청은 0건이라
    done_today가 세 번 조회 모두 0이었다. `replied_at`도 대안이 못 된다 — "회신을 적은
    시각"이지 "확정한 시각"이 아니라서 같은 날 회신·다음 날 확정이면 또 어긋난다.
    그래서 "확정한 시각" 자체를 남기는 `confirmed_at` 컬럼이 필요하다.

    ⚠⚠ 이 컬럼의 마이그레이션(0053)은 파일만 만들고 DB에는 적용하지 않는다 —
    하네스 권한 분류기가 `alembic upgrade` 실행을 막고 있다(0051·0052와 같은 상태).
    우회하지 않는다. 그래서 컬럼이 실제로 생기기 전까지는 "오늘 확정 0건"을 자신
    있게 말하지 않는다 — 없는 컬럼을 무조건 SELECT/UPDATE하면 이 화면 전체
    (목록 조회·확정)가 500으로 죽는다(api/auth.py의 _schema_ready()와 같은 이유로
    같은 방식을 쓴다). 매 요청 무조건 information_schema를 다시 읽지 않도록 결과를
    프로세스 안에서 캐싱한다 — 스키마는 이 프로세스가 떠 있는 동안 바뀌지 않는다
    (마이그레이션은 항상 재배포로 적용된다).
    """
    global _confirmed_at_col_ready
    if _confirmed_at_col_ready is None:
        with engine.connect() as conn:
            _confirmed_at_col_ready = bool(conn.execute(text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
                " WHERE table_name='product_sourcing_quotes' AND column_name='confirmed_at')"
            )).scalar())
    return _confirmed_at_col_ready


@router.get("/sourcing")
def sourcing(page: int = 1, size: int = 100, q: str = "", part_type: str = ""):
    """매입 견적 대기 — 서버 페이지네이션 + 검색.

    `q`는 상품명·SKU·상품코드를 함께 본다(운영자는 셋 중 아무거나 손에 있는 것으로 찾는다).
    견적·확정 이력은 **이 페이지의 상품에 대해서만** 조회한다 — 예전에는 진행 중인 견적과
    확정 이력을 전건 읽고 나서 목록에 붙였다.
    """
    size = max(1, min(size, 500))
    page = max(1, page)
    kw = (q or "").strip()
    p = {"q": kw, "like": f"%{kw}%", "part_type": (part_type or "").strip(),
         "size": size, "offset": (page - 1) * size}
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) " + _WHERE), p).scalar_one()
        rows = conn.execute(text(_PENDING), p).mappings().all()
        codes = [r["product_code"] for r in rows]
        quotes = conn.execute(text(
            "SELECT q.quote_id, q.product_code, q.supplier_id, q.vendor, q.price, q.status,"
            " q.replied_at, q.memo, q.created_at, s.name AS supplier"
            " FROM product_sourcing_quotes q LEFT JOIN suppliers s USING (supplier_id)"
            " WHERE q.status IN ('요청','회신') AND q.product_code = ANY(:c)"
            " ORDER BY q.quote_id"), {"c": codes}).mappings().all() if codes else []
        # 활성 공급처만 — 견적 요청 화면(ADM-SRC-010)이 "고를 수 있는 곳"을 물으면 중지된
        # 곳은 선택지가 아니다(admin_setup.py의 부트스트랩 판정과 같은 기준: status='활성').
        # brands(취급 브랜드)도 함께 준다 — 계약 §㉮ "목록에 이름 + 취급 브랜드".
        sups = conn.execute(text(
            "SELECT supplier_id, name, brands FROM suppliers"
            " WHERE status='활성' ORDER BY name")).mappings().all()
        in_progress_total = conn.execute(text(_IN_PROGRESS), p).scalar_one()
        # done_today — _confirmed_at_ready() 참조. 컬럼이 없는 동안은 "0건"을 지어내지
        # 않고 왜 못 세는지를 함께 돌려준다(done_today_reason).
        if _confirmed_at_ready():
            # 「오늘」= KST 달력일(timeutil.py 규약) — admin_dashboard.sessions_today와 같은
            # 병(confirmed_at도 naive UTC라 CURRENT_DATE를 그대로 쓰면 09:00 KST 이전에
            # KST 어제분과 섞인다), 같은 처방(2026-08-21).
            _today_kst = datetime.now(KST).date()
            _d_lo, _d_hi = kst_day_range(iso(_today_kst), iso(_today_kst))
            done = conn.execute(text(
                "SELECT COUNT(*) FROM product_sourcing_quotes"
                " WHERE status='확정' AND confirmed_at >= :lo AND confirmed_at < :hi"),
                {"lo": _d_lo, "hi": _d_hi}).scalar_one()
            done_today_reason = None
        else:
            done = None
            done_today_reason = "확정 시각 기록이 없어 오늘 확정 건수를 셀 수 없습니다 — 마이그레이션 0053 미적용"
        # 최근 확정 — 확정해도 재고가 0이면 대기에 남으므로(가격 결정 ≠ 입고) 이력을 함께 보여준다
        confirmed = conn.execute(text(
            "SELECT DISTINCT ON (q.product_code) q.product_code, q.price, q.replied_at,"
            " s.name AS supplier FROM product_sourcing_quotes q"
            " LEFT JOIN suppliers s USING (supplier_id)"
            " WHERE q.status='확정' AND q.product_code = ANY(:c)"
            " ORDER BY q.product_code, q.quote_id DESC"),
            {"c": codes}).mappings().all() if codes else []
    last_fix = {c["product_code"]: {"price": c["price"], "supplier": c["supplier"]}
                for c in confirmed}

    by_pc: dict = {}
    for q in quotes:
        by_pc.setdefault(q["product_code"], []).append(q)

    items = []
    for r in rows:
        qs = by_pc.get(r["product_code"], [])
        replied = [q for q in qs if q["price"] is not None]
        best = min((q["price"] for q in replied), default=None)
        state = "req" if not qs else ("reply" if replied else "wait")
        items.append({
            "product_code": r["product_code"], "sku": r["sku"], "name": r["product_name"],
            "cat": PART_TYPE_LABELS.get(r["part_type"], r["part_type"]),
            "stock": r["stock_qty"], "safety_stock": r["safety_stock"],
            "purchase": r["purchase_price"], "why": _why(r), "state": state,
            "last_fix": last_fix.get(r["product_code"]),   # 매입 확정됨 — 입고만 남음
            "quotes": [{
                "quote_id": q["quote_id"], "supplier_id": q["supplier_id"],
                "supplier": q["supplier"] or q["vendor"] or "—",
                "price": q["price"], "status": q["status"],
                "replied_at": iso(q["replied_at"]) if q["replied_at"] else None,
                "memo": q["memo"], "best": q["price"] is not None and q["price"] == best,
            } for q in qs],
        })
    # note 필드는 여기서 주지 않는다(결함 수정 2026-08-15, 확인자 지적) — sourcing.html.j2는
    # 이 필드를 한 번도 읽지 않았다(죽은 필드, 소비자 0). 화면이 실제로 보여줘야 하는
    # "정직 4건"은 이미 계약(docs/design/spec-sourcing.md)의 인용문을 그대로 리터럴로
    # 담고 있다 — 요청은 기록일 뿐(버튼 문구 자체가 "기록") · 회신은 대행 입력 ·
    # 확정은 가격 결정(입고 아님) · 대기 목록은 매 조회 파생. 지웠던 이 note는 그 넷을
    # 한 문단으로 다시 요약하려 했지만 계약 문구와 어긋났다 — 예를 들어 확정 사실을
    # "재고는 입고 화면에서 늘어납니다"로만 적고, 계약이 ⚠⚠로 못박은 "그래서 이 상품은
    # 대기 목록에서 사라지지 않는다"는 빠뜨렸다. 화면 문구를 더 손볼 일이 있으면 계약
    # 문장을 그대로 옮겨야지 이 필드를 되살려 다시 요약하지 않는다(CANON §1 "같은 것을
    # 두 벌 두지 않는다").
    return {"items": items, "done_today": done, "done_today_reason": done_today_reason,
            "in_progress_total": in_progress_total,
            "page": page, "size": size, "total": total,
            "pages": (total + size - 1) // size,
            "q": kw, "part_type": p["part_type"],
            "suppliers": [{"id": s["supplier_id"], "name": s["name"], "brands": s["brands"]}
                          for s in sups]}


class RequestBody(BaseModel):
    product_code: int
    supplier_ids: list[int] = []


@router.post("/sourcing/request")
def request_quotes(body: RequestBody):
    if not body.supplier_ids:
        raise HTTPException(400, "견적을 요청할 공급처를 선택하세요")
    with engine.begin() as conn:
        discovered = conn.execute(text(
            "SELECT product_code FROM products WHERE product_code=:pc"),
            {"pc": body.product_code}).scalar()
        if discovered is None:
            raise HTTPException(404, "상품이 없습니다")
        try:
            lock_products(conn, [body.product_code])
        except ProductScopeChanged:
            raise HTTPException(409, "상품 연결이 변경되었습니다. 다시 확인하세요") from None
        p = conn.execute(text(
            "SELECT sku, product_name FROM products WHERE product_code=:pc"),
            {"pc": body.product_code}).mappings().first()
        if p is None:
            raise HTTPException(409, "상품 연결이 변경되었습니다. 다시 확인하세요")
        dup = conn.execute(text(
            "SELECT 1 FROM product_sourcing_quotes WHERE product_code=:pc"
            " AND status IN ('요청','회신') LIMIT 1"), {"pc": body.product_code}).first()
        if dup:
            raise HTTPException(409, "이미 진행 중인 견적 요청이 있습니다")
        batch_id = conn.execute(text(
            "INSERT INTO sourcing_batches (title, status) VALUES (:t, '진행') RETURNING batch_id"),
            {"t": f"{p['sku']} 매입 견적"}).scalar()
        made = []
        for sid in body.supplier_ids:
            s = conn.execute(text("SELECT name FROM suppliers WHERE supplier_id=:s"),
                             {"s": sid}).scalar()
            if s is None:
                raise HTTPException(404, f"공급처가 없습니다: {sid}")
            qid = conn.execute(text(
                "INSERT INTO product_sourcing_quotes"
                " (batch_id, product_code, supplier_id, vendor, status)"
                " VALUES (:b, :pc, :s, :v, '요청') RETURNING quote_id"),
                {"b": batch_id, "pc": body.product_code, "s": sid, "v": s}).scalar()
            made.append({"quote_id": qid, "supplier": s})
        log_id = _log(conn, "sourcing_request", p["sku"],
                      {"product_code": body.product_code, "batch_id": batch_id,
                       "quotes": made}, kind="sourcing")
        return {"ok": True, "batch_id": batch_id, "quotes": made, "undo_id": log_id}


class ReplyBody(BaseModel):
    price: int
    memo: str | None = None


@router.post("/sourcing/quotes/{quote_id}/reply")
def record_reply(quote_id: int, body: ReplyBody):
    """공급처 회신을 운영자가 대행 입력(자동 수신 아님 — 정직)."""
    if body.price <= 0:
        raise HTTPException(400, "회신 매입가는 1원 이상이어야 합니다")
    with engine.begin() as conn:
        discovered = conn.execute(text(
            "SELECT quote_id, product_code, batch_id FROM product_sourcing_quotes"
            " WHERE quote_id=:i"), {"i": quote_id}).mappings().first()
        if discovered is None:
            raise HTTPException(404, "견적 요청이 없습니다")
        try:
            lock_products(conn, [discovered["product_code"]])
        except ProductScopeChanged:
            raise HTTPException(409, "견적의 상품 연결이 변경되었습니다. 다시 확인하세요") from None
        q = conn.execute(text(
            "SELECT quote_id, product_code, batch_id, status, price, memo, replied_at"
            " FROM product_sourcing_quotes WHERE quote_id=:i FOR UPDATE"),
            {"i": quote_id}).mappings().first()
        if (q is None or q["product_code"] != discovered["product_code"]
                or q["batch_id"] != discovered["batch_id"]):
            raise HTTPException(409, "견적의 상품 또는 배치 연결이 변경되었습니다. 다시 확인하세요")
        if q["status"] not in ("요청", "회신"):
            raise HTTPException(409, f"'{q['status']}' 상태에서는 회신을 기록할 수 없습니다")
        conn.execute(text(
            "UPDATE product_sourcing_quotes SET price=:p, memo=:m, status='회신',"
            " replied_at=now() WHERE quote_id=:i"),
            {"p": body.price, "m": body.memo, "i": quote_id})
        # 되돌리기 재료(2026-08-28, req-activity-undo.md §④와 맞물린다) — 이 UPDATE 가
        # 덮어쓰는 네 필드(price·status·replied_at·memo)의 이전 값을 UPDATE 전에 읽어
        # 둔다(admin_stock.inbound·admin_category_mapping.move 의 before 관례와 동일 —
        # 실제로 바뀌는 값만 담는다). 최초 회신이면 price=NULL·status='요청'이고,
        # 이미 회신된 값을 다시 고치는 경우(가드가 status in ('요청','회신') 둘 다
        # 허용)에는 그 이전 회신값이 담긴다 — 되돌리기가 구현되면 이 분기를 그대로
        # 복원해야 한다(무조건 NULL로 되돌리면 틀린 값이 된다).
        # ⚠ 되돌리기 라우트는 아직 만들지 않는다 — 이 남기기 작업의 범위 밖이다.
        _log(conn, "sourcing_reply", str(quote_id),
             {"quote_id": quote_id, "product_code": q["product_code"], "price": body.price,
              "before": {"price": q["price"], "status": q["status"],
                         "replied_at": iso(q["replied_at"]) if q["replied_at"] else None,
                         "memo": q["memo"]}},
             kind="sourcing")
        return {"ok": True, "price": body.price}


@router.post("/sourcing/quotes/{quote_id}/confirm")
def confirm_quote(quote_id: int):
    """매입 확정 — psp 갱신 + 재판정(가격 이력 reason='sourcing'). 재고는 늘지 않는다(T10 경계).

    트랜잭션 본문·잠금 순서는 `_confirm_quote_tx` 참조. 여기서는 그 안에서 데드락이
    나는 경우만 잡는다(아래).
    """
    try:
        return _confirm_quote_tx(quote_id)
    except OperationalError as exc:
        # SQLSTATE 40P01 = deadlock_detected(PostgreSQL). **실측**(제작자, 2026-08-29,
        # threading.Barrier로 같은 상품의 형제 견적 둘을 동시에 confirm) — 서버 로그:
        #   psycopg2.errors.DeadlockDetected: deadlock detected
        #   CONTEXT:  while locking tuple (...) in relation "products"
        # 이 원인은 `_confirm_quote_tx` 머리말의 ⚠⚠ 항목 참조. SQLAlchemy는 이를
        # sqlalchemy.exc.OperationalError로 감싸고 원본은 .orig에 담는다.
        # 트랜잭션 정리: `with engine.begin()`은 블록 밖으로 예외가 나가면 자동으로
        # rollback한다(api/auth.py의 register_device() try/with 관례와 동일) — 서버가
        # 이미 이 트랜잭션을 강제 종료한 뒤이므로 여기서 conn.rollback()을 따로 부를
        # 필요가 없고, 부를 conn도 이 스코프엔 없다(트랜잭션은 _confirm_quote_tx
        # 안에서 열고 닫힌다).
        # 재시도가 유효한 이유: 데드락은 PostgreSQL이 둘 중 하나만 강제 종료하는
        # 것이지 요청 자체가 틀린 게 아니다 — 살아남은 쪽은 이미 정상 커밋됐다.
        # "다른 사람이 먼저 확정했습니다"라고 말하지 않는다 — 그건 아래 상태 확인
        # (status != '회신') 409의 몫이고, 이 견적이 실제로 그 상태가 됐다면 재시도 시
        # 그 문구로 안내된다. 여기서는 "동시에 시도해서 겹쳤다"만 말한다.
        if getattr(exc.orig, "pgcode", None) == "40P01":
            raise HTTPException(
                409, "다른 확정 요청과 동시에 처리되어 충돌했습니다. 다시 시도하세요")
        raise   # 다른 원인의 OperationalError(예: 접속 끊김)는 그대로 500으로 — 지어낸 안내를 붙이지 않는다


def _confirm_quote_tx(quote_id: int):
    """상품 전체 오름차순 → 배치 → 관련 견적 quote_id 오름차순으로 잠근다.

    core가 일반 조회로 발견한 대상·형제의 상품 집합을 먼저 잠그고,
    배치와 관련 견적을 잠근 뒤 연결 집합을 다시 확인한다. 새 상품이나
    연결 변경은 쓰기 전에409로 중단하며 추가 상품을 늦게 잠그지 않는다.
    같은 배치가 여러 상품을 포함하거나 batch_id가 NULL인 기존 행도 처리한다.
    JOIN의 내부 잠금 순서에 의존하지 않으며 다른 writer 전체의 잠금 순서,
    ABA/revision/receipt 보호를 증명하는 변경은 아니다. caller TX와
    confirm_quote()의40P01→409 경계 및 기존 callback 구현은 유지한다.
    """
    with engine.begin() as conn:
        return _confirm_quote_core(
            conn, quote_id, settings=_settings, reprice=_reprice,
            log=_log, confirmed_at_ready=_confirmed_at_ready)
