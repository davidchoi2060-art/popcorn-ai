"""0133: 신규 설치 추천 뷰의 VRAM·CPU 코어 노출 복구.

공개 1ecf4df의 단일 head 0132 후행. 원본 DDL의 뒤쪽에만 추가한다.
예상 외 중첩 SELECT/필드 타입은 거절하며 데이터·메타·의존뷰를 지우지 않는다.
"""
import re
from alembic import op
from sqlalchemy import text

revision = "0133"
down_revision = "0132"
branch_labels = None
depends_on = None

FIELDS = ("vram_gb", "cpu_cores")
ATTRIBUTE_SQL = """
SELECT attname, atttypid = 'integer'::regtype AND atttypmod = -1 AS is_integer
FROM pg_attribute
WHERE attrelid = :oid AND attname = ANY(:fields)
  AND attnum > 0 AND NOT attisdropped
"""


def _append_columns(ddl, missing):
    # pg_get_viewdef의 단순 명시 SELECT 형상만 지원한다. 모르는 정의는 거절한다.
    # 문자열에 SELECT가 있어도 보수적으로 거절하며 SQL parser라고 주장하지 않는다.
    if not isinstance(ddl, str) or len(re.findall(r"\bSELECT\b", ddl, re.I)) != 1:
        raise RuntimeError("0133: unexpected or nested recommendation SELECT")
    match = re.search(r"\n\s*FROM\s", ddl, re.I)
    if not match or not re.search(r"\bproduct_specs\s+ps\b", ddl, re.I):
        raise RuntimeError("0133: unexpected recommendation FROM/ps alias")
    if any(field not in FIELDS for field in missing):
        raise RuntimeError("0133: unexpected appended field")
    additions = ''.join(', ps.' + field for field in missing)
    return ddl[:match.start()] + additions + ddl[match.start():]


def upgrade() -> None:
    conn = op.get_bind()
    view_oid = conn.execute(text(
        "SELECT to_regclass('v_recommendation_candidates')::oid")).scalar()
    specs_oid = conn.execute(text("SELECT to_regclass('product_specs')::oid")).scalar()
    if view_oid is None or specs_oid is None:
        raise RuntimeError("0133: recommendation view or specs table is missing")
    source = dict(conn.execute(text(ATTRIBUTE_SQL),
                              {"oid": specs_oid, "fields": list(FIELDS)}).all())
    current = dict(conn.execute(text(ATTRIBUTE_SQL),
                               {"oid": view_oid, "fields": list(FIELDS)}).all())
    if any(source.get(field) is not True for field in FIELDS):
        raise RuntimeError("0133: specs field missing or not integer")
    if any(current[field] is not True for field in FIELDS if field in current):
        raise RuntimeError("0133: existing view field is not integer")
    missing = [field for field in FIELDS if field not in current]
    if not missing:
        return
    ddl = conn.execute(text("SELECT pg_get_viewdef(:oid, true)"),
                       {"oid": view_oid}).scalar()
    updated = _append_columns(ddl, missing)
    # regclass::text를 DB가 인용한 이름으로 받아 SQL 식별자 형식을 보존한다.
    view_name = conn.execute(text("SELECT CAST(:oid AS oid)::regclass::text"),
                            {"oid": view_oid}).scalar()
    if not isinstance(view_name, str) or not view_name:
        raise RuntimeError("0133: recommendation view identity missing")
    conn.execute(text("CREATE OR REPLACE VIEW " + view_name + " AS " + updated))


def downgrade() -> None:
    # 컬럼을 빼는 DROP VIEW는 의존객체를 깨뜨릴 수 있어 실행하지 않는다.
    # 복구 컬럼·사양값·메타가 남으며 완전한 과거 정의 복원은 아니다.
    pass
