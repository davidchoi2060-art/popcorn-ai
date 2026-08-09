"""방문자 키 — 한 사람의 상담·견적·클릭·주문을 꿰는 실 (2026-08-09).

■ 왜 필요한가 (실측)
  깔때기 단계가 서로 이어지지 않았다. 상담 3,885건 중 회원이 붙은 것 **1건**,
  `promo_click_logs` 235행 중 `user_id` 있는 것 **0건**. 숫자는 있는데
  *"이 3,885건 중 몇 명이 주문까지 갔나"* 를 답할 수 없다.

■ 새 축을 만들지 않는다
  `users(user_id, anon_key)` 가 **이미 익명 방문자 표**이고 네 곳이 FK 로 참조한다
  (`promo_click_logs` · `swap_event_logs` · `recommendations` · `members.user_id`).
  **익명 → 회원 승격 경로까지 설계돼 있었다.** 값을 넣는 코드만 없었다.
  이 모듈이 그 코드다.

■ 쿠키 규약은 회원 세션과 같게 간다
  `httponly` · `samesite=lax` · `path=/` · `secure`는 `cookie_secure()` 를 따른다.
  다만 **수명이 다르다** — 회원 세션은 로그인 유지용이라 짧고, 방문자 키는
  "같은 사람인가"를 잇는 용도라 길어야 한다(1년).

■ 실패해도 장사를 막지 않는다
  키 발급이 실패하면 `None` 을 돌려주고 호출부는 그대로 진행한다.
  **집계용 축이 상담·주문을 막으면 안 된다** — `clicks` 가 "실패해도 화면을 막지
  않는다"고 한 것과 같은 판단이다.

■ 과거는 소급하지 않는다
  기존 상담·주문에는 키가 없다. 그럴듯한 키를 만들어 채우면 **없던 관계를 발명하는
  것**이다(재고 7,594건을 `inbound` 가 아니라 기초 재고로 기록한 것과 같은 규칙).
  깔때기는 **오늘 이후 발생분**만 센다는 사실을 화면이 먼저 말한다.
"""
import secrets

from fastapi import Request, Response
from sqlalchemy import text

from .customer_auth import cookie_secure

COOKIE = "pc_vid"
MAX_AGE = 365 * 24 * 3600      # 1년 — 회원 세션(짧음)과 수명이 다르다


def _new_key() -> str:
    return secrets.token_urlsafe(24)


def resolve(conn, request: Request, response: Response | None = None) -> int | None:
    """이번 요청의 방문자 `user_id`. 없으면 만들고 쿠키를 심는다.

    `response` 가 없으면(쿠키를 심을 수 없는 호출부) **읽기만** 한다 — 쿠키에 키가
    있으면 그 행을 찾아 주고, 없으면 `None`. 새 키를 만들어 놓고 못 심으면
    요청마다 새 방문자가 생겨 **한 사람이 여럿으로 세어진다.**
    """
    try:
        key = (request.cookies.get(COOKIE) or "").strip()
        if key:
            row = conn.execute(text(
                "SELECT user_id FROM users WHERE anon_key = :k"), {"k": key}).first()
            if row:
                return row[0]
            # 쿠키는 있는데 행이 없다(DB 초기화 등). 같은 키로 되살린다 —
            # 새 키를 주면 그 사람의 이전 행동과 끊긴다.
            if response is None:
                return None
            uid = conn.execute(text(
                "INSERT INTO users (anon_key) VALUES (:k)"
                " ON CONFLICT (anon_key) DO UPDATE SET anon_key = EXCLUDED.anon_key"
                " RETURNING user_id"), {"k": key}).scalar()
            return uid

        if response is None:
            return None
        key = _new_key()
        uid = conn.execute(text(
            "INSERT INTO users (anon_key) VALUES (:k) RETURNING user_id"),
            {"k": key}).scalar()
        response.set_cookie(COOKIE, key, httponly=True, samesite="lax", path="/",
                            max_age=MAX_AGE, secure=cookie_secure())
        return uid
    except Exception:
        # 집계용 축이 장사를 막지 않는다.
        return None


def promote(conn, user_id: int | None, member_id: int) -> None:
    """로그인·가입 시 방문자 키를 회원에 붙인다.

    이러면 **익명으로 상담하다 가입해도 앞의 행동이 이어진다.**
    이미 다른 방문자 키가 붙어 있으면 덮지 않는다 — 처음 붙은 것이 그 회원의
    출발점이고, 덮으면 그 사람의 최초 유입을 잃는다.
    """
    if not user_id:
        return
    try:
        conn.execute(text(
            "UPDATE members SET user_id = :u WHERE member_id = :m AND user_id IS NULL"),
            {"u": user_id, "m": member_id})
    except Exception:
        pass
