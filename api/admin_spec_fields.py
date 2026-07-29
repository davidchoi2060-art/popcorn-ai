"""ADM-PRD-050 상품 스펙 관리 — 사양 항목을 화면에서 늘린다 (슬라이스 56).

**왜 화면에서 컬럼을 만드나.** 현장 운영자가 쓰면서 필요한 사양을 계속 발견한다. 그때마다
개발 배포를 기다리면 데이터가 머릿속과 엑셀에 남는다(2026-07-28 사용자 결정).

**대신 위험을 구조로 막는다.** 컬럼 하나를 늘리면 따라가야 하는 곳이 일곱이었다.
넷은 `spec_fields` 메타로 자동이 됐고(적재·대안·검수 승인·필수 판정), 이 API가 나머지
셋을 한 트랜잭션에서 직접 처리한다:

  ① `product_specs` 컬럼 추가 (ALTER TABLE)
  ② 추천 뷰 두 개 재생성 — 컬럼을 명시 나열하므로 자동으로 안 들어온다
  ③ **마이그레이션 파일 기록** — 화면에서 만든 컬럼이 Alembic 이력에 없으면
     서버를 새로 구축하거나 백업에서 복구할 때 **그 컬럼이 사라진다**

owner 전용이다. 삭제는 열지 않는다 — 컬럼을 지우면 그 안의 데이터가 함께 사라지고,
되돌릴 수 없다. 쓰지 않을 항목은 `part_types`를 비워 화면에서 감춘다.
"""
import io
import os
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from . import spec_fields as SF
from .auth import current_operator_id
from .db import engine

router = APIRouter(prefix="/api/admin")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIG_DIR = os.path.join(ROOT, "db", "migrations", "versions")

# 컬럼명 규칙 — SQL 식별자로 안전하고, 우리 코드가 점 표기 없이 쓰는 형태.
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,38}$")
TYPES = {"INTEGER": "INTEGER", "NUMERIC": "NUMERIC(10,2)", "VARCHAR": "VARCHAR(80)",
         "BOOLEAN": "BOOLEAN", "JSONB": "JSONB"}
# 자료형 설명 — 운영자가 고를 때 무엇을 담는 그릇인지 알아야 한다(슬라이스 85).
# **값은 그대로 두고 표시만 늘린다** — 저장되는 것은 키(INTEGER 등)다.
TYPE_HELP = {
    "INTEGER": "정수 — 개수·와트·mm처럼 소수점이 없는 수",
    "NUMERIC": "소수 — 인치·전압처럼 소수점이 필요한 수",
    "VARCHAR": "짧은 글자 — 소켓·규격·인터페이스 같은 이름값",
    "BOOLEAN": "예/아니오 — 있다·없다로 답하는 값",
    "JSONB": "목록 — 지원 소켓처럼 값이 여러 개인 것",
}
# 이미 쓰이는 이름·예약어는 막는다(다른 뜻으로 읽히면 판정이 틀어진다)
RESERVED = {"product_code", "part_type", "created_at", "updated_at", "verified_yn",
            "extract_source", "confidence", "spec_sources", "select", "from", "where",
            "order", "group", "table", "column", "user", "default", "check"}
ALL_PART_TYPES = ("CPU", "MB", "RAM", "GPU", "SSD", "HDD", "POWER", "CASE",
                  "COOLER_CPU_AIR", "COOLER_CPU_AIO",
                  "MONITOR", "KEYBOARD", "MOUSE", "HEADSET", "SPEAKER", "WEBCAM")
# 화면의 부품 축. 견적 대상(부품)과 주변기기를 나눈다 — 주변기기는 8슬롯에 안 들어간다.
PART_LABEL = {"CPU": "CPU", "MB": "메인보드", "RAM": "메모리", "GPU": "그래픽카드",
              "CASE": "케이스", "POWER": "파워", "SSD": "SSD", "HDD": "HDD",
              "COOLER_CPU_AIR": "CPU쿨러(공랭)", "COOLER_CPU_AIO": "CPU쿨러(수랭)",
              "MONITOR": "모니터", "KEYBOARD": "키보드", "MOUSE": "마우스",
              "HEADSET": "헤드셋", "SPEAKER": "스피커", "WEBCAM": "웹캠"}
CORE_PARTS = ("CPU", "MB", "RAM", "GPU", "CASE", "COOLER_CPU_AIR", "COOLER_CPU_AIO",
              "POWER", "SSD", "HDD")


def _add_col_to_view(conn, view: str, key: str) -> bool:
    """추천 뷰의 SELECT 목록 **끝에** 새 컬럼을 붙인다.

    `CREATE OR REPLACE VIEW`는 컬럼을 **끝에 추가만** 허용한다 — 순서를 바꾸거나 빼면
    "cannot drop columns from view"로 거부한다(실제로 뷰를 통째로 다시 쓰다 겪었다).
    그래서 기존 정의를 그대로 두고 마지막 컬럼 뒤에 한 줄만 끼운다.

    이 재생성이 없으면 화면에는 값이 있는데 **엔진은 그 값을 못 본다** — 가장 찾기 어려운
    종류의 버그다(슬라이스 46 전례).
    """
    ddl = conn.execute(text("SELECT pg_get_viewdef(:v, true)"), {"v": view}).scalar()
    if not ddl:
        return False
    m = re.search(r"\n\s*FROM\s", ddl)
    if not m:
        return False
    head, tail = ddl[:m.start()], ddl[m.start():]
    conn.execute(text("CREATE OR REPLACE VIEW " + view + " AS "
                      + head + ",\n    ps." + key + tail))
    return True


def _next_revision() -> tuple[str, str]:
    """다음 Alembic 리비전 번호와 직전 head."""
    nums = []
    for fn in os.listdir(MIG_DIR):
        m = re.match(r"^(\d{4})_", fn)
        if m:
            nums.append(int(m.group(1)))
    cur = max(nums) if nums else 0
    return f"{cur + 1:04d}", f"{cur:04d}"


@router.get("/spec-fields")
def list_spec_fields():
    """사양 항목 목록 + 화면이 폼을 그릴 때 필요한 선택지."""
    fields = SF.all_fields()
    with engine.connect() as conn:
        # 메타에 있어도 실제 컬럼이 없을 수 있다 — 캐시가 앞서거나, DB에서 직접 지운 경우다.
        # 없는 컬럼을 세려다 500이 나면 화면 전체가 죽는다(실제로 겪었다).
        real = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name='product_specs'")).all()}
        live = [f for f in fields if f["field_key"] in real]
        used = dict(conn.execute(text(
            "SELECT field_key, n FROM ("
            + " UNION ALL ".join(
                f"SELECT '{f['field_key']}' AS field_key,"
                f" count({f['field_key']}) AS n FROM product_specs"
                for f in live) + ") x")).all()) if live else {}

        # 부품별 충족률 — 이 화면의 핵심 수치다(슬라이스 83).
        # 지금까지 '채워진 값'은 **분모가 전 상품 22,841**이라 아무것도 알려주지 못했다.
        # socket 3,476은 CPU가 준비됐는지 말해주지 않는다(socket은 CPU·MB에만 해당).
        # 부품을 축으로 세우면 "CPU 301개 중 284개(94%)"가 되고, 그게 검수 우선순위다.
        cols = ", ".join(f"count(s.{f['field_key']}) AS f_{f['field_key']}" for f in live)
        fill_rows = conn.execute(text(
            "SELECT p.part_type, count(*) AS n"
            + (", " + cols if cols else "")
            + " FROM products p JOIN product_specs s USING (product_code)"
            " WHERE p.status = '판매중' AND p.stock_qty > 0"
            " GROUP BY p.part_type")).mappings().all()
        fill = {r["part_type"]: r for r in fill_rows}
        # 판매중·재고와 무관한 전체 보유량도 함께 준다(축 칩이 '팔 수 있는 것'을 말하되,
        # 카탈로그에 몇 개가 있는지도 알아야 "왜 이렇게 적지?"에 답할 수 있다)
        total_by = dict(conn.execute(text(
            "SELECT part_type, count(*) FROM products"
            " WHERE category_group IN ('core_part','peripheral')"
            " GROUP BY part_type")).all())
        # 이 값을 읽는 규칙 — '필수가 아니면 영향 없음'은 거짓이다.
        # radiator_rows는 필수가 아니지만 비면 그 수랭은 어떤 케이스와도 못 묶인다.
        readers = SF.rule_readers(conn)
    # 화면에서 만든 항목 중 **코드 이력이 없는 것**. 서버에서는 마이그레이션 파일을 쓸 수
    # 없어 이 상태가 생긴다(cpu_gpu 전례). 그대로 두면 재구축·복구 때 컬럼이 사라지는데
    # 아무 데도 표시가 없어 알 길이 없었다 — 여기서 드러낸다.
    try:
        mig_files = os.listdir(MIG_DIR)
    except OSError:
        mig_files = []
    unrecorded = [f["field_key"] for f in fields
                  if f.get("is_custom")
                  and not any(fn.endswith(f"_spec_field_{f['field_key']}.py")
                              for fn in mig_files)]

    ghosts = [f["field_key"] for f in fields if f["field_key"] not in real]
    if ghosts:
        SF.reload()                      # 캐시가 낡았을 수 있다 — 다음 조회는 새로 읽는다
        fields = [f for f in SF.all_fields() if f["field_key"] in real]
    return {
        "items": [{
            "field_key": f["field_key"], "label": f["label"], "data_type": f["data_type"],
            "unit": f["unit"], "part_types": f["part_types"], "required_for": f["required_for"],
            "is_engine": f["is_engine"], "is_custom": f["is_custom"],
            "in_ingest": f.get("in_ingest", False), "sort_order": f["sort_order"],
            "note": f["note"], "filled": used.get(f["field_key"], 0),
        } for f in fields],
        "data_types": sorted(TYPES),
        # 화면 셀렉트에 괄호로 붙일 설명. 값(key)은 건드리지 않는다.
        "data_type_help": {k: TYPE_HELP.get(k, "") for k in sorted(TYPES)},
        "part_types": list(ALL_PART_TYPES),
        # 부품 축 — 화면이 이걸로 칩을 그리고, 고른 부품의 사양만 보여준다.
        # 한 사양이 여러 부품에 걸리므로(form_factor는 4곳, tag_rgb는 10곳)
        # '부품별 정렬'은 성립하지 않는다. 축을 바꿔야 중복 없이 보인다.
        "parts": [{
            "part_type": pt,
            "label": PART_LABEL.get(pt, pt),
            "group": "core" if pt in CORE_PARTS else "peripheral",
            "in_quote": pt in CORE_PARTS,
            "live": (fill.get(pt) or {}).get("n", 0),      # 판매중 · 재고 > 0
            "total": total_by.get(pt, 0),
            "fields": [{
                "field_key": f["field_key"], "label": f["label"],
                "required": pt in (f["required_for"] or []),
                "is_engine": f["is_engine"],
                "used_by": readers.get((pt, f["field_key"]), []),
                "filled": (fill.get(pt) or {}).get("f_" + f["field_key"], 0),
            } for f in fields if pt in (f["part_types"] or [])],
        } for pt in ALL_PART_TYPES],
        # 메타에는 있는데 컬럼이 없는 항목 — 있으면 화면이 그 사실을 말해야 한다
        "ghosts": ghosts,
        # 컬럼은 있는데 코드 이력이 없는 항목 — 복구하면 사라진다
        "unrecorded": unrecorded,
        "note": ("사양 항목을 추가하면 product_specs에 컬럼이 생기고 추천 뷰가 재생성되며"
                 " 마이그레이션 파일이 기록됩니다(복구·재구축 시 이 컬럼이 살아남습니다)."
                 " 삭제는 열지 않습니다 — 컬럼을 지우면 그 안의 데이터가 함께 사라집니다."
                 + (f" ⚠ 코드 이력이 없는 항목 {len(unrecorded)}건"
                    f"({', '.join(unrecorded)}) — 지금 복구하면 사라집니다."
                    if unrecorded else "")),
    }


class FieldBody(BaseModel):
    field_key: str
    label: str
    data_type: str
    unit: str | None = None
    part_types: list[str] = []
    required_for: list[str] = []
    is_engine: bool = False
    in_ingest: bool = False
    note: str | None = None


@router.post("/spec-fields")
def add_spec_field(body: FieldBody):
    from .admin_orders import _log

    key = (body.field_key or "").strip().lower()
    if not KEY_RE.match(key):
        raise HTTPException(400, "항목 키는 영문 소문자로 시작하고 소문자·숫자·밑줄만"
                                 " 쓸 수 있습니다(2~39자)")
    if key in RESERVED:
        raise HTTPException(400, f"'{key}'는 예약된 이름입니다")
    if body.data_type not in TYPES:
        raise HTTPException(400, f"알 수 없는 자료형: {body.data_type}")
    if not (body.label or "").strip():
        raise HTTPException(400, "표시 이름을 입력하세요")
    bad = [p for p in (body.part_types or []) if p not in ALL_PART_TYPES]
    if bad:
        raise HTTPException(400, "알 수 없는 부품 종류: " + ", ".join(bad))
    # 필수는 적용 종류 안에서만 정할 수 있다 — 쓰지도 않는 종류에 필수를 걸면
    # 그 종류 상품이 전부 영원히 검수 대기가 된다
    outside = [p for p in (body.required_for or []) if p not in (body.part_types or [])]
    if outside:
        raise HTTPException(400, "필수로 지정한 종류가 적용 대상에 없습니다: " + ", ".join(outside))

    with engine.begin() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.columns"
            " WHERE table_name='product_specs' AND column_name=:k"), {"k": key}).first()
        if exists:
            raise HTTPException(409, f"'{key}' 컬럼이 이미 있습니다")
        # ① 실제 컬럼
        conn.execute(text(f"ALTER TABLE product_specs ADD COLUMN {key} {TYPES[body.data_type]}"))
        # ② 메타 행
        conn.execute(text("""
            INSERT INTO spec_field_defs
              (field_key, label, data_type, unit, part_types, required_for,
               is_engine, is_custom, in_ingest, sort_order, note, created_by)
            VALUES (:k, :l, :t, :u, CAST(:pt AS JSONB), CAST(:rf AS JSONB),
                    :eng, true, :ing,
                    (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM spec_field_defs),
                    :note, :op)"""),
            {"k": key, "l": body.label.strip()[:60], "t": body.data_type,
             "u": (body.unit or "").strip()[:20] or None,
             "pt": _json(body.part_types), "rf": _json(body.required_for),
             "eng": body.is_engine, "ing": body.in_ingest,
             "note": (body.note or "").strip() or None, "op": current_operator_id()})
        # ③ 엔진이 읽는 값이면 추천 뷰를 다시 만든다 — 안 하면 값은 있는데 엔진이 못 본다
        SF.reload()
        if body.is_engine:
            _add_col_to_view(conn, "v_recommendation_candidates", key)
        log_id = _log(conn, "spec_field_add", key,
                      {"field_key": key, "label": body.label, "data_type": body.data_type,
                       "part_types": body.part_types, "required_for": body.required_for,
                       "is_engine": body.is_engine, "in_ingest": body.in_ingest},
                      kind="product")

    # ④ 마이그레이션 파일 — 화면에서 만든 컬럼이 이력에 없으면 재구축·복구 때 사라진다.
    #
    # **쓰지 못할 수 있다.** 배포 서버에서 앱은 리포 폴더에 쓸 권한이 없다(있어도 쓰면 안 된다 —
    # 배포 타깃에 파일을 만들면 working tree가 어긋나 다음 git pull이 깨진다).
    # 실제로 그렇게 실패했다: 운영자가 '내장그래픽(cpu_gpu)'을 만들었을 때 ①~③은 커밋됐는데
    # 여기서 예외가 나 500이 반환됐다. 운영자 화면엔 '실패'라고 떴지만 **컬럼은 이미 생겼다.**
    # 되돌릴 수도 없고, 이력도 안 남고, 아무도 그 사실을 몰랐다(2026-07-28 → 07-29 발견).
    #
    # 그래서 여기서는 실패해도 요청을 실패로 만들지 않는다. 이미 일어난 변경을 부정하는 대신
    # **이력이 없다는 사실을 정확히 말한다.** 목록 화면이 그 항목에 계속 표시를 단다.
    rev, prev = _next_revision()
    path = os.path.join(MIG_DIR, f"{rev}_spec_field_{key}.py")
    recorded, why = True, None
    try:
        io.open(path, "w", encoding="utf-8", newline="").write(
            _migration_src(rev, prev, key, body))
    except OSError as e:
        recorded, why = False, f"{type(e).__name__}: {e}"
        print(f"[spec-fields] 마이그레이션 파일을 쓰지 못했습니다({key}): {why}")

    # ⑤ 버전 스탬프 — DB는 이미 그 상태인데 alembic_version만 뒤처져 있으면
    #    "적용 안 된 마이그레이션이 있다"고 보인다. 생성한 파일은 멱등하게 썼으므로
    #    나중에 upgrade가 다시 돌아도 안전하지만, 상태는 사실과 맞춰 둔다.
    #    **파일을 못 썼으면 스탬프도 찍지 않는다** — 없는 리비전을 가리키면 다음 배포에서
    #    alembic이 "그런 리비전 없음"으로 멈춘다.
    if recorded:
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": rev})
    SF.reload()
    return {"ok": True, "field_key": key, "revision": rev if recorded else None,
            "migration": os.path.basename(path) if recorded else None,
            "undo_id": log_id, "view_rebuilt": body.is_engine,
            "recorded": recorded,
            "note": (f"'{body.label}' 항목을 만들었습니다."
                     + (f" 마이그레이션 {rev}로 기록했으니 서버를 다시 세워도 남습니다."
                        if recorded else
                        " 다만 **코드 이력에 남기지 못했습니다**(이 서버에는 쓸 수 없습니다)."
                        " 지금 상태로는 서버를 다시 세우거나 백업에서 복구하면 이 항목이"
                        " 사라집니다 — 개발 PC에서 마이그레이션을 추가해야 합니다.")
                     + (" 추천 뷰를 재생성했습니다 — 엔진이 이 값을 읽습니다."
                        if body.is_engine else
                        " 표시용이라 추천 판정에는 쓰이지 않습니다."))}


def _json(v) -> str:
    import json as _j
    return _j.dumps(list(v or []), ensure_ascii=False)


def _migration_src(rev: str, prev: str, key: str, b: FieldBody) -> str:
    """화면에서 만든 항목을 코드 이력에 남긴다 — 손으로 쓴 마이그레이션과 같은 모양."""
    col = TYPES[b.data_type]
    return f'''"""사양 항목 추가 — {key} ({b.label}).

관리자 화면(ADM-PRD-050)에서 만든 항목이다. 화면이 DDL을 실행했지만, 이력이 없으면
서버를 새로 세우거나 백업에서 복구할 때 이 컬럼이 사라진다. 그래서 같은 변경을
마이그레이션으로도 남긴다.

  · 적용 부품: {", ".join(b.part_types) or "(지정 없음)"}
  · 필수 사양: {", ".join(b.required_for) or "(없음)"}
  · 엔진 사용: {"예 — 추천 뷰에 포함" if b.is_engine else "아니오 — 표시용"}

Revision ID: {rev}
Revises: {prev}
"""
from alembic import op

revision = "{rev}"
down_revision = "{prev}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE product_specs ADD COLUMN IF NOT EXISTS {key} {col}")
    op.execute("""
        INSERT INTO spec_field_defs
          (field_key, label, data_type, unit, part_types, required_for,
           is_engine, is_custom, in_ingest, sort_order, note)
        VALUES ('{key}', '{b.label}', '{b.data_type}',
                {"NULL" if not b.unit else "'" + b.unit + "'"},
                '{_json(b.part_types)}'::jsonb, '{_json(b.required_for)}'::jsonb,
                {str(b.is_engine).lower()}, true, {str(b.in_ingest).lower()},
                (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM spec_field_defs),
                '화면에서 추가')
        ON CONFLICT (field_key) DO NOTHING
    """)


def downgrade() -> None:
    # 컬럼을 지우면 값이 함께 사라진다 — 메타만 지우고 컬럼은 남긴다.
    op.execute("DELETE FROM spec_field_defs WHERE field_key = '{key}'")
'''
