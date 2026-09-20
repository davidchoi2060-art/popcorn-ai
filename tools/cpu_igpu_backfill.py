# -*- coding: utf-8 -*-
"""CPU 내장그래픽(`product_specs.cpu_gpu`) 백필 — 원문 + 모델명 규칙 (2026-09-18).

실행:
  .venv/Scripts/python tools/cpu_igpu_backfill.py --dry      # 기본. DB 무변경
  .venv/Scripts/python tools/cpu_igpu_backfill.py --apply    # NULL 인 행만 채운다
  .venv/Scripts/python tools/cpu_igpu_backfill.py --dry --show-null      # NULL 로 남길 것 전부
  .venv/Scripts/python tools/cpu_igpu_backfill.py --dry --show-override  # 원문을 뒤집은 행
  .venv/Scripts/python tools/cpu_igpu_backfill.py --verify   # 사장님 6벌 + F 계열 대조

■ 왜 필요한가
`cpu_gpu`(0020)는 CPU 683 행 중 **1 행만** 채워져 있던 죽은 필드였다. 그런데 사장님이
실제로 파는 사무용 PC 6 벌은 **전부 내장그래픽 CPU** 다 — 「사무용 = 내장그래픽」이
정의인데 DB 가 그걸 모른다. 모르면 사무용 견적에 쓸모없는 외장 GPU(최저 297,700원)를
붙이거나, 안 붙이면 **화면 출력이 안 되는 PC** 를 내민다.

■ 실측으로 드러난 것 — 원문도 모델명도 «혼자서는» 못 믿는다 (2026-09-18, CPU 683 행)
  · `products.spec_source_text`(다나와 규격 문자열)에 항목이 있다: 683 중 580 행.
    형태는 두 가지뿐이다 — `내장그래픽 : 없음` / `내장그래픽 / 라데온 그래픽`.
  · **그런데 원문이 틀린 곳이 있다**(실측 확인):
      11900F · 11900KF -> 원문 「내장그래픽 / UHD 750」  ← F 는 정의상 iGPU 가 없다
      11400 · 9900K    -> 원문 「내장그래픽 : 없음」      ← 실제로는 UHD 가 있다
    다나와 쪽에서 비-F 모델의 값이 F 행에 섞여 들어간 형태다.
  · **모델명 규칙도 틀린 곳이 있다**: AMD 라이젠 7000/9000(Zen4·Zen5)은 G 가 없어도
    내장그래픽(라데온 2CU)이 «있다» — 원문이 그렇게 적고 있고 그게 맞다.
    「AMD 는 G 가 붙어야 iGPU」는 Zen3 까지의 이야기다.

■ 그래서 판정 순서 — 위험이 «비대칭»이라 이렇게 짰다
잘못 True = 화면 출력 안 되는 PC 를 판다(되돌릴 수 없다).
잘못 False = 필요 없는 그래픽카드가 붙는다(비싸지만 «조립은 된다»).
그래서 애매하면 항상 False 쪽으로 기운다.

  ① **접미문자 확정 규칙이 원문을 이긴다**(유일한 예외이자 안전장치):
       인텔 모델번호가 F/KF 로 끝남     -> False. 'F' 는 제조사가 «그래픽 없음»을
                                          뜻으로 붙이는 글자다. 원문이 UHD 를 적어도
                                          그건 다나와 오기다(실측 11900F).
       인텔 제온(Xeon)                   -> False. 서버용이라 대부분 없다.
                                          (E3-1275V6 처럼 있는 모델도 있지만 안전한
                                           쪽으로 내린다 — 사무용에 제온을 쓰지 않는다)
       AMD 모델번호가 F 로 끝남(7500F)  -> False. AMD 도 F 는 iGPU 비활성 표시다.
  ② 그 밖에는 **원문**이 정한다(1순위 근거):
       `내장그래픽 : 없음` / `내장그래픽없음` -> False
       `내장그래픽` 항목이 있고 뒤에 GPU 이름 -> True
     ⚠ **'없음' 을 «먼저» 본다.** 둘 다 '내장그래픽' 이라는 글자를 갖고 있어서 포함
     쪽을 먼저 돌리면 7500F 를 True 로 오판한다 — 그 오판의 결과가 화면 안 나오는 견적이다
     (`cpu_bundled_cooler` 의 '미포함 먼저' 와 같은 이유. 순서가 곧 안전장치다).
     ⚠ 단 **인텔 비-F 인데 원문이 '없음' 이라고 적은 행은 NULL 로 남긴다.** 실측상 이
     조합에는 원문이 맞는 것(i9-10900X 등 코어X-시리즈 — 실제로 iGPU 없음)과 원문이
     틀린 것(i5-11400 · i9-9900K — 실제로는 UHD 있음)이 «섞여» 있어서 어느 쪽인지
     기계가 가릴 수 없다. 틀린 False 는 화면은 나오지만(안전) 쓸모없는 그래픽카드를
     붙이므로, 지어내는 대신 모른다고 적는 쪽을 택한다.
  ③ 원문에 항목이 없으면 **모델명 규칙**(2순위):
       인텔 비-F 이고 모델번호를 읽을 수 있음 -> True
       AMD  G/GE/GT(APU)                      -> True
       그 밖                                   -> 판정하지 않는다
     ⚠ AMD 의 「G 가 없음」은 **False 의 근거가 되지 못한다**(위 Zen4 실측). 그래서
     원문 없는 AMD 비-G 는 NULL 로 남긴다.
  ④ 아무 근거도 없으면 **NULL.** 지어내지 않는다 — 셀러론/펜티엄 G 계열 구형(원문 없음),
     쓰레드리퍼, 제조사 불명 행이 여기 남는다.

■ 지키는 규칙
  · `locked_fields` 에 'cpu_gpu' 가 잠긴 행은 건너뛴다(ERD §4.3).
  · **이미 값이 있는 행은 덮지 않는다** — 사람이 검수한 값일 수 있다(멱등성도 여기서 온다).
  · 출처를 `product_specs.spec_sources.cpu_gpu` 에 남긴다.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

from sqlalchemy import text                          # noqa: E402

from api.db import engine                            # noqa: E402

# ── 원문 토큰 ───────────────────────────────────────────────────────────────
# 부정형은 콜론이 있는 규격 문자열(`내장그래픽 : 없음`)과 상품명이 그대로 원문인
# 경우(`내장그래픽없음`) 두 형태로 나온다. 둘 다 잡는다.
IGPU_TXT_NONE = re.compile(r"내장\s*그래픽\s*[:：]?\s*없음")
IGPU_TXT_ANY = re.compile(r"내장\s*그래픽")

# ── 접미문자 확정 규칙(원문보다 우선) ───────────────────────────────────────
INTEL_NO_IGPU = re.compile(r"(?<![0-9A-Za-z])\d{3,5}K?F(?![0-9A-Za-z])")
AMD_NO_IGPU_F = re.compile(r"(?<![0-9A-Za-z])\d{4}F(?![0-9A-Za-z])")
SERVER_HINT = re.compile(r"제온|xeon", re.I)

# ── 모델명 규칙(원문이 없을 때만) ───────────────────────────────────────────
INTEL_MODEL = re.compile(r"(?<![0-9A-Za-z])\d{3,5}[A-Za-z]{0,2}(?![0-9A-Za-z])")
AMD_HAS_IGPU = re.compile(r"(?<![0-9A-Za-z])\d{3,4}G[ET]?(?![0-9A-Za-z])")
HEDT_HINT = re.compile(r"쓰레드리퍼|스레드리퍼|threadripper|epyc|에픽", re.I)

INTEL_MK = ("인텔", "Intel", "INTEL", "intel")
AMD_MK = ("AMD", "amd", "에이엠디")

# 이 도구가 `spec_sources.cpu_gpu` 에 남기는 출처 문자열 — `--retract-conflict` 가
# 「이 도구가 쓴 값」만 거둬들이기 위해 쓴다(사람이 넣은 값은 건드리지 않는다).
TOOL_SOURCES = ("igpu_source_text", "igpu_model_rule")


def suffix_verdict(name: str, maker: str):
    """① 접미문자 확정 규칙 — False 만 내린다(안전한 방향). 없으면 (None, None)."""
    nm = name or ""
    mk = (maker or "").strip()
    if mk in INTEL_MK:
        if SERVER_HINT.search(nm):
            return False, "rule:제온(서버용) - 원문보다 우선"
        if INTEL_NO_IGPU.search(nm):
            return False, "rule:인텔 F/KF 접미 - 원문보다 우선"
    if mk in AMD_MK and AMD_NO_IGPU_F.search(nm):
        return False, "rule:AMD F 접미 - 원문보다 우선"
    return None, None


def text_verdict(src: str):
    """② 원문 판정 — '없음' 을 먼저 본다."""
    s = src or ""
    if IGPU_TXT_NONE.search(s):
        return False, "source_text:내장그래픽 없음"
    if IGPU_TXT_ANY.search(s):
        return True, "source_text:내장그래픽 항목"
    return None, None


def model_verdict(name: str, maker: str):
    """③ 모델명 규칙 — 원문이 없을 때만. AMD 비-G 는 판정하지 않는다."""
    nm = name or ""
    mk = (maker or "").strip()
    if HEDT_HINT.search(nm):
        return None, None
    if mk in INTEL_MK and INTEL_MODEL.search(nm):
        return True, "model_rule:인텔 비-F"
    if mk in AMD_MK and AMD_HAS_IGPU.search(nm):
        return True, "model_rule:AMD G/GE/GT(APU)"
    return None, None


def decide(row):
    """(값, 근거, 상태) — 상태는 suffix/text/model/unknown, 원문 뒤집음이면 *_override."""
    name, maker, src = row["product_name"], row["maker"], row["spec_source_text"]
    tv, tw = text_verdict(src)
    sv, sw = suffix_verdict(name, maker)
    if sv is not None:
        if tv is not None and tv != sv:
            return sv, "%s (원문은 '%s' 라 적혀 있으나 오기로 본다)" % (sw, tw), "suffix_override"
        return sv, sw, "suffix"
    if tv is False and (maker or "").strip() in INTEL_MK and INTEL_MODEL.search(name or ""):
        # 인텔 비-F(접미 규칙이 안 걸린 행)인데 원문이 '없음' 이라고 적었다 — 실측상
        # 맞기도 하고(코어X-시리즈) 틀리기도 해서(11400·9900K) 가릴 수 없다. NULL.
        return None, "원문 '없음' vs 인텔 비-F 규칙 충돌 - 가릴 수 없어 NULL", "text_conflict"
    if tv is not None:
        return tv, tw, "text"
    mv, mw = model_verdict(name, maker)
    if mv is not None:
        return mv, mw, "model"
    return None, "근거 없음(원문에 항목 없음 + 모델명 규칙 적용 불가)", "unknown"


def load():
    with engine.connect() as c:
        return [dict(r) for r in c.execute(text("""
            SELECT p.product_code, p.product_name, p.maker, p.locked_fields,
                   p.spec_source_text, ps.cpu_gpu, ps.spec_sources
              FROM products p
              JOIN product_specs ps ON ps.product_code = p.product_code
             WHERE p.part_type = 'CPU'
             ORDER BY p.product_code
        """)).mappings()]


# 검증 대상 — 사장님이 실제로 파는 사무용 6벌의 CPU 는 전부 True 여야 하고,
# F 계열은 전부 False 여야 한다. **둘 다 맞아야** 규칙이 맞는 것이다.
VERIFY_TRUE = ["3200G", "5500GT", "8500G", "12100", "14100", "225"]
VERIFY_FALSE = ["12100F", "14100F", "225F", "7500F"]


def run_verify():
    ok = True
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(text("""
            SELECT p.product_code, p.product_name, p.maker, ps.cpu_gpu
              FROM products p JOIN product_specs ps ON ps.product_code = p.product_code
             WHERE p.part_type = 'CPU' ORDER BY p.product_code""")).mappings()]

    def pick(model, exclude_f):
        out = []
        for r in rows:
            nm = r["product_name"] or ""
            if not re.search(r"(?<![0-9A-Za-z])%s(?![0-9A-Za-z])" % model, nm):
                continue
            if exclude_f and re.search(r"(?<![0-9A-Za-z])%sF(?![0-9A-Za-z])" % model, nm):
                continue
            out.append(r)
        return out

    print("[verify] 사장님 사무용 6벌 CPU -> 전부 TRUE 여야 한다")
    for m in VERIFY_TRUE:
        hits = pick(m, exclude_f=True)
        bad = [h for h in hits if h["cpu_gpu"] is not True]
        mark = "OK " if hits and not bad else "NG "
        if not hits or bad:
            ok = False
        print("  %s %-8s rows=%-3d true=%-3d not-true=%d"
              % (mark, m, len(hits), len(hits) - len(bad), len(bad)))
        for b in bad:
            print("       ! %s %s -> %s" % (b["product_code"], b["product_name"][:60], b["cpu_gpu"]))

    print("[verify] F 계열 -> 전부 FALSE 여야 한다")
    for m in VERIFY_FALSE:
        hits = pick(m, exclude_f=False)
        bad = [h for h in hits if h["cpu_gpu"] is not False]
        mark = "OK " if hits and not bad else "NG "
        if not hits or bad:
            ok = False
        print("  %s %-8s rows=%-3d false=%-3d not-false=%d"
              % (mark, m, len(hits), len(hits) - len(bad), len(bad)))
        for b in bad:
            print("       ! %s %s -> %s" % (b["product_code"], b["product_name"][:60], b["cpu_gpu"]))
    print("[verify] %s" % ("ALL OK" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="DB 에 기록(기본은 드라이런)")
    ap.add_argument("--dry", action="store_true", help="드라이런(기본값 · 명시용)")
    ap.add_argument("--verify", action="store_true", help="DB 현재값을 6벌/F계열과 대조만 한다")
    ap.add_argument("--show-null", action="store_true", help="NULL 로 남길 행 전부 출력")
    ap.add_argument("--show-override", action="store_true", help="원문을 뒤집은 행 전부 출력")
    ap.add_argument("--retract-conflict", action="store_true",
                    help="이 도구가 쓴 값 중 지금 규칙으로는 '가릴 수 없음'인 행을 NULL 로 되돌린다")
    a = ap.parse_args()
    if a.verify:
        return run_verify()
    apply = a.apply and not a.dry

    if a.retract_conflict:
        # 규칙을 조인 뒤(인텔 비-F + 원문'없음' -> NULL), 이전 실행이 기록해 둔 값을
        # 거둬들인다. **이 도구가 쓴 것만** 건드린다 — spec_sources.cpu_gpu 가 이
        # 도구의 출처 문자열인 행. 사람이 검수한 값·잠긴 값은 손대지 않는다.
        rows = load()
        targets = [r for r in rows
                   if "cpu_gpu" not in (r["locked_fields"] or [])
                   and r["cpu_gpu"] is not None
                   and (r["spec_sources"] or {}).get("cpu_gpu") in TOOL_SOURCES
                   and decide(r)[2] == "text_conflict"]
        print("[retract] 대상 %d 행 (mode=%s)" % (len(targets), "APPLY" if apply else "DRY"))
        for r in targets:
            print("  %s %-58s %s -> NULL" % (r["product_code"], r["product_name"][:58], r["cpu_gpu"]))
        if apply and targets:
            with engine.begin() as c:
                for r in targets:
                    src = dict(r["spec_sources"] or {})
                    src.pop("cpu_gpu", None)
                    c.execute(text("""UPDATE product_specs
                                         SET cpu_gpu = NULL, spec_sources = CAST(:s AS JSONB),
                                             updated_at = now()
                                       WHERE product_code = :c"""),
                              {"s": json.dumps(src, ensure_ascii=False), "c": r["product_code"]})
            print("[OK] retracted %d rows" % len(targets))
        elif not apply:
            print("(dry-run: DB 무변경)")
        return 0

    rows = load()
    stat = Counter()
    writes, nulls, overrides = [], [], []

    for r in rows:
        stat["total"] += 1
        if "cpu_gpu" in (r["locked_fields"] or []):
            stat["skip_locked"] += 1
            continue
        if r["cpu_gpu"] is not None:
            stat["skip_existing"] += 1     # 멱등: 이미 있는 값은 덮지 않는다
            continue
        val, why, state = decide(r)
        stat["state_" + state] += 1
        if state == "suffix_override":
            overrides.append((r["product_code"], r["product_name"], val, why))
        if val is None:
            stat["null"] += 1
            nulls.append((r["product_code"], r["maker"], r["product_name"], why))
            continue
        stat["true" if val else "false"] += 1
        writes.append((r["product_code"], val, state, r["spec_sources"]))

    print("[cpu_igpu_backfill] mode=%s" % ("APPLY" if apply else "DRY"))
    print("  CPU rows            : %d" % stat["total"])
    print("  skip (locked_fields): %d" % stat["skip_locked"])
    print("  skip (already set)  : %d" % stat["skip_existing"])
    print("  -> TRUE             : %d" % stat["true"])
    print("  -> FALSE            : %d" % stat["false"])
    print("  -> left NULL        : %d" % stat["null"])
    print("  evidence: suffix_rule=%d suffix_override=%d source_text=%d model_rule=%d"
          " text_conflict=%d none=%d"
          % (stat["state_suffix"], stat["state_suffix_override"], stat["state_text"],
             stat["state_model"], stat["state_text_conflict"], stat["state_unknown"]))

    if overrides:
        print("\n[OVERRIDE] 접미문자 규칙이 원문을 이긴 행 (%d)" % len(overrides))
        for code, name, val, why in (overrides if a.show_override else overrides[:10]):
            print("  %s %-60s -> %s | %s" % (code, name[:60], val, why))
    if a.show_null:
        print("\n[NULL] 근거가 없어 남긴 행 (%d)" % len(nulls))
        for code, mk, name, why in nulls:
            print("  %s [%s] %s | %s" % (code, mk, name[:60], why))

    if not apply:
        print("\n(dry-run: DB 무변경. 기록하려면 --apply)")
        return 0

    with engine.begin() as c:
        for code, val, state, srcs in writes:
            src = dict(srcs or {})
            src["cpu_gpu"] = ("igpu_source_text" if state == "text" else "igpu_model_rule")
            c.execute(text("""UPDATE product_specs
                                 SET cpu_gpu = :v, spec_sources = CAST(:s AS JSONB),
                                     updated_at = now()
                               WHERE product_code = :c AND cpu_gpu IS NULL"""),
                      {"v": val, "s": json.dumps(src, ensure_ascii=False), "c": code})
    print("\n[OK] wrote %d rows" % len(writes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
