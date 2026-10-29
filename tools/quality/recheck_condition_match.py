"""조건·추천 일치 재검수 -- 코덱스 24조합(용도 4 x 예산 6) 입력을 그대로 다시 던지고 불일치 표시를 기계로 센다.

왜 있나 (2026-10-12 중헌 님 「담당에게 넘겨서 고쳐」 · 코덱스 검수 v2):
  같은 입력(case-plan.json)으로 고친 뒤를 다시 봐야 한다. 사람이 24번 입력·캡처하던 것을 상담·추천 API 두 번으로 줄인다.
  화면을 대신하지는 않는다 -- 상세 화면(부품 표·대표 소개)은 브라우저로 따로 본다(PR 본문 「재검수 방법」).

흐름 (조합 하나당 -- 화면 mockups/mvp3/live-flow.js 와 같은 본문)
  ① POST {BASE}/api/talk/parse      {text, state:null, chat_flow:null, history:[]}
  ② POST {BASE}/api/grid/recommend  {state: ①의 state, text}
  손님이 보는 말풍선 = answer + reply, 그 아래 카드 = card_sets[].items.

세는 것 (검수 v2 1~5번에 대응. 판정이 아니라 «다시 볼 곳» 표시다)
  4k_notice     「4K … 반영하지 못해요」인데 카드 수준 작업 설명에 4K 가 있다
  power         말풍선의 ○○○W 가 카드 파워 최대치보다 크다
  budget_word   카드가 전부 예산 초과인데 말풍선이 「예산 안에서 가장 가까운」·「예산으로 … 준비/맞춰/찾아 드리겠」을 말한다
  cpu_suffix    상품명에는 12400F 처럼 접미가 있는데 카드 CPU 에는 없다
  igpu_2cu      8000G APU 카드의 GPU 가 「내장 2CU」다

지키는 것
  - 개발 서버에 상담·추천 호출만 한다(손님 한 명이 물은 것과 같은 흔적). 다른 데이터는 바꾸지 않는다.
  - 방문자 호출 한도(api/access_gate: 분당 5 · 하루 40)를 지킨다 -- 상담 호출은 13초 간격, 분 한도 429 는 기다렸다 다시.
    한 번 돌리면 상담 24회다. 하루 한도 429 는 「측정 못함」으로 적는다.

쓰는 법
  python tools/quality/recheck_condition_match.py D:/WORK/코덱스-검수/2026-10-12-1935-조건추천일치-검수-v2/case-plan.json \
      --out recheck.md [--only 10,11,13]
환경변수: BASE(기본 https://dev.popcornai.co.kr)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "https://dev.popcornai.co.kr").rstrip("/")
UA = "popcorn-recheck-condition-match/1"
CALL_GAP_SEC = 13
_last = [0.0]

_WATT = re.compile(r"(?<!\d)(\d{3,4})\s*W(?![a-z])", re.I)
_BARE_WATT = re.compile(r"(?<![\d.])(\d{3,4})(?![\d.])")
_BUDGET_WORD = re.compile(r"예산 안에서 가장 가까운|(예산|\d+\s*만\s*원)[^.]{0,25}?(준비|맞춰|맞추|찾)[^.]{0,8}겠")


def _post(path: str, body: dict, gap: bool) -> tuple[int, dict]:
    wait = CALL_GAP_SEC - (time.monotonic() - _last[0])
    if gap and wait > 0:
        time.sleep(wait)
    if gap:
        _last[0] = time.monotonic()
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    for _ in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            try:
                data = json.loads(e.read() or b"{}")
            except ValueError:
                data = {}
            if e.code == 429 and data.get("window") == "minute":
                time.sleep(int(data.get("retry_after_sec") or 60) + 1)
                continue
            return e.code, data
    return 429, {}


def _psu_watt(psu) -> int | None:
    if not isinstance(psu, str):
        return None
    m = _WATT.search(psu)
    if m:
        return int(m.group(1))
    bare = [int(x) for x in _BARE_WATT.findall(psu) if 300 <= int(x) <= 2000]
    return bare[0] if bare else None


def check(case: dict) -> dict:
    code, talk = _post("/api/talk/parse", {"text": case["input"], "state": None, "chat_flow": None, "history": []}, True)
    if code != 200:
        return {"case": case, "error": "talk HTTP %s" % code}
    bubble = "\n\n".join(x for x in ((talk.get("answer") or "").strip(), (talk.get("reply") or "").strip()) if x)
    code, reco = _post("/api/grid/recommend", {"state": talk.get("state"), "text": case["input"][:300]}, False)
    if code != 200:
        return {"case": case, "bubble": bubble, "error": "recommend HTTP %s" % code}
    sets = [s for s in reco.get("card_sets") or [] if s.get("kind") == "sold"]
    items = [it for s in sets for it in s.get("items") or []]
    works = " ".join(str(s.get("min_level_work") or "") for s in sets) + " " + \
        " ".join(r for it in items for r in it.get("reasons") or [] if isinstance(r, str))
    flags = []
    if "4K" in bubble and "반영하지 못해요" in bubble and "4K" in works:
        flags.append("4k_notice")
    watts = [w for it in items if (w := _psu_watt((it.get("spec") or {}).get("psu")))]
    if watts and any(int(m.group(1)) > max(watts) for m in _WATT.finditer(bubble)):
        flags.append("power")
    if items and all(it.get("over_budget") for it in items) and _BUDGET_WORD.search(bubble):
        flags.append("budget_word")
    for it in items:
        cpu, name = str((it.get("spec") or {}).get("cpu") or ""), str(it.get("name") or "")
        m = re.search(r"(\d{4,5})$", cpu)
        if m and re.search(r"(?<![0-9A-Za-z])" + m.group(1) + r"[A-Z]{1,3}(?![0-9A-Za-z])", name):
            flags.append("cpu_suffix:%s" % it.get("product_code"))
        if "내장 2CU" in str((it.get("spec") or {}).get("gpu") or "") and re.search(r"8[5-7]00G", cpu):
            flags.append("igpu_2cu:%s" % it.get("product_code"))
    return {"case": case, "bubble": bubble, "items": items, "flags": flags,
            "notes": reco.get("talk_notes") or []}


def report(rows: list[dict]) -> str:
    out = ["# 조건·추천 일치 재검수 (%s · BASE=%s)" % (time.strftime("%Y-%m-%d %H:%M"), BASE), "",
           "| ID | 용도 · 예산 | 카드(상품번호 · 총액 · 예산초과) | 표시 |", "|---|---|---|---|"]
    for r in rows:
        c = r["case"]
        cards = "<br>".join("%s · %s원 · %s" % (it.get("product_code"), format(it.get("price") or 0, ","),
                                                "초과" if it.get("over_budget") else "이하") for it in r.get("items") or [])
        flag = r.get("error") or (", ".join(r["flags"]) if r.get("flags") else "없음")
        out.append("| %s | %s · %d만원 | %s | %s |" % (c["case_id"], c["use"], c["budget_won"] // 10000, cards or "-", flag))
    out += ["", "## 말풍선 전문", ""]
    for r in rows:
        out += ["### %s %s %d만원" % (r["case"]["case_id"], r["case"]["use"], r["case"]["budget_won"] // 10000), "",
                (r.get("bubble") or "(없음)").replace("\n", "  \n"), ""]
        if r.get("notes"):
            out += ["카드 안내: " + " / ".join(r["notes"]), ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plan", help="코덱스 case-plan.json")
    ap.add_argument("--out", default="recheck-condition-match.md")
    ap.add_argument("--only", default="", help="쉼표로 구분한 case_id (예: 10,11,13)")
    a = ap.parse_args(argv)
    with open(a.plan, encoding="utf-8") as f:
        cases = json.load(f)
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    rows = []
    for c in cases:
        if only and c["case_id"] not in only:
            continue
        r = check(c)
        print(c["case_id"], r.get("error") or r.get("flags"), flush=True)
        rows.append(r)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(report(rows))
    flagged = [r for r in rows if r.get("flags") or r.get("error")]
    print("flagged %d / %d -> %s" % (len(flagged), len(rows), a.out))
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
