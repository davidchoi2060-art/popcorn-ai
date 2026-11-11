# -*- coding: utf-8 -*-
"""팝콘PC AI API 시험 실행기. 기본은 offline 이다.

    python tools/popcorn_api_runner.py                      # 가짜 API 로 29개 케이스
    python tools/popcorn_api_runner.py --out result.json
    python tools/popcorn_api_runner.py --mode live --call single --ledger L.json --out E.json
    python tools/popcorn_api_runner.py --mode live --call single --ledger L.json --out E.json --resume-reason "사유"

live 는 운영 몰에 price GET 을 보낸다. 문서 예시 3개 상품만, 기록부 기준 누적 10회까지, 호출 간 1초 이상이다.
직전 호출이 비정상이면 멈추고, 사유를 적은 --resume-reason 이 있을 때만 같은 기록부에 이어 간다.
새 기록부는 --init-ledger 를 줘야 만든다. basket 은 사용자가 승인한 1회 시험(--api basket)만 있고 ok 인 price 직후에만 나간다.
증거에는 허용 필드만 저장한다. 추가 필드 값과 응답 원문은 저장하지 않는다.
비정상 응답 본문은 메모리에서만 분류하고 고정 종류와 글자 모양만 남긴다. 본문의 단어는 어떤 형태로도 남기지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import mall_ai_api as M    # noqa: E402

LIVE_CODES = ("124401", "124407", "124409")
LIVE_CALLS = {"single": LIVE_CODES[:1], "triple": LIVE_CODES}
# 사용자 작업용 내부 상한이다(2026-11-09 사용자 지시, 누적). API 공식 제한이 아니다. 공식 제한은 호출당 상품 50개다.
INTERNAL_RUNNER_LIVE_BUDGET = 10
RESUME_REASON_MIN_CHARS = 8
# 2026-11-11 사용자가 직접 승인한 실제 basket 시험. 기록부 전체에서 한 번뿐이고 주문·결제 경로는 없다.
INTERNAL_RUNNER_BASKET_BUDGET = 1
BASKET_APPROVAL_MIN_CHARS = 8
_SAFE_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,23}")
KST = timezone(timedelta(hours=9))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PopcornPC AI API test runner")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--call", choices=tuple(LIVE_CALLS), help="live only")
    parser.add_argument("--api", choices=("price", "basket"), default="price",
                        help="live only: basket is one user-approved write to the real mall basket")
    parser.add_argument("--basket-approval", help="basket only: the user's approval, recorded in the ledger")
    parser.add_argument("--key-out", help="basket only: new file that receives the quote key (kept out of the ledger)")
    parser.add_argument("--ledger", help="live call ledger json (required for live)")
    parser.add_argument("--out", help="result json path")
    parser.add_argument("--resume-reason", help="live only: why to continue after an abnormal call (recorded)")
    parser.add_argument("--init-ledger", action="store_true", help="live only: create a new ledger (must not exist)")
    parser.add_argument("--request-profile", choices=sorted(M.REQUEST_PROFILES), default="default",
                        help="live only: request headers, to separate client effects from server behaviour")
    return parser


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _write_json(path: str, document) -> None:
    def default(value):
        if isinstance(value, Decimal):
            return str(value)
        raise TypeError(type(value).__name__)

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(document, ensure_ascii=False, indent=2, default=default), encoding="utf-8")


# ---------------------------------------------------------------- offline

class _Collector(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows = []

    def _add(self, test, status):
        self.rows.append((test.id().split(".")[-1], status))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._add(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._add(test, "fail")

    def addError(self, test, err):
        super().addError(test, err)
        self._add(test, "error")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._add(test, "skip")


def run_offline(out: str | None) -> int:
    from tests import test_popcorn_pc_api_20261109 as cases
    suite = unittest.defaultTestLoader.loadTestsFromModule(cases)
    result = _Collector()
    suite.run(result)
    table = {}
    for name, status in result.rows:
        parts = name.split("_")
        if len(parts) > 1 and parts[1] in cases.CASE_IDS:
            table[parts[1]] = {"status": status, "test": name}
    report = {
        "at": _now(), "mode": "offline", "target": "in-memory fake / local block only",
        "real_basket": "not_run", "real_network_attempts": cases._net["attempts"],
        "live_part_not_covered_here": ["P01", "P02", "P12"],    # 실제 price 몫은 호출 기록부로 따로 본다
        "cases": {cid: table.get(cid, {"status": "not_run"}) for cid in cases.CASE_IDS},
        "tests_total": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped),
    }
    for cid, row in report["cases"].items():
        print("%s %s" % (cid, row["status"]))
    print("tests=%d failures=%d errors=%d skipped=%d real_basket=not_run" % (
        result.testsRun, len(result.failures), len(result.errors), len(result.skipped)))
    for test, trace in result.failures + result.errors:
        print("---- %s\n%s" % (test.id(), trace))
    if out:
        _write_json(out, report)
    ok = result.wasSuccessful() and not result.skipped and all(r["status"] == "pass" for r in report["cases"].values())
    return 0 if ok else 1


# ---------------------------------------------------------------- live (price only)

_IPV4_RE = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")
_DENY_WORDS = ("denied", "forbidden", "not allowed", "not permitted", "unauthorized", "blocked", "refused",
               "접근", "거부", "차단", "권한", "불가")
_ALLOWLIST_WORDS = ("whitelist", "allowlist", "allowed ip", "ip not", "허용", "아이피", "등록된 ip", "허가")
_DEBUG_WORDS = ("debug", "var_dump", "print_r", "array(", "notice:", "warning:", "fatal error", "stack trace", "sql")
_SCAN_CHARS = 4096
_SHAPE_MAX_CHARS = 64


def _shape(text: str) -> str:
    """글자 종류만 남긴다. 숫자 9, 영문 a, 그 밖의 글자 가, 공백 _, 기호는 그대로."""
    out = []
    for ch in text:
        if ch.isascii() and ch.isdigit():
            out.append("9")
        elif ch.isascii() and ch.isalpha():
            out.append("a")
        elif ch.isspace():
            out.append("_")
        elif ch.isascii():
            out.append(ch)
        else:
            out.append("가")
    return "".join(out)


def _resolve_server_ips() -> set:
    try:
        return {info[4][0] for info in socket.getaddrinfo(M.API_HOST, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return set()


def _local_ips() -> set:
    try:
        return {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, proto=socket.IPPROTO_TCP)}
    except OSError:
        return set()


def _ipv4_relation(found: list) -> list:
    """응답의 IP 가 무엇인지 메모리에서 비교한다. 값이 아니라 관계만 돌려준다."""
    server, local = _resolve_server_ips(), _local_ips()
    rows = []
    for raw in found[:4]:
        address = ipaddress.ip_address(raw)
        rows.append({"is_private": address.is_private, "matches_mall_server_dns": raw in server,
                     "matches_local_interface": raw in local})
    return rows


def _json_values(text: str) -> list:
    """앞에서부터 JSON 값의 종류를 읽는다. 값 자체는 돌려주지 않는다."""
    decoder = json.JSONDecoder()
    kinds, pos = [], len(text) - len(text.lstrip())
    while pos < len(text) and len(kinds) < 16:
        try:
            value, end = decoder.raw_decode(text, pos)
        except ValueError:
            kinds.append("not_json")
            break
        kinds.append(type(value).__name__)
        pos = end + len(text[end:]) - len(text[end:].lstrip())
    return kinds


def classify_body(body: bytes) -> dict:
    """비정상 응답을 메모리에서만 분류한다. 값이 아니라 종류와 모양만 돌려준다."""
    result = {"kind": "plain_text_other", "ipv4_count": 0, "keyword_groups": []}
    if not body.strip():
        result["kind"] = "empty"
        return result
    try:
        text = body[3:].decode("utf-8") if body.startswith(b"\xef\xbb\xbf") else body.decode("utf-8")
    except UnicodeDecodeError:
        result["kind"] = "non_utf8"
        return result
    stripped = text.strip()
    scan = stripped[:_SCAN_CHARS]
    lowered = scan.lower()
    ips = _IPV4_RE.findall(scan)
    result["ipv4_count"] = len(ips)
    groups = {"deny": _DENY_WORDS, "allowlist": _ALLOWLIST_WORDS, "debug": _DEBUG_WORDS}
    result["keyword_groups"] = [g for g, words in groups.items() if any(w in lowered for w in words)]
    kinds = _json_values(scan) if len(stripped) <= _SCAN_CHARS else []
    result["json_value_kinds"] = kinds
    result["leading_whitespace"] = len(text) - len(text.lstrip())
    result["trailing_whitespace"] = len(text) - len(text.rstrip())
    if ips:
        result["ipv4_relation"] = _ipv4_relation(ips)
    if len(stripped) <= _SHAPE_MAX_CHARS:
        result["shape"] = _shape(stripped)
    if stripped.startswith("<"):
        result["kind"] = "html"
    elif M.IP_ERROR_BODY_RE.fullmatch(text):
        result["kind"] = "ip_error"     # 관측된 전체 문구와 정확히 같을 때만. 고정 라벨이라 본문을 옮기지 않는다
    elif len(kinds) == 1 and kinds[0] != "not_json":
        result["kind"] = "json_document"
    elif len(kinds) > 1 and all(k in ("dict", "list") for k in kinds):
        result["kind"] = "concatenated_json"
    elif ips and _IPV4_RE.fullmatch(stripped):
        result["kind"] = "ipv4_only"
    elif "allowlist" in result["keyword_groups"]:
        result["kind"] = "ip_allowlist_error"
    elif "deny" in result["keyword_groups"]:
        result["kind"] = "access_denied"
    elif ips:
        result["kind"] = "ipv4_with_text"
    elif "debug" in result["keyword_groups"]:
        result["kind"] = "debug_output"
    return result


class _Recording:
    """응답 크기·해시·형식과 분류만 기록한다. 본문은 남기지 않는다."""

    def __init__(self, inner, prior_entries=(), *, keep_hash=True):
        self.inner = inner
        self.prior_entries = prior_entries
        self.keep_hash = keep_hash
        self.basket_write_allowed = getattr(inner, "basket_write_allowed", False) is True
        self.meta = {}
        self.last_body = None       # 메모리 전용. 어디에도 쓰지 않는다

    def get(self, url, *, timeout, max_bytes):
        response = self.inner.get(url, timeout=timeout, max_bytes=max_bytes)
        self.last_body = response.body
        stripped = response.body.strip()
        digest = hashlib.sha256(response.body).hexdigest()
        try:
            diagnosis = classify_body(response.body)
        except Exception as exc:    # 진단이 죽어 호출 기록을 잃지 않게 한다(API-011)
            diagnosis = {"kind": "classifier_error", "error": type(exc).__name__}
        self.meta = {"http_status": response.status, "content_type": response.content_type,
                     "bytes": len(response.body), "starts_with_brace": stripped.startswith(b"{"),
                     "ends_with_brace": stripped.endswith(b"}"), "diagnosis": diagnosis,
                     "same_body_as_seq": [e["seq"] for e in self.prior_entries if e.get("body_sha256") == digest]}
        if not self.keep_hash:
            self.meta["body_sha256_withheld"] = "basket body carries the quote key"
        elif (diagnosis.get("ipv4_count") or diagnosis["kind"] == "classifier_error"
                or len(stripped) <= _SHAPE_MAX_CHARS):
            self.meta["body_sha256_withheld"] = "short body can be recovered from its hash"
        else:
            self.meta["body_sha256"] = digest
        return response


def _read_ledger(path: Path) -> list:
    if not path.exists():
        return []
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise SystemExit("ledger format invalid")
    if [e.get("seq") for e in entries] != list(range(1, len(entries) + 1)):
        raise SystemExit("ledger seq broken: entries must stay in place")
    return entries


def run_live(call: str | None, ledger: str | None, out: str | None, *, resume_reason: str | None = None,
             init_ledger: bool = False, request_profile: str = "default") -> int:
    if call not in LIVE_CALLS or not ledger or not out:
        print("live needs --call single|triple --ledger --out", file=sys.stderr)
        return 2
    codes = LIVE_CALLS[call]
    path = Path(ledger)
    if init_ledger == path.exists():    # 없는 파일로 예산을 새로 시작하지 않는다
        print("blocked: --init-ledger is only for a ledger that does not exist yet, and is required for one",
              file=sys.stderr)
        return 3
    lock = path.with_name(path.name + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)    # 동시 실행 0
    except FileExistsError:
        print("blocked: another live run holds the ledger lock", file=sys.stderr)
        return 3
    os.close(fd)
    try:
        entries = _read_ledger(path)
        if len(entries) >= INTERNAL_RUNNER_LIVE_BUDGET:
            print("blocked: internal runner budget exhausted (%d)" % len(entries), file=sys.stderr)
            return 3
        abnormal = bool(entries) and entries[-1].get("outcome") != "ok"
        reason = (resume_reason or "").strip()
        if abnormal and len(reason) < RESUME_REASON_MIN_CHARS:
            print("blocked: previous live call was not ok; give --resume-reason to continue", file=sys.stderr)
            return 3
        if reason and not abnormal:
            print("blocked: --resume-reason is only for continuing after an abnormal call", file=sys.stderr)
            return 3
        if entries:
            wait = 1.0 - (time.time() - entries[-1]["epoch"])
            if wait > 0:
                time.sleep(wait)
        entry = {"seq": len(entries) + 1, "at": _now(), "epoch": time.time(), "api": "price",
                 "pd_nos": list(codes), "outcome": "started", "request_profile": request_profile,
                 "actual_basket_calls": 0, "body_persisted": False}
        if abnormal:
            entry["resume"] = {"reason": reason, "after_seq": entries[-1]["seq"], "after_code": entries[-1].get("code")}
        prior = list(entries)
        entries.append(entry)
        _write_json(str(path), entries)     # 나가기 전에 먼저 적는다. 죽어도 호출 수가 남는다
        recording = _Recording(M.LivePriceTransport(max_calls=1, request_profile=request_profile), prior)
        evidence = {"at": entry["at"], "seq": entry["seq"], "target": "real price GET (production mall, read only)",
                    "real_basket": "not_run", "url_masked": M.mask_url(M.build_price_url(codes)), "pd_nos": list(codes)}
        try:
            result = M.fetch_prices(codes, transport=recording)
        except M.MallApiError as exc:
            failure = {"http_status": exc.http_status, **recording.meta, "outcome": "error", "code": exc.code,
                       "detail": exc.detail}
            entry.update(failure)
            evidence.update(failure)
            print("live error code=%s status=%s detail=%s diagnosis=%s" % (
                exc.code, failure["http_status"], exc.detail, json.dumps(recording.meta.get("diagnosis"))))
            return_code = 1
        else:
            entry.update(recording.meta)
            entry.update(outcome="ok", missing=list(result.missing), dropped_field_count=result.dropped_field_count)
            evidence.update(outcome="ok", transport=recording.meta, allowed_fields_raw=list(result.allowed_raw),
                            parsed=result.public())
            print("live ok requested=%d missing=%d dropped_fields=%d observed=%s" % (
                len(codes), len(result.missing), result.dropped_field_count, dict(result.observed)))
            return_code = 0
        _write_json(str(path), entries)
        _write_json(out, evidence)
        return return_code
    finally:
        os.unlink(lock)


class _LiveBasketOnce(M.LivePriceTransport):
    """사용자가 승인한 시험 전용. 미리 정한 basket 주소 하나를 정확히 한 번만 보낸다. 재시도가 없다."""

    def __init__(self, expected_url: str, *, opener=None):
        super().__init__(max_calls=1, opener=opener)
        self._expected = expected_url
        self.basket_write_allowed = True

    def get(self, url, *, timeout, max_bytes):
        if url != self._expected or not url.startswith(M.API_URL + "?api_id=basket&") or self._calls:
            raise M.MallApiError("basket_write_blocked")
        self._calls += 1
        return self._send(url, timeout, max_bytes)


def _names(mapping) -> list:
    return sorted(k for k in mapping if isinstance(k, str) and _SAFE_NAME_RE.fullmatch(k))


def basket_shape(body, key: str) -> dict:
    """basket 응답의 구조만 적는다. 키 이름과 타입, 링크가 기대와 같은지만 남기고 값은 남기지 않는다."""
    try:
        text = (body or b"").decode("utf-8-sig")
        document = json.loads(text)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return {"json": False}
    if not isinstance(document, dict):
        return {"json": True, "top_type": type(document).__name__}
    shape = {"json": True, "top_keys": _names(document), "other_top_key_count": len(document) - len(_names(document)),
             "result_type": type(document.get("result")).__name__, "result_is_ok": document.get("result") == "ok",
             "has_error": "error" in document}
    link = document.get("link")
    shape["link"] = {"type": type(link).__name__}
    if isinstance(link, str):
        expected = M.expected_link(key)
        shape["link"].update(equals_expected=link == expected, starts_with_origin=link.startswith(M.ORIGIN + "/"),
                             has_basket_path=M.BASKET_LINK_PATH in link, has_key=key in link,
                             length_delta=len(link) - len(expected))
    items = document.get("items")
    shape["items"] = {"type": type(items).__name__}
    if isinstance(items, list):
        rows = [i for i in items if isinstance(i, dict)]
        shape["items"].update(count=len(items), dict_count=len(rows),
                              keys=sorted({k for r in rows for k in _names(r)}),
                              pd_no_types=sorted({type(r.get("pd_no")).__name__ for r in rows}),
                              qty_types=sorted({type(r.get("qty")).__name__ for r in rows}))
    return shape


def run_live_basket(call: str | None, ledger: str | None, out: str | None, *, approval: str | None = None,
                    key_out: str | None = None) -> int:
    if call not in LIVE_CALLS or not ledger or not out or not key_out:
        print("basket needs --call single|triple --ledger --out --key-out --basket-approval", file=sys.stderr)
        return 2
    codes = LIVE_CALLS[call]
    path, key_path = Path(ledger), Path(key_out)
    approval = (approval or "").strip()
    if len(approval) < BASKET_APPROVAL_MIN_CHARS:
        print("blocked: basket needs the user's approval text in --basket-approval", file=sys.stderr)
        return 3
    if not path.exists() or key_path.exists() or key_path.resolve().parent == path.resolve().parent:
        print("blocked: basket needs the existing ledger and a new --key-out file outside the ledger folder",
              file=sys.stderr)
        return 3
    lock = path.with_name(path.name + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("blocked: another live run holds the ledger lock", file=sys.stderr)
        return 3
    os.close(fd)
    try:
        entries = _read_ledger(path)
        if len(entries) >= INTERNAL_RUNNER_LIVE_BUDGET:
            print("blocked: internal runner budget exhausted (%d)" % len(entries), file=sys.stderr)
            return 3
        if sum(1 for e in entries if e.get("api") == "basket") >= INTERNAL_RUNNER_BASKET_BUDGET:
            print("blocked: the one approved basket call is already in the ledger", file=sys.stderr)
            return 3
        last = entries[-1] if entries else {}
        if not (last.get("api") == "price" and last.get("outcome") == "ok" and last.get("pd_nos") == list(codes)
                and last.get("missing") == []):
            print("blocked: basket runs only right after an ok price call for the same items", file=sys.stderr)
            return 3
        wait = 1.0 - (time.time() - last["epoch"])
        if wait > 0:
            time.sleep(wait)
        key = M.new_quote_key()
        lines = M.normalize_basket_lines(codes)
        url = M.build_basket_url(key, lines)
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(key + "\n")
        entry = {"seq": len(entries) + 1, "at": _now(), "epoch": time.time(), "api": "basket",
                 "pd_nos": list(codes), "qty_each": 1, "outcome": "started", "actual_basket_calls": 1,
                 "body_persisted": False, "key_persisted_here": False, "approval": approval,
                 "after_price_seq": last["seq"]}
        prior = list(entries)
        entries.append(entry)
        _write_json(str(path), entries)     # 나가기 전에 먼저 적는다
        recording = _Recording(_LiveBasketOnce(url), prior, keep_hash=False)
        evidence = {"at": entry["at"], "seq": entry["seq"],
                    "target": "real basket GET (production mall, one approved write, basket only)",
                    "real_basket": "run_once", "url_masked": M.mask_url(url), "pd_nos": list(codes), "qty_each": 1}
        try:
            receipt = M.BasketClient(recording).replace(key, lines)
        except M.MallApiError as exc:
            failure = {"http_status": exc.http_status, **recording.meta, "outcome": "error", "code": exc.code,
                       "outcome_unknown": exc.outcome_unknown, "detail": exc.detail,
                       "response_shape": basket_shape(recording.last_body, key)}
            entry.update(failure)
            evidence.update(failure)
            print("basket error code=%s unknown=%s status=%s shape=%s" % (
                exc.code, exc.outcome_unknown, failure["http_status"], json.dumps(failure["response_shape"])))
            return_code = 1
        else:
            done = {**recording.meta, "outcome": "ok", "lines": len(receipt.lines), "link_verified": True,
                    "response_shape": basket_shape(recording.last_body, key)}
            entry.update(done)
            evidence.update(done)
            print("basket ok lines=%d link_verified=True" % len(receipt.lines))
            return_code = 0
        _write_json(str(path), entries)
        _write_json(out, evidence)
        return return_code
    finally:
        os.unlink(lock)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.mode == "offline":
        if (args.call or args.ledger or args.resume_reason or args.init_ledger or args.request_profile != "default"
                or args.api != "price" or args.basket_approval or args.key_out):
            print("--call/--ledger/--resume-reason/--init-ledger/--request-profile/--api/--basket-approval/--key-out "
                  "are live only", file=sys.stderr)
            return 2
        return run_offline(args.out)
    if args.api == "basket":
        if args.resume_reason or args.init_ledger or args.request_profile != "default":
            print("basket takes no --resume-reason/--init-ledger/--request-profile", file=sys.stderr)
            return 2
        return run_live_basket(args.call, args.ledger, args.out, approval=args.basket_approval, key_out=args.key_out)
    if args.basket_approval or args.key_out:
        print("--basket-approval/--key-out are basket only", file=sys.stderr)
        return 2
    return run_live(args.call, args.ledger, args.out, resume_reason=args.resume_reason,
                    init_ledger=args.init_ledger, request_profile=args.request_profile)


if __name__ == "__main__":
    raise SystemExit(main())
