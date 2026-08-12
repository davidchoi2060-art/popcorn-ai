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
import io
import json
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/admin/dash", tags=["admin-dash"])

ROOT = Path(__file__).resolve().parent.parent
# 프로젝트 키 — Claude Code 가 cwd 를 이 규칙으로 접는다 (E:\DEV -> E--DEV)
PROJ_KEY = "E--DEV"
SESS_DIR = Path(os.path.expanduser("~")) / ".claude" / "projects" / PROJ_KEY
QUEUE = ROOT / ".claude" / "dash-queue.jsonl"      # 화면 -> 세션 (우리가 만든 파일)

# 팀원 이름 -> 한글. `.claude/agents/*.md` 가 정본이고 여기는 표시용이다.
TEAM_KO = {
    "investigator": "조사자", "maker": "제작자", "checker": "확인자",
    "writer": "문장가", "dba": "DBA", "crosschecker": "검증자", "sweeper": "점검자",
    "general-purpose": "범용", "Explore": "탐색", "Plan": "계획",
}


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
                out.append({"kind": "say", "text": (c["text"] or "").strip()[:600]})
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
        who = TEAM_KO.get(str(inp.get("subagent_type") or ""), inp.get("subagent_type") or "")
        return "%s — %s" % (who, str(inp.get("description") or "")[:60])
    if name == "Skill":
        return str(inp.get("skill") or "")
    return re.sub(r"\s+", " ", json.dumps(inp, ensure_ascii=False))[:90]


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


@router.get("/state")
def state(limit: int = 40):
    """현황 한 벌. 화면이 주기적으로 부른다."""
    p = _latest_session()
    if p is None:
        return {"ok": False, "reason": "세션 전사본 없음", "dir": str(SESS_DIR),
                "events": [], "agents": [], "agents_older": 0,
                "agents_window_min": AGENT_WINDOW_S // 60, "queued": _queue_pending()}
    evts = []
    for line in _tail_lines(p, limit * 6):
        line = line.strip()
        if not line:
            continue
        try:
            e = _event(json.loads(line))
        except Exception:                                    # noqa: BLE001
            continue
        if e:
            evts.append(e)
    st = p.stat()
    agents, agents_older = _bg_tasks()
    return {
        "ok": True,
        "session": p.stem,
        "idle_s": int(time.time() - st.st_mtime),
        "size_mb": round(st.st_size / 1e6, 1),
        "events": evts[-limit:],
        "agents": agents,
        "agents_older": agents_older,        # 창 밖 — 「없다」와 구분해 화면이 적는다
        "agents_window_min": AGENT_WINDOW_S // 60,
        "queued": _queue_pending(),
    }


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
