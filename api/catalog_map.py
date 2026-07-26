"""카탈로그 적재 매핑 규칙 — 실파일(24,303행 · 사양 EAV 339,650행) 실측 기반 (슬라이스 39).

**원천의 형태**(실측):
  · products 축약본(db_products.csv)은 다나와No·공급처·모델명을 잃었으므로 **원본 32컬럼을
    마스터로** 쓰고, 사양은 EAV(db_product_specs.csv)를 결합한다.
  · EAV의 60%(203,467행)가 `특성` 키에 값만 들어 있다 — 소켓·DDR·폼팩터·용량은
    **키가 아니라 값 패턴**으로 뽑아야 한다.
  · 그래서 추출은 3계층이다: ① EAV 키 직결 ② `특성` 값 패턴 ③ 상품명 유도.
    어느 계층에서 왔는지를 `spec_sources`에 남긴다 — 근거가 창작이 아니라 사실이 되게.

**정직 원칙**: 유도하지 못한 필수 사양은 채우지 않고 검수 큐로 보낸다. 값을 지어내면
추천이 "조립 가능"이라고 말하는 근거가 무너진다.
"""
import re

# ─────────────────────────── part_type 매핑 ───────────────────────────
# 실측 category_l1 > l2 조합 122종 중 취급 대상만 매핑한다.
# category_group: 'core_part'(추천 슬롯 — 뷰 게이트가 이 값을 요구) / 'peripheral' / 'etc'
CORE_L2 = {
    "프로세서(CPU)": "CPU",
    "메인보드(M/B)": "MB",
    "메모리(RAM)": "RAM",
    "그래픽카드(VGA)": "GPU",
    "파워(POWER)": "POWER",
    "케이스(CASE)": "CASE",
    "고속저장(SSD)": "SSD",
    "저장장치(HDD)": "HDD",
}
PERIPH_L2 = {
    "키보드": "KEYBOARD",
    "마우스": "MOUSE",
    "헤드셋＊이어폰": "HEADSET",
    "스피커": "SPEAKER",
}
MONITOR_L2 = {"27인치 모니터", "24인치 모니터", "32인치 이상", "23인치 이하"}

# 적재하지 않는 분류 — 취급 상품이 아니다(운영 흔적·삭제 대기·결제용 더미)
SKIP_L1 = {"삭제대기", "내부관리용", "고객님 개인결제"}


def map_part_type(l1: str, l2: str, l3: str, name: str):
    """(part_type, category_group, skip_reason) — 매핑 못 해도 카탈로그에는 넣는다.

    part_type을 못 정한 상품은 `category_group='etc'`로 적재된다: 추천 대상이 아니지만
    재고·가격 관리 대상이기 때문이다(시스템 쿨러·튜닝용품·완제품PC·케이블 등).
    """
    l1, l2, l3 = (l1 or "").strip(), (l2 or "").strip(), (l3 or "").strip()
    if l1 in SKIP_L1:
        return None, None, f"{l1} 분류"
    if l2 in CORE_L2:
        return CORE_L2[l2], "core_part", None
    if l2 == "CPU쿨러":
        # 실측: l3가 공랭쿨러 314 / 수냉쿨러 239로 갈린다(빈값 2건은 검수)
        if "수냉" in l3 or "수랭" in l3:
            return "COOLER_CPU_AIO", "core_part", None
        if "공랭" in l3:
            return "COOLER_CPU_AIR", "core_part", None
        return None, "etc", "쿨러 냉각 방식 미분류(공랭/수냉)"
    if l1 == "모니터" and l2 in MONITOR_L2:
        return "MONITOR", "peripheral", None
    if l2 in PERIPH_L2:
        return PERIPH_L2[l2], "peripheral", None
    if l2 == "마이크/웹캠":
        # 마이크와 웹캠이 한 분류에 섞여 있다 — 상품명으로만 갈린다
        return ("WEBCAM", "peripheral", None) if re.search(r"웹캠|캠|WEBCAM", name, re.I) \
            else (None, "etc", "마이크/웹캠 혼재 — 상품명으로 구분 불가")
    return None, "etc", None


# ─────────────────────────── 값 패턴 ───────────────────────────
SOCKET = re.compile(r"^(LGA\s?\d{3,4}[A-Za-z]?|LGA115\(X\)|AM4|AM5|sTRX4|TR4|LGA2011(?:-V3)?|LGA2066)$", re.I)
MEM_TYPE = re.compile(r"^(DDR[345])$", re.I)
FORM_FACTOR = {
    "ATX": "ATX", "M-ATX": "m-ATX", "MATX": "m-ATX", "M-ATX(마이크로ATX)": "m-ATX",
    "MICRO-ATX": "m-ATX", "MINIITX": "mini-ITX", "MINI-ITX": "mini-ITX", "ITX": "mini-ITX",
    "M-ITX": "mini-ITX", "EATX": "E-ATX", "E-ATX": "E-ATX", "SFX": "SFX", "TFX": "TFX",
}
CHIPSET_FEAT = re.compile(r"^([A-Z]\d{2,3}[A-Z]?)\s*\((?:AMD|Intel|인텔)\)$")
CHIPSET_NAME = re.compile(r"\b([ABZHXW]\d{3}[A-Z]?)\b")
GB = re.compile(r"^([\d.,]+)\((GB|TB)\)$", re.I)
MHZ = re.compile(r"^([\d,]+)\(MHz\)", re.I)
WATT_FEAT = re.compile(r"^([\d,]+)\(W\)$", re.I)
WATT_NAME = re.compile(r"(\d{3,4})\s?W\b", re.I)
PCIE = re.compile(r"PCIe\s?([\d.]+)", re.I)
GPU_MODEL = re.compile(r"(RTX|GTX|GT|RX)\s?(\d{3,4})\s?(Ti|SUPER|XT|XTX)?", re.I)
NUM = re.compile(r"([\d,]+(?:\.\d+)?)")
INCH_L2 = {"27인치 모니터": 27, "24인치 모니터": 24, "23인치 이하": 23}


def _num(s):
    if s is None:
        return None
    m = NUM.search(str(s))
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return int(v) if v.is_integer() else v


def gpu_chipset_key(name: str):
    """상품명에서 칩셋 키 정규화 — 'RTX 5070 TI'. 실측 추출률 91%."""
    m = GPU_MODEL.search(name or "")
    if not m:
        return None
    suffix = f" {m.group(3).upper()}" if m.group(3) else ""
    return f"{m.group(1).upper()} {m.group(2)}{suffix}"


def extract_specs(part_type: str, kv: dict, feats: list, name: str, l2: str,
                  gpu_ref: dict) -> tuple:
    """(specs, sources) — 뽑힌 값만 담는다. 못 뽑은 필드는 넣지 않는다(NULL 유지).

    sources: 필드 → 'eav'(키 직결) | 'feature'(특성 값) | 'name'(상품명) | 'reference'(표준표)
    """
    s, src = {}, {}

    def put(field, value, source):
        if value is not None and field not in s:
            s[field] = value
            src[field] = source

    sockets = [v.upper().replace(" ", "") for v in feats if SOCKET.match(v)]

    if part_type == "CPU":
        put("socket", (kv.get("소켓 형태") or "").upper().replace(" ", "") or None, "eav")
        put("socket", sockets[0] if sockets else None, "feature")
        put("tdp_watt", _num(kv.get("열 설계 전력(TDP)")), "eav")
        put("mem_type", next((v.upper() for v in feats if MEM_TYPE.match(v)), None), "feature")

    elif part_type == "MB":
        put("socket", sockets[0] if sockets else None, "feature")
        put("mem_type", next((v.upper() for v in feats if MEM_TYPE.match(v)), None), "feature")
        chip = next((CHIPSET_FEAT.match(v).group(1) for v in feats if CHIPSET_FEAT.match(v)), None)
        put("chipset", chip, "feature")
        m = CHIPSET_NAME.search(name or "")
        put("chipset", m.group(1) if m else None, "name")
        put("form_factor", _form(feats), "feature")
        put("pcie_gen", _pcie(feats), "feature")

    elif part_type == "RAM":
        put("mem_type", next((v.upper() for v in feats if MEM_TYPE.match(v)), None), "feature")
        put("capacity_gb", _cap(kv.get("메모리 용량") or kv.get("용량")), "eav")
        put("capacity_gb", _cap_feat(feats), "feature")
        put("clock_mhz", _num(kv.get("동작 클럭") or kv.get("클럭")), "eav")
        put("clock_mhz", next((_num(MHZ.match(v).group(1)) for v in feats if MHZ.match(v)), None),
            "feature")

    elif part_type == "GPU":
        put("length_mm", _num(kv.get("길이")), "eav")
        put("pcie_gen", _pcie(feats), "feature")
        put("required_power_watt", _num(kv.get("권장파워")), "eav")
        key = gpu_chipset_key(name)
        if key and key in gpu_ref:
            put("required_power_watt", gpu_ref[key], "reference")

    elif part_type == "POWER":
        put("rated_watt", _num(kv.get("정격출력")), "eav")
        put("rated_watt", next((_num(WATT_FEAT.match(v).group(1)) for v in feats
                                if WATT_FEAT.match(v)), None), "feature")
        m = WATT_NAME.search(name or "")
        put("rated_watt", _num(m.group(1)) if m else None, "name")
        put("form_factor", _form(feats), "feature")

    elif part_type == "CASE":
        put("form_factor", _form(feats), "feature")
        put("gpu_max_mm", _num(kv.get("VGA장착길이")), "eav")
        put("cooler_height_mm", _num(kv.get("CPU쿨러장착높이")), "eav")

    elif part_type in ("COOLER_CPU_AIR", "COOLER_CPU_AIO"):
        if sockets:
            s["socket_list"] = sorted(set(sockets))
            src["socket_list"] = "feature"
            s.setdefault("socket", sockets[0])
            src.setdefault("socket", "feature")
        put("cooler_tdp", _num(kv.get("TDP")), "eav")
        if part_type == "COOLER_CPU_AIR":
            put("cooler_height_mm", _num(kv.get("높이")), "eav")

    elif part_type in ("SSD", "HDD"):
        put("capacity_gb", _cap(kv.get("용량")), "eav")
        put("capacity_gb", _cap_feat(feats), "feature")
        put("capacity_gb", _cap_name(name), "name")
        iface, ff = _storage(feats, kv)
        put("interface", iface, "feature")
        put("form_factor", ff, "feature")

    elif part_type == "MONITOR":
        put("size_inch", INCH_L2.get((l2 or "").strip()), "feature")
        put("refresh_hz", _num(kv.get("주사율")), "eav")
        put("resolution", kv.get("해상도"), "eav")
        put("panel", kv.get("패널") or kv.get("패널종류"), "eav")

    return s, src


def _form(feats):
    for v in feats:
        k = v.upper().replace(" ", "")
        if k in FORM_FACTOR:
            return FORM_FACTOR[k]
    return None


def _pcie(feats):
    for v in feats:
        m = PCIE.search(v)
        if m:
            return m.group(1)
    return None


def _cap(v):
    """'32(GB)' · '1(TB)' · '512GB' → GB 정수."""
    if not v:
        return None
    m = GB.match(str(v).strip())
    if m:
        n = float(m.group(1).replace(",", ""))
        return int(n * 1024) if m.group(2).upper() == "TB" else int(n)
    return _num(v)


def _cap_feat(feats):
    for v in feats:
        got = _cap(v) if GB.match(v) else None
        if got:
            return got
    return None


def _cap_name(name):
    m = re.search(r"(\d+(?:\.\d+)?)\s?(TB|GB)\b", name or "", re.I)
    if not m:
        return None
    n = float(m.group(1))
    return int(n * 1024) if m.group(2).upper() == "TB" else int(n)


def _storage(feats, kv):
    """(interface, form_factor) — 'M.2(NVMe)' · '2.5형(SATA3)' 같은 특성값에서."""
    iface = ff = None
    for v in feats:
        u = v.upper()
        if "NVME" in u:
            iface = iface or "NVMe"
        if "SATA" in u:
            iface = iface or "SATA"
        if "M.2" in u:
            ff = ff or "M.2"
        if "2.5" in u:
            ff = ff or "2.5형"
        if "3.5" in u:
            ff = ff or "3.5형"
    if ff is None and kv.get("M.2사이즈"):
        ff = "M.2"
    return iface, ff
