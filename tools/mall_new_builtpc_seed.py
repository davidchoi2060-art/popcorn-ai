# -*- coding: utf-8 -*-
"""몰 새 완제PC 수집 결과 -> 0169 모양의 적재 데이터 JSON (2026-11-20, 0180).

■ 입력: `tools/mall_builtpc_fetch.py --codes … --out new.json` 의 결과(공개 상세 페이지에서 읽은 제목 · 시중가 ·
  판매가 · 부품 줄). 이 도구는 네트워크를 쓰지 않는다.
■ 출력: db/migrations/data/new_builtpc_YYYYMMDD.json — 0169 와 같은 키(code · name · sale_price · market_price ·
  spec_source_text · url · includes · spec · balance · dominated_by · fit).
■ 평가: `tools/product_fit.py` 의 specs_of · evaluate · balance_notes · title_mismatch 를 그대로 쓴다(기준표를 바꾸지 않는다).
  상품명이 아니라 **기본 구성 부품 줄**로 평가한다 — 몰 상품명과 구성이 다른 상품이 있다(11-20 실측).
  이름과 구성이 다르면 balance 에 적어 관리자 용도 매트릭스에서 보이게 한다.

    python tools/mall_new_builtpc_seed.py new.json db/migrations/data/new_builtpc_20261120.json 2026-11-20
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import product_fit as F  # noqa: E402

URL = "https://www.popcornpc.co.kr/shop/system_detail.html?pd_no=%s"
SLOT = {"프로세서(CPU)": "CPU", "그래픽(VGA)": "GPU", "메모리(RAM)": "RAM", "초고속(SSD)": "SSD"}


def spec_source_text(parts):
    """몰 엑셀과 같은 「슬롯@@값 ,@@」 모양 — tools/builtpc_parse.py 가 슬롯 어휘로 읽는다."""
    return "".join("%s@@%s ,@@" % (p["cate"], p["name"].strip()) for p in parts)


def name_mismatch(title, sp):
    """상품명의 [램/SSD] 표기와 기본 구성이 다르면 적는다(그래픽은 F.title_mismatch 가 본다)."""
    out = []
    m = re.search(r"/(\d+)G/(\d+)(TB|GB|G)\b", title or "")
    if not m:
        return out
    ram_named = int(m.group(1))
    ssd_named = int(m.group(2)) * (1000 if m.group(3) == "TB" else 1)
    if sp["ram"] and sp["ram"] != ram_named:
        out.append(f"상품명은 램 {ram_named}GB 인데 기본 구성은 {sp['ram']}GB")
    if sp["ssd"] and sp["ssd"] != ssd_named:
        out.append(f"상품명은 SSD {ssd_named}GB 인데 기본 구성은 {sp['ssd']}GB")
    return out


def build(fetched, evaluated_at, source):
    results = []
    for it in fetched["items"]:
        row = {}
        for p in it["parts"]:
            key = SLOT.get(p["cate"])
            if key and key not in row:
                row[key] = p["name"]
        sp = F.specs_of(row)
        if not sp["cpu"]:
            raise SystemExit(f"{it['product_code']}: CPU 판독 불가 — product_fit.CPU_TABLE 에 먼저 추가하세요")
        if sp["ram"] is None or sp["ssd"] is None:
            raise SystemExit(f"{it['product_code']}: 램·SSD 판독 불가")
        title = it["title"].strip()
        ev = F.evaluate(sp)
        results.append(dict(code=int(it["product_code"]), name=title, price=it["sale_price"],
                            market=it["market_price"], parts=it["parts"], spec=sp, eval=ev, excluded=[],
                            includes=[], balance=F.balance_notes(sp, it["sale_price"]) + F.title_mismatch(title, sp)
                            + name_mismatch(title, sp)))
    F.mark_dominated(results)
    prods = []
    for r in results:
        sp = r["spec"]
        cpu, gpu = sp["cpu"] or {}, sp["gpu"] or {}
        prods.append(dict(
            code=r["code"], name=r["name"], sale_price=r["price"], market_price=r["market"],
            spec_source_text=spec_source_text(r["parts"]), url=URL % r["code"], includes=None,
            spec=dict(cpu=cpu.get("name"), gpu=gpu.get("name"), ram_gb=sp["ram"], ssd_gb=sp["ssd"],
                      cpu_mt=cpu.get("mt"), cpu_st=cpu.get("st"), gpu_idx=gpu.get("idx"), vram_gb=gpu.get("vram")),
            balance=" · ".join(r["balance"]) or None,
            dominated_by=int(r["dominated_by"]["code"]) if r.get("dominated_by") else None,
            fit=[dict(usage=u, level=v[0], blocked=v[1]) for u, v in r["eval"].items()]))
    return dict(source=source, evaluated_at=evaluated_at, products=prods)


def main(src, dst, evaluated_at):
    fetched = json.load(open(src, encoding="utf-8"))
    if fetched.get("failed"):
        raise SystemExit(f"수집 실패 항목이 있습니다: {fetched['failed']}")
    out = build(fetched, evaluated_at,
                f"팝콘PC 몰 공개 상품 페이지 수집 {evaluated_at} (tools/mall_builtpc_fetch.py) + tools/product_fit.py")
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    for p in out["products"]:
        print(p["code"], p["sale_price"], p["spec"]["cpu"], p["spec"]["gpu"], p["spec"]["ram_gb"], p["spec"]["ssd_gb"],
              "|", p["balance"] or "")


if __name__ == "__main__":
    main(*sys.argv[1:4])
