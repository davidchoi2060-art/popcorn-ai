"""카카오톡 채널 · 네이버 톡톡 상담 연결(api/talk_channels) -- 2026-10-14 사장님 「카카오, 네이버 등 연동」. 기본 꺼짐.

① 스위치·비밀값이 하나라도 없으면 404, 비밀값이 틀리면 거절.
② 5초 제한: 카카오는 즉시 useCallback 으로 받고 답은 콜백으로, 네이버는 즉시 200 을 주고 답은 보내기 API 로.
③ 카카오 콜백 주소가 없거나 카카오 도메인이 아니면 상담을 돌리지 않고 홈페이지 상담 안내로 끝낸다.
④ 카드는 run_turn 카드에서만 만들고 금액은 서버 값 그대로. 대화 기록은 손님별로 이어지고 개인정보는 가린다.
상담 엔진(run_turn)과 바깥 요청(requests.post)은 흉내 낸다.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import talk_channels as CH

ENV = {"POPCORN_TALK_AGENT": "1", "POPCORN_CHANNEL_KAKAO": "1", "POPCORN_KAKAO_SKILL_KEY": "k-secret",
       "POPCORN_CHANNEL_NAVER": "1", "POPCORN_NAVER_WEBHOOK_TOKEN": "n-token", "POPCORN_NAVER_SEND_KEY": "n-send"}
CALLBACK = "https://bot-api.kakao.com/v1/callback/abc"
CARD = {"ref": "P1", "product_code": 101, "name": "게이밍 PC A", "price": 1_498_000, "mall_url": "https://shop.example/p/101",
        "spec": {"cpu": "라이젠5 7500F", "gpu": "RTX 5060", "ram_gb": 16, "ssd_gb": 500}}
TURN = {"ok": True, "status": "ok", "reply": "게임용으로 이 PC를 권해요.", "cards": [CARD], "anchor_code": 101}


def _client():
    app = FastAPI()
    app.include_router(CH.router)
    return TestClient(app)


def _kakao(text="게임용 PC 150만원", user="u1", callback=CALLBACK):
    req = {"utterance": text, "user": {"id": user}}
    if callback:
        req["callbackUrl"] = callback
    return {"userRequest": req, "bot": {"id": "b1"}}


def _ok_response():
    r = MagicMock(status_code=200)
    r.json.return_value = {"success": True, "resultCode": "00"}
    return r


class Base(unittest.TestCase):
    def setUp(self):
        CH.MEMORY = CH.Memory()
        self.env = patch.dict(os.environ, ENV, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.c = _client()


class Switches(Base):
    def test_off_without_engine_switch(self):
        with patch.dict(os.environ, {"POPCORN_TALK_AGENT": ""}):
            self.assertEqual(self.c.post("/api/channel/kakao/skill", json=_kakao(),
                                         headers={"X-Popcorn-Channel-Key": "k-secret"}).status_code, 404)
            self.assertEqual(self.c.post("/api/channel/naver/webhook/n-token", json={"event": "open"}).status_code, 404)

    def test_off_without_channel_switch_or_secret(self):
        with patch.dict(os.environ, {"POPCORN_CHANNEL_KAKAO": "0", "POPCORN_NAVER_SEND_KEY": ""}):
            self.assertEqual(self.c.post("/api/channel/kakao/skill", json=_kakao(),
                                         headers={"X-Popcorn-Channel-Key": "k-secret"}).status_code, 404)
            self.assertEqual(self.c.post("/api/channel/naver/webhook/n-token", json={"event": "open"}).status_code, 404)

    def test_wrong_secret_is_refused_without_running_turn(self):
        with patch.object(CH.AG, "run_turn") as rt:
            self.assertEqual(self.c.post("/api/channel/kakao/skill", json=_kakao(),
                                         headers={"X-Popcorn-Channel-Key": "nope"}).status_code, 403)
            self.assertEqual(self.c.post("/api/channel/kakao/skill", json=_kakao()).status_code, 403)
            self.assertEqual(self.c.post("/api/channel/naver/webhook/wrong",
                                         json={"event": "send", "user": "x", "textContent": {"text": "hi"}}).status_code, 404)
        rt.assert_not_called()


class Kakao(Base):
    H = {"X-Popcorn-Channel-Key": "k-secret"}

    def test_callback_flow(self):
        with patch.object(CH.AG, "run_turn", return_value=TURN) as rt, patch.object(CH.requests, "post",
                                                                                    return_value=_ok_response()) as post:
            r = self.c.post("/api/channel/kakao/skill", json=_kakao(), headers=self.H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"version": "2.0", "useCallback": True, "data": {"text": CH.WAIT_TEXT}})
        rt.assert_called_once()
        url, body = post.call_args.args[0], post.call_args.kwargs["json"]
        self.assertEqual(url, CALLBACK)
        outs = body["template"]["outputs"]
        self.assertEqual(outs[0]["simpleText"]["text"], TURN["reply"])
        item = outs[1]["carousel"]["items"][0]
        self.assertEqual(item["title"], "게이밍 PC A")
        self.assertIn("판매가 1,498,000원", item["description"])
        self.assertIn("램 16GB", item["description"])
        self.assertEqual(item["buttons"][0]["webLinkUrl"], CARD["mall_url"])

    def test_no_callback_does_not_run_turn(self):
        with patch.object(CH.AG, "run_turn") as rt:
            r = self.c.post("/api/channel/kakao/skill", json=_kakao(callback=None), headers=self.H)
        rt.assert_not_called()
        card = r.json()["template"]["outputs"][0]["textCard"]
        self.assertEqual(card["description"], CH.NO_CALLBACK_TEXT)
        self.assertTrue(card["buttons"][0]["webLinkUrl"].endswith("/mvp3/talk.html"))

    def test_foreign_callback_host_is_not_called(self):
        for bad in ("https://evil.example/cb", "http://bot-api.kakao.com/cb", "https://kakao.com.evil.example/cb"):
            with patch.object(CH.AG, "run_turn") as rt, patch.object(CH.requests, "post") as post:
                r = self.c.post("/api/channel/kakao/skill", json=_kakao(callback=bad), headers=self.H)
            self.assertNotIn("useCallback", r.json(), bad)
            rt.assert_not_called()
            post.assert_not_called()

    def test_no_cards_means_text_only(self):
        with patch.object(CH.AG, "run_turn", return_value=dict(TURN, cards=[])), \
                patch.object(CH.requests, "post", return_value=_ok_response()) as post:
            self.c.post("/api/channel/kakao/skill", json=_kakao(), headers=self.H)
        self.assertEqual(len(post.call_args.kwargs["json"]["template"]["outputs"]), 1)

    def test_engine_crash_sends_fixed_reply(self):
        with patch.object(CH.AG, "run_turn", side_effect=RuntimeError("db down: secret detail")), \
                patch.object(CH.requests, "post", return_value=_ok_response()) as post:
            self.c.post("/api/channel/kakao/skill", json=_kakao(), headers=self.H)
        text = post.call_args.kwargs["json"]["template"]["outputs"][0]["simpleText"]["text"]
        self.assertEqual(text, CH.AG.TE.REPLY_AI_UNREADABLE)


class Naver(Base):
    URL = "/api/channel/naver/webhook/n-token"

    def test_open_greets_synchronously(self):
        r = self.c.post(self.URL, json={"event": "open", "user": "nu1"})
        self.assertEqual(r.json()["textContent"]["text"], CH.GREETING)

    def test_send_replies_through_send_api(self):
        with patch.object(CH.AG, "run_turn", return_value=TURN), \
                patch.object(CH.requests, "post", return_value=_ok_response()) as post:
            r = self.c.post(self.URL, json={"event": "send", "user": "nu1", "textContent": {"text": "게임용 PC"}})
        self.assertEqual((r.status_code, r.json()), (200, {}))
        self.assertEqual(post.call_count, 2)
        first, second = (c.kwargs for c in post.call_args_list)
        self.assertEqual(post.call_args_list[0].args[0], CH.NAVER_SEND_URL)
        self.assertEqual(first["headers"]["Authorization"], "n-send")
        self.assertEqual(first["json"], {"event": "send", "user": "nu1", "textContent": {"text": TURN["reply"]}})
        comp = second["json"]["compositeContent"]["compositeList"][0]
        self.assertEqual(comp["title"], "게이밍 PC A")
        self.assertIn("판매가 1,498,000원", comp["description"])
        self.assertEqual(comp["buttonList"][0]["data"]["url"], CARD["mall_url"])

    def test_failed_text_send_stops_cards(self):
        bad = MagicMock(status_code=500)
        bad.json.return_value = {}
        with patch.object(CH.AG, "run_turn", return_value=TURN), patch.object(CH.requests, "post", return_value=bad) as post:
            self.c.post(self.URL, json={"event": "send", "user": "nu1", "textContent": {"text": "게임용 PC"}})
        self.assertEqual(post.call_count, 1)

    def test_other_events_are_acknowledged_only(self):
        with patch.object(CH.AG, "run_turn") as rt:
            for ev in ({"event": "leave", "user": "nu1"}, {"event": "echo", "user": "nu1"},
                       {"event": "send", "user": "nu1", "imageContent": {"imageUrl": "https://x/y.png"}}):
                self.assertEqual(self.c.post(self.URL, json=ev).status_code, 200)
        rt.assert_not_called()


class Memory(Base):
    def test_history_continues_per_user_and_masks_contacts(self):
        seen = []

        def fake(text, history, anchor):
            seen.append(([(t.role, t.text) for t in history], anchor))
            return TURN

        with patch.object(CH.AG, "run_turn", side_effect=fake):
            CH.answer("naver", "nu1", "제 번호는 010-1234-5678 이에요. 게임용 PC")
            CH.answer("naver", "nu1", "더 싸게")
            CH.answer("naver", "nu2", "사무용")
            CH.answer("kakao", "nu1", "안녕하세요")
        self.assertEqual(seen[0], ([], None))
        hist, anchor = seen[1]
        self.assertEqual(anchor, 101)
        self.assertEqual([r for r, _ in hist], ["user", "assistant"])
        self.assertNotIn("010-1234-5678", hist[0][1])
        self.assertEqual(seen[2], ([], None))     # 다른 손님
        self.assertEqual(seen[3], ([], None))     # 같은 ID 라도 다른 채널

    def test_user_id_is_not_kept_in_clear(self):
        with patch.object(CH.AG, "run_turn", return_value=TURN):
            CH.answer("kakao", "plain-user-id", "hi")
        self.assertFalse(any("plain-user-id" in k for k in CH.MEMORY._d))

    def test_forgets_after_ttl_and_caps_users(self):
        m = CH.Memory()
        m.MAX_USERS = 2
        for u in ("a", "b", "c"):
            m.add(CH.Memory.key("naver", u), "q", "a", None)
        self.assertEqual(len(m._d), 2)
        k = CH.Memory.key("naver", "c")
        m._d[k]["at"] -= m.TTL_SEC + 1
        self.assertEqual(m.get(k)["turns"], [])


if __name__ == "__main__":
    unittest.main()
