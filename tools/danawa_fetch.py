# -*- coding: utf-8 -*-
"""다나와 상세 사양 수집 — 검수 큐에 **제안값**으로 올린다 (슬라이스 51).

실행:
  .venv/Scripts/python tools/danawa_fetch.py --dry --limit 20
  .venv/Scripts/python tools/danawa_fetch.py --limit 200            # 판매중·재고>0 우선
  .venv/Scripts/python tools/danawa_fetch.py --all --limit 500

**수집한 값을 정본에 바로 넣지 않는다.** `product_reviews.suggested_value`에 제안으로만
올리고, 운영자가 검수 화면에서 확인해야 `product_specs`에 들어간다. 남의 페이지에서 온 값이
그대로 견적 근거가 되면 "모든 견적에는 이유가 있습니다"가 무너진다. 일괄 확정 대상도
아니다(그건 `origin_value` 기준) — 사람 확인이 강제된다.

**pcode 오매핑이 실재한다.** 우리 메인보드에 랜케이블 pcode가 붙은 경우를 실측했다
(제목 유사도 0.16). 그래서 제목이 충분히 닮지 않으면 사양을 쓰지 않고 '코드 불일치'로
검수에 알린다 — 엉뚱한 사양이 조용히 들어가는 것이 최악이다.

접근 규범: robots.txt가 막은 `/api/`·`/info/ajax/`·`/list/ajax/`·`/community/`는 건드리지
않고 허용 경로인 `/info/`만 쓴다. 요청 간격을 두고, 연속 실패·차단 응답이면 즉시 멈춘다.
받은 원문은 캐시에 남겨 파서를 고칠 때 재수집하지 않는다.
"""
import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                      # noqa: E402
from sqlalchemy import create_engine, text          # noqa: E402

from api.danawa import (                            # noqa: E402
    head_mismatch, page_title, parse_spec_list, title_similarity, to_fields,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("DANAWA_CACHE") or os.path.join(ROOT, ".cache", "danawa")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
DELAY = 1.5              # 요청 간격(초) — 예의이자 차단 회피
MAX_FAIL = 5             # 연속 실패가 이만큼이면 멈춘다(차단 의심)
SIM_MIN = 0.45           # 제목 유사도 하한 — 미만이면 다른 상품으로 본다

# JSONB 컬럼은 목록으로 들어간다 — 제안값은 문자열이므로 표기를 통일한다
JSON_FIELDS = {"socket_list", "form_factor_list"}


def fetch(pcode: str) -> str | None:
    """캐시 우선. 없으면 1회 요청. 실패는 None."""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"{pcode}.html")
    if os.path.exists(p):
        return io.open(p, encoding="utf-8").read()
    req = urllib.request.Request(
        f"https://prod.danawa.com/info/?pcode={pcode}",
        headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise RuntimeError(f"차단 응답 {e.code} — 수집을 멈춥니다")
        return None
    except Exception:                                # noqa: BLE001
        return None
    io.open(p, "w", encoding="utf-8").write(html)
    time.sleep(DELAY)
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--all", action="store_true", help="판매 불가 상품도 포함")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    sell = "" if args.all else " AND p.status='판매중' AND p.stock_qty>0"
    with engine.connect() as c:
        rows = c.execute(text(f"""
            SELECT p.product_code, p.danawa_code, p.part_type, p.product_name,
                   array_agg(r.field_name) AS fields
              FROM product_reviews r JOIN products p USING (product_code)
             WHERE r.review_status='대기' AND r.review_type='spec_missing'
               AND r.suggested_value IS NULL
               AND p.danawa_code IS NOT NULL AND p.danawa_code ~ '^[0-9]+$'
               {sell}
             GROUP BY 1,2,3,4
             ORDER BY p.product_code
             LIMIT :n"""), {"n": args.limit}).all()
    print(f"수집 대상 {len(rows):,}건"
          + ("" if args.all else " (판매중·재고>0)") + f" · 캐시 {CACHE}\n")

    props, mismatch, nospec, fail = [], [], 0, 0
    for i, (pc, code, pt, name, fields) in enumerate(rows, 1):
        try:
            html = fetch(code)
        except RuntimeError as e:
            print(f"\n중단: {e}")
            break
        if not html:
            fail += 1
            if fail >= MAX_FAIL:
                print(f"\n중단: 연속 실패 {fail}건 — 차단이 의심됩니다")
                break
            continue
        fail = 0
        head, kv, txt = parse_spec_list(html)
        title = page_title(html)
        sim = title_similarity(name, title)
        if sim < SIM_MIN:
            mismatch.append((pc, code, name, title, sim))
            continue
        got = to_fields(pt, head, kv, txt)
        use = {f: v for f, v in got.items() if f in set(fields)}
        if not use:
            nospec += 1
            continue
        props.append({"pc": pc, "vals": use, "title": title, "sim": sim,
                      "head": head, "mis": head_mismatch(pt, head)})
        if i % 25 == 0:
            print(f"  진행 {i}/{len(rows)} · 제안 {len(props)} · 불일치 {len(mismatch)}")

    filled = sum(len(p["vals"]) for p in props)
    print(f"\n제안 가능 {len(props):,}건 상품 · 필드 {filled:,}개")
    print(f"코드 불일치(사양 미사용) {len(mismatch):,}건 · 사양 없음 {nospec:,}건")
    if mismatch[:5]:
        print("  불일치 샘플:")
        for pc, code, ours, theirs, sim in mismatch[:5]:
            print(f"    [{sim:.2f}] 우리: {(ours or '')[:34]} | 다나와: {theirs[:34]}")
    head_bad = [p for p in props if p["mis"]]
    if head_bad:
        print(f"  ⚠ 다나와 분류가 우리 part_type과 다른 상품 {len(head_bad)}건"
              " — 사양보다 분류를 먼저 봐야 합니다")

    if args.dry:
        print("\n--dry 모드 — DB를 바꾸지 않았습니다.")
        if props[:5]:
            print("  제안 샘플:")
            for p in props[:5]:
                print(f"    {p['pc']} {p['vals']}")
        return
    if not props and not mismatch:
        print("\n올릴 제안이 없습니다.")
        return

    with engine.begin() as conn:
        n_prop = 0
        for p in props:
            for f, v in p["vals"].items():
                sv = json.dumps(v, ensure_ascii=False) if f in JSON_FIELDS else str(v)
                r = conn.execute(text("""
                    UPDATE product_reviews
                       SET suggested_value = :v,
                           detail = detail || ' [다나와 제안: ' || :v || ' · 유사도 '
                                    || :sim || ' — 확인 후 승인하세요]'
                     WHERE product_code = :pc AND field_name = :f
                       AND review_status = '대기' AND suggested_value IS NULL"""),
                    {"v": sv, "pc": p["pc"], "f": f, "sim": f"{p['sim']:.2f}"})
                n_prop += r.rowcount
        # 코드 불일치는 사양이 아니라 **매핑**을 고쳐야 한다 — 별도 검수 항목으로 알린다
        n_mis = 0
        for pc, code, ours, theirs, sim in mismatch:
            r = conn.execute(text("""
                INSERT INTO product_reviews (product_code, review_type, field_name, detail,
                       review_status, confidence)
                SELECT :pc, 'spec_conflict', 'danawa_code',
                       '다나와코드 ' || :code || ' 가 다른 상품을 가리킵니다 (유사도 '
                       || :sim || ') — 다나와: ' || :theirs,
                       '대기', 0.9
                 WHERE NOT EXISTS (SELECT 1 FROM product_reviews x
                                    WHERE x.product_code = :pc AND x.field_name = 'danawa_code'
                                      AND x.review_status = '대기')"""),
                {"pc": pc, "code": code, "sim": f"{sim:.2f}", "theirs": theirs[:80]})
            n_mis += r.rowcount
    print(f"\n제안 기록 {n_prop:,}개 필드 · 코드 불일치 회부 {n_mis:,}건")
    print("검수 화면(ADM-PRD-020)에서 제안값을 확인하고 승인하면 정본에 반영됩니다.")


if __name__ == "__main__":
    main()
