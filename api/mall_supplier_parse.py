# -*- coding: utf-8 -*-
"""몰 공급처 페이지(HTML) 파서 -- 단일 원천 (2026-08-26 신설).

`/adm_cate/product_com_list.php?pd_no=` 응답에서 업체 행을 뽑아내고(파싱), 그 업체명을
`suppliers`와 맞추는(매칭) 로직이다. **두 곳이 이것을 쓴다**:

    tools/mall_supplier_fetch.py     CLI -- 하네스가 받아둔 파일에서 읽어 처리(--from-dir)
    api/admin_mall_supplier.py       API -- 브라우저가 읽은 rows_html을 그대로 받아 처리

원래 이 로직 전부가 tools/mall_supplier_fetch.py 안에 있었다. API 쪽에서도 같은 파싱이
필요해지면서(2026-08-26, admin_mall_supplier.py 신설) 두 벌을 만들면 반드시 갈라진다는
이 저장소의 지병(CANON.md §1 "같은 것을 두 벌 두지 않는다") 때문에 여기로 옮겼다 --
tools/ 쪽은 이제 이 모듈을 import해서 쓴다(동작은 그대로, 정의 위치만 옮겼다).

■ 왜 반대 방향(api가 tools/mall_supplier_fetch.py를 직접 import)으로 안 했나
  tools/mall_supplier_fetch.py는 **모듈 최상단**에서 `ensure_utf8_console()`을 불러
  stdout·stderr를 재포장한다 -- CLI 1회성 실행에는 맞는 처방이지만, 상시 구동 중인
  API 서버 프로세스가 그 파일을 import하면(라우터 자동 등록이 `api/` 평면을 전부
  훑는다) 그 부작용이 서버 프로세스 전체에 걸린다. 게다가 그 파일은 argparse CLI ·
  urllib 네트워크 수집 · 캐시 파일 관리까지 함께 들고 있어, API 프로세스가 그런
  CLI 전용 코드를 끌어들일 이유가 없다. 반대 방향(이 파일을 tools/가 import)은
  부작용이 없어 안전하다 -- 이 파일은 순수 함수·상수·읽기전용 SELECT 하나뿐이다.

■ 이 파일이 하지 않는 것
  네트워크 호출 없음 · 쓰기 SQL 실행 없음(SQL 문자열만 값으로 갖고 있고, 실행은
  호출부가 한다) · CLI(argparse) 없음 · import 시점 부작용 없음. `api/main.py`의
  라우터 자동 등록(`_discover_routers`)이 이 파일도 훑지만 `router`(APIRouter)가
  없어 그냥 건너뛴다(`admin_ui_common.py`와 같은 처지).

■ 실측 확정 (2026-08-26, 하네스 브라우저 실측 -- 상품 121807, EUC-KR, 공급처 8행)
  ① 행 구획 -- input[name^="pd_no["]가 있는 <tr>만 공급처 행이다. "통합관리자"를
     포함하는 <tr>이 9개였지만 마지막(업체 신규 추가용 select, 옵션 417개)은 pd_no
     입력칸이 없어 공급처가 아니다 -- 길이·셀 수가 아니라 pd_no 유무로 가른다.
  ② 발주가(balju_price)는 짐작과 반대로 확인됐다 -- []첨자가 «전혀» 없고 문서
     전체에 balju_price1 하나뿐이다. 행 구분이 불가능해 지어내지 않고 전 행 NULL로
     둔다.
  ③ ment[N] select는 옵션 3개(판매중/품절/단종), value+라벨 둘 다 존재 -- 다만
     **select 자체의 `name` 속성에 따옴표가 없다**(`<select name=ment[0]>`).
     처음엔 "가정대로"라고 적었는데 그건 **브라우저 DOM(`selectedIndex`)으로 읽은
     결과**였지, 이 파일의 정규식 파서로 실제 HTML 캐시 파일을 돌려본 결과가
     아니었다(2026-08-26 하네스 지적 -- selftest는 통과하는데 실물 캐시 121807.html을
     `tools/mall_supplier_fetch.py --from-dir`로 처음 돌리자 8행 전부
     `state=None`). 정규식이 따옴표를 요구해 실물에서 단 한 번도 안 걸렸다 --
     지금은 따옴표 유무 둘 다 받는다(`_selected_option` 참조).
  ④ 연락처 줄은 그 업체 행 HTML 안에 있는 것도 맞다 -- 다만 앞에 몰 배열 순위
     숫자가 붙어 나온다("0 (주)메종시스템 ..."). 파싱에서 그 숫자를 뗀다.
  ⑤ o_price1[N](hidden)은 `<tr>...</tr>` 태그 쌍의 «밖»(닫는 `</tr>` 뒤, 다음 행의
     `<tr>` 앞)에 있다 -- 처음엔 이걸 "그 행 안에 없는 경우가 있다"고만 적어 마치
     행 밖 전체를 뒤져야 하는 것처럼 보였는데, 이 파서의 «세그먼트»(이 행의 pd_no
     위치 -> 다음 행의 pd_no 위치 직전까지)는 `</tr>` 뒤의 숨은 입력칸들도 포함하므로
     실측 8행 전부 세그먼트 «안»에서 찾아진다(문서 전체 폴백은 한 번도 안 쓰였다).
     그래도 폴백은 방어적으로 남겨 둔다. 저장하는 공급가는 price1[N](쉼표 포함
     표기)을 파싱한 값을 원천으로 쓰고, o_price1은 교차검증(price_mismatch)에만
     쓴다.
  ⑥ **name_blob을 자르는 지점은 전화번호 «값»이 아니라 "전화"/"발주번호" «라벨»의
     위치다**(2026-08-26 실물 캐시로 처음 돌려서 발견 -- 행7 "아이보라"는 담당자
     전화번호 «값»이 비어 있다: "전화 : <br>발주번호 : ..."). 값 기준으로 자르던
     처음 버전은 이 행(하필 배열의 마지막 행이라 다음 pd_no 경계가 없어 세그먼트가
     문서 끝까지 이어진다)에서 잘라낼 지점을 못 찾아 **다음 "업체 신규 추가" 섹션의
     잔여 텍스트까지 통째로 연락처에 삼켰다**. `_parse_contact` 참조.
  `tools/mall_supplier_fetch.py --selftest`가 이 실측값(8개 행)을 그대로 검증한다
  (검증 코드 자체는 옮기지 않았다 -- CLI 진입점 소관으로 남겨둔다). **픽스처는
  캐시 파일(`.cache/mall_supplier/121807.html`)에서 실제 `<tr>`을 뽑아 만든 것이다**
  -- ③⑥ 두 결함 다 "합성 마크업으로 만든 selftest는 통과하는데 실물은 실패"로
  드러났으므로, 이후로는 합성 마크업을 손으로 짓지 않는다(연락처 개인정보만
  자리표시자로 치환).
"""
import re

from sqlalchemy import text

# 몰의 재고상태(판매중/품절/단종, ment[N] select 라벨) -> 기존 product_supplier_prices.
# supply_state 어휘('가능'/'품절'/'문의', api/price_parser.py._resolve_state와 동일 값역).
# _reprice()가 `s == '가능'`으로 최저가 후보를 고르므로, 몰의 '판매중'을 그대로 넣으면
# 그 비교가 하나도 안 맞아 몰 수집분이 전부 "가능한 공급처 없음"으로 밀려난다 -- 그래서
# 정규화해서 넣는다. 원문(판매중/품절/단종 구분)은 mall_state_raw가 그대로 보존한다.
STATE_MAP = {"판매중": "가능", "품절": "품절", "단종": "품절"}

# 업체명 자리에 재고 상태값이 들어오는 오염 -- 실물 데이터에서 실재한다(2026-08-26,
# 100건 캐시 수집 중 12건, 전부 pd_no[0] 행 <b>재고있음</b> -- companyid=herosys 링크로
# 보면 실제로는 한 계정의 표시 이름이 몰 쪽에서 깨진 것으로 보인다). 이건 공급처가
# 아니라 재고 상태값이다 -- products.supplier 컬럼에서도 같은 성격의 오염이 1,331건
# 있었다(CLAUDE.md 데이터 절 참조). 매칭 실패(unmatched)로 섞으면 "새 공급처로 등록해야
# 하나"로 오인한다 -- resolve_supplier()가 별도 match_kind("excluded_stock_status")로
# 갈라 호출부가 "제외"로 따로 셀 수 있게 한다.
#
# 어휘는 **하드코딩 한 단어("재고있음")로 끝내지 않는다** -- 이 페이지가 이미 정의한
# 재고상태 어휘(STATE_MAP의 판매중/품절/단종)에 그 대칭꼴(재고있음/재고없음 -- 실측된
# 것과 그 반대말)을 더한 것으로 한정했다. "재고나라" 같은 진짜 상호가 있을 수 있어
# (지시서 경고) 부분/포함 일치는 쓰지 않고 **정확히 일치**만 거른다 -- 아래 정규식은
# 문자열 맨 앞이 이 토큰과 같고 그 다음이 공백이거나 문자열 끝인 경우만 잡는다
# ("재고나라"는 "재고" 다음이 "있음"이 아니라 "나라"라 애초에 안 걸리고, "재고있음상사"
# 처럼 공백 없이 이어지는 것도 다음 글자가 공백/끝이 아니므로 안 걸린다 -- 실제 오염
# 형태인 "재고있음 herosys"·"재고있음" 단독만 정확히 잡는다).
STOCK_STATUS_TOKENS = set(STATE_MAP) | {"재고있음", "재고없음"}
_STOCK_STATUS_RE = re.compile(
    r'^(?:%s)(?=\s|$)' % '|'.join(re.escape(t) for t in
                                    sorted(STOCK_STATUS_TOKENS, key=len, reverse=True)))

# 2026-08-31 사장님 확정 -- 이 오염 중 «herosys» 계정 하나는 "회사가 아닌 값"이
# 아니라 "회사명이 깨져 나온 것"이었다("재고있음 herosys"는 suppliers.supplier_id=444
# 주식회사 팝콘컴퓨터와 같은 계정). 전수(2,959개 캐시) 실측 -- 이 오염이 실제로
# 관측된 값은 "재고있음 herosys" «단 하나뿐»(426행, 다른 토큰·다른 계정은 0건)이라
# herosys 이외 계정은 아직 확인된 사실이 없다. 아래 SELF_STOCK_ACCOUNTS와
# resolve_supplier()가 처리한다 -- 이 표에 없는 나머지는 여전히 excluded_stock_status.
CORP_TOKENS = ("주식회사", "주시회사", "(주)", "㈜")

# 클릭나라 특례 -- docs/supplier-consolidation-2026-08-25.md 8-3-1, 사장님 확정
# ("기존 id 2와 다른 곳으로 본다"에서 "같은 곳이다 -- 합친다"로 오후에 정정됐다).
# '클릭나라'/'(주)클릭나라' 두 표기 모두 supplier_id=2로 잇는다. 495((주)클릭나라)는
# 그 결정으로 '중지' 상태로 접힌 동일 업체라 새 몰 수집분도 거기로 보내면 안 된다.
CLICK_NARA_SUPPLIER_ID = 2

# 자사 재고 특례 -- 사장님 확정(2026-08-31, 지시서 원문: "「재고있음 herosys」와
# 「주식회사 팝콘컴퓨터(supplier_id=444)」는 같은 계정이다"). 회사명 칸이
# STOCK_STATUS_TOKENS로 깨져 나오는 행 중 «herosys» 계정(companyid=herosys 링크로
# 실측 -- tools/mall_supplier_fetch.py의 _STOCK_STATUS_ROW_HTML 주석 참조)은 새
# 공급처가 아니라 이미 있는 444(주식회사 팝콘컴퓨터)다. 전화번호로는 못 잇는다 --
# 444는 order_phone 010-6330-3544인데 이 행은 010-9923-8834로 다르다(2026-08-31
# 실측, 426행 전부 동일값). **근거는 오직 사장님의 위 확인 하나뿐이다.**
#
# 클릭나라 특례와 같은 모양으로 "이름 문자열"이 아니라 "계정 식별자 -> supplier_id"
# 고정 사전을 쓴다 -- 회사명 칸이 이미 깨져 있어 이름 매칭이 원천적으로 성립하지
# 않기 때문이다(정규화·포함 일치를 시도해도 "herosys"라는 문자열 자체가 suppliers.name
# 그 무엇과도 안 닮았다).
#
# 키는 STOCK_STATUS_TOKENS 토큰 다음에 오는 «나머지 문자열»(소문자, 공백 트림)이다
# -- 앞의 토큰 자체가 무엇인지는 안 가린다("재고있음 herosys"뿐 아니라 가정상
# "품절 herosys"·"단종 herosys"가 와도 같은 계정으로 잇는다). 이렇게 일반화한 이유:
# 이 오염은 몰이 그 상품의 «현재 재고 상태»를 (엉뚱한 자리에) 그대로 흘려보낸 것으로
# 보이므로 토큰은 상품 상태에 따라 바뀔 수 있다 -- 실제 상태 판정 자체는 이 사전과
# 무관하게 state_raw/state 필드가 이미 정확히 담당한다, 여기서 가리는 것은 "그 값을
# «누구 몫»으로 볼지"뿐이다. herosys가 아닌 다른 나머지 문자열은 이 사전에 없으므로
# 여전히 excluded_stock_status로 빠진다(다른 계정도 같은 오염을 낸다는 것은 아직
# 확인된 사실이 아니다 -- 지어내지 않는다. 지금까지 실측된 값은 "herosys" 하나뿐).
#
# ⚠ resolve_supplier()는 "이 행이 «누구 것인가»"만 답한다. 아래 둘은 호출부 책임이다
# (CLICK_NARA_SUPPLIER_ID도 같은 경계 -- 이 함수는 한 행만 보고 값을 매기지, 그
# 값을 실제로 쓸지·다른 데이터를 덮어쓸지는 판단하지 않는다):
#   ① 같은 상품 안에 이미 «정상 라벨»로 이 supplier_id에 매칭되는 다른 행이 있으면
#      (2026-08-31 실측 4건 -- 110585·118517·119574·121957: "재고있음 herosys" 행과
#      "주식회사 팝콘컴퓨터 Tpop1234 통합관리자" 행이 «서로 다른 idx·가격·재고상태»로
#      «같은 상품 안에» 공존한다) 자사 재고 행까지 그대로 쓰면 PSP_UPSERT의
#      UNIQUE(product_code, supplier_id) 충돌로 나중 처리되는 행이 앞 행을 덮어써
#      «정상 행의 값이 조용히 사라진다»(idx가 큰 쪽이 나중이라 방향도 예측 불가).
#      resolve_supplier()는 형제 행을 모르므로 이 충돌을 못 막는다 -- 호출부가 같은
#      상품의 다른 행을 먼저 훑어야 한다(tools/mall_supplier_fetch.py의 run() 참조).
#   ② 이 행의 연락처(전화·발주번호·contact_raw)를 suppliers에 그대로 채우면 안 된다
#      -- "재고있음 herosys"의 발주번호(010-9923-8834)·원문 그 자체("재고있음
#      herosys")는 이미 확보된 444의 진짜 담당자 정보(Tpop1234 통합관리자·
#      010-6330-3544)보다 못한 값이다. "같은 계정"이라는 확인은 «가격을 어느 회사
#      것으로 볼지»에 대한 확인이지 "이 전화번호로 담당자 연락처를 덮어써도 된다"는
#      확인이 아니다 -- 잃을 게 있는 곳에서는 손대지 않는다.
SELF_STOCK_ACCOUNTS = {"herosys": 444}


# ==================================================================== 파싱 ==
_ROW_RE = re.compile(r'name=["\']pd_no\[(\d+)\]["\']')


def _attr(seg: str, name: str):
    """<input name="X" ... value="Y"> -- 속성 순서가 뒤바뀐 형태도 찾는다
    (api/mall.py._field()와 같은 패턴)."""
    for pat in (r'name=["\']%s["\'][^>]*value=["\']([^"\']*)["\']',
                r'value=["\']([^"\']*)["\'][^>]*name=["\']%s["\']'):
        m = re.search(pat % re.escape(name), seg)
        if m:
            return m.group(1)
    return None


def _selected_option(seg: str, select_name: str):
    """<select name="X">...</select> 안 selected 옵션의 (value속성, 라벨텍스트).

    둘 다 돌려주고 호출부가 STATE_MAP과 일치하는 쪽을 쓴다.

    ⚠ **name 속성에 따옴표가 없을 수 있다**(2026-08-26 실물 재검증 -- 상품 121807
    캐시로 처음 돌려 보고서야 드러남). 실제 마크업은 `<select name=ment[0]>`처럼
    따옴표가 «전혀 없다». 처음 버전은 `name=["\\']%s["\\']`(따옴표 필수)였는데,
    그러면 이 정규식이 실물에서 단 한 번도 매치하지 못해 **8행 전부 재고상태
    판정 불가(None)**가 됐다 -- selftest는 따옴표 있는 합성 픽스처로 만들어져
    있어 이 결함을 못 잡았다. 지금은 따옴표 유무 둘 다 받는다."""
    m = re.search(
        r'<select\b[^>]*\bname=["\']?%s["\']?(?=[\s>])[^>]*>(.*?)</select>'
        % re.escape(select_name), seg, re.S)
    if not m:
        return None, None
    block = m.group(1)
    for opt in re.finditer(r'<option\b([^>]*)>(.*?)</option>', block, re.S):
        attrs, label = opt.groups()
        if re.search(r'\bselected\b', attrs):
            vm = re.search(r'value=["\']([^"\']*)["\']', attrs)
            return (vm.group(1) if vm else None), re.sub(r'<[^>]+>', '', label).strip()
    return None, None


_SELECT_BLOCK_RE = re.compile(r'<select\b.*?</select>', re.S | re.I)


def _strip_select_blocks(seg: str) -> str:
    """<select>...</select> 전체(옵션 라벨 포함)를 지운다.

    raw HTML을 태그만 벗기면(_strip_tags) select 안의 모든 <option> 텍스트가 선택
    여부와 무관하게 그대로 남는다(예: "판매중품절단종") -- 사람이 보는 화면에는 선택된
    라벨 하나만 보이지만, 원문에는 셋 다 있다. 연락처 파싱 전에 이 잡음을 걷어내지
    않으면 회사명 앞에 엉뚱한 글자가 붙는다."""
    return _SELECT_BLOCK_RE.sub(' ', seg)


def _strip_tags(seg: str) -> str:
    return re.sub(r'<[^>]+>', ' ', seg)


def _parse_contact(visible_text: str):
    """'0 (주)메종시스템 Tmaison 통합관리자 전화 : 02-706-0102 발주번호 : 01027874718'
    -> (name_blob, phone, order_phone).

    name_blob은 회사명+담당자 표기가 섞인 원문 그대로다 -- 분리는 resolve_supplier()가
    suppliers 목록과 대조해서 한다(회사명 사전 없이는 어디서 자를지 알 수 없다).
    맨 앞의 몰 배열 순위 숫자(실측 2026-08-26 -- "0 (주)메종시스템 ...")는 여기서 뗀다 --
    순위는 이미 idx로 따로 갖고 있고, 남겨두면 회사명 매칭을 방해한다.

    ⚠ **name_blob을 자르는 기준은 "전화"·"발주번호" «라벨»의 위치이지, 전화번호
    «값»의 위치가 아니다**(2026-08-26 실물 재검증으로 발견 -- 상품 121807 캐시,
    행7 "아이보라"). 처음 버전은 전화번호 «값»이 매치된 지점(`m_phone.start()`)에서
    잘랐는데, 실물에는 담당자 전화번호가 비어 있는 공급처가 실재한다
    ("전화 : <br>발주번호 : 010-7238-1220..." -- 콜론 뒤에 숫자가 없다). 값 매치가
    실패하면 `cut`이 `len(visible_text)`로 떨어져 name_blob이 **이 행의 나머지
    전체**(가격·리베이트·로그·삭제·발주가 입력칸)를 삼켰고, 하필 이 행이 배열의
    «마지막 행»이라 다음 pd_no 경계가 없어 세그먼트가 문서 끝까지 이어지는 바람에
    **다음 "업체 신규 추가" 섹션의 잔여 텍스트("신규입력 지정 업체명 재고 판매가격
    리베이트 등록 업체명 : ...")까지** 통째로 붙어 나왔다. 라벨 위치로 자르면 값의
    유무와 무관하게 항상 올바른 지점에서 끊긴다(라벨 자체는 값이 비어도 항상 있다)."""
    m_label = re.search(r'(전화|발주번호)\s*[:：]', visible_text)
    m_phone = re.search(r'전화\s*[:：]\s*([0-9\-]{7,20})', visible_text)
    m_order = re.search(r'발주번호\s*[:：]\s*([0-9\-]{7,20})', visible_text)
    phone = m_phone.group(1) if m_phone else None
    order_phone = m_order.group(1) if m_order else None
    cut = m_label.start() if m_label else len(visible_text)
    name_blob = re.sub(r'\s+', ' ', visible_text[:cut]).strip()
    name_blob = re.sub(r'^\d+\s*', '', name_blob)   # 선두 순위 숫자 제거(실측 ④)
    return (name_blob or None), phone, order_phone


def _to_int(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if not s or not re.fullmatch(r"-?\d+", s):
        return None
    return int(s)


def _to_pct(s):
    if s is None:
        return None
    s = str(s).strip().rstrip("%")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_rows(html: str) -> list:
    """product_com_list.php 응답(또는 그 일부 -- pd_no 있는 <tr>들을 포함한 조각) ->
    업체 행 목록.

    2026-08-26 하네스 브라우저 실측(상품 121807)으로 구조가 확정됐다 -- 모듈 docstring
    §실측 확정을 본다. 요약:
      · 행 구획 -- input[name^="pd_no["]가 있는 <tr>만 공급처 행이다. `_ROW_RE`가
        pd_no[N] 패턴만 매치하므로 "업체 신규 추가" 행(pd_no 없음, select 옵션 417개)은
        애초에 positions에 안 들어간다 -- 별도 필터가 필요 없다.
      · 발주가(order_price)는 행 구분이 불가능해(첨자 없음, 문서에 balju_price1 하나뿐)
        항상 None이다 -- 지어내지 않는다.
      · 공급가(o_price)는 price1[N](쉼표 포함 표기)을 파싱한 값이 원천이다. o_price1[N]
        (hidden)은 `</tr>` 뒤(다음 행 앞)에 있어 세그먼트 안에서 찾아진다(문서 전체
        폴백은 방어적으로만 남겨둔다) -- 교차검증(price_mismatch)에 쓴다.
      · select의 `name` 속성은 따옴표가 없다(`<select name=ment[0]>`). `_selected_option`이
        따옴표 유무 둘 다 받는다 -- 안 받으면 재고상태가 전 행 판정 불가(None)가 된다
        (2026-08-26 실물 캐시로 처음 돌려서 발견한 결함, 모듈 docstring §실측 확정 ③).
      · 연락처 줄 앞의 몰 배열 순위 숫자는 `_parse_contact`가 뗀다. name_blob을 자르는
        지점은 전화번호 «값»이 아니라 "전화"/"발주번호" «라벨»의 위치다 -- 담당자
        전화번호가 비어 있는 행(실측 예: 배열 마지막 행)이 있어, 값 기준으로 자르면
        다음 pd_no 경계가 없는 마지막 행은 문서 끝(다음 섹션)까지 통째로 삼킨다
        (모듈 docstring §실측 확정 ⑥).

    각 원소: idx(몰 배열 첨자, 0=1순위) · o_price(정수, price1을 쉼표 제거해 파싱한
    공급가) · price_raw(쉼표포함 원문) · price_mismatch(o_price1이 찾아졌는데 o_price와
    다르면 True) · rebate_pct · rebate_price · order_price(발주가 -- 행 구분 불가라
    항상 None) · state_raw(몰 원문 판매중/품절/단종 또는 None) ·
    state(STATE_MAP 정규화값 또는 None) · contact_blob(연락처 줄 원문에서 순위 숫자를
    뗀 것) · phone · order_phone.
    """
    positions = {}
    for m in _ROW_RE.finditer(html):
        i = int(m.group(1))
        if i not in positions:
            # 매치 시작은 `name=` 위치(태그 중간)다 -- 태그 여는 `<`까지 되짚어야
            # _strip_tags()가 이 input 태그를 온전한 태그로 인식해 지운다. 안 그러면
            # `name="pd_no[0]" value="121807">` 조각이 "글자"로 남아 연락처 파싱을 오염시킨다.
            lt = html.rfind("<", 0, m.start())
            positions[i] = lt if lt != -1 else m.start()
    ordered = sorted(positions, key=lambda i: positions[i])
    rows = []
    for n, idx in enumerate(ordered):
        s = positions[idx]
        e = positions[ordered[n + 1]] if n + 1 < len(ordered) else len(html)
        seg = html[s:e]

        price_raw = _attr(seg, f"price1[{idx}]")
        o_price = _to_int(price_raw)   # 공급가 원천 -- price1(쉼표 포함)을 파싱한다(실측 ⑤)

        # o_price1[N](hidden)은 실측에서 행 안에 없는 경우가 있었다 -- 행 안 -> 문서
        # 전체 순으로 찾아지면 교차검증에만 쓴다(저장값 자체는 위 o_price 그대로).
        o_price_ref = _to_int(_attr(seg, f"o_price1[{idx}]"))
        if o_price_ref is None:
            o_price_ref = _to_int(_attr(html, f"o_price1[{idx}]"))
        price_mismatch = bool(o_price is not None and o_price_ref is not None
                               and o_price != o_price_ref)

        rebate_pct = _to_pct(_attr(seg, f"pp_rebate_per[{idx}]"))
        rebate_price = _to_int(_attr(seg, f"pp_rebate_price[{idx}]"))

        # 발주가(balju_price) -- 실측(2026-08-26)으로 첨자가 «전혀» 없음이 확인됐다
        # (문서 전체에 balju_price1 하나뿐, 행마다 이름이 같다). 행 구분이 안 되므로
        # 지어내지 않고 전 행 NULL로 둔다.
        order_price = None

        val, label = _selected_option(seg, f"ment[{idx}]")
        state_raw = next((x for x in (label, val) if x in STATE_MAP), None)

        contact_blob, phone, order_phone = _parse_contact(
            _strip_tags(_strip_select_blocks(seg)))

        rows.append({
            "idx": idx, "o_price": o_price, "price_raw": price_raw,
            "price_mismatch": price_mismatch,
            "rebate_pct": rebate_pct, "rebate_price": rebate_price,
            "order_price": order_price,
            "state_raw": state_raw, "state": STATE_MAP.get(state_raw),
            "contact_blob": contact_blob, "phone": phone, "order_phone": order_phone,
        })
    return rows


def cheapest_summary(rows: list):
    """한 상품의 파싱 결과에서 "판매중 최저가" 판정.

    품절·단종 공급처가 더 싸도 살 수 없다 -- 그래서 "전체 최저가"와 "실제로 살 수
    있는(판매중) 최저가"를 따로 낸다. 가격 있는 행이 하나도 없으면 None.

        cheapest_overall     가격 있는 행 중 최저(상태 무관)
        cheapest_available   그 중 state=='가능'(판매중)인 것만의 최저 -- 없으면 None
        mismatch              둘의 가격이 다른가(전체 최저가가 품절/단종에 있다는 뜻)
    """
    priced = [r for r in rows if r["o_price"] is not None]
    if not priced:
        return None
    cheapest_overall = min(priced, key=lambda r: r["o_price"])
    available = [r for r in priced if r["state"] == "가능"]
    cheapest_available = min(available, key=lambda r: r["o_price"]) if available else None
    mismatch = bool(cheapest_available is not None
                     and cheapest_available["o_price"] != cheapest_overall["o_price"])
    return {"cheapest_overall": cheapest_overall, "cheapest_available": cheapest_available,
            "mismatch": mismatch}


# ============================================================ 공급처 매칭 ==
def _normalize_name(s: str) -> str:
    """docs/supplier-consolidation-2026-08-25.md §2와 같은 정규화(법인 토큰+공백 제거)."""
    t = s or ""
    for tok in CORP_TOKENS:
        t = t.replace(tok, "")
    return re.sub(r"\s+", "", t).strip().lower()


def _flex_pattern(name: str):
    """name의 각 글자 사이에 공백 0개 이상을 허용하는 접두 매칭 패턴 -- 정규화로 같아진
    이름이 원문 어디까지인지 되짚어(remainder를 잘라내) contact_name을 뽑는 데 쓴다."""
    core = name
    for tok in CORP_TOKENS:
        core = core.replace(tok, "")
    chars = [re.escape(ch) for ch in core if not ch.isspace()]
    body = r"\s*".join(chars) if chars else re.escape(name)
    return re.compile(r"(?:주식회사|주시회사|\(주\)|㈜)?\s*" + body)


def load_suppliers(conn) -> list:
    rows = conn.execute(text(
        "SELECT supplier_id, name, status FROM suppliers")).mappings().all()
    return [dict(r) for r in rows]


def resolve_supplier(name_blob, suppliers: list):
    """(supplier_id, matched_name, contact_name잔여, match_kind) 하나.

    매칭 실패면 (None, None, name_blob, 'unmatched'). 업체명 자리에 재고 상태값이
    온 행이면 (None, None, name_blob, 'excluded_stock_status') -- 이건 "모르는
    회사"가 아니라 "애초에 회사가 아닌 값"이라 매칭을 시도하지 않는다(위
    STOCK_STATUS_TOKENS 참조). **다만 그 나머지 문자열이 SELF_STOCK_ACCOUNTS에 있는
    계정("herosys")이면** (supplier_id, matched_name, None, 'self_stock_account')
    -- 이건 "회사가 아닌 값"이 아니라 "이미 아는 회사(444)의 깨진 표시"다(2026-08-31
    사장님 확정, 위 SELF_STOCK_ACCOUNTS 참조). 우선순위: **재고 상태값 판정**(그 중
    자사 계정이면 self_stock_account, 아니면 excluded_stock_status) -> 클릭나라 특례
    -> 원문 정확 일치 -> 정규화 일치 -> 정규화 접두 일치(긴 이름부터 -- 짧은 이름이
    먼저 걸려 잘못 잘리는 것을 막는다). 활성 공급처를 우선하되 없으면 중지 상태도 쓴다
    (중지된 곳으로만 매칭되면 사람이 검토해야 한다 -- 호출부가 match_kind로 안다).

    ⚠ **self_stock_account는 "누구 것인가"만 답한다 -- "그대로 써도 되는가"는 호출부
    책임이다.** 같은 상품 안에 이 supplier_id로 이미 정상 매칭된 다른 행이 있을 수
    있고(실측 4건), 이 행의 연락처를 suppliers에 덮어쓰면 안 된다. 두 경계 모두 위
    SELF_STOCK_ACCOUNTS 주석 ①②에 있다 -- 이 함수 밖(호출부)에서 지켜야 한다.

    ⚠ **sid가 None이어도 그 행의 가격·재고상태(o_price·state)는 멀쩡히 파싱돼 있다**
    (2026-08-30 실측 -- 추천 후보 2,707건 중 47건이 product_supplier_prices에 행이
    0개였던 사고의 근본 원인 조사). 이 함수는 "회사를 못 찾았다"만 판정할 뿐 그
    데이터를 버리지 않는다 -- 버리는 지점은 호출부다: `product_supplier_prices.
    supplier_id`가 NOT NULL FK라서(db 스키마), sid가 None인 행은 애초에 그 표에 쓸
    수 없다(가짜 supplier_id를 만들어 끼워 넣지 않는다 -- CANON "suppliers 표에 가짜
    업체를 만들지 마라"). 그래서 tools/mall_supplier_fetch.py의 run()이 이 함수가
    돌려준 kind별로 **제품 단위 결과**(이 상품이 결국 공급처를 하나도 못 얻었는가)를
    따로 집계해 보고한다 -- DB에 못 쓴다고 그 사실 자체가 조용히 사라지면 안 된다.
    tools/mall_daily_sync.py 4단계는 그 결과(product_supplier_prices 행이 0개)를
    "전 공급처 품절"과 **다르게** 본다 -- 0개는 "확인해 보니 다 품절"이 아니라 "아직
    아무것도 확인 못 함"이라 자동으로 추천 후보에서 빼면 안 된다(A-115가 이미 같은
    논리로 mall_rank NULL 행을 "확인된 품절"에서 뺐다 -- 모르는 상태를 품절로 단정하지
    않는다는 원칙의 연장). unmatched로 남는 이름(예: "RSystem")을 자동으로
    `suppliers`에 등록하지도 않는다 -- 업체 등록은 사람이 `POST /api/admin/suppliers`
    (api/admin_suppliers.py)로 하는 일이다, 이 파서·수집기가 대신 판단하지 않는다.
    """
    blob = (name_blob or "").strip()
    if not blob:
        return None, None, None, "empty"
    stock_m = _STOCK_STATUS_RE.match(blob)
    if stock_m:
        account = blob[stock_m.end():].strip().lower()
        self_sid = SELF_STOCK_ACCOUNTS.get(account)
        if self_sid is not None:
            s = next((s for s in suppliers if s["supplier_id"] == self_sid), None)
            if s is not None:
                return s["supplier_id"], s["name"], None, "self_stock_account"
            # suppliers 목록에 그 id가 없으면(캐시가 낡았거나 다른 시드) 새 업체를
            # 만들지 않는다 -- 안전하게 재고상태 제외로 떨어진다(CANON "suppliers에
            # 가짜 업체를 만들지 마라"와 같은 이유).
        return None, None, blob, "excluded_stock_status"
    norm_blob = _normalize_name(blob)
    if norm_blob.startswith(_normalize_name("클릭나라")):
        return CLICK_NARA_SUPPLIER_ID, "클릭나라", blob, "click_nara_special_case"

    def _pick(cands):
        active = [c for c in cands if c["status"] == "활성"]
        return (active or cands)[0]

    exact = [s for s in suppliers if s["name"].strip() == blob]
    if exact:
        s = _pick(exact)
        return s["supplier_id"], s["name"], None, "exact"

    norm_exact = [s for s in suppliers if _normalize_name(s["name"]) == norm_blob]
    if norm_exact:
        s = _pick(norm_exact)
        return s["supplier_id"], s["name"], None, "normalized"

    # 포함 일치(접두가 아니라 어디든) -- 실제 마크업의 select 라벨·다른 텍스트가
    # 회사명 «앞»에 낄 수 있어(2026-08-26 selftest로 실제로 걸림) 문자열 시작
    # 고정(startswith/match)이 아니라 어디서든 찾는다. 긴 이름부터 시도해 짧은
    # 이름이 먼저 걸려 잘못 끊기는 것을 막는다.
    for s in sorted(suppliers, key=lambda s: -len(_normalize_name(s["name"]))):
        nn = _normalize_name(s["name"])
        if nn and nn in norm_blob:
            m = _flex_pattern(s["name"]).search(blob)
            remainder = blob[m.end():].strip() if m else None
            return s["supplier_id"], s["name"], (remainder or None), "contains"

    return None, None, blob, "unmatched"


# ================================================== product_supplier_prices ==
# (product_code, supplier_id) 당 한 행 UPSERT -- tools/mall_supplier_fetch.py(CLI)와
# api/admin_mall_supplier.py(HTTP) 둘 다 이 SQL 하나를 쓴다(두 벌이면 갈라진다).
PSP_UPSERT = text("""
    INSERT INTO product_supplier_prices
      (product_code, supplier_id, cost_price, supply_state, mall_rank,
       rebate_pct, rebate_price, order_price, mall_state_raw, fetched_at, updated_at)
    VALUES (:pc, :s, :cost, :state, :rank, :rpct, :rprice, :oprice, :sraw, :fa, now())
    ON CONFLICT (product_code, supplier_id) DO UPDATE SET
      cost_price = EXCLUDED.cost_price, supply_state = EXCLUDED.supply_state,
      mall_rank = EXCLUDED.mall_rank, rebate_pct = EXCLUDED.rebate_pct,
      rebate_price = EXCLUDED.rebate_price, order_price = EXCLUDED.order_price,
      mall_state_raw = EXCLUDED.mall_state_raw, fetched_at = EXCLUDED.fetched_at,
      updated_at = now()
""")

# 연락처는 «최신 관측값이 있으면» 덮어쓴다(COALESCE(:새값, 기존값) -- 새 값이 NULL일
# 때만 기존 값을 유지한다). suppliers의 이 컬럼들은 0066에서 열렸다(2026-08-25).
SUPPLIER_CONTACT_UPDATE = text("""
    UPDATE suppliers SET
      contact_name = COALESCE(:cn, contact_name),
      contact_phone = COALESCE(:cp, contact_phone),
      order_phone = COALESCE(:op, order_phone),
      contact_raw = COALESCE(:cr, contact_raw),
      contact_fetched_at = :fa
    WHERE supplier_id = :s
""")
