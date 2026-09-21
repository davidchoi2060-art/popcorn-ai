# -*- coding: utf-8 -*-
"""팝콘톡 답변 경로 [B] — 「자유롭게 답하되, 우리 DB 로 필터링해 내보낸다」.

사장님 확정(2026-09-21):
  > "LLM이 답변을 충분히 자유롭게 하도록 해야해.. 그런 다음에 구체적으로 질문이
  >  좁혀지면, 우리쪽으로 유도를 해야지.. 그리고 먼저는 우리 DB를 읽고
  >  불충분하면, 직접 웹검색을 하던.. 대답을 해줘야지.."

설계서: `D:/Hermes-Workspace/talk_design_v2.md`. 이 모듈은 그 §1-0 의 [B] 경로다.

■ 고친 병 — 「답을 담을 칸 자체가 계약에 없었다」
  프롬프트가 `reply` 를 **되묻기/확인 전용 200자**로 못박고 있었다(talk.py §reply 규칙).
  그래서 고객이 세 번 물어도 세 번 다 되묻기만 돌아왔다(사장님이 직접 보신 증상):
      고객: 요즘 인기 많은 게임을 소개해줘
      봇  : "혹시 게임할 새 컴퓨터를 맞추려고...?"
  `reply` 는 **손대지 않는다.** 답변 칸(`answer`)을 **형제 필드로 새로 낸다** —
  `chat_flow` 를 TalkState 밖 형제로 둔 전례 그대로(좌표와 흐름을 섞지 않는다).

■ [A] 좌표 추출과 **가른다**
  근거(설계서 §6-1): 3사 날것 실측에서 시스템 프롬프트 없이 던지면 **셋 다 100%
  부품·가격을 지어냈다.** 「자유롭게 답하라」는 압력이 매우 강해서, 같은 호출에
  「추측하지 마라. 적힌 것만 옮긴다」를 함께 두면 두 압력이 한 출력에서 싸운다 —
  **지는 쪽이 좌표 추출이면 티가 안 난다**(견적은 계속 나오고, 틀린 용도로 나온다).
  그래서 **[A] 의 프롬프트를 한 글자도 건드리지 않는다**(제약 추출 정확도 유지).

■ 근거 순서 — DB 먼저, 불충분하면 웹
  ① DB 조회(SQL 이 한다. LLM 이 아니다) ② 불충분 판정(필드 유무로 기계 판정)
  ③ 위키 조회(유사도 관문 + 80자 문턱) ④ 자유 답변 ⑤ **필터** ⑥ 유도 한 줄
  둘 다 없으면 **「자료 없음」이라 말한다. 지어내지 않는다.**

■ ★ `game_customer_copy` 는 **검수 전에는 내보내지 않는다**
  86/86 완비지만 `reviewed_by` 가 **0/86** 이다. 사장님 확정: "전수 검수 후에 낸다".
  그래서 `reviewed_by IS NOT NULL` 인 행만 읽는다 — 지금은 0건이라 아무것도 안 나간다.
  검수가 끝나면 **코드 수정 없이** 저절로 나가기 시작한다.

■ ★ `games.description` 을 고객에게 읽어주지 않는다
  86/86 채워져 있지만 «게임 소개»가 아니라 **사양 부하 메모**다(평균 70자 ·
  발로란트·오버워치2·배그가 거의 같은 문장). 고객 답변 근거로 싣지 않는다.

■ 로그는 ASCII 기호만(서버 stdout cp949) · `.env` 값을 찍지 않는다.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sqlalchemy import bindparam, text

from . import llm
from . import talk_filter as TF
from . import talk_schema as TS
from . import wiki_fetch as WF

log = logging.getLogger(__name__)

# ── 상한 (설계서 §1-1 · §6-2) ───────────────────────────────────────────────
ANSWER_MAX_LEN = 600        # `reply` 200자와 **독립**이다. 서로를 죽이지 않는다
ANSWER_MAX_TOKENS = 900     # 실측 out 95~319 -> 900
ANSWER_TIMEOUT_SEC = 8      # 답변 LLM 상한(설계서 §4-2)
PATH_B_TIMEOUT_SEC = 10     # [B] 경로 전체 상한
# 자유 답변 모델 — 설계서 §5-3 제안. 좌표 추출(task.s1_parse)은 haiku 그대로 둔다.
#   gpt-5.6-luna: 3.27초 · 입력 $0.2 / 출력 $1.2 per 1M · **날짜·출처를 스스로 인용**
#   같은 근거를 준 haiku 는 순위 수치를 빠뜨렸다. 건당 비용 +8%.
ANSWER_TASK_KEY = "task.talk_answer"

# ── 고정 문구 — **서버가 정한다. 모델에게 맡기지 않는다** ──────────────────────
# 근거: 실측에서 OpenAI 는 묻지도 않았는데 먼저 견적을 제안했다("100/150/200만").
# 유도 문구를 모델이 쓰면 그 안에 숫자가 들어간다(`REPLY_ROLE_GUIDE` 전례).
NOTICE_WEB = "저희 자료에 없는 내용이라 잠깐 찾아볼게요. 조금만 기다려 주세요."
SOURCE_OWN = "저희가 정리해 둔 자료예요."
SOURCE_WEB = "저희 자료엔 없어서 방금 찾아봤어요 - {origin}, {as_of} 기준이에요."
# 유도 한 줄 — narrow 에서 **1회만**. wide 에서는 쓰지 않는다(이른 유도가 대화를 끊는다).
NUDGE_NARROW = "혹시 이 중에 마음이 가는 게임이 있으시면, 그 게임 기준으로 PC를 맞춰 보여드릴게요."
NO_DATA = "이 게임은 저희 자료로 아직 정리하지 못했어요. 확인해서 알려드릴게요."


# ── 1. DB 조회 계층 ────────────────────────────────────────────────────────
@dataclass
class GameFacts:
    """한 게임에 대해 **우리가 실제로 아는 것**. 없는 것은 None 이다 — 지어내지 않는다."""
    name: str
    genre: str | None = None
    vendor: str | None = None
    release_date: str | None = None
    grade: str | None = None
    # 인기도 — `game_popularity_snapshots` 104행(PC방 29 · Steam 동접 68) = 83종.
    # `games.popularity_rank` 는 0/86 죽은 컬럼이라 읽지 않는다.
    pcbang_rank: int | None = None
    pcbang_share: float | None = None
    steam_ccu: int | None = None
    snapshot_date: str | None = None
    snapshot_source: str | None = None
    # 검수를 통과한 copy 만. `reviewed_by IS NULL` 이면 비어 있다(사장님 확정).
    copy_spec: str | None = None
    copy_why: str | None = None

    def popularity_line(self) -> str | None:
        """인기도 한 줄 — **날짜·모수를 반드시 병기한다**(없으면 None)."""
        if self.pcbang_rank and self.snapshot_date:
            s = "%s 기준 PC방 점유율 %d위" % (self.snapshot_date, self.pcbang_rank)
            if self.pcbang_share is not None:
                s += " (%.2f%%)" % float(self.pcbang_share)
            return s
        if self.steam_ccu and self.snapshot_date:
            return "%s 기준 Steam 동시접속 %s명" % (
                self.snapshot_date, format(int(self.steam_ccu), ","))
        return None


def load_game_facts(conn, names: list[str], vocab: "TS.Vocab") -> list[GameFacts]:
    """고객이 말한 게임명 -> 우리 DB 사실. 목록 밖 이름은 **조용히 버리지 않고** 빠진다.

    이름 대조는 `talk_schema.match_game()` 하나가 한다 — 여기서 다시 적지 않는다
    (줄임말·표기 흔들림을 그 함수가 이미 처리한다: \"오버워치\" -> \"오버워치2\").
    """
    canon: list[str] = []
    for n in names:
        m = TS.match_game(n, vocab)
        if m and m not in canon:
            canon.append(m)
    if not canon:
        return []
    rows = conn.execute(text(
        "SELECT g.game_id, g.name, g.genre, g.vendor, g.release_date,"
        "       a.grade,"
        "       c.spec_summary_ko, c.why_this_pc, c.reviewed_by"
        "  FROM games g"
        "  LEFT JOIN game_grade_assignments a ON a.game_id = g.game_id"
        "  LEFT JOIN game_customer_copy c ON c.game_id = g.game_id"
        " WHERE g.name IN :names"
    ).bindparams(bindparam("names", expanding=True)), {"names": canon}).mappings().all()
    out: list[GameFacts] = []
    for r in rows:
        f = GameFacts(name=r["name"], genre=r["genre"], vendor=r["vendor"],
                      release_date=str(r["release_date"]) if r["release_date"] else None,
                      grade=r["grade"])
        # ★ 검수 전에는 내보내지 않는다(reviewed_by 0/86 — 사장님 확정).
        if r["reviewed_by"]:
            f.copy_spec = r["spec_summary_ko"]
            f.copy_why = r["why_this_pc"]
        pop = conn.execute(text(
            "SELECT snapshot_date, source, pcbang_rank, pcbang_share_pct, steam_ccu"
            "  FROM game_popularity_snapshots WHERE game_id = :gid"
            " ORDER BY snapshot_date DESC LIMIT 1"), {"gid": r["game_id"]}).mappings().first()
        if pop:
            f.pcbang_rank = pop["pcbang_rank"]
            f.pcbang_share = float(pop["pcbang_share_pct"]) if pop["pcbang_share_pct"] is not None else None
            f.steam_ccu = pop["steam_ccu"]
            f.snapshot_date = str(pop["snapshot_date"])
            f.snapshot_source = pop["source"]
        out.append(f)
    return out


def popular_games(conn, genres: list[str] | None = None,
                  limit: int = 6) -> list[GameFacts]:
    """인기 게임 — `game_popularity_snapshots` 최신 스냅샷 기준. **날짜·모수 병기 필수.**

    `games.popularity_rank` 는 0/86 이라 쓰지 않는다(죽은 컬럼). 장르가 주어지면
    그 장르들로 좁힌다 — 장르 값의 정본은 `games.genre` 다(코드에 박지 않는다).
    """
    sql = (
        "SELECT g.name, g.genre, g.vendor, a.grade,"
        "       p.snapshot_date, p.source, p.pcbang_rank, p.pcbang_share_pct, p.steam_ccu"
        "  FROM games g"
        "  JOIN LATERAL (SELECT * FROM game_popularity_snapshots s"
        "                 WHERE s.game_id = g.game_id"
        "                 ORDER BY s.snapshot_date DESC LIMIT 1) p ON TRUE"
        "  LEFT JOIN game_grade_assignments a ON a.game_id = g.game_id"
    )
    params: dict = {"lim": limit}
    stmt = None
    if genres:
        sql += " WHERE g.genre IN :genres"
        params["genres"] = list(genres)
        stmt = text(sql + " ORDER BY p.pcbang_rank NULLS LAST,"
                          " p.steam_ccu DESC NULLS LAST LIMIT :lim").bindparams(
            bindparam("genres", expanding=True))
    else:
        stmt = text(sql + " ORDER BY p.pcbang_rank NULLS LAST,"
                          " p.steam_ccu DESC NULLS LAST LIMIT :lim")
    rows = conn.execute(stmt, params).mappings().all()
    out = []
    for r in rows:
        out.append(GameFacts(
            name=r["name"], genre=r["genre"], vendor=r["vendor"], grade=r["grade"],
            pcbang_rank=r["pcbang_rank"],
            pcbang_share=float(r["pcbang_share_pct"]) if r["pcbang_share_pct"] is not None else None,
            steam_ccu=r["steam_ccu"], snapshot_date=str(r["snapshot_date"]),
            snapshot_source=r["source"]))
    return out


# ── 2. 어휘 매칭 — [B] 는 [A] 의 state 를 기다리지 않는다 ─────────────────────
# 근거(설계서 §6-1 단서): [B] 가 [A] 의 `state` 를 쓰면 **병렬이 깨진다**(순차 12초).
# 그래서 [B] 는 자체 어휘 매칭으로 판정하고, [A] 의 state 는 **응답 조립 시점에
# 교차 검증으로만** 쓴다. 어휘는 `load_vocab` 이 준 것을 그대로 쓴다 — 새로 만들지 않는다.
_GAME_WORDS = ("게임", "겜", "플레이", "유저", "장르", "타이틀")


def match_genres(sentence: str, vocab: "TS.Vocab") -> list[str]:
    """문장에서 장르를 찾는다 -> `games.genre` 실값 목록.

    어휘의 정본은 **DB 둘**이다: `games.genre`(장르 실값)와 `talk_genre_aliases`
    (고객이 쓰는 말 -> 그 실값, 0111). **코드에 별칭을 박지 않는다.**

    왜 별칭표가 필요한가 — 사장님이 보신 증상의 한 조각이다: 고객은 「슈팅게임」이라
    말했는데 우리 장르 값은 `FPS`·`협동슈팅`·`익스트랙션FPS`·`액션TPS` 라 글자가 한
    곳도 안 맞았다. 그래서 장르로 인식되지 않았고, 좁혀짐 판정이 `wide` 에 머물러
    그 장르의 우리 게임을 꺼내 오지 못했다.

    ① 장르 실값이 문장에 그대로 있으면 그것(\"MMORPG 추천해줘\").
    ② 별칭이 문장에 있으면 그 별칭이 가리키는 장르 전부(\"슈팅게임\" -> FPS 외 4종).
    운영자가 표에 한 줄 넣으면 **다음 요청부터** 반영된다.
    """
    s = (sentence or "").lower()
    if not s:
        return []
    hits: list[str] = []
    for g in vocab.genres:
        if g and g.lower() in s and g not in hits:
            hits.append(g)
    # 별칭은 긴 것부터 본다 — \"슈팅게임\" 이 \"슈팅\" 보다 먼저 걸려야 한다.
    for alias in sorted(vocab.genre_aliases, key=len, reverse=True):
        if alias in s:
            for g in vocab.genre_aliases[alias]:
                if g not in hits:
                    hits.append(g)
    return hits


def is_game_related(sentence: str, vocab: "TS.Vocab") -> bool:
    """이번 문장이 게임 이야기인가 — `advance_smalltalk(game_related=)` 이 쓴다.

    **새 판정기를 만들지 않는다** — 게임명(`vocab.all_game_names`)·장르어
    (`vocab.genres`)·게임 낱말 셋 중 하나라도 걸리면 참이다.
    """
    if not sentence:
        return False
    if any(w in sentence for w in _GAME_WORDS):
        return True
    if match_genres(sentence, vocab):
        return True
    s = sentence.strip()
    return any(TS.match_game(tok, vocab) for tok in re.split(r"[\s,·]+", s) if len(tok) >= 2)


def extract_game_names(sentence: str, vocab: "TS.Vocab") -> list[str]:
    """문장에서 우리 목록에 있는 게임명을 찾는다(대조는 `match_game` 이 한다)."""
    out: list[str] = []
    for name in vocab.all_game_names:
        if name and name in sentence and name not in out:
            out.append(name)
    if out:
        return out
    for tok in re.split(r"[\s,·?!.]+", sentence.strip()):
        if len(tok) < 2:
            continue
        m = TS.match_game(tok, vocab)
        if m and m not in out:
            out.append(m)
    return out


# ── 3. 근거 수집 — DB 먼저, 불충분하면 웹 ──────────────────────────────────
@dataclass
class Evidence:
    db_lines: list[str] = field(default_factory=list)
    web_lines: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    used_web: bool = False
    facts: list[GameFacts] = field(default_factory=list)

    def has_any(self) -> bool:
        return bool(self.db_lines or self.web_lines)


def _fact_lines(f: GameFacts) -> list[str]:
    """한 게임의 DB 사실 -> 근거 줄. **없는 것은 적지 않는다.**"""
    bits = []
    if f.genre:
        bits.append("장르 %s" % f.genre)
    if f.vendor:
        bits.append("제작 %s" % f.vendor)
    if f.release_date:
        bits.append("출시 %s" % f.release_date)
    lines = ["%s: %s" % (f.name, " · ".join(bits))] if bits else []
    pop = f.popularity_line()
    if pop:
        lines.append("%s 인기도: %s (출처 %s)" % (f.name, pop, f.snapshot_source or "-"))
    # 검수를 통과한 copy 만 실린다(reviewed_by). 지금은 0/86 이라 안 실린다.
    if f.copy_spec:
        lines.append("%s 안내: %s" % (f.name, f.copy_spec))
    if f.copy_why:
        lines.append("%s 상세: %s" % (f.name, f.copy_why))
    return lines


def collect_evidence(conn, sentence: str, vocab: "TS.Vocab", *,
                     allow_web: bool = True) -> Evidence:
    """★ 근거 순서 — DB 먼저, 불충분하면 웹검색(설계서 §1-3).

    「불충분」은 **필드 유무로 기계 판정**한다 — 「짧으면 불충분」은 기준으로 쓰지
    않는다(길이는 품질의 대리값이 아니고, 글자 수 문턱은 웹검색을 늘리라는 압력이 된다).
    """
    ev = Evidence()
    names = extract_game_names(sentence, vocab)
    genres = match_genres(sentence, vocab)

    if names:
        ev.facts = load_game_facts(conn, names, vocab)
    elif genres:
        # 게임명 없이 장르만 좁혀졌다 — 그 장르의 우리 게임을 인기 순으로 낸다.
        # 별칭 하나가 여러 장르를 가리키므로(\"슈팅게임\" -> FPS 외 4종) 한 번에 조회한다.
        ev.facts = popular_games(conn, genres=genres, limit=6)
    else:
        ev.facts = popular_games(conn, limit=6)

    seen: set = set()
    uniq: list[GameFacts] = []
    for f in ev.facts:
        if f.name not in seen:
            seen.add(f.name)
            uniq.append(f)
    ev.facts = uniq[:6]

    for f in ev.facts:
        ev.db_lines.extend(_fact_lines(f))
    if ev.db_lines:
        ev.sources.append({"kind": "own", "label": SOURCE_OWN})

    # U2 — 「무슨 게임인가」는 DB 에 컬럼이 0/86 이다. 게임명이 특정됐고 아직 소개가
    # 없으면(= 검수된 copy 가 없으면) 웹으로 간다. 이것이 기본 경로가 된다.
    need_web = allow_web and bool(names) and not any(f.copy_why for f in ev.facts)
    if need_web:
        # 한 턴에 **한 게임만** 찾는다. 위키 왕복이 게임당 중앙 1.82초 · p90 3.09초라
        # 두 개를 타면 [B] 경로 상한(10초)을 혼자 다 먹는다(실측: 아이온2 처럼 표제어를
        # 못 찾는 게임은 search 까지 돌아 더 걸린다). 고객이 이름을 댄 첫 게임이면 족하다.
        for f in ev.facts[:1]:
            r = WF.fetch_game(f.name)
            if not r.ok:
                # ★ 근거가 얇으면 문장을 만들지 않는다(80자 문턱). 삼키지 않고 로그.
                log.info("[talk-answer] wiki not used for a game: %s", r.reason)
                continue
            ev.used_web = True
            ev.web_lines.append("%s: %s" % (f.name, r.extract[:600]))
            ev.sources.append({
                "kind": "web", "url": r.url,
                "label": SOURCE_WEB.format(origin="위키백과", as_of="방금"),
            })
    return ev


# ── 4. 자유 답변 프롬프트 — **격자 어휘를 싣지 않는다** ───────────────────────
# 근거(설계서 §6-1-2): 답변 호출 실측 프롬프트가 170~270토큰이다. 좌표 추출은 8,260토큰.
# 답변을 격자 프롬프트에 얹으면 토큰이 30배 비싸진다 — 가르는 쪽이 오히려 싸다.
def build_answer_prompt(sentence: str, ev: Evidence, narrowing: str,
                        history: list | None = None) -> str:
    hist = ["%s: %s" % ("고객" if r == "user" else "상담원", t)
            for r, t in (history or [])][-4:]
    lines = [
        "당신은 PC 견적 가게의 상담원이다. 고객의 «게임 질문»에 **직접 답한다**.",
        "되묻기만 하고 답을 미루지 않는다 - 고객은 이미 물었다.",
        "",
        "[말투] 존댓말 상담 말투. 반말·구어체 금지. 내부 용어(원장·격자·좌표·등급·state) 금지.",
        "[길이] %d자 이내. 문단을 나눠도 좋다." % ANSWER_MAX_LEN,
        "",
        "[절대 금지] 아래는 다른 시스템이 답한다. 한 글자도 말하지 않는다:",
        "- 부품 이름·칩셋(RTX/GTX/라이젠/i5 등)과 사양 수치(GB·Hz·fps).",
        "- 가격·예산 금액. \"60만원이면 충분\" 같은 말.",
        "- 그 게임이 사양을 얼마나 먹는지(고사양/저사양/중급형) 단정.",
        "- 재고·배송·할인.",
        "",
        "[근거] **아래 적힌 것만 쓴다.** 적히지 않은 수치·날짜·순위를 지어내지 않는다.",
        "근거에 없는 내용은 \"확인해서 알려드릴게요\" 로 넘긴다.",
        "수치를 말할 때는 근거에 적힌 **날짜와 출처를 함께** 말한다.",
        "",
        "[저희 자료]",
    ]
    lines.extend(ev.db_lines or ["(없음)"])
    lines.append("")
    lines.append("[방금 찾아본 것 - 위키백과]")
    lines.extend(ev.web_lines or ["(없음)"])
    lines.append("")
    # 유도는 **서버가 붙인다**. 모델에게 시키지 않는다(그 안에 숫자가 들어간다).
    if narrowing == TS.NARROWING_WIDE:
        lines.append("[이번 답변] 고객이 아직 둘러보는 중이다. **게임 이야기만 한다.**"
                     " PC·견적 이야기를 꺼내지 않는다. 끝에 열린 질문 한 줄만 붙인다.")
    elif narrowing == TS.NARROWING_NARROW:
        lines.append("[이번 답변] 장르나 게임이 좁혀졌다. 그 게임들을 근거대로 설명한다."
                     " **PC 이야기는 붙이지 않는다** - 서버가 한 줄 덧붙인다.")
    else:
        lines.append("[이번 답변] 고객이 게임과 조건을 말했다. 게임 설명을 짧게 하고 마무리한다.")
    lines.append("")
    if hist:
        lines.append("[대화 이력 - 오래된 것부터]")
        lines.extend(hist)
        lines.append("")
    lines.append("[고객 문장]")
    lines.append(sentence)
    return "\n".join(lines)


# ── 5. [B] 경로 본체 ──────────────────────────────────────────────────────
@dataclass
class AnswerResult:
    answer: str = ""
    sources: list[dict] = field(default_factory=list)
    narrowing: str = TS.NARROWING_WIDE
    notice: str | None = None                 # 「조금 걸린다」 안내(웹검색 턴만)
    game_names: list[str] = field(default_factory=list)
    filter_report: dict = field(default_factory=dict)
    used_web: bool = False
    elapsed_sec: float = 0.0
    provider: str | None = None
    model: str | None = None
    cost_usd: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None


def _grade_of(ev: Evidence) -> str | None:
    """대조에 쓸 게임 부하 등급 — 여럿이면 첫 확정 등급. 없으면 None(전체 최저를 쓴다)."""
    for f in ev.facts:
        if f.grade:
            return f.grade
    return None


def answer_path(conn_factory, sentence: str, vocab: "TS.Vocab", *,
                prev_state: "TS.TalkState | None" = None,
                history: list | None = None,
                allow_web: bool = True,
                timeout_sec: float = PATH_B_TIMEOUT_SEC) -> AnswerResult:
    """★ [B] 경로 — 근거 수집 -> 자유 답변 -> **필터** -> 유도.

    `conn_factory` 는 `engine.connect` 같은 «연결을 여는 것»을 받는다. [A] 와 병렬로
    도는 자리라 호출부의 연결을 빌려 쓰지 않는다(연결 하나를 두 스레드가 쓰지 않게).

    실패해도 **예외를 올리지 않는다** — `error` 에 사유를 담아 돌려준다. 답변 경로가
    죽어도 좌표 추출([A])은 살아야 하고, 상담이 끊기면 안 된다.
    """
    t0 = time.time()
    res = AnswerResult()
    try:
        # ★ [B] 는 **게임 이야기일 때만** 답한다.
        #   여기는 PC 견적 창구다. \"오늘 점심 뭐 먹을까\"에 게임 순위를 읊으면 그것이야말로
        #   사장님이 막으라 하신 «엉뚱한 답»이다. 잡담은 [A] 의 `reply`([잡담] 문단)가
        #   이미 받아준다 -- 그 경로를 [B] 가 덮어쓰지 않는다.
        #   판정은 `is_game_related` 하나가 한다(잡담 카운터가 쓰는 것과 **같은 함수**) --
        #   두 벌로 두면 「답은 하는데 카운터는 오르는」 어긋남이 생긴다.
        if not is_game_related(sentence, vocab):
            res.elapsed_sec = round(time.time() - t0, 3)
            return res
        with conn_factory() as conn:
            genres = match_genres(sentence, vocab)
            names_now = extract_game_names(sentence, vocab)
            # narrowing 은 [A] 를 기다리지 않는다 — 이전 state(화면이 되돌려 보낸 것) +
            # 이번 문장의 어휘 매칭으로 판정한다(병렬 유지).
            merged = prev_state
            if names_now:
                g = TS.GameState(names=names_now)
                if merged is None:
                    merged = TS.TalkState(game=g)
                else:
                    merged = merged.model_copy(update={
                        "game": TS.GameState(
                            names=list(dict.fromkeys(
                                (merged.game.names if merged.game else []) + names_now)),
                            grade=merged.game.grade if merged.game else None,
                            grade_src=merged.game.grade_src if merged.game else None,
                            resolution=merged.game.resolution if merged.game else None)})
            res.narrowing = TS.narrowing_level(merged, bool(genres))
            ev = collect_evidence(conn, sentence, vocab, allow_web=allow_web)
            floors = TF.price_floors(conn)
        res.used_web = ev.used_web
        res.sources = ev.sources
        res.game_names = [f.name for f in ev.facts]
        if ev.used_web:
            res.notice = NOTICE_WEB
        if not ev.has_any():
            # 둘 다 없다 — **지어내지 않는다.** 「자료 없음」으로 둔다.
            res.answer = NO_DATA
            res.elapsed_sec = round(time.time() - t0, 3)
            return res

        prompt = build_answer_prompt(sentence, ev, res.narrowing, history)
        out = llm.call(prompt, task_key=ANSWER_TASK_KEY, customer_facing=True,
                       max_output_tokens=ANSWER_MAX_TOKENS,
                       timeout_sec=int(min(ANSWER_TIMEOUT_SEC, timeout_sec)))
        res.provider, res.model = out.provider, out.model
        res.cost_usd, res.tokens_in, res.tokens_out = out.cost_usd, out.tokens_in, out.tokens_out
        raw = (out.text or "").strip()

        # ★ 필터 — LLM 이 자유롭게 쓴 것을 우리 DB 기준으로 거른다.
        fr = TF.apply_filter(raw, floors, _grade_of(ev))
        body = fr.text[:ANSWER_MAX_LEN]
        res.filter_report = {
            "kept": fr.kept, "replaced": fr.replaced, "dropped": fr.dropped,
            "gate_hit": fr.gate_hit,
        }
        # 유도 한 줄 — narrow 에서만 **1회**. 서버 상수다(모델이 쓰면 숫자가 들어간다).
        if res.narrowing == TS.NARROWING_NARROW:
            body = (body + " " + NUDGE_NARROW).strip()
        res.answer = body
    except llm.LLMBlockedError as e:
        res.error = "llm blocked: %s/%s" % (e.kind, e.provider)
    except llm.LLMNotConfiguredError:
        res.error = "llm not configured"
    except (llm.LLMAllProvidersFailedError, llm.LLMProviderError) as e:
        res.error = "llm failed: %s" % type(e).__name__
    except Exception as e:                                   # noqa: BLE001
        # ⚠ 예외 문자열에 DSN 이 새어 나온 사고가 있었다 — **타입 이름만** 남긴다.
        res.error = "answer path error: %s" % type(e).__name__
        log.warning("[talk-answer] path failed: %s", type(e).__name__)
    res.elapsed_sec = round(time.time() - t0, 3)
    return res


def run_parallel(fn_a, fn_b, timeout_sec: float = PATH_B_TIMEOUT_SEC):
    """[A] 좌표 추출 ∥ [B] 답변 — **병렬이 필수다**(설계서 §4-1).

    순차면 12초로 `LLM_TIMEOUT_SEC = 15` 에 육박한다. 병렬이면 최악 7초.
    [B] 가 늦거나 죽어도 [A] 는 그대로 나간다 — 답변이 없는 것이 상담이 끊기는 것보다 낫다.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(fn_a)
        fb = pool.submit(fn_b)
        a = fa.result()                       # [A] 실패는 그대로 올린다(502 규약)
        try:
            b = fb.result(timeout=timeout_sec)
        except Exception as e:                # noqa: BLE001
            log.warning("[talk-answer] path B timed out or failed: %s", type(e).__name__)
            b = AnswerResult(error="path B unavailable: %s" % type(e).__name__)
    return a, b
