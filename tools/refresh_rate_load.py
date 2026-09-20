# -*- coding: utf-8 -*-
"""주사율 적재기 - 게임 목표 주사율 86종 + 주사율<->필요 GPU 대응표를 적재한다.

배경: db/migrations/versions/0099_refresh_rate_targets.py 가 만든 칸/표를 채운다.
값은 이 스크립트가 만들지 않는다 - 조사자가 출처를 붙여 모은 JSON 을 그대로 옮긴다.
JSON 에 null 이면 DB 도 null 이다. 추정으로 메우지 않는다.

관례는 tools/game_catalog_load.py 를 따른다(그 파일은 읽기만 했고 고치지 않았다):
  --dry 필수 / 멱등 / 기존 값 덮어쓰기 금지 + 차단된 필드 전부 출력.

■ 건드리는 칸을 좁힌다 - 다른 제작자가 같은 표를 동시에 만지고 있다
  games 에서 이 스크립트가 쓰는 칸은 0099 가 만든 8개뿐이다(REFRESH_COLS).
  name/genre 를 포함해 그 밖의 어떤 칸도 SET 절에 넣지 않는다. 그래서 INSERT 도
  하지 않는다 - 86종은 이미 games 에 있고(실측), 없는 이름은 새로 만들지 않고
  건너뛰며 보고한다. games 에 없는 이름을 이 도구가 만들면 genre 를 지어내야 한다.

■ 덮어쓰기 금지의 의미
  0099 칸은 원래 전부 NULL 이라 첫 적재는 전부 통과한다. 두 번째 실행부터는
  '기존 값이 있고 새 값과 다르면' 싣지 않고 보고한다(멱등 + 사고 방지).
  같은 값이면 조용히 통과한다. 굳이 덮으려면 --overwrite 를 명시해야 한다.

■ 신뢰도
  조사 confidence(확인 23 / 2차출처 35 / 추정 28)를 games.refresh_confidence 에
  그대로 싣는다. '추정' 28건은 값을 지어낸 게 아니라 장르 기준을 준용한 것이고
  selection_note 에 "전용 근거 없음"이 적혀 있다 - 지우지 않고 표시해서 넣는다.
  games.confidence(사양 신뢰도) / community_confidence(0098) 는 건드리지 않는다.

■ fps 와 Hz 를 합치지 않는다
  철권8 · 스트리트파이터6 은 competitive_fps_target=60 인데 typical_monitor_hz=240
  이다(엔진 60fps 고정 + 240Hz 패널의 입력지연 이득). 두 칸을 각각 그대로 싣는다.

■ refresh_gpu_requirement - 한 조합이 여러 행이 된다
  조사 JSON 한 원소(해상도 x 주사율)에 최대 3개 블록이 있다:
    aaa_ultra_native_full  -> workload=AAA          criterion=native_full
    aaa_ultra_native_vrr80 -> workload=AAA          criterion=vrr80
    esports                -> workload=COMPETITIVE  criterion=community
  블록이 null 이면 행을 만들지 않는다(도달 불가라는 사실은 verdict 에 남아 있다).
  source_urls 가 없는 블록은 INSERT 하지 않고 보고한다.

■ 모니터 주사율 자체는 적재하지 않는다
  product_specs.refresh_hz 는 이미 2,104 행 채워져 있다. 이 도구는 products /
  product_specs 를 읽지도 쓰지도 않는다.

실행:
  .venv/Scripts/python tools/refresh_rate_load.py \
      --games D:/Hermes-Workspace/game_refresh_rate.json \
      --monitor D:/Hermes-Workspace/monitor_refresh_market.json --dry
  (--dry 를 빼면 실제로 쓴다)

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

# 이 도구가 games 에서 건드리는 칸 - 전부 0099 신설분이다. 그 밖은 손대지 않는다.
REFRESH_COLS = (
    "competitive_fps_target", "comfortable_fps_target", "minimum_fps_target",
    "typical_monitor_hz", "esports_standard_hz",
    "refresh_confidence", "refresh_selection_note", "refresh_source_urls",
)
_JSONB_COLS = {"refresh_source_urls"}
_CONF_WIDTH = 40        # games.refresh_confidence varchar(40)

# 조사 JSON 블록 -> (workload, criterion)
_BLOCKS = (
    ("aaa_ultra_native_full", "AAA", "native_full"),
    ("aaa_ultra_native_vrr80", "AAA", "vrr80"),
    ("esports", "COMPETITIVE", "community"),
)
_REQ_COLS = (
    "resolution", "refresh_hz", "workload", "criterion",
    "gpu_tier", "gpu_card", "gpu_cards", "measured_fps", "our_price_krw",
    "verdict", "quote_claim", "selection_note", "source_urls",
)


def _jsonb(v):
    return json.dumps(v, ensure_ascii=False) if v else None


def build_games(items, report):
    """조사 JSON -> games UPDATE 파라미터. 값을 가공하지 않는다(그대로 옮긴다)."""
    rows = []
    for it in items:
        name = (it.get("name") or "").strip()
        if not name:
            report.append(("(no name)", "-", "missing name -> skipped"))
            continue
        p = {c: None for c in REFRESH_COLS}
        p["name"] = name
        for c in ("competitive_fps_target", "comfortable_fps_target",
                  "minimum_fps_target", "typical_monitor_hz", "esports_standard_hz"):
            v = it.get(c)
            if v is not None and not isinstance(v, int):
                # 정수 칸이다. 소수/문자를 조용히 캐스팅하지 않는다.
                report.append((name, c, f"non-integer value {v!r} -> left NULL"))
                v = None
            p[c] = v
        conf = it.get("confidence")
        if conf and len(conf) > _CONF_WIDTH:
            report.append((name, "refresh_confidence",
                           f"len={len(conf)} > varchar({_CONF_WIDTH}) -> left NULL"))
            conf = None
        p["refresh_confidence"] = conf
        p["refresh_selection_note"] = it.get("selection_note")
        p["refresh_source_urls"] = _jsonb(it.get("source_urls"))
        if not it.get("source_urls"):
            # 출처 없는 주사율도 값 자체는 싣되(조사자가 장르 기준 준용을 명시했다)
            # 근거가 비었다는 사실을 보고한다.
            report.append((name, "refresh_source_urls", "no source_urls in JSON"))
        rows.append(p)
    return rows


def build_reqs(data, report):
    """해상도 x 주사율 원소 -> workload x criterion 행으로 펼친다."""
    rows = []
    for it in data.get("refresh_to_gpu_tier") or []:
        res, hz = it.get("resolution"), it.get("refresh_hz")
        verdict, claim = it.get("verdict"), it.get("quote_claim")
        key = f"{res} {hz}Hz"
        if not res or hz is None or not verdict or not claim:
            report.append((key, "-", "missing resolution/hz/verdict/quote_claim -> skipped"))
            continue
        for field, workload, criterion in _BLOCKS:
            b = it.get(field)
            if not b:
                continue        # 도달 불가 - verdict 에 이미 남아 있다
            # 블록 자체 출처가 있으면 그걸 쓰고, 없으면 조합 단위 출처를 쓴다.
            srcs = b.get("sources") or it.get("sources")
            if not srcs:
                report.append((key, f"{workload}/{criterion}",
                               "no source_urls -> NOT inserted"))
                continue
            note = it.get("selection_note")
            if b.get("note"):
                # 블록 고유 근거(예: 경쟁게임 60Ti vs AAA 70Ti 충돌 해결)를 잃지 않는다.
                note = f"{note}\n[{workload}/{criterion}] {b['note']}" if note else b["note"]
            rows.append({
                "resolution": res, "refresh_hz": hz,
                "workload": workload, "criterion": criterion,
                "gpu_tier": b.get("tier"),
                "gpu_card": b.get("card"),
                "gpu_cards": _jsonb(b.get("cards")),
                "measured_fps": b.get("measured_fps"),
                "our_price_krw": b.get("our_price_krw"),
                "verdict": verdict, "quote_claim": claim,
                "selection_note": note, "source_urls": _jsonb(srcs),
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", metavar="JSON", help="game_refresh_rate.json")
    ap.add_argument("--monitor", metavar="JSON", help="monitor_refresh_market.json")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--overwrite", action="store_true",
                    help="기존 값과 다른 새 값을 덮어쓴다(기본 꺼짐)")
    args = ap.parse_args()
    if not args.games and not args.monitor:
        ap.error("--games / --monitor 중 최소 하나는 필요하다")

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    report = []
    grows, rrows = [], []
    if args.games:
        with open(args.games, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"{args.games}: top-level must be a JSON array")
        grows = build_games(data, report)
    if args.monitor:
        with open(args.monitor, encoding="utf-8") as f:
            rrows = build_reqs(json.load(f), report)

    # ---- 기존 값 보호 ----
    missing, blocked = [], []
    if grows:
        with engine.connect() as conn:
            cur = {
                r[0]: dict(zip(REFRESH_COLS, r[1:]))
                for r in conn.execute(text(
                    "SELECT name, " + ", ".join(REFRESH_COLS) + " FROM games"))
            }
        keep = []
        for r in grows:
            if r["name"] not in cur:
                # games 에 없는 이름은 만들지 않는다(genre NOT NULL 을 지어내야 한다)
                missing.append(r["name"])
                continue
            now = cur[r["name"]]
            for col in REFRESH_COLS:
                old, new = now.get(col), r[col]
                if old is None or new is None:
                    continue
                if col in _JSONB_COLS:
                    same = json.loads(new) == (
                        old if not isinstance(old, str) else json.loads(old))
                else:
                    same = str(old) == str(new)
                if not same:
                    blocked.append((r["name"], col))
                    if not args.overwrite:
                        r[col] = None
            keep.append(r)
        grows = keep

    print(f"games rows to update: {len(grows)}")
    print(f"games not found (NOT created): {len(missing)}")
    for n in missing:
        print(f"  missing game: {n}")
    mode = "OVERWRITTEN" if args.overwrite else "left as-is"
    print(f"refresh columns with a differing existing value: {len(blocked)} ({mode})")
    for n, col in blocked:
        print(f"  keep existing: {n}.{col}")
    for c in REFRESH_COLS:
        print(f"  carrying {c}: {sum(1 for r in grows if r[c] is not None)}/{len(grows)}")
    print(f"refresh_gpu_requirement rows: {len(rrows)}")
    for n, field, why in report:
        print(f"  note: {n} field={field} reason={why}")

    if args.dry:
        print("\n--dry mode -- no rows written")
        return

    g = q = 0
    with engine.begin() as conn:
        # games 는 UPDATE 만 한다 - 이 8개 칸 외에는 SET 절에 없다.
        # 값이 있는 칸만 덮는다: NULL 파라미터가 기존 값을 지우지 않게 COALESCE.
        sets = ", ".join(
            f"{c} = COALESCE(CAST(:{c} AS JSONB), {c})" if c in _JSONB_COLS
            else f"{c} = COALESCE(:{c}, {c})" for c in REFRESH_COLS)
        for r in grows:
            if all(r[c] is None for c in REFRESH_COLS):
                continue
            conn.execute(text(f"UPDATE games SET {sets} WHERE name = :name"), r)
            g += 1

        upd = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in _REQ_COLS
            if c not in ("resolution", "refresh_hz", "workload", "criterion"))
        for r in rrows:
            conn.execute(text(f"""
                INSERT INTO refresh_gpu_requirement ({", ".join(_REQ_COLS)})
                VALUES ({", ".join(f":{c}" for c in _REQ_COLS)})
                ON CONFLICT (resolution, refresh_hz, workload, criterion)
                DO UPDATE SET {upd}
            """), r)
            q += 1

    print(f"\nwritten: games={g} refresh_gpu_requirement={q}")


if __name__ == "__main__":
    main()
