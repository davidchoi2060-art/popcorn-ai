"""용도 하한 관리 (ADM-ENG-030) — 슬라이스 75.

용도별 부품 하한(`usage_floors`)은 슬라이스 58에서 만들었지만 **고칠 화면이 없었다.**
값은 내가 실측으로 정한 것 그대로였고, 운영자는 그게 무엇인지도 볼 수 없었다.

이 값은 견적을 직접 바꾼다 — "게임 GPU 550W 이상"을 600으로 올리면 그만큼 후보가
줄고, 어떤 예산에서는 견적이 아예 안 나온다. 그래서 **바꾸기 전에 영향을 보여준다**:
그 하한을 적용하면 후보가 몇 개 남는지 실측해서 알린다.

owner 전용. compat_rules·spec_field_defs와 같은 취급이다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from . import usage_floors as UF
from .auth import current_operator
from .candidates import SLOT_KO
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin")

# 하한을 걸 수 있는 필드 — 값이 채워져 있고 크기 비교가 뜻을 갖는 것만.
# 여기 없는 필드로 하한을 만들면 판정이 늘 실패해 그 슬롯이 전멸한다.
FLOOR_FIELDS = {
    "required_power_watt": {"label": "GPU 권장 전원", "unit": "W",
                            "slots": ["GPU"],
                            "note": "성능 지표가 없어 전력 등급을 근사로 씁니다"},
    "capacity_gb": {"label": "용량", "unit": "GB",
                    "slots": ["RAM", "SSD", "HDD"], "note": ""},
}
# 화면 표시 전용 이름 — 위 FLOOR_FIELDS(편집 대상 목록)는 늘리지 않고, 표에 나오는
# 다른 하한 항목이 영문 키 그대로 보이지 않게만 한다(2026-10-10).
_DISPLAY_ONLY = {"vram_gb": {"label": "그래픽 메모리", "unit": "GB"}}


def _slot_types(slot: str) -> list:
    return ["COOLER_CPU_AIR", "COOLER_CPU_AIO"] if slot == "COOLER" else [slot]


def _pass_count(conn, slot: str, field: str, op: str, value, active: bool) -> int:
    """하한 «한 줄» 기준 통과 수 — 목록 pass_count · 미리보기 pass_before/after 가 이 하나를 쓴다.

    견적 엔진(usage_floors)과 같은 규칙으로 센다(2026-11-03): 비활성 줄은 엔진이 아예
    읽지 않으므로(_rows 의 WHERE active) 이 줄로는 거르지 않는다 — 슬롯 후보 전체가 통과.
    활성이면 passes() 처럼 op(gte/lte)를 그대로 보고 값이 NULL 이면 불통과다.
    같은 용도의 다른 하한은 세지 않는다 — 이 수는 «이 줄» 기준이다(용도 전체 견적 가능 여부 아님).
    """
    sql = "SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty > 0 AND part_type = ANY(:pt)"
    if active:
        sql += f" AND {field} IS NOT NULL AND {field} {'<=' if op == 'lte' else '>='} :v"
    return conn.execute(text(sql), {"pt": _slot_types(slot), "v": value}).scalar_one()


def _owner():
    me = current_operator() or {}
    if me.get("role") != "owner":
        raise HTTPException(403, "관리자만 바꿀 수 있습니다")
    return me


@router.get("/usage-floors")
def list_floors():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT floor_id, usage_key, usage_label, match_terms, slot, field, op,"
            " value, label, detail_fmt, active, sort_order, created_at"
            " FROM usage_floors ORDER BY sort_order, floor_id")).mappings().all()
        # 각 하한이 실제로 몇 개를 남기는지 — 화면이 숫자를 지어내지 않게 여기서 센다
        counts = {}
        for r in rows:
            n = _pass_count(conn, r["slot"], r["field"], r["op"], r["value"], r["active"])
            total = _pass_count(conn, r["slot"], r["field"], r["op"], r["value"], False)
            counts[r["floor_id"]] = {"pass": n, "total": total}

    groups: dict = {}
    for r in rows:
        g = groups.setdefault(r["usage_key"], {
            "usage_key": r["usage_key"], "usage_label": r["usage_label"],
            "match_terms": r["match_terms"] or [], "items": []})
        c = counts.get(r["floor_id"], {})
        g["items"].append({
            "floor_id": r["floor_id"], "slot": r["slot"],
            "slot_label": SLOT_KO.get(r["slot"], r["slot"]),
            "field": r["field"], "op": r["op"], "value": r["value"],
            "label": r["label"], "active": r["active"],
            "field_label": (FLOOR_FIELDS.get(r["field"]) or _DISPLAY_ONLY.get(r["field"], {})).get("label", r["field"]),
            "unit": (FLOOR_FIELDS.get(r["field"]) or _DISPLAY_ONLY.get(r["field"], {})).get("unit", ""),
            "pass_count": c.get("pass"), "slot_total": c.get("total"),
            "at": iso(r["created_at"]),
        })
    return {"groups": list(groups.values()), "fields": FLOOR_FIELDS,
            "note": ("이 값은 견적을 직접 바꿉니다 — 하한을 올리면 후보가 줄고,"
                     " 어떤 예산에서는 견적이 아예 나오지 않습니다."
                     " 각 줄의 '통과'는 지금 재고에서 실제로 세어 본 수입니다.")}


class FloorBody(BaseModel):
    value: int
    active: bool = True
    preview: bool = False


@router.post("/usage-floors/{floor_id}")
def update_floor(floor_id: int, body: FloorBody):
    """하한 값 변경 — preview로 영향을 먼저 보고 확인 후 적용한다."""
    from .admin_orders import _log

    me = _owner()
    if body.value < 0:
        raise HTTPException(400, "하한은 0 이상이어야 합니다")
    with engine.begin() as conn:
        r = conn.execute(text(
            "SELECT usage_key, usage_label, slot, field, op, value, label, active"
            " FROM usage_floors WHERE floor_id=:i FOR UPDATE"),
            {"i": floor_id}).mappings().first()
        if r is None:
            raise HTTPException(404, "그런 하한이 없습니다")
        # before = 지금 저장된 값·활성, after = 보낸 값·활성 — 둘 다 «이 줄» 기준(_pass_count).
        before = _pass_count(conn, r["slot"], r["field"], r["op"], r["value"], r["active"])
        after = _pass_count(conn, r["slot"], r["field"], r["op"], body.value, body.active)
        total = _pass_count(conn, r["slot"], r["field"], r["op"], body.value, False)

        impact = {
            "usage": r["usage_label"], "slot": SLOT_KO.get(r["slot"], r["slot"]),
            "field": r["field"], "from": r["value"], "to": body.value,
            "active_before": r["active"], "active_after": body.active,
            "pass_before": before, "pass_after": after, "slot_total": total,
            "buildable_after": after > 0,
        }
        impact["note"] = (
            f"{r['usage_label']} · {impact['slot']} 하한을 {r['value']} → {body.value}로"
            f" 바꾸면 후보가 {before}개 → {after}개가 됩니다(전체 {total}개)."
            + ("" if body.active else
               " 이 하한을 끄면 이 줄로는 거르지 않습니다 — 같은 용도의 다른 하한은 그대로 적용됩니다.")
            + ("" if after > 0 else
               " **후보가 0이 되어 이 용도로는 견적을 만들 수 없습니다.**"))
        if body.preview:
            return {"preview": True, "impact": impact}

        conn.execute(text(
            "UPDATE usage_floors SET value=:v, active=:a WHERE floor_id=:i"),
            {"v": body.value, "a": body.active, "i": floor_id})
        _log(conn, "usage_floor", r["usage_key"],
             {"floor_id": floor_id, "usage": r["usage_label"], "slot": r["slot"],
              "field": r["field"], "from": r["value"], "to": body.value,
              "active_from": r["active"], "active_to": body.active}, kind="engine")
    UF.reload()          # 캐시를 비워야 다음 견적부터 새 값이 쓰인다
    return {"ok": True, "impact": impact,
            "note": (f"하한을 {body.value}로 바꿨습니다."
                     " 다음 견적부터 적용됩니다 — 이미 만든 견적은 그대로입니다.")}
