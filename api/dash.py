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

■ 다른 모듈이 "하네스에게 알린다" — `notify_harness()` (2026-08-27, 요청·승인 결함⑦)
  화면(`say()`, `POST /say`)이 아니라 **서버 코드**가 알려야 하는 경우(예: 새 요청
  등록)를 위한 진입점이다. `say()`는 이 프로세스의 로컬 디스크(`QUEUE`)에 쓰는데,
  배포 서버는 `ProtectSystem=strict`라 그 경로에 못 쓴다 — 그래서 `notify_harness()`는
  DB(`harness_notify_queue`, 0071)에 쓴다. 읽는 쪽(`_queue_pending()` → `/state`의
  `queued`)은 파일과 DB를 합쳐서 돌려주므로 `scripts/dash_watch.py`는 손대지 않았다.
  상세 근거는 `notify_harness()`/`_db_queue_pending()`/`0071_harness_notify_queue.py`.
"""
import asyncio
import datetime
import hashlib
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

from .timeutil import iso as _iso_tz, now_iso

router = APIRouter(prefix="/api/admin/dash", tags=["admin-dash"])

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / ".claude" / "agents"          # 팀원 정의 정본
# 프로젝트 키 — Claude Code 가 cwd 를 이 규칙으로 접는다 (E:\DEV -> E--DEV)
PROJ_KEY = "E--DEV"
SESS_DIR = Path(os.path.expanduser("~")) / ".claude" / "projects" / PROJ_KEY
QUEUE = ROOT / ".claude" / "dash-queue.jsonl"      # 화면 -> 세션 (우리가 만든 파일)
WATCH_HEARTBEAT = ROOT / ".claude" / "dash-watch.heartbeat"   # 감시자(로컬) 생존 신호


# ── 로컬 / 배포 서버 판정 (2026-08-27 — 「진행 흐름」을 배포 서버에서도 보이게) ──────
#
# 로컬은 세션 전사본(`SESS_DIR`)을 직접 읽는다. 배포 서버에는 그 폴더 자체가 없다
# (사장님 PC 전용 경로라 서버에 배포해도 안 생긴다) — **폴더 유무 자체가 이미 정확한
# 신호**다. 배포마다 별도 설정을 맞출 필요가 없고, 설정을 빼먹어 조용히 틀린 쪽으로
# 판정하는 사고도 없다(설정이 아예 없다).
#
# `POPCORN_DASH_MODE=server|local` 로 강제할 수 있다 — 점검용(예: 로컬에서 "서버라면
# 어떻게 보이는지" 확인). 값이 없거나 다른 문자열이면 자동판정으로 되돌아간다.
def _is_server_mode() -> bool:
    override = os.environ.get("POPCORN_DASH_MODE", "").strip().lower()
    if override in ("server", "local"):
        return override == "server"
    try:
        return not (SESS_DIR.is_dir() and any(SESS_DIR.glob("*.jsonl")))
    except OSError:
        return True


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
                full = re.sub(r"\s+", " ", str(body or ""))
                # 자르기 전에 원문 전체로 검사한다 — 도구 stdout 은 무엇이든 담길 수
                # 있어 Grep·Glob 입력과 같은 절단-미탐 위험이 있다(_tool_detail 참고).
                txt = _REDACTED_MARK if _has_secret(full) else full[:220]
                return {"who": "result", "ts": ts, "blocks": [{"kind": "result", "text": txt}]}
    return None


def _tool_detail(name: str, inp: dict) -> str:
    """도구 호출을 한 줄로. **전체 명령을 그대로 싣지 않는다** — 비밀값이 섞일 수 있다.

    ⚠ **자르기 «전»에 원문 전체로 비밀값을 검사한다**(2026-08-27 결함 수정 — 확인자가
    JWT 를 84자 뒤에 이어붙인 시험으로 재현). 여기서 쓰는 표시 길이(Grep·Glob 70자,
    그 밖 90~110자)는 짧다 — 자른 «뒤»에 검사하면 긴 토큰이 절단 지점에 걸려 남는
    조각이 길이 기준(예: 32자 이상)을 못 채워 미탐이 난다. 그래서 순서를 뒤집었다:
    원문에서 걸리면 잘라 보여주지 않고 통째로 가리고, 안 걸려야만 자른다. Bash 는
    `description` 이 있어 원래도 위험이 낮았지만(자유 서술이라 비밀값이 잘 안 실린다),
    Grep·Glob·Skill·그 밖 MCP 도구(마지막 분기)는 입력 자체가 비밀값일 수 있어 열려
    있었다. `_has_secret`/`_REDACTED_MARK` 는 이 함수보다 아래에 있지만, 파이썬은
    호출 시점에 이름을 찾으므로(모듈이 전부 로드된 뒤 요청이 온다) 문제없다.
    """
    if name == "Bash":
        raw = str(inp.get("description") or inp.get("command") or "")
        if _has_secret(raw):
            return _REDACTED_MARK
        return re.sub(r"\s+", " ", raw)[:110]
    if name in ("Read", "Write", "Edit"):
        raw = str(inp.get("file_path") or "")
        if _has_secret(raw):
            return _REDACTED_MARK
        return raw[-70:]
    if name in ("Grep", "Glob"):
        raw = str(inp.get("pattern") or "")
        if _has_secret(raw):
            return _REDACTED_MARK
        return raw[:70]
    if name == "Agent":
        raw = str(inp.get("subagent_type") or "")
        canon = ALIAS.get(raw, raw)                    # 옛 이름은 지금 이름으로 접는다
        who = TEAM_KO.get(canon, canon)
        desc = str(inp.get("description") or "")
        if _has_secret(desc):
            return _REDACTED_MARK
        return "%s — %s" % (who, desc[:60])
    if name == "Skill":
        raw = str(inp.get("skill") or "")
        if _has_secret(raw):
            return _REDACTED_MARK
        return raw
    raw = json.dumps(inp, ensure_ascii=False)
    if _has_secret(raw):
        return _REDACTED_MARK
    return re.sub(r"\s+", " ", raw)[:90]


# ── 비밀값 가림 — 배포 서버로 밀어 올리기 전에 쓴다 (2026-08-27 · 같은 날 결함 수정) ──
#
# `_tool_detail()`가 이미 명령 전문을 자르지만(위 주석), 잘린 조각 안에도 접속
# 문자열·쿠키·환경변수 식별자가 남을 수 있다(2026-08-26 조사자 전수 검사: 세션
# 전사본에 접속 문자열 2건 · 쿠키·세션 토큰류 241건 · `ADMIN_PW` 식별자 143건 실재).
# 그래서 **감시자가 보내기 전(로컬)** 과 **서버가 받을 때(POST /push)** 두 곳에서
# 같은 이 함수로 한 번씩, 총 두 번 건다 — 감시자 쪽 코드가 낡거나 우회돼도 서버가
# 마지막 방어선이 되게. 의심스러우면 보낸다/보이는다가 아니라 **가린다** 쪽으로 정한다.
#
# ⚠ **결함 수정(확인자 실측)** — `POST /push` 로 넷을 보내니 대조군(접속 문자열)
# 하나만 가려지고 셋이 평문으로 저장됐다: `UI_CHECK_PW=x1y2` · `admin_pw=hunter2`
# (소문자) · `OLD_ADMIN_PW=hunter2new`(접두 변형). 원인 셋, 고침 셋:
#   ① 이 식별자 정규식에 `re.I` 가 없었다(쿠키·세션 패턴엔 있었는데 이 패턴만 없었다)
#      → 추가.
#   ② `\b` 는 `_` 를 «단어 문자»로 봐서 밑줄로 이어붙은 접두(`OLD_ADMIN_PW`)·접미
#      (`ADMIN_PW2`)를 못 가른다 → `\b` 를 없애 **부분 문자열 포함**으로 바꿨다
#      (의심 기준 검사이므로 과탐은 감수한다 — 위 주석 그대로).
#   ③ `UI_CHECK_PW` 처럼 이 프로젝트가 실제로 쓰는 이름이 하드코딩 목록에 없었다
#      → 아래 `_secret_names()` 가 `.env` 류 파일의 **키 이름만** 동적으로 읽어 채운다.
_SECRET_PATTERNS = [
    # DB·서비스 접속 문자열: scheme://user:pass@host
    re.compile(r"[a-zA-Z][\w+.\-]{1,20}://[^\s'\"<>]+:[^\s'\"<>@]+@[^\s'\"<>]+"),
    # .env 식별자 «생김새» — 아직 아래 동적 목록에 없는 새 이름도 관례로 잡는 2차 방어선.
    # re.I 로 대소문자 무시, `\b` 없이(밑줄·숫자로 이어붙은 접두·접미 변형까지 잡는다).
    re.compile(r"(ADMIN_PW|ADMIN_EMAIL|DATABASE_URL|[A-Z][A-Z0-9_]*PASSWORD[A-Z0-9_]*"
               r"|[A-Z][A-Z0-9_]*SECRET[A-Z0-9_]*|[A-Z][A-Z0-9_]*API_?KEY[A-Z0-9_]*"
               r"|[A-Z][A-Z0-9_]*ACCESS_?KEY[A-Z0-9_]*|PRIVATE_KEY)", re.I),
    # 관리자 세션 쿠키(api/auth.py COOKIE) · 쿠키·세션 헤더 모양
    re.compile(r"popcorn_admin_session|Set-Cookie\s*:|(?<![A-Za-z])Cookie\s*:", re.I),
    re.compile(r"\bsession(_id)?\s*=\s*[A-Za-z0-9%._-]{12,}", re.I),
    # JWT 모양(header.payload.signature)
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    # 순수 16진수 32자 이상 — 해시·토큰
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
]

# ── 비밀값 «이름» 목록 — 하드코딩하지 않고 실제 설정 파일에서 읽는다 ─────────────
#
# 위 정규식의 PASSWORD/SECRET/API_KEY 류 「생김새」 규칙은 그 관례를 따르지 않는
# 이름(`UI_CHECK_PW` 처럼 짧은 약어)을 못 잡는다. 그렇다고 이름을 이 파일에 목록으로
# 박으면 새 비밀값이 생길 때마다 이 파일을 고쳐야 하고, 안 고치면 다시 낡는다(이번
# 결함이 그렇게 생겼다). 그래서 **값은 절대 읽지 않고 키 «이름»만** 두 후보 경로에서
# 읽는다 — 존재하는 파일만 읽고 없으면 조용히 건너뛴다(다른 OS·환경엔 나머지 하나가
# 원래 없다):
#   로컬 개발 PC(윈도우)   프로젝트 루트 `.env`
#   배포 서버(리눅스)      systemd 가 읽는 `/etc/popcorn-ai.env`
#                         (전역 CLAUDE.md 정본 경로 — 배포 명령이 이 파일을 그대로
#                         source 한다. `api/db.py` 의 `load_dotenv(REPO_ROOT/".env")`는
#                         배포 서버에 그 파일이 없으면 조용히 no-op 이라, 서버의 실제
#                         비밀값은 이 경로로 들어온다고 봐야 한다 — 그래서 이 경로도
#                         봐야 "서버가 마지막 방어선" 이라는 설계 의도가 서버에서도
#                         실제로 선다)
# 새 비밀값을 `.env`(또는 `/etc/popcorn-ai.env`)에 추가하면, 프로세스 재시작 없이도
# (mtime 캐시라) 다음 호출부터 자동으로 가림 대상에 들어간다 — 이 파일을 고칠 일이 없다.
_ENV_CANDIDATES = [ROOT / ".env", Path("/etc/popcorn-ai.env")]
_env_names_cache: dict = {"sig": None, "names": frozenset()}


def _env_secret_names() -> frozenset:
    """후보 경로들의 키 «이름»만 읽는다 — 값은 절대 읽지도 돌려주지도 않는다."""
    names = set()
    for path in _ENV_CANDIDATES:
        try:
            for line in io.open(path, encoding="utf-8", errors="ignore"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip()
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                    names.add(key.upper())
        except OSError:
            continue
    return frozenset(names)


def _secret_names() -> frozenset:
    """`_env_secret_names()` 캐시 — 후보 파일들의 mtime 서명이 바뀌면 다시 읽는다."""
    sig = []
    for path in _ENV_CANDIDATES:
        try:
            sig.append(path.stat().st_mtime)
        except OSError:
            sig.append(None)
    sig_t = tuple(sig)
    if _env_names_cache["sig"] != sig_t:
        _env_names_cache["names"] = _env_secret_names()
        _env_names_cache["sig"] = sig_t
    return _env_names_cache["names"]


def _has_secret(text) -> bool:
    """비밀값처럼 «보이는» 문자열인가. 확신이 아니라 의심 기준 — 과탐이 누락보다 낫다."""
    t = str(text or "")
    if not t:
        return False
    for pat in _SECRET_PATTERNS:
        if pat.search(t):
            return True
    # `.env` 류 파일에 실재하는 키 이름 — 대소문자 무시 + 부분 문자열 포함(접두·접미
    # 변형도 잡는다: "OLD_ADMIN_PW"·"ADMIN_PW2" 는 "ADMIN_PW" 를 부분 문자열로 담는다).
    names = _secret_names()
    if names:
        tu = t.upper()
        for name in names:
            if name in tu:
                return True
    # 공백 없이 32자 이상 이어지고 대/소문자·숫자가 섞인 덩어리 — 토큰으로 의심
    for m in re.finditer(r"[A-Za-z0-9+/_=-]{32,}", t):
        s = m.group(0)
        if re.search(r"[A-Z]", s) and re.search(r"[a-z]", s) and re.search(r"[0-9]", s):
            return True
    return False


_REDACTED_MARK = "[가림 — 비밀값으로 보여 전송 제외]"


def _event_hash(e: dict) -> str:
    """사건 하나의 안정된 지문 — 감시자의 "본 것" 기억과 서버의 중복 거르기가 **같은
    정의**를 쓴다(결함 ③ 수정, 2026-08-27).

    `who`·`ts`·`blocks`(가리기 «전» 원문)로 만든다 — 내용이 같으면 감시자가 재시작돼
    다시 보내거나, 여러 세션이 겹쳐 같은 사건을 보내도 항상 같은 값이 나온다.
    `tokens`·`agents` 는 뺀다 — 사건의 「같음」과 무관한 부가 집계라 흔들려도 판정이
    갈리면 안 된다. `blocks` 는 `sort_keys=True` 로 직렬화해 키 순서 차이를 없앤다.

    ⚠ **가리기 «전» 내용으로 잰다.** `_redact_event()` 뒤의 내용으로 재면, 서로 다른
    비밀값을 담은 서로 다른 사건이 똑같은 `[가림 — ...]` 문구로 바뀐 뒤 우연히 같은
    지문이 될 수 있다 — 사건의 정체성은 원문이 정하는 것이지 가림 문구가 정하는 게
    아니다.

    ⚠ **서버(`push_events`)는 감시자가 보낸 값을 믿지 않고 받은 내용으로 스스로 다시
    계산한다.** 로컬 감시자와 배포 서버가 서로 다른 시점에 배포된 `api/dash.py` 를
    돌 수 있어(감시자는 재시작 전까지 옛 리비전을 계속 import 한다) 클라이언트가
    보낸 해시를 그대로 신뢰하면 두 프로세스의 계산이 어긋날 수 있다 — 서버가 자기가
    저장할 내용으로 직접 계산하면 이 위험이 아예 없다.
    """
    try:
        blob = json.dumps({"who": e.get("who"), "ts": e.get("ts"), "blocks": e.get("blocks") or []},
                          ensure_ascii=False, sort_keys=True, default=str)
    except Exception:                                            # noqa: BLE001
        blob = "%s|%s|%s" % (e.get("who"), e.get("ts"), e.get("blocks"))
    return hashlib.sha1(blob.encode("utf-8", "ignore")).hexdigest()


def _redact_event(e: dict) -> tuple[dict, int]:
    """사건 하나(`_event()` 결과와 같은 모양)의 블록을 검사해 의심스러운 것만 가린다.

    블록 단위로 가린다 — 한 사건에 도구 호출 여러 개가 섞여 있으면 그중 의심되는
    것만 지우고 나머지는 남긴다(사건 전체를 지우면 화면에서 맥락이 통째로 빈다).
    반환값 둘째 항목은 이번에 가린 블록 수 — 호출부가 「몇 건 가렸는지」를 잴 때 쓴다.

    ⚠ **결함 수정(2026-08-27)** — 적중 판정은 `detail`·`text`·`name` 셋을 다 보면서
    실제로 지우는 것은 `detail`·`text` 둘뿐이었다(비대칭). `name`(도구 이름, 예:
    "Bash")이 단독으로 걸리는 경우는 실무에서 사실상 없지만(도구 이름은 고정된
    목록이라 사용자 입력이 아니다), 판정과 처리가 다른 필드를 보면 "가렸다고
    세어 놓고 안 가린" 상태가 생긴다 — 판정한 필드는 전부 지운다.
    """
    n = 0
    blocks = []
    for b in (e.get("blocks") or []):
        if not isinstance(b, dict):
            continue
        bb = dict(b)
        hit = False
        for key in ("detail", "text", "name"):
            v = bb.get(key)
            if v is not None and _has_secret(v):
                hit = True
                break
        if hit:
            for key in ("detail", "text", "name"):
                if key in bb:
                    bb[key] = _REDACTED_MARK
            n += 1
        blocks.append(bb)
    out = dict(e)
    out["blocks"] = blocks
    return out, n


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


def _recent_events(limit: int = 60, path: Path | None = None) -> list[dict]:
    """윈도 사건 목록 — `state()` 의 기본(팀원 필터 없음) 경로가 쓰던 로직을 뺐다(2026-08-27).

    **감시자(`scripts/dash_watch.py`)가 배포 서버로 밀어 올릴 때도 이 함수를 그대로
    부른다** — 화면에 보이는 것과 서버로 올라가는 것이 다른 코드에서 각자 계산되면
    둘이 갈라질 위험이 생긴다(같은 정의를 두 곳에 적지 않는다는 원칙, CANON.md).
    `path` 를 안 주면 `_latest_session()` 으로 스스로 찾는다 — `state()` 호출 맥락
    밖(감시자 프로세스)에서도 단독으로 쓸 수 있게.
    """
    p = path or _latest_session()
    if p is None:
        return []
    sc = _scan(p)                       # 자란 만큼만 읽음 — 반복 호출에 안전(오프셋 기억)
    id2agent = sc.get("agent_ids", {})
    evts = []
    for line in _tail_lines(p, limit * 6):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:                                        # noqa: BLE001
            continue
        e = _event(o)
        if e is None:
            continue
        e["agents"] = _event_agents(o, id2agent)   # 팀원 카드 필터가 쓴다(클라 추측 없음)
        evts.append(e)
    return evts[-limit:]


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

    **배포 서버에서는 세션 전사본이 없다**(2026-08-27) — `_is_server_mode()` 가
    참이면 `_state_server()` 로 넘긴다. 응답 모양은 그대로다(화면 템플릿 불변).
    """
    if watcher:
        _WATCH_PING["ts"] = time.time()
        _WATCH_PING["iso"] = now_iso()          # 타임존 포함 — naive면 배포 서버(UTC)를 브라우저가 로컬로 오독한다(timeutil)
    if _is_server_mode():
        return _state_server(limit=limit, agent=(agent or "").strip())
    p = _latest_session()
    if p is None:
        return {"ok": False, "reason": "세션 전사본 없음", "dir": str(SESS_DIR),
                "events": [], "agents": [], "agents_older": 0,
                "agents_window_min": AGENT_WINDOW_S // 60, "queued": _queue_pending(),
                "watcher": _watcher(), "mode": "local"}
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
        evts = _recent_events(limit, path=p)
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
        "mode": "local",                     # 로컬(전사본 직접 읽기) — _state_server()는 "server"
    }


# 서버에 마지막으로 데이터가 올라온 지 이만큼(초) 지나면 「오래됨」이다 — 감시자 폴링
# 주기(30초)의 20배. `_team()` 의 팀원 지연 기준(DELAY_S=600, 10분)과 같은 값을 쓴다
# — 근거를 새로 만들지 않고 이미 있는 "10분이면 물린 것" 판단을 그대로 재사용한다.
PUSH_STALE_S = 600


def _state_server(limit: int = 40, agent: str = "") -> dict:
    """배포 서버용 `/state` — 로컬 전사본 대신 `dash_events`(감시자가 밀어 올린 것)를 읽는다.

    **응답 모양은 로컬과 같다** — 화면(`dash.html.j2`)을 바꾸지 않기 위해서다. 다른 점은
    ① `events` 의 원천이 DB ② `session`/`idle_s` 가 "전사본 신선도"가 아니라 "마지막으로
    올라온 시각까지의 경과"를 뜻한다(그래서 기존 dot·상태 문구 로직이 손 안 대고도 맞게
    작동한다 — 8초 미만 "작업 중", 120초 미만 "대기", 그 이상 "멈춤 N분") ③ `push` 필드가
    추가로 붙는다 — 화면의 작은 추가 배지(헤더) 하나가 이 값을 읽는다(§④, template 쪽
    최소 추가).

    팀원 명단(`roster`)은 `_team()` 을 그대로 부른다 — `.claude/agents/*.md` 는 git으로
    배포되므로 이름·역할은 정확히 나온다. 다만 실행 중/완료 같은 **활동 수치는 여기서
    잴 방법이 없어 전부 0/대기로 나온다**(전사본이 없다) — 지어내지 않고 정직하게 비운다.
    팀원 카드·백그라운드 작업 배지는 이번 작업 범위가 아니다(지시서 §범위 밖).
    """
    roster, tot = _team()
    team_unmapped = [a["name"] for a in roster if a.get("defined") and not a.get("ko_mapped", True)]
    try:
        from api.db import engine
        from sqlalchemy import text as _t
        with engine.connect() as conn:
            rows = conn.execute(_t(
                "SELECT ev_ts, who, blocks, agents, tokens FROM dash_events"
                " ORDER BY event_id DESC LIMIT :n"), {"n": max(limit, 1) * 3}).mappings().all()
            summary = conn.execute(_t(
                "SELECT MAX(received_at) AS last_at, COUNT(*) AS n FROM dash_events")).mappings().first()
    except Exception as e:                                        # noqa: BLE001
        # DB 예외 원문을 그대로 내보내지 않는다(CLAUDE.md 규약) -- 예외 종류만 알린다.
        return {"ok": False, "reason": "진행 흐름 DB 조회 실패: %s" % type(e).__name__,
                "events": [], "agents": [], "agents_older": 0,
                "agents_window_min": AGENT_WINDOW_S // 60, "queued": _queue_pending(),
                "watcher": _watcher(), "roster": roster, "today": _today(tot),
                "team_unmapped": team_unmapped, "mode": "server"}
    evts = []
    for r in reversed(rows):                    # DESC 로 뽑았으니 화면 순서(오래된 -> 최신)로 되돌린다
        blocks = r["blocks"] if isinstance(r["blocks"], list) else (json.loads(r["blocks"]) if r["blocks"] else [])
        ags = r["agents"] if isinstance(r["agents"], list) else (json.loads(r["agents"]) if r["agents"] else None)
        evts.append({"who": r["who"], "ts": r["ev_ts"], "blocks": blocks,
                     "tokens": r["tokens"], "agents": ags or ["harness"]})
    agent_filter = None
    if agent:
        evts = [e for e in evts if agent in (e.get("agents") or ["harness"])]
        agent_filter = agent
    evts = evts[-limit:]
    last_at = summary["last_at"] if summary else None
    n_total = int(summary["n"]) if summary and summary["n"] is not None else 0
    now = datetime.datetime.now(datetime.timezone.utc)
    if last_at is not None:
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=datetime.timezone.utc)
        # 로컬-DB 서버 간 초 단위 시계 오차로 음수가 나올 수 있다(실측) — 0으로 붙인다.
        age_s = max(0, int((now - last_at).total_seconds()))
    else:
        age_s = None
    return {
        "ok": True,
        "session": None,                        # 로컬처럼 "세션 파일 하나"가 아니다 — 화면은 빈칸으로 둔다
        "idle_s": age_s if age_s is not None else 999999,  # 재사용: "마지막 수신 후 경과"(위 함수 docstring ②)
        "size_mb": 0,
        "events": evts,
        "agent_filter": agent_filter,
        "agents": [], "agents_older": 0,         # 백그라운드 작업 배지 — 서버에서는 알 길이 없다(범위 밖)
        "agents_window_min": AGENT_WINDOW_S // 60,
        "queued": _queue_pending(),              # 서버 자신의 큐 파일(로컬과 별개 — 기존 동작 그대로)
        "roster": roster,
        "today": _today(tot),
        "watcher": _watcher(),
        "team_unmapped": team_unmapped,
        "mode": "server",
        "push": {                                # §④ — 화면의 작은 추가 배지가 읽는다(template 최소 추가)
            "last": _iso_tz(last_at) if last_at is not None else None,
            "age_s": age_s,
            "stale": age_s is None or age_s > PUSH_STALE_S,
            "count": n_total,
        },
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


def _db_queue_pending() -> list[dict]:
    """`harness_notify_queue`(0071)의 미읽음 — say()/`QUEUE` 파일의 «DB 짝»
    (`notify_harness()` 아래 참조 — 배포 서버는 파일을 못 쓴다).

    실패해도 `_queue_pending()`(따라서 `/state` 전체)을 죽이지 않는다 — 알림 큐 하나
    때문에 현황판이 500이 되면 안 된다. 마이그레이션 0071 이 아직 없는 환경(구 DB)에서도
    이 함수는 조용히 빈 목록을 돌려준다.
    """
    try:
        from .db import engine
        from sqlalchemy import text as _t
        with engine.connect() as conn:
            rows = conn.execute(_t(
                "SELECT text, created_at FROM harness_notify_queue"
                " WHERE read_at IS NULL ORDER BY notify_id LIMIT 20")).mappings().all()
        return [{"ts": _iso_tz(r["created_at"]), "text": r["text"], "read": False} for r in rows]
    except Exception as e:                                     # noqa: BLE001
        print(f"[dash] harness_notify_queue read failed: {type(e).__name__}: {e}")
        return []


def _queue_pending() -> list[dict]:
    """`poll()`(`scripts/dash_watch.py`)이 보는 `queued` — 파일 큐 + DB 큐(0071)를 합친다.

    `poll()`은 원소가 어디서 왔는지 모른다(`{"ts","text"}` 모양만 본다) — 그래서 합쳐도
    감시자 쪽은 한 글자도 안 고친다. 순서는 파일 먼저 · DB 나중(둘 다 대체로 시각순이라
    크게 안 어긋난다 — 엄격한 전역 정렬이 필요해지면 그때 합쳐서 정렬한다).
    """
    out = []
    if QUEUE.exists():
        for line in _tail_lines(QUEUE, 20):
            try:
                d = json.loads(line)
            except Exception:                                    # noqa: BLE001
                continue
            if not d.get("read"):
                out.append(d)
    out.extend(_db_queue_pending())
    return out


@router.post("/say")
def say(body: Say):
    """화면에서 한 마디 — 큐에 넣는다. Monitor 가 보고 깨운다.

    **여기서 세션에 직접 밀어 넣지 않는다.** 그런 경로가 없다(앱 내부다).
    텔레그램과 같은 구조이고, 같은 한계를 갖는다 — 도중에는 못 읽는다.

    ⚠ **로컬 전용이라 봐도 된다.** 배포 서버는 이 파일(`QUEUE`)에 못 쓴다
    (`notify_harness()` 문서 참조) — 배포 서버에서 이 엔드포인트를 부르면 500이 난다.
    다른 모듈이 "하네스에게 알린다"를 하려면 이 엔드포인트를 부르지 말고
    `notify_harness()`를 직접 부른다(로컬·배포 어디서도 동작한다).
    """
    t = (body.text or "").strip()
    if not t:
        return {"ok": False, "verdict": "내용 없음"}
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": t[:2000], "read": False}
    with io.open(QUEUE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "verdict": "전달 완료 · 작업 완료 후 읽음"}


# ── DB 큐 쓰기 — say() 의 짝, 배포 서버에서도 동작한다 (2026-08-27, 요청·승인 결함⑦) ──
def notify_harness(message: str, *, source: str = "") -> bool:
    """다른 모듈이 "하네스에게 알린다"고 부르는 단일 진입점.

    `say()`와 목적은 같지만(큐에 한 줄 넣기 — Monitor 가 보고 깨운다) **DB**
    (`harness_notify_queue`, 0071)에 쓴다. `say()`는 이 프로세스 자신의 로컬 디스크에
    쓰는데, 배포 서버는 systemd `ProtectSystem=strict`라 `.claude/`(QUEUE 가 가리키는
    경로)에 쓰기가 막혀 있다(`deploy/popcorn-api.service`의 `ReadWritePaths`는 `.cache`
    하나뿐 — 2026-08-27 실측). `say()`를 그대로 불렀다면 배포 서버에서 조용히 실패해
    "알렸다는데 아무도 못 받는" 사고가 났을 것이다 — 캡처 · 「진행 흐름」이 같은 systemd
    제약을 이미 두 번 우회한 것과 같은 판단으로 DB를 골랐다(모듈 0071 참조).

    **실패해도 예외를 던지지 않는다** — 알림은 부가 기능이지, 이걸 부르는 쪽의 원래
    동작(예: 요청 등록)이 알림 실패 때문에 500이 되면 안 된다. 실패는 콘솔에만 남는다
    (ASCII 만 — cp949 stdout 이 em-dash·화살표를 만나면 500을 낸 전례가 있다, 그래서
    이 함수 자신의 로그 문자열에도 그 규칙을 지킨다).

    쓸 때마다 **읽은 지 30일 지난 행**을 함께 지운다(`dash_events`처럼 별도 배치를
    두지 않는다 — 이 표는 쓰기 빈도가 훨씬 낮아 사흘이 아니라 30일로 느슨하게 잡았다).
    미읽음 행은 지우지 않는다 — 감시자가 오래 꺼져 있어도 알림 자체가 사라지면 안 된다.
    """
    text_ = (message or "").strip()
    if not text_:
        return False
    try:
        from .db import engine
        from sqlalchemy import text as _t
        with engine.begin() as conn:
            conn.execute(_t(
                "INSERT INTO harness_notify_queue (text, source) VALUES (:t, :s)"),
                {"t": text_[:2000], "s": (source or "")[:40]})
            conn.execute(_t(
                "DELETE FROM harness_notify_queue"
                " WHERE read_at IS NOT NULL AND read_at < now() - interval '30 days'"))
        return True
    except Exception as e:                                     # noqa: BLE001
        print(f"[dash] notify_harness failed: {type(e).__name__}: {e}")
        return False


# ── 진행 흐름 밀어 올리기 — 감시자 -> 배포 서버 (2026-08-27 신설) ────────────────
#
# 로컬 감시자(`scripts/dash_watch.py`)가 `_recent_events()` 로 뽑은 것과 **같은 모양**
# (who·ts·blocks·tokens·agents)을 그대로 받는다 — 원문 전사본 줄이 아니다. 받은 뒤에도
# `_redact_event()` 로 한 번 더 가린다(감시자 쪽 필터가 낡거나 우회돼도 여기가 마지막
# 방어선). `dash_events` 는 원장이 아니라 표시용 캐시라 매 호출마다 보관 기간을 넘긴
# 것을 함께 정리한다(별도 배치 불필요 — 0068 마이그레이션 설명 참조). 같은 사건이
# 두 번 오면 `event_hash` 유니크 인덱스가 한 벌만 남긴다(0069 마이그레이션 —
# `_event_hash()`/`push_events()` 결함 ③ 수정 참고).
class PushEventIn(BaseModel):
    ts: str | None = None
    who: str | None = None
    blocks: list = []
    tokens: int | None = None
    agents: list[str] | None = None


class PushBody(BaseModel):
    session: str = ""
    events: list[PushEventIn] = []


DASH_EVENTS_KEEP_DAYS = 3        # dash_events 보관 기간 — 원장이 아니라 표시 캐시다
DASH_EVENTS_KEEP_ROWS = 5000     # 화면이 실제 보는 건 limit(기본 40~60)뿐 — 넉넉한 상한
PUSH_BATCH_CAP = 200             # 한 요청에 담을 수 있는 사건 수 — 폭주 방지


@router.post("/push")
def push_events(body: PushBody):
    """감시자가 로컬 「진행 흐름」을 배포 서버로 민다.

    `/api/admin/dash/*` 전체와 같은 세션 인증을 그대로 받는다(`api/auth.py` 미들웨어) —
    이 라우트만 따로 여는 예외를 만들지 않았다. 성공 여부와 무관하게 `_WATCH_PING`
    을 갱신한다 — 이 호출 자체가 "감시자가 방금 서버에 닿았다"는 증거이기 때문이다
    (`?watcher=1` 핑과 같은 취급).

    ⚠ **결함 수정(2026-08-27) — 서버가 중복을 거른다.** 확인자 실측: 같은 사건을 두
    번 보내면 매번 `inserted:1` 이 나와 행이 둘 생겼다 — 서버 쪽 중복 방어가
    «전무»했다. 감시자가 실패 뒤 재시도하면(`scripts/dash_watch.py` 결함 ② 수정)
    같은 사건을 두 번 보낼 수 있고, 이 프로젝트는 **세션마다 감시자를 새로 띄우라고
    지시**해(`CLAUDE.md` §첫 세션 시작 ④) 재시작될 때마다 최근 60건을 다시 밀어
    올릴 수 있다 — 정상적인 사용 자체가 중복을 만든다. 그래서 `event_hash`
    (`_event_hash()`, 0069 마이그레이션의 유니크 인덱스)로 DB 가 원자적으로 막는다.
    **유니크 인덱스를 골랐다** — 삽입 직전 SELECT 로 존재를 먼저 물으면 두 요청이
    거의 동시에 오면 둘 다 "없음"을 보고 둘 다 INSERT 하는 경합(TOCTOU)이 생긴다.
    `ON CONFLICT ... DO NOTHING` 은 DB 가 원자적으로 처리해 그 경합이 없다.
    **해시는 감시자가 보낸 값을 쓰지 않고 서버가 받은 내용으로 스스로 계산한다**
    (`_event_hash` 문서 참고 — 감시자·서버가 서로 다른 리비전을 돌 수 있어서다).
    """
    _WATCH_PING["ts"] = time.time()
    _WATCH_PING["iso"] = now_iso()
    evs = body.events[:PUSH_BATCH_CAP]
    if not evs:
        return {"ok": True, "inserted": 0, "redacted": 0, "duplicate": 0}
    from api.db import engine
    from sqlalchemy import text as _t
    inserted = redacted = duplicate = 0
    with engine.begin() as conn:
        for ev in evs:
            raw = ev.model_dump()
            h = _event_hash(raw)                    # 가리기 «전» 원문으로 지문을 낸다
            e, n = _redact_event(raw)
            redacted += n
            row = conn.execute(_t(
                "INSERT INTO dash_events (session_id, ev_ts, who, blocks, agents, tokens, source, event_hash)"
                " VALUES (:sid, :ts, :who, CAST(:blocks AS JSONB), CAST(:agents AS JSONB), :tok, :src, :h)"
                " ON CONFLICT (event_hash) DO NOTHING"),
                {"sid": (body.session or "")[:80], "ts": str(e.get("ts") or "")[:40],
                 "who": str(e.get("who") or "")[:16],
                 "blocks": json.dumps(e.get("blocks") or [], ensure_ascii=False),
                 "agents": json.dumps(e.get("agents") or [], ensure_ascii=False),
                 "tok": e.get("tokens"), "src": "dash_watch", "h": h})
            if row.rowcount:
                inserted += 1
            else:
                duplicate += 1               # event_hash 충돌 — 이미 저장된 사건, 새 행 없음
        # 보관 정책 — 원장이 아니다. 사흘 지난 것과 최신 5,000행을 넘는 것을 지운다
        # (0068 마이그레이션 설명 §보관). 푸시가 들어올 때 함께 돈다 — 별도 배치가 없다.
        conn.execute(_t("DELETE FROM dash_events WHERE received_at < now() - make_interval(days => :d)"),
                     {"d": DASH_EVENTS_KEEP_DAYS})
        conn.execute(_t(
            "DELETE FROM dash_events WHERE event_id NOT IN"
            " (SELECT event_id FROM dash_events ORDER BY event_id DESC LIMIT :keep)"),
            {"keep": DASH_EVENTS_KEEP_ROWS})
    return {"ok": True, "inserted": inserted, "redacted": redacted, "duplicate": duplicate}


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
    """세션이 큐를 읽었다고 표시. 화면의 「대기 중」이 사라진다.

    파일 큐 «와» DB 큐(`harness_notify_queue`, 0071) 둘 다 마크한다(2026-08-27,
    `notify_harness()` 가 생기면서 — 파일만 마크하면 DB 쪽 알림이 30초마다 계속
    다시 나온다). 둘 다 **블랭킷**(지금 미읽음 전부)으로 마크한다 — 파일 쪽의 기존
    정책 그대로다. 파일이 없거나 DB 에 미읽음이 없어도 실패로 보지 않는다.
    """
    n = 0
    if QUEUE.exists():
        lines = io.open(QUEUE, encoding="utf-8").read().splitlines()
        out = []
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
    try:
        from .db import engine
        from sqlalchemy import text as _t
        with engine.begin() as conn:
            r = conn.execute(_t(
                "UPDATE harness_notify_queue SET read_at = now() WHERE read_at IS NULL"))
            n += r.rowcount
    except Exception as e:                                       # noqa: BLE001
        print(f"[dash] harness_notify_queue mark-read failed: {type(e).__name__}: {e}")
    return {"ok": True, "marked": n}
