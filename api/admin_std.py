# -*- coding: utf-8 -*-
"""조립 사양 표준 관리 — `std.spec_defs` (2026-08-11)

■ 왜 사람이 항목을 추가할 수 있어야 하나
  사용자 방침: *"모자란 사양이 있다면 사용자가 직접 필요한 내용을 추가할 수 있도록
  UI를 만들면 된다. 없는 스펙을 전부 맞출려고 하지 마라 — 일부는 사람에게 남겨두면 된다."*

  표준 49항목은 우리가 호환성 22쌍에서 역산한 것이다. 실제로 조립을 해 보면
  **우리가 생각 못 한 축**이 나온다(라디에이터 두께가 그렇게 늦게 발견됐다).
  그때마다 마이그레이션을 기다리면 현장이 멈춘다.

■ EAV라서 **컬럼을 만들 필요가 없다**
  `std.part_specs` 는 (상품, 필드) 행이라 정의를 하나 넣으면 바로 값을 받을 수 있다.
  기존 `public.spec_field_defs` 는 wide 라 ALTER + 마이그레이션 파일 기록이 필요했고,
  그 파일 쓰기가 배포 서버에서 실패한 전례가 있다(슬라이스 81 `cpu_gpu`).
  **그 실패 경로가 여기엔 없다.**

■ 삭제는 열지 않는다
  정의를 지우면 그 값이 어디에도 안 남는다(FK CASCADE 가 아니라 RESTRICT 다).
  쓰지 않을 항목은 `part_types` 를 비워 감춘다 — 값은 남고 판정에서만 빠진다.
"""
import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .db import engine
from .taxonomy import PART_LABELS

router = APIRouter(prefix="/api/admin/std", tags=["admin-std"])

# 관계표(0040)가 가리키지만 **아직 `part_type` 이 아닌** 것들 — 그래서 `PART_LABELS`
# 에 없다. 팬·확장카드·ODD 는 지금 `ETC` 에 묻혀 있고, 분류를 세우는 것이 F 그룹의
# 첫 일감이다. 이름을 여기 따로 두는 이유: 정본(`taxonomy.PART_LABELS`)은 엔진이
# 읽는 닫힌 집합이라 **화면 사정으로 늘리지 않는다.**
PENDING_LABELS = {"FAN": "팬", "EXPANSION": "확장카드", "ODD": "광학드라이브",
                  "구성 전체": "구성 전체"}

TYPES = {"INT": "정수", "NUM": "소수", "TEXT": "짧은 글자", "BOOL": "예/아니오", "LIST": "목록"}
# 조감도와 같은 번호 체계. 새 관계를 만들 수는 없다 — 그건 설계 결정이라 문서가 먼저다.
PAIRS = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",
         "B1", "B2", "B3", "B4", "B5", "B6", "C1", "C2", "C3", "C4",
         "D1", "D2", "D3", "E1", "F1", "F2", "F3", "F4", "F5"]
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
# 이미 다른 뜻으로 쓰이는 이름 — 겹치면 판정이 조용히 틀어진다
RESERVED = {"product_code", "field_key", "part_type", "source", "source_ref",
            "value_text", "value_num", "value_json", "locked", "updated_at",
            "confidence", "verified_by", "verified_at"}


def _core_types(conn) -> list:
    return [r[0] for r in conn.execute(text(
        "SELECT DISTINCT part_type FROM products"
        " WHERE category_group='core_part' ORDER BY 1")).all()]


@router.get("/spec-defs")
def list_defs(part: str | None = None):
    """표준 항목 목록 + **재고 있는 상품 기준 충족률**.

    충족률을 함께 주는 이유: 항목이 있다는 것과 값이 있다는 것은 다르다.
    화면이 그 둘을 섞으면 "표준을 세웠다"는 착각을 만든다.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            WITH need AS (
              SELECT p.product_code, p.part_type, d.field_key
              FROM products p JOIN std.spec_defs d ON d.part_types ? p.part_type
              WHERE p.status='판매중' AND p.stock_qty>0 AND p.category_group='core_part'),
            fill AS (
              SELECT n.field_key, n.part_type, COUNT(*) AS need,
                     COUNT(s.field_key) AS got
              FROM need n LEFT JOIN std.part_specs s
                ON s.product_code=n.product_code AND s.field_key=n.field_key
              GROUP BY 1,2)
            SELECT d.field_key, d.label, d.data_type, d.unit, d.part_types,
                   d.compat_pairs, d.is_blocking, d.is_custom, d.note, d.sort_order,
                   COALESCE(SUM(f.need),0) AS need, COALESCE(SUM(f.got),0) AS got
            FROM std.spec_defs d LEFT JOIN fill f ON f.field_key = d.field_key
            GROUP BY d.field_key, d.label, d.data_type, d.unit, d.part_types,
                     d.compat_pairs, d.is_blocking, d.is_custom, d.note, d.sort_order
            ORDER BY d.sort_order, d.field_key""")).mappings().all()
        types = _core_types(conn)

    out = []
    for r in rows:
        parts = list(r["part_types"] or [])
        if part and part not in parts:
            continue
        need, got = int(r["need"]), int(r["got"])
        out.append({
            "field_key": r["field_key"], "label": r["label"],
            "data_type": r["data_type"], "unit": r["unit"],
            "part_types": parts, "compat_pairs": list(r["compat_pairs"] or []),
            "is_blocking": r["is_blocking"], "is_custom": r["is_custom"],
            "note": r["note"],
            "need": need, "got": got,
            "pct": round(got * 100 / need) if need else None,
        })
    # /compat-map과 같은 방식(UX-24 ③ · taxonomy.PART_LABELS를 화면이 베끼지 않는다) —
    # 선택지(types)와 각 항목이 실제로 물고 있는 part_types를 함께 훑는다. 지금은
    # 후자가 전자의 부분집합이지만(실측: referenced ⊆ types) 미래에도 맞는 계산이다.
    referenced = set(types) | {pt for r in rows for pt in (r["part_types"] or [])}
    return {"items": out, "total": len(out), "part_types": types,
            "types": TYPES, "pairs": PAIRS,
            # 화면이 선택지를 하드코딩하지 않도록 서버가 준다(슬라이스 54 전례)
            "reserved": sorted(RESERVED),
            "part_labels": {k: PART_LABELS.get(k, PENDING_LABELS.get(k, k))
                            for k in sorted(referenced)}}


class DefBody(BaseModel):
    field_key: str
    label: str
    data_type: str
    unit: str | None = None
    part_types: list[str] = []
    compat_pairs: list[str] = []
    is_blocking: bool = True
    note: str | None = None


@router.post("/spec-defs")
def add_def(body: DefBody):
    """표준 항목 추가. **컬럼을 만들지 않는다** — EAV 라 정의 행 하나면 끝이다."""
    key = (body.field_key or "").strip().lower()
    if not KEY_RE.match(key):
        raise HTTPException(400, "키는 영문 소문자로 시작하고 소문자·숫자·밑줄 3~40자여야 합니다")
    if key in RESERVED:
        raise HTTPException(400, f"이미 다른 뜻으로 쓰는 이름입니다: {key}")
    if body.data_type not in TYPES:
        raise HTTPException(400, f"알 수 없는 자료형: {body.data_type}")
    bad = [p for p in body.compat_pairs if p not in PAIRS]
    if bad:
        raise HTTPException(400, f"알 수 없는 호환 관계: {bad}. "
                                 "새 관계는 설계 문서에서 먼저 정합니다")
    label = (body.label or "").strip()
    if not label:
        raise HTTPException(400, "이름(라벨)을 적어 주세요")

    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM std.spec_defs WHERE field_key=:k"),
                        {"k": key}).first():
            raise HTTPException(409, f"이미 있는 항목입니다: {key}")
        types = set(_core_types(conn))
        unknown = [p for p in body.part_types if p not in types]
        if unknown:
            raise HTTPException(400, f"없는 부품 종류입니다: {unknown}")
        nxt = (conn.execute(text(
            "SELECT COALESCE(MAX(sort_order),0)+10 FROM std.spec_defs")).scalar() or 10)
        conn.execute(text(
            "INSERT INTO std.spec_defs"
            " (field_key, label, data_type, unit, part_types, required_for,"
            "  compat_pairs, is_blocking, is_custom, note, sort_order)"
            " VALUES (:k, :l, :t, :u, CAST(:p AS JSONB), CAST('[]' AS JSONB),"
            "         CAST(:c AS JSONB), :b, true, :n, :s)"),
            {"k": key, "l": label[:60], "t": body.data_type,
             "u": (body.unit or "").strip()[:10] or None,
             "p": json.dumps(body.part_types, ensure_ascii=False),
             "c": json.dumps(body.compat_pairs), "b": body.is_blocking,
             "n": (body.note or "").strip() or None, "s": nxt})

    return {"ok": True, "field_key": key,
            # 무엇이 일어났는지 화면이 그대로 말하게 한다(건수가 아니라 영향)
            "verdict": f"항목 «{label}» 을 추가했습니다. "
                       f"적용 대상 {len(body.part_types)}종 · "
                       f"{'조립을 막는' if body.is_blocking else '경고만 하는'} 항목입니다. "
                       "값은 아직 0건이라 지금은 판정에 쓰이지 않습니다."}


class DefEditBody(BaseModel):
    """UX-24 확정: 편집은 **이름·단위·메모만**. 키·자료형은 여기서 받지 않는다 —
    받아 놓고 무시하면 다음 사람이 «되는 줄» 안다. 이미 저장된 값(std.part_specs)의
    해석이 깨지기 때문에 막은 것이지 빠뜨린 것이 아니다. 적용 부품은 `/part-types`가
    맡는다(다른 동사·다른 위험이라 갈랐다 — 이름을 고치다 부품을 잘못 건드리지 않는다)."""
    label: str
    unit: str | None = None
    note: str | None = None


@router.patch("/spec-defs/{field_key}")
def edit_def(field_key: str, body: DefEditBody):
    """이름·단위·메모를 고친다. 키·자료형·적용 부품·호환 관계는 이 경로로 못 바꾼다."""
    label = (body.label or "").strip()
    if not label:
        raise HTTPException(400, "이름(라벨)을 적어 주세요")
    with engine.begin() as conn:
        cur = conn.execute(text(
            "SELECT label FROM std.spec_defs WHERE field_key=:k"),
            {"k": field_key}).first()
        if not cur:
            raise HTTPException(404, "없는 항목입니다")
        conn.execute(text(
            "UPDATE std.spec_defs SET label=:l, unit=:u, note=:n WHERE field_key=:k"),
            {"k": field_key, "l": label[:60],
             "u": (body.unit or "").strip()[:10] or None,
             "n": (body.note or "").strip() or None})
    return {"ok": True, "field_key": field_key,
            "verdict": f"«{label}» 이름·단위·메모를 저장했습니다 — 키·자료형은 그대로입니다."}


class ApplyBody(BaseModel):
    part_types: list[str]


@router.patch("/spec-defs/{field_key}/part-types")
def set_part_types(field_key: str, body: ApplyBody):
    """적용 대상을 바꾼다 — **쓰지 않을 항목을 감추는 유일한 방법**이다(삭제는 없다).

    비우면 어떤 부품도 이 항목을 요구하지 않는다. 값은 그대로 남는다.
    """
    with engine.begin() as conn:
        cur = conn.execute(text(
            "SELECT part_types, label FROM std.spec_defs WHERE field_key=:k"),
            {"k": field_key}).first()
        if not cur:
            raise HTTPException(404, "없는 항목입니다")
        types = set(_core_types(conn))
        unknown = [p for p in body.part_types if p not in types]
        if unknown:
            raise HTTPException(400, f"없는 부품 종류입니다: {unknown}")
        before = list(cur[0] or [])
        conn.execute(text(
            "UPDATE std.spec_defs SET part_types = CAST(:p AS JSONB) WHERE field_key=:k"),
            {"k": field_key, "p": json.dumps(body.part_types, ensure_ascii=False)})
    added = sorted(set(body.part_types) - set(before))
    removed = sorted(set(before) - set(body.part_types))
    bits = []
    if added:
        bits.append("추가 " + ",".join(added))
    if removed:
        bits.append("제외 " + ",".join(removed) + " (값은 남습니다)")
    return {"ok": True, "verdict": f"«{cur[1]}» 적용 대상 변경 — " + (" · ".join(bits) or "변화 없음")}


@router.get("/compat-map")
def compat_map():
    """조립 호환 지도 — **관계 22쌍 · 부품별 사양 · 충족률**을 한 번에 준다.

    화면이 관계 이름·비교 항목을 지어내지 않도록 **전부 서버가 준다.**
    지금까지 그 정보는 설계 문서와 조감도 HTML 에만 있었다(0040 에서 DB 로 옮겼다).

    `rule_key` 가 채워진 쌍은 엔진이 실제로 검사한다(`public.compat_rules`).
    비어 있으면 **관계는 알지만 아직 검사하지 않는다** — 그 차이가 이 화면의 요점이다.
    """
    with engine.connect() as conn:
        groups = [dict(r) for r in conn.execute(text(
            "SELECT group_key, label, note FROM std.compat_groups ORDER BY sort_order")
        ).mappings().all()]

        pairs = [dict(r) for r in conn.execute(text(
            "SELECT p.pair_key, p.group_key, p.left_part, p.right_part, p.compares,"
            "       p.rule_key, p.in_scope, p.note,"
            "       (r.rule_key IS NOT NULL) AS rule_active, r.label AS rule_label"
            "  FROM std.compat_pairs p"
            "  LEFT JOIN compat_rules r ON r.rule_key = p.rule_key AND r.active"
            " ORDER BY p.sort_order")).mappings().all()]

        # 부품별 사양 + 충족률 — 재고 있는 판매중 코어 부품 기준
        specs = conn.execute(text("""
            WITH need AS (
              SELECT p.product_code, p.part_type, d.field_key, d.label, d.unit,
                     d.compat_pairs, d.is_blocking, d.is_custom
              FROM products p JOIN std.spec_defs d ON d.part_types ? p.part_type
              WHERE p.status='판매중' AND p.stock_qty>0 AND p.category_group='core_part')
            SELECT n.part_type, n.field_key, n.label, n.unit, n.compat_pairs,
                   n.is_blocking, n.is_custom,
                   COUNT(*) AS need, COUNT(s.field_key) AS got
            FROM need n LEFT JOIN std.part_specs s
              ON s.product_code=n.product_code AND s.field_key=n.field_key
            GROUP BY 1,2,3,4,5,6,7
            ORDER BY 1, 6 DESC, 9 DESC""")).mappings().all()

        stock = {r[0]: r[1] for r in conn.execute(text(
            "SELECT part_type, COUNT(*) FROM products"
            " WHERE status='판매중' AND stock_qty>0 AND category_group='core_part'"
            " GROUP BY 1")).all()}

    by_part: dict = {}
    for r in specs:
        pt = r["part_type"]
        d = by_part.setdefault(pt, {"part_type": pt, "name": PART_LABELS.get(pt, pt),
                                    "stock": stock.get(pt, 0), "specs": []})
        d["specs"].append({
            "field_key": r["field_key"], "label": r["label"], "unit": r["unit"],
            "pairs": list(r["compat_pairs"] or []), "is_blocking": r["is_blocking"],
            "is_custom": r["is_custom"],
            "pct": round(int(r["got"]) * 100 / int(r["need"])) if r["need"] else None,
        })
    for d in by_part.values():
        blocking = [s for s in d["specs"] if s["is_blocking"]]
        d["total"] = len(d["specs"])
        d["blocking"] = len(blocking)
        d["zero"] = len([s for s in d["specs"] if s["pct"] == 0])
        # 부품 단위 충족률 = **막는 항목만** 센다. 경고 항목이 채워졌다고
        # 조립을 보증할 수 있는 것은 아니다.
        d["pct"] = round(sum(s["pct"] for s in blocking) / len(blocking)) if blocking else None

    # 쌍마다 어떤 사양이 얽히는지 — 한쪽만 있으면 판정할 수 없다
    for p in pairs:
        rel = []
        for pt, d in by_part.items():
            for s in d["specs"]:
                if p["pair_key"] in s["pairs"]:
                    rel.append({"part_type": pt, "field_key": s["field_key"],
                                "label": s["label"], "pct": s["pct"],
                                "is_blocking": s["is_blocking"]})
        p["specs"] = rel
        p["parts_involved"] = sorted({x["part_type"] for x in rel})
        # 값이 하나라도 0%면 그 쌍은 판정이 반쪽이다
        p["ready"] = bool(rel) and all((x["pct"] or 0) > 0 for x in rel)
        # **상태는 서버가 정한다.** 화면 셋(지도·진단·매트릭스)이 같은 데이터를 쓰는데
        # 각자 파생하면 세 곳에서 어긋난다. 회귀도 이 한 값만 보면 된다.
        p["status"] = ("out" if not p["in_scope"] else
                       "checking" if p["rule_active"] else
                       "norule" if p["ready"] else "missing")

    # 지도에는 재고가 없는 종류도 노드로 선다(모니터·팬·확장카드·ODD).
    # 그 이름까지 화면이 지어내지 않도록 **참조된 전부**를 여기서 준다.
    referenced = {x for p in pairs for x in (p["left_part"], p["right_part"])} | set(by_part)
    return {
        "groups": groups, "pairs": pairs,
        "part_labels": {k: PART_LABELS.get(k, PENDING_LABELS.get(k, k))
                        for k in sorted(referenced)},
        "parts": sorted(by_part.values(), key=lambda d: -d["total"]),
        "summary": {
            "pairs_total": len(pairs),
            "pairs_in_scope": len([p for p in pairs if p["in_scope"]]),
            "pairs_checked": len([p for p in pairs if p["rule_active"]]),
            "pairs_ready": len([p for p in pairs if p["in_scope"] and p["ready"]]),
            "specs_total": sum(d["total"] for d in by_part.values()),
        },
    }
