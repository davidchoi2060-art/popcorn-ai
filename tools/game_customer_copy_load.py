# -*- coding: utf-8 -*-
"""고객용 게임 상세설명 + 기계 등급 제안 로더.

  .venv/Scripts/python tools/game_customer_copy_load.py \
      --file D:/Hermes-Workspace/game_customer_copy.json --dry
  .venv/Scripts/python tools/game_customer_copy_load.py \
      --file D:/Hermes-Workspace/game_customer_copy.json

적재 대상은 0103 이 만든 두 표다.
  game_customer_copy       문구 4필드 + source_fields + confidence     (86종)
  game_grade_suggestions   기계 제안 등급 + 근거                        (65종)

■ 문구를 고치지 않는다
  JSON 에 있는 문장을 **한 글자도 바꾸지 않고** 옮긴다. 조사자가 tests/regression.py
  의 「[55] 고객 문구 수치 실재」 검사와 같은 규칙으로 GPU 모델명·fps·Hz·GB 를 전부
  DB 값과 대조해 위반 0건을 만든 문장이다. 로더가 손대면 그 검증이 무효가 된다.
  공백 strip 조차 하지 않는다(문장 끝 공백도 조사자가 쓴 그대로다).

■ 기존 값이 NULL 일 때만 채운다 (tools/game_catalog_load.py 의 관례)
  그쪽 머리 주석에 적힌 사고 - COALESCE(EXCLUDED.c, t.c) 는 «새 값이 NULL 이면
  기존 값을 지킨다»일 뿐이라 새 값이 있으면 기존을 갈아엎는다. 실제로 기존 23종에서
  48개 필드가 그렇게 덮여 고객이 읽던 격자 문구가 조사자 소개문으로 바뀌었다.

  여기선 더 위험하다 - 이 표는 **사람이 검수하고 고치는 표**다. 사장님이나 검수자가
  말투를 다듬은 문장을 재적재가 조용히 되돌리면, 되돌아간 사실조차 아무도 모른다.
  그래서 COALESCE(t.c, EXCLUDED.c) - **기존 값이 NULL 인 칸만** 채운다.
  차단된 칸은 전부 출력한다. 덮어쓰려면 --overwrite 를 명시해야 한다.

  reviewed_by / reviewed_at 은 **아예 쓰지 않는다.** 검수는 사람이 하는 일이고
  로더가 건드릴 칸이 아니다(INSERT 때도 null 로 둔다).

■ 등급 제안은 «제안»으로만 넣는다
  game_grade_assignments 를 읽지도 쓰지도 않는다. 확정 배정이 이미 있는 21종은
  JSON 이 grade_confidence='확정(...)' 으로 표시해 두었고, 그 행은 제안 표에도
  넣지 않는다 - 확정된 것을 기계가 다시 «제안»하면 승인 화면에 잡음만 는다.
  제안 65종 = 86 - 확정 21.

  suggested_grade 가 null 인 7종도 그대로 넣는다. 「기계가 판정 못 했다」는 것도
  승인 화면이 알아야 할 사실이다(비워 두면 그 게임이 목록에서 사라진다).

■ 멱등
  두 표 모두 PK 가 game_id 다. 같은 파일로 두 번 돌리면 두 번째는 기존 값이
  전부 NOT NULL 이므로 아무 칸도 바뀌지 않는다(차단 목록에만 뜬다).

콘솔 출력은 ASCII 기호만 쓴다(서버 stdout 이 cp949).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console        # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                        # noqa: E402
from sqlalchemy import create_engine, text             # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COPY_COLS = ("spec_summary_ko", "why_this_pc", "upgrade_hint", "caution",
             "source_fields", "confidence", "source_url")
SUG_COLS = ("suggested_grade", "confidence", "reason", "rule_version")

# 제안기 규칙 버전. 값이 아니라 «어느 규칙이 만든 제안인가»를 남긴다 -
# 규칙을 고친 뒤 어느 행이 낡은 제안인지 이 칸으로 가른다.
RULE_VERSION = "grade_rules/2026-09-19"


def build(items):
    copy_rows, sug_rows, notes = [], [], []
    for it in items:
        gid = it.get("game_id")
        if gid is None:
            notes.append((it.get("name"), "game_id 없음 -> 건너뜀"))
            continue
        copy_rows.append({
            "game_id": gid,
            "name": it.get("name"),
            # 문장은 손대지 않는다(strip 도 하지 않는다)
            # 빈 문자열은 «내용 없음»이지 «빈 글»이 아니다 - null 로 통일한다.
            # 조사자가 일부러 비운 칸이 있다(GTA=사양 미공개 · 스팀 인디=장르 통칭).
            # 그 칸을 ''로 두면 「채워져 있다」고 세어져 채움률 보고가 거짓이 된다.
            "spec_summary_ko": it.get("spec_summary_ko") or None,
            "why_this_pc": it.get("why_this_pc") or None,
            "upgrade_hint": it.get("upgrade_hint") or None,
            "caution": it.get("caution") or None,
            "source_fields": (json.dumps(it["source_fields"], ensure_ascii=False)
                              if it.get("source_fields") else None),
            "confidence": it.get("confidence"),
            # JSON 에 문구 전용 외부 출처 필드가 없다. 근거는 DB 컬럼(source_fields)이다.
            # 없는 URL 을 지어내지 않는다.
            "source_url": None,
        })

        gc = it.get("grade_confidence") or ""
        if gc.startswith("확정"):
            # 이미 사람이 확정한 등급이다 - 제안 표에 넣지 않는다
            continue
        sug_rows.append({
            "game_id": gid,
            "name": it.get("name"),
            "suggested_grade": it.get("grade_suggestion"),
            "confidence": gc or None,
            "reason": it.get("grade_reason"),
            "rule_version": RULE_VERSION,
        })
    return copy_rows, sug_rows, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", nargs="+", required=True, metavar="JSON")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--overwrite", action="store_true",
                    help="기존 값이 있는 칸도 덮어쓴다(기본 꺼짐)")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    items = []
    for path in args.file:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"{path}: top-level must be a JSON array")
        items.extend(data)

    copy_rows, sug_rows, notes = build(items)

    with engine.connect() as conn:
        known = {r[0]: r[1] for r in conn.execute(text("SELECT game_id, name FROM games"))}
        grades = {r[0] for r in conn.execute(text("SELECT grade FROM game_load_grades"))}
        cur_copy = {r[0]: dict(zip(COPY_COLS, r[1:])) for r in conn.execute(text(
            "SELECT game_id, " + ", ".join(COPY_COLS) + " FROM game_customer_copy"))}
        cur_sug = {r[0]: dict(zip(SUG_COLS, r[1:])) for r in conn.execute(text(
            "SELECT game_id, " + ", ".join(SUG_COLS) + " FROM game_grade_suggestions"))}

    # game_id 가 games 에 실제로 있는가 + 이름이 같은가 (JSON 이 낡았을 수 있다)
    bad = []
    for r in copy_rows + sug_rows:
        if r["game_id"] not in known:
            bad.append((r["game_id"], r["name"], "games 에 없는 game_id"))
        elif known[r["game_id"]] != r["name"]:
            bad.append((r["game_id"], r["name"],
                        f"이름 불일치(db={known[r['game_id']]!r})"))
    copy_rows = [r for r in copy_rows if r["game_id"] in known]
    sug_rows = [r for r in sug_rows if r["game_id"] in known]

    # 등급 어휘 검사 - FK 가 막긴 하지만 사유를 사람이 읽을 수 있게 먼저 본다
    for r in sug_rows:
        g = r["suggested_grade"]
        if g is not None and g not in grades:
            bad.append((r["game_id"], r["name"], f"game_load_grades 에 없는 등급 {g!r}"))

    def _same(col, old, new):
        """같은 값인가. source_fields 는 jsonb 라 DB 가 list 로 돌려준다 -
        문자열끼리 비교하면 늘 '다르다'가 나와 멱등 보고가 거짓이 된다."""
        if col == "source_fields":
            try:
                o = old if isinstance(old, (list, dict)) else json.loads(old)
                n = new if isinstance(new, (list, dict)) else json.loads(new)
                return o == n
            except (TypeError, ValueError):
                pass
        return str(old) == str(new)

    blocked = []
    for r in copy_rows:
        cur = cur_copy.get(r["game_id"], {})
        for col in COPY_COLS:
            if cur.get(col) is not None and r[col] is not None \
                    and not _same(col, cur[col], r[col]):
                blocked.append(("copy", r["name"], col))
                if not args.overwrite:
                    r[col] = None
    for r in sug_rows:
        cur = cur_sug.get(r["game_id"], {})
        for col in SUG_COLS:
            if cur.get(col) is not None and r[col] is not None \
                    and str(cur[col]) != str(r[col]):
                blocked.append(("suggestion", r["name"], col))
                if not args.overwrite:
                    r[col] = None

    print(f"input: {len(items)}")
    print(f"game_customer_copy:     rows={len(copy_rows)} "
          f"(new={sum(1 for r in copy_rows if r['game_id'] not in cur_copy)})")
    print(f"game_grade_suggestions: rows={len(sug_rows)} "
          f"(new={sum(1 for r in sug_rows if r['game_id'] not in cur_sug)})")
    mode = "OVERWRITTEN" if args.overwrite else "left as-is"
    print(f"cells with a differing existing value: {len(blocked)} ({mode})")
    for kind, name, col in blocked:
        print(f"  keep existing: [{kind}] {name}.{col}")
    for gid, name, why in bad:
        print(f"  WARN: game_id={gid} {name} reason={why}")
    for name, why in notes:
        print(f"  note: {name} {why}")

    # 채움률 - 무엇이 비었는지 사람이 보고 판단하게 한다
    for col in COPY_COLS:
        n = sum(1 for r in copy_rows if r[col] is not None)
        print(f"  filled copy.{col}: {n}/{len(copy_rows)}")
    ng = sum(1 for r in sug_rows if r["suggested_grade"] is not None)
    print(f"  filled suggestion.suggested_grade: {ng}/{len(sug_rows)} "
          f"(null={len(sug_rows) - ng} -> 기계가 판정 못 함)")

    if bad:
        print("\nABORT: 위 WARN 을 먼저 해소하라 - 잘못된 game_id 로 적재하지 않는다")
        return 2
    if args.dry:
        print("\n--dry mode -- no rows written")
        return 0

    cw = sw = 0
    with engine.begin() as conn:
        # COALESCE(t.c, EXCLUDED.c) - 기존 값이 NULL 인 칸만 채운다(머리 주석 참조)
        cset = ", ".join(
            f"{c} = COALESCE(game_customer_copy.{c}, EXCLUDED.{c})" for c in COPY_COLS)
        for r in copy_rows:
            conn.execute(text(f"""
                INSERT INTO game_customer_copy
                  (game_id, {", ".join(COPY_COLS)}, updated_at)
                VALUES (:game_id, :spec_summary_ko, :why_this_pc, :upgrade_hint,
                        :caution, CAST(:source_fields AS jsonb), :confidence,
                        :source_url, now())
                ON CONFLICT (game_id) DO UPDATE SET {cset}, updated_at = now()
            """), r)
            cw += 1

        sset = ", ".join(
            f"{c} = COALESCE(game_grade_suggestions.{c}, EXCLUDED.{c})" for c in SUG_COLS)
        for r in sug_rows:
            conn.execute(text(f"""
                INSERT INTO game_grade_suggestions
                  (game_id, {", ".join(SUG_COLS)}, created_at, updated_at)
                VALUES (:game_id, :suggested_grade, :confidence, :reason,
                        :rule_version, now(), now())
                ON CONFLICT (game_id) DO UPDATE SET {sset}, updated_at = now()
            """), r)
            sw += 1

    print(f"\nwritten: game_customer_copy={cw} game_grade_suggestions={sw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
