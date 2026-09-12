"""GPU VRAM(vram_gb) / CPU 코어 수(cpu_cores) 상품명 파싱 채움 — 2026-09-11 신설 필드 백필.

출처: CPU 코어 수 룩업 사전은 **제조사 공식 사양**(Intel ARK / AMD 제품 사양 페이지) 기준의
공개 수치를 옮긴 것이다. 인텔 하이브리드(P+E) 는 **총 코어 수**(예: i5-14600K = 6P+8E = 14).
확실히 아는 모델만 적었다 — 사전에 없는 모델은 NULL 로 남긴다(값을 지어내지 않는다).

GPU VRAM 은 상품명에서만 읽는다:
  1) 'D6/D6X/D7/GDDR6/GDDR7 ... NNGB' 처럼 메모리 규격 뒤에 오는 GB 를 우선
  2) 없으면 상품명의 마지막 'NNGB'
  3) 칩셋별 상식표(RTX 5090=32 등)와 어긋나면 **채우지 않고** 이상치로 보고한다
  4) GB 표기가 없으면 NULL (상식표로 추정하지 않는다)

반영 규칙: product_specs 의 해당 컬럼이 NULL 인 행만 UPDATE (COALESCE — 기존 값을 덮지 않음).
필드별 출처는 spec_sources JSONB 에 {"vram_gb": "name_parse"} 로 남긴다
(extract_source 는 행 단위 적재 경로(csv/rule/ai_text) 의미라 건드리지 않는다).

사용:
  .venv/Scripts/python tools/backfill_gpu_cpu_specs.py               # dry-run, 재고(판매중·stock>0) 범위
  .venv/Scripts/python tools/backfill_gpu_cpu_specs.py --scope all   # dry-run, 전체
  .venv/Scripts/python tools/backfill_gpu_cpu_specs.py --apply       # 실제 UPDATE
로그 문자열은 ASCII 만 쓴다(Windows 콘솔 cp949 깨짐 방지).
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from sqlalchemy import text  # noqa: E402

from api.db import engine  # noqa: E402

# ---------------------------------------------------------------------------
# CPU 코어 수 사전 — 모델 토큰 -> 총 코어 수. 패밀리별로 나눠 오검출을 막는다
# (인텔 코어 울트라 '245K' 같은 3자리 토큰은 '울트라' 문맥에서만 찾는다).
# ---------------------------------------------------------------------------
INTEL_CORE = {
    # 14th (Raptor Lake Refresh)
    "14900KS": 24, "14900K": 24, "14900KF": 24, "14900F": 24, "14900": 24,
    "14700K": 20, "14700KF": 20, "14700F": 20, "14700": 20,
    "14600K": 14, "14600KF": 14, "14600": 14, "14500": 14,
    "14400": 10, "14400F": 10, "14100": 4, "14100F": 4,
    # 13th (Raptor Lake)
    "13900KS": 24, "13900K": 24, "13900KF": 24, "13900F": 24, "13900": 24,
    "13700K": 16, "13700KF": 16, "13700F": 16, "13700": 16,
    "13600K": 14, "13600KF": 14, "13600": 14, "13500": 14,
    "13400": 10, "13400F": 10, "13100": 4, "13100F": 4,
    # 12th (Alder Lake)
    "12900KS": 16, "12900K": 16, "12900KF": 16, "12900F": 16, "12900": 16,
    "12700K": 12, "12700KF": 12, "12700F": 12, "12700": 12,
    "12600K": 10, "12600KF": 10, "12600": 6, "12500": 6,
    "12400": 6, "12400F": 6, "12100": 4, "12100F": 4,
    # 11th (Rocket Lake)
    "11900K": 8, "11900KF": 8, "11900F": 8, "11900": 8, "11700K": 8, "11700KF": 8, "11700F": 8, "11700": 8,
    "11600K": 6, "11600KF": 6, "11600": 6, "11500": 6, "11400": 6, "11400F": 6,
    # 10th (Comet Lake)
    "10900K": 10, "10900KF": 10, "10900F": 10, "10900": 10, "10850K": 10,
    "10700K": 8, "10700KF": 8, "10700": 8, "10700F": 8,
    "10600K": 6, "10600KF": 6, "10600": 6, "10500": 6, "10400": 6, "10400F": 6,
    "10105": 4, "10105F": 4, "10100": 4, "10100F": 4,
    # 9th (Coffee Lake-R)
    "9900KS": 8, "9900K": 8, "9900KF": 8, "9900": 8, "9700K": 8, "9700KF": 8, "9700F": 8, "9700": 8,
    "9600K": 6, "9600KF": 6, "9500": 6, "9500F": 6, "9400": 6, "9400F": 6, "9100": 4, "9100F": 4,
    # 8th (Coffee Lake)
    "8700K": 6, "8700": 6, "8086K": 6, "8600K": 6, "8600": 6, "8500": 6, "8400": 6,
    "8350K": 4, "8300": 4, "8100": 4,
    # 7th/6th (Kaby Lake / Skylake)
    "7700K": 4, "7700": 4, "7600K": 4, "7500": 4, "7400": 4, "7100": 2,
    "6700K": 4, "6700": 4, "6600K": 4, "6600": 4, "6500": 4, "6400": 4, "6100": 2,
    # Core X (HEDT)
    "10980XE": 18, "10940X": 14, "10920X": 12, "10900X": 10,
    "9980XE": 18, "9960X": 16, "9940X": 14, "9920X": 12, "9900X": 10, "9820X": 10, "9800X": 8,
    "7980XE": 18, "7960X": 16, "7940X": 14, "7920X": 12, "7900X": 10, "7820X": 8, "7800X": 6, "7740X": 4, "7640X": 4,
}
INTEL_XEON = {  # Xeon Scalable(2nd/3rd gen) / E3 — 자주 보이는 것만
    "4310": 12, "4314": 16, "4316": 20, "4309Y": 8,
    "6242R": 20, "6246R": 16, "6248R": 24, "6226R": 16, "5218R": 20, "4214R": 12, "4210R": 10,
    "1275V6": 4, "1245V6": 4, "1230V6": 4, "1225V6": 4, "1270V6": 4,
    "2224": 4, "2234": 4, "2236": 6, "2244": 4, "2246": 6, "2278": 8, "2288": 8,
}
AMD_ATHLON = {"3000G": 2, "200GE": 2, "220GE": 2, "240GE": 2}
INTEL_ULTRA = {  # Core Ultra Series 2 (Arrow Lake-S) — desktop
    "285K": 24, "285": 24, "265K": 20, "265KF": 20, "265": 20, "265F": 20,
    "245K": 14, "245KF": 14, "245": 14, "235": 14, "225": 10, "225F": 10,
    # 'Plus'(Arrow Lake Refresh) 250K/270K 등은 공식 사양 확인 전 — 비워 둠
}
INTEL_LOWEND = {  # Celeron / Pentium Gold
    "G5900": 2, "G5905": 2, "G5920": 2, "G5925": 2, "G6900": 2, "G5400": 2, "G5420": 2,
    "G6400": 2, "G6405": 2, "G6500": 2, "G6600": 2, "G7400": 2, "G4900": 2, "G4930": 2,
    "G4560": 2, "G4600": 2, "G4620": 2, "G3900": 2, "G3930": 2, "G3950": 2,
    "G1820": 2, "G1840": 2, "G1850": 2,
}
AMD_RYZEN = {
    # 9000 (Granite Ridge)
    "9950X3D": 16, "9950X": 16, "9900X3D": 12, "9900X": 12,
    "9800X3D": 8, "9700X": 8, "9600X": 6, "9600": 6, "9500F": 6,
    # 8000G/F (Phoenix)
    "8700G": 8, "8700F": 8, "8600G": 6, "8500G": 6, "8400F": 6, "8300G": 4,
    # 7000 (Raphael)
    "7950X3D": 16, "7950X": 16, "7900X3D": 12, "7900X": 12, "7900": 12,
    "7800X3D": 8, "7700X": 8, "7700": 8, "7600X3D": 6, "7600X": 6, "7600": 6,
    "7500F": 6, "7400F": 6,
    # 5000 (Vermeer / Cezanne)
    "5950X": 16, "5900X": 12, "5900XT": 16, "5800X3D": 8, "5800X": 8, "5800XT": 8, "5800": 8,
    "5700X3D": 8, "5700X": 8, "5700G": 8, "5700": 8,
    "5600X3D": 6, "5600X": 6, "5600XT": 6, "5600": 6, "5600G": 6, "5600GT": 6,
    "5500": 6, "5500GT": 6, "5300G": 4,
    # 4000 (Renoir)
    "4700G": 8, "4600G": 6, "4500": 6, "4300G": 4, "4100": 4,
    # 3000 (Matisse / Picasso)
    "3950X": 16, "3900X": 12, "3900XT": 12, "3800X": 8, "3800XT": 8, "3700X": 8,
    "3600X": 6, "3600XT": 6, "3600": 6, "3400G": 4, "3300X": 4, "3200G": 4, "3100": 4,
    # 2000 (Pinnacle Ridge / Raven Ridge) · 1000 (Summit Ridge)
    "2700X": 8, "2700": 8, "2600X": 6, "2600": 6, "2400G": 4, "2200G": 4,
    "1800X": 8, "1700X": 8, "1700": 8, "1600X": 6, "1600": 6, "1500X": 4, "1400": 4, "1300X": 4, "1200": 4,
}
AMD_THREADRIPPER = {
    # 9000 (Shimada Peak)
    "9980X": 64, "9970X": 32, "9960X": 24,
    "9995WX": 96, "9985WX": 64, "9975WX": 32, "9965WX": 24, "9955WX": 16, "9945WX": 12,
    # 7000 (Storm Peak)
    "7980X": 64, "7970X": 32, "7960X": 24,
    "7995WX": 96, "7985WX": 64, "7975WX": 32, "7965WX": 24, "7955WX": 16, "7945WX": 12,
    # 5000 PRO (Chagall)
    "5995WX": 64, "5975WX": 32, "5965WX": 24, "5955WX": 16, "5945WX": 12,
    # 3000 (Castle Peak)
    "3990X": 64, "3970X": 32, "3960X": 24,
    "3995WX": 64, "3975WX": 32, "3955WX": 16, "3945WX": 12,
    # 2000 (Colfax) · 1000 (Whitehaven)
    "2990WX": 32, "2970WX": 24, "2950X": 16, "2920X": 12, "1950X": 16, "1920X": 12, "1900X": 8,
}
AMD_EPYC = {  # EPYC 4004 (AM5) + 7003 (Milan) 자주 보이는 것
    "4124P": 4, "4244P": 6, "4344P": 8, "4364P": 8, "4464P": 12, "4484PX": 12,
    "4564P": 16, "4584PX": 16,
    "7313": 16, "7313P": 16, "7343": 16, "7413": 24, "7443": 24, "7443P": 24,
    "7453": 28, "7513": 32, "7543": 32, "7543P": 32, "7643": 48, "7713": 64, "7713P": 64, "7763": 64,
}

_TOKEN = re.compile(r"(?<![A-Z0-9])([A-Z]?\d{3,5}[A-Z]{0,3}\d?[A-Z]?)(?![A-Z0-9])")


def cpu_cores_from_name(name: str) -> tuple[int | None, str]:
    """(코어 수, 사유). 패밀리 문맥을 먼저 정하고 그 사전에서만 찾는다."""
    n = name.upper()
    families = [
        (lambda: "스레드리퍼" in name or "THREADRIPPER" in n, AMD_THREADRIPPER, "threadripper"),
        (lambda: "EPYC" in n, AMD_EPYC, "epyc"),
        (lambda: "애슬론" in name or "ATHLON" in n, AMD_ATHLON, "athlon"),
        (lambda: "라이젠" in name or "RYZEN" in n, AMD_RYZEN, "ryzen"),
        (lambda: "제온" in name or "XEON" in n, INTEL_XEON, "xeon"),
        (lambda: "울트라" in name or "ULTRA" in n, INTEL_ULTRA, "core_ultra"),
        (lambda: "셀러론" in name or "펜티엄" in name or "CELERON" in n or "PENTIUM" in n,
         INTEL_LOWEND, "intel_lowend"),
        (lambda: "코어" in name or re.search(r"\bI[3579]\b|I[3579]-", n), INTEL_CORE, "intel_core"),
    ]
    tokens = _TOKEN.findall(n)
    for test, table, fam in families:
        if test():
            break
    else:
        # 패밀리 단어가 없는 이름('9950X TRAY ...') — 모든 사전을 뒤져 **정확히 한 사전**에서만
        # 걸리고 값이 하나일 때만 받는다. 겹치면(인텔 7700 vs 라이젠 7700) NULL.
        hits = [(t, tb[t], nm) for _, tb, nm in families for t in tokens if t in tb]
        if not hits:
            return None, f"no_family:{'/'.join(tokens[:4])}"
        if len({nm for _, _, nm in hits}) > 1 or len({v for _, v, _ in hits}) > 1:
            return None, f"ambiguous_family:{hits}"
        return hits[0][1], f"fallback:{hits[0][2]}:{hits[0][0]}"
    hits = [(t, table[t]) for t in tokens if t in table]
    if not hits:
        return None, f"no_model:{fam}:{'/'.join(tokens[:4])}"
    if len({v for _, v in hits}) > 1:
        return None, f"ambiguous:{fam}:{hits}"
    return hits[0][1], f"model:{hits[0][0]}"


# ---------------------------------------------------------------------------
# GPU VRAM 파싱 + 칩셋 상식표
# ---------------------------------------------------------------------------
_GB_AFTER_MEM = re.compile(r"(?:GDDR\d\s*X?|\bD\d\s*X?)\s*(\d{1,3})\s*GB\b", re.I)
_GB_ANY = re.compile(r"(\d{1,3})\s*GB\b", re.I)

# 칩셋 -> 허용 VRAM 집합. 패턴은 길고 구체적인 것부터 (5060 Ti 가 5060 보다 먼저).
GPU_SANITY = [
    (r"RTX\s*PRO\s*6000", {96}), (r"RTX\s*PRO\s*5000", {48, 72}), (r"RTX\s*PRO\s*4500", {32}),
    (r"RTX\s*PRO\s*4000", {24}), (r"RTX\s*PRO\s*2000", {16}), (r"RTX\s*PRO\s*1000", {8}),
    (r"\bH200\b", {141}), (r"\bH100\s*NVL\b", {94}), (r"\bH100\b", {80, 94}), (r"\bL40S?\b", {48}), (r"\bL4\b", {24}),
    (r"\bA100\b", {40, 80}), (r"\bA40\b", {48}), (r"\bA30\b", {24}), (r"\bA10\b", {24}), (r"\bA16\b", {64}), (r"\bA2\b", {16}),
    (r"RTX\s*A5500", {24}), (r"\bT1000\b", {4, 8}), (r"\bT600\b", {4}), (r"\bT400\b", {2, 4}),
    (r"AI\s*PRO\s*R9700", {32}), (r"PRO\s*W7900", {48}), (r"PRO\s*W7800", {32, 48}), (r"PRO\s*W7700", {16}),
    (r"PRO\s*W7600", {8}), (r"PRO\s*W7500", {8}), (r"PRO\s*W6800", {32}), (r"PRO\s*W6600", {8}), (r"PRO\s*W6400", {4}),
    (r"라데온\s*VII\b", {16}), (r"RX\s*9060\s*XT", {8, 16}), (r"RX\s*9060\b", {8}), (r"ARC\s*A580", {8}),
    (r"RTX\s*6000\s*ADA", {48}), (r"RTX\s*5000\s*ADA", {32}), (r"RTX\s*4500\s*ADA", {24}),
    (r"RTX\s*4000\s*(?:SFF\s*)?ADA", {20}), (r"RTX\s*2000\s*(?:E\s*)?ADA", {16}),
    (r"RTX\s*A6000", {48}), (r"RTX\s*A5000", {24}), (r"RTX\s*A4500", {20}), (r"RTX\s*A4000", {16}),
    (r"RTX\s*A2000", {6, 12}), (r"RTX\s*A1000", {8}), (r"RTX\s*A400", {4}),
    (r"RTX\s*5090", {32}), (r"RTX\s*5080", {16}), (r"RTX\s*5070\s*TI", {16}), (r"RTX\s*5070", {12}),
    (r"RTX\s*5060\s*TI", {8, 16}), (r"RTX\s*5060", {8}), (r"RTX\s*5050", {8}),
    (r"RTX\s*4090\s*D", {24}), (r"RTX\s*4090", {24}), (r"RTX\s*4080\s*SUPER", {16}), (r"RTX\s*4080", {16}),
    (r"RTX\s*4070\s*TI\s*SUPER", {16}), (r"RTX\s*4070\s*TI", {12}), (r"RTX\s*4070\s*SUPER", {12}),
    (r"RTX\s*4070", {12}), (r"RTX\s*4060\s*TI", {8, 16}), (r"RTX\s*4060", {8}),
    (r"RTX\s*3090\s*TI", {24}), (r"RTX\s*3090", {24}), (r"RTX\s*3080\s*TI", {12}), (r"RTX\s*3080", {10, 12}),
    (r"RTX\s*3070\s*TI", {8}), (r"RTX\s*3070", {8}), (r"RTX\s*3060\s*TI", {8}), (r"RTX\s*3060", {8, 12}),
    (r"RTX\s*3050", {4, 6, 8}),
    (r"RTX\s*2080\s*TI", {11}), (r"RTX\s*2080", {8}), (r"RTX\s*2070", {8}),
    (r"RTX\s*2060\s*SUPER", {8}), (r"RTX\s*2060", {6, 12}),
    (r"GTX\s*1660", {6}), (r"GTX\s*1650", {4}), (r"GTX\s*1630", {4}),
    (r"GTX\s*1080\s*TI", {11}), (r"GTX\s*1080", {8}), (r"GTX\s*1070", {8}), (r"GTX\s*1060", {3, 6}),
    (r"GTX\s*1050\s*TI", {4}), (r"GTX\s*1050", {2, 3}),
    (r"GT\s*1030", {2, 4}), (r"GT\s*730", {1, 2, 4}), (r"GT\s*710", {1, 2}), (r"\bG210\b", set()),
    (r"RX\s*9070\s*GRE", {12}), (r"RX\s*9070\s*XT", {16}), (r"RX\s*9070", {16}), (r"RX\s*9060\s*XT", {8, 16}),
    (r"RX\s*7900\s*XTX", {24}), (r"RX\s*7900\s*XT", {20}), (r"RX\s*7900\s*GRE", {16}),
    (r"RX\s*7800\s*XT", {16}), (r"RX\s*7700\s*XT", {12}), (r"RX\s*7600\s*XT", {16}), (r"RX\s*7600", {8}),
    (r"RX\s*6950\s*XT", {16}), (r"RX\s*6900\s*XT", {16}), (r"RX\s*6800", {16}),
    (r"RX\s*6750\s*XT", {12}), (r"RX\s*6700\s*XT", {12}), (r"RX\s*6700", {10}),
    (r"RX\s*6650\s*XT", {8}), (r"RX\s*6600", {8}), (r"RX\s*6500\s*XT", {4, 8}), (r"RX\s*6400", {4}),
    (r"RX\s*5700\s*XT", {8}), (r"RX\s*5700\b", {8}), (r"RX\s*5600\s*XT", {6}), (r"RX\s*5500\s*XT", {4, 8}),
    (r"RX\s*590\b", {8}), (r"RX\s*580\b", {4, 8}), (r"RX\s*570\b", {4, 8}), (r"RX\s*560\b", {2, 4}), (r"RX\s*550\b", {2, 4}),
    (r"ARC\s*B580", {12}), (r"ARC\s*B570", {10}), (r"ARC\s*A770", {8, 16}), (r"ARC\s*A750", {8}),
    (r"ARC\s*A380", {6}), (r"ARC\s*A310", {4}),
]


def gpu_vram_from_name(name: str) -> tuple[int | None, str]:
    """(VRAM GB, 사유). 값이 상식표와 어긋나면 None + 'anomaly:...'."""
    n = name.upper()
    m = _GB_AFTER_MEM.search(n)
    src = "mem_tag"
    if m:
        gb = int(m.group(1))
    else:
        alls = _GB_ANY.findall(n)
        if not alls:
            return None, "no_gb"
        gb, src = int(alls[-1]), "last_gb"
    for pat, allowed in GPU_SANITY:
        if re.search(pat, n):
            if allowed and gb not in allowed:
                return None, f"anomaly:{pat}:{gb}:allowed={sorted(allowed)}"
            return gb, f"{src}:{pat}"
    # 상식표에 없는 칩셋: 메모리 규격 태그(D6 8GB) 뒤의 값만 믿는다. 태그 없이 'NNGB' 만 있는
    # 이름은 완제품 RAM·SSD 용량일 수 있어(예: '(5600X/3060/NVMe 512GB/16GB)') 채우지 않는다.
    if src != "mem_tag":
        return None, f"unknown_chip_no_mem_tag:{gb}"
    return gb, f"{src}:unknown_chip"


# ---------------------------------------------------------------------------
def run(scope: str, apply: bool) -> None:
    where = "p.part_type = :pt"
    if scope == "live":
        where += " AND p.status = '판매중' AND p.stock_qty > 0"
    sql_sel = text(
        "SELECT p.product_code, p.product_name, s.{col} AS cur"
        " FROM products p JOIN product_specs s USING (product_code)"
        f" WHERE {where} ORDER BY p.product_code")
    sql_upd = {
        "vram_gb": text(
            "UPDATE product_specs SET vram_gb = COALESCE(vram_gb, :v),"
            " spec_sources = COALESCE(spec_sources, '{}'::jsonb) || '{\"vram_gb\": \"name_parse\"}'::jsonb,"
            " updated_at = now() WHERE product_code = :c AND vram_gb IS NULL"),
        "cpu_cores": text(
            "UPDATE product_specs SET cpu_cores = COALESCE(cpu_cores, :v),"
            " spec_sources = COALESCE(spec_sources, '{}'::jsonb) || '{\"cpu_cores\": \"name_parse\"}'::jsonb,"
            " updated_at = now() WHERE product_code = :c AND cpu_cores IS NULL"),
    }
    jobs = [("GPU", "vram_gb", gpu_vram_from_name), ("CPU", "cpu_cores", cpu_cores_from_name)]
    summary = {}
    with engine.begin() as conn:
        for pt, col, fn in jobs:
            rows = conn.execute(text(str(sql_sel).format(col=col)), {"pt": pt}).all()
            stats = {"total": len(rows), "already": 0, "filled": 0, "null": 0, "anomaly": 0}
            blocked, anomalies = [], []
            for code, name, cur in rows:
                if cur is not None:
                    stats["already"] += 1
                    continue
                val, why = fn(name or "")
                if val is None:
                    if why.startswith("anomaly"):
                        stats["anomaly"] += 1
                        anomalies.append((code, name, why))
                    else:
                        stats["null"] += 1
                        blocked.append((code, name, why))
                    continue
                stats["filled"] += 1
                if apply:
                    conn.execute(sql_upd[col], {"v": val, "c": code})
            summary[col] = {"stats": stats, "blocked": blocked, "anomalies": anomalies}
            print(f"[{col}] scope={scope} apply={apply} {json.dumps(stats)}")
            for code, name, why in anomalies:
                print(f"  ANOMALY {code} {why} :: {name}".encode("ascii", "backslashreplace").decode())
            # 막힌 사유 집계(모델 토큰 미등록 등)
            from collections import Counter
            cnt = Counter(w.split(":")[0] + ":" + (w.split(":")[1] if ":" in w else "") for _, _, w in blocked)
            print("  blocked_by_reason:", dict(cnt))
    out = os.path.join(ROOT, "docs", "reports", f"backfill_gpu_cpu_specs_{scope}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1, default=list)
    print("report:", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["live", "all"], default="live")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    run(a.scope, a.apply)
