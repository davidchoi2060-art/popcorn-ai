# -*- coding: utf-8 -*-
"""게임 커뮤니티 보강분 병합기 - game_catalog_community.json(33종)을 games 에 합친다.

tools/game_catalog_load.py 와 같은 관례를 따른다. 다만 저쪽은 '신규 적재',
이쪽은 **이미 값이 있는 86종 위에 얹는 병합**이라 규칙이 한 단계 더 좁다.

■ 절대 규칙: 기존 값을 지우지 않는다
  앞선 사고(COALESCE(EXCLUDED.c, games.c) 로 기존 23종 48개 필드가 덮어써진 건)와
  같은 유형을 원천 차단한다. 이 도구는 컬럼별로 셋 중 하나로만 동작한다.

    FILL_ONLY   기존이 NULL 일 때만 쓴다. 값이 있으면 절대 안 건드린다.
                -> bottleneck, fps_sensitivity
    APPEND      기존이 NULL 이면 그대로, 값이 있으면 **구분선을 넣고 뒤에 잇는다**.
                기존 문장은 한 글자도 사라지지 않는다.
                -> community_note, bottleneck_evidence
    MERGE_JSON  기존 배열과 새 배열의 합집합(순서 보존, 중복 제거).
                -> community_source_urls

  UPDATE 문에 EXCLUDED 를 쓰지 않는다. 파이썬에서 '쓸 값'을 다 계산한 뒤,
  실제로 바뀌는 칸만 SET 한다. 안 바뀌는 칸은 SQL 에 등장하지도 않는다.

■ 멱등성
  APPEND 는 붙일 본문이 이미 기존 텍스트 안에 있으면 건너뛴다.
  MERGE_JSON 은 합집합이라 두 번 해도 같다.
  fps 는 (game_id, gpu_model, resolution, preset) 유니크 키 + **같은 출처일 때만**
  갱신한다(다른 출처가 선점한 행은 손대지 않고 보고한다).

■ measured_fps - 평균 fps 가 아니다
  조사자 명시: 이 숫자는 개별 GPU 의 실측 평균이 아니라
  "그 조건에서 해당 fps 를 넘기는 **최저 GPU 등급**" 이다.
  그래서 전부 is_threshold=true 로 넣고 note 첫 줄에 그 사실을 박아 둔다.
  평균 fps 로 오해하면 견적이 틀린다.

  JSON 은 한 (게임·GPU등급·해상도·옵션) 조합에 대해 최대 3줄로 온다:
    '평균 fps 하한 도달 등급'   -> fps_avg 후보(하한 25)
    '쾌적 기준(평균 60fps) 도달' -> fps_avg 후보(60). 둘 다 있으면 이쪽을 쓴다(상위 기준).
    '최저 fps 하한 도달 등급'   -> fps_1pct_low
  171줄이 137행으로 접힌다. 접었다는 사실과 원문 3줄은 note 에 전부 남긴다.

■ 확인 14 / 추정 19
  games.community_confidence(0098 신설, 전부 NULL)에 넣는다.
  기존 games.confidence(공식 사양 출처 신뢰도)는 의미가 다르므로 건드리지 않는다.

콘솔 출력은 ASCII 기호만 쓴다(서버 stdout 이 cp949).

실행:
  .venv/Scripts/python tools/game_community_merge.py --file D:/Hermes-Workspace/game_catalog_community.json --dry
  .venv/Scripts/python tools/game_community_merge.py --file D:/Hermes-Workspace/game_catalog_community.json
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

# APPEND 시 기존 문장과 새 문장 사이에 넣는 구분선. 이 문자열이 이미 있으면
# 같은 보강이 들어간 것으로 보고 다시 붙이지 않는다(멱등성).
APPEND_MARK = "[커뮤니티 보강]"
SEP = "\n\n" + APPEND_MARK + " "

FILL_ONLY_COLS = ("bottleneck", "fps_sensitivity")
APPEND_COLS = ("community_note", "bottleneck_evidence")

# game_measured_fps 의 note 머리말. 평균 fps 오독을 막는다.
THRESHOLD_HEAD = ("[임계값] 개별 GPU 실측 평균이 아니라, 그 조건에서 해당 fps 를 "
                  "넘기는 최저 GPU 등급이다. 평균 fps 로 읽으면 안 된다.")

_AVG = "평균 fps 하한"
_COMFORT = "쾌적 기준"
_LOW = "최저 fps 하한"


def _merge_urls(cur, new):
    """기존 배열 + 새 배열 합집합. 순서 보존, 중복 제거. 바뀐 게 없으면 None."""
    cur_list = cur if isinstance(cur, list) else []
    out = list(cur_list)
    for u in (new or []):
        if u not in out:
            out.append(u)
    return out if out != cur_list else None


def build(items):
    """JSON -> (게임별 병합 후보, fps 후보, 스킵 사유) 로 정리한다. DB 는 아직 안 본다."""
    games, fps, skipped = [], [], []

    for it in items:
        name = (it.get("name") or "").strip()
        if not name:
            skipped.append(("(no name)", "missing name"))
            continue

        conf = (it.get("confidence") or "").strip() or None
        if conf and conf not in ("확인", "추정"):
            # 지어내지 않는다. 모르는 값은 넣지 말고 보고한다.
            skipped.append((name, f"unexpected confidence={conf!r} -> not stored"))
            conf = None

        games.append({
            "name": name,
            "community_confidence": conf,
            "community_note": it.get("community_note"),
            # 근거 문장 + 출처 URL 이 community_note 안에 같이 들어 있다.
            # game_catalog_load.py 와 같은 판단을 따른다.
            "bottleneck_evidence": it.get("community_note"),
            "community_source_urls": it.get("community_sources"),
            "bottleneck": None,       # JSON 에 필드가 없다. 지어내지 않는다.
            "fps_sensitivity": None,
        })

        # ---- measured_fps: 3종 기준을 한 행으로 접는다 ----
        buckets = {}
        for m in it.get("measured_fps") or []:
            if not m.get("source_url"):
                skipped.append((name, "measured_fps: no source_url (NOT NULL) -> skipped"))
                continue
            if not (m.get("gpu") and m.get("resolution") and m.get("preset")):
                skipped.append((name, "measured_fps: missing gpu/resolution/preset -> skipped"))
                continue
            key = (m["gpu"], m["resolution"], m["preset"], m["source_url"])
            buckets.setdefault(key, []).append(m)

        for (gpu, res, preset, url), ms in buckets.items():
            avg = low = None
            for m in ms:
                note = m.get("note") or ""
                if _COMFORT in note:
                    avg = m.get("fps")           # 쾌적 기준이 있으면 이쪽이 상위 기준
                elif _AVG in note and avg is None:
                    avg = m.get("fps")
                elif _LOW in note:
                    low = m.get("fps")
            lines = [THRESHOLD_HEAD] + [
                f"- {m.get('note')}: {m.get('fps')}fps" for m in ms]
            fps.append({
                "name": name, "gpu_model": gpu, "resolution": res, "preset": preset,
                "fps_avg": avg, "fps_1pct_low": low,
                "is_threshold": True, "source_url": url,
                "note": "\n".join(lines),
            })

    return games, fps, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", nargs="+", required=True, metavar="JSON")
    ap.add_argument("--dry", action="store_true")
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

    cand_games, cand_fps, skipped = build(items)

    read_cols = ("community_confidence",) + FILL_ONLY_COLS + APPEND_COLS \
        + ("community_source_urls",)
    with engine.connect() as conn:
        cur_rows = {
            r[0]: dict(zip(read_cols, r[1:]))
            for r in conn.execute(text(
                "SELECT name, " + ", ".join(read_cols) + " FROM games"))
        }
        fps_have = {
            (r[0], r[1], r[2], r[3]): r[4]
            for r in conn.execute(text(
                "SELECT g.name, m.gpu_model, m.resolution, m.preset, m.source_url "
                "FROM game_measured_fps m JOIN games g ON g.game_id = m.game_id"))
        }

    # ---- 컬럼별로 '쓸 값' 을 확정한다. 기존 값은 어떤 경우에도 줄어들지 않는다 ----
    plans, missing, blocked, appended, noop = [], [], [], [], []
    for r in cand_games:
        cur = cur_rows.get(r["name"])
        if cur is None:
            # 신규 게임은 만들지 않는다. 이 도구는 '보강 병합' 전용이다.
            missing.append(r["name"])
            continue
        sets = {}

        for col in ("community_confidence",):
            if r[col] is not None and cur[col] is None:
                sets[col] = r[col]
            elif r[col] is not None and str(cur[col]) != str(r[col]):
                blocked.append((r["name"], col, "existing value kept"))

        for col in FILL_ONLY_COLS:
            if r[col] is None:
                continue
            if cur[col] is None:
                sets[col] = r[col]
            else:
                blocked.append((r["name"], col, "existing value kept (FILL_ONLY)"))

        for col in APPEND_COLS:
            new = (r[col] or "").strip()
            if not new:
                continue
            old = cur[col]
            if not old:
                sets[col] = new
            elif new in old:
                noop.append((r["name"], col, "already present"))
            else:
                sets[col] = old + SEP + new       # 기존 문장 전문 보존 + 뒤에 잇기
                appended.append((r["name"], col, len(old), len(new)))

        merged = _merge_urls(cur["community_source_urls"], r["community_source_urls"])
        if merged is not None:
            sets["community_source_urls"] = json.dumps(merged, ensure_ascii=False)

        if sets:
            plans.append((r["name"], sets))

    # ---- fps: 다른 출처가 선점한 행은 건드리지 않는다 ----
    fps_ins, fps_upd, fps_keep = [], [], []
    for r in cand_fps:
        k = (r["name"], r["gpu_model"], r["resolution"], r["preset"])
        if k not in fps_have:
            fps_ins.append(r)
        elif fps_have[k] == r["source_url"]:
            fps_upd.append(r)
        else:
            fps_keep.append(r)

    print(f"input games: {len(items)} / mergeable: {len(plans)} "
          f"/ no-change: {len(cand_games) - len(plans) - len(missing)}")
    print(f"not found in games (NOT created): {len(missing)}")
    for n in missing:
        print(f"  missing: {n}")
    print(f"append (existing text preserved + new appended): {len(appended)}")
    for n, c, lo, ln in appended:
        print(f"  append: {n}.{c} keep {lo} chars + add {ln} chars")
    print(f"blocked (existing value kept, new value NOT written): {len(blocked)}")
    for n, c, why in blocked:
        print(f"  blocked: {n}.{c} -- {why}")
    print(f"idempotent skip (already merged): {len(noop)}")
    for n, c, why in noop:
        print(f"  skip: {n}.{c} -- {why}")

    conf = {}
    for r in cand_games:
        conf[r["community_confidence"]] = conf.get(r["community_confidence"], 0) + 1
    print(f"community_confidence: {conf}")

    print(f"game_measured_fps: insert={len(fps_ins)} update(same source)={len(fps_upd)} "
          f"keep(other source, NOT touched)={len(fps_keep)}")
    for r in fps_keep:
        print(f"  fps keep: {r['name']} / {r['gpu_model']} / {r['resolution']}")
    print(f"rows skipped: {len(skipped)}")
    for n, why in skipped:
        print(f"  skip: {n} -- {why}")

    if args.dry:
        print("\n--dry mode -- no rows written")
        return

    gw = fw = 0
    with engine.begin() as conn:
        for name, sets in plans:
            assign = ", ".join(f"{c} = :{c}" for c in sets)
            conn.execute(text(f"UPDATE games SET {assign} WHERE name = :name"),
                         dict(sets, name=name))
            gw += 1

        ids = {r[1]: r[0] for r in conn.execute(text("SELECT game_id, name FROM games"))}
        for r in fps_ins + fps_upd:
            gid = ids.get(r["name"])
            if gid is None:
                continue
            conn.execute(text("""
                INSERT INTO game_measured_fps
                  (game_id, gpu_model, resolution, preset, fps_avg, fps_1pct_low,
                   is_threshold, source_url, note)
                VALUES (:gid, :gpu_model, :resolution, :preset, :fps_avg, :fps_1pct_low,
                        :is_threshold, :source_url, :note)
                ON CONFLICT (game_id, gpu_model, resolution, preset) DO UPDATE SET
                  fps_avg = EXCLUDED.fps_avg,
                  fps_1pct_low = EXCLUDED.fps_1pct_low,
                  is_threshold = EXCLUDED.is_threshold,
                  note = EXCLUDED.note
                WHERE game_measured_fps.source_url = EXCLUDED.source_url
            """), dict(r, gid=gid))
            fw += 1

    print(f"\nwritten: games={gw} game_measured_fps={fw}")


if __name__ == "__main__":
    main()
