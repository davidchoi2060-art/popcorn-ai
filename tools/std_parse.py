# -*- coding: utf-8 -*-
"""조립 보증 사양 재파싱 — `products.spec_source_text` → `std.part_specs` (2026-08-10)

■ 왜 재파싱인가
  저쪽 운영 시스템의 **구조화된 상세 옵션은 사실상 비어 있다**(상품 폼 `option_value[N]`
  10건 전수에서 `selected` 0개 · 고객 페이지 상세정보 표도 항목명만 있고 값 없음).
  **정보는 `pd_spec` 텍스트에만 있고, 그 원문을 우리는 99.7% 갖고 있다.**
  즉 저쪽에서 가져올 게 아니라 **이미 가진 원문을 다시 읽는 것**이다.

■ 이 도구가 지키는 규칙
  1. **`public` 을 건드리지 않는다.** 쓰기 대상은 `std.part_specs` 뿐이다.
  2. **드라이런이 기본**이다. `--apply` 를 줘야 쓴다.
  3. **근거를 함께 남긴다**(`source_ref` = 매칭된 원문 조각). 근거 없는 값은 지어낸 값과
     구별되지 않는다.
  4. **`locked` 행은 건드리지 않는다.** 사람이 고친 값을 파싱이 덮으면 어제 고친 값이
     오늘 되돌아간다.
  5. **모르면 넣지 않는다.** 어휘에 없는 값·형식이 다른 값은 건너뛰고 세어서 보고한다.

■ 매핑하지 않기로 한 것 (실측 후 판단)
  · CASE `gpu_max_slots` ← `PCI슬롯 : N` 은 **확장 슬롯 총 개수**이지 GPU 최대 두께가
    아니다. 갖다 붙이면 3슬롯 카드를 7슬롯 케이스에서 통과시킨다.
  · CPU `igpu_yn=false` — 원문에 '내장그래픽' 이 없다고 내장그래픽이 없는 것은 아니다.
    **있으면 true 만 넣는다.**
  · COOLER `ram_clearance_mm` — 공랭 쿨러 원문에 사양이 거의 없다(제조사·모델명뿐).
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console                    # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                                    # noqa: E402
from sqlalchemy import create_engine, text                        # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
ENGINE = create_engine(os.environ["DATABASE_URL"])

# 알려진 파워 규격만 취한다 — 모르는 값은 넣지 않는다
PSU_FF = {"ATX": "ATX", "표준 ATX": "ATX", "SFX": "SFX", "SFX L": "SFX-L",
          "SFX-L": "SFX-L", "TFX": "TFX", "FLEX": "FLEX", "M ATX": "M-ATX",
          "MATX": "M-ATX", "DC TO DC": "DC-DC"}


def _int(s):
    return int(str(s).replace(",", ""))


def p_num(rx, cast=_int, pick="first"):
    """숫자 하나를 뽑는 규칙. pick='max' 면 여러 매치 중 최대."""
    def f(txt):
        ms = list(re.finditer(rx, txt))
        if not ms:
            return None
        m = max(ms, key=lambda x: cast(x.group(1))) if pick == "max" else ms[0]
        return cast(m.group(1)), m.group(0)
    return f


def p_flag(rx):
    def f(txt):
        m = re.search(rx, txt)
        return (True, m.group(0)) if m else None
    return f


def p_text(rx):
    def f(txt):
        m = re.search(rx, txt)
        if not m:
            return None
        v = m.group(1).strip()
        return (v[:200], m.group(0)[:120]) if v else None
    return f


def p_psu_ff(txt):
    """케이스가 수용하는 파워 규격. **첫 항목만** 본다 —
    원문은 `지원 파워 : ATX / ATX / mATX / MiniITX` 처럼 뒤에 **보드 규격**이 이어진다.

    ⚠ `지원 파워 : mATX` 처럼 **첫 항목이 단독 mATX** 인 것은 넣지 않는다.
      실제 원문이 `지원 파워 : mATX / ATX / mATX / ITX`(미들타워)인데, 미들타워가
      M-ATX 파워만 받는다는 것은 말이 안 된다 — **뒤의 보드 규격 목록이 앞으로 밀려온
      것**으로 본다. 6건뿐이고, 틀린 값을 넣으면 B5 판정이 반대로 뒤집힌다.
      `mATX,SFX` 처럼 **쉼표로 명시된 것은 진짜 파워 규격 표기**라 살린다.
    """
    m = re.search(r"지원\s*파워\s*:\s*([^/]+)", txt)
    if not m:
        return None
    raw = m.group(1).strip()
    parts = re.split(r"[,·]", raw)
    if len(parts) == 1 and parts[0].strip().upper().replace("-", " ").strip() in ("M ATX", "MATX"):
        return None
    out = []
    for part in parts:
        key = part.strip().upper().replace("-", " ").strip()
        if key in PSU_FF and PSU_FF[key] not in out:
            out.append(PSU_FF[key])
    return (out, m.group(0)[:120]) if out else None


def p_mem_types(txt):
    out = []
    for m in re.finditer(r"(?<![A-Za-z0-9])(DDR[45])(?![A-Za-z0-9])", txt):
        if m.group(1) not in out:
            out.append(m.group(1))
    return (out, "·".join(out)) if out else None


def p_psu_aux(txt):
    """파워가 제공하는 PCIe 보조전원. 형식이 둘이다:
       `16핀 PCIe(12+4) : 12V2x6 1(개)` · `8핀 PCIe(6+2) : 3(개)`"""
    out, refs = [], []
    m = re.search(r"16핀\s*PCIe[^:]*:\s*\S*\s*(\d+)", txt)
    if m:
        out.append({"type": "12V-2x6", "count": _int(m.group(1))}); refs.append(m.group(0))
    m = re.search(r"8핀\s*PCIe[^:]*:\s*(\d+)", txt)
    if m:
        out.append({"type": "8pin", "count": _int(m.group(1))}); refs.append(m.group(0))
    return (out, " / ".join(refs)[:120]) if out else None


_SOCK_TOKEN = re.compile(
    r"(?:소켓\s*|LGA\s*)(\d{3,4})\s*(\(X\)|V\s*3)?|(?<![A-Za-z])(AM[45])(?![0-9])"
    r"|(?<![A-Za-z])(sTRX\d|STRX\d|TR4|sTR5|STR5)(?![0-9])", re.I)


def p_socket_list(txt):
    """쿨러가 지원하는 소켓 목록.

    ■ 왜 다시 파싱하나 — **기존 값이 틀렸다**(실물 검증이 잡았다)
      원문에 소켓 표기가 **두 형식**으로 섞여 있는데 기존 파서는 `LGA1700` 만 읽고
      **`소켓1700`(한글 '소켓' + 숫자, 275건)을 놓쳤다.** 그 결과 `LGA1700` 이
      **234건**에서 빠졌다 — 인텔 12~14세대 현행 주력 소켓이다.

      실제 사례(Thermalright Peerless Assassin 120 SE, 제조사 공식 스펙으로 확인):
        원문   : … / 소켓1700 / LGA1200 / LGA115(X) / LGA2011 V3 / … / AM4 / …
        기존 값: [AM4, LGA115(X), LGA1200, LGA2011, LGA2011-V3, LGA2066]  ← 1700 없음
      **멀쩡한 쿨러가 LGA1700 CPU 와 안 맞는다고 판정돼 조용히 견적에서 빠진다.**

    ■ 어휘는 기존 저장값을 따른다
      `LGA115(X)` · `LGA2011-V3` 처럼 이미 쓰이는 표기를 유지한다 — 새 표기를 만들면
      같은 소켓이 두 이름으로 갈라진다.
    """
    out, refs = [], []
    for m in _SOCK_TOKEN.finditer(txt):
        num, suf, am, tr = m.group(1), m.group(2), m.group(3), m.group(4)
        if num:
            v = "LGA" + num
            if suf and "(" in suf:
                v = "LGA115(X)" if num == "115" else v + "(X)"
            elif suf:
                v += "-V3"
        elif am:
            v = am.upper()
        else:
            v = tr.upper().replace("STRX", "STRX")
        if v not in out:
            out.append(v)
            refs.append(m.group(0).strip())
    return (out, " / ".join(refs)[:200]) if out else None


def p_gpu_aux(txt):
    """GPU 가 요구하는 보조전원. `16핀(12V2x6),1개` · `8핀,2개` 형식."""
    out, refs = [], []
    for m in re.finditer(r"(\d+)핀\(([^)]*)\)\s*,?\s*(\d+)?개?", txt):
        kind = "12V-2x6" if "12V2X6" in m.group(2).upper().replace(" ", "") else m.group(1) + "pin"
        out.append({"type": kind, "count": _int(m.group(3) or 1)}); refs.append(m.group(0))
    return (out, " / ".join(refs)[:120]) if out else None


# 부품 종류 → {필드: 파서}
RULES = {
    "MB": {
        # '슬롯 : N' — 구분자 바로 뒤여야 한다(`PCI슬롯` 같은 다른 항목과 섞이지 않게)
        "mem_slots":         p_num(r"(?:^|/)\s*슬롯\s*:\s*(\d+)"),
        "mem_max_gb":        p_num(r"최대\s*([\d,]+)\(GB\)"),
        "m2_slots":          p_num(r"M\.2\s*:\s*(\d+)"),
        "sata_ports":        p_num(r"SATA3?\s*:\s*(\d+)"),
        "pcie_x16_gen":      p_num(r"PCIe(\d)\.0", pick="max"),
        "mem_max_clock_mhz": p_num(r"([\d,]+)\(MHz\)", pick="max"),
    },
    "CASE": {
        "bay_35_count":         p_num(r"3\.5베이\s*:\s*(\d+)"),
        "bay_25_count":         p_num(r"2\.5베이\s*:\s*(\d+)"),
        "psu_form_factor_list": p_psu_ff,
    },
    "RAM": {
        "module_count": p_num(r"패키지\s*구성\s*:\s*(\d+)"),
    },
    "CPU": {
        "igpu_yn":          p_flag(r"내장그래픽"),
        "cpu_generation":   p_text(r"/\s*([^/]*(?:레이크|Zen\s*\d|릿지|리프레시|세대)[^/]*?)\s*/"),
        "mem_type_support": p_mem_types,
    },
    "POWER": {
        "length_mm":          p_num(r"깊이\s*:\s*([\d.]+)\(mm\)", cast=lambda s: int(float(s))),
        "eps_connectors":     p_num(r"보조전원\s*:[^/]*?x\s*(\d+)"),
        "sata_connectors":    p_num(r"SATA\s*:\s*(\d+)"),
        "aux_power_provided": p_psu_aux,
    },
    "GPU": {
        "aux_power_req": p_gpu_aux,
    },
    # 쿨러는 원문에 사양이 거의 없지만 **소켓 목록만은 있고, 그게 틀려 있었다**
    "COOLER_CPU_AIR": {"socket_list": p_socket_list},
    "COOLER_CPU_AIO": {"socket_list": p_socket_list},
}

LIST_FIELDS = {"psu_form_factor_list", "mem_type_support", "aux_power_provided",
               "aux_power_req", "socket_list"}
BOOL_FIELDS = {"igpu_yn"}
TEXT_FIELDS = {"cpu_generation"}

# 항목별 신뢰도 — **추출에 성공했다고 값이 확실한 것은 아니다.**
# 낮은 것은 사람 검수 대상이 되고, 필수 승격 전에 확인해야 한다.
CONFIDENCE = {
    # 원문이 `PCIe5.0 / PCIe4.0` 처럼 세대를 나열만 한다. 그중 5.0 이 x16 슬롯인지
    # M.2 인지 원문으로는 구분되지 않는다 — 최대값을 쓰되 낙관적임을 신뢰도로 남긴다.
    "pcie_x16_gen": 0.60,
    # 메모리 클럭도 여러 값이 나열되면 최대를 취한다(오버클럭 표기 포함 가능).
    "mem_max_clock_mhz": 0.75,
    # 케이스 파워 규격은 뒤에 보드 규격이 이어붙는 원문이라 첫 항목만 취한다.
    "psu_form_factor_list": 0.80,
}
DEFAULT_CONFIDENCE = 0.90


def run(apply_it, only=None, limit=None):
    part_types = [p for p in RULES if not only or p == only]
    plan, skipped = [], {}
    with ENGINE.connect() as c:
        defined = {r[0] for r in c.execute(text("SELECT field_key FROM std.spec_defs")).all()}
        locked = {(r[0], r[1]) for r in c.execute(text(
            "SELECT product_code, field_key FROM std.part_specs WHERE locked")).all()}
        existing = {(r[0], r[1]): (r[2], r[3], r[4]) for r in c.execute(text(
            "SELECT product_code, field_key, value_text, value_num, value_json"
            " FROM std.part_specs")).all()}

        for pt in part_types:
            unknown = [f for f in RULES[pt] if f not in defined]
            if unknown:
                raise SystemExit(f"std.spec_defs 에 없는 필드: {pt} -> {unknown}")
            # **모집단을 재고로 좁히지 않는다.** 처음엔 `status='판매중' AND stock_qty>0`
            # 으로 제한했는데, 그 결과 재고 0인 `DEEPCOOL AG400`(112889)이 **원문에
            # LGA1700 이 있는데도 옛 값 그대로** 남아 실물 검증에서 탈락했다.
            # 재고는 내일 바뀌고 **파싱은 공짜다** — 사람 입력만 우선순위를 두면 된다.
            q = ("SELECT product_code, spec_source_text FROM products"
                 " WHERE part_type=:t AND category_group='core_part'"
                 "   AND spec_source_text IS NOT NULL AND spec_source_text <> ''")
            if limit:
                q += " ORDER BY product_code DESC LIMIT :n"
            rows = c.execute(text(q), {"t": pt, "n": limit}).all()
            skipped[pt] = {"모집단": len(rows)}
            for pc, txt in rows:
                for field, fn in RULES[pt].items():
                    got = fn(txt)
                    if not got:
                        skipped[pt][field] = skipped[pt].get(field, 0) + 1
                        continue
                    val, ref = got
                    if (pc, field) in locked:
                        continue
                    plan.append((pc, field, val, ref, pt))

    # ── 드라이런 보고 — 건수가 아니라 **영향**을 말한다 ────────────────────
    # **부품 종류별로 센다.** 필드명으로만 세면 `socket_list` 가 공랭·수랭 양쪽에
    # 걸려 합산돼 추출률이 173% 로 나온다(실제로 그렇게 틀린 수를 냈다).
    by_field = {}
    for pc, field, val, ref, pt in plan:
        d = by_field.setdefault((pt, field), {"new": 0, "same": 0, "diff": 0, "sample": None})
        cur = existing.get((pc, field))
        if cur is None:
            d["new"] += 1
        else:
            old = cur[0] if cur[0] is not None else (cur[1] if cur[1] is not None else cur[2])
            d["same" if str(old) == str(val) else "diff"] += 1
        if d["sample"] is None:
            d["sample"] = (pc, val, ref)

    print("=" * 74)
    print("조립 사양 재파싱 — %s" % ("적용" if apply_it else "드라이런(쓰지 않음)"))
    print("=" * 74)
    for pt in part_types:
        pop = skipped[pt]["모집단"]
        print("\n[%s] 모집단 %d건" % (pt, pop))
        for field in RULES[pt]:
            d = by_field.get((pt, field), {"new": 0, "same": 0, "diff": 0, "sample": None})
            got = d["new"] + d["same"] + d["diff"]
            miss = skipped[pt].get(field, 0)
            print("  %-22s 추출 %4d (%3.0f%%) · 신규 %4d · 동일 %4d · 변경 %3d · 못읽음 %4d"
                  % (field, got, got * 100.0 / max(pop, 1), d["new"], d["same"], d["diff"], miss))
            if d["sample"]:
                pc, val, ref = d["sample"]
                print("        예: %s = %s   ← %r" % (pc, json.dumps(val, ensure_ascii=False), ref[:60]))

    print("\n총 %d건을 쓸 예정" % len(plan))
    if not apply_it:
        print("적용하려면 --apply")
        return 0

    with ENGINE.begin() as c:
        for pc, field, val, ref, _pt in plan:
            vt = vn = vj = None
            if field in LIST_FIELDS:
                vj = json.dumps(val, ensure_ascii=False)
            elif field in BOOL_FIELDS:
                vt = "true" if val else "false"
            elif field in TEXT_FIELDS:
                vt = val
            else:
                vn = val
            c.execute(text(
                "INSERT INTO std.part_specs"
                " (product_code, field_key, value_text, value_num, value_json,"
                "  source, source_ref, confidence, updated_at)"
                " VALUES (:pc, :f, :vt, :vn, CAST(:vj AS JSONB), 'parsed', :ref, :cf, now())"
                " ON CONFLICT (product_code, field_key) DO UPDATE SET"
                "   value_text = EXCLUDED.value_text, value_num = EXCLUDED.value_num,"
                "   value_json = EXCLUDED.value_json, source = 'parsed',"
                "   source_ref = EXCLUDED.source_ref, confidence = EXCLUDED.confidence,"
                "   updated_at = now()"
                " WHERE std.part_specs.locked = false"),
                {"pc": pc, "f": field, "vt": vt, "vn": vn, "vj": vj, "ref": ref[:200],
                 "cf": CONFIDENCE.get(field, DEFAULT_CONFIDENCE)})
    print("적용 완료 — %d건" % len(plan))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다(기본은 드라이런)")
    ap.add_argument("--part", help="부품 종류 하나만")
    ap.add_argument("--limit", type=int, help="상품 수 제한(시험용)")
    a = ap.parse_args()
    sys.exit(run(a.apply, a.part, a.limit))
