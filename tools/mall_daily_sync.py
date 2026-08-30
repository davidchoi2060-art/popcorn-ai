# -*- coding: utf-8 -*-
"""몰 공급처·가격 갱신 -- 손으로 돌린다 (2026-08-27 자동 실행용으로 신설,
2026-08-29 decision-log A-124로 손으로 돌리는 것으로 확정).

⚠ **새벽 systemd timer 가 부르지 않는다.** 2026-08-27 작성 당시에는 그것이
목적이었지만(deploy/systemd/popcorn-mall-sync.timer 가 그 산출물이다), 그 무인
새벽 실행이 매번 유효한 쿠키를 요구하는 것과 부딪혀(§쿠키 참조) A-124가 자동
스케줄을 켜지 않기로 정했다. 이 파일의 로직·안전장치는 그대로 유효하다 --
바뀐 것은 "누가 언제 --apply 로 돌리는가"뿐이다(지금은 사람이 필요할 때 손으로).

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
         ⚠ 2026-08-30 개정 -- "공급처가 «전혀» 없는 상품"(product_supplier_prices 행이
         0개)은 "확인해 보니 전부 품절"과 **다르게** 본다(근거·경위는 아래 4단계
         함수 docstring). 전 공급처 품절(19)·재가격(101) 같은 기존 판정은 이 개정으로
         바뀌지 않는다 -- `_mall_state_verdict` 참조.

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
  한다 -- 이 파일은 그 규약을 그대로 따른다). **이 파일은 쿠키 값을 어디에도
  저장하지 않는다** -- A-124(2026-08-29) 이후에는 서버 설정 파일(`/etc/popcorn-ai.env`)
  에도 넣지 않는다. 사장님이 로그인해 둔 브라우저에서 값을 확인해 하네스에게
  전달하면, 하네스가 그 값을 **이 실행 프로세스 하나에만 유효한 환경변수**로
  넘겨 돌린다(비밀값을 다루는 것은 제작자 소관이 아니다). 절차는
  deploy/README.md 「몰 공급처·가격 갱신」 §쿠키를 얻는 법.

■ 드라이런이 기본이다
  --apply 를 줘야 실제로 DB 에 쓴다(mall_sync_runs 행조차 만들지 않는다 -- 이
  저장소의 "로컬 DB 가 곧 운영 DB" 규약과 같은 이유). 드라이런도 몰에는 실제로
  GET 요청을 보낸다(tools/mall_supplier_fetch.py 의 기존 드라이런 관례 그대로 --
  그래야 "몇 건이 어떻게 바뀔지" 실제로 셀 수 있다).

Usage:
  .venv/Scripts/python tools/mall_daily_sync.py --selftest
  .venv/Scripts/python tools/mall_daily_sync.py                 (드라이런 -- 전체 후보, DB 안 씀)
  .venv/Scripts/python tools/mall_daily_sync.py --limit 20       (드라이런 -- 20건만, 손으로 확인할 때)
  .venv/Scripts/python tools/mall_daily_sync.py --apply          (실제 반영 -- 필요할 때 사람이 손으로 돌린다. 자동 스케줄 없음, decision-log A-124)
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

    ⚠ 2026-08-31 수정(잠복 지뢰 -- 이번 diff 밖의 기존 코드였다) -- "0건 수집" 판정이
    stats['fetched']+stats['cached']만 봤다. 이 둘은 ②네트워크 경로에서만 올라가고,
    ①파일 경로(--from-dir, tools/mall_supplier_fetch.py 모듈 docstring이 정식 경로로
    문서화한 그 경로)로 들어오면 대신 stats['from_file']이 올라간다. 이 파일은 지금
    run()을 항상 file_map=None(②경로)으로만 부르므로 stats['from_file']은 언제나
    0이다 -- **그래서 이 수정은 지금 실행 결과를 하나도 안 바꾼다**(from_file이 0이면
    더해도 합은 그대로다). 다만 언젠가 이 파일에 --from-dir 전달을 추가하면, 파일로
    수백 건을 실제로 읽고도 "0건 수집"으로 오판해 3·4단계를 매번 건너뛰는 잠복
    결함이었다. 판정을 느슨하게 만들지 않도록(지시서 경고 그대로) 이 신호 하나만
    더했다 -- 나머지 세 신호(로그인 만료·순환중단·0행 파싱)는 그대로다.
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
    if (stats.get("fetched", 0) + stats.get("cached", 0)
            + stats.get("from_file", 0)) == 0:
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
def _mall_state_verdict(total_rows: int, avail_cnt: int) -> str:
    """product_supplier_prices 집계 하나(어떤 상품의 «전체 행수»·«판매중 행수»)를
    판정 셋 중 하나로 바꾼다 -- 순수 함수라 --selftest 로 DB 없이 검증한다.

    2026-08-30 신설(지시서 대응 -- 47건 사고: 추천 후보 2,707건 중 47건이
    product_supplier_prices 에 행이 0개였는데, 옛 SQL은 product_supplier_prices
    를 먼저 GROUP BY 했다(사실상 INNER JOIN) -- 행이 0개인 상품은 GROUP BY 결과
    자체에 없어 "전 공급처 품절"인지조차 검사받지 못하고 안전장치를 완전히
    빠져나갔다).

        total_rows == 0    이 상품은 공급처 데이터를 «전혀» 확보하지 못했다
                            -> "unresolved". **"exclude"(전 공급처 품절)와 다르게
                            본다** -- 제외하지 않고 보고만 한다.
                            근거(2026-08-30 실측, 캐시 파일 47건 전수 재파싱):
                            이 47건 중 41건(87%)은 실제로는 몰에 판매중 공급처가
                            «있었다» -- 다만 그 행의 회사명 칸이 "재고있음"
                            같은 재고상태값으로 오염됐거나(43건, api/
                            mall_supplier_parse.STOCK_STATUS_TOKENS) 아직
                            suppliers 에 없는 업체("RSystem", 3건)라 매칭에
                            실패해 product_supplier_prices 에 아예 못 썼을
                            뿐이다(supplier_id NOT NULL FK -- 가짜 업체를 만들어
                            끼워 넣지 않는다). "행이 0개"를 "전부 품절"과 같이
                            보면 이 41건을 실제로는 살 수 있는데 "품절"로
                            단정해 추천 후보에서 빼는 꼴이 된다 -- A-115 가
                            mall_rank IS NULL 행(재고 상태를 확인 못 한 행)을
                            "확인된 품절" 판정에서 제외한 것과 같은 원칙이다
                            ("모르는 상태를 품절로 단정하지 않는다",
                            decision-log A-115 §mall_rank IS NOT NULL 이 왜
                            필요한가). 나머지 6건(118516·126048·127030·
                            128642·128654·128911)은 몰 응답 자체에 판매중
                            공급처가 없었지만, 그 이유가 "회사명이 안 읽혀서"인지
                            "정말 다 품절이라서"인지 이 표(product_supplier_
                            prices)만으로는 구분할 수 없다 -- 그래서 total_rows
                            == 0 은 이유를 따지지 않고 전부 "unresolved"로 묶는다
                            (이유를 나누려면 raw HTML 을 다시 봐야 하는데, 이
                            SQL 은 DB 만 본다).
        total_rows > 0
          avail_cnt == 0    확보한 공급처 «전부»가 품절/단종 -- 실제로 확인된
                            사실이다. "exclude"(A-115 그대로, 기존 판정과 동일 --
                            이 개정으로 바뀌지 않는다).
          avail_cnt > 0     판매중 공급처가 있다 -- "ok"(그대로 둔다).
    """
    if total_rows == 0:
        return "unresolved"
    if avail_cnt == 0:
        return "exclude"
    return "ok"


def _exclude_no_supplier(conn, apply_: bool, run_id, target_codes: list) -> tuple:
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

    ■ 2026-08-30 개정 -- LEFT JOIN 으로 "행 0개" 상품도 판정 대상에 넣는다
    옛 SQL은 product_supplier_prices 를 먼저 GROUP BY 했다(사실상 INNER JOIN) --
    그 표에 행이 «하나도» 없는 상품은 GROUP BY 결과 자체가 없어 이 함수가
    존재조차 몰랐다. products 에서 product_supplier_prices 로 LEFT JOIN 하고
    total_rows(전체 행수)를 함께 세어 `_mall_state_verdict` 로 "exclude"(행은
    있는데 전부 품절 -- 기존과 동일 판정)와 "unresolved"(행 자체가 0개 -- 새
    판정, 제외하지 않는다)를 가른다.

    ⚠ **exclude 판정의 모집단은 이번 실행 대상(target_codes)으로 좁히지 않는다**
    -- products 테이블 전체(ai_candidate_yn=true)를 그대로 쓴다(기존과 같은
    모집단). 2026-08-30 실측으로 신·구 SQL 의 avail_cnt 가 product_supplier_
    prices 에 행이 있는 상품 2,911건 «전원»에서 한 건도 안 어긋남을 확인했다 --
    옛 판정(어제 실행 기준 제외 19건·재가격 101건)을 그대로 보존한다는 뜻이다.
    **unresolved 보고만** target_codes(이번 실행이 실제로 시도한 상품 -- 보통
    v_recommendation_candidates 전체)로 좁힌다 -- 안 좁히면 "이번에 시도조차
    안 한, 그냥 아직 한 번도 몰에서 못 가져온" 상품까지 전부 섞여(2026-08-30
    실측 6,741건) 정작 봐야 할 신호(47건)가 묻힌다.

    반환: (before_snapshot, guard, exclude_log_id, unresolved)
      guard = {"blocked": bool, "reason": str|None}
      unresolved = 공급처 데이터가 «전혀» 없어(product_supplier_prices 행 0개)
                   판정하지 못한 product_code 목록 -- **제외하지 않았다**(사람이
                   확인해야 한다 -- 이유는 위 `_mall_state_verdict` docstring).
    """
    rows = conn.execute(text("""
        WITH mall_state AS (
          SELECT p.product_code,
                 COUNT(psp.psp_id) AS total_rows,
                 COUNT(*) FILTER (WHERE psp.supply_state = '가능') AS avail_cnt
          FROM products p
          LEFT JOIN product_supplier_prices psp
            ON psp.product_code = p.product_code AND psp.mall_rank IS NOT NULL
          WHERE p.ai_candidate_yn = true
          GROUP BY p.product_code)
        SELECT m.product_code AS pc, p.part_type, p.locked_fields,
               m.total_rows, m.avail_cnt
        FROM mall_state m JOIN products p USING (product_code)
        ORDER BY m.product_code
    """)).mappings().all()

    target_set = set(target_codes or [])
    unresolved = [r["pc"] for r in rows
                  if _mall_state_verdict(r["total_rows"], r["avail_cnt"]) == "unresolved"
                  and r["pc"] in target_set]
    rows = [r for r in rows
            if _mall_state_verdict(r["total_rows"], r["avail_cnt"]) == "exclude"
            and not (r["locked_fields"] and "ai_candidate_yn" in r["locked_fields"])]

    if not rows:
        return [], {"blocked": False, "reason": None}, None, unresolved

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
                               " 합니다(몰 응답이 이상했을 수 있습니다)")}, None, unresolved

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

    return before, {"blocked": False, "reason": None}, exclude_log_id, unresolved


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

    # ⑦ 2026-08-31 수정 -- ①파일 경로(--from-dir)로 실제 수집했으면(fetched·cached는
    # 0이어도) "0건 수집"으로 오판하지 않는다. 이 파일은 지금 이 경로를 안 쓰지만
    # (run()을 항상 file_map=None으로 부른다), 언젠가 --from-dir를 연결하면 실제로
    # 터질 잠복 지뢰였다 -- _abort_reason() docstring 참조.
    check(_abort_reason([1, 2, 3], {"login_abort": False, "circuit_break_abort": False,
                                    "fetched": 0, "cached": 0, "rows_total": 12,
                                    "from_file": 3}) is None,
         "from_file>0(파일 경로로 실제 수집) -> fetched+cached=0이어도 중단 사유 없음"
         "(수정 전에는 이 경우도 '0건 수집'으로 오판해 중단시켰다)")

    # 큰 변동 판정(②안전장치) -- 기본 배율 2.0의 경계값을 정확히 가르는지
    check(_is_big_swing(100000, 200000, 2.0) is True, "정확히 2.0배는 보류(경계 포함)")
    check(_is_big_swing(100000, 199999, 2.0) is False, "2.0배에 살짝 못 미치면 보류 아님")
    check(_is_big_swing(100000, 50000, 2.0) is True, "정확히 1/2.0배도 보류(경계 포함)")
    check(_is_big_swing(100000, 50001, 2.0) is False, "1/2.0배를 살짝 넘으면 보류 아님")
    check(_is_big_swing(None, 50000, 2.0) is False, "기존 매입가가 없으면(첫 관측) 보류 대상 아님")
    check(_is_big_swing(0, 50000, 2.0) is False, "기존 매입가 0이면 보류 판정에서 제외(0나눗셈 방지)")
    check(_is_big_swing(675000, 2210000, 2.0) is True,
         "실사고 재현 -- 109253(675,000 -> 2,210,000, 3.3배)은 기본 배율로 보류돼야 한다")

    # 4단계 판정(2026-08-30 신설) -- "행 0개"와 "전 공급처 품절"을 가르는 순수 함수
    check(_mall_state_verdict(0, 0) == "unresolved",
         "공급처 데이터 0행 -> unresolved(전 공급처 품절과 다르게 본다, 제외 대상 아님)")
    check(_mall_state_verdict(3, 0) == "exclude",
         "공급처 3행을 확보했는데 전부 품절/단종 -> exclude(A-115와 동일 판정)")
    check(_mall_state_verdict(3, 2) == "ok", "공급처 3행 중 2행 판매중 -> ok(그대로 둔다)")
    check(_mall_state_verdict(1, 1) == "ok", "공급처 1행, 판매중 -> ok")
    # avail_cnt는 total_rows==0일 때 항상 0(LEFT JOIN의 COUNT가 그렇게 만든다) -- 그래도
    # "0행"이 먼저 걸려 unresolved로 가지 exclude로 잘못 새지 않는지 확인한다.
    check(_mall_state_verdict(0, 0) != "exclude",
         "행 0개는 avail_cnt도 0이지만 exclude로 새지 않는다(순서: total_rows 먼저 본다)")

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
        # 2026-08-31 개정(확인자 지적 ②) -- "판정 불가"를 products_supplier_unresolved
        # 하나만 세면 아래 4단계 unresolved(48건 -- product_supplier_prices 행 자체가
        # 0개인 상품, products_no_rows_parsed 1건까지 포함한 수)와 합계가 안 맞았다
        # (43+3+1=47 vs 48, 차이 1은 no_rows_parsed였는데 이 화면 어디에도 없었다).
        # 「행이 있는데 회사명을 못 읽음」(unresolved)과 「행 자체가 0개」
        # (no_rows_parsed)는 원인이 다르므로 한 숫자로 뭉개지 않고 이유 사전에 별도
        # 키로 나란히 둔다 -- 합계는 48로 맞으면서 어느 쪽이 몇 건인지는 구분된다.
        total_unresolved = (stats.get("products_supplier_unresolved", 0)
                            + stats.get("products_no_rows_parsed", 0))
        if total_unresolved:
            # tools/mall_supplier_fetch.run()이 이미 계산해 돌려주는 값을 여기서
            # 처음 «찍는다» -- 예전엔 이 값을 받기만 하고(위 stats 변수) 아무도 안
            # 읽어, 아래 4단계 "2단계 보고가 원인을 말해줍니다"라는 문구가 가리키는
            # 대상이 콘솔에 없었다(2026-08-30 확인자 지적). 새로 계산하지 않는다 --
            # tools/mall_supplier_fetch.py가 이미 채운 reason·samples를 그대로 쓴다.
            reasons = dict(stats.get("products_supplier_unresolved_reason", {}))
            if stats.get("products_no_rows_parsed"):
                reasons["no_rows_parsed"] = stats["products_no_rows_parsed"]
            breakdown = " · ".join(f"{k}={v}" for k, v in
                                   sorted(reasons.items(), key=lambda kv: -kv[1]))
            print(f"  판정 불가(상품 단위) {total_unresolved}건({breakdown}) -- 가격·"
                 "재고상태는 파싱됐지만 공급처를 특정하지 못해 product_supplier_prices"
                 "에 못 쓴 상품입니다(회사명이 재고상태값으로 오염됐거나 suppliers에"
                 " 없는 업체입니다 -- no_rows_parsed는 다른 원인입니다: 응답에 공급처"
                 " 행 자체가 없었습니다). 표본:")
            combined = (list(stats.get("products_supplier_unresolved_samples", []))
                       + [{"pd_no": pc, "reason": "no_rows_parsed", "names": []}
                          for pc in stats.get("products_no_rows_parsed_samples", [])])
            shown_c = combined[:5]
            for s in shown_c:
                print(f"    pd_no={s['pd_no']} 이유={s['reason']} 회사명원문={s['names']}")
            if len(combined) > len(shown_c):
                print(f"    (표본 {len(shown_c)}/{len(combined)}건 표시 -- 나머지"
                     f" {len(combined) - len(shown_c)}건도 위 건수·이유별 집계에는"
                     " 포함돼 있고, mall_sync_runs.detail에 전건이 남습니다)")

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
                excluded, guard, exclude_log_id, unresolved = _exclude_no_supplier(
                    conn, True, run_id, codes)
        else:
            with engine.connect() as conn:
                excluded, guard, exclude_log_id, unresolved = _exclude_no_supplier(
                    conn, False, run_id, codes)
        if guard["blocked"]:
            print(f"4단계 보류: {guard['reason']}")
        else:
            print(f"4단계 완료: 전 공급처 품절이라 후보에서"
                 f" {'뺀' if args.apply else '뺄 예정인'} 상품 {len(excluded)}건")
        if unresolved:
            # 2026-08-30 확인자 지적 -- 예전엔 "2단계 보고가 원인을 말해줍니다"라고
            # 적어놓고 그 2단계 보고 자체가 아무것도 안 찍었다(자기 참조 오류). 지금은
            # 위에서 실제로 찍었고, 그걸 다시 부르지 않고 pd_no로 «교차 대조»해
            # 이 unresolved 목록(DB의 product_supplier_prices 행 0개 판정, 아래
            # _exclude_no_supplier 소관)과 stats(이번 실행의 몰 응답 파싱 결과, 위
            # _msf.run 소관)를 code 단위로 직접 연결한다.
            # ⚠ 2026-08-31 정정(확인자 지적 ④) -- 바로 아래 문구가 예전엔 "위 2단계와
            # 같은 원인입니다"라고 «단정»했다. 실제로는 원천이 다르다: unresolved(이
            # 목록, 48건)는 DB의 product_supplier_prices 현재 상태(직전 --apply 실행이
            # 남긴 것)를 세고, 2단계 판정 불가(47+1건)는 «이번» 실행이 몰에서 방금
            # 새로 읽은 응답을 센다 -- 드라이런은 아무것도 쓰지 않으므로 이 둘은 서로
            # 다른 시점(직전 반영 시점 vs 지금 파싱 시점)을 가리킬 수 있다. 그래서
            # "같은 원인"이라 말하지 않고 "이번 실행에서 실제로 찾은 것만" 보여준다고
            # 고쳐 말한다 -- 아래 missing 안내가 뜨면 그 차이가 실제로 있었다는 뜻이다.
            reason_by_pc = {s["pd_no"]: s for s in
                            stats.get("products_supplier_unresolved_samples", [])}
            for pc in stats.get("products_no_rows_parsed_samples", []):
                reason_by_pc.setdefault(pc, {"pd_no": pc, "reason": "no_rows_parsed",
                                             "names": []})
            print(f"  참고 -- 공급처 데이터를 «전혀» 확보하지 못해 판정하지 않은 상품"
                 f" {len(unresolved)}건(전 공급처 품절과 다르게 봅니다 -- 제외하지"
                 " 않았습니다). 이 목록은 DB(product_supplier_prices)를 기준으로 세고"
                 " 위 2단계 판정 불가는 이번 실행이 몰에서 새로 읽은 응답을 기준으로"
                 " 셉니다 -- 원인이 같은 경우가 많지만 항상 같다는 보장은 없습니다."
                 " 아래는 이번 실행에서 실제로 이유를 찾은 표본입니다:")
            shown, missing = 0, 0
            for pc in unresolved:
                s = reason_by_pc.get(pc)
                if not s:
                    missing += 1
                    continue
                if shown < 5:
                    print(f"    pd_no={pc} 이유={s['reason']} 회사명원문={s['names']}")
                shown += 1
            if shown == 0:
                print("    (이번 실행에서 이유를 되짚을 수 있는 표본이 없습니다 --"
                     " 아래 번호로 개별 확인이 필요합니다)")
            elif shown > 5:
                print(f"    (표본 5/{shown}건 표시 -- 나머지 {shown - 5}건도 이유는"
                     " mall_sync_runs.detail.no_supplier_data_reason_samples에 전건"
                     " 남습니다)")
            if missing:
                print(f"    ({missing}건은 이번 실행에서 이유를 못 찾았습니다 -- DB"
                     " 상태와 이번 파싱 시점 사이에 몰 데이터가 바뀌었을 수 있습니다)")
            _id_cap = 500
            ids_shown = unresolved[:_id_cap]
            id_tail = (f" ... (전체 {len(unresolved)}건 중 {_id_cap}건 표시)"
                      if len(unresolved) > _id_cap else "")
            print(f"    전체 번호({len(unresolved)}건): {ids_shown}{id_tail}")

        # ── 기록 + 요약 ──────────────────────────────────────────────────
        # detail은 --apply 여부와 무관하게 항상 만든다(지시서 요구: "mall_sync_runs.
        # detail에 이유 분해를 함께 남긴다" -- 나중에 되짚을 수 있게). 드라이런에서는
        # DB에 쓰지 않고 콘솔에만 찍는다 -- "들어갈 값을 드라이런으로 확인"하는 것을
        # --apply 없이 매번 할 수 있게 한다(아래 else 분기).
        # 2026-08-31 개정(확인자 지적 ①②) -- detail은 "나중에 되짚는 용도"라 콘솔
        # 표본(5건)과 다르게 «길어도 된다»(지시서 그대로). 그런데 예전엔 여기도
        # products_supplier_unresolved_samples(당시 최대 20건 캡)와 unresolved 집합의
        # 교집합만 담아서, 48건 중 최대 20건만 이유가 남고(순서상 실제로는 그보다도
        # 적을 수 있다) 나머지는 detail에도 없었다. 지금은 두 원인 버킷(unresolved --
        # 회사명 인식 실패, no_rows_parsed -- 응답에 행 자체가 없음)을 합쳐 이유
        # 사전에 넣고(합계가 no_supplier_data_count와 맞아야 한다), 표본도 캡 없이
        # 이번 실행이 실제로 찾은 전건을 담는다.
        reason_counts = dict(stats.get("products_supplier_unresolved_reason", {}))
        if stats.get("products_no_rows_parsed"):
            reason_counts["no_rows_parsed"] = stats["products_no_rows_parsed"]
        reason_samples_all = (list(stats.get("products_supplier_unresolved_samples", []))
                              + [{"pd_no": pc, "rows": 0, "reason": "no_rows_parsed",
                                 "names": []}
                                 for pc in stats.get("products_no_rows_parsed_samples", [])])
        reason_by_pc_all = {s["pd_no"]: s for s in reason_samples_all}
        matched_reason_samples = [reason_by_pc_all[pc] for pc in unresolved
                                  if pc in reason_by_pc_all]
        detail = {"held_samples": held[:10], "guard": guard,
                 "locked_skip": locked_skip, "swing_ratio": swing_ratio,
                 "no_supplier_data_count": len(unresolved),
                 "no_supplier_data_samples": unresolved,
                 # 2026-08-30 신설(확인자 지적 대응) -- 위 samples는 pd_no뿐이라
                 # 되짚으려면 다시 --from-dir를 돌려야 했다. 이유 분해와, 이번 실행이
                 # 이미 확보한 표본(pd_no·이유·회사명 원문)을 함께 남긴다 -- 새로
                 # 계산하지 않고 stats(_msf.run 반환값)에서 그대로 가져온다.
                 "no_supplier_data_reason": reason_counts,
                 # ⚠ 이 표본은 «이번 실행이 새로 읽은 몰 응답» 기준이라 위
                 # no_supplier_data_count(DB 기준)와 건수가 다를 수 있다 -- 다르면
                 # 아래 matched/unmatched가 그 차이를 숫자로 보여준다(콘솔 4단계의
                 # missing 안내와 같은 사실을 detail에도 남긴 것).
                 "no_supplier_data_reason_samples": matched_reason_samples,
                 "no_supplier_data_reason_matched": len(matched_reason_samples),
                 "no_supplier_data_reason_unmatched":
                     len(unresolved) - len(matched_reason_samples)}
        if args.apply and run_id is not None:
            with engine.begin() as conn:
                _finish_run(conn, run_id, ok=True, collected_count=collected,
                           price_changed_count=len(applied), held_count=len(held),
                           excluded_count=len(excluded), reprice_log_id=reprice_log_id,
                           exclude_log_id=exclude_log_id, detail=detail)
        else:
            print("\nmall_sync_runs.detail 에 기록될 값(드라이런 -- DB에 쓰지 않았습니다):")
            print(json.dumps(detail, ensure_ascii=False, indent=2))

        print("\n=== 요약 ===")
        line = (f"몰 갱신 -- 수집 {collected}건 · 가격 {len(applied)}건 변경 ·"
               f" 보류 {len(held)}건 · 후보 제외 {len(excluded)}건 ·"
               f" 판정 불가(공급처 데이터 없음) {len(unresolved)}건")
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
