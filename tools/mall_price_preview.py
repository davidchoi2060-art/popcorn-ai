# -*- coding: utf-8 -*-
"""몰 공급처 가격 반영 미리보기 -- DB 에 쓰지 않는다 (2026-10-12 신설).

왜 따로 있나
  tools/mall_daily_sync.py 의 드라이런은 2단계(몰 수집)를 DB 에 쓰지 않으므로, 3단계
  (매입가·판매가 재계산)가 **어제 DB 에 있던 공급처 가격**으로 계산된다. 그래서
  드라이런만으로는 "오늘 몰 값으로 반영하면 판매가가 얼마가 되나"를 볼 수 없다.

  이 도구는 직전 드라이런이 남긴 캐시 HTML(.cache/mall_supplier/{pd_no}.html)을
  파싱해 DB 의 product_supplier_prices 위에 «덮어쓴 것처럼» 합친 뒤, 3단계와 같은
  대상 선정·안전장치·공식으로 판매가를 계산한다. 반영은 같은 캐시로
  `tools/mall_daily_sync.py --apply --from-cache` 를 돌리면 된다(미리본 원문 그대로).

사용
  .venv/Scripts/python tools/mall_daily_sync.py --margin 0            # 드라이런, 캐시를 채운다
  .venv/Scripts/python tools/mall_price_preview.py --margin 0 --out preview.csv
  .venv/Scripts/python tools/mall_daily_sync.py --margin 0 --apply --from-cache

쿠키가 필요 없다(네트워크를 쓰지 않는다). DB 는 SELECT 만 한다.
"""
import argparse
import csv
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv                              # noqa: E402
from sqlalchemy import create_engine, text                  # noqa: E402

from tools import mall_supplier_fetch as _msf               # noqa: E402
from tools.mall_daily_sync import _is_big_swing, _big_swing_ratio  # noqa: E402
from api.admin_price_import import _settings                # noqa: E402
from api.mall_supplier_parse import parse_rows, load_suppliers, resolve_supplier  # noqa: E402
from api.pricing import sale_from_purchase                  # noqa: E402


def merged_supply(db_rows: list, fresh_rows: list) -> dict:
    """{supplier_id: (cost, state, rank)} -- DB 행 위에 이번 수집 행을 덮는다.

    반영(_plan_and_maybe_apply)은 (상품, 공급처) 단위 UPSERT 라, 이번 몰 화면에 없는
    공급처의 옛 행은 그대로 남는다. 미리보기도 같은 결과를 내야 하므로 지우지 않고 덮는다."""
    out = {sid: (cost, state, rank) for sid, cost, state, rank in db_rows}
    for sid, cost, state, rank in fresh_rows:
        out[sid] = (cost, state, rank)
    return out


def live_min(supply: dict):
    """3단계의 live CTE 와 같다: '가능' 이고 몰 순위가 있는 행의 최저 매입가."""
    avail = [c for c, s, r in supply.values() if s == "가능" and r is not None and c is not None]
    return min(avail) if avail else None


def plan(prod: dict, mall_min, fee: float, margin: float, swing: float):
    """3단계(_reprice_from_mall) 대상 선정을 상품 하나에 적용한다.

    반환 (판정, 새 판매가). 판정: apply · held · locked · skip."""
    purchase, sale = prod["purchase_price"], prod["sale_price"]
    if not prod["ai_candidate_yn"] or purchase is None or mall_min is None:
        return "skip", None
    if mall_min == purchase or not (mall_min < purchase or mall_min > (sale or 0)):
        return "skip", None
    if "purchase_price" in (prod["locked_fields"] or []):
        return "locked", None
    if _is_big_swing(purchase, mall_min, swing):
        return "held", None
    new_sale = sale if "sale_price" in (prod["locked_fields"] or []) \
        else sale_from_purchase(mall_min, fee, margin)
    return "apply", new_sale


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--margin", type=float, default=None,
                    help="계산에 쓸 마진(예: 0). 주지 않으면 pricing_settings 값")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", type=str, default="mall_price_preview.csv")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])
    swing = _big_swing_ratio()

    with engine.connect() as conn:
        fee, margin = _settings(conn)
        if args.margin is not None:
            margin = args.margin
        codes = _msf.target_codes(conn, "", args.limit)
        suppliers = load_suppliers(conn)
        db = {}
        for pc, sid, cost, state, rank in conn.execute(text(
                "SELECT product_code, supplier_id, cost_price, supply_state, mall_rank"
                " FROM product_supplier_prices")).all():
            db.setdefault(pc, []).append((sid, cost, state, rank))
        prods = {r["product_code"]: dict(r) for r in conn.execute(text(
            "SELECT product_code, product_name, part_type, purchase_price, sale_price,"
            " locked_fields, ai_candidate_yn FROM products"
            " WHERE product_code = ANY(:c)"), {"c": list(codes)}).mappings()}

    out_rows, counts = [], {"apply": 0, "held": 0, "locked": 0, "skip": 0,
                            "no_cache": 0, "no_available": 0}
    for pc in codes:
        p = os.path.join(_msf.CACHE, f"{pc}.html")
        if not os.path.exists(p):
            counts["no_cache"] += 1
            continue
        rows = parse_rows(io.open(p, encoding="utf-8").read())
        fresh = []
        for r in rows:
            sid, _n, _rem, _k = resolve_supplier(r["contact_blob"], suppliers)
            if sid is not None and r["o_price"] is not None and r["state"] is not None:
                fresh.append((sid, r["o_price"], r["state"], r["idx"]))
        if rows and not any(s == "가능" for _sid, _c, s, _r in fresh):
            counts["no_available"] += 1
        prod = prods.get(pc)
        if prod is None:
            continue
        mm = live_min(merged_supply(db.get(pc, []), fresh))
        verdict, new_sale = plan(prod, mm, fee, margin, swing)
        counts[verdict] += 1
        if verdict == "skip":
            continue
        old_sale = prod["sale_price"]
        diff = (new_sale - old_sale) if (new_sale is not None and old_sale) else None
        out_rows.append({
            "product_code": pc, "part_type": prod["part_type"],
            "name": prod["product_name"], "verdict": verdict,
            "purchase_price": prod["purchase_price"], "sale_price": old_sale,
            "mall_min": mm, "new_sale": new_sale, "diff_won": diff,
            "diff_pct": round(diff / old_sale * 100, 1) if diff is not None else None})

    with io.open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else ["product_code"])
        w.writeheader()
        w.writerows(out_rows)

    applied = [r for r in out_rows if r["verdict"] == "apply" and r["diff_won"] is not None]
    up = [r for r in applied if r["diff_won"] > 0]
    down = [r for r in applied if r["diff_won"] < 0]
    print(f"대상 {len(codes)}건 · 마진 {margin} · 수수료 {fee} · 보류 배율 {swing}")
    print(f"반영 {counts['apply']}건(판매가 오름 {len(up)} · 내림 {len(down)}) ·"
          f" 큰 변동 보류 {counts['held']} · 매입가 잠금 {counts['locked']} ·"
          f" 변경 없음 {counts['skip']} · 캐시 없음 {counts['no_cache']} ·"
          f" 판매중 공급처 0곳 {counts['no_available']}")
    print("가장 크게 바뀌는 10건:")
    for r in sorted(applied, key=lambda r: -abs(r["diff_pct"] or 0))[:10]:
        print(f"  {r['product_code']} {r['sale_price']:,} -> {r['new_sale']:,}"
              f" ({r['diff_pct']:+.1f}%) {r['name'][:40]}")
    print(f"표: {args.out}")


if __name__ == "__main__":
    main()
