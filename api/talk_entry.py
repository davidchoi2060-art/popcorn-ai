"""상담 갈래 -- 새 PC 찾기 / 쓰던 PC 업그레이드 / 부품·구성 물어보기(2026-10-11).

사장님 2026-10-11 「위 채팅 내용을 보고 적당한 화면으로 보내야지」 · 코덱스 1816 보강6 의견 v1
(입구는 하나, 안에 시작 단추 셋). 세 갈래는 같은 대화 화면에서 이어지고, 갈래는 그 대화의 첫
응대만 바꾼다 -- 새 PC 는 빠진 조건부터, 업그레이드는 지금 PC 의 불편한 점부터, 부품 질문은
설명부터. 갈래는 화면이 왕복하는 chat_flow 에 남아 다음 턴에도 이어진다.

판정 순서(빠른 것부터, 새 AI 호출은 없다):
  ① 단추   화면이 보낸 `entry`(고객이 고른 것)
  ② 유지   지난 턴에 정한 갈래(chat_flow.entry)
  ③ 규칙   이번 문장의 낱말(아래 classify)
  ④ 상태   기존 AI 판정이 용도·예산을 읽었으면 새 PC 찾기
  ⑤ 묻기   그래도 모르고 PC 이야기면 한 번만 되묻는다(ASK)
문장은 로그에 남기지 않는다 -- 갈래 키와 판정 출처만 남긴다.
"""
import re

KEYS = ("new_pc", "upgrade", "parts")
LABELS = {"new_pc": "새 PC 찾기", "upgrade": "쓰던 PC 업그레이드", "parts": "부품·구성 물어보기"}

_UPGRADE = re.compile(
    r"업그레이드|업글|쓰던|지금\s*쓰는|쓰고\s*있는|사용\s*중인|기존\s*(?:pc|컴|본체)|내\s*(?:pc|컴|본체)"
    r"|느려|버벅|렉\s*(?:이|걸)|증설|교체|갈아\s*끼|(?:만|도)\s*바꾸|추가로\s*(?:달|장착)", re.I)
_PART = re.compile(r"cpu|gpu|그래픽|vga|램|메모리|ssd|hdd|하드|파워|케이스|쿨러|메인\s*보드|보드|부품|구성|사양", re.I)
_ASK = re.compile(r"차이|뭐가\s*(?:달라|다르|좋)|역할|무슨\s*(?:뜻|의미)|뭐예요|뭔가요|뭐야|뭐에요|호환|궁금|설명|알려\s*(?:줘|주)")
_NEW = re.compile(
    r"새\s*(?:pc|컴|컴퓨터|본체)|새로\s*(?:사|맞|장만)|맞추|맞춰|장만|구매|구입|사려|살려|사고\s*싶|추천|견적"
    r"|\d+\s*만\s*원?|예산|게임용|사무용|편집용|작업용|방송용|조립\s*(?:pc|컴)", re.I)

ASK = ("새 PC를 찾으시는지, 쓰던 PC를 업그레이드하시는지, 부품·구성이 궁금하신지 알려 주시면"
       " 그에 맞춰 도와드릴게요.")

PROMPT = {
    "new_pc": "[상담 갈래 -- 새 PC 찾기] 고객은 새 PC 를 찾는다. 이미 말한 용도·예산은 다시 묻지 않고,"
              " 빠진 것 중 하나만 묻는다.",
    "upgrade": "[상담 갈래 -- 쓰던 PC 업그레이드] 고객은 지금 쓰는 PC 를 고치거나 부품을 바꾸려 한다."
               " 어떤 작업에서 불편한지와 지금 구성을 먼저 묻는다. 새 PC 구매를 먼저 권하지 않는다.",
    "parts": "[상담 갈래 -- 부품·구성 물어보기] 고객은 부품이나 구성을 이해하려 한다. 물은 것에 먼저"
             " 쉽게 답한다. 질문만으로 예산을 묻거나 새 PC 추천을 시작하지 않는다.",
}


def classify(text: str) -> str | None:
    """이번 문장의 낱말로 갈래를 고른다. 모르면 None(지어내지 않는다)."""
    t = text or ""
    if _UPGRADE.search(t):
        return "upgrade"
    asks_part = bool(_PART.search(t) and _ASK.search(t))
    wants_new = bool(_NEW.search(t))
    if asks_part and not wants_new:
        return "parts"
    if wants_new:
        return "new_pc"
    return None


def from_flow(raw) -> tuple[str | None, bool]:
    """화면이 보낸 chat_flow -> (정해 둔 갈래, 이미 물었나)."""
    raw = raw if isinstance(raw, dict) else {}
    entry = raw.get("entry")
    return (entry if entry in KEYS else None), raw.get("entry_asked") is True


def prompt_block(entry: str | None) -> str:
    return PROMPT.get(entry or "", "")
