"""AI 사용량 · 비용(ADM-AI-050) — 읽기 전용 관측 창. `api/main.py`가 자동으로 싣는다
(§discovery). 페이지 라우트는 `admin_ui_ai_usage_cost.py`. 쓰기 액션은 없다(요구사항 ①·⑥).

■ 정본 복제 금지 — `api/admin_system.py`의 `GET /api/admin/system` 안 `ai_cost` 서브가
  이미 "행수 + empty + reason" 판정을 하고 있다(조사자 datamap 실측). 그런데 이 화면이
  필요한 것은 그보다 훨씬 넓다 — 기간·프로바이더·모델 필터, 5종 KPI, 프로바이더/작업
  분해, 게이지, 14일 추이까지 요구사항(req-ai-usage-cost.md ④~⑤)이 명시한다. 그 서브
  응답을 그대로 재사용하는 것은 이 화면 요구를 채우지 못해(불충분) 여기서 SELECT를
  다시 연다 — 다만 **"왜 0인가"의 설명(2026-07-21 LLM 연동 보류 결정)은 그 모듈의
  reason 문구와 같은 사실을 가리키도록 맞췄다**(같은 사실을 두 곳에서 다르게 말하지
  않는다). `api/admin_system.py`는 이 세션에서 고치지 않았다(내 담당 밖).

■ "0" vs "원천 없음" vs "스키마 없음" — 세 값을 절대 섞지 않는다(요구사항 ⑦):
    · `api_cost_logs` 테이블 자체가 0행(`source_exists=False`)이면 모든 금액 KPI는
      "원천 없음"이다 — 0이 아니라 잴 근거 자체가 없다는 뜻.
    · 테이블에 행이 생긴 뒤(`source_exists=True`) 특정 기간·필터에 걸리는 행이 없으면
      그건 진짜 "0"이다(원천은 있고 값이 0).
    · "작업 종류별 분해"는 `api_cost_logs`에 그 컬럼 자체가 없다(실측:
      `db/migrations/versions/0001_initial_schema.py`) — 행이 아무리 쌓여도 계산할 수
      없는 **구조적** 결측이라 "스키마 없음"으로 항상 고정 표기한다(원천 없음과 다른
      말이어야 한다는 요구사항 그대로).
  아래 SQL은 이 세 상태를 실시간으로 다시 재는 것이지 하드코딩이 아니다 —
  `cost_thresholds`(AI 연동 설정에서 owner가 저장하면 즉시 채워진다)와 `api_cost_logs`
  둘 다 이 파일이 쓰지 않고 읽기만 한다.

■ Claude Code 세션 비용 블록은 **고정 라벨**이다(원안 `docs/design/dc-ai-usage-cost.html`
  `CC_ROWS`를 그대로 따름 — 원안도 `tokens`를 실수치가 아니라 "세션 전사본 기준"이라는
  방법론 문구로 렌더한다). `api/dash.py`가 세션 전사본에서 토큰을 이미 세고 있지만
  (`_event`, ADM-AI-010 작업 현황판 전용) 그 함수들은 밑줄 접두어(모듈 내부 전용)이고
  이 화면이 필요로 하는 것과 집계 단위가 다르다(요구사항은 "환산 기준 없음"만 밝히면
  충분 — 요구사항 ⑤ "토큰은 인지하되 금액 환산 기준이 없어 비용은 비운다"). 실시간 토큰
  합산을 새로 배선하지 않은 것은 범위 판단이며 보고서에 남긴다.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .admin_ai_integration import PROVIDERS, PROVIDER_MAP, TASKS
from .db import engine
from .timeutil import KST, iso, kst_day_range, now_iso

router = APIRouter(prefix="/api/admin/ai-usage-cost")

PERIODS = [
    {"key": "today", "label": "오늘", "desc": "오늘"},
    {"key": "d7", "label": "7일", "desc": "최근 7일"},
    {"key": "d30", "label": "30일", "desc": "최근 30일"},
    {"key": "month", "label": "이번 달", "desc": "이번 달"},
]
PERIOD_MAP = {p["key"]: p for p in PERIODS}

MODELS = [p["model"] for p in PROVIDERS]

# CLAUDE.md: "DB 구축 완료(2026-07-23)" — `req-ai-usage-cost.md` ④가 같은 날짜를
# "api_cost_logs 0행"의 관측 시작점으로 인용한다. 계산은 실시간(now() 기준)으로 한다 —
# 오늘 날짜가 바뀌어도 "N주째"가 그날그날 다시 맞게 나오게(하드코딩된 "5주째"를 박지 않는다).
BUILT_AT = date(2026, 7, 23)
DECISION_AT = "2026-07-21"

REASON = (f"실제 LLM 연동이 보류 상태({DECISION_AT} 결정)라 사용량·비용 기록이 없습니다."
          " 착수하면 이 화면이 실값으로 채워집니다(컬럼은 이미 있어 행만 쌓이면 됩니다).")
SCHEMA_REASON = ("이 분해는 데이터가 쌓여도 계산되지 않습니다 — api_cost_logs에 작업 종류"
                  " 컬럼을 먼저 추가해야 합니다(스키마 변경 필요).")

NOSOURCE_STYLE_NOTE = {
    "per_consult": "분모(상담)·분자(비용) 모두 없음",
    "per_batch": "배치는 세션 비용 구역 참조",
}


def _num(v):
    return float(v) if v is not None else None


def _period_bounds(period_key: str):
    if period_key not in PERIOD_MAP:
        raise HTTPException(400, f"알 수 없는 기간입니다: {period_key}")
    today = datetime.now(KST).date()
    if period_key == "today":
        d0 = today
    elif period_key == "d7":
        d0 = today - timedelta(days=6)
    elif period_key == "d30":
        d0 = today - timedelta(days=29)
    else:  # month
        d0 = today.replace(day=1)
    lo, hi = kst_day_range(iso(d0), iso(today))
    return lo, hi, d0, today


def _day_range_bounds(d0: date, d1: date):
    lo, hi = kst_day_range(iso(d0), iso(d1))
    return lo, hi


def _agg(conn, lo, hi, provider=None, model=None) -> dict:
    where = ["created_at >= :lo", "created_at < :hi"]
    params = {"lo": lo, "hi": hi}
    if provider:
        where.append("provider = :prov")
        params["prov"] = provider
    if model:
        where.append("model = :model")
        params["model"] = model
    row = conn.execute(text(
        "SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd),0) AS cost,"
        " COALESCE(SUM(tokens_in),0) + COALESCE(SUM(tokens_out),0) AS tokens"
        " FROM api_cost_logs WHERE " + " AND ".join(where)), params).mappings().first()
    return {"n": row["n"], "cost": float(row["cost"]), "tokens": int(row["tokens"])}


@router.get("/summary")
def summary(period: str = "today", provider: str | None = None, model: str | None = None):
    if provider is not None and provider not in PROVIDER_MAP:
        raise HTTPException(400, f"알 수 없는 프로바이더입니다: {provider}")
    if model is not None and model not in MODELS:
        raise HTTPException(400, f"알 수 없는 모델입니다: {model}")

    lo, hi, d0, d1 = _period_bounds(period)
    period_label = PERIOD_MAP[period]["desc"]

    with engine.connect() as conn:
        total_rows = conn.execute(text("SELECT COUNT(*) FROM api_cost_logs")).scalar_one()
        threshold_rows = conn.execute(text("SELECT COUNT(*) FROM cost_thresholds")).scalar_one()
        source_exists = total_rows > 0

        today_kst = datetime.now(KST).date()
        today_lo, today_hi = _day_range_bounds(today_kst, today_kst)
        month_lo, month_hi = _day_range_bounds(today_kst.replace(day=1), today_kst)
        today_agg = _agg(conn, today_lo, today_hi, provider, model)
        month_agg = _agg(conn, month_lo, month_hi, provider, model)
        # period(lo,hi)로 필터한 합계 자체는 KPI 카드로 노출하지 않는다(①·②는 "오늘"·
        # "이번 달"에 고정된 카드라 위 두 집계로 충분하다) — 대신 아래 분해·추이 SQL이
        # lo/hi를 직접 쓴다.

        # ── 프로바이더별 분해(범위 = 선택한 period·model, provider 필터는 여기선 안 건다
        #    — 필터로 좁혀도 "다른 프로바이더는 0"임을 보여주는 게 분해의 목적이다) ──
        prov_where = ["created_at >= :lo", "created_at < :hi"]
        prov_params = {"lo": lo, "hi": hi}
        if model:
            prov_where.append("model = :model")
            prov_params["model"] = model
        prov_rows = conn.execute(text(
            "SELECT provider, COUNT(*) AS n, COALESCE(SUM(cost_usd),0) AS cost,"
            " COALESCE(SUM(tokens_in),0) + COALESCE(SUM(tokens_out),0) AS tokens"
            " FROM api_cost_logs WHERE " + " AND ".join(prov_where) +
            " GROUP BY provider"), prov_params).mappings().all()
        prov_map = {r["provider"]: r for r in prov_rows}

        # ── 일 한도(게이지 분모) — AI 연동 설정에서 owner가 저장하면 즉시 여기 반영된다 ──
        gauge_provider_keys = [provider] if provider else [p["key"] for p in PROVIDERS]
        thr_rows = conn.execute(text(
            "SELECT key, daily_usd FROM cost_thresholds WHERE key = ANY(:ks)"),
            {"ks": gauge_provider_keys}).mappings().all()
        limit_vals = [float(r["daily_usd"]) for r in thr_rows if r["daily_usd"] is not None]
        limit_total = sum(limit_vals) if limit_vals else None

        # ── 추이(일별, 선택 기간 전체) ──
        trend_where = ["created_at >= :lo", "created_at < :hi"]
        trend_params = {"lo": lo, "hi": hi}
        if provider:
            trend_where.append("provider = :prov")
            trend_params["prov"] = provider
        if model:
            trend_where.append("model = :model")
            trend_params["model"] = model
        trend_rows = conn.execute(text(
            "SELECT (created_at + interval '9 hour')::date AS d, COALESCE(SUM(cost_usd),0) AS cost"
            " FROM api_cost_logs WHERE " + " AND ".join(trend_where) +
            " GROUP BY 1 ORDER BY 1"), trend_params).mappings().all()

    # ── KPI 5종 ── note는 항상 실측 total_rows로 만든다(source_exists==False일 때도
    # total_rows는 곧 0이므로 문구가 저절로 "api_cost_logs 0행"이 된다 — 별도 리터럴을
    # 두면 코드의 조건과 문구가 따로 놀 수 있다).
    def money_kpi(key, label, agg):
        if source_exists:
            return {"key": key, "label": label, "kind": "value", "unit": "USD",
                    "value": round(agg["cost"], 2), "note": f"api_cost_logs {total_rows}행"}
        return {"key": key, "label": label, "kind": "nosource", "unit": "USD",
                "value": "원천 없음", "note": f"api_cost_logs {total_rows}행"}

    kpis = [
        money_kpi("today_cost", "오늘 사용액", today_agg),
        money_kpi("month_cost", "이번 달 누계", month_agg),
        {"key": "per_consult", "label": "상담 1건당 평균", "kind": "nosource", "unit": "USD",
         "value": "원천 없음", "note": NOSOURCE_STYLE_NOTE["per_consult"]},
        {"key": "per_batch", "label": "배치당 평균", "kind": "nosource", "unit": "USD",
         "value": "원천 없음", "note": NOSOURCE_STYLE_NOTE["per_batch"]},
        {"key": "by_task", "label": "작업 종류별 분해", "kind": "noschema", "unit": "",
         "value": "스키마 없음", "note": "api_cost_logs에 작업 종류 컬럼 없음"},
    ]

    # ── 게이지 ──
    if limit_total is None and not source_exists:
        gauge = {"available": False, "limit_usd": None, "used_usd": None,
                 "note": "한도도 사용액도 원천이 없습니다 — 게이지를 그릴 근거가 없습니다"}
    elif limit_total is None:
        gauge = {"available": False, "limit_usd": None, "used_usd": round(today_agg["cost"], 2),
                 "note": "일 한도가 아직 설정되지 않았습니다 — AI 연동 설정에서 정하면 채워집니다"}
    elif not source_exists:
        gauge = {"available": False, "limit_usd": round(limit_total, 2), "used_usd": None,
                 "note": f"일 한도는 설정돼 있으나(${limit_total:g}/일) 오늘 사용액 원천이 아직 없습니다"}
    else:
        used = round(today_agg["cost"], 2)
        pct = round(used / limit_total * 100, 1) if limit_total else None
        gauge = {"available": True, "limit_usd": round(limit_total, 2), "used_usd": used,
                 "pct": pct, "note": f"오늘 ${used:g} / 한도 ${limit_total:g} ({pct}%)"}

    # ── 프로바이더별 분해 ──
    prov_breakdown_rows = []
    for p in PROVIDERS:
        r = prov_map.get(p["key"])
        prov_breakdown_rows.append({
            "key": p["key"], "name": p["vendor"], "sub": p["company"],
            "tokens": int(r["tokens"]) if (r and source_exists) else None,
            "cost": round(float(r["cost"]), 2) if (r and source_exists) else None,
        })
    leftover = set(prov_map) - set(PROVIDER_MAP)
    for extra in sorted(leftover):
        r = prov_map[extra]
        prov_breakdown_rows.append({"key": extra, "name": extra, "sub": "카탈로그에 없는 프로바이더",
                                     "tokens": int(r["tokens"]), "cost": round(float(r["cost"]), 2)})

    breakdowns = {
        "provider": {"available": source_exists, "source": "api_cost_logs.provider",
                      "reason": None if source_exists else REASON, "rows": prov_breakdown_rows},
        "task": {"available": False, "schema_missing": True, "source": "컬럼 없음",
                  "reason": SCHEMA_REASON,
                  # 원안(dc-ai-usage-cost.html TASKS)은 작업 키 자체를 행 아래 보조
                  # 라벨로 함께 보여준다 — 프로바이더 분해의 "company" 보조 라벨과 같은 자리.
                  "rows": [{"key": t["key"], "name": t["label"], "sub": t["key"],
                            "tokens": None, "cost": None} for t in TASKS]},
    }

    # ── 추이 ──
    trend_map = {r["d"]: float(r["cost"]) for r in trend_rows}
    days = []
    d = d0
    while d <= d1:
        days.append(d)
        d += timedelta(days=1)
    trend_points = [{"date": iso(dd),
                      "cost": (round(trend_map.get(dd, 0.0), 2) if source_exists else None)}
                     for dd in days]

    weeks_since_build = (today_kst - BUILT_AT).days // 7

    return {
        "generated_at": now_iso(),
        "period": period, "period_label": period_label,
        "provider": provider, "model": model,
        "periods": PERIODS,
        "filters": {"providers": [{"key": p["key"], "label": p["vendor"]} for p in PROVIDERS],
                    "models": [{"key": p["model"], "label": p["vendor"] + " · " + p["model"]}
                               for p in PROVIDERS]},
        "scope_note": f"이 화면은 우리 서버가 프로바이더에 직접 호출한 비용만 셉니다 · 범위 {period_label}",
        "source": {
            "api_cost_logs_rows": total_rows, "cost_thresholds_rows": threshold_rows,
            "built_at": iso(BUILT_AT), "decision_at": DECISION_AT,
            "weeks_since_build": weeks_since_build,
            "reason": REASON,
        },
        "kpis": kpis,
        "gauge": gauge,
        "trend": {"available": source_exists, "days": len(days), "period_label": period_label,
                   "points": trend_points,
                   "note": (None if source_exists
                             else "그릴 점이 없습니다 — 0이 아니라 기록 자체가 없습니다")},
        "breakdowns": breakdowns,
        "claude_code_session": {
            "rows": [
                {"name": "웹 사양 채움 배치(specfiller)", "tokens_label": "세션 전사본 기준",
                 "cost_label": "환산 기준 없음"},
                {"name": "개발 세션(maker·checker 등)", "tokens_label": "세션 전사본 기준",
                 "cost_label": "환산 기준 없음"},
                {"name": "합계", "tokens_label": "세션 전사본 기준", "cost_label": "환산 기준 없음"},
            ],
            "note": ("specfiller 같은 배치는 Claude Code 세션 안에서 돕니다 — 우리 서버가 프로바이더에"
                      " 직접 호출한 것이 아니므로 api_cost_logs에 잡히지 않습니다."
                      " 위 지표와 절대 합산하지 않습니다."),
            "note2": ("원천은 세션 전사본(작업 현황판 ADM-AI-010과 같은 원천)입니다 — 토큰은 셀 수"
                       " 있지만 금액 환산 기준이 없어 비용은 비워 둡니다."),
        },
        "legend": [
            {"chip": "0", "desc": "원천은 있는데 값이 0 — 실제로 아무도 쓰지 않았다는 뜻입니다."
                                    " 지금은 이 상태가 아닙니다." if not source_exists else
                                    "원천은 있는데 값이 0 — 실제로 아무도 쓰지 않았다는 뜻입니다."},
            {"chip": "원천 없음", "desc": "쌓이는 경로 자체가 없어 셀 대상이 없습니다."
                                          " 오늘 이 화면 전 구간이 이 상태입니다(LLM 연동 보류)."
                                          if not source_exists else
                                          "쌓이는 경로 자체가 없어 셀 대상이 없습니다."},
            {"chip": "스키마 없음", "desc": "데이터가 쌓여도 계산되지 않습니다 — 컬럼을 먼저"
                                            " 추가해야 합니다(작업 종류별 분해)."},
        ],
    }
