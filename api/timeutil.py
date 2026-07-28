"""시각 표기 단일 원천 — 화면이 서울 시각으로 읽을 수 있게 한다(슬라이스 62).

문제: DB(Cloud SQL)는 **UTC**로 돌고 시각 컬럼은 `timestamp without time zone`이다.
그래서 `dt.isoformat()`이 `"2026-07-28T07:27:12"`처럼 **타임존이 없는 문자열**을 만들었다.
브라우저의 `new Date(...)`는 타임존이 없으면 그 값을 **로컬 시각으로 해석**한다 —
UTC 07:27이 서울 07:27로 찍혔다. 실제로는 16:27이라 **9시간이 어긋났다**(사용자 보고).

해결은 타임존을 붙이는 것이다. `"...+00:00"`이면 브라우저가 알아서 서울 시각으로 그린다.
서버가 KST 문자열을 만들어 주는 방법도 있지만, 그러면 값에 지역이 박혀 나중에
다른 지역에서 볼 때 다시 어긋난다. **시각은 절대값으로 주고 표시를 각자 한다.**

`now()`도 여기서 만든다: `datetime.now()`는 서버가 어디서 도느냐에 따라 값이 달라진다
(로컬 PC는 KST, GCP VM은 UTC). 같은 코드가 두 값을 주면 안 된다.
"""
from datetime import datetime, timezone


def iso(dt) -> str | None:
    """DB에서 읽은 시각 → 타임존이 붙은 ISO 문자열.

    naive(타임존 없음)면 **UTC로 간주**한다 — DB가 UTC로 돌기 때문이다.
    이미 타임존이 있으면 그대로 둔다.

    **날짜(date)는 손대지 않는다**: 정산일 같은 값에는 시각이 없어 타임존도 없다.
    `date.replace(tzinfo=...)`는 TypeError를 낸다(정산 화면이 실제로 500이 났다).
    """
    if dt is None:
        return None
    if not hasattr(dt, "hour"):          # date — 시각이 없으면 타임존도 없다
        return dt.isoformat()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def now_iso() -> str:
    """지금 시각 → 타임존이 붙은 ISO. 서버 위치와 무관하게 같은 값을 준다."""
    return datetime.now(timezone.utc).isoformat()
