# -*- coding: utf-8 -*-
"""몰 상품별 공급처 다건 수집 -- /adm_cate/product_com_list.php?pd_no=

지금 product_supplier_prices는 상품당 행이 사실상 1개뿐이다(2026-08-25 공급처 정리
작업이 products.supplier 텍스트 1건을 이름 매칭해 넣은 결과). 이 도구는 몰 관리자
페이지가 실제로 보여주는 "업체 여러 곳"(순위·공급가·리베이트·재고상태·연락처)을
전부 읽어 product_supplier_prices(공급처별 값)와 suppliers(업체 연락처)에 채운다.

■ 지금 쓰는 방식 (2026-08-26 사장님 결정 -- 쿠키를 파일에 두지 않는다)
  이 페이지는 로그인 세션이 있어야 열린다(아래 §과거 방식 참조). **하네스가 브라우저로
  직접 페이지를 읽어 HTML을 파일로 떨군다** -- .env에 쿠키를 넣지 않는다. 그래서 이
  도구는 두 갈래로 나뉜다:

      가져오기      하네스가 브라우저로 페이지를 받아 파일로 저장한다(이 스크립트 밖의 일)
      파싱·적재     이 스크립트가 --from-dir <폴더> 로 그 파일들을 읽어 처리한다

  파일 이름은 상품번호를 담아야 한다(예: 121807.html -- 파일명 선두 숫자를 pd_no로
  읽는다). 아래 §과거 방식(네트워크 직접 수집)은 지우지 않고 남겨 둔다 -- 나중에
  로그인 세션을 다시 확보하면 그대로 쓴다. 지금 기본은 파일 처리다.

■ (과거 방식 -- 2026-08-25 작성 당시 설계. 2026-08-26 사장님 결정으로 지금은 쓰지
  않는다 -- 코드는 지우지 않고 남긴다) 세션 -- 이 페이지는 로그인 없이는 안 열린다
  (2026-08-26 실측, 익명 GET)
    GET https://popcornpc.co.kr/adm_cate/product_com_list.php?pd_no=121807
    -> 200 OK인데 본문이 alert('로그인 하십시오') + location.replace('../bbs/login.php?...')

  로그인은 POST 폼 제출이라 이 스크립트가 대신하지 않는다(CLAUDE.md 규약 -- 몰에는
  GET만, 폼 제출 금지. 그리고 비밀번호를 이 저장소 어디에도 남기지 않는다는 규칙과도
  맞다). 대신 **이미 로그인된 세션의 쿠키 값**을 사람이 한 번 복사해 .env에 넣는
  방식이었다(지금은 쓰지 않음 -- 위 §지금 쓰는 방식 참조):

    1. 사장님 계정으로 popcornpc.co.kr 관리자에 브라우저로 로그인한다(평소 하던 대로).
    2. 개발자도구 Network 탭에서 /adm_cate/ 로 시작하는 아무 요청이나 열어
       Request Headers의 Cookie 값 전체를 복사한다.
    3. .env에 한 줄 추가: MALL_ADMIN_COOKIE=<복사한 값 그대로>
    4. 세션은 유효기간이 있다 -- 로그인 페이지로 다시 튕기면(LoginRequired) 이 스크립트가
       즉시 전체 수집을 멈추고 이유를 말한다("이 상품 하나가 이상하다"가 아니라
       "세션이 죽었다"이므로 낱개 실패로 취급하지 않는다). 다시 복사해 갱신한다.

  쿠키 값은 코드에 박지 않는다 -- 매번 os.environ에서 읽는다. .env는 gitignore 대상이라
  이 값도 리포에 남지 않는다.

■ 대상 -- --from-dir를 쓰면 대상은 그 폴더의 파일들이다(그 안에서도 --codes/--limit으로
  다시 추릴 수 있다). --from-dir 없이 네트워크 경로(위 §과거 방식)를 쓰면 기본은 추천
  후보(v_recommendation_candidates, 2026-08-26 실측 약 2,959건)다.

■ 드라이런이 기본이다. --apply를 줘야 실제로 DB에 쓴다. --from-dir/--from-cache는
  네트워크를 아예 쓰지 않는다. (과거 방식인) 네트워크 경로는 드라이런에서도 몰에는
  실제로 GET 요청을 보낸다(그래야 "몇 건이 어떻게 바뀔지" 셀 수 있다) -- DB에 안
  쓴다는 뜻이지 네트워크를 안 쓴다는 뜻이 아니었다.

■ 속도·중단 (저장소 규약 A-18과 동일, 네트워크 경로에 한함 -- 지금은 안 씀)
  요청 간격 1.5초, 연속 실패 5회면 멈춘다. 받은 원문은 .cache/mall_supplier/{pd_no}.html에
  남아 재실행 시 그 상품은 네트워크 요청 없이 캐시를 다시 쓴다(이어서 하기). 상품별
  처리 결과는 .cache/mall_supplier/_progress.json에 남는다 -- --apply로 이미 반영된
  상품은 재실행 시 건너뛴다(--reapply로 강제 재반영). --from-dir도 이 진행표를 같이 쓴다.

■ 매입가는 이 도구에서 건드리지 않는다
  product_supplier_prices에 행을 넣고 갱신할 뿐, products.purchase_price/sale_price는
  쓰지 않는다(_reprice() 호출 없음). 여러 공급처 중 최저가를 products에 반영할지는
  별도 결정이다 -- 이 도구가 하는 일과 그 반영은 분리돼 있다. 다만 **요약에는 "판매중
  최저가"를 함께 보고한다** -- 품절·단종 공급처가 더 싸도 살 수 없으므로, 전체
  최저가와 실제로 살 수 있는(판매중) 최저가가 다르면 그 사실을 밝힌다(DB에는 어느
  쪽도 쓰지 않는다 -- 보고뿐이다).

■ 실측 확정 (2026-08-26 1차, 하네스 브라우저 DOM 실측 -- 상품 121807, EUC-KR, 공급처 8행)
  아래는 더 이상 가정이 아니라 확인된 사실이다(전날 §검증되지 않은 가정 ①~④의 답):
    ① 행 구획 -- input[name^="pd_no["]가 있는 <tr>만 공급처 행이다. "통합관리자"를
       포함하는 <tr>이 9개였지만 마지막(업체 신규 추가용 select, 옵션 417개)은 pd_no
       입력칸이 없어 공급처가 아니다 -- 길이·셀 수가 아니라 pd_no 유무로 가른다.
    ② 발주가(balju_price)는 짐작과 반대로 확인됐다 -- []첨자가 «전혀» 없고 문서
       전체에 balju_price1 하나뿐이다. 행 구분이 불가능해 지어내지 않고 전 행 NULL로
       둔다.
    ③ ment[N] select는 옵션 3개(판매중/품절/단종), value+라벨 둘 다 존재 -- 가정대로
       (DOM `selectedIndex`로 읽은 결과 기준. **주의 -- 이건 원문 마크업의 속성
       «따옴표 유무»까지는 답하지 않는다**, 아래 2차 참조).
    ④ 연락처 줄은 그 업체 행 HTML 안에 있는 것도 맞다 -- 다만 앞에 몰 배열 순위
       숫자가 붙어 나온다("0 (주)메종시스템 ..."). 파싱에서 그 숫자를 뗀다.
    ⑤ (새로 발견) o_price1[N](hidden)이 그 행 <tr> 안에 없는 경우가 있다(페이지의
       다른 자리에 있다). 그래서 저장하는 공급가는 price1[N](쉼표 포함 표기)을
       파싱한 값을 원천으로 쓰고, o_price1은 찾아지면(행 안 -> 문서 전체 순) 교차
       검증(price_mismatch)에만 쓴다 -- 못 찾아도 실패로 취급하지 않는다.
  --selftest는 이 실측값(상품 121807의 8개 행 -- 회사명·공급가·상태)을 그대로 검증«했다»
  (과거형 -- 아래 2차 참조).

■ 실측 정정 (2026-08-26 2차, 몰 세션이 생겨 처음으로 `.cache/mall_supplier/121807.html`
  캐시를 이 파서로 직접 돌려 봄 -- 1차는 브라우저 DOM을 읽었을 뿐, 이 정규식 파서 자체를
  실물 HTML에 돌려본 적이 없었다). --selftest는 통과했는데 실물은 결함이 «둘» 있었다:
    ③의 정정 -- ment[N] select의 **`name` 속성에 따옴표가 없다**(`<select name=ment[0]>`).
       DOM은 이미 파싱된 트리를 읽으므로 원문 속성 형태를 안 가린다. 정규식은 따옴표를
       요구하고 있었고, 그래서 실물 8행 «전부» 재고상태 판정 불가(None)였다.
       `api/mall_supplier_parse.py`의 `_selected_option`이 따옴표 유무 둘 다 받도록 고쳤다.
    (새 발견) 담당자 «전화번호 값»이 비어 있는 공급처가 실재한다(행7 "아이보라" --
       "전화 : <br>발주번호 : ..."). name_blob을 전화번호 «값» 매치 위치에서 자르던
       코드는 이 행에서 자를 지점을 못 찾아 «해당 행 나머지 전체»를 삼켰는데, 하필 이
       행이 배열의 마지막이라 다음 pd_no 경계가 없어 세그먼트가 문서 끝(다음 "업체
       신규 추가" 섹션)까지 이어졌다 -- 그 섹션 잔여 텍스트("신규입력 지정 업체명 재고
       판매가격 리베이트 등록 업체명 : ...")까지 연락처에 통째로 붙어 나왔다.
       `_parse_contact`가 값이 아니라 "전화"/"발주번호" «라벨» 위치에서 자르도록 고쳤다.
  **selftest 픽스처도 다시 짰다** -- 1차 픽스처는 이 둘을 못 잡는 합성 마크업(따옴표
  붙은 select, 모든 행에 전화번호 값 존재)이었다. 지금은 캐시 파일에서 실제 <tr> 구조를
  뽑아 만든다(담당자 계정코드·전화·발주번호만 자리표시자로 치환 -- 실제 값을 git 이력에
  남기지 않는다). §자기검증 섹션 참조.

■ 연락처는 suppliers에 둔다(product_supplier_prices가 아니라)
  담당자·전화·발주번호는 업체 단위 정보다 -- 상품이 바뀐다고 그 업체 담당자가 바뀌지
  않는다. suppliers는 이미 업체 단위 표(공급처 정리 작업으로 117개 실제 회사가 들어와
  있다)이므로 거기 채운다. 순위·리베이트·재고상태는 (상품,공급처) 조합마다 다른 값이라
  product_supplier_prices에 넣는다(발주가는 위 실측 ②로 항상 NULL).

Usage:
  .venv/Scripts/python tools/mall_supplier_fetch.py --selftest
  .venv/Scripts/python tools/mall_supplier_fetch.py --from-dir <하네스가 받아둔 폴더> --codes 121807
  .venv/Scripts/python tools/mall_supplier_fetch.py --from-dir <하네스가 받아둔 폴더> --limit 50
  .venv/Scripts/python tools/mall_supplier_fetch.py --from-dir <하네스가 받아둔 폴더> --apply --limit 500
  .venv/Scripts/python tools/mall_supplier_fetch.py --codes 121807 --limit 1   (과거 방식 -- 세션 있을 때만)
  .venv/Scripts/python tools/mall_supplier_fetch.py --from-cache               (네트워크 경로가 남긴 캐시 재파싱)
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                       # noqa: E402
from sqlalchemy import text                          # noqa: E402

# 파싱·매칭·UPSERT SQL은 여기서 정의하지 않는다 -- api/mall_supplier_parse.py가 단일
# 원천이다(2026-08-26, api/admin_mall_supplier.py 신설과 함께 옮김). 아래 별칭(as _이름)은
# 이 파일 안의 기존 호출부(run·_selftest·_plan_and_maybe_apply)를 한 글자도 안 고치기
# 위한 것이지, 이름을 감추려는 것이 아니다.
from api.mall_supplier_parse import (                 # noqa: E402
    STATE_MAP, CLICK_NARA_SUPPLIER_ID, parse_rows, load_suppliers, resolve_supplier,
    cheapest_summary as _cheapest_summary,
    PSP_UPSERT as _PSP_UPSERT, SUPPLIER_CONTACT_UPDATE as _SUPPLIER_CONTACT_UPDATE,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("MALL_SUPPLIER_CACHE") or os.path.join(ROOT, ".cache", "mall_supplier")
PROGRESS_PATH = os.path.join(CACHE, "_progress.json")

BASE = "https://popcornpc.co.kr"
URL_TMPL = BASE + "/adm_cate/product_com_list.php?pd_no=%s"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      " (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
DELAY = 1.5              # 요청 간격(초) -- A-18과 동일
MAX_FAIL = 5             # 연속 실패면 멈춘다(차단 의심) -- A-18과 동일

# STATE_MAP · CORP_TOKENS · CLICK_NARA_SUPPLIER_ID -- api/mall_supplier_parse.py로 옮김
# (위 import). CORP_TOKENS는 이 파일에서 더 안 쓰여 import하지 않았다(내부 헬퍼
# _normalize_name·_flex_pattern 전용 -- 그 둘도 함께 옮겼다).


class LoginRequired(RuntimeError):
    """세션이 없거나 만료됐다 -- 상품 하나의 문제가 아니라 전체를 멈출 신호다."""


# ============================================================== 세션·수집 ==
def _cookie_header() -> str:
    v = os.environ.get("MALL_ADMIN_COOKIE")
    if not v:
        raise RuntimeError(
            "MALL_ADMIN_COOKIE가 없습니다 -- 이 페이지는 로그인 세션이 있어야 열립니다"
            "(2026-08-26 실측: 익명 GET은 200 OK로 응답하면서 본문이 로그인 페이지로"
            " 튕깁니다). 몰 관리자(popcornpc.co.kr)에 사장님 계정으로 로그인한 브라우저"
            "에서 개발자도구 Network 탭 -> adm_cate 요청 하나 -> Request Headers의"
            " Cookie 값을 그대로 복사해 .env에 MALL_ADMIN_COOKIE=<복사한 값>으로"
            " 넣으세요. 이 스크립트는 로그인 폼을 대신 제출하지 않습니다.")
    return v


def _looks_like_login_redirect(raw: bytes) -> bool:
    """2026-08-26 실측 응답: <=267바이트, alert('로그인 하십시오') +
    location.replace('../bbs/login.php?url=...'). 짧은 응답 + login.php 문자열로 판정."""
    if b"login.php" in raw and len(raw) < 4000:
        return True
    try:
        krtxt = raw.decode("cp949", "replace")
    except Exception:                                       # noqa: BLE001
        krtxt = ""
    return "location.replace" in krtxt and "로그인" in krtxt


def fetch(pd_no: int, cookie: str, cache_only: bool = False, refetch: bool = False):
    """캐시 우선. 없으면 1회 요청 -> (html, fetched_at, from_cache).

    cache_only=True면 네트워크를 아예 쓰지 않는다(--from-cache) -- 캐시에 없으면
    (None, None, False).

    refetch=True면 캐시 파일이 있어도 무시하고 다시 요청해 덮어쓴다.
    ⚠ 2026-08-27 결함 수정(tools/mall_daily_sync.py 를 짜다 발견) -- 이 함수는 전부터
    `refetch` 매개변수 자체가 없었다. 호출부 run()은 `--refetch` 플래그로 `need_network`
    라는 변수를 계산해 놓고도(쿠키를 미리 물어야 하는지 판단하는 데만 썼다) 정작
    이 함수를 부를 때는 그 값을 넘기지 않았다 -- 그래서 캐시 파일이 한 번 생기면
    `--refetch` 를 줘도 **영원히 그 파일을 그대로 돌려줬다.** 몰 가격은 매일 바뀌는데
    자동화가 매일 새벽 어제와 똑같은 캐시만 읽으면 "자동 반영"이 "어제 값 재반영"이
    된다 -- 이 자동화의 존재 이유 자체가 무너지는 결함이라 여기서 고친다(engine·엔진
    로직이 아니라 이 CLI 전용 파일이라 CANON 의 "api/ 아래는 건드리지 않는다"와도
    무관하고, 이번 지시서가 "고칠 것이 있으면"이라고 명시적으로 허용했다).
    로그인 리다이렉트로 보이면 LoginRequired -- 호출부가 전체 수집을 멈춘다.
    """
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"{pd_no}.html")
    if os.path.exists(p) and not refetch:
        observed = datetime.fromtimestamp(os.path.getmtime(p))
        return io.open(p, encoding="utf-8").read(), observed, True
    if cache_only:
        return None, None, False
    req = urllib.request.Request(
        URL_TMPL % pd_no,
        headers={"User-Agent": UA, "Cookie": cookie, "Accept-Language": "ko-KR,ko;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise RuntimeError(f"차단 응답 {e.code} -- 수집을 멈춥니다")
        return None, None, False
    except Exception:                                        # noqa: BLE001
        return None, None, False
    if _looks_like_login_redirect(raw):
        raise LoginRequired("몰 세션이 없거나 만료됐습니다(로그인 페이지로 redirect) --"
                             " MALL_ADMIN_COOKIE를 다시 복사해 넣으세요.")
    html = raw.decode("cp949", "replace")
    io.open(p, "w", encoding="utf-8").write(html)
    time.sleep(DELAY)
    return html, datetime.now(), False


def _read_html_file(path: str) -> str:
    """--from-dir 파일 읽기 -- 하네스가 브라우저로 받은 원문이라 인코딩을 모른다.

    UTF-8을 먼저 시도한다(브라우저가 이미 유니코드로 디코딩한 것을 하네스가 저장했을
    가능성이 높다) -- 실패하면 몰 원래 인코딩(cp949, fetch()와 동일)으로 읽는다."""
    raw = io.open(path, "rb").read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp949", "replace")


def _scan_from_dir(dir_path: str):
    """--from-dir 폴더를 훑어 {pd_no: 파일경로} 맵과 (파일명에서 상품번호를 못 읽어
    건너뛴 파일명 목록)을 돌려준다. 파일명은 선두 숫자를 pd_no로 읽는다(예: 121807.html,
    121807_2026-08-26.html도 허용 -- "121807.html 식"이라는 지시를 넉넉하게 해석했다)."""
    file_map, skipped = {}, []
    for fn in sorted(os.listdir(dir_path)):
        if not fn.lower().endswith(".html"):
            continue
        m = re.match(r"(\d+)", fn)
        if not m:
            skipped.append(fn)
            continue
        file_map[int(m.group(1))] = os.path.join(dir_path, fn)
    return file_map, skipped


# ==================================================================== 파싱 ==
# HTML 파싱(parse_rows) · 판매중 최저가 판정(cheapest_summary) · 공급처 매칭
# (load_suppliers · resolve_supplier) · UPSERT SQL은 api/mall_supplier_parse.py로
# 옮겼다(위 import) -- api/admin_mall_supplier.py(HTTP 수신 엔드포인트, 2026-08-26
# 신설)도 같은 함수를 쓴다. 두 벌을 두면 반드시 갈라진다(CANON.md §1) -- 여기서는
# 더 이상 정의하지 않는다.


# ==================================================================== DB ==


def _plan_and_maybe_apply(engine, apply_: bool, pc: int, sid: int, sname, remainder,
                           r: dict, observed, stats: dict):
    """읽기 전용 SELECT로 신규/갱신을 분류하고, apply_면 실제로 쓴다.

    드라이런에서도 이 SELECT는 실행한다(그래야 "몇 건이 신규고 몇 건이 갱신인지"를
    실제로 셀 수 있다) -- DB에 쓰지는 않는다."""
    with engine.connect() as conn:
        existed = conn.execute(text(
            "SELECT 1 FROM product_supplier_prices WHERE product_code=:pc AND supplier_id=:s"),
            {"pc": pc, "s": sid}).first() is not None
        cur_phone = conn.execute(text(
            "SELECT contact_phone FROM suppliers WHERE supplier_id=:s"), {"s": sid}).scalar()
    stats["psp_update" if existed else "psp_insert"] += 1
    will_fill_contact = bool(remainder or r["phone"] or r["order_phone"])
    if will_fill_contact:
        stats["contact_filled" if apply_ else "contact_would_fill"] += 1
        if cur_phone and r["phone"] and cur_phone != r["phone"]:
            stats["contact_conflict"].append((sid, sname, cur_phone, r["phone"]))
    if not apply_:
        return
    with engine.begin() as conn:
        conn.execute(_PSP_UPSERT, {
            "pc": pc, "s": sid, "cost": r["o_price"], "state": r["state"],
            "rank": r["idx"], "rpct": r["rebate_pct"], "rprice": r["rebate_price"],
            "oprice": r["order_price"], "sraw": r["state_raw"], "fa": observed})
        if will_fill_contact:
            conn.execute(_SUPPLIER_CONTACT_UPDATE, {
                "cn": remainder, "cp": r["phone"], "op": r["order_phone"],
                "cr": r["contact_blob"], "fa": observed, "s": sid})


# ================================================================= 진행표 ==
def _load_progress():
    if os.path.exists(PROGRESS_PATH):
        return json.load(io.open(PROGRESS_PATH, encoding="utf-8"))
    return {"done": {}}


def _save_progress(state):
    os.makedirs(CACHE, exist_ok=True)
    io.open(PROGRESS_PATH, "w", encoding="utf-8").write(
        json.dumps(state, ensure_ascii=False, indent=2))


def target_codes(conn, codes_arg: str, limit):
    if codes_arg:
        return [int(c) for c in codes_arg.split(",") if c.strip()]
    rows = conn.execute(text(
        "SELECT product_code FROM v_recommendation_candidates ORDER BY product_code")).all()
    codes = [r[0] for r in rows]
    return codes[:limit] if limit is not None else codes


# ==================================================================== 실행 ==
def run(engine, codes: list, apply_: bool, refetch: bool, cache_only: bool, reapply: bool,
        file_map: dict = None):
    """file_map이 주어지면(--from-dir) 그 {pd_no: 파일경로} 맵에서 HTML을 읽는다 --
    네트워크(fetch/쿠키)는 전혀 쓰지 않는다. file_map이 None이면 기존 네트워크·캐시
    경로(과거 방식, 모듈 docstring §과거 방식 참조)를 그대로 쓴다."""
    progress = _load_progress()
    done = progress.setdefault("done", {})
    with engine.connect() as conn:
        suppliers = load_suppliers(conn)

    stats = {
        "target": len(codes), "cached": 0, "fetched": 0, "fetch_fail": 0,
        "from_file": 0, "from_file_missing": 0, "from_file_login_like": 0,
        "login_abort": False,
        # 연속 실패로 순환중단(MAX_FAIL)에 걸려 «목표를 다 돌지 못하고» 멈췄는가.
        # 2026-08-27 신설(tools/mall_daily_sync.py 필요) -- 예전엔 이 상태를 콘솔에
        # 문자열로만 찍고 stats 에는 아무 표시가 없어, 호출부가 "부분 수집으로
        # 멈췄다"를 프로그램적으로 알 방법이 없었다(사람이 로그를 읽어야만 알았다).
        # 자동화는 로그를 안 읽으므로 이 값으로 판정한다.
        "circuit_break_abort": False,
        "rows_total": 0, "state_unknown": 0, "price_mismatch": 0,
        "psp_insert": 0, "psp_update": 0,
        "contact_filled": 0, "contact_would_fill": 0, "contact_conflict": [],
        "supplier_matched": set(), "supplier_unmatched": {},
        # 업체명 자리에 재고 상태값("재고있음" 등)이 온 행 -- 공급처가 아니라서 매칭을
        # 시도하지 않는다(mall_supplier_parse.STOCK_STATUS_TOKENS). unmatched와 섞으면
        # "새 공급처로 등록해야 하나"로 오인한다 -- 별도 집계(지시서 요구사항).
        "supplier_excluded_stock_status": 0,
        "products_with_available_price": 0, "products_no_available_supplier": 0,
        "cheapest_is_unavailable": 0, "cheapest_unavailable_samples": [],
    }
    samples, cookie_val, consec_fail = [], None, 0

    for n, pd_no in enumerate(codes):
        key = str(pd_no)
        if apply_ and not reapply and done.get(key, {}).get("status") == "applied":
            continue

        if file_map is not None:
            path = file_map.get(pd_no)
            if not path:
                stats["from_file_missing"] += 1
                continue
            html = _read_html_file(path)
            observed = datetime.fromtimestamp(os.path.getmtime(path))
            if _looks_like_login_redirect(html.encode("utf-8", "replace")):
                stats["from_file_login_like"] += 1
                print(f"  건너뜀: {os.path.basename(path)} -- 로그인 리다이렉트로 보입니다"
                      "(하네스가 다시 받아야 합니다)")
                continue
            stats["from_file"] += 1
        else:
            need_network = refetch or not os.path.exists(os.path.join(CACHE, f"{pd_no}.html"))
            try:
                if need_network and not cache_only and cookie_val is None:
                    cookie_val = _cookie_header()   # 필요할 때만 요구 -- 전량 캐시 히트면 필요 없다
                html, observed, from_cache = fetch(
                    pd_no, cookie_val or "", cache_only=cache_only, refetch=refetch)
            except LoginRequired as e:
                remaining = len(codes) - n
                print(f"\n중단: {e} -- 이후 {remaining}건을 시도하지 않았습니다.")
                stats["login_abort"] = True
                done[key] = {"status": "login_required", "ts": datetime.now().isoformat()}
                break
            except RuntimeError as e:
                print(f"\n중단: {e}")
                break

            if html is None:
                if cache_only:
                    continue   # --from-cache인데 캐시가 없는 코드 -- 통계에 안 넣는다
                stats["fetch_fail"] += 1
                consec_fail += 1
                done[key] = {"status": "fetch_fail", "ts": datetime.now().isoformat()}
                if consec_fail >= MAX_FAIL:
                    print(f"\n중단: 연속 실패 {consec_fail}건 -- 차단이 의심됩니다")
                    stats["circuit_break_abort"] = True
                    break
                continue
            consec_fail = 0
            stats["cached" if from_cache else "fetched"] += 1

        rows = parse_rows(html)
        stats["rows_total"] += len(rows)

        # 판매중 최저가 판정(지시서 §③) -- 품절/단종 공급처가 더 싸도 살 수 없다.
        cheapest = _cheapest_summary(rows)
        if cheapest is not None:
            if cheapest["cheapest_available"] is not None:
                stats["products_with_available_price"] += 1
                if cheapest["mismatch"]:
                    stats["cheapest_is_unavailable"] += 1
                    if len(stats["cheapest_unavailable_samples"]) < 5:
                        co, ca = cheapest["cheapest_overall"], cheapest["cheapest_available"]
                        stats["cheapest_unavailable_samples"].append({
                            "pd_no": pd_no, "overall_price": co["o_price"],
                            "overall_state": co["state_raw"], "available_price": ca["o_price"]})
            else:
                stats["products_no_available_supplier"] += 1

        for r in rows:
            if r["state"] is None:
                stats["state_unknown"] += 1
            if r["price_mismatch"]:
                stats["price_mismatch"] += 1
            sid, sname, remainder, kind = resolve_supplier(r["contact_blob"], suppliers)
            if kind == "excluded_stock_status":
                # 미매칭(unmatched)이 아니라 "공급처가 아닌 값" -- 등록 후보 목록에
                # 섞이지 않게 애초에 다른 집계로 뺀다.
                stats["supplier_excluded_stock_status"] += 1
            elif sid is None:
                label = r["contact_blob"] or "(빈 값)"
                stats["supplier_unmatched"][label] = stats["supplier_unmatched"].get(label, 0) + 1
            else:
                stats["supplier_matched"].add(sid)
            if len(samples) < 8:
                samples.append({"pd_no": pd_no, **r, "supplier_id": sid,
                                "supplier_name": sname, "contact_name": remainder,
                                "match_kind": kind})
            # 반영 가능 조건 -- 상태를 모르거나(state None) 가격이 없거나 공급처를 못
            # 찾으면 반영하지 않는다(모르는 것을 지어내지 않는다).
            if sid is not None and r["o_price"] is not None and r["state"] is not None:
                _plan_and_maybe_apply(engine, apply_, pd_no, sid, sname, remainder,
                                       r, observed, stats)

        done[key] = {"status": "applied" if apply_ else "parsed",
                     "rows": len(rows), "ts": datetime.now().isoformat()}
        if n % 20 == 0:
            _save_progress(progress)

    _save_progress(progress)
    return stats, samples


# ================================================================ 보고문 ==
def _print_report(stats: dict, samples: list, apply_: bool, from_dir: bool = False):
    print()
    print("=== 요약 ===")
    if from_dir:
        # stats 합계가 아니라 호출부(main())가 --from-dir 여부를 명시로 넘긴다 --
        # 파일이 0건(빈 폴더·전부 건너뜀)이면 from_file 등이 전부 0이라 stats만으로는
        # "네트워크 경로인데 0건"과 구분이 안 된다.
        print(f"--from-dir 파일 처리 {stats['from_file']}건 · 폴더에 파일 없음"
              f" {stats['from_file_missing']}건 · 로그인 리다이렉트로 보여 건너뜀"
              f" {stats['from_file_login_like']}건(네트워크 요청 0건)")
    else:
        print(f"대상 {stats['target']}건 -- 캐시 재사용 {stats['cached']}건 · 신규 요청"
              f" {stats['fetched']}건 · 요청 실패 {stats['fetch_fail']}건")
    if stats["login_abort"]:
        print("몰 세션이 없어 중단했습니다 -- MALL_ADMIN_COOKIE를 .env에 넣고 다시"
              " 실행하세요(모듈 docstring 참조).")
    print(f"파싱된 업체 행 합계 {stats['rows_total']}건")
    print(f"  재고상태 판정 불가(select 미인식) {stats['state_unknown']}건 -- 이 행은"
          " 반영 대상에서 제외했습니다")
    print(f"  price1과 o_price1 표기 불일치(참고용 필드 오차) {stats['price_mismatch']}건")
    print(f"  공급처가 아닌 값이라 제외(업체명 자리에 재고 상태값 -- \"재고있음\" 등)"
          f" {stats['supplier_excluded_stock_status']}건 -- 미매칭 목록에 넣지 않았습니다"
          "(공급처 등록 대상이 아닙니다)")
    print(f"  공급처 매칭 성공(고유 업체) {len(stats['supplier_matched'])}곳")
    if stats["supplier_unmatched"]:
        total_un = sum(stats["supplier_unmatched"].values())
        top = sorted(stats["supplier_unmatched"].items(), key=lambda kv: -kv[1])[:10]
        print(f"  공급처 매칭 실패(suppliers에 없는 이름) {total_un}건 · 서로 다른"
              f" 이름 {len(stats['supplier_unmatched'])}종 -- 상위 10:")
        for name, cnt in top:
            print(f"    {cnt:>4}건  {name}")
    print(f"판매중 공급처가 있는 상품 {stats['products_with_available_price']}건 · 전 공급처"
          f" 품절/단종이라 살 수 있는 곳이 없는 상품 {stats['products_no_available_supplier']}건")
    if stats["cheapest_is_unavailable"]:
        print(f"  주의 -- 전체 최저가가 품절/단종 공급처에 있어 «실제로 살 수 있는» 최저가"
              f"(판매중)와 다른 상품 {stats['cheapest_is_unavailable']}건(표본, 최대 5):")
        for s in stats["cheapest_unavailable_samples"]:
            print(f"    pd_no={s['pd_no']} 전체 최저가={s['overall_price']}"
                  f"({s['overall_state']}, 구매 불가) 판매중 최저가={s['available_price']}")
    label = "반영" if apply_ else "반영 예정(드라이런 -- 실제로 쓰지 않았습니다)"
    print(f"product_supplier_prices {label}: 신규 {stats['psp_insert']}행 ·"
          f" 갱신 {stats['psp_update']}행")
    fill_key = "contact_filled" if apply_ else "contact_would_fill"
    print(f"suppliers 연락처 {label}: {stats[fill_key]}건")
    if stats["contact_conflict"]:
        print(f"  주의 -- 기존 전화번호와 다른 값이 관측된 공급처 {len(stats['contact_conflict'])}곳"
              "(최신 관측값으로 덮어쓰도록 설계돼 있습니다 -- 아래 표본):")
        for sid, sname, old, new in stats["contact_conflict"][:5]:
            print(f"    {sid} {sname}: {old} -> {new}")
    if samples:
        print("\n표본(최대 8행):")
        for s in samples:
            print(f"  pd_no={s['pd_no']} rank={s['idx']} price={s['o_price']}"
                  f" state={s['state']}({s['state_raw']}) rebate%={s['rebate_pct']}"
                  f" rebate_won={s['rebate_price']} order_price={s['order_price']}"
                  f" supplier={s['supplier_id']}/{s['supplier_name']}({s['match_kind']})"
                  f" contact={s['contact_name']} phone={s['phone']}"
                  f" order_phone={s['order_phone']}")
    print("\n이 도구는 product_supplier_prices와 suppliers 연락처만 씁니다."
          " products.purchase_price/sale_price는 건드리지 않습니다"
          " -- 재판정(_reprice)은 별도 결정·별도 실행입니다.")


# ================================================================ 자기검증 ==
# 2026-08-26(1차) 하네스 브라우저 DOM 실측(상품 121807)을 손으로 옮겨 적은 합성
# 마크업이었다 -- 그런데 실제로 `.cache/mall_supplier/121807.html`(하네스가 받아둔
# 몰 원문 캐시)을 이 파서(정규식 기반)로 처음 돌려 보니 결함이 둘 드러났다:
#   ① 재고상태 전 행 판정 불가(select 미인식) -- select의 name 속성이 실물은
#      «따옴표가 없다»(`<select name=ment[0]>`)인데 합성 픽스처는 따옴표를 붙여
#      만들었다(DOM 실측은 `selectedIndex`로 읽어 원문 속성 형태를 보지 않는다).
#   ② 행7(아이보라)의 연락처가 "업체 신규 추가" 섹션 전체를 삼킴 -- 실물은 그 행의
#      담당자 전화번호 «값»이 비어 있는데("전화 : <br>발주번호 : ...") 합성 픽스처는
#      모든 행에 전화번호 값을 채워 넣어서 이 경우를 아예 표현하지 못했다.
# 그래서 2026-08-26(2차)에 픽스처를 **캐시 파일에서 실제 <tr>을 뽑아** 다시 짰다 --
# 합성 마크업을 손으로 짓지 않는다(태그·속성 따옴표 유무·셀 순서·`</tr>` 뒤 숨은
# 입력칸 위치까지 원문 그대로). 담당자 계정코드·전화·발주번호·로그일시만 자리표시자로
# 치환했다(실제 값을 git 이력에 남기지 않는다 -- 회사명은 개인정보가 아니라 그대로 둔다).
# 아래 두 값은 실물과 다르게 «의도적으로» 바꿨다(원문 그대로는 이 경로를 검증 못 한다):
#   · 행0의 o_price1 -- 실물은 price1과 일치(278490, mismatch=False)라 999999로
#     바꿔 price_mismatch=True 경로를 확인한다.
#   · 행1의 리베이트 -- 실물 8행 전부 공란이라 1.5%/4200원으로 채워 `_to_pct`/
#     `_to_int` 파싱 경로를 확인한다.
def _mall_row_html(idx, company, vendor, phone, order_phone, state_idx,
                    price_raw, o_price1_val, rebate_per, rebate_price):
    """실측 캐시(2026-08-26, 상품 121807)의 <tr> 한 행 구조를 그대로 뜬 틀.

    state_idx: 0=판매중 1=품절 2=단종(select option 순서, 실물 그대로) -- 선택된
    옵션에만 실물처럼 `selected`가 붙는다(공백 배치까지 실물과 동일하게 재현:
    선택 안 된 옵션은 원문에 공백이 두 칸 남는다 -- `<option value='1'  style=...`).
    phone=None이면 실물 행7처럼 "전화 : <br>"(값 없이 라벨만)을 낸다."""
    def opt(v, label, extra=""):
        sel = "selected" if state_idx == v else ""
        return f"<option value='{v}' {sel}{extra}>{label}</option>"
    select_html = (opt(0, "판매중") + opt(1, "품절", " style=background:#F0E09D;")
                   + opt(2, "단종", " style=background:#FF5959;"))
    phone_part = f"전화 : {phone}<br>" if phone else "전화 : <br>"
    return f"""<tr bgcolor=white height='20' align=center>
	<td align=center><input type='radio' name='gigung' value='{idx}' ></td>
	<td align=center>{idx} <input type='hidden' name='pd_no[{idx}]' size='3' value='121807'></td>
	<td align=center><b>{company}</b> <p style='margin-top:5px;'>{vendor} 통합관리자<br>{phone_part}발주번호 : {order_phone} <a href="javascript:na_open_window('sms', '/adm/sms.php?reserve_phone={order_phone}&send_phone=1644-0249&msg=&od_no=&group=', 100,100, 250, 480, 0, 0, 0, 0, 0)"><img src='/img/b_sub10.gif' align=absmiddle></a> <a href='/adm_cate/price_my_list_admin.php?companyid={vendor}' target='_blank' class='bx_bl'>관</a>&nbsp; <!-- {company}{vendor} --></td>
	<td><select name=ment[{idx}]>{select_html}</select></td>
	<td><input type='text' name='price1[{idx}]' size='7' value='{price_raw}'  style='ime-mode:disabled;text-align:right;' onkeydown='onlyNum()' onkeyup='tranNum.call(this);'  onblur='change_money({idx},this.value);'> </td>
	<td><input type='text' name='pp_rebate_per[{idx}]' size='3' value='{rebate_per}' onblur='change_percent({idx},this.value)'>%<br><input type='text' name='pp_rebate_price[{idx}]' size='7' value='{rebate_price}'  onblur='change_price({idx})'   style='ime-mode:disabled;text-align:right;' onkeydown='onlyNum()' onkeyup='tranNum.call(this);' >원</td>
	<td><a href='product_price_update_log.php?pd_no=121807&com_id={vendor}' target='_blank' class='bx_re'>로그보기</a><br>2026-08-26 00:00:00</td>
	<td><a href="javascript:DeleteOrder('product_price_delete.php?pd_no=121807&com_id={vendor}')">삭제</a></td>
	<td><input type='text' name='balju_price1' size='7' value='0'  style='ime-mode:disabled;text-align:right;' onkeydown='onlyNum()' onkeyup='tranNum.call(this);'  onblur=chkSaleAgency('121807','{vendor}',this.value)></td>
	</tr>
	<input type='hidden' name='kno[{idx}]' size='7' value='Y'>
	<input type='hidden' name='o_ment[{idx}]' size='7' value='{state_idx}'>
	<input type='hidden' name='o_price1[{idx}]' size='7' value='{o_price1_val}'>
	<input type='hidden' name='com_id[{idx}]' size='7' value='{vendor}'>
	<input type='hidden' name='o_pp_gigung[{idx}]' size='7' value='0'>
	<input type='hidden' name='o_pp_rebate_per[{idx}]' size='7' value='{rebate_per}'>
	<input type='hidden' name='o_pp_rebate_price[{idx}]' size='7' value='{rebate_price}'>
"""


# (idx, 회사명, 계정코드자리표시자, 전화자리표시자(행7=None -- 실물처럼 값 없음),
#  발주번호자리표시자, state_idx, price_raw, o_price1값, 리베이트%, 리베이트원)
_ROW_ARGS = [
    (0, "(주)메종시스템", "Tv0", "02-000-0000", "010-0000-1000", 0,
     "278,490", "999999", "", "0"),          # o_price1 의도적 불일치(실물은 278490 일치)
    (1, "(주)에스티테크놀로지이노베이션", "Tv1", "02-000-0001", "010-0000-1001", 0,
     "280,000", "280000", "1.5", "4200"),    # 리베이트 의도적 삽입(실물은 공란)
    (2, "(주)파인인포", "Tv2", "02-000-0002", "010-0000-1002", 0,
     "304,000", "304000", "", "0"),
    (3, "주식회사 로아컴퍼니스", "Tv3", "02-000-0003", "010-0000-1003", 0,
     "304,000", "304000", "", "0"),
    (4, "(주)아인스시스템 선인", "Tv4", "02-000-0004", "010-0000-1004", 0,
     "304,000", "304000", "", "0"),
    (5, "(주) 메이드시스템", "Tv5", "02-000-0005", "010-0000-1005", 0,
     "304,000", "304000", "", "0"),
    (6, "주식회사 팝콘컴퓨터", "Tv6", "02-000-0006", "010-0000-1006", 1,
     "295,000", "295000", "", "0"),
    (7, "아이보라", "Tv7", None, "010-0000-1007", 1,          # 전화 값 없음(실물 그대로)
     "342,000", "342000", "", "0"),
]

# "업체 신규 추가" 섹션(9번째 <tr> -- pd_no가 없어 공급처 행이 아니다)에 쓰는 select
# 옵션은 실물이 아니라 자리표시자다 -- 실물 목록엔 개인 상호(예: 담당자 개인 이름으로
# 등록된 소규모 거래처)가 섞여 있어 그대로 옮기지 않는다. 이 섹션의 존재 목적은
# "pd_no 없는 대용량 텍스트가 뒤에 있다"는 사실 자체이지 그 내용이 아니다.
_NEW_SUPPLIER_OPTIONS = "".join(
    f"<option value='{n}'>거래처후보{n:03d}주식회사</option>" for n in range(1, 61))

# 실물(2026-08-26 캐시) 512~541행을 그대로 뜬 "업체 신규 추가" 섹션 -- 행7 직후
# `</table>`까지는 실측 그대로, 두 번째 form/table(신규입력)도 헤더 셀 문구까지
# 실측 그대로다("신규입력 지정 업체명 재고 판매가격 리베이트 등록" -- 결함②가
# 삼켰던 바로 그 문구, docs 참조: 하네스 보고 원문).
_TAIL_HTML = f"""	</table>
<input type=hidden name='pd_no' value='121807' class='ed'>
<p style='margin-top:5px;'>
<center><input type='submit' name='상태/가격수정하기' value='상태/가격수정하기'></center>
</form>
<p style='margin-top:5px;'>
<form name=price_insert method=post action="product_price_insert.php">
<table width=920 cellspacing=0 cellpadding=5 border=1 bordercolor='#CFCFCF' style='border-collapse:collapse;' align=center>
<tr align=center height='30' bgcolor='#ededed'>
	<td rowspan='2' width='70'>신규입력</td>
	<td width='30'>지정</td>
	<td >업체명</td>
	<td width='80'>재고</td>
	<td width='80' align=center bgcolor='#ededed'>판매가격</td>
	<td width='90' align=center bgcolor='#ededed'>리베이트</td>
	<td width='50'>등록</td>
</tr>
<tr bgcolor=white height='20' align=center>
	<td align=center><input type='radio' name='gigungInsert' value='1'></td>
	<td align=left><select name='company' style='width:100%;margin-bottom:2px;'>{_NEW_SUPPLIER_OPTIONS}</select><br/>업체명 : <input type='text' name='csearch' value='' placeholder='' style='width:150px;'> <input type='button' value='검색' onclick='price_insert_search()'></td>
	<td><select name=ment><option value='0' >판매중</option><option value='1' style=background:#F0E09D;>품절</option><option value='2' style=background:#FF5959;>단종</option></select></td>
	<td><input type='text' name='price1' size='7' value=''  style='ime-mode:disabled;text-align:right;' onkeydown='onlyNum()' onkeyup='tranNum.call(this);'  onblur=change_money_insert(this.value)></td>
	<td align=left><input type='text' name='pp_rebate_per' size='3' value='' onchange='change_percent_insert(this.value)' style='margin-bottom:2px;'>%<br><input type='text' name='pp_rebate_price' size='7' value=''  onchange='change_price_insert()'   style='ime-mode:disabled;text-align:right;' onkeydown='onlyNum()'>원</td>
	<td><input type='button' name='등록하기' value='등록하기' onclick='price_insert_submit()'></td>
	</tr>
	<input type='hidden' name='pd_no' size='3' value='121807'>
</table>
</form>
"""

_FIXTURE = ("<html><body><form>\n"
            + "".join(_mall_row_html(*args) for args in _ROW_ARGS)
            + _TAIL_HTML + "</body></html>")

_FIXTURE_SUPPLIERS = [
    {"supplier_id": 501, "name": "(주)메종시스템", "status": "활성"},
    {"supplier_id": 502, "name": "(주)에스티테크놀로지이노베이션", "status": "활성"},
    {"supplier_id": 503, "name": "(주)파인인포", "status": "활성"},
    {"supplier_id": 504, "name": "주식회사 로아컴퍼니스", "status": "활성"},
    {"supplier_id": 505, "name": "(주)아인스시스템 선인", "status": "활성"},
    {"supplier_id": 506, "name": "(주) 메이드시스템", "status": "활성"},
    {"supplier_id": 507, "name": "주식회사 팝콘컴퓨터", "status": "활성"},
    {"supplier_id": 508, "name": "아이보라", "status": "활성"},
    {"supplier_id": 2, "name": "클릭나라", "status": "활성"},
    {"supplier_id": 495, "name": "(주)클릭나라", "status": "중지"},
]

# 업체명 자리에 재고 상태값이 온 행("재고있음") -- 2026-08-26 실물 캐시
# (.cache/mall_supplier/97820.html, pd_no[0] 행)에서 그대로 뽑았다(합성 마크업이
# 아니다 -- 위 §실측 확정과 같은 원칙). companyid=herosys 링크로 보아 실제 계정 식별자는
# "herosys"이지만 -- 그 계정코드는 다른 행들과 같은 방식(Tv0..Tv7)으로 "Tv8"로,
# 담당자 연락처 값(발주번호 010-9923-8834)도 다른 행과 같은 자리표시자 패턴으로
# 익명화했다(회사명 "재고있음" 자체는 실제 값 그대로 -- 이건 몰 데이터의 오염된
# "회사명"이라 개인정보가 아니다). 원문은 담당자 전화번호가 비어 있었는데(행7과
# 같은 형태 -- "전화 : <br>") 그 형태까지 그대로 보존했다.
_STOCK_STATUS_ROW_HTML = """<tr bgcolor=white height='20' align=center>	
	<td align=center><input type='radio' name='gigung' value='0' ></td>
	<td align=center>0 <input type='hidden' name='pd_no[0]' size='3' value='97820'></td>	
	<td align=center><b> 재고있음</b> <p style='margin-top:5px;'>Tv8 <br>전화 : <br>발주번호 : 010-0000-1008 <a href="javascript:na_open_window('sms', '/adm/sms.php?reserve_phone=010-0000-1008&send_phone=1644-0249&msg=&od_no=&group=', 100,100, 250, 480, 0, 0, 0, 0, 0)"><img src='/img/b_sub10.gif' align=absmiddle></a> <a href='/adm_cate/price_my_list_admin.php?companyid=Tv8' target='_blank' class='bx_bl'>관</a>&nbsp; <!--  재고있음Tv8 --></td>		
	<td><select name=ment[0]><option value='0' selected>판매중</option><option value='1'  style=background:#F0E09D;>품절</option><option value='2'  style=background:#FF5959;>단종</option></select></td>
	<td><input type='text' name='price1[0]' size='7' value='41,000'  style='ime-mode:disabled;text-align:right;' onkeydown='onlyNum()' onkeyup='tranNum.call(this);'  onblur='change_money(0,this.value);'> </td>
	<td><input type='text' name='pp_rebate_per[0]' size='3' value='' onblur='change_percent(0,this.value)'>%<br><input type='text' name='pp_rebate_price[0]' size='7' value='0'  onblur='change_price(0)'   style='ime-mode:disabled;text-align:right;' onkeydown='onlyNum()' onkeyup='tranNum.call(this);' >원</td>
	<td><a href='product_price_update_log.php?pd_no=97820&com_id=Tv8' target='_blank' class='bx_re'>로그보기</a><br>2026-08-26 00:00:00</td>
	<td><a href="javascript:DeleteOrder('product_price_delete.php?pd_no=97820&com_id=Tv8')">삭제</a></td>
	<td><input type='text' name='balju_price1' size='7' value='0'  style='ime-mode:disabled;text-align:right;' onkeydown='onlyNum()' onkeyup='tranNum.call(this);'  onblur=chkSaleAgency('97820','Tv8',this.value)></td>
	</tr> 
	<input type='hidden' name='kno[0]' size='7' value='Y'>
	<input type='hidden' name='o_ment[0]' size='7' value='0'>
	<input type='hidden' name='o_price1[0]' size='7' value='41000'>	
	<input type='hidden' name='com_id[0]' size='7' value='Tv8'>	
	<input type='hidden' name='o_pp_gigung[0]' size='7' value='0'>	
	<input type='hidden' name='o_pp_rebate_per[0]' size='7' value=''>
	<input type='hidden' name='o_pp_rebate_price[0]' size='7' value='0'>
"""

# (idx, 회사명, 공급가, 상태원문) -- 2026-08-26 하네스 실측 8행 그대로.
_EXPECTED_ROWS = [
    (0, "(주)메종시스템", 278490, "판매중"),
    (1, "(주)에스티테크놀로지이노베이션", 280000, "판매중"),
    (2, "(주)파인인포", 304000, "판매중"),
    (3, "주식회사 로아컴퍼니스", 304000, "판매중"),
    (4, "(주)아인스시스템 선인", 304000, "판매중"),
    (5, "(주) 메이드시스템", 304000, "판매중"),
    (6, "주식회사 팝콘컴퓨터", 295000, "품절"),
    (7, "아이보라", 342000, "품절"),
]


def _selftest() -> bool:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  [PASS] " if cond else "  [FAIL] ") + msg)
        ok = ok and cond

    rows = parse_rows(_FIXTURE)
    check(len(rows) == 8,
          f"실측 구조 8개 공급처 행만 파싱, 9번째(업체 신규 추가용 -- pd_no 없음, select"
          f" 옵션은 자리표시자로 축약)는 걸러짐(실제 {len(rows)})")
    by_idx = {r["idx"]: r for r in rows}

    for idx, name_hint, price, state_raw in _EXPECTED_ROWS:
        r = by_idx.get(idx)
        if r is None:
            check(False, f"행{idx} 파싱됨(실제: 없음)")
            continue
        check(r["o_price"] == price, f"행{idx} 공급가={price}(실제 {r['o_price']})")
        check(r["state_raw"] == state_raw,
              f"행{idx} 상태원문={state_raw}(실제 {r['state_raw']})")
        check(r["state"] == STATE_MAP[state_raw],
              f"행{idx} 상태정규화={STATE_MAP[state_raw]}(실제 {r['state']})")
        check(r["order_price"] is None,
              f"행{idx} 발주가는 행 구분 불가라 NULL(실제 {r['order_price']})")
        check(bool(r["contact_blob"]) and name_hint in r["contact_blob"],
              f"행{idx} contact_blob에 회사명 포함(실제 {r['contact_blob']!r})")
        check(not re.match(r'^\d', r["contact_blob"] or ""),
              f"행{idx} contact_blob 선두 순위 숫자 제거됨(실제 {r['contact_blob']!r})")

    r7 = by_idx.get(7)
    check(bool(r7) and r7["phone"] is None,
          f"행7(아이보라) -- 실물처럼 담당자 전화번호 «값»이 없음(실제 {r7 and r7['phone']!r})"
          " -- 결함②(라벨이 아니라 값 위치로 자르면 이 행에서 다음 섹션을 통째로 삼킴)를"
          " 실제로 재현하는 조건")
    check(bool(r7) and bool(r7["order_phone"]),
          f"행7 -- 발주번호는 실물처럼 값이 있음(실제 {r7 and r7['order_phone']!r})")
    # 임계값 60 -- 정상 행의 contact_blob은 "회사명 계정코드 통합관리자" 정도라
    # 실측 17~31자(실물 8행) 안팎이다. 처음엔 200으로 뒀는데(옛 픽스처 상속) 이건
    # «일부러 깨뜨려» 재보니 무의미했다 -- 9번째 행의 select 옵션은 몇 개든
    # `_strip_select_blocks`가 통째로 지우므로, 삼켜도 늘어나는 건 그 «둘레»
    # (헤더 셀·라벨 문구) 텍스트뿐이라 길이가 옵션 수와 무관하게 대략 고정이다
    # (이 픽스처 기준 119자 -- 200 밑이라 200 임계값은 이 결함을 통과시켰다,
    # 검사가 아무것도 증명 못 하는 상태). 60으로 좁혀 정상(30자 이하)과
    # 삼킴(119자)을 실제로 가르는지 재확인했다(고치기 전 코드로 되돌려 FAIL
    # 확인 후 다시 복구).
    check(len((r7 or {}).get("contact_blob") or "") < 60,
          "마지막 실공급처 행(7)의 contact_blob이 9번째 행(업체 신규 추가 섹션 --"
          " 헤더 셀 「신규입력 지정 업체명 재고 판매가격 리베이트 등록」 등)을 삼키지"
          " 않음(행 경계·자르기 지점이 무너지면 이 값이 100자를 훌쩍 넘는다 --"
          " 2026-08-26 하네스가 실물 캐시로 처음 돌렸을 때 실제로 이렇게 났다)")

    r0, r1, r2 = by_idx.get(0), by_idx.get(1), by_idx.get(2)
    if r0:
        # 실물(2026-08-26 캐시)은 o_price1이 price1과 일치해(278490) mismatch가
        # 자연 발생하지 않는다 -- 그래서 이 행 하나만 픽스처에서 o_price1을
        # 999999로 의도적으로 바꿔 mismatch 판정 경로를 확인한다(_ROW_ARGS 주석 참조).
        check(r0["price_mismatch"] is True,
              f"행0 -- o_price1(의도적으로 999999)과 price1(278,490)이 달라"
              f" mismatch=True(실제 {r0['price_mismatch']})")
        sid, sname, remainder, kind = resolve_supplier(r0["contact_blob"], _FIXTURE_SUPPLIERS)
        check(sid == 501 and kind == "contains",
              f"행0 공급처 매칭->501/contains(실제 {sid}/{kind}, remainder={remainder!r})")
    if r1:
        # 리베이트도 실물 8행 전부 공란이라 이 행만 1.5%/4200원으로 의도적으로
        # 채워 `_to_pct`/`_to_int` 파싱을 확인한다(_ROW_ARGS 주석 참조).
        check(r1["rebate_pct"] == 1.5, f"행1 rebate_pct=1.5(실제 {r1['rebate_pct']})")
        check(r1["price_mismatch"] is False,
              f"행1 -- o_price1(280000)과 price1(280,000)이 실물처럼 일치 ->"
              f" mismatch=False(실제 {r1['price_mismatch']})")
        sid2, _n2, _r2, kind2 = resolve_supplier(r1["contact_blob"], _FIXTURE_SUPPLIERS)
        check(sid2 == 502, f"행1 공급처 매칭->502(실제 {sid2}/{kind2})")
    if r2:
        check(r2["price_mismatch"] is False,
              f"행2 -- o_price1(같은 세그먼트 안, 304000)과 price1(304,000)이 실물처럼"
              f" 일치 -> mismatch=False(실제 {r2['price_mismatch']})")

    r6 = by_idx.get(6)
    if r6:
        sid6, _n6, _r6, kind6 = resolve_supplier(r6["contact_blob"], _FIXTURE_SUPPLIERS)
        check(sid6 == 507, f"행6(품절) 공급처 매칭->507(실제 {sid6}/{kind6})")

    sid3, *_ = resolve_supplier("(주)클릭나라 담당 전화 : 02-000-0000 발주번호 : 010",
                                 _FIXTURE_SUPPLIERS)
    check(sid3 == CLICK_NARA_SUPPLIER_ID, f"클릭나라 특례->id=2(실제 {sid3})")

    sid4, *_, kind4 = resolve_supplier("어디에도없는상호 전화 : 02-1-1 발주번호 : 010",
                                        _FIXTURE_SUPPLIERS)
    check(sid4 is None and kind4 == "unmatched",
          f"미등록 업체는 unmatched(실제 sid={sid4}/kind={kind4})")

    # 업체명 자리에 재고 상태값이 온 행 -- 2026-08-26 지시서 대응(공급처 매칭에서
    # "재고있음"을 새 공급처로 오인하지 않게 막는다). parse_rows()는 이 행도 정상
    # 파싱해야 한다(가격·상태는 멀쩡하다 -- 깨진 건 "회사명" 자리뿐이다). 실제 문제는
    # resolve_supplier() 단계다: unmatched가 아니라 excluded_stock_status로 갈라져야
    # 등록 후보(미매칭) 목록에 안 섞인다.
    stock_rows = parse_rows(_STOCK_STATUS_ROW_HTML)
    check(len(stock_rows) == 1, f"재고있음 행 1개 파싱(실제 {len(stock_rows)})")
    if stock_rows:
        sr = stock_rows[0]
        check(sr["o_price"] == 41000, f"재고있음 행 공급가=41000(실제 {sr['o_price']})")
        check(sr["state"] == "가능" and sr["state_raw"] == "판매중",
              f"재고있음 행 상태=가능/판매중(실제 {sr['state']}/{sr['state_raw']})"
              " -- 가격·상태 파싱 자체는 멀쩡하다, 깨진 건 회사명 자리뿐이다")
        check(bool(sr["contact_blob"]) and sr["contact_blob"].startswith("재고있음"),
              f"재고있음 행 contact_blob이 '재고있음'으로 시작(실제 {sr['contact_blob']!r})")
        sid5, sname5, rem5, kind5 = resolve_supplier(sr["contact_blob"], _FIXTURE_SUPPLIERS)
        check(sid5 is None and kind5 == "excluded_stock_status",
              f"재고있음 행 -> excluded_stock_status, unmatched 아님"
              f"(실제 sid={sid5}/kind={kind5})")

    # 경계 -- "재고나라" 같은 진짜 상호를 잘못 거르지 않는다(지시서 경고 그대로).
    # 정확히 일치가 아니므로 excluded_stock_status가 아니라 보통의 unmatched로 빠져야
    # 한다(등록 여부는 사람이 판단할 몫으로 남는다 -- 이 함수가 회사를 지우면 안 된다).
    sid6b, *_, kind6b = resolve_supplier("재고나라 전화 : 02-1-1 발주번호 : 010",
                                          _FIXTURE_SUPPLIERS)
    check(kind6b == "unmatched",
          f"'재고나라'(진짜 상호일 수 있음)는 excluded 아니고 unmatched"
          f"(실제 kind={kind6b})")
    sid6c, *_, kind6c = resolve_supplier("재고있음상사 전화 : 02-1-1 발주번호 : 010",
                                          _FIXTURE_SUPPLIERS)
    check(kind6c == "unmatched",
          f"'재고있음상사'(토큰 뒤에 공백/끝이 아닌 문자가 붙음)는 excluded 아니고"
          f" unmatched(실제 kind={kind6c})")
    sid6d, *_, kind6d = resolve_supplier("재고있음", _FIXTURE_SUPPLIERS)
    check(kind6d == "excluded_stock_status",
          f"'재고있음' 단독(꼬리 문자열 없음)도 excluded(실제 kind={kind6d})")

    # 판매중 최저가 판정(§③) -- 실측 8행은 마침 전체 최저가(278,490)가 이미 판매중이라
    # "전체 최저가가 품절에 있다"는 갈래를 못 덮는다. 그 갈래는 합성 데이터로 따로 확인한다.
    real_summ = _cheapest_summary(rows)
    check(real_summ is not None and real_summ["cheapest_overall"]["o_price"] == 278490,
          f"실측 8행 전체 최저가=278490"
          f"(실제 {real_summ and real_summ['cheapest_overall']['o_price']})")
    check(real_summ is not None and real_summ["mismatch"] is False,
          f"실측 8행은 전체 최저가가 이미 판매중이라 mismatch=False"
          f"(실제 {real_summ and real_summ['mismatch']})")

    synth_mismatch = [{"o_price": 100000, "state": "품절"},
                       {"o_price": 150000, "state": "가능"},
                       {"o_price": 200000, "state": "가능"}]
    summ = _cheapest_summary(synth_mismatch)
    check(summ is not None and summ["mismatch"] is True
          and summ["cheapest_overall"]["o_price"] == 100000
          and summ["cheapest_available"]["o_price"] == 150000,
          f"품절(100000)이 판매중(150000)보다 싸면 mismatch=True(실제 {summ})")

    synth_no_avail = [{"o_price": 100000, "state": "품절"}, {"o_price": 120000, "state": "품절"}]
    summ2 = _cheapest_summary(synth_no_avail)
    check(summ2 is not None and summ2["cheapest_available"] is None,
          f"전 공급처 품절이면 cheapest_available=None(실제 {summ2})")

    check(_cheapest_summary([{"o_price": None, "state": None}]) is None,
          "가격 있는 행이 하나도 없으면 _cheapest_summary는 None")

    print("\n" + ("전체 통과" if ok else "일부 실패") + " -- 2026-08-26(2차) 몰 원문 캐시"
          "(.cache/mall_supplier/121807.html)에서 실제 <tr> 구조를 뽑아 만든 픽스처"
          "(연락처만 자리표시자)로 상품 121807의 8개 공급처 행(회사명·공급가·상태)을"
          " 검증한다. 1차(DOM 실측 기반 합성 마크업)는 이 검증을 통과했는데도 실물 캐시"
          "에서는 실패했다(select 미인식 · 행7 연락처가 다음 섹션을 삼킴) -- 그래서"
          " 이제는 캐시 파일 원문 구조로 검증한다. --from-dir로 실제 파일을 처리한"
          " 결과와도 재대조해야 한다.")
    return ok


# ====================================================================== ==
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true",
                     help="네트워크·DB 없이 파서 자체 검증만 하고 끝낸다")
    ap.add_argument("--codes", type=str, default="",
                     help="쉼표구분 pd_no 목록(지정 시 --limit이 그 목록에 적용)")
    ap.add_argument("--limit", type=int, default=None,
                     help="대상 상한(기본: 추천 후보 전체)")
    ap.add_argument("--apply", action="store_true",
                     help="실제로 DB에 반영한다. 기본은 드라이런(DB에 쓰지 않음)")
    ap.add_argument("--refetch", action="store_true",
                     help="캐시를 무시하고 몰에 다시 요청한다")
    ap.add_argument("--from-cache", action="store_true",
                     help="(과거 방식이 남긴) 캐시된 html만 재파싱한다(네트워크 요청 0건)")
    ap.add_argument("--from-dir", type=str, default="",
                     help="네트워크 대신 이 폴더의 HTML 파일(파일명 선두 숫자=pd_no, 예:"
                          " 121807.html)을 읽어 처리한다 -- 하네스가 브라우저로 받아 둔"
                          " 파일. 2026-08-26부터 기본 경로(쿠키를 .env에 두지 않는다)")
    ap.add_argument("--reapply", action="store_true",
                     help="--apply와 함께: 이미 '반영 완료'로 기록된 상품도 다시 반영한다")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if _selftest() else 1)

    if args.from_dir and args.from_cache:
        print("오류: --from-dir와 --from-cache는 함께 쓸 수 없습니다(원천이 둘일 수 없다).")
        sys.exit(2)

    load_dotenv(os.path.join(ROOT, ".env"))
    from sqlalchemy import create_engine
    engine = create_engine(os.environ["DATABASE_URL"])

    file_map = None
    if args.from_dir:
        if not os.path.isdir(args.from_dir):
            print(f"오류: --from-dir 경로가 없습니다 -- {args.from_dir}")
            sys.exit(2)
        file_map, skipped_names = _scan_from_dir(args.from_dir)
        codes = sorted(file_map)
        if args.codes:
            want = {int(c) for c in args.codes.split(",") if c.strip()}
            codes = [c for c in codes if c in want]
        if args.limit is not None:
            codes = codes[:args.limit]
        print(f"--from-dir 파일 {len(codes)}건을 처리합니다(네트워크 요청 0건) -- {args.from_dir}")
        if skipped_names:
            print(f"  파일명 선두에서 상품번호를 못 읽어 건너뜀 {len(skipped_names)}건"
                  f" -- 예: {skipped_names[:3]}")
    elif args.from_cache:
        codes = []
        if os.path.isdir(CACHE):
            codes = sorted(int(f[:-5]) for f in os.listdir(CACHE) if f.endswith(".html"))
        print(f"캐시 파일 {len(codes)}건을 재파싱합니다(네트워크 요청 0건) -- {CACHE}")
    else:
        with engine.connect() as conn:
            codes = target_codes(conn, args.codes, args.limit)
        src = "--codes 지정" if args.codes else "추천 후보(v_recommendation_candidates)"
        print(f"수집 대상 {len(codes)}건({src}, 과거 방식 -- 세션 필요) -- 캐시 {CACHE}")

    if not args.apply:
        net = not (args.from_dir or args.from_cache)
        print("드라이런 모드입니다 -- DB에 쓰지 않습니다"
              + ("(몰에는 실제로 GET합니다)." if net else ".")
              + " 실제로 반영하려면 --apply.")
    if args.apply:
        print(f"--apply 모드입니다 -- product_supplier_prices·suppliers에 실제로 씁니다"
              f"(대상 {len(codes)}건).")

    stats, samples = run(engine, codes, args.apply, args.refetch,
                          cache_only=args.from_cache, reapply=args.reapply, file_map=file_map)
    _print_report(stats, samples, args.apply, from_dir=bool(args.from_dir))


if __name__ == "__main__":
    main()
