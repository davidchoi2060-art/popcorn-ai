# -*- coding: utf-8 -*-
"""게임 카탈로그 확장 로더 - game_catalog_expanded.json(86종)을 적재한다.

배경: db/migrations/versions/0097_games_catalog_expand.py 가 만든 컬럼/표를 채운다.
값은 이 스크립트가 만들지 않는다 - 조사자가 출처를 붙여 모은 JSON 을 그대로 옮긴다.
JSON 에 null 이면 DB 도 null 이다. 추정으로 메우지 않는다.

기존 tools/game_db_load.py 와 같은 관례를 따른다(UPSERT + COALESCE).
다만 그쪽은 0073 의 game_performance 를 채우고, 이쪽은 0097 의 확장 컬럼과
game_measured_fps / game_popularity_snapshots / game_ratings 를 채운다.

실행:
  .venv/Scripts/python tools/game_catalog_load.py --file D:/Hermes-Workspace/game_catalog_expanded.json --dry
  .venv/Scripts/python tools/game_catalog_load.py --file D:/Hermes-Workspace/game_catalog_expanded.json

■ 기존 23종을 덮어쓰지 않는다 - COALESCE 만으로는 부족했다(실측)
  tools/game_db_load.py 의 COALESCE(EXCLUDED.col, games.col) 은 '새 값이 NULL 이면
  기존 값을 지킨다' 일 뿐, 새 값이 있으면 기존 값을 갈아엎는다. 실측해 보니 기존
  23종에서 **48개 필드가 그렇게 덮어써졌다** - 대부분 description(고객이 읽는
  격자 문구 -> 조사자의 게임 소개문)과 checked_date, 그리고 디아블로4의 정리된
  사양 문자열(-> 원문 (R)(TM) 기호가 붙은 스팀 원문).
  그래서 **기존 컬럼(LEGACY_COLS)에 한해 '기존 값이 NULL 일 때만 채운다'** 로
  더 좁힌다. 0097 로 새로 생긴 컬럼은 전부 NULL 이므로 영향이 없다.
  덮어쓰기를 굳이 원하면 --overwrite-legacy 로 명시해야 한다(기본 꺼짐).
  차단된 건수는 매 실행 때 출력한다 - 조사자 값이 더 나은 경우가 있을 수 있고,
  그 판단은 기획/사장님 몫이지 적재 도구가 조용히 할 일이 아니다.

■ 등급 체계는 건드리지 않는다
  game_load_grades / game_grade_assignments / game_grade_resolution_tiers 를
  읽지도 쓰지도 않는다.

■ 파생값 - 무엇을 '읽어내고' 무엇을 '비워 두는가'

  아래 넷은 JSON 에 독립 필드가 없고, 공식 사양표 원문(official_spec_note)에
  문장으로 들어 있다. 원문은 min_spec_note_raw / rec_spec_note_raw 에 그대로
  싣고, 거기서 '명확할 때만' 정규화 값을 뽑는다.

    rec_target_resolution / rec_target_fps / rec_preset / min_* 도 동일

  판정 규칙: 원문에서 후보가 **정확히 1개**일 때만 채운다. 2개 이상이면 null.
  예) 사일런트힐 f 권장 원문은 "Performance 60FPS 또는 Quality 30FPS" 라 fps
      후보가 둘이다 -> null. 워독스는 "1440p 70fps+ 또는 4K 60fps+" 라 해상도도
      fps 도 둘이다 -> 둘 다 null. 이런 건 기계가 고르면 안 된다.
  뽑히지 않은 건수는 실행할 때마다 출력한다(사람이 감사할 수 있게).

  rec_assumes_upscaling / rec_assumes_frame_gen / requires_ssd / requires_nvme 는
  **언급이 있을 때만 true** 로 둔다. 언급이 없는 것은 false 가 아니라 '모름'이므로
  null 로 남긴다.

  is_active 는 JSON 에 대응 필드가 없어 전부 null 이다.
  is_bucket 은 조사자가 confidence 로 명시한 행("통칭/사양 산정 불가")만 true 로
  두고 나머지는 null 이다 - "나머지는 전부 실제 게임" 은 우리가 단정할 일이 아니다.

  steam_appid 는 official_url 이 store.steampowered.com/app/<id> 형태일 때만 뽑는다.
  rec_gpu_nvidia/amd/intel 은 원문 rec_gpu 를 '/' 로 기계 분할해 벤더 키워드로
  가른 것이다. 원문은 rec_gpu 에 그대로 남는다(출처 보존). 토큰이 컬럼 길이를
  넘으면 자르지 않고 null 로 두고 보고한다.

콘솔 출력은 ASCII 기호만 쓴다(서버 stdout 이 cp949).
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console        # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                        # noqa: E402
from sqlalchemy import create_engine, text             # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# games 에 쓸 컬럼 전체(기존 컬럼 + 0097 신설). name/genre 는 따로 다룬다.
GAME_COLS = (
    "official_source_url", "min_cpu", "min_gpu", "min_ram_gb",
    "rec_cpu", "rec_gpu", "rec_ram_gb", "checked_date", "note", "description",
    "rec_target_resolution", "rec_target_fps", "rec_preset",
    "rec_assumes_upscaling", "rec_assumes_frame_gen",
    "min_target_resolution", "min_target_fps", "min_preset",
    "min_spec_note_raw", "rec_spec_note_raw",
    "min_vram_gb", "rec_vram_gb", "min_storage_gb", "rec_storage_gb",
    "requires_ssd", "requires_nvme",
    "bottleneck", "bottleneck_evidence", "fps_sensitivity",
    "name_en", "steam_appid", "vendor", "release_date", "is_bucket", "is_active",
    "confidence", "rec_gpu_nvidia", "rec_gpu_amd", "rec_gpu_intel",
    "community_note", "community_source_urls", "source_urls",
)

# 0097 이전부터 있던 컬럼. 기존 23종에 대해서는 '기존 값이 NULL 일 때만' 채운다
# (머리 주석 참조). genre/name 은 키라 여기 넣지 않는다.
LEGACY_COLS = (
    "official_source_url", "min_cpu", "min_gpu", "min_ram_gb",
    "rec_cpu", "rec_gpu", "rec_ram_gb", "checked_date", "note", "description",
)

_RES_PAT = re.compile(
    r"(?<![0-9a-zA-Z])(720p|1080p|1440p|2160p|4k|2560x1440|1920x1080|fullhd|fhd)"
    r"(?![0-9a-zA-Z])", re.I)
_RES_NORM = {"2560x1440": "1440p", "1920x1080": "1080p", "fullhd": "1080p",
             "fhd": "1080p", "2160p": "4K", "4k": "4K"}
_FPS_PAT = re.compile(r"(\d{2,3})\s*(?:fps|프레임)", re.I)
_PRESET_PATS = (
    re.compile(r"preset[:\s]*[\"\u201c\u2018']?\s*([A-Za-z]+)", re.I),
    re.compile(r"[\"\u201c\u2018']([A-Za-z]+)[\"\u201d\u2019']\s*graphics setting", re.I),
    re.compile(r"\b(low|medium|high|ultra|epic|average|lowest|highest)\b"
               r"\s*graphics (?:settings?|options?)", re.I),
    re.compile(r"graphics settings? are set to\s*[\"\u201c]?([A-Za-z]+)", re.I),
)
_UPSCALE_PAT = re.compile(r"DLSS|FSR|XeSS|upscal", re.I)
_FRAMEGEN_PAT = re.compile(r"frame\s*gen", re.I)
_SSD_REQ_PAT = re.compile(r"SSD[^.;]{0,30}required|requires?\s+(?:an?\s+)?SSD"
                          r"|SSD\s*Required", re.I)
_NVME_REQ_PAT = re.compile(r"NVMe[^.;]{0,20}required|requires?\s+(?:an?\s+)?NVMe", re.I)
_APPID_PAT = re.compile(r"store\.steampowered\.com/app/(\d+)")
_VENDOR_PATS = (
    ("rec_gpu_nvidia", re.compile(r"NVIDIA|GeForce|GTX|RTX", re.I)),
    ("rec_gpu_amd", re.compile(r"\bAMD\b|Radeon|\bRX\s|\bR[579]\b|\bHD\s*\d", re.I)),
    ("rec_gpu_intel", re.compile(r"\bIntel\b|\bArc\b|\bUHD\b|\bIris\b", re.I)),
)
_DATE_FORMATS = ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B, %Y", "%B %d, %Y")

# 기존 games 의 varchar 폭(0073 이전부터 있던 컬럼). 0097 은 컬럼을 '추가만' 했고
# 기존 컬럼 폭은 건드리지 않았다 - 기존 표 구조를 고치지 않는다는 규약 때문이다.
# 그래서 조사 원문이 이 폭을 넘는 경우가 생긴다. 잘라 넣지 않는다(잘린 값은
# 원문인 척하는 가짜다). 그 컬럼만 비우고 사람이 볼 수 있게 보고한다.
_LEGACY_WIDTH = {
    "min_cpu": 160, "min_gpu": 160, "rec_cpu": 160, "rec_gpu": 160,
    "note": 200, "official_source_url": 300, "name": 60, "genre": 30,
}


def _one(pat, textv, norm=None):
    """원문에서 후보가 정확히 1개일 때만 돌려준다. 여러 개면 None(기계가 고르지 않는다)."""
    if not textv:
        return None
    found = []
    for m in pat.finditer(textv):
        v = m.group(1)
        v = norm.get(v.lower(), v) if norm else v
        if v not in found:
            found.append(v)
    return found[0] if len(found) == 1 else None


def _preset(textv):
    if not textv:
        return None
    for pat in _PRESET_PATS:
        v = _one(pat, textv)
        if v:
            return v
    return None


def _parse_date(s):
    if not s:
        return None
    s = s.strip()
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    return None


def _jsonb(v):
    return json.dumps(v, ensure_ascii=False) if v else None


def build(items):
    rows, fps_rows, pop_rows, rating_rows = [], [], [], []
    skipped, unparsed = [], []

    for it in items:
        name = (it.get("name") or "").strip()
        if not name:
            skipped.append(("(no name)", "missing name"))
            continue
        if not it.get("genre"):
            # games.genre 는 NOT NULL 이다. '미분류' 를 지어내지 않는다.
            skipped.append((name, "missing genre (NOT NULL)"))
            continue

        spec = it.get("official_spec_note") or {}
        min_raw, rec_raw = spec.get("min"), spec.get("rec")
        both = " ".join(x for x in (min_raw, rec_raw) if x)

        p = {c: None for c in GAME_COLS}
        p["name"] = name
        p["genre"] = it["genre"]
        for k in ("official_source_url",):
            p[k] = it.get("official_url")
        for k in ("min_cpu", "min_gpu", "min_ram_gb", "rec_cpu", "rec_gpu",
                  "rec_ram_gb", "checked_date", "note", "description",
                  "min_vram_gb", "rec_vram_gb", "min_storage_gb",
                  "bottleneck", "fps_sensitivity", "name_en", "vendor",
                  "confidence"):
            p[k] = it.get(k)
        # RAM/VRAM/용량은 integer 컬럼이다. 조사 원문이 소수인 경우가 있다
        # (테라리아 min_ram_gb=2.5). Postgres 가 조용히 반올림해 3 이 되면 원문과
        # 다른 값이 정본인 척하게 되므로, 반올림 사실을 반드시 보고한다.
        for k in ("min_ram_gb", "rec_ram_gb", "min_vram_gb", "rec_vram_gb",
                  "min_storage_gb"):
            v = p.get(k)
            if isinstance(v, float) and v != int(v):
                # Postgres 의 정수 캐스팅은 '0에서 먼 쪽'으로 반올림한다(2.5 -> 3).
                # 파이썬 round() 는 짝수 쪽으로 가므로(2.5 -> 2) 쓰지 않는다.
                stored = int(v + (0.5 if v >= 0 else -0.5))
                unparsed.append((name, k,
                                 f"json={v} is fractional; integer column -> stored as "
                                 f"{stored} (rounded, see loader header)"))
        # rec_storage_gb 는 JSON 에 필드가 없다 - null 로 둔다(min 값을 복사하지 않는다).

        p["min_spec_note_raw"] = min_raw
        p["rec_spec_note_raw"] = rec_raw
        p["min_target_resolution"] = _one(_RES_PAT, min_raw, _RES_NORM)
        p["rec_target_resolution"] = _one(_RES_PAT, rec_raw, _RES_NORM)
        mf = _one(_FPS_PAT, min_raw)
        rf = _one(_FPS_PAT, rec_raw)
        p["min_target_fps"] = int(mf) if mf else None
        p["rec_target_fps"] = int(rf) if rf else None
        p["min_preset"] = _preset(min_raw)
        p["rec_preset"] = _preset(rec_raw)
        p["rec_assumes_upscaling"] = True if rec_raw and _UPSCALE_PAT.search(rec_raw) else None
        p["rec_assumes_frame_gen"] = True if rec_raw and _FRAMEGEN_PAT.search(rec_raw) else None
        p["requires_ssd"] = True if both and _SSD_REQ_PAT.search(both) else None
        p["requires_nvme"] = True if both and _NVME_REQ_PAT.search(both) else None

        p["bottleneck_evidence"] = it.get("community_note")  # 근거 문장 + URL 이 여기 있다
        p["community_note"] = it.get("community_note")
        p["community_source_urls"] = _jsonb(it.get("community_sources"))
        p["source_urls"] = _jsonb(it.get("sources"))
        p["release_date"] = _parse_date(it.get("release"))
        if it.get("release") and not p["release_date"]:
            unparsed.append((name, "release", it["release"]))

        m = _APPID_PAT.search(it.get("official_url") or "")
        p["steam_appid"] = int(m.group(1)) if m else None

        conf = it.get("confidence") or ""
        p["is_bucket"] = True if conf.startswith("통칭") else None
        p["is_active"] = None   # JSON 에 대응 필드가 없다

        rg = it.get("rec_gpu")
        if rg:
            for col, vpat in _VENDOR_PATS:
                for tok in re.split(r"\s*/\s*", rg):
                    tok = tok.strip()
                    if tok and vpat.search(tok):
                        if len(tok) <= 80:
                            p[col] = tok
                        else:
                            unparsed.append((name, col, "token too long"))
                        break
        rows.append(p)

        # 기존 컬럼 폭 초과분은 싣지 않고 보고한다(자르지 않는다)
        for col, width in _LEGACY_WIDTH.items():
            v = p.get(col)
            if isinstance(v, str) and len(v) > width:
                unparsed.append((name, col,
                                 f"len={len(v)} > legacy varchar({width}) -> left NULL"))
                p[col] = None

        # ---- 실측 fps ----
        for mfps in it.get("measured_fps") or []:
            if not mfps.get("source_url"):
                unparsed.append((name, "measured_fps", "no source_url -> skipped"))
                continue
            note = mfps.get("note") or ""
            fps_rows.append({
                "name": name,
                "gpu_model": mfps.get("gpu"),
                "cpu_model": None,
                "resolution": mfps.get("resolution"),
                "preset": mfps.get("preset"),
                "upscaling": None,
                "frame_gen": None,
                "ray_tracing": None,
                "fps_avg": mfps.get("fps"),
                "fps_1pct_low": None,
                # 조사자 note 가 "60fps 를 넘는 최저 등급" 이라고 명시한 행만 임계값이다.
                "is_threshold": True if "최저 등급" in note else None,
                "source_url": mfps["source_url"],
                "source_name": None,
                "measured_date": None,
                "note": note or None,
            })

        # ---- 인기 스냅샷 ----
        ra = it.get("ratings") or {}
        src = ra.get("pcbang_source") or ""
        if ra.get("pcbang_rank") is not None or ra.get("pcbang_share_pct") is not None:
            dm = re.search(r"(\d{4}-\d{2}-\d{2})", src)
            if not dm:
                unparsed.append((name, "pcbang", "no snapshot date in source -> skipped"))
            else:
                key = ("gametrics" if "gametrics.com" in src else
                       "gametrics_secondary")
                pop_rows.append({
                    "name": name, "snapshot_date": dm.group(1), "source": key,
                    "pcbang_rank": ra.get("pcbang_rank"),
                    "pcbang_share_pct": ra.get("pcbang_share_pct"),
                    "steam_ccu": None, "steam_ccu_peak": None,
                    "source_url": src,
                })
        if ra.get("concurrent_players_steam") is not None:
            asof = ra.get("concurrent_players_asof")
            if not asof:
                unparsed.append((name, "steam_ccu", "no asof date -> skipped"))
            else:
                pop_rows.append({
                    "name": name, "snapshot_date": asof, "source": "steam_api",
                    "pcbang_rank": None, "pcbang_share_pct": None,
                    "steam_ccu": ra["concurrent_players_steam"],
                    "steam_ccu_peak": None, "source_url": None,
                })

        # ---- 평점 ----
        if ra.get("metacritic") is not None:
            rating_rows.append({
                "name": name, "source": "metacritic", "score": ra["metacritic"],
                "sample_size": None, "score_desc": None, "source_url": None,
                "checked_date": it.get("checked_date"),
            })
        if ra.get("opencritic") is not None:
            rating_rows.append({
                "name": name, "source": "opencritic", "score": ra["opencritic"],
                "sample_size": None, "score_desc": None, "source_url": None,
                "checked_date": it.get("checked_date"),
            })
        if ra.get("steam_pct") is not None:
            rating_rows.append({
                "name": name, "source": "steam", "score": ra["steam_pct"],
                "sample_size": ra.get("steam_review_n"),
                "score_desc": ra.get("steam_desc"),
                "source_url": it.get("official_url"),
                "checked_date": it.get("checked_date"),
            })

    return rows, fps_rows, pop_rows, rating_rows, skipped, unparsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", nargs="+", required=True, metavar="JSON")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--overwrite-legacy", action="store_true",
                    help="기존 컬럼의 기존 값을 조사 값으로 덮어쓴다(기본 꺼짐)")
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

    rows, fps_rows, pop_rows, rating_rows, skipped, unparsed = build(items)

    with engine.connect() as conn:
        have = {r[0] for r in conn.execute(text("SELECT name FROM games"))}
        legacy_now = {
            r[0]: dict(zip(LEGACY_COLS, r[1:]))
            for r in conn.execute(text(
                "SELECT name, " + ", ".join(LEGACY_COLS) + " FROM games"))
        }
    new = [r for r in rows if r["name"] not in have]
    upd = [r for r in rows if r["name"] in have]

    # 기존 컬럼 보호 - 기존 값이 이미 있는 칸은 조사 값을 싣지 않는다
    blocked = []
    for r in upd:
        cur = legacy_now.get(r["name"], {})
        for col in LEGACY_COLS:
            if cur.get(col) is not None and r[col] is not None \
                    and str(cur[col]) != str(r[col]):
                blocked.append((r["name"], col))
                if not args.overwrite_legacy:
                    r[col] = None

    print(f"input: {len(items)} / loadable: {len(rows)} / skipped: {len(skipped)}")
    print(f"games: new={len(new)} update(existing)={len(upd)}")
    mode = "OVERWRITTEN" if args.overwrite_legacy else "left as-is"
    print(f"legacy columns with a differing existing value: {len(blocked)} ({mode})")
    for name, col in blocked:
        print(f"  legacy keep: {name}.{col}")
    print(f"game_measured_fps: {len(fps_rows)}")
    print(f"game_popularity_snapshots: {len(pop_rows)}")
    print(f"game_ratings: {len(rating_rows)}")
    for name, why in skipped:
        print(f"  skip: {name} reason={why}")
    for name, field, why in unparsed[:20]:
        print(f"  unparsed: {name} field={field} reason={why}")

    # 정규화 추출 감사표 - 몇 건이나 뽑혔는지 사람이 보고 판단하게 한다
    for col in ("rec_target_resolution", "rec_target_fps", "rec_preset",
                "min_target_resolution", "min_target_fps", "min_preset",
                "rec_assumes_upscaling", "rec_assumes_frame_gen",
                "requires_ssd", "requires_nvme", "steam_appid", "release_date",
                "rec_gpu_nvidia", "rec_gpu_amd", "rec_gpu_intel"):
        n = sum(1 for r in rows if r[col] is not None)
        print(f"  extracted {col}: {n}/{len(rows)}")

    if args.dry:
        print("\n--dry mode -- no rows written")
        return

    g = f = pw = rw = 0
    with engine.begin() as conn:
        placeholders = ", ".join(f":{c}" for c in GAME_COLS)
        # COALESCE - 기존 23종의 기존 값을 덮어쓰지 않는다
        excl = ", ".join(f"{c} = COALESCE(EXCLUDED.{c}, games.{c})" for c in GAME_COLS)
        excl += ", genre = COALESCE(EXCLUDED.genre, games.genre)"
        for p in rows:
            conn.execute(text(f"""
                INSERT INTO games (name, genre, {", ".join(GAME_COLS)})
                VALUES (:name, :genre, {placeholders})
                ON CONFLICT (name) DO UPDATE SET {excl}
            """), p)
            g += 1

        ids = {r[1]: r[0] for r in conn.execute(text("SELECT game_id, name FROM games"))}

        for r in fps_rows:
            gid = ids.get(r["name"])
            if gid is None or not r["gpu_model"] or not r["resolution"] or not r["preset"]:
                print(f"  skip fps: {r['name']} reason=missing key field")
                continue
            conn.execute(text("""
                INSERT INTO game_measured_fps
                  (game_id, gpu_model, cpu_model, resolution, preset, upscaling,
                   frame_gen, ray_tracing, fps_avg, fps_1pct_low, is_threshold,
                   source_url, source_name, measured_date, note)
                VALUES (:gid, :gpu_model, :cpu_model, :resolution, :preset, :upscaling,
                        :frame_gen, :ray_tracing, :fps_avg, :fps_1pct_low, :is_threshold,
                        :source_url, :source_name, :measured_date, :note)
                ON CONFLICT (game_id, gpu_model, resolution, preset) DO UPDATE SET
                  fps_avg = EXCLUDED.fps_avg, is_threshold = EXCLUDED.is_threshold,
                  source_url = EXCLUDED.source_url, note = EXCLUDED.note
            """), dict(r, gid=gid))
            f += 1

        for r in pop_rows:
            gid = ids.get(r["name"])
            if gid is None:
                continue
            conn.execute(text("""
                INSERT INTO game_popularity_snapshots
                  (game_id, snapshot_date, source, pcbang_rank, pcbang_share_pct,
                   steam_ccu, steam_ccu_peak, source_url)
                VALUES (:gid, :snapshot_date, :source, :pcbang_rank, :pcbang_share_pct,
                        :steam_ccu, :steam_ccu_peak, :source_url)
                ON CONFLICT (game_id, snapshot_date, source) DO UPDATE SET
                  pcbang_rank = EXCLUDED.pcbang_rank,
                  pcbang_share_pct = EXCLUDED.pcbang_share_pct,
                  steam_ccu = EXCLUDED.steam_ccu,
                  source_url = COALESCE(EXCLUDED.source_url,
                                        game_popularity_snapshots.source_url)
            """), dict(r, gid=gid))
            pw += 1

        for r in rating_rows:
            gid = ids.get(r["name"])
            if gid is None:
                continue
            conn.execute(text("""
                INSERT INTO game_ratings
                  (game_id, source, score, sample_size, score_desc, source_url, checked_date)
                VALUES (:gid, :source, :score, :sample_size, :score_desc,
                        :source_url, :checked_date)
                ON CONFLICT (game_id, source) DO UPDATE SET
                  score = EXCLUDED.score, sample_size = EXCLUDED.sample_size,
                  score_desc = EXCLUDED.score_desc,
                  source_url = COALESCE(EXCLUDED.source_url, game_ratings.source_url),
                  checked_date = EXCLUDED.checked_date
            """), dict(r, gid=gid))
            rw += 1

    print(f"\nwritten: games={g} game_measured_fps={f} "
          f"game_popularity_snapshots={pw} game_ratings={rw}")


if __name__ == "__main__":
    main()
