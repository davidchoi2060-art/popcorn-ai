# -*- coding: utf-8 -*-
"""팝콘PC AI API 시험 실행기. 기본은 offline 이다.

    python tools/popcorn_api_runner.py                      # 가짜 API 로 29개 케이스
    python tools/popcorn_api_runner.py --out result.json
    python tools/popcorn_api_runner.py --mode live --call single --ledger L.json --out E.json

live 는 운영 몰에 price GET 을 보낸다. 문서 예시 3개 상품만, 기록부 기준 총 3회까지, 호출 간 1초 이상,
직전 호출이 비정상이면 중지한다. basket 은 live 에서 선택할 수 없다.
증거에는 허용 필드만 저장한다. 추가 필드 값과 응답 원문은 저장하지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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
LIVE_BUDGET = 3
KST = timezone(timedelta(hours=9))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PopcornPC AI API test runner")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--call", choices=tuple(LIVE_CALLS), help="live only")
    parser.add_argument("--ledger", help="live call ledger json (required for live)")
    parser.add_argument("--out", help="result json path")
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

class _Recording:
    """응답 크기·해시·형식만 기록한다. 본문은 남기지 않는다."""

    basket_write_allowed = False

    def __init__(self, inner):
        self.inner = inner
        self.meta = {}

    def get(self, url, *, timeout, max_bytes):
        response = self.inner.get(url, timeout=timeout, max_bytes=max_bytes)
        stripped = response.body.strip()
        self.meta = {"http_status": response.status, "content_type": response.content_type,
                     "bytes": len(response.body), "body_sha256": hashlib.sha256(response.body).hexdigest(),
                     "starts_with_brace": stripped.startswith(b"{"), "ends_with_brace": stripped.endswith(b"}")}
        return response


def _read_ledger(path: Path) -> list:
    if not path.exists():
        return []
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise SystemExit("ledger format invalid")
    return entries


def run_live(call: str | None, ledger: str | None, out: str | None) -> int:
    if call not in LIVE_CALLS or not ledger or not out:
        print("live needs --call single|triple --ledger --out", file=sys.stderr)
        return 2
    codes = LIVE_CALLS[call]
    path = Path(ledger)
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
        if len(entries) >= LIVE_BUDGET:
            print("blocked: live budget exhausted (%d)" % len(entries), file=sys.stderr)
            return 3
        if entries and entries[-1].get("outcome") != "ok":
            print("blocked: previous live call was not ok; investigate first", file=sys.stderr)
            return 3
        if entries:
            wait = 1.0 - (time.time() - entries[-1]["epoch"])
            if wait > 0:
                time.sleep(wait)
        entry = {"seq": len(entries) + 1, "at": _now(), "epoch": time.time(), "api": "price",
                 "pd_nos": list(codes), "outcome": "started"}
        entries.append(entry)
        _write_json(str(path), entries)     # 나가기 전에 먼저 적는다. 죽어도 호출 수가 남는다
        recording = _Recording(M.LivePriceTransport(max_calls=1))
        evidence = {"at": entry["at"], "seq": entry["seq"], "target": "real price GET (production mall, read only)",
                    "real_basket": "not_run", "url_masked": M.mask_url(M.build_price_url(codes)), "pd_nos": list(codes)}
        try:
            result = M.fetch_prices(codes, transport=recording)
        except M.MallApiError as exc:
            failure = {"http_status": exc.http_status, **recording.meta, "outcome": "error", "code": exc.code,
                       "detail": exc.detail}
            entry.update(failure)
            evidence.update(failure)
            print("live error code=%s status=%s detail=%s" % (exc.code, failure["http_status"], exc.detail))
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


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.mode == "offline":
        if args.call or args.ledger:
            print("--call/--ledger are live only", file=sys.stderr)
            return 2
        return run_offline(args.out)
    return run_live(args.call, args.ledger, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
