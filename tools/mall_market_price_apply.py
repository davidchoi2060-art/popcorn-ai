# -*- coding: utf-8 -*-
"""몰 시중가 -> products.market_price (2026-09-22)

■ 무엇을 하나
  팝콘PC 몰 완제PC 상세 상단의 **시중가**를 우리 `products.market_price` 에 올린다.
  우리 DB 는 지금 판매가만 안다(2026-08-23 실측: market_price 양수 467건 · 0 22,649건 ·
  NULL 35건). 시중가가 있어야 고객 화면이 "정가 대비 얼마 싸다"를 근거 있게 말한다.

■ 값 쓰기를 새로 구현하지 않는다
  기존 시세 경로(A-103·A-104·A-108)를 그대로 탄다:
    ① `product_reviews` 에 field_name='market_price' 제안을 넣는다
       (`tools/danawa_fetch.PRICE_INSERT_SQL` 을 그대로 import 해 쓴다 — 같은 SQL 을
        두 벌 두지 않는다. detail 문구만 매개변수로 다르게 준다)
    ② `api.admin_reviews.auto_approve_market_price(review_id)` 로 판정·승인
    ③ 값 쓰기 · `locked_fields` 잠금 · `product_price_history` · 검수행 전이는
       전부 `_approve_product_field()` 가 한다(사람이 화면에서 누를 때와 같은 코드)
  **잠금이 중요하다**: `locked_fields ? 'market_price'` 가 붙어야 다음 카탈로그 적재가
  이 값을 되돌리지 않는다(`api/catalog_ingest.py` UPSERT · A-104).

■ A-108 「첫 값은 사람이 확인한다」와 이 도구의 관계
  자동 승인 판정(`market_auto_approve_decision`)은 현재 값이 0/NULL 이면 «사람 확인»을
  낸다. 완제PC 는 대부분 0 이라 212건이 전부 검수 대기로 남고, 그 큐에는 시세용 일괄
  승인 버튼이 없다(`bulk_confirm` 은 low_confidence 전용) — 사장님이 212번을 눌러야 한다.
  그래서 **`--approve-first` 를 줄 때만** 첫 값도 승인한다. 근거는 사장님의 2026-09-22
  「승인」(스레드 「완제PC 몰 페이지 수집」 — 「시중가를 우리 DB에 넣기」에 대한 답)이고,
  그 사실을 원장 detail 에 남긴다.
  ⚠ **판정 함수는 건드리지 않는다** — 다나와 경로의 규칙은 그대로다. 이 도구가 스스로
  판정을 느슨하게 하는 것이 아니라, 사람이 내린 일괄 결정을 기계적으로 집행하는 것이다.

■ 안 하는 것
  · 드라이런이 기본이다(`--apply` 를 줘야 쓴다).
  · `part_type='PC_COMPLETE'` 인 행만 건드린다.
  · 몰 시중가 < 몰 판매가(뒤집힌 값)면 건너뛴다 — 지어내지 않고 건너뛴 사실을 보고한다.
  · 값이 지금과 같으면 건너뛴다(빈 이력 행을 만들지 않는다).
  · 범위 검증(PRODUCT_PRICE_MIN ~ part_type 별 상한)은 기존 코드가 그대로 한다.
  되돌리기는 기존 경로 그대로다 — `POST /api/admin/reviews/undo/{log_id}`.

■ 실행
    python tools/mall_market_price_apply.py --fetch                 # 드라이런
    python tools/mall_market_price_apply.py --fetch --apply --approve-first
    python tools/mall_market_price_apply.py --from-json out.json --apply --approve-first
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools._console import ensure_utf8_console                       # noqa: E402
ensure_utf8_console()

# 제안 INSERT 는 다나와 경로가 쓰는 것을 «그대로» 쓴다 — 같은 SQL 을 두 벌 두지 않는다.
# review_type 도 같은 값('price_suggest')이다: 이 축은 «무엇에 대한 제안인가»를 말하지
# 출처를 말하지 않는다(출처는 detail 문구에 적는다 — 다나와 제안도 같은 방식이다).
# ⚠ import 를 함수 안에 둔다: `tools.danawa_fetch` 가 모듈 최상단에서 `api.db` 를 끌어와
#   DATABASE_URL 이 없으면 그 자리에서 죽는다. 그러면 `--help` 도, "--fetch 를 주세요"
#   안내도 못 나온다 — DB 가 필요 없는 경로까지 DB 를 요구하게 두지 않는다.

# 사장님 일괄 승인 근거 — 원장 detail 에 그대로 남긴다(왜 첫 값을 사람 클릭 없이
# 넣었는지가 나중에 답이 돼야 한다).
OWNER_APPROVAL = ("사장님 2026-09-22 일괄 승인 - 스레드 '완제PC 몰 페이지 수집'"
                  " ('시중가를 우리 DB에 넣기' 에 대한 답 '승인')")
DETAIL_TMPL = "[몰 시중가: {v:,}원 (popcornpc.co.kr 상세 상단, {when} 관측)]"


def load_from_json(path):
    d = json.load(io.open(path, encoding="utf-8"))
    return d.get("items") if isinstance(d, dict) else d


def fetch_from_mall(limit=None):
    """몰에서 직접 받는다 — 서버에는 수집 JSON 이 없으므로 이 경로가 기본이다."""
    from tools.mall_builtpc_fetch import collect_plist, fetch, parse
    codes, how, total = collect_plist()
    print("목록 %d건(몰이 말한 전체 %s · %s)" % (len(codes), total, how))
    if limit:
        codes = codes[:limit]
    from tools.mall_builtpc_fetch import MAX_FAIL
    items, streak = [], 0
    for i, c in enumerate(codes, 1):
        html, _ = fetch(c)
        if not html:
            streak += 1
            print("  %s 받기 실패 (연속 %d)" % (c, streak))
            # 연속 실패는 차단 신호로 본다 -- 계속 두드리지 않는다(A-18).
            if streak >= MAX_FAIL:
                print("  연속 %d회 실패 -- 수집을 멈춘다." % streak)
                break
            continue
        streak = 0
        items.append(parse(c, html))
        if i % 50 == 0:
            print("  %d/%d" % (i, len(codes)))
    return items


def plan(conn, items):
    """무엇을 바꿀지 정한다. (대상 목록, 건너뛴 사유별 목록)"""
    from sqlalchemy import text
    codes = [str(r["product_code"]) for r in items]
    rows = conn.execute(text(
        "SELECT product_code, part_type, status, sale_price, market_price"
        "  FROM products WHERE product_code = ANY(:codes)"),
        {"codes": codes}).mappings().all()
    db = {str(r["product_code"]): r for r in rows}

    targets, skipped = [], {"우리 DB 에 없음": [], "완제PC 아님": [], "시중가 없음": [],
                            "시중가가 판매가보다 낮음": [], "이미 같은 값": []}
    for it in items:
        pc = str(it["product_code"])
        mp, sp = it.get("market_price"), it.get("sale_price")
        row = db.get(pc)
        if row is None:
            skipped["우리 DB 에 없음"].append(pc); continue
        if row["part_type"] != "PC_COMPLETE":
            skipped["완제PC 아님"].append("%s(%s)" % (pc, row["part_type"])); continue
        if not mp or mp <= 0:
            skipped["시중가 없음"].append(pc); continue
        if sp and mp < sp:
            skipped["시중가가 판매가보다 낮음"].append("%s(%s<%s)" % (pc, mp, sp)); continue
        if row["market_price"] == mp:
            skipped["이미 같은 값"].append(pc); continue
        targets.append({"pc": pc, "new": mp, "old": row["market_price"],
                        "sale_db": row["sale_price"], "status": row["status"]})
    return targets, skipped


def apply_one(t, when, approve_first):
    """제안 한 건 기록 + 승인. (결과문자열, 반영여부)"""
    from api.db import engine
    from api.admin_reviews import (auto_approve_market_price, _lock_waiting_review,
                                   _approve_product_field, _log)
    from tools.danawa_fetch import PRICE_INSERT_SQL, PRICE_REVIEW_TYPE
    with engine.begin() as conn:
        rid = conn.execute(PRICE_INSERT_SQL, {
            "pc": t["pc"], "rtype": PRICE_REVIEW_TYPE,
            "detail": DETAIL_TMPL.format(v=t["new"], when=when),
            "sv": str(t["new"]), "conf": 1.0}).scalar()
    if rid is None:
        return "같은 제안이 이미 대기 중", False

    res = auto_approve_market_price(rid)
    if res["auto_approved"]:
        return "자동 승인(%s)" % res["reason"], True
    if not approve_first:
        return "검수 대기로 남김(%s)" % res["reason"], False

    # 첫 값 일괄 승인 — 값 쓰기는 기존 코드가 한다(위 머리말 참고).
    from fastapi import HTTPException
    with engine.begin() as conn:
        try:
            review = _lock_waiting_review(conn, rid)
            before, _ = _approve_product_field(conn, review, str(t["new"]), "자동승인", auto=True)
        except HTTPException as e:
            return "승인 거부됨(%s)" % e.detail, False
        _log(conn, "review_auto_approve", str(rid), {
            "mode": "approve", "auto": True, "review_id": rid, "field": "market_price",
            "value": str(t["new"]), "pct_change": None, "threshold_pct": None,
            "before": before, "source": "popcornpc.co.kr 상세 상단 시중가",
            "note": OWNER_APPROVAL}, auto=True)
    return "승인(첫 값)", True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="몰에서 직접 받는다")
    ap.add_argument("--from-json", default="", help="수집 JSON 에서 읽는다")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다(기본은 드라이런)")
    ap.add_argument("--approve-first", action="store_true",
                    help="현재 값이 0/NULL 인 «첫 값»도 승인한다(사장님 일괄 승인 근거 필요)")
    a = ap.parse_args()

    if a.from_json:
        items = load_from_json(a.from_json)
        if a.limit:
            items = items[:a.limit]
    elif a.fetch:
        items = fetch_from_mall(a.limit)
    else:
        raise SystemExit("--fetch 또는 --from-json 중 하나를 주세요.")
    print("몰 자료 %d건" % len(items))

    from datetime import date
    from api.db import engine
    with engine.connect() as conn:
        targets, skipped = plan(conn, items)

    print("\n바꿀 것 %d건" % len(targets))
    for t in targets[:10]:
        print("  %s  시중가 %s -> %s  (우리 판매가 %s)"
              % (t["pc"], t["old"], format(t["new"], ","), t["sale_db"]))
    if len(targets) > 10:
        print("  ... 그 밖 %d건" % (len(targets) - 10))
    for why, lst in skipped.items():
        if lst:
            print("건너뜀 · %s %d건: %s" % (why, len(lst), ", ".join(lst[:8])))

    if not a.apply:
        print("\n드라이런입니다 — 아무것도 쓰지 않았습니다. 반영하려면 --apply.")
        return

    when = date.today().isoformat()
    done = 0
    reasons = {}
    for i, t in enumerate(targets, 1):
        msg, ok = apply_one(t, when, a.approve_first)
        done += 1 if ok else 0
        reasons[msg.split("(")[0]] = reasons.get(msg.split("(")[0], 0) + 1
        if i % 25 == 0 or i == len(targets):
            print("  %d/%d  반영 %d" % (i, len(targets), done))
    print("\n반영 %d건 / 대상 %d건" % (done, len(targets)))
    for k, v in reasons.items():
        print("  %s %d건" % (k, v))
    print("되돌리기: 관리자 화면 작업 기록에서 해당 행 되돌리기"
          " (또는 POST /api/admin/reviews/undo/{log_id})")


if __name__ == "__main__":
    main()
