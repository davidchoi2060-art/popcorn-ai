# -*- coding: utf-8 -*-
"""소프트웨어 카탈로그 로더 - software_catalog.json 을 software 표에 적재한다.

배경: db/migrations/versions/0096_software_catalog.py 가 만든 표를 채운다.
값은 이 스크립트가 만들지 않는다 - 조사자가 출처를 붙여 모은 JSON 을 그대로 옮긴다.
JSON 에 null 이면 DB 도 null 이다. 추정으로 메우지 않는다.

실행:
  .venv/Scripts/python tools/software_db_load.py --file D:/Hermes-Workspace/software_catalog.json --dry
  .venv/Scripts/python tools/software_db_load.py --file D:/Hermes-Workspace/software_catalog.json

입력 원소(JSON 배열):
  {"name_ko": "어도비 프리미어 프로", "name_en": "Adobe Premiere Pro",
   "category": "영상편집", "vendor": "Adobe", "official_url": "...",
   "checked_date": "2026-09-18", "min_cpu": ..., "min_ram_gb": 8, ...,
   "community_rec": {"ram_gb": 32, "vram_gb": 8, "note": "...", "source_urls": [...]},
   "confidence": "확인", "sources": [...], "spec_gap_reason": "..."}

■ 멱등성 - name 으로 UPSERT 한다. 두 번 돌려도 행이 늘지 않는다.
  값은 COALESCE(EXCLUDED.col, software.col) - 채우기만 하고 지우지 않는다
  (tools/game_db_load.py 와 같은 관례, CLAUDE.md "적재는 채우기만 하고 지우지 않는다").

■ 커뮤니티 권장치는 software_community_spec 에 (software_id, spec_key='aggregate')
  로 UPSERT 한다. 이번 조사는 프로그램당 커뮤니티 종합 1건이다.

■ 싣지 못하는 필드 - 지어내지 않는다
  software_community_spec.sample_size / source_type 은 JSON 에 독립 필드가 없다.
  표본 수는 note 안에 서술로만 들어 있고("표본: 상위 게시물 6건 + Puget 1건"),
  출처 종류도 URL 을 보고 사람이 판단해야 하는 값이다. 둘 다 null 로 둔다.

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

# (DB 컬럼, JSON 키) - 이름이 다른 것만 매핑한다
FIELD_MAP = [
    ("name_en", "name_en"),
    ("category", "category"),
    ("vendor", "vendor"),
    ("official_source_url", "official_url"),
    ("min_cpu", "min_cpu"),
    ("min_gpu", "min_gpu"),
    ("min_ram_gb", "min_ram_gb"),
    ("min_vram_gb", "min_vram_gb"),
    ("min_storage_gb", "min_storage_gb"),
    ("min_os", "min_os"),
    ("rec_cpu", "rec_cpu"),
    ("rec_gpu", "rec_gpu"),
    ("rec_ram_gb", "rec_ram_gb"),
    ("rec_vram_gb", "rec_vram_gb"),
    ("rec_storage_gb", "rec_storage_gb"),
    ("description", "description"),
    ("bottleneck", "bottleneck"),
    ("bottleneck_note", "bottleneck_note"),
    ("license_type", "license_type"),
    ("price_note", "price_note"),
    ("popularity_note", "popularity_note"),
    ("confidence", "confidence"),
    ("spec_gap_reason", "spec_gap_reason"),
    ("checked_date", "checked_date"),
]


def _load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path}: top-level must be a JSON array")
    return data


def build_rows(items):
    """JSON -> (software row, community row) 목록. 값 변환은 하지 않는다."""
    rows, comm, skipped = [], [], []
    for it in items:
        name = (it.get("name_ko") or "").strip()
        if not name:
            skipped.append(("(no name_ko)", "missing name_ko"))
            continue
        # category / confidence 는 NOT NULL 이다. 없으면 기본값을 지어내지 않고 거른다.
        if not it.get("category"):
            skipped.append((name, "missing category (NOT NULL)"))
            continue
        if not it.get("confidence"):
            skipped.append((name, "missing confidence (NOT NULL)"))
            continue
        params = {"name": name}
        for col, key in FIELD_MAP:
            params[col] = it.get(key)
        srcs = it.get("sources")
        params["source_urls"] = json.dumps(srcs, ensure_ascii=False) if srcs else None
        params["note"] = None      # 이번 JSON 에 software 용 note 필드가 없다
        rows.append(params)

        cr = it.get("community_rec") or {}
        if cr.get("ram_gb") is not None or cr.get("vram_gb") is not None or cr.get("note"):
            urls = cr.get("source_urls")
            comm.append({
                "name": name,
                "spec_key": "aggregate",
                "ram_gb": cr.get("ram_gb"),
                "vram_gb": cr.get("vram_gb"),
                "note": cr.get("note"),
                "source_type": None,     # JSON 에 없다 - 지어내지 않는다
                "sample_size": None,     # JSON 에 없다 - note 안 서술뿐이다
                "source_urls": json.dumps(urls, ensure_ascii=False) if urls else None,
            })
    return rows, comm, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", nargs="+", required=True, metavar="JSON")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    items = []
    for p in args.file:
        items.extend(_load(p))
    rows, comm, skipped = build_rows(items)

    print(f"input: {len(items)} / loadable software: {len(rows)}"
          f" / community rows: {len(comm)} / skipped: {len(skipped)}")
    for name, why in skipped:
        print(f"  skip: {name} reason={why}")

    cols = [c for c, _ in FIELD_MAP] + ["source_urls", "note"]

    with engine.connect() as conn:
        have = {r[0] for r in conn.execute(text("SELECT name FROM software"))}
    new = [r for r in rows if r["name"] not in have]
    upd = [r for r in rows if r["name"] in have]
    print(f"software: new={len(new)} update={len(upd)}")
    print(f"software_community_spec: candidates={len(comm)}")

    if args.dry:
        print("\n--dry mode -- no rows written")
        return

    sw_written = comm_written = 0
    with engine.begin() as conn:
        for p in rows:
            placeholders = ", ".join(f":{c}" for c in cols)
            excl = ", ".join(
                f"{c} = COALESCE(EXCLUDED.{c}, software.{c})" for c in cols)
            conn.execute(text(f"""
                INSERT INTO software (name, {", ".join(cols)})
                VALUES (:name, {placeholders})
                ON CONFLICT (name) DO UPDATE SET {excl}
            """), p)
            sw_written += 1

        for cspec in comm:
            sid = conn.execute(text("SELECT software_id FROM software WHERE name=:n"),
                               {"n": cspec["name"]}).scalar()
            if sid is None:
                print(f"  skip community: software not found: {cspec['name']}")
                continue
            p = dict(cspec, software_id=sid)
            conn.execute(text("""
                INSERT INTO software_community_spec
                  (software_id, spec_key, ram_gb, vram_gb, note, source_type,
                   sample_size, source_urls)
                VALUES (:software_id, :spec_key, :ram_gb, :vram_gb, :note,
                        :source_type, :sample_size, :source_urls)
                ON CONFLICT (software_id, spec_key) DO UPDATE SET
                  ram_gb      = COALESCE(EXCLUDED.ram_gb, software_community_spec.ram_gb),
                  vram_gb     = COALESCE(EXCLUDED.vram_gb, software_community_spec.vram_gb),
                  note        = COALESCE(EXCLUDED.note, software_community_spec.note),
                  source_type = COALESCE(EXCLUDED.source_type, software_community_spec.source_type),
                  sample_size = COALESCE(EXCLUDED.sample_size, software_community_spec.sample_size),
                  source_urls = COALESCE(EXCLUDED.source_urls, software_community_spec.source_urls)
            """), p)
            comm_written += 1

    print(f"\nwritten: software={sw_written} software_community_spec={comm_written}")


if __name__ == "__main__":
    main()
