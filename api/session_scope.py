"""세션 조회 술어 — 다섯 파일이 각자 적던 「어느 세션을 포함하는가」를 한 자리로 모은다.

배경(U-34, decision-log 2026-08-20): `consult_sessions.data_origin`(real/test/demo)
표식은 2026-08-20 과거분 소급 적용으로 끝났다(과거분 5,296건 + 검증 5건 — `docs/data-ops/
2026-08-20_consult-sessions-test-mark*.md`). 다섯 파일(admin_dashboard·admin_funnel·
admin_sessions·admin_members·scripts/status)이 각자 `FROM consult_sessions` 를 새로
썼는데, 이 함수 하나로 모아 **정책이 정해지는 날 한 곳만 고치면 되게** 만들었다
(제작 지시 원문). 정책은 아래 A-81 로 정해졌다 — 그래서 이제 이 함수가 실제로 거른다.

■ A-81 확정(decision-log.md, ✅ 2026-08-20 사장님 확정) — 이 함수가 반영하는 값

    필터     consult_sessions.data_origin = 'real'
    기준선   created_at > 2026-08-19 15:57:46 (UTC)
             = X-Popcorn-Test 헤더 게이트 배포 커밋 `ead6dd3`(2026-08-20 00:57:46 KST) 시각
    어휘     그 이전 구간을 「시험 운영 기간」이라 부른다(이미 `api/customer_write_lock.py`
             의 `REASON` 이 고객에게 쓰던 말 — 새로 짓지 않았다)

  **왜 이 시각인가**: 이 순간부터 `X-Popcorn-Test` 헤더 게이트가 회귀·점검 트래픽을
  가려내기 시작했다 — **그 앞은 코드가 아무것도 지키지 않던 구간**이고 **그 뒤는 게이트가
  지키는 구간**이다. 기준선이 실측치가 아니라 배포 사실 자체로 정당화된다(달력일 기준보다
  이 경계에서 「일부러 미판정으로 남긴」 반복 패턴 잔존율이 79% → 0% 로 떨어짐 — 상세 근거는
  decision-log A-81 본문). 이 상수는 **등재 시점(2026-08-20) 실측이 4건이었다는 사실과
  별개**다 — 지금 다시 재면 다른 값이 나온다(계속 늘어난다).

⚠ **시각 리터럴은 UTC 로 해석된다 — KST 로 새면 9시간이 어긋난다.** `consult_sessions.
created_at` 은 `timestamp without time zone` 이고, DB 서버 세션 TimeZone 이 `UTC`(직접
확인: `SHOW TIMEZONE` → `UTC`, 컬럼 기본값 `now()` 가 이 세션에서 naive 로 캐스팅되며 저장됨)
라 **naive 컬럼 값 자체가 이미 UTC 벽시계 값**이다(`api/timeutil.py:21` 의 "naive = UTC 로
간주" 규약과 정확히 일치). 그래서 이 술어의 리터럴도 **타임존 접미사 없이** 그대로 쓴다
(`TIMESTAMP '2026-08-19 15:57:46'`) — `+00`·`Z`·`AT TIME ZONE` 을 붙이면 이미 naive 인
값에 불필요한 변환이 끼어들 위험이 있다.

⚠ **별칭은 `s` 고정이다**(`pending_where()` 가 `p` 로 고정한 것과 같은 이유). 이 저장소가
배선한 18개 조회 지점(2026-08-20 실측)이 전부 `FROM/JOIN consult_sessions s` 형태다 —
직접 grep 으로 재확인했다(`FROM consult_sessions s`·`JOIN consult_sessions s` 외 별칭 0건).

⚠ **SQL 주입 방지.** 이 술어는 **상수 문자열**이다 — 매개변수를 받지 않으므로 바깥 입력이
끼어들 통로가 없다(`pending_where()` 는 `hold`·`kind` 인자를 고정된 상수 중에서만 고르는데,
이 함수는 그보다도 좁게 인자 자체를 받지 않는다).

⚠ **대상의 경계 — `consult_sessions` 를 직접 조회하거나, 거기 딸린 세션 집합을 분모로
삼는 파생 집계까지.** `quote_snapshots` 만 단독으로 세는 「완주」 집계(`admin_sessions.
list_sessions()` 의 `done_total`, `admin_dashboard.quote_quality()` 의 `done`)는 처음엔
대상 밖으로 뒀는데, 분모(`total`·`sess`, scope 적용)와 분자(`done_total`·`done`, scope
미적용)가 다른 모집단이 되어 **정책이 켜지자 실제로 완주율이 100%를 넘었다**(제작 중
발견·수정, 2026-08-20). 그래서 이 둘도 `quote_snapshots q JOIN consult_sessions s ON
s.session_id=q.session_id WHERE {session_scope_where()}` 형태로 이 함수를 거친다. 남은
예외는 `quote_snapshots` 만으로 존재하고 어떤 `consult_sessions` 파생 분모와도 나눗셈으로
짝짓지 않는 값(`quote_quality()` 의 `tiers` — quote_type 분포, 세션 수와 비교하지 않고
화면에도 쓰이지 않는다, `api/admin_ui_home.py:35` 실측)뿐이다.
"""
from datetime import datetime, timezone

# 시각은 timeutil.iso()로만 문자열화한다 — 회귀 [15]가 api/*.py 전체를 텍스트로 훑어
# 타임존 없는 원문 메서드 호출(점 + iso + format + 괄호) 리터럴이 있으면 실패시킨다
# (맥락을 안 보는 검사다 — admin_funnel.py가 같은 이유로 이미 그 리터럴을 피해 적었다).
# 이 값은 이미 tzinfo가 있어 iso()가 그대로 돌려준다(모듈 docstring 참조).
from .timeutil import iso

# A-81 기준선 — SQL 술어와 화면 표시 문구가 **같은 값 하나**에서 나온다(따로 적으면 갈린다).
SCOPE_BASELINE = datetime(2026, 8, 19, 15, 57, 46, tzinfo=timezone.utc)
SCOPE_BASELINE_ISO = iso(SCOPE_BASELINE)                        # "2026-08-19T15:57:46+00:00"
SCOPE_BASELINE_SQL = SCOPE_BASELINE.strftime("%Y-%m-%d %H:%M:%S")  # naive — timeutil 규약과 일치
SCOPE_LABEL = "시험 운영 기간"                                    # api/customer_write_lock.py REASON 과 같은 말

_SCOPE_WHERE = f"s.data_origin = 'real' AND s.created_at > TIMESTAMP '{SCOPE_BASELINE_SQL}'"


def session_scope_where() -> str:
    """세션 조회의 「어느 세션을 포함하는가」— 단일 원천.

    A-81(decision-log.md) 확정: `data_origin='real'` 이고 `created_at` 이 헤더 게이트
    배포 시각(2026-08-19 15:57:46 UTC) 이후인 세션만 포함한다. WHERE 절에 ``AND`` 로
    이어 붙이거나(``WHERE {session_scope_where()} AND ...``) 단독으로도 쓸 수 있다
    (``WHERE {session_scope_where()}``).

    정책이 다시 바뀌면 이 함수의 반환값만 바꾼다. 매개변수를 받지 않는 이유는 모듈
    docstring 「SQL 주입 방지」 참조.
    """
    return _SCOPE_WHERE


def scope_note() -> str:
    """A-81 기준선을 사람이 읽는 안내 문장으로 — 세션 수가 왜 줄었는지 화면이 말할 때 쓴다.

    「이게 없으면 상담 4건이 무슨 뜻인지 아무도 모른다」(제작 지시 원문)에 대한 답.
    어휘는 `SCOPE_LABEL`(「시험 운영 기간」) 하나로 고정 — 이미 `api/customer_write_lock.py`
    의 `REASON` 이 고객에게 쓰던 말이다. 새 말을 지어내지 않는다.
    """
    return (f"{SCOPE_BASELINE_SQL}(UTC) 이전은 「{SCOPE_LABEL}」으로 분리해 이 수치에서"
            f" 제외했습니다 — 그 이전은 회귀·점검 트래픽과 섞여 있었습니다(data_origin="
            f"'real' · 기준선 이후만 집계).")
