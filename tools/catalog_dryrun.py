# -*- coding: utf-8 -*-
"""카탈로그 적재 사전 검증(dry-run) — DB를 건드리지 않고 추출률만 실측한다 (슬라이스 39).

실행:
  .venv/Scripts/python tools/catalog_dryrun.py

적재 전에 "몇 건이 추천 풀에 들어가고 몇 건이 검수로 가는지"를 먼저 안다. 이 숫자를 모른 채
24,303행을 넣으면, 결과가 나쁠 때 파서 문제인지 원천 문제인지 구분할 수 없다.
"""
import csv
import io
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

from api.catalog_map import extract_specs, map_part_type   # noqa: E402

SRC = r"E:\GDRIVE\0.신사업\2.AI 영업사원\2단계\산출물"
MASTER = os.path.join(SRC, "최종_정제완료_상품데이터.csv")
DB_PRODUCTS = os.path.join(SRC, "db_products.csv")
DB_SPECS = os.path.join(SRC, "db_product_specs.csv")

REQUIRED = {
    "CPU": ["socket", "tdp_watt"],
    "MB": ["socket", "chipset", "form_factor", "mem_type"],
    "RAM": ["mem_type", "capacity_gb", "clock_mhz"],
    "GPU": ["length_mm", "required_power_watt", "pcie_gen"],
    "SSD": ["form_factor", "interface", "capacity_gb"],
    "HDD": ["form_factor", "interface", "capacity_gb"],
    "POWER": ["rated_watt", "form_factor"],
    "CASE": ["form_factor", "gpu_max_mm", "cooler_height_mm"],
    "COOLER_CPU_AIR": ["socket_list", "cooler_height_mm", "cooler_tdp"],
    "COOLER_CPU_AIO": ["socket_list", "cooler_tdp"],
    "MONITOR": ["size_inch", "resolution", "refresh_hz", "panel"],
}


def load_gpu_ref():
    """DB에서 참조표를 읽는다(없으면 빈 dict — dry-run은 DB 없이도 돌아야 한다)."""
    try:
        from dotenv import load_dotenv
        from sqlalchemy import create_engine, text
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
        e = create_engine(os.environ["DATABASE_URL"])
        with e.connect() as c:
            return dict(c.execute(text(
                "SELECT chipset_key, recommended_watt FROM gpu_power_reference")).all())
    except Exception as ex:
        print(f"  (GPU 참조표 로드 실패 — reference 계층 제외: {type(ex).__name__})")
        return {}


def main():
    gpu_ref = load_gpu_ref()
    print(f"GPU 권장파워 참조표: {len(gpu_ref)}종\n")

    # product_id → 자체상품코드 (EAV 조인 키)
    pid_to_code = {}
    for r in csv.DictReader(io.open(DB_PRODUCTS, encoding="utf-8-sig", newline="")):
        pid_to_code[r["product_id"]] = (r["custom_product_code"] or "").strip()

    # 자체상품코드 → EAV
    kvs, feats = defaultdict(dict), defaultdict(list)
    for r in csv.DictReader(io.open(DB_SPECS, encoding="utf-8-sig", newline="")):
        code = pid_to_code.get(r["product_id"])
        if not code:
            continue
        k, v = (r["spec_key"] or "").strip(), (r["spec_value"] or "").strip()
        if k == "특성":
            feats[code].append(v)
        elif k:
            kvs[code].setdefault(k, v)

    rows = list(csv.DictReader(io.open(MASTER, encoding="utf-8-sig", newline="")))
    stat = defaultdict(lambda: {"n": 0, "sale": 0, "full": 0, "field": Counter(), "src": Counter()})
    skipped, etc, no_spec_row = Counter(), 0, 0

    for r in rows:
        code = (r["자체상품코드"] or "").strip()
        name = (r["상품명"] or "").strip()
        l1, l2, l3 = r["카테고리1"], r["카테고리2"], r["카테고리3"]
        pt, group, reason = map_part_type(l1, l2, l3, name)
        if reason:
            skipped[reason] += 1
            continue
        if pt is None:
            etc += 1
            continue
        sale = (r["상태값"] or "").strip() == "판매중"
        st = stat[pt]
        st["n"] += 1
        if not sale:
            continue
        st["sale"] += 1
        if code not in kvs and code not in feats:
            no_spec_row += 1
        specs, src = extract_specs(pt, kvs.get(code, {}), feats.get(code, []), name, l2, gpu_ref)
        need = REQUIRED.get(pt, [])
        for f in need:
            if specs.get(f) is not None:
                st["field"][f] += 1
        for f, s in src.items():
            st["src"][s] += 1
        if need and all(specs.get(f) is not None for f in need):
            st["full"] += 1

    print("=== 슬롯별 추출 결과 (판매중 기준) ===")
    print(f"{'part_type':16s} {'전체':>7s} {'판매중':>7s} {'전필드':>7s}  필드별 추출률")
    core_full = core_sale = 0
    for pt in ("CPU", "MB", "RAM", "GPU", "POWER", "CASE", "SSD", "HDD",
               "COOLER_CPU_AIR", "COOLER_CPU_AIO", "MONITOR", "KEYBOARD", "MOUSE",
               "HEADSET", "SPEAKER", "WEBCAM"):
        st = stat.get(pt)
        if not st:
            continue
        need = REQUIRED.get(pt, [])
        pct = " · ".join(f"{f} {st['field'][f]*100//max(st['sale'],1)}%" for f in need)
        print(f"{pt:16s} {st['n']:>7,} {st['sale']:>7,} {st['full']:>7,}  {pct}")
        if need and pt not in ("MONITOR",):
            core_full += st["full"]
            core_sale += st["sale"]
    print(f"\n핵심 부품 판매중 {core_sale:,}건 중 **필수 사양 전부 채워진 것 {core_full:,}건**"
          f" ({core_full*100//max(core_sale,1)}%) → 나머지는 검수 큐")
    print(f"\n적재 제외: {dict(skipped)} · part_type 미매핑(etc로 적재) {etc:,}건"
          f" · 사양 행 없음 {no_spec_row:,}건")
    print("\n출처 계층 분포(핵심 부품):")
    total_src = Counter()
    for pt, st in stat.items():
        if REQUIRED.get(pt):
            total_src.update(st["src"])
    print("  " + " · ".join(f"{k} {v:,}" for k, v in total_src.most_common()))


if __name__ == "__main__":
    main()
