# -*- coding: utf-8 -*-
"""사무 용도 2분할 — `office` -> «단순 사무용»(office_simple) · «복합 사무용»(office_complex).

설계 정본: docs/design/usage-rules-rebuild-2026-09-18.md §2-개정
사장님 확정(2026-09-18): "대다수 오피스 문서작성 등은 8GB 램이면 충분한데" /
  "단순 작업.. 그리고 좀 더 무거운 작업.. 이런식으로 구분해서" / "**단순 사무용, 복합 사무용**"

■ 왜 이 마이그레이션이 필요한가 — 0101 ②의 자기 정정
  0101 이 `office` RAM 하한을 8 -> 16GB 로 올렸다. 근거로 든 것은
  `software_community_spec` 의 16GB 네 건인데, **그 note 를 다시 읽으면 대부분
  조사자의 «해석»이다**(전부 실조회로 확인):

      프로그램            값            note 가 실제로 말하는 것
      줌(id 39)          rec_ram_gb 16 **제조사 공식 권장값** (confidence '확인')
      MS 오피스(id 36)    커뮤 16       "...16GB가 현실적 기준이라는 **해석**.
                                        정량 표본은 빈약하므로 confidence 추정"
      팀즈(id 40)        커뮤 16       "Teams 단독 정량 표본은 미확보 ...
                                        **현실적이라는 해석**. confidence 추정"
      웹브라우저(id 42)   커뮤 16       "다른 프로그램 상담 중 반복적으로 등장
                                        (Lightroom/Photoshop 스레드) ... confidence 추정"
      한글(id 35)        커뮤 8        "한글 단독으로는 논의 대상이 아니며,
                                        실사용은 브라우저 다중 탭·엑셀과 **동시 구동**이
                                        전제이므로 시스템 전체 8GB"
      PDF(id 37)·카톡(id 41)  값 없음   "정량 커뮤니티 권장치 미확보(null)"

  **공식 최소는 전부 4GB 이하다**(한글 2 · MS 오피스 4 · 줌 4 · 팀즈 4).
  16GB 를 부르는 근거는 네 건 모두 **「동시에 쓴다」**이지 프로그램이 무거워서가
  아니다 — note 원문이 그렇게 적혀 있다("브라우저·메신저 동시 구동", "상시 구동 +
  오피스·브라우저 동시 사용", "브라우저 다중 탭·엑셀과 동시 구동").

  즉 `office` 한 키 안에 **한글만 쓰는 사람**과 **엑셀+줌+브라우저 30탭을 동시에
  켜는 사람**이 섞여 있어서 8이냐 16이냐로 싸운 것이다. **나누면 둘 다 맞는다.**
  ⚠ 0101 은 이미 적용됐다 — 수정하지 않는다. 이 새 파일로 개정한다.

■ ★ 판정 ⓐ/ⓑ/ⓒ — **ⓑ(office 를 office_simple 로 개명 + office_complex 신설)**
  ⓐ office 를 남기고 둘을 추가 — **버린다.** 세 키가 되면 「사무용」이 어디로 갈지
     가 다시 모호해진다. 사장님 구분의 요점은 «둘 중 하나로 갈라라»다.
  ⓒ office 를 지우고 둘 다 신설 — **버린다.** `usage_alloc` 3행이 usage_key='office'
     를 들고 있고 회귀 [52]① 이 「활성 usage_alloc.usage_key ⊆ usage_floors.usage_key」
     를 불변식으로 검사한다. 지우면 그 순간 깨진다. floor_id 20·21 의 이력도 끊긴다.
  ⓑ **개명** — 고른 쪽. floor_id 20·21 을 그대로 두고 usage_key/label/terms/값만
     고친다. RAM 은 8 로 되돌아가는데 이것은 «0101 이전 값으로의 복귀»가 아니라
     **한글 커뮤니티 8GB(software_community_spec id 35) 라는 실측값의 재확인**이다.
     `usage_alloc` 3행도 같이 개명하고 office_complex 3행을 복제해 넣는다.

■ ★ 판정 — 「사무용」처럼 양쪽에 걸리는 말은 어디로 가는가 -> **단순 쪽 (사장님 확정)**
  사장님 2026-09-18 추가 지시: "i3 CPU 에 8GB 메모리를 쓰는데, 대부분 문서작업과
  학교 수업자료 준비라 큰 어려움은 없어보여.. 그런 사람들에게 비용은 좀 부담일 수
  있어" -> **단순 사무용은 «최저가 등급»이 아니라 «맞는 사양»이다.** 모호할 때
  비싼 쪽을 내밀면 얻는 것 없이 30만원을 더 받는다(실측: 단순 약 41만 vs 복합 약 70만).
  싼 걸 내밀고 "더 필요하세요?"가, 비싼 걸 내밀고 "사실 필요 없어요"보다 낫다 —
  후자는 이미 결제한 뒤에야 알게 된다.
  `match()` 는 sort_order 순 **첫 usage_key 하나만** 쓴다. 그래서 순서로 정한다:
      office_complex  sort 60, 61   (앞)
      office_simple   sort 62, 63   (뒤)
  ⚠ office 가 지금 60,61 이다. **그 자리를 그대로 쓴다** — trading(21,22)·
    dev(23)·stream(25)·music(27) 이 먼저 잡히는 0101 ③의 관계를 한 줄도 깨지 않는다
    (60~63 은 여전히 27 뒤, video_3d 103 앞).

  복합을 «앞》에 두는데 결과가 왜 「단순 쪽」인가 — **낱말의 성격이 다르기 때문이다.**
    · office_complex 의 낱말은 전부 **특정 신호**다(엑셀·화상회의·줌·팀즈·재택근무·
      동시작업). 모호한 말이 하나도 없다.
    · 모호한 말(「사무」·「사무용」)은 **office_simple 만** 갖는다.
  따라서 "사무용" -> 복합의 낱말에 안 걸리고 -> **office_simple**(8GB).
  반대로 "문서작성이랑 화상회의" 처럼 **둘 다 걸리는 문장은 복합이 이긴다** — 이쪽이
  옳다. 「화상회의」는 동시 구동을 명시한 신호이고, 「문서」는 아무 말도 아니다.
  ⚠ 순서를 뒤집어 단순을 앞에 두면 "문서작성이랑 화상회의"가 단순(8GB)으로 접힌다.
    그건 **고객이 말한 신호를 버리는 것**이라 안 된다. 안전한 기본값(모호 -> 단순)은
    낱말 배치로 얻고, 순서는 «구체적 신호가 이긴다»에 쓴다 — 두 목적을 분리했다.

  ⚠ 「업무용」은 복합에 둔다(사장님 지시 목록 그대로). 다만 이것은 판단이 갈린
    자리다 — 「업무용」은 「사무용」만큼 모호하다. 그래서 **바 「업무」가 아니라
    「업무용」만** 넣었다(「회사 업무」·「업무 보조」는 단순으로 떨어진다).

■ 낱말 변경 — 「웹」을 뺀다
  옛 office 의 「웹」은 **부분일치로 너무 많이 삼켰다**(「웹 개발」이 office 로 갔던
  0101 ③의 원인 중 하나). 「인터넷」·「웹서핑」으로 좁혀서 대신한다.
  「사무」는 남긴다 — `grid_cells.usage='사무·인강'`(12행)과 회귀가 이 낱말로 붙는다.

Revision ID: 0102
Revises: 0101
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0102"
down_revision = "0101"
branch_labels = None
depends_on = None


# ── 신설/개정 정의 ────────────────────────────────────────────────────────
# (slot, field, op, value, label, detail_fmt)
SIMPLE_KEY, SIMPLE_LABEL = "office_simple", "단순 사무용"
COMPLEX_KEY, COMPLEX_LABEL = "office_complex", "복합 사무용"

# ⚠ 모호한 말(「사무」·「사무용」)은 **여기에만** 있다. 위 ★ 판정 참조.
SIMPLE_TERMS = [
    "문서작성", "한글", "워드", "문서", "인터넷", "웹서핑",
    "인강", "강의", "가벼운 사무", "단순 사무", "사무용", "사무",
    # 「수업」 — 사장님이 직접 든 사례("학교 수업자료 준비")가 실측에서 **아무 하한도
    #   못 받았다**(match -> None). 그 사람이 바로 단순 사무용의 정의인데 표에
    #   낱말이 없었다. 「수업자료」·「수업 준비」를 부분일치로 함께 받도록 「수업」으로 넣는다.
    #   ⚠ 충돌 확인: 다른 usage_key 의 낱말 어디에도 '수업'이 부분문자열로 없다.
    "수업",
]
# ⚠ 전부 «특정 신호»만 — 모호한 말을 넣으면 위 판정이 무너진다.
COMPLEX_TERMS = [
    "엑셀", "대용량", "화상회의", "줌", "팀즈",
    "다중작업", "동시작업", "재택근무", "복합 사무", "업무용",
]

SIMPLE_RULES = [
    # RAM 8 — 한글 커뮤니티 8GB(software_community_spec id 35). 카테고리 「사무·문서」
    #   에서 «가장 낮은» 커뮤니티 값이고, 공식 최소는 더 낮다(한글 2 · MS 오피스 4).
    #   ⚠ 이 8GB 자체도 note 가 "…현실적이라는 해석. confidence 추정"이라 적는다 —
    #     그대로 표시하고 쓴다. 공식 근거만으로는 4GB 이므로 8 은 이미 보수적이다.
    #   ★ 문구는 «부족해서 싸다»가 아니라 «맞아서 이 값이다»라고 말해야 한다
    #     (사장님 2026-09-18 추가 지시). 그래서 근거 한 줄에 «왜 8GB 로 충분한가»와
    #     «언제 복합으로 올려야 하는가»를 같이 적는다. 숫자는 전부 실조회값이다.
    ("RAM", "capacity_gb", "gte", 8, "사무 메모리",
     "{v}GB — 문서·웹·인강은 한 번에 하나씩 쓰는 순차 작업이라 8GB 로 충분합니다"
     " (한글 공식 최소 2GB · MS오피스 공식 최소 4GB, 커뮤니티 해석 8GB 를 하한으로)."
     " 엑셀 대용량 파일과 화상회의를 «동시에» 쓰신다면 복합 사무용을 보세요"),
    # SSD 250 — 옛 office 값 유지. 올릴 근거가 `software` 에 없다
    #   (MS 오피스 min_storage_gb=4 · 팀즈 3 · 나머지 null).
    ("SSD", "capacity_gb", "gte", 250, "사무 저장 용량",
     "{v}GB (MS오피스 공식 설치 4GB + 문서·PDF 보관 기준)"),
]
COMPLEX_RULES = [
    # RAM 16 — **줌 공식 권장 rec_ram_gb=16**(software id 39 · confidence '확인').
    #   이 표에서 16GB 를 말하는 값 중 **유일하게 제조사 공식값**이다. 나머지 세 건
    #   (MS오피스·팀즈·브라우저)은 note 가 스스로 "해석 · confidence 추정"이라 적는다 —
    #   방향이 같아 보조 근거로만 적고, 하한의 근거는 줌 공식값 하나로 세운다.
    ("RAM", "capacity_gb", "gte", 16, "복합 사무 메모리",
     "{v}GB (줌 공식 권장 {r}GB — 화상회의+문서+브라우저 동시 구동. "
     "MS오피스·팀즈·브라우저 커뮤니티 16GB 는 해석값이라 보조 근거)"),
    # SSD 500 — 팀즈 공식 3GB + MS오피스 4GB 설치에 더해 회의 녹화·대용량 엑셀·
    #   첨부 보관을 함께 두는 구성. 재고 실측상 500/512GB 가 45종이라 좁아지지 않는다
    #   (0101 이 dev·stream·music 에 같은 근거로 500 을 쓴 것과 같은 판단).
    ("SSD", "capacity_gb", "gte", 500, "복합 사무 저장 용량",
     "{v}GB (MS오피스 4GB + 팀즈 3GB 공식 설치 + 대용량 파일·회의 녹화 보관)"),
]

COMPLEX_ORDER = {"RAM": 60, "SSD": 61}   # office 가 쓰던 자리 — 상대 순서 불변
SIMPLE_ORDER = {"RAM": 62, "SSD": 63}

# 0101 이 남긴 office 의 상태(downgrade 복원용)
_OFFICE_LABEL = "사무·인강"
_OFFICE_TERMS = ["사무", "인강", "문서", "웹", "화상회의"]
_OFFICE_RULES = {
    "RAM": (16, "사무 메모리",
            "{v}GB (줌 공식 권장 {r}GB · 팀즈·MS오피스 커뮤니티 16GB)"),
    "SSD": (250, "사무 저장 용량", "{v}GB (기준 {r}GB 이상)"),
}
_OFFICE_ORDER = {"RAM": 60, "SSD": 61}

# ── usage_alloc — office 3행을 개명하고 복합용 3행을 복제 ──────────────────
# ⚠ 배분율은 **새로 짓지 않는다.** 0086 의 office 표본("사무 GPU 9%(n=1)·iGPU 97%"
#   · "CPU 31%(n=31)" · "RAM 21%(n=30)")은 «나누기 전의 사무 전체» 표본이라 두
#   갈래 어느 쪽의 값도 아니다. 표본을 갈라 다시 잴 근거가 없으므로 **같은 값을
#   양쪽에 그대로 준다** — note 에 "분할 전 사무 표본 공용"이라고 명시한다.
#   (여기서 값을 지어내면 이 마이그레이션이 고치려는 바로 그 잘못을 반복한다.)
_ALLOC_NOTE_SUFFIX = " [0102: 분할 전 «사무» 표본 공용 — 갈래별 재측정 전까지 동일]"


def _ins_floor_params(key, label, terms, rules, order_map):
    blob = json.dumps(terms, ensure_ascii=False)
    for slot, field, oper, val, rlabel, fmt in rules:
        yield {"k": key, "ul": label, "t": blob, "s": slot, "f": field,
               "o": oper, "v": val, "l": rlabel, "d": fmt, "so": order_map[slot]}


_INS_FLOOR = sa.text(
    "INSERT INTO usage_floors (usage_key, usage_label, match_terms, slot,"
    " field, op, value, label, detail_fmt, sort_order)"
    " VALUES (:k, :ul, CAST(:t AS JSONB), :s, :f, :o, :v, :l, :d, :so)")


def upgrade() -> None:
    conn = op.get_bind()

    # ── ① office -> office_simple 개명 + 값 개정 (floor_id 20·21 유지) ────────
    simple_blob = json.dumps(SIMPLE_TERMS, ensure_ascii=False)
    for slot, field, oper, val, rlabel, fmt in SIMPLE_RULES:
        conn.execute(sa.text(
            "UPDATE usage_floors SET usage_key=:k, usage_label=:ul,"
            " match_terms=CAST(:t AS JSONB), op=:o, value=:v, label=:l,"
            " detail_fmt=:d, sort_order=:so"
            " WHERE usage_key='office' AND slot=:s AND field=:f"),
            {"k": SIMPLE_KEY, "ul": SIMPLE_LABEL, "t": simple_blob, "o": oper,
             "v": val, "l": rlabel, "d": fmt, "so": SIMPLE_ORDER[slot],
             "s": slot, "f": field})

    # ── ② office_complex 신설 — 재실행 안전 ────────────────────────────────
    have = {r[0] for r in conn.execute(sa.text(
        "SELECT DISTINCT usage_key FROM usage_floors")).all()}
    if COMPLEX_KEY not in have:
        for params in _ins_floor_params(COMPLEX_KEY, COMPLEX_LABEL,
                                        COMPLEX_TERMS, COMPLEX_RULES,
                                        COMPLEX_ORDER):
            conn.execute(_INS_FLOOR, params)

    # ── ③ usage_alloc — 개명 + 복합 복제 ───────────────────────────────────
    conn.execute(sa.text(
        "UPDATE usage_alloc SET usage_key=:k,"
        " note = CASE WHEN note LIKE :mark THEN note ELSE note || :suf END"
        " WHERE usage_key='office'"),
        {"k": SIMPLE_KEY, "mark": "%0102:%", "suf": _ALLOC_NOTE_SUFFIX})
    exists = conn.execute(sa.text(
        "SELECT 1 FROM usage_alloc WHERE usage_key=:k LIMIT 1"),
        {"k": COMPLEX_KEY}).first()
    if not exists:
        conn.execute(sa.text(
            "INSERT INTO usage_alloc (usage_key, slot, pct_min, pct_max, note,"
            " active, sort_order)"
            " SELECT :new, slot, pct_min, pct_max, note, active, sort_order + 10"
            " FROM usage_alloc WHERE usage_key=:old"),
            {"new": COMPLEX_KEY, "old": SIMPLE_KEY})


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("DELETE FROM usage_alloc WHERE usage_key=:k"),
                 {"k": COMPLEX_KEY})
    conn.execute(sa.text(
        "UPDATE usage_alloc SET usage_key='office',"
        " note = replace(note, :suf, '') WHERE usage_key=:k"),
        {"k": SIMPLE_KEY, "suf": _ALLOC_NOTE_SUFFIX})

    conn.execute(sa.text("DELETE FROM usage_floors WHERE usage_key=:k"),
                 {"k": COMPLEX_KEY})

    office_blob = json.dumps(_OFFICE_TERMS, ensure_ascii=False)
    for slot, (val, rlabel, fmt) in _OFFICE_RULES.items():
        conn.execute(sa.text(
            "UPDATE usage_floors SET usage_key='office', usage_label=:ul,"
            " match_terms=CAST(:t AS JSONB), value=:v, label=:l, detail_fmt=:d,"
            " sort_order=:so WHERE usage_key=:k AND slot=:s"),
            {"ul": _OFFICE_LABEL, "t": office_blob, "v": val, "l": rlabel,
             "d": fmt, "so": _OFFICE_ORDER[slot], "k": SIMPLE_KEY, "s": slot})
