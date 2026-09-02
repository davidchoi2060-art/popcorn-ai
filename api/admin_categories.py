"""판매 카테고리 관리 (ADM-CAT-010) — 슬라이스 B.

`categories`는 **판매 탐색 축**이다. 부품 종류(`part_type`)와 다른 축이고,
**엔진은 이 표를 읽지 않는다** — 운영자가 카테고리를 옮겨도 견적 결과는 그대로여야 한다
(A-02 재현성). 회귀 `[33]`이 "엔진 모듈이 categories를 참조하지 않는다"를 소스로 지킨다.

기존 임대 관리자에서 물려받지 않기로 한 것들(`docs/research/legacy-admin-2026-08-04.md`):

  · **고정 깊이 없음** — 저쪽 4단 고정이 미매핑 1,458건을 만들었다. 여기선 `parent_id`만 둔다.
  · **트리는 한 벌** — 저쪽 `베스트7주력부품`은 부품 트리의 두 번째 복제본이었다.
  · **업무 상태를 넣지 않는다** — 저쪽 `내부관리용 > 상품평 21~50개`는 리뷰 수가 카테고리였다.
  · **allowed_part_types** — 저쪽에 없던 안전장치. 여기 올 수 있는 part_type을 걸어 둔다.
    NULL이면 제한 없음. **위반을 막지는 않되 근거와 함께 경고한다** — 막으면 운영자가
    이유도 모른 채 벽을 만나고, 안 알리면 저쪽처럼 `위메이드`가 부품 밑에 들어간다.

쓰기는 owner·operator(2026-08-13 사장님 결정 — "operator도 권한을 줘도 됩니다" —
`admin_category_mapping.py`의 매핑 이동·되돌리기와 같은 등급으로 확대했다). viewer는
여전히 막는다 — 분류를 바꾸면 고객이 상품을 찾는 길이 바뀐다는 이유 자체는 그대로다.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import _log
from .auth import current_operator
from .db import engine
from .pricing import margin_source_text, resolve_margins
from .taxonomy import DISPLAY_LABELS, PART_LABELS, display_labels, expand_display
from .timeutil import iso

router = APIRouter(prefix="/api/admin")

MAX_NAME = 80


def _margins(conn, rows):
    """노드별 적용 마진 — 자기 노드 → 조상 → 전역(pricing_settings).

    공식·상속 규칙은 `pricing`이 단일 원천이다. 여기서 다시 계산하지 않는다.
    """
    default = float(conn.execute(text(
        "SELECT margin_rate FROM pricing_settings"
        " ORDER BY effective_from DESC LIMIT 1")).scalar() or 0)
    own = {r[0]: float(r[1]) for r in conn.execute(text(
        "SELECT category_id, margin_rate FROM category_margin_policies"))}
    eff = resolve_margins([(r["category_id"], r["parent_id"]) for r in rows], own, default)
    return own, eff, default


def _operator():
    """카테고리 쓰기 게이트 — owner·operator(2026-08-13 확대). viewer는 403.

    `admin_category_mapping.py`의 `_operator()`와 판정·문구 관례를 맞춘다(공용 헬퍼는
    아직 없다 — 각 파일이 자기 `_operator()`를 갖는 구조를 그대로 따른다).
    """
    me = current_operator() or {}
    if me.get("role") not in ("owner", "operator"):
        raise HTTPException(403, "운영자 이상만 카테고리를 바꿀 수 있습니다")
    return me


def _clean_name(v) -> str:
    name = (v or "").strip()
    if not name:
        raise HTTPException(400, "카테고리 이름을 입력하세요")
    if len(name) > MAX_NAME:
        raise HTTPException(400, f"이름은 {MAX_NAME}자 이내여야 합니다")
    return name


def _clean_types(v):
    """allowed_part_types 검증 — 없는 part_type을 걸면 그 카테고리는 영영 경고만 낸다.

    화면은 **표시 종류 18종**을 보낸다(쿨러가 하나 — 2026-09-02 기록자 정정, 16종은
    오기. 확인: `len(api.taxonomy.DISPLAY_LABELS)`, 아래 170행과 같은 오기였다).
    저장은 **실제 part_type**으로
    푼다 — `'COOLER'` → 공랭·수랭 둘 다. 이 표를 읽는 것은 위반 판정
    (`allowed_part_types @> part_type`)이고, 그쪽은 실제 값과 대조하기 때문이다.
    표시 키를 그대로 넣으면 쿨러 1,373건이 전부 '허용 종류 위반'으로 뜬다.
    """
    if v is None:
        return None
    if not isinstance(v, list):
        raise HTTPException(400, "허용 부품 종류는 목록이어야 합니다")
    out = []
    for t in v:
        if t in DISPLAY_LABELS:
            out.extend(expand_display(t))
        elif t in PART_LABELS:      # 예전 화면·API 호출이 실제 키를 보내도 받는다
            out.append(t)
        else:
            raise HTTPException(400, "없는 부품 종류입니다: " + str(t))
    return sorted(set(out)) or None    # 빈 목록 = 제한 없음(NULL)과 같은 뜻으로 둔다


def _rows(conn):
    # n_sub = 자손까지 합친 수. **트리 배지는 이 값을 써야 한다** — 상위 노드는 직접 상품이
    # 0건인 게 보통이라, 직접 수를 배지에 쓰면 13,308건을 담은 `부품`이 "0"으로 보인다
    # (슬라이스 C에서 화면이 빈 채로 열린 것과 같은 함정).
    return conn.execute(text(
        "SELECT c.category_id, c.parent_id, c.name, c.sort_order, c.is_visible,"
        "       c.allowed_part_types, c.created_at, c.updated_at,"
        "       (SELECT count(*) FROM products p WHERE p.category_id = c.category_id) AS n,"
        "       (SELECT count(*) FROM products p WHERE p.category_id IN ("
        "          WITH RECURSIVE t AS ("
        "            SELECT category_id FROM categories WHERE category_id = c.category_id"
        "            UNION ALL"
        "            SELECT c2.category_id FROM categories c2 JOIN t ON c2.parent_id = t.category_id"
        "          ) SELECT category_id FROM t)) AS n_sub,"
        "       (SELECT count(*) FROM products p WHERE p.category_id = c.category_id"
        "          AND p.stock_qty > 0) AS n_stock"
        "  FROM categories c ORDER BY c.sort_order, c.name")).mappings().all()


def _descendants(rows, root_id: int) -> set:
    """자손 전체 — 이동이 순환을 만드는지 판정할 때 쓴다."""
    kids, seen, stack = {}, set(), [root_id]
    for r in rows:
        kids.setdefault(r["parent_id"], []).append(r["category_id"])
    while stack:
        cur = stack.pop()
        for k in kids.get(cur, []):
            if k not in seen:
                seen.add(k)
                stack.append(k)
    return seen


def _violations(conn):
    """allowed_part_types를 어긴 매핑 — 막지 않고 세어서 알린다."""
    return conn.execute(text(
        "SELECT c.category_id, count(*) n FROM products p JOIN categories c USING (category_id)"
        " WHERE c.allowed_part_types IS NOT NULL"
        "   AND NOT (c.allowed_part_types @> to_jsonb(p.part_type))"
        " GROUP BY 1")).mappings().all()


@router.get("/categories")
def categories():
    with engine.connect() as conn:
        rows = _rows(conn)
        viol = {v["category_id"]: v["n"] for v in _violations(conn)}
        unmapped = conn.execute(text(
            "SELECT count(*) FROM products WHERE category_id IS NULL")).scalar()
        unmapped_live = conn.execute(text(
            "SELECT count(*) FROM products WHERE category_id IS NULL AND stock_qty > 0")).scalar()
        own_margin, eff_margin, default_margin = _margins(conn, rows)
    names = {r["category_id"]: r["name"] for r in rows}
    items = [{
        "category_id": r["category_id"], "parent_id": r["parent_id"], "name": r["name"],
        "sort_order": r["sort_order"], "is_visible": r["is_visible"],
        "allowed_part_types": r["allowed_part_types"],
        # 라벨은 접어서 보여준다 — 쿨러가 걸린 카테고리가 '공랭, 수랭' 두 줄로 뜨면
        # 화면에서 하나로 고른 것이 저장 뒤에 둘로 보인다(같은 것을 다르게 말하는 셈).
        "allowed_labels": display_labels(r["allowed_part_types"]),
        "product_count": r["n"], "subtree_count": r["n_sub"],
        "in_stock_count": r["n_stock"],
        "violations": viol.get(r["category_id"], 0),
        # 마진 — **세 값을 구분해서 준다.** 적용값만 주면 운영자는 이 노드에 값이
        # 걸린 줄 알고, 지우려 해도 지울 게 없다(상속이면 조상에 걸려 있다).
        "margin_rate": own_margin.get(r["category_id"]),          # 이 노드에 직접 건 값(없으면 null)
        "margin_effective": eff_margin[r["category_id"]][0],       # 실제 적용되는 값
        "margin_source": margin_source_text(
            eff_margin[r["category_id"]][1], r["category_id"], names),
        "created_at": iso(r["created_at"]), "updated_at": iso(r["updated_at"]),
    } for r in rows]
    return {
        "items": items,
        "unmapped": unmapped, "unmapped_in_stock": unmapped_live,
        # 고르는 자리는 **표시 종류 18종**이다(쿨러 하나 — 사용자 결정 2026-08-05).
        # 19종(part_type distinct) − 쿨러 1(공랭·수랭이 한 자리) = 18. 확인:
        # `len(api.taxonomy.DISPLAY_LABELS)` — 2026-09-02 기록자 재확인, 16종은 오기.
        # 저장은 `_clean_types`가 실제 part_type으로 푼다.
        "part_types": [{"key": k, "label": v} for k, v in DISPLAY_LABELS.items()],
        "default_margin": default_margin,
        "margin_note": ("마진은 **다음 재산정부터** 쓰입니다 — 분류를 옮겨도 저장된"
                        " 판매가는 그 자리에서 바뀌지 않습니다."),
        "note": ("카테고리는 **판매 탐색 축**입니다 — 엔진(견적)은 이 표를 읽지 않습니다."
                 " 카테고리를 옮겨도 견적 결과는 달라지지 않습니다."),
    }


class CreateBody(BaseModel):
    name: str
    parent_id: int | None = None
    sort_order: int = 0
    allowed_part_types: list[str] | None = None


@router.post("/categories")
def create(body: CreateBody):
    _operator()
    name = _clean_name(body.name)
    types = _clean_types(body.allowed_part_types)
    with engine.begin() as conn:
        if body.parent_id is not None:
            if not conn.execute(text("SELECT 1 FROM categories WHERE category_id=:i"),
                                {"i": body.parent_id}).first():
                raise HTTPException(404, "상위 카테고리를 찾을 수 없습니다")
        dup = conn.execute(text(
            "SELECT 1 FROM categories WHERE name=:n AND parent_id IS NOT DISTINCT FROM :p"),
            {"n": name, "p": body.parent_id}).first()
        if dup:
            raise HTTPException(409, "같은 위치에 같은 이름의 카테고리가 이미 있습니다")
        cid = conn.execute(text(
            "INSERT INTO categories (parent_id, name, sort_order, allowed_part_types)"
            " VALUES (:p, :n, :s, CAST(:t AS JSONB)) RETURNING category_id"),
            {"p": body.parent_id, "n": name, "s": body.sort_order,
             "t": json.dumps(types) if types else None}).scalar()
        _log(conn, "카테고리 추가", str(cid),
             {"name": name, "parent_id": body.parent_id}, kind="category")
    return {"category_id": cid, "verdict": f"'{name}' 카테고리를 추가했습니다"}


class PatchBody(BaseModel):
    name: str | None = None
    parent_id: int | None = None
    move_to_root: bool = False        # parent_id=None은 '안 바꿈'과 구분이 안 되므로 별도 플래그
    sort_order: int | None = None
    is_visible: bool | None = None
    allowed_part_types: list[str] | None = None
    clear_part_types: bool = False


@router.patch("/categories/{cid}")
def patch(cid: int, body: PatchBody):
    _operator()
    with engine.begin() as conn:
        rows = _rows(conn)
        cur = next((r for r in rows if r["category_id"] == cid), None)
        if cur is None:
            raise HTTPException(404, "카테고리를 찾을 수 없습니다")

        sets, params, before, after = [], {"i": cid}, {}, {}

        if body.name is not None:
            name = _clean_name(body.name)
            if name != cur["name"]:
                before["name"], after["name"] = cur["name"], name
                sets.append("name=:n"), params.update(n=name)

        new_parent = cur["parent_id"]
        if body.move_to_root:
            new_parent = None
        elif body.parent_id is not None:
            new_parent = body.parent_id
        if new_parent != cur["parent_id"]:
            if new_parent is not None:
                if not any(r["category_id"] == new_parent for r in rows):
                    raise HTTPException(404, "옮길 상위 카테고리를 찾을 수 없습니다")
                # 자기 자신 또는 자기 자손 밑으로는 못 간다 — 트리가 고리가 된다.
                if new_parent == cid or new_parent in _descendants(rows, cid):
                    raise HTTPException(400, "자기 자신이나 하위 카테고리 밑으로는 옮길 수 없습니다")
            before["parent_id"], after["parent_id"] = cur["parent_id"], new_parent
            sets.append("parent_id=:p"), params.update(p=new_parent)

        # 이름·부모가 바뀌면 같은 자리에 같은 이름이 생길 수 있다(부분 유니크가 잡지만
        # 409로 먼저 답해야 운영자가 이유를 안다).
        final_name = after.get("name", cur["name"])
        if ("name" in after) or ("parent_id" in after):
            dup = conn.execute(text(
                "SELECT 1 FROM categories WHERE name=:n AND parent_id IS NOT DISTINCT FROM :p"
                " AND category_id <> :i"),
                {"n": final_name, "p": new_parent, "i": cid}).first()
            if dup:
                raise HTTPException(409, "같은 위치에 같은 이름의 카테고리가 이미 있습니다")

        if body.sort_order is not None and body.sort_order != cur["sort_order"]:
            before["sort_order"], after["sort_order"] = cur["sort_order"], body.sort_order
            sets.append("sort_order=:s"), params.update(s=body.sort_order)

        if body.is_visible is not None and body.is_visible != cur["is_visible"]:
            before["is_visible"], after["is_visible"] = cur["is_visible"], body.is_visible
            sets.append("is_visible=:v"), params.update(v=body.is_visible)

        if body.clear_part_types:
            if cur["allowed_part_types"] is not None:
                before["allowed_part_types"], after["allowed_part_types"] = \
                    cur["allowed_part_types"], None
                sets.append("allowed_part_types=NULL")
        elif body.allowed_part_types is not None:
            types = _clean_types(body.allowed_part_types)
            if types != cur["allowed_part_types"]:
                before["allowed_part_types"], after["allowed_part_types"] = \
                    cur["allowed_part_types"], types
                sets.append("allowed_part_types=CAST(:t AS JSONB)")
                params.update(t=json.dumps(types) if types else None)

        if not sets:
            raise HTTPException(400, "바뀐 내용이 없습니다")

        conn.execute(text(f"UPDATE categories SET {', '.join(sets)}, updated_at=now()"
                          " WHERE category_id=:i"), params)
        _log(conn, "카테고리 수정", str(cid), {"from": before, "to": after}, kind="category")
    return {"verdict": f"'{final_name}' 카테고리를 수정했습니다", "changed": sorted(after)}


@router.delete("/categories/{cid}")
def remove(cid: int):
    _operator()
    with engine.begin() as conn:
        cur = conn.execute(text(
            "SELECT name FROM categories WHERE category_id=:i"), {"i": cid}).mappings().first()
        if cur is None:
            raise HTTPException(404, "카테고리를 찾을 수 없습니다")
        kids = conn.execute(text(
            "SELECT count(*) FROM categories WHERE parent_id=:i"), {"i": cid}).scalar()
        if kids:
            raise HTTPException(409, f"하위 카테고리 {kids}개를 먼저 옮기거나 지우세요")
        # 상품이 걸려 있으면 지우지 않는다 — 지우면 그 상품들이 조용히 미매핑이 된다
        # (저쪽이 1,458건을 그렇게 쌓았다).
        n = conn.execute(text(
            "SELECT count(*) FROM products WHERE category_id=:i"), {"i": cid}).scalar()
        if n:
            raise HTTPException(409, f"상품 {n:,}건이 이 카테고리에 있습니다 — 먼저 옮기세요")
        conn.execute(text("DELETE FROM categories WHERE category_id=:i"), {"i": cid})
        _log(conn, "카테고리 삭제", str(cid), {"name": cur["name"]}, kind="category")
    return {"verdict": f"'{cur['name']}' 카테고리를 지웠습니다"}


# ── 마진 정책 ─────────────────────────────────────────────────────────
# 이 트리가 마진을 정한다(2026-08-05). 예전엔 `category_margin_policies`가 자유
# 문자열 키에 0행이었고 어느 화면도 저장하지 않았다 — 표만 있고 이어지지 않은
# 죽은 테이블이었다. 이제 노드에 걸고 아래로 상속시킨다.

class MarginBody(BaseModel):
    margin_rate: float | None = None      # null = 이 노드의 값을 지운다(상속으로 되돌림)


def _subtree_products(conn, cid: int) -> int:
    """이 노드가 마진을 정하게 되는 상품 수 — 자손까지 센다."""
    return conn.execute(text(
        "SELECT count(*) FROM products WHERE category_id IN ("
        "  WITH RECURSIVE t AS ("
        "    SELECT category_id FROM categories WHERE category_id = :i"
        "    UNION ALL"
        "    SELECT c.category_id FROM categories c JOIN t ON c.parent_id = t.category_id"
        "  ) SELECT category_id FROM t)"), {"i": cid}).scalar()


@router.put("/categories/{cid}/margin")
def set_margin(cid: int, body: MarginBody):
    """노드에 마진을 걸거나(값) 지운다(null → 상속으로 되돌림).

    **판매가를 여기서 바꾸지 않는다.** 다음 재산정에서 쓰인다 — 응답이 그 사실과
    영향을 받는 상품 수를 함께 말한다. 값만 저장하고 조용히 있으면 운영자는
    가격이 이미 바뀐 줄 안다.
    """
    _operator()
    r = body.margin_rate
    if r is not None and not (0 <= float(r) < 1):
        raise HTTPException(400, "마진율은 0 이상 1 미만이어야 합니다(0.13 = 13%)")

    with engine.begin() as conn:
        cur = conn.execute(text(
            "SELECT name FROM categories WHERE category_id=:i"), {"i": cid}).mappings().first()
        if cur is None:
            raise HTTPException(404, "카테고리를 찾을 수 없습니다")
        before = conn.execute(text(
            "SELECT margin_rate FROM category_margin_policies WHERE category_id=:i"),
            {"i": cid}).scalar()

        if r is None:
            if before is None:
                raise HTTPException(400, "이 분류에 직접 걸린 마진이 없습니다")
            conn.execute(text(
                "DELETE FROM category_margin_policies WHERE category_id=:i"), {"i": cid})
        else:
            conn.execute(text(
                "INSERT INTO category_margin_policies (category_id, margin_rate, updated_at)"
                " VALUES (:i, :m, now())"
                " ON CONFLICT (category_id) DO UPDATE SET"
                "   margin_rate = EXCLUDED.margin_rate, updated_at = now()"),
                {"i": cid, "m": float(r)})

        n = _subtree_products(conn, cid)
        _log(conn, "카테고리 마진", str(cid),
             {"name": cur["name"], "from": float(before) if before is not None else None,
              "to": float(r) if r is not None else None, "products": n}, kind="price")

    if r is None:
        return {"verdict": f"'{cur['name']}' 마진을 지웠습니다 — 상위 분류를 따릅니다",
                "products": n,
                "note": ("**판매가는 지금 바뀌지 않습니다.**"
                         " 반영하려면 [판매가 재산정](reprice.html)에서 미리보기 후 확인하세요."),
                "reprice_href": "reprice.html"}
    return {"verdict": f"'{cur['name']}' 마진을 {float(r) * 100:.1f}%로 정했습니다",
            "products": n,
            "note": (f"이 분류와 하위의 **{n:,}건**이 다음 재산정에서 이 마진을 씁니다."
                     " **판매가는 지금 바뀌지 않습니다** —"
                     " [판매가 재산정](reprice.html)에서 미리보기 후 확인하세요."),
            "reprice_href": "reprice.html"}
