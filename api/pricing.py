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
