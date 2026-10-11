# -*- coding: utf-8 -*-
"""쇼핑몰 가격 -> 우리 판매가 반영의 단일 원천 (2026-10-11).

■ 두 겹 안전장치 (중헌 님 2026-10-11 지시)
      1겹 배치    관리자 엑셀 업로드(file) · 쇼핑몰 자동 갱신 하루 1~2회(auto) · 손 실행(manual)
      2겹 실시간  장바구니에 넣는 순간(cart) · 결제로 넘어가는 순간(checkout)
  어느 겹이든 판매가를 바꾸는 코드는 이 파일의 `apply_changes()` 하나다. 이력
  (product_price_history) · 확인 기록(mall_price_checks) · 되돌림 근거(활동 로그)가
  한 함수에서 함께 남는다 — 길마다 따로 쓰면 한쪽만 이력을 빠뜨린다
  (PATCH /products 가 이력을 안 남겨 46158 이력이 멈춘 전례 · admin_ui_sale_price 주석).

■ 무엇을 바꾸고 무엇을 안 바꾸나
  · products.sale_price 만 바꾼다. 매입가·마진·잠금은 건드리지 않는다.
  · 판매가가 잠긴 상품(locked_fields ? 'sale_price')은 건너뛴다 — 직접 소싱해 덮어쓴
    예외 값이다(판매가 관리 화면 규약 「기본 = 몰 가격 · 예외 = 잠근 값」).
  · 기본 범위는 완제품 PC(part_type='PC_COMPLETE')다. 부품 판매가는 지금 매입가 × 마진
    공식(단가표 반영 · 판매가 재산정 · mall_daily_sync)이 정하므로, 쇼핑몰 값으로 덮으면
    두 경로가 서로 되돌린다. 그래서 부품은 `include_parts=True` 로 열어 둘 때만 바꾼다.
  · 마진 정책·재산정 파일(admin_engine_rules · admin_reprice)은 쓰지도 부르지도 않는다.

■ 되돌리기
  배치 한 번의 이전 값을 활동 로그 한 행(action='mall_price_apply')에 남기고,
  `undo_run()` 이 그 값으로 되돌린다. 그 사이 다른 경로가 같은 상품을 또 바꿨으면
  그 상품은 건너뛴다(남의 변경을 덮지 않는다).
"""
import csv
import hashlib
import io
import json
import re
from html.parser import HTMLParser

from sqlalchemy import text

from .admin_activity_log_core import log_action
from .pricing_write_guard_core import lock_products

MOMENTS = ("file", "auto", "manual", "cart", "checkout")
BATCH_MOMENTS = ("file", "auto", "manual")
REASON_PREFIX = "mall_price_"          # product_price_history.reason = mall_price_<moment>
UNDO_SUFFIX = "_undo"                 # 되돌림 = 원래 사유 + _undo (가격 이력 화면이 이 짝으로 「되돌려짐」을 그린다)
PC_PART_TYPE = "PC_COMPLETE"
BIG_CHANGE_DEFAULT = 0.30              # 30% 넘게 움직이면 «큰 변동»으로 표시(자동 실행은 보류)

# 쇼핑몰 「상품엑셀」 열 이름. 앞의 것이 우선이다.
#   자체상품코드 = 쇼핑몰 pd_no = 우리 product_code (catalog_ingest 가 같은 열을 쓴다)
#   일반회원     = 우리 판매가로 들어가는 열 (catalog_ingest: "sp2": _int(r["일반회원"]))
CODE_COLS = ("자체상품코드", "상품번호", "pd_no", "상품코드")
PRICE_COLS = ("일반회원", "판매가", "가격")
NAME_COLS = ("상품명", "품명")
MAX_FILE_BYTES = 64 * 1024 * 1024


class PriceFileError(ValueError):
    """파일을 읽을 수 없다 — 화면에 그대로 보여 줄 문장을 담는다."""


# ================================================================ 파일 읽기 ==

def _norm(v) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\xa0", " ")).strip()


def _to_int(v):
    """'1,624,400' · 1624400.0 · '1624400원' -> 1624400. 못 읽으면 None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(round(v)) if v == v else None
    s = re.sub(r"[,\s원₩]", "", str(v))
    if re.fullmatch(r"\d+(\.0+)?", s):
        return int(float(s))
    return None


class _TableParser(HTMLParser):
    """쇼핑몰 「엑셀」 내려받기는 흔히 HTML 표를 .xls 이름으로 준다 — 표 셀만 모은다."""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(_norm("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise PriceFileError("파일 글자를 읽지 못했습니다. UTF-8 또는 EUC-KR 로 저장해 주세요.")


def _grid(raw: bytes) -> tuple[list[list], str]:
    """파일 -> (행 목록, 형식). xlsx · HTML 표(.xls) · CSV 를 받는다."""
    if raw[:4] == b"PK\x03\x04":
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception as e:                                    # noqa: BLE001
            raise PriceFileError("엑셀 파일을 열지 못했습니다: %s" % type(e).__name__)
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)], "xlsx"
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise PriceFileError("옛 엑셀(.xls) 형식은 읽지 못합니다. 엑셀에서 .xlsx 또는 CSV 로 다시 저장해 주세요.")
    txt = _decode(raw)
    if re.search(r"<\s*table", txt[:20000], re.I):
        p = _TableParser()
        p.feed(txt)
        return p.rows, "html"
    return list(csv.reader(io.StringIO(txt, newline=""))), "csv"


def _pick(header: list[str], names) -> int | None:
    for n in names:
        if n in header:
            return header.index(n)
    return None


def read_price_file(raw: bytes) -> dict:
    """쇼핑몰 상품 파일 -> {"prices": {code: price}, "names": {code: name}, ...}.

    머리글 줄은 위 10줄 안에서 상품코드 열이 있는 첫 줄이다. 가격이 비었거나 0 이하인
    줄은 «못 읽은 줄»로 세고 버린다(0원은 팔 수 있는 값이 아니다 — api/mall.py 와 같은 규칙).
    같은 상품코드가 두 번 나오면 마지막 값을 쓰고 그 사실을 센다.
    """
    if not raw:
        raise PriceFileError("빈 파일입니다.")
    if len(raw) > MAX_FILE_BYTES:
        raise PriceFileError("파일이 너무 큽니다(한도 %dMB)." % (MAX_FILE_BYTES // 1048576))
    rows, fmt = _grid(raw)
    head_i = None
    for i, r in enumerate(rows[:10]):
        header = [_norm(c) for c in r]
        if _pick(header, CODE_COLS) is not None:
            head_i = i
            break
    if head_i is None:
        raise PriceFileError("상품코드 열을 찾지 못했습니다. 다음 중 하나가 있어야 합니다: "
                             + ", ".join(CODE_COLS))
    header = [_norm(c) for c in rows[head_i]]
    ci, pi, ni = _pick(header, CODE_COLS), _pick(header, PRICE_COLS), _pick(header, NAME_COLS)
    if pi is None:
        raise PriceFileError("가격 열을 찾지 못했습니다. 다음 중 하나가 있어야 합니다: "
                             + ", ".join(PRICE_COLS))
    prices, names, bad, dup, total = {}, {}, 0, 0, 0
    for r in rows[head_i + 1:]:
        if not r or all(_norm(c) == "" for c in r):
            continue
        total += 1
        code = _to_int(r[ci]) if ci < len(r) else None
        price = _to_int(r[pi]) if pi < len(r) else None
        if code is None or code <= 0 or price is None or price <= 0:
            bad += 1
            continue
        if code in prices:
            dup += 1
        prices[code] = price
        if ni is not None and ni < len(r):
            names[code] = _norm(r[ni])[:200]
    if not prices:
        raise PriceFileError("가격을 읽은 상품이 한 건도 없습니다.")
    return {"prices": prices, "names": names, "format": fmt, "rows": total,
            "bad_rows": bad, "dup_codes": dup,
            "columns": {"code": header[ci], "price": header[pi],
                        "name": header[ni] if ni is not None else None}}


# ================================================================ 비교 계획 ==

def build_plan(conn, prices: dict, *, include_parts: bool = False,
               big_ratio: float = BIG_CHANGE_DEFAULT) -> dict:
    """{code: 쇼핑몰 가격} -> 무엇이 바뀌는지. DB 를 바꾸지 않는다(이 결과가 미리보기다)."""
    codes = sorted(int(c) for c in prices)
    rows = {}
    if codes:
        rows = {r["product_code"]: r for r in conn.execute(text(
            "SELECT product_code, product_name, part_type, sale_price, locked_fields"
            " FROM products WHERE product_code = ANY(:c)"), {"c": codes}).mappings()}
    changes, locked, same, out_scope, not_found = [], [], 0, 0, []
    for code in codes:
        p = rows.get(code)
        if p is None:
            not_found.append(code)
            continue
        if p["part_type"] != PC_PART_TYPE and not include_parts:
            out_scope += 1
            continue
        new, old = int(prices[code]), p["sale_price"]
        if old == new:
            same += 1
            continue
        item = {"product_code": code, "name": p["product_name"], "part_type": p["part_type"],
                "old": old, "new": new, "diff": None if old is None else new - old,
                "big": old is None or old <= 0 or abs(new - old) / old >= big_ratio}
        if "sale_price" in (p["locked_fields"] or []):
            locked.append(item)
        else:
            changes.append(item)
    changes.sort(key=lambda x: -(abs(x["diff"]) if x["diff"] is not None else 10 ** 12))
    return {
        "changes": changes, "locked": locked, "same": same, "out_of_scope": out_scope,
        "not_found": not_found, "include_parts": include_parts,
        "seen": len(codes), "matched": len(changes) + len(locked) + same,
        "up": sum(1 for c in changes if c["diff"] is not None and c["diff"] > 0),
        "down": sum(1 for c in changes if c["diff"] is not None and c["diff"] < 0),
        "big": sum(1 for c in changes if c["big"]),
        "token": plan_token(changes),
    }


def plan_token(changes) -> str:
    """미리보기와 적용이 같은 내용인지 대조하는 값 — 다른 파일·다른 시점의 확인을 막는다."""
    key = json.dumps(sorted((c["product_code"], c["old"], c["new"]) for c in changes))
    return hashlib.sha256(key.encode()).hexdigest()[:24]


# ================================================================ 실행 기록 ==

def start_run(conn, moment: str, *, source: str, operator_id: int, file_name: str | None = None,
              include_parts: bool = False) -> int:
    if moment not in BATCH_MOMENTS:
        raise ValueError(moment)
    return conn.execute(text(
        "INSERT INTO mall_price_runs (moment, source, file_name, include_parts, operator_id)"
        " VALUES (:m, :s, :f, :p, :op) RETURNING run_id"),
        {"m": moment, "s": source, "f": (file_name or None) and file_name[:200],
         "p": include_parts, "op": operator_id}).scalar()


def finish_run(conn, run_id: int, *, ok: bool, fail_reason: str | None = None,
               counts: dict | None = None, apply_log_id: int | None = None,
               detail: dict | None = None) -> None:
    c = counts or {}
    conn.execute(text(
        "UPDATE mall_price_runs SET finished_at=clock_timestamp(), ok=:ok, fail_reason=:fr,"
        " seen_count=:seen, matched_count=:matched, changed_count=:changed, up_count=:up,"
        " down_count=:down, held_count=:held, locked_count=:locked,"
        " apply_log_id=:log, detail=CAST(:d AS JSONB) WHERE run_id=:r"),
        {"ok": ok, "fr": (fail_reason or None) and fail_reason[:300],
         "seen": c.get("seen"), "matched": c.get("matched"), "changed": c.get("changed"),
         "up": c.get("up"), "down": c.get("down"), "held": c.get("held"),
         "locked": c.get("locked"), "log": apply_log_id,
         "d": json.dumps(detail or {}, ensure_ascii=False), "r": run_id})


_CHECK_SQL = text(
    "INSERT INTO mall_price_checks (moment, run_id, product_code, our_price, mall_price, diff,"
    " outcome, note, source_url, quote_id, visitor_ref)"
    " VALUES (:moment, :run_id, :pc, :our, :mall, :diff, :outcome, :note, :url,"
    " CAST(:quote AS UUID), :visitor) RETURNING check_id")


def record_check(conn, moment: str, product_code: int, *, our_price, mall_price, outcome: str,
                 run_id=None, note=None, source_url=None, quote_id=None, visitor_ref=None) -> int:
    """확인 한 번을 남긴다(추가만 한다)."""
    diff = (mall_price - our_price) if (mall_price is not None and our_price is not None) else None
    return conn.execute(_CHECK_SQL, {
        "moment": moment, "run_id": run_id, "pc": product_code, "our": our_price,
        "mall": mall_price, "diff": diff, "outcome": outcome,
        "note": (note or None) and note[:200], "url": (source_url or None) and source_url[:300],
        "quote": quote_id, "visitor": (visitor_ref or None) and str(visitor_ref)[:64]}).scalar()


# ================================================================ 적용 ==

def apply_changes(conn, changes: list, *, moment: str, operator_id: int, run_id=None,
                  hold_big: bool = False, quote_id=None, visitor_ref=None,
                  source_url_of=None) -> dict:
    """계획의 changes 를 반영한다. 트랜잭션은 부르는 쪽 것이다.

    상품별로: 지금 값이 계획의 old 와 다르면(그 사이 다른 경로가 바꿈) 'stale' 로 건너뛴다.
    잠겼으면 'locked', hold_big 이고 큰 변동이면 'held', 아니면 바꾸고 'changed'.
    바꾼 상품은 product_price_history(reason=mall_price_<moment>, ref_id=활동 로그)에 남긴다.
    """
    if moment not in MOMENTS:
        raise ValueError(moment)
    codes = sorted({int(c["product_code"]) for c in changes})
    lock_products(conn, codes)          # 상품 잠금 순서를 다른 가격 쓰기와 같게 둔다
    cur = {r["product_code"]: r for r in conn.execute(text(
        "SELECT product_code, sale_price, locked_fields FROM products"
        " WHERE product_code = ANY(:c)"), {"c": codes}).mappings()} if codes else {}
    todo, outcomes = [], {"changed": 0, "held": 0, "locked": 0, "stale": 0}
    rest = []
    for c in changes:
        pc = int(c["product_code"])
        now = cur[pc]
        if "sale_price" in (now["locked_fields"] or []):
            rest.append((c, "locked", "판매가가 잠겨 있어 바꾸지 않았습니다"))
        elif now["sale_price"] != c["old"]:
            rest.append((c, "stale", "확인 뒤 다른 경로가 판매가를 바꿔 건너뛰었습니다"))
        elif hold_big and c.get("big"):
            rest.append((c, "held", "변동이 커서 사람 확인을 기다립니다"))
        else:
            todo.append(c)
    log_id = None
    if todo:
        log_id = log_action(conn, "mall_price_apply", "run:%s" % run_id if run_id else moment, {
            "moment": moment, "run_id": run_id,
            "before": {str(c["product_code"]): c["old"] for c in todo},
            "after": {str(c["product_code"]): c["new"] for c in todo},
        }, kind="product", operator_id=lambda: operator_id)
        reason = REASON_PREFIX + moment
        for c in todo:
            conn.execute(text(
                "UPDATE products SET sale_price=:v, updated_at=now() WHERE product_code=:pc"),
                {"v": c["new"], "pc": c["product_code"]})
            conn.execute(text(
                "INSERT INTO product_price_history"
                " (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
                " VALUES (:pc, 'sale', :o, :n, :r, :ref, :op)"),
                {"pc": c["product_code"], "o": c["old"], "n": c["new"], "r": reason,
                 "ref": log_id, "op": operator_id})
            record_check(conn, moment, c["product_code"], our_price=c["old"], mall_price=c["new"],
                         outcome="changed", run_id=run_id, quote_id=quote_id,
                         visitor_ref=visitor_ref,
                         source_url=source_url_of(c["product_code"]) if source_url_of else None)
        outcomes["changed"] = len(todo)
    for c, outcome, note in rest:
        outcomes[outcome] += 1
        record_check(conn, moment, c["product_code"], our_price=cur[int(c["product_code"])]["sale_price"],
                     mall_price=c["new"], outcome=outcome, note=note, run_id=run_id,
                     quote_id=quote_id, visitor_ref=visitor_ref,
                     source_url=source_url_of(c["product_code"]) if source_url_of else None)
    return {"log_id": log_id, "applied": todo, **outcomes,
            "up": sum(1 for c in todo if c["diff"] is not None and c["diff"] > 0),
            "down": sum(1 for c in todo if c["diff"] is not None and c["diff"] < 0),
            "held_items": [c for c, o, _n in rest if o == "held"]}


# ================================================================ 되돌리기 ==

class UndoRefused(RuntimeError):
    pass


def undo_run(conn, run_id: int, *, operator_id: int) -> dict:
    """배치 한 번을 되돌린다. 지금 값이 그때 넣은 값과 같은 상품만 이전 값으로 돌린다."""
    run = conn.execute(text(
        "SELECT run_id, moment, apply_log_id, undone_at FROM mall_price_runs WHERE run_id=:r FOR UPDATE"),
        {"r": run_id}).mappings().first()
    if run is None:
        raise UndoRefused("실행 기록이 없습니다")
    if run["undone_at"] is not None:
        raise UndoRefused("이미 되돌린 실행입니다")
    if run["apply_log_id"] is None:
        raise UndoRefused("이 실행은 바꾼 판매가가 없습니다")
    d = conn.execute(text(
        "SELECT detail FROM admin_operator_activity_logs WHERE log_id=:l"),
        {"l": run["apply_log_id"]}).scalar()
    d = d if isinstance(d, dict) else json.loads(d)
    before = {int(k): v for k, v in d["before"].items()}
    after = {int(k): v for k, v in d["after"].items()}
    codes = sorted(before)
    lock_products(conn, codes)
    cur = dict(conn.execute(text(
        "SELECT product_code, sale_price FROM products WHERE product_code = ANY(:c)"),
        {"c": codes}).all())
    # 값이 같다는 것만으로는 부족하다 — 다른 경로가 바꿨다가 같은 값으로 돌아온 경우도 같다.
    # 이 실행이 남긴 이력 뒤에 그 상품의 판매가 이력이 또 있으면 남의 변경으로 보고 건너뛴다
    # (2026-10-11 코덱스 검수 #99 지적 반영 · 게임 등급 되돌리기와 같은 유형).
    later = {r[0] for r in conn.execute(text(
        "SELECT DISTINCT h.product_code FROM product_price_history h"
        " JOIN (SELECT product_code, MAX(history_id) AS hid FROM product_price_history"
        "        WHERE field='sale' AND ref_id=:l AND product_code = ANY(:c) GROUP BY product_code) mine"
        "   ON mine.product_code = h.product_code"
        " WHERE h.field='sale' AND h.history_id > mine.hid"),
        {"l": run["apply_log_id"], "c": codes})}
    back = [pc for pc in codes if cur.get(pc) == after[pc] and pc not in later]
    skipped = [pc for pc in codes if pc not in back]
    undo_log = log_action(conn, "mall_price_undo", "run:%s" % run_id, {
        "run_id": run_id, "ref_log_id": run["apply_log_id"],
        "restored": {str(pc): before[pc] for pc in back},
        "skipped": [str(pc) for pc in skipped],
    }, kind="product", operator_id=lambda: operator_id)
    for pc in back:
        conn.execute(text(
            "UPDATE products SET sale_price=:v, updated_at=now() WHERE product_code=:pc"),
            {"v": before[pc], "pc": pc})
        conn.execute(text(
            "INSERT INTO product_price_history"
            " (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
            " VALUES (:pc, 'sale', :o, :n, :r, :ref, :op)"),
            {"pc": pc, "o": after[pc], "n": before[pc], "r": REASON_PREFIX + run["moment"] + UNDO_SUFFIX,
             "ref": undo_log, "op": operator_id})
    conn.execute(text(
        "UPDATE mall_price_runs SET undone_at=now(), undo_log_id=:l WHERE run_id=:r"),
        {"l": undo_log, "r": run_id})
    return {"restored": len(back), "skipped": len(skipped), "skipped_codes": skipped[:50],
            "log_id": undo_log}
