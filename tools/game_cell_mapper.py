# -*- coding: utf-8 -*-
"""게임·AI 작업 <-> 격자 칸 매핑 배치 — game_cell_map·workload_cell_map 재계산.

배경: docs/design/game-quote-mapping-2026-09-07.md SS2(판정 3경로)·SS5(작업 순서 (2)).
저장 구조: db/migrations/versions/0075_cell_maps.py — 이 두 표는 파생 캐시다(원장이
아니다, 그 마이그레이션 머리 주석 참조). 그래서 이 배치는 돌 때마다 두 표를
TRUNCATE 하고 처음부터 다시 계산한다.

실행:
  .venv/Scripts/python tools/game_cell_mapper.py --dry
  .venv/Scripts/python tools/game_cell_mapper.py

GPU 칩셋 파싱 — games.rec_gpu/min_gpu 는 자유문자열("NVIDIA GeForce X / AMD Y" 형태)
이라 api.catalog_map.gpu_chipset_key()(상품명 전용 파서)로는 못 돌린다. 대신
gpu_ladder.chipset 목록을 후보로 두고 문자열이 그 칩셋명을 부분 문자열로 포함하는지
본다(긴 칩셋명부터 검사 -- "RTX 5060 TI"가 "RTX 5060"보다 먼저 매칭돼야 한다).
매칭된 후보 중 최고 점수를 기준으로 쓴다(설계 문서 SS2 "최고 rank 하나 = 기준
rank" 그대로). 매칭이 하나도 안 되면 억지로 맞추지 않고 그 게임(또는 그 필드)을
스킵한다 -- 애매하면 스킵.

칸 GPU -- grid_quotes(is_current).payload.items 의 part_type=GPU 행의 name 을
api.catalog_map.gpu_chipset_key() 로 정규화한다. "RTX 5090 XT"(워터블럭 변형,
팝콘PC 판매몰 표기)는 gpu_ladder 에 없으므로 "RTX 5090"으로 흡수한다(0074
마이그레이션 note가 로더 소관으로 남긴 규칙).

RAM 하한 -- games.rec_ram_gb / ai_workloads.min_ram_gb 는 그 칸 견적의 part_type=RAM
행들의 product_specs.capacity_gb 합과 비교한다. 부족하면 한 단계 강등한다(권장충족
->최소충족, 권장구성->구동가능). 이미 최하단이면 그대로 둔다 -- 설계 문서가 배제를
요구한 것은 GPU 미달뿐이다.

콘솔 출력은 ASCII만 쓴다(cp949 콘솔 깨짐 방지, grid_generate.py와 같은 관례). 게임/
작업 이름 같은 한글은 마지막 줄의 SUMMARY_JSON 한 줄(ensure_ascii=True로 \\uXXXX
이스케이프)에 담아 낸다 -- 콘솔은 순수 ASCII를 유지하면서 정보는 잃지 않는다.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console        # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                        # noqa: E402
from sqlalchemy import create_engine, text             # noqa: E402

from api.catalog_map import gpu_chipset_key            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 팝콘PC 판매몰 표기 "RTX 5090 XT"(워터블럭 변형) -> gpu_ladder 표 "RTX 5090"으로 흡수.
# 0074_gpu_ladder.py 머리 주석이 "로더 구현 소관"으로 남긴 규칙.
GPU_KEY_ABSORB = {"RTX 5090 XT": "RTX 5090"}


def _match_chipset_text(text_val: str, ladder: dict, chipsets_by_len: list):
    """자유문자열에서 gpu_ladder 후보를 부분 문자열로 찾아 최고 점수 하나를 돌려준다.

    돌려주는 값: (chipset, score) 또는 매칭 없으면 (None, None).
    """
    if not text_val:
        return None, None
    norm = re.sub(r"\s+", " ", text_val).upper()
    best_chipset, best_score = None, None
    for cs in chipsets_by_len:
        if cs in norm:
            score = ladder[cs][0]
            if best_score is None or score > best_score:
                best_chipset, best_score = cs, score
    return best_chipset, best_score


def _build_cell_index(conn, ladder: dict):
    """is_current grid_quotes 각 칸의 (GPU 칩셋 점수/VRAM, RAM 합)을 미리 구한다."""
    rows = conn.execute(text(
        "SELECT cell_id, payload FROM grid_quotes WHERE is_current")).mappings().all()

    raw = []
    all_ram_codes = set()
    for r in rows:
        cid = r["cell_id"]
        items = ((r["payload"] or {}).get("items")) or []
        gpu_item = next((it for it in items if it.get("part_type") == "GPU"), None)
        ram_codes = [it.get("product_code") for it in items
                     if it.get("part_type") == "RAM" and it.get("product_code")]
        all_ram_codes.update(ram_codes)
        raw.append((cid, gpu_item, ram_codes))

    cap_map = {}
    if all_ram_codes:
        cap_rows = conn.execute(text(
            "SELECT product_code, capacity_gb FROM product_specs"
            " WHERE product_code = ANY(:codes)"),
            {"codes": list(all_ram_codes)}).mappings().all()
        cap_map = {cr["product_code"]: cr["capacity_gb"] for cr in cap_rows}

    cell_index = {}
    skip_reasons = Counter()
    skip_detail = []
    for cid, gpu_item, ram_codes in raw:
        if not gpu_item or not gpu_item.get("name"):
            skip_reasons["cell_gpu_item_missing"] += 1
            skip_detail.append({"cell_id": cid, "reason": "cell_gpu_item_missing"})
            continue
        raw_key = gpu_chipset_key(gpu_item["name"])
        lookup_key = GPU_KEY_ABSORB.get(raw_key, raw_key)
        if not lookup_key or lookup_key not in ladder:
            skip_reasons["cell_gpu_not_in_ladder"] += 1
            skip_detail.append({"cell_id": cid, "reason": "cell_gpu_not_in_ladder",
                                 "chipset": raw_key, "name": gpu_item["name"]})
            continue
        score, vram = ladder[lookup_key]
        ram_gb = sum((cap_map.get(c) or 0) for c in ram_codes)
        cell_index[cid] = {"chipset": lookup_key, "score": score, "vram": vram,
                            "ram_gb": ram_gb}

    return cell_index, len(rows), skip_reasons, skip_detail


def _map_games(conn, ladder: dict, chipsets_by_len: list, cell_index: dict):
    games = conn.execute(text(
        "SELECT game_id, name, rec_gpu, min_gpu, rec_ram_gb"
        " FROM games ORDER BY game_id")).mappings().all()

    insert_rows = []
    per_game = []
    skip_reasons = Counter()
    skip_detail = []

    for g in games:
        if not g["rec_gpu"]:
            skip_reasons["rec_gpu_missing"] += 1
            skip_detail.append({"game": g["name"], "reason": "rec_gpu_missing"})
            continue

        rec_chipset, rec_score = _match_chipset_text(g["rec_gpu"], ladder, chipsets_by_len)
        if rec_score is None:
            skip_reasons["rec_gpu_parse_failed"] += 1
            skip_detail.append({"game": g["name"], "reason": "rec_gpu_parse_failed",
                                 "rec_gpu": g["rec_gpu"]})
            continue

        min_chipset, min_score = (None, None)
        if g["min_gpu"]:
            min_chipset, min_score = _match_chipset_text(g["min_gpu"], ladder, chipsets_by_len)
            if min_score is None:
                skip_reasons["min_gpu_parse_failed_partial"] += 1
                skip_detail.append({"game": g["name"], "reason": "min_gpu_parse_failed_partial",
                                     "min_gpu": g["min_gpu"]})
                # 게임 자체는 스킵하지 않는다 -- 권장충족 판정은 여전히 가능.

        matched = 0
        for cid, info in cell_index.items():
            if info["score"] >= rec_score:
                level = "권장충족"
            elif min_score is not None and info["score"] >= min_score:
                level = "최소충족"
            else:
                continue
            if (level == "권장충족" and g["rec_ram_gb"] is not None
                    and info["ram_gb"] < g["rec_ram_gb"]):
                level = "최소충족"
            insert_rows.append((g["game_id"], cid, level, info["chipset"]))
            matched += 1

        per_game.append({"game_id": g["game_id"], "name": g["name"],
                          "rec_chipset": rec_chipset, "min_chipset": min_chipset,
                          "matched_cells": matched})
        if matched == 0:
            skip_reasons["zero_matching_cells"] += 1
            skip_detail.append({"game": g["name"], "reason": "zero_matching_cells",
                                 "rec_chipset": rec_chipset})

    return insert_rows, per_game, len(games), skip_reasons, skip_detail


def _map_workloads(conn, cell_index: dict):
    workloads = conn.execute(text(
        "SELECT workload_id, task, model_size, min_vram_gb, rec_vram_gb, min_ram_gb"
        " FROM ai_workloads ORDER BY workload_id")).mappings().all()

    insert_rows = []
    per_workload = []
    skip_reasons = Counter()
    skip_detail = []

    for w in workloads:
        label = (w["task"] or "") + ((" " + w["model_size"]) if w["model_size"] else "")
        if w["min_vram_gb"] is None:
            skip_reasons["min_vram_gb_missing"] += 1
            skip_detail.append({"workload": label, "reason": "min_vram_gb_missing"})
            continue

        matched = 0
        for cid, info in cell_index.items():
            if info["vram"] is None:
                continue
            if w["rec_vram_gb"] is not None and info["vram"] >= w["rec_vram_gb"]:
                level = "권장구성"
            elif info["vram"] >= w["min_vram_gb"]:
                level = "구동가능"
            else:
                continue
            if (level == "권장구성" and w["min_ram_gb"] is not None
                    and info["ram_gb"] < w["min_ram_gb"]):
                level = "구동가능"
            insert_rows.append((w["workload_id"], cid, level, info["chipset"]))
            matched += 1

        per_workload.append({"workload_id": w["workload_id"], "label": label,
                              "matched_cells": matched})
        if matched == 0:
            skip_reasons["zero_matching_cells"] += 1
            skip_detail.append({"workload": label, "reason": "zero_matching_cells"})

    return insert_rows, per_workload, len(workloads), skip_reasons, skip_detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as conn:
        ladder_rows = conn.execute(text(
            "SELECT chipset, ladder_score, vram_gb FROM gpu_ladder")).mappings().all()
        ladder = {r["chipset"]: (float(r["ladder_score"]), r["vram_gb"]) for r in ladder_rows}
        chipsets_by_len = sorted(ladder.keys(), key=len, reverse=True)

        cell_index, cells_total, cell_skip_reasons, cell_skip_detail = \
            _build_cell_index(conn, ladder)

        print(f"[game_cell_mapper] gpu_ladder={len(ladder)} grid_quotes_current={cells_total}"
              f" cells_usable={len(cell_index)} cells_skipped={cells_total - len(cell_index)}")

        game_rows, per_game, games_total, game_skip_reasons, game_skip_detail = \
            _map_games(conn, ladder, chipsets_by_len, cell_index)
        print(f"[game_cell_mapper] games_total={games_total}"
              f" games_mapped={sum(1 for g in per_game if g['matched_cells'] > 0)}"
              f" game_rows={len(game_rows)}")

        wl_rows, per_workload, wl_total, wl_skip_reasons, wl_skip_detail = \
            _map_workloads(conn, cell_index)
        print(f"[game_cell_mapper] ai_workloads_total={wl_total}"
              f" workloads_mapped={sum(1 for w in per_workload if w['matched_cells'] > 0)}"
              f" workload_rows={len(wl_rows)}")

        if not args.dry:
            with engine.begin() as wconn:
                wconn.execute(text("TRUNCATE TABLE game_cell_map"))
                wconn.execute(text("TRUNCATE TABLE workload_cell_map"))
                if game_rows:
                    wconn.execute(text(
                        "INSERT INTO game_cell_map (game_id, cell_id, match_level, gpu_used,"
                        " computed_at) VALUES (:gid, :cid, :lvl, :gpu, now())"),
                        [{"gid": gid, "cid": cid, "lvl": lvl, "gpu": gpu}
                         for gid, cid, lvl, gpu in game_rows])
                if wl_rows:
                    wconn.execute(text(
                        "INSERT INTO workload_cell_map (workload_id, cell_id, match_level,"
                        " gpu_used, computed_at) VALUES (:wid, :cid, :lvl, :gpu, now())"),
                        [{"wid": wid, "cid": cid, "lvl": lvl, "gpu": gpu}
                         for wid, cid, lvl, gpu in wl_rows])
            print(f"[game_cell_mapper] written game_cell_map={len(game_rows)}"
                  f" workload_cell_map={len(wl_rows)}")
        else:
            print("[game_cell_mapper] --dry mode -- no rows written")

    summary = {
        "cells": {"total": cells_total, "usable": len(cell_index),
                  "skip_reasons": dict(cell_skip_reasons), "skip_detail": cell_skip_detail},
        "games": {"total": games_total, "rows": len(game_rows),
                  "skip_reasons": dict(game_skip_reasons), "skip_detail": game_skip_detail,
                  "per_game": per_game},
        "ai_workloads": {"total": wl_total, "rows": len(wl_rows),
                          "skip_reasons": dict(wl_skip_reasons), "skip_detail": wl_skip_detail,
                          "per_workload": per_workload},
    }
    print("[game_cell_mapper] SUMMARY_JSON " + json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    main()
