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
  · **2026-08-24 — supplier(공급처)를 추가로 넓혔다.** 이건 market_price와 다른 종류의
    구멍이었다: market_price는 "잠갔는데도 덮인다"였지만 supplier는 **잠금과 무관하게
    CSV 그 행의 공급처 칸이 비어 있기만 해도** 무조건 `EXCLUDED.supplier`가 들어가
    기존 값을 NULL로 지웠다(실측: 공급처 칸이 비어 있던 4,153건 중 4,113건=99.0%가
    NULL이 됨 · 값이 있던 18,618건은 14건=0.08%만 영향 — 그 14건은 이번 원인과 다를
    가능성이 높고 이번 조사·수정 대상이 아니다). `purchase_price`·`sale_price`가 이미
    갖고 있던 `COALESCE(EXCLUDED.col, products.col)`과 `locked_fields ? 'col'` 가드를
    **한 CASE WHEN 표현에 합쳐서** 그대로 옮겼다 — "CSV가 비었을 때"와 "운영자가
    잠갔을 때" 둘 다 이 한 줄로 지켜진다. 이미 NULL이 된 4,113건은 이 수정의 대상이
    아니다(복구는 별도 작업, 원천 조사 중 — 여기서는 앞으로의 적재만 막는다). 나머지
    6개(product_name·maker·model_name·danawa_code·spec_source_text·data_origin)도
    같은 병(CSV 빈 칸이 그대로 NULL로 들어가 기존 값을 지움)을 앓고 있을 수 있으나
    실측하지 않았다 — 이번 지시는 supplier 하나였다.
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
            # product_imports 원본 냉동 보관용(2026-08-24 — 사장님 지시, 아래 apply_plan의
            # product_imports INSERT 주석 참조). 원본 그대로 얕은 복사 — 이 시점 이후
            # 코드가 r을 다시 안 건드리므로 사본 없이 그대로 써도 안전하지만, "이 필드는
            # UPSERT 파라미터가 아니라 원본 보존용"이라는 사실을 명확히 하려고 별도 키로
            # 분리했다(UPSERT_PRODUCTS_SQL은 이 키를 모른다 — 알려진 :파라미터 이름에
            # 없는 키는 SQLAlchemy가 그냥 무시한다).
            "raw": dict(r),
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
#             2026-08-23 A-104가 market_price를 추가 — 시장가 제안 승인의 짝.
#             2026-08-24 supplier를 추가(아래 supplier 전용 문단). 같은 날 후속으로
#             나머지 여섯 중 다섯을 추가 — 아래 "여섯 컬럼 확장" 문단)**
#   잠금 적용    purchase_price · sale_price(기존) + part_type · category_group(분류)
#               + ai_candidate_yn · review_required_yn(검수 게이트) + market_price
#               (2026-08-23 — 다나와 제안을 사람이 승인한 값을 다음 CSV 적재가
#               되돌리면 그 승인이 무의미해진다. A-16 "적재는 채우기만 하고 지우지
#               않는다"의 가격판) + supplier + product_name·maker·model_name·
#               danawa_code·spec_source_text(전부 2026-08-24 — 아래 참조. product_name은
#               잠금만 적용 — COALESCE는 NOT NULL 컬럼이라 못 넣었다, 아래 참조)
#   잠금 제외    stock_qty · status · **data_origin** — 셋 다 무조건 EXCLUDED다.
#               stock_qty·status는 기존 이유(몰의 실시간 값을 옮겨 적은 것이라
#               영구히 얼리면 안 된다) 그대로다. data_origin은 2026-08-24 검토
#               대상이었지만 **잠금·COALESCE 둘 다 일부러 안 넣기로 판단**했다
#               (근거는 아래 "여섯 컬럼 확장" 문단 — 게이트 오분류 위험 + NOT NULL이라
#               COALESCE가 무의미) — 그래서 이 컬럼만 이번 확장 전후로 SQL이 문자
#               그대로 같다. 가격·분류·검수 플래그는 "우리가 소싱/판정해 안다"는
#               값이라 잠그는 것이 맞지만, 재고·판매상태·데이터출처는 "몰이 지금
#               뭐라고 하는가" 또는 "이 배치가 진짜인가"를 매번 다시 확인해야 하는
#               값이라 영구히 얼리는 것과 안 맞는다 — CLAUDE.md "가격 원천은 몰.
#               소싱한 경우만 우리가 덮어쓰고 잠근다"와 같은 구분선. 이 UPSERT의
#               갱신 컬럼은 16개(product_code·sku 제외) — **잠금 인식 13개**
#               (purchase_price·sale_price·part_type·category_group·
#               ai_candidate_yn·review_required_yn·market_price·supplier·
#               product_name·maker·model_name·danawa_code·spec_source_text,
#               이 중 product_name·market_price 둘만 COALESCE 없이 잠금만) +
#               **무조건 EXCLUDED 3개**(stock_qty·status·data_origin) = 16.
#               patch_product의 EDITABLE(admin_products.py:333-343)은 이 중
#               product_name(키 "name")·maker·supplier(및 stock_qty·status)만 잠글 수
#               있다(실측) — model_name·danawa_code·spec_source_text·data_origin은
#               지금은 patch_product로도 검수 승인으로도 못 고치는 값이라 «잠글 방법
#               자체가 없다». product_name·maker를 이 UPSERT가 못 보던 것은 **기존
#               결함**이었는데(supplier 확장 시점까지 미해소 상태로 보고됨) 이번에
#               막았다.
#
# **supplier(공급처) 전용 — 왜 뒤늦게 보호되는가, A-104에서 왜 빠졌는가 (2026-08-24)**
#   A-104(2026-08-23)는 market_price 하나만 다뤘다 — 그때 이 파일 docstring이 "나머지
#   14개 컬럼"에 supplier를 포함해 "이번 지시 대상이 아니라 손대지 않았다"고 명시적으로
#   적어 두었다(위 모듈 docstring 참조). 그 "미룬 일"이 실제 사고였다: supplier는
#   `purchase_price`처럼 CASE WHEN 가드도 COALESCE도 없이 맨몸으로 `EXCLUDED.supplier`
#   였다. CSV의 그 행이 공급처 칸을 못 채우면(원천이 이 칸을 비우는 이유는 조사 대상
#   밖이다) `build_plan()`이 만드는 `sup` 값이 애초에 None이고(아래 참고), 그 None이
#   `EXCLUDED.supplier`를 통해 그대로 들어가 products.supplier를 지웠다. 조사자 실측
#   (이번 지시서 원문 표): CSV 공급처 칸이 **비어 있던** 4,153건 중 **4,113건(99.0%)**의
#   products.supplier가 지금 NULL이고, 칸에 **값이 있던** 18,618건 중에는 **14건
#   (0.08%)**만 NULL이다 — 전자는 사실상 전부 이 경로로 지워졌다는 뜻이고 후자 14건은
#   다른 원인일 가능성이 높아 이번 조사·수정 대상이 아니다(products.supplier 전체
#   NULL 건수와의 합산 대조는 이번 지시 범위 밖 — 새로 계산해 지어내지 않는다).
#   build_plan()의 "sup" 필드 파생(:260행, `(r["공급처"] or "").strip()[:80] or None`)을
#   직접 실행해 확인했다 — 빈 문자열(csv.DictReader가 칸이 있고 비어 있을 때 주는 값)·
#   None(행이 헤더보다 짧을 때 restval로 주는 값)·공백만 있는 문자열 셋 다 None으로
#   접히고, 값이 있으면 그대로 통과한다. 즉 `purchase_price`·`sale_price`가 `_int()`로
#   빈 값을 None으로 접는 것과 **정확히 같은 모양**이라, 그 둘과 같은
#   `COALESCE(EXCLUDED.col, products.col)` 하나로 "CSV가 비웠다"와 "운영자가 잠갔다"
#   둘 다 지켜진다(market_price처럼 plain EXCLUDED만 쓰지 않는 이유이기도 하다 —
#   market_price는 A-104에서 COALESCE 대안을 명시적으로 안 쓰기로 했지만 supplier는
#   그 결정 대상이 아니었으므로 이 규칙에 매이지 않는다). 이미 NULL이 된 4,113건은
#   복구하지 않는다 — 원천을 찾는 별도 작업이고, 이 수정은 앞으로의 적재만 막는다.
#
# **여섯 컬럼 확장 — product_name·maker·model_name·danawa_code·spec_source_text·
#   data_origin (2026-08-24, 사장님 지시 — "나머지 여섯도 같이 보호하라. supplier에
#   한 것과 같은 일이다")**
#   빈 값 보호(①)는 **넷(maker·model_name·spec_source_text·danawa_code)에 COALESCE로
#   넣었다.** 넣기 전에 build_plan()이 각 컬럼의 빈 값을 무엇으로 접는지 직접 실행해
#   확인했다(코드로, 추측 아님) — 결과: 넷 다 SQL에 닿기 전에 이미 None으로 접혀 있어
#   `NULLIF` 같은 추가 장치가 필요 없었다.
#     · maker·model_name·spec_source_text·danawa_code — supplier와 똑같은
#       `(r["..."] or "").strip()[:N] or None` 모양(252-264행 부근). 빈 문자열·
#       None·공백만 있는 문자열 셋 다 None.
#     · danawa_code는 한 가지 더 있다 — `dan_use`가 None이 되는 경우가 «CSV가
#       비었다» 말고 하나 더 있다: 같은 배치 안에 다나와No가 중복이면 대표 1건만
#       코드를 받고(dan_rep), DB에서 이미 다른 상품이 그 코드를 쥐고 있으면(dan_owner)
#       도 None이 된다(240-248행). 이 COALESCE는 그 경우도 "이 상품에 새 값을 못
#       준다"로 똑같이 취급해 기존 값을 지킨다 — 대표를 재조정하거나 소유권을
#       바꾸는 로직은 아니고(그건 이번 지시 밖), «못 줄 땐 지우지 않는다»만 지킨다.
#   **product_name·data_origin 둘은 COALESCE를 넣지 «않았다» — 시도했다가 뺐다.**
#   실측(임시 테이블로 직접 재현): PostgreSQL은 `ON CONFLICT DO UPDATE`에서도 NOT NULL을
#   **COALESCE가 평가되기 전, VALUES 단계**에서 검사한다 — `SET v=COALESCE(EXCLUDED.v,
#   t.v)`를 걸어도 `:v`가 NULL이면 그 즉시 NotNullViolation으로 죽는다(충돌 여부와
#   무관). 이 둘은 실측상 NOT NULL 컬럼이다(information_schema.columns.is_nullable=
#   'NO'). 그래서 COALESCE를 적어도 :name·:origin이 NULL이면 문장 전체가 죽지, 기존
#   값을 지켜주지 않는다 — **COALESCE가 "빈 값이면 지킨다"는 보호를 실제로 수행하는
#   게 아니라, 아무것도 안 하고 죽는 것과 결과가 같다.** 적으나 안 적으나 같다면
#   안 적는 쪽이 정직하다(있으나 마나 한 코드는 "여기 방어막이 있다"는 착시만 남긴다).
#   그래서 이 둘의 실제 보호는 **호출부 쪽**에 있다 — product_name은 build_plan()이
#   상품명 빈 행을 통째로 errors로 보내 그 상품코드가 이 배치에서 아예 UPSERT되지
#   않는다(220-223행, `if code is None or not name: errors.append(...); continue`).
#   data_origin은 아래 참조. 상세 근거·재현 방법은 UPSERT_PRODUCTS_SQL 본문의
#   product_name·data_origin 인라인 주석에 그대로 남겼다(다음 사람이 같은 함정에
#   COALESCE를 다시 넣지 않도록).
#   잠금(②)은 **다섯만** 넣었다 — data_origin은 뺐다. 판단 근거:
#     · product_name·maker — patch_product의 EDITABLE(admin_products.py:334-335)에
#       이미 있다. 운영자가 상세에서 고치고 잠글 수 있는 필드인데 이 UPSERT가 그
#       잠금을 못 보는 것은 위 "잠금 범위" 요약이 이미 **기존 결함**으로 짚어 온
#       구멍이다 — 지금 막는다.
#     · model_name·spec_source_text — patch_product·검수 승인 어디에도 이 값을
#       locked_fields에 넣는 길이 없다(실측: EDITABLE 키 7개 중 없음,
#       admin_reviews.PRODUCT_FIELD_CAST = {'market_price'}뿐이라 검수 승인 경로도
#       아님). **지금은 가드가 죽은 코드다.** 그래도 넣은 이유: 넣어서 생기는 위험이
#       없고(잠글 방법이 없으니 오작동할 수도 없다), 나중에 EDITABLE이 넓어질 때
#       (오늘 supplier가 그랬듯) 엔진을 다시 배포하지 않아도 되게 하는 편이
#       "지금 안 쓰니까 굳이" 보다 낫다고 판단했다.
#     · danawa_code — 위와 같은 "지금은 무용지물" 이유가 똑같이 적용되지만,
#       **값의 무게가 달라 넣었다.** 시세 관측(단가표 자동 매칭)이 이 컬럼 하나로
#       이어지므로, 나중에 잠금 UI가 필요해질 개연성이 model_name·spec_source_text
#       보다 높다고 판단했다 — 정성적 판단이라 사장님이 다르게 볼 수 있다(보고 참조).
#     · **data_origin은 잠금도 COALESCE도 다 뺐다 — 이번 확장에서 문자 그대로
#       바뀌지 않은 유일한 컬럼이다.** 잠금을 빼는 이유: 이 값은 CSV 한 행의
#       속성이 아니라 적재 «작업 전체»에 매기는 real/demo 분류이고(build_plan()의
#       `origin` 인자, CSV 컬럼이 아니다), `v_recommendation_candidates`·
#       `admin_pool.py`가 `data_origin IS DISTINCT FROM 'demo'`로 추천 후보를
#       거르는 **게이트**다(CANON.md 함정표 "시연용 상품이 견적에" 항목과 같은
#       컬럼). 잠그면 다음 CSV 적재로도 오분류를 못 고친다 — 데모로 잘못 박힌
#       실제 상품은 영영 후보에서 빠지고, 반대로 실제로는 데모인데 실데이터로
#       잘못 잠긴 상품은 교정 시도가 와도 안 풀려 고객 견적에 계속 노출될 수
#       있다. 사양·분류·가격 잠금은 "우리가 소싱/판정해 안다"는 값을 지키는
#       장치인데, data_origin은 애초에 "이 배치가 진짜인가 시험인가"를 매번
#       다시 선언하는 값이라 성격이 다르다. COALESCE를 빼는 이유는 product_name과
#       같다 — data_origin도 실측상 NOT NULL 컬럼이라 COALESCE가 방어막 역할을
#       못 한다(위 ① 문단 참조). 실제 보호는 호출부 쪽에 있다 — 둘 다
#       (`admin_catalog_import.py` Form 검증 · `tools/catalog_import.py`
#       argparse choices) origin을 'real'|'demo' 로만 강제해 :origin이 애초에
#       NULL일 수 없다.
UPSERT_PRODUCTS_SQL = """
    INSERT INTO products (product_code, sku, product_name, maker, model_name, part_type,
      category_group, status, ai_candidate_yn, review_required_yn, purchase_price,
      sale_price, market_price, supplier, danawa_code, stock_qty, spec_source_text,
      data_origin)
    VALUES (:pc, :sku, :name, :maker, :model, :pt, :grp, :status, :ai, :rev, :pp, :sp2,
      :mp, :sup, :dan, :stock, :spec_text, :origin)
    ON CONFLICT (product_code) DO UPDATE SET
      -- product_name(2026-08-24 — 나머지 여섯 확장, 아래 "여섯 컬럼 확장" 문단):
      -- **잠금만 적용하고 COALESCE는 안 썼다 — 여기가 supplier·maker와 다르다.**
      -- product_name은 NOT NULL 컬럼이다(실측: information_schema.columns.is_nullable=
      -- 'NO'). 그런데 PostgreSQL은 `ON CONFLICT DO UPDATE`에서도 NOT NULL을 **VALUES
      -- 단계(=충돌 판정 이전, SET절의 COALESCE가 평가되기도 전)에서** 검사한다 —
      -- 임시 테이블로 직접 재현해 확인했다: NOT NULL 컬럼 하나짜리 표에 같은 모양의
      -- `ON CONFLICT DO UPDATE SET col = COALESCE(EXCLUDED.col, t.col)`를 걸어도
      -- 새로 주는 값이 NULL이면 COALESCE가 평가되기도 전에 그대로 위반으로 죽는다.
      -- 즉 COALESCE를 적어도 상품명 파라미터가 NULL이면 무조건 이 문장 전체가
      -- IntegrityError로 죽는다 — COALESCE는 실행되지도 못한다. 그래서 이 컬럼의
      -- "빈 값 보호"는 SQL이 아니라 **build_plan()의 상위 검증**(221-223행,
      -- 상품명이 비면 그 행 자체를 prods에 안 올리고 errors로 보낸다)이 전부 한다 —
      -- 여기 도달하는 상품명 값은 원천적으로 빈 값일 수 없다. 잠금(②)은 유효하다 —
      -- patch_product의 EDITABLE에 이미 있어(admin_products.py 334-335행, "name")
      -- 운영자가 상세에서 고치고 잠글 수 있는데, 이 UPSERT가 그 잠금을 못 보는 것은
      -- 위 잠금범위 주석이 이미 «이번에도 고치지 않은 기존 결함»으로 지목했던 바로
      -- 그 구멍이다 — 이번에 막는다.
      product_name = CASE WHEN products.locked_fields ? 'product_name'
                          THEN products.product_name
                          ELSE EXCLUDED.product_name END,
      -- maker(같은 2026-08-24): product_name과 달리 **NULL 허용 컬럼**이라(실측:
      -- is_nullable='YES') 위 NOT NULL 함정이 없다 — COALESCE가 정상 작동한다.
      maker = CASE WHEN products.locked_fields ? 'maker'
                   THEN products.maker
                   ELSE COALESCE(EXCLUDED.maker, products.maker) END,
      -- model_name: 빈 값 보호는 같은 이유로 필요하지만, **잠금은 지금 무용지물이다** —
      -- EDITABLE·검수 승인(_approve_product_field, market_price 전용) 어디에도
      -- 'model_name'을 locked_fields에 넣는 경로가 없다(실측: PRODUCT_FIELD_CAST =
      -- {'market_price'}뿐). 그래도 가드를 미리 둔다 — CSV 빈 칸 보호(COALESCE)는
      -- 잠금 유무와 무관하게 필요하므로 CASE 틀은 이미 있고, 나중에 EDITABLE이
      -- 넓어지면(공급처가 방금 그랬듯) 이 엔진 쪽을 다시 배포할 필요가 없어진다.
      -- 해가 되는 경우가 없다는 점이 danawa_code·spec_source_text와 같다(data_origin과
      -- 다른 점 — 아래 참조).
      model_name = CASE WHEN products.locked_fields ? 'model_name'
                        THEN products.model_name
                        ELSE COALESCE(EXCLUDED.model_name, products.model_name) END,
      status = EXCLUDED.status,
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
      -- supplier(공급처, 2026-08-24 — 오늘 지시): purchase_price·sale_price와 완전히
      -- 같은 표현이다. 근거는 위 "supplier(공급처) 전용" 문단 — CSV 빈 칸이 그대로
      -- EXCLUDED.supplier(NULL)로 들어와 4,113건이 지워진 실사고를 이 CASE가 막는다.
      supplier = CASE WHEN products.locked_fields ? 'supplier'
                      THEN products.supplier
                      ELSE COALESCE(EXCLUDED.supplier, products.supplier) END,
      -- danawa_code(2026-08-24): **시세를 잇는 열쇠**라 잠금 가드를 지금 넣어 둔다 —
      -- model_name과 같이 지금은 걸어 줄 UI 경로가 없어 무용지물이지만(위와 같은 실측),
      -- 값의 무게가 다르다고 판단했다: 이 컬럼이 잘못 덮이면 단가표 자동 매칭이
      -- 조용히 끊긴다(build_plan()의 중복 대표 판정과도 맞물린다 — 아래 참고).
      -- 빈 값 보호는 두 원인을 함께 지킨다 — ① CSV의 다나와No 칸이 비어 있을 때
      -- ② 이 배치 안에서 이 상품이 "대표"가 아니거나 DB에서 이미 다른 상품이 그
      -- 코드를 쥐고 있을 때(build_plan의 dan_rep/dan_owner 판정, 240-248행) — 두
      -- 경우 다 build_plan이 이미 dan_use=None으로 넘기므로 COALESCE가 기존 값을
      -- 그대로 지킨다. **주의**: ②의 COALESCE는 "이 상품이 그 코드를 새로 받지
      -- 못한다"만 막을 뿐, 기존에 갖고 있던(어쩌면 이제 안 맞는) danawa_code를
      -- 적극적으로 재검증하지는 않는다 — 그건 이번 지시 범위 밖이다.
      danawa_code = CASE WHEN products.locked_fields ? 'danawa_code'
                        THEN products.danawa_code
                        ELSE COALESCE(EXCLUDED.danawa_code, products.danawa_code) END,
      stock_qty = EXCLUDED.stock_qty,
      -- spec_source_text(2026-08-24): model_name과 같은 성격 — 빈 값 보호는 유효하고
      -- 잠금 가드는 지금은 걸어 줄 UI 경로가 없어 무용지물이지만 미리 둔다(해될 게 없다).
      spec_source_text = CASE WHEN products.locked_fields ? 'spec_source_text'
                              THEN products.spec_source_text
                              ELSE COALESCE(EXCLUDED.spec_source_text,
                                            products.spec_source_text) END,
      -- data_origin(2026-08-24): **잠금도 COALESCE도 안 썼다 — 결과적으로 이 줄은
      -- 이번 확장 전과 문자 그대로 같다.** 잠금을 뺀 이유는 나머지 다섯과 다른
      -- 종류의 컬럼이라서다(근거는 위 "여섯 컬럼 확장" 문단) — 이 값은 CSV 칸이
      -- 아니라 적재 «작업 단위» 전체에 매기는 real/demo 분류이고
      -- (`v_recommendation_candidates`·`admin_pool.py`가 data_origin='demo'를 추천
      -- 후보에서 제외하는 «게이트»다), 잠그면 오분류를 다음 적재로도 못 고친다.
      -- COALESCE를 뺀 이유는 product_name과 같다 — data_origin도 NOT NULL 컬럼이라
      -- (실측: is_nullable='NO') PostgreSQL이 COALESCE 평가 전에 VALUES 단계에서
      -- 이미 NOT NULL을 검사한다(위 product_name 주석 · 임시 테이블 재현 참조).
      -- COALESCE(EXCLUDED.data_origin, ...)를 적어도 origin 파라미터가 NULL이면
      -- 그대로 죽으므로 "빈 값이면 지키는" 방어막 역할을 못 한다 — 적으나 안 적으나
      -- 결과가 같다면 없는 게 정직하다. 실제 보호는 **호출부의 값 자체 제한**이
      -- 한다(둘 다 origin을 'real'|'demo' 로만 강제해 그 값이 애초에 NULL일 수 없다 —
      -- admin_catalog_import.py 83행 Form 검증, tools/catalog_import.py 45행
      -- argparse choices). 그래서 이 값은 항상 EXCLUDED를 그대로 쓴다.
      data_origin = EXCLUDED.data_origin,
      updated_at = now()
"""
# 잠금 가드가 있어야 하는 컬럼 — 회귀[44]가 이 목록과 SQL 본문을 대조한다(정적 검사).
# **data_origin은 일부러 여기 없다** — 잠금(CASE WHEN locked_fields 가드)도 COALESCE도
# 둘 다 없이 여전히 무조건 EXCLUDED다(이번 확장 전과 문자 그대로 같다). 근거는
# UPSERT_PRODUCTS_SQL의 data_origin 인라인 주석(2026-08-24) — ① 잠그면 real/demo
# 오분류를 다음 적재로도 못 고친다(추천 후보 게이트) ② NOT NULL 컬럼이라 COALESCE는
# 애초에 방어막이 못 된다(PostgreSQL이 VALUES 단계에서 먼저 죽는다 — product_name과
# 같은 함정). 이 목록에 넣지 않은 것 = 「빠뜨렸다」가 아니라 「잠그지 않기로 판단했다」.
LOCK_AWARE_PRODUCT_COLS = ("purchase_price", "sale_price", "part_type", "category_group",
                           "ai_candidate_yn", "review_required_yn", "market_price",
                           "supplier", "product_name", "maker", "model_name",
                           "danawa_code", "spec_source_text")

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

    # ── product_imports — 반영 행 원본 냉동 보관 (2026-08-24, 사장님 지시) ──────────
    # **이건 새 기능이 아니라 «안 지키고 있던 기존 설계를 이제 지키는 것»이다.**
    # ERD(`docs/06_db-erd.md` §3.1)는 이 표를 "CSV 업로드 원본 행을 JSONB로 통째
    # 보존 — 목적은 재정규화 가능성"이라고 2026-07-07(ADR-001)에 이미 정의해 뒀다.
    # 그런데 실제로는 `apply_plan`이 여기 쓰는 코드가 **아예 없었다** — 실측 0행.
    # 그 "없음"은 나중에 다른 문서 세대에서 "성공 행 원본은 저장하지 않는다(원본
    # CSV가 정본, 용량 중복 회피)"는 별도 근거로 재해석됐다(`api/admin_imports.py`
    # 독스트링 · `templates/admin/catalog_import.html.j2` · `docs/design/req/
    # req-product-bulk-import.md`의 쓰는 테이블 표 — 셋 다 "설계상 항상 0행"이라
    # 명시). **오늘 그 근거가 실패로 드러났다**: 공급처 CSV 빈 칸이 4,113건을
    # NULL로 덮었는데(위 supplier 전용 문단) 되짚을 원본이 어디에도 없었고, Cloud
    # SQL point-in-time 복구도 창(7일)을 넘겨 못 썼다(사고 후 9일). "원본 CSV가
    # 정본이라 안 남겨도 된다"는 전제가, 그 원본 CSV 파일 자체를 못 구하는 순간
    # 무너진다는 뜻이다. **위 세 문서는 이 커밋 이후로 사실이 아니게 된다** — 이
    # 파일 담당 범위 밖이라 고치지 않았다(보고 참조 — 각 파일 담당자·기록자가
    # 갱신해야 한다).
    #
    # **전 행 vs 바뀐 행만 — 전 행을 택했다.** ERD의 존재 이유("재정규화 가능성")는
    # 정규화 룰이 나중에 바뀌면 이 표에서 다시 돌리는 것이다 — 그 용도에는 "이번에
    # 값이 안 바뀐 행"의 원본도 똑같이 필요하다(안 바뀐 행도 룰이 바뀌면 다르게
    # 분류될 수 있다). "바뀐 행만"으로 좁히려면 "바뀜"의 정의가 필요한데, 그 정의를
    # 잘못 짜면 오늘 고친 것과 똑같은 병(조용한 누락)을 새 코드에 또 심는 꼴이다 —
    # 이번 사고의 교훈과 정면으로 어긋난다. 대신 **정리(오래된 것 치우기)는 별도
    # 장치로 미룬다** — 이 파일은 짓지 않는다(제안만, 보고 참조).
    #
    # **원본은 build_plan()의 `r`(csv.DictReader가 만든 행 그대로, Korean 헤더)** —
    # prods 항목에 "raw" 키로 이미 실어 왔다(위 prods.append 참조). csv_import_errors가
    # 거부 행 원본을 담당하는 것과 대칭이다(성공 행은 여기, 거부 행은 거기 — 표 역할이
    # 겹치지 않는다). BATCH(500)로 나눠 넣는다 — 위 상품 UPSERT와 같은 방식.
    ins_pi = text(
        "INSERT INTO product_imports (job_id, product_code, raw_row)"
        " VALUES (:job, :pc, CAST(:raw AS JSONB))")
    import_rows = [{"job": job_id, "pc": p["pc"], "raw": json.dumps(p["raw"], ensure_ascii=False)}
                   for p in prods]
    for i in range(0, len(import_rows), BATCH):
        conn.execute(ins_pi, import_rows[i:i + BATCH])

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
