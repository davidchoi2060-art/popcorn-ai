# -*- coding: utf-8 -*-
"""usage_floors 8군 전면 반영 — xlsx 확정(2026-09-15 사장님 직접 확정) 이행.

■ 원본 — 사장님이 xlsx(`용도별 구분.xlsx`)로 직접 확정한 8개 용도군.
  docs/design/usage-8group-migration-plan-2026-09-15.md 가 재고 실측 대조까지
  마친 설계다(§0~§9). 이 마이그레이션은 그 §9 DDL 초안을 그대로 옮기되,
  사장님이 이후 확정한 두 가지로 조정했다:
    ① trading·design GPU 하한 신설 — **하지 않는다**(2026-09-15 사장님 확정
       "하한을 잡을 필요가 있나?" — iGPU 슬롯 생략(b4180fd)이 이미 있어
       GPU 하한 없이도 저렴하게 나가는 게 맞다는 판단. §10-2 항목 보류가 아니라
       기각으로 확정).
    ② orphan 5종(ai·dev·stream·media·web) — **8군 전면 교체**로 확정
       (§10-4, "8군으로 전면 교체 — ai만 유지"). dev·stream·media·web 4개는
       폐기한다 — 매칭이 없어지는 검색어는 남은 가장 가까운 군(대개 office)으로
       흐른다. ai 는 A-135 가 이미 "지금 구조(ai_workloads) 유지"로 별도 확정.

■ 게임 3단계(game_casual·game·gaming_high) — GPU 하한이 550W 로 동률(§10-3
  미해결, §4-4 실측). 이번엔 §5 조사자 제안대로 SSD 하한(500GB vs 1000GB)으로
  갈라 구분한다 — 완전한 해소는 아니지만(RAM 상한 등 다른 축은 usage_floors
  구조상 표현 불가), 지어내지 않고 표현 가능한 범위에서만 반영한다.

■ "발로란트" 중복(§5) — xlsx 원문이 캐주얼(3항)·게임 일반(4항) 양쪽에 실어
  두었으나 `usage_floors.match()`는 첫 hit 하나만 쓴다. game_casual 에만
  남기고 game(일반)에서는 뺀다 — 발로란트는 이스포츠 경량 타이틀이라 캐주얼
  정의와 더 맞는다(spec-tier-migration-plan-2026-09-14.md §2-3 선례와 일치).

■ CPU 등급 축(§4-9) — usage_floors 에 걸 자리가 없다(FLOOR_FIELDS 에 CPU 없음).
  이번에도 반영하지 않는다 — 지어내지 않는다. 필요하면 usage_tier_rules(0085,
  cpu_cores 필드 이미 있음)로 별도 이행한다(이 마이그레이션 범위 밖).

■ "백업용 HDD"(design, §4-6) — SSD·HDD 두 슬롯 조합을 한 필드로 표현 못 한다.
  SSD 하한만 반영하고 HDD 요건은 포기한다(설계서와 동일한 한계 — 새 설계
  없이는 못 채운다).

■ sort_order — 기존 0~53 구간을 보존한다. 삭제되는 4종(stream 7-9·dev
  18-19·media 54-55·web 56-57)의 번호는 비게 두고(재사용하지 않는다 — 다음
  마이그레이션이 그 번호를 다시 쓰면 순서 실수가 나기 쉽다), 신규 2종
  (game_casual·video_3d)은 뒤에 이어 붙인다(_START=100, 기존 최대값 57보다
  충분히 뒤).

■ downgrade — UPDATE 값은 이전 값으로 되돌리고, DELETE 된 4종은 0016/0057의
  원래 SEED 값으로 복원하고, INSERT 된 2종(game_casual·video_3d)은 삭제한다.
  0057 관례와 같다 — 값 자체가 이 파일이 원본이라 되돌려도 잃는 것이 없다.

Revision ID: 0090
Revises: 0089
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


# ── UPDATE 대상 — 기존 6개 usage_key, 값만 xlsx 8군 기준으로 갱신 ──────────
# (usage_key, slot, field, 새 op, 새 value, 새 label, 새 detail_fmt)
UPDATES = [
    ("game", "GPU", "required_power_watt", "gte", 550,
     "게임 GPU 등급", "권장 전원 {v}W (RTX 5060 실측 — 8군 확정, 기존 450W)"),
    ("game", "SSD", "capacity_gb", "gte", 1000,
     "게임 저장 용량", "{v}GB (8군 확정, 기존 500GB)"),
    ("gaming_high", "GPU", "required_power_watt", "gte", 650,
     "고사양 게임 GPU 등급", "권장 전원 {v}W (RTX 5070 실측 — 8군 확정, 기존 550W)"),
    ("gaming_high", "RAM", "capacity_gb", "gte", 32,
     "고사양 게임 메모리", "{v}GB (8군 확정, 기존 16GB)"),
    ("gaming_high", "SSD", "capacity_gb", "gte", 1000,
     "고사양 게임 저장 용량", "{v}GB (8군 확정, 기존 500GB)"),
    ("video", "GPU", "required_power_watt", "gte", 600,
     "영상편집 GPU 등급", "권장 전원 {v}W (RTX 5060 Ti 실측 — 8군 확정, 기존 450W)"),
    ("video", "SSD", "capacity_gb", "gte", 2000,
     "영상편집 저장 용량", "{v}GB (고속 NVMe 기준, 8군 확정, 기존 1000GB)"),
]
# 되돌릴 이전 값(downgrade용 — UPDATES와 같은 순서·같은 키)
UPDATES_PREV = [
    ("game", "GPU", "required_power_watt", "gte", 450,
     "게임 GPU 등급", "권장 전원 {v}W (게임 기준 {r}W 이상)"),
    ("game", "SSD", "capacity_gb", "gte", 500,
     "게임 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ("gaming_high", "GPU", "required_power_watt", "gte", 550,
     "고사양 게임 GPU 등급", "권장 전원 {v}W (고사양 게임 기준 {r}W 이상)"),
    ("gaming_high", "RAM", "capacity_gb", "gte", 16,
     "고사양 게임 메모리", "{v}GB (기준 {r}GB 이상)"),
    ("gaming_high", "SSD", "capacity_gb", "gte", 500,
     "고사양 게임 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ("video", "GPU", "required_power_watt", "gte", 450,
     "영상편집 GPU 등급", "권장 전원 {v}W (영상편집 기준 {r}W 이상)"),
    ("video", "SSD", "capacity_gb", "gte", 1000,
     "영상편집 저장 용량", "{v}GB (소스 보관 기준 {r}GB 이상)"),
]

# ── DELETE 대상 — orphan 4종(8군 전면 교체, ai만 유지) ─────────────────────
ORPHAN_KEYS = ["dev", "stream", "media", "web"]

# 되돌릴 원본 SEED(downgrade용 — 0016/0057 원문 그대로)
ORPHAN_RESTORE = [
    ("stream", "방송·스트리밍", ["방송", "스트리밍"], [
        ("GPU", "required_power_watt", "gte", 550,
         "방송 GPU 등급", "권장 전원 {v}W (방송 기준 {r}W 이상)"),
        ("RAM", "capacity_gb", "gte", 32, "방송 메모리", "{v}GB (인코딩 기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 1000, "방송 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ]),
    ("dev", "개발", ["개발"], [
        ("RAM", "capacity_gb", "gte", 16, "개발 메모리", "{v}GB (기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 500, "개발 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ]),
    ("media", "영화·미디어", ["영화", "넷플릭스", "미디어 감상", "영상 시청"], [
        ("RAM", "capacity_gb", "gte", 8, "영화 메모리", "{v}GB (기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 500, "영화 저장 용량", "{v}GB (영상 파일 기준 {r}GB 이상)"),
    ]),
    ("web", "인터넷·시청", ["인터넷", "강의 시청"], [
        ("RAM", "capacity_gb", "gte", 8, "인터넷 메모리", "{v}GB (기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 250, "인터넷 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ]),
]

# ── INSERT 신규 — game_casual(캐주얼 게임) · video_3d(3D 그래픽) ──────────
# sort_order 100번대 — 기존 0~57 을 건드리지 않는다. game_casual 은 game·
# gaming_high 보다 "좁은 낱말"이라 앞서 걸려야 한다(usage_floors.match()가
# sort_order 오름차순 첫 hit) — 100은 기존 전체(0~57)보다 뒤이지만, 셋
# 사이에서는 game_casual(100)이 video_3d(103)보다 먼저다. game·gaming_high
# 와의 상대 순서는 이 표 자체가 아니라 sort_order 절대값이 정한다: game_casual
# 이 100이라 game(sort 13~15)·gaming_high(sort 1~3)보다 뒤에 걸린다 — 즉
# "게임"·"고사양 게임" 문구가 있으면 그쪽이 먼저 이긴다. game_casual 고유
# 검색어(리그 오브 레전드·FC 온라인 등)는 game·gaming_high match_terms에
# 없으므로 실제로는 충돌하지 않는다(발로란트만 예외 — 아래 참조).
NEW_SEED = [
    ("game_casual", "캐주얼 게임", [
        # ⚠ 라벨 자신(「캐주얼 게임」)을 맨 앞에 둔다 — 0057 불변식("라벨은 자기
        # 낱말로 잡혀야 한다") 위반이 실제로 났다(2026-09-15, LLM이 usage_label을
        # 그대로 반환하면 match_terms에 그 부분 문자열이 없어 game(넓은 라벨,
        # "게임"이 부분일치)으로 새어나갔다 — 실측: UF.match("캐주얼 게임") 이
        # game_casual이 아니라 game을 반환). 되짚은 뒤 이 SEED에 반영했다.
        "캐주얼 게임",
        "캐주얼 게임용", "리그 오브 레전드", "롤", "FC 온라인", "저사양 게임용", "FHD 해상도 입문형",
        # ⚠ "발로란트"는 여기만 둔다 — game(일반)의 기존 match_terms에서 뺀다(아래 참조).
        "발로란트",
    ], [
        ("GPU", "required_power_watt", "gte", 550, "캐주얼 게임 GPU 등급",
         "권장 전원 {v}W (캐주얼 게임 기준 {r}W 이상 — RTX 3050 실측)"),
        ("RAM", "capacity_gb", "gte", 16, "캐주얼 게임 메모리", "{v}GB (기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 500, "캐주얼 게임 저장 용량", "{v}GB (기준 {r}GB 이상)"),
    ]),
    ("video_3d", "3D 그래픽", [
        "3D 그래픽", "건축 디자인", "3ds Max", "Maya", "Blender", "CAD",
        "엔지니어링", "수백만 폴리곤 렌더링",
    ], [
        ("GPU", "required_power_watt", "gte", 850, "3D 그래픽 GPU 등급",
         "권장 전원 {v}W (3D 작업 기준 {r}W 이상 — RTX 5080 실측)"),
        ("RAM", "capacity_gb", "gte", 64, "3D 그래픽 메모리", "{v}GB (기준 {r}GB 이상)"),
        ("SSD", "capacity_gb", "gte", 2000, "3D 그래픽 저장 용량", "{v}GB (고속 NVMe 기준 {r}GB 이상)"),
    ]),
]
_NEW_START = 100


def upgrade() -> None:
    conn = op.get_bind()

    # ① UPDATE — 기존 6개 usage_key 값 갱신
    for key, slot, field, oper, val, label, fmt in UPDATES:
        conn.execute(sa.text(
            "UPDATE usage_floors SET op=:o, value=:v, label=:l, detail_fmt=:d"
            " WHERE usage_key=:k AND slot=:s AND field=:f"),
            {"o": oper, "v": val, "l": label, "d": fmt, "k": key, "s": slot, "f": field})

    # ② "발로란트"·"롤" 중복 처리 — game(일반)의 match_terms에서 뺀다
    # (game_casual에만 남긴다 — 둘 다 xlsx 원문상 캐주얼 대표 타이틀이다)
    row = conn.execute(sa.text(
        "SELECT match_terms FROM usage_floors WHERE usage_key='game' LIMIT 1")).scalar()
    terms = [t for t in row if t not in ("발로란트", "롤")]
    conn.execute(sa.text(
        "UPDATE usage_floors SET match_terms=CAST(:t AS JSONB) WHERE usage_key='game'"),
        {"t": json.dumps(terms, ensure_ascii=False)})

    # ③ DELETE — orphan 4종(8군 전면 교체, ai만 유지)
    conn.execute(sa.text(
        "DELETE FROM usage_floors WHERE usage_key = ANY(:ks)"), {"ks": ORPHAN_KEYS})

    # ④ INSERT — game_casual · video_3d 신규
    # ⚠ sort_order — game_casual은 100번대가 아니라 **5~7**에 둔다(gaming_high
    # 0~2 다음, game 12~14 이전) — 2026-09-15 실사고로 교정: 100번대에 두면
    # game(sort 12~14)보다 뒤라 "캐주얼 게임" 라벨 자체가 game(넓은 매칭,
    # "게임" 부분일치)에 먼저 잡혔다(실측: UF.match("캐주얼 게임") → game).
    # "좁은 것 먼저" 원칙(0016·0057)을 sort_order로 실제로 지켜야 한다.
    # video_3d는 이 문제가 없다(video와 소속 라벨이 겹치지 않는다) — 100대 유지.
    _ORDER = {"game_casual": 5, "video_3d": _NEW_START}
    for key, label, terms, rules in NEW_SEED:
        blob = json.dumps(terms, ensure_ascii=False)
        order = _ORDER[key]
        for slot, field, oper, val, rlabel, fmt in rules:
            conn.execute(sa.text(
                "INSERT INTO usage_floors (usage_key, usage_label, match_terms, slot,"
                " field, op, value, label, detail_fmt, sort_order)"
                " VALUES (:k, :ul, CAST(:t AS JSONB), :s, :f, :o, :v, :l, :d, :so)"),
                {"k": key, "ul": label, "t": blob, "s": slot, "f": field, "o": oper,
                 "v": val, "l": rlabel, "d": fmt, "so": order})
            order += 1

    # ⑤ usage_floors 에서 orphan 4종을 지우면 usage_tier_rules 의 dev 참조가
    # 붕 뜬다(회귀 [51] "활성 usage_tier_rules.usage_key ⊆ usage_floors.usage_key"
    # — 2026-09-15 실행에서 실제로 잡혔다). dev 는 사장님이 8군 전면 교체로
    # 폐기를 확정했으므로, usage_tier_rules 의 dev 행도 함께 비활성화한다
    # (삭제가 아니라 active=false — 원장 규약과 같은 이유, downgrade 가 되돌린다).
    conn.execute(sa.text(
        "UPDATE usage_tier_rules SET active=false WHERE usage_key='dev' AND active"))


def downgrade() -> None:
    conn = op.get_bind()

    # ⑤의 역 — dev usage_tier_rules 재활성화
    conn.execute(sa.text(
        "UPDATE usage_tier_rules SET active=true WHERE usage_key='dev' AND NOT active"))

    # ④의 역 — 신규 2종 삭제
    conn.execute(sa.text(
        "DELETE FROM usage_floors WHERE usage_key IN ('game_casual', 'video_3d')"))

    # ③의 역 — orphan 4종 복원(0016/0057 원본 SEED 그대로, sort_order도 원래 번호로)
    restore_order = {"stream": 7, "dev": 18, "media": 54, "web": 56}
    for key, label, terms, rules in ORPHAN_RESTORE:
        blob = json.dumps(terms, ensure_ascii=False)
        order = restore_order[key]
        for slot, field, oper, val, rlabel, fmt in rules:
            conn.execute(sa.text(
                "INSERT INTO usage_floors (usage_key, usage_label, match_terms, slot,"
                " field, op, value, label, detail_fmt, sort_order)"
                " VALUES (:k, :ul, CAST(:t AS JSONB), :s, :f, :o, :v, :l, :d, :so)"),
                {"k": key, "ul": label, "t": blob, "s": slot, "f": field, "o": oper,
                 "v": val, "l": rlabel, "d": fmt, "so": order})
            order += 1

    # ②의 역 — "발로란트"·"롤"을 game(일반) match_terms로 복원
    row = conn.execute(sa.text(
        "SELECT match_terms FROM usage_floors WHERE usage_key='game' LIMIT 1")).scalar()
    if row:
        terms = list(row)
        for t in ("발로란트", "롤"):
            if t not in terms:
                terms.append(t)
        conn.execute(sa.text(
            "UPDATE usage_floors SET match_terms=CAST(:t AS JSONB) WHERE usage_key='game'"),
            {"t": json.dumps(terms, ensure_ascii=False)})

    # ①의 역 — 기존 6개 usage_key 값 원복
    for key, slot, field, oper, val, label, fmt in UPDATES_PREV:
        conn.execute(sa.text(
            "UPDATE usage_floors SET op=:o, value=:v, label=:l, detail_fmt=:d"
            " WHERE usage_key=:k AND slot=:s AND field=:f"),
            {"o": oper, "v": val, "l": label, "d": fmt, "k": key, "s": slot, "f": field})
