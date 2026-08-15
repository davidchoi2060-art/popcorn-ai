# -*- coding: utf-8 -*-
"""유입 성과(ADM-HND-030 후보) 집계 API — `GET /api/admin/funnel-performance`.

계약 `docs/design/spec-funnel.md`(사장님 확정 2026-08-15, **1a 안** "끊긴 깔때기를 그대로
그린다"). 정의서 `docs/design/req/req-funnel-performance.md`. 원문(Claude Design)은
하네스만 연다 — 이 파일은 계약 요약 텍스트 + 직접 실측만으로 지었다.

**조회 전용.** 쓰기 없음.

■ 이 화면의 전부 — 두 구간을 정직하게 가른다
  (A) 지금 우리 데이터만으로 잴 수 있는 구간   상담 -> 완주 -> 인계  (이 API 가 낸다)
  (B) 몰 데이터가 있어야 재는 구간             인계 -> 클릭 -> 구매  (이 API 는 내지 않는다
      — 값 자체가 없다. 화면은 [향후 사용예정] 정적 문구로만 채운다. 이 파일이 숫자를
      지어 채우지 않는다)

■★ 담당 파일이 셋이라(`admin_ui_funnel.py`·`funnel.html.j2`·이 파일) `admin_ui_handoff_log.py`
  처럼 한 파일에 페이지+데이터를 합칠 필요가 없었다. **`admin_sessions.py` / `admin_ui_
  consult_sessions.py` 분리 패턴**(데이터는 `/api/admin/*`, 페이지는 `/admin2/*`)을 그대로
  따랐다 — 이게 더 중요한 이유가 있다: `api/auth.py`를 직접 읽어 확인한 결과(2026-08-15,
  담당 파일 밖 — 읽기만 했다) **`_is_gated()`가 이제 `/api/admin/*` 뿐 아니라 `/admin2/*`
  전체도 막는다**(`auth_middleware`/`_is_gated`, 2026-08-15 갱신 — `admin_ui_handoff_log.py`
  의 "그 미들웨어 밖이다" 서술은 그 갱신 **이전** 시점 기준이라 지금은 낡았다. `admin_ui_
  mall_sync.py` 모듈 docstring 이 이미 이 최신 사실을 반영해 "미들웨어가 `/admin2/`를
  막는 것이 전제 — 이 파일 자신은 로그인을 확인하지 않는다"라고 적어 뒀다). 그런데 `/admin2/*`
  아래 데이터 엔드포인트는 **명시적 화이트리스트**(`ADMIN2_JSON_DATA_PATHS`, 지금은
  `/admin2/handoff-log/data` 하나뿐)에 있어야만 거절 응답이 JSON이 되고, 그 목록은
  `auth.py`(담당 밖 — 절대 고치지 말라는 지시)에 있다. 그래서 데이터를 `/admin2/...`
  아래 새로 두면 이 화이트리스트에 없어 무세션 요청이 **HTML 로그인 안내**를 받고,
  `funnel.html.j2`의 `fetch(...).json()` 파싱이 조용히 null이 되어 실패 사유가
  사라진다(그 사고가 이미 `auth.py` 주석에 남아 있다 — 같은 함정을 다시 만들 이유가
  없다). **`/api/admin/funnel-performance`로 두면 이 문제 자체가 생기지 않는다** —
  `_is_gated()`가 `path.startswith("/api/admin/")`로 이미 잡고, 그 경로의 거절은
  원래부터 JSON이다(`_is_admin2_page()`가 `/admin2` 로 시작하지 않는 경로는 애초에
  보지 않는다). 그래서 이 파일도 `admin_sessions.py`와 마찬가지로 **자체 인증 코드를
  두지 않는다** — 미들웨어가 이미 게이트한다. 쓰기가 없으므로(전부 GET) 필요 등급도
  `required_role()` 기본값(viewer)로 충분하다(§결정 3 — 열람 등급은 사장님 결정 대기,
  ADM-HND-030 자체가 아직 화면 ID 후보인 것과 별개로 **미로그인 401 은 이미 계약이
  확정**했다 — 등급을 owner/operator로 좁히는 것은 이 파일 담당 밖의 후속 결정이다).

■ 제작 전 실측 (2026-08-15, `api.db.engine` 직접 SELECT — 전부 읽기 전용, 지시서
  §「제작자가 먼저 재야 하는 것」 다섯 항목 그대로)

  ① **인계 기능 시작일이 어디에 기록돼 있나** — 코드 한 곳(`db/migrations/versions/
     0042_handoffs.py` 파일 자체의 docstring "(2026-08-11)")뿐이다. `alembic_version`
     테이블은 **현재 head 리비전 문자열 하나만** 담고 있고(직접 SELECT, 2026-08-15:
     `0051` 한 행) 각 마이그레이션이 "언제" 적용됐는지 이력은 어디에도 없다 —
     `ops_settings`/`ops_settings_history`도 "인계 기능"이라는 개념 자체를 모른다
     (그 표는 운영 모드 스위치 5종만 다룬다, 직접 SELECT로 확인). **그래서 이 API 는
     매 요청 `MIN(handoffs.created_at)`를 직접 재서 쓴다**(아래 `_feature_start()`).
     화면 어디에도 "2026-08-11"을 문자열로 박지 않는다 — 이 값은 응답의
     `feature.start_date`로만 나간다. 실측 결과 두 값이 **일치한다**(첫 handoff
     `2026-08-11 12:56:58+00:00` → KST 21:56:58, 같은 날짜) — 그래서 지금은 어느
     쪽을 봐도 같은 답이지만, `handoffs`가 훗날 전부 비워지면(재현 불가능한 가정은
     아니다 — 이 프로젝트는 베타 잔재를 비우고 새로 세우는 절차를 이미 여러 번 썼다,
     CLAUDE.md "베타 배포 상태" 참조) `MIN()`이 NULL이 되므로, 그때만 마이그레이션
     날짜 상수로 대체하고 `feature.source`로 어느 쪽인지 밝힌다(아래).
  ② **(A) 3단계를 낼 수 있나** — 된다. `consult_sessions`(상담) →
     `quote_snapshots`(완주 판정) → `handoffs`(인계) 순으로 `session_id`가 이어진다
     (실측: `handoffs` 3건 전부 `session_id`가 NULL이 아니고 `consult_sessions`에
     실제로 존재한다 — 세션 이전 시각(pre-0811) 소속 handoff 0건도 직접 SELECT로
     확인, 아래 참조).
  ③ **"완주"의 정의** — `api/admin_sessions.py`(담당 밖, 읽기만)가 이미 "세션에
     `quote_snapshots`가 하나라도 있으면 완주"로 판정하고 있다(`done_total =
     COUNT(DISTINCT session_id) FROM quote_snapshots`). 이 화면도 **같은 정의**를
     그대로 쓴다 — 화면마다 "완주"가 다른 뜻이면 안 된다(단일 원천).
  ④ **인계 건의 티어·가격 재확인 결과가 어디 있나** — 티어는 `handoffs.quote_type`
     (값 셋: value/recommend/highend, `api/handoff.py` L61-62 검증 그대로). 가격
     재확인은 **라인 단위**로 `handoff_items.mall_status`에 있다(값 셋: 확인됨/
     가격변동/확인못함 — `api/admin_ui_mall_sync.py` 모듈 docstring이 이미 실측해
     둔 사실과 일치, 재확인 완료 — 2026-08-15 SELECT: 확인됨 12·가격변동 13·
     확인못함 2, 총 27라인). `handoffs.price_checked`는 라인 단위 3분류가 아니라
     "확인못함이 하나라도 있으면 false"인 **이진값**이라(`api/handoff.py` L106),
     3칸 요약에는 못 쓴다 — 그래서 이 API 는 `handoff_items.mall_status`를 직접
     GROUP BY 한다(§겹침 판단은 아래).
  ⑤ **`promo_click_logs` ↔ `handoffs` 조인이 정말 0건인가** — 직접 셌다(2026-08-15):
     `handoffs.user_id`(473·474·563) 로 `promo_click_logs`를 JOIN한 결과 **0행**,
     `handoffs.session_id`(4247·4315) 로 `swap_event_logs`를 JOIN한 결과도 **0행**.
     두 표 자체는 비어 있지 않다(`promo_click_logs` 309행·`swap_event_logs` 318행,
     둘 다 전체 카운트로 확인) — "표가 비어서 0"이 아니라 "겹치는 사람이 아직 없어서
     0"이다. 이 API 는 이 사실을 구분해서 내보낸다(`signals.*.total_rows` 별도 필드).

■ 판단한 것 (계약에 명시되지 않아 이 파일이 정한 것 — checker 확인 필요)

  ① **기간 소속은 세션 코호트 기준.** "몇 명이 왔고(상담) 그중 몇 명이 완주했고 그중
     몇 건이 인계됐나"를 묻는 화면이라, `consult_sessions.created_at`으로 기간을
     정하고 그 세션들에 딸린 완주·인계를 센다(핸드오프 자신의 `created_at`이 아니다).
     실측으로 핸드오프가 기간 밖 세션을 가리키는 사례가 없음을 확인했으므로(위 ②)
     오늘은 두 기준이 같은 답을 내지만, 정의는 **세션 기준**으로 고정한다 —
     "이 세션 코호트가 나중에 어떻게 됐나"를 지키기 위해서다.
  ② **가격 재확인 3칸(④㉯)의 분모는 라인이지, 건이 아니다.** 계약 문구가 "분모(인계
     {n}건)를 밝힌다"고 적어서 처음엔 건 단위를 의심했지만, `mall_status` 자체가
     라인 컬럼이라 건 단위로 뭉치려면 "한 건 안에 확인못함과 가격변동이 섞이면
     어느 쪽으로 셀지"를 새로 지어내야 한다(계약에 없다 — 지어내지 않는다는 원칙에
     걸린다). 그래서 **라인 수를 1차 분모로 쓰고**, "인계 {n}건 기준"이라는 문장을
     **별도 사실로 함께** 내려보낸다(뭉개지 않고 둘 다 보여준다) — `mall_sync` 화면의
     "확인됨/가격변동/확인못함" 정의(라인 GROUP BY)와도 같아서 두 화면이 같은 질문에
     다른 답을 하지 않는다(§단일 원천).
  ③ **경고 배너의 "인계율"은 완주 대비로 고정한다.** 계약 §4 예시 문장이 "완주 대비
     인계 {비율}"을 쓰고 있어(다른 문단은 "전체 세션 대비"도 잠깐 나오지만 예시일 뿐),
     화면 전체에서 "인계율"이라는 한 단어가 두 가지 다른 분모를 가리키면 안 되므로
     하나로 통일했다. 세션 대비 값도 `funnel.sessions`/`funnel.handoff` 로 원자료가
     이미 나가 있어 필요하면 화면이 별도로 조합할 수 있다(계산은 서버가 다 해서
     보내고, 화면은 문자열만 조립한다).
  ④ **표본이 작다는 caveat 은 인계 세션 수 < 30일 때 붙인다.** 계약은 "표본이 작으면"
     이라고만 하고 정확한 문턱을 주지 않는다. 30은 통계적으로 흔히 쓰는 "작은 표본"
     관행값이고, 지금 실측값(전 기간 2·기능기간 2)은 이 문턱 안에서도 한참 작아
     어느 문턱을 골라도 결론(=caveat 표시)은 같다 — 문턱 자체가 결과를 바꾸지 않는
     지금 시점엔 안전한 판단이다.
  ⑤ **`handoffs.session_id IS NULL`인 행이 있으면 이 화면의 기간별 집계에서 조용히
     빠진다**(세션 코호트 기준이라 세션이 없으면 어느 기간에도 속할 수 없다). 지금은
     0건(전수 확인)이라 안 보이지만, 나중에 생기면 화면이 "인계가 준 것처럼" 보일 수
     있어 `integrity.orphan_handoffs`로 전역(기간 무관) 카운트를 항상 함께 내려보낸다
     — 0이 아니면 화면이 배너로 알려야 한다(템플릿 담당).
"""
from datetime import date, datetime
from datetime import timezone as _tz

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .admin_nav import NAV
from .db import engine
from .timeutil import KST, iso, kst_day_range, range_sql

router = APIRouter(prefix="/api/admin")

# 인계 기능 마이그레이션 — `MIN(handoffs.created_at)`이 NULL일 때(표가 비었을 때)만 쓰는
# 대체값이다. 정본은 실측값(위 모듈 docstring ① 참조) — 이 상수를 화면에 절대 직접
# 노출하지 않는다(항상 `feature.source`로 어느 값을 썼는지 밝힌 채로 `start_date`에 담아 낸다).
HANDOFF_MIGRATION_DATE = date(2026, 8, 11)
HANDOFF_MIGRATION_FILE = "db/migrations/versions/0042_handoffs.py"

TIER_LABELS = {"highend": "고성능형", "recommend": "추천형", "value": "가성비형"}
TIER_ORDER = ["highend", "recommend", "value"]      # 계약 §④㉮ 표기 순서 그대로
MALL_STATUS_ORDER = ["확인됨", "가격변동", "확인못함"]  # `api/handoff.py`가 쓰는 3값 전부

# 카드 ④㉯·⑤ 링크 대상 — 경로로 판정한다(라벨 아님). `admin_ui_swap_click_logs.py`가
# 겪은 사고(라벨 리네임으로 조회가 조용히 깨짐)와 같은 이유로 `admin_ui_handoff_log.py`·
# `admin_ui_mall_sync.py`가 이미 쓴 방식을 그대로 따른다 — 각 파일의 실제
# `@router.get(...)` 선언을 직접 읽어 확인한 경로다(2026-08-15).
NAV_TARGETS = {
    "handoff_log": {"display": "인계 기록", "path": "/admin2/handoff-log"},
    "mall_sync": {"display": "쇼핑몰 동기화", "path": "/admin2/mall-sync"},
}

LOW_SAMPLE_THRESHOLD = 30  # 위 모듈 docstring "판단한 것 ④" 근거


def _nav_links() -> dict:
    """admin_nav.NAV를 "그 경로가 실제로 링크돼 있는가"로만 훑는다(읽기 전용)."""
    live = {href for _title, _icon, items in NAV for _label, href, _note in items if href}
    out = {}
    for key, t in NAV_TARGETS.items():
        ok = t["path"] in live
        out[key] = {
            "label": t["display"], "path": t["path"], "available": ok,
            "reason": None if ok else "아직 admin2 메뉴에 연결되지 않았습니다 — 신설 예정",
        }
    return out


def _kst_date_of(utc_naive_dt) -> date | None:
    """naive(=UTC로 간주, `api/timeutil.py` 규약) datetime -> KST 달력일."""
    if utc_naive_dt is None:
        return None
    if utc_naive_dt.tzinfo is None:
        utc_naive_dt = utc_naive_dt.replace(tzinfo=_tz.utc)
    return utc_naive_dt.astimezone(KST).date()


def _pct(n: int, d: int, digits: int = 1):
    if not d:
        return None
    return round(n * 100.0 / d, digits)


def _feature_start(conn) -> tuple[date, str]:
    """인계 기능 시작일 — 매 요청 실측(위 모듈 docstring ① 참조)."""
    row = conn.execute(text("SELECT MIN(created_at) FROM handoffs")).scalar()
    if row is not None:
        return _kst_date_of(row), "measured"
    return HANDOFF_MIGRATION_DATE, "migration_date_fallback"


def _stage_counts(conn, lo, hi) -> dict:
    """세션 코호트 [lo, hi) 안에서 상담·완주·인계(세션·건)를 함께 센다."""
    params = {}
    if lo is not None:
        params["_dt_lo"] = lo
    if hi is not None:
        params["_dt_hi"] = hi
    rs = range_sql("s.created_at", lo, hi)
    sessions = conn.execute(text(
        "SELECT COUNT(*) FROM consult_sessions s WHERE 1=1" + rs), params).scalar_one()
    done = conn.execute(text(
        "SELECT COUNT(DISTINCT s.session_id) FROM consult_sessions s"
        " JOIN quote_snapshots q ON q.session_id = s.session_id WHERE 1=1" + rs),
        params).scalar_one()
    ho = conn.execute(text(
        "SELECT COUNT(DISTINCT h.session_id), COUNT(*) FROM consult_sessions s"
        " JOIN handoffs h ON h.session_id = s.session_id WHERE 1=1" + rs),
        params).first()
    return {"sessions": sessions, "done": done,
            "handoff_sessions": ho[0], "handoff_count": ho[1]}


def _ratio_block(stage: dict, digits: int = 2) -> dict:
    """완주 대비 인계 — 위 모듈 docstring "판단한 것 ③" 근거로 이 정의로 고정한다."""
    num, den = stage["handoff_sessions"], stage["done"]
    return {"num": num, "den": den, "pct": _pct(num, den, digits)}


def _raw_ratio(stage: dict):
    """배수 계산 전용 — 반올림하지 않은 원 비율. `_ratio_block()["pct"]`는 화면 표시용으로
    이미 반올림돼 있어(예: 0.04·0.18), 그 반올림된 값끼리 나누면 배수가 왜곡된다(실측:
    반올림값으로 나누면 4.5배, 원값으로 나누면 4.4배 — 2026-08-15 자기 검증 중 발견해
    고쳤다). 배수는 항상 이 함수의 결과로만 계산한다."""
    num, den = stage["handoff_sessions"], stage["done"]
    return (num / den) if den else None


def _scoped_handoffs(conn, lo, hi) -> list:
    params = {}
    if lo is not None:
        params["_dt_lo"] = lo
    if hi is not None:
        params["_dt_hi"] = hi
    rs = range_sql("s.created_at", lo, hi)
    rows = conn.execute(text(
        "SELECT h.handoff_id, h.handoff_no, h.session_id, h.user_id, h.quote_type,"
        " h.total_quoted FROM consult_sessions s"
        " JOIN handoffs h ON h.session_id = s.session_id WHERE 1=1" + rs + " ORDER BY h.handoff_id"),
        params).mappings().all()
    return list(rows)


@router.get("/funnel-performance")
def funnel_performance(preset: str = "feature", date_from: str | None = None,
                        date_to: str | None = None):
    """유입 성과 — (A) 상담->완주->인계 구간 집계. (B) 구간은 값 자체가 없어 이 API 가
    내지 않는다(화면이 정적 문구로 채운다).

    `preset`:
      `feature`  인계 기능 존재 기간(실측 시작일 ~ 오늘) — 계약 §기간선택 ㉮, 기본값 후보
      `all`      전체 기간(세션 최초 기록 ~ 오늘) — ㉯
      `custom`   `date_from`·`date_to`(YYYY-MM-DD, KST 달력일, 포함) 직접 지정 — ㉰
    """
    if preset not in ("feature", "all", "custom"):
        raise HTTPException(400, "알 수 없는 기간 프리셋입니다: %s" % preset)

    with engine.connect() as conn:
        feature_start, feature_source = _feature_start(conn)
        # 회귀 [15](tests/regression.py test_pool_gate(), 파일 텍스트 전체를 훑는 검사 —
        # "API에 타임존 없는 isoformat 호출이 없다")가 이 파일 텍스트에 그 메서드 호출
        # 리터럴이 있는지만 본다(맥락은 안 본다). 그래서 이 주석에도 그 리터럴 문자열을
        # 그대로 적지 않는다 — 적었다가 주석만으로 검사에 걸린 전례가 이 파일 안에 있었다
        # (2026-08-15). 여기서 다루는 값은 전부 date(시각 자체가 없음)라 실사용자 위험은
        # 낮지만(확인자 판정), 검사를 통과하려면 예외 없이 `iso()`로 통일해야 한다.
        feature_lo, _ = kst_day_range(iso(feature_start), None)

        sessions_min_raw = conn.execute(text("SELECT MIN(created_at) FROM consult_sessions")).scalar()
        sessions_min_date = _kst_date_of(sessions_min_raw)
        today_kst = datetime.now(KST).date()

        if preset == "all":
            lo, hi = None, None
            period_from_label = iso(sessions_min_date)
            period_to_label = iso(today_kst)
            period_label = "전체 기간"
        elif preset == "feature":
            lo, hi = feature_lo, None
            period_from_label = iso(feature_start)
            period_to_label = iso(today_kst)
            period_label = "인계 기능 존재 기간"
        else:
            if not date_from or not date_to:
                raise HTTPException(400, "기간 직접 고르기는 date_from·date_to가 모두 필요합니다")
            try:
                lo, hi = kst_day_range(date_from, date_to)
            except ValueError as e:
                raise HTTPException(400, str(e))
            period_from_label, period_to_label = date_from, date_to
            period_label = "직접 고른 기간"

        primary = _stage_counts(conn, lo, hi)

        # ── 경고 배너 — 선택 기간이 인계 기능 시작일 이전을 포함하면 ────────────────
        crosses = (lo is None) or (lo < feature_lo)
        warning = None
        if crosses:
            narrow_lo = feature_lo if lo is None else max(lo, feature_lo)
            narrow = _stage_counts(conn, narrow_lo, hi)
            broad_r = _ratio_block(primary)
            narrow_r = _ratio_block(narrow)
            broad_raw, narrow_raw = _raw_ratio(primary), _raw_ratio(narrow)
            multiplier = None
            if broad_raw not in (None, 0) and narrow_raw is not None:
                multiplier = round(narrow_raw / broad_raw, 1)
            pre_start_to = date.fromordinal(feature_start.toordinal() - 1)
            warning = {
                "pre_start_from": period_from_label,
                "pre_start_to": iso(pre_start_to),
                "broad": {**broad_r, "sessions": primary["sessions"], "from": period_from_label},
                "narrow": {**narrow_r, "sessions": narrow["sessions"], "from": iso(feature_start)},
                "multiplier": multiplier,
            }

        # ── (A) 3단계 표기 ──────────────────────────────────────────────
        sess_to_done_pct = _pct(primary["done"], primary["sessions"], 1)
        done_to_ho = _ratio_block(primary, digits=2)
        funnel = {
            "sessions": {"n": primary["sessions"]},
            "done": {"n": primary["done"], "pct_of_sessions": sess_to_done_pct,
                     "note": "그 세션에 quote_snapshots가 하나라도 있으면 완주로 판정합니다"
                             "(견적 상담 기록 화면과 같은 정의)."},
            "handoff": {
                "sessions": primary["handoff_sessions"], "count": primary["handoff_count"],
                "pct_of_done": done_to_ho["pct"], "denominator_done": primary["done"],
                "low_sample": primary["handoff_sessions"] < LOW_SAMPLE_THRESHOLD,
            },
        }

        # ── ④㉮ 티어 분포 + 총액(합계·건수만 — 평균 금지) ─────────────────
        scoped = _scoped_handoffs(conn, lo, hi)
        ids = [r["handoff_id"] for r in scoped]
        tier_counts = {k: 0 for k in TIER_LABELS}
        amount_sum = 0
        for r in scoped:
            qt = r["quote_type"]
            if qt in tier_counts:
                tier_counts[qt] += 1
            amount_sum += r["total_quoted"] or 0
        tiers = {"order": TIER_ORDER, "labels": TIER_LABELS, "counts": tier_counts,
                 "total": len(scoped)}
        amount = {"sum": amount_sum, "n": len(scoped)}

        # ── ④㉯ 인계 시점 가격 재확인 — 라인 단위(위 모듈 docstring "판단한 것 ②") ──
        line_counts = {k: 0 for k in MALL_STATUS_ORDER}
        line_total = 0
        if ids:
            for st, n in conn.execute(text(
                    "SELECT mall_status, COUNT(*) FROM handoff_items"
                    " WHERE handoff_id = ANY(:ids) GROUP BY mall_status"), {"ids": ids}):
                if st in line_counts:
                    line_counts[st] = n
                line_total += n
        # 비율은 여기서 계산해 내려보낸다 — 화면(JS)은 나눗셈을 하지 않는다(계약
        # "배수·비율은 서버가 계산한다. 화면이 나누지 않는다" — 경고 배너뿐 아니라
        # 이 3칸에도 같은 원칙을 적용한다. 2026-08-15 자기 검증 중 발견해 고쳤다:
        # 처음엔 이 라인 비율을 템플릿 JS에서 계산했다).
        line_pcts = {k: {"n": v, "pct": _pct(v, line_total, 1)} for k, v in line_counts.items()}
        price_check = {"lines": {**line_pcts, "total": line_total},
                        "handoff_n": len(scoped)}

        # ── ④㉰ 근거 클릭 · 부품 교체 결합 — 직접 조인해서 센다(지어내지 않는다) ────
        promo_total = conn.execute(text("SELECT COUNT(*) FROM promo_click_logs")).scalar_one()
        swap_total = conn.execute(text("SELECT COUNT(*) FROM swap_event_logs")).scalar_one()
        promo_matched = swap_matched = 0
        if ids:
            promo_matched = conn.execute(text(
                "SELECT COUNT(DISTINCT h.handoff_id) FROM handoffs h"
                " JOIN promo_click_logs c ON c.user_id = h.user_id"
                " WHERE h.handoff_id = ANY(:ids)"), {"ids": ids}).scalar_one()
            swap_matched = conn.execute(text(
                "SELECT COUNT(DISTINCT h.handoff_id) FROM handoffs h"
                " JOIN swap_event_logs e ON e.session_id = h.session_id"
                " WHERE h.handoff_id = ANY(:ids)"), {"ids": ids}).scalar_one()
        signals = {
            "promo_click": {"matched_handoffs": promo_matched, "total_rows": promo_total,
                             "scoped_handoffs": len(scoped)},
            "swap": {"matched_handoffs": swap_matched, "total_rows": swap_total,
                     "scoped_handoffs": len(scoped)},
        }

        # ── 데이터 정합성 — 세션 없는 인계(있으면 이 화면의 기간 집계에서 조용히 빠진다) ──
        orphan_handoffs = conn.execute(text(
            "SELECT COUNT(*) FROM handoffs WHERE session_id IS NULL")).scalar_one()

    return {
        "generated_at": iso(datetime.now(_tz.utc)),
        "feature": {"start_date": iso(feature_start), "source": feature_source,
                    "migration_file": HANDOFF_MIGRATION_FILE},
        "period": {"preset": preset, "from": period_from_label, "to": period_to_label,
                   "label": period_label},
        "history_bounds": {"sessions_min": iso(sessions_min_date),
                           "today": iso(today_kst)},
        "warning": warning,
        "funnel": funnel,
        "tiers": tiers,
        "amount": amount,
        "price_check": price_check,
        "signals": signals,
        "integrity": {"orphan_handoffs": orphan_handoffs},
        "nav": _nav_links(),
    }
