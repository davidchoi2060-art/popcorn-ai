"""손님 화면 그대로 대화를 다시 돌려 본다 -- 개발 서버 공개 API 만 쓴다(읽기 전용, 비밀값 없음).

2026-10-16 중헌 님이 개발 서버에서 겪은 대화(「배그와 롤 150만원」 -> 보관 견적 불러오기 -> 「가장 비싼 GPU로
바꿔줘」 -> 「저 PC중에 성능으로 가장 좋은 걸로」 -> 「오른쪽 화면에 뜬 세가지 PC는 뭐야?」)를 화면(live-flow.js)과
같은 본문으로 보낸다. 대화 화면처럼 오른쪽 카드와 고른(불러온) PC 를 display_context 로 함께 보낸다.
결과는 GitHub 주석(::notice)과 표준 출력으로 남긴다.

환경변수: BASE(기본 https://dev.popcornai.co.kr)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "https://dev.popcornai.co.kr").rstrip("/")
UA = "popcorn-screen-replay/1"


def post(path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            data = json.loads(e.read() or b"{}") if e.code != 502 else {}
            if e.code == 429:
                time.sleep(int(data.get("retry_after_sec") or 30) + 1)
                continue
            return e.code, data
    return 429, {}


def cards_of(rec: dict) -> list[dict]:
    out = []
    for cs in rec.get("card_sets") or []:
        if isinstance(cs, dict) and cs.get("kind") == "sold":
            out += [i for i in cs.get("items") or [] if isinstance(i, dict) and type(i.get("product_code")) is int]
    return out


def show(items: list[dict]) -> str:
    return "\n".join("  - [%s] %s · %s원" % (i["product_code"], i.get("name"), format(i.get("price") or 0, ","))
                     for i in items[:6])


def one(text: str) -> int:
    """문장 하나를 화면과 같은 본문으로 보내고 응답(설명·카드·조건)을 그대로 남긴다 -- 점검에서 이상한 답을 다시 볼 때."""
    if text.startswith("@long:"):
        # 「@long:반복할 글|끝 문장|글자 수」 -- 아주 긴 글 점검(E16·E17)
        body, tail, n = (text[6:].split("|") + ["", "20000"])[:3]
        text = (body * (int(n) // max(1, len(body)) + 1))[:int(n)] + "\n" + tail
    if text.startswith("@fb:"):
        # 「@fb:고객 문장」 -- 부품 직접 고르기 시작(/api/mvp3/free-build/start) 응답을 그대로 본다
        code, res = post("/api/mvp3/free-build/start", {"text": text[4:]})
        out = "HTTP %s\n%s" % (code, json.dumps(res, ensure_ascii=False, indent=1)[:6000])
        print(out)
        for i in range(0, len(out), 1300):
            print("::notice title=문장 하나 %d::%s" % (i // 1300 + 1,
                  out[i:i + 1300].replace("%", "%25").replace("\r", "").replace("\n", "%0A")))
        return 0
    code, res = post("/api/talk/parse", {"text": text, "history": [], "defer_answer": True})
    keep = {k: res.get(k) for k in ("ok", "agent", "reply", "answer", "explain_only", "state", "missing", "fallback",
                                    "truncated", "agent_meta", "exceptions", "silent", "agent_cards", "action")}
    out = "HTTP %s 글자 %d\n%s" % (code, len(text), json.dumps(keep, ensure_ascii=False, indent=1)[:6000])
    print(out)
    for i in range(0, len(out), 1300):
        print("::notice title=문장 하나 %d::%s" % (i // 1300 + 1,
              out[i:i + 1300].replace("%", "%25").replace("\r", "").replace("\n", "%0A")))
    return 0


def main() -> int:
    if os.environ.get("TEXT"):
        return one(os.environ["TEXT"])
    log: list[str] = []
    state, flow, history, right, selected = None, None, [], [], None

    def turn(text: str, screen: str) -> None:
        nonlocal state, flow, right
        ctx = {"screen": screen, "source": "saved_quote" if selected else "recommendation",
               "cards": [{"product_code": i["product_code"]} for i in right[:6]],
               "selected": {"product_code": selected["product_code"]} if selected else None}
        body = {"text": text, "state": state, "chat_flow": flow, "history": history[-6:], "defer_answer": True,
                "display_context": ctx}
        code, res = post("/api/talk/parse", body)
        log.append("손님: %s" % text)
        if code != 200:
            log.append("  (HTTP %s %s)" % (code, str(res)[:200]))
            return
        reply = "\n\n".join(x for x in ((res.get("answer") or "").strip(), (res.get("reply") or "").strip()) if x)
        log.append("AI: %s" % reply)
        history.extend([{"role": "user", "text": text[:1000]}, {"role": "assistant", "text": reply[:300]}])
        if res.get("shown_note"):
            history.append({"role": "assistant", "text": res["shown_note"]})
        flow = res.get("chat_flow")
        if isinstance(res.get("state"), dict) and not res.get("explain_only") and not res.get("missing"):
            state = res["state"]
            rb = {"state": state}
            if res.get("nav"):
                rb.update(nav=res["nav"], anchor_code=(selected or (right[0] if right else {})).get("product_code"))
            c2, rec = post("/api/grid/recommend", rb)
            new = cards_of(rec) if c2 == 200 else []
            picked = [c for c in res.get("agent_cards") or [] if type(c.get("product_code")) is int]
            if picked and not {c["product_code"] for c in picked} <= {c["product_code"] for c in new}:
                new = picked + [c for c in new if c["product_code"] not in {p["product_code"] for p in picked}]
            if new:
                right = new
                log.append("  [오른쪽 카드가 바뀜]\n" + show(right))
        elif res.get("state"):
            state = res["state"]

    turn("배그와 롤을 하려는데 150만원 정도로 추천해줘", "results")
    # 보관 견적 불러오기: 같은 용도의 265K·5070 Ti 판매 PC 를 고른 것으로 둔다(중헌 님 화면의 「다이아 265/5070Ti」).
    c, rec = post("/api/grid/recommend", {"state": {**(state or {"usages": ["게임"]}), "budget_won": 3_500_000,
                                                    "budget_bound": "이하"}})
    pool = cards_of(rec) if c == 200 else []
    selected = next((i for i in pool if "5070" in str(i.get("name"))), pool[0] if pool else None)
    log.append("[견적 불러오기] %s" % (show([selected]).strip() if selected else "(고를 PC 없음)"))
    history = []                        # 화면 load() 는 대화 기록을 비운다
    turn("가장 비싼 GPU로 바꿔줘", "final")
    turn("저 PC중에 성능으로 가장 좋은 걸로", "final")
    turn("오른쪽 화면에 뜬 세가지 PC는 뭐야? 그럼?", "final")
    text = "\n".join(log)
    print(text)
    for i in range(0, len(text), 1300):
        print("::notice title=화면 대화 다시 돌리기 %d::%s" % (i // 1300 + 1,
              text[i:i + 1300].replace("%", "%25").replace("\r", "").replace("\n", "%0A")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
