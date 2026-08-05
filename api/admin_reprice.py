"""판매가 재산정 (ADM-PRC-050) — 슬라이스 E.

마진 정책(12%)과 카드수수료는 화면에서 고칠 수 있지만, **이미 매겨진 판매가를 정책에 맞춰
다시 계산할 길이 없었다.** 정책을 바꿔도 아무 일도 일어나지 않았다는 뜻이다.

■ 기존 `_reprice`로는 못 한다 — 다른 일이기 때문이다
`admin_price_import._reprice`는 **공급처 단가가 바뀌었을 때** 매입가를 재판정하고 그에 따라
판매가를 다시 매긴다. 그래서 `product_supplier_prices` 행이 없으면 아무것도 하지 않는다.
그런데 매입가가 있는 18,748건 중 **18,743건이 공급처 단가 행이 없다**(적재가 매입가만 넣었다).
즉 기존 경로로는 거의 전부를 손대지 못한다.

여기서 하는 일은 **매입가는 그대로 두고 판매가만 정책대로 다시 계산**하는 것이다.
공식은 `pricing.sale_from_purchase` 하나를 쓴다(단일 원천 — 두 곳에서 계산하면 갈라진다).

■ 실측이 설계를 바꿨다 (2026-08-04)
처음엔 "정책과 다른 것 N건을 맞춘다"로 설계했는데, 재 보니 그 수가 **18,540건**이었고
총액 변동은 **-2.4억**이었다. 이 수를 그대로 내밀면 운영자는 판단할 수 없다.
나눠 보니 서로 다른 세 가지가 섞여 있었다:

    정책 미달   판매중·재고>0의 97%(7,129건)가 배수 1.00~1.15 — 정책(1.146)보다 **낮다**
                → 정책을 적용하면 **가격이 오른다**. 매출에 직결되는 결정이다.
    역마진      1,008건이 매입가보다 싸다(판매가 0원 포함). 대부분 품절이지만 판매중도 3건.
    이상치      206건이 배수 2.0 이상, 최대 **20,000배**(매입 45,000 / 판매 9억).
                매입가가 100원·4,000원 같은 자리표시 값이다 — 데이터 오류지 가격이 아니다.

**총액 하나로 합치면 이 셋이 서로 상쇄되어 거짓말이 된다.** 9억짜리 이상치 한 건이
나머지 18,539건의 인상분을 통째로 덮는다. 그래서 미리보기는 **오름·내림을 갈라서** 보이고,
이상치와 역마진을 **따로 세운다**.

■ 드라이런 → 확인 → 적용 (카탈로그 적재와 같은 형태)
미리보기가 낸 변동 건수를 적용 요청이 그대로 되돌려 보내야 한다. 그 사이에 다른 사람이
가격을 고쳤으면 수가 달라져 거부된다 — 다른 화면을 확정하는 사고를 막는 장치다.

■ 잠긴 것은 건드리지 않는다
`locked_fields`에 `sale_price`가 있으면 운영자가 손으로 정한 값이다(ERD §6.3
"locked면 제안만·정책 변경 차단"). 세기만 하고 바꾸지 않는다.

■ 되돌릴 수 있다
`product_price_history`에 행을 남기고(reason='margin_policy'), 로그 detail에 상품별
이전 값을 담는다. 되돌리기는 **역방향 전이**이고 `ref_log_id`로 원 기록을 가리킨다.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import _log
from .admin_price_import import _settings
from .auth import current_operator, current_operator_id
from .db import engine
from .pricing import formula_text, resolve_margins, sale_from_purchase
from .taxonomy import PART_LABELS

router = APIRouter(prefix="/api/admin")

MAX_APPLY = 20000        # 한 번에 반영할 상한 — 넘으면 응답이 빠진 수를 밝힌다
OUTLIER_X = 2.0          # 이 배수 이상은 '가격'이 아니라 데이터 오류로 본다

SCOPES = {
    "live": ("판매중 · 재고 있음", "p.status = '판매중' AND p.stock_qty > 0"),
    "selling": ("판매중 전체", "p.status = '판매중'"),
    "all": ("전체", "TRUE"),
}


def _owner():
    me = current_operator() or {}
    if me.get("role") != "owner":
        raise HTTPException(403, "관리자(owner)만 판매가를 재산정할 수 있습니다")
    return me


def _rows(conn, scope):
    return conn.execute(text(
        "SELECT p.product_code, p.product_name, p.part_type, p.purchase_price, p.sale_price,"
        "       p.status, p.stock_qty, p.locked_fields, p.category_id"
        "  FROM products p"
        f" WHERE p.purchase_price IS NOT NULL AND p.purchase_price > 0 AND {SCOPES[scope][1]}"
        " ORDER BY p.product_code")).mappings().all()


def _margin_map(conn, default):
    """{category_id: 적용 마진}. 상속 규칙은 `pricing`이 단일 원천이다.

    카테고리가 없는 상품(미매핑)은 **전역**을 쓴다 — 마진을 못 정했다고 값을
    안 매기면 그 상품만 옛 가격으로 남아 조용히 어긋난다.
    """
    nodes = conn.execute(text("SELECT category_id, parent_id FROM categories")).all()
    own = {r[0]: float(r[1]) for r in conn.execute(text(
        "SELECT category_id, margin_rate FROM category_margin_policies"))}
    return {cid: m for cid, (m, _src) in resolve_margins(nodes, own, default).items()}


def _classify(rows, fee, margin, mmap=None):
    """상품별 판정. **세 가지를 섞지 않는다** — 섞으면 총액이 서로 상쇄된다.

    마진은 상품이 걸린 **분류**를 따른다(2026-08-05). `mmap`이 없으면 전역 하나다.
    """
    mmap = mmap or {}
    up, down, same, locked, outlier, negative = [], [], 0, [], [], []
    used = {}          # 어떤 마진이 몇 건에 쓰였는가
    for r in rows:
        cur = r["sale_price"]
        m = mmap.get(r["category_id"], margin)
        # **적용한 그 값을 센다.** 따로 한 번 더 계산하면 계산과 보고가 갈라진다 —
        # 실제로 전역만 쓰면서 "분류별로 썼다"고 보고할 수 있었다(사보타주로 확인).
        used[m] = used.get(m, 0) + 1
        new = sale_from_purchase(r["purchase_price"], fee, m)
        purchase = float(r["purchase_price"])
        item = {"product_code": r["product_code"], "name": r["product_name"],
                "part_label": PART_LABELS.get(r["part_type"], r["part_type"]),
                "purchase": r["purchase_price"], "current": cur, "proposed": new,
                "margin_rate": m,      # 이 상품에 실제로 쓰인 마진 — 화면이 근거로 쓴다
                "delta": (new - cur) if cur is not None else None,
                "status": r["status"], "stock_qty": r["stock_qty"],
                "ratio": round(cur / purchase, 3) if cur is not None else None}
        # 잠긴 것은 어느 통에도 넣지 않는다 — 바꾸지 않을 것이므로 변동에 세면 거짓말이다
        if "sale_price" in (r["locked_fields"] or []):
            if new != cur:
                locked.append(item)
            continue
        if cur is not None and cur < purchase:
            negative.append(item)
        if cur is not None and cur >= purchase * OUTLIER_X:
            outlier.append(item)
        if new == cur:
            same += 1
        elif cur is None or new > cur:
            up.append(item)
        else:
            down.append(item)
    return {"up": up, "down": down, "same": same, "locked": locked,
            "outlier": outlier, "negative": negative, "margins_used": used}


def _summary(c, scope, fee, margin, ex=6):
    top = lambda xs, k: sorted(xs, key=k, reverse=True)[:ex]     # noqa: E731
    return {
        "scope": scope, "scope_label": SCOPES[scope][0],
        "formula": formula_text(fee, margin),
        "card_fee_rate": fee, "margin_rate": margin,
        # **마진이 하나가 아닐 수 있다**(분류별 정책 — 2026-08-05). 공식 한 줄만 내밀면
        # 그 줄이 맞지 않는 상품이 섞여 있다는 사실을 감추는 셈이다.
        "margins_used": [{"margin_rate": k, "count": v}
                         for k, v in sorted(c["margins_used"].items())],
        "margin_varies": len(c["margins_used"]) > 1,
        "target": len(c["up"]) + len(c["down"]) + c["same"] + len(c["locked"]),
        "changed": len(c["up"]) + len(c["down"]),
        # **오름·내림을 갈라서 낸다** — 하나로 합치면 9억짜리 이상치가 나머지를 덮는다
        "up_count": len(c["up"]), "up_sum": sum(i["delta"] or 0 for i in c["up"]),
        "down_count": len(c["down"]), "down_sum": sum(i["delta"] or 0 for i in c["down"]),
        "same": c["same"],
        "locked_count": len(c["locked"]),
        "outlier_count": len(c["outlier"]), "negative_count": len(c["negative"]),
        "examples": {
            "up": top(c["up"], lambda i: i["delta"] or 0),
            "down": top(c["down"], lambda i: -(i["delta"] or 0)),
            "outlier": top(c["outlier"], lambda i: i["ratio"] or 0),
            "negative": top(c["negative"],
                            lambda i: (i["purchase"] or 0) - (i["current"] or 0)),
            "locked": c["locked"][:ex],
        },
        "max_apply": MAX_APPLY,
        "note": ("**미리보기입니다 — 아무것도 바뀌지 않았습니다.**"
                 " 오름과 내림을 따로 냅니다: 합치면 이상치 한 건이 나머지 전부를 덮습니다."
                 " 잠긴 판매가(운영자가 손으로 정한 값)는 세기만 하고 바꾸지 않습니다."
                 + (" 마진은 **분류마다 다릅니다** — 위 공식은 전역 마진을 쓰는 상품에만"
                    " 해당하고, 상품별로 적용된 마진은 목록에 함께 표시됩니다."
                    if len(c["margins_used"]) > 1 else "")),
    }


@router.get("/reprice/preview")
def preview(scope: str = "live"):
    if scope not in SCOPES:
        raise HTTPException(400, "알 수 없는 범위입니다")
    with engine.connect() as conn:
        fee, margin = _settings(conn)
        mmap = _margin_map(conn, margin)
        rows = _rows(conn, scope)
    return _summary(_classify(rows, fee, margin, mmap), scope, fee, margin)


class ApplyBody(BaseModel):
    scope: str
    expect_changed: int      # 미리보기가 낸 변동 건수 — 그대로 되돌려 보내야 한다
    note: str = ""


@router.post("/reprice/apply")
def apply(body: ApplyBody):
    _owner()
    if body.scope not in SCOPES:
        raise HTTPException(400, "알 수 없는 범위입니다")
    with engine.begin() as conn:
        fee, margin = _settings(conn)
        mmap = _margin_map(conn, margin)
        c = _classify(_rows(conn, body.scope), fee, margin, mmap)
        targets = c["up"] + c["down"]
        if not targets:
            raise HTTPException(400, "정책과 다른 판매가가 없습니다 — 바꿀 것이 없습니다")
        if len(targets) != body.expect_changed:
            raise HTTPException(409,
                                f"미리보기 이후 값이 달라졌습니다 — 다시 확인해 주세요"
                                f" (미리보기 {body.expect_changed:,}건 · 지금 {len(targets):,}건)")
        dropped = 0
        if len(targets) > MAX_APPLY:
            dropped = len(targets) - MAX_APPLY
            targets = targets[:MAX_APPLY]

        op = current_operator_id()
        before = []
        for t in targets:
            conn.execute(text(
                "UPDATE products SET sale_price=:v, updated_at=now() WHERE product_code=:pc"),
                {"v": t["proposed"], "pc": t["product_code"]})
            conn.execute(text(
                "INSERT INTO product_price_history"
                " (product_code, field, old_price, new_price, reason, changed_by)"
                " VALUES (:pc, 'sale', :o, :n, 'margin_policy', :op)"),
                {"pc": t["product_code"], "o": t["current"], "n": t["proposed"], "op": op})
            before.append({"pc": t["product_code"], "sale": t["current"]})

        log_id = _log(conn, "판매가 재산정", body.scope, {
            "scope": body.scope, "scope_label": SCOPES[body.scope][0],
            "card_fee_rate": fee, "margin_rate": margin,
            # 어떤 마진으로 매겼는지 원장에 남긴다 — 나중에 "왜 이 값이지?"에 답하려면
            # 그때 전역이 얼마였는지만으로는 부족하다(분류별 정책이 섞여 있다).
            "margins_used": {str(k): v for k, v in sorted(c["margins_used"].items())},
            "changed": len(targets),
            "up": len(c["up"]), "down": len(c["down"]),
            "note": (body.note or "").strip()[:200],
            "before": before,
        }, kind="price")

    msg = (f"{len(targets):,}건의 판매가를 정책대로 다시 매겼습니다"
           f" (오름 {len(c['up']):,} · 내림 {len(c['down']):,})")
    if c["locked"]:
        msg += f" · 잠긴 {len(c['locked']):,}건은 그대로 두었습니다"
    if dropped:
        msg += f" · 상한 {MAX_APPLY:,}건을 넘어 {dropped:,}건은 남았습니다"
    return {"verdict": msg, "changed": len(targets), "up": len(c["up"]),
            "down": len(c["down"]), "locked": len(c["locked"]),
            "dropped": dropped, "log_id": log_id}


class UndoBody(BaseModel):
    log_id: int


@router.post("/reprice/undo")
def undo(body: UndoBody):
    _owner()
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT detail, action FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": body.log_id}).mappings().first()
        if row is None or row["action"] != "판매가 재산정":
            raise HTTPException(404, "되돌릴 재산정 기록을 찾을 수 없습니다")
        dup = conn.execute(text(
            "SELECT 1 FROM admin_operator_activity_logs"
            " WHERE detail->>'ref_log_id' = CAST(:i AS TEXT)"), {"i": body.log_id}).first()
        if dup:
            raise HTTPException(409, "이미 되돌린 기록입니다")
        detail = row["detail"] if isinstance(row["detail"], dict) else json.loads(row["detail"])
        before = detail.get("before") or []
        if not before:
            raise HTTPException(400, "이 기록에는 되돌릴 근거가 없습니다")

        op = current_operator_id()
        for b in before:
            cur = conn.execute(text(
                "SELECT sale_price FROM products WHERE product_code=:pc"),
                {"pc": b["pc"]}).scalar()
            conn.execute(text(
                "UPDATE products SET sale_price=:v, updated_at=now() WHERE product_code=:pc"),
                {"v": b["sale"], "pc": b["pc"]})
            conn.execute(text(
                "INSERT INTO product_price_history"
                " (product_code, field, old_price, new_price, reason, changed_by)"
                " VALUES (:pc, 'sale', :o, :n, 'margin_policy_undo', :op)"),
                {"pc": b["pc"], "o": cur, "n": b["sale"], "op": op})

        _log(conn, "판매가 재산정 되돌림", detail.get("scope", "—"),
             {"ref_log_id": body.log_id, "restored": len(before)}, kind="price")
    return {"verdict": f"{len(before):,}건의 판매가를 이전 값으로 되돌렸습니다",
            "restored": len(before)}
