"""고객 상담 예외 입력 대응 -- 막지 않고 받아서 PC 상담으로 이끈다(2026-10-11 사장님 지시).

사장님 원문: *"고객단은 지금 예외 상황에 대한 대처가 필요해.. 정말 이상한 질문... 무조건
차단하면 안되거든.. 충분히 대응할 수 있도록.. LLM 한계는 일단 초반에 다 풀거거든.."*

■ 원칙
  - **거르지 않는다.** 이상한 말·엉뚱한 말·욕·외국어·아주 긴 글도 AI 가 그대로 읽는다.
    이 모듈은 AI 앞에서 문을 닫는 층이 아니라, AI 가 읽은 뒤 «무엇을 덧붙이고 무엇을
    바꿔 말할지» 정하는 층이다.
  - 판정은 **고객 문장 원문(정규식)과 검증된 state 만** 본다. AI 출력은 보지 않는다
    (talk_rules ⑤ 와 같은 방식 -- 같은 문장에는 같은 대응이 나간다).
  - 서버가 문장을 «바꿔» 말하는 것은 두 경우뿐이다(안전상 꼭 필요한 최소 보호):
      ① 자해·자살 신호  -- 상담 대신 도움받을 곳(자살예방상담전화 109)을 먼저 알린다.
      ② 역할 바꾸기 시도 -- 「이전 지시 무시」「시스템 프롬프트 알려 줘」 같은 말에 AI 가
         내부 지시문을 읊거나 다른 역할을 맡지 않게, 정해진 한 문장으로 답한다.
    나머지는 AI 문장을 살리고 **한 줄을 덧붙이거나**, AI 가 PC 이야기로 못 받았을 때만
    정해진 안내로 바꾼다.
  - 모르면 사람에게 넘긴다 -- `handoff_offer` 가 참이면 화면이 「사람 상담 남기기」
    (구매 상담 신청 양식, 주제 「기타」)를 띄운다.
  - 관리자가 나중에 모아 볼 수 있게 `talk_intent_hits.matched_terms` 에 `예외:<종류>`
    꼬리표를 남긴다(관리자 「고객 문의 · 보관 견적」이 읽는다).

■ 이 파일에 없는 것
  - 빈 입력·아주 긴 글의 길이 처리는 `api/talk.py`(parse_talk 입구)가 한다. 여기는 꼬리표
    이름과 안내 문장만 갖는다.
  - 잡담이 길어질 때의 단계(3회 허용 -> 4회 안내)는 `talk_schema.advance_smalltalk` 그대로다.
    다만 5회째부터 «답하지 않음»(침묵)은 오늘 지시로 걷었다 -- `api/talk.py` `_reply_text`.
"""
import re

EXCEPTION_TAG = "예외:"

# (종류 키, 관리자 화면 이름) -- 순서가 곧 고객 문장을 바꿀 때의 우선순위다.
KINDS: tuple[tuple[str, str], ...] = (
    ("self_harm", "자해·자살 신호"),
    ("prompt_injection", "역할 바꾸기 시도"),
    ("human", "사람 상담 요청"),
    ("personal_info", "민감 정보 입력"),
    ("privacy_request", "남의 개인정보 요청"),
    ("order_status", "주문·결제·환불 확인 요청"),
    ("abuse", "욕설·장난"),
    ("gibberish", "알아볼 수 없는 입력"),
    ("foreign", "외국어"),
    ("contradiction", "모순된 조건"),
    ("repeat", "같은 말 반복"),
    ("link", "링크 붙여 넣기"),
    ("competitor", "다른 쇼핑몰 비교"),
    ("too_long", "아주 긴 글"),
    ("off_topic", "주제 밖 이야기"),
    ("smalltalk_long", "잡담 계속"),
    ("ai_unreadable", "AI 응답 처리 실패"),
    ("empty", "빈 입력"),
)
_KIND_KEYS = tuple(k for k, _ in KINDS)


def kind_label(key: str) -> str | None:
    return next((label for k, label in KINDS if k == key), None)


# ── 고객에게 보이는 문장 -- 쉬운 존댓말 · 두 문장 이내 · 부품·가격·약속 없음 ─────────────
REPLY_EMPTY = ("어떤 PC가 필요하신지 편하게 말씀해 주세요."
               " 예를 들어 「배그 하고 예산은 150만원」처럼 적어 주시면 돼요.")
REPLY_SELF_HARM = ("많이 힘드신 것 같아요. 혼자 견디기 어려우시면 자살예방상담전화 109(24시간)에"
                   " 전화해 이야기해 보세요. PC 상담은 언제든 다시 도와드릴게요.")
REPLY_INJECTION = ("저는 팝콘PC의 PC 견적 상담만 도와드릴 수 있어요."
                   " 쓰실 용도와 예산을 알려 주시면 맞는 PC를 찾아볼게요.")
REPLY_HUMAN = ("사람과 상담을 원하시면 아래 「사람 상담 남기기」에 연락처를 남겨 주세요."
               " 담당자가 확인한 뒤 연락드려요.")
REPLY_ABUSE = ("불편한 일이 있으셨다면 죄송해요. 원하시는 PC 조건을 말씀해 주시면 바로 찾아볼게요.")
REPLY_GIBBERISH = ("입력하신 내용을 잘 알아보지 못했어요."
                   " 「롤 하고 예산 100만원」처럼 용도와 예산을 적어 주시면 바로 찾아볼게요.")
NOTE_FOREIGN = ("지금은 한국어로만 상담하고 있어요. 쓰실 용도와 예산을 한국어로 알려 주시면"
                " 맞는 PC를 찾아 드릴게요.")
# 「예산 안에서 가장 가까운 구성」은 예산 안 카드가 하나도 없을 때 거짓 약속이 됐다(2026-10-12 코덱스 24조합 검수 3번:
# 고사양 60만원에 이 문장 바로 아래 「60만원 안에는 맞는 PC가 없어요」와 102만원 넘는 카드). 예산 안 여부는 카드가 말한다.
NOTE_CONTRADICTION = ("말씀하신 예산으로는 원하시는 사양을 맞추기 어려울 수 있어요."
                      " 예산 안에 맞는 PC가 없으면 그렇다고 알려 드리고, 조건에 맞는 가장 낮은 가격의 PC를 함께 보여 드릴게요."
                      " 사양이 더 중요하면 예산을 알려 주세요.")
NOTE_LOW_BUDGET = ("말씀하신 예산으로는 새 조립 PC를 찾기 어려울 수 있어요."
                   " 찾는 대로 보여 드리고, 맞는 상품이 없으면 그렇다고 말씀드릴게요.")
NOTE_TOO_LONG = ("글이 길어 앞부분과 끝부분을 합쳐 %s자만 읽었어요."
                 " 빠진 내용이 있으면 용도와 예산부터 나눠서 말씀해 주세요.")
# 2026-10-11 코덱스 예외 55개(1815) 36~55번 대응
NOTE_PERSONAL = "카드번호·주민번호·비밀번호 같은 정보는 상담 창에 적지 않으셔도 돼요."
NOTE_PERSONAL_MASKED = " 적어 주신 번호는 가려서 읽었어요."
NOTE_PRIVACY = ("다른 분의 연락처·주소·주문 내역 같은 개인정보는 알려 드릴 수 없어요."
                " 문의는 아래 「사람 상담 남기기」로 남겨 주세요.")
NOTE_ORDER_STATUS = ("주문·결제·환불 처리 상태는 제가 여기서 확인할 수 없어요."
                     " 아래 「사람 상담 남기기」에 연락처를 남겨 주시면 담당자가 확인해 연락드려요.")
NOTE_LINK = "링크 안의 내용은 제가 열어 볼 수 없어요. 비교할 구성과 금액을 글로 적어 주시면 함께 볼게요."
NOTE_REPEAT = ("같은 말씀을 여러 번 하셨네요. 제 답이 부족했다면 원하시는 조건을 하나만 더 알려 주시거나,"
               " 아래 「사람 상담 남기기」를 눌러 주세요.")
# 다른 쇼핑몰 비교에 AI 가 「저희도 맞춰드릴 수 있습니다」처럼 약속하면 그 문장을 걷고 이 한 줄을 앞에 둔다.
NOTE_COMPETITOR = "다른 곳 가격은 제가 확인할 수 없어요."
NOTE_SMALLTALK_LONG = "PC가 필요하시면 언제든 용도와 예산을 말씀해 주세요."
REPLY_AI_UNREADABLE = ("방금 말씀을 제가 잘 정리하지 못했어요. 한 번만 다르게 말씀해 주시거나,"
                       " 사람 상담을 원하시면 아래 「사람 상담 남기기」를 눌러 주세요.")

# 예산 판정 경계 -- 견적을 지어내는 수가 아니라 «어려울 수 있다»고 미리 말할지의 문턱이다.
# 실제 가능 여부는 추천(엔진의 budget.verdict)이 판정한다 -- 여기 수는 화면에 나가지 않는다.
VERY_LOW_BUDGET_WON = 300_000
CONTRADICTION_BUDGET_WON = 700_000

# ── 판정 정규식 ────────────────────────────────────────────────────────────────
_SELF_HARM = re.compile(r"자살|죽고\s*싶|죽어\s*버리|목숨을?\s*끊|자해|살기\s*싫")
_INJECTION = re.compile(
    r"(이전|앞|위)의?\s*(지시|명령|규칙|프롬프트)\S*\s*(을|를)?\s*(무시|잊)|"
    r"(지시|명령|규칙)\S*\s*(을|를)?\s*무시|"
    r"시스템\s*프롬프트|프롬프트\s*(를|을)?\s*(알려|보여|출력)|"
    r"너는?\s*(이제|지금부터)\s*\S*\s*(이야|야|이다|역할)|"
    r"개발자\s*모드|탈옥|jail\s*break|"
    r"ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+(instructions|prompts?)|"
    r"system\s+prompt|developer\s+mode|\bDAN\b",
    re.I)
_HUMAN = re.compile(
    r"(상담원|상담사|사람|직원|담당자|사장님|매니저)\S{0,3}\s*(이랑|하고|과|와|한테|에게|좀|으로|로)?\s*"
    r"(연결|바꿔|바꾸|얘기|이야기|통화|상담|불러|대화)|"
    r"(전화|통화)\s*(상담|하고\s*싶|할\s*수|가능|되나|번호|주세요|부탁)|"
    r"(실제|진짜)\s*사람")
# 강한 욕설만 센다. 「존나 좋은」「미친 성능」 같은 강조어는 욕으로 세지 않는다.
_ABUSE = re.compile(
    r"씨\s*발|시\s*발|ㅅ\s*ㅂ|ㅆ\s*ㅂ|씨\s*바|병\s*신|ㅂ\s*ㅅ|개\s*새\s*끼|개\s*색\s*기|좆|ㅈ\s*같|지\s*랄|"
    r"꺼\s*져|닥\s*쳐|엿\s*먹|fuck|shit|bitch",
    re.I)
# 민감 정보 -- 번호 자체(가려서 읽는다)와 그 이름을 꺼낸 말(안내 한 줄)을 따로 본다.
_RRN = re.compile(r"(?<!\d)\d{6}\s*-\s*[1-8]\d{6}(?!\d)")
_CARD = re.compile(r"(?<!\d)\d{4}(?:[\s-]?\d{4}){3}(?!\d)")
_PERSONAL_WORD = re.compile(r"주민\s*(등록)?\s*번호|카드\s*번호|계좌\s*비밀\s*번호|비밀\s*번호|cvc|cvv|보안\s*코드", re.I)
MASK = "[가림]"
# 남의 개인정보 -- 제3자(사장·직원·다른 고객 …) + 연락처·주소·주문 내역 + 알려/보여 달라는 말
_PRIVACY_REQ = re.compile(
    r"(사장|대표|직원|담당자|기사|다른\s*(고객|사람|분|회원|손님)|남의|그\s*사람)\S{0,6}\s*"
    r"(개인\s*)?(휴대\s*폰|핸드\s*폰|전화\s*번호|연락처|번호|집\s*주소|주소|주문\s*내역|구매\s*내역|개인\s*정보|이름|계좌)"
    r"\S{0,4}\s*(좀\s*)?(알려|보여|가르쳐|줘|주세요|공개|뭐)")
# 내 주문의 처리 상태 확인 -- 정책 질문(「배송 며칠?」)은 판매 안내 자료가 답하므로 여기 넣지 않는다.
_ORDER_STATUS = re.compile(
    r"(결제|입금|송금|주문|구매)\s*(했는데|했으니|했어요|했어|했습니다|한\s*지|완료\s*했)|"
    r"환불\S{0,4}\s*(언제|아직|안\s*(들어|와|됐|되))|"
    r"(주문|결제|입금)\S{0,4}\s*(안\s*(보|떠|돼|되|들어)|확인\s*(해|좀|부탁))|"
    r"(배송|택배)\S{0,4}\s*(어디|언제\s*와|안\s*와|조회)")
_LINK = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(com|co\.kr|kr|net)\b", re.I)
_COMPETITOR = re.compile(r"다나와|쿠팡|11번가|지마켓|G마켓|옥션|컴퓨존|아이코다|네이버\s*쇼핑|"
                         r"다른\s*(쇼핑몰|업체|곳|가게|사이트)|타\s*(업체|사이트)", re.I)
_REPEAT_WORD = re.compile(r"(\S{1,8})(?:\s+\1){2,}")
REPEAT_SAME_TURNS = 2       # 같은 문장을 이전에 두 번 보냈으면(이번이 세 번째) 반복으로 본다
_HANGUL_SYL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")
_DIGIT = re.compile(r"[0-9]")
_CJK = re.compile(r"[一-鿿぀-ヿ]")
_OTHER_SCRIPT = re.compile(r"[Ѐ-ԯ֐-ۿऀ-෿฀-๿]")
# PC 상담에서 흔한 영문 약어 -- 이것만 있는 문장은 외국어가 아니다(「rtx 4070 pc」).
_PC_LATIN = re.compile(
    r"\b(pc|cpu|gpu|ram|ssd|hdd|rtx|gtx|rx|amd|intel|ryzen|i[3579]|4k|qhd|fhd|uhd|fps|hz|"
    r"lol|pubg|gb|tb|ddr\d?|nvme|m\.?2|os|win\d*|windows|ok|okay|ai|as|a/s|vs)\b",
    re.I)
_KEYBOARD_MASH = re.compile(r"asdf|qwer|zxcv|hjkl|sdfg|dfgh|uiop", re.I)
_JAMO_ONLY = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]")


def _letters_ok(t: str) -> bool:
    return bool(_HANGUL_SYL.search(t) or _LATIN.search(t) or _DIGIT.search(t)
                or _CJK.search(t) or _OTHER_SCRIPT.search(t))


def is_gibberish(text: str) -> bool:
    """뜻을 담은 글자가 없는 입력 -- 기호·이모지·낱자모만, 또는 자판 두드리기.

    「ㅋㅋㅋ」「ㅠㅠ」 같은 낱자모만 있는 문장도 여기 든다. 다만 AI 는 그래도 읽는다 --
    대화 중 웃음일 수 있으니, 고객 문장을 바꾸는 것은 AI 가 PC 이야기로 못 받았을 때뿐이다.
    """
    t = (text or "").strip()
    if not t:
        return False
    if not _letters_ok(t):
        return True        # 기호·이모지·낱자모만
    if _HANGUL_SYL.search(t) or _DIGIT.search(t):
        return False
    latin = re.sub(r"[^A-Za-z]", "", t)
    if latin and _KEYBOARD_MASH.search(latin) and not _PC_LATIN.search(t):
        return True
    # 모음이 하나도 없는 5자 이상 영문 덩어리(「sdfghjkl」)
    words = re.findall(r"[A-Za-z]{5,}", t)
    return bool(words) and all(not re.search(r"[aeiouy]", w, re.I) for w in words) \
        and not _PC_LATIN.search(t)


def foreign_language(text: str) -> str | None:
    """한국어가 거의 없는 문장의 언어 묶음 -- 'en' | 'ja' | 'zh' | 'other' | None.

    PC 약어(rtx·ssd·4k …)와 숫자만 있는 문장은 외국어가 아니다.
    """
    t = (text or "").strip()
    if not t or _HANGUL_SYL.search(t):
        return None
    if re.search(r"[぀-ヿ]", t):
        return "ja"
    if _CJK.search(t):
        return "zh"
    if _OTHER_SCRIPT.search(t):
        return "other"
    rest = _PC_LATIN.sub(" ", t)
    words = re.findall(r"[A-Za-z]{2,}", rest)
    if len(words) >= 2 and not is_gibberish(t):
        return "en"
    return None


def mask_personal(text: str) -> tuple[str, bool]:
    """주민번호·카드번호 모양의 숫자를 가린다 -> (가린 문장, 가렸는가).

    AI 에게 보내기 전·문의 기록에 남기기 전에 부른다. 번호를 «읽지» 않아도 상담은 된다.
    """
    t = text or ""
    out = _CARD.sub(MASK, _RRN.sub(MASK, t))
    return out, out != t


def _norm(t: str) -> str:
    return re.sub(r"[\s.,!?~]+", "", (t or "").lower())


def repeated(text: str, history: list | None) -> str | None:
    """같은 말 반복 -- 'turns'(같은 문장을 거듭 보냄) | 'words'(한 문장 안 되풀이) | None."""
    n = _norm(text)
    if n and history:
        same = sum(1 for role, t in history if role == "user" and _norm(t) == n)
        if same >= REPEAT_SAME_TURNS:
            return "turns"
    if _REPEAT_WORD.search(text or ""):
        return "words"
    return None


def _budget(state) -> int | None:
    b = getattr(state, "budget_won", None)
    return b if isinstance(b, int) and b > 0 else None


def contradiction(text: str, state, top_spec_re, uhd_re) -> str | None:
    """예산과 요구가 서로 맞지 않는가 -- 'low_budget' | 'top_spec' | None.

    한쪽을 지우지 않는다(talk.py 모듈 docstring 「모순되는 조건은 둘 다 남긴다」).
    여기서는 «어려울 수 있다»고 미리 말할지만 정한다. 실제 판정은 추천 엔진이 한다.
    """
    b = _budget(state)
    if b is None or getattr(state, "budget_bound", None) == "이상":
        return None
    t = text or ""
    usages = list(getattr(state, "usages", None) or [])
    wants_top = bool(top_spec_re.search(t) or uhd_re.search(t)
                     or any("고사양" in u for u in usages))
    if wants_top and b < CONTRADICTION_BUDGET_WON:
        return "top_spec"
    if b < VERY_LOW_BUDGET_WON:
        return "low_budget"
    return None


def classify(text: str, *, state=None, pc=None, stage: str | None = None,
             truncated: bool = False, top_spec_re=None, uhd_re=None,
             masked: bool = False, history: list | None = None) -> list[str]:
    """고객 문장 -> 예외 종류 키 목록(우선순위 순서). 빈 목록이면 평범한 문장이다."""
    t = text or ""
    found: set[str] = set()
    if _SELF_HARM.search(t):
        found.add("self_harm")
    if _INJECTION.search(t):
        found.add("prompt_injection")
    if _HUMAN.search(t):
        found.add("human")
    if masked or _PERSONAL_WORD.search(t) or MASK in t:
        found.add("personal_info")
    if _PRIVACY_REQ.search(t):
        found.add("privacy_request")
    if _ORDER_STATUS.search(t):
        found.add("order_status")
    if _ABUSE.search(t):
        found.add("abuse")
    if is_gibberish(t):
        found.add("gibberish")
    if foreign_language(t):
        found.add("foreign")
    if state is not None and top_spec_re is not None and uhd_re is not None \
            and contradiction(t, state, top_spec_re, uhd_re):
        found.add("contradiction")
    if repeated(t, history):
        found.add("repeat")
    if _LINK.search(t):
        found.add("link")
    if _COMPETITOR.search(t):
        found.add("competitor")
    if truncated:
        found.add("too_long")
    if pc is False:
        found.add("off_topic")
    if stage == "silent":
        found.add("smalltalk_long")
    return [k for k in _KIND_KEYS if k in found]


def respond(reply: str, kinds: list[str], *, pc, text: str = "", state=None,
            top_spec_re=None, uhd_re=None, read_len: int = 0, masked: bool = False,
            history: list | None = None) -> tuple[str, bool]:
    """(지금까지 정해진 고객 문장, 예외 종류) -> (내보낼 문장, 사람 상담 길을 띄울지).

    바꿔 말하는 것은 자해 신호·역할 바꾸기 시도 둘뿐이고(안전 최소 보호), 나머지는
    AI 가 PC 이야기로 받았으면 그 문장을 살린 채 한 줄만 덧붙인다.
    """
    ks = set(kinds)
    handoff = bool(ks & {"human", "ai_unreadable", "privacy_request", "order_status"})
    if "repeat" in ks and repeated(text, history) == "turns":
        handoff = True
    if "self_harm" in ks:
        return REPLY_SELF_HARM, False
    if "prompt_injection" in ks:
        return REPLY_INJECTION, handoff
    out = reply or ""
    if "human" in ks:
        out = REPLY_HUMAN if pc is not True else (out.rstrip() + " " + REPLY_HUMAN).strip()
    elif "abuse" in ks and pc is not True:
        out = REPLY_ABUSE
    elif "gibberish" in ks and pc is not True:
        out = REPLY_GIBBERISH
    if "competitor" in ks:
        out = _drop_promises(out)
    if "foreign" in ks and NOTE_FOREIGN not in out:
        out = (out.rstrip() + " " + NOTE_FOREIGN).strip()
    if "contradiction" in ks and state is not None and top_spec_re is not None:
        kind = contradiction(text, state, top_spec_re, uhd_re)
        note = NOTE_CONTRADICTION if kind == "top_spec" else NOTE_LOW_BUDGET
        if note not in out:
            out = (out.rstrip() + " " + note).strip()
    if "personal_info" in ks:
        out = _add(out, NOTE_PERSONAL + (NOTE_PERSONAL_MASKED if masked else ""))
    # 2026-10-11 개발 서버: AI 의 「알려 드릴 수 없어요」 뒤에 같은 말이 한 번 더 붙었고, 주문 확인
    # 문의에는 결제 안내 넉 줄 뒤에 확인 불가 안내가 또 붙었다. PC 이야기가 아니면 안내 한 줄로 바꾼다.
    if "privacy_request" in ks:
        out = NOTE_PRIVACY if pc is not True else _add(out, NOTE_PRIVACY)
    if "order_status" in ks and "human" not in ks:
        no_pc = not list(getattr(state, "usages", None) or [])
        out = NOTE_ORDER_STATUS if no_pc else _add(out, NOTE_ORDER_STATUS)
    if "link" in ks:
        out = _add(out, NOTE_LINK)
    if "repeat" in ks and repeated(text, history) == "turns":
        out = _add(out, NOTE_REPEAT)
    if "too_long" in ks and read_len:
        out = _add(out, NOTE_TOO_LONG % format(read_len, ","))
    return out, handoff


_SENT = re.compile(r"(?<=[.!?。])\s+")


def _drop_promises(out: str) -> str:
    """가게가 해 주겠다는 약속 문장(talk_rules.PROMISE_PATTERNS)을 걷는다 -- 걷었으면 확인 불가 한 줄을 앞에 둔다.
    남의 가격을 모르는 채 「맞춰 드릴게요」라고 하면 근거 없는 약속이다(2026-10-12 개발 서버)."""
    from .talk_rules import PROMISE_PATTERNS     # talk_rules 는 이 모듈을 읽지 않는다 -- 순환 없음
    sents = [x for x in _SENT.split(out or "") if x.strip()]
    kept = [x for x in sents if not any(p.search(x) for _label, p in PROMISE_PATTERNS)]
    if len(kept) == len(sents):
        return out
    kept = [x for x in kept if NOTE_COMPETITOR not in x]
    if kept:      # 걷은 문장을 가리키던 「그전에」는 따라 뺀다
        kept[0] = re.sub(r"^\s*그\s*전에\s*,?\s*", "", kept[0])
    return " ".join([NOTE_COMPETITOR] + kept).strip()


def _add(out: str, note: str) -> str:
    return out if note in out else (out.rstrip() + " " + note).strip()


def tags(kinds: list[str]) -> list[str]:
    return [EXCEPTION_TAG + k for k in kinds]
