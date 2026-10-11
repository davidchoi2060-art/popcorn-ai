# -*- coding: utf-8 -*-
"""2겹 실시간 안전장치 — 장바구니·결제 순간 쇼핑몰 현재가 확인 (2026-10-11).

■ 중헌 님 지시
  "장바구니에 넣는 순간, 결제하는 순간 팝콘PC 쇼핑몰의 지금 현재 금액을 비교하고
   금액변경이 있을 경우 고객에게 고시하고 금액 업데이트 해야 함.. 그렇게 DB에도
   기록해야 하고. 이게 마지막 안전장치야."
  1겹(관리자 엑셀 업로드 · 하루 1~2회 자동 갱신)은 배치라 그 사이에 쇼핑몰 가격이
  움직일 수 있다. 이 파일이 그 틈을 고객 앞에서 메운다.

■ 자리
      cart       mvp3 「견적 보관」   (api/mvp3_saved_quotes.save_quote)
      checkout   mvp3 「쇼핑몰에서 구매」 (api/mvp3_handoff.handoff_saved_quote)

■ 하나로 모은 것 — 1겹과 같은 원천을 쓴다
      읽기   api/mall_price_reader.read_price()   (자동 갱신의 상품별 읽기와 같은 함수)
      쓰기   api/mall_price.apply_changes()       (판매가 · 가격 이력 · 활동 로그 · 확인 기록)
      기록   mall_price_checks                    (moment = cart / checkout 로 1겹과 가른다)

■ 막지 않는다
  쇼핑몰 응답을 3초까지만 기다린다. 못 읽으면 저장·이동은 그대로 진행하고 고객에게
  "현재 가격 확인이 안 되어 쇼핑몰에서 최종 확인됩니다" 라고 말한다. 이 함수는
  예외를 던지지 않는다 — 안전장치가 고장 나서 구매 길을 막으면 안 된다.

■ 판매가를 바꾸지 않는 경우 (확인 기록에는 남는다)
  · 판매가가 잠긴 상품(직접 소싱 예외 값)          outcome 'locked'
  · 30% 넘게 움직인 큰 변동(사람 확인을 기다린다)  outcome 'held'
  · 완제품 PC 가 아닌 상품(부품은 마진 공식이 정한다) outcome 'held'
  · 그 사이 다른 경로가 판매가를 바꿈              outcome 'stale'
  어느 경우든 고객에게는 쇼핑몰 현재가를 알린다 — 고객이 실제로 결제하는 값이다.
"""
import logging

from sqlalchemy import text

from . import mall_price, mall_price_reader
from .db import engine
from .timeutil import now_iso

log = logging.getLogger(__name__)      # ASCII only (server stdout is cp949)

TIMEOUT = 3.0
MSG_UNCHECKED = "현재 가격 확인이 안 되어 쇼핑몰에서 최종 확인됩니다"


def _won(v: int) -> str:
    return "{:,}원".format(v)


def _message(moment: str, quoted: int, mall: int) -> str:
    head = "쇼핑몰 현재 가격이 %s에서 %s으로 바뀌었습니다." % (_won(quoted), _won(mall))
    if moment == "checkout":
        return head + " 쇼핑몰에서는 바뀐 가격으로 결제됩니다."
    return head + " 바뀐 가격으로 보관했습니다."


def _part_type(code: int):
    with engine.connect() as conn:
        return conn.execute(text("SELECT part_type FROM products WHERE product_code=:c"),
                            {"c": code}).scalar()


def _settle(conn, moment, code, quoted, got, *, quote_id, visitor_ref):
    """읽은 결과 -> 기록(과 필요하면 판매가 반영). 트랜잭션은 부르는 쪽 것이다."""
    url = got.get("url")
    row = conn.execute(text(
        "SELECT sale_price, part_type FROM products WHERE product_code=:c"),
        {"c": code}).mappings().first()
    ours = row["sale_price"] if row else None
    mall = got.get("price") if got.get("ok") else None
    common = {"quote_id": quote_id, "visitor_ref": visitor_ref, "source_url": url}
    saved = False
    if mall is None:
        mall_price.record_check(conn, moment, code, our_price=ours, mall_price=None,
                                outcome="failed", note=(got.get("err") or "읽기 실패"), **common)
        return {"status": "unchecked", "quoted": quoted, "mall": None, "diff": None,
                "saved": False, "message": MSG_UNCHECKED}
    if row is None or ours == mall:
        mall_price.record_check(conn, moment, code, our_price=ours, mall_price=mall,
                                outcome="same", note=None if row else "우리 상품에 없음", **common)
    elif row["part_type"] != mall_price.PC_PART_TYPE:
        mall_price.record_check(conn, moment, code, our_price=ours, mall_price=mall, outcome="held",
                                note="부품 판매가는 바꾸지 않습니다", **common)
    else:
        big = ours is None or ours <= 0 or abs(mall - ours) / ours >= mall_price.BIG_CHANGE_DEFAULT
        res = mall_price.apply_changes(conn, [{
            "product_code": code, "old": ours, "new": mall,
            "diff": None if ours is None else mall - ours, "big": big}],
            moment=moment, operator_id=None, hold_big=True, quote_id=quote_id,
            visitor_ref=visitor_ref, source_url_of=lambda _c: url)
        saved = bool(res["changed"])
    out = {"quoted": quoted, "mall": mall, "diff": mall - quoted, "saved": saved}
    if mall == quoted:
        out.update(status="same", message=None)
    else:
        out.update(status="changed", message=_message(moment, quoted, mall))
    return out


def confirm(moment: str, code: int, quoted: int, *, quote_id=None, visitor_ref=None) -> dict:
    """쇼핑몰 현재가를 읽어 비교하고 기록한다. 예외를 던지지 않는다.

    돌려주는 것(고객 응답에 그대로 싣는다):
      status    same · changed · unchecked
      quoted    고객이 보던 가격
      mall      쇼핑몰 현재가(못 읽으면 None)
      diff      mall - quoted
      saved     우리 판매가를 이번에 고쳤나
      message   고객에게 보일 문장(같으면 None)
      soldout   쇼핑몰이 품절로 표시했나(부품 페이지만 알려 준다)
      checked_at
    """
    now = now_iso()
    try:
        part_type = _part_type(code)
        got = mall_price_reader.read_price(code, part_type or mall_price.PC_PART_TYPE, timeout=TIMEOUT)
    except Exception as e:                                          # noqa: BLE001
        log.warning("[mall-live] read %s failed: %s", code, type(e).__name__)
        got = {"ok": False, "err": type(e).__name__}
    try:
        with engine.begin() as conn:
            out = _settle(conn, moment, code, quoted, got, quote_id=quote_id, visitor_ref=visitor_ref)
    except Exception as e:                                          # noqa: BLE001
        # 기록이 실패해도 고객 길은 막지 않는다. 읽은 값은 그대로 알린다.
        log.warning("[mall-live] settle %s failed: %s", code, type(e).__name__)
        mall = got.get("price") if got.get("ok") else None
        if mall is None:
            out = {"status": "unchecked", "quoted": quoted, "mall": None, "diff": None,
                   "saved": False, "message": MSG_UNCHECKED}
        else:
            out = {"status": "same" if mall == quoted else "changed", "quoted": quoted,
                   "mall": mall, "diff": mall - quoted, "saved": False,
                   "message": None if mall == quoted else _message(moment, quoted, mall)}
    out["soldout"] = bool(got.get("soldout"))
    out["checked_at"] = now
    log.info("[mall-live] %s code=%s status=%s saved=%s", moment, code, out["status"], out["saved"])
    return out
