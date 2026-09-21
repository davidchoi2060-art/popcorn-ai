# -*- coding: utf-8 -*-
"""위키백과 조회 — 게임 소개를 «그때그때» 채운다. **유사도 관문 필수.**

사장님 확정(2026-09-21): "웹검색은 위키백과만 쓰되 유사도 관문을 건다. 못 찾으면
「자료 없음」으로 둔다." 일반 검색 API 는 이 환경에서 전부 막혔다(설계서 §4-1 실측:
DuckDuckGo CAPTCHA · Bing 파싱 불가 · Gemini grounding 429).

■ 왜 이 모듈이 필요한가
  `games.description` 은 86/86 채워져 있지만 **«게임 소개»가 아니라 사양 부하 메모**다
  (평균 70자 · 발로란트·오버워치2·배그가 거의 같은 문장). 고객에게 그대로 읽어주면
  안 된다. 「무슨 게임인가」 컬럼은 **0/86** 이라 웹으로 채운다(설계서 §1-3 U2).

■ ★ 유사도 관문 — 이 한 줄이 10건의 거짓을 막았다
  설계서 §4-1 실측: search 경유 31건 중 **10건이 오매칭**이었다.
      아이온2 -> 리튬 이온 전지      아크 서바이벌 -> 아이언 (래퍼)
      워독스 -> 문호 스트레이 독스    패스 오브 엑자일2 -> 카카오게임즈
      MS 플라이트 시뮬레이터 2024 -> IBM PC 호환기종   리니지 클래식 -> 엔씨
  선행 조사는 "게임 이름은 오매핑할 대상이 없다"고 했지만 **실측이 반박했다.**
  정규화 후 `SequenceMatcher >= 0.6` **또는** 포함 관계일 때만 쓴다.

■ ★ 근거 80자 문턱 — 「배틀그라운드 19자」 사고
  위키 본문이 19자뿐인데 haiku 가 204토큰짜리 그럴듯한 설명을 냈다. 내용은 맞지만
  **근거에 없던 말**이다(모델이 사전지식으로 메웠다). 그래서 **근거 본문이 80자
  미만이면 그 근거로 문장을 만들지 않는다.** 이 문턱은 커버리지 측정에 쓴 값과 같아
  두 벌로 두지 않는다.

■ 예절
  · 위키백과만 부른다. UA 에 연락처를 싣는다(없으면 403 — 실측).
  · 원문은 `.cache/wiki/` 에 둔다(gitignore). 같은 게임은 고객마다 답이 같다.
  · 타임아웃은 짧게(설계서 §4-2: 웹검색 3.5초).
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = _ROOT / ".cache" / "wiki"

# 설계서 §4-1 실측값 그대로. 여기 말고 다른 곳에 적지 않는다.
SIMILARITY_MIN = 0.6      # 제목 유사도 관문
EXTRACT_MIN_CHARS = 80    # 근거 문턱 — 이 밑이면 문장을 만들지 않는다
TIMEOUT_SEC = 3.5         # 실측 p90 3.09초 + 여유

_SUMMARY_URL = "https://ko.wikipedia.org/api/rest_v1/page/summary/%s"
_SEARCH_URL = ("https://ko.wikipedia.org/w/api.php?action=query&list=search"
               "&srsearch=%s&srlimit=3&format=json")
# UA 에 연락처가 없으면 403 이다(실측). 위키백과 예절 규약.
_UA = ("PopcornPC-Talk/1.0 (https://popcorn-pc.example; contact: ops@popcorn-pc.example)"
       " python-urllib")


@dataclass
class WikiResult:
    ok: bool
    title: str | None = None
    extract: str = ""
    url: str | None = None
    reason: str = ""          # 실패 사유(ASCII) — 삼키지 않는다
    similarity: float | None = None
    from_cache: bool = False
    elapsed_sec: float = 0.0


def _norm_title(s: str) -> str:
    """제목 비교용 정규화 — 공백·구분기호 제거 + casefold.

    `talk_schema._norm_name` 과 같은 뜻의 처리지만 저쪽은 «게임명 -> DB 게임명» 대조용
    이고 여기는 «게임명 -> 위키 표제어» 대조용이라 소비처가 다르다. 로마숫자·아라비아
    숫자 혼용(\"아이온2\"/\"아이온 II\")까지 보려면 이 자리가 더 커져야 한다 — 지금은
    실측된 오매칭을 막는 데 필요한 만큼만 한다.
    """
    s = re.sub(r"\(.*?\)", "", s or "")          # 위키 동음이의 괄호
    return "".join(ch for ch in s if ch not in " \t·:-_.,()[]'\"" ).casefold()


def title_similarity(query: str, title: str) -> float:
    """정규화 후 유사도 0.0~1.0. 포함 관계면 1.0 으로 본다(짧은 쪽 2자 이상)."""
    q, t = _norm_title(query), _norm_title(title)
    if not q or not t:
        return 0.0
    if len(q) >= 2 and len(t) >= 2 and (q in t or t in q):
        return 1.0
    return SequenceMatcher(None, q, t).ratio()


def passes_gate(query: str, title: str) -> bool:
    """★ 유사도 관문 — 이것을 통과해야만 고객에게 나간다(설계서 §4-1 필수 조항)."""
    return title_similarity(query, title) >= SIMILARITY_MIN


def _cache_path(name: str) -> Path:
    safe = re.sub(r"[^0-9A-Za-z가-힣]+", "_", name)[:80]
    return CACHE_DIR / (safe + ".json")


def _read_cache(name: str) -> dict | None:
    p = _cache_path(name)
    try:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        log.warning("[wiki] cache read failed: %s", type(e).__name__)
    return None


def _write_cache(name: str, payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as e:                                   # noqa: BLE001
        log.warning("[wiki] cache write failed: %s", type(e).__name__)


def _get(url: str, timeout: float) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _summary(name: str, timeout: float) -> tuple[str | None, str, str | None]:
    """표제어 직행 — (title, extract, url). 없으면 (None, '', None)."""
    try:
        d = _get(_SUMMARY_URL % urllib.parse.quote(name, safe=""), timeout)
    except Exception:                                        # noqa: BLE001
        return None, "", None
    if not d or d.get("type", "").endswith("not_found"):
        return None, "", None
    url = ((d.get("content_urls") or {}).get("desktop") or {}).get("page")
    return d.get("title"), (d.get("extract") or "").strip(), url


def _search(name: str, timeout: float) -> list[str]:
    """표제어를 모를 때의 보조 — 후보 제목 목록(최대 3)."""
    try:
        d = _get(_SEARCH_URL % urllib.parse.quote(name, safe=""), timeout)
    except Exception:                                        # noqa: BLE001
        return []
    return [h.get("title") for h in ((d or {}).get("query") or {}).get("search", [])
            if h.get("title")]


def fetch_game(name: str, *, timeout: float = TIMEOUT_SEC,
               use_cache: bool = True) -> WikiResult:
    """게임명 -> 위키 요약. **관문과 문턱을 둘 다 통과해야 ok=True 다.**

    2단 해석: ① summary 직행 ② 실패하면 search 로 표제어를 찾아 다시 summary.
    ②의 결과는 **반드시 유사도 관문**을 탄다 — 오매칭이 실제로 31건 중 10건이었다.

    실패해도 예외를 올리지 않는다 — `ok=False` + `reason` 으로 돌려준다. 상담을
    끊을 일이 아니고, 호출부는 「자료 없음」으로 답하면 된다(지어내지 않는다).
    """
    t0 = time.time()
    if use_cache:
        c = _read_cache(name)
        if c is not None:
            return WikiResult(ok=c.get("ok", False), title=c.get("title"),
                              extract=c.get("extract", ""), url=c.get("url"),
                              reason=c.get("reason", ""),
                              similarity=c.get("similarity"), from_cache=True,
                              elapsed_sec=round(time.time() - t0, 3))

    title, extract, url = _summary(name, timeout)
    sim = 1.0 if title else None
    if title and not passes_gate(name, title):
        # 직행이어도 위키가 넘겨준 표제어가 다를 수 있다(리다이렉트) — 관문을 태운다.
        sim = title_similarity(name, title)
        log.info("[wiki] direct title rejected by gate: sim=%.2f", sim)
        title, extract, url = None, "", None

    if not title:
        for cand in _search(name, timeout):
            if not passes_gate(name, cand):
                log.info("[wiki] search candidate rejected by gate: sim=%.2f",
                         title_similarity(name, cand))
                continue
            t2, e2, u2 = _summary(cand, timeout)
            if t2 and passes_gate(name, t2):
                title, extract, url = t2, e2, u2
                sim = title_similarity(name, t2)
                break

    elapsed = round(time.time() - t0, 3)
    if not title:
        res = WikiResult(ok=False, reason="not found or rejected by title gate",
                         elapsed_sec=elapsed)
    elif len(extract) < EXTRACT_MIN_CHARS:
        # ★ 「배틀그라운드 19자」 사고 — 근거가 얇으면 문장을 만들지 않는다.
        res = WikiResult(ok=False, title=title, extract=extract, url=url,
                         similarity=sim, elapsed_sec=elapsed,
                         reason="extract too short (%d < %d chars)" % (
                             len(extract), EXTRACT_MIN_CHARS))
    else:
        res = WikiResult(ok=True, title=title, extract=extract, url=url,
                         similarity=sim, elapsed_sec=elapsed)

    if use_cache:
        # ★ **실패는 캐시하지 않는다**(단, 80자 문턱 미달은 캐시한다).
        #   「못 찾았다」에는 두 가지가 섞여 있다: ① 정말 없는 표제어 ② 이번에 네트워크가
        #   느렸을 뿐. ②를 캐시하면 **한 번의 타임아웃이 영구적인 「자료 없음」이 된다.**
        #   반대로 「본문이 19자뿐」은 위키 쪽 사실이라 다시 물어도 같다 — 그건 캐시한다.
        cacheable = res.ok or bool(res.title)
        if cacheable:
            _write_cache(name, {"ok": res.ok, "title": res.title,
                                "extract": res.extract, "url": res.url,
                                "reason": res.reason, "similarity": res.similarity})
    return res
