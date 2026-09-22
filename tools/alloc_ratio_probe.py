# -*- coding: utf-8 -*-
"""완제PC 실구성에서 슬롯별 예산 비율을 «잰다» — 읽기 전용 (2026-09-22)

실행(사장님 PC · DB 필요):
  .venv/Scripts/python tools/builtpc_parse.py --out D:/Hermes-Workspace/builtpc.json
  .venv/Scripts/python tools/alloc_ratio_probe.py --in D:/Hermes-Workspace/builtpc.json

■ 왜 이 도구인가 (A-139 의 남은 일)
  `usage_alloc`(0086) 은 **GPU·CPU·RAM 세 자리만** 갖고 있다. 메인보드·케이스·쿨러·
  파워·SSD 는 행이 없어 `candidates.BUDGET_ALLOC` 상수의 상한만 걸리고 **하한이 0**이다.
  2026-09-22 에 그 넷을 최저가 정책으로 옮기면서(A-139) 「비싼 쪽으로 차오르는」 병은
  없어졌지만, 이제 **반대쪽을 막을 것이 없다** — 300만원 견적에 만원짜리 케이스가
  들어가도 아무도 안 막는다. 그 바닥을 만드는 것이 `pct_min` 이고, 그 값은 **지어내면
  안 된다.**

■ 무엇을 근거로 삼나 — 우리가 실제로 파는 완제PC
  0086 의 GPU·CPU·RAM 값은 완제품 표본의 중앙값이었다(`docs/design/usage-alloc-
  2026-09-12.md`). 같은 자리를 채우는 것이므로 **같은 종류의 근거**를 쓴다. 다만 그때
  자료(`D:/Hermes-Workspace/crawl/analysis.md`)는 리포 밖이라 재현할 수 없어서, 이
  도구는 **우리 DB 안의 완제PC 구성**을 원천으로 쓴다 — `products.spec_source_text` 에
  전체 부품 구성이 들어 있고 `tools/builtpc_parse.py`(2026-09-17)가 이미 그것을 우리
  슬롯 어휘로 읽는다. **파싱을 여기서 다시 구현하지 않는다**(§단일 원천) — 그 도구의
  산출 JSON 을 그대로 먹는다.

■ 비율을 어떻게 구하나
  완제PC 원문은 부품 «이름»만 갖고 «가격»은 없다. 그래서 각 부품 이름을 우리 카탈로그
  (`products`)에 맞춰 가격을 얻고 `부품가 / 완제품가` 를 낸다. 이름 대조는
  `api/dedupe.score` 를 그대로 쓴다 — **거기 적힌 규칙이 이미 옳다**(부스트 없음 ·
  용량/수치가 다르면 점수를 깎는다). `find_similar` 를 안 부르는 이유는 그 함수의
  문턱값 0.97 이 「등록 전 중복 경고」용이라 이 용도엔 너무 높기 때문이고, 그래서
  **문턱값을 인자로 드러내고 맞은 비율·점수 분포를 함께 찍는다** — 숨은 상수가
  결과를 정하지 않게.

■ 이 도구가 «하지 않는» 것
  1. DB 에 쓰지 않는다. SELECT 뿐이고 산출물은 화면 출력과 (선택) JSON 이다.
  2. 못 맞춘 부품을 추정하지 않는다. 못 맞추면 그 건은 분모에서 빠지고, **몇 건이
     빠졌는지 그대로 찍는다.**
  3. `usage_alloc` 행을 만들지 않는다. 마이그레이션은 이 출력을 보고 사람이 쓴다.

■ 읽을 때 조심할 것 (출력에도 같이 찍힌다)
  · **오늘 가격으로 옛 구성을 잰다.** 완제PC 가 처음 값이 매겨진 시점의 부품가가 아니라
    지금 카탈로그 가격이다. 비율은 그만큼 흔들린다.
  · **합이 1 이 아니다.** 조립비·마진·주변기기가 완제품가에 들어 있어 부품가 합은
    완제품가보다 작은 것이 정상이다. 이 도구는 그 합(`부품합/완제품가`)을 함께 찍는데,
    그 값이 1 을 넘거나 지나치게 낮으면 **대조가 틀린 것**이지 시장이 그런 것이 아니다.
  · 용도(`usage_key`)별로 가르지 않는다. 완제PC 에는 용도 축이 없다(`builtpc_kind` 는
    `ai_workstation` 하나뿐 · 0088). 그래서 이 출력은 `usage_alloc` 의 **기본(NULL) 행**
    용이다. 용도별 세분은 근거가 따로 생긴 뒤에 한다.
"""
import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console                  # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                                  # noqa: E402
from sqlalchemy import create_engine, text                      # noqa: E402

from api.dedupe import score                                    # noqa: E402
from api.product_name import display_name                       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

# 견적 8 자리와 같은 순서(taxonomy.SLOTS). HDD 는 견적 슬롯이 아니라 따로 본다.
SLOTS = ["CPU", "MB", "RAM", "GPU", "CASE", "COOLER", "POWER", "SSD"]
# 쿨러는 part_type 이 둘이다(공랭·수랭) — 슬롯 하나로 접어 대조한다(taxonomy.slot_of 와 같은 규칙).
PART_TYPES = {"COOLER": ("COOLER_CPU_AIR", "COOLER_CPU_AIO")}

DEFAULT_MIN_SCORE = 0.60     # 근거 없는 값이다. 그래서 아래 §문턱 민감도를 함께 찍는다.
SENSITIVITY = (0.50, 0.60, 0.70, 0.80)


def part_query_name(part: dict) -> str:
    """대조에 쓸 이름. 원문(`raw`)이 가장 정보가 많다 — 파서가 뽑은 maker/model 은
    원문의 «부분»이라 그것만 쓰면 오히려 후보를 좁힌다."""
    return part.get("raw") or " ".join(
        str(part.get(k) or "") for k in ("maker", "model")).strip()


def load_catalog(conn):
    """슬롯별 카탈로그 (표시용 이름, 원천 이름, 판매가). 판매중·가격 있는 것만.

    ⚠ 이름은 `display_name()` 을 거친다. `product_name` 에는 판매조건 꼬리가 붙어 있고
    ("… 회원가입 계좌이체 맞춤할인 2.5%"), 완제PC 원문에는 그 꼬리가 없다 — 그대로
    대조하면 **맞는 짝인데도 점수가 깎인다**(실측: 코어i5-14400F 가 0.72 까지 내려간다).
    꼬리를 걷는 단일 원천이 이미 `api/product_name` 이라 그것을 부른다(A-38 ⑤).

    후보를 SQL 로 좁히지 않고 슬롯 단위로 통째로 읽어 파이썬에서 점수를 매긴다 —
    완제PC 는 몇백 건이고 슬롯당 카탈로그도 수천 건이라 감당된다. `find_similar` 의
    토큰 OR 좁히기를 흉내 내면 그 함수의 400건 한도까지 같이 흉내 내게 된다.
    """
    out = {}
    for slot in SLOTS:
        pts = PART_TYPES.get(slot, (slot,))
        rows = conn.execute(text(
            "SELECT product_name, sale_price FROM products"
            " WHERE part_type = ANY(:pts) AND status = '판매중'"
            "   AND sale_price IS NOT NULL AND sale_price > 0"),
            {"pts": list(pts)}).mappings().all()
        out[slot] = [(display_name(r["product_name"]), int(r["sale_price"]))
                     for r in rows]
    return out


def best_match(name: str, catalog: list):
    """(점수, 가격, 이름). 카탈로그가 비었거나 이름이 비면 (0, None, None)."""
    if not name or not catalog:
        return 0.0, None, None
    best = (0.0, None, None)
    for cname, price in catalog:
        s = score(name, cname)
        if s > best[0]:
            best = (s, price, cname)
    return best


def pct(values: list, q: float) -> float:
    """오름차순 분위값. statistics.quantiles 는 표본이 적으면 던진다 — 직접 센다."""
    if not values:
        return 0.0
    xs = sorted(values)
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]


def main():
    ap = argparse.ArgumentParser(
        description="완제PC 실구성에서 슬롯별 예산 비율을 잰다(읽기 전용)")
    ap.add_argument("--in", dest="src", required=True,
                    help="tools/builtpc_parse.py --out 이 만든 JSON")
    ap.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE,
                    help=f"이름 대조 문턱값(기본 {DEFAULT_MIN_SCORE})")
    ap.add_argument("--min-slots", type=int, default=6,
                    help="이 수 이상 슬롯이 대조된 완제PC 만 «합» 검산에 쓴다(기본 6)")
    ap.add_argument("--samples", type=int, default=3,
                    help="슬롯마다 눈으로 볼 대조 예시 수(기본 3)")
    ap.add_argument("--out", help="산출 JSON 경로(선택)")
    args = ap.parse_args()

    with open(args.src, encoding="utf-8") as f:
        builts = json.load(f)
    print(f"완제PC 구성 {len(builts)}건을 읽었습니다: {args.src}")

    try:
        engine = create_engine(os.environ["DATABASE_URL"])
        with engine.connect() as conn:
            catalog = load_catalog(conn)
    except KeyError:
        print("DATABASE_URL 이 없습니다(.env 확인).", file=sys.stderr)
        return 2
    except Exception:
        # DB 예외 원문에는 접속 문자열(비밀번호 포함)이 실린다 — 그대로 내지 않는다.
        print("DB 조회에 실패했습니다. .env 의 DATABASE_URL 을 확인하세요.", file=sys.stderr)
        return 2
    print("카탈로그(판매중): " + " ".join(f"{s} {len(catalog[s])}" for s in SLOTS))

    # 슬롯별 비율 · 문턱 민감도 · 검산용 합
    ratios = {s: [] for s in SLOTS}
    samples = {s: [] for s in SLOTS}
    hit_at = {t: {s: 0 for s in SLOTS} for t in SENSITIVITY}
    tried = {s: 0 for s in SLOTS}
    sums, rows_out = [], []

    for b in builts:
        total = b.get("sale_price")
        if not total:
            continue
        matched, part_sum = {}, 0
        for slot in SLOTS:
            part = (b.get("parts") or {}).get(slot)
            if not part:
                continue
            tried[slot] += 1
            s, price, cname = best_match(part_query_name(part), catalog[slot])
            for t in SENSITIVITY:
                if s >= t:
                    hit_at[t][slot] += 1
            if s < args.min_score or price is None:
                continue
            matched[slot] = {"score": s, "price": price, "catalog_name": cname,
                             "raw": part.get("raw")}
            part_sum += price
            ratios[slot].append(price / total)
            if len(samples[slot]) < args.samples:
                samples[slot].append((part.get("raw"), cname, s))
        if len(matched) >= args.min_slots:
            sums.append(part_sum / total)
        rows_out.append({"product_code": b.get("product_code"),
                         "product_name": b.get("product_name"),
                         "sale_price": total, "matched": matched})

    print(f"\n[이름 대조 문턱 민감도] 슬롯마다 «대조 시도 건수» 중 몇 건이 그 문턱을 넘나")
    print("  슬롯     시도 " + " ".join(f"{t:>6.2f}" for t in SENSITIVITY))
    for slot in SLOTS:
        line = " ".join(
            f"{(hit_at[t][slot] / tried[slot] * 100 if tried[slot] else 0):5.0f}%"
            for t in SENSITIVITY)
        print(f"  {slot:<7} {tried[slot]:>4}  {line}")
    print("  문턱을 올리면 맞은 건수가 줄고 남은 것만 신뢰도가 높아집니다.")
    print("  어느 문턱에서도 대조율이 낮은 슬롯은 «시장이 그런 것»이 아니라"
          " 우리 카탈로그에 그 부품이 없다는 뜻입니다.")

    if sums:
        print(f"\n[검산] 부품가 합 / 완제품가  (슬롯 {args.min_slots}개 이상 대조된 {len(sums)}건)")
        print(f"  최저 {min(sums):.2f}  중앙 {statistics.median(sums):.2f}  최고 {max(sums):.2f}")
        print("  1 을 넘으면 대조가 틀린 것입니다(완제품가에 조립비·마진이 들어 있으므로"
              " 1 보다 작아야 정상).")
    else:
        print(f"\n[검산] 슬롯 {args.min_slots}개 이상 대조된 완제PC 가 없습니다."
              " --min-score 를 낮춰 보세요.")

    print(f"\n[슬롯별 예산 비율] 문턱 {args.min_score} 기준 · 부품가 / 완제품가")
    print("  슬롯      n   최저    10%    중앙    90%    최고")
    for slot in SLOTS:
        v = ratios[slot]
        if not v:
            print(f"  {slot:<7} {0:>4}   (대조된 건이 없습니다)")
            continue
        print(f"  {slot:<7} {len(v):>4}  " + "  ".join(
            f"{x * 100:5.1f}%" for x in
            (min(v), pct(v, 0.10), statistics.median(v), pct(v, 0.90), max(v))))
    print("\n  usage_alloc 의 pct_min 은 이 표의 «10%» 쯤, pct_max 는 «90%» 쯤이"
          " 출발점입니다(0086 이 GPU·CPU·RAM 에 쓴 것과 같은 방식).")
    print("  다만 정하는 것은 사장님이고, 이 도구는 재기만 합니다.")

    print("\n[대조 예시] 원문 -> 카탈로그 (점수)")
    for slot in SLOTS:
        for raw, cname, s in samples[slot]:
            print(f"  {slot:<7} {str(raw)[:44]:<44} | {str(cname)[:44]:<44} {s:.2f}")

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"min_score": args.min_score, "builts": rows_out},
                      f, ensure_ascii=False, indent=1)
        print(f"\n저장: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
