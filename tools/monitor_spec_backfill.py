# -*- coding: utf-8 -*-
"""모니터 사양 회수 — 원문에 있는데 파서가 안 보던 인치·해상도를 채운다 (2026-08-22).

실행:
  .venv/Scripts/python tools/monitor_spec_backfill.py            # 드라이런(기본, DB 무변경)
  .venv/Scripts/python tools/monitor_spec_backfill.py --apply    # 빈 필드만 채운다
  .venv/Scripts/python tools/monitor_spec_backfill.py --apply --fix-wrong
                                                                 # + 틀린 size_inch 도 교정
  .venv/Scripts/python tools/monitor_spec_backfill.py --rollback <스냅샷파일>

■ 왜 respec.py 로 안 되나
`respec.py` 는 대상이 «검수 대기 상태의 핵심 부품»이고, `REQUIRED` 에 없는 슬롯은
`continue` 로 건너뛴다. MONITOR 는 주변기기라 둘 다에 안 걸려 **한 번도 재파싱된 적이
없다.** REQUIRED 에 MONITOR 를 넣으면 4중 게이트 판정까지 바뀌므로(주변기기는 그 게이트의
대상이 아니다) 슬롯 전용 도구를 따로 둔다.

■ 무엇을 고치나 (실측 2026-08-22 · 재고 있는 모니터 579건)
  · `size_inch`  비어 있던 122건 — L2 가 「32인치 이상」이면 INCH_L2 에 그 항목이 없어
    통째로 NULL 이었다(32형 90 · 34형 16 · 49형 5 …).
  · `resolution` 비어 있던 514건 — 원문에 「1920 x 1080, (FHD)」로 있는데 «키가 없어»
    EAV(kv) 로 안 잡혔다. 26건 → 540건.
  · `size_inch` **틀린 값 82건**(--fix-wrong) — L2 분류가 부정확했다. 15·17·19형이
    「24인치 모니터」로 분류돼 24 로 기록돼 있었고, BenQ ZOWIE XL2746K(27형)·
    DELL U4924DW(49형)도 24 였다. 원문이 맞다.

■ 지키는 규칙 (respec.py 와 같다)
  · `locked_fields` 에 잠긴 필드는 건너뛴다(ERD §4.3).
  · `verified_yn` 이 참인 행은 **건드리지 않는다** — 사람이 검수한 값이다.
  · 출처를 `spec_sources` 에 'text_tokens' 로 남긴다.
  · **값을 지어내지 않는다** — 원문에서 안 읽히면 비운 채로 둔다.
  · 되돌림: 바꾸기 전 값을 스냅샷 JSON 으로 남기고 `--rollback` 으로 되돌린다.
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

from sqlalchemy import text                          # noqa: E402

from api.db import engine                            # noqa: E402
from api.catalog_map import monitor_inch, monitor_resolution   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(ROOT, "_private", "backfill-snapshots")


def _load():
    with engine.connect() as c:
        return c.execute(text("""
            SELECT p.product_code, p.product_name, p.locked_fields, p.stock_qty, p.status,
                   p.spec_source_text, ps.size_inch, ps.resolution,
                   ps.spec_sources, ps.verified_yn
              FROM products p
              JOIN product_specs ps ON ps.product_code = p.product_code
             WHERE p.part_type = 'MONITOR'
        """)).mappings().all()


def _differs(field, cur, new):
    """현재값과 새 값이 «실제로» 다른가 — size_inch 는 Decimal 이라 수치로 견준다."""
    if field == "size_inch":
        return float(cur) != float(new)
    return str(cur) != str(new)


def _plan(rows, fix_wrong: bool):
    """(변경목록, 집계) — 무엇을 왜 바꾸는지까지 담는다."""
    updates, tally = [], Counter()
    for r in rows:
        if r["verified_yn"]:
            tally["건너뜀 · 사람이 검수한 행"] += 1
            continue
        locked = set(r["locked_fields"] or [])
        raw = r["spec_source_text"] or ""
        got = {"size_inch": monitor_inch(raw), "resolution": monitor_resolution(raw)}
        vals, before, why = {}, {}, {}
        for f, v in got.items():
            if v is None:
                continue
            if f in locked or f"specs.{f}" in locked:
                tally["건너뜀 · 잠긴 필드"] += 1
                continue
            cur = r[f]
            if cur is None:
                vals[f], before[f], why[f] = v, None, "빈 값을 채움"
                tally[f"{f} · 새로 채움"] += 1
            elif _differs(f, cur, v):
                if not fix_wrong:
                    tally[f"{f} · 값이 다름(교정 안 함)"] += 1
                    continue
                vals[f], before[f], why[f] = v, cur, "L2 분류값을 원문값으로 교정"
                tally[f"{f} · 교정"] += 1
        if vals:
            src = dict(r["spec_sources"] or {})
            for f in vals:
                src[f] = "text_tokens"
            updates.append({"pc": r["product_code"], "name": r["product_name"],
                            "vals": vals, "before": before, "why": why, "src": src})
    return updates, tally


def _apply(updates):
    os.makedirs(SNAP_DIR, exist_ok=True)
    snap = os.path.join(SNAP_DIR, "monitor-spec-%d.json" % len(updates))
    with open(snap, "w", encoding="utf-8") as f:
        # size_inch 는 NUMERIC -> Decimal 이라 그대로는 직렬화되지 않는다. 문자열로 남겨도
        # 되돌릴 때 psycopg2 가 numeric 으로 캐스팅한다(None 은 default 를 안 타고 null 로 간다).
        json.dump([{"pc": u["pc"], "before": u["before"]} for u in updates],
                  f, ensure_ascii=False, indent=1, default=str)
    with engine.begin() as conn:
        for u in updates:
            sets = [f"{f} = :{f}" for f in u["vals"]]
            params = dict(u["vals"], pc=u["pc"],
                          src=json.dumps(u["src"], ensure_ascii=False))
            sets += ["spec_sources = CAST(:src AS JSONB)", "updated_at = now()"]
            conn.execute(text(
                "UPDATE product_specs SET %s WHERE product_code = :pc"
                % ", ".join(sets)), params)
    return snap


def _rollback(path):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    with engine.begin() as conn:
        for r in rows:
            sets = [f"{f} = :{f}" for f in r["before"]]
            if not sets:
                continue
            conn.execute(text(
                "UPDATE product_specs SET %s, updated_at = now() WHERE product_code = :pc"
                % ", ".join(sets)), dict(r["before"], pc=r["pc"]))
    print("되돌림 완료 — %d건" % len(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 반영한다(기본은 드라이런)")
    ap.add_argument("--fix-wrong", action="store_true", help="틀린 size_inch 도 교정한다")
    ap.add_argument("--rollback", metavar="스냅샷", help="스냅샷으로 되돌린다")
    args = ap.parse_args()

    if args.rollback:
        _rollback(args.rollback)
        return

    rows = _load()
    updates, tally = _plan(rows, args.fix_wrong)
    print("모니터 {:,}건을 재파싱합니다\n".format(len(rows)))
    print("=== 계획 ===")
    for k, v in sorted(tally.items(), key=lambda x: -x[1]):
        print("  %-34s %5d" % (k, v))
    print("\n바뀌는 상품 %d건" % len(updates))

    if updates:
        print("\n=== 표본 5건 ===")
        for u in updates[:5]:
            for f, v in u["vals"].items():
                print("  %-34s %-11s %s -> %s" % (u["name"][:34], f,
                      u["before"][f] if u["before"][f] is not None else "(빈값)", v))

    if not args.apply:
        print("\n드라이런 — DB를 바꾸지 않았습니다. 반영하려면 --apply")
        return
    if not updates:
        print("\n바꿀 것이 없습니다.")
        return
    snap = _apply(updates)
    print("\n반영 완료 — %d건" % len(updates))
    print("되돌림: .venv/Scripts/python tools/monitor_spec_backfill.py --rollback %s" % snap)


if __name__ == "__main__":
    main()
