# -*- coding: utf-8 -*-
"""몰 공급처 행 수신 -- 브라우저가 읽은 것을 그대로 받는 자리 (2026-08-26 신설).

■ 왜 있나
  몰의 공급처 화면(`/adm_cate/product_com_list.php?pd_no=`)은 **사장님이 로그인해
  두신 브라우저**에서만 읽힌다 -- 쿠키를 파일(`.env`)에 두지 않기로 했다(2026-08-26
  사장님 확정 · CLAUDE.md §데이터 원천③ · decision-log A-114). 그래서 흐름은:

      브라우저(몰 세션)  ->  몰 페이지를 읽고 pd_no 있는 <tr>만 추려  ->  이 엔드포인트로 POST

  전에는 그 "우리 서버로 POST"할 자리가 없었다. 하네스가 결과를 대화창으로 옮기는
  방법은 못 쓴다 -- 2,959개 상품이면 20MB가 넘는다.

■ 파싱은 여기서 다시 짜지 않는다
  `api/mall_supplier_parse.py`(원래 tools/mall_supplier_fetch.py 안에 있던 것을
  2026-08-26에 공용 자리로 옮겼다 -- 그 파일 docstring 참조)를 그대로 import해서
  쓴다. tools/mall_supplier_fetch.py(CLI, --from-dir)와 이 파일(HTTP)이 같은
  parse_rows·resolve_supplier·PSP_UPSERT를 공유한다 -- 두 벌을 두면 반드시
  갈라진다(CANON.md §1).

■ 이 엔드포인트가 건드리는 것 / 안 건드리는 것
  건드림      product_supplier_prices(UPSERT) · suppliers 연락처(contact_name·
             contact_phone·order_phone·contact_raw·contact_fetched_at)
  안 건드림   products -- 매입가·판매가 반영(재판정)은 별도 결정·별도 실행이다
             (tools/mall_supplier_fetch.py와 동일한 경계).

■ 업체 매칭 실패를 만들지 않는다
  suppliers에 없는 업체명이 나오면 **새로 만들지 않고** `unmatched_suppliers`
  목록으로 돌려준다 -- "클릭나라"를 다른 회사로 두 번 등록했던 사고
  (docs/supplier-consolidation-2026-08-25.md)를 반복하지 않는다. 그 행은
  product_supplier_prices에도 쓰지 않는다.

■ dryrun이 기본이다
  `dryrun: true`(또는 생략)면 파싱·매칭·분류(신규/갱신/값 동일)까지 전부 수행하되
  **DB에는 아무것도 쓰지 않는다**. `dryrun: false`를 명시해야 실제로 반영한다 --
  안전한 기본값이 실수로 반영하는 사고를 막는다.

■ 안전
  ㉮ 한 번에 받는 상품 수 상한(MAX_ITEMS) -- 넘으면 요청 전체를 400으로 거부한다.
  ㉯ 상품별 rows_html 길이 상한(MAX_ROWS_HTML_CHARS) -- 실측(상품 121807, 공급처
     8행)은 <10KB였다. 업체 신규 추가용 select(옵션 417개)까지 통째로 포함해도
     수십 KB를 넘기지 않는다 -- 그래서 300,000자는 정상 데이터의 수십 배
     여유이면서 "페이지 전체를 잘못 붙여넣었다"류의 사고는 막는다.
  ㉰ 합계 상한(MAX_TOTAL_ROWS_HTML_CHARS) -- 상품별 상한을 다 채운 200건이 합쳐지는
     것까지 막는다(200 x 300,000 = 60,000,000자는 막되, 정상 규모인 200 x 수십 KB는
     통과한다).
  ㉱ 상품 하나가 실패(존재하지 않는 상품코드·파싱 예외·DB 예외)해도 나머지는
     계속 처리하고 `errors`에 담아 알린다 -- 한 건 때문에 전체가 롤백되지 않는다.
  ㉲ DB 예외 원문은 응답에 담지 않는다(예외 클래스 이름만) -- CLAUDE.md 규약.

■ 권한
  owner 전용. `api/auth.py`의 경로 접두어 표(`OWNER_WRITE_PREFIXES`)는 이 파일이
  건드릴 수 있는 범위 밖이라(제작팀 규약 -- 담당 파일 밖은 고치지 않는다) 등록하지
  못했다. 대신 `api/admin_ai_integration.py`가 이미 쓰고 있는 자체 가드 패턴
  (`current_operator()`로 role을 직접 검사)을 그대로 따른다 -- AI 관리 3화면이
  OWNER_WRITE_PREFIXES에 등록되기 «전에» 쓰던 것과 같은 이중 방어의 앞단이다.
  ⚠ 이 경로를 OWNER_WRITE_PREFIXES에도 추가하면 미들웨어 단계에서 한 번 더
  막히는 이중 가드가 된다 -- `api/auth.py` 담당자에게 넘길 사항으로 보고에 남긴다.
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, text

from .admin_orders import _log
from .auth import current_operator
from .db import engine
from .mall_supplier_parse import (
    PSP_UPSERT, SUPPLIER_CONTACT_UPDATE, cheapest_summary, load_suppliers, parse_rows,
    resolve_supplier,
)

router = APIRouter(prefix="/api/admin")

# 근거는 모듈 docstring §안전 참조.
MAX_ITEMS = 200
MAX_ROWS_HTML_CHARS = 300_000
MAX_TOTAL_ROWS_HTML_CHARS = 8_000_000

# product_supplier_prices에서 "값이 실제로 달라졌는가"를 판정할 때 대조하는 컬럼.
_COMPARE_COLS = ("cost_price", "supply_state", "mall_rank", "rebate_price",
                  "order_price", "mall_state_raw")


class _IngestItem(BaseModel):
    # 모르는 필드는 조용히 무시하지 않는다 -- 보낸 쪽이 성공했다고 믿게 두면 안 된다.
    model_config = ConfigDict(extra="forbid")
    product_code: int
    rows_html: str


class _IngestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dryrun: bool = True
    items: list[_IngestItem]


def _require_owner() -> dict:
    """api/admin_ai_integration.py의 자체 가드와 같은 패턴(모듈 docstring §권한 참조)."""
    op = current_operator()
    if op is None or op.get("role") != "owner":
        raise HTTPException(
            403, f"권한이 부족합니다 (필요: owner, 현재: {op['role'] if op else '로그인 필요'})")
    return op


def _known_product_codes(conn, codes: list[int]) -> set:
    if not codes:
        return set()
    rows = conn.execute(text(
        "SELECT product_code FROM products WHERE product_code IN :codes"
    ).bindparams(bindparam("codes", expanding=True)), {"codes": codes}).scalars().all()
    return set(rows)


def _existing_psp_rows(conn, codes: list[int]) -> dict:
    """이번 배치의 상품코드들에 대해 이미 있는 (product_code, supplier_id) 행을
    한 번에 읽어온다 -- 상품마다 SELECT를 반복하지 않는다."""
    if not codes:
        return {}
    rows = conn.execute(text(
        "SELECT product_code, supplier_id, cost_price, supply_state, mall_rank,"
        " rebate_pct, rebate_price, order_price, mall_state_raw"
        " FROM product_supplier_prices WHERE product_code IN :codes"
    ).bindparams(bindparam("codes", expanding=True)), {"codes": codes}).mappings().all()
    return {(r["product_code"], r["supplier_id"]): dict(r) for r in rows}


def _classify(prev: dict | None, new_vals: dict) -> str:
    """"new" · "updated" · "unchanged" 셋 중 하나.

    rebate_pct는 DB가 NUMERIC(6,3)(Decimal)로 돌려주고 새 값은 float라 반올림
    비교한다 -- 그 외 컬럼(정수·문자열)은 직접 비교로 충분하다."""
    if prev is None:
        return "new"
    for k in _COMPARE_COLS:
        if prev.get(k) != new_vals.get(k):
            return "updated"
    pv, nv = prev.get("rebate_pct"), new_vals.get("rebate_pct")
    if (pv is None) != (nv is None):
        return "updated"
    if pv is not None and round(float(pv), 3) != round(float(nv), 3):
        return "updated"
    return "unchanged"


@router.post("/mall-supplier/ingest")
def ingest(body: _IngestBody):
    """브라우저가 읽은 상품별 공급처 행(rows_html)을 받아 파싱·매칭·반영한다.

    응답은 이번 호출 하나가 무엇을 했는지를 말한다 -- 누적 통계가 아니다."""
    _require_owner()

    if len(body.items) > MAX_ITEMS:
        raise HTTPException(
            400, f"한 번에 받는 상품 수는 {MAX_ITEMS}건까지입니다(받은 {len(body.items)}건)")
    for it in body.items:
        if len(it.rows_html) > MAX_ROWS_HTML_CHARS:
            raise HTTPException(
                400, f"상품 {it.product_code}의 rows_html이 상한"
                     f"({MAX_ROWS_HTML_CHARS:,}자)을 넘었습니다({len(it.rows_html):,}자)")
    total_chars = sum(len(it.rows_html) for it in body.items)
    if total_chars > MAX_TOTAL_ROWS_HTML_CHARS:
        raise HTTPException(
            400, f"받은 rows_html 합계({total_chars:,}자)가 상한"
                 f"({MAX_TOTAL_ROWS_HTML_CHARS:,}자)을 넘었습니다")

    dryrun = body.dryrun
    codes = [it.product_code for it in body.items]
    observed = datetime.now()

    with engine.connect() as conn:
        known = _known_product_codes(conn, codes)
        suppliers = load_suppliers(conn)
        existing_psp = _existing_psp_rows(conn, codes)

    totals = {"new": 0, "updated": 0, "unchanged": 0}
    parsed_rows_total = 0
    unusable_rows = 0
    unmatched_suppliers: dict = {}
    # 업체명 자리에 재고 상태값("재고있음" 등)이 온 행 -- 공급처가 아니라서 매칭을
    # 시도하지 않는다(mall_supplier_parse.STOCK_STATUS_TOKENS). unmatched_suppliers와
    # 섞으면 화면이 "새 공급처로 등록해야 하나"로 오인한다 -- tools/mall_supplier_fetch.py
    # (CLI)와 같은 구분을 이 엔드포인트에도 둔다(두 벌이면 갈라진다, CANON.md 참조).
    excluded_stock_status_rows = 0
    cheapest_mismatch_products = 0
    errors = []

    for it in body.items:
        pc = it.product_code
        try:
            if pc not in known:
                errors.append({"product_code": pc, "error": "products에 없는 상품코드입니다"})
                continue

            rows = parse_rows(it.rows_html)
            parsed_rows_total += len(rows)

            summ = cheapest_summary(rows)
            if summ is not None and summ["mismatch"]:
                cheapest_mismatch_products += 1

            # (supplier_id, supplier_name, contact 잔여, row, 분류)
            plan = []
            for r in rows:
                # 상태를 모르거나(select 미인식) 가격이 없으면 반영 대상이 아니다 --
                # tools/mall_supplier_fetch.py의 반영 조건과 동일(모르는 것을 지어내지 않는다).
                if r["state"] is None or r["o_price"] is None:
                    unusable_rows += 1
                    continue
                sid, sname, remainder, kind = resolve_supplier(r["contact_blob"], suppliers)
                if kind == "excluded_stock_status":
                    excluded_stock_status_rows += 1
                    continue
                if sid is None:
                    label = r["contact_blob"] or "(빈 값)"
                    unmatched_suppliers[label] = unmatched_suppliers.get(label, 0) + 1
                    continue
                new_vals = {
                    "cost_price": r["o_price"], "supply_state": r["state"],
                    "mall_rank": r["idx"], "rebate_pct": r["rebate_pct"],
                    "rebate_price": r["rebate_price"], "order_price": r["order_price"],
                    "mall_state_raw": r["state_raw"],
                }
                classification = _classify(existing_psp.get((pc, sid)), new_vals)
                plan.append((sid, sname, remainder, r, classification))

            item_counts = {"new": 0, "updated": 0, "unchanged": 0}
            for _sid, _sname, _remainder, _r, classification in plan:
                item_counts[classification] += 1

            if not dryrun and plan:
                # 상품 하나 = 트랜잭션 하나. 이렇게 나누는 이유는 실패한 상품이 있어도
                # 나머지는 계속 처리하기 위해서다 -- 배치 전체를 한 트랜잭션으로 묶으면
                # 한 상품의 오류가 이미 반영된 다른 상품까지 롤백시킨다.
                with engine.begin() as wconn:
                    for sid, _sname, remainder, r, _classification in plan:
                        wconn.execute(PSP_UPSERT, {
                            "pc": pc, "s": sid, "cost": r["o_price"], "state": r["state"],
                            "rank": r["idx"], "rpct": r["rebate_pct"],
                            "rprice": r["rebate_price"], "oprice": r["order_price"],
                            "sraw": r["state_raw"], "fa": observed})
                        will_fill_contact = bool(remainder or r["phone"] or r["order_phone"])
                        if will_fill_contact:
                            wconn.execute(SUPPLIER_CONTACT_UPDATE, {
                                "cn": remainder, "cp": r["phone"], "op": r["order_phone"],
                                "cr": r["contact_blob"], "fa": observed, "s": sid})
                    _log(wconn, "mall_supplier_ingest", str(pc),
                         {"rows_parsed": len(rows), **item_counts}, kind="supplier")

            for k, v in item_counts.items():
                totals[k] += v
        except Exception as e:                                    # noqa: BLE001
            # DB 예외 원문을 그대로 내보내지 않는다(CLAUDE.md 규약) -- 예외 종류만 알린다.
            errors.append({"product_code": pc,
                            "error": f"{type(e).__name__} -- 처리하지 못했습니다"})

    note = (
        f"상품 {len(body.items)}건에서 공급처 행 {parsed_rows_total}건을 파싱했습니다"
        f"(신규 {totals['new']} · 갱신 {totals['updated']} · 값 동일 {totals['unchanged']})."
        + (f" 공급처가 아닌 값(업체명 자리에 재고 상태값)이라 제외한 행"
           f" {excluded_stock_status_rows}건은 등록 후보로 취급하지 않았습니다."
           if excluded_stock_status_rows else "")
        + (f" 업체명을 못 맞춘 표기 {len(unmatched_suppliers)}종은 반영하지 않았습니다."
           if unmatched_suppliers else "")
        + (f" 판매중 최저가가 전체 최저가와 다른 상품 {cheapest_mismatch_products}건입니다."
           if cheapest_mismatch_products else "")
        + (f" 처리하지 못한 상품 {len(errors)}건이 있습니다." if errors else "")
        + (" 실제로 반영하지 않았습니다(드라이런) -- dryrun:false로 다시 호출해야 반영됩니다."
           if dryrun else " product_supplier_prices·suppliers에 반영했습니다."))

    return {
        "dryrun": dryrun,
        "received_products": len(body.items),
        "parsed_rows": parsed_rows_total,
        "new_rows": totals["new"],
        "updated_rows": totals["updated"],
        "unchanged_rows": totals["unchanged"],
        "unusable_rows": unusable_rows,
        # 공급처가 아닌 값이라 제외한 행 -- unmatched_suppliers(등록 후보)와는 다른
        # 자리다. 미매칭 목록에 섞이면 화면이 "등록해야 하나"로 오인한다(지시서 요구사항).
        "excluded_non_supplier": excluded_stock_status_rows,
        "unmatched_suppliers": sorted(unmatched_suppliers),
        "cheapest_mismatch_products": cheapest_mismatch_products,
        "errors": errors,
        "note": note,
    }
