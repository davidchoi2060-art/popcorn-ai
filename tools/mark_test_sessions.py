# -*- coding: utf-8 -*-
"""회귀가 만든 상담 세션에 data_origin='test' 를 찍는다 (2026-08-20 사장님 승인).

■ 왜
  tests/regression.py 가 실제 상담 원장에 쌓이고 있었다. 회귀 BASE=localhost:8000 이
  배포 서버와 «같은» Cloud SQL 을 쓰고, 요청마다 새 consult_sessions 가 INSERT 된다.
  실측(2026-08-19): 6,893건 중 6,732건(97.7%)이 회귀 리터럴과 문자 그대로 일치했다.
  그 위에서 「고객이 조건 2개에서 멈춘다 92.1%」 같은 판단을 했고, 4모드 구조를
  줄일지 정하려던 근거가 통째로 무효가 됐다.

  앞으로의 오염은 어제 막았다(X-Popcorn-Test 헤더 + localhost + .env 스위치 →
  api/recommend.py 의 _resolve_data_origin). 이 스크립트는 «이미 쌓인 과거분»을 찍는다.

■ 무엇을 찍나 — 「화면이 낼 수 없는 값」만
  guided 예산 문항은 git 이력 전체에서 항상 접미사가 붙는다(「100만원 이하」).
  그래서 접미사 없는 「100만원」은 guided 화면이 구조적으로 낼 수 없다.

  ⚠ 가릴 수 없는 것은 «일부러» 안 찍는다(미판정으로 남긴다):
       guided [게임, 200만원 이상]  436건   화면이 낼 수 있는 완전한 값이다
       chat   [120만원, 고사양 게임] 669건  ┐ talk.py 프롬프트가 「숫자만원이 기본」이라
       chat   [120만원, 기타]        354건  ┘ 실고객도 접미사 없이 나온다
  확실하지 않은 것을 확실한 것처럼 다루면 나중에 그 위에서 또 판단하게 된다 —
  그게 이번 사고의 뿌리다.

■ 대상 목록의 출처
  docs/data-ops/2026-08-20_consult-sessions-test-mark.md 의 「표식한 session_id 전체
  목록」을 읽는다. 그 문서가 되돌림 안전판이고, 이 스크립트는 그것을 집행할 뿐이다.
  ⚠ 목록을 여기 하드코딩하지 않는 이유: 두 벌이 되면 갈라진다. 문서가 원천이다.

■ 쓰는 법
      .venv/Scripts/python tools/mark_test_sessions.py            # 드라이런 (기본)
      .venv/Scripts/python tools/mark_test_sessions.py --apply    # 실제 적용

  드라이런은 아무것도 쓰지 않고 「지금 찍으면 몇 건이 바뀌는지」만 보여준다.
  --apply 는 패턴별 개별 트랜잭션으로 돌고, 기대 건수와 어긋나면 그 패턴을 롤백한다.

  멱등하다 — 이미 'test' 인 행은 대상에서 빠지므로 두 번 돌려도 같다.

■ 되돌림
  docs/data-ops/2026-08-20_consult-sessions-test-mark.md §되돌림 방법 A.
  이 스크립트가 찍은 것만 정확히 되돌리려면 같은 문서의 session_id 목록을 쓴다.

■ 안 건드리는 것
  quote_snapshots · swap_event_logs · handoffs 는 세션을 FK 로 참조하므로 조인으로
  따라온다. 그 표들에는 컬럼을 더하지도, 값을 쓰지도 않는다.
"""
import argparse
import io
import os
import re
import sys

# state.py 와 같은 처방 — Windows 콘솔(cp949)에서 한글·기호가 깨지지 않게 UTF-8 고정.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace",
                                  line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "data-ops",
                   "2026-08-20_consult-sessions-test-mark.md")

HEAD_RE = re.compile(r"^###\s*패턴\s*(\d+)\s*[-–—]\s*(.+?)\s*\((\d+)건\)\s*$")
IDS_RE = re.compile(r"^[\s0-9,]+$")


def parse_doc(path):
    """안전판 문서에서 패턴별 (제목, 기대건수, id 목록) 을 뽑는다."""
    if not os.path.exists(path):
        raise SystemExit("안전판 문서를 찾지 못했다: %s" % path)
    text = io.open(path, encoding="utf-8", errors="replace").read()

    blocks, cur = [], None
    for line in text.splitlines():
        m = HEAD_RE.match(line.strip())
        if m:
            cur = {"no": int(m.group(1)), "title": m.group(2),
                   "expect": int(m.group(3)), "ids": []}
            blocks.append(cur)
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("#"):          # 다음 절로 넘어갔다
            cur = None
            continue
        if s and IDS_RE.match(s):
            cur["ids"].extend(int(x) for x in re.findall(r"\d+", s))

    if not blocks:
        raise SystemExit("문서에서 패턴 블록을 찾지 못했다 — 형식이 바뀌었는지 확인하라")

    # 문서 자신이 적은 기대 건수와 실제 목록 길이가 다르면 멈춘다.
    for b in blocks:
        if len(b["ids"]) != b["expect"]:
            raise SystemExit(
                "패턴 %d 「%s」 목록이 기대와 다르다 — 문서 %d건 / 실제 %d건. "
                "문서가 손상됐을 수 있으니 확인 전에는 적용하지 마라."
                % (b["no"], b["title"], b["expect"], len(b["ids"])))

    # 패턴끼리 겹치면 멈춘다(같은 세션을 두 번 세면 집계가 틀어진다).
    seen = {}
    for b in blocks:
        for i in b["ids"]:
            if i in seen:
                raise SystemExit("session_id %d 가 패턴 %d 와 %d 에 겹친다"
                                 % (i, seen[i], b["no"]))
            seen[i] = b["no"]
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="실제로 적용한다(기본은 드라이런)")
    args = ap.parse_args()

    sys.path.insert(0, ROOT)
    from sqlalchemy import text
    from api.db import engine

    blocks = parse_doc(DOC)
    total_expect = sum(b["expect"] for b in blocks)

    print("=" * 72)
    print("상담 세션 표식 — %s" % ("적용" if args.apply else "드라이런 (아무것도 쓰지 않는다)"))
    print("목록 출처: %s" % os.path.relpath(DOC, ROOT))
    print("=" * 72)

    with engine.connect() as c:
        before = dict(c.execute(text(
            "SELECT data_origin, count(*) FROM consult_sessions GROUP BY 1")).all())
    print("\n지금: %s" % " · ".join("%s %d" % (k, v) for k, v in sorted(before.items())))
    print("문서가 지목한 대상: %d건 (패턴 %d개)\n" % (total_expect, len(blocks)))

    changed_total = 0
    for b in blocks:
        ids = b["ids"]
        with engine.connect() as c:
            # 지금 'real' 인 것만이 실제로 바뀔 행이다(이미 test 면 대상 아님).
            todo = c.execute(text(
                "SELECT count(*) FROM consult_sessions "
                "WHERE session_id = ANY(:ids) AND data_origin = 'real'"),
                {"ids": ids}).scalar()
            missing = len(ids) - c.execute(text(
                "SELECT count(*) FROM consult_sessions WHERE session_id = ANY(:ids)"),
                {"ids": ids}).scalar()

        note = ""
        if missing:
            note = "  ⚠ 문서 목록 중 %d건이 DB 에 없다" % missing
        print("  패턴 %d  %-44s  목록 %4d · 바뀔 것 %4d%s"
              % (b["no"], b["title"][:44], len(ids), todo, note))

        if not args.apply:
            changed_total += todo
            continue

        # 적용 — 패턴 하나가 트랜잭션 하나다. 기대와 어긋나면 그 패턴만 롤백한다.
        with engine.begin() as c:
            res = c.execute(text(
                "UPDATE consult_sessions SET data_origin = 'test' "
                "WHERE session_id = ANY(:ids) AND data_origin = 'real'"),
                {"ids": ids})
            if res.rowcount != todo:
                raise SystemExit(
                    "패턴 %d 에서 예상(%d)과 실제(%d)가 다르다 — 롤백하고 멈춘다"
                    % (b["no"], todo, res.rowcount))
            changed_total += res.rowcount

    with engine.connect() as c:
        after = dict(c.execute(text(
            "SELECT data_origin, count(*) FROM consult_sessions GROUP BY 1")).all())
        # 주문은 이 표식과 무관해야 한다 — 드라이런에서 0건이었다.
        touched_orders = c.execute(text(
            "SELECT count(*) FROM orders o JOIN consult_sessions s "
            "USING (session_id) WHERE s.data_origin = 'test'")).scalar()

    print("\n" + "-" * 72)
    if args.apply:
        print("적용했다: %d건" % changed_total)
        print("지금: %s" % " · ".join("%s %d" % (k, v) for k, v in sorted(after.items())))
        print("표식된 세션에 딸린 주문: %d건 %s"
              % (touched_orders, "(정상 — 0이어야 한다)" if touched_orders == 0
                 else "⚠ 0이 아니다. 문서 §되돌림 을 보라"))
        print("\n다음: 이 결과를 안전판 문서의 「패턴 · 기대 건수 · 실제 적용 건수」 표에 적는다.")
    else:
        print("드라이런이다 — 아무것도 쓰지 않았다. 바뀔 것: %d건" % changed_total)
        print("적용하려면:  .venv/Scripts/python tools/mark_test_sessions.py --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
