# -*- coding: utf-8 -*-
"""완제PC 구성 파싱 — `products.spec_source_text` → JSON (2026-09-17)

■ 왜 이 도구인가
  팝콘PC 몰의 '완제PC' 상품 `spec_source_text` 에 **전체 부품 구성이 통째로** 들어 있다.
  실제 조립되어 판매 중인 구성이라 **호환성이 실물로 검증된 정답지**다.
  이 도구는 그 원문을 우리 슬롯 어휘(CPU/MB/RAM/GPU/SSD/HDD/CASE/POWER/COOLER)로
  읽어 JSON 으로 뽑는다.

■ 이 도구가 지키는 규칙
  1. **DB 를 쓰지 않는다.** 읽기 전용(SELECT)이고 산출물은 JSON 파일뿐이다.
  2. **값을 지어내지 않는다.** 원문에서 못 읽으면 그 필드는 `None`. 추론·짐작 금지.
  3. **`raw` 는 반드시 남긴다.** 파싱이 틀려도 원문으로 되짚을 수 있어야 한다.
  4. **미선택은 값 없음이다.** '...를 선택하세요.' 는 고객이 안 고른 옵션이지 부품이 아니다.
  5. **모르는 슬롯도 버리지 않는다.** 우리 어휘에 없는 슬롯은 `extras` 에 원문 그대로 남긴다.

■ 추론하지 않기로 한 것 (실측 후 판단)
  · POWER `rated_watt` ← 모델명 숫자(`FX500`, `TFX-500P`)를 와트로 읽지 **않는다.**
    실측 반례: `[AONE] TFX-500P KC [정격 250W]` — 모델명은 500 이지만 정격은 250W 다.
    `정격 NNNW` 또는 단독 `NNNW` 토큰만 취한다. 없으면 None.
  · SSD `form` ← 폼팩터 표기가 없는 제품(`870 EVO 250GB`)을 SATA 로 단정하지 않는다.
  · CPU `socket` ← 원문에 소켓 표기가 없다. 필드 자체를 만들지 않고 `series_hint` 만 둔다.
  · POWER `efficiency` ← `80+` 처럼 등급 없는 표기는 등급을 지어내지 않고 None.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console                    # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                                    # noqa: E402
from sqlalchemy import create_engine, text                        # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

SQL = """
SELECT product_code, product_name, sale_price, spec_source_text
  FROM products
 WHERE part_type = 'PC_COMPLETE'
   AND status = '판매중'
   AND spec_source_text IS NOT NULL
 ORDER BY product_code
"""

# 몰 슬롯명 -> 우리 part_type. 여기에 없는 슬롯은 extras 로 간다.
SLOT_MAP = {
    "프로세서(CPU)": "CPU",
    "메인보드": "MB",
    "메모리(RAM)": "RAM",
    "그래픽(VGA)": "GPU",
    "초고속(SSD)": "SSD",
    "대용량(HDD)": "HDD",
    "케이스": "CASE",
    "파워": "POWER",
    "CPU쿨러": "COOLER",
}

# 고객이 고르지 않은 옵션 = 값 없음
UNSELECTED = re.compile(r"선택하세요|선택안함|선택 안함|해당없음")

TAG = re.compile(r"<[^>]+>")
BRACKET = re.compile(r"\[([^\[\]]*)\]")

# 대괄호 안이 제조사가 아닌 것들 — 분류 태그·사양·판촉 문구
NOT_MAKER = re.compile(
    r"세대|지포스|라데온|초부팅|Turbo|정격|높이\s*:|크기\s*:|TDP|코어|쓰레드|보증|"
    r"회원가입|할인|한정|벌크|라이젠\s*AM|인텔\s*\d{3,4}|슬롯|메모리슬롯|"
    r"^\s*\d+\s*$|GHz|플랫케이블|모듈러|PCIE|x\s*\d+\s*$|G\s*x\s*\d",
    re.I,
)
# 판촉/유통 꼬리 — model 에서만 걷어낸다(raw 는 그대로 둔다)
PROMO_BRACKET = re.compile(r"\[[^\[\]]*(회원가입|할인|한정|현금|맞춤가|선착순)[^\[\]]*\]")
PROMO_TAIL = re.compile(
    r"(\s+(New\s+)?HIT\b|\s+NEW\b|\s+할인\s*-\s*[\d.]+%?|\s+낱장.*$|\s+무료.*$)", re.I
)
DISTRIBUTOR = re.compile(
    r"\s*[\[\(]?\s*(대원씨티에스|인텍앤컴퍼니|디앤디컴|피씨디렉트|제이씨현|에즈윈|"
    r"컴포인트|서린|대원|이엠텍)(\s*/\s*(대원씨티에스|인텍앤컴퍼니|디앤디컴|피씨디렉트|"
    r"제이씨현|에즈윈|컴포인트|서린|대원|이엠텍))*\s*[\]\)]?\s*$"
)
QTY = re.compile(r"\*\s*(\d+)\s*개")


def clean(s):
    """HTML 태그·특수문자·공백 정리. 원문 정제는 여기 한 곳에서만 한다."""
    if s is None:
        return ""
    s = TAG.sub("", s)
    s = (s.replace("\u2122", "").replace("\u00ae", "")
          .replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(",").strip()


def strip_promo(s):
    """model 계산용 — 판촉 문구·사양 대괄호·유통사 꼬리를 걷어낸다(raw 는 건드리지 않는다)."""
    s = PROMO_BRACKET.sub(" ", s)
    s = QTY.sub(" ", s)
    # 사양 설명 대괄호([Turbo 4.4GHz, ...], [정격 500W / ...], [높이:155mm])는 모델명이 아니다
    s = re.sub(r"\[([^\[\]]*)\]",
               lambda m: " " if not _is_maker(m.group(1).strip()) else m.group(0), s)
    prev = None
    while prev != s:
        prev = s
        s = PROMO_TAIL.sub("", s).strip()
        s = DISTRIBUTOR.sub("", s).strip()
    return re.sub(r"\s+", " ", s).strip(" /-,")


def _is_maker(inner):
    """대괄호 안이 제조사인가. `[AMD B550]`·`[인텔 Z790]` 은 칩셋 표기지 제조사가 아니다."""
    if not inner or NOT_MAKER.search(inner):
        return False
    if CHIPSET.search(inner) and re.search(r"AMD|인텔|INTEL", inner, re.I):
        return False
    return True


def pick_maker(val, lexicon):
    """제조사 — ① 앞머리 대괄호 ② 어휘에 있는 앞머리 단어. 둘 다 아니면 None."""
    rest = val
    # [삼성전자][삼성전자] 처럼 겹친 대괄호는 앞에서부터 훑는다
    while True:
        m = re.match(r"\s*\[([^\[\]]*)\]\s*", rest)
        if not m:
            break
        inner = m.group(1).strip()
        rest = rest[m.end():]
        if _is_maker(inner):
            return inner, rest
    # 대괄호가 없으면 어휘에 있는 앞머리 단어만 제조사로 인정한다
    for name in lexicon:
        if val.upper().startswith(name.upper() + " "):
            return name, val[len(name):].strip()
    return None, val


# ---- 슬롯별 세부 규칙 -------------------------------------------------------

CHIPSET = re.compile(r"\b((?:TRX|WRX)\d{2,3}|[ABCHQWXZ]\d{3})(?=[A-Z]{0,3}\d?\b|[-/])")


def f_mb(val, core):
    m = None
    for inner in BRACKET.findall(val):          # [AMD B550] / [인텔 Z790]
        c = CHIPSET.search(inner)
        if c:
            m = c.group(1)
            break
    if not m:                                    # 대괄호 밖 모델명에서 (B550M -> B550)
        c = CHIPSET.search(val)
        m = c.group(1) if c else None
    return {"chipset": m}


def f_ram(val, core):
    t = re.search(r"\bDDR([345])\b", val)
    # 규격 토큰(PC4-25600, DDR5-5600, CL46)은 용량 오인 소지가 있어 먼저 제거
    s = re.sub(r"PC\d-\d+|DDR\d-\d+|CL\d+(-\d+)*", " ", val)
    cap = re.search(r"(\d+)\s*G(?:B)?\b", s)
    st = re.search(r"(\d+)\s*G\s*(?:B)?\s*[xX*]\s*(\d+)", val)
    if not st:
        st = re.search(r"[xX]\s*(\d+)\s*\)", val)
        sticks = int(st.group(1)) if st else None
    else:
        sticks = int(st.group(2))
    return {
        "mem_type": ("DDR" + t.group(1)) if t else None,
        "capacity_gb": int(cap.group(1)) if cap else None,
        "sticks": sticks,
    }


GPU_CHIP = re.compile(
    r"\b(RTX\s*PRO\s*\d{4}|RTX\s*A\d{4}|RTX\s*\d{3,4}\s*(?:Ti\s*SUPER|Ti|SUPER)?|"
    r"GTX\s*\d{3,4}\s*(?:Ti|SUPER)?|RX\s*\d{3,4}\s*(?:XTX|XT|GRE)?|"
    r"H\d{3}\s*(?:NVL|SXM|PCIe)?|Arc\s*[AB]\d{3}|UHD\s*Graphics|"
    r"Radeon\s*Graphics|(?:Intel\s*)?(?:Iris\s*)?Xe\s*Graphics)\b", re.I)


def f_gpu(val, core):
    m = GPU_CHIP.search(val)
    return {"chip": re.sub(r"\s+", " ", m.group(1)).strip() if m else None}


def _cap_gb(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB)\b", s, re.I)
    if not m:
        return None
    n = float(m.group(1))
    return int(n * 1024) if m.group(2).upper() == "TB" else int(n)


def f_ssd(val, core):
    forms = []
    if re.search(r"\bM\.?2\b", val, re.I):
        forms.append("M.2")
    if re.search(r"\bNVMe\b", val, re.I):
        forms.append("NVMe")
    if re.search(r"\bSATA\b", val, re.I):
        forms.append("SATA")
    return {"capacity_gb": _cap_gb(val), "form": " ".join(forms) or None}


def f_hdd(val, core):
    return {"capacity_gb": _cap_gb(val),
            "rpm": (lambda m: int(m.group(1)) if m else None)(
                re.search(r"\b(5400|5640|7200|10000)\b", val))}


EFF = re.compile(
    r"(80\s*\+?\s*PLUS|ETA)\s*-?\s*(STANDARD|BRONZE|SILVER|GOLD|PLATINUM|TITANIUM|"
    r"스탠다드|브론즈|실버|골드|플래티넘|티타늄)", re.I)
EFF_KO = {"스탠다드": "STANDARD", "브론즈": "BRONZE", "실버": "SILVER",
          "골드": "GOLD", "플래티넘": "PLATINUM", "티타늄": "TITANIUM"}


def f_power(val, core):
    # ① '정격 NNNW' 가 최우선 — 모델명 숫자와 어긋나는 실물 사례가 있다
    m = re.search(r"정격\s*(\d{2,4})\s*W", val, re.I)
    if not m:
        # ② 단독 와트 토큰. 모델코드에 붙은 숫자(FX500, SF-700R12ST)는 취하지 않는다
        m = re.search(r"(?<![A-Za-z0-9\-])(\d{3,4})\s*W\b", val, re.I)
    e = EFF.search(val)
    grade = None
    if e:
        g = e.group(2)
        # ETA 는 80PLUS 와 다른 인증 체계다 — 같은 등급으로 뭉뚱그리지 않고 그대로 표기
        scheme = "ETA" if e.group(1).upper() == "ETA" else "80PLUS"
        grade = scheme + " " + EFF_KO.get(g, g.upper())
    return {"rated_watt": int(m.group(1)) if m else None,
            "efficiency": grade}


SIZE = re.compile(r"(빅타워|미들\s*타워|미들타워|미니\s*타워|미니타워|미니\s*ITX|"
                  r"미니ITX|슬림형|슬림)")


def f_case(val, core):
    m = SIZE.search(val)
    return {"size_hint": re.sub(r"\s+", "", m.group(1)) if m else None}


def f_cpu(val, core):
    # series_hint = 제조사/사양 대괄호/판촉을 걷어낸 핵심 문자열
    s = re.sub(r"\[[^\[\]]*\]", " ", core)
    s = re.sub(r"\((?:멀티팩|정품|박스|벌크)[^)]*\)", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,/-")
    return {"series_hint": s or None}


FIELDERS = {"CPU": f_cpu, "MB": f_mb, "RAM": f_ram, "GPU": f_gpu, "SSD": f_ssd,
            "HDD": f_hdd, "CASE": f_case, "POWER": f_power, "COOLER": None}


def parse_part(pt, val, lexicon):
    maker, rest = pick_maker(val, lexicon)
    core = strip_promo(rest)
    q = QTY.search(val)
    out = {"raw": val, "maker": maker, "model": core or None,
           "qty": int(q.group(1)) if q else None}
    fn = FIELDERS.get(pt)
    if fn:
        out.update(fn(val, core))
    return out


def split_items(spec):
    """',@@' 로 항목을 나누고 '슬롯명@@값' 으로 쪼갠다. 슬롯명에도 <br> 이 섞여 있다."""
    for chunk in spec.split(",@@"):
        if "@@" not in chunk:
            continue
        slot, val = chunk.split("@@", 1)
        slot, val = clean(slot), clean(val)
        if not slot:
            continue
        yield slot, val


def build_lexicon(rows):
    """제조사 어휘를 데이터에서 만든다 — 사람이 지어낸 목록이 아니라 원문에 실제로
    대괄호로 표기된 이름만 모은다(대괄호 없는 표기를 인정하기 위한 근거)."""
    c = Counter()
    for r in rows:
        for _slot, val in split_items(r["spec_source_text"] or ""):
            if UNSELECTED.search(val):
                continue
            m = re.match(r"\s*\[([^\[\]]*)\]", val)
            if m:
                inner = m.group(1).strip()
                if _is_maker(inner) and len(inner) >= 2:
                    c[inner] += 1
    # 긴 이름부터 맞춰야 'WD' 가 'WD Blue' 를 먹지 않는다
    return sorted([k for k, v in c.items() if v >= 2], key=len, reverse=True)


def main():
    ap = argparse.ArgumentParser(description="완제PC spec_source_text 구성 파서(읽기 전용)")
    ap.add_argument("--out", help="산출 JSON 경로")
    ap.add_argument("--limit", type=int, help="시험용 — 앞에서 N건만")
    ap.add_argument("--code", help="한 건만 파싱해서 화면에 출력")
    args = ap.parse_args()

    try:
        engine = create_engine(os.environ["DATABASE_URL"])
        with engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(text(SQL))]
    except KeyError:
        print("DATABASE_URL 이 없습니다(.env 확인).", file=sys.stderr)
        return 2
    except Exception:
        # DB 예외 원문에는 접속 문자열(비밀번호 포함)이 실린다 — 절대 그대로 내지 않는다
        print("DB 조회에 실패했습니다. .env 의 DATABASE_URL 과 네트워크를 확인하세요.",
              file=sys.stderr)
        return 2

    if args.code:
        rows = [r for r in rows if str(r["product_code"]) == str(args.code)]
    lexicon = build_lexicon(rows)

    result, stats, field_stats, skipped = [], Counter(), defaultdict(Counter), 0
    for r in rows:
        spec = r["spec_source_text"] or ""
        if ",@@" not in spec:
            skipped += 1
            continue
        parts, extras, unparsed = {}, {}, []
        for slot, val in split_items(spec):
            if not val or UNSELECTED.search(val):
                continue                     # 미선택 = 값 없음
            pt = SLOT_MAP.get(slot)
            if pt:
                if pt in parts:              # 같은 슬롯이 두 번 — 덮지 않고 남긴다
                    unparsed.append({"slot": slot, "raw": val,
                                     "why": "중복 슬롯"})
                    continue
                parts[pt] = parse_part(pt, val, lexicon)
                stats[pt] += 1
                for k, v in parts[pt].items():
                    if k in ("raw",):
                        continue
                    field_stats[pt][k] += 1 if v is not None else 0
            else:
                extras.setdefault(slot, []).append(val)
        result.append({
            "product_code": r["product_code"],
            "product_name": r["product_name"],
            "sale_price": int(r["sale_price"]) if r["sale_price"] is not None else None,
            "parts": parts,
            "extras": {k: (v[0] if len(v) == 1 else v) for k, v in extras.items()},
            "unparsed": unparsed,
        })
        if args.limit and len(result) >= args.limit:
            break

    if args.code:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    n = len(result)
    print(f"파싱 대상 {n}건 (',@@' 구조 없음으로 건너뜀: {skipped}건)")
    print("\n[슬롯별 보유율]")
    for pt in ["CPU", "MB", "RAM", "GPU", "SSD", "HDD", "CASE", "POWER", "COOLER"]:
        c = stats[pt]
        print(f"  {pt:<7} {c:>4}/{n}  {c / n * 100:5.1f}%" if n else f"  {pt} 0")
    print("\n[필드별 추출률] (분모 = 해당 슬롯 보유 건수)")
    for pt in ["CPU", "MB", "RAM", "GPU", "SSD", "HDD", "CASE", "POWER", "COOLER"]:
        d = stats[pt]
        if not d:
            continue
        fs = ", ".join(f"{k} {v}/{d}({v / d * 100:.0f}%)"
                       for k, v in field_stats[pt].items())
        print(f"  {pt:<7} {fs}")

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(f"\n저장: {args.out} ({n}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
