# -*- coding: utf-8 -*-
"""용도 규칙 재정비 — 빠진 용도 3종 신설 · office 하한 상향 · 주식 분리 · 조건부 규칙 표 신설.

설계 정본: docs/design/usage-rules-rebuild-2026-09-18.md
근거 자료: `software` 42종 + `software_community_spec` 실조회(2026-09-18) · TechSpot 2026-01.

**이 파일의 모든 숫자는 DB 실조회에서 왔다 — 지어내지 않았다.** 각 값의 출처를
아래 주석과 각 행의 note/detail_fmt 에 프로그램 이름과 수치까지 적는다.

■ 무엇을 하는가 (5 가지)
  ① usage_floors 신설 3종 — dev(개발) · stream(방송 송출) · music(음악 작업)
     `software` 42종 중 12종(28%)이 이 세 카테고리인데 표에 자리가 없었다.
     (0090 이 dev·stream 을 8군 전면 교체로 지웠는데, 그 뒤 소프트웨어 카탈로그
      0096 이 들어오면서 «근거가 생겼다» — 값이 없어 지운 것을 값을 갖고 되돌린다.)
  ② office RAM 하한 8GB -> 16GB
  ③ 주식(trading)을 office 보다 «먼저» 잡히게 한다 — office 의 sort_order 만 뒤로 민다
  ④ usage_tier_rules — dev 2행 재활성화 + music·trading 신설
  ⑤ part_cond_rules 표 신설 — 「VRAM 8GB 그래픽카드를 고르면 RAM 32GB」

■ ★ ④ 가 아니라 ⑤ 가 필요했던 이유 (P-08 스키마 신설 판정)
  usage_tier_rules 의 축은 (usage_key, budget_min) 이고, `passes()` 는 **부품 하나**를
  **자기 슬롯의 규칙**과 비교한다. 「GPU 의 VRAM 이 8GB 이면 RAM 을 32GB 로」는
  **슬롯을 건너뛰는 조건**이라 그 구조로는 표현할 수 없다 — budget_min 을 아무리
  써도 "어떤 GPU 를 골랐는지"가 규칙에 들어오지 않는다. 그래서 새 표를 만든다.
  ⚠ 이 마이그레이션은 **표와 값까지만** 만든다. 견적 엔진(recommend.py) 연결은
    다른 담당자가 같은 시각에 그 파일을 고치고 있어 이번 범위 밖이다 —
    설계 문서 §5 에 연결 지점을 적어 두었다.

■ ★ ③ 판정 — 왜 trading 을 올리지 않고 office 를 내리는가
  실측: `UF.match("사무실에서 주식")` -> **office**. '사무'(sort 19)가 '주식'(21)보다
  앞서기 때문이다. 고칠 방법이 둘인데:
    ㉮ trading 을 19 앞으로 당긴다 — 빈 번호가 8·17·18 셋뿐이라 신설 3종까지
       앞에 놓을 자리가 없다.
    ㉯ **office 를 뒤로 민다(19,20 -> 60,61)** — 고른 쪽.
       office 의 낱말('사무'·'인강'·'문서'·'웹'·'화상회의')은 표에서 **가장 넓다**.
       넓은 낱말이 맨 뒤에 서는 것이 `match()` 의 「좁은 것 먼저」 원칙과 맞다.
       그리고 60 은 기존 최대값(trading 22)보다 크고 video_3d(103)보다 작아
       **기존 키들 사이의 상대 순서를 한 줄도 바꾸지 않는다** — office 가
       trading·신설 3종보다 뒤로 가는 것만이 유일한 변화다(그것이 목적이다).
  ⚠ 동작 변경: '웹 개발' -> (전) office / (후) dev · '사무실에서 주식' -> (후) trading.
    둘 다 의도한 교정이다.

■ ★ 하한과 겨냥을 어디에 두는가 — 이 마이그레이션이 따른 기준
      usage_floors      «예산과 무관한 최저선». 이것보다 낮으면 그 용도를 못 한다.
                        -> 카테고리 프로그램들의 커뮤니티 권장치 중 **가장 낮은 값**
                           (모든 사용자가 공통으로 필요한 선)
      usage_tier_rules  «예산이 허락하면 겨냥하는 값». 못 맞추면 풀고 짓는다.
                        -> 같은 카테고리의 **무거운 쪽**(전업·대형 프로젝트) 수치
  예) 개발 — VS Code 커뮤니티 16GB 가 하한, 안드로이드 스튜디오·인텔리제이·도커
      커뮤니티 32GB 가 겨냥. 32 를 하한으로 박으면 60만원 개발 PC 가 아예 안 나오고,
      16 만 두면 예산이 있어도 32 로 안 올라간다. **둘 다 필요해서 표가 둘이다.**

Revision ID: 0101
Revises: 0100
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None


# ── ① usage_floors 신설 3종 ────────────────────────────────────────────────
# (usage_key, usage_label, match_terms, [(slot, field, op, value, label, detail_fmt)])
#
# ⚠ GPU 하한은 셋 다 «걸지 않는다» — `software.rec_gpu` 실측 결과:
#     개발 6종 전부 NULL(불요) · 방송 2종 전부 NULL · 음악은 에이블톤만
#     "영상 작업 시에만 외장 GPU". 그래픽 성능이 필요한 용도가 아니다
#     (사장님 확정 「환경축」 = GPU 불요 · 재기획안 §2).
#   0016 의 옛 stream 은 GPU 550W 를 걸고 있었는데, 그 값에는 근거가 없었다.
NEW_SEED = [
    ("dev", "개발", [
        # 라벨 자신이 잡혀야 한다(0057 불변식): 「개발」 ⊃ 「개발」 ✓
        "개발", "코딩", "프로그래밍", "웹 개발", "앱 개발",
        "안드로이드 스튜디오", "인텔리제이", "비주얼 스튜디오", "도커", "WSL",
    ], [
        # RAM 16 — VS Code 커뮤니티 16GB(software_community_spec.ram_gb=16,
        #   "실제 개발 환경에서 16GB가 현실적 하한") + 비주얼 스튜디오 공식
        #   권장 rec_ram_gb=16. 카테고리 6종 중 «가장 낮은» 커뮤니티 값이다.
        #   더 무거운 32GB(안드로이드 스튜디오·인텔리제이·도커)는 예산 연동이라
        #   usage_tier_rules 로 간다(아래 ④).
        ("RAM", "capacity_gb", "gte", 16, "개발 메모리",
         "{v}GB (VS Code 커뮤니티 기준 {r}GB · 비주얼 스튜디오 공식 권장 16GB)"),
        # SSD 500 — 비주얼 스튜디오 공식 권장 설치 rec_storage_gb=50 에
        #   0016 이 확정해 둔 개발 하한 500GB 를 유지한다(0090 이 지우기 전 값).
        #   재고 실측상 500/512GB 가 45종이라 선택지가 좁아지지 않는다.
        ("SSD", "capacity_gb", "gte", 500, "개발 저장 용량",
         "{v}GB (비주얼 스튜디오 공식 설치 50GB + 소스·컨테이너 이미지 기준)"),
    ]),
    ("stream", "방송 송출", [
        # 0058 판정을 그대로 따른다 — 「스트리밍」 단독은 넣지 않는다
        # (송출인지 시청인지 알 수 없다). 송출 «신호»만 남긴다.
        "방송", "송출", "생방송", "트위치", "아프리카TV", "치지직",
        "OBS", "스트림랩스",
    ], [
        # RAM 16 — 스트림랩스 공식 권장 rec_ram_gb=16 · 커뮤니티 16 ·
        #   OBS 커뮤니티 16(스트림랩스 공식값 준용). 방송 2종 모두 16GB 로 일치한다.
        #   ⚠ 0016 의 옛 값 32GB 는 근거가 없었다 — 실측에 맞춰 내린다.
        ("RAM", "capacity_gb", "gte", 16, "방송 메모리",
         "{v}GB (스트림랩스 공식 권장 {r}GB · OBS 커뮤니티 16GB)"),
        # SSD 500 — 스트림랩스 공식 권장 rec_storage_gb=512.
        #   재고에 512GB 가 30종 있어 500 하한이면 그대로 통과한다.
        ("SSD", "capacity_gb", "gte", 500, "방송 저장 용량",
         "{v}GB (스트림랩스 공식 권장 512GB — 녹화본 보관)"),
    ]),
    ("music", "음악 작업", [
        # ⚠ 「미디」는 넣지 않는다 — '멀티미디어'의 부분문자열이라 엉뚱한 문장을 끌어온다.
        "음악", "작곡", "편곡", "음원", "DAW", "큐베이스", "에이블톤",
        "FL 스튜디오", "로직 프로",
    ], [
        # RAM 16 — 에이블톤 공식 권장 rec_ram_gb=16 · 에이블톤 커뮤니티 16
        #   ("16GB가 편안한 제작 최소선") · FL 스튜디오 커뮤니티 16.
        #   큐베이스 커뮤니티 32 는 «무거운 쪽»이라 겨냥(④)으로 보낸다.
        ("RAM", "capacity_gb", "gte", 16, "음악 메모리",
         "{v}GB (에이블톤 공식 권장 {r}GB · 커뮤니티 \"편안한 제작 최소선 16GB\")"),
        # SSD 500 — 에이블톤 공식 권장 rec_storage_gb=500(샘플 라이브러리).
        ("SSD", "capacity_gb", "gte", 500, "음악 저장 용량",
         "{v}GB (에이블톤 공식 권장 {r}GB — 샘플 라이브러리)"),
    ]),
]
# sort_order — trading(21,22) 뒤, office(60,61 로 밀림) 앞. 셋 사이 순서는 서로
# 낱말이 겹치지 않아 뜻이 없다(사전순으로 dev -> stream -> music 고정).
_NEW_ORDER = {"dev": 23, "stream": 25, "music": 27}

# ── ② office RAM 하한 8 -> 16 ──────────────────────────────────────────────
# 근거(software_community_spec.ram_gb 실측):
#   줌            공식 권장 rec_ram_gb = 16   ("공식 권장이 이미 충분히 보수적")
#   MS 오피스      커뮤니티 16                 ("4GB 공식 최소로는 쾌적하지 않다")
#   마이크로소프트 팀즈  커뮤니티 16
#   웹브라우저 다중 탭  커뮤니티 16
# 4종이 전부 16GB 를 가리킨다. 8GB 를 가리키는 것은 「한글」 하나뿐이고 그것도
# "한글 단독으로는 논의 대상이 아니다"라는 단서가 붙어 있다.
_OFFICE_RAM_AFTER = (16, "{v}GB (줌 공식 권장 {r}GB · 팀즈·MS오피스 커뮤니티 16GB)")
_OFFICE_RAM_BEFORE = (8, "{v}GB (기준 {r}GB 이상)")

# ── ③ office sort_order 를 뒤로 — trading·신설 3종이 먼저 잡히게 ──────────
_OFFICE_ORDER_AFTER = {"RAM": 60, "SSD": 61}
_OFFICE_ORDER_BEFORE = {"RAM": 19, "SSD": 20}

# ③-b trading 낱말에 「영웅문」을 더한다 — `software` 의 행 이름이 「주식 HTS (영웅문 등)」다.
#   국내에서 가장 많이 불리는 이름인데 표에 없어 아무 하한도 안 걸렸다(실측: match 결과 None).
#   ⚠ 기존 낱말은 한 개도 빼지 않는다 — 더하기만 한다.
#   ⚠ 「차트」 단독은 넣지 않는다 — 「차트 디자인」·「조직도 차트」처럼 주식과 무관한
#     문장을 끌어온다(기존 「차트 여러」가 이미 좁게 잡고 있다).
_TRADING_TERMS_ADD = ["영웅문", "키움"]

# ── ④ usage_tier_rules — 겨냥(예산 연동) ──────────────────────────────────
# (usage_key, budget_min, slot, field, op, value, label, note, sort_order)
TIER_NEW = [
    ("music", 1_500_000, "RAM", "capacity_gb", "gte", 32, "메모리 32GB 이상",
     "큐베이스 커뮤니티 32GB · 에이블톤 커뮤니티 \"무거운 라이브러리를 쓰면 32GB 권장\"", 208),
    ("trading", 1_500_000, "RAM", "capacity_gb", "gte", 32, "메모리 32GB 이상",
     "주식 HTS 커뮤니티 32GB — \"창을 수십 개 띄우는 전업 트레이더 기준 32GB 이상\""
     " (같은 표본이 \"HTS+MTS+엑셀 병행은 16GB면 쾌적\"도 말한다 — 그래서 하한은 16, 겨냥이 32)", 209),
]
# dev 2행은 0090 이 usage_floors 에서 dev 를 지우며 active=false 로 내린 것이다
# (회귀 [51] 불변식 때문). dev 가 돌아왔으니 되살린다.
_DEV_RULE_IDS_SQL = "UPDATE usage_tier_rules SET active=:a WHERE usage_key='dev'"

# ── ⑤ part_cond_rules — 슬롯을 건너뛰는 조건부 규칙 ──────────────────────
COND_SEED = [
    (None, "GPU", "vram_gb", "lte", "8", "RAM", "capacity_gb", "gte", "32",
     "VRAM 8GB 이하 그래픽카드 — 메모리 32GB",
     "TechSpot 2026-01 전수 확인(검은신화 오공·킹덤컴 딜리버런스2·사이버펑크2077·"
     "배틀필드6): 최신 게임 대부분 시스템 램 16GB로 충분하지만, VRAM 8GB 카드를 쓰면"
     " 8GB 초과분이 시스템 램으로 넘어가 페이지파일 스왑이 일어나 프레임타임이 무너진다."
     " 32GB 로 바꾸면 1% low 가 60% 개선된다. 게임별 값이 아니라 «어떤 GPU 를 골랐는지»에"
     " 달린 조건이라 games·usage_floors·usage_tier_rules 어디에도 자리가 없다.", 100),
]


def _floor_rows(seed, order_map):
    for key, label, terms, rules in seed:
        blob = json.dumps(terms, ensure_ascii=False)
        order = order_map[key]
        for slot, field, oper, val, rlabel, fmt in rules:
            yield {"k": key, "ul": label, "t": blob, "s": slot, "f": field,
                   "o": oper, "v": val, "l": rlabel, "d": fmt, "so": order}
            order += 1


_INS_FLOOR = sa.text(
    "INSERT INTO usage_floors (usage_key, usage_label, match_terms, slot,"
    " field, op, value, label, detail_fmt, sort_order)"
    " VALUES (:k, :ul, CAST(:t AS JSONB), :s, :f, :o, :v, :l, :d, :so)")


def upgrade() -> None:
    conn = op.get_bind()

    # ⑤ 표부터 만든다 — 아래 어느 단계가 실패해도 표 정의는 남는 편이 낫다.
    #   value 를 VARCHAR 로 둔다: usage_tier_rules 가 INTEGER 로 만들었다가 op='in'
    #   (칩셋 집합)을 넣느라 뒤늦게 넓히고 로더에서 캐스팅을 덧대야 했다(0085 →
    #   api/usage_tier_rules.py 45행 주석). 같은 실수를 반복하지 않는다 —
    #   숫자 캐스팅은 로더(api/part_cond_rules.py)가 한 곳에서 한다.
    op.execute("""
        CREATE TABLE IF NOT EXISTS part_cond_rules (
            cond_id     SERIAL PRIMARY KEY,
            usage_key   VARCHAR(32),
            when_slot   VARCHAR(16)  NOT NULL,
            when_field  VARCHAR(64)  NOT NULL,
            when_op     VARCHAR(8)   NOT NULL DEFAULT 'lte',
            when_value  VARCHAR(255) NOT NULL,
            then_slot   VARCHAR(16)  NOT NULL,
            then_field  VARCHAR(64)  NOT NULL,
            then_op     VARCHAR(8)   NOT NULL DEFAULT 'gte',
            then_value  VARCHAR(255) NOT NULL,
            label       VARCHAR(80)  NOT NULL,
            note        TEXT,
            active      BOOLEAN      NOT NULL DEFAULT TRUE,
            sort_order  INTEGER      NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)
    op.execute("COMMENT ON TABLE part_cond_rules IS "
               "'슬롯을 건너뛰는 조건부 규칙(0101) — «A 슬롯이 이 조건이면 B 슬롯에 이 하한». "
               "usage_floors(고정 하한)·usage_tier_rules(예산 연동 겨냥) 어느 쪽으로도 "
               "표현할 수 없는 것만 여기 둔다. 정본 docs/design/usage-rules-rebuild-2026-09-18.md'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_part_cond_rules_usage"
               " ON part_cond_rules (usage_key, when_slot)")
    if not conn.execute(sa.text("SELECT count(*) FROM part_cond_rules")).scalar():
        for row in COND_SEED:
            conn.execute(sa.text(
                "INSERT INTO part_cond_rules (usage_key, when_slot, when_field,"
                " when_op, when_value, then_slot, then_field, then_op, then_value,"
                " label, note, sort_order) VALUES"
                " (:uk, :ws, :wf, :wo, :wv, :ts, :tf, :to, :tv, :l, :n, :so)"),
                dict(zip(("uk", "ws", "wf", "wo", "wv", "ts", "tf", "to", "tv",
                          "l", "n", "so"), row)))

    # ③ office 를 뒤로 민다 — ① 이 넣을 자리를 비우는 일이기도 하다
    for slot, order in _OFFICE_ORDER_AFTER.items():
        conn.execute(sa.text(
            "UPDATE usage_floors SET sort_order=:so WHERE usage_key='office' AND slot=:s"),
            {"so": order, "s": slot})

    # ③-b trading 낱말 보강 — 읽어서 더한다(덮어쓰지 않는다: 운영자가 화면에서
    #   낱말을 고쳤을 수 있다).
    cur = conn.execute(sa.text(
        "SELECT match_terms FROM usage_floors WHERE usage_key='trading' LIMIT 1")).scalar()
    if cur is not None:
        terms = list(cur) + [t for t in _TRADING_TERMS_ADD if t not in cur]
        conn.execute(sa.text(
            "UPDATE usage_floors SET match_terms=CAST(:t AS JSONB) WHERE usage_key='trading'"),
            {"t": json.dumps(terms, ensure_ascii=False)})

    # ② office RAM 하한 상향
    val, fmt = _OFFICE_RAM_AFTER
    conn.execute(sa.text(
        "UPDATE usage_floors SET value=:v, detail_fmt=:d"
        " WHERE usage_key='office' AND slot='RAM' AND field='capacity_gb'"),
        {"v": val, "d": fmt})

    # ① 신설 3종 — 재실행 안전(이미 있으면 건너뛴다)
    have = {r[0] for r in conn.execute(sa.text(
        "SELECT DISTINCT usage_key FROM usage_floors")).all()}
    for params in _floor_rows(NEW_SEED, _NEW_ORDER):
        if params["k"] in have:
            continue
        conn.execute(_INS_FLOOR, params)

    # ④ 겨냥 규칙 — dev 재활성화 + music·trading 신설
    conn.execute(sa.text(_DEV_RULE_IDS_SQL), {"a": True})
    for (uk, bmin, slot, field, o, v, label, note, so) in TIER_NEW:
        exists = conn.execute(sa.text(
            "SELECT 1 FROM usage_tier_rules WHERE usage_key=:uk AND budget_min=:b"
            " AND slot=:s AND field=:f AND op=:o"),
            {"uk": uk, "b": bmin, "s": slot, "f": field, "o": o}).first()
        if exists:
            continue
        conn.execute(sa.text(
            "INSERT INTO usage_tier_rules"
            " (usage_key, budget_min, slot, field, op, value, label, note, sort_order)"
            " VALUES (:uk, :b, :s, :f, :o, :v, :l, :n, :so)"),
            {"uk": uk, "b": bmin, "s": slot, "f": field, "o": o, "v": v,
             "l": label, "n": note, "so": so})


def downgrade() -> None:
    conn = op.get_bind()

    # ④의 역
    for (uk, bmin, slot, field, o, *_rest) in TIER_NEW:
        conn.execute(sa.text(
            "DELETE FROM usage_tier_rules WHERE usage_key=:uk AND budget_min=:b"
            " AND slot=:s AND field=:f AND op=:o"),
            {"uk": uk, "b": bmin, "s": slot, "f": field, "o": o})
    # dev 는 다시 내린다 — usage_floors 에서 dev 가 사라지면 회귀 [51] 이 깨진다
    conn.execute(sa.text(_DEV_RULE_IDS_SQL), {"a": False})

    # ①의 역
    conn.execute(sa.text(
        "DELETE FROM usage_floors WHERE usage_key IN ('dev', 'stream', 'music')"))

    # ②의 역
    val, fmt = _OFFICE_RAM_BEFORE
    conn.execute(sa.text(
        "UPDATE usage_floors SET value=:v, detail_fmt=:d"
        " WHERE usage_key='office' AND slot='RAM' AND field='capacity_gb'"),
        {"v": val, "d": fmt})

    # ③-b 의 역 — 더한 낱말만 뺀다
    cur = conn.execute(sa.text(
        "SELECT match_terms FROM usage_floors WHERE usage_key='trading' LIMIT 1")).scalar()
    if cur is not None:
        terms = [t for t in cur if t not in _TRADING_TERMS_ADD]
        conn.execute(sa.text(
            "UPDATE usage_floors SET match_terms=CAST(:t AS JSONB) WHERE usage_key='trading'"),
            {"t": json.dumps(terms, ensure_ascii=False)})

    # ③의 역
    for slot, order in _OFFICE_ORDER_BEFORE.items():
        conn.execute(sa.text(
            "UPDATE usage_floors SET sort_order=:so WHERE usage_key='office' AND slot=:s"),
            {"so": order, "s": slot})

    # ⑤의 역
    op.execute("DROP TABLE IF EXISTS part_cond_rules")
