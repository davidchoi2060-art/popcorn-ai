# -*- coding: utf-8 -*-
"""표준 검증 — **실제로 조립되어 팔린 PC** 로 표준이 옳은지 본다 (2026-08-10)

■ 왜 이게 가장 강한 검증인가
  사용자 지적: *"데이터를 많이 만드는 게 중요한 게 아니고, 진짜 제대로 된 표준을 세우는
  게 중요합니다."* 맞다. 지금까지 42,022건을 넣었지만 **표준이 옳다는 증거는 없었다.**

  가장 강한 증거는 이것이다 — **실제로 조립되어 나간 PC 가 우리 규칙에서 탈락하면
  규칙이 틀린 것이다.** 반대로 통과하면 규칙이 최소한 실물을 배신하지 않는다.

  표본: `products.part_type='PC_COMPLETE'` **318종**(판매중 208).
  구성이 `spec_source_text` 에 `슬롯명@@부품명 ,@@` 형식으로 들어 있다.

■ 이 도구가 정직하게 세는 것
  1. **이름 매칭률** — 구성의 부품명을 우리 카탈로그에서 찾았는가. 못 찾으면 검증 불가다.
  2. **판정 가능률** — 표준 값이 양쪽에 다 있어야 비교할 수 있다. 없으면 '모름'이지 '통과'가 아니다.
  3. **판정 결과** — 통과 / **탈락**. 탈락이 진짜 검증 신호다.

  **'모름'을 '통과'로 세지 않는다.** 그러면 값이 없을수록 통과율이 올라가는 거짓 지표가 된다.

■ 쓰기 없음. 읽기만 한다.
"""
import argparse
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv                                    # noqa: E402
from sqlalchemy import create_engine, text                        # noqa: E402

from api.dedupe import score as sim                               # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
ENGINE = create_engine(os.environ["DATABASE_URL"])

SLOT = {"프로세서(CPU)": "CPU", "메인보드": "MB", "메모리(RAM)": "RAM", "그래픽(VGA)": "GPU",
        "초고속(SSD)": "SSD", "대용량(HDD)": "HDD", "케이스": "CASE", "파워": "POWER",
        "CPU쿨러": "COOLER"}
COOLERS = ("COOLER_CPU_AIR", "COOLER_CPU_AIO")
MATCH_MIN = 0.55        # 이 아래는 '못 찾았다'로 본다(다른 부품을 잘못 붙이는 것보다 낫다)

# ── 모델 번호 매칭 ────────────────────────────────────────────────────────
# `api.dedupe.score` 는 **중복 판정용**이라 부스트를 일부러 뺐다(0.97 임계, 실측 근거 있음).
# 여기 문제는 다르다 — **어휘가 다른 두 표기를 잇는 것**이다:
#     완제품 구성 : 인텔 15세대 코어 울트라7 265 Turbo 5.3GHz, 20코어(8+12), Xe Graphics
#     카탈로그    : 인텔 코어 울트라7 시리즈2 265 (애로우레이크) (정품)      base 0.40
# 사람은 `265` 하나로 같은 물건임을 안다. 그 신호를 쓴다.
# **dedupe 를 고치지 않는다** — 거긴 부스트가 들어가면 중복 판정이 망가진다.

# 규격·단위라서 모델 식별자가 아닌 토큰
_NOT_MODEL = {
    "ddr3", "ddr4", "ddr5", "pcie3", "pcie4", "pcie5", "pcie", "atx3", "atx12v",
    "pc3", "pc4", "pc5", "80plus", "sata2", "sata3", "usb2", "usb3", "m2", "12v",
    "3d", "2d", "4k", "8k", "1ms", "7p", "6p", "x2", "x4", "x8", "x16", "cl16",
    "cl18", "cl22", "cl30", "cl38", "cl40", "cl46", "rgb", "argb", "type-c",
}
_UNIT_TAIL = re.compile(r"^\d+(gb|tb|mb|kb|w|v|a|mhz|ghz|mm|cm|hz|bit|ea|p)$")
# **하이픈으로 쪼갠다** — 안 쪼개면 `i5-14600k` 와 `14600k` 가 다른 토큰이 되어
# 같은 CPU 를 못 알아본다(실제로 그렇게 틀렸다).
_TOKEN = re.compile(r"[a-z0-9]+")
# `dedupe` 가 세는 용량 토큰. 이게 어긋나면 **다른 상품**이므로 부스트를 주면 안 된다
# (16GB 와 32GB 가 `DDR5-5600` 공통 토큰 때문에 0.96 으로 붙었다).
_CAP = re.compile(r"\d+\s*(?:gb|tb|mb|w|mm|hz)")


# **치수는 모델명이 아니다.** 쿨러의 `240`·`360` 은 라디에이터 크기, 팬의 `120`·`140` 은
# 팬 지름이다. 이걸 강한 토큰으로 보면 전혀 다른 제품이 붙는다 —
# `DARKFLASH NEBULA DN 240` 과 `DARKFLASH Twister DX 240 (핑크)` 이 1.00 으로 붙었다.
_DIMENSION = {"92", "120", "140", "200", "240", "280", "360", "420", "480"}
# 부스트를 주기 전에 넘어야 하는 이름 자체의 최소 유사도.
# 모델 토큰이 겹쳐도 **이름이 전혀 다르면** 다른 제품일 가능성이 높다.
_BASE_FLOOR = 0.30


def model_tokens(s):
    """모델 식별자 후보를 **강·약으로 나눈다.**

    · **강** = 숫자 3자리 이상을 품은 토큰(`14600k`·`9950x`·`265`·`5090`·`sn580`).
      이게 겹쳐야 같은 물건이라 볼 수 있다.
    · **약** = 나머지(`i5`·`d7`) **와 치수**(`240`·`360`). 겹쳐도 증거가 못 된다 —
      `RTX 5060 Ti … D7` 과 `RTX 5090 … D7` 이 `d7` 하나로 붙었고,
      쿨러는 `240` 하나로 다른 제품끼리 붙었다.
    """
    strong, weak = set(), set()
    for t in _TOKEN.findall(str(s or "").lower()):
        if not any(ch.isdigit() for ch in t):
            continue
        if t in _NOT_MODEL or _UNIT_TAIL.match(t):
            continue
        digits = sum(ch.isdigit() for ch in t)
        if t.isdigit() and len(t) < 3:      # 세대·코어수 같은 한두 자리 수는 신호가 아니다
            continue
        if t in _DIMENSION:                 # 치수는 약한 토큰
            weak.add(t)
            continue
        (strong if digits >= 3 else weak).add(t)
    return strong, weak


def match_score(a, b):
    """0~1. `dedupe.score` 에 **모델 번호 일치**를 더한 값.

    `api.dedupe.score` 를 고치지 않는 이유: 거긴 **중복 판정용**이라 부스트를 일부러 뺐고
    임계 0.97 이 실측으로 정해져 있다. 부스트를 넣으면 그 판정이 망가진다.

    규칙 셋 — **전부 "붙이지 않을 이유"를 먼저 본다**:
      ① 용량이 어긋나면(`16GB` vs `32GB`) 부스트 없음. 다른 상품이다.
      ② 강한 모델 토큰이 양쪽에 있는데 안 겹치면 깎는다(`5060` vs `5090`).
      ③ 강한 토큰이 겹칠 때만 올린다. 약한 토큰(`d7`·`i5`)만으로는 올리지 않는다.
    """
    base = sim(a, b)
    ca, cb = set(_CAP.findall(a.lower())), set(_CAP.findall(b.lower()))
    if ca and cb and ca != cb:                       # ①
        return base
    sa, wa = model_tokens(a)
    sb, wb = model_tokens(b)
    inter = sa & sb
    if not inter and sa and sb:                      # ②
        return base * 0.60
    if inter and base >= _BASE_FLOOR:                # ③
        return min(1.0, base + 0.40 + 0.05 * min(len(inter), 3))
    return base


def parse_build(txt):
    """`슬롯명@@부품명 ,@@` → {슬롯: 부품명}. '선택하세요' 는 미선택이라 뺀다."""
    parts, out = txt.split("@@"), {}
    for i in range(0, len(parts) - 1, 2):
        k = parts[i].replace(",", " ").strip()
        v = re.sub(r"\s+", " ", parts[i + 1]).strip().rstrip(",").strip()
        if k in SLOT and v and "선택하세요" not in v and "선택하셔요" not in v:
            out[SLOT[k]] = v
    return out


def main(limit, show):
    with ENGINE.connect() as c:
        builds = c.execute(text(
            "SELECT product_code, product_name, spec_source_text FROM products"
            " WHERE part_type='PC_COMPLETE' AND spec_source_text LIKE '%@@%'"
            " ORDER BY product_code DESC" + (" LIMIT :n" if limit else "")),
            {"n": limit}).all()

        cat = {}
        for r in c.execute(text(
                "SELECT product_code, product_name, part_type FROM products"
                " WHERE category_group='core_part'")).all():
            cat.setdefault(r[2], []).append((r[0], r[1]))

        specs = {}
        for r in c.execute(text(
                "SELECT product_code, field_key, value_text, value_num, value_json"
                " FROM std.part_specs")).all():
            v = r[2] if r[2] is not None else (r[3] if r[3] is not None else r[4])
            specs.setdefault(r[0], {})[r[1]] = v

        rules = c.execute(text(
            "SELECT rule_key, slot, field, op, ref_slot, ref_field, label, part_types"
            " FROM compat_rules WHERE active ORDER BY sort_order")).mappings().all()

    def find(name, slot):
        pool = []
        for pt in (COOLERS if slot == "COOLER" else [slot]):
            pool += cat.get(pt, [])
        best, bs = None, 0.0
        for pc, pn in pool:
            s = match_score(name, pn)
            if s > bs:
                best, bs = (pc, pn), s
        return (best, bs) if bs >= MATCH_MIN else (None, bs)

    # ── 1. 매칭 ──────────────────────────────────────────────────────────
    resolved, m_stat = [], Counter()
    for pc, pname, txt in builds:
        b = parse_build(txt)
        got, miss = {}, []
        for slot, nm in b.items():
            hit, s = find(nm, slot)
            m_stat[slot + ("_ok" if hit else "_miss")] += 1
            if hit:
                got[slot] = hit[0]
            else:
                miss.append((slot, nm, round(s, 2)))
        resolved.append((pc, pname, b, got, miss))

    slots_seen = sorted({s.replace("_ok", "").replace("_miss", "") for s in m_stat})
    print("=" * 74)
    print("표준 검증 — 실제로 조립되어 팔린 PC %d종" % len(builds))
    print("=" * 74)
    print("\n[1] 이름 매칭 (유사도 %.2f 이상만 인정)" % MATCH_MIN)
    for s in slots_seen:
        ok, ms = m_stat[s + "_ok"], m_stat[s + "_miss"]
        if ok + ms:
            print("  %-8s 찾음 %3d / %3d (%3.0f%%)" % (s, ok, ok + ms, ok * 100.0 / (ok + ms)))

    # ── 2. 규칙 판정 ─────────────────────────────────────────────────────
    def val(pc, field):
        return specs.get(pc, {}).get(field)

    def cmp_(op, v, r):
        if v is None or r is None:
            return None
        try:
            if op == "eq":
                return str(v).strip().upper() == str(r).strip().upper()
            if op == "gte":
                return float(v) >= float(r)
            if op == "lte":
                return float(v) <= float(r)
            if op == "contains":
                seq = v if isinstance(v, list) else [v]
                return any(str(r).strip().upper() == str(x).strip().upper() for x in seq)
        except (TypeError, ValueError):
            return None
        return None

    verdict = Counter()
    fails = []
    for pc, pname, b, got, miss in resolved:
        for ru in rules:
            slot, ref = ru["slot"], ru["ref_slot"]
            a = got.get(slot)
            rb = got.get(ref)
            if a is None or rb is None:
                verdict[ru["rule_key"] + "|no_part"] += 1
                continue
            res = cmp_(ru["op"], val(a, ru["field"]), val(rb, ru["ref_field"]))
            if res is None:
                verdict[ru["rule_key"] + "|unknown"] += 1
            elif res:
                verdict[ru["rule_key"] + "|pass"] += 1
            else:
                verdict[ru["rule_key"] + "|fail"] += 1
                fails.append((pc, pname, ru["rule_key"], ru["label"],
                              slot, b.get(slot), val(a, ru["field"]),
                              ref, b.get(ref), val(rb, ru["ref_field"])))

    print("\n[2] 규칙 판정 — **'모름'을 '통과'로 세지 않는다**")
    print("  %-26s %6s %6s %8s %8s" % ("규칙", "통과", "탈락", "값모름", "부품못찾음"))
    for ru in rules:
        k = ru["rule_key"]
        p, f, u, n = (verdict[k + "|pass"], verdict[k + "|fail"],
                      verdict[k + "|unknown"], verdict[k + "|no_part"])
        judged = p + f
        mark = "  ← 탈락 있음" if f else ("  ← 판정 0건" if judged == 0 else "")
        print("  %-26s %6d %6d %8d %8d%s" % (k[:26], p, f, u, n, mark))

    tot_p, tot_f = sum(v for k, v in verdict.items() if k.endswith("|pass")), \
                   sum(v for k, v in verdict.items() if k.endswith("|fail"))
    tot_u = sum(v for k, v in verdict.items() if k.endswith("|unknown"))
    tot_n = sum(v for k, v in verdict.items() if k.endswith("|no_part"))
    print("\n  합계: 통과 %d · 탈락 %d · 값모름 %d · 부품못찾음 %d" % (tot_p, tot_f, tot_u, tot_n))
    if tot_p + tot_f:
        print("  **판정할 수 있었던 것 중 통과율 %.1f%%**" % (tot_p * 100.0 / (tot_p + tot_f)))
    print("  판정 가능 비율 %.1f%% (나머지는 값이 없거나 부품을 못 찾았다)"
          % ((tot_p + tot_f) * 100.0 / max(tot_p + tot_f + tot_u + tot_n, 1)))

    if fails:
        print("\n[3] **탈락한 실물 조합** — 이게 규칙이 틀렸다는 신호다 (상위 %d건)" % show)
        for x in fails[:show]:
            print("  · %s %s" % (x[0], x[1][:44]))
            print("      %s (%s)" % (x[3], x[2]))
            print("      %-6s %s  = %r" % (x[4], (x[5] or "")[:40], x[6]))
            print("      %-6s %s  = %r" % (x[7], (x[8] or "")[:40], x[9]))

    print("\n[4] 못 찾은 부품 표본")
    shown = 0
    for pc, pname, b, got, miss in resolved:
        for slot, nm, s in miss:
            if shown >= 8:
                break
            print("  %-6s (최고 유사도 %.2f) %s" % (slot, s, nm[:60]))
            shown += 1
        if shown >= 8:
            break
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="완제품 수 제한(시험용)")
    ap.add_argument("--show", type=int, default=6, help="탈락 사례 표시 수")
    a = ap.parse_args()
    sys.exit(main(a.limit, a.show))
