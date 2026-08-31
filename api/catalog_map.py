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
# 완성품 중 **베어본·미니PC만** 분류 토큰으로 잴 수 있다(아래 NOT_PART 에 이미 있는 말이다).
# 완제품 PC 판정은 `map_part_type` 주석 참조(2026-08-16 부로 분기가 생겼다).
BAREBONE_CLS = re.compile(r"베어본|미니\s*PC", re.I)

# 완제품 PC — 카테고리1 축(2026-08-16, `docs/상품다운_2026-08-15_병합_24721.csv` 24,721행
# 전수 실측). 이 CSV 안에서 완제 PC 를 담는 카테고리1 은 이 값 **하나뿐**이다(다른
# 카테고리1 17종 어디에도 '완제'·'조립PC'·'바로쓰는' 류 표기가 없다 — 전수 검색 결과).
PREMIUM_PC_L1 = "프리미엄 피씨"
# 그런데 이 카테고리1 아래에 완제품이 아닌 것이 섞여 있다(실측 359건 중 19건):
#   '생활가전'(15+1건) — 표본 전수가 에어컨·냉풍기·제빙기·건조기다. 몰이 교차판매용으로
#     같은 카테고리1 에 끼워 넣은 것으로 보인다 — PC가 아니다.
#   '소중한고객님※개인결제※'(3건) — 상품명이 '테스트용PC'·개인 이름(예: 최명국_서버)인
#     개인결제 안내 페이지다. `SKIP_L1` 의 '고객님 개인결제'와 같은 성격이라 제외한다.
# 상품명이 아니라 **카테고리2 값 자체**로 거른다(슬라이스 51 — 상품명 유추는 오탐을 만든다).
PREMIUM_PC_EXCLUDE_L2 = {"생활가전", "소중한고객님※개인결제※"}

# ─── 중고 부품(2026-08-16, 사장님 지시 "중고 부품은 견적에서 빼둔다. 다만 분류는
# 제대로 잡아라") — 24,721행 전수 실측 근거는 map_part_type 하단 `map_part_type`
# 독스트링과 `has_used_mark` 주석 참조. ───
#
# 중고 그래픽카드 — 카테고리2 자체가 표준 '그래픽카드(VGA)'와 다른, 몰이 아예 분리해
# 둔 값이다. 카테고리 그 자체가 이미 "중고"라는 판매조건을 담고 있으므로 **상품명 표시
# 여부와 무관하게** 여기서 category_group을 core_part 밖(etc)으로 정한다 — 상품명에
# 오탈자가 있어도(실측 24건 중 1건 "[중괴]") 카테고리가 더 믿을 수 있는 근거다(슬라이스
# 51과 같은 원칙 — 카테고리로 거른다). `l1`을 함께 본다 — 아래 '중고그래픽카드'(공백
# 없음, 컴퓨터주변기기 축)는 전혀 다른 것이다: 그래픽카드가 아니라 **중고 조립PC 번들**
# (CPU+RAM+SSD+GPU 전체 구성)을 검색 노출 목적으로 그래픽카드 카테고리에 끼워 넣은
# 것으로 보인다(실측 12건 전수가 상품명에 "중고조립컴퓨터"·"중고게이밍컴퓨터"를 명시하고
# 스펙 필드도 부품 사양이 아니라 "[12400F/16G/250G/GTX1660SU]"식 완제품 구성이다 —
# 카테고리3 값도 "그래픽카드중고pc"로 몰 스스로 'pc'를 붙여 구분해 뒀다). part_type=GPU로
# 넣으면 그래픽카드가 아닌 것을 그래픽카드라 부르는 거짓 분류가 된다 — 여기서는 판정하지
# 않는다(기존과 같이 미분류로 남는다). 완제품 축(PC_COMPLETE)으로 볼지는 `PREMIUM_PC_L1`
# 축 밖의 별도 사례라 이번 수정에 포함하지 않았다(보고 참조).
USED_GPU_L1 = "알레오코인 채굴기/ 부품"
USED_GPU_L2 = "중고 그래픽카드"

# 알레오코인(채굴) 카테고리 아래 부품 — 우리 표준 라벨과 표기만 다르다(괄호 약어 없음).
# 이 카테고리 자체는 "채굴용"이라는 뜻이지 "중고"라는 뜻이 아니다(실측: 이 별칭 5건 중
# 1건 "COLORFUL H81A-BTC"는 상품명·스펙 어디에도 중고 표시가 없다 — 카테고리만으로
# 중고 단정은 오판이다). 중고 여부는 `has_used_mark`가 상품명+스펙 원문에서 따로
# 판정한다 — 아래 CORE_L2로 들어가는 정상 표기 상품도 **같은 판정**을 받는다(이 별칭에
# 국한된 로직이 아니다).
MINING_L1 = "알레오코인 채굴기/ 부품"
MINING_L2_ALIAS = {"메인보드": "MB", "파워서플라이": "POWER", "저장장치(SSD)": "SSD"}

# 프로모션 진열 카테고리("베스트7주력부품") 아래 CPU·SSD — 표기만 다르다(괄호 없음).
# "중고"와 무관하다(실측 3건 전부 상품명·스펙에 중고 표시 없음 — CPU 1건은 "(정품박스)"로
# 신품임을 스스로 밝힌다).
PROMO_L1 = "베스트7주력부품"
PROMO_L2_ALIAS = {"CPU": "CPU", "SSD": "SSD"}

# 상품명·스펙 원문에 몰이 명시한 중고·리퍼 표시 — **표준 카테고리로 이미 core_part가
# 되는 상품 안에도 이 표시가 섞여 있다**(실측 67건: '그래픽카드(VGA)'·'메모리(RAM)'·
# '메인보드(M/B)' 같은 정상 카테고리인데 상품명이나 스펙 원문(형식 B의 "분류 : 중고",
# 부품 계열 접두어 "중고/리퍼 컴퓨터부품 / ...")이 스스로 중고·리퍼임을 밝힌다).
# '벌크'(정품박스 없는 유통 형태)·'미사용'(신품이라는 뜻)은 중고가 아니므로 넣지 않는다
# — 실측에서 '(정품)'·'[미사용]'이 함께 걸리는 상품도 있었고, 그런 것은 신품 판정을
# 그대로 둔다(예: "AMD 라이젠 스레드리퍼 PRO 3975WX (캐슬 픽-W)(정품)"). '리퍼' 단독은
# '쓰레드리퍼'(Threadripper)·'스레드리퍼' 일부와 겹쳐 오탐이 난다(실측 47건 오탐) —
# 대괄호로 감싼 표시이거나 '리퍼비시' 전체 단어일 때만 인정한다(extract_tags와 같은
# "명시 표현만" 원칙 — 태그 소스와 똑같이 name+raw를 합쳐서 본다).
USED_MARK = re.compile(r"중고|리퍼비시|\[\s*리퍼\s*\]")


def has_used_mark(name: str, raw: str = "") -> bool:
    """상품명 또는 스펙 원문이 스스로 중고·리퍼임을 밝히는가(명시 표현만 신뢰)."""
    return bool(USED_MARK.search((name or "") + " " + (raw or "")))


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

# 노트북용 메모리(SO-DIMM)는 데스크톱 보드에 꽂히지 않는다 — 견적에 들어가면 조립 불가다
# (슬라이스 58: "타무즈 노트북용 DDR5"가 200만원 고성능 구성에 실제로 올라왔다).
# **'노트북'만으로는 안 된다**: 원천은 M.2 SSD를 "PC / 노트북"으로 적는데 그건 겸용이라는 뜻이다.
# 노트북 전용 = SO DIMM이 명시됐거나, 분류에 '노트북'이 있고 'PC'가 없는 경우(실측 102건·오탐 0).
SODIMM = re.compile(r"SO[\s\-]?DIMM", re.I)
NB_ONLY = re.compile(r"(^|/)\s*노트북\s*(/|$)")
PC_ALSO = re.compile(r"(^|/)\s*PC\s*(/|$)", re.I)


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
    if part_type == "RAM" and is_sodimm(raw):
        return "원문 분류가 노트북 전용(SO-DIMM) — 데스크톱 메모리 슬롯 아님"
    return None


def is_sodimm(raw: str) -> bool:
    """노트북 전용 메모리인가 — 분류 토큰만 본다(상품명은 보지 않는다)."""
    cls = _class_tokens(raw or "")
    if SODIMM.search(cls):
        return True
    return bool(NB_ONLY.search(cls)) and not PC_ALSO.search(cls)


def map_part_type(l1: str, l2: str, l3: str, name: str, raw: str = ""):
    """(part_type, category_group, skip_reason) — 분류 판정 + 중고 표시로 후보 제외.

    실제 분류는 `_classify`가 한다. 여기서는 그 결과에 **상품명·스펙 원문의 중고 표시**
    (`has_used_mark`)를 얹어 `category_group`만 내린다 — `part_type`은 그대로 둔다
    (2026-08-16, 사장님 지시 "중고 부품은 견적에서 빼둔다. 다만 분류는 제대로 잡아라").
    그래서 중고 그래픽카드는 상품 목록·필터·통계에서는 여전히 GPU로 보이지만
    (part_type 유지) 두 후보 뷰(core_part/peripheral만 보는 v_recommendation_candidates·
    v_companion_candidates)에는 들어가지 않는다(category_group='etc').

    `_classify`가 이미 'etc'로 내린 것(완제품 PC·베어본·미분류·액세서리)은 건드리지
    않는다 — 이 판정은 core_part/peripheral로 **올라간 뒤에만** 적용한다. 그래서
    "기존 판정이 하나도 바뀌면 안 된다"는 요구를 어기지 않는다: 정상 부품(중고 표시가
    없는 상품)은 이 판정에서 전혀 걸리지 않고 `_classify`의 결과를 그대로 돌려준다.
    """
    pt, grp, reason = _classify(l1, l2, l3, name, raw)
    if pt and grp in ("core_part", "peripheral") and has_used_mark(name, raw):
        return pt, "etc", None
    return pt, grp, reason


def _classify(l1: str, l2: str, l3: str, name: str, raw: str = ""):
    """(part_type, category_group, skip_reason) — 매핑 못 해도 카탈로그에는 넣는다.

    part_type을 못 정한 상품은 `category_group='etc'`로 적재된다: 추천 대상이 아니지만
    재고·가격 관리 대상이기 때문이다(시스템 쿨러·튜닝용품·완제품PC·케이블 등).

    `raw`(스펙 원문)를 주면 원천이 액세서리로 분류한 상품을 core_part로 올리지 않는다.

    중고 표시(has_used_mark)는 여기서 보지 않는다 — 공개 함수 `map_part_type`이 이
    결과 위에 얹어서 판정한다(위 독스트링 참조). 이 함수 자체는 "이 상품이 무슨
    부품인가"만 답한다.
    """
    l1, l2, l3 = (l1 or "").strip(), (l2 or "").strip(), (l3 or "").strip()
    if l1 in SKIP_L1:
        return None, None, f"{l1} 분류"
    # 완성품 축(2026-08-05) — **액세서리 판정보다 먼저** 본다.
    #
    # 베어본·미니PC 는 위 `NOT_PART` 에 이미 들어 있어 아래 `is_accessory` 가 잡아
    # `etc` 로 떨어뜨렸다. 이제는 "부품이 아님"에서 멈추지 않고 **무엇인지**까지 말한다.
    # 이 분기가 필요한 이유: `part_type` 은 저장된 판정이 아니라 **적재마다 다시 계산되는
    # 파생값**이고, 적재 UPSERT 는 운영자가 갈라 놓은 `category_id` 를 읽지도 쓰지도 않는다.
    # 분기가 없으면 다음 적재가 되돌린다.
    #
    # `category_group='etc'` 는 유지한다 — 두 후보 뷰가 core_part/peripheral 만 보므로
    # 같은 슬라이스에서 축을 하나만 움직인다.
    if BAREBONE_CLS.search(f"{l1} {l2} {l3}") or (raw and BAREBONE_CLS.search(raw)):
        return "BAREBONE", "etc", None

    # **완제품 PC**(2026-08-16 — 위 `PREMIUM_PC_L1`/`PREMIUM_PC_EXCLUDE_L2` 주석 참조).
    # `BAREBONE_CLS` **다음에** 둔다 — 이 카테고리1 에서 베어본이 나올 근거는 실측 0건이지만,
    # 원문이 '베어본'·'미니PC'를 스스로 명시하면 그쪽이 더 구체적인 사실이라 우선한다.
    # `category_group='etc'` 는 그대로 둔다(0031 — 두 후보 뷰가 core_part/peripheral 만
    # 본다. part_type 축만 옮기고 후보 노출 축은 같은 슬라이스에서 움직이지 않는다).
    if l1 == PREMIUM_PC_L1 and l2 not in PREMIUM_PC_EXCLUDE_L2:
        return "PC_COMPLETE", "etc", None

    if raw and is_accessory(raw):
        return None, "etc", "원천 분류가 액세서리·베어본 — 부품 아님"
    if l2 in CORE_L2:
        bad = wrong_slot(CORE_L2[l2], raw) if raw else None
        if bad:
            return None, "etc", bad
        return CORE_L2[l2], "core_part", None
    # 중고 그래픽카드 — 카테고리 자체가 이미 "중고"를 담고 있어 여기서 바로 etc로
    # 내린다(위 `USED_GPU_L1`/`USED_GPU_L2` 주석 참조 — 상품명 오탈자와 무관하게 판정).
    if l1 == USED_GPU_L1 and l2 == USED_GPU_L2:
        return "GPU", "etc", None
    # 알레오코인 채굴기 카테고리의 표기 별칭(위 `MINING_L2_ALIAS` 주석 참조). 중고 여부는
    # 아래 공개 함수 `map_part_type`이 `has_used_mark`로 별도 판정하므로 여기서는
    # core_part로 둔다 — CORE_L2 정상 경로와 동일하게 취급한다.
    if l1 == MINING_L1 and l2 in MINING_L2_ALIAS:
        pt2 = MINING_L2_ALIAS[l2]
        bad = wrong_slot(pt2, raw) if raw else None
        if bad:
            return None, "etc", bad
        return pt2, "core_part", None
    # 프로모션 진열 카테고리의 표기 별칭(위 `PROMO_L2_ALIAS` 주석 참조).
    if l1 == PROMO_L1 and l2 in PROMO_L2_ALIAS:
        pt2 = PROMO_L2_ALIAS[l2]
        bad = wrong_slot(pt2, raw) if raw else None
        if bad:
            return None, "etc", bad
        return pt2, "core_part", None
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

# RAM 총용량 — 이름 교정 경로 (2026-08-31). eav/feature가 «모듈당» 값을 총량으로 잘못
# 받는 사고가 실측됐다(예: 상품명 "DDR5 32GB [16G x 2]"인데 특성값에 홀로 있는
# "16(GB)"를 그대로 받아 32가 아니라 16이 저장됨). 이름에는 총량과 모듈 구성이 함께
# 적히는 경우가 많고, 실측 70건 전부 "명시 총량 = 모듈당×개수"였다 — 이 두 표기가
# 서로를 검증해 주므로 RAM에서는 이름이 eav/feature보다 더 믿을 만하다(_cap_ram_name
# 사용처 주석 참조). SSD/HDD는 반대로 eav/feature 불일치가 0건이라 그대로 둔다.
RAM_DDR = re.compile(r"DDR[2345]", re.I)
RAM_TOTAL = re.compile(r"(\d+(?:\.\d+)?)\s?(TB|GB)\b(?!\s*[xX×]\s*\d)", re.I)
RAM_MODxN = re.compile(r"(\d+(?:\.\d+)?)\s?G(?:B)?\s*[xX×]\s*(\d+)", re.I)
INCH_L2 = {"27인치 모니터": 27, "24인치 모니터": 24, "23인치 이하": 23}
# ⚠ INCH_L2 에 「32인치 이상」이 없다 — **일부러 없다.** 그 분류는 «범위»라 단일 값이 없고,
# 32 를 박으면 34·40·49형이 전부 32형으로 «틀리게» 기록된다. 대신 아래 MON_INCH 가 원문의
# 「32(형)」을 읽어 정확한 값을 넣는다(실측 2026-08-22: L2 가 32인치 이상이라 NULL 이던
# 132건 중 122건이 원문에서 읽혔다 — 32형 90 · 34형 16 · 49형 5 · 31.5형 2 …).

# 원문(형식 A — 키 없이 「/」로 나열)에서 모니터 사양을 읽는다.
#   ASUS / 32(형) / 와이드(16:9) / 1920 x 1080, (FHD) / … / 주사율 : 170(Hz) /
# 주사율만 「키 : 값」이라 EAV(B_MAP·kv)로 잡혔고 인치·해상도는 **키가 없어** 아무도 안 읽었다.
# 쿨러 TDP(커밋 0123553)와 같은 모양 — 원문 부재가 아니라 파서 누락이다.
MON_INCH = re.compile(r"(?<![0-9.])(\d{2}(?:\.\d)?)\s*\(형\)")
# 약칭 앞의 콤마는 «있을 때도 없을 때도» 있다 — 원문에 「1920 x 1080, (FHD)」와
# 「1920 x 1080(FHD)」가 섞여 있다. 콤마를 필수로 두면 뒤 형식에서 약칭을 통째로 잃는다
# (교정 드라이런에서 삼성 S22E45K 등이 「1920 x 1080」으로 깎일 뻔했다).
MON_RES = re.compile(r"(\d{3,4})\s*[xX×]\s*(\d{3,4})\s*,?\s*(?:\(([^)]{1,24})\))?")
# 약칭을 줄여야 하는 것만 적는다 — `resolution` 은 varchar(20) 이고 원문을 그대로 넣으면
# 잘린다(실측: 기존 26건 중 「3440 x 1440, (Ultra 」·「3840 x 2160, (4K-UHD」 처럼 **손상된
# 값**이 있었다). 콤마를 빼고 이 표로 줄이면 실재 14종이 전부 20자 안에 들어간다.
MON_RES_ABBR = {"Ultra WQHD": "UWQHD"}


def monitor_inch(raw: str):
    """원문에서 화면 크기(형) — 없으면 None. 지어내지 않는다."""
    m = MON_INCH.search(raw or "")
    if not m:
        return None
    v = float(m.group(1))
    return int(v) if v.is_integer() else v


def monitor_resolution(raw: str):
    """원문에서 해상도 — 「1920 x 1080 (FHD)」 꼴. 없으면 None.

    ⚠ 같은 원문에 「NNNxNNN」이 «해상도가 아닌 자리»로 또 있다 — 드라이런에서
    「월마운트(VESA) : 100x100(mm)」을 해상도로 읽어 뷰소닉 VX3208 에
    **「100 x 100」**을 넣을 뻔했다. 그래서 모양만 보지 않고 **값의 범위**로 거른다:
    실재 최소 해상도는 1024 x 768 이고 VESA 규격은 75·100·200·400(mm) 이라 겹치지 않는다.
    「모양이 맞으니 그 값이겠지」가 정확히 이 저장소가 여러 번 당한 병이다.

    20자(컬럼 폭)를 넘으면 약칭을 버리고 숫자만 남긴다 — **자르지 않는다.**
    잘린 값은 「(4K-UHD」처럼 뜻이 깨져 화면이 거짓말을 하게 된다.
    """
    for m in MON_RES.finditer(raw or ""):
        w, h = int(m.group(1)), int(m.group(2))
        if w < 1024 or h < 720 or w < h:      # 해상도가 아닌 수(VESA mm 등)를 버린다
            continue
        num = "%d x %d" % (w, h)
        ab = (m.group(3) or "").strip()
        ab = MON_RES_ABBR.get(ab, ab)
        full = "%s (%s)" % (num, ab) if ab else num
        return full if len(full) <= 20 else num
    return None


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
        # 이름을 eav/feature보다 먼저 본다 — SSD/HDD(eav→feature→name)와 순서가
        # 다르다. RAM은 원천 특성값이 모듈당/총량을 구분하지 못해 eav·feature가
        # 틀린 값(모듈당)을 총량인 것처럼 내놓는 사고가 실측됐고, 이름 쪽은 두 표기
        # (총량·모듈×개수)가 서로 일치해 더 믿을 만하다(위 RAM_DDR 주석 참조).
        put("capacity_gb", _cap_ram_name(name), "name")
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
        put("radiator_max_rows",
            _b_rows(kv.get("수랭쿨러지원") or kv.get("수랭쿨러 지원")), "eav")

    elif part_type in ("COOLER_CPU_AIR", "COOLER_CPU_AIO"):
        if sockets:
            s["socket_list"] = sorted(set(sockets))
            src["socket_list"] = "feature"
            s.setdefault("socket", sockets[0])
            src.setdefault("socket", "feature")
        put("cooler_tdp", _num(kv.get("TDP")), "eav")
        if part_type == "COOLER_CPU_AIR":
            put("cooler_height_mm", _num(kv.get("높이")), "eav")
        else:
            v, vsrc = radiator_rows(_num(kv.get("수랭팬개수")), name)
            if v:
                put("radiator_rows", v, vsrc)

    elif part_type in ("SSD", "HDD"):
        put("capacity_gb", _cap(kv.get("용량")), "eav")
        put("capacity_gb", _cap_feat(feats), "feature")
        put("capacity_gb", _cap_name(name), "name")
        iface, ff = _storage(feats, kv)
        put("interface", iface, "feature")
        put("form_factor", ff, "feature")

    elif part_type == "MONITOR":
        # 원문 토큰을 먼저 본다 — put() 은 «먼저 넣은 값»이 이긴다. 정확한 「32(형)」이
        # 범위 분류(INCH_L2)보다 앞서야 34·49형이 32형으로 뭉개지지 않는다.
        mon_raw = " / ".join(feats)
        put("size_inch", monitor_inch(mon_raw), "feature")
        put("size_inch", INCH_L2.get((l2 or "").strip()), "feature")
        put("refresh_hz", _num(kv.get("주사율")), "eav")
        # 해상도도 원문이 먼저다 — kv 경로는 원문을 그대로 넣어 varchar(20) 에서 잘렸다.
        put("resolution", monitor_resolution(mon_raw), "feature")
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


def _cap_ram_name(name):
    """RAM 총용량을 상품명에서 읽는다 — `_cap_name()`을 그대로 못 쓴다: 묶음상품
    ([SSD + RAM] 류)에서 SSD 용량(1TB/2TB)을 먼저 집어 RAM 용량으로 착각하고
    (실측 119879·120880·120881), "16Gx2"처럼 총량 없이 모듈×개수만 있는 표기는
    아예 못 읽는다(리터럴 "GB"/"TB" 요구 — 실측 문제 92건 중 22건이 이 형태).

    두 신호를 이름에서 찾되 **DDR2/3/4/5 표기 이후로만** 찾는다 — 묶음상품은 SSD
    용량이 DDR 표기보다 앞에 오므로 이 한 줄로 오독을 막는다. **DDR 표기 자체가
    없으면 아예 시도하지 않는다**(실측: `part_type='RAM'`인데 실은 그래픽카드인
    오분류 상품 — 예 "…RTX 4070 SUPER…D6X 12GB DUAL" — 이 이름의 유일한 용량
    토큰은 VRAM 12GB다. DDR 표기가 없다는 것은 이 이름을 RAM 총량 판단 근거로
    믿을 수 없다는 신호이므로, 그 신호를 무시하고 전체에서 찾지 않는다 — 가를 수
    없으면 값을 안 쓴다):
      ① 명시 총량 — "32GB"·"128GB". 바로 뒤에 배수(x2 등)가 오면 그건 총량이
         아니라 모듈당 표기이므로 제외한다("32GB x 4"에서 32를 총량으로 안 읽는다
         — 진짜 총량 128GB는 그 앞에 따로 있다. 없으면 ②로 넘어간다).
      ② 모듈당 × 개수 — "16Gx2"·"16G x 2"·"32GB x 4". ①이 없을 때만 쓴다.
    실측(2026-08-31 조사자): 이름에 ①·②가 둘 다 있는 70건 전부 ①=②였다 —
    지어낸 규칙이 아니라 원천 표기 자체가 서로 검증해 주는 관계다.

    가를 수 없으면(DDR 표기가 없거나, 있어도 둘 다 못 찾으면) None을 돌려준다 —
    틀린 값보다 빈 값이 낫다.
    """
    if not name:
        return None
    m = RAM_DDR.search(name)
    if not m:
        return None
    zone = name[m.start():]
    mt = RAM_TOTAL.search(zone)
    if mt:
        n = float(mt.group(1))
        return int(n * 1024) if mt.group(2).upper() == "TB" else int(n)
    mm = RAM_MODxN.search(zone)
    if mm:
        per, cnt = float(mm.group(1)), int(mm.group(2))
        return int(per * cnt) if cnt > 0 else None
    return None


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


def _b_rows(v):
    """'최대 3열' · '3(EA)' → 3. 실측 범위는 1~4열(480mm까지)."""
    n = _b_num(v)
    return int(n) if isinstance(n, (int, float)) and 1 <= n <= 4 else None


# 상품명에 제조사가 쓴 라디에이터 규격 → 열 수.
# **추론이 아니라 명시 표현이다** — 제조사가 제품명에 적은 규격을 읽을 뿐이다(태그 규칙과 같다).
RAD_NAME = re.compile(r"\b(120|140|240|280|360|420|480)\b")
RAD_ROWS = {"120": 1, "140": 1, "240": 2, "280": 2, "360": 3, "420": 3, "480": 4}


def radiator_rows_from_name(name: str):
    m = RAD_NAME.search(name or "")
    return RAD_ROWS.get(m.group(1)) if m else None


def radiator_rows(fan_count, name: str):
    """수랭 라디에이터 열 수 — 제품명 규격이 있으면 그것이 실제 크기다.

    원문 '수랭팬개수'는 라디에이터 크기와 어긋날 수 있다(실측):
      · 360 제품에 팬 2로 적힌 것 5건 — **과소**. `<=` 규칙에서 과소는
        조립 불가 조합을 통과시키는 방향이라 가장 위험하다.
      · 발키리 GL36(360 푸시풀)에 팬 6 — **과대**. 6열 케이스는 없으므로
        어떤 케이스에도 안 들어가는 부품이 된다(0021이 고친 것과 같은 전멸).

    그래서 팬개수를 그대로 쓰지 않는다:
      ① 제품명에 규격이 있으면 그 값(제조사가 쓴 실제 라디에이터 크기)
      ② 없으면 팬개수 — 단 4 이상은 푸시풀과 구분할 수 없어 **비워 둔다**.
         모르면 값을 넣지 않는다. 규칙은 NULL을 통과시키지 않고, 검수에서 사람이 채운다.
    """
    by_name = radiator_rows_from_name(name)
    if by_name:
        return by_name, "name_explicit"
    if fan_count and 1 <= fan_count <= 3:
        return fan_count, "text_kv"
    return None, None


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
             "쿨러 높이": ("cooler_height_mm", _b_num),
             "수랭쿨러 지원": ("radiator_max_rows", _b_rows),
             "수랭쿨러지원": ("radiator_max_rows", _b_rows)},
    "POWER": {"정격 출력": ("rated_watt", _b_num), "표준 출력": ("rated_watt", _b_num),
              "제품 분류": ("form_factor", _b_form), "ATX12V 규격": ("form_factor", _b_form)},
    "GPU": {"권장 파워": ("required_power_watt", _b_num),
            "권장파워": ("required_power_watt", _b_num),
            "길이": ("length_mm", _b_num), "가로": ("length_mm", _b_num)},
    "COOLER_CPU_AIR": {"TDP": ("cooler_tdp", _b_num), "높이": ("cooler_height_mm", _b_num),
                       "쿨러 높이": ("cooler_height_mm", _b_num)},
    "COOLER_CPU_AIO": {"TDP": ("cooler_tdp", _b_num),
                       "수랭팬개수": ("radiator_rows", _b_rows)},
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
    if part_type == "MONITOR":
        # 형식 A(키 없이 나열)에 인치·해상도가 살아 있는데 B_MAP 에 MONITOR 가 없어
        # respec 이 이 슬롯을 아예 안 건드렸다. CASE 의 case_form_list 와 같은 자리다.
        for _f, _v in (("size_inch", monitor_inch(raw)),
                       ("resolution", monitor_resolution(raw))):
            if _v is not None:
                s[_f] = _v
                src[_f] = "text_tokens"
    for bkey, (field, conv) in mapping.items():
        if field in s or bkey not in kv:
            continue
        got = conv(kv[bkey])
        if got is not None:
            s[field] = got
            src[field] = "text_kv"
    if part_type == "COOLER_CPU_AIO":
        # 팬개수를 그대로 열 수로 쓰지 않는다 — radiator_rows()가 이유를 설명한다.
        v, vsrc = radiator_rows(_b_rows(kv.get("수랭팬개수")), name)
        if v:
            s["radiator_rows"] = v
            src["radiator_rows"] = vsrc
        else:
            s.pop("radiator_rows", None)
            src.pop("radiator_rows", None)

    tags, tsrc = extract_tags(part_type, name, raw)      # 명시 표현만(슬라이스 48)
    s.update(tags)
    src.update(tsrc)
    return s, src
