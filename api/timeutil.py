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
from datetime import datetime, timedelta, timezone


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


# ── 기간 필터 (2026-08-05) ────────────────────────────────────────────
# 운영자는 **서울 날짜**로 생각하는데 DB 시각 컬럼은 전부 `timestamp without time zone`
# 이고 값은 **UTC**다(실측: DB TimeZone=UTC, now()가 UTC). 그래서 화면이 보낸
# `2026-08-06` 을 그대로 `created_at::date = '2026-08-06'` 에 넣으면 **9시간이 어긋난다** —
# 슬라이스 100에서 화면 표기로 이미 한 번 겪은 그 함정이 이번엔 **조회 조건**에서 난다.
#
# 서울 2026-08-06 하루 = UTC 2026-08-05 15:00 ~ 2026-08-06 15:00 이다.
#
# 끝날은 **반개구간**으로 만든다(`< 다음날 00:00`). `<= date_to` 로 두면 그날 낮에 생긴
# 행이 통째로 빠진다 — 자정 값만 걸리기 때문이다. 이건 흔한 오프바이원이고
# "지난주 주문"이 조용히 하루치 모자라는 형태로 나타난다.
KST = timezone(timedelta(hours=9))


def kst_day_range(date_from: str | None, date_to: str | None):
    """서울 날짜(YYYY-MM-DD) 범위 → **UTC naive** 경계 `[from, to)`.

    컬럼이 naive 라 naive 로 돌려준다(형 변환이 조용히 끼어들지 않게).
    잘못된 형식이나 뒤집힌 범위는 `ValueError` — 호출자가 400 으로 바꾼다.
    """
    def _one(s: str, plus_days: int = 0):
        try:
            d = datetime.strptime(s.strip(), "%Y-%m-%d").date()
        except ValueError:
            # strptime 의 원문("time data ... does not match format '%Y-%m-%d'")을
            # 그대로 내보내면 운영자가 읽을 수 없다 — 화면에 뜰 말로 바꾼다.
            raise ValueError("기간은 YYYY-MM-DD 형식으로 입력하세요")
        kst_midnight = datetime(d.year, d.month, d.day, tzinfo=KST) + timedelta(days=plus_days)
        return kst_midnight.astimezone(timezone.utc).replace(tzinfo=None)

    lo = _one(date_from) if date_from else None
    hi = _one(date_to, 1) if date_to else None          # 그날 전체를 포함한다
    if lo is not None and hi is not None and lo >= hi:
        raise ValueError("시작일이 종료일보다 뒤입니다")
    return lo, hi


def range_sql(col: str, lo, hi) -> str:
    """`[lo, hi)` 조건절. 값이 없으면 그 쪽 조건을 빼서 항상 참으로 둔다."""
    parts = []
    if lo is not None:
        parts.append(f"{col} >= :_dt_lo")
    if hi is not None:
        parts.append(f"{col} < :_dt_hi")
    return (" AND " + " AND ".join(parts)) if parts else ""
