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

    **`part_type`은 더 이상 WHERE로 걸지 않는다 — ORDER BY 우선순위로만 쓴다**
    (결함 ⓐ-1, 2026-08-15). 예전엔 `WHERE p.part_type = :pt`로 후보 자체를 그
    분류 안에서만 뽑았다. 그런데 분류 변경(슬라이스 67)이 상세에서 열려 있어서,
    상품을 재분류한 뒤 **그 상품이 빠져나간 옛 분류로 같은 이름을 다시 등록하면**
    검색 범위가 새 분류만 보느라 후보 SQL 단계에서부터 진짜 중복을 놓쳤다
    (재현: CPU쿨러(공랭)로 등록 → CPU쿨러(수랭)로 재분류 → 같은 이름을 다시
    CPU쿨러(공랭)로 등록 시도 → 막혀야 하는데 200 OK로 통과).
    이 필터를 언제 왜 넣었는지는 이력(최초 커밋 f9b8af0)에 설명이 없다 — 재분류
    기능(c07e02c)이 같은 날 그 14분 전에 들어갔는데도 상호작용을 검토한 흔적이
    없다. 실카탈로그 800건 표본으로 분류 제한 없이 돌려보면 **분류가 다른 후보가
    걸리는 경우는 0.25%(2/800)뿐**이고, 그 둘도 노이즈가 아니라 진짜 같은 상품
    (ETC 오분류 vs 정상 분류)이었다 — 막아야 했던 오탐이 애초에 실증되지 않는다.
    다만 완전히 걷어내면 다른 문제가 생긴다: 토큰 OR 매칭 자체가 이미 헐거워서
    (최대 6개 토큰 중 하나만 겹쳐도 후보) 후보가 400건 한도에 걸리는 경우가
    (표본 기준) 분류 제한이 있어도 60%, 없으면 86%로 더 늘어난다 — 흔한 이름일수록
    진짜 중복이 400건 밖으로 밀릴 위험이 커진다. 그래서 **막지 않고 앞세운다**:
    같은 분류 후보를 항상 먼저 채우므로(정밀도는 그대로) 이미 검증된 동일 분류
    동작은 바뀌지 않고, 여유가 있을 때 다른 분류로 옮겨간 진짜 중복도 함께 잡힌다.
    """
    toks = [t for t in norm(name).split() if len(t) >= 2][:6]
    if not toks:
        return []
    where = ["(" + " OR ".join(
        f"p.product_name ILIKE '%%' || :t{i} || '%%'" for i in range(len(toks))) + ")"]
    params = {f"t{i}": t for i, t in enumerate(toks)}
    if exclude is not None:
        where.append("p.product_code <> :ex")
        params["ex"] = exclude
    order_by = "p.product_code"
    if part_type:
        order_by = "(p.part_type = :pt) DESC, p.product_code"
        params["pt"] = part_type
    rows = conn.execute(text(
        "SELECT p.product_code, p.sku, p.product_name, p.part_type, p.maker,"
        " p.sale_price, p.stock_qty, p.status"
        " FROM products p WHERE " + " AND ".join(where)
        + " ORDER BY " + order_by + " LIMIT 400"), params).mappings().all()

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
