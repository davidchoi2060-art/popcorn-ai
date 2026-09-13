# -*- coding: utf-8 -*-
"""tools/tag_ai_workstation.py — 완제품 AI 워크스테이션 표시(builtpc_kind='ai_workstation') 초안 도구

  python tools/tag_ai_workstation.py            # --dry (기본): 표만 출력, DB 안 건드림
  python tools/tag_ai_workstation.py --apply    # builtpc_kind/builtpc_spec 이 NULL 인 행에만 쓴다

■ 후보 = products WHERE part_type='PC_COMPLETE' AND status='판매중'
         AND (product_name 에 '[AI' 또는 '딥러닝')
  판정 근거를 상품명에 두는 것은 **이 초안 도구 한 번**뿐이다 — 결과는 명시 컬럼(0088)에 남고,
  고객 화면·API 는 컬럼만 본다(CLAUDE.md — 이름 파싱 판정은 표기가 바뀌는 날 빠져나간다).

■ 파싱: 상품명 끝의 [CPU/RAM/SSD/GPU] 네 칸을 '/' 로 나눈다(HTML 태그 제거 후, 마지막 '[' 부터).
  gpu_count: GPU 칸의 '*2' · 'x 2' · '* 3EA' 패턴. 없으면 1(GPU 명이 잡혔을 때만).
  ram_gb: '64G' · '128GB' → 정수. 실패 필드는 None 으로 비운다 — **지어내지 않는다**.
  '***' 로 끝나는 이름은 뜻을 모른다 → 그대로 두고 표에 표시만 한다(judgment 는 사람 몫).

■ --apply 는 builtpc_kind IS NULL AND builtpc_spec IS NULL 인 행만 UPDATE 한다 — 사람이 이미
  손본 값을 초안이 덮지 않는다. 되돌리기: UPDATE products SET builtpc_kind=NULL, builtpc_spec=NULL
  WHERE builtpc_kind='ai_workstation'.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

KIND = "ai_workstation"

SELECT_SQL = """
    SELECT product_code, sale_price, product_name, builtpc_kind, builtpc_spec
      FROM products
     WHERE part_type = 'PC_COMPLETE' AND status = '판매중'
       AND (product_name LIKE '%[AI%' OR product_name LIKE '%딥러닝%')
     ORDER BY sale_price
"""
UPDATE_SQL = """
    UPDATE products
       SET builtpc_kind = :kind, builtpc_spec = CAST(:spec AS JSONB), updated_at = now()
     WHERE product_code = :pc AND builtpc_kind IS NULL AND builtpc_spec IS NULL
"""

_TAG = re.compile(r"<[^>]+>")
_COUNT = re.compile(r"(?:\*\s*|\s+x\s*)(\d+)\s*(?:EA|WAY)?\s*$", re.I)  # '*2' · 'x 2' · '* 3EA' — 'RTX5090' 의 X 는 아님
_RAM = re.compile(r"^(\d+)\s*G(?:B)?$", re.I)


def parse_spec(name: str) -> tuple[dict, list[str]]:
    """상품명 → ({cpu, ram_gb, ssd, gpu, gpu_count}, 실패 필드 목록). 실패 필드는 None."""
    spec = {"cpu": None, "ram_gb": None, "ssd": None, "gpu": None, "gpu_count": None}
    fails: list[str] = []
    plain = _TAG.sub(" ", name)
    plain = re.sub(r"\*{3,}\s*$", "", plain.strip())  # 끝의 '***' 는 사양이 아니다
    # 마지막 '[' 부터 — 앞쪽 [용도]·[H100 NVL * 1WAY] 는 사양 칸이 아니다
    i = plain.rfind("[")
    if i < 0:
        return spec, ["cpu", "ram_gb", "ssd", "gpu", "gpu_count"]
    body = plain[i + 1:]
    body = body.split("]")[0] if "]" in body else body  # 닫는 ']' 가 없는 행도 있다(H100)
    parts = [p.strip() for p in body.split("/")]
    if len(parts) != 4:
        return spec, ["cpu", "ram_gb", "ssd", "gpu", "gpu_count"]
    cpu, ram, ssd, gpu = parts
    spec["cpu"] = cpu or None
    if not cpu:
        fails.append("cpu")
    m = _RAM.match(ram)
    if m:
        spec["ram_gb"] = int(m.group(1))
    else:
        fails.append("ram_gb")
    spec["ssd"] = ssd or None
    if not ssd:
        fails.append("ssd")
    m = _COUNT.search(gpu)
    if m:
        spec["gpu_count"] = int(m.group(1))
        gpu = gpu[:m.start()].strip()
    gpu = gpu.replace("_", " ").strip()
    if gpu:
        spec["gpu"] = gpu
        if spec["gpu_count"] is None:
            spec["gpu_count"] = 1
    else:
        fails += ["gpu", "gpu_count"]
    return spec, fails


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry", action="store_true", help="표만 출력(기본)")
    g.add_argument("--apply", action="store_true", help="NULL 인 행에만 쓴다")
    a = ap.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL 없음(.env)", file=sys.stderr)
        return 2
    eng = create_engine(url)
    with eng.connect() as c:
        rows = c.execute(text(SELECT_SQL)).fetchall()

    plans = []
    print(f"{'코드':>7} {'판매가':>12} {'CPU':<10} {'RAM':>5} {'SSD':<10} {'GPU':<20} {'GPU수':>4} 실패/비고")
    for pc, price, name, kind, existing in rows:
        spec, fails = parse_spec(name)
        note = []
        if fails:
            note.append("파싱실패:" + ",".join(fails))
        if re.search(r"\*{3,}\s*(<p>)?\s*$", name):
            note.append("이름끝 *** (뜻 미확인)")
        if kind is not None or existing is not None:
            note.append(f"이미 값 있음(kind={kind}) → 건너뜀")
        plans.append((pc, spec, kind is None and existing is None))
        print(f"{pc:>7} {price or 0:>12,} {str(spec['cpu'] or '-'):<10} {str(spec['ram_gb'] or '-'):>5} "
              f"{str(spec['ssd'] or '-'):<10} {str(spec['gpu'] or '-'):<20} {str(spec['gpu_count'] or '-'):>4} "
              + " · ".join(note))
    n_fail = sum(1 for _, s, _ in plans if any(v is None for v in s.values()))
    print(f"\n후보 {len(rows)}건 · 파싱 일부 실패 {n_fail}건 · 쓸 수 있는 행(NULL) {sum(1 for p in plans if p[2])}건")

    if not a.apply:
        print("(--dry) DB 변경 없음. 쓰려면 --apply")
        return 0
    written = 0
    with eng.begin() as c:
        for pc, spec, writable in plans:
            if not writable:
                continue
            r = c.execute(text(UPDATE_SQL), {"kind": KIND, "spec": json.dumps(spec, ensure_ascii=False), "pc": pc})
            written += r.rowcount
    print(f"(--apply) builtpc_kind='{KIND}' 기록 {written}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
