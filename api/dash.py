# -*- coding: utf-8 -*-
"""작업 현황판 — 지금 무엇을 하고 있는지 보고, 말을 건다 (2026-08-12)

■ 왜 만드나
  텔레그램이 폰에서 그 일을 하고 있는데 두 가지가 안 된다:
  **진행 중인 것을 실시간으로 못 본다**(끝나야 알림이 온다) 그리고 **긴 내용을 못 읽는다.**
  PC 앞에 있을 때는 화면이 낫다.

■ 어디서 읽나 — 새 배선이 없다
  Claude Code 가 세션 전사본을 **이미 디스크에 쌓고 있다.**

      ~/.claude/projects/<프로젝트키>/<세션>.jsonl     매 턴 append
      %TEMP%/claude/<프로젝트키>/<세션>/tasks/*.output  서브에이전트 출력

  그래서 이 모듈은 **읽기만 한다.** Claude Code 에 붙는 연동이 아니라 파일을 보는 것이다.

■ 말을 거는 쪽 — 텔레그램과 같은 구조
  화면이 큐 파일에 한 줄 쓰고, Monitor 가 그걸 보다 깨운다.
  **「도중에」는 못 본다** — 단일 스레드라 도구가 도는 중에는 끼어들 수 없고,
  Monitor 는 「끝나자마자」까지만 보장한다(`docs/telegram-rules.md` 와 같은 한계).
  화면이 그 사실을 먼저 말한다 — 기다리는 사람이 «왜 답이 없지»를 겪지 않게.

■ 읽기 전용이라 안전하다
  전사본을 고치지 않는다. 큐 파일만 쓴다(우리가 만든 파일이다).
"""
import asyncio
import datetime
import io
import json
import os
import re
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .timeutil import now_iso

router = APIRouter(prefix="/api/admin/dash", tags=["admin-dash"])

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / ".claude" / "agents"          # 팀원 정의 정본
# 프로젝트 키 — Claude Code 가 cwd 를 이 규칙으로 접는다 (E:\DEV -> E--DEV)
PROJ_KEY = "E--DEV"
SESS_DIR = Path(os.path.expanduser("~")) / ".claude" / "projects" / PROJ_KEY
QUEUE = ROOT / ".claude" / "dash-queue.jsonl"      # 화면 -> 세션 (우리가 만든 파일)
WATCH_HEARTBEAT = ROOT / ".claude" / "dash-watch.heartbeat"   # 감시자(로컬) 생존 신호

# 팀원 이름 -> 한글. `.claude/agents/*.md` 가 정본이고 여기는 표시용이다.
# ⚠ 2026-08-15 점검자 실측 — 신설 팀원 둘(archivist·designchecker)이 빠져 있어
# 응답이 "ko":"archivist"·"ko":"designchecker"로 영문 그대로 나오고 있었다(.claude/
# agents/ 10명 전수 대조로 확인 — 10명 전원이 이제 있다). 한글은 CLAUDE.md
# "★ 확인은 세 축이고..."·"하네스가 손으로 하던 넷을 기록자에게 넘긴다" 항목과
# 각 정의 파일(archivist.md·designchecker.md)의 description 문구를 그대로 따랐다.
# ⚠ 2026-08-25 제작자 실측 재발 — 2026-08-19 신설된 pathfinder 가 같은 방식으로
# 빠져 있었다(.claude/agents/ 11명 전수 대조로 확인 — 이번에 11명 전원). 한글
# "길잡이"는 CLAUDE.md "★ 길잡이(pathfinder) 신설 — 화면 «사이»를 본다" 항목과
# pathfinder.md 의 role/description 을 그대로 따랐다 — 저장소 전반에 이미 쓰이는
# 호칭이라 새로 짓지 않았다.
TEAM_KO = {
    "investigator": "조사자", "maker": "제작자", "checker": "확인자",
    "writer": "문장가", "dba": "DBA", "crosschecker": "검증자", "sweeper": "점검자",
    "specfiller": "웹크롤링", "archivist": "기록자", "designchecker": "계약자",
    "pathfinder": "길잡이",
    "general-purpose": "하네스", "Explore": "하네스", "Plan": "하네스",
}

# 옛 이름 -> 지금 이름. 팀원 이름을 바꾸면 전사본에는 옛 이름의 호출이 남는다 —
# 그걸 별도 카드로 세우면 같은 사람이 둘로 보인다(사용자 지적 2026-08-12: copy-auditor).
# 접되 지우지는 않는다: 호출·실패 수는 지금 이름의 카드에 그대로 계산된다.
ALIAS = {"copy-auditor": "writer", "surveyor": "investigator"}

# Claude Code 기본 제공 서브에이전트 — 이 셋은 「팀원」이 아니라 **하네스(주 세션) 자신이
# 위임하는 호출**이다. TEAM_KO 가 셋 다 "하네스"로 표기하면서도 `_roster()` 는 이 이름을
# 모르므로, 예전 코드는 이걸 몰라 별도 "정의 없음" 카드를 또 만들었다 — roster 에 "하네스"
# 이름 카드가 둘 서는 결함이었다(2026-08-13 실측: 10장 중 2장). 지금은 별도 카드를 만들지
# 않고 `_team()` 의 harness 카드로, `_event_agents()` 의 태그로 합산한다.
HARNESS_BUILTINS = ("general-purpose", "Explore", "Plan")


# ── 감시자(dash_watch.py) 생존 표시 ─────────────────────────────────────
#
# 로컬 PC: `scripts/dash_watch.py` 가 5초마다 `WATCH_HEARTBEAT` 파일을 덮어쓴다.
#   → 파일 mtime 이 15초 이내면 살아 있다.
# 배포 서버: 로컬 파일이 없다(다른 프로세스). 대신 감시자가 30초마다
#   `?watcher=1` 을 붙여 이 서버를 부른다 — 그 요청이 온 시각을 여기 적어 둔다.
#   → 마지막 핑이 90초 이내면 살아 있다.
# **지어내지 않는다** — 둘 다 없으면(또는 둘 다 낡았으면) alive=False, last=None.
_WATCH_PING: dict = {"ts": None, "iso": None}

HEARTBEAT_FRESH_S = 15
PING_FRESH_S = 90


def _watcher() -> dict:
    cands = []                                 # (age_s, last_iso, src)
    try:
        st = WATCH_HEARTBEAT.stat()
        age = time.time() - st.st_mtime
        if age <= HEARTBEAT_FRESH_S:
            try:
                last = io.open(WATCH_HEARTBEAT, encoding="utf-8", errors="ignore").read().strip() or None
            except OSError:
                last = None
            cands.append((age, last, "heartbeat"))
    except OSError:
        pass
    if _WATCH_PING["ts"] is not None:
        age = time.time() - _WATCH_PING["ts"]
        if age <= PING_FRESH_S:
            cands.append((age, _WATCH_PING["iso"], "ping"))
    if not cands:
        return {"alive": False, "last": None, "src": None}
    cands.sort(key=lambda c: c[0])              # 더 신선한(나이 적은) 쪽을 쓴다
    age, last, src = cands[0]
    return {"alive": True, "last": last, "src": src}


# ── 팀원 명단 · 활동 ────────────────────────────────────────────────────
#
# **「실행 중」을 지어내지 않는다.** 전사본에서 이렇게 판정한다:
#     Agent tool_use 가 있고 같은 tool_use_id 의 tool_result 가 **아직 없으면** 실행 중
#     결과가 도착했으면 완료
# 그 밖의 방법은 없다 — `tasks/*.output` 파일은 서브에이전트와 백그라운드 셸을
# 구분하지 못한다(2026-08-12 실측: 목록에 뜬 것이 uvicorn 재시작 명령이었다).
#
# 전사본이 24MB 라 매초 통째로 읽지 않는다. **읽은 바이트 위치를 기억해 새로 자란 만큼만**
# 읽어 누적한다(아래 `_SCAN`). 파일이 바뀌거나 줄어들면 처음부터 다시 센다.
# `agent_ids` — Agent/Task 호출의 tool_use_id -> 에이전트 정본 이름. `runs[*]["open"]`
# 과 달리 **결과가 와도 지우지 않는다**(하루 내내 누적) — 팀원 카드 클릭 필터가
# 꼬리(최근 N줄) 밖에서 열린 호출의 결과를 만나도 누구 것인지 이 맵으로 알아낸다.
_SCAN: dict = {"path": None, "off": 0, "runs": {}, "tools": 0, "says": 0, "day": None,
               "agent_ids": {}}


def _roster() -> list[dict]:
    """`.claude/agents/*.md` 의 앞머리(frontmatter)를 읽는다. 정의 파일이 정본이다."""
    out = []
    if not AGENTS_DIR.is_dir():
        return out
    for p in sorted(AGENTS_DIR.glob("*.md")):
        name, desc, role = p.stem, "", ""
        try:
            txt = io.open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        m = re.match(r"\s*---\s*\n(.*?)\n---", txt, re.S)
        if m:
            for line in m.group(1).splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip() or name
                elif line.startswith("role:"):
                    role = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()
        desc = re.sub(r"\*\*", "", desc)
        # 카드의 역할 줄은 정의의 `role:`(명사구)만 쓴다 — description 산문을 잘라 쓰다가
        # 「~한다」 서술문이 카드에 그대로 흘렀다(사용자 지적 2026-08-12: 시스템 UI 는
        # 명사구다). role 이 없으면 **지어내지 않고 빈칸**으로 둔다 — 정의에 채울 일이다.
        #
        # `ko_mapped` — 2026-08-15 추가(조기 발견 장치). TEAM_KO 에 없어 `ko`가 원문
        # 이름으로 폴백됐는지를 **여기서 표시해 둔다**(archivist·designchecker 가 3주
        # 가까이 영문으로 새고도 아무 데도 안 걸렸던 것과 같은 재발을 막는다). 기존
        # 키(name·ko·role·desc·defined)는 그대로 두고 **추가만** 한다.
        out.append({"name": name, "ko": TEAM_KO.get(name, name),
                    "role": role[:44], "desc": desc[:180], "defined": True,
                    "ko_mapped": name in TEAM_KO})
    return out


def _kst_day(ts: str) -> str:
    """전사본 시각은 UTC(Z) 다. 「오늘」은 한국 날짜로 센다 — 안 그러면 오전 9시에 날이 바뀐다."""
    try:
        d = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (d + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")
    except Exception:                                        # noqa: BLE001
        return ""


def _scan(path: Path) -> dict:
    """전사본을 **자란 만큼만** 읽어 누적한다. 오늘이 바뀌면 오늘치를 비운다."""
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")
    if _SCAN["path"] != str(path) or _SCAN["day"] != today:
        _SCAN.update({"path": str(path), "off": 0, "runs": {}, "tools": 0,
                      "says": 0, "day": today, "agent_ids": {}})
    try:
        size = path.stat().st_size
    except OSError:
        return _SCAN
    if size < _SCAN["off"]:                 # 파일이 줄었다 = 다른 세션이거나 잘렸다
        _SCAN.update({"off": 0, "runs": {}, "tools": 0, "says": 0, "agent_ids": {}})
    if size == _SCAN["off"]:
        return _SCAN
    with io.open(path, "rb") as f:
        f.seek(_SCAN["off"])
        chunk = f.read(size - _SCAN["off"])
    # 마지막 줄이 잘렸을 수 있다 — 개행까지만 먹고 나머지는 다음번에
    cut = chunk.rfind(b"\n")
    if cut < 0:
        return _SCAN
    _SCAN["off"] += cut + 1
    runs = _SCAN["runs"]
    for line in chunk[:cut].decode("utf-8", "ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:                                    # noqa: BLE001
            continue
        t, ts = o.get("type"), o.get("timestamp") or ""
        same_day = _kst_day(ts) == today
        if t == "assistant":
            for c in (o.get("message") or {}).get("content") or []:
                if c.get("type") != "tool_use":
                    continue
                if same_day:
                    _SCAN["tools"] += 1
                if c.get("name") in ("Agent", "Task"):
                    inp = c.get("input") or {}
                    who = str(inp.get("subagent_type") or "?")
                    who = ALIAS.get(who, who)          # 옛 이름은 지금 이름으로 접는다
                    r = runs.setdefault(who, {"open": {}, "today": 0, "fail": 0, "last": None})
                    r["open"][c.get("id")] = {"desc": str(inp.get("description") or "")[:70],
                                              "ts": ts}
                    r["last"] = ts
                    # 팀원 카드 필터(사건 태깅)가 쓴다 — 결과가 와도 지우지 않는다(위 주석)
                    _SCAN["agent_ids"][c.get("id")] = who
        elif t == "user":
            cc = (o.get("message") or {}).get("content")
            if isinstance(cc, str) and same_day:
                _SCAN["says"] += 1
            elif isinstance(cc, list):
                for c in cc:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "text" and same_day:
                        _SCAN["says"] += 1
                    elif c.get("type") == "tool_result":
                        tid = c.get("tool_use_id")
                        for r in runs.values():
                            if tid in r["open"]:
                                r["open"].pop(tid, None)
                                if not same_day:
                                    continue
                                # **실패를 완료로 세지 않는다.** 2026-08-12 에 `copy-auditor`
                                # 호출이 «Agent type not found» 로 죽었는데 화면이 그걸
                                # 「오늘 완료 1회」로 세고 있었다 — 사장님 질문으로 드러났다.
                                if c.get("is_error"):
                                    r["fail"] = r.get("fail", 0) + 1
                                else:
                                    r["today"] += 1
    return _SCAN


def _team() -> tuple[list[dict], dict]:
    """명단 + 활동. 정의에 없는데 불린 이름도 **숨기지 않고** 뒤에 붙인다."""
    p = _latest_session()
    sc = _scan(p) if p else _SCAN
    runs = sc["runs"]
    roster = _roster()
    known = {a["name"] for a in roster}
    for who in sorted(runs):
        if who in HARNESS_BUILTINS:
            continue        # 의사 카드를 만들지 않는다 — 아래서 harness 카드로 합산한다
        if who not in known:
            builtin = who == "claude"
            roster.append({"name": who, "ko": TEAM_KO.get(who, who), "defined": False,
                           "role": "Claude Code 기본 제공" if builtin else "정의 없음",
                           "desc": ("Claude Code(하네스)가 기본으로 제공하는 에이전트 (%s)" % who)
                                   if builtin else "`.claude/agents/` 에 정의가 없는 이름"})
    # 신호등 (사용자 지시 2026-08-12): 대기=회색 · 실행=노랑 깜빡 · 지연·오류=빨강 · 완료=초록.
    # 「지연」에는 기준이 있어야 한다 — 실행 시작 후 10분. 오늘 실측에서 팀원 한 건이
    # 37초에 끝났고, 이 리포의 가장 긴 단일 작업이 회귀 8분이다. 10분이면 물린 것이다.
    DELAY_S = 600
    now = datetime.datetime.now(datetime.timezone.utc)
    done = running = failed = delayed = 0
    for a in roster:
        r = runs.get(a["name"]) or {}
        opened = r.get("open") or {}
        a["running"] = len(opened)
        a["today"] = r.get("today", 0)
        a["fail"] = r.get("fail", 0)
        a["last"] = r.get("last")
        a["doing"] = sorted((v["desc"] for v in opened.values()))[:2]
        age = 0
        for v in opened.values():
            try:
                ts = datetime.datetime.fromisoformat(str(v["ts"]).replace("Z", "+00:00"))
                age = max(age, int((now - ts).total_seconds()))
            except Exception:                                # noqa: BLE001
                pass
        if a["running"] and age > DELAY_S:
            a["sig"], a["state"] = "delay", "지연 %d분" % (age // 60)
            delayed += 1
        elif a["running"]:
            a["sig"], a["state"] = "run", "실행 중"
        elif a["fail"] and not a["today"]:
            a["sig"], a["state"] = "fail", "실패"
        elif a["today"]:
            a["sig"], a["state"] = "done", "완료"
        else:
            a["sig"], a["state"] = "wait", "대기"
        done += a["today"]
        running += a["running"]
        failed += a["fail"]
    # 하네스 카드 — 팀원이 아니라 **이 화면을 채우는 주 세션 자체**. 위 루프를 태우면
    # `runs.get("harness")` 가 비어 있어 대기로 덮인다 — 그래서 루프 밖에서 따로 만들어
    # 맨 앞에 꽂는다.
    #
    # **결함 수정(2026-08-13)**: `general-purpose`/`Explore`/`Plan` 호출은 TEAM_KO 에서
    # 이미 "하네스"로 표기되는데, 예전 코드는 위 루프 앞에서 이 이름들을 모르는 이름으로
    # 보고 별도 "정의 없음" 카드를 또 만들었다 — roster 에 "하네스" 카드가 둘 서는
    # 결함이었다(실측: 10장 중 2장). 지금은 그 셋을 별도 카드로 세우지 않고(위에서 continue)
    # 여기서 running/today/fail/last/doing 을 이 하네스 카드 하나에 합산한다.
    idle_s = int(time.time() - p.stat().st_mtime) if p else None
    h_running = h_fail = h_today = 0
    h_last = None
    h_doing: list[str] = []
    h_age = 0
    for b in HARNESS_BUILTINS:
        r = runs.get(b) or {}
        opened = r.get("open") or {}
        h_running += len(opened)
        h_today += r.get("today", 0)
        h_fail += r.get("fail", 0)
        if r.get("last") and (h_last is None or r["last"] > h_last):
            h_last = r["last"]
        for v in opened.values():
            h_doing.append(v["desc"])
            try:
                ts = datetime.datetime.fromisoformat(str(v["ts"]).replace("Z", "+00:00"))
                h_age = max(h_age, int((now - ts).total_seconds()))
            except Exception:                                    # noqa: BLE001
                pass
    harness = {
        "name": "harness", "ko": "하네스", "defined": True,
        "role": "주 세션 · 사장님과 대화 · 팀원 호출",
        "desc": ("이 현황판을 채우는 주 세션 자체다 — general-purpose/Explore/Plan 호출"
                 "(TEAM_KO 의 \"하네스\" 별칭)의 활동은 별도 카드 없이 이 카드에 합산된다."),
        "running": h_running, "fail": h_fail, "today": h_today, "last": h_last,
        "doing": sorted(h_doing)[:2] if h_doing else
                 ["오늘 도구 %d · 발화 %d" % (sc.get("tools", 0), sc.get("says", 0))],
    }
    # 신호는 둘을 겹친다 — **위임한 호출이 있으면 그 실행/지연 상태**를 우선하고,
    # 없으면 세션 자체의 idle_s(전사본 최종 수정 후 경과 — /state 가 쓰는 것과 같은 정의).
    if h_running and h_age > DELAY_S:
        harness["sig"], harness["state"] = "delay", "지연 %d분" % (h_age // 60)
    elif h_running:
        harness["sig"], harness["state"] = "run", "실행 중"
    elif idle_s is not None and idle_s <= 120:
        harness["sig"], harness["state"] = "run", "활동 중"
    else:
        harness["sig"], harness["state"] = "idle", "대기"
    done += h_today
    running += h_running
    failed += h_fail
    if h_running and h_age > DELAY_S:
        delayed += 1
    roster.insert(0, harness)
    return roster, {"tools": sc["tools"], "says": sc["says"], "day": sc["day"],
                    "agent_done": done, "agent_running": running,
                    "agent_fail": failed, "agent_delayed": delayed}


def _latest_session() -> Path | None:
    """가장 최근에 쓰인 전사본. 없으면 None — **지어내지 않는다.**"""
    if not SESS_DIR.is_dir():
        return None
    files = [p for p in SESS_DIR.glob("*.jsonl") if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _tail_lines(path: Path, n: int) -> list[str]:
    """끝에서 n 줄. 22MB 를 통째로 읽지 않는다 — 화면이 매초 부른다."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    block, data, pos = 262144, b"", size
    with io.open(path, "rb") as f:
        while pos > 0 and data.count(b"\n") <= n:
            step = min(block, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
    return data.decode("utf-8", "ignore").splitlines()[-n:]


def _event(d: dict) -> dict | None:
    """전사본 한 줄 -> 화면이 쓸 사건. 관심 없는 줄은 None."""
    t = d.get("type")
    ts = d.get("timestamp")
    if t == "assistant":
        m = d.get("message") or {}
        out = []
        for c in (m.get("content") or []):
            if c.get("type") == "tool_use":
                out.append({"kind": "tool", "name": c.get("name"),
                            "detail": _tool_detail(c.get("name"), c.get("input") or {})})
            elif c.get("type") == "text" and (c.get("text") or "").strip():
                # 4000자 — 현황판이 발화 속 마크다운 표를 렌더한다(2026-08-12).
                # 600자로 자르면 표가 중간에서 끊긴다. user say·result 절단은 그대로다.
                out.append({"kind": "say", "text": (c["text"] or "").strip()[:4000]})
        if not out:
            return None
        u = m.get("usage") or {}
        return {"who": "claude", "ts": ts, "blocks": out,
                "tokens": (u.get("input_tokens", 0) or 0) + (u.get("output_tokens", 0) or 0)}
    if t == "user":
        m = d.get("message") or {}
        c = m.get("content")
        if isinstance(c, str):
            return {"who": "user", "ts": ts, "blocks": [{"kind": "say", "text": c[:600]}]}
        if isinstance(c, list):
            # tool_result 는 도구가 돌려준 것이라 사람 발화가 아니다 — 결과만 요약한다
            res = [x for x in c if isinstance(x, dict) and x.get("type") == "tool_result"]
            say = [x for x in c if isinstance(x, dict) and x.get("type") == "text"]
            if say:
                return {"who": "user", "ts": ts,
                        "blocks": [{"kind": "say", "text": (say[0].get("text") or "")[:600]}]}
            if res:
                body = res[0].get("content")
                if isinstance(body, list):
                    body = " ".join(str(b.get("text", "")) for b in body if isinstance(b, dict))
                txt = re.sub(r"\s+", " ", str(body or ""))[:220]
                return {"who": "result", "ts": ts, "blocks": [{"kind": "result", "text": txt}]}
    return None


def _tool_detail(name: str, inp: dict) -> str:
    """도구 호출을 한 줄로. **전체 명령을 그대로 싣지 않는다** — 비밀값이 섞일 수 있다."""
    if name == "Bash":
        return re.sub(r"\s+", " ", str(inp.get("description") or inp.get("command") or ""))[:110]
    if name in ("Read", "Write", "Edit"):
        return str(inp.get("file_path") or "")[-70:]
    if name in ("Grep", "Glob"):
        return str(inp.get("pattern") or "")[:70]
    if name == "Agent":
        raw = str(inp.get("subagent_type") or "")
        canon = ALIAS.get(raw, raw)                    # 옛 이름은 지금 이름으로 접는다
        who = TEAM_KO.get(canon, canon)
        return "%s — %s" % (who, str(inp.get("description") or "")[:60])
    if name == "Skill":
        return str(inp.get("skill") or "")
    return re.sub(r"\s+", " ", json.dumps(inp, ensure_ascii=False))[:90]


def _event_agents(d: dict, id2agent: dict) -> list[str]:
    """이 사건이 어느 팀원 것인가 — 팀원 카드 클릭 필터가 쓴다.

    **지어내지 않는다.** 전사본에 실제로 있는 것만 본다: Agent/Task 호출 자신과
    그 결과(tool_result)만 그 팀원으로 태그하고, 나머지(하네스 자신의 도구 호출·발화,
    사장님 발화)는 전부 'harness' 로 태그한다. 서브에이전트 **내부** 도구 호출은 이
    전사본에 없다 — 별도 출력 파일(`tasks/*.output`)이고 그나마도 백그라운드 셸 명령과
    구분이 안 된다(`_bg_tasks` 주석과 같은 한계). 한 메시지에 서로 다른 팀원 호출이
    여럿이면(병렬 호출) 전부 담는다 — 하나만 골라 나머지를 숨기지 않는다.
    """
    t = d.get("type")
    out: list[str] = []
    if t == "assistant":
        for c in (d.get("message") or {}).get("content") or []:
            if c.get("type") == "tool_use" and c.get("name") in ("Agent", "Task"):
                who = str((c.get("input") or {}).get("subagent_type") or "?")
                who = ALIAS.get(who, who)
                # 결함 1 수정: general-purpose/Explore/Plan 은 별도 카드가 없다 —
                # 하네스 필터가 이 사건들을 잡도록 "harness" 로 태그한다.
                if who in HARNESS_BUILTINS:
                    who = "harness"
                if who not in out:
                    out.append(who)
    elif t == "user":
        m = d.get("message") or {}
        c = m.get("content")
        if isinstance(c, list):
            for x in c:
                if isinstance(x, dict) and x.get("type") == "tool_result":
                    who = id2agent.get(x.get("tool_use_id"))
                    if who in HARNESS_BUILTINS:
                        who = "harness"
                    if who and who not in out:
                        out.append(who)
    return out or ["harness"]


def _agent_events(path: Path, agent: str, cap: int = 200) -> list[dict]:
    """팀원 카드 클릭 필터 — **당일 전사본 전체**에서 이 팀원의 사건만 모은다(윈도 무관).

    **결함 2 (2026-08-13 조사자 실측으로 원인 확정)**: 카드의 `today` 집계(`_scan`)는
    당일 전사본 전체를 누적하는데, 기본 사건 목록(`state()` 의 windowed 경로)은
    `_tail_lines(limit*6)` — 끝 240줄짜리 창만 본다. 새벽에 호출된 팀원의 호출·결과
    쌍이 파일 앞쪽(창 밖)에 있으면 카드는 「오늘 2건」인데 필터는 0건을 보여준다
    (limit=200 이면 4장 모두 today 와 일치하는 사건이 나온다 — 실측 확인).

    이 경로는 창을 쓰지 않는다 — 파일 전체를 한 번 훑어 오늘(KST) 것만, 이 팀원
    태그(`_event_agents` 와 같은 판정)가 붙은 사건만 담는다. id2agent 매핑도 이 함수
    안에서 처음부터 다시 쌓는다(`_SCAN["agent_ids"]` 에 기대지 않는다 — 이 요청이
    세션 재시작·파일 교체 이후에 와도 스스로 맞는다). 상한(cap)은 두되 「없다」와
    「상한에 잘렸다」를 섞지 않도록 호출부가 반환 건수를 그대로 화면에 보인다.
    """
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")
    try:
        data = io.open(path, "rb").read()
    except OSError:
        return []
    id2agent: dict = {}
    out: list[dict] = []
    for line in data.decode("utf-8", "ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:                                        # noqa: BLE001
            continue
        if _kst_day(o.get("timestamp") or "") != today:
            continue
        # 이 사건 이전의 Agent/Task 호출로 tool_use_id -> 팀원 매핑을 앞에서부터 쌓는다
        # (전사본은 호출이 결과보다 항상 먼저 온다 — `_scan()` 과 같은 가정).
        if o.get("type") == "assistant":
            for c in (o.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_use" and c.get("name") in ("Agent", "Task"):
                    who = str((c.get("input") or {}).get("subagent_type") or "?")
                    who = ALIAS.get(who, who)
                    if who in HARNESS_BUILTINS:
                        who = "harness"
                    id2agent[c.get("id")] = who
        e = _event(o)
        if e is None:
            continue
        e["agents"] = _event_agents(o, id2agent)
        if agent in e["agents"]:
            out.append(e)
    return out[-cap:]


# 백그라운드 작업 출력을 「지금 도는 것」으로 볼 수 있는 창. 넘으면 지난 일이다.
AGENT_WINDOW_S = 1800          # 30분
AGENT_LIVE_S = 60              # 이보다 최근에 쓰였으면 아직 쓰는 중


def _bg_tasks() -> tuple[list[dict], int]:
    """백그라운드 작업 출력 파일 — 무엇이 돌고 있나. `(창 안 목록, 창 밖 건수)`.

    **「팀원 작업」이라 부르지 않는다.** `tasks/*.output` 은 서브에이전트와 백그라운드
    셸 명령을 **구분하지 않는다** — 실측하니 목록에 뜬 것이 uvicorn 재시작 명령이었다
    (2026-08-12). 파일만 보고는 어느 쪽인지 알 수 없으므로 화면도 그렇게 부르지 않는다.
    누가 어떤 팀원인지는 전사본의 `Agent` 도구 호출(`_tool_detail`)이 말한다.

    **오래된 파일을 「도는 작업」으로 내밀지 않는다.** 파일은 지워지지 않고 남으므로
    거르지 않으면 4일 전 것이 목록 맨 위에 앉는다(실측 368,543초 = 4.3일).
    화면은 그걸 지금 일로 읽는다 — 숫자를 지어내지 않는다는 규칙과 같은 종류의 거짓이다.

    창 밖의 것은 **버리지 않고 수만 돌려준다** — 「없다」와 「창 밖에 있다」는 다르다.
    """
    base = Path(os.environ.get("TEMP", "")) / "claude" / PROJ_KEY
    if not base.is_dir():
        return [], 0
    now, out, older = time.time(), [], 0
    for sess in base.iterdir():
        d = sess / "tasks"
        if not d.is_dir():
            continue
        for f in d.glob("*.output"):
            try:
                st = f.stat()
            except OSError:
                continue
            age = int(now - st.st_mtime)
            if age > AGENT_WINDOW_S:
                older += 1
                continue
            out.append({"id": f.stem, "bytes": st.st_size, "age_s": age,
                        "live": age <= AGENT_LIVE_S,
                        "tail": "".join(_tail_lines(f, 2))[-160:]})
    out.sort(key=lambda a: a["age_s"])
    return out[:8], older


AGENT_EVENTS_CAP = 200          # 팀원 필터(당일 전체 스캔) 상한 — 결함 2


@router.get("/state")
def state(limit: int = 40, watcher: int = 0, agent: str = ""):
    """현황 한 벌. 화면이 주기적으로 부른다.

    `watcher=1` 이 붙으면 감시자(배포 서버 쪽)가 방금 이 서버를 불렀다는 뜻이라
    시각을 적어 둔다(`_WATCH_PING`) — 세션 유무와 무관하게 항상 기록한다.

    `agent=이름` 이 붙으면 사건 목록을 **당일 전사본 전체**에서 그 팀원 것만 모아
    돌려준다(`_agent_events`, 창 무관 · 상한 `AGENT_EVENTS_CAP`) — 결함 2 수정.
    기본(파라미터 없음)은 그대로 최근 `limit*6` 줄짜리 창(`_tail_lines`)이다.
    화면은 팀원 카드를 누르면 이 파라미터를 붙여 재조회하고, 해제하면 다시 없이
    부른다(폴링·SSE 갱신도 같은 `load()` 를 타므로 필터가 계속 걸린 채 갱신된다).
    """
    if watcher:
        _WATCH_PING["ts"] = time.time()
        _WATCH_PING["iso"] = now_iso()          # 타임존 포함 — naive면 배포 서버(UTC)를 브라우저가 로컬로 오독한다(timeutil)
    p = _latest_session()
    if p is None:
        return {"ok": False, "reason": "세션 전사본 없음", "dir": str(SESS_DIR),
                "events": [], "agents": [], "agents_older": 0,
                "agents_window_min": AGENT_WINDOW_S // 60, "queued": _queue_pending(),
                "watcher": _watcher()}
    # 팀원 명단·활동을 먼저 잰다 — `_scan()` 이 이때 `_SCAN["agent_ids"]`(사건 태깅용
    # tool_use_id -> 팀원 이름 맵)을 채운다. 사건 목록보다 먼저 불러야 아래 태깅이
    # 최신 상태를 쓴다.
    roster, tot = _team()
    # 2026-08-15 추가(조기 발견 장치) — `.claude/agents/*.md`에 정의는 있는데 TEAM_KO에
    # 없어 `ko`가 영문 이름으로 폴백된 팀원. archivist·designchecker가 이 상태로 있다가
    # 화면에 그대로 노출됐다(폴백이 에러를 안 내 조용히 틀렸다). 비어 있으면 지금은
    # 전원 한글 매핑이 있다는 뜻이다.
    team_unmapped = [a["name"] for a in roster if a.get("defined") and not a.get("ko_mapped", True)]
    agent = (agent or "").strip()
    if agent:
        evts = _agent_events(p, agent, cap=AGENT_EVENTS_CAP)
    else:
        id2agent = _SCAN.get("agent_ids", {})
        evts = []
        for line in _tail_lines(p, limit * 6):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:                                    # noqa: BLE001
                continue
            e = _event(o)
            if e is None:
                continue
            e["agents"] = _event_agents(o, id2agent)   # 팀원 카드 필터가 쓴다(클라 추측 없음)
            evts.append(e)
        evts = evts[-limit:]
    st = p.stat()
    agents, agents_older = _bg_tasks()
    return {
        "ok": True,
        "session": p.stem,
        "idle_s": int(time.time() - st.st_mtime),
        "size_mb": round(st.st_size / 1e6, 1),
        "events": evts,
        "agent_filter": agent or None,       # 서버가 실제로 적용한 필터 — 화면 추측 방지
        "agents": agents,
        "agents_older": agents_older,        # 창 밖 — 「없다」와 구분해 화면이 적는다
        "agents_window_min": AGENT_WINDOW_S // 60,
        "queued": _queue_pending(),
        "roster": roster,                    # 팀원 명단 + 신호
        "today": _today(tot),                # 오늘 처리한 것 — 셀 수 있는 것만
        "watcher": _watcher(),               # 감시자 생존 — heartbeat 또는 ping, 신선한 쪽
        "team_unmapped": team_unmapped,       # 정의는 있으나 TEAM_KO 미등록(위 주석) — 추가만
    }


def _today(tot: dict) -> dict:
    """오늘 처리한 업무 — **세는 방법이 있는 것만 센다.**

    「업무 건수」는 정의가 없는 말이라, 무엇을 세었는지 이름으로 밝힌다.
    커밋과 인계는 원장·이력이라 정확하고, 도구·발화는 이 세션 전사본 기준이다
    (다른 창에서 돈 세션은 포함되지 않는다 — 화면이 그 사실을 적는다).
    """
    out = {"day": tot.get("day"), "tools": tot.get("tools", 0), "says": tot.get("says", 0),
           "agent_done": tot.get("agent_done", 0), "agent_running": tot.get("agent_running", 0),
           "agent_fail": tot.get("agent_fail", 0),
           # 2026-08-15 추가 — `_team()`은 이미 지연(실행 10분 초과) 팀원 수를 세고
           # `tot["agent_delayed"]`에 담아 왔지만, 이 함수가 그 값을 응답에 안 실어
           # 계산만 하고 나가지 않는 코드로 남아 있었다. 지금 화면이 안 쓰더라도 값
           # 자체는 이미 정확하므로(지어낸 수가 아니다) 추가만 한다 — 나중에 지연
           # 카운터 UI를 붙일 때 이 필드를 바로 쓸 수 있다.
           "agent_delayed": tot.get("agent_delayed", 0)}
    try:
        n = subprocess.run(["git", "log", "--since=midnight", "--oneline"],
                           cwd=str(ROOT), capture_output=True, timeout=10)
        out["commits"] = len([x for x in n.stdout.decode("utf-8", "ignore").splitlines() if x.strip()])
    except Exception:                                        # noqa: BLE001
        out["commits"] = None                                # 못 쟀음 — 0 과 구분한다
    if QUEUE.exists():
        try:
            said = 0
            for line in io.open(QUEUE, encoding="utf-8"):
                line = line.strip()
                if line and (json.loads(line).get("ts") or "").startswith(str(out["day"])):
                    said += 1
            out["dash_msgs"] = said
        except Exception:                                    # noqa: BLE001
            out["dash_msgs"] = None
    else:
        out["dash_msgs"] = 0
    return out


@router.get("/stream")
async def stream(request: Request):
    """SSE — 전사본이 자라면 흘려보낸다. 폴링보다 가볍고 즉시 보인다.

    **`time.sleep` 을 쓰지 않는다.** `async def` 안의 `time.sleep` 은 이벤트 루프를
    통째로 멈춘다 — 이 화면을 열어 둔 사람이 **서버의 모든 요청을 느리게 만든다.**
    실측(2026-08-12): 현황판을 켠 채 `/state` 5.2~6.0초 · `/say` 6.0초.
    버튼이 안 먹는 것처럼 보였던 것의 원인이 이것이었다(응답이 늦게 온 것이지
    콜백이 안 돈 게 아니다). `asyncio.sleep` 은 그 동안 루프를 놓아 준다.

    파일 stat 도 루프 위에서 하지 않는다 — 디스크가 느리면 같은 병이 재발한다.
    """
    async def gen():
        last = None
        while True:
            if await request.is_disconnected():
                return
            cur = await asyncio.to_thread(_session_mark)
            if cur != last:
                last = cur
                yield "data: %s\n\n" % json.dumps({"changed": True}, ensure_ascii=False)
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1.5)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _session_mark() -> tuple | None:
    """전사본이 자랐는지 판정할 표식. 스레드에서 부른다."""
    p = _latest_session()
    if p is None:
        return None
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_mtime, st.st_size)


class Say(BaseModel):
    text: str


def _queue_pending() -> list[dict]:
    if not QUEUE.exists():
        return []
    out = []
    for line in _tail_lines(QUEUE, 20):
        try:
            d = json.loads(line)
        except Exception:                                    # noqa: BLE001
            continue
        if not d.get("read"):
            out.append(d)
    return out


@router.post("/say")
def say(body: Say):
    """화면에서 한 마디 — 큐에 넣는다. Monitor 가 보고 깨운다.

    **여기서 세션에 직접 밀어 넣지 않는다.** 그런 경로가 없다(앱 내부다).
    텔레그램과 같은 구조이고, 같은 한계를 갖는다 — 도중에는 못 읽는다.
    """
    t = (body.text or "").strip()
    if not t:
        return {"ok": False, "verdict": "내용 없음"}
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": t[:2000], "read": False}
    with io.open(QUEUE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "verdict": "전달 완료 · 작업 완료 후 읽음"}


# ── 메모 (0044 · 사용자 요청 2026-08-12) ─────────────────────────────────
# 진행 흐름에서 항목을 골라 저장했다가, 나중에 찾아 **다시 세션에 보낸다**(큐 재투입).
# 개인 메모라 삭제를 연다 — 원장이 아니다. 재실행 이력(used_at·used_count)은 남긴다.


class MemoBody(BaseModel):
    content: str
    event_ts: str = ""
    who: str = ""


@router.get("/memos")
def memos():
    from api.db import engine
    from sqlalchemy import text as _t
    with engine.connect() as conn:
        rows = conn.execute(_t(
            "SELECT memo_id, event_ts, who, content, created_at, used_at, used_count"
            " FROM dash_memos ORDER BY memo_id DESC LIMIT 50")).mappings().all()
    return {"ok": True, "memos": [dict(r) for r in rows]}


@router.post("/memos")
def memo_add(body: MemoBody):
    t = (body.content or "").strip()
    if not t:
        return {"ok": False, "verdict": "내용 없음"}
    from api.db import engine
    from sqlalchemy import text as _t
    with engine.begin() as conn:
        mid = conn.execute(_t(
            "INSERT INTO dash_memos (event_ts, who, content) VALUES (:ts, :w, :c)"
            " RETURNING memo_id"),
            {"ts": body.event_ts[:40], "w": body.who[:16], "c": t[:4000]}).scalar()
    return {"ok": True, "memo_id": mid, "verdict": "메모 저장됨"}


@router.post("/memos/{memo_id}/send")
def memo_send(memo_id: int):
    """메모를 큐에 다시 넣는다 — 재실행. 이력을 남긴다."""
    from api.db import engine
    from sqlalchemy import text as _t
    with engine.begin() as conn:
        row = conn.execute(_t(
            "UPDATE dash_memos SET used_at=now(), used_count=used_count+1"
            " WHERE memo_id=:i RETURNING content"), {"i": memo_id}).mappings().first()
    if row is None:
        return {"ok": False, "verdict": "메모 없음"}
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": row["content"][:2000], "read": False}
    with io.open(QUEUE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "verdict": "전달 완료 · 작업 완료 후 읽음"}


@router.delete("/memos/{memo_id}")
def memo_del(memo_id: int):
    from api.db import engine
    from sqlalchemy import text as _t
    with engine.begin() as conn:
        n = conn.execute(_t("DELETE FROM dash_memos WHERE memo_id=:i"), {"i": memo_id}).rowcount
    return {"ok": bool(n), "verdict": "삭제됨" if n else "메모 없음"}


@router.post("/mark-read")
def mark_read():
    """세션이 큐를 읽었다고 표시. 화면의 「대기 중」이 사라진다."""
    if not QUEUE.exists():
        return {"ok": True, "marked": 0}
    lines = io.open(QUEUE, encoding="utf-8").read().splitlines()
    out, n = [], 0
    for line in lines:
        try:
            d = json.loads(line)
        except Exception:                                    # noqa: BLE001
            continue
        if not d.get("read"):
            d["read"] = True
            n += 1
        out.append(json.dumps(d, ensure_ascii=False))
    io.open(QUEUE, "w", encoding="utf-8").write("\n".join(out) + ("\n" if out else ""))
    return {"ok": True, "marked": n}
