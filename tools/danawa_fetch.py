# -*- coding: utf-8 -*-
"""다나와 상세 사양 수집 — 검수 큐에 **제안값**으로 올린다 (슬라이스 51).

실행:
  .venv/Scripts/python tools/danawa_fetch.py --dry --limit 20
  .venv/Scripts/python tools/danawa_fetch.py --limit 200            # 판매중·재고>0 우선
  .venv/Scripts/python tools/danawa_fetch.py --all --limit 500
  .venv/Scripts/python tools/danawa_fetch.py --from-cache --dry      # 캐시 재파싱, 네트워크 0건

**수집한 값을 정본에 바로 넣지 않는다.** `product_reviews.suggested_value`에 제안으로만
올리고, 운영자가 검수 화면에서 확인해야 `product_specs`에 들어간다. 남의 페이지에서 온 값이
그대로 견적 근거가 되면 "모든 견적에는 이유가 있습니다"가 무너진다. 일괄 확정 대상도
아니다(그건 `origin_value` 기준) — 사람 확인이 강제된다.

**시세(market_price)도 같은 규칙이다**(사장님 확정 ㉠·㉣, 2026-08-23 — A-18을 가격에도
확장 적용). 다나와 최저가는 `product_reviews`에 `field_name='market_price'` 제안으로만
올라간다. **`products.market_price`에 직접 쓰지 않는다** — 전량 사람 승인을 거쳐야 정본이
된다. 고객 화면·응답에는 "다나와"·"최저가"를 재게시하지 않고 **"시세 관측가"**로만 표기한다
(약관 ㉣) — 이 표기·마커는 검수 화면(운영자 전용)에만 보인다.

**pcode 오매핑이 실재한다.** 우리 메인보드에 랜케이블 pcode가 붙은 경우를 실측했다
(제목 유사도 0.16). 그래서 제목이 충분히 닮지 않으면 사양을 쓰지 않고 '코드 불일치'로
검수에 알린다 — 엉뚱한 사양이 조용히 들어가는 것이 최악이다. 시세 제안도 같은 제목
유사도 하한(`SIM_MIN`)을 넘어야 만든다.

접근 규범: robots.txt가 막은 `/api/`·`/info/ajax/`·`/list/ajax/`·`/community/`는 건드리지
않고 허용 경로인 `/info/`만 쓴다. 요청 간격을 두고, 연속 실패·차단 응답이면 즉시 멈춘다.
받은 원문은 캐시에 남겨 파서를 고칠 때 재수집하지 않는다. `--from-cache`는 그 캐시만
재파싱해 시세 관측 제안을 만든다 — **네트워크 요청이 0건**이라 언제든 다시 돌려도 된다.
"""
import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                      # noqa: E402
from sqlalchemy import create_engine, text          # noqa: E402

from api.danawa import (                            # noqa: E402
    head_mismatch, page_title, parse_market_price, parse_spec_list,
    title_similarity, to_fields,
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


# ── 시세 관측(market_price) 제안 (사장님 확정 ㉠·㉣, A-18 가격에도 확장) ────────────
# 다나와 최저가는 «시세 관측가» 제안으로만 올린다. products.market_price 에 직접 쓰지
# 않는다 — 사람이 검수 화면(ADM-PRD-020)에서 승인해야 정본이 된다.
PRICE_REVIEW_TYPE = "price_suggest"

PRICE_INSERT_SQL = text("""
    INSERT INTO product_reviews
           (product_code, review_type, field_name, detail, review_status,
            suggested_value, confidence)
    SELECT :pc, :rtype, 'market_price', :detail, '대기', :sv, :conf
     WHERE NOT EXISTS (
       SELECT 1 FROM product_reviews x
        WHERE x.product_code = :pc AND x.field_name = 'market_price'
          AND x.review_status = '대기' AND x.suggested_value = :sv)
""")


def _price_detail(value: int, sim: float, locked: bool) -> str:
    """기존 다나와 사양 제안과 같은 마커(' [다나와 제안: ... ]')를 쓰되, 새 행이라
    앞에 '시세 관측(...)' 관측 근거를 붙인다(고객 응답에는 재게시하지 않는다 — 출처는
    운영자 검수 화면에서만 보인다)."""
    observed = datetime.now().isoformat(timespec="seconds")
    d = (f"시세 관측(다나와 info 페이지, 관측 시각 {observed}) "
         f"[다나와 제안: {value:,} · 유사도 {sim:.2f} — 확인 후 승인하세요]")
    if locked:
        d += " [잠김 — 승인 시 덮어씀 주의]"
    return d


def _price_candidate(pc: int, name: str, locked_fields, html: str, seen: set):
    """(제안 dict | None, 건너뛴 사유 | None) 하나를 만든다.

    사유: 'parse_fail'(og:description 없음/형식 불일치) ·
          'mismatch'(제목 유사도가 SIM_MIN 미만 — pcode 오매핑 의심, 사양 제안과 같은 기준) ·
          'dup'(같은 (product_code, market_price) 대기 제안이 이미 있음)
    """
    v = parse_market_price(html)
    if v is None:
        return None, "parse_fail"
    title = page_title(html)
    sim = title_similarity(name, title)
    if sim < SIM_MIN:
        return None, "mismatch"
    sv = str(v)
    if (pc, sv) in seen:
        return None, "dup"
    locked = "market_price" in (locked_fields or [])
    return {"pc": pc, "name": name, "value": v, "sv": sv, "sim": sim,
            "locked": locked, "detail": _price_detail(v, sim, locked)}, None


def _load_pending_market_price(engine) -> set:
    """이미 대기중인 (product_code, suggested_value) 쌍 — 중복 제안을 막는 데 쓴다."""
    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT product_code, suggested_value FROM product_reviews
             WHERE field_name = 'market_price' AND review_status = '대기'""")).all()
    return {(pc, sv) for pc, sv in rows}


def _write_price_proposals(conn, price_props: list) -> int:
    n = 0
    for p in price_props:
        r = conn.execute(PRICE_INSERT_SQL, {
            "pc": p["pc"], "rtype": PRICE_REVIEW_TYPE, "detail": p["detail"],
            "sv": p["sv"], "conf": round(p["sim"], 2)})
        n += r.rowcount
    return n


def run_from_cache(engine, dry: bool):
    """`.cache/danawa/`에 이미 있는 파일만 읽어 시세 관측 제안을 만든다 — 재수집 없음
    (네트워크 요청 0건). 기존 사양 제안 대상(검수 대기 spec_missing)으로 좁히지 않고
    캐시에 있는 상품 전부를 대상으로 한다 — 시세는 사양 결측 여부와 무관하다."""
    files = sorted(f[:-5] for f in os.listdir(CACHE) if f.endswith(".html"))
    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT product_code, danawa_code, product_name, locked_fields
              FROM products
             WHERE danawa_code IS NOT NULL AND danawa_code ~ '^[0-9]+$'""")).all()
    by_code = {}
    for pc, code, name, locked in rows:
        by_code.setdefault(code, []).append((pc, name, locked))

    seen = _load_pending_market_price(engine)
    props, no_match, parse_fail, mismatch, dup = [], 0, 0, 0, 0
    for code in files:
        matches = by_code.get(code)
        if not matches:
            no_match += 1
            continue
        html = io.open(os.path.join(CACHE, f"{code}.html"), encoding="utf-8").read()
        for pc, name, locked_fields in matches:
            prop, reason = _price_candidate(pc, name, locked_fields, html, seen)
            if prop:
                props.append(prop)
                seen.add((pc, prop["sv"]))
            elif reason == "parse_fail":
                parse_fail += 1
            elif reason == "mismatch":
                mismatch += 1
            elif reason == "dup":
                dup += 1

    print(f"캐시 파일 {len(files):,}건 · 상품 매칭 없음(코드 불일치·미등록) {no_match:,}건"
          " · 네트워크 요청 0건\n")
    print(f"시세 관측 제안 대상 {len(props):,}건")
    print(f"  파싱 실패(og:description 없음/형식 불일치) {parse_fail:,}건")
    print(f"  제목 유사도 미달(코드 불일치 의심 — 미제안) {mismatch:,}건")
    print(f"  이미 대기중(중복 생략) {dup:,}건")
    if props[:5]:
        print("  제안 샘플:")
        for p in props[:5]:
            print(f"    {p['pc']} {p['name'][:40]} -> {p['value']:,}원"
                  f" (유사도 {p['sim']:.2f}{', 잠김' if p['locked'] else ''})")

    if dry:
        print("\n--dry 모드 — DB를 바꾸지 않았습니다.")
        return
    if not props:
        print("\n올릴 제안이 없습니다.")
        return
    with engine.begin() as conn:
        n = _write_price_proposals(conn, props)
    print(f"\n시세 관측 제안 기록 {n:,}건")
    print("검수 화면(ADM-PRD-020)에서 제안값을 확인하고 승인하면 정본에 반영됩니다.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--all", action="store_true", help="판매 불가 상품도 포함")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--from-cache", action="store_true",
                     help="`.cache/danawa/`의 895건만 재수집 없이 파싱해 시세 관측"
                          "(market_price) 제안만 만든다 — 네트워크 요청 0건")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    if args.from_cache:
        run_from_cache(engine, args.dry)
        return

    sell = "" if args.all else " AND p.status='판매중' AND p.stock_qty>0"
    with engine.connect() as c:
        rows = c.execute(text(f"""
            SELECT p.product_code, p.danawa_code, p.part_type, p.product_name,
                   p.locked_fields, array_agg(r.field_name) AS fields
              FROM product_reviews r JOIN products p USING (product_code)
             WHERE r.review_status='대기' AND r.review_type='spec_missing'
               AND r.suggested_value IS NULL
               AND p.danawa_code IS NOT NULL AND p.danawa_code ~ '^[0-9]+$'
               {sell}
             GROUP BY 1,2,3,4,5
             ORDER BY p.product_code
             LIMIT :n"""), {"n": args.limit}).all()
    print(f"수집 대상 {len(rows):,}건"
          + ("" if args.all else " (판매중·재고>0)") + f" · 캐시 {CACHE}\n")

    seen_price = _load_pending_market_price(engine)
    price_props, price_fail, price_mismatch, price_dup = [], 0, 0, 0
    props, mismatch, nospec, fail = [], [], 0, 0
    for i, (pc, code, pt, name, locked_fields, fields) in enumerate(rows, 1):
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
        # 시세 관측(market_price) 제안 — 같은 요청으로 받은 html을 재사용한다(추가 요청 없음).
        # 사양 유사도 미달로 아래에서 continue하기 «전에» 시도해야 이 상품에 대한 시세도
        # (내부에서 같은 SIM_MIN 기준으로 다시 판정해) 빠짐없이 집계된다.
        price_prop, price_reason = _price_candidate(pc, name, locked_fields, html, seen_price)
        if price_prop:
            price_props.append(price_prop)
            seen_price.add((pc, price_prop["sv"]))
        elif price_reason == "parse_fail":
            price_fail += 1
        elif price_reason == "mismatch":
            price_mismatch += 1
        elif price_reason == "dup":
            price_dup += 1
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

    print(f"\n시세 관측 제안 대상 {len(price_props):,}건 · 파싱 실패 {price_fail:,}건"
          f" · 유사도 미달(미제안) {price_mismatch:,}건 · 중복 생략 {price_dup:,}건")

    if args.dry:
        print("\n--dry 모드 — DB를 바꾸지 않았습니다.")
        if props[:5]:
            print("  제안 샘플:")
            for p in props[:5]:
                print(f"    {p['pc']} {p['vals']}")
        if price_props[:5]:
            print("  시세 관측 제안 샘플:")
            for p in price_props[:5]:
                print(f"    {p['pc']} {p['name'][:40]} -> {p['value']:,}원"
                      f" (유사도 {p['sim']:.2f}{', 잠김' if p['locked'] else ''})")
        return
    if not props and not mismatch and not price_props:
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
        n_price = _write_price_proposals(conn, price_props)
    print(f"\n제안 기록 {n_prop:,}개 필드 · 코드 불일치 회부 {n_mis:,}건"
          f" · 시세 관측 제안 {n_price:,}건")
    print("검수 화면(ADM-PRD-020)에서 제안값을 확인하고 승인하면 정본에 반영됩니다.")


if __name__ == "__main__":
    main()
