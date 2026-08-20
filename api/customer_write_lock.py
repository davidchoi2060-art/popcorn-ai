"""고객 쓰기 잠금 — 지인·테스터 오픈 준비 (2026-08-20).

■ 왜 필요한가
  `api/customer_auth.py`의 신원 검증은 `if "@" not in email` 한 줄이 전부다(dev
  어댑터 — 실 OAuth 붙이기 전 상태, 그 파일은 이 작업의 담당 밖이라 고치지 않는다).
  남의 이메일만 알면 그 사람의 세션을 그대로 받는다. `api/my_account.py`·
  `api/my_orders.py`의 소유권 검사(`member_id` 대조)는 정상 동작하지만, **세션 자체가
  피해자 것**이라 그 검사를 정당하게 통과한다 — 검사를 고치는 문제가 아니라, 시험
  기간 동안 원장에 남는 쓰기(후기·환불 접수)를 별도로 잠그는 문제다.
  읽기(주문·결제 조회)는 막지 않는다 — "실제 개인정보를 넣지 마세요" 공지로 지인·
  테스터 범위에서는 감수한다.

■ 기존 ops_settings 5종(member·pay·settle·ship·refund)을 재사용하지 않은 이유
  그 스위치들(`api/admin_ops.py`)은 "이 기능을 자체/쇼핑몰 중 누가 처리하는가"라는
  영구적 사업 축이고 값 도메인이 own/mall 둘뿐이다(`KEYS`·검증 로직). refund 스위치를
  실측한 결과도 같은 결론이었다 — `api/my_orders.py`의 `create_refund()`는
  `ops_snapshot`에서 `refund_mode`를 읽어 **새 환불 행에 적어 넣기만** 할 뿐, 접수
  자체를 막는 조건으로 쓰지 않는다(막을 수 있는 "잠금" 상태가 애초에 그 도메인에
  없다 — own/mall 뿐). "잠금"이라는 세 번째 상태를 그 스위치에 넣으려면
  `api/admin_ops.py`(KEYS·검증·라벨·효과 목록)와 그걸 노출하는 관리자 화면까지
  고쳐야 하는데, 그건 이 작업의 담당 파일 밖이고, 그 스위치들의 "영구적 사업 라우팅"
  수명주기와도 맞지 않는다 — 이건 실 OAuth가 붙으면 통째로 지울 임시 안전장치다.
  그래서 같은 수명주기를 가진 기존 선례를 그대로 따른다: `POPCORN_TEST_HEADER_ENABLED`
  (`api/recommend.py`) — 둘 다 ".env로 켜고 끄는, 시험 기간 전용, 기본 꺼짐" 스위치이고
  `cookie_secure()`(`api/customer_auth.py`)와 같은 "env 읽는 함수 하나" 모양을 쓴다.

■ 동작
  기본값 = 꺼짐(쓰기 열림 — 지금 동작 그대로. 아무것도 안 하면 오늘 동작이 안 바뀐다).
  켜려면 `.env`에 아래 줄을 추가하고 **서버를 재기동**해야 한다(다른 `.env` 스위치와
  같은 이유 — `api/db.py`의 `load_dotenv()`는 프로세스 시작 시 한 번만 읽는다. 파일만
  고치고 재기동하지 않으면 아무 효과가 없다):

      POPCORN_CUSTOMER_WRITE_LOCK=1

  켜진 동안 `POST /api/my/reviews`·`POST /api/my/refunds`는 403으로 거부된다.
  다른 경로(주문·결제·후기 조회, `POST /api/my/account/map` 포함)는 이 스위치의 영향을
  받지 않는다 — 이 슬라이스의 담당(후기·환불 접수) 밖이라 건드리지 않았다.
"""
import os

ENV_KEY = "POPCORN_CUSTOMER_WRITE_LOCK"

REASON = (
    "지금은 시험 운영 기간이라 후기·환불 접수 등 쓰기 기능을 잠시 막아 두었습니다."
    " 로그인 보호가 강화되는 대로 다시 엽니다. 조회는 계속 이용하실 수 있습니다."
)


def write_locked() -> bool:
    """켜져 있으면 True. truthy 표기는 기존 `.env` 불리언 스위치와 같은 집합을 쓴다
    (`POPCORN_TEST_HEADER_ENABLED`·`COOKIE_SECURE`와 동일 — `api/recommend.py`
    `_test_header_enabled()` 참조)."""
    return os.environ.get(ENV_KEY, "").strip() in ("1", "true", "True", "yes")
