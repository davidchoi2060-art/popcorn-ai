"""상품 카테고리 매핑 (ADM-CAT-020) — 슬라이스 C.

슬라이스 B가 트리를 세우고 `part_type` 17종을 1단으로 깔았다. 그래서 지금은 전량 매핑돼
있지만, **`미분류` 하나에 5,148건(재고>0 2,415건)이 몰려 있다.** 그 안에는 케이블 473 ·
USB 144 · 쿨링부자재 141 · 마우스패드 · 캡처보드 · 확장카드 · 시스템팬 · 그래픽카드 지지대,
그리고 PC와 무관한 "한경희 미니 건조기"까지 들어 있다.

이 화면이 하는 일은 **그 덩어리를 사람이 갈라내는 것**이다.

■ 기본 화면이 '문제'다
기존 임대 관리자는 미매핑 1,458건(판매중 325건)을 별도 화면(`카테고리매핑오류`)에 넣어
두고 방치했다. 여기서는 **처리할 것이 있으면 그것을 먼저 보여준다** — 미매핑과
허용 종류 위반이 목록의 기본 필터다. 없으면 그때 전체를 본다.

■ 되돌릴 수 있다
일괄 이동은 한 번에 수천 건을 옮긴다. 잘못 옮기면 되돌릴 길이 있어야 한다.
원장 규약을 그대로 따른다 — 삭제가 아니라 **역방향 전이**이고, 되돌림 로그는
`ref_log_id`로 원 기록을 가리킨다(활동 로그가 그 키로 '되돌려짐' 배지를 파생한다).
이동 전 각 상품의 카테고리를 로그 detail에 담아 두므로 **부분 이동도 정확히 복구된다.**

■ 막지 않고 알린다
`allowed_part_types`를 어기는 이동도 **허용한다.** 운영자가 "이건 여기 둬야 한다"고
판단할 수 있고(예: 겸용 부품), 막으면 이유도 모른 채 벽을 만난다. 대신 응답이
위반 건수를 돌려주고 화면이 그것을 말한다.

■ 상한을 숨기지 않는다
한 번에 옮길 수 있는 수에 상한이 있다(`MAX_MOVE`). 상한에 걸리면 **몇 건이 빠졌는지
응답이 밝힌다** — 조용한 절단은 "다 옮겼다"로 읽힌다.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import _log
from .auth import current_operator
from .db import engine
from .taxonomy import DISPLAY_LABELS, PART_LABELS, expand_display

router = APIRouter(prefix="/api/admin")

MAX_MOVE = 2000        # 한 번에 옮길 수 있는 상한. 넘으면 응답이 빠진 수를 밝힌다.
MAX_PAGE = 500


def _operator():
    me = current_operator() or {}
    if me.get("role") not in ("owner", "operator"):
        raise HTTPException(403, "운영자 이상만 매핑을 바꿀 수 있습니다")
    return me


# scope: 'unmapped'(미매핑) · 'violation'(허용 종류 위반) · 'category'(특정 카테고리) · 'all'
_WHERE = {
    "unmapped":  "p.category_id IS NULL",
    "violation": ("p.category_id IS NOT NULL AND c.allowed_part_types IS NOT NULL"
                  " AND NOT (c.allowed_part_types @> to_jsonb(p.part_type))"),
    # 적재가 부품 종류를 못 정한 것. **카테고리가 아니라 part_type 으로 센다** —
    # 예전엔 "allowed_part_types 가 정확히 ['ETC'] 인 카테고리"를 찾아 그 id를 줬는데,
    # 미분류를 갈라내며 그 조건에 맞는 카테고리가 13개가 되자 첫 번째(쿨링·튜닝)를 가리켰다.
    # 탭은 5,148이라 말하고 목록은 1,668을 보여주는 상태였다(2026-08-05 발견).
    "unclassified": "p.part_type = 'ETC'",
    "category":  "p.category_id = :cid",
    # 트리에서 상위 노드를 누르면 그 아래 전부를 본다. 재귀 CTE로 자손을 모은다 —
    # 깊이를 저장하지 않기로 했으므로(슬라이스 B) 질의 때마다 훑는 것이 맞다.
    "subtree":   ("p.category_id IN (WITH RECURSIVE t AS ("
                  "   SELECT category_id FROM categories WHERE category_id = :cid"
                  "   UNION ALL"
                  "   SELECT c2.category_id FROM categories c2 JOIN t ON c2.parent_id = t.category_id"
                  " ) SELECT category_id FROM t)"),
    "all":       "TRUE",
}


def _common_filters(q, part_type, in_stock):
    """검색어·부품 종류·재고 — **scope(탭 축)를 뺀 나머지 필터만**.

    탭 배지 4종(미매핑·위반·미분류·전체)은 서로 다른 scope 조건을 각자 갖고 있어
    하나의 WHERE로 합칠 수 없다. 그래서 scope를 뺀 이 부분만 따로 만들어 각 배지가
    "자기 scope AND 이 공통 필터"로 쓴다 — `_filters()`도 이 위에 scope 하나만 더
    얹는 식으로 다시 짰다(결함 ①, 2026-09-02 수정: 이전엔 `mapping()`의 `counts` 질의가
    이 필터를 전혀 받지 않아, 탭 배지가 검색어·부품 종류·재고 필터와 무관하게 늘
    전체 상품 기준이었다 — 정의서 `req-product-category-map.md:123-125`).
    """
    where = []
    p = {"q": (q or "").strip(), "pt": (part_type or "").strip()}
    if p["q"]:
        where.append("(p.product_name ILIKE '%' || :q || '%'"
                     " OR CAST(p.product_code AS TEXT) = :q)")
    if p["pt"]:
        # 화면이 보내는 것은 **표시 종류**다(쿨러 하나). 실제 part_type 으로 풀어서 건다 —
        # 'COOLER' 를 그대로 비교하면 그런 part_type 은 없어서 **0건**이 나온다.
        p["pts"] = list(expand_display(p["pt"]))
        where.append("p.part_type = ANY(:pts)")
    if in_stock:
        where.append("p.stock_qty > 0")
    return where, p


def _filters(scope, cid, q, part_type, in_stock):
    common, p = _common_filters(q, part_type, in_stock)
    where = [_WHERE.get(scope, "TRUE")] + common
    p["cid"] = cid
    return " AND ".join(where), p


@router.get("/category-mapping")
def mapping(scope: str = "unmapped", category_id: int | None = None, q: str = "",
            part_type: str = "", in_stock: bool = False, page: int = 1, size: int = 100):
    if scope not in _WHERE:
        raise HTTPException(400, "알 수 없는 범위입니다")
    if scope in ("category", "subtree") and category_id is None:
        raise HTTPException(400, "카테고리를 선택하세요")
    size = max(1, min(size, MAX_PAGE))
    page = max(1, page)
    where, p = _filters(scope, category_id, q, part_type, in_stock)
    p.update(size=size, offset=(page - 1) * size)

    join = " LEFT JOIN categories c ON c.category_id = p.category_id"
    # counts 전용 — scope 뺀 공통 필터(검색어·부품 종류·재고)만 별도로 짓는다. `p`(위
    # `_filters()` 결과, total·rows 질의가 쓴다)와는 **별개 딕셔너리**로 바인딩하므로
    # 이름이 같은 `:q`·`:pts`가 있어도 섞이지 않는다 — counts 질의는 이 `common_p`만 쓴다.
    common_where, common_p = _common_filters(q, part_type, in_stock)
    common_sql = "".join(" AND " + c for c in common_where)
    with engine.connect() as conn:
        total = conn.execute(text(
            f"SELECT count(*) FROM products p{join} WHERE {where}"), p).scalar()
        rows = conn.execute(text(
            "SELECT p.product_code, p.product_name, p.part_type, p.sale_price,"
            "       p.stock_qty, p.status, p.category_id, c.name AS cat,"
            "       c.allowed_part_types"
            f" FROM products p{join} WHERE {where}"
            " ORDER BY p.product_code LIMIT :size OFFSET :offset"), p).mappings().all()
        # 각 범위의 크기를 항상 함께 준다 — 운영자가 '남은 일'을 화면 하나에서 본다.
        # **scope 뺀 공통 필터(common_sql)를 얹는다**(결함 ①, 2026-09-02 수정) — 정의서
        # 123-125행 "범위별 집계는 현재 페이지가 아니라 그 조건 전체 기준이어야 한다"를
        # 지금까지 어기고 있었다: 이 질의에 필터가 전혀 안 실려 탭 배지 4종(미매핑·위반·
        # 미분류·전체)이 검색어·부품 종류·재고 필터와 무관하게 항상 전체 상품 기준으로
        # 떴다. scope 자체는 배지마다 달라 공통으로 못 쓰므로, 각 FILTER 절에 이 공통
        # 조건만 AND로 덧붙인다(각 배지는 "자기 scope × 공통 필터").
        counts = conn.execute(text(
            f"SELECT count(*) FILTER (WHERE p.category_id IS NULL{common_sql}) AS unmapped,"
            f"       count(*) FILTER (WHERE p.category_id IS NULL AND p.stock_qty > 0{common_sql})"
            "         AS unmapped_stock,"
            "       count(*) FILTER (WHERE p.category_id IS NOT NULL"
            "         AND c.allowed_part_types IS NOT NULL"
            f"         AND NOT (c.allowed_part_types @> to_jsonb(p.part_type)){common_sql}) AS violation,"
            # 적재가 종류를 정하지 못한 것 = 실제 backlog. 미매핑이 0이어도 이건 남아 있다.
            f"       count(*) FILTER (WHERE p.part_type = 'ETC'{common_sql}) AS unclassified,"
            f"       count(*) FILTER (WHERE p.part_type = 'ETC' AND p.stock_qty > 0{common_sql})"
            "         AS unclassified_stock,"
            f"       count(*) FILTER (WHERE TRUE{common_sql}) AS all_products"
            f" FROM products p{join}"), common_p).mappings().one()
        # n = 이 카테고리 직접 · n_sub = 자손까지 합친 수.
        # 트리 배지는 **자손 합계**를 보여야 한다 — 상위 노드에 0이 뜨면 비어 보이는데
        # 실제로는 아래에 수천 건이 있을 수 있다(슬라이스 C에서 빈 화면으로 열린 것과 같은 함정).
        cats = conn.execute(text(
            "SELECT c.category_id, c.parent_id, c.name, c.allowed_part_types, c.is_visible,"
            "       c.sort_order,"
            "       (SELECT count(*) FROM products x WHERE x.category_id = c.category_id) n,"
            "       (SELECT count(*) FROM products x WHERE x.category_id IN ("
            "          WITH RECURSIVE t AS ("
            "            SELECT category_id FROM categories WHERE category_id = c.category_id"
            "            UNION ALL"
            "            SELECT c2.category_id FROM categories c2 JOIN t ON c2.parent_id = t.category_id"
            "          ) SELECT category_id FROM t)) n_sub,"
            "       (SELECT count(*) FROM products x WHERE x.category_id = c.category_id"
            "          AND x.stock_qty > 0) n_stock"
            " FROM categories c ORDER BY c.sort_order, c.name")).mappings().all()

    items = [{
        "product_code": r["product_code"], "name": r["product_name"],
        "part_type": r["part_type"], "part_label": PART_LABELS.get(r["part_type"], r["part_type"]),
        "sale_price": r["sale_price"], "stock_qty": r["stock_qty"],
        "status": r["status"],
        "category_id": r["category_id"], "category": r["cat"],
        # 이 상품이 지금 카테고리의 허용 종류를 어기고 있는가
        "violates": bool(r["allowed_part_types"]
                         and r["part_type"] not in (r["allowed_part_types"] or [])),
    } for r in rows]

    return {
        "items": items, "page": page, "size": size, "total": total,
        "pages": (total + size - 1) // size,
        "scope": scope, "category_id": category_id,
        "counts": dict(counts),
        # 화면이 '일이 있는 곳'으로 열리게 서버가 알려 준다 — 기본 탭이 늘 비어 있으면
        # 운영자는 할 일이 없다고 읽는다(실제로는 미분류에 5천 건이 쌓여 있어도).
        "open_at": ("unmapped" if counts["unmapped"] else
                    "violation" if counts["violation"] else
                    "unclassified" if counts["unclassified"] else "all"),
        # unclassified 는 이제 서버 범위다 — 화면이 카테고리 id로 치환할 필요가 없다.
        "categories": [{"category_id": c["category_id"], "parent_id": c["parent_id"],
                        "name": c["name"], "allowed_part_types": c["allowed_part_types"],
                        "is_visible": c["is_visible"], "sort_order": c["sort_order"],
                        "product_count": c["n"], "subtree_count": c["n_sub"],
                        "in_stock_count": c["n_stock"]} for c in cats],
        # 부품 종류 목록은 **서버가 준다**(taxonomy 단일 원천).
        # 예전엔 화면이 ① 현재 페이지 상품과 ② 카테고리의 allowed_part_types 에서 조립했다.
        # 그래서 탭마다 목록이 달라졌고, ②에서 온 것은 한글 라벨이 없어 `CASE`·`MB`·`GPU`
        # 같은 **영문 키가 그대로** 떴다(17종 중 16종). 카테고리 관리 화면과 다른 목록이
        # 보이는 원인이었다 — 같은 것을 두 곳에서 만들면 갈라진다(슬라이스 66 규약).
        # 고르는 자리는 **표시 종류 18종**(쿨러 하나 — 2026-09-02 정정, 이전엔 "16종"으로
        # 오기돼 있었다. 실측: `api/taxonomy.py` DISPLAY_LABELS len()==18, PART_LABELS
        # 19종에서 공랭·수랭이 한 자리로 접혀 1개 준다). 목록 행의 `part_label`은 그대로
        # 'CPU쿨러(수랭)'이라 적는다 — 고르는 자리를 합치는 것이지 사실을 감추는 게 아니다.
        "part_types": [{"key": k, "label": v} for k, v in DISPLAY_LABELS.items()],
        "max_move": MAX_MOVE,
        "note": ("목록은 서버에서 걸러 페이지로 나눕니다 — 위 건수는 현재 페이지가 아니라"
                 " 조건 전체입니다. 허용 부품 종류를 어기는 이동도 **막지 않습니다**;"
                 " 옮긴 뒤 몇 건이 어긋나는지 알려 드립니다."),
    }


class MoveBody(BaseModel):
    product_codes: list[int]
    category_id: int


@router.post("/category-mapping/move")
def move(body: MoveBody):
    _operator()
    codes = list(dict.fromkeys(body.product_codes or []))     # 중복 제거, 순서 유지
    if not codes:
        raise HTTPException(400, "옮길 상품을 선택하세요")
    dropped = 0
    if len(codes) > MAX_MOVE:
        dropped = len(codes) - MAX_MOVE
        codes = codes[:MAX_MOVE]

    with engine.begin() as conn:
        cat = conn.execute(text(
            "SELECT name, allowed_part_types FROM categories WHERE category_id=:i"),
            {"i": body.category_id}).mappings().first()
        if cat is None:
            raise HTTPException(404, "카테고리를 찾을 수 없습니다")

        # 이동 전 상태를 먼저 읽는다 — 되돌리기의 근거가 된다(부분 이동도 정확히 복구).
        before = conn.execute(text(
            "SELECT product_code, category_id, part_type FROM products"
            " WHERE product_code = ANY(:codes)"), {"codes": codes}).mappings().all()
        if not before:
            raise HTTPException(404, "해당 상품을 찾을 수 없습니다")
        found = {r["product_code"] for r in before}
        missing = [c for c in codes if c not in found]

        # 이미 그 카테고리인 것은 옮길 것이 없다 — 로그를 부풀리지 않는다.
        targets = [r for r in before if r["category_id"] != body.category_id]
        # 결함 ②(2026-09-02 수정): 이 수를 버리지 않는다 — 정의서 128-129행 "이미 그
        # 카테고리인 상품은 자동으로 이동 대상에서 빠지고, 그 사실이 결과에 남는다"·
        # 승인 디자인 dc-product-category-map.html:599 `same.length`와 같은 값이다.
        already = len(before) - len(targets)
        if not targets:
            # 전량이 이미 그 카테고리다 — 옮길 것이 하나도 없어 여기서 끝낸다(승인 디자인
            # 599행 "same.length === picked.length"와 동일 조건). UPDATE 이전이라 쓰기가
            # 전혀 없다 — `already`를 이 에러 본문에 굳이 싣지 않는다(메시지 자체가 이미
            # "전량"이라는 사실을 말한다).
            raise HTTPException(400, "이미 모두 그 카테고리에 있습니다")

        conn.execute(text(
            "UPDATE products SET category_id=:cid, updated_at=now()"
            " WHERE product_code = ANY(:codes)"),
            {"cid": body.category_id, "codes": [r["product_code"] for r in targets]})

        allowed = cat["allowed_part_types"]
        violated = [r["product_code"] for r in targets
                    if allowed and r["part_type"] not in allowed]

        log_id = _log(conn, "카테고리 매핑 이동", str(body.category_id), {
            "to": body.category_id, "to_name": cat["name"], "moved": len(targets),
            "violated": len(violated),
            # 되돌리기용 — 상품별 원래 카테고리
            "before": [{"pc": r["product_code"], "cat": r["category_id"]} for r in targets],
        }, kind="category")

    msg = f"{len(targets):,}건을 '{cat['name']}'(으)로 옮겼습니다"
    if already:
        # 승인 디자인 599행 문구("이미 그 분류였던 N건은 제외")와 같은 말이다.
        msg += f" · 이미 그 분류였던 {already:,}건은 제외했습니다"
    if violated:
        msg += f" · 그중 {len(violated):,}건은 이 카테고리의 허용 부품 종류와 다릅니다"
    if dropped:
        msg += f" · 상한 {MAX_MOVE:,}건을 넘어 {dropped:,}건은 옮기지 않았습니다"
    if missing:
        msg += f" · 없는 상품 {len(missing):,}건은 건너뛰었습니다"
    return {"verdict": msg, "moved": len(targets), "violated": len(violated),
            "dropped": dropped, "missing": len(missing), "already": already, "log_id": log_id}


class UndoBody(BaseModel):
    log_id: int


@router.post("/category-mapping/undo")
def undo(body: UndoBody):
    _operator()
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT detail, action FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": body.log_id}).mappings().first()
        if row is None or row["action"] != "카테고리 매핑 이동":
            raise HTTPException(404, "되돌릴 이동 기록을 찾을 수 없습니다")
        # 이중 되돌리기 가드 — 활동 로그의 '되돌려짐' 배지와 같은 관계로 판정한다.
        dup = conn.execute(text(
            "SELECT 1 FROM admin_operator_activity_logs"
            " WHERE detail->>'ref_log_id' = CAST(:i AS TEXT)"), {"i": body.log_id}).first()
        if dup:
            raise HTTPException(409, "이미 되돌린 기록입니다")

        detail = row["detail"] if isinstance(row["detail"], dict) else json.loads(row["detail"])
        before = detail.get("before") or []
        if not before:
            raise HTTPException(400, "이 기록에는 되돌릴 근거가 없습니다")

        # 역방향 전이 — 상품별로 원래 카테고리를 되돌린다(삭제가 아니다).
        for b in before:
            conn.execute(text(
                "UPDATE products SET category_id=:c, updated_at=now() WHERE product_code=:p"),
                {"c": b.get("cat"), "p": b.get("pc")})

        _log(conn, "카테고리 매핑 이동 되돌림", str(detail.get("to")),
             {"ref_log_id": body.log_id, "restored": len(before)}, kind="category")
    return {"verdict": f"{len(before):,}건을 원래 카테고리로 되돌렸습니다",
            "restored": len(before)}
