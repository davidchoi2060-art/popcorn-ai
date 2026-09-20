# -*- coding: utf-8 -*-
"""PC방 상위권 사양 공백 9종의 공식 요구사양을 games 에 병합한다.

  .venv/Scripts/python tools/game_specs_missing9_load.py \
      --file D:/Hermes-Workspace/game_specs_missing9.json --dry
  .venv/Scripts/python tools/game_specs_missing9_load.py \
      --file D:/Hermes-Workspace/game_specs_missing9.json \
      --refresh-confidence --refresh-note --refresh-checked-date

대상 9종(PC방 순위): 리니지 클래식(3) 스타크래프트(10) 메이플스토리 월드(14)
WoW(17) 워크래프트3 리포지드(19) 검은사막(26) 스타크래프트2(27) POE1(30) FF14(46)

■ 기존 값이 NULL 인 칸만 채운다
  tools/game_catalog_load.py 머리 주석의 사고를 그대로 따른다 -
  COALESCE(EXCLUDED.c, games.c) 는 «새 값이 NULL 이면 기존을 지킨다»일 뿐이라
  새 값이 있으면 기존을 갈아엎는다. 그렇게 기존 23종에서 48개 필드가 덮여
  고객이 읽던 문구가 바뀐 전례가 있다. 여기선 방향을 뒤집어
  COALESCE(games.c, :new) - **기존 값이 NULL 인 칸만** 채운다.
  값이 이미 있어 싣지 못한 칸은 매 실행 전부 출력한다(조용히 넘기지 않는다).

■ 예외 세 칸 - 명시 플래그가 있어야만 덮어쓴다
  이 9종의 기존 값은 «사양을 못 찾았다»는 사실을 적어 둔 칸이다. 사양이 들어온
  지금 그대로 두면 DB 가 스스로와 모순된다. 그래서 아래 셋만, 조건을 좁혀서,
  플래그가 있을 때만 덮어쓴다. 덮어쓴 칸은 전/후 값을 전부 출력한다.
    confidence    기존 값에 '미확보' 가 들어 있을 때만  (--refresh-confidence)
    note          기존 값이 '사양 미확보' 류 경고문일 때만 (--refresh-note)
    checked_date  --checked-date 로 받은 날짜로          (--refresh-checked-date)
  note 를 고치는 이유는 하나 더 있다 - tests/regression.py [55] 가 games.note 를
  「고객 문구가 인용해도 되는 사실」 haystack 에 넣는다. 낡은 경고문이 남아 있으면
  없는 근거가 근거인 척 남는다.

■ 값을 만들지 않는다
  JSON 이 null 이면 DB 도 null 이다. 조사자가 «제조사가 안 적었다»는 이유로 비운
  칸이 있다(VRAM 6종 · bottleneck_evidence 4종 · fps 목표 일부). 채우지 않는다.

  VRAM 은 integer 컬럼인데 조사 원문이 소수인 경우가 있다(스타크래프트 0.25GB
  =256MB). 반올림하면 0GB/1GB 라는 **원문에 없는 값**이 정본인 척한다. 그래서
  싣지 않고 비워 두고 보고한다.

■ 2단 스키마에 안 들어가는 원문은 버리지 않는다
  검은사막 공식 5단계 티어표 · 스타크래프트 실시간조명 VRAM 단서 · 리니지
  OpenGL 4.3 · 메이플 월드의 «월드별로 사양이 다를 수 있음» 은 min/rec 두 칸으로
  압축되지 않는다. min_spec_note_raw / rec_spec_note_raw 에 원문 그대로 싣는다.
  OS 는 games 에 전용 컬럼이 없어 같은 두 칸에 라벨을 붙여 넣는다.

■ 리니지 클래식의 rec_gpu == min_gpu 는 오류가 아니다
  공식 표가 GPU·저장장치·OpenGL 을 최소=권장 동일로 적었고 차등은 CPU·RAM 뿐이다.
  «권장은 최소보다 높아야 한다»는 strict 검사는 이 행에서 틀린다. 이 로더의
  정합성 점검은 rec >= min 으로 보고, 같은 값은 경고조차 내지 않는다(정상값이다).

■ POE1 / POE2
  games 에 「패스 오브 엑자일」(146, POE1) 과 「패스 오브 엑자일2」(10, POE2) 가
  별도 행으로 있다. 이 로더는 game_id 로 집고 이름까지 대조해 다르면 중단한다.
  POE2(10) 는 이 파일의 대상이 아니므로 손대지 않는다.

콘솔 출력은 ASCII 기호만 쓴다(서버 stdout 이 cp949).
"""
import argparse
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

# JSON 필드명 == games 컬럼명인 것들. 전부 «기존이 NULL 일 때만» 채운다.
DIRECT_COLS = (
    "official_source_url", "min_cpu", "min_gpu", "min_ram_gb",
    "rec_cpu", "rec_gpu", "rec_ram_gb",
    "min_vram_gb", "rec_vram_gb", "min_storage_gb", "rec_storage_gb",
    "requires_ssd", "bottleneck", "bottleneck_evidence", "steam_appid",
    "competitive_fps_target", "comfortable_fps_target", "minimum_fps_target",
)
DERIVED_COLS = ("min_spec_note_raw", "rec_spec_note_raw",
                "rec_gpu_nvidia", "rec_gpu_amd", "rec_gpu_intel")
FILL_COLS = DIRECT_COLS + DERIVED_COLS
# 조건부 덮어쓰기 칸(머리 주석 참조)
REFRESH_COLS = ("confidence", "note", "checked_date")

INT_COLS = ("min_ram_gb", "rec_ram_gb", "min_vram_gb", "rec_vram_gb",
            "min_storage_gb", "rec_storage_gb", "steam_appid",
            "competitive_fps_target", "comfortable_fps_target",
            "minimum_fps_target")

_LEGACY_WIDTH = {"min_cpu": 160, "min_gpu": 160, "rec_cpu": 160, "rec_gpu": 160,
                 "official_source_url": 300, "note": 200, "confidence": 120,
                 "bottleneck": 16}

_VENDOR_PATS = (
    ("rec_gpu_nvidia", re.compile(r"NVIDIA|GeForce|GTX|RTX", re.I)),
    ("rec_gpu_amd", re.compile(r"\bAMD\b|Radeon|\bRX\s|\bR[579]\b|\bHD\s*\d", re.I)),
    ("rec_gpu_intel", re.compile(r"\bIntel\b|\bArc\b|\bUHD\b|\bIris\b", re.I)),
)

# note 를 덮어써도 되는 «낡은 경고문» 판정. 여기 걸리지 않으면 건드리지 않는다
# (사람이 써 넣은 문장을 로더가 지우면 안 된다).
_STALE_NOTE = re.compile(r"미확보|미확인|추출하지 못|사양 표 페이지를 특정하지 못"
                         r"|반환하지 않|전부 null|min/rec null")


def _clip(name, col, v, unparsed):
    """컬럼 폭을 넘으면 자르지 않고 비운다 - 잘린 값은 원문인 척하는 가짜다."""
    w = _LEGACY_WIDTH.get(col)
    if w and isinstance(v, str) and len(v) > w:
        unparsed.append((name, col, f"len={len(v)} > varchar({w}) -> left NULL"))
        return None
    return v


def build(items, checked_date):
    rows, unparsed = [], []
    for it in items:
        name = it["name"]
        p = {c: None for c in FILL_COLS + REFRESH_COLS}
        for c in DIRECT_COLS:
            p[c] = it.get(c)

        # 정수 컬럼 - 소수는 싣지 않는다(반올림하면 원문에 없는 값이 된다)
        for c in INT_COLS:
            v = p.get(c)
            if isinstance(v, float):
                if v == int(v):
                    p[c] = int(v)
                else:
                    unparsed.append((name, c, f"json={v} is fractional; integer "
                                              f"column -> left NULL (not rounded)"))
                    p[c] = None

        # 2단 스키마에 안 들어가는 원문 보존 + OS(전용 컬럼 없음)
        raw = it.get("spec_note_raw")
        minp = [f"[최소 OS] {it['min_os']}"] if it.get("min_os") else []
        recp = [f"[권장 OS] {it['rec_os']}"] if it.get("rec_os") else []
        if raw:
            recp.append(f"[공식 사양 원문 메모] {raw}")
        src = it.get("official_source_url")
        if src:
            recp.append(f"[출처] {src}")
        p["min_spec_note_raw"] = " / ".join(minp) or None
        p["rec_spec_note_raw"] = " / ".join(recp) or None

        rg = it.get("rec_gpu")
        if rg:
            for col, vpat in _VENDOR_PATS:
                for tok in re.split(r"\s*/\s*", rg):
                    tok = tok.strip()
                    if tok and vpat.search(tok):
                        p[col] = tok if len(tok) <= 80 else None
                        if len(tok) > 80:
                            unparsed.append((name, col, "token too long -> NULL"))
                        break

        p["confidence"] = it.get("confidence")
        p["checked_date"] = checked_date
        # 새 note - 지어내지 않는다. 출처 URL·출처 종류·확인일만 적는다.
        st = it.get("source_type") or ""
        nt = f"{checked_date} 공식 요구사양 확보({st}). 출처: {src}"
        cav = it.get("found_note") or ""
        if "월드별" in (raw or ""):
            nt = (f"{checked_date} 공식 요구사양 확보({st}). 공식 문구상 월드별로 "
                  f"최소/권장이 다를 수 있다. 출처: {src}")
        elif "확장팩" in (raw or ""):
            nt = (f"{checked_date} 공식 요구사양 확보({st}). 확장팩마다 갱신되므로 "
                  f"재확인 필요. 출처: {src}")
        elif "티어" in (raw or ""):
            nt = (f"{checked_date} 공식 요구사양 확보({st}). 공식은 5단계 티어표이며 "
                  f"상위 3티어는 rec_spec_note_raw 에 원문 보존. 출처: {src}")
        p["note"] = nt
        del cav

        for c in list(p):
            p[c] = _clip(name, c, p[c], unparsed)

        p["game_id"] = it["game_id"]
        p["name"] = name
        rows.append(p)
    return rows, unparsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", nargs="+", required=True, metavar="JSON")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--checked-date", default="2026-09-19",
                    help="조사일(game_specs_missing9.md 머리말)")
    ap.add_argument("--refresh-confidence", action="store_true")
    ap.add_argument("--refresh-note", action="store_true")
    ap.add_argument("--refresh-checked-date", action="store_true")
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

    rows, unparsed = build(items, args.checked_date)
    ids = [r["game_id"] for r in rows]

    allc = FILL_COLS + REFRESH_COLS
    with engine.connect() as conn:
        cur = {r[0]: dict(zip(("name",) + allc, r[1:]))
               for r in conn.execute(
                   text("SELECT game_id, name, " + ", ".join(allc) +
                        " FROM games WHERE game_id = ANY(:i)"), {"i": ids})}

    # 이름 대조 - JSON 이 낡았거나 game_id 를 잘못 집으면 여기서 멈춘다.
    # POE1(146)/POE2(10) 혼동이 실제로 일어날 수 있는 자리라 특히 중요하다.
    bad = []
    for r in rows:
        c = cur.get(r["game_id"])
        if c is None:
            bad.append((r["game_id"], r["name"], "games 에 없는 game_id"))
        elif c["name"] != r["name"]:
            bad.append((r["game_id"], r["name"], f"이름 불일치(db={c['name']!r})"))

    blocked, refreshed, wrote = [], [], []
    for r in rows:
        c = cur.get(r["game_id"]) or {}
        for col in FILL_COLS:
            if r[col] is None:
                continue
            if c.get(col) is not None:
                if str(c[col]) != str(r[col]):
                    blocked.append((r["name"], col, c[col], r[col]))
                r[col] = None            # 기존 값이 있으면 싣지 않는다
            else:
                wrote.append((r["name"], col, r[col]))
        # 조건부 덮어쓰기
        old_conf, old_note, old_cd = (c.get("confidence"), c.get("note"),
                                      c.get("checked_date"))
        if not (args.refresh_confidence and old_conf and "미확보" in str(old_conf)):
            if old_conf is not None:
                if r["confidence"] is not None and str(old_conf) != str(r["confidence"]):
                    blocked.append((r["name"], "confidence", old_conf, r["confidence"]))
                r["confidence"] = None
            elif r["confidence"] is not None:
                wrote.append((r["name"], "confidence", r["confidence"]))
        else:
            refreshed.append((r["name"], "confidence", old_conf, r["confidence"]))
        if not (args.refresh_note and old_note and _STALE_NOTE.search(str(old_note))):
            if old_note is not None:
                if str(old_note) != str(r["note"]):
                    blocked.append((r["name"], "note", str(old_note)[:40] + "...",
                                    str(r["note"])[:40] + "..."))
                r["note"] = None
            else:
                wrote.append((r["name"], "note", r["note"]))
        else:
            refreshed.append((r["name"], "note", old_note, r["note"]))
        if not args.refresh_checked_date:
            if old_cd is not None:
                r["checked_date"] = None
            else:
                wrote.append((r["name"], "checked_date", r["checked_date"]))
        elif str(old_cd) != str(r["checked_date"]):
            refreshed.append((r["name"], "checked_date", old_cd, r["checked_date"]))
        else:
            r["checked_date"] = None

    # 정합성 - rec >= min (같은 값은 정상이다. 리니지 클래식이 공식으로 그렇다)
    incons = []
    for r in rows:
        src = next(i for i in items if i["game_id"] == r["game_id"])
        for a, b in (("min_ram_gb", "rec_ram_gb"), ("min_vram_gb", "rec_vram_gb")):
            x, y = src.get(a), src.get(b)
            if x is not None and y is not None and y < x:
                incons.append((r["name"], f"{b}({y}) < {a}({x})"))
        if src.get("min_gpu") and src.get("rec_gpu") and src["min_gpu"] == src["rec_gpu"]:
            print(f"  note: {r['name']} rec_gpu == min_gpu "
                  f"(official table says so - not an error)")

    print(f"input: {len(items)} / target game_ids: {ids}")
    print(f"cells to fill (existing NULL): {len(wrote)}")
    for n, col, v in wrote:
        print(f"  fill: {n}.{col} = {str(v)[:70]}")
    print(f"cells kept (existing value differs, NOT overwritten): {len(blocked)}")
    for n, col, o, v in blocked:
        print(f"  keep: {n}.{col} db={str(o)[:40]!r} json={str(v)[:40]!r}")
    print(f"cells refreshed (explicit flag): {len(refreshed)}")
    for n, col, o, v in refreshed:
        print(f"  refresh: {n}.{col}")
        print(f"     before: {str(o)[:110]}")
        print(f"     after : {str(v)[:110]}")
    for n, col, why in unparsed:
        print(f"  unparsed: {n} field={col} reason={why}")
    for n, why in incons:
        print(f"  INCONSISTENT: {n} {why}")
    for gid, n, why in bad:
        print(f"  WARN: game_id={gid} {n} reason={why}")

    if bad or incons:
        print("\nABORT: 위 WARN/INCONSISTENT 를 먼저 해소하라")
        return 2
    if args.dry:
        print("\n--dry mode -- no rows written")
        return 0

    n = 0
    with engine.begin() as conn:
        # COALESCE(games.c, :c) - 기존 값이 NULL 인 칸만 채운다
        sets = ", ".join(f"{c} = COALESCE(games.{c}, :{c})" for c in FILL_COLS)
        # REFRESH 칸은 위에서 자격을 판정해 통과한 것만 not-NULL 로 남아 있다
        sets += ", " + ", ".join(f"{c} = COALESCE(:{c}, games.{c})"
                                 for c in REFRESH_COLS)
        for r in rows:
            conn.execute(text(
                f"UPDATE games SET {sets} WHERE game_id = :game_id"), r)
            n += 1
    print(f"\nwritten: games rows touched={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
