# -*- coding: utf-8 -*-
"""게임/AI 성능 DB 로더 — 수집 JSON을 games·game_performance·ai_workloads 에 채운다.

배경: docs/design/prebuilt-grid-benchmark-2026-09-07.md 격자-7. 저장 구조는
db/migrations/versions/0073_game_ai_db.py. 값은 이 스크립트가 만들지 않는다 —
연구팀(조사자/검증자)이 출처를 붙여 모은 JSON을 그대로 옮겨 적재만 한다.

실행:
  .venv/Scripts/python tools/game_db_load.py --games a.json b.json --dry
  .venv/Scripts/python tools/game_db_load.py --games a.json --ai c.json
  .venv/Scripts/python tools/game_db_load.py --ai c.json

입력 형식(JSON, 파일당 최상위가 배열):

  --games 파일의 원소 (games 1건 + 그 게임의 fps_data 0건 이상):
    {"name": "배틀그라운드", "genre": "배틀로얄",
     "min_cpu": "...", "min_gpu": "...", "min_ram_gb": 8,
     "rec_cpu": "...", "rec_gpu": "...", "rec_ram_gb": 16,
     "popularity_rank": 3, "official_source_url": "...",
     "checked_date": "2026-09-01", "note": "...",
     "fps_data": [
       {"gpu": "RTX 4060", "resolution": "FHD", "fps_avg": 92,
        "source_url": "https://...", "checked_date": "2026-09-01"}
     ]}
  name 이외는 전부 생략 가능. games 컬럼과 이름이 다른 키는 무시한다.

  --ai 파일의 원소:
    {"task": "LLM 로컬 추론", "model_size": "14B", "min_vram_gb": 12,
     "rec_vram_gb": 16, "min_ram_gb": 32, "recommended_tier": "팝콘 9",
     "source_url": "https://...", "checked_date": "2026-09-01", "note": "..."}

■ games 는 name 으로 UPSERT — COALESCE(새 값, 기존 값). 채우기만 하고 지우지
  않는다(카탈로그 적재와 같은 관례, CLAUDE.md "적재는 채우기만 하고 지우지
  않는다"). fps_data·ai_workloads 행은 반대로 **매번 새 값으로 덮어쓴다** — 이
  값은 정본 사실이 아니라 그 시점의 벤치마크 관측이라, 최신 수집이 이전 수집을
  대체하는 것이 맞다(games 의 사양 필드처럼 "누적해서 채운다"는 개념이 없다).

■ gpu_band 변환 — fps_data 의 gpu 모델명을 required_power_watt 등급으로 바꾼다.
  v_recommendation_candidates 에서 part_type='GPU' 이고 product_name 에 그 모델명이
  들어간 행들의 required_power_watt 최빈값을 쓴다(개별 GPU가 아니라 성능 밴드로
  참조 — 0073 머리 주석 참조). 매핑되는 행이 하나도 없으면 그 fps 항목은
  스킵하고 사유를 출력한다(지어내지 않는다).

■ 출처 필수 — source_url 없는 game_performance·ai_workloads 항목은 적재를
  거부한다(그 항목만, 파일 전체가 아니다). games 자체(이름·장르)는 출처 없이도
  들어간다 — "게임이 존재한다"는 사실이지 성능 주장이 아니기 때문이다.

--dry 는 DB에 아무것도 쓰지 않고 반영될 내용만 센다. 콘솔 출력은 ASCII만.
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

GAME_FIELDS = (
    "genre", "min_cpu", "min_gpu", "min_ram_gb", "rec_cpu", "rec_gpu",
    "rec_ram_gb", "popularity_rank", "official_source_url", "checked_date", "note",
)
AI_REQUIRED = ("task", "source_url", "checked_date")
AI_FIELDS = (
    "task", "model_size", "min_vram_gb", "rec_vram_gb", "min_ram_gb",
    "recommended_tier", "source_url", "checked_date", "note",
)
FPS_BAND_EDGES = ((144, "144+"), (100, "100+"), (60, "60+"), (30, "30+"))


def _fps_band(fps_avg):
    if fps_avg is None:
        return None
    for edge, label in FPS_BAND_EDGES:
        if fps_avg >= edge:
            return label
    return "30미만"


def _load_json_list(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path}: top-level must be a JSON array")
    return data


def _resolve_gpu_band(conn, gpu_model, cache):
    if gpu_model in cache:
        return cache[gpu_model]
    rows = conn.execute(text(
        "SELECT required_power_watt, count(*) c FROM v_recommendation_candidates"
        " WHERE part_type = 'GPU' AND required_power_watt IS NOT NULL"
        " AND product_name ILIKE :pat"
        " GROUP BY required_power_watt ORDER BY c DESC"),
        {"pat": f"%{gpu_model}%"}).all()
    band = rows[0][0] if rows else None
    cache[gpu_model] = band
    return band


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", nargs="+", default=[], metavar="JSON")
    ap.add_argument("--ai", nargs="+", default=[], metavar="JSON")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not args.games and not args.ai:
        print("nothing to do: give --games and/or --ai")
        sys.exit(1)

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    games_in = []
    for p in args.games:
        games_in.extend(_load_json_list(p))
    ai_in = []
    for p in args.ai:
        ai_in.extend(_load_json_list(p))

    # ---- games + game_performance 준비 ----
    game_rows = []
    perf_candidates = []   # (game_name, fps_entry)
    perf_skip_source = []
    for g in games_in:
        name = (g.get("name") or "").strip()
        if not name:
            print("skip: game entry without name")
            continue
        game_rows.append(g)
        for fp in g.get("fps_data") or []:
            if not fp.get("source_url"):
                perf_skip_source.append((name, fp.get("gpu"), fp.get("resolution")))
                continue
            perf_candidates.append((name, fp))

    # ---- ai_workloads 준비 ----
    ai_ok, ai_skip = [], []
    for w in ai_in:
        missing = [k for k in AI_REQUIRED if not w.get(k)]
        if missing:
            ai_skip.append((w.get("task"), w.get("model_size"), missing))
            continue
        ai_ok.append(w)

    print(f"games input: {len(games_in)} / ai_workloads input: {len(ai_in)}")
    print(f"game_performance candidates: {len(perf_candidates)}"
          f" / skipped(no source_url): {len(perf_skip_source)}")
    print(f"ai_workloads accepted: {len(ai_ok)} / skipped(missing required): {len(ai_skip)}")
    for name, gpu, reso in perf_skip_source[:10]:
        print(f"  skip perf: game={name} gpu={gpu} resolution={reso} reason=no_source_url")
    for task, size, missing in ai_skip[:10]:
        print(f"  skip ai: task={task} model_size={size} missing={missing}")

    gpu_band_cache = {}
    perf_ok, perf_unmapped = [], []
    with engine.connect() as conn:
        for name, fp in perf_candidates:
            gpu_model = fp.get("gpu")
            resolution = fp.get("resolution")
            if not gpu_model or not resolution:
                perf_unmapped.append((name, gpu_model, resolution, "missing gpu/resolution"))
                continue
            band = _resolve_gpu_band(conn, gpu_model, gpu_band_cache)
            if band is None:
                perf_unmapped.append((name, gpu_model, resolution,
                                       "no matching GPU row in v_recommendation_candidates"))
                continue
            fps_avg = fp.get("fps_avg")
            band_label = fp.get("fps_band") or _fps_band(fps_avg)
            if not band_label:
                perf_unmapped.append((name, gpu_model, resolution,
                                       "no fps_avg/fps_band given"))
                continue
            perf_ok.append({
                "game_name": name, "gpu_band": band, "resolution": resolution,
                "fps_band": band_label, "fps_avg": fps_avg,
                "source_url": fp["source_url"], "checked_date": fp.get("checked_date"),
            })

    print(f"game_performance mapped: {len(perf_ok)} / gpu unmapped: {len(perf_unmapped)}")
    for name, gpu, reso, why in perf_unmapped[:10]:
        print(f"  unmapped: game={name} gpu={gpu} resolution={reso} reason={why}")

    if args.dry:
        print("\n--dry mode -- no rows written")
        return

    games_written = perf_written = ai_written = 0
    with engine.begin() as conn:
        for g in game_rows:
            name = g["name"].strip()
            params = {k: g.get(k) for k in GAME_FIELDS}
            params["name"] = name
            # ON CONFLICT 라도 Postgres 는 INSERT 후보 행의 NOT NULL 을 먼저 검사한다 —
            # genre 없이 UPSERT 하면 기존 행이 있어도 NotNullViolation 이 난다(실측).
            # 수집 자료에 genre 가 없으면 기존 행 값을 미리 읽어 채운다(시드 장르가 정본,
            # 덮어쓰기 아님). 기존 행도 없고 genre 도 없으면 그 게임은 적재를 거부한다 —
            # '미분류' 같은 기본값을 지어내 넣지 않는다.
            if params.get("genre") is None:
                cur = conn.execute(text("SELECT genre FROM games WHERE name=:n"),
                                   {"n": name}).scalar()
                if cur is None:
                    print(f"  skip game: {name} reason=new_row_without_genre")
                    continue
                params["genre"] = cur
            cols = ", ".join(GAME_FIELDS)
            placeholders = ", ".join(f":{c}" for c in GAME_FIELDS)
            excl = ", ".join(f"{c} = COALESCE(EXCLUDED.{c}, games.{c})" for c in GAME_FIELDS)
            conn.execute(text(f"""
                INSERT INTO games (name, {cols})
                VALUES (:name, {placeholders})
                ON CONFLICT (name) DO UPDATE SET {excl}
            """), params)
            games_written += 1

        for row in perf_ok:
            game_id = conn.execute(text(
                "SELECT game_id FROM games WHERE name = :n"), {"n": row["game_name"]}).scalar()
            if game_id is None:
                print(f"  skip perf write: game not found in games table: {row['game_name']}")
                continue
            conn.execute(text("""
                INSERT INTO game_performance
                  (game_id, gpu_band, resolution, fps_band, fps_avg, source_url, checked_date)
                VALUES (:gid, :band, :reso, :fband, :favg, :src, :cdate)
                ON CONFLICT (game_id, gpu_band, resolution) DO UPDATE SET
                  fps_band = EXCLUDED.fps_band, fps_avg = EXCLUDED.fps_avg,
                  source_url = EXCLUDED.source_url, checked_date = EXCLUDED.checked_date
            """), {"gid": game_id, "band": row["gpu_band"], "reso": row["resolution"],
                   "fband": row["fps_band"], "favg": row["fps_avg"],
                   "src": row["source_url"], "cdate": row["checked_date"]})
            perf_written += 1

        for w in ai_ok:
            params = {k: w.get(k) for k in AI_FIELDS}
            cols = ", ".join(AI_FIELDS)
            excl = ", ".join(f"{c} = EXCLUDED.{c}" for c in AI_FIELDS
                              if c not in ("task", "model_size"))
            conn.execute(text(f"""
                INSERT INTO ai_workloads ({cols})
                VALUES ({", ".join(f":{c}" for c in AI_FIELDS)})
                ON CONFLICT (task, model_size) DO UPDATE SET {excl}
            """), params)
            ai_written += 1

    print(f"\nwritten: games={games_written} game_performance={perf_written} "
          f"ai_workloads={ai_written}")


if __name__ == "__main__":
    main()
