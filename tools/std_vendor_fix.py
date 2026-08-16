# -*- coding: utf-8 -*-
"""제조사 자료로 사양을 바로잡는다 — `source='vendor'` (2026-08-10)

■ 왜 필요한가
  저쪽 원문(`pd_spec`)은 **등록 시점에 멈춰 있다.** 같은 제품인데 SKU 마다 소켓 목록이
  다른 것이 실제로 확인됐다(쿨러 모델 770그룹 중 **58그룹 · SKU 160개**).

    Thermalright Peerless Assassin 120 SE — SKU 4개
      112835 : LGA1200 · LGA115(X) · LGA2011 … AM4        ← LGA1700 아예 없음
      114723 : 소켓1700 · LGA1200 …                        ← 있음
      129384 : LGA1851 · LGA1700 · … · AM5 · AM4          ← 최신

  쿨러는 브래킷 추가로 신규 소켓을 지원하게 되는데 상품 텍스트는 안 따라간다.
  **파싱으로는 영원히 못 고친다.** 제조사 자료를 봐야 한다.

■ 이 도구가 지키는 것
  · `source='vendor'` · `locked=true` — 다음 재파싱이 덮지 못한다.
  · **`source_ref` 에 출처 URL 을 반드시 남긴다.** 근거 없는 값은 지어낸 값과 같다.
  · 드라이런이 기본. 무엇이 늘고 무엇이 빠지는지 **양쪽 다** 보여준다 —
    제조사 자료는 빠진 것을 채우기도 하지만 **잘못 들어간 것을 빼기도 한다.**
  · `public` 은 건드리지 않는다.

■ 한계 — 정직하게 적는다
  **이건 자동화되지 않는다.** 모델마다 사람이 제조사 자료를 확인해야 한다.
  58그룹이면 검색 수십 회다. 다만 「같은 모델의 SKU 간 소켓이 다르다」가
  **검증 대상을 좁히는 신호**라, 전수 확인보다 훨씬 적게 든다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console                    # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                                    # noqa: E402
from sqlalchemy import create_engine, text                        # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
ENGINE = create_engine(os.environ["DATABASE_URL"])

# (상품명 LIKE 패턴, 부품종류 접두, 필드, 값, 출처 URL, 확인 메모)
FIXES = [
    (
        "%KRAKEN ELITE%", "COOLER", "socket_list",
        ["LGA1851", "LGA1700", "LGA1200", "LGA115(X)", "AM5", "AM4"],
        "https://support.nzxt.com/hc/en-us/articles/47306825106459-Kraken-Elite-2024-Specs",
        "NZXT 공식: Intel LGA1851/1700/1200/115X + AMD AM5/AM4. "
        "sTRX4·TR4 는 '브래킷 미포함'이라 지원 여부가 우리 운영 정책에 달렸다 — 보류",
    ),
]


ADD_ONLY = True   # --replace 로 끈다


def run(apply_it):
    with ENGINE.connect() as c:
        plan = []
        for like, ptype, field, val, url, note in FIXES:
            rows = c.execute(text(
                "SELECT p.product_code, p.product_name, s.value_json, s.source, s.locked"
                " FROM products p LEFT JOIN std.part_specs s"
                "   ON s.product_code = p.product_code AND s.field_key = :f"
                " WHERE p.product_name ILIKE :l AND p.part_type LIKE :t"
                "   AND p.category_group = 'core_part'"
                " ORDER BY p.product_code"),
                {"f": field, "l": like, "t": ptype + "%"}).all()
            for pc, nm, cur, src, lk in rows:
                old = sorted(str(x) for x in (cur or []))
                # `--add-only` 는 **넣기만 하고 빼지 않는다.**
                # 제조사 자료가 "빠졌다"고 말하는 근거와 "지원하지 않는다"고 말하는 근거는
                # 세기가 다르다. NZXT 는 Threadripper 를 "브래킷 미포함" 이라 적는데,
                # 그건 **우리가 브래킷을 구비하느냐**에 달린 운영 정책 문제다.
                # 잘못 빼면 팔 수 있는 조합을 못 팔게 되고, 그건 조용한 손실이다.
                new = sorted(set(old) | set(val)) if ADD_ONLY else sorted(val)
                plan.append((pc, nm, field, old, new, src, lk, url, note))

    print("=" * 74)
    print("제조사 자료 반영 — %s" % ("적용" if apply_it else "드라이런(쓰지 않음)"))
    print("=" * 74)
    add = rm = same = 0
    for pc, nm, field, old, new, src, lk, url, note in plan:
        a, d = set(new) - set(old), set(old) - set(new)
        if not a and not d:
            same += 1
            continue
        add += bool(a)
        rm += bool(d)
        print("\n  %s %s   [기존 출처 %s%s]" % (pc, nm[:48], src or "없음", " · 잠김" if lk else ""))
        if a:
            print("     + %s" % sorted(a))
        if d:
            print("     - %s   ← 제조사 자료에 없다" % sorted(d))
    print("\n  대상 %d건 · 값이 늘어남 %d · **줄어듦 %d** · 변화 없음 %d"
          % (len(plan), add, rm, same))
    print("  출처: %s" % FIXES[0][4])
    if not apply_it:
        print("\n적용하려면 --apply")
        return 0

    with ENGINE.begin() as c:
        n = 0
        for pc, nm, field, old, new, src, lk, url, note in plan:
            c.execute(text(
                "INSERT INTO std.part_specs"
                " (product_code, field_key, value_json, source, source_ref,"
                "  confidence, locked, updated_at)"
                " VALUES (:pc, :f, CAST(:v AS JSONB), 'vendor', :ref, 1.00, true, now())"
                " ON CONFLICT (product_code, field_key) DO UPDATE SET"
                "   value_json = EXCLUDED.value_json, value_text = NULL, value_num = NULL,"
                "   source = 'vendor', source_ref = EXCLUDED.source_ref,"
                "   confidence = 1.00, locked = true, updated_at = now()"),
                {"pc": pc, "f": field, "v": json.dumps(new, ensure_ascii=False),
                 "ref": ("%s | %s" % (note, url))[:200]})
            n += 1
    print("\n적용 완료 — %d건 (source='vendor' · 잠김)" % n)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--replace", action="store_true",
                    help="제조사 목록으로 **교체**한다(빼기 포함). 기본은 넣기만 한다")
    a = ap.parse_args()
    ADD_ONLY = not a.replace
    sys.exit(run(a.apply))
