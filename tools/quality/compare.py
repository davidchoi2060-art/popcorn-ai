"""상담 AI 답 품질 비교 -- 같은 질문을 우리 상담 AI 와 일반 AI 에 던지고 AI 심판이 나란히 채점한다.

왜 있나 (2026-10-11 사장님):
  > "그냥 일반 LLM 쓰다가 이걸 썼더니.. 바보같은 소리나.. 하고.. 헤매면.. 정말 다시는 안돌아 와.."
  손님의 비교 대상은 챗GPT 같은 일반 AI 다. 그래서 «일반 AI 보다 못한 답»을 하나라도 내면 빨간불이다.

흐름 (질문 하나당)
  ① 우리 답     POST {BASE}/api/talk/parse  -- 화면(mockups/mvp3/live-flow.js)과 같은 본문.
                손님이 보는 말풍선 = answer + 빈 줄 + reply (silent 면 말풍선 없음). 화면 규칙 그대로.
  ② 일반 AI 답  Claude API, 시스템 지시문 없이 질문만. 모델은 api/llm.py 의 Claude 기본 모델
                (`default_model=`)을 그대로 읽는다 -- 따로 적으면 한쪽만 바뀐다.
  ③ 심판        같은 모델이 두 답을 A/B 로 받아(순서는 질문마다 섞는다 -- 앞자리 편향 방지)
                「우리가 못함 / 비슷함 / 우리가 나음」과 이유 한 줄을 낸다.

지키는 것
  - 개발 서버에는 상담 API 호출만 한다. 그 호출이 남기는 상담 기록(talk 히트)은 손님 한 명이
    물은 것과 같은 흔적이다. 다른 데이터는 바꾸지 않는다.
  - 방문자 호출 한도(api/access_gate: 기본 분당 5 · 하루 40)를 지킨다 -- 13초 간격으로 부르고,
    분 한도 429 는 기다렸다 다시, 하루 한도 429 는 「측정 못함」으로 적는다(지어내지 않는다).
  - 측정 못한 질문은 판정하지 않는다. 「측정 못함」이 있으면 그 사실을 표 머리에 밝힌다.

쓰는 법
  python tools/quality/compare.py run --subset all --shard 1/3 --out out/s1
  python tools/quality/compare.py combine out/s1 out/s2 out/s3 --report report.md --gate
환경변수: BASE(기본 https://popcornai.co.kr) · ANTHROPIC_API_KEY · QUALITY_MODEL(선택)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = Path(__file__).with_name("questions.json")
BASE = os.environ.get("BASE", "https://popcornai.co.kr").rstrip("/")
CALL_GAP_SEC = 13            # 분당 5회 한도 아래로
UA = "popcorn-answer-quality/1"

WORSE, SAME, BETTER, UNMEASURED = "우리가 못함", "비슷함", "우리가 나음", "측정 못함"


# ── 질문 ──────────────────────────────────────────────────────────────────────
def expand(q: dict) -> str:
    t = q["text"]
    if isinstance(t, dict) and t.get("kind") == "long":
        body, n = t["body"], int(t["chars"])
        return (body * (n // len(body) + 1))[:n] + "\n" + t["tail"]
    return t


def shown(q: dict) -> str:
    """표에 적는 질문 -- 긴 글은 줄여서."""
    t = q["text"]
    if isinstance(t, dict):
        return "%s (%s자 글 + 「%s」)" % (q.get("note", "긴 글"), t["chars"], t["tail"])
    if not t.strip():
        return "[%s]" % q.get("note", "빈 입력")
    s = t + (" (×%d)" % q["repeat"] if q.get("repeat") else "")
    return s


def load_questions(subset: str, shard: str | None) -> list[dict]:
    qs = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if subset == "pr":
        qs = [q for q in qs if q.get("pr")]
    elif subset != "all":
        ids = {s.strip() for s in subset.split(",")}
        qs = [q for q in qs if q["id"] in ids]
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        qs = qs[i - 1::n]
    return qs


# ── ① 우리 답 ─────────────────────────────────────────────────────────────────
_last_call = [0.0]


def _post(path: str, body: dict) -> tuple[int, dict, dict]:
    wait = CALL_GAP_SEC - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.load(r), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            data = json.loads(raw)
        except ValueError:
            data = {"detail": raw[:300].decode("utf-8", "replace")}
        return e.code, data, dict(e.headers or {})


def ask_ours(text: str, state=None, chat_flow=None, history=None) -> dict:
    body = {"text": text, "state": state, "chat_flow": chat_flow, "history": history or []}
    for _ in range(4):
        code, data, headers = _post("/api/talk/parse", body)
        if code == 429 and data.get("window") == "minute":
            time.sleep(int(data.get("retry_after_sec") or headers.get("Retry-After") or 60) + 1)
            continue
        break
    if code != 200:
        return {"ok": False, "error": "HTTP %s %s" % (code, str(data.get("detail") or data.get("error") or "")[:160]),
                "rate_limited_day": code == 429}
    answer, reply = (data.get("answer") or "").strip(), (data.get("reply") or "").strip()
    bubble = "" if data.get("silent") else "\n\n".join(x for x in (answer, reply) if x)
    # 화면(live-flow.js submit)은 조건이 다 차면 곧바로 추천을 불러 말풍선 «아래»에 상품 카드를 붙인다.
    # 손님이 보는 것은 말풍선 + 카드다 -- 카드까지 우리 답에 넣는다(2026-10-11 사장님 기준).
    cards = ""
    st = data.get("state")
    if (isinstance(st, dict) and not data.get("silent") and data.get("pc_related") is not False
            and not data.get("fallback") and not data.get("missing")):
        cards = recommend_cards(st, text)
    return {"ok": True, "text": "\n\n".join(x for x in (bubble, cards) if x), "silent": bool(data.get("silent")),
            "cards": bool(cards) and "[아래 상품 카드]" in cards,
            "handoff_offer": data.get("handoff_offer") is True, "pc_related": data.get("pc_related"),
            "answer_error": data.get("answer_error"), "elapsed_sec": data.get("elapsed_sec"),
            "_state": data.get("state"), "_chat_flow": data.get("chat_flow")}


def _spec_line(spec) -> str:
    if isinstance(spec, dict):
        vals = [str(v) for v in spec.values() if isinstance(v, (str, int, float)) and str(v).strip()]
    elif isinstance(spec, list):
        vals = [str(v.get("value") or v.get("v") or "") if isinstance(v, dict) else str(v) for v in spec]
    else:
        vals = []
    return " / ".join(v for v in vals if v)[:120]


def recommend_cards(state: dict, text: str) -> str:
    """POST /api/grid/recommend -- 화면과 같은 본문. 카드(이름·가격·사양)와 카드 뒤 안내 문장을 글로 옮긴다."""
    code, data, _ = _post("/api/grid/recommend", {"state": state, "text": text[:300]})
    if code != 200 or not isinstance(data, dict):
        return "[상품 카드를 불러오지 못함: HTTP %s]" % code
    lines = []
    for cs in data.get("card_sets") or []:
        if not isinstance(cs, dict) or cs.get("kind") != "sold":
            continue
        items = [i for i in cs.get("items") or [] if isinstance(i, dict) and i.get("name")]
        if not items and (cs.get("empty_note") or cs.get("empty_reason")):
            lines.append("(카드 없음: %s)" % (cs.get("empty_note") or cs.get("empty_reason")))
        for i in items[:6]:
            price = i.get("price")
            spec = _spec_line(i.get("spec"))
            lines.append("- %s · %s%s" % (i["name"], ("%s원" % format(price, ",")) if isinstance(price, int) else "가격 미정",
                                           (" · " + spec) if spec else ""))
    notes = [n for n in data.get("talk_notes") or [] if isinstance(n, str) and n.strip()]
    if not lines and not notes:
        return ""
    head = "[아래 상품 카드]" if any(l.startswith("- ") for l in lines) else "[상품 카드 자리]"
    return "\n".join([head] + lines + notes)


def ours_for(q: dict) -> dict:
    text, turns = expand(q), int(q.get("repeat") or 1)
    state = flow = None
    history: list = []
    res: dict = {}
    for _ in range(turns):
        res = ask_ours(text, state, flow, history[-6:])
        if not res["ok"]:
            return res
        state, flow = res.pop("_state"), res.pop("_chat_flow")
        history += [{"role": "user", "text": text[:1000]}]
        if res["text"]:
            history.append({"role": "assistant", "text": res["text"][:300]})
    res.pop("_state", None), res.pop("_chat_flow", None)
    return res


# ── ② 일반 AI · ③ 심판 ──────────────────────────────────────────────────────
def repo_model() -> str:
    """api/llm.py 의 Claude 기본 모델 -- 저장소 설정을 따른다(QUALITY_MODEL 로 덮을 수 있다)."""
    if os.environ.get("QUALITY_MODEL"):
        return os.environ["QUALITY_MODEL"]
    src = (ROOT / "api" / "llm.py").read_text(encoding="utf-8")
    m = re.search(r'key="claude".*?default_model="([^"]+)"', src, re.S)
    if not m:
        raise SystemExit("api/llm.py 에서 Claude 기본 모델을 찾지 못했다")
    return m.group(1)


_client = None


def _claude(messages: list, system: str | None = None, max_tokens: int = 1200) -> str:
    global _client
    import anthropic
    if _client is None:
        _client = anthropic.Anthropic(timeout=120.0, max_retries=3)
    kw = {"model": repo_model(), "max_tokens": max_tokens, "messages": messages}
    if system:
        kw["system"] = system
    resp = _client.messages.create(**kw)
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


def ask_generic(q: dict) -> str:
    text = expand(q)
    if not text.strip():
        return "(일반 AI 채팅창은 빈 입력을 보낼 수 없다 -- 답 없음)"
    msgs: list = []
    out = ""
    for _ in range(int(q.get("repeat") or 1)):
        msgs.append({"role": "user", "content": text})
        out = _claude(msgs)
        msgs.append({"role": "assistant", "content": out})
    return out


JUDGE_SYSTEM = """너는 PC 판매점 상담 품질 심사관이다. 같은 손님 질문에 대한 두 답(A, B)을 손님 입장에서 비교한다.
한쪽은 PC 판매점의 상담 AI이고 다른 쪽은 일반 AI 채팅이다. 어느 쪽인지는 알려주지 않는다.
손님은 일반 AI 채팅에 익숙하다. 판매점 상담이 일반 AI보다 헛소리를 하거나, 질문을 비껴가거나,
되묻기만 하고 답을 안 주면 손님은 다시 오지 않는다.

기준(모두 손님 눈으로):
1. 명확함 -- 핵심 답이 바로 보이는가
2. 정확함 -- 틀린 사실·근거 없는 수치·지어낸 정책(배송일, 환불 기간, 가격 등)이 없는가
3. 실제로 답했는가 -- 질문에 직접 답했는가, 되묻기·회피로 끝나지 않았는가
4. 헛소리·지어냄 없음 -- 모르는 것을 아는 척하지 않았는가
5. 자연스러움 -- 사람과 대화하듯 자연스러운 한국어(또는 손님 언어)인가
판매점 상담 답에는 말풍선 아래에 붙는 「상품 카드」 목록이 함께 적혀 있을 수 있다. 손님은 말풍선과 카드를 함께 본다.
판매점 사장의 기준(그대로 적용한다):
- 좋은 판매점 답 = 일반 AI 수준의 설명(구성·가격대·이유)이 위에 있고, 그 설명에 맞는 실제 상품 카드가 아래에 함께 나온다.
- 되묻기만 하고 답을 미루면 판매점이 못한 것이다. 손님은 계속 되물으면 짜증을 낸다.
- 카드가 설명 기준과 크게 어긋나면(예: "가장 저렴하게"에 비싼 카드) 감점이다. 크게 어긋나지 않으면 카드는 가점이다.
- 구매 확정 뒤에도 상담사가 전화로 다시 컨설팅하므로, 답을 늦추는 확인 절차나 검증 단계를 요구하지 마라. 손님 눈에 보이는 결과만 비교한다.
이 질문에서 좋은 답의 기준도 함께 주어진다. 판매점이 알 수 없는 주문·결제 사실을 일반 AI가 모른다고 하는 것은 감점이 아니다.
판매점 답이 PC 상담으로 자연스럽게 이어 가는 것은 감점이 아니지만, 손님이 물은 것을 먼저 답하지 않으면 감점이다.
한쪽 답이 비어 있으면 손님에게는 아무 말도 안 한 것이다.

반드시 JSON 한 줄만 낸다: {"better":"A"|"B"|"tie","reason":"한국어 한 문장(60자 이내)"}
tie 는 손님이 보기에 실질 차이가 없을 때만 쓴다."""


def judge(q: dict, ours: str, generic: str, rng: random.Random) -> dict:
    swap = rng.random() < 0.5
    a, b = (generic, ours) if swap else (ours, generic)
    q_text = expand(q)
    if len(q_text) > 3000:
        q_text = q_text[:1200] + "\n...(중략)...\n" + q_text[-600:]
    prompt = ("손님 질문:\n%s\n\n좋은 답의 기준: %s\n\n[답 A]\n%s\n\n[답 B]\n%s"
              % (q_text if q_text.strip() else "(빈 입력)", q["criterion"], a or "(빈 답)", b or "(빈 답)"))
    raw = _claude([{"role": "user", "content": prompt}], system=JUDGE_SYSTEM, max_tokens=300)
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        j = json.loads(m.group(0)) if m else {}
    except ValueError:
        j = {}
    pick = str(j.get("better", "")).strip().upper()
    ours_slot = "B" if swap else "A"
    if pick == "TIE":
        verdict = SAME
    elif pick in ("A", "B"):
        verdict = BETTER if pick == ours_slot else WORSE
    else:
        return {"verdict": UNMEASURED, "reason": "심판 응답을 읽지 못함: " + raw[:80]}
    return {"verdict": verdict, "reason": str(j.get("reason", "")).strip()}


# ── 실행 · 합치기 ─────────────────────────────────────────────────────────────
def cmd_run(args) -> int:
    qs = load_questions(args.subset, args.shard)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    model = repo_model()
    print("질문 %d개 · 대상 %s · 모델 %s · API 키 %s" % (len(qs), BASE, model, "있음" if has_key else "없음"), flush=True)
    rng = random.Random(args.seed)
    rows = []
    for q in qs:
        row = {"id": q["id"], "group": q["group"], "question": shown(q), "criterion": q["criterion"]}
        o = ours_for(q)
        row["ours"] = o.get("text", "")
        row["ours_meta"] = {k: v for k, v in o.items() if k != "text"}
        if not o["ok"]:
            row.update(verdict=UNMEASURED, reason="우리 답을 받지 못함: " + o["error"])
        elif not has_key:
            row.update(generic="", verdict=UNMEASURED, reason="ANTHROPIC_API_KEY 없음 -- 일반 AI·심판 생략")
        else:
            try:
                row["generic"] = ask_generic(q)
                row.update(judge(q, row["ours"], row["generic"], rng))
            except Exception as e:                               # noqa: BLE001
                row.setdefault("generic", "")
                row.update(verdict=UNMEASURED, reason="일반 AI·심판 호출 실패: %s" % type(e).__name__)
        print("%s  %s  %s" % (row["id"], row["verdict"], row.get("reason", "")), flush=True)
        rows.append(row)
    (out / "rows.json").write_text(json.dumps({"base": BASE, "model": model, "rows": rows},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def _cell(s: str, limit: int = 0) -> str:
    s = (s or "").strip()
    if limit and len(s) > limit:
        s = s[:limit] + "…"
    return (s or "(빈 답)").replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def cmd_combine(args) -> int:
    rows, base, model = [], BASE, ""
    for d in args.dirs:
        p = Path(d) / "rows.json"
        if not p.exists():
            print("없음: %s" % p, file=sys.stderr)
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        base, model = data.get("base", base), data.get("model", model)
        rows += data["rows"]
    order = {q["id"]: i for i, q in enumerate(json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"])}
    rows.sort(key=lambda r: order.get(r["id"], 999))
    count = {k: sum(1 for r in rows if r["verdict"] == k) for k in (WORSE, SAME, BETTER, UNMEASURED)}
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    lines = [
        "# 상담 AI 답 비교 — %s" % stamp, "",
        "- 우리: `%s/api/talk/parse` (손님 말풍선 = answer + reply)" % base,
        "- 일반 AI·심판: Claude `%s` (지시문 없이 질문만)" % model,
        "- 질문 %d개 · **%s %d** · %s %d · %s %d · %s %d" % (
            len(rows), WORSE, count[WORSE], SAME, count[SAME], BETTER, count[BETTER], UNMEASURED, count[UNMEASURED]),
        "",
    ]
    if count[UNMEASURED]:
        lines += ["> 측정 못한 질문이 %d개 있다. 판정에서 뺐다(못함으로도 나음으로도 세지 않았다)." % count[UNMEASURED], ""]
    worse = [r for r in rows if r["verdict"] == WORSE]
    if worse:
        lines += ["## 우리가 못한 답", ""] + ["- **%s** %s — %s" % (r["id"], _cell(r["question"], 80), r["reason"]) for r in worse] + [""]
    lines += ["## 나란히 표", "", "| 번호 | 질문 | 우리 답 | 일반 AI 답 | 판정 | 이유 |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            r["id"], _cell(r["question"], 160), _cell(r.get("ours", "")), _cell(r.get("generic", ""), 1500),
            r["verdict"], _cell(r.get("reason", ""))))
    report = "\n".join(lines) + "\n"
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(report, encoding="utf-8")
    Path(args.report).with_suffix(".json").write_text(
        json.dumps({"base": base, "model": model, "count": count, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines[:6 + (2 if count[UNMEASURED] else 0)]) + "\n")
            if worse:
                f.write("\n".join(["", "## 우리가 못한 답", ""] + ["- **%s** %s — %s" % (
                    r["id"], _cell(r["question"], 80), r["reason"]) for r in worse]) + "\n")
    if args.print_rows:
        # 산출물(zip)을 못 받는 곳에서도 작업 기록만으로 결과를 되짚을 수 있게 한 줄씩 남긴다.
        for r in rows:
            print("ROW " + json.dumps({k: r.get(k) for k in ("id", "question", "ours", "generic", "verdict", "reason")},
                                      ensure_ascii=False))
    print("못함 %d · 비슷 %d · 나음 %d · 측정 못함 %d" % (count[WORSE], count[SAME], count[BETTER], count[UNMEASURED]))
    if args.gate and count[WORSE]:
        print("::error::일반 AI 보다 못한 답 %d개" % count[WORSE])
        return 1
    if args.gate and not rows:
        print("::error::결과가 하나도 없다")
        return 1
    if args.require_judge and count[UNMEASURED] == len(rows):
        print("::error::판정한 질문이 하나도 없다(API 키·서버 확인)")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--subset", default="pr", help="pr | all | 쉼표로 구분한 번호")
    r.add_argument("--shard", default=None, help="i/n -- 질문을 n 묶음으로 나눈 것 중 i 번째")
    r.add_argument("--out", required=True)
    r.add_argument("--seed", type=int, default=20261011)
    c = sub.add_parser("combine")
    c.add_argument("dirs", nargs="+")
    c.add_argument("--report", required=True)
    c.add_argument("--summary", default=None)
    c.add_argument("--gate", action="store_true", help="우리가 못함이 하나라도 있으면 실패")
    c.add_argument("--print-rows", action="store_true", help="결과를 한 줄 JSON 으로 작업 기록에 남긴다")
    c.add_argument("--require-judge", action="store_true", help="판정이 하나도 없으면 실패")
    a = ap.parse_args()
    return cmd_run(a) if a.cmd == "run" else cmd_combine(a)


if __name__ == "__main__":
    sys.exit(main())
