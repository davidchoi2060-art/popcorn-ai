# -*- coding: utf-8 -*-
"""웹 검색 사양 제안 적용 — 검수 큐에 **제안값**으로 올린다 (spec_web_suggestions).

실행:
  .venv/Scripts/python tools/spec_fill_apply.py suggestions.jsonl            # 드라이런(기본)
  .venv/Scripts/python tools/spec_fill_apply.py suggestions.jsonl --apply    # 실제 반영

입력은 JSONL(한 줄 = 제안 하나). 채움 담당(specfiller)이 웹 검색으로 찾은 값을 이 형식으로
적어 넘긴다 — 못 찾은 것은 이 파일에 넣지 않는다(별도로 "못 찾았다"고 보고한다):

  {"product_code": 123456, "field_name": "cooler_tdp", "suggested_value": "150",
   "source_url": "https://...", "source_name": "제조사 공식", "confidence": 0.8,
   "note": "제품 상세 페이지 표 3행"}

**수집한 값은 우리 사실이 아니다.** danawa_fetch.py와 같은 계약(A-18) — 이 스크립트는
`product_reviews.suggested_value`에 제안으로만 올리고, `spec_web_suggestions`에 출처를
남긴다. 운영자가 검수 화면(ADM-PRD-020)에서 확인해야 `product_specs`에 들어간다.

**`product_specs`는 이 스크립트가 절대 쓰지 않는다.** 정본 불가침.

`spec_web_suggestions` 테이블이 없으면(마이그레이션 0045 미적용) 안내만 하고 종료한다 —
DBA가 먼저 `alembic upgrade head`를 돌려야 한다.
"""
import argparse
import io
import json
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                      # noqa: E402
from sqlalchemy import create_engine, text          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED_KEYS = ("product_code", "field_name", "suggested_value", "source_url")
# JSONB 대상 필드는 제안값이 JSON 배열 문자열이어야 한다 — danawa_fetch.py와 같은 표기 규약
JSON_FIELDS = {"socket_list", "form_factor_list"}


def _load_lines(path):
    """(줄번호, 파싱된 dict 또는 None, 오류사유 또는 None) 목록. 못 읽은 줄도 빠뜨리지 않는다."""
    out = []
    with io.open(path, encoding="utf-8") as f:
        for i, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                out.append((i, None, f"JSON 파싱 실패: {e}"))
                continue
            if not isinstance(obj, dict):
                out.append((i, None, "JSON 객체가 아님"))
                continue
            missing = [k for k in REQUIRED_KEYS
                       if obj.get(k) is None or str(obj.get(k)).strip() == ""]
            if missing:
                out.append((i, None, f"필수 값 누락: {','.join(missing)}"))
                continue
            try:
                obj["product_code"] = int(obj["product_code"])
            except (TypeError, ValueError):
                out.append((i, None, f"product_code 정수 아님: {obj.get('product_code')!r}"))
                continue
            out.append((i, obj, None))
    return out


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or url[:40]
    except Exception:                                # noqa: BLE001
        return url[:40]


def _confidence(raw):
    """0~1 범위의 신뢰도만 인정한다. 없거나 숫자가 아니거나 범위 밖이면 None.

    specfiller.md 규약("confidence는 0~1")을 벗어난 값을 지어내 채우지 않는다 —
    호출부는 이 None을 UPDATE의 COALESCE로 받아 **기존 값을 덮지 않는다**
    (적재는 채우기만 하고 지우지 않는다 — 이 저장소 관례).
    """
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v < 0.0 or v > 1.0:
        return None
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl_path")
    ap.add_argument("--apply", action="store_true", help="DB에 실제로 반영(기본은 드라이런)")
    args = ap.parse_args()

    if not os.path.exists(args.jsonl_path):
        print(f"입력 파일이 없습니다: {args.jsonl_path}")
        sys.exit(1)

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as c:
        has_table = c.execute(text(
            "SELECT 1 FROM information_schema.tables"
            " WHERE table_name = 'spec_web_suggestions'")).first()
    if not has_table:
        print("spec_web_suggestions 테이블이 없습니다.")
        print("먼저 DBA가 마이그레이션을 적용해야 합니다 (db/migrations/versions/0045_*.py):")
        print("  .venv/Scripts/python -m alembic -c db/alembic.ini upgrade head")
        sys.exit(1)

    lines = _load_lines(args.jsonl_path)
    invalid = [(i, why) for i, obj, why in lines if obj is None]
    rows = [obj for _i, obj, why in lines if obj is not None]
    print(f"입력 {len(lines):,}줄 / 파싱 성공 {len(rows):,} / 입력 오류 {len(invalid):,}\n")

    with engine.connect() as c:
        valid_fields = {r[0] for r in
                         c.execute(text("SELECT field_key FROM spec_field_defs")).all()}
        pcs = sorted({r["product_code"] for r in rows})
        snap = []
        if pcs:
            snap = c.execute(text(
                "SELECT review_id, product_code, field_name, review_status, suggested_value"
                " FROM product_reviews WHERE product_code = ANY(:pcs)"),
                {"pcs": pcs}).mappings().all()

    # (product_code, field_name) -> 그 조합의 검수 행들(상태 무관)
    by_key = {}
    for r in snap:
        by_key.setdefault((r["product_code"], r["field_name"]), []).append(r)

    ok, already, no_wait, bad_field, bad_format = [], [], [], [], []
    for row in rows:
        pc, field = row["product_code"], row["field_name"]
        val = str(row["suggested_value"])
        if field not in valid_fields:
            bad_field.append(row)
            continue
        if field in JSON_FIELDS:
            try:
                parsed = json.loads(val)
                if not isinstance(parsed, list) or not parsed:
                    raise ValueError("empty or not a list")
            except Exception:                        # noqa: BLE001
                bad_format.append(row)
                continue
        cands = by_key.get((pc, field), [])
        waiting = [r for r in cands if r["review_status"] == "대기"]
        if not waiting:
            no_wait.append(row)
            continue
        target = next((r for r in waiting if r["suggested_value"] is None), None)
        if target is None:
            already.append(row)
            continue
        row["_review_id"] = target["review_id"]
        ok.append(row)

    # confidence는 REQUIRED_KEYS가 아니라 여기서는 걸러내지 않는다 - 값 자체는 적용하되
    # 신뢰도만 무시된 건수를 알린다(조용히 삼키지 않는다).
    bad_confidence = [r for r in ok if r.get("confidence") is not None
                       and _confidence(r.get("confidence")) is None]

    def _fmt(r):
        return f"  {r['product_code']} {r['field_name']} = {r['suggested_value']!r}"

    print(f"채울 수 있음      {len(ok):,}")
    print(f"이미 제안 있음    {len(already):,}")
    print(f"대기 행 없음      {len(no_wait):,}")
    print(f"필드 불명         {len(bad_field):,}")
    if bad_format:
        print(f"형식 오류(목록형) {len(bad_format):,}")
    if bad_confidence:
        print(f"confidence 무시(범위 밖·비정상) {len(bad_confidence):,}"
              " - 값은 적용되고 신뢰도만 기존 값을 유지합니다.")
    if invalid:
        print(f"입력 오류         {len(invalid):,}")
        for i, why in invalid[:5]:
            print(f"    줄 {i}: {why}")

    for label, bucket in (("이미 제안 있음", already), ("대기 행 없음", no_wait),
                          ("필드 불명", bad_field), ("형식 오류", bad_format)):
        if bucket:
            print(f"\n{label} 샘플(최대 5):")
            for r in bucket[:5]:
                print(_fmt(r))

    if not args.apply:
        print("\n드라이런 - DB를 바꾸지 않았습니다. --apply 로 실제 반영합니다.")
        if ok:
            print("적용 시 반영될 샘플(최대 5):")
            for r in ok[:5]:
                print(_fmt(r))
        return

    if not ok:
        print("\n적용할 제안이 없습니다.")
        return

    done, failed = 0, []
    for row in ok:
        pc, field = row["product_code"], row["field_name"]
        val = str(row["suggested_value"])
        source_url = row["source_url"]
        source_name = row.get("source_name")
        confidence = _confidence(row.get("confidence"))
        note = row.get("note")
        domain = _domain(source_url)
        try:
            with engine.begin() as conn:
                # danawa_fetch.py와 같은 WHERE 조건 — 처리 사이 상태가 바뀌었으면 조용히
                # 건너뛰지 않고 실패로 센다(경합 방어).
                # confidence는 COALESCE — 없거나 범위 밖(0~1 아님)이면 기존 값(적재 기본값
                # 0.8 등)을 그대로 둔다. 이걸 SET절에서 빠뜨려 검수 큐가 옛 신뢰도(0.8)만
                # 보고 실제 값(0.25~0.90)은 spec_web_suggestions에만 남던 결함의 재발 방지.
                r = conn.execute(text("""
                    UPDATE product_reviews
                       SET suggested_value = :v,
                           confidence = COALESCE(:conf, confidence),
                           detail = coalesce(detail, '') || ' [웹 제안: ' || :v || ' · 출처 '
                                    || :domain || ' — 확인 후 승인하세요]'
                     WHERE review_id = :rid AND review_status = '대기'
                       AND suggested_value IS NULL
                     RETURNING review_id
                """), {"v": val, "conf": confidence, "domain": domain,
                       "rid": row["_review_id"]}).first()
                if r is None:
                    failed.append((pc, field, "대기 행 없음(경합 - 처리 사이 상태 변경)"))
                    continue
                conn.execute(text("""
                    INSERT INTO spec_web_suggestions
                      (product_code, field_name, suggested_value, source_url, source_name,
                       confidence, note, fetched_at, applied_review_id)
                    VALUES (:pc, :f, :v, :url, :sn, :conf, :note, now(), :rid)
                """), {"pc": pc, "f": field, "v": val, "url": source_url, "sn": source_name,
                       "conf": confidence, "note": note, "rid": row["_review_id"]})
            done += 1
        except Exception as ex:                       # noqa: BLE001
            failed.append((pc, field, str(ex)[:120]))

    print(f"\n적용 {done:,}건 / 실패 {len(failed):,}건")
    for pc, field, why in failed[:10]:
        print(f"    실패 {pc} {field}: {why}")
    print("검수 화면(ADM-PRD-020)에서 제안값을 확인하고 승인하면 정본에 반영됩니다.")


if __name__ == "__main__":
    main()
