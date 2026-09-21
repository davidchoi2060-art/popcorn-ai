# -*- coding: utf-8 -*-
"""게임·AI 작업 <-> 격자 칸 매핑 배치 — game_cell_map·workload_cell_map 재계산.

배경: docs/design/game-quote-mapping-2026-09-07.md SS2(판정 3경로)·SS5(작업 순서 (2)).
저장 구조: db/migrations/versions/0075_cell_maps.py + 0109_cell_map_variant_axis.py —
이 두 표는 파생 캐시다(원장이 아니다, 0075 머리 주석 참조). 그래서 이 배치는 돌
때마다 두 표를 TRUNCATE 하고 처음부터 다시 계산한다.

실행:
  .venv/Scripts/python tools/game_cell_mapper.py --dry
  .venv/Scripts/python tools/game_cell_mapper.py

────────────────────────────────────────────────────────────────────────
■ 판정 단위는 «칸»이 아니라 «견적»이다 (0109 · 2026-09-21)

  0092 이후 칸 하나가 (가성비·추천·고성능) 현재본을 갖는다 — 실측 134칸 · 388행.
  옛 코드는 `cell_index[cell_id] = ...` 로 칸을 키로 써서 뒤에 읽힌 1벌이 앞의
  2벌을 **조용히 덮어썼다**. 실측: 134칸 중 **98칸**이 변종마다 GPU 칩셋이 다르다.

      cell 97(게임/QHD)  가성비 RTX 3050(21.9) / 추천 RTX 5060(43.4) / 고성능 RTX 5070 TI(76.2)

  어느 변종이 남는지가 SELECT 의 행 순서에 달려 있었다 — 순서 보장이 없으니 같은
  게임이 어제는 되고 오늘은 안 되는 상태였다. 이제 키를 `(cell_id, tier_variant)`
  로 두고 **변종마다 따로 판정한다**. 대안(칸 대표값 고정)을 왜 버렸는지는 0109
  머리 주석에 적었다.

■ 「가벼운 게임」 판정 경로 — 사장님 확정(2026-09-21)

  인용: "사다리 밖 가벼운 게임은 «모든 게임 칸에서 돌아간다» 로 판정한다
        (공식 권장이 우리 최저 GPU 보다 낮으니 사실이다)"

  ★ «가벼움»을 문자열로 판정하지 않는다. 조건을 **데이터 둘의 논리곱**으로 세운다:

      (1) `games.rec_gpu` 가 `gpu_ladder` 어느 칩셋과도 매칭되지 않는다
          -> 그 칩이 우리 서열표 **밖**이라는 사실. 서열표 최하단은 RX 560(7.5)이다.
      (2) `game_grade_assignments` 에 그 게임의 **확정(is_confirmed) 등급**이 있고
          그 값이 **E(경쟁 이스포츠) 또는 L(경량)** 이다
          -> 사람이 이미 «가볍다»고 판정한 사실. 우리 DB 의 사람확정 값이다.

  (1)만으로는 가벼움이 아니다 — 서열표 밖에는 «너무 구형»과 «우리가 안 파는 현대
  칩» 이 섞여 있다. 실측으로 엘든링(GTX 1070 권장 · 확정등급 A)이 (1)에 걸린다.
  그건 파싱 실패지 가벼운 게 아니다. (2)가 그 둘을 가른다.

  실측 결과 (1)∧(2) = **13종**. 전부 확정 등급 E 4종 · L 9종이다.
  (1)∧¬(2) 중 확정등급 A/B/C/S = 10종(서열표 구멍) · 등급 미확정 = 1종(WoW).

  ★ 붙이는 범위 — **게임 칸에 한한다.**
    사장님 문구가 «모든 게임 칸»이다. `grid_cells.usage = '게임'` 인 칸의 견적만
    대상으로 한다. 내장그래픽 칸(cell 107·108)은 견적에 GPU 항목 자체가 없어
    아래 `_build_quote_index()` 단계에서 이미 빠진다 — 이번 범위 밖이다.
    (그 칸의 판단은 별도 사안이다. `game_matrix_gap.md` SS3 이 양쪽 근거를 적어 뒀다.)
    비게임 칸(사무·개발·방송 등)에도 GPU 가 달린 견적이 있으나 **붙이지 않는다** —
    사장님이 고른 문구를 임의로 넓히지 않는다.

  ★ 등급 — `경량충족`. 기존 어휘(권장충족·최소충족)에 합치지 않는다.
    권장충족은 «칸 GPU 점수 >= 게임 권장 점수»를 서열표로 대조한 결과다. 경량충족은
    그 대조를 **하지 못한 채** 사람확정 등급으로 판정한 것이라 **근거 경로가 다르다.**
    같은 라벨에 넣으면 화면이 서로 다른 두 근거를 한 말로 부르게 된다.
    화면(`templates/admin/game_matrix.html.j2`)이 이 등급을 통과 색으로 알아보고,
    근거 패널이 서열 점수 대신 이 경로를 밝히도록 같은 커밋에서 고쳤다.

■ 스킵 사유는 **매번 전 종을 다시 쓴다**
  옛 코드는 이번 실행에서 다룬 id 만 UPDATE 해 게임 23종 시절의 값이 그대로 남아
  있었다(실측 8행 / 86종). 사유 없이 빈 게임이 63종이면 화면은 「판정 불가」 배지도
  못 띄운다 — 고객도 운영자도 이유를 모른다. 이제 `games` 전 행을 대상으로
  «사유 또는 NULL» 을 한 번에 덮어쓴다.

  사유 키 — 서열표 밖 파싱 실패를 **셋으로 가른다**(옛 코드는 전부
  `rec_gpu_parse_failed` 하나였고, 그 문구가 "대부분의 PC에서 충분히 돌아갈
  것으로 보이나" 라고 **추정**을 말하고 있었다):
      light_game_all_game_cells   -> 사유가 아니다. 매핑된다(위 경로).
      rec_gpu_not_in_ladder       -> 확정등급 A/B/C/S. 서열표에 그 칩이 없다.
      rec_gpu_grade_unassigned    -> 등급 미확정 + 서열표 밖. 판정 근거가 둘 다 없다.
      rec_gpu_missing             -> 원천에 값이 없다(종전과 같다).
      zero_matching_cells         -> 파싱은 됐으나 성립 견적이 0건.

■ 로그 수치 — 단위를 섞지 않는다
  옛 출력의 `cells_skipped = cells_total - len(cell_index)` 는 **견적 행 수에서 칸
  수를 뺀 값**(388 - 98 = 290)이라 대응하는 실체가 없었다. 이제 칸은 칸끼리, 견적은
  견적끼리 센다. 로그가 거짓말을 하면 다음 사람이 오판한다.

GPU 칩셋 파싱 — games.rec_gpu/min_gpu 는 자유문자열("NVIDIA GeForce X / AMD Y" 형태)
이라 api.catalog_map.gpu_chipset_key()(상품명 전용 파서)로는 못 돌린다. 대신
gpu_ladder.chipset 목록을 후보로 두고 문자열이 그 칩셋명을 부분 문자열로 포함하는지
본다(긴 칩셋명부터 검사 -- "RTX 5060 TI"가 "RTX 5060"보다 먼저 매칭돼야 한다).
매칭된 후보 중 최고 점수를 기준으로 쓴다(설계 문서 SS2 "최고 rank 하나 = 기준
rank" 그대로). 매칭이 하나도 안 되면 억지로 맞추지 않는다 -- 애매하면 스킵.

칸 GPU -- grid_quotes(is_current).payload.items 의 part_type=GPU 행의 name 을
api.catalog_map.gpu_chipset_key() 로 정규화한다. "RTX 5090 XT"(워터블럭 변형,
팝콘PC 판매몰 표기)는 gpu_ladder 에 없으므로 "RTX 5090"으로 흡수한다(0074
마이그레이션 note가 로더 소관으로 남긴 규칙).

RAM 하한 -- games.rec_ram_gb / ai_workloads.min_ram_gb 는 그 견적의 part_type=RAM
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

# 「가벼운 게임」 판정에 쓰는 사람확정 등급 — game_grade_assignments.grade.
# E = 경쟁 이스포츠, L = 경량. 0091 이 정의한 어휘다. 여기에 A/B/C/S 를 넣으면
# 파싱 실패를 가벼움으로 오판한다(엘든링이 그 예다 — 머리 주석 참조).
LIGHT_GRADES = ("E", "L")

# 가벼운 게임을 붙일 칸의 용도 — 사장님 문구 「모든 게임 칸」 그대로.
GAME_USAGE = "게임"

# 매칭 등급 어휘. 경량충족은 근거 경로가 달라 별도 라벨이다(머리 주석 참조).
LV_REC, LV_MIN, LV_LIGHT = "권장충족", "최소충족", "경량충족"


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


def _build_quote_index(conn, ladder: dict):
    """is_current grid_quotes **한 벌마다** (GPU 칩셋 점수/VRAM, RAM 합)을 구한다.

    키가 `(cell_id, tier_variant)` 다 — 칸이 아니다. 옛 코드가 칸을 키로 써서
    변종 2벌을 조용히 버린 것이 이번 결함의 핵심이었다(머리 주석 SS판정 단위).
    """
    rows = conn.execute(text(
        "SELECT q.cell_id, q.tier_variant, q.payload, c.usage, c.platform"
        " FROM grid_quotes q JOIN grid_cells c ON c.cell_id = q.cell_id"
        " WHERE q.is_current"
        " ORDER BY q.cell_id, q.tier_variant")).mappings().all()

    raw = []
    all_ram_codes = set()
    for r in rows:
        items = ((r["payload"] or {}).get("items")) or []
        gpu_item = next((it for it in items if it.get("part_type") == "GPU"), None)
        ram_codes = [it.get("product_code") for it in items
                     if it.get("part_type") == "RAM" and it.get("product_code")]
        all_ram_codes.update(ram_codes)
        raw.append((r["cell_id"], r["tier_variant"], r["usage"], gpu_item, ram_codes))

    cap_map = {}
    if all_ram_codes:
        cap_rows = conn.execute(text(
            "SELECT product_code, capacity_gb FROM product_specs"
            " WHERE product_code = ANY(:codes)"),
            {"codes": list(all_ram_codes)}).mappings().all()
        cap_map = {cr["product_code"]: cr["capacity_gb"] for cr in cap_rows}

    quote_index = {}
    skip_reasons = Counter()
    skip_detail = []
    for cid, variant, usage, gpu_item, ram_codes in raw:
        if not gpu_item or not gpu_item.get("name"):
            skip_reasons["quote_gpu_item_missing"] += 1
            skip_detail.append({"cell_id": cid, "tier_variant": variant,
                                 "reason": "quote_gpu_item_missing"})
            continue
        raw_key = gpu_chipset_key(gpu_item["name"])
        lookup_key = GPU_KEY_ABSORB.get(raw_key, raw_key)
        if not lookup_key or lookup_key not in ladder:
            skip_reasons["quote_gpu_not_in_ladder"] += 1
            skip_detail.append({"cell_id": cid, "tier_variant": variant,
                                 "reason": "quote_gpu_not_in_ladder",
                                 "chipset": raw_key, "name": gpu_item["name"]})
            continue
        score, vram = ladder[lookup_key]
        ram_gb = sum((cap_map.get(c) or 0) for c in ram_codes)
        quote_index[(cid, variant)] = {
            "chipset": lookup_key, "score": score, "vram": vram,
            "ram_gb": ram_gb, "usage": usage}

    # 칸 단위 통계 — 로그가 «칸»을 말할 때 쓰는 값. 견적 행 수와 섞지 않는다.
    cells_all = set(r["cell_id"] for r in rows)
    cells_usable = set(cid for cid, _ in quote_index)
    stats = {
        "quotes_total": len(rows),
        "quotes_usable": len(quote_index),
        "quotes_skipped": len(rows) - len(quote_index),
        "cells_total": len(cells_all),
        "cells_usable": len(cells_usable),
        "cells_skipped": len(cells_all - cells_usable),
        "game_cells_usable": len(set(
            cid for (cid, _), v in quote_index.items() if v["usage"] == GAME_USAGE)),
        "game_quotes_usable": sum(
            1 for v in quote_index.values() if v["usage"] == GAME_USAGE),
    }
    return quote_index, stats, skip_reasons, skip_detail


def _light_game_ids(conn):
    """사람이 확정한 «가벼운» 등급(E·L)을 가진 game_id 집합.

    `is_confirmed` 를 반드시 본다 — 미확정 행은 사람이 판정한 사실이 아니다
    (실측: 76행 중 1행이 미확정 = WoW).
    """
    rows = conn.execute(text(
        "SELECT game_id, grade FROM game_grade_assignments"
        " WHERE is_confirmed AND grade = ANY(:g)"), {"g": list(LIGHT_GRADES)}
    ).mappings().all()
    return {r["game_id"]: r["grade"] for r in rows}


def _map_games(conn, ladder: dict, chipsets_by_len: list, quote_index: dict):
    games = conn.execute(text(
        "SELECT game_id, name, rec_gpu, min_gpu, rec_ram_gb"
        " FROM games ORDER BY game_id")).mappings().all()
    light_grades = _light_game_ids(conn)

    insert_rows = []
    per_game = []
    skip_reasons = Counter()
    skip_detail = []

    for g in games:
        gid = g["game_id"]
        if not g["rec_gpu"]:
            skip_reasons["rec_gpu_missing"] += 1
            skip_detail.append({"game_id": gid, "game": g["name"],
                                 "reason": "rec_gpu_missing"})
            continue

        rec_chipset, rec_score = _match_chipset_text(g["rec_gpu"], ladder, chipsets_by_len)

        if rec_score is None:
            # ── 서열표 밖이다. 여기서 «가벼워서 밖»과 «구멍이라 밖»을 가른다.
            grade = light_grades.get(gid)
            if grade is None:
                # 확정 등급이 없거나 E·L 이 아니다 -> 가벼움으로 보지 않는다.
                reason = ("rec_gpu_not_in_ladder"
                          if _has_confirmed_grade(conn, gid)
                          else "rec_gpu_grade_unassigned")
                skip_reasons[reason] += 1
                skip_detail.append({"game_id": gid, "game": g["name"],
                                     "reason": reason, "rec_gpu": g["rec_gpu"]})
                continue

            # 사장님 확정 경로 — 게임 칸의 견적 전부에 «경량충족».
            matched = 0
            for (cid, variant), info in quote_index.items():
                if info["usage"] != GAME_USAGE:
                    continue
                insert_rows.append((gid, cid, variant, LV_LIGHT, info["chipset"]))
                matched += 1
            per_game.append({"game_id": gid, "name": g["name"],
                              "path": "light_game", "grade": grade,
                              "rec_chipset": None, "min_chipset": None,
                              "matched_quotes": matched,
                              "matched_cells": len(set(
                                  cid for (cid, v), info in quote_index.items()
                                  if info["usage"] == GAME_USAGE))})
            skip_reasons["light_game_mapped"] += 1
            if matched == 0:
                skip_reasons["zero_matching_cells"] += 1
                skip_detail.append({"game_id": gid, "game": g["name"],
                                     "reason": "zero_matching_cells"})
            continue

        # ── 서열표 대조 경로(종전과 같다) ───────────────────────────
        min_chipset, min_score = (None, None)
        if g["min_gpu"]:
            min_chipset, min_score = _match_chipset_text(g["min_gpu"], ladder, chipsets_by_len)
            if min_score is None:
                skip_reasons["min_gpu_parse_failed_partial"] += 1
                skip_detail.append({"game": g["name"], "reason": "min_gpu_parse_failed_partial",
                                     "min_gpu": g["min_gpu"]})
                # 게임 자체는 스킵하지 않는다 -- 권장충족 판정은 여전히 가능.

        matched = 0
        matched_cells = set()
        for (cid, variant), info in quote_index.items():
            if info["score"] >= rec_score:
                level = LV_REC
            elif min_score is not None and info["score"] >= min_score:
                level = LV_MIN
            else:
                continue
            if (level == LV_REC and g["rec_ram_gb"] is not None
                    and info["ram_gb"] < g["rec_ram_gb"]):
                level = LV_MIN
            insert_rows.append((gid, cid, variant, level, info["chipset"]))
            matched += 1
            matched_cells.add(cid)

        per_game.append({"game_id": gid, "name": g["name"],
                          "path": "ladder",
                          "rec_chipset": rec_chipset, "min_chipset": min_chipset,
                          "matched_quotes": matched, "matched_cells": len(matched_cells)})
        if matched == 0:
            skip_reasons["zero_matching_cells"] += 1
            skip_detail.append({"game_id": gid, "game": g["name"],
                                 "reason": "zero_matching_cells", "rec_chipset": rec_chipset})

    return insert_rows, per_game, len(games), skip_reasons, skip_detail


_GRADE_CACHE = {}


def _has_confirmed_grade(conn, game_id: int) -> bool:
    """그 게임에 사람확정 등급이 있는가 — 사유 키를 가르는 데만 쓴다.

    있으면 「서열표에 그 칩이 없다」(우리 쪽 결손), 없으면 「등급도 칩도 없다」
    (판정 근거가 둘 다 없다). 두 경우를 한 사유로 뭉개면 운영자가 무엇을
    채워야 하는지 모른다.
    """
    if not _GRADE_CACHE:
        for r in conn.execute(text(
                "SELECT game_id FROM game_grade_assignments WHERE is_confirmed")):
            _GRADE_CACHE[r[0]] = True
    return bool(_GRADE_CACHE.get(game_id))


def _map_workloads(conn, quote_index: dict):
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
            skip_detail.append({"workload_id": w["workload_id"], "workload": label,
                                 "reason": "min_vram_gb_missing"})
            continue

        matched = 0
        matched_cells = set()
        for (cid, variant), info in quote_index.items():
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
            insert_rows.append((w["workload_id"], cid, variant, level, info["chipset"]))
            matched += 1
            matched_cells.add(cid)

        per_workload.append({"workload_id": w["workload_id"], "label": label,
                              "matched_quotes": matched,
                              "matched_cells": len(matched_cells)})
        if matched == 0:
            skip_reasons["zero_matching_cells"] += 1
            skip_detail.append({"workload_id": w["workload_id"], "workload": label,
                                 "reason": "zero_matching_cells"})

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

        quote_index, cstats, cell_skip_reasons, cell_skip_detail = \
            _build_quote_index(conn, ladder)

        # ★ 단위를 섞지 않는다 — 칸은 칸으로, 견적은 견적으로 센다.
        #   옛 출력의 cells_skipped(=388-98=290)는 두 단위를 뺀 허수였다.
        print(f"[game_cell_mapper] gpu_ladder={len(ladder)}"
              f" cells_total={cstats['cells_total']}"
              f" cells_usable={cstats['cells_usable']}"
              f" cells_skipped={cstats['cells_skipped']}"
              f" (cells, not rows)")
        print(f"[game_cell_mapper] quotes_current={cstats['quotes_total']}"
              f" quotes_usable={cstats['quotes_usable']}"
              f" quotes_skipped={cstats['quotes_skipped']}"
              f" game_cells_usable={cstats['game_cells_usable']}"
              f" game_quotes_usable={cstats['game_quotes_usable']}")

        game_rows, per_game, games_total, game_skip_reasons, game_skip_detail = \
            _map_games(conn, ladder, chipsets_by_len, quote_index)
        light_n = sum(1 for g in per_game if g.get("path") == "light_game")
        print(f"[game_cell_mapper] games_total={games_total}"
              f" games_mapped={sum(1 for g in per_game if g['matched_quotes'] > 0)}"
              f" via_ladder={sum(1 for g in per_game if g.get('path') == 'ladder' and g['matched_quotes'] > 0)}"
              f" via_light_path={light_n}"
              f" game_rows={len(game_rows)}")

        wl_rows, per_workload, wl_total, wl_skip_reasons, wl_skip_detail = \
            _map_workloads(conn, quote_index)
        print(f"[game_cell_mapper] ai_workloads_total={wl_total}"
              f" workloads_mapped={sum(1 for w in per_workload if w['matched_quotes'] > 0)}"
              f" workload_rows={len(wl_rows)}")

        # ── 스킵 사유 — **전 종을 매번 다시 쓴다** ──────────────────
        # 옛 코드는 이번 실행에서 다룬 id 만 UPDATE 해서, 게임이 23종에서
        # 86종으로 늘어난 뒤 63종이 «사유 없이» 비어 있었다(화면이 「판정
        # 불가」 배지조차 못 띄운다). 이제 표의 전 행을 모집단으로 둔다 —
        # 매핑된 것은 NULL, 아닌 것은 사유. 둘 중 하나가 반드시 적힌다.
        game_skip_by_id = {d["game_id"]: d["reason"] for d in game_skip_detail if "game_id" in d}
        wl_skip_by_id = {d["workload_id"]: d["reason"] for d in wl_skip_detail if "workload_id" in d}
        mapped_game_ids = {gid for gid, _, _, _, _ in game_rows}
        mapped_wl_ids = {wid for wid, _, _, _, _ in wl_rows}
        all_game_ids = [r[0] for r in conn.execute(text("SELECT game_id FROM games"))]
        all_wl_ids = [r[0] for r in conn.execute(text("SELECT workload_id FROM ai_workloads"))]

        # 사유를 못 만든 채 비는 항목이 있으면 그것 자체가 결함이다 — 로그로 드러낸다.
        reason_gap = [gid for gid in all_game_ids
                      if gid not in mapped_game_ids and not game_skip_by_id.get(gid)]
        print(f"[game_cell_mapper] skip_reason_coverage games={len(all_game_ids)}"
              f" mapped={len(mapped_game_ids)}"
              f" with_reason={len(all_game_ids) - len(mapped_game_ids) - len(reason_gap)}"
              f" reason_missing={len(reason_gap)} {reason_gap[:8]}")

        if not args.dry:
            with engine.begin() as wconn:
                wconn.execute(text("TRUNCATE TABLE game_cell_map"))
                wconn.execute(text("TRUNCATE TABLE workload_cell_map"))
                if game_rows:
                    wconn.execute(text(
                        "INSERT INTO game_cell_map (game_id, cell_id, tier_variant,"
                        " match_level, gpu_used, computed_at)"
                        " VALUES (:gid, :cid, :tv, :lvl, :gpu, now())"),
                        [{"gid": gid, "cid": cid, "tv": tv, "lvl": lvl, "gpu": gpu}
                         for gid, cid, tv, lvl, gpu in game_rows])
                if wl_rows:
                    wconn.execute(text(
                        "INSERT INTO workload_cell_map (workload_id, cell_id, tier_variant,"
                        " match_level, gpu_used, computed_at)"
                        " VALUES (:wid, :cid, :tv, :lvl, :gpu, now())"),
                        [{"wid": wid, "cid": cid, "tv": tv, "lvl": lvl, "gpu": gpu}
                         for wid, cid, tv, lvl, gpu in wl_rows])
                for gid in all_game_ids:
                    reason = None if gid in mapped_game_ids else game_skip_by_id.get(gid)
                    wconn.execute(text(
                        "UPDATE games SET mapping_skip_reason = :r WHERE game_id = :i"),
                        {"r": reason, "i": gid})
                for wid in all_wl_ids:
                    reason = None if wid in mapped_wl_ids else wl_skip_by_id.get(wid)
                    wconn.execute(text(
                        "UPDATE ai_workloads SET mapping_skip_reason = :r WHERE workload_id = :i"),
                        {"r": reason, "i": wid})
            print(f"[game_cell_mapper] written game_cell_map={len(game_rows)}"
                  f" workload_cell_map={len(wl_rows)}"
                  f" skip_reason_rewritten games={len(all_game_ids)}"
                  f" workloads={len(all_wl_ids)}")
        else:
            print("[game_cell_mapper] --dry mode -- no rows written")

    summary = {
        "cells": {**cstats,
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
