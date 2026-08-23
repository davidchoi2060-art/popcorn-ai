"""카탈로그 적재 로직 — CLI와 업로드 API의 **단일 원천** (슬라이스 50).

이전에는 적재가 `tools/catalog_import.py` 하나뿐이었고 파일 경로가 하드코딩이었다.
업로드 화면을 열면서 같은 일을 두 번 구현하면 **스크립트와 화면이 다른 결과를 낸다** —
그 순간 "왜 이 상품이 안 올라왔지?"에 답할 수 없게 된다. 그래서 계획 수립(build_plan)과
반영(apply_plan)을 여기로 옮기고, CLI도 API도 이 함수만 부른다.

경계:
  · build_plan은 **DB를 건드리지 않는다** — 순수 계산이라 드라이런이 곧 미리보기다.
  · apply_plan은 한 트랜잭션이다 — 중간에 실패하면 통째로 없던 일이 된다.
  · 적재는 product_code 기준 upsert이고 **삭제가 없다**. 올린다고 기존 상품이 사라지지 않는다.
  · `locked_fields`로 잠근 값은 덮지 않는다(운영자가 손으로 고친 값 보호 — ERD §4.3).
    **2026-08-16까지는 매입가·판매가 둘만 지켰다** — 같은 UPSERT의 나머지 14개 컬럼은
    무조건 EXCLUDED였다(실사고: 0031이 올려놓은 완제품·베어본 분류를 08-15 적재가
    340건 되돌림, 검수 회부(123034)가 적재마다 지워짐). 지금은 part_type·category_group
    (분류) · ai_candidate_yn·review_required_yn(검수 게이트) · product_specs의
    SPEC_COLS 전부(사양) · **market_price(시장가, 2026-08-23 A-104)까지** 넓혔다 —
    근거·제외 이유(stock_qty·status는 의도적으로 제외)는 `UPSERT_PRODUCTS_SQL` 상수
    주석에 있다. 표기(잠금 문자열)는 두 갈래가 공존한다(`col` 맨 이름 / `specs.col`
    접두어) — `_spec_locked()`가 둘 다 인식한다. market_price는 사양이 아니라
    `purchase_price`·`sale_price`와 같은 **상품 컬럼** 갈래라 맨 이름(`market_price`)
    표기만 쓴다 — 승인 시 `locked_fields`에 실제로 추가하는 쪽은 `api/admin_reviews.py`의
    `_approve_product_field()`다(이 물결에서 함께 확장). 이 파일은 그 잠금을 UPSERT가
    존중하도록 CASE WHEN 가드만 추가한다 — 잠그는 동작 자체는 여기 없다.
  · 가격(purchase_price·sale_price)이 바뀌면 product_price_history에 reason='csv'로 남긴다
    (ERD §6 3원칙 3항 · §189 reason 열거값). 값이 같거나 잠긴 필드면 남기지 않고, 신규
    상품의 최초 가격은 비교할 이전 값이 없어 이력 대상이 아니다(등록 화면과 같은 규약).
    **이 규칙은 앞으로의 적재부터만 적용된다** — 이미 이력 없이 지금 값이 된 과거분은
    소급해 채우지 않는다(지어낸 이력은 원장을 통째로 못 믿게 만든다).
"""
import csv
import io
import json
import os
from collections import defaultdict

from sqlalchemy import text

from .catalog_map import extract_specs, map_part_type

REQUIRED = {
    "CPU": ["socket", "tdp_watt"],
    "MB": ["socket", "chipset", "form_factor", "mem_type"],
    "RAM": ["mem_type", "capacity_gb", "clock_mhz"],
    "GPU": ["length_mm", "required_power_watt", "pcie_gen"],
    "SSD": ["form_factor", "interface", "capacity_gb"],
    "HDD": ["form_factor", "interface", "capacity_gb"],
    "POWER": ["rated_watt", "form_factor"],
    "CASE": ["form_factor_list", "gpu_max_mm", "cooler_height_mm"],
    "COOLER_CPU_AIR": ["socket_list", "cooler_height_mm", "cooler_tdp"],
    "COOLER_CPU_AIO": ["socket_list", "cooler_tdp"],
    # 주변기기 없음 — 견적 슬롯 밖이고 제안 코드가 NULL을 견딘다(슬라이스 84).
    # 폴백 상수다. 정본은 spec_field_defs 메타 — _required_for()가 그것을 먼저 본다.
}
SPEC_COLS = ["socket", "socket_list", "chipset", "mem_type", "capacity_gb", "clock_mhz",
             "tdp_watt", "rated_watt", "required_power_watt", "length_mm", "gpu_max_mm",
             "cooler_height_mm", "cooler_tdp", "pcie_gen", "form_factor", "interface",
             "size_inch", "resolution", "refresh_hz", "panel",
             "radiator_rows", "radiator_max_rows"]
JSON_COLS = {"socket_list", "form_factor_list"}
# product_specs의 VARCHAR 길이(DB 실측) — 초과 값은 잘라 넣고 검수로 알린다
SPEC_MAXLEN = {"socket": 30, "chipset": 50, "mem_type": 10, "pcie_gen": 20,
               "form_factor": 50, "interface": 50, "resolution": 20, "panel": 20}
BATCH = 500

# 마스터 CSV가 반드시 가져야 하는 컬럼. 없으면 적재가 아니라 **거부**다 —
# 컬럼이 어긋난 파일을 받아 절반만 넣으면 나중에 무엇이 틀렸는지 알 수 없다.
MASTER_REQUIRED_COLS = ["자체상품코드", "상품명", "카테고리1", "카테고리2", "카테고리3",
                        "상태값", "매입가", "일반회원", "시중가", "공급처", "스펙",
                        "제조사", "모델명", "다나와No"]


def _int(v):
    s = (v or "").strip().replace(",", "")
    return int(s) if s.isdigit() else None


def read_master(raw: bytes) -> list[dict]:
    """마스터 CSV 바이트 → 행 목록. 컬럼이 모자라면 ValueError."""
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    if not rows:
        raise ValueError("빈 파일입니다")
    missing = [c for c in MASTER_REQUIRED_COLS if c not in rows[0]]
    if missing:
        raise ValueError("필수 컬럼이 없습니다: " + ", ".join(missing))
    return rows


def load_eav(products_raw: bytes | None, specs_raw: bytes | None):
    """사양 EAV(선택) — 없으면 빈 값. 그 경우 사양은 상품명·스펙 원문에서만 뽑힌다."""
    if not products_raw or not specs_raw:
        return {}, {}
    pid_to_code = {}
    for r in csv.DictReader(io.StringIO(products_raw.decode("utf-8-sig"), newline="")):
        pid_to_code[r.get("product_id")] = (r.get("custom_product_code") or "").strip()
    kvs, feats = defaultdict(dict), defaultdict(list)
    for r in csv.DictReader(io.StringIO(specs_raw.decode("utf-8-sig"), newline="")):
        code = pid_to_code.get(r.get("product_id"))
        if not code:
            continue
        k, v = (r.get("spec_key") or "").strip(), (r.get("spec_value") or "").strip()
        if k == "특성":
            feats[code].append(v)
        elif k:
            kvs[code].setdefault(k, v)
    return dict(kvs), dict(feats)


def _required_for(part_type: str) -> list:
    """필수 사양 — **메타(spec_field_defs)가 단일 원천**이다 (슬라이스 84).

    여기가 상수를 쓰는 바람에 판정 원천이 둘로 갈려 있었다:
      · 적재     상수 REQUIRED — 주변기기 항목이 아예 없다
      · 검수·수정 메타(admin_products.required_fields) — 주변기기 4~3종이 필수
    그래서 **같은 모니터가 어느 경로를 거쳤느냐로 결과가 달라졌다.** 적재로 들어오면
    검수 통과, 상세에서 값을 하나 고치면 그 순간 필수 미충족으로 판정돼 주변기기
    제안 풀에서 빠진다. 운영자에게는 "고쳤더니 사라졌다"로만 보인다.

    상수는 메타를 못 읽을 때의 폴백으로만 남긴다(admin_products와 같은 규약).
    """
    try:
        from . import spec_fields as SF
        got = SF.required_for(part_type)
        if got:
            return got
    except Exception:                                    # noqa: BLE001
        pass
    return REQUIRED.get(part_type, [])


def gate_fields() -> list:
    """필수 판정에 쓰이는 필드 전부. 기존 값을 함께 봐야
    "이 적재 후 이 상품의 사양이 완전한가"를 정직하게 판단할 수 있다."""
    try:
        from . import spec_fields as SF
        got = sorted({f for fs in SF.required_map().values() for f in fs})
        if got:
            return got
    except Exception:                                    # noqa: BLE001
        pass
    return sorted({f for fs in REQUIRED.values() for f in fs})


GATE_FIELDS = sorted({f for fs in REQUIRED.values() for f in fs})   # 폴백용 상수


def read_refs(conn) -> dict:
    """계획 수립에 필요한 현재 DB 상태(잠금·다나와 점유·GPU 참조표·기존 사양)."""
    gpu_ref = dict(conn.execute(text(
        "SELECT chipset_key, recommended_watt FROM gpu_power_reference")).all())
    # build_plan()이 이 값으로 잠긴 사양을 계획에서 뺀다(_locked_for) — 예전엔 여기서
    # 만들기만 하고 아무도 안 읽었다(2026-08-15까지의 실사고: 소비처가
    # tools/catalog_import.py의 화면 출력뿐이었다). product 컬럼 잠금(part_type 등)은
    # apply_plan의 UPSERT SQL이 이 딕셔너리가 아니라 DB의 products.locked_fields를
    # 직접(SQL 안에서) 다시 읽는다 — 여기서 만든 스냅샷은 사양 쪽에만 쓰인다.
    locked = {r[0]: (r[1] or []) for r in conn.execute(text(
        "SELECT product_code, locked_fields FROM products"
        " WHERE jsonb_array_length(locked_fields) > 0")).all()}
    # danawa_code는 UNIQUE다(단가표 자동 매칭이 이 값으로 상품 하나를 특정한다).
    dan_owner = {r[0]: r[1] for r in conn.execute(text(
        "SELECT danawa_code, product_code FROM products WHERE danawa_code IS NOT NULL")).all()}
    # 이미 확인된 사양. **이걸 모르면 EAV 없이 올린 파일이 기존 사양을 지운 것으로 계산되어
    # 멀쩡한 추천 후보를 검수로 떨어뜨린다** — 실제로 그런 일이 있었다(슬라이스 50).
    gf = gate_fields()          # 메타가 원천 — 화면에서 필수를 늘리면 여기도 따라온다
    existing = {r[0]: {k: v for k, v in zip(gf, r[1:]) if v is not None}
                for r in conn.execute(text(
                    f"SELECT product_code, {', '.join(gf)} FROM product_specs")).all()}
    return {"gpu_ref": gpu_ref, "locked": locked, "dan_owner": dan_owner,
            "existing": existing}


def _locked_for(refs: dict, code: int) -> set:
    """이 상품의 잠긴 필드 이름 집합. 표기가 두 갈래다 — 검수 승인(admin_reviews._approve)은
    `specs.<field>` 접두어를, 사양 PATCH(admin_products.patch_product_specs)는 맨
    필드명을 쓴다(DB 실측: 기존 559건 전부 접두어 · 3건 맨 이름). 정본을 하나로 통일하지
    않고(§보고 참조) 여기서 둘 다 인식한다 — `tools/respec.py:89`와 같은 이중 검사다."""
    return set((refs.get("locked") or {}).get(code) or [])


def _spec_locked(locked: set, col: str) -> bool:
    return col in locked or f"specs.{col}" in locked


def build_plan(rows: list[dict], kvs: dict, feats: dict, refs: dict, origin: str) -> dict:
    """행 목록 → 적재 계획. **DB를 바꾸지 않는다** — 이 결과가 곧 드라이런 리포트다."""
    gpu_ref, dan_owner = refs["gpu_ref"], refs["dan_owner"]
    existing = refs.get("existing") or {}

    # 실측: 다나와No가 채워진 행 중 중복이 있다(같은 제품을 색상·패키지별 코드로 관리).
    # UNIQUE 제약을 지키려면 **대표 1건만** 코드를 갖고 나머지는 비워 검수로 보낸다.
    dan_rep = {}
    for r in rows:
        d = (r["다나와No"] or "").strip()
        c0 = _int(r["자체상품코드"])
        if not d or c0 is None:
            continue
        sale0 = (r["상태값"] or "").strip() == "판매중"
        key = (0 if sale0 else 1, c0)          # 판매중 우선 → 코드 오름차순
        if d not in dan_rep or key < dan_rep[d][0]:
            dan_rep[d] = (key, c0)
    dan_rep = {d: v[1] for d, v in dan_rep.items()}

    prods, specs, reviews, errors = [], [], [], []
    skipped = defaultdict(int)
    for i, r in enumerate(rows, 1):
        code = _int(r["자체상품코드"])
        name = (r["상품명"] or "").strip()
        if code is None or not name:
            errors.append((i, r, "자체상품코드 또는 상품명 없음"))
            continue
        l1, l2, l3 = r["카테고리1"], r["카테고리2"], r["카테고리3"]
        # 스펙 원문을 함께 넘긴다 — 원천이 액세서리로 분류한 것을 부품으로 올리지 않는다
        pt, group, reason = map_part_type(l1, l2, l3, name, (r["스펙"] or "").strip())
        if reason:
            skipped[reason] += 1
            continue
        skey = (r["자체상품코드"] or "").strip()
        sale = (r["상태값"] or "").strip() == "판매중"
        sp, src = extract_specs(pt, kvs.get(skey, {}), feats.get(skey, []), name, l2, gpu_ref) \
            if pt else ({}, {})
        need = _required_for(pt)
        # 적재는 채우기만 하고 지우지 않는다(apply_plan의 COALESCE) — 따라서 '없는 사양'은
        # 새로 뽑은 값과 **이미 있는 값을 합쳐서** 판정해야 한다. 새 값만 보면 EAV를 안 올린
        # 파일이 멀쩡한 후보를 전부 검수로 떨어뜨린다(슬라이스 50 실측: 후보 -1 · 검수 +169).
        have = existing.get(code) or {}
        missing = [f for f in need if sp.get(f) is None and have.get(f) is None]
        dan = (r["다나와No"] or "").strip()[:40] or None
        dan_use = dan
        if dan:
            owner = dan_owner.get(dan)
            if dan_rep.get(dan) != code or (owner is not None and owner != code):
                dan_use = None          # 대표가 아니거나 다른 상품이 점유 중
                reviews.append({"pc": code, "field": "danawa_code",
                                "detail": f"다나와코드 {dan} 중복 — 대표 상품이 이미 점유"
                                          " (단가표 자동 매칭 대상에서 제외됨)"})
        # 게이트 ②: 필수 사양 전부 충족 ∧ core_part만 추천 후보로 승격
        ok = bool(need) and not missing and group == "core_part"
        prods.append({
            "pc": code, "sku": skey, "name": name[:200],
            "maker": (r["제조사"] or "").strip()[:60] or None,
            "model": (r["모델명"] or "").strip()[:120] or None,
            # part_type은 NOT NULL이다 — 미매핑은 'ETC'(미분류)로 넣는다.
            "pt": pt or "ETC", "grp": group or "etc",
            "status": "판매중" if sale else "품절",
            "ai": ok, "rev": (not ok) and group == "core_part",
            "pp": _int(r["매입가"]), "sp2": _int(r["일반회원"]), "mp": _int(r["시중가"]),
            "sup": (r["공급처"] or "").strip()[:80] or None,
            "dan": dan_use,
            # 재고 수량은 원천에 없다(사용자 결정 2026-07-26): 판매중=1, 품절=0.
            "stock": 1 if sale else 0,
            "spec_text": (r["스펙"] or "").strip()[:2000] or None,
            "origin": origin,
        })
        if pt:
            locked = _locked_for(refs, code)
            row = {"pc": code, "pt": pt, "sources": json.dumps(src, ensure_ascii=False)}
            for col in SPEC_COLS:
                if _spec_locked(locked, col):
                    # 잠긴 사양은 계획에 새 값을 올리지 않는다(2026-08-16 — 사장님 지시:
                    # 잠금을 사양까지 넓힌다). None으로 두면 apply_plan의
                    # COALESCE(EXCLUDED.col, product_specs.col)가 기존 값을 그대로
                    # 지킨다 — '적재는 채우기만 하고 지우지 않는다'는 이미 있던 장치를
                    # 그대로 재사용한다(SQL을 따로 고칠 필요가 없다). CSV 원문에 값이
                    # 있어 재추출되면 덮이던 위험 사례(예: socket=AM5 ↔ CSV
                    # "AMD(소켓AM5)")가 바로 이 분기로 막힌다.
                    row[col] = None
                    continue
                v = sp.get(col)
                if col in JSON_COLS and v is not None:
                    v = json.dumps(v)
                elif isinstance(v, str) and col in SPEC_MAXLEN:
                    # 잘라 넣되 잘렸다는 사실을 검수로 알린다 — 조용히 버리지 않는다.
                    if len(v) > SPEC_MAXLEN[col]:
                        reviews.append({"pc": code, "field": col,
                                        "detail": f"'{col}' 원천 값이 컬럼 한계"
                                                  f"({SPEC_MAXLEN[col]}자)를 넘어 잘림"
                                                  f" — 원문: {v[:60]}"})
                        v = v[:SPEC_MAXLEN[col]]
                row[col] = v
            specs.append(row)
        for f in missing:
            reviews.append({"pc": code, "field": f,
                            "detail": f"{pt} 필수 사양 '{f}' 미확인 — 적재 원천에서 추출 실패"})

    return {"prods": prods, "specs": specs, "reviews": reviews, "errors": errors,
            "skipped": dict(skipped), "row_total": len(rows)}


def plan_impact(conn, plan: dict) -> dict:
    """이 적재가 **무엇을 바꾸는가** — 신규/갱신, 추천 후보 진입/이탈.

    건수만 보여주면 "몇 건 들어간다"만 알고 "무엇이 무너지는가"는 모른다.
    슬라이스 50에서 EAV 없이 올린 파일이 후보를 떨어뜨렸는데 리포트에는 안 보였다.
    """
    codes = [p["pc"] for p in plan["prods"]]
    if not codes:
        return {"new": 0, "update": 0, "pool_in": 0, "pool_out": 0,
                "review_new": 0, "review_planned": 0, "market_price_locked_preserved": 0}
    known = {r[0] for r in conn.execute(
        text("SELECT product_code FROM products WHERE product_code = ANY(:c)"),
        {"c": codes}).all()}
    # 지금 후보에 있는 상품 중 이번 적재 대상
    pool_now = {r[0] for r in conn.execute(
        text("SELECT product_code FROM v_recommendation_candidates"
             " WHERE stock_qty > 0 AND product_code = ANY(:c)"), {"c": codes}).all()}
    # 적재 후 후보가 될 상품 = 게이트 ②(ai) ∧ 재고>0 ∧ core_part
    will = {p["pc"] for p in plan["prods"]
            if p["ai"] and p["stock"] > 0 and p["grp"] == "core_part"}
    # 검수 회부는 (상품, 필드)로 중복을 막으므로 계획 수(len(reviews))가 곧 증가분이 아니다.
    # "198건 회부"라고 말했는데 실제 증가가 0이면 화면이 헛수를 말한 것이다(슬라이스 50).
    pending = {(r[0], r[1]) for r in conn.execute(text(
        "SELECT product_code, field_name FROM product_reviews"
        " WHERE review_status = '대기' AND product_code = ANY(:c)"), {"c": codes}).all()}
    review_new = len({(r["pc"], r["field"]) for r in plan["reviews"]} - pending)
    # market_price 잠금 보존 (A-104 · 2026-08-23) — 승인값이 이번 적재에서 몇 건
    # 지켜지는지를 드라이런이 직접 말한다. "잠갔다"만으로는 무엇이 지켜지는지 모른다
    # (§화면 정직성과 같은 이유 — 건수만이 아니라 «무엇이 보호됐는가»).
    market_price_locked_preserved = conn.execute(text(
        "SELECT count(*) FROM products"
        " WHERE product_code = ANY(:c) AND locked_fields ? 'market_price'"),
        {"c": codes}).scalar_one()
    return {
        "new": sum(1 for c in codes if c not in known),
        "update": sum(1 for c in codes if c in known),
        "pool_in": len(will - pool_now),
        "pool_out": len(pool_now - will),
        "review_new": review_new,
        "review_planned": len(plan["reviews"]),
        "market_price_locked_preserved": market_price_locked_preserved,
    }


def plan_summary(plan: dict) -> dict:
    """드라이런 리포트 — 화면이 그대로 쓰는 수치. 추정이 아니라 계획의 실측이다."""
    prods = plan["prods"]
    by_type: dict[str, dict] = {}
    for p in prods:
        b = by_type.setdefault(p["pt"], {"n": 0, "promote": 0})
        b["n"] += 1
        if p["ai"]:
            b["promote"] += 1
    return {
        "row_total": plan["row_total"],
        "ok": len(prods),
        "spec_rows": len(plan["specs"]),
        "review": len(plan["reviews"]),
        "error": len(plan["errors"]),
        "promote": sum(1 for p in prods if p["ai"]),
        "skipped": plan["skipped"],
        "skipped_total": sum(plan["skipped"].values()),
        "by_type": sorted(
            ({"part_type": k, **v} for k, v in by_type.items()),
            key=lambda x: -x["n"]),
        "error_samples": [{"row_no": n, "reason": why} for n, _, why in plan["errors"][:20]],
    }


# ── 상품 UPSERT (CLI·API 공통) ────────────────────────────────────────────────
# 모듈 상수로 뺀다(2026-08-16) — 회귀가 이 SQL 문자열을 직접 import해 ①EXPLAIN으로
# 문법을 파싱하고 ②어떤 컬럼이 잠금 가드를 갖는지 정적으로 검사할 수 있어야 한다.
# apply_plan() 안 지역 변수로 있으면 함수를 실행(=DB에 쓰기)하지 않고는 손댈 수 없다
# — '회귀는 정본을 쓰지 않는다'(슬라이스 50)를 지키면서 SQL 자체를 검증하는 유일한 길.
#
# **잠금 범위(2026-08-16 — 사장님 지시: "잠금을 사양·분류·검수 플래그까지 전부 넓혀라".
#             2026-08-23 A-104가 market_price를 추가 — 시장가 제안 승인의 짝)**
#   잠금 적용    purchase_price · sale_price(기존) + part_type · category_group(분류)
#               + ai_candidate_yn · review_required_yn(검수 게이트) + market_price
#               (2026-08-23 — 다나와 제안을 사람이 승인한 값을 다음 CSV 적재가
#               되돌리면 그 승인이 무의미해진다. A-16 "적재는 채우기만 하고 지우지
#               않는다"의 가격판)
#   잠금 제외    stock_qty · status — **의도적 판단**이다. 이 둘은 몰의 실시간 재고·
#               판매상태를 옮겨 적은 값이라(CSV `상태값`이 그대로 stock_qty=1/0을
#               결정한다 — build_plan 참조) 영구히 얼리면 몰이 품절로 바꿔도 우리는
#               계속 판매중이라 말해 없는 물건을 팔거나, 반대로 재입고를 계속
#               감춘다. 가격·분류·검수 플래그는 "우리가 소싱/판정해 안다"는 값이라
#               잠그는 것이 맞지만, 재고·판매상태는 "몰이 지금 뭐라고 하는가"이지
#               우리가 확정할 사실이 아니다 — CLAUDE.md "가격 원천은 몰. 소싱한
#               경우만 우리가 덮어쓰고 잠근다"와 같은 구분선. 이 UPSERT의 갱신 컬럼은
#               16개(product_code·sku 제외) — 잠금 인식 7개(2026-08-23까지 6개 +
#               market_price) + stock_qty·status(의도적 제외) + 나머지 7개
#               (product_name·maker·model_name·supplier·danawa_code·
#               spec_source_text·data_origin)는 이번 지시(사양·분류·검수·시장가)의
#               대상이 아니라 손대지 않았다 — patch_product가 이미 이 중 일부
#               (product_name·maker·stock_qty·status)를 잠글 수 있는데 이 UPSERT가
#               그 잠금을 못 보는 것은 **이번에 고치지 않은 기존 결함**이다(보고 참조).
UPSERT_PRODUCTS_SQL = """
    INSERT INTO products (product_code, sku, product_name, maker, model_name, part_type,
      category_group, status, ai_candidate_yn, review_required_yn, purchase_price,
      sale_price, market_price, supplier, danawa_code, stock_qty, spec_source_text,
      data_origin)
    VALUES (:pc, :sku, :name, :maker, :model, :pt, :grp, :status, :ai, :rev, :pp, :sp2,
      :mp, :sup, :dan, :stock, :spec_text, :origin)
    ON CONFLICT (product_code) DO UPDATE SET
      product_name = EXCLUDED.product_name, maker = EXCLUDED.maker,
      model_name = EXCLUDED.model_name, status = EXCLUDED.status,
      -- locked_fields는 JSONB 배열이다 — 요소 존재는 `?` 연산자로 본다.
      -- 운영자가 손으로 고친 값을 적재가 덮으면 검수 노동이 무효가 된다(ERD §4.3).
      -- 잠기지 않았어도 COALESCE로 기존 값을 지킨다 — 원천 CSV가 이 행에 매입가·판매가를
      -- 안 실었을 뿐인데(_int()가 None) 그걸 그대로 넣으면 멀쩡한 가격이 NULL로 지워진다.
      -- '적재는 채우기만 하고 지우지 않는다'는 아래 product_specs와 이미 같은 원칙이었는데
      -- 가격 두 컬럼만 빠져 있었다. market_price·다른 컬럼은 이번 범위가 아니다(가격 둘만).
      purchase_price = CASE WHEN products.locked_fields ? 'purchase_price'
                            THEN products.purchase_price
                            ELSE COALESCE(EXCLUDED.purchase_price, products.purchase_price) END,
      sale_price = CASE WHEN products.locked_fields ? 'sale_price'
                        THEN products.sale_price
                        ELSE COALESCE(EXCLUDED.sale_price, products.sale_price) END,
      -- 분류·검수 게이트도 같은 이유로 잠근다. 실사고 둘: ① 0031이 완제품·베어본을
      -- ETC에서 올려놓은 뒤 08-15 몰 적재가 340건을 다시 ETC로 되돌렸다 ② 123034는
      -- 검수로 회부된 채(review_id=8193, 대기)인데 적재가 review_required_yn을
      -- 재계산해 후보로 되돌렸다. 이 넷을 잠그는 쪽은 admin_products.change_part_type
      -- 이다 — 여기서 그 잠금을 존중하지 않으면 다음 재적재가 그대로 되돌린다.
      part_type = CASE WHEN products.locked_fields ? 'part_type'
                       THEN products.part_type
                       ELSE COALESCE(EXCLUDED.part_type, products.part_type) END,
      category_group = CASE WHEN products.locked_fields ? 'category_group'
                            THEN products.category_group
                            ELSE COALESCE(EXCLUDED.category_group, products.category_group) END,
      ai_candidate_yn = CASE WHEN products.locked_fields ? 'ai_candidate_yn'
                             THEN products.ai_candidate_yn
                             ELSE COALESCE(EXCLUDED.ai_candidate_yn, products.ai_candidate_yn) END,
      review_required_yn = CASE WHEN products.locked_fields ? 'review_required_yn'
                                THEN products.review_required_yn
                                ELSE COALESCE(EXCLUDED.review_required_yn,
                                              products.review_required_yn) END,
      -- stock_qty·status는 위 모듈 주석대로 의도적으로 잠금 대상 밖이다.
      -- market_price도 이제 잠금을 본다 (A-104 · 2026-08-23 사장님 확정 — 시장가 제안
      -- 승인 안 §1-3 실측: CSV '시중가'가 admin_reviews._approve_product_field()가
      -- 넣은 승인값을 무조건 덮어써 «승인값이 살아남을 수 없었다». 매입가·판매가와
      -- 정확히 같은 표현(CASE WHEN ... ELSE EXCLUDED... END) — 사장님이 명시적으로
      -- COALESCE 대안은 택하지 않았다(decision-log A-104 "①을 택했다(②COALESCE·
      -- ③컬럼 재정의는 택하지 않음)") — 그래서 잠기지 않은 상품은 이전과 똑같이
      -- CSV 값이 없어도(EXCLUDED.market_price가 NULL이어도) 그대로 NULL로 덮인다,
      -- 이 부분은 이번 결정으로 안 바뀐다.
      market_price = CASE WHEN products.locked_fields ? 'market_price'
                          THEN products.market_price
                          ELSE EXCLUDED.market_price END,
      supplier = EXCLUDED.supplier,
      danawa_code = EXCLUDED.danawa_code, stock_qty = EXCLUDED.stock_qty,
      spec_source_text = EXCLUDED.spec_source_text, data_origin = EXCLUDED.data_origin,
      updated_at = now()
"""
# 잠금 가드가 있어야 하는 컬럼 — 회귀[44]가 이 목록과 SQL 본문을 대조한다(정적 검사).
LOCK_AWARE_PRODUCT_COLS = ("purchase_price", "sale_price", "part_type", "category_group",
                           "ai_candidate_yn", "review_required_yn", "market_price")

# ── 사양 UPSERT ────────────────────────────────────────────────────────────
# 잠긴 사양은 이 SQL이 몰라도 된다 — build_plan()이 잠긴 필드를 이미 None으로 비워
# 보낸다(두 표기 다 인식, 위 _spec_locked 참조). COALESCE(EXCLUDED.col, 기존)는
# EXCLUDED.col이 NULL이면 항상 기존 값을 지키므로, '적재는 채우기만 하고 지우지
# 않는다'는 기존 장치 그대로 잠금까지 함께 지켜진다 — SQL을 따로 고칠 필요가 없었다.
_SPEC_SET_COLS = ", ".join(f"{c} = COALESCE(EXCLUDED.{c}, product_specs.{c})" for c in SPEC_COLS)
UPSERT_SPECS_SQL = f"""
    INSERT INTO product_specs (product_code, part_type, {', '.join(SPEC_COLS)},
      spec_sources, extract_source, confidence)
    VALUES (:pc, :pt, {', '.join(':' + c for c in SPEC_COLS)},
      CAST(:sources AS JSONB), 'csv', 0.8)
    ON CONFLICT (product_code) DO UPDATE SET
      part_type = EXCLUDED.part_type, {_SPEC_SET_COLS},
      -- 출처도 덮지 않고 합친다(새 출처가 우선) — 어디서 온 값인지 잃지 않는다
      spec_sources = COALESCE(product_specs.spec_sources, '{{}}'::jsonb)
                     || COALESCE(EXCLUDED.spec_sources, '{{}}'::jsonb),
      extract_source = 'csv', updated_at = now()
"""


def apply_plan(conn, plan: dict, file_name: str, origin: str, operator_id: int) -> int:
    """계획을 한 트랜잭션으로 반영하고 배치 번호를 돌려준다. 호출자가 트랜잭션을 연다."""
    prods, specs, reviews, errors = (plan["prods"], plan["specs"],
                                     plan["reviews"], plan["errors"])
    job_id = conn.execute(text(
        "INSERT INTO csv_import_jobs (file_name, row_total, row_ok, row_error, row_review,"
        " status, data_origin, source, created_by)"
        " VALUES (:f, :t, :ok, :er, :rv, '완료', :o, 'catalog_csv', :by) RETURNING job_id"),
        {"f": file_name[:200], "t": plan["row_total"], "ok": len(prods),
         "er": len(errors), "rv": len(reviews), "o": origin, "by": operator_id}).scalar()

    ins_p = text(UPSERT_PRODUCTS_SQL)
    # ── 재고 델타·가격 변경 전 값을 함께 읽는다 (슬라이스 98 + 가격 이력 결손 보완) ──
    # 적재는 `stock_qty = EXCLUDED.stock_qty`로 **덮어쓴다**. 그런데 원장에는 아무것도
    # 남지 않아, 재고>0인데 원장이 없는 상품이 7,547건 쌓여 있었다. `stock_movements`
    # 합으로 재고를 검증할 수 없다는 뜻이고, "이 재고가 어디서 왔나"에 답할 수 없다.
    #
    # 절대값이 아니라 **델타**를 남긴다 — 재적재가 8을 5로 바꾸면 -3이다.
    # 종류: 처음 우리 재고로 기록되면(0 -> N) `inbound`, 이후 원천과 맞추는 것은 `adjust`.
    #       적재가 물리적 입고를 목격한 것은 아니므로 후자를 입고라고 부르지 않는다.
    #
    # 매입가·판매가·잠금도 같은 조회에 담는다 — UPSERT는 "바뀌기 전 값"을 알려주지 않으므로
    # 아래 가격 이력도 이 스냅샷 없이는 old_price를 채울 수 없다(재고 델타와 같은 문제).
    #
    # 왕복(조회)은 하나로 합치되 **쓰는 쪽은 가른다** — `stock_before`는 재고 델타 전용으로
    # 이름·모양을 그대로 유지한다(회귀 [26]이 이 파일에 이 리터럴이 있는지로 "적재가 절대값이
    # 아니라 델타를 남긴다"를 판정한다 — 슬라이스 98). 가격 이력은 별도 `price_before`를 쓴다.
    pcs = [p["pc"] for p in prods]
    stock_before, price_before = {}, {}
    if pcs:
        rows = conn.execute(text(
            "SELECT product_code, stock_qty, purchase_price, sale_price, locked_fields"
            " FROM products WHERE product_code = ANY(:c)"),
            {"c": pcs}).all()
        stock_before = {r[0]: (r[1] or 0) for r in rows}
        price_before = {r[0]: {"purchase_price": r[2], "sale_price": r[3],
                               "locked": set(r[4] or [])} for r in rows}

    for i in range(0, len(prods), BATCH):
        conn.execute(ins_p, prods[i:i + BATCH])

    moves = []
    for p in prods:
        b = stock_before.get(p["pc"], 0)
        a = int(p["stock"] or 0)
        if a == b:
            continue
        moves.append({"pc": p["pc"], "q": a - b, "ref": job_id,
                      "t": "inbound" if b == 0 and a > 0 else "adjust"})
    if moves:
        ins_mv = text(
            "INSERT INTO stock_movements"
            " (product_code, movement_type, qty_delta, ref_kind, ref_id)"
            " VALUES (:pc, :t, :q, 'catalog', :ref)")
        for i in range(0, len(moves), BATCH):
            conn.execute(ins_mv, moves[i:i + BATCH])

    # ── 가격 변경을 이력에 남긴다 (ERD §6 3원칙 3항 · reason='csv') ─────────────────
    # 지금까지 적재는 가격을 바꾸면서도 product_price_history에 아무것도 남기지 않았다
    # (실측: reason='csv' 0건 — ERD가 요구한 값인데 코드에 그 문자열 자체가 없었다).
    # **앞으로의 적재부터만** 남긴다 — 이미 이력 없이 지금 값이 된 상품(sale 15,594건·
    # purchase 18,744건, 실측)은 언제 그 값이 됐는지 모르므로 소급해 채우지 않는다
    # (지어낸 이력은 원장 전체를 못 믿게 만든다 — CLAUDE.md 원장 규약과 같은 이유).
    #
    # · 신규 상품(이번에 처음 INSERT됨)은 대상에서 제외한다 — 비교할 '이전 값'이 없다.
    #   상품 등록(admin_products.register_product)도 최초 매입가를 이력에 남기지 않는
    #   같은 규약이다(등록 시점엔 old_price가 존재한 적이 없다).
    # · 잠긴 필드는 건너뛴다 — 위 UPSERT의 CASE가 실제로 값을 안 바꾸므로 남길 변경이 없다.
    # · 값이 같으면(원천에 값이 없어 COALESCE로 기존 값을 지킨 경우 포함) 행을 남기지
    #   않는다(선례: admin_price_import.py:166,183 `if new_purchase != ...` ·
    #   admin_products.py:572 `if before[k]==v: continue`) — 안 지키면 적재 1회에 최대
    #   22,840행이 두 필드분 쌓여, 지금 28,994행인 원장이 한 번에 두 배 가까이 된다.
    # · market_price는 이 이력 대상에 없다(가격 이력은 여전히 매입가·판매가 둘만) —
    #   승인값이 CSV 재적재에 덮이는 문제는 이력이 아니라 **잠금**(위 UPSERT_PRODUCTS_SQL의
    #   market_price CASE WHEN, A-104)으로 막는다. 잠긴 market_price는 이제 이 UPSERT가
    #   손대지 않으므로(=값이 안 바뀌므로) 애초에 남길 변경이 없다. 잠기지 않은
    #   market_price는 예전처럼 이력 없이 계속 덮인다 — 이번 결정은 그걸 바꾸지 않았다.
    price_moves = []
    for p in prods:
        b = price_before.get(p["pc"])
        if b is None:
            continue                        # 신규 상품 — 최초 가격은 이력 대상이 아니다
        for col, field, key in (("purchase_price", "purchase", "pp"),
                                 ("sale_price", "sale", "sp2")):
            if col in b["locked"]:
                continue                    # 잠긴 값 — 실제로 바뀌지 않는다
            old = b[col]
            raw_new = p[key]
            new = raw_new if raw_new is not None else old   # 위 COALESCE와 동일 규칙
            if new == old:
                continue                    # 값이 안 바뀌면 남기지 않는다
            price_moves.append({"pc": p["pc"], "field": field, "old": old, "new": new,
                                "ref": job_id, "op": operator_id})
    if price_moves:
        ins_ph = text(
            "INSERT INTO product_price_history"
            " (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
            " VALUES (:pc, :field, :old, :new, 'csv', :ref, :op)")
        for i in range(0, len(price_moves), BATCH):
            conn.execute(ins_ph, price_moves[i:i + BATCH])

    # **적재는 채우기만 하고 지우지 않는다.** 새 파일에서 못 뽑은 필드가 기존 값을 NULL로
    # 덮으면, EAV를 빼고 마스터만 올린 한 번의 적재가 추천 후보를 통째로 무너뜨린다
    # (슬라이스 50에서 실제로 겪었다). 잘못된 사양을 비우는 일은 검수 화면 소관이다.
    # 잠긴 사양도 같은 장치로 지켜진다 — build_plan()이 이미 None으로 비워 보냈다
    # (모듈 상수 UPSERT_SPECS_SQL 주석 참조).
    ins_s = text(UPSERT_SPECS_SQL)
    for i in range(0, len(specs), BATCH):
        conn.execute(ins_s, specs[i:i + BATCH])

    # 검수 큐 — 같은 상품·같은 필드의 대기 행이 있으면 만들지 않는다(재실행 안전)
    ins_r = text("""
        INSERT INTO product_reviews (product_code, review_type, field_name, detail,
          review_status, confidence)
        SELECT :pc, 'spec_missing', :field, :detail, '대기', 0.8
         WHERE NOT EXISTS (SELECT 1 FROM product_reviews x
                            WHERE x.product_code = :pc AND x.field_name = :field
                              AND x.review_status = '대기')
    """)
    for i in range(0, len(reviews), BATCH):
        conn.execute(ins_r, reviews[i:i + BATCH])

    for row_no, raw, why in errors[:200]:
        conn.execute(text(
            "INSERT INTO csv_import_errors (job_id, row_no, raw_row, reason)"
            " VALUES (:j, :n, CAST(:r AS JSONB), :why)"),
            {"j": job_id, "n": row_no, "r": json.dumps(raw, ensure_ascii=False), "why": why})
    return job_id


def read_file(path: str) -> bytes:
    with io.open(path, "rb") as f:
        return f.read()


def basename(path: str) -> str:
    return os.path.basename(path)
