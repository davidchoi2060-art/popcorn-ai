# -*- coding: utf-8 -*-
"""몰 공급처·가격 일일 자동 반영 -- 새벽 systemd timer 가 부른다 (2026-08-27 신설).

사장님이 어제(2026-08-26) 사람 손으로 한 절차를 그대로 자동화한다. 그 절차는 넷이다
(순서대로 실행한다):

  1단계  추천 후보 상품 목록을 뽑는다      -- v_recommendation_candidates
         (tools/mall_supplier_fetch.target_codes -- 새로 짓지 않는다)
  2단계  몰에서 공급처·가격을 읽어 반영한다  -- product_com_list.php?pd_no=, 1.5초 간격
         (tools/mall_supplier_fetch.run -- 새로 짓지 않는다. --apply 로 실제 반영)
  3단계  「가능」 공급처 최저가로 매입가를 갱신하고 판매가를 재계산한다
         (api/admin_price_import._reprice -- 정본 공식을 그대로 부른다. 재구현하지 않는다)
  4단계  전 공급처가 품절인 상품을 추천 후보에서 뺀다
         (A-115 와 같은 판정 SQL -- 이번엔 매일 자동으로 반복하도록 이 파일에 정착시켰다)

어제 3·4단계는 DBA 가 스크래치패드 스크립트(A-115·A-116)로 손으로 했다. 스크래치패드는
세션이 끝나면 사라지므로, 그 로직을 이 정식 도구로 옮겨야 자동화할 수 있다는 것이
이 파일이 새로 생긴 이유다.

■ 안전장치 -- 이 작업의 핵심(지시서 그대로)

  ① 세션 만료 · 0건 수집 감지 -> 즉시 3·4단계를 건너뛰고 실패로 기록한다
     tools/mall_supplier_fetch.py 의 LoginRequired(로그인 리다이렉트 감지)를 그대로
     쓴다. **더해서** "0건 수집"도 실패로 본다(정상적으로 0건일 리 없다) -- 아래
     _abort_reason() 이 네 가지 신호를 본다: 로그인 만료 · 연속 실패로 순환중단
     (tools/mall_supplier_fetch.py 를 이번에 고쳐 circuit_break_abort 플래그를 새로
     받게 했다) · 응답 자체를 하나도 못 받음 · 응답은 받았는데 공급처 행을 하나도
     못 뽑음(몰 페이지 구조가 바뀌었을 가능성). 후보 목록 자체가 비어 있어도 같다.

  ② 큰 변동은 그 건만 보류한다
     매입가가 MALL_SYNC_BIG_SWING_RATIO 배 이상 뛰거나 그 역수 이하로 떨어지면
     그 상품만 반영하지 않고(purchase_price 는 그대로 둔다) 목록으로 알린다.
     나머지는 정상 반영한다 -- 한 건 때문에 전체를 멈추지 않는다.
     한도는 환경변수로 뺐다(기본 2.0 배 -- 아래 BIG_SWING_RATIO_DEFAULT 주석 참조).

  ③ 하루치를 통째로 되돌릴 수 있다
     3·4단계는 각각 admin_operator_activity_logs 에 그날 바뀐 전 건의 before
     스냅샷을 남긴다(A-115·A-116 과 같은 모양 -- action=mall_daily_sync_reprice /
     mall_daily_sync_exclude_no_supplier). log_id 하나로 그날 것 전부를 되돌릴 수
     있다 -- 되돌리는 절차는 deploy/README.md 「몰 공급처·가격 일일 자동 반영」 절.

  ④ 끝나면 반드시 기록한다 -- 성공이든 실패든
     ⚠ 2026-08-27 정정(사장님 확인) -- 처음엔 로컬 작업 현황판(.claude/dash-queue.jsonl,
     api/dash.py)에 남기려 했는데, **그 화면은 하네스의 로컬 세션 전사본을 읽는
     화면이라 배포 서버에서 도는 이 배치의 결과가 거기까지 닿지 않는다.** 그래서
     결과를 DB(mall_sync_runs -- db/migrations/versions/0067)에 남기고,
     **관리자 대시보드**(api/admin_dashboard.mall_sync_status, /admin2/)가 그것을
     읽어 "언제 · 성공/실패 · 건수"를 한 줄로 보여준다. 로그인만 하면 보인다.

■ 이 파일이 실제로 DB 에 쓰는 표
  mall_sync_runs(실행 요약 한 행) · admin_operator_activity_logs(3·4단계 before
  스냅샷 · A-115/A-116과 같은 모양) · product_supplier_prices·suppliers(2단계,
  tools/mall_supplier_fetch.py 소관) · products.purchase_price/sale_price(3단계,
  api/admin_price_import._reprice 소관) · products.ai_candidate_yn/locked_fields(4단계).
  product_price_history 는 _reprice() 가 알아서 남긴다(재구현하지 않는다).

■ 쿠키
  MALL_ADMIN_COOKIE 를 환경에서 읽는다(tools/mall_supplier_fetch.py 가 이미 그렇게
  한다 -- 이 파일은 그 규약을 그대로 따른다). **이 파일은 쿠키 값을 서버에 넣지
  않는다** -- 어디에 어떤 이름으로 넣어야 하는지는 deploy/README.md 에 적었고,
  실제로 넣는 것은 사장님과 하네스가 한다(비밀값을 다루는 것은 제작자 소관이 아니다).

■ 드라이런이 기본이다
  --apply 를 줘야 실제로 DB 에 쓴다(mall_sync_runs 행조차 만들지 않는다 -- 이
  저장소의 "로컬 DB 가 곧 운영 DB" 규약과 같은 이유). 드라이런도 몰에는 실제로
  GET 요청을 보낸다(tools/mall_supplier_fetch.py 의 기존 드라이런 관례 그대로 --
  그래야 "몇 건이 어떻게 바뀔지" 실제로 셀 수 있다).

Usage:
  .venv/Scripts/python tools/mall_daily_sync.py --selftest
  .venv/Scripts/python tools/mall_daily_sync.py                 (드라이런 -- 전체 후보, DB 안 씀)
  .venv/Scripts/python tools/mall_daily_sync.py --limit 20       (드라이런 -- 20건만, 손으로 확인할 때)
  .venv/Scripts/python tools/mall_daily_sync.py --apply          (실제 반영 -- systemd 가 매일 이걸 돌린다)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# ⚠ 여기서 ensure_utf8_console() 을 직접 부르지 않는다(2026-08-27 실측으로 발견) --
# tools/mall_supplier_fetch.py 를 import 하는 순간 그 파일이 **자기 모듈 최상단에서
# 이미 한 번** 부른다. 같은 프로세스에서 두 번 부르면 stdout 이 두 번 재포장되는데,
# 첫 번째 TextIOWrapper 객체가 sys.stdout 재할당으로 참조를 잃고 GC 되면서 자신이
# 물고 있던 «공유» 하위 버퍼까지 닫아버려("ValueError: I/O operation on closed
# file") --selftest 의 첫 print() 에서 그대로 죽었다. 이 파일이 tools/_console.py
# 를 직접 만지지 않고(그 파일은 10개 넘는 다른 도구가 함께 쓰는 공유 파일이라
# 담당 밖이다) 대신 "정확히 한 번만 부르게" 호출 순서로 피한다 -- 아래
# `from tools import mall_supplier_fetch as _msf` 가 대신 불러 준다.
from dotenv import load_dotenv                        # noqa: E402
from sqlalchemy import text                            # noqa: E402

# 새로 짓지 않는다 -- 지시서가 명시한 "이미 있는 것" 셋을 그대로 부른다.
# (참고: 이 import 가 tools/mall_supplier_fetch.py 를 통해 ensure_utf8_console() 을
# 대신 한 번 불러 준다 -- 위 주석 참조. 이 줄의 위치를 옮기지 않는다.)
from tools import mall_supplier_fetch as _msf           # noqa: E402
from api.admin_price_import import _reprice, _settings  # noqa: E402
from api.pricing import sale_from_purchase               # noqa: E402
from api.taxonomy import slot_of                         # noqa: E402
from api.auth import current_operator_id                 # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 설정값 -- 환경변수로 바꿀 수 있다(지시서 "한도 값은 설정으로 빼라") ──────────
BIG_SWING_RATIO_DEFAULT = 2.0
# 왜 2.0 배인가: 2026-08-26 사람이 손으로 반영한 245건 중 최대 상승례가 675,000 ->
# 2,210,000(3.3배, 상품 109253)이었다 -- 그 정도로 큰 변동은 "밤사이 자동으로"
# 조용히 넘어가면 안 된다는 것이 이번 작업의 계기다. 2.0배는 그 사고 사례(3.3배)
# 보다는 낮고, 부품 가격이 정상적으로 오르내리는 폭(대개 수 %~수십 %)보다는
# 넉넉히 높은 값으로 골랐다 -- 정상적인 하루치 가격 변동은 통과시키고, "자릿수가
# 달라진 값"만 사람 확인으로 넘긴다. 사장님이 바꾸실 수 있도록 환경변수로 뺐다.
MALL_SYNC_LIMIT_ENV = "MALL_SYNC_LIMIT"
MALL_SYNC_SWING_ENV = "MALL_SYNC_BIG_SWING_RATIO"


def _big_swing_ratio() -> float:
    v = os.environ.get(MALL_SYNC_SWING_ENV)
    return float(v) if v else BIG_SWING_RATIO_DEFAULT


def _is_big_swing(old_purchase, mall_min, ratio: float) -> bool:
    """매입가 변동이 한도를 넘는가 -- 순수 함수라 --selftest 로 DB 없이 검증한다.

    old_purchase 가 없거나(첫 관측 -- 비교할 과거 값이 없다) 0/음수면 "변동"이라는
    개념 자체가 성립하지 않으므로 보류 대상이 아니다(0으로 나누기도 막는다).
    """
    if not old_purchase or old_purchase <= 0:
        return False
    r = mall_min / old_purchase
    return r >= ratio or r <= 1.0 / ratio


# ==================================================== ① 세션 만료·0건 감지 ==
def _abort_reason(codes: list, stats: dict) -> str | None:
    """3·4단계로 넘어가도 되는지 판정한다. 문제가 있으면 그 사유 한 줄, 없으면 None.

    네 가지를 본다(전부 "정상적으로는 있을 수 없는" 신호다 -- 지어내지 않는다):
      · 후보 목록 자체가 비어 있다(v_recommendation_candidates 조회 이상)
      · 세션이 만료됐다(로그인 리다이렉트 -- tools/mall_supplier_fetch.LoginRequired)
      · 연속 요청 실패로 순환중단됐다(몰 접속이 막혔을 가능성)
      · 요청은 갔는데 응답을 하나도 못 받았거나, 응답은 받았는데 공급처 행을
        하나도 못 뽑았다("0건 수집도 실패다" -- 정상적으로 0건일 리 없다)
    """
    if not codes:
        return ("추천 후보 목록이 비어 있습니다(0건) -- v_recommendation_candidates"
                " 조회 자체를 확인해야 합니다")
    if stats.get("login_abort"):
        return ("몰 세션이 만료되었습니다(로그인 페이지로 redirect 감지) --"
                " MALL_ADMIN_COOKIE 를 다시 넣어야 합니다")
    if stats.get("circuit_break_abort"):
        return (f"연속 요청 실패로 수집이 중단되었습니다(연속 실패 {_msf.MAX_FAIL}회,"
                 f" 누적 실패 {stats.get('fetch_fail')}건) -- 몰 접속이 막혔거나"
                 " 네트워크 문제일 수 있습니다")
    if (stats.get("fetched", 0) + stats.get("cached", 0)) == 0:
        return "몰에서 응답을 하나도 받지 못했습니다(0건 수집)"
    if stats.get("rows_total", 0) == 0:
        return ("응답은 받았지만 공급처 행을 하나도 파싱하지 못했습니다(0건 수집 --"
                " 몰 페이지 구조가 바뀌었을 수 있습니다)")
    return None


# ============================================ mall_sync_runs -- 실행 기록 ==
def _start_run(conn, target_count: int) -> int:
    return conn.execute(text(
        "INSERT INTO mall_sync_runs (target_count) VALUES (:t) RETURNING run_id"),
        {"t": target_count}).scalar()


def _finish_run(conn, run_id: int, ok: bool, fail_reason: str = None,
                collected_count: int = None, price_changed_count: int = None,
                held_count: int = None, excluded_count: int = None,
                reprice_log_id: int = None, exclude_log_id: int = None,
                detail: dict = None) -> None:
    # fail_reason 은 VARCHAR(300)(0067 마이그레이션) -- 슬롯 이름이 여럿 걸리는
    # 드문 경우 문장이 길어질 수 있어 여기서 미리 자른다. 컬럼 폭을 넘겨 DB 예외로
    # 죽으면 "실패를 기록하려다 실패 기록 자체가 실패"하는 최악의 경우가 된다.
    fr = (fail_reason or None)
    if fr and len(fr) > 290:
        fr = fr[:287] + "..."
    conn.execute(text(
        "UPDATE mall_sync_runs SET finished_at=now(), ok=:ok, fail_reason=:fr,"
        " collected_count=:cc, price_changed_count=:pcc, held_count=:hc,"
        " excluded_count=:ec, reprice_log_id=:rl, exclude_log_id=:el,"
        " detail=CAST(:d AS JSONB) WHERE run_id=:rid"),
        {"ok": ok, "fr": fr, "cc": collected_count, "pcc": price_changed_count,
         "hc": held_count, "ec": excluded_count, "rl": reprice_log_id, "el": exclude_log_id,
         "d": json.dumps(detail or {}, ensure_ascii=False), "rid": run_id})


# ================================================ 3단계 -- 매입가 재계산 ==
def _reprice_from_mall(conn, fee: float, margin: float, swing_ratio: float,
                       apply_: bool, run_id) -> tuple:
    """「가능」 공급처 최저가로 매입가를 갱신하고 판매가를 재계산한다.

    ⚠ 2026-08-27 정정(확인자 실측): 처음엔 "A-116 은 방향(내리거나 손해거나)으로
    걸렀지만 이 자동화는 매일 도는 것이니 방향과 무관하게 달라진 전부를 대상으로
    하고 ②안전장치(큰 변동 보류)로 막는다"는 설계였다. 그런데 그날 실제 후보로
    돌려보니 applied 2,433건 중 2,391건(98.3%)이 **매입가는 전혀 안 바뀌는데
    판매가만 바뀌는** 반영이었다(중앙값 +11.6%) -- 원인은 ②안전장치(`_is_big_swing`)
    가 old_purchase 대 mall_min "비율"만 보고, 판매가 델타는 어디서도 비교하지
    않는다는 것이었다. `--big-swing-ratio` 를 아무리 낮춰도(1.01 배까지) 이
    2,391건은 걸리지 않았다 -- 안전장치로 덮을 수 있는 종류의 문제가 아니라
    **대상 선정 자체가 넓어진 것**이었다.

    그래서 대상 선정을 A-116 의 조건 그대로로 되돌렸다(`docs/decisions/decision-log.md`
    A-116 의 SQL 을 그대로 옮김 -- 새로 짓지 않는다): `l.mall_min <>
    p.purchase_price`(몰 값이 실제로 다름) AND (`l.mall_min < p.purchase_price`
    -- 내릴 것 OR `l.mall_min > p.sale_price` -- 팔면 손해). A-116 은 이 조건에
    더해 "방향"으로도 갈라 오를 것 중 아직 손해가 아닌 것(그날 기준 42건)은
    뺐는데, **이 자동화도 그 제외를 그대로 물려받았다** -- 사장님 지시 원문이
    "어제 245건 고를 때 쓴 조건 그대로"였고, 매일 도는 배치가 "오를 것"까지
    전부 따라가면 손해가 아닌데도 매입가·판매가가 매일 흔들릴 수 있다(마진
    공식이 매입가에 단조증가라 판매가도 함께 오른다). "내릴 것"은 항상 반영해
    마진을 놓치지 않고 "손해"는 항상 반영해 원가 밑으로 파는 것을 막되, 손해가
    아닌 오름은 급하지 않으니 다음 실행을 기다려도 된다는 판단이다.
    **다만 이 판단은 확인 재료일 뿐 확정이 아니다** -- "몰 값이 바뀌면 방향
    무관 무조건 따라간다"가 더 맞다면 아래 SQL 의 둘째 AND(방향 조건)만 지우면
    된다.

    반환: (applied, held, locked_skip, reprice_log_id)
      applied  실제(또는 드라이런이면 "반영하면") 매입가·판매가가 바뀌는 상품들
      held     배율 한도를 넘어 보류한 상품들
      locked_skip  매입가가 잠겨 있어(locked_fields) 애초에 건드리지 않은 수
      reprice_log_id  apply_ 이고 applied 가 있으면 활동 로그 log_id, 아니면 None

    ai_candidate_yn=true(현재 후보)인 상품만 본다 -- 이미 후보에서 빠진 상품은
    더 이상 이 자동화가 매일 수집하는 대상도 아니므로(1단계가 candidates 뷰만
    본다) 건드릴 이유가 없다.
    """
    rows = conn.execute(text("""
        WITH live AS (
          SELECT product_code, MIN(cost_price) AS mall_min
          FROM product_supplier_prices
          WHERE supply_state = '가능' AND mall_rank IS NOT NULL
          GROUP BY product_code)
        SELECT p.product_code AS pc, p.purchase_price, p.sale_price, p.locked_fields,
               l.mall_min
        FROM live l JOIN products p USING (product_code)
        WHERE p.ai_candidate_yn = true
          AND p.purchase_price IS NOT NULL
          AND l.mall_min <> p.purchase_price
          AND ( l.mall_min < p.purchase_price          -- 내릴 것
             OR l.mall_min > p.sale_price )             -- 팔면 손해
        ORDER BY p.product_code
    """)).mappings().all()

    applied, held = [], []
    locked_skip = 0
    for r in rows:
        locked = r["locked_fields"] or []
        if "purchase_price" in locked:
            locked_skip += 1
            continue
        old_purchase, mall_min = r["purchase_price"], r["mall_min"]
        if _is_big_swing(old_purchase, mall_min, swing_ratio):
            ratio = (mall_min / old_purchase) if old_purchase else None
            held.append({"product_code": r["pc"], "old_purchase": old_purchase,
                        "mall_min": mall_min,
                        "ratio": round(ratio, 3) if ratio is not None else None})
            continue
        planned_sale = sale_from_purchase(mall_min, fee, margin)
        # purchase_will_change 는 위 SQL 의 `l.mall_min <> p.purchase_price` 로 이미
        # 보장된다(이 행이 나왔다는 것 자체가 매입가가 다르다는 뜻) -- 그래도 계산은
        # 남겨 둔다. 조건이 나중에 또 바뀌어도 아래 멱등 가드가 조용히 계속 맞는
        # 값을 내야 하기 때문이다(가드를 SQL 결과에 기대어 지우면, SQL 이 바뀌는
        # 순간 이 가드도 같이 낡는다 -- 검사가 "그 값 자체"를 다시 재는 것과
        # "이름만 믿는" 것의 차이, CLAUDE.md §회귀 세트).
        purchase_will_change = (mall_min != old_purchase)
        sale_locked = "sale_price" in locked
        sale_will_change = (not sale_locked) and (planned_sale != r["sale_price"])
        if not purchase_will_change and not sale_will_change:
            continue   # 이미 몰 값과 같다 -- 반영할 것이 없다(멱등)
        applied.append({"pc": r["pc"], "purchase": old_purchase, "sale": r["sale_price"],
                        "locked_sale": sale_locked, "mall_min": mall_min,
                        "planned_sale": planned_sale})

    reprice_log_id = None
    if apply_ and applied:
        reprice_log_id = conn.execute(text(
            "INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind,"
            " target_id, detail) VALUES (:op, 'mall_daily_sync_reprice', 'product_bulk',"
            " :tid, CAST(:d AS JSONB)) RETURNING log_id"),
            {"op": current_operator_id(), "tid": f"mall-daily-sync-{run_id}-reprice",
             "d": json.dumps({
                 "before": [{"pc": a["pc"], "purchase": a["purchase"], "sale": a["sale"],
                            "locked_sale": a["locked_sale"]} for a in applied],
                 "swing_ratio": swing_ratio, "held_count": len(held),
             }, ensure_ascii=False)}).scalar()
        for a in applied:
            rp = _reprice(conn, a["pc"], fee, margin, "mall_daily_sync_reprice", reprice_log_id)
            a["purchase_changed"] = rp["purchase_changed"]
            a["sale_changed"] = rp["sale_changed"]
            a["sale_locked_at_apply"] = rp["sale_locked"]

    return applied, held, locked_skip, reprice_log_id


# ========================================= 4단계 -- 전 공급처 품절 제외 ==
def _exclude_no_supplier(conn, apply_: bool, run_id) -> tuple:
    """전 공급처가 품절인 상품을 추천 후보에서 뺀다(A-115 판정 SQL 그대로, 매일
    반복 가능하도록 두 가지를 더했다):
      · ai_candidate_yn=true(아직 후보인 것)만 본다 -- 이미 제외된 상품을 매일
        다시 만지지 않는다(중복 로그·중복 잠금 시도를 피한다)
      · locked_fields 에 ai_candidate_yn 이 이미 걸려 있으면 건드리지 않는다 --
        운영자가 수동으로 다시 후보에 넣었다면 그 판단을 존중한다

    ■ 안전장치 -- 슬롯 0 검사(A-115 가 사람이 손으로 하던 확인을 자동화)
    이 제외를 전부 적용했다고 가정했을 때 견적 슬롯(taxonomy.slot_of -- 공랭·
    수랭 쿨러는 한 슬롯) 어느 하나라도 0이 되면, **이번 제외 전체를 보류**하고
    아무것도 바꾸지 않는다. 하루 사이 몰 데이터가 크게 이상해져도(예: 몰 응답이
    깨져 전체가 "품절"로 잘못 보이는 경우) 견적 자체가 막히는 사고로 번지지
    않게 한다.

    반환: (before_snapshot, guard, exclude_log_id)
      guard = {"blocked": bool, "reason": str|None}
    """
    rows = conn.execute(text("""
        WITH mall_state AS (
          SELECT product_code,
                 COUNT(*) FILTER (WHERE supply_state='가능') AS avail_cnt
          FROM product_supplier_prices
          WHERE mall_rank IS NOT NULL
          GROUP BY product_code)
        SELECT p.product_code AS pc, p.part_type, p.locked_fields
        FROM mall_state m JOIN products p USING (product_code)
        WHERE m.avail_cnt = 0
          AND p.ai_candidate_yn = true
          AND NOT (p.locked_fields @> '["ai_candidate_yn"]'::jsonb)
        ORDER BY p.product_code
    """)).mappings().all()

    if not rows:
        return [], {"blocked": False, "reason": None}, None

    slot_current: dict = {}
    for part_type, n in conn.execute(text(
            "SELECT part_type, COUNT(*) FROM v_recommendation_candidates"
            " GROUP BY part_type")).all():
        s = slot_of(part_type)
        slot_current[s] = slot_current.get(s, 0) + n
    slot_removed: dict = {}
    for r in rows:
        s = slot_of(r["part_type"])
        slot_removed[s] = slot_removed.get(s, 0) + 1
    zeroed = sorted(s for s, n in slot_removed.items() if slot_current.get(s, 0) - n <= 0)
    if zeroed:
        return [], {"blocked": True,
                    "reason": (f"슬롯 {', '.join(zeroed)}이(가) 0이 되어 이번 제외"
                               f"({len(rows)}건)를 전부 보류했습니다 -- 사람이 확인해야"
                               " 합니다(몰 응답이 이상했을 수 있습니다)")}, None

    before = [{"pc": r["pc"], "part_type": r["part_type"],
              "locked_fields": r["locked_fields"], "ai_candidate_yn": True} for r in rows]

    exclude_log_id = None
    if apply_:
        codes = [r["pc"] for r in rows]
        exclude_log_id = conn.execute(text(
            "INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind,"
            " target_id, detail) VALUES (:op, 'mall_daily_sync_exclude_no_supplier',"
            " 'product_bulk', :tid, CAST(:d AS JSONB)) RETURNING log_id"),
            {"op": current_operator_id(), "tid": f"mall-daily-sync-{run_id}-exclude",
             "d": json.dumps({"before": before}, ensure_ascii=False)}).scalar()
        # locked_fields 는 JSONB 배열이다 -- 있으면 그대로, 없으면 원소를 더한다
        # (교체가 아니라 추가, api/admin_reviews.py 가 이미 쓰는 관용구와 같다).
        conn.execute(text(
            "UPDATE products SET ai_candidate_yn=false,"
            " locked_fields = CASE WHEN locked_fields ? 'ai_candidate_yn' THEN locked_fields"
            "   ELSE locked_fields || jsonb_build_array('ai_candidate_yn') END,"
            " updated_at=now() WHERE product_code = ANY(:codes)"),
            {"codes": codes})

    return before, {"blocked": False, "reason": None}, exclude_log_id


# ============================================================ 자기검증 ==
def _selftest() -> bool:
    """DB·네트워크 없이 순수 로직만 검증한다(--apply 를 실행하지 않는다는 지시를
    지키면서도 자체 점검은 한다 -- CANON §4 "측정하고 말한다"). 3·4단계 SQL과
    mall_sync_runs 기록은 실제 DB 대조가 필요하므로 이 테스트로 검증되지
    않는다 -- 드라이런(--apply 없이)으로 확인해야 한다(checker 몫)."""
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  [PASS] " if cond else "  [FAIL] ") + msg)
        ok = ok and cond

    # ① 세션 만료 감지 -- 즉시 중단해야 한다
    check(_abort_reason([1, 2, 3], {"login_abort": True, "circuit_break_abort": False,
                                    "fetched": 5, "cached": 0, "rows_total": 10}) is not None,
         "login_abort=True -> 중단 사유 있음(세션 만료)")

    # ② "0건 수집"도 실패다 -- 세션은 정상으로 보이는데 응답을 하나도 못 받음
    check(_abort_reason([1, 2, 3], {"login_abort": False, "circuit_break_abort": False,
                                    "fetched": 0, "cached": 0, "rows_total": 0}) is not None,
         "fetched+cached=0 -> 중단 사유 있음(0건 수집)")

    # ③ 응답은 받았는데 공급처 행이 0(파서가 깨졌거나 몰 페이지 구조가 바뀌었을 가능성)
    check(_abort_reason([1, 2, 3], {"login_abort": False, "circuit_break_abort": False,
                                    "fetched": 3, "cached": 0, "rows_total": 0}) is not None,
         "rows_total=0 -> 중단 사유 있음(파싱 결과 0건)")

    # ④ 후보 목록 자체가 비어 있음(1단계 조회 이상)
    check(_abort_reason([], {"login_abort": False, "circuit_break_abort": False,
                             "fetched": 0, "cached": 0, "rows_total": 0}) is not None,
         "빈 후보 목록 -> 중단 사유 있음")

    # ⑤ 연속 실패로 순환중단된 경우도 세션 만료와 같은 무게로 막는다
    check(_abort_reason([1, 2, 3], {"login_abort": False, "circuit_break_abort": True,
                                    "fetched": 1, "cached": 0, "rows_total": 8}) is not None,
         "circuit_break_abort=True -> 중단 사유 있음")

    # ⑥ 정상 수집 -- 중단 사유가 없어야 3·4단계로 넘어간다
    check(_abort_reason([1, 2, 3], {"login_abort": False, "circuit_break_abort": False,
                                    "fetched": 3, "cached": 0, "rows_total": 24}) is None,
         "정상 수집(로그인 정상·행 있음) -> 중단 사유 없음")

    # 큰 변동 판정(②안전장치) -- 기본 배율 2.0의 경계값을 정확히 가르는지
    check(_is_big_swing(100000, 200000, 2.0) is True, "정확히 2.0배는 보류(경계 포함)")
    check(_is_big_swing(100000, 199999, 2.0) is False, "2.0배에 살짝 못 미치면 보류 아님")
    check(_is_big_swing(100000, 50000, 2.0) is True, "정확히 1/2.0배도 보류(경계 포함)")
    check(_is_big_swing(100000, 50001, 2.0) is False, "1/2.0배를 살짝 넘으면 보류 아님")
    check(_is_big_swing(None, 50000, 2.0) is False, "기존 매입가가 없으면(첫 관측) 보류 대상 아님")
    check(_is_big_swing(0, 50000, 2.0) is False, "기존 매입가 0이면 보류 판정에서 제외(0나눗셈 방지)")
    check(_is_big_swing(675000, 2210000, 2.0) is True,
         "실사고 재현 -- 109253(675,000 -> 2,210,000, 3.3배)은 기본 배율로 보류돼야 한다")

    print("\n" + ("전체 통과" if ok else "일부 실패") + " -- DB·네트워크 없이 순수 로직만"
         " 검증했다. 1·2단계(대상 조회·몰 수집)와 3·4단계 SQL, mall_sync_runs 기록은"
         " 이 테스트로 검증되지 않는다 -- --apply 없는 드라이런으로 실제 DB 대조까지"
         " 확인해야 한다.")
    return ok


# ================================================================ 실행 ==
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="실제로 DB에 반영한다(mall_sync_runs 기록 포함). 기본은 드라이런")
    ap.add_argument("--limit", type=int, default=None,
                    help=f"추천 후보 대상 상한(기본: 환경변수 {MALL_SYNC_LIMIT_ENV} 또는"
                         " 전체). 평소엔 안 준다 -- 손으로 소수만 확인할 때 쓴다")
    ap.add_argument("--big-swing-ratio", type=float, default=None,
                    help=f"이 배율(기본: 환경변수 {MALL_SYNC_SWING_ENV} 또는"
                         f" {BIG_SWING_RATIO_DEFAULT}) 이상 뛰거나 그 역수 이하로"
                         " 떨어지면 그 상품만 보류한다")
    ap.add_argument("--selftest", action="store_true",
                    help="DB·네트워크 없이 순수 로직(안전장치 판정)만 검증하고 끝낸다")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if _selftest() else 1)

    limit = args.limit
    if limit is None and os.environ.get(MALL_SYNC_LIMIT_ENV):
        limit = int(os.environ[MALL_SYNC_LIMIT_ENV])
    swing_ratio = args.big_swing_ratio or _big_swing_ratio()

    load_dotenv(os.path.join(ROOT, ".env"))
    from sqlalchemy import create_engine
    engine = create_engine(os.environ["DATABASE_URL"])

    run_id = None
    collected = 0
    try:
        # ── 1단계 ────────────────────────────────────────────────────────
        with engine.connect() as conn:
            codes = _msf.target_codes(conn, "", limit)
        print(f"1단계: 추천 후보 {len(codes)}건(v_recommendation_candidates)")

        if args.apply:
            with engine.begin() as conn:
                run_id = _start_run(conn, len(codes))
            print(f"실행 기록 run_id={run_id}(mall_sync_runs, 대시보드가 이 표를 읽는다)")
        else:
            print("드라이런 모드입니다 -- DB에 쓰지 않습니다(몰에는 실제로 GET합니다)."
                 " 실제로 반영하려면 --apply.")

        # ── 2단계 -- 새로 짓지 않는다, tools/mall_supplier_fetch.run 그대로 ──
        # refetch=True: 몰 가격은 매일 바뀌므로 어제 캐시를 재사용하면 안 된다.
        # reapply=True: 어제 이미 "반영 완료"였던 상품도 오늘 다시 갱신해야 한다.
        # 이 둘이 없으면 "자동 반영"이 사실상 "첫날 값 고정"이 된다(이번에 함께
        # 고친 tools/mall_supplier_fetch.fetch()의 refetch 결함 참조).
        print(f"2단계: 몰에서 공급처·가격을 읽습니다(요청 간격 {_msf.DELAY}초,"
             f" 세션 만료 시 즉시 중단)")
        stats, samples = _msf.run(engine, codes, apply_=args.apply, refetch=True,
                                  cache_only=False, reapply=True, file_map=None)
        collected = stats["fetched"] + stats["cached"]
        print(f"2단계 완료: 응답 {collected}건 · 공급처 행 {stats['rows_total']}건 ·"
             f" product_supplier_prices {'반영' if args.apply else '반영 예정'}"
             f" {stats['psp_insert'] + stats['psp_update']}행")

        reason = _abort_reason(codes, stats)
        if reason:
            print(f"\n중단: {reason}")
            if args.apply and run_id is not None:
                with engine.begin() as conn:
                    _finish_run(conn, run_id, ok=False, fail_reason=reason,
                               collected_count=collected)
            print("\n=== 요약 ===")
            print(f"몰 갱신 실패 -- {reason}")
            sys.exit(1)

        # ── 3단계 ────────────────────────────────────────────────────────
        # ⚠ _settings() 는 pricing_settings 의 전역 한 값(fee, margin)만 준다 --
        # api/pricing.resolve_margins() 의 분류별 마진 상속을 거치지 않는다. 지금은
        # category_margin_policies 가 0행이라 두 경로의 결과가 같지만, 나중에
        # 카테고리별 마진이 생기면 **이 자동화만** 그것을 무시하고 전역 마진으로
        # 계산한다. 새로 발견한 문제가 아니다 -- api/admin_price_import._reprice()
        # 가 원래 이렇게 동작해 왔고(_settings 를 그대로 받아 쓴다), 그 함수는
        # 다른 화면 셋이 함께 쓰므로 여기서 고치지 않는다(고치면 그 화면들의
        # 동작까지 바뀐다) -- 사실만 남긴다.
        with engine.connect() as conn:
            fee, margin = _settings(conn)
        if args.apply:
            with engine.begin() as conn:
                applied, held, locked_skip, reprice_log_id = _reprice_from_mall(
                    conn, fee, margin, swing_ratio, True, run_id)
        else:
            with engine.connect() as conn:
                applied, held, locked_skip, reprice_log_id = _reprice_from_mall(
                    conn, fee, margin, swing_ratio, False, run_id)
        print(f"3단계 완료: 매입가·판매가 변경 {len(applied)}건"
             f"({'반영' if args.apply else '반영 예정'}) · 큰 변동으로 보류 {len(held)}건"
             f"(배율 {swing_ratio}) · 매입가 잠금으로 건너뜀 {locked_skip}건")
        if held:
            print("  보류 표본(최대 5):")
            for h in held[:5]:
                print(f"    {h['product_code']}  {h['old_purchase']:,} -> {h['mall_min']:,}"
                     f"  (배율 {h['ratio']})")

        # ── 4단계 ────────────────────────────────────────────────────────
        if args.apply:
            with engine.begin() as conn:
                excluded, guard, exclude_log_id = _exclude_no_supplier(conn, True, run_id)
        else:
            with engine.connect() as conn:
                excluded, guard, exclude_log_id = _exclude_no_supplier(conn, False, run_id)
        if guard["blocked"]:
            print(f"4단계 보류: {guard['reason']}")
        else:
            print(f"4단계 완료: 전 공급처 품절이라 후보에서"
                 f" {'뺀' if args.apply else '뺄 예정인'} 상품 {len(excluded)}건")

        # ── 기록 + 요약 ──────────────────────────────────────────────────
        if args.apply and run_id is not None:
            with engine.begin() as conn:
                _finish_run(conn, run_id, ok=True, collected_count=collected,
                           price_changed_count=len(applied), held_count=len(held),
                           excluded_count=len(excluded), reprice_log_id=reprice_log_id,
                           exclude_log_id=exclude_log_id,
                           detail={"held_samples": held[:10], "guard": guard,
                                  "locked_skip": locked_skip, "swing_ratio": swing_ratio})

        print("\n=== 요약 ===")
        line = (f"몰 갱신 -- 수집 {collected}건 · 가격 {len(applied)}건 변경 ·"
               f" 보류 {len(held)}건 · 후보 제외 {len(excluded)}건")
        if guard["blocked"]:
            line += f" (후보 제외는 보류: {guard['reason']})"
        print(line)
        print("product_supplier_prices·suppliers 는 tools/mall_supplier_fetch.py,"
             " products.purchase_price/sale_price 는 api/admin_price_import._reprice,"
             " products.ai_candidate_yn 은 이 파일이 각각 반영합니다.")

    except Exception as e:                                       # noqa: BLE001
        # DB 예외 상세를 그대로 찍지 않는다(지시서 규약) -- 종류만 남긴다.
        print(f"\n예외로 중단: {type(e).__name__}")
        if args.apply and run_id is not None:
            try:
                with engine.begin() as conn:
                    _finish_run(conn, run_id, ok=False,
                               fail_reason=f"예외로 중단: {type(e).__name__}",
                               collected_count=collected)
            except Exception:                                    # noqa: BLE001
                # 실패 기록조차 못 남기면 mall_sync_runs 행이 시작만 있고 끝이 없는
                # 채로 남는다 -- 대시보드의 "응답 없음(stalled)" 판정이 그것을 잡는다.
                print("실패 기록도 남기지 못했습니다 -- mall_sync_runs 가"
                     " '응답 없음'으로 남을 것입니다(대시보드가 경고로 보여줍니다).")
        raise


if __name__ == "__main__":
    main()
