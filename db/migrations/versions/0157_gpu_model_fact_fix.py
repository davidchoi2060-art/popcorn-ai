"""부품 설명의 「GPU 모델」 칸 바로잡기 (2026-10-15 코덱스 오픈테스트 C04-F03).

판매처 원문은 「Geforce RTX 50 / RTX 5070 Ti / …」처럼 시리즈를 먼저 적는다. 초안 생성기
(`tools/build_part_explanations.py`)가 앞의 시리즈 토큰을 집어 GPU 26종의 모델이
「RTX 50」·「RX 9000」으로 들어갔다. 생성기는 같은 커밋에서 고쳤고, 이 마이그레이션은
이미 DB에 있는 설명을 원문(`source_snapshot.spec`)의 단독 모델 칸으로 바로잡는다.

**공개 PC를 내리지 않는다.** 공개·검토 중 PC는 부품 설명의 해시를 고정해 두므로, 내용이
바뀌면 그 PC는 공개 조건을 잃는다. 그래서 아래 행만 고친다.
  · 상태가 `draft` (승인·보관된 설명은 건드리지 않는다 — 운영자 편집 후 재승인 경로를 탄다)
  · 어떤 PC 구성(`pc_configuration_parts`)에도 쓰이지 않는다
  · 지금 값이 원문에서 다시 뽑은 모델과 다르고, 그 모델이 시리즈 값으로 시작한다
건너뛴 행은 `alembic` 로그에 코드와 사유를 남긴다.
"""
import json
import re

from alembic import op
import sqlalchemy as sa

revision = "0157"
down_revision = "0156"
branch_labels = None
depends_on = None

LABEL = "GPU 모델"
MODEL = re.compile(r"(?:^|/)\s*((?:RTX|GTX|RX)\s*\d{4}(?:\s*(?:Ti|SUPER|XTX|XT|GRE)\b)?)\s*(?=/|$)", re.I)
SERIES = re.compile(r"(?:RTX|GTX|RX)\s*\d(?:0|000)", re.I)
NOTE = "C04-F03 시리즈 토큰을 원문 단독 모델 칸으로 교정"


def corrected(content, spec):
    """고친 내용과 (이전 값, 새 값)을 돌려준다. 고칠 것이 없으면 None."""
    fact = next((f for f in content.get("facts") or [] if f.get("label") == LABEL), None)
    match = MODEL.search(spec or "")
    if not fact or not match:
        return None
    old, new = fact.get("value") or "", re.sub(r"\s+", " ", match[1]).strip()
    if old == new or not SERIES.fullmatch(old) or not new.upper().startswith(old.upper().split()[0]):
        return None
    out = json.loads(json.dumps(content))
    for f in out["facts"]:
        if f.get("label") == LABEL and f.get("value") == old:
            f["value"] = new
    if isinstance(out.get("summary"), str):
        out["summary"] = out["summary"].replace(f"{LABEL} {old}", f"{LABEL} {new}")
    out["highlights"] = [h.replace(f"{LABEL}: {old}", f"{LABEL}: {new}") if isinstance(h, str) else h
                         for h in out.get("highlights") or []]
    out.setdefault("_admin_part_history", []).append(dict(
        at="2026-10-15T00:00:00+09:00", operator_id=None, evidence_note=NOTE,
        before={"facts": {LABEL: old}}, after={"facts": {LABEL: new}}))
    return out, old, new


def upgrade():
    conn = op.get_bind()
    rows = conn.execute(sa.text("""SELECT e.source_product_code AS code, e.status, e.content,
          e.source_snapshot->>'spec' AS spec,
          EXISTS (SELECT 1 FROM pc_configuration_parts pp WHERE pp.explanation_code = e.source_product_code) AS used
        FROM product_explanations e WHERE e.content->>'slot' = 'GPU'
        ORDER BY e.source_product_code""")).mappings().all()
    for r in rows:
        content = r["content"] if isinstance(r["content"], dict) else json.loads(r["content"])
        fix = corrected(content, r["spec"])
        if not fix:
            continue
        out, old, new = fix
        if r["status"] != "draft" or r["used"]:
            print(f"[0157] skip {r['code']} {old} -> {new}: status={r['status']} used={r['used']}")
            continue
        conn.execute(sa.text("""UPDATE product_explanations SET content = CAST(:v AS JSONB), updated_at = now()
            WHERE source_product_code = :code AND status = 'draft'"""),
            dict(code=r["code"], v=json.dumps(out, ensure_ascii=False)))
        print(f"[0157] fixed {r['code']} {old} -> {new}")


def downgrade():
    # 잘못된 시리즈 값으로 되돌리지 않는다. 변경 이력은 content._admin_part_history 에 남아 있다.
    pass
