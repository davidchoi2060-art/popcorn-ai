"""다나와 상세 사양 파서 — 순수 함수만 (슬라이스 51).

**여기에 네트워크 코드는 없다.** HTML 문자열을 받아 값을 뽑는 일만 한다.
수집(요청·속도 제한·중단)은 `tools/danawa_fetch.py` 소관이고, 그렇게 나눠야
파서를 저장된 원문으로 재실행·검증할 수 있다.

**수집한 값은 우리 사실이 아니다.** 그래서 이 모듈이 뽑은 값은 `product_specs`에 바로
들어가지 않고 검수 큐의 **제안값(`suggested_value`)** 으로만 올라간다. 운영자가 확인해야
정본이 된다 — "모든 견적에는 이유가 있습니다"의 이유가 남의 페이지일 수는 없다.

**코드 오매핑이 실재한다.** 우리 메인보드에 랜케이블 pcode가 붙어 있는 경우를 실측했다.
그래서 제목 유사도 검증(`title_similarity`)을 통과하지 못하면 사양을 쓰지 않고
'코드 불일치'로 알린다 — 엉뚱한 사양이 조용히 들어가는 것이 최악이다.
"""
import difflib
import re

# 상세 사양 블록. 다나와가 마크업을 바꾸면 여기만 고치면 된다.
SPEC_RE = re.compile(r'class="[^"]*spec_list[^"]*"[^>]*>(.*?)</div>', re.S)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")


def parse_spec_list(html: str) -> tuple[str, dict, str]:
    """(카테고리 토큰, {키: 값}, 원문텍스트). 키 없는 토큰은 카테고리·특성으로 본다."""
    m = SPEC_RE.search(html or "")
    if not m:
        return "", {}, ""
    txt = re.sub(r"\s+", " ", TAG_RE.sub(" ", m.group(1))).strip()
    # 구역 머리표 "[호환/크기]"는 **분리 전에** 지운다 — 안에 '/'가 있어서 그대로 두면
    # 토큰이 "[호환"과 "크기] 인텔 소켓"으로 쪼개져 키가 깨진다(실측).
    clean = re.sub(r"\[[^\]]*\]", " ", txt)
    kv, head = {}, ""
    for i, tok in enumerate(clean.split("/")):
        tok = tok.strip()
        if not tok:
            continue
        if ":" in tok:
            k, _, v = tok.partition(":")
            if k.strip() and v.strip():
                kv.setdefault(k.strip(), v.strip())
        elif i == 0:
            head = tok                                     # "ATX 케이스" · "시스템 쿨러"
    return head, kv, clean


def page_title(html: str) -> str:
    m = TITLE_RE.search(html or "")
    if not m:
        return ""
    t = TAG_RE.sub(" ", m.group(1))
    return re.sub(r"\s*:\s*다나와.*$", "", t).strip()


def _norm(s: str) -> str:
    """기호·공백 차이를 지우고 비교용으로 만든다.

    **괄호 안을 지우지 않는다.** 다나와는 모델명을 괄호에 넣는 경우가 흔해
    ("도시바 N300 7200/256M (14TB, HDWG21E)") 괄호를 통째로 버리면 매칭 근거인
    모델명이 사라진다 — 실제로 같은 상품을 유사도 0.33으로 놓쳤다(슬라이스 51).
    """
    s = re.sub(r"[^0-9A-Za-z가-힣]+", " ", s or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def title_similarity(our_name: str, danawa_title: str) -> float:
    """0~1. 낮으면 pcode가 다른 상품을 가리키고 있다는 뜻이다."""
    a, b = _norm(our_name), _norm(danawa_title)
    if not a or not b:
        return 0.0
    base = difflib.SequenceMatcher(None, a, b).ratio()
    # 모델명 토큰(영문+숫자 조합)이 겹치면 표기 차이를 넘어 같은 상품일 가능성이 크다
    ta = {t for t in a.split() if re.search(r"\d", t) and len(t) >= 3}
    tb = {t for t in b.split() if re.search(r"\d", t) and len(t) >= 3}
    if ta and tb:
        overlap = len(ta & tb) / len(ta)
        base = max(base, overlap)
    return round(base, 3)


def _num(v: str):
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", v or "")
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return int(n) if n.is_integer() else n


FF_MAP = {"E-ATX": "E-ATX", "EATX": "E-ATX", "ATX": "ATX", "M-ATX": "m-ATX",
          "MATX": "m-ATX", "MICRO-ATX": "m-ATX", "M-ITX": "mini-ITX",
          "MITX": "mini-ITX", "MINI-ITX": "mini-ITX", "ITX": "mini-ITX",
          # 파워 전용 소형 규격. 없으면 "M-ATX(SFX) 파워"에서 앞의 m-ATX만 잡혀
          # SFX 파워가 일반 케이스에 들어가는 것으로 잘못 판정된다(실측 13건).
          "SFX": "SFX", "SFX-L": "SFX", "SFXL": "SFX", "TFX": "TFX", "FLEX": "Flex-ATX"}


def _forms(v: str) -> list:
    out = []
    # 콤마·중점뿐 아니라 괄호·공백으로도 갈린다("M-ATX(SFX) 파워" · "ATX , M-ATX , M-ITX")
    for tok in re.split(r"[,·()\s]+", v or ""):
        k = tok.strip().upper()
        k = re.sub(r"^(표준|풀|미니)-?", "", k)
        got = FF_MAP.get(k)
        if got and got not in out:
            out.append(got)
    # 큰 규격부터. 파워 전용 소형 규격(SFX·TFX)도 목록에 있어야 한다 —
    # 빠져 있으면 여기서 걸러져 SFX 파워가 m-ATX로 확정된다(실측 13건).
    order = ["E-ATX", "ATX", "m-ATX", "mini-ITX", "SFX", "TFX", "Flex-ATX"]
    return [o for o in order if o in out]


def _sockets(kv: dict) -> list:
    """인텔·AMD 소켓 목록을 합친다. 쿨러 호환 판정이 이 목록을 쓴다."""
    out = []
    for key in ("인텔 소켓", "AMD 소켓", "소켓", "CPU 소켓"):
        for tok in re.split(r"[,·]", kv.get(key, "")):
            s = tok.strip().upper().replace(" ", "")
            if not s:
                continue
            m = re.match(r"(LGA\d{3,4}[A-Z]?|LGA115X|AM[45]|STRX4|TR4|STR5)", s)
            if m and m.group(1) not in out:
                out.append(m.group(1))
    return out


# part_type별 추출 규칙: 우리 필드 <- (다나와 키 후보들, 변환기)
RULES = {
    "CASE": {
        "form_factor_list": (("지원보드규격",), _forms),
        "gpu_max_mm": (("VGA 길이", "그래픽카드 길이"), _num),
        "cooler_height_mm": (("CPU쿨러 높이",), _num),
    },
    "MB": {
        "form_factor": (("보드규격", "폼팩터"), lambda v: (_forms(v) or [None])[0]),
        "mem_type": (("메모리 규격", "메모리 종류"),
                     lambda v: (re.search(r"DDR[345]", v or "", re.I) or [None])
                     and (re.search(r"DDR[345]", v or "", re.I).group(0).upper()
                          if re.search(r"DDR[345]", v or "", re.I) else None)),
    },
    "CPU": {
        "tdp_watt": (("TDP",), _num),
    },
    "POWER": {
        "rated_watt": (("정격출력", "출력"), _num),
    },
    "GPU": {
        "length_mm": (("가로(길이)", "길이"), _num),
        "required_power_watt": (("권장 파워", "권장파워"), _num),
    },
    "COOLER_CPU_AIR": {
        "cooler_height_mm": (("높이", "쿨러 높이"), _num),
        "cooler_tdp": (("TDP",), _num),
    },
    "COOLER_CPU_AIO": {
        "cooler_tdp": (("TDP",), _num),
    },
}


def to_fields(part_type: str, head: str, kv: dict, txt: str = "") -> dict:
    """다나와 사양 → 우리 필드. 규칙에 없는 것은 뽑지 않는다(추측 금지)."""
    got = {}
    for field, (keys, conv) in (RULES.get(part_type) or {}).items():
        for k in keys:
            if k in kv:
                v = conv(kv[k])
                if v:
                    got[field] = v
                break
    if part_type == "POWER":
        # 파워는 규격·정격이 키-값이 아니라 자유 토큰으로 온다("M-ATX(SFX) 파워 / 750W / ...")
        if "form_factor" not in got:
            f = _forms(head or "")
            if f:
                # "M-ATX(SFX)"처럼 둘이 함께 오면 **더 구체적인 소형 규격**이 실물이다.
                # 앞의 것을 그냥 고르면 SFX 파워를 m-ATX로 확정해 호환 판정이 틀어진다.
                small = [x for x in f if x in ("SFX", "TFX", "Flex-ATX")]
                got["form_factor"] = small[0] if small else f[0]
        if "rated_watt" not in got:
            m = re.search(r"(?:^|/)\s*(\d{3,4})\s*W\s*(?:/|$)", txt or "")
            if m:
                got["rated_watt"] = int(m.group(1))
    if part_type in ("COOLER_CPU_AIR", "COOLER_CPU_AIO"):
        s = _sockets(kv)
        if s:
            got["socket_list"] = s
    # ── 자유 토큰에 있는 값들 ──────────────────────────────────────────────
    # 다나와는 핵심 사양을 키-값이 아니라 토큰으로 흘려둔다("PCIe5.0x16" · "550W 이상"
    # · "5600MHz (PC5-44800)" · head "AMD(소켓AM5)"). 키만 보면 200건 넘게 놓친다.
    t = txt or ""
    if part_type == "CPU":
        if "socket" not in got:
            m = re.search(r"소켓\s*(AM[45]|sTR\d|TR4|\d{3,4})", head or "", re.I)
            if m:
                v = m.group(1).upper()
                got["socket"] = v if v.startswith(("AM", "S", "T")) else "LGA" + v
        if "tdp_watt" not in got:
            # 인텔 신형은 TDP 대신 PBP-MTP로 표기한다("125-181W" → 기본 전력 125)
            m = re.search(r"PBP[- ]?MTP\s*:?\s*(\d{2,3})", t, re.I)
            if m:
                got["tdp_watt"] = int(m.group(1))
    elif part_type == "RAM":
        if "mem_type" not in got:
            m = re.search(r"\bDDR([345])\b", t, re.I)
            if m:
                got["mem_type"] = "DDR" + m.group(1)
        if "clock_mhz" not in got:
            m = re.search(r"(?:^|/)\s*([\d,]{4,6})\s*MHz", t, re.I)
            if m:
                got["clock_mhz"] = int(m.group(1).replace(",", ""))
    elif part_type == "GPU":
        if "pcie_gen" not in got:
            m = re.search(r"PCIe\s*([2-5]\.\d)", t, re.I)
            if m:
                got["pcie_gen"] = "PCIe" + m.group(1)
        if "required_power_watt" not in got:
            m = re.search(r"(?:^|/)\s*(\d{3,4})\s*W\s*이상", t)
            if m:
                got["required_power_watt"] = int(m.group(1))
    return got


# 다나와가 스스로 말하는 분류로 **우리 분류의 오류**를 잡는다.
#
# 단, 긍정 목록("이 분류여야 한다")으로 판정하면 오탐이 쏟아진다 — head는 분류가 아니라
# 상품 특성인 경우가 흔하기 때문이다: 케이스는 "미니ITX"·"랙마운트", 보드는 "AMD(소켓AM5)",
# GPU는 "RTX 5050", SSD는 "6.4cm(2.5형)", 램은 "데스크탑용"이 온다(실측 318건 중 대부분).
# 그래서 **명백히 다른 물건을 가리키는 표현만** 부정 목록으로 잡는다.
PERIPH_HEAD = ("키보드", "마우스", "모니터", "헤드셋", "스피커", "웹캠", "마이크")
NOTPART_HEAD = ("액세서리", "케이블", "베어본", "미니pc", "ups", "허브", "젠더", "받침대")
WRONG_HEAD = {
    # 시스템 쿨러 = 케이스 팬이다. CPU 쿨러가 아니라 견적 슬롯에 들어가면 안 된다.
    "COOLER_CPU_AIR": ("시스템 쿨러",),
    "COOLER_CPU_AIO": ("시스템 쿨러",),
}


def wrong_kind(part_type: str, head: str, txt: str = "") -> str | None:
    """우리 part_type이 명백히 틀렸다고 볼 근거. 없으면 None.

    확실한 것만 말한다 — 잘못 배제하면 멀쩡한 부품이 추천에서 사라진다(위험 방향이 반대).
    """
    h = (head or "").lower()
    if not h:
        return None
    for w in NOTPART_HEAD:
        if w in h:
            return f"다나와 분류 '{head}' — 부품이 아님"
    for w in PERIPH_HEAD:
        if w in h:
            return f"다나와 분류 '{head}' — 주변기기"
    for w in WRONG_HEAD.get(part_type, ()):
        if w in h:
            return f"다나와 분류 '{head}' — CPU 쿨러가 아님"
    # 저장장치 자리에 메모리 사양이 오면 램이 잘못 들어온 것이다(실측 9건)
    if part_type in ("SSD", "HDD") and re.search(r"\bDDR[345]\b", txt or "") \
            and re.search(r"\bCL\d{1,2}\b", txt or ""):
        return "다나와 사양이 메모리(DDR·CL) — 저장장치가 아님"
    return None


def head_mismatch(part_type: str, head: str, txt: str = "") -> bool:
    """분류가 명백히 어긋나는가(수집기 경고용)."""
    return wrong_kind(part_type, head, txt) is not None
