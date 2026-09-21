# -*- coding: utf-8 -*-
"""팝콘톡 답변 필터 — LLM 이 자유롭게 쓴 문장을 **우리 DB 기준으로 걸러 내보낸다**.

사장님 확정(2026-09-21):
  > "우리와 관련된 건 LLM이 자유롭게 답변한 내용을 우리가 필터링(DB기준) 해야해"

설계서: `D:/Hermes-Workspace/talk_design_v2.md` §2·§3. 이 파일은 그 §2 의 3층 후처리를
구현한다. 경계는 **ⓐ-2(중간 — 게임 부하 등급·사양 어휘까지 포함)**, 걸린 문장 처리는
**ⓑ-1(우리 값으로 치환), 치환값이 없으면 ⓑ-2(삭제)** — 둘 다 사장님 확정이다.

■ 왜 2패스 LLM 이 아니라 후처리 규칙인가 (설계서 §2-1, 근거 4)
  ① **결정론이다.** 같은 입력에 같은 결과가 나오고 회귀로 고정할 수 있다. 2패스 LLM 은
     검사 자체가 확률적이라 «필터가 통과시킨 거짓»의 책임 소재가 사라진다.
  ② 비용이 0 에 가깝다(하루 캡 $2 가 이미 빠듯하다).
  ③ 지연이 0 에 가깝다(2패스는 최소 +1.5~3초).
  ④ **실측 성능이 충분했다** — 설계자가 3사 응답 667문장에 실제로 돌렸다:
     보수 설정 적발 61문장(9.1%) · 재현율 13/14 · 오탐 0/10.
     1턴(순수 게임 소개)은 3사 모두 0건, 3턴(장르 좁혀짐)에 집중 — 옳은 자리를 때린다.

■ ★ 대조 기준을 **코드에 박지 않는다**
  게임 칸 최저 성립가(L 645,000 / E·A 908,800 — 2026-09-21 실측)는 **조회로** 얻는다
  (`price_floors()`). 지금 다른 담당이 예산 구간·용도 체계를 재설계 중이라, 숫자를
  박으면 그 작업이 끝나는 순간 필터가 거짓을 말한다. 조회로 두면 **저절로 따라간다.**
  용도 이름도 박지 않는다 — `is_game_usage()`(talk_schema)가 판정한다.

■ 탐지(규칙)와 대조(DB)를 반드시 나눈다
  탐지된 문장 중 «실제로 값을 주장하는 것»만 대조를 타고 나머지는 통과한다. 이것이
  「이 중에서 고르시면 딱 맞는 PC 사양을 맞추는 건 쉬워집니다」 같은 **유도 문장을
  살리는 층**이다(설계서 §2-3 의 「애매한 문장」).

■ 로그는 ASCII 기호만 (서버 stdout 이 cp949)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import text

from . import talk_schema as TS

log = logging.getLogger(__name__)

# ── 1층. 문장 분해 ──────────────────────────────────────────────────────────
# 표·목록 줄도 한 단위로 센다(설계서 §2-1) — 줄바꿈을 문장 경계로 함께 본다.
# 마침표 뒤 공백/줄끝, 물음표·느낌표, 그리고 줄바꿈이 경계다.
_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")


def split_sentences(t: str) -> list[str]:
    """답변 원문 -> 문장 목록. 빈 조각은 버린다. **원문 글자는 바꾸지 않는다.**"""
    if not t:
        return []
    return [s.strip() for s in _SENT_SPLIT.split(t) if s and s.strip()]


# ── 2층. 탐지 — 정규식 3종 + 어휘 사전 1종 (설계서 §2-2) ──────────────────────
# 실측된 탐지기 그대로다(`_bench_filter.py` — 3사 667문장 검증).
KIND_PRICE = "price"      # 가격 주장
KIND_PART = "part"        # 부품명·칩셋
KIND_SPEC = "spec"        # 사양 수치(GB/Hz/fps/TB)
KIND_LEXICON = "lexicon"  # 부품·사양·등급 어휘(완곡 표현까지 잡는 두 번째 그물)
KIND_STOCK = "stock"      # 재고·배송 — **무조건 삭제**

_RE_PRICE = re.compile(r"\d{1,4}\s*만\s*원|\d{1,3}(?:,\d{3})+\s*원|\d+\s*만원")
_RE_PART = re.compile(
    r"(?:RTX|GTX|RX|GT)\s?\d{3,4}\s?(?:Ti|TI|SUPER|XT)?|i[3579][-\s]?\d{4,5}"
    r"|라이젠\s?\d|Ryzen\s?\d", re.IGNORECASE)
_RE_SPEC = re.compile(r"\d+\s*GB|\d+\s*Hz|\d+\s*fps|\d+\s*TB", re.IGNORECASE)

# 어휘 사전 — 설계서 §2-2 표 그대로. 이것이 「느슨」이 놓친 6문장을 잡는다
# (\"너무 고사양 PC까지는 필요하지 않음\" · \"이 게임은 요구사양이 매우 낮습니다\" 등).
# ⚠ 이것은 **탐지** 사전이지 대조 원천이 아니다. 대조는 전부 DB 조회다.
_LEXICON = (
    "그래픽카드", "지포스", "라데온", "CPU", "GPU", "램", "SSD", "파워", "메인보드",
    "본체", "견적", "사양", "고사양", "저사양", "중사양", "중급형", "보급형", "주사율",
    "모니터", "예산", "가격", "원대", "호환",
)
# 재고·배송 — 상담 경로가 답할 일이 아니다. 대조 없이 **무조건 삭제**(설계서 §2-4).
_LEXICON_STOCK = ("재고", "배송", "할인", "품절", "입고")


def detect(sentence: str) -> list[str]:
    """문장 -> 걸린 종류 목록(빈 목록이면 무해). **순수함수다** — DB 를 보지 않는다."""
    kinds: list[str] = []
    if _RE_PRICE.search(sentence):
        kinds.append(KIND_PRICE)
    if _RE_PART.search(sentence):
        kinds.append(KIND_PART)
    if _RE_SPEC.search(sentence):
        kinds.append(KIND_SPEC)
    if any(w in sentence for w in _LEXICON_STOCK):
        kinds.append(KIND_STOCK)
    if any(w in sentence for w in _LEXICON):
        kinds.append(KIND_LEXICON)
    return kinds


# ── 3층. 대조 — 원천은 전부 DB ──────────────────────────────────────────────
@dataclass
class PriceFloors:
    """게임 칸의 «성립 총액» 하한 — `grid_quotes ⨝ grid_cells` 실조회 결과.

    **코드에 박힌 숫자가 하나도 없다.** 다른 담당의 예산 재설계가 끝나면 이 값이
    저절로 따라간다(설계서 §2-4 의 ★).
    """
    by_grade: dict[str, int] = field(default_factory=dict)   # grade -> 최저 성립 총액
    overall_min: int | None = None                           # 게임 칸 전체 최저

    def floor_for(self, grade: str | None) -> int | None:
        """등급 -> 그 등급의 최저 성립가. 등급을 모르면 게임 칸 전체 최저."""
        if grade and grade in self.by_grade:
            return self.by_grade[grade]
        return self.overall_min


def price_floors(conn) -> PriceFloors:
    """게임 계열 칸의 현재 성립 견적에서 등급별 최저 총액을 읽는다.

    조건: `is_current` 이고 `verdict='within'`(성립한 것만) · 용도가 게임 계열.
    용도 이름을 리터럴로 쓰지 않는다 — `talk_schema.is_game_usage()` 가 판정한다
    (다른 담당이 용도 체계를 재설계 중이라 이름이 바뀔 수 있다).
    """
    rows = conn.execute(text(
        "SELECT c.usage AS usage, c.game_grade AS grade, MIN(q.total) AS lo"
        "  FROM grid_quotes q JOIN grid_cells c ON c.cell_id = q.cell_id"
        " WHERE q.is_current AND q.verdict = 'within' AND q.total IS NOT NULL"
        " GROUP BY 1, 2")).mappings().all()
    by_grade: dict[str, int] = {}
    overall: int | None = None
    for r in rows:
        if not TS.is_game_usage(r["usage"]):
            continue
        lo = int(r["lo"])
        overall = lo if overall is None else min(overall, lo)
        g = r["grade"]
        if g:
            by_grade[g] = min(by_grade.get(g, lo), lo)
    return PriceFloors(by_grade=by_grade, overall_min=overall)


def _fmt_won(n: int) -> str:
    return format(int(n), ",") + "원"


# ── 치환 문구 — **서버가 고정한다. 모델에게 맡기지 않는다** ────────────────────
# 근거: 실측에서 OpenAI 는 묻지도 않았는데 먼저 견적을 제안했다(\"100/150/200만\").
# 문구를 모델이 쓰면 그 안에 숫자가 들어간다. `REPLY_ROLE_GUIDE` 의 전례 그대로.
#
# ⚠ 고객 응답이므로 **상담 말투**다(관리자 화면 어휘 규약을 그대로 씌우지 않는다).
#   다만 구어·반말은 쓰지 않는다.
SUB_PRICE = "저희가 지금 구성할 수 있는 게임용 PC는 {floor}부터 시작해요."
SUB_PRICE_NO_FLOOR = "구체적인 금액은 견적으로 정확히 보여드릴게요."
SUB_PART = "어떤 부품을 넣을지는 게임과 예산을 정하신 뒤에 견적으로 보여드릴게요."
SUB_GRADE = "이 게임에 어떤 사양이 필요한지는 저희 기준으로 견적에 담아 보여드릴게요."
# 재고·배송은 치환하지 않는다 — 삭제다(빈 문자열).
SUB_DROP = ""


@dataclass
class FilterResult:
    text: str                                  # 고객에게 내보낼 최종 문장
    kept: int = 0                              # 손대지 않고 통과한 문장 수
    replaced: list[dict] = field(default_factory=list)   # [{before, after, kinds, source}]
    dropped: list[dict] = field(default_factory=list)    # [{before, kinds, reason}]
    gate_hit: bool = False                     # 문장 끝 게이트가 걸렸나(§2-5)


def _claims_value(sentence: str, kinds: list[str]) -> bool:
    """걸린 문장이 «실제로 값을 주장하는가» — 대조를 태울지 판정한다.

    설계서 §2-4: 탐지는 규칙, 대조는 DB. 두 단계를 나누는 이유가 여기다.
    숫자(가격·사양)나 부품명이 있으면 값 주장이다. 어휘만 걸린 문장은
    「고사양이 필요해요」류의 **등급 단정**일 때만 값 주장으로 본다 — 그 밖의
    유도 문장(\"골라주시면 맞추기 쉬워집니다\")은 무해 통과시킨다.
    """
    if KIND_PRICE in kinds or KIND_PART in kinds or KIND_SPEC in kinds:
        return True
    if KIND_STOCK in kinds:
        return True
    # 부품을 **이름으로 거명**하면 값 주장이다 — \"램, 그래픽카드, CPU 밸런스 중요\"처럼
    # 숫자 없이 부품만 늘어놓는 문장이 규칙의 실측 미탐이었다(설계서 §2-3 「느슨이 놓친
    # 6문장」). A-03 상 LLM 은 부품을 고르지 않으므로 이것도 대조로 보낸다.
    part_nouns = ("그래픽카드", "지포스", "라데온", "CPU", "GPU", "램", "SSD",
                  "파워", "메인보드")
    if any(w in sentence for w in part_nouns):
        return True
    # 어휘만 걸렸다 — 등급·사양을 «단정»하는 말일 때만 대조로 보낸다.
    grade_claim = ("고사양", "저사양", "중사양", "중급형", "보급형", "요구사양",
                   "요구 사양", "필요 사양", "사양이 낮", "사양이 높", "사양을 먹",
                   "사양까지는", "사양이 필요", "사양 필요")
    return any(w in sentence for w in grade_claim)


def _substitute(sentence: str, kinds: list[str], floors: PriceFloors,
                grade: str | None) -> tuple[str, str]:
    """걸린 문장 -> (치환 문장, 대조 원천 이름). 빈 문자열이면 삭제(ⓑ-2 로 접음).

    ⓑ-1(치환) 기본 · 치환할 «우리 값»이 없으면 ⓑ-2(삭제). ⓑ-3(둘 다 보임)은 쓰지
    않는다 — 거짓을 한 번 내보내는 것이라 설계자도 반대했다.
    """
    # 재고·배송이 가장 세다 — 대조할 원천 자체가 상담 경로에 없다.
    if KIND_STOCK in kinds:
        return SUB_DROP, "none(stock/shipping is not answered here)"
    # 가격 주장 -> grid_quotes 실조회 값으로 갈아 끼운다.
    if KIND_PRICE in kinds:
        floor = floors.floor_for(grade)
        if floor:
            return SUB_PRICE.format(floor=_fmt_won(floor)), "grid_quotes x grid_cells"
        return SUB_PRICE_NO_FLOOR, "none(no current quote)"
    # 부품·사양 수치 -> LLM 은 부품을 고르지 않는다(A-03). 치환할 «우리 값»이 없다.
    if KIND_PART in kinds or KIND_SPEC in kinds:
        return SUB_PART, "A-03(LLM does not build quotes)"
    # 등급 단정 -> 등급의 정본은 DB 다(game_load_grades · game_grade_assignments).
    return SUB_GRADE, "game_grade_assignments"


def apply_filter(answer: str, floors: PriceFloors,
                 grade: str | None = None) -> FilterResult:
    """★ 본체 — LLM 자유 답변 -> 우리 DB 기준으로 거른 고객 문장.

    3층(문장 분해 -> 탐지 -> 대조·처리)을 차례로 태운다. 손댄 것은 전부
    `replaced`/`dropped` 에 **원문과 함께** 남긴다 — 조용히 지우지 않는다
    (이 저장소의 `dropped[]` 규약과 같은 원칙).

    ■ 문장 끝 게이트 (설계서 §2-5 「세 번째 그물」)
      탐지기를 통과했더라도 답변 전체에 숫자·부품 어휘가 남아 있으면 `gate_hit` 을
      세운다. 미탐을 «조용한 사고»가 아니라 **«보이는 사고»**로 만든다 —
      「중급형으로 가는 게 좋습니다」처럼 숫자도 부품명도 없는 완곡 표현이 규칙의
      유일한 미탐이었다(실측 1/14).
    """
    out: list[str] = []
    # 게이트는 «모델이 쓴 문장»만 본다 — 우리가 써 넣은 치환 문구에도 금액이 들어 있어
    # (\"908,800원부터\") 그것까지 세면 게이트가 항상 걸린다. 서버가 DB 에서 읽어 쓴 값은
    # 검사 대상이 아니다(그 값이 곧 «우리 값»이다).
    survived: list[str] = []
    res = FilterResult(text="")
    for s in split_sentences(answer):
        kinds = detect(s)
        if not kinds:
            out.append(s)
            survived.append(s)
            res.kept += 1
            continue
        if not _claims_value(s, kinds):
            # 탐지는 됐지만 값을 주장하지 않는다 — 무해 통과(유도 문장을 살리는 층).
            out.append(s)
            survived.append(s)
            res.kept += 1
            continue
        new, src = _substitute(s, kinds, floors, grade)
        if new:
            # 같은 치환 문구가 연달아 두 번 나가지 않게 한다(답변이 어색해진다).
            if new not in out:
                out.append(new)
            res.replaced.append({"before": s, "after": new, "kinds": kinds,
                                 "source": src})
        else:
            res.dropped.append({"before": s, "kinds": kinds, "reason": src})
    final = " ".join(out).strip()
    # 문장 끝 게이트 — **모델이 쓴** 문장에 숫자 주장이 남았는가.
    leftover = " ".join(survived)
    if _RE_PRICE.search(leftover) or _RE_PART.search(leftover):
        res.gate_hit = True
        log.warning("[talk-filter] end gate hit - numeric claim survived filter")
    res.text = final
    return res
