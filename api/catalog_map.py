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


# 원천이 **스스로 '액세서리'라 분류한 것**을 우리가 부품으로 올리지 않는다(슬라이스 51).
# 시스템 팬을 CPU쿨러로, 베어본을 메인보드로 올려두면 채울 수 없는 사양을 영원히 검수
# 대기에 쌓는다(실측 160건이 그 상태였다).
# 판단 근거는 **스펙 원문의 분류 토큰**뿐이다 — 상품명으로 보면 모듈러 파워의 '케이블',
# SSD의 '연장가이드'까지 걸려 진짜 부품을 추천에서 떨어뜨린다(위험 방향이 반대다).
NOT_PART = re.compile(
    r"액세서리|베어본|미니PC|\bUPS\b|허브\.컨버터"
    r"|케이블,젠더|커버,필터|브라켓,가이드|라이저"
    # 네트워크 장비·케이블류가 메인보드 자리에 올라와 있었다(실측)
    r"|스위치허브|랜케이블|LAN\s*케이블|HDMI\s*케이블|DP\s*케이블"
    r"|케이블/AV|전원\.튜닝케이블", re.I)

# '시스템 쿨러'는 케이스 팬을 뜻하지만, 원천이 이 말을 **CPU 쿨러 대분류로도 쓴다**
# ("샤칸 / 시스템쿨러 / 수랭 / 수랭팬개수 : 2" = 진짜 수랭 CPU 쿨러).
# 그래서 냉각 방식(수랭·공랭) 표시가 함께 있으면 CPU 쿨러로 본다 — 이 구분이 없으면
# 멀쩡한 AIO를 추천에서 지운다.
SYS_FAN = re.compile(r"시스템\s*쿨러|시스템/케이스용", re.I)
CPU_COOL_HINT = re.compile(r"수랭|수냉|공랭|공냉|CPU\s*쿨러", re.I)
# '허브랙'은 넣지 않는다 — "서버, 허브랙 / 랙마운트(3U)"는 진짜 랙마운트 PC 케이스이고
# CPU쿨러 장착높이·VGA 장착길이까지 가진 부품이다(실측 3건이 오검출됐다).

# 저장장치 자리에 메모리가 들어오면 원문이 스스로 밝힌다(DDR + CL + MHz).
MEM_SPEC = re.compile(r"\bDDR[345]\b", re.I)
MEM_CL = re.compile(r"\bCL\s?\d{1,2}\b", re.I)


def _class_tokens(raw: str, n: int = 5) -> str:
    """원천의 **분류 영역** — 앞쪽 토큰 중 키-값이 아닌 것들.

    분류는 "제조사 / 시스템/케이스용 / 시스템 쿨러 / 가로: 80mm" 처럼 앞에 오지만
    항상 1~2번째는 아니다(제조사·수입원이 먼저 오기도 한다). 그렇다고 전체를 훑으면
    모듈러 파워의 '케이블' 같은 사양 값에 걸려 진짜 부품을 떨어뜨린다.
    **키-값(`:` 포함) 토큰은 사양이지 분류가 아니므로** 그것만 걸러내면 둘 다 피할 수 있다.
    """
    out = []
    for tok in (raw or "").split("/"):
        tok = tok.strip()
        if not tok or ":" in tok:
            continue
        out.append(tok)
        if len(out) >= n:
            break
    return " / ".join(out)


def is_accessory(raw: str) -> bool:
    """원천이 스스로 부품이 아니라고 말하는가."""
    cls = _class_tokens(raw)
    if NOT_PART.search(cls):
        return True
    # 시스템 팬 — 단, 냉각 방식 표시가 있으면 CPU 쿨러다(원문 전체를 본다)
    return bool(SYS_FAN.search(cls)) and not CPU_COOL_HINT.search(raw or "")


def wrong_slot(part_type: str, raw: str) -> str | None:
    """part_type이 원문과 명백히 어긋나는가. 확실한 것만 말한다."""
    if part_type in ("SSD", "HDD") and MEM_SPEC.search(raw or "") and MEM_CL.search(raw or ""):
        return "원문 사양이 메모리(DDR·CL) — 저장장치가 아님"
    return None


def map_part_type(l1: str, l2: str, l3: str, name: str, raw: str = ""):
    """(part_type, category_group, skip_reason) — 매핑 못 해도 카탈로그에는 넣는다.

    part_type을 못 정한 상품은 `category_group='etc'`로 적재된다: 추천 대상이 아니지만
    재고·가격 관리 대상이기 때문이다(시스템 쿨러·튜닝용품·완제품PC·케이블 등).

    `raw`(스펙 원문)를 주면 원천이 액세서리로 분류한 상품을 core_part로 올리지 않는다.
    """
    l1, l2, l3 = (l1 or "").strip(), (l2 or "").strip(), (l3 or "").strip()
    if l1 in SKIP_L1:
        return None, None, f"{l1} 분류"
    if raw and is_accessory(raw):
        return None, "etc", "원천 분류가 액세서리·베어본 — 부품 아님"
    if l2 in CORE_L2:
        bad = wrong_slot(CORE_L2[l2], raw) if raw else None
        if bad:
            return None, "etc", bad
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


# ─────────────────── 형식 B 파서 (슬라이스 42) ───────────────────
# 원천 '스펙' 문자열에 **두 가지 표기 형식이 섞여 있다**(슬라이스 42 실측):
#   A: "ASRock / AMD / AM4 / A520 (AMD) / m ATX / DDR4 / ..."      값만 나열
#   B: "제조회사 : ASRock / CPU 소켓 : AMD(소켓AM4) / 세부 칩셋 : (AMD) B550 / 폼팩터 : M ATX"
# EAV(db_product_specs.csv)는 A만 파싱했고 B는 1~2%만 담겨 있다. 그래서 B는 원문
# (products.spec_source_text)에서 직접 읽는다 — **값을 지어내는 게 아니라 원천을 제대로 읽는 것**이다.
# 실측 회수 가능성: MB 소켓 46% · CASE form_factor 78%(표기 확인 필요) · POWER 67%.

# 원천 표기 실측: "인텔(소켓1700)" · "AMD(소켓AM4)" 형태가 많다 — LGA 접두 없이
# '소켓' 뒤에 숫자만 온다. 이걸 못 읽어 메인보드 소켓 98건이 검수에 남아 있었다(슬라이스 51).
B_SOCKET = re.compile(r"(?:소켓\s*)?(LGA\s?\d{3,4}|AM[45]|sTRX4|TR4)|소켓\s*(\d{3,4})", re.I)
B_CHIPSET = re.compile(r"([A-Z]\d{2,3}[A-Z]?)")
B_NUM = re.compile(r"([\d,]+(?:\.\d+)?)")


def parse_kv_text(raw: str) -> dict:
    """원문에서 '키 : 값' 쌍을 뽑는다(형식 B). 키가 없는 토큰은 무시(형식 A는 EAV가 담당)."""
    out = {}
    for tok in (raw or "").split("/"):
        tok = tok.strip()
        if ":" not in tok:
            continue
        k, _, v = tok.partition(":")
        k, v = k.strip(), v.strip()
        if k and v:
            out.setdefault(k, v)
    return out


def _b_socket(v):
    m = B_SOCKET.search(v or "")
    if not m:
        return None
    if m.group(1):
        return m.group(1).upper().replace(" ", "")      # LGA1700 · AM4 형태 그대로
    return "LGA" + m.group(2)                           # "소켓1700" -> LGA1700


def _b_chipset(v):
    m = B_CHIPSET.search((v or "").replace("(AMD)", "").replace("(Intel)", "").replace("(인텔)", ""))
    return m.group(1) if m else None


def _b_form(v):
    k = (v or "").upper().replace("-", "").replace(" ", "")
    for pat, out in (("EATX", "E-ATX"), ("MATX", "m-ATX"), ("MICROATX", "m-ATX"),
                     ("MINIITX", "mini-ITX"), ("ITX", "mini-ITX"),
                     ("SFX", "SFX"), ("TFX", "TFX"), ("ATX", "ATX")):
        if pat in k:
            return out
    return None


def _b_num(v):
    m = B_NUM.search(v or "")
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return int(n) if n.is_integer() else n


def _b_mem(v):
    m = re.search(r"DDR[345]", v or "", re.I)
    return m.group(0).upper() if m else None


# 형식 B 키 -> (우리 필드, 변환기). 슬롯별로 의미가 달라 슬롯 안에서만 적용한다.
B_MAP = {
    "MB": {"CPU 소켓": ("socket", _b_socket), "소켓": ("socket", _b_socket),
           "세부 칩셋": ("chipset", _b_chipset), "칩셋": ("chipset", _b_chipset),
           "폼팩터": ("form_factor", _b_form), "메모리 종류": ("mem_type", _b_mem)},
    "CPU": {"CPU 소켓": ("socket", _b_socket), "소켓": ("socket", _b_socket),
            "열 설계 전력": ("tdp_watt", _b_num), "TDP": ("tdp_watt", _b_num)},
    "CASE": {"그래픽카드 장착": ("gpu_max_mm", _b_num),
             "CPU쿨러 장착": ("cooler_height_mm", _b_num),
             "쿨러 높이": ("cooler_height_mm", _b_num)},
    "POWER": {"정격 출력": ("rated_watt", _b_num), "표준 출력": ("rated_watt", _b_num),
              "제품 분류": ("form_factor", _b_form), "ATX12V 규격": ("form_factor", _b_form)},
    "GPU": {"권장 파워": ("required_power_watt", _b_num),
            "권장파워": ("required_power_watt", _b_num),
            "길이": ("length_mm", _b_num), "가로": ("length_mm", _b_num)},
    "COOLER_CPU_AIR": {"TDP": ("cooler_tdp", _b_num), "높이": ("cooler_height_mm", _b_num),
                       "쿨러 높이": ("cooler_height_mm", _b_num)},
    "COOLER_CPU_AIO": {"TDP": ("cooler_tdp", _b_num)},
    "RAM": {"메모리 종류": ("mem_type", _b_mem), "메모리 용량": ("capacity_gb", _cap),
            "동작 클럭": ("clock_mhz", _b_num)},
    "SSD": {"용량": ("capacity_gb", _cap)},
    "HDD": {"용량": ("capacity_gb", _cap)},
}


# ─────────── 케이스 지원 보드 규격 목록 (슬라이스 43) ───────────
# 케이스는 규격을 여러 개 수용한다(실측: 3개 1,110건·4개 566건). 원천 스펙 문자열에
# "ATX / mATX / MiniITX" 형태로 적혀 있어 92%가 회수된다.
#
# **'지원 파워 : ATX'는 세면 안 된다** — 그건 파워 규격이지 보드 규격이 아니다. 섞으면
# mATX 전용 케이스가 ATX 보드도 받는다고 말하게 되어(과하게 관대) 조립 보증이 무너진다.
# 그래서 "키 : 값" 형태 토큰은 건너뛰고 **키 없는 토큰(형식 A의 특성값)에서만** 모은다.
FF_TOKEN = re.compile(r"^(E-?ATX|XL-?ATX|M-?ATX|Micro-?ATX|Mini-?ITX|MiniITX|ITX|ATX)$", re.I)
FF_NORM = {"ATX": "ATX", "MATX": "m-ATX", "MICROATX": "m-ATX",
           "MINIITX": "mini-ITX", "ITX": "mini-ITX",
           "EATX": "E-ATX", "XLATX": "E-ATX"}
# 규격 포함 관계 — 큰 규격을 받는 케이스는 작은 규격도 받는다(업계 표준 크기 순서).
# 원천 목록이 불완전한 케이스(ATX만 적힌 것)에서 mATX 보드를 부당하게 막지 않기 위해 넓힌다.
FF_ACCEPTS = {"E-ATX": ["E-ATX", "ATX", "m-ATX", "mini-ITX"],
              "ATX": ["ATX", "m-ATX", "mini-ITX"],
              "m-ATX": ["m-ATX", "mini-ITX"],
              "mini-ITX": ["mini-ITX"]}


def case_form_list(raw: str) -> list:
    """케이스가 수용하는 보드 규격 목록. 못 뽑으면 빈 리스트(= 검수 대상, 불통과)."""
    found = []
    for tok in (raw or "").split("/"):
        tok = tok.strip()
        if not tok:
            continue
        if ":" in tok:
            # "지원 파워 규격 : 표준 ATX"는 **파워** 규격이라 보드 규격이 아니다(제외).
            # 다만 "제품 분류 : PC케이스(ATX)"는 케이스가 수용하는 보드 규격이다 —
            # 이걸 통째로 버려서 63건이 검수에 남아 있었다(슬라이스 51).
            k, _, v = tok.partition(":")
            if k.strip() != "제품 분류":
                continue
            tok = v.strip().replace("PC케이스", "").strip("()（） ")
        m = FF_TOKEN.match(tok)
        if not m:
            continue
        norm = FF_NORM.get(m.group(1).upper().replace("-", ""))
        if norm and norm not in found:
            found.append(norm)
    if not found:
        return []
    # 가장 큰 규격의 수용 범위로 확장 — 목록 표기가 빠진 경우를 덮는다
    order = ["E-ATX", "ATX", "m-ATX", "mini-ITX"]
    biggest = next((o for o in order if o in found), None)
    out = list(FF_ACCEPTS.get(biggest, found))
    for v in found:                      # 표기된 것은 무조건 포함
        if v not in out:
            out.append(v)
    return [o for o in order if o in out]


# ─────────── 선호 태그 회수 (슬라이스 48) ───────────
# S1의 "조용하게"·"화이트로"는 서버가 후보 수에 실제로 반영하는 조건인데,
# 적재가 `tag_silent`·`tag_white`를 채우지 않아 태그 보유가 시드 몇 개뿐이었다.
# 그 결과 저소음 조건에서 쿨러(AIO) 슬롯이 0이 되어 **견적이 불성립**했고,
# S1은 "387개로 3구성을 만들 수 있다"고 말했다(거짓).
#
# **명시된 표현만 태그로 인정한다.** '무소음'·'저소음'처럼 제조사가 상품명·스펙에 쓴 말이
# 근거다. "팬이 크니 조용할 것"처럼 추론하지 않는다 — 조용함은 주관적이고, 지어낸 태그는
# 고객이 "조용하게"라고 말한 이유를 배신한다.
TAG_WHITE_RE = re.compile(r"화이트|WHITE|백색", re.I)
TAG_SILENT_RE = re.compile(r"무소음|저소음|정숙|사일런트|SILENT|LOW\s*NOISE", re.I)
# 저소음이 의미 있는 슬롯(소음원). 그 밖의 부품에 붙이면 필터가 무의미해진다.
TAG_SILENT_SLOTS = ("GPU", "POWER", "CASE", "COOLER_CPU_AIR", "COOLER_CPU_AIO")


def extract_tags(part_type: str, name: str, raw: str) -> tuple:
    """(tags, sources) — 명시 표현이 있을 때만 True를 담는다(False는 담지 않는다).

    False를 담지 않는 이유: '태그 없음'과 '아직 판정 안 함'을 구분해야 한다.
    DB 기본값(NULL/false)이 곧 '명시 표현 없음'이다.
    """
    src = (name or "") + " " + (raw or "")
    tags, sources = {}, {}
    if part_type == "CASE" and TAG_WHITE_RE.search(src):
        tags["tag_white"] = True
        sources["tag_white"] = "name_explicit"
    if part_type in TAG_SILENT_SLOTS and TAG_SILENT_RE.search(src):
        tags["tag_silent"] = True
        sources["tag_silent"] = "name_explicit"
    return tags, sources


def extract_from_text(part_type: str, raw: str, name: str = "") -> tuple:
    """형식 B 원문 + 명시 태그에서 뽑기 — (specs, sources).

    sources: 'text_kv'(형식 B 키) · 'text_tokens'(케이스 규격 목록) ·
    'name_explicit'(태그 — 제조사가 쓴 말)
    """
    kv = parse_kv_text(raw)
    # kv가 비어도 태그·케이스 규격은 뽑을 수 있으므로 조기 return 하지 않는다(슬라이스 48)
    mapping = B_MAP.get(part_type) or {}
    s, src = {}, {}
    if part_type == "CASE":
        lst = case_form_list(raw)
        if lst:
            s["form_factor_list"] = lst
            src["form_factor_list"] = "text_tokens"
            s.setdefault("form_factor", lst[0])       # 대표값(표시용) — 판정은 목록이 한다
            src.setdefault("form_factor", "text_tokens")
    for bkey, (field, conv) in mapping.items():
        if field in s or bkey not in kv:
            continue
        got = conv(kv[bkey])
        if got is not None:
            s[field] = got
            src[field] = "text_kv"
    tags, tsrc = extract_tags(part_type, name, raw)      # 명시 표현만(슬라이스 48)
    s.update(tags)
    src.update(tsrc)
    return s, src
