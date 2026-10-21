"""0170 — 몰에서 바뀐 부품(쿨러 49 · 케이스 7 · 메모리 수량 1)을 팝콘AI 몰 등록 구성에 따라 넣는다 (2026-10-21 대표 「바꿔」).

■ 왜
  2026-10-21 몰 공개 페이지와 팝콘AI 를 대조하니 50개 상품의 부품이 달랐다 — 몰은 CPU쿨러를
  [JIUSHARK] JF120R Emerald RGB 블랙으로 바꿨는데 팝콘AI 는 [ABKO] 자이로스 120X4 FRGB 블랙 그대로였다
  (케이스 7개 · 123380 메모리 수량도). 상품명 기준 원칙과 부딪히는 것은 없다 — 바뀐 칸은 쿨러·케이스와
  123380 메모리 수량(상품명 16GB · 몰이 「× 2개」 오기를 고쳤다)뿐이다.

■ 무엇을 바꾸나 — 데이터 db/migrations/data/mall_parts_20261021.json
  products.spec_source_text 의 해당 슬롯 값 한 칸씩만 몰 옵션 문구로 바꾼다(다른 슬롯은 손대지 않는다).
  지금 값이 대조 때 본 옛 값과 같을 때만 바꾼다 — 그 사이 몰 엑셀 적재·운영자가 고쳤으면 두고 넘어간다.
  mvp4 상세의 «몰 등록 구성» 표(api/customer_pc_registered)가 이 원문을 읽는다.

■ 바꾸지 않는 것
  공개 승인된 구성(pc_configuration_parts · 25개 상품)은 그대로다. 그 구성은 승인·게시 증빙에 묶여 있어
  부품을 바꾸면 승인이 풀린다 — 다시 승인할 때(대표 사진 재제작과 함께) 관리자 구성표 부품 수정으로 바꾼다.
"""
import json
import re
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0170"
down_revision = "0169"
branch_labels = None
depends_on = None

DATA = Path(__file__).resolve().parents[1] / "data" / "mall_parts_20261021.json"
_QTY = re.compile(r"\*\s*(\d+)\s*개")
_TAG = re.compile(r"<[^>]+>")


def _key(val: str) -> str:
    # api/customer_pc_registered.key(_QTY.sub(" ", 값)) 과 같은 비교 — 태그·공백·상표 기호·대소문자 차이만 지운다
    return re.sub(r"\s+", "", re.sub(r"[™®]", "", _QTY.sub(" ", _TAG.sub(" ", val)))).lower()


def _slot(raw: str) -> str:
    return re.sub(r"\s+", "", _TAG.sub("", raw))


def _swap(text: str, slot: str, old_key: str, new: str):
    """slot 칸 값이 old_key 이면 new 로 바꾼 원문, 아니면 None."""
    chunks = text.split(",@@")
    hit = None
    for i, chunk in enumerate(chunks):
        if "@@" not in chunk:
            continue
        head, val = chunk.split("@@", 1)
        if _slot(head) != slot:
            continue
        if hit is not None or _key(val) != old_key:
            return None
        tail = val[len(val.rstrip()):]
        chunks[i] = head + "@@" + new + tail
        hit = i
    return None if hit is None else ",@@".join(chunks)


def _apply(conn, frm: str, to: str, only_public: bool = False) -> None:
    d = json.loads(DATA.read_text(encoding="utf-8"))
    for p in d["products"]:
        if only_public and not p["public_configuration"]:
            continue
        sst = conn.execute(sa.text("SELECT spec_source_text FROM products WHERE product_code=:c"),
                           {"c": p["code"]}).scalar()
        if not sst:
            continue
        new = sst
        for ch in p["changes"]:
            old = ch[frm] + (" * %d개" % ch["old_qty"] if frm == "old" and ch["old_qty"] > 1 else "")
            want = ch[to] + (" * %d개" % ch["old_qty"] if to == "old" and ch["old_qty"] > 1 else "")
            swapped = _swap(new, ch["slot"], _key(old), want)
            if swapped is None:
                new = None
                break
            new = swapped
        if new is not None and new != sst:
            conn.execute(sa.text("UPDATE products SET spec_source_text=:t WHERE product_code=:c"
                                 " AND spec_source_text=:o"), {"t": new, "c": p["code"], "o": sst})


def upgrade() -> None:
    _apply(op.get_bind(), "old", "new")


def downgrade() -> None:
    _apply(op.get_bind(), "new", "old")
