"""카카오톡 채널 · 네이버 톡톡 상담 연결 -- 2026-10-14 사장님 「카카오, 네이버 등 연동」 · 「둘 다」. **기본 꺼짐.**

손님이 카카오톡 채널이나 네이버 톡톡에 말하면 이 모듈이 받아 도구 상담(talk_agent.run_turn)에 넘기고,
답과 PC 카드를 그쪽 메시지 모양으로 바꿔 돌려준다. 상담 엔진은 홈페이지 /api/talk/chat 과 같다.
조사 문서: /mnt/project-files/카카오-네이버-연동/상담채널-연동-조사-v1.md

■ 왜 «먼저 받고 나중에 보낸다»인가
  두 곳 모두 우리 서버가 5초 안에 답해야 한다. 상담 한 턴은 최대 talk_agent.DEADLINE_SEC(25초)라서
  · 카카오: 오픈빌더 «AI 챗봇 콜백». 즉시 {"useCallback": true} 로 받고, 답은 userRequest.callbackUrl 로 한 번 보낸다.
           콜백이 승인되지 않아 callbackUrl 이 없으면 상담을 돌리지 않고 홈페이지 상담 안내로 끝낸다.
  · 네이버: 웹훅에 바로 200 을 주고, 답은 보내기 API(gw.talk.naver.com/chatbot/v1/event)로 보낸다.

■ 켜는 조건 (하나라도 없으면 404 -- 경로가 없는 것과 같다)
  · POPCORN_TALK_AGENT=1 (상담 엔진 스위치) 그리고
  · 카카오: POPCORN_CHANNEL_KAKAO=1 + POPCORN_KAKAO_SKILL_KEY (오픈빌더 스킬 헤더 X-Popcorn-Channel-Key 에 넣는 값)
  · 네이버: POPCORN_CHANNEL_NAVER=1 + POPCORN_NAVER_WEBHOOK_TOKEN (웹훅 주소 끝 경로) + POPCORN_NAVER_SEND_KEY (보내기 API 키)
  비밀값은 서버 환경 파일(/etc/popcorn-ai.env)에만 둔다. 저장소에 적지 않는다.

■ 서버가 지키는 것
  · 요청 진위: 카카오는 스킬 헤더 비밀값, 네이버는 비밀 경로. 둘 다 hmac.compare_digest 로 비교한다.
  · 콜백 주소는 https 이고 카카오 도메인일 때만 보낸다(다른 곳으로 요청을 내보내는 통로가 되지 않게).
  · 손님 ID 는 해시로만 들고 있다. 대화 기록은 talk_agent 와 같은 가림(mask)을 다시 거친다.
  · 카드는 run_turn 이 사실 묶음에서 만든 것만 바꾼다. 금액은 서버 카드 값만 쓴다.

■ 아직 하지 않는 것
  · 대화 기록은 프로세스 메모리에 둔다(uvicorn 단일 프로세스 · 재시작하면 처음부터). DB 표는 ERD 개정과 함께 다음 단계.
  · 사람 상담원 넘기기(카카오 상담톡·네이버 핸드오버), 사진 썸네일, 같은 메시지 재전송 걸러내기.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
from collections import OrderedDict
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from . import talk_agent as AG

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channel", tags=["talk-channels"])

KAKAO_FLAG = "POPCORN_CHANNEL_KAKAO"
NAVER_FLAG = "POPCORN_CHANNEL_NAVER"
NAVER_SEND_URL = "https://gw.talk.naver.com/chatbot/v1/event"
SEND_TIMEOUT_SEC = 10
MAX_CARDS = 10                    # 카카오 캐러셀 · 네이버 composite 모두 10장까지
KAKAO_TEXT_MAX = 1000             # simpleText
NAVER_TEXT_MAX = 10000            # textContent

WAIT_TEXT = "질문을 확인하고 있어요. 잠시만 기다려 주세요."
GREETING = ("안녕하세요, 팝콘PC 상담입니다. 쓰실 용도(게임·사무·영상 편집 등)와 예산을 말씀해 주시면 "
            "판매 중인 PC 가운데에서 맞는 것을 찾아 드릴게요.")
NO_CALLBACK_TEXT = "지금은 이곳에서 바로 답을 드리기 어려워요. 아래 버튼을 눌러 홈페이지에서 상담을 이어가 주세요."
NOT_TEXT = "지금은 글로 보내 주신 말씀만 읽을 수 있어요. 궁금하신 점을 글로 적어 주세요."


def _on(flag: str) -> bool:
    return AG.enabled() and os.environ.get(flag, "").strip() == "1"


def _secret(name: str) -> str:
    return os.environ.get(name, "").strip()


def _same(given: str | None, expected: str) -> bool:
    return bool(expected) and given is not None and hmac.compare_digest(given.encode(), expected.encode())


def _site() -> str:
    return os.environ.get("POPCORN_PUBLIC_BASE", "https://popcornai.co.kr").rstrip("/")


def talk_url() -> str:
    return _site() + "/mvp3/talk.html"


# ── 대화 기록 (채널 손님별) ────────────────────────────────────────────────
class Memory:
    """(채널, 손님 ID 해시) -> 최근 대화·anchor_code. 30분 동안 말이 없으면 잊는다. 최대 MAX_USERS 명."""

    TTL_SEC = 30 * 60
    MAX_USERS = 5000

    def __init__(self):
        self._d: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(channel: str, user_id: str) -> str:
        return channel + ":" + hashlib.sha256(user_id.encode()).hexdigest()[:32]

    def get(self, key: str) -> dict:
        with self._lock:
            row = self._d.get(key)
            if not row or time.monotonic() - row["at"] > self.TTL_SEC:
                self._d.pop(key, None)
                return {"turns": [], "anchor_code": None}
            return {"turns": list(row["turns"]), "anchor_code": row["anchor_code"]}

    def add(self, key: str, user_text: str, reply: str, anchor_code: int | None) -> None:
        with self._lock:
            row = self._d.pop(key, None) or {"turns": [], "anchor_code": None}
            turns = row["turns"] + [{"role": "user", "text": user_text}, {"role": "assistant", "text": reply}]
            self._d[key] = {"turns": turns[-AG.HISTORY_TURNS:], "anchor_code": anchor_code or row["anchor_code"],
                            "at": time.monotonic()}
            while len(self._d) > self.MAX_USERS:
                self._d.popitem(last=False)


MEMORY = Memory()


def answer(channel: str, user_id: str, text: str) -> dict:
    """한 턴 상담 -> run_turn 결과. 기록에는 가린 손님 말만 남긴다."""
    key = Memory.key(channel, user_id)
    past = MEMORY.get(key)
    history = [AG.Turn(role=t["role"], text=t["text"]) for t in past["turns"]]
    try:
        out = AG.run_turn(text, history, past["anchor_code"])
    except Exception as e:      # noqa: BLE001 -- 손님에게는 정해진 안내, 원문 예외는 로그에만
        log.warning("[talk_channels] %s turn failed: %s", channel, type(e).__name__)
        out = {"ok": False, "status": "failed", "reply": AG.TE.REPLY_AI_UNREADABLE, "cards": [], "anchor_code": None}
    masked, _ = AG.mask(text)
    MEMORY.add(key, masked, out.get("reply") or "", out.get("anchor_code"))
    return out


def _won(price) -> str:
    return f"판매가 {price:,}원" if isinstance(price, int) and price > 0 else "가격 확인 중"


def _clip(s: str | None, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _card_lines(card: dict) -> str:
    lines = [_won(card.get("price"))]
    spec = card.get("spec")
    if isinstance(spec, dict):          # 화면 카드와 같은 키(mockups/mvp3/live-model.js cardSpecRows)
        bits = [str(spec[k]).strip() for k in ("cpu", "gpu") if spec.get(k)]
        bits += [f"{label} {spec[k]}GB" for k, label in (("ram_gb", "램"), ("ssd_gb", "SSD")) if spec.get(k)]
        if bits:
            lines.append(" · ".join(bits))
    return "\n".join(lines)


# ── 카카오 (오픈빌더 스킬 응답 2.0) ───────────────────────────────────────
def _kakao_callback_ok(url: str | None) -> bool:
    if not url:
        return False
    u = urlparse(url)
    hosts = [h.strip().lower() for h in os.environ.get("POPCORN_KAKAO_CALLBACK_HOSTS", "kakao.com,kakaoenterprise.com").split(",")
             if h.strip()]
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in hosts)


def kakao_outputs(out: dict) -> dict:
    outputs = [{"simpleText": {"text": _clip(out.get("reply"), KAKAO_TEXT_MAX) or AG.TE.REPLY_AI_UNREADABLE}}]
    items = []
    for c in (out.get("cards") or [])[:MAX_CARDS]:
        buttons = []
        if c.get("mall_url"):
            buttons.append({"action": "webLink", "label": "자세히 보기", "webLinkUrl": c["mall_url"]})
        buttons.append({"action": "webLink", "label": "홈페이지 상담", "webLinkUrl": talk_url()})
        items.append({"title": _clip(c.get("name"), 50), "description": _clip(_card_lines(c), 230), "buttons": buttons})
    if items:
        outputs.append({"carousel": {"type": "textCard", "items": items}})
    return {"version": "2.0", "template": {"outputs": outputs}}


def _kakao_link_reply(text: str) -> dict:
    return {"version": "2.0", "template": {"outputs": [{"textCard": {
        "description": text, "buttons": [{"action": "webLink", "label": "홈페이지 상담", "webLinkUrl": talk_url()}]}}]}}


def kakao_finish(user_id: str, text: str, callback_url: str) -> None:
    body = kakao_outputs(answer("kakao", user_id, text))
    try:
        r = requests.post(callback_url, json=body, timeout=SEND_TIMEOUT_SEC)
        if r.status_code >= 300:
            log.warning("[talk_channels] kakao callback http %s", r.status_code)
    except requests.RequestException as e:
        log.warning("[talk_channels] kakao callback failed: %s", type(e).__name__)


@router.post("/kakao/skill")
async def kakao_skill(request: Request, tasks: BackgroundTasks):
    """오픈빌더 스킬. 5초 안에 답해야 하므로 상담은 뒤에서 돌리고 콜백으로 보낸다."""
    if not _on(KAKAO_FLAG) or not _secret("POPCORN_KAKAO_SKILL_KEY"):
        raise HTTPException(404, "Not Found")
    if not _same(request.headers.get("X-Popcorn-Channel-Key"), _secret("POPCORN_KAKAO_SKILL_KEY")):
        raise HTTPException(403, "Forbidden")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "Bad Request")
    ureq = (body or {}).get("userRequest") or {}
    text = (ureq.get("utterance") or "").strip()[:2000]
    user_id = str(((ureq.get("user") or {}).get("id")) or "")
    if not user_id:
        raise HTTPException(400, "Bad Request")
    if not text:
        return _kakao_link_reply(NOT_TEXT)
    callback_url = ureq.get("callbackUrl")
    if not _kakao_callback_ok(callback_url):
        return _kakao_link_reply(NO_CALLBACK_TEXT)
    tasks.add_task(kakao_finish, user_id, text, callback_url)
    return {"version": "2.0", "useCallback": True, "data": {"text": WAIT_TEXT}}


# ── 네이버 톡톡 (챗봇 API v1) ─────────────────────────────────────────────
def naver_messages(out: dict) -> list[dict]:
    """보내기 API 본문들(user 는 보낼 때 채운다). 글 하나 + 카드가 있으면 composite 하나."""
    msgs = [{"textContent": {"text": _clip(out.get("reply"), NAVER_TEXT_MAX) or AG.TE.REPLY_AI_UNREADABLE}}]
    comps = []
    for c in (out.get("cards") or [])[:MAX_CARDS]:
        buttons = []
        if c.get("mall_url"):
            buttons.append({"type": "LINK", "data": {"title": "자세히 보기", "url": c["mall_url"], "mobileUrl": c["mall_url"]}})
        buttons.append({"type": "LINK", "data": {"title": "홈페이지 상담", "url": talk_url(), "mobileUrl": talk_url()}})
        comps.append({"title": _clip(c.get("name"), 200), "description": _clip(_card_lines(c), 1000), "buttonList": buttons})
    if comps:
        msgs.append({"compositeContent": {"compositeList": comps}})
    return msgs


def naver_send(user: str, message: dict) -> bool:
    try:
        r = requests.post(NAVER_SEND_URL, json={"event": "send", "user": user, **message},
                          headers={"Authorization": _secret("POPCORN_NAVER_SEND_KEY"),
                                   "Content-Type": "application/json;charset=UTF-8"},
                          timeout=SEND_TIMEOUT_SEC)
        ok = r.status_code == 200 and (r.json() or {}).get("success") is True
        if not ok:
            log.warning("[talk_channels] naver send http %s", r.status_code)
        return ok
    except (requests.RequestException, ValueError) as e:
        log.warning("[talk_channels] naver send failed: %s", type(e).__name__)
        return False


def naver_finish(user: str, text: str) -> None:
    for m in naver_messages(answer("naver", user, text)):
        if not naver_send(user, m):
            break


@router.post("/naver/webhook/{token}")
async def naver_webhook(token: str, request: Request, tasks: BackgroundTasks):
    """톡톡 웹훅. 손님 글은 바로 200 으로 받고, 답은 보내기 API 로 따로 보낸다."""
    if not _on(NAVER_FLAG) or not _secret("POPCORN_NAVER_SEND_KEY"):
        raise HTTPException(404, "Not Found")
    if not _same(token, _secret("POPCORN_NAVER_WEBHOOK_TOKEN")):
        raise HTTPException(404, "Not Found")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "Bad Request")
    event, user = (body or {}).get("event"), str((body or {}).get("user") or "")
    if event == "open":
        return {"event": "send", "textContent": {"text": GREETING}}
    if event != "send" or not user:
        return {}
    text = (((body.get("textContent") or {}).get("text")) or "").strip()[:2000]
    if not text:
        return {"event": "send", "textContent": {"text": NOT_TEXT}}
    tasks.add_task(naver_finish, user, text)
    return {}
