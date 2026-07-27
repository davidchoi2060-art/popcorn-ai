# -*- coding: utf-8 -*-
"""검수 제안 승인 — 기계 검증을 통과한 것만 (슬라이스 52).

실행:
  .venv/Scripts/python tools/approve_suggestions.py --dry
  .venv/Scripts/python tools/approve_suggestions.py --min-sim 0.9

**A-18(사람 확인 전제)을 우회하지 않는다.** 620건을 하나씩 클릭하는 것은 비현실적이지만,
"전부 자동 승인"도 답이 아니다. 그래서 **기계가 확실히 판정할 수 있는 것만** 통과시키고
나머지는 사람에게 남긴다:

  · 제목 유사도가 임계 이상 — pcode가 같은 상품을 가리킨다는 근거
  · 값이 물리적으로 가능한 범위 안 (GPU 길이 120~600mm 등)
  · 목록·열거형이 우리가 아는 값

이 검증이 실제로 일했다: SFX 파워 13건이 `m-ATX`로 제안돼 있었다(다나와 파서가 SFX를
몰라 "M-ATX(SFX)"에서 앞의 것만 잡았다). 그대로 승인했다면 소형 파워가 일반 케이스에
호환되는 것으로 판정됐을 것이다.

승인은 API를 거치지 않고 `_approve`(단건 검수와 같은 함수)를 직접 부른다 —
정본 반영·검수 상태 전이·후보 진입 판정이 화면 승인과 **완전히 같은 경로**여야 한다.
"""
import argparse
import io
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv                      # noqa: E402
from sqlalchemy import create_engine, text          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 물리적으로 가능한 범위. 벗어나면 기계가 판정하지 않고 사람에게 넘긴다.
RANGE = {
    "gpu_max_mm": (120, 600), "cooler_height_mm": (20, 220), "length_mm": (100, 450),
    "tdp_watt": (15, 400), "rated_watt": (150, 2000), "cooler_tdp": (30, 400),
    "clock_mhz": (1600, 9000), "required_power_watt": (150, 1200),
    "capacity_gb": (1, 65536), "refresh_hz": (24, 600),
}
ENUM = {
    "mem_type": {"DDR3", "DDR4", "DDR5"},
    "form_factor": {"ATX", "m-ATX", "mini-ITX", "E-ATX", "SFX", "TFX", "Flex-ATX",
                    "M.2 (2280)", "M.2 (2242)", "M.2 (22110)", "6.4cm(2.5형)", "8.9cm(3.5형)"},
}
FF_OK = {"ATX", "m-ATX", "mini-ITX", "E-ATX"}
# product_specs에서 INTEGER인 필드 — 소수 제안은 캐스트가 실패한다
INT_FIELDS = {"length_mm", "rated_watt", "refresh_hz", "capacity_gb", "clock_mhz",
              "tdp_watt", "required_power_watt", "gpu_max_mm", "cooler_height_mm",
              "cooler_tdp"}


def verdict(field: str, value, sim: float, min_sim: float) -> str | None:
    """통과면 None, 아니면 사람이 봐야 하는 사유."""
    if sim < min_sim:
        return f"유사도 {sim:.2f} < {min_sim}"
    if field in RANGE:
        try:
            n = float(str(value))
        except ValueError:
            return f"{field}={value} 숫자 아님"
        lo, hi = RANGE[field]
        if not lo <= n <= hi:
            return f"{field}={value} 범위 밖({lo}~{hi})"
        # 정수 컬럼에 소수가 오면(다나와가 "241.3mm"로 준다) 캐스트가 실패한다.
        # 임의로 반올림하지 않는다 — 값을 바꾸는 판단은 사람 몫이다.
        if field in INT_FIELDS and "." in str(value):
            return f"{field}={value} 소수(정수 컬럼) — 반올림 판단 필요"
        return None
    if field in ("form_factor_list", "socket_list"):
        try:
            lst = json.loads(value)
        except Exception:                            # noqa: BLE001
            return f"{field}={value} JSON 아님"
        if not isinstance(lst, list) or not lst:
            return f"{field} 빈 목록"
        if field == "form_factor_list" and not set(lst) <= FF_OK:
            return f"{field}={value} 미지 규격"
        return None
    if field in ENUM and str(value) not in ENUM[field]:
        return f"{field}={value} 허용값 아님"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--min-sim", type=float, default=0.9,
                    help="제목 유사도 하한 (기본 0.9 — 같은 상품이라는 근거)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT r.review_id, r.field_name, r.suggested_value, r.detail,
                   p.part_type, p.product_name
              FROM product_reviews r JOIN products p USING (product_code)
             WHERE r.review_status='대기' AND r.suggested_value IS NOT NULL
             ORDER BY r.review_id""")).all()
        pool_before = c.execute(text("SELECT count(*) FROM v_recommendation_candidates"
                                     " WHERE stock_qty > 0")).scalar()

    passed, held = [], []
    for rid, field, value, detail, pt, name in rows:
        m = re.search(r"유사도\s*([\d.]+)", detail or "")
        sim = float(m.group(1)) if m else 0.0
        why = verdict(field, value, sim, args.min_sim)
        (held if why else passed).append((rid, field, value, pt, name, why))

    print(f"제안 {len(rows):,}건 → 기계 검증 통과 {len(passed):,}건 ·"
          f" 사람 검수로 남김 {len(held):,}건")
    print("\n남기는 사유")
    for k, n in Counter((h[5] or "").split("=")[0].split(" ")[0] for h in held).most_common(8):
        print(f"  {k:24s} {n:>4}")
    print("\n승인할 필드 상위")
    for k, n in Counter(f"{p[3]}.{p[1]}" for p in passed).most_common(8):
        print(f"  {k:34s} {n:>4}")

    if args.dry:
        print("\n--dry 모드 — DB를 바꾸지 않았습니다.")
        return
    if not passed:
        print("\n승인할 항목이 없습니다.")
        return
    if args.limit:
        passed = passed[:args.limit]

    # 화면 승인과 같은 경로(_approve)를 쓴다 — 정본 반영·상태 전이·후보 판정이 갈리면 안 된다
    from api.admin_reviews import _approve, _lock_waiting_review
    from api.admin_orders import _log

    done, failed, pool_added = 0, [], 0
    # **건별 트랜잭션**이다. 하나로 묶었다가 형식 오류 1건이 배치 전체를 롤백시켰다
    # (241.3 → INTEGER 실패 → 이후 전부 InFailedSqlTransaction). 승인은 각각 독립
    # 사건이므로 원장 관점에서도 건별이 맞다.
    for rid, field, value, pt, name, _ in passed:
        try:
            with engine.begin() as conn:
                review = _lock_waiting_review(conn, rid)
                before, added = _approve(conn, review, value, "승인")
                pool_added += added
                _log(conn, "review_process", str(rid),
                     {"mode": "approve", "review_id": rid, "field": field,
                      "value": str(value), "before": before,
                      "note": "다나와 제안 · 기계 검증 통과(유사도·범위·열거값)"})
            done += 1
        except Exception as ex:                      # noqa: BLE001
            failed.append((rid, field, str(ex)[:80]))
        if done and done % 100 == 0:
            print(f"  승인 {done:,}/{len(passed):,}")

    with engine.connect() as c:
        pool = c.execute(text("SELECT count(*) FROM v_recommendation_candidates"
                              " WHERE stock_qty > 0")).scalar()
        left = c.execute(text("SELECT count(*) FROM product_reviews"
                              " WHERE review_status='대기'")).scalar()
    print(f"\n승인 {done:,}건 · 실패 {len(failed)}건 · 추천 후보 진입 {pool_added:,}")
    print(f"  추천 후보 {pool_before:,} -> {pool:,} · 검수 대기 {left:,}")
    for rid, field, err in failed[:5]:
        print(f"    실패 {rid} {field}: {err}")


if __name__ == "__main__":
    main()
