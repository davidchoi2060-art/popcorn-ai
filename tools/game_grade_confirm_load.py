# -*- coding: utf-8 -*-
"""game_grade_suggestions 의 기계 제안을 사람이 재검토한 결과를 game_grade_assignments 에 확정 적재한다.

  .venv/Scripts/python tools/game_grade_confirm_load.py \
      --file D:/Hermes-Workspace/grade_decisions_2026-09-20.json --dry
  .venv/Scripts/python tools/game_grade_confirm_load.py \
      --file D:/Hermes-Workspace/grade_decisions_2026-09-20.json --apply

■ 무엇을 싣는가
  JSON 의 rows[] 한 줄 = game_grade_assignments 한 행. grade / is_confirmed=true /
  note 만 쓴다. 등급을 «이 로더가» 계산하지 않는다 - 사람이 재검토해 적어 넣은 값을
  그대로 옮길 뿐이고, 값이 없는 게임은 애초에 JSON 에 없다(지어내지 않는다).

■ 기존 확정 행은 불가침
  적재 전에 game_grade_assignments 를 통째로 스냅샷(--snapshot-dir)으로 떠 둔다.
  2026-09-15/16 에 사장님이 확정한 21행 + 미배정 GTA 1행(grade IS NULL)은
  이 로더가 만들어지기 전부터 있던 행이고, 그 game_id 가 정확히 1..22 다
  (2026-09-20 적재 직전 스냅샷 snapshot_game_grade_assignments_20260920-202250.json
  으로 실측). 그래서 PROTECTED_IDS = 1..22 를 상수로 박고, JSON 이 그중 하나라도
  가리키면 아무것도 쓰지 않고 중단한다.
  ⚠ '이미 is_confirmed 면 중단' 으로 막지 않는 이유는 멱등 때문이다 - 그렇게 하면
     이 로더가 자기가 쓴 행 때문에 두 번째 실행에서 죽는다. 보호 대상은 «이 로더
     밖에서 확정된 행»이지 «확정됐다는 사실» 이 아니다.

■ game_grade_suggestions 는 지우지 않는다
  제안은 이력이다. 이 로더는 그 표를 읽기만 한다 - JSON 의 suggested/confidence 가
  지금 DB 값과 다르면 **중단한다**. 사람이 본 제안과 DB 의 제안이 어긋난 채로
  확정하면 근거가 근거가 아니게 된다(다른 제작자가 재판정을 돌렸을 수 있다).

■ 멱등
  ON CONFLICT (game_id) DO UPDATE - 같은 파일로 두 번 돌리면 두 번째는 변경 0건으로
  보고한다(grade/note/is_confirmed 가 모두 같으면 '변경 없음'으로 센다).

■ --dry 가 기본이다
  --apply 를 명시하지 않으면 어떤 경우에도 커밋하지 않는다.

콘솔 출력은 ASCII 기호만 쓴다(서버 stdout 이 cp949).
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console        # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                        # noqa: E402
from sqlalchemy import create_engine, text             # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 이 로더가 절대 쓰지 않는 game_id - 사장님 확정 21행 + 미배정 GTA(17). 머리말 참고.
PROTECTED_IDS = frozenset(range(1, 23))

VALID_GRADES = None      # DB 에서 읽는다(game_load_grades)


def _die(msg):
    print("[FAIL] " + msg)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="실제 커밋. 없으면 --dry 와 동일(기본 dry)")
    ap.add_argument("--dry", action="store_true", help="명시적 dry-run(기본값)")
    ap.add_argument("--snapshot-dir", default="D:/Hermes-Workspace")
    args = ap.parse_args()

    apply_mode = bool(args.apply) and not args.dry
    mode = "APPLY" if apply_mode else "DRY"
    print("[mode] %s  file=%s" % (mode, args.file))

    with open(args.file, "r", encoding="utf-8") as f:
        doc = json.load(f)
    rows = doc.get("rows") or []
    if not rows:
        _die("rows[] 가 비었다")

    seen = set()
    for r in rows:
        gid = r.get("game_id")
        if gid is None or not isinstance(gid, int):
            _die("game_id 가 없거나 정수가 아니다: %r" % (r.get("name"),))
        if gid in seen:
            _die("game_id 중복: %d" % gid)
        seen.add(gid)
        if gid in PROTECTED_IDS:
            _die("game_id %d 는 PROTECTED_IDS - 사장님 확정 행이라 이 로더가 손대지 않는다" % gid)
        for k in ("name", "grade", "note", "suggested", "confidence"):
            if not r.get(k):
                _die("game_id %d: 필수 칸 '%s' 이(가) 비었다" % (gid, k))

    load_dotenv(os.path.join(ROOT, ".env"))
    url = os.environ.get("DATABASE_URL")
    if not url:
        _die("DATABASE_URL 없음")
    engine = create_engine(url, future=True)

    with engine.connect() as conn:
        grades_ok = set(conn.execute(text("SELECT grade FROM game_load_grades")).scalars().all())
        games = {r[0]: r[1] for r in conn.execute(text("SELECT game_id, name FROM games"))}
        cur = {r[0]: dict(game_id=r[0], grade=r[1], is_confirmed=r[2], note=r[3])
               for r in conn.execute(text(
                   "SELECT game_id, grade, is_confirmed, note FROM game_grade_assignments"))}
        sug = {r[0]: (r[1], r[2]) for r in conn.execute(text(
            "SELECT game_id, suggested_grade, confidence FROM game_grade_suggestions"))}

    # 스냅샷 - 적재 전 game_grade_assignments 전량.
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    snap = os.path.join(args.snapshot_dir, "snapshot_game_grade_assignments_%s.json" % stamp)
    os.makedirs(args.snapshot_dir, exist_ok=True)
    with open(snap, "w", encoding="utf-8") as f:
        json.dump(list(cur.values()), f, ensure_ascii=False, indent=1)
    print("[snapshot] %d rows -> %s" % (len(cur), snap))

    # 검증 -------------------------------------------------------------
    errs = []
    for r in rows:
        gid, nm = r["game_id"], r["name"]
        if gid not in games:
            errs.append("id=%d (%s): games 에 없는 game_id" % (gid, nm))
            continue
        if games[gid] != nm:
            errs.append("id=%d: 이름 불일치 JSON='%s' DB='%s'" % (gid, nm, games[gid]))
        if r["grade"] not in grades_ok:
            errs.append("id=%d (%s): game_load_grades 에 없는 등급 '%s'" % (gid, nm, r["grade"]))
        old = cur.get(gid)  # noqa: F841 - plan 계산에서 쓴다
        if gid not in sug:
            errs.append("id=%d (%s): game_grade_suggestions 에 제안 행이 없다" % (gid, nm))
        else:
            sg, sc = sug[gid]
            if (sg or "") != r["suggested"] or (sc or "") != r["confidence"]:
                errs.append("id=%d (%s): 제안이 DB 와 다르다 JSON=(%s,%s) DB=(%s,%s)"
                            % (gid, nm, r["suggested"], r["confidence"], sg, sc))
    if errs:
        print("[FAIL] 검증 %d 건 - 아무것도 쓰지 않는다" % len(errs))
        for e in errs:
            print("   - " + e)
        sys.exit(1)
    print("[ok] 검증 통과 %d 행 (등급 %s)" % (
        len(rows), ", ".join("%s:%d" % (g, sum(1 for r in rows if r["grade"] == g))
                             for g in sorted({r["grade"] for r in rows}))))

    # 제안을 사람이 바꾼 건 - 눈에 띄게 따로 찍는다.
    changed = [r for r in rows if r["grade"] != r["suggested"]]
    print("[changed] 사람이 제안을 바꾼 건: %d" % len(changed))
    for r in changed:
        print("   - %s (id=%d): %s -> %s" % (r["name"], r["game_id"], r["suggested"], r["grade"]))

    ins = [r for r in rows if r["game_id"] not in cur]
    upd = [r for r in rows if r["game_id"] in cur]
    same = [r for r in upd
            if cur[r["game_id"]]["grade"] == r["grade"] and cur[r["game_id"]]["note"] == r["note"]]
    print("[plan] insert=%d update=%d (그중 변경없음=%d)" % (len(ins), len(upd), len(same)))

    if not apply_mode:
        print("[DRY] 커밋하지 않았다. 실제로 쓰려면 --apply")
        return

    sql = text(
        "INSERT INTO game_grade_assignments (game_id, grade, is_confirmed, note, assigned_at)"
        " VALUES (:gid, :grade, true, :note, now())"
        " ON CONFLICT (game_id) DO UPDATE SET"
        "   grade = EXCLUDED.grade, is_confirmed = true,"
        "   note = EXCLUDED.note, assigned_at = now()")
    with engine.begin() as conn:
        for r in rows:
            conn.execute(sql, {"gid": r["game_id"], "grade": r["grade"], "note": r["note"]})
    with engine.connect() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM game_grade_assignments WHERE is_confirmed")).scalar()
        tot = conn.execute(text("SELECT count(*) FROM game_grade_assignments")).scalar()
        nsug = conn.execute(text("SELECT count(*) FROM game_grade_suggestions")).scalar()
    print("[APPLY] done. assignments total=%d confirmed=%d ; suggestions 보존=%d" % (tot, n, nsug))


if __name__ == "__main__":
    main()
