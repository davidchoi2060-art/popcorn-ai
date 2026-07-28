"""중복 등록 확인 — 같은 상품을 두 번 만들지 않게 (슬라이스 68).

**기존 `danawa.title_similarity`를 쓰지 않는다.** 그건 "다나와 pcode가 딴 물건을
가리키는가"를 거르는 용도(0.45 미만 버림)라, 모델명 토큰이 겹치면 점수를 끌어올린다.
그래서 실측하면 이런 것들이 1.000으로 나온다:

    MP600 PRO **NH** (8TB)  vs  MP600 PRO **XT** (8TB)      -> 1.000
    EXCERIA **히트싱크** (1TB) vs  EXCERIA (1TB)              -> 1.000
    RTX 3050 EX **6GB**     vs  RTX 3050 EX **8GB**         -> 0.849

중복 판정은 반대 방향이 필요하다 — **다른 점을 지우지 않아야** 한다. 그래서
부스트를 빼고, 대신 용량·크기 같은 수치가 어긋나면 점수를 깎는다. 위 세 쌍은
0.946 / 0.909 / 0.467로 내려가 확인창이 뜨지 않는다(임계 0.97).

임계값은 실카탈로그 3,889쌍 실측으로 정했다: 0.97 이상이 6.5%뿐이라 등록할 때마다
뜨지 않고, 그 안에는 '벌크/정품' · '중고/신품'처럼 사람이 봐야 할 것들이 들어온다.
"""
import difflib
import re

from sqlalchemy import text

# 상품명에 붙는 판매 문구 — 같은 상품인지 판단하는 데 방해만 된다
_NOISE = re.compile(
    r"회원가입|계좌이체|맞춤할인|현금할인|무료배송|정품박스|정품|병행수입|벌크|중고|"
    r"\d+(?:\.\d+)?%")
_PUNCT = re.compile(r"[\[\]()/,·:]+")
_NUM_TOKEN = re.compile(r"\d+\s*(?:gb|tb|mb|w|mm|hz)")

SIMILAR_THRESHOLD = 0.97   # 실측 근거는 위 독스트링
SIMILAR_LIMIT = 5          # 보여줄 후보 수 — 더 많으면 판단이 아니라 훑기가 된다


def norm(s: str) -> str:
    s = _NOISE.sub(" ", str(s or "").lower())
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", s)).strip()


def _nums(s: str) -> set:
    """용량·크기 토큰. 6GB와 8GB를 가르는 결정적 신호다."""
    return {re.sub(r"\s+", "", t) for t in _NUM_TOKEN.findall(s)}


def score(a: str, b: str) -> float:
    """0~1. 높을수록 같은 상품일 가능성. **부스트 없음** — 차이를 지우지 않는다."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    base = difflib.SequenceMatcher(None, na, nb).ratio()
    ca, cb = _nums(na), _nums(nb)
    if ca and cb and ca != cb:
        base *= 0.55        # 수치가 다르면 다른 상품이다(1TB vs 8TB)
    return round(base, 3)


def find_similar(conn, name: str, part_type: str | None = None,
                 exclude: int | None = None, limit: int = SIMILAR_LIMIT) -> list:
    """이름이 닮은 기존 상품. 후보를 DB에서 좁힌 뒤 파이썬으로 점수를 매긴다.

    22,841건 전체를 파이썬으로 훑을 수는 없다. 상품명의 **의미 있는 토큰**으로
    먼저 거른다 — 하나도 안 겹치면 닮았을 리가 없다.
    """
    toks = [t for t in norm(name).split() if len(t) >= 2][:6]
    if not toks:
        return []
    where = ["(" + " OR ".join(
        f"p.product_name ILIKE '%%' || :t{i} || '%%'" for i in range(len(toks))) + ")"]
    params = {f"t{i}": t for i, t in enumerate(toks)}
    if part_type:
        where.append("p.part_type = :pt")
        params["pt"] = part_type
    if exclude is not None:
        where.append("p.product_code <> :ex")
        params["ex"] = exclude
    rows = conn.execute(text(
        "SELECT p.product_code, p.sku, p.product_name, p.part_type, p.maker,"
        " p.sale_price, p.stock_qty, p.status"
        " FROM products p WHERE " + " AND ".join(where)
        + " ORDER BY p.product_code LIMIT 400"), params).mappings().all()

    out = []
    for r in rows:
        s = score(name, r["product_name"])
        if s >= SIMILAR_THRESHOLD:
            out.append({"product_code": r["product_code"], "sku": r["sku"],
                        "name": r["product_name"], "part_type": r["part_type"],
                        "maker": r["maker"], "sale_price": r["sale_price"],
                        "stock_qty": r["stock_qty"], "status": r["status"],
                        "score": s})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]
