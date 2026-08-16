# -*- coding: utf-8 -*-
"""오분류 교정 — 원천이 액세서리로 분류한 상품을 부품 자리에서 내린다 (슬라이스 51).

실행:
  .venv/Scripts/python tools/reclassify.py --dry
  .venv/Scripts/python tools/reclassify.py

**왜 필요한가.** 시스템 팬이 CPU쿨러로, 베어본 미니PC가 메인보드로, 라이저 케이블이
케이스로 올라가 있었다(실측 160건). 이들은 필수 사양을 채울 수 없으므로 영원히 검수
대기에 남고, 큐 규모를 실제 할 일보다 부풀린다. 채우는 문제가 아니라 **분류 문제**다.

**판단 근거는 스펙 원문의 분류 토큰뿐이다**(`catalog_map.is_accessory`). 상품명으로 보면
모듈러 파워의 '케이블', SSD의 '연장가이드'까지 걸려 진짜 부품을 추천에서 떨어뜨린다 —
잘못 배제하는 쪽이 훨씬 위험하다.

**삭제하지 않는다.** `category_group`을 'etc'로 내리고(재고·가격 관리 대상은 유지),
추천 후보에서만 빠진다. 검수 대기 행은 '처리'로 전이하고 사유를 남긴다.
"""
import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                      # noqa: E402
from sqlalchemy import create_engine, text          # noqa: E402

from api.catalog_map import is_accessory, wrong_slot   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def danawa_hits(engine) -> list:
    """다나와가 '다른 물건'이라고 말하는 상품 (슬라이스 51).

    우리 원천(스펙 원문)에는 단서가 없어도 다나와 분류로는 드러나는 것들이 있다:
    라이저 케이블이 케이스로, 기계식 키보드·스위치허브가 메인보드로, 노트북 램이 SSD로,
    시스템 팬이 CPU쿨러로 올라가 있었다. **이미 받아둔 캐시만 본다**(재수집 없음).
    """
    from api.danawa import parse_spec_list, page_title, title_similarity, wrong_kind
    cache = os.environ.get("DANAWA_CACHE") or os.path.join(ROOT, ".cache", "danawa")
    if not os.path.isdir(cache):
        return []
    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT product_code, danawa_code, part_type, product_name
              FROM products
             WHERE category_group = 'core_part' AND danawa_code IS NOT NULL""")).all()
    out = []
    for pc, code, pt, name in rows:
        p = os.path.join(cache, f"{code}.html")
        if not os.path.exists(p):
            continue
        html = io.open(p, encoding="utf-8").read()
        # 제목이 닮지 않으면 pcode가 다른 상품이다 — 그 근거로 분류를 바꾸면 안 된다
        if title_similarity(name, page_title(html)) < 0.45:
            continue
        head, _kv, txt = parse_spec_list(html)
        why = wrong_kind(pt, head, txt)
        if why:
            out.append((pc, pt, name, why))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--danawa", action="store_true",
                    help="다나와 캐시 근거도 함께 본다(재수집 없음)")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT product_code, part_type, product_name, spec_source_text, status, stock_qty
              FROM products WHERE category_group = 'core_part'
        """)).all()
        pool_before = c.execute(text("SELECT count(*) FROM v_recommendation_candidates"
                                     " WHERE stock_qty > 0")).scalar()
        review_before = c.execute(text("SELECT count(*) FROM product_reviews"
                                       " WHERE review_status='대기'")).scalar()

    # 두 종류를 함께 본다: ① 부품이 아님(액세서리·팬·케이블) ② 슬롯이 틀림(SSD 자리의 램).
    # ②는 **올바른 슬롯으로 옮기지 않는다** — 자동으로 슬롯을 바꾸면 엉뚱한 자리에 들어갈
    # 위험이 있다. etc로 내리고 사유를 남겨 사람이 결정하게 한다(A-20 정신).
    hit = []
    for pc, pt, name, raw, st, q in rows:
        if is_accessory(raw):
            hit.append((pc, pt, name, "원천 분류가 액세서리·베어본 — 부품 아님"))
            continue
        bad = wrong_slot(pt, raw)
        if bad:
            hit.append((pc, pt, name, bad))
    print(f"핵심 부품 {len(rows):,}건 중 부품이 아니거나 슬롯이 틀린 것 {len(hit):,}건")
    if args.danawa:
        known = {h[0] for h in hit}
        extra = [h for h in danawa_hits(engine) if h[0] not in known]
        print(f"다나와 캐시 근거로 추가 검출 {len(extra):,}건")
        hit += extra
    by = {}
    for _, pt, _, _ in hit:
        by[pt] = by.get(pt, 0) + 1
    for k in sorted(by, key=lambda x: -by[x]):
        print(f"  {k:18s} {by[k]:>4}")
    print("\n샘플 8건")
    for pc, pt, name, why in hit[:8]:
        print(f"  [{pt:14s}] {(name or '')[:46]:48s} | {why[:40]}")

    if args.dry:
        print("\n--dry 모드 — DB를 바꾸지 않았습니다.")
        return
    if not hit:
        print("\n교정할 항목이 없습니다.")
        return

    codes = [pc for pc, _, _, _ in hit]
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE products SET category_group = 'etc', ai_candidate_yn = false,
                                review_required_yn = false, updated_at = now()
             WHERE product_code = ANY(:c)"""), {"c": codes})
        closed = 0
        for pc, _pt, _name, why in hit:
            r = conn.execute(text("""
                UPDATE product_reviews SET review_status = '처리', reviewed_at = now(),
                       detail = detail || ' [분류 교정: ' || :why || ']'
                 WHERE product_code = :pc AND review_status = '대기'"""),
                {"pc": pc, "why": why})
            closed += r.rowcount

    with engine.connect() as c:
        pool = c.execute(text("SELECT count(*) FROM v_recommendation_candidates"
                              " WHERE stock_qty > 0")).scalar()
        review = c.execute(text("SELECT count(*) FROM product_reviews"
                                " WHERE review_status='대기'")).scalar()
    print(f"\n교정 {len(hit):,}건 · 검수 해소 {closed:,}건")
    print(f"  추천 후보 {pool_before:,} -> {pool:,} · 검수 대기 {review_before:,} -> {review:,}")


if __name__ == "__main__":
    main()
