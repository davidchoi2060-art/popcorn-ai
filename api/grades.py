# -*- coding: utf-8 -*-
"""부품 등급 — "얼마나 좋은가"의 **단일 원천** (재설계안 §3-① · 2026-08-07).

■ 이 축이 왜 생겼나
  엔진이 읽는 사양 22종은 전부 **호환**(소켓·전력·길이·규격)과 **취향**(RGB·저소음·화이트)
  이다. CPU 와 GPU 에 성능 지표가 하나도 없다. 그래서 거르고 남은 것 중 **가장 싼 것**이
  뽑힌다. "최선의 부품"이라 말하면서 최저가를 고르고 있었다.

■ 점수는 **슬롯 안에서만** 뜻을 갖는다
  GPU 80점과 CPU 80점은 같은 뜻이 아니다. 슬롯 간 환산은 하지 않는다 — 하려면 근거가
  필요한데 우리에겐 없다. 가성비(점수/가격)도 슬롯 안에서만 비교한다.

■ 근거가 없으면 등급도 없다
  `basis` 는 스키마에서 NOT NULL 이고 공백도 막는다(0032). 여기서 한 번 더 막는 이유는
  **화면에 이유를 말해 주기 위해서**다 — DB 오류를 그대로 내보내면 운영자는 무엇이
  잘못됐는지 모른다. 지어낸 태그를 금지한 것과 같은 규칙이다.

■ 엔진은 아직 이 값을 읽지 않는다
  축만 만들고 값이 찬 뒤에 연결한다. 지금 연결하면 등급 없는 부품이 전부 0점이 되거나
  등급 있는 소수만 추천되거나 둘 중 하나인데, 둘 다 지금보다 나쁘다.
  완제품 축(0031)과 같은 순서다. 회귀가 "엔진이 아직 등급을 읽지 않는다"를 지킨다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .auth import current_operator_id
from .db import engine
from .taxonomy import CORE_TYPES, PART_LABELS, choice_tree, expand_display

router = APIRouter(prefix="/api/admin")

# 등급을 매길 수 있는 슬롯 — **조립 부품만**이다.
# 주변기기·완제품에 등급을 매기는 것은 다른 판단이고(비교 축이 다르다) 지금 열지 않는다.
GRADABLE = tuple(CORE_TYPES)


def _slot_choices() -> list[dict]:
    """화면이 고를 슬롯 목록.

    **고르는 자리의 정본은 `taxonomy.choice_tree` 하나다**(A-32). 여기서 라벨을 다시
    만들면 쿨러가 이 화면에서만 둘로 갈라진다. 다만 등급은 공랭·수랭을 나눠 매길 이유가
    없어(같은 슬롯 안의 서열이다) 접힌 키를 그대로 쓰고 `options` 는 버린다.
    """
    return [{"key": e["key"], "label": e["label"]} for e in choice_tree(GRADABLE)]


@router.get("/grades/meta")
def grades_meta():
    """화면이 필요로 하는 어휘 — 슬롯 목록과 척도 설명."""
    return {
        "slots": _slot_choices(),
        "scale": {
            "min": 0, "max": 100,
            # 화면이 이 문구를 그대로 쓴다 — 척도의 뜻을 두 곳에 적지 않는다.
            "note": ("0~100 점. **같은 슬롯 안에서만** 비교됩니다 — "
                     "그래픽카드 80점과 CPU 80점은 같은 뜻이 아닙니다."),
        },
        "basis_required": True,
        "engine_reads": False,
        "engine_note": ("등급은 아직 견적 엔진이 읽지 않습니다. "
                        "값이 채워진 뒤에 연결합니다 — 지금 연결하면 등급 없는 부품이 "
                        "전부 0점으로 취급됩니다."),
    }


@router.get("/grades")
def list_grades(slot: str, q: str | None = None, only: str | None = None,
                page: int = 1, size: int = 100):
    """슬롯 하나의 서열표. **등급 없는 것도 함께** 보여준다 — 빈칸이 곧 할 일이다.

    `only=graded|ungraded` 로 좁힌다. 목록은 서버가 나눈다(전 행 반환 금지).
    """
    types = expand_display(slot) or (slot,)
    bad = [t for t in types if t not in GRADABLE]
    if bad:
        raise HTTPException(400, "등급을 매길 수 없는 종류입니다: " + ", ".join(bad))
    if only not in (None, "", "graded", "ungraded"):
        raise HTTPException(400, "only 는 graded 또는 ungraded 입니다")

    page = max(1, int(page or 1))
    size = min(200, max(1, int(size or 100)))

    where = ["p.part_type = ANY(:types)"]
    params: dict = {"types": list(types), "lim": size, "off": (page - 1) * size}
    if q:
        where.append("(p.product_name ILIKE :q OR p.product_code::text = :qe)")
        params["q"] = "%" + q.strip() + "%"
        params["qe"] = q.strip()
    if only == "graded":
        where.append("g.product_code IS NOT NULL")
    elif only == "ungraded":
        where.append("g.product_code IS NULL")
    w = " AND ".join(where)

    with engine.connect() as c:
        total = c.execute(text(
            "SELECT count(*) FROM products p"
            " LEFT JOIN part_grades g USING (product_code) WHERE " + w), params).scalar_one()
        rows = c.execute(text(
            "SELECT p.product_code, p.product_name, p.part_type, p.sale_price, p.stock_qty,"
            "       g.grade, g.basis, g.source, g.graded_at,"
            "       (v.product_code IS NOT NULL) AS in_pool"
            " FROM products p"
            " LEFT JOIN part_grades g USING (product_code)"
            " LEFT JOIN v_recommendation_candidates v USING (product_code)"
            " WHERE " + w +
            # 등급 있는 것이 위, 그 안에서 점수 높은 순. 등급 없는 것은 비싼 것부터 —
            # 비싼 부품일수록 견적에 미치는 영향이 커서 먼저 매길 값이 있다.
            " ORDER BY (g.grade IS NULL), g.grade DESC NULLS LAST,"
            "          p.sale_price DESC NULLS LAST, p.product_code"
            " LIMIT :lim OFFSET :off"), params).mappings().all()
        # 슬롯 전체의 채움 상태 — 화면이 "얼마나 남았나"를 말한다
        cov = c.execute(text(
            "SELECT count(*) AS total,"
            "       count(g.product_code) AS graded,"
            "       count(*) FILTER (WHERE v.product_code IS NOT NULL) AS pool,"
            "       count(g.product_code) FILTER (WHERE v.product_code IS NOT NULL) AS pool_graded"
            " FROM products p"
            " LEFT JOIN part_grades g USING (product_code)"
            " LEFT JOIN v_recommendation_candidates v USING (product_code)"
            " WHERE p.part_type = ANY(:types)"), {"types": list(types)}).mappings().first()

    return {
        "slot": slot,
        "slot_label": dict((s["key"], s["label"]) for s in _slot_choices()).get(slot, slot),
        "page": page, "size": size, "total": total,
        "pages": max(1, -(-total // size)),
        "coverage": dict(cov),
        # **추천 후보 안의 채움률이 실제 진척이다.** 카탈로그 전체는 품절이 대부분이라
        # 그 비율을 보면 영원히 낮아 보이고, 운영자는 끝이 없다고 느낀다.
        "note": ("추천 후보 %d개 중 %d개에 등급이 있습니다. "
                 "카탈로그 전체(%d개)에는 품절이 많이 섞여 있어 후보 기준으로 셉니다."
                 % (cov["pool"], cov["pool_graded"], cov["total"])),
        "items": [dict(r, part_label=PART_LABELS.get(r["part_type"], r["part_type"]))
                  for r in rows],
    }


class GradeBody(BaseModel):
    grade: int
    basis: str
    source: str | None = None


@router.put("/grades/{product_code}")
def set_grade(product_code: int, body: GradeBody):
    """등급을 넣거나 고친다. **근거가 없으면 거부한다.**"""
    if not (0 <= body.grade <= 100):
        raise HTTPException(400, "등급은 0~100 사이입니다")
    basis = (body.basis or "").strip()
    if not basis:
        # 스키마도 막지만, 화면에는 **왜 막혔는지**를 말해 줘야 한다.
        raise HTTPException(400, "근거를 적어 주세요 — 근거 없는 등급은 저장하지 않습니다")

    with engine.begin() as c:
        row = c.execute(text(
            "SELECT part_type FROM products WHERE product_code=:pc"),
            {"pc": product_code}).first()
        if row is None:
            raise HTTPException(404, "없는 상품입니다")
        if row[0] not in GRADABLE:
            raise HTTPException(
                400, "조립 부품에만 등급을 매깁니다 — 이 상품은 %s 입니다"
                     % PART_LABELS.get(row[0], row[0]))
        before = c.execute(text(
            "SELECT grade, basis, source FROM part_grades WHERE product_code=:pc"),
            {"pc": product_code}).mappings().first()
        c.execute(text(
            "INSERT INTO part_grades (product_code, grade, basis, source, graded_by)"
            " VALUES (:pc, :g, :b, :s, :op)"
            " ON CONFLICT (product_code) DO UPDATE SET"
            "   grade=EXCLUDED.grade, basis=EXCLUDED.basis, source=EXCLUDED.source,"
            "   graded_by=EXCLUDED.graded_by, updated_at=now()"),
            {"pc": product_code, "g": body.grade, "b": basis,
             "s": (body.source or "").strip() or None, "op": current_operator_id()})
        # 원장에 남긴다 — 사람의 판단이므로 누가 언제 무엇을 바꿨는지 되짚을 수 있어야 한다.
        c.execute(text(
            "INSERT INTO admin_operator_activity_logs"
            " (operator_id, action, target_kind, target_id, detail)"
            " VALUES (:op, 'grade_set', 'product', :pc, CAST(:d AS jsonb))"),
            {"op": current_operator_id(), "pc": str(product_code),
             "d": _json({"before": dict(before) if before else None,
                         "after": {"grade": body.grade, "basis": basis,
                                   "source": (body.source or "").strip() or None}})})
    return {"ok": True, "product_code": product_code, "grade": body.grade,
            "note": "등급 %d 로 저장했습니다. 견적 엔진은 아직 이 값을 읽지 않습니다." % body.grade}


@router.delete("/grades/{product_code}")
def clear_grade(product_code: int):
    """등급을 지운다 — 잘못 매긴 것을 되돌리는 길."""
    with engine.begin() as c:
        before = c.execute(text(
            "SELECT grade, basis, source FROM part_grades WHERE product_code=:pc"),
            {"pc": product_code}).mappings().first()
        if before is None:
            raise HTTPException(404, "등급이 없습니다")
        c.execute(text("DELETE FROM part_grades WHERE product_code=:pc"), {"pc": product_code})
        c.execute(text(
            "INSERT INTO admin_operator_activity_logs"
            " (operator_id, action, target_kind, target_id, detail)"
            " VALUES (:op, 'grade_clear', 'product', :pc, CAST(:d AS jsonb))"),
            {"op": current_operator_id(), "pc": str(product_code),
             "d": _json({"before": dict(before), "after": None})})
    return {"ok": True, "note": "등급을 지웠습니다."}


def _json(o) -> str:
    import json
    return json.dumps(o, ensure_ascii=False, default=str)
