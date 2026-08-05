"""판매가 공식의 단일 원천 (슬라이스 E).

    판매가 = 매입가 × (1 + 카드수수료 + 마진) → 1,000원 단위 half-up

이 한 줄이 `admin_price_import._reprice` · `admin_price_review` · `admin_engine_rules`의
예시까지 **세 곳에 흩어져** 있었다. 슬라이스 A에서 부품 어휘가 네 벌로 갈라져 이미 어긋나
있던 것과 같은 구조다 — 값이 아니라 **가격 공식**이라 갈라지면 화면마다 다른 가격을 말한다.

기존 임대 관리자(윈윈소프트)도 같은 공식을 쓴다(카테고리관리 화면 상단 명시):
    소비자 판매가 생성기준 = (매입가 + 기본설정된 카드수수료 (2.585%) + 실제 소비자마진)
수수료 2.585%는 그쪽 운영값이고, 사용자가 2026-08-04에 우리도 그 값으로 맞추기로 정했다.

■ 1,000원 half-up인 이유
가격표에 987,431원 같은 수를 내밀지 않기 위해서다. `round()`는 은행가 반올림이라
0.5를 짝수로 보내므로 쓰지 않는다(같은 입력에 다른 결과처럼 보인다).
"""
from decimal import Decimal, ROUND_HALF_UP


def half_up_1000(v) -> int:
    """1,000원 단위 half-up. 파이썬 기본 round()의 은행가 반올림을 피한다."""
    return int((Decimal(str(v)) / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 1000


def sale_from_purchase(purchase, fee: float, margin: float) -> int | None:
    """정책이 말하는 판매가. 매입가가 없으면 산정하지 않는다(0원을 만들지 않는다)."""
    if purchase is None:
        return None
    return half_up_1000(float(purchase) * (1 + fee + margin))


def formula_text(fee: float, margin: float) -> str:
    """화면이 근거로 그대로 쓰는 문장 — 화면이 공식을 따로 적지 않게 한다."""
    return (f"판매가 = 매입가 × (1 + 카드수수료 {fee * 100:.3f}% + 마진 {margin * 100:.1f}%)"
            f" = 매입가 × {1 + fee + margin:.5f} → 1,000원 단위 반올림")


# ── 카테고리별 마진 (슬라이스 2026-08-05) ─────────────────────────────
# 마진은 **판매 분류 노드**에 걸린다. part_type이 아니다 — 트리는 이미 갈라져서
# 13개 노드가 `ETC` 하나를 공유한다(완제품 PC와 케이블이 같은 종류다). 마진은 파는
# 물건의 성격을 따르므로 트리가 맞는 축이다.
#
# 상속: **자기 노드 → 조상 → 전역**. 트리에 값을 다 채우게 하지 않기 위해서다
# ('부품'에 10%를 걸면 그 아래 전부가 10%, 'GPU'만 8%로 덮어쓴다).
#
# **이 값이 저장된 판매가를 그 자리에서 바꾸지 않는다.** 다음 재산정에서 쓰인다 —
# 그래서 분류를 옮겼는데 값이 말없이 달라지는 일이 없다.

def resolve_margins(nodes, policies: dict, default: float) -> dict:
    """{category_id: (적용 마진, 그 값이 온 노드 id 또는 None=전역)}.

    `nodes`는 (category_id, parent_id) 쌍의 목록이다. DB를 모르는 순수 함수라
    회귀가 트리를 지어내 상속을 직접 검사할 수 있다.

    부모 사슬이 끊겼거나(고아) 순환이면 **전역으로 떨어뜨린다** — 여기서 무한
    루프를 돌면 가격 화면이 통째로 멈춘다.
    """
    parent = {int(c): (int(p) if p is not None else None) for c, p in nodes}
    out = {}
    for cid in parent:
        cur, seen = cid, set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            if cur in policies:
                out[cid] = (float(policies[cur]), cur)
                break
            cur = parent.get(cur)
        else:
            # 조상까지 훑어도 없었다(또는 고아·순환이라 사슬이 끊겼다) → 전역
            out[cid] = (default, None)
    return out


def margin_source_text(source_id, own_id, node_names: dict) -> str:
    """마진이 **어디서 왔는지** 화면이 그대로 쓰는 문장.

    숫자만 보여주면 운영자는 이 노드에 값이 걸린 줄 안다 — 지우려 해도 지울 게 없다.
    """
    if source_id is None:
        return "전역 기본"
    if source_id == own_id:
        return "이 분류"
    return f"상속: {node_names.get(source_id, source_id)}"
