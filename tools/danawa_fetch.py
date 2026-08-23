# -*- coding: utf-8 -*-
"""다나와 상세 사양 수집 — 검수 큐에 **제안값**으로 올린다 (슬라이스 51).

실행:
  .venv/Scripts/python tools/danawa_fetch.py --dry --limit 20
  .venv/Scripts/python tools/danawa_fetch.py --limit 200            # 판매중·재고>0 우선
  .venv/Scripts/python tools/danawa_fetch.py --all --limit 500
  .venv/Scripts/python tools/danawa_fetch.py --from-cache --dry      # 캐시 재파싱, 네트워크 0건
  .venv/Scripts/python tools/danawa_fetch.py --market --limit 500   # 시세 전용 · 재고 후보
                                                                      # 전체 대상(A-103)
  .venv/Scripts/python tools/danawa_fetch.py --market --group fast   # A-109 주 1회 대상만
                                                                      # (GPU·CPU·쿨러)
  .venv/Scripts/python tools/danawa_fetch.py --market --group slow   # A-109 월 1회 대상만
  .venv/Scripts/python tools/danawa_fetch.py --from-cache --no-auto-approve --dry
                                                                      # 자동 승인 끄고 미리보기

**대상 선정 두 갈래(2026-08-23 · A-103).** 기본값은 "사양 검수 대기"(`review_type=
'spec_missing'`) 상품만 고른다 — 사양 제안이 목적이던 시절 그대로다. `--market`은 대상을
"재고 후보 전체"(`v_recommendation_candidates`, `stock_qty>0`)로 바꾼다 — **시세는 사양
검수 여부와 무관하게 필요하다.** 두 모집단은 다르다: 사양 검수 대기는 640건뿐인데
시세가 필요한 재고 후보(danawa_code 보유)는 2,979건이라, 기본 모드로만 돌리면 MB·SSD·
쿨러·HDD처럼 애초에 검수 대기가 아니었던 슬롯이 통째로 비어 버린다.

**시세 제안 보완 셋(2026-08-23 · A-110, A-108·A-109의 실행 수단)**:
  ㉠ 이미 승인된 `products.market_price`와 **정확히 같은** 관측값은 제안을 만들지
     않는다(`_load_current_market_price()` — 「같다」의 정의와 근거는 그 함수의
     docstring 참조).
  ㉡ 제안 문구의 "관측 시각"은 **이 html을 실제로 받은 시각**이다 — 캐시 히트면 캐시
     파일 mtime, 새로 받았으면 지금 시각(`fetch()`가 html과 함께 그 시각을 돌려준다).
     `datetime.now()`로 스크립트 «실행» 시각을 찍지 않는다 — 몇 주 전 캐시를 읽어도
     오늘 날짜가 찍히던 문제(실측: 캐시 07-27·문구 08-23)를 고친다.
  ㉢ `--group fast|slow`(A-109 두 묶음 — 정의는 `PART_GROUPS` 한 자리) 또는
     `--parts GPU,CPU`(임의 조합)로 대상을 부품 종류로 좁힌다. 부품 목록의 정의는
     한 곳(`FAST_PARTS`·`SLOW_PARTS`)뿐이다 — 두 방식(--group·--parts)이 각자
     다른 목록을 갖지 않는다.

**시세 제안 직후 자동 승인(2026-08-23 · A-108).** 새로 만든 market_price 제안마다
`api.admin_reviews.auto_approve_market_price()`를 부른다 — **승인 로직은 여기서 다시
만들지 않는다**, 그 계약을 그대로 쓴다. `--no-auto-approve`로 끌 수 있다(처음 돌리거나
문제가 의심될 때 전량 사람이 보게). `--dry`는 이 스위치와 무관하게 항상 자동 승인을
하지 않는다 — DB를 안 건드리는 것이 `--dry`의 뜻이다.

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
# A-108 자동 승인 배선 — 승인 로직은 여기서 다시 짜지 않고 이 계약을 그대로 쓴다.
from api.admin_reviews import (                     # noqa: E402
    auto_approve_market_price, MARKET_AUTO_APPROVE_PCT,
)
# 부품 어휘 단일 원천(CANON §1) — part_type 목록·라벨을 여기서 다시 정의하지 않는다.
from api.taxonomy import CORE_TYPES, PART_LABELS    # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("DANAWA_CACHE") or os.path.join(ROOT, ".cache", "danawa")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
DELAY = 1.5              # 요청 간격(초) — 예의이자 차단 회피
MAX_FAIL = 5             # 연속 실패가 이만큼이면 멈춘다(차단 의심)
SIM_MIN = 0.45           # 제목 유사도 하한 — 미만이면 다른 상품으로 본다

# JSONB 컬럼은 목록으로 들어간다 — 제안값은 문자열이므로 표기를 통일한다
JSON_FIELDS = {"socket_list", "form_factor_list"}

# ── A-109 차등 재수집 주기의 두 묶음(2026-08-23 사장님 확정 — "GPU·CPU·쿨러는 주
# 1회, 나머지는 월 1회"). **정의는 이 두 튜플 한 자리뿐**이다 — `--group`이 이것만
# 참조한다(§단일 원천, CANON.md). part_type 코드 자체는 `api.taxonomy`(부품 어휘
# 단일 원천)에서 가져오고 여기서 새 코드를 만들지 않는다.
#
# 근거(A-109 실측 — 27일 표본, 부품 종류별 |변동률| 중앙값. **표본이 얕다**: 종류당
# 8~15건·관측 27일간 1회뿐이다. decision-log.md U-55가 이 한계를 남겼다 — 다음 재수집
# 주기에 표본을 늘려 재확인해야 한다):
#   GPU 7.05% · 쿨러(공랭) 4.55% · CPU 2.65%                    -> FAST(주 1회)
#   RAM 0.20% · SSD 0.09% · 케이스 0.04% · MB 0.00% · 파워 0.00% -> SLOW(월 1회)
# 변동이 뚜렷한 세 종류와 사실상 안 변하는 다섯 종류가 갈리는 지점이 이 경계다.
FAST_PARTS = ("GPU", "CPU", "COOLER_CPU_AIR", "COOLER_CPU_AIO")
SLOW_PARTS = tuple(t for t in CORE_TYPES if t not in FAST_PARTS)
PART_GROUPS = {"fast": FAST_PARTS, "slow": SLOW_PARTS}


def fetch(pcode: str) -> tuple:
    """캐시 우선. 없으면 1회 요청. 실패는 (None, None).

    두 번째 반환값은 이 html을 **실제로 관측한 시각**이다(A-110 ㉡) — 캐시 히트면
    캐시 파일의 mtime, 새로 받았으면 지금 시각. 예전에는 이 시각을 어디서도 들고
    있지 않아서 호출부(`_price_detail`)가 매번 `datetime.now()`(스크립트 실행
    시각)를 대신 썼다 — 캐시를 읽어도 오늘 날짜가 찍혀, 몇 주 전 캐시로 만든 제안이
    승인 화면에서 방금 관측한 것처럼 보였다.
    """
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"{pcode}.html")
    if os.path.exists(p):
        observed = datetime.fromtimestamp(os.path.getmtime(p))
        return io.open(p, encoding="utf-8").read(), observed
    req = urllib.request.Request(
        f"https://prod.danawa.com/info/?pcode={pcode}",
        headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise RuntimeError(f"차단 응답 {e.code} — 수집을 멈춥니다")
        return None, None
    except Exception:                                # noqa: BLE001
        return None, None
    io.open(p, "w", encoding="utf-8").write(html)
    time.sleep(DELAY)
    return html, datetime.now()


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
    RETURNING review_id
""")
# ↑ RETURNING review_id — A-108 자동 승인 배선의 전제(2026-08-23). 이게 없으면
# _write_price_proposals()가 rowcount만 돌려줘 auto_approve_market_price(review_id)를
# 부를 방법이 없었다(하네스가 남긴 숙제). WHERE NOT EXISTS에 걸려 실제로 삽입되지
# 않은 건은 RETURNING이 빈 결과라 아래 _write_price_proposals()의 목록에 자연히
# 안 들어간다.


def _price_detail(value: int, sim: float, locked: bool, observed: datetime) -> str:
    """기존 다나와 사양 제안과 같은 마커(' [다나와 제안: ... ]')를 그대로 쓴다 —
    `api/admin_reviews.list_reviews()`가 이 부분 문자열로 `suggest_source='danawa'`를
    판정하므로(검수 화면이 출처를 읽는 유일한 단서) 마커 문구 자체는 건드리지 않는다.
    바뀌는 것은 앞에 붙는 '시세 관측 ...' 근거뿐이다(A-110 ㉡).

    **관측 시각은 «이 html을 실제로 받은 시각»이다** — 캐시 히트면 캐시 파일의 mtime,
    새로 받았으면 지금 시각(`fetch()`가 돌려준 값을 그대로 받는다). `datetime.now()`
    (스크립트 실행 시각)를 찍지 않는다 — 캐시가 몇 주 전 것이어도 오늘 날짜가 찍혀
    승인 화면에서 값의 신선도를 알 수 없었다(2026-08-23 실측: 캐시 07-27 · 옛 문구는
    08-23을 찍었다).

    문구에 «오늘로부터 며칠 전인지»도 함께 적는다 — 날짜만 있으면 사람이 매번
    암산해야 한다. 날짜 차이는 **달력 날짜 기준**(자정 경계)으로 센다 — 시각까지
    포함해 24시간 단위로 끊으면(`timedelta.days`) 캐시 파일의 생성 시각에 따라
    같은 날짜 차이인데도 하루가 늘거나 줄 수 있다.
    """
    days_ago = (datetime.now().date() - observed.date()).days
    when = observed.strftime("%Y-%m-%d")
    age = "(오늘)" if days_ago <= 0 else f"({days_ago}일 전)"
    d = (f"시세 관측 {when}{age} (다나와 info 페이지) "
         f"[다나와 제안: {value:,} · 유사도 {sim:.2f} — 확인 후 승인하세요]")
    if locked:
        d += " [잠김 — 승인 시 덮어씀 주의]"
    return d


def _price_candidate(pc: int, name: str, locked_fields, html: str, seen: set,
                      observed: datetime, current_map: dict):
    """(제안 dict | None, 건너뛴 사유 | None) 하나를 만든다.

    사유: 'parse_fail'(og:description 없음/형식 불일치) ·
          'mismatch'(제목 유사도가 SIM_MIN 미만 — pcode 오매핑 의심, 사양 제안과 같은 기준) ·
          'unchanged'(새 관측값이 이미 승인된 products.market_price와 **정확히 같음** —
                      A-110 ㉠, 제안을 만들지 않는다. 「같다」의 정의는
                      `_load_current_market_price()` docstring 참조) ·
          'dup'(같은 (product_code, market_price) 대기 제안이 이미 있음)

    순서(parse_fail → mismatch → unchanged → dup)는 의도된 것이다: 제목이 충분히
    닮지 않은 건(mismatch) 애초에 다른 상품 페이지를 본 것일 수 있어, 그 값을 우리
    현재가와 비교하는 것 자체가 의미가 없다 — 그래서 unchanged 판정보다 먼저 걸러낸다.
    """
    v = parse_market_price(html)
    if v is None:
        return None, "parse_fail"
    title = page_title(html)
    sim = title_similarity(name, title)
    if sim < SIM_MIN:
        return None, "mismatch"
    cur = current_map.get(pc)
    if cur is not None and v == cur:
        return None, "unchanged"
    sv = str(v)
    if (pc, sv) in seen:
        return None, "dup"
    locked = "market_price" in (locked_fields or [])
    return {"pc": pc, "name": name, "value": v, "sv": sv, "sim": sim,
            "locked": locked, "detail": _price_detail(v, sim, locked, observed)}, None


def _load_pending_market_price(engine) -> set:
    """이미 대기중인 (product_code, suggested_value) 쌍 — 중복 제안을 막는 데 쓴다."""
    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT product_code, suggested_value FROM product_reviews
             WHERE field_name = 'market_price' AND review_status = '대기'""")).all()
    return {(pc, sv) for pc, sv in rows}


def _load_current_market_price(engine) -> dict:
    """product_code -> 현재 승인된 products.market_price (A-110 ㉠).

    **「같다」의 정의(이 함수를 쓰는 `_price_candidate()`가 지키는 계약): 정확히
    같은 정수값만.** market_price는 BIGINT라 부동소수점 반올림 문제가 없어 정확
    비교가 항상 명확하다. 「아주 작은 차이도 같다고 본다」로 넓히려면 허용 오차
    (예: ±1%)를 새로 정해야 하는데, 그 숫자를 뒷받침할 근거가 없다 — A-108의 5%는
    **자동 승인** 임계값이지 **제안을 아예 안 만드는** 임계값이 아니다(다른 결정의
    숫자를 그 결정이 답하지 않은 질문에 끌어다 쓰면 안 된다. 근거 없이 숫자를
    지어내는 것과 같다).

    그래서 더 안전한 쪽 — **정확히 같은 값만 걸러 제안을 생략한다** — 을 택했다:
    1원이라도 다르면 여전히 제안을 만들어 사람(또는 A-108 자동 승인)이 판단하게
    둔다. 이 필터가 «더 많이» 거르다가 실제 변동을 놓치는 것이, «덜» 걸러 이미
    승인된 값과 같은 제안이 몇 건 더 큐에 남는 것보다 나쁘다 — 후자는 검수 화면에서
    승인하면 그만이지만 전자는 진짜 변동을 조용히 숨긴다.
    """
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT product_code, market_price FROM products"
            " WHERE market_price IS NOT NULL")).all()
    return {pc: v for pc, v in rows}


def _write_price_proposals(conn, price_props: list) -> list:
    """제안을 쓰고 **새로 만들어진 review_id만** 돌려준다.

    PRICE_INSERT_SQL에 RETURNING review_id를 붙였다(A-108 자동 승인 배선의 전제 —
    review_id가 있어야 auto_approve_market_price()를 부를 수 있다). 중복 가드
    (INSERT ... WHERE NOT EXISTS)에 걸려 실제로 삽입되지 않은 건은 RETURNING이 빈
    결과라 자연히 이 목록에 안 들어간다 — 별도 판정 없이 "새로 만든 것만"이 보장된다.
    """
    ids = []
    for p in price_props:
        r = conn.execute(PRICE_INSERT_SQL, {
            "pc": p["pc"], "rtype": PRICE_REVIEW_TYPE, "detail": p["detail"],
            "sv": p["sv"], "conf": round(p["sim"], 2)})
        row = r.first()
        if row is not None:
            ids.append(row[0])
    return ids


def _run_auto_approve(review_ids: list) -> tuple:
    """새로 만든 시세 제안 review_id마다 auto_approve_market_price()를 부른다(A-108).

    **승인 로직은 여기서 다시 짜지 않는다** — `api.admin_reviews.auto_approve_market_price()`
    가 이미 만든 계약을 그대로 쓴다(하네스 지시 그대로: "승인 로직을 다시 짜지 마라").
    이 함수가 보태는 일은 ① 목록을 순회 ② 개별 건이 예외를 던져도 수집 자체는
    죽이지 않고 그 건만 대기로 남기는 것(A-110 요구사항 그대로 — 자동 승인 실패가
    수집을 죽이면 안 된다) ③ 자동/사람/예외 세 갈래로 건수를 센다, 셋뿐이다.

    반환: (자동 승인 n, 사람 대기로 남김 n, 예외로 실패해 처리 못 한 n).
    예외가 난 건은 review_status가 '대기'로 그대로 남는다 — auto_approve_market_price()가
    건마다 자체 트랜잭션(engine.begin())을 쓰므로 한 건의 예외가 다른 건에 번지지 않는다.
    """
    n_auto, n_human, n_err = 0, 0, 0
    for rid in review_ids:
        try:
            result = auto_approve_market_price(rid)
        except Exception as e:                          # noqa: BLE001
            n_err += 1
            print(f"  경고: 자동 승인 처리 실패(review_id={rid}) — 대기로 남습니다: {e}")
            continue
        if result["auto_approved"]:
            n_auto += 1
        else:
            n_human += 1
    return n_auto, n_human, n_err


def run_from_cache(engine, dry: bool, part_filter=None, auto_approve: bool = True,
                    limit=None):
    """`.cache/danawa/`에 이미 있는 파일만 읽어 시세 관측 제안을 만든다 — 재수집 없음
    (네트워크 요청 0건). 기존 사양 제안 대상(검수 대기 spec_missing)으로 좁히지 않고
    캐시에 있는 상품 전부를 대상으로 한다 — 시세는 사양 결측 여부와 무관하다.

    part_filter: None이면 전부. 지정하면 이 part_type 집합만(A-110 ㉢ — 정의는
    `PART_GROUPS`/`FAST_PARTS`/`SLOW_PARTS` 한 자리).
    limit: None이면 이 함수의 원래 계약대로 **전부** 반영한다(캐시 재파싱은 네트워크가
    없어 원래도 전량 처리가 안전했다 — 이 기본값을 바꾸지 않는다). 지정하면 **통계는
    전체 대상 기준 그대로 두고, 실제로 DB에 쓰는 것(및 그 뒤 자동 승인 대상)만 앞에서
    부터 그만큼 자른다** — 작은 표본으로 실제 반영해 보는 검증(`--limit 5` 등)이
    캐시 전체를 건드리지 않게 하기 위해서다.
    """
    files = sorted(f[:-5] for f in os.listdir(CACHE) if f.endswith(".html"))
    part_sql = " AND part_type = ANY(:parts)" if part_filter else ""
    params = {"parts": list(part_filter)} if part_filter else {}
    with engine.connect() as c:
        rows = c.execute(text(f"""
            SELECT product_code, danawa_code, product_name, locked_fields, part_type
              FROM products
             WHERE danawa_code IS NOT NULL AND danawa_code ~ '^[0-9]+$'{part_sql}"""),
            params).all()
    by_code = {}
    for pc, code, name, locked, pt in rows:
        by_code.setdefault(code, []).append((pc, name, locked, pt))

    seen = _load_pending_market_price(engine)
    current_map = _load_current_market_price(engine)
    props, no_match = [], 0
    parse_fail = mismatch = unchanged = dup = 0
    dist = {}
    for code in files:
        matches = by_code.get(code)
        if not matches:
            no_match += 1
            continue
        path = os.path.join(CACHE, f"{code}.html")
        html = io.open(path, encoding="utf-8").read()
        observed = datetime.fromtimestamp(os.path.getmtime(path))
        for pc, name, locked_fields, pt in matches:
            dist[pt] = dist.get(pt, 0) + 1
            prop, reason = _price_candidate(pc, name, locked_fields, html, seen,
                                             observed, current_map)
            if prop:
                props.append(prop)
                seen.add((pc, prop["sv"]))
            elif reason == "parse_fail":
                parse_fail += 1
            elif reason == "mismatch":
                mismatch += 1
            elif reason == "unchanged":
                unchanged += 1
            elif reason == "dup":
                dup += 1

    print(f"캐시 파일 {len(files):,}건 · 상품 매칭 없음(코드 불일치·미등록) {no_match:,}건"
          " · 네트워크 요청 0건")
    if part_filter:
        print(f"  부품 필터: {','.join(part_filter)}"
              f" ({','.join(PART_LABELS.get(t, t) for t in part_filter)})")
    if dist:
        dist_txt = " · ".join(f"{PART_LABELS.get(k, k)} {v:,}" for k, v in
                               sorted(dist.items(), key=lambda kv: -kv[1]))
        print(f"  대상(매칭된 상품·캐시 쌍) 부품 종류 분포: {dist_txt}")
    print()
    print(f"시세 관측 제안 대상 {len(props):,}건")
    print(f"  파싱 실패(og:description 없음/형식 불일치) {parse_fail:,}건")
    print(f"  제목 유사도 미달(코드 불일치 의심 — 미제안) {mismatch:,}건")
    print(f"  이미 승인된 값과 같음(생략 — A-110 ㉠) {unchanged:,}건")
    print(f"  이미 대기중(중복 생략) {dup:,}건")
    if props[:5]:
        print("  제안 샘플:")
        for p in props[:5]:
            print(f"    {p['pc']} {p['name'][:40]} -> {p['value']:,}원"
                  f" (유사도 {p['sim']:.2f}{', 잠김' if p['locked'] else ''})")

    if dry:
        print("\n--dry 모드 — DB를 바꾸지 않았습니다. 자동 승인도 하지 않았습니다.")
        return
    if not props:
        print("\n올릴 제안이 없습니다.")
        return

    write_props = props
    if limit is not None and len(props) > limit:
        print(f"\n--limit {limit} — 이번 실행은 대상 {len(props):,}건 중 앞 {limit:,}건만"
              " 실제로 반영합니다(위 통계는 전체 기준입니다).")
        write_props = props[:limit]

    with engine.begin() as conn:
        ids = _write_price_proposals(conn, write_props)
    print(f"\n시세 관측 제안 기록 {len(ids):,}건")

    n_auto = n_human = n_err = 0
    if auto_approve and ids:
        n_auto, n_human, n_err = _run_auto_approve(ids)
    print(f"요약 — 제안 {len(ids):,}건 · 자동 승인 {n_auto:,}건 · 사람 대기 {n_human:,}건"
          f" · 값 같아서 생략(A-110 ㉠) {unchanged:,}건 · 파싱 실패 {parse_fail:,}건"
          + (f" · 자동 승인 예외 {n_err:,}건(대기로 남김)" if n_err else ""))
    print("검수 화면(ADM-PRD-020)에서 대기 항목을 확인하고 승인하면 정본에 반영됩니다.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                     help="대상 상한. 기본 100(과거와 동일) — 단 --from-cache는 예외로"
                          " 지정하지 않으면 캐시 전체를 대상으로 한다(네트워크가 없어"
                          " 원래도 전량 처리가 안전했다). --from-cache에 지정하면 그만큼만"
                          " 실제로 DB에 반영한다(통계 출력은 전체 기준 그대로)")
    ap.add_argument("--all", action="store_true", help="판매 불가 상품도 포함")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--from-cache", action="store_true",
                     help="`.cache/danawa/`의 캐시만 재수집 없이 파싱해 시세 관측"
                          "(market_price) 제안만 만든다 — 네트워크 요청 0건")
    ap.add_argument("--market", action="store_true",
                     help="대상을 «사양 검수 대기»(spec_missing) 대신 «재고 후보 전체»"
                          "(v_recommendation_candidates, stock_qty>0)로 바꾼다 — 시세"
                          "(market_price) 제안만 만든다. 이미 대기중인 market_price 제안이"
                          " 있는 상품은 제외한다. 2026-08-23·A-103 참조")
    ap.add_argument("--group", choices=list(PART_GROUPS), default=None,
                     help="A-109 차등 재수집 주기 묶음(부품 종류 필터, A-110 ㉢). "
                          "fast=GPU·CPU·CPU쿨러(공랭·수랭)(주 1회 대상) · "
                          "slow=MB·RAM·SSD·HDD·케이스·파워(월 1회 대상). "
                          "정의는 이 파일의 FAST_PARTS·SLOW_PARTS 한 자리뿐이다. "
                          "--parts와 동시 지정 불가")
    ap.add_argument("--parts", type=str, default="",
                     help="임의 part_type 조합(쉼표 구분, 예: GPU,CPU) — --group의 두"
                          " 묶음 외에 필요한 조합이 있을 때. --group과 동시 지정 불가")
    ap.add_argument("--no-auto-approve", action="store_true",
                     help="시세 제안 자동 승인(A-108)을 끈다 — 새로 만든 제안을 전부"
                          " 대기로 남긴다. 처음 돌리거나 문제가 의심될 때 전량 사람이"
                          " 확인하도록 하는 스위치. --dry는 이 스위치와 무관하게 항상"
                          " 자동 승인을 하지 않는다(DB를 안 건드리는 것이 --dry의 뜻이다)")
    args = ap.parse_args()

    if args.group and args.parts:
        ap.error("--group과 --parts는 함께 쓸 수 없습니다(부품 목록은 한 자리에만 적습니다)")
    part_filter = None
    if args.group:
        part_filter = PART_GROUPS[args.group]
    elif args.parts:
        given = tuple(p.strip().upper() for p in args.parts.split(",") if p.strip())
        unknown = [p for p in given if p not in PART_LABELS]
        if unknown:
            ap.error(f"알 수 없는 부품 종류: {','.join(unknown)}"
                     f" (허용: {','.join(PART_LABELS)})")
        part_filter = given
    auto_approve = not args.no_auto_approve
    if auto_approve:
        print(f"(자동 승인 켜짐 — |변동률| < {MARKET_AUTO_APPROVE_PCT}% 이면 사람 없이"
              " 승인합니다. 끄려면 --no-auto-approve. A-108)")

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    if args.from_cache:
        run_from_cache(engine, args.dry, part_filter, auto_approve, args.limit)
        return

    limit = args.limit if args.limit is not None else 100

    # seen_price는 두 갈래 다 쓴다 — 시세 모드는 대상 선정에서 제외 목록으로,
    # 아래 루프는 기존대로 (product_code, suggested_value) 중복 방지로.
    seen_price = _load_pending_market_price(engine)
    # 이미 승인된 현재값 — A-110 ㉠. 값이 같으면 제안을 만들지 않는다(정의는
    # _load_current_market_price() docstring 참조).
    current_map = _load_current_market_price(engine)

    # 부품 종류 필터(A-110 ㉢) — --group/--parts가 지정됐을 때만 조건을 더한다.
    # 정의는 PART_GROUPS(=FAST_PARTS/SLOW_PARTS) 한 자리뿐이다(§단일 원천).
    # 두 SQL이 part_type을 다른 방식으로 참조해서(아래 market 분기는 뷰를 별칭 없이
    # 직접 조회, else 분기는 products에 p 별칭을 붙여 JOIN) 조각을 따로 둔다 —
    # 부품 «목록»은 하나(PART_GROUPS)지만 그 목록을 SQL에 꽂는 조각은 두 분기의
    # 컬럼 참조 방식에 맞춰야 한다.
    part_sql_view = " AND part_type = ANY(:parts)" if part_filter else ""
    part_sql_p = " AND p.part_type = ANY(:parts)" if part_filter else ""
    part_note = (f" · 부품 필터 {','.join(part_filter)}" if part_filter else "")

    def _print_dist(rows_, pt_index):
        dist = {}
        for r in rows_:
            dist[r[pt_index]] = dist.get(r[pt_index], 0) + 1
        if dist:
            dist_txt = " · ".join(f"{PART_LABELS.get(k, k)} {v:,}" for k, v in
                                   sorted(dist.items(), key=lambda kv: -kv[1]))
            print(f"  대상 부품 종류 분포: {dist_txt}")

    if args.market:
        # 2026-08-23 · A-103 · 하네스 실측: main()의 기존 대상 선정(바로 아래 else 분기)은
        # "사양 검수 대기"(review_type='spec_missing' · suggested_value IS NULL) 행이 있는
        # 상품만 고른다 — 640건뿐이다. 그런데 시세(market_price)는 사양 검수 여부와 무관하게
        # **재고 후보 전체**(danawa_code 보유 2,979건)에 필요하다. 이 차이 때문에 오늘 캐시로
        # 만든 제안 893건이 재고 후보의 8.0%밖에 못 채웠고 MB·SSD·쿨러·HDD 슬롯이 통째로
        # 비었다 — 그 상품들은 애초에 spec_missing 대상이 아니라 수집 대상 자체가 아니었다.
        #
        # 모집단은 엔진이 실제로 쓰는 후보와 **같은 원천을 실조회**한다(술어를 여기 다시
        # 적지 않는다 — CLAUDE.md §화면 정직성 "판정은 뷰·엔진과 같은 원천을 실조회한다").
        # api/recommend.py의 _load_pool()이 견적에 쓰는 조회와 동일하게
        # `v_recommendation_candidates WHERE stock_qty > 0`. 이 뷰가 이미 product_code·
        # danawa_code·part_type·product_name·locked_fields를 컬럼으로 갖고 있어(실측 —
        # information_schema.columns) products를 별도로 다시 조인하지 않는다: 조인하면
        # 같은 값을 두 원천(뷰 컬럼 vs JOIN한 products 컬럼)에서 읽게 돼 갈라질 여지만
        # 늘어난다.
        already = {pc for pc, _sv in seen_price}
        q_params = {"n": limit, "excl": list(already)}
        if part_filter:
            q_params["parts"] = list(part_filter)
        with engine.connect() as c:
            raw = c.execute(text(f"""
                SELECT product_code, danawa_code, part_type, product_name, locked_fields
                  FROM v_recommendation_candidates
                 WHERE stock_qty > 0
                   AND danawa_code IS NOT NULL AND danawa_code ~ '^[0-9]+$'
                   AND product_code != ALL(:excl){part_sql_view}
                 ORDER BY product_code
                 LIMIT :n"""), q_params).all()
        # 사양 제안용 fields를 빈 목록으로 둔다 — 이 모드는 사양 검수 대기 행이 없으므로
        # 뽑을 사양 제안이 원천적으로 없다(아래 루프의 `use = {f: v for ... if f in fields}`가
        # 빈 집합과 비교돼 자연히 0건이 된다). 시세·사양을 억지로 가르지 않고 기존 루프
        # 구조를 그대로 쓰기 위한 표기다.
        rows = [(pc, code, pt, name, locked, []) for pc, code, pt, name, locked in raw]
        print(f"수집 대상 {len(rows):,}건 (시세 모드 — 재고 후보 · danawa_code 보유"
              f" · 대기중 제안 있는 상품 {len(already):,}건 제외{part_note}) · 캐시 {CACHE}")
        _print_dist(raw, 2)
        print()
    else:
        sell = "" if args.all else " AND p.status='판매중' AND p.stock_qty>0"
        q_params = {"n": limit}
        if part_filter:
            q_params["parts"] = list(part_filter)
        with engine.connect() as c:
            rows = c.execute(text(f"""
                SELECT p.product_code, p.danawa_code, p.part_type, p.product_name,
                       p.locked_fields, array_agg(r.field_name) AS fields
                  FROM product_reviews r JOIN products p USING (product_code)
                 WHERE r.review_status='대기' AND r.review_type='spec_missing'
                   AND r.suggested_value IS NULL
                   AND p.danawa_code IS NOT NULL AND p.danawa_code ~ '^[0-9]+$'
                   {sell}{part_sql_p}
                 GROUP BY 1,2,3,4,5
                 ORDER BY p.product_code
                 LIMIT :n"""), q_params).all()
        print(f"수집 대상 {len(rows):,}건"
              + ("" if args.all else " (판매중·재고>0)") + part_note + f" · 캐시 {CACHE}")
        _print_dist(rows, 2)
        print()

    price_props, price_fail, price_mismatch, price_dup, price_unchanged = [], 0, 0, 0, 0
    props, mismatch, nospec, fail = [], [], 0, 0
    for i, (pc, code, pt, name, locked_fields, fields) in enumerate(rows, 1):
        try:
            html, observed = fetch(code)
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
        price_prop, price_reason = _price_candidate(pc, name, locked_fields, html, seen_price,
                                                      observed, current_map)
        if price_prop:
            price_props.append(price_prop)
            seen_price.add((pc, price_prop["sv"]))
        elif price_reason == "parse_fail":
            price_fail += 1
        elif price_reason == "mismatch":
            price_mismatch += 1
        elif price_reason == "unchanged":
            price_unchanged += 1
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
    if args.market:
        print("  (시세 모드 — 사양 검수 대기 행이 없는 대상이라 사양 제안은 원천적으로"
              " 0건입니다. 위 '사양 없음'은 결측이 아니라 이 모드의 정상 동작입니다"
              " — 2026-08-23·A-103)")
    if mismatch[:5]:
        print("  불일치 샘플:")
        for pc, code, ours, theirs, sim in mismatch[:5]:
            print(f"    [{sim:.2f}] 우리: {(ours or '')[:34]} | 다나와: {theirs[:34]}")
    head_bad = [p for p in props if p["mis"]]
    if head_bad:
        print(f"  ⚠ 다나와 분류가 우리 part_type과 다른 상품 {len(head_bad)}건"
              " — 사양보다 분류를 먼저 봐야 합니다")

    print(f"\n시세 관측 제안 대상 {len(price_props):,}건 · 파싱 실패 {price_fail:,}건"
          f" · 유사도 미달(미제안) {price_mismatch:,}건"
          f" · 이미 승인된 값과 같음(생략) {price_unchanged:,}건 · 중복 생략 {price_dup:,}건")

    if args.dry:
        print("\n--dry 모드 — DB를 바꾸지 않았습니다. 자동 승인도 하지 않았습니다.")
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
        price_ids = _write_price_proposals(conn, price_props)
    print(f"\n제안 기록 {n_prop:,}개 필드 · 코드 불일치 회부 {n_mis:,}건"
          f" · 시세 관측 제안 {len(price_ids):,}건")

    n_auto = n_human = n_err = 0
    if auto_approve and price_ids:
        n_auto, n_human, n_err = _run_auto_approve(price_ids)
    print(f"요약 — 시세 제안 {len(price_ids):,}건 · 자동 승인 {n_auto:,}건"
          f" · 사람 대기 {n_human:,}건 · 값 같아서 생략(A-110 ㉠) {price_unchanged:,}건"
          f" · 파싱 실패 {price_fail:,}건"
          + (f" · 자동 승인 예외 {n_err:,}건(대기로 남김)" if n_err else ""))
    print("검수 화면(ADM-PRD-020)에서 제안값을 확인하고 승인하면 정본에 반영됩니다.")


if __name__ == "__main__":
    main()
