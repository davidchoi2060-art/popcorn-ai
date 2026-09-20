# -*- coding: utf-8 -*-
"""사양이 새로 들어온 9종의 고객용 설명과 등급 «제안» 을 다시 쓴다.

  .venv/Scripts/python tools/game_copy_refresh9.py \
      --file D:/Hermes-Workspace/game_copy_missing9.json --dry
  .venv/Scripts/python tools/game_copy_refresh9.py \
      --file D:/Hermes-Workspace/game_copy_missing9.json --apply

■ 왜 «덮어쓰기» 로더가 따로 필요한가
  tools/game_customer_copy_load.py 는 기존 값이 NULL 인 칸만 채운다. 사람이 다듬은
  문장을 재적재가 조용히 되돌리는 사고를 막기 위해서다. 그 원칙은 옳다.
  다만 이 9종의 현재 문구는 **사양이 비어 있던 시점에 그 사실을 적은 글**이다
  ("게임사 요구사양이 없어 부품 등급을 단정해 드릴 수 없습니다"). 사양이 들어온
  지금 그대로 두면 고객에게 사실과 다른 문장이 나간다. 그래서 여기서는 덮어쓴다.
  대신 범위를 좁힌다:
    - --file 에 담긴 game_id 만 건드린다(9종). 나머지 77종은 조회조차 하지 않는다.
    - **사람이 검수한 행은 덮어쓰지 않는다**(reviewed_by IS NOT NULL -> 건너뛰고 보고).
      사장님/검수자가 손댄 문장을 도구가 되돌리는 것이 원래 막으려던 사고다.
    - --apply 없이는 아무것도 쓰지 않는다. 전/후 문장을 전부 출력한다.
    - reviewed_by / reviewed_at 은 쓰지 않는다(검수는 사람 일이다).

■ 문구는 DB 값으로만 쓴다
  이 로더는 문장을 만들지 않는다. JSON 의 문장을 한 글자도 바꾸지 않고 옮긴다.
  적재 직전 tests/regression.py [55] 와 **같은 규칙**으로 원고를 검사한다 -
  문구에 쓰인 GPU 모델명·fps·Hz·GB 가 그 game_id 의 DB 값에 실재하지 않으면 중단한다.
  회귀가 나중에 잡아 주기를 기다리지 않고 적재 자체를 막는다.

■ 등급은 «제안» 이고, 애매하면 사람에게 넘긴다
  판정은 D:/Hermes-Workspace/grade_rules.py 를 그대로 호출한다(규칙을 고치지 않는다).
  그 위에 **좁히는 방향으로만** 가드를 하나 둔다:
    공식 사양 원문(rec_spec_note_raw)에 rec_gpu 보다 위 세대 GPU 가 들어 있는데
    규칙이 «구형 등급» 이라는 이유로 경량 판정을 내렸다면, 그 판정은 서지 않는다.
    등급을 바꾸지 않고 confidence 만 «사람 확인 필요» 로 되돌린다.
  가드는 등급을 올리지도 내리지도 않는다 - 확신만 낮춘다.

콘솔 출력은 ASCII 기호만 쓴다(서버 stdout 이 cp949).
"""
import argparse
import importlib.util
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console        # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                        # noqa: E402
from sqlalchemy import create_engine, text             # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPY_COLS = ("spec_summary_ko", "why_this_pc", "upgrade_hint", "caution",
             "source_fields", "confidence")
SUG_COLS = ("suggested_grade", "confidence", "reason", "rule_version")
RULE_VERSION = "grade_rules/2026-09-19+specs9"
GRADE_RULES = "D:/Hermes-Workspace/grade_rules.py"

# 사내 어휘가 고객 문구로 새는 것을 막는다(등급 E/L/A/B/C/S · 티어 T1~T5).
_INTERNAL = re.compile(r"등급\s*[ELABCS]\b|\bT[1-5]\b|경량 캐주얼|CPU 바운드 시뮬")
# 우리 지식을 슬쩍 끼워 넣는 표현. DB 에 없는 말은 쓰지 않는다.
_HEDGE = ("일반적으로", "보통은", "대체로", "흔히", "알려져 있", "보고가 반복")


def _load_reg_rules():
    """tests/regression.py [55] 의 검출기를 그대로 가져온다(복제하지 않는다).

    regression.py 는 import 하면 서버 호출까지 하므로 모듈째 실행하지 않고
    [55] 검출기 구간만 떼어 실행한다. 정규식이 회귀와 갈라지지 않게 하려는 것이다.
    """
    src = open(os.path.join(ROOT, "tests", "regression.py"), encoding="utf-8").read()
    seg = src[src.index("_COPY_GPU_RE = "):src.index("def test_game_customer_copy()")]
    ns = {"re": re}
    exec(seg, ns)                                        # noqa: S102
    return ns


def _load_grade_rules():
    spec = importlib.util.spec_from_file_location("grade_rules", GRADE_RULES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", nargs="+", required=True, metavar="JSON")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="실제로 덮어쓴다. 없으면 아무것도 쓰지 않는다")
    args = ap.parse_args()
    if args.apply and args.dry:
        print("ABORT: --dry 와 --apply 를 같이 줄 수 없다")
        return 2

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])
    reg = _load_reg_rules()
    rules = _load_grade_rules()

    items = []
    for path in args.file:
        with open(path, encoding="utf-8") as f:
            items.extend(json.load(f))
    ids = [it["game_id"] for it in items]

    with engine.connect() as conn:
        rs = conn.execute(text(
            "SELECT * FROM games WHERE game_id = ANY(:i) ORDER BY game_id"),
            {"i": ids})
        gcols = list(rs.keys())
        games = {r[0]: dict(zip(gcols, r)) for r in rs}
        rs = conn.execute(text(
            "SELECT game_id, " + ", ".join(
                reg["_COPY_GAME_TEXT_COLS"] + reg["_COPY_GAME_NUM_COLS"]) +
            " FROM games"))
        hcols = list(rs.keys())
        hrows = [dict(zip(hcols, r)) for r in rs]
        mfps = [dict(r._mapping) for r in conn.execute(text(
            "SELECT game_id, gpu_model, cpu_model, note, preset, fps_avg,"
            "       fps_1pct_low FROM game_measured_fps"))]
        cur_copy = {r[0]: dict(zip(("reviewed_by",) + COPY_COLS, r[1:]))
                    for r in conn.execute(text(
                        "SELECT game_id, reviewed_by, " + ", ".join(COPY_COLS) +
                        " FROM game_customer_copy WHERE game_id = ANY(:i)"),
                        {"i": ids})}
        cur_sug = {r[0]: dict(zip(SUG_COLS, r[1:]))
                   for r in conn.execute(text(
                       "SELECT game_id, " + ", ".join(SUG_COLS) +
                       " FROM game_grade_suggestions WHERE game_id = ANY(:i)"),
                       {"i": ids})}
        confirmed = {r[0] for r in conn.execute(text(
            "SELECT game_id FROM game_grade_assignments"
            " WHERE is_confirmed AND game_id = ANY(:i)"), {"i": ids})}
        known_grades = {r[0] for r in conn.execute(
            text("SELECT grade FROM game_load_grades"))}
        mfps_by = {}
        for m in mfps:
            mfps_by.setdefault(m["game_id"], []).append(m)

    # ---- haystack ([55] 와 동일 구성) ----
    by = {}
    for m in mfps:
        by.setdefault(m["game_id"], []).append(m)
    hay = {}
    for g in hrows:
        parts = [str(g.get(k) or "") for k in reg["_COPY_GAME_TEXT_COLS"]]
        for m in by.get(g["game_id"], []):
            parts += [str(m.get(k) or "") for k in
                      ("gpu_model", "cpu_model", "note", "preset",
                       "fps_avg", "fps_1pct_low")]
        parts += [str(g[k]) for k in reg["_COPY_GAME_NUM_COLS"]
                  if g.get(k) is not None]
        hay[g["game_id"]] = " || ".join(parts)

    bad = []
    rows = []
    for it in items:
        gid = it["game_id"]
        g = games.get(gid)
        if g is None:
            bad.append((gid, it["name"], "games 에 없는 game_id"))
            continue
        if g["name"] != it["name"]:
            bad.append((gid, it["name"], f"이름 불일치(db={g['name']!r})"))
        rows.append({
            "game_id": gid, "name": it["name"],
            "spec_summary_ko": it.get("spec_summary_ko") or None,
            "why_this_pc": it.get("why_this_pc") or None,
            "upgrade_hint": it.get("upgrade_hint") or None,
            "caution": it.get("caution") or None,
            "source_fields": (json.dumps(it["source_fields"], ensure_ascii=False)
                              if it.get("source_fields") else None),
            "confidence": it.get("confidence"),
        })

    # ---- 적재 전 검증: 회귀 [55] 와 같은 규칙 ----
    viol = reg["_copy_violations"](rows, hay)
    for gid, name, kind, v in viol:
        bad.append((gid, name, f"[55] 규칙 위반 {kind}={v!r} - DB 값에 없는 수치/모델명"))
    for r in rows:
        t = " ".join(filter(None, (r["spec_summary_ko"], r["why_this_pc"],
                                   r["upgrade_hint"], r["caution"])))
        m = _INTERNAL.search(t)
        if m:
            bad.append((r["game_id"], r["name"], f"사내 어휘 노출 {m.group(0)!r}"))
        for h in _HEDGE:
            if h in t:
                bad.append((r["game_id"], r["name"], f"근거 없는 표현 {h!r}"))
        if r["confidence"] not in ("높음", "보통", "낮음"):
            bad.append((r["game_id"], r["name"],
                        f"confidence 어휘 밖 {r['confidence']!r}"))
        for col in ("spec_summary_ko", "why_this_pc"):
            if not r[col]:
                bad.append((r["game_id"], r["name"], f"{col} 가 비었다"))

    # ---- 등급 재판정 ----
    sug = []
    for r in rows:
        gid = r["game_id"]
        g = games[gid]
        grade, conf, reason = rules.suggest(g, mfps_by.get(gid, []))
        guard = None
        raw = str(g.get("rec_spec_note_raw") or "")
        if grade == "L" and "구형 등급" in (reason or ""):
            higher = [m for m in re.findall(
                r"RTX\s?\d{4}[A-Za-z ]{0,8}|GTX\s?1[6-9]\d0[A-Za-z ]{0,6}", raw)
                if not re.match(r"GTX\s?16", m)]
            if higher:
                guard = ("공식 사양 원문에 상위 GPU 단계가 있다: "
                         + ", ".join(sorted(set(x.strip() for x in higher))[:4]))
        if guard:
            conf = "사람 확인 필요"
            reason = (reason or "") + " / [가드] " + guard + \
                     " - 경량 판정이 공식 상위 단계와 어긋나 확신을 낮춘다"
        if gid in confirmed:
            bad.append((gid, r["name"], "확정 배정이 있는데 제안 표 대상이다"))
        if grade is not None and grade not in known_grades:
            bad.append((gid, r["name"], f"game_load_grades 에 없는 등급 {grade!r}"))
        sug.append({"game_id": gid, "name": r["name"], "suggested_grade": grade,
                    "confidence": conf, "reason": reason,
                    "rule_version": RULE_VERSION})

    # ---- 보고 ----
    print(f"input: {len(items)} / target game_ids: {ids}")
    print(f"[55] 규칙 위반: {len(viol)}  (0 이어야 적재한다)")
    skip_rev = [r["name"] for r in rows
                if (cur_copy.get(r["game_id"]) or {}).get("reviewed_by")]
    print(f"사람 검수된 행(덮어쓰지 않고 건너뜀): {len(skip_rev)} {skip_rev}")
    print("\n---- game_customer_copy before/after ----")
    for r in rows:
        cur = cur_copy.get(r["game_id"], {})
        print(f"\n[{r['game_id']}] {r['name']}"
              + ("   (검수됨 -> SKIP)" if cur.get("reviewed_by") else ""))
        for col in ("spec_summary_ko", "why_this_pc", "upgrade_hint",
                    "caution", "confidence"):
            o, n = cur.get(col), r[col]
            if str(o) == str(n):
                print(f"  = {col}: (변화 없음)")
            else:
                print(f"  - {col} before: {o}")
                print(f"  + {col} after : {n}")
    print("\n---- game_grade_suggestions before/after ----")
    moved = 0
    for s in sug:
        cur = cur_sug.get(s["game_id"], {})
        was = f"{cur.get('suggested_grade')}/{cur.get('confidence')}"
        now = f"{s['suggested_grade']}/{s['confidence']}"
        if cur.get("confidence") == "사람 확인 필요" and s["confidence"] != "사람 확인 필요":
            moved += 1
        print(f"  [{s['game_id']}] {s['name']}: {was} -> {now}")
        print(f"      reason: {s['reason']}")
    print(f"\n«사람 확인 필요» 를 벗어난 게임: {moved}/{len(sug)}")

    for gid, name, why in bad:
        print(f"  WARN: game_id={gid} {name} reason={why}")
    if bad:
        print("\nABORT: 위 WARN 을 먼저 해소하라")
        return 2
    if not args.apply:
        print("\n--apply 가 없다 -- no rows written")
        return 0

    cw = sw = 0
    with engine.begin() as conn:
        for r in rows:
            if (cur_copy.get(r["game_id"]) or {}).get("reviewed_by"):
                continue
            conn.execute(text("""
                UPDATE game_customer_copy SET
                  spec_summary_ko = :spec_summary_ko,
                  why_this_pc = :why_this_pc,
                  upgrade_hint = :upgrade_hint,
                  caution = :caution,
                  source_fields = CAST(:source_fields AS jsonb),
                  confidence = :confidence,
                  updated_at = now()
                WHERE game_id = :game_id AND reviewed_by IS NULL
            """), r)
            cw += 1
        for s in sug:
            conn.execute(text("""
                UPDATE game_grade_suggestions SET
                  suggested_grade = :suggested_grade,
                  confidence = :confidence,
                  reason = :reason,
                  rule_version = :rule_version,
                  updated_at = now()
                WHERE game_id = :game_id
            """), s)
            sw += 1
    print(f"\nwritten: game_customer_copy={cw} game_grade_suggestions={sw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
