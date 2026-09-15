# -*- coding: utf-8 -*-
"""spec_tiers(T0~T5) + 게임 부하등급(E/A/B/C/S/L) — A-135 격자 재설계 1단계.

■ 왜 필요한가 — 격자를 "가격 구간 먼저"에서 "스펙 하한 → 가격은 결과"로
  전환한다(2026-09-15 사장님 확정, decision-log A-135). "억지로 금액에 맞추다
  보니까 이상해진다"는 지적이 그대로 이 전환의 근거다 — 사무용 65만원 견적이
  iGPU CPU를 이미 골라놓고도 쓸모없는 GPU를 또 사던 사고(b4180fd로 해소)가
  가격 구간 먼저 방식의 대표 증상이었다.

■ 이 파일이 세우는 것 넷:
    ① spec_tiers                   T0~T5 스펙 하한(GPU VRAM·전력·CPU 코어·RAM·SSD)
    ② game_load_grades             게임 부하 등급 E/A/B/C/S + **L**(신규)
    ③ game_grade_resolution_tiers  등급×해상도 → spec_tiers.tier_key
    ④ game_grade_assignments       games 23행 → 등급 매핑(확정 22 · 미배정 1)

  원본 설계는 `docs/design/spec-tier-migration-plan-2026-09-14.md`(A-135
  1차 조사)다. DDL·값은 그 문서 §1(spec_tiers)·§2(game_load_grades 등)를
  그대로 옮기되, 이 파일에서 **L등급을 신설**한다(2026-09-15 사장님 확정) —
  원본 문서는 E/A/B/C/S 5등급만 다뤘고, 실제 게임 23종 조사(game-grades
  -2026-09-15.md · game-grades-round2-2026-09-15.md, 2차에 걸친 웹조사)에서
  6종(로스트아크·메이플스토리·던전앤파이터·GTA·로블록스·마인크래프트)이
  공식 사양은 확보했지만 E/A/B/C/S 어디에도 등급 정의상 맞지 않는다는 사실이
  드러났다 — "이 게임들이 성능을 안 요구한다"(사장님 확인)는 실측 근거
  (재고 rec_gpu가 GT430~RTX2060 저가~중가대에 몰림, GTA만 값 없음)로 L을
  신설해 묶는다. L은 T1(입문)에 매핑한다 — T0(GPU 하한 없음)보다 위인 이유는
  로스트아크(GTX1660S)·마인크래프트(2026-07 Mojang 공식 개정판 RTX2060)
  일부가 내장그래픽만으로는 실제로 부족하다는 재고 실측 때문이다(사장님 확정
  — "T0보단 약간 위인 T1").

■ 게임 매핑 22건 확정 근거 — 2회에 걸친 독립 웹조사
  1차(game-grades-2026-09-15.md): 22종(스팀인디 통칭 제외) 개별 웹검색,
  10종 확정(E4·A1·B2·C3). 2차(game-grades-round2-2026-09-15.md): 1차 불확실
  12종을 퍼블리셔 공식 문서·장르 전문 커뮤니티·서면 벤치마크로 재조사, 6종
  신규 확정(E2·A2·S2) — 총 16종이 E/A/B/C/S로 확정됐고, 나머지 6종은
  "공식 사양은 확보했으나 등급 정의 자체가 그 장르(MMORPG·2D 액션·샌드박스·
  버전 불명)를 다루지 않는다"는 구조적 이유로 L(경량 캐주얼)로 신설 배정한다.
  스팀 인디(game_id=23)는 특정 게임이 아니라 장르 통칭이라 애초에 조사 대상이
  아니었다 — 미배정(grade=NULL)으로 남긴다.

■ T0 GPU 슬롯 필수 한계 — 이미 해소됨(2026-09-15, b4180fd)
  원본 설계서(§1-5)는 "T0 실현에는 별도 엔진 변경이 필요하다"고 적었는데,
  같은 날 iGPU 슬롯 생략(`cpu_has_igpu`+`_igpu_gpu_omit`, api/recommend.py)이
  이미 구현·배포됐다 — GPU 성능 하한이 없는 용도(T0급)에서 CPU가 내장그래픽을
  가지면 GPU 슬롯을 실제로 생략한다. 이 마이그레이션은 그 엔진 변경에 기대어
  T0을 그대로 세운다(추가 엔진 작업 불필요).

■ T5 SSD 4TB 하한 — 재고 실측으로 위험 해소
  원본 설계서가 우려한 "3932GB 탈락" 문제는 실측 결과 **재고에 3932GB가
  없다**(4096GB만 14건) — ssd_min_gb=4000 그대로 채택.

■ downgrade — 4개 테이블 전부 drop(신규 테이블이라 원장 걱정 없음, 0016
  create_table과 같은 성격).

Revision ID: 0091
Revises: 0090
"""
import sqlalchemy as sa
from alembic import op

revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None


# ── ① spec_tiers ────────────────────────────────────────────────────────
SPEC_TIERS = [
    # tier_key, popcorn_name, label, gpu_vram_min_gb, gpu_watt_min, cpu_cores_min,
    # ram_min_gb, ssd_min_gb, sort_order, note
    ("T0", "팝콘3", "사무·웹", None, None, 6, 16, 512, 0,
     "원본 §2: 별도 그래픽카드 불필요. GPU 하한 NULL. iGPU 슬롯 생략(2026-09-15,"
     " b4180fd)으로 엔진 구현 완료."),
    ("T1", "팝콘5", "입문", 8, 550, 6, 16, 1000, 1,
     "원본 §2 RTX 5060/RX 9060 XT 8GB/Arc B580. gpu_watt_min=550W는 재고 실측"
     "(5060·9060XT 각 n=85,33, 550W 단일값). CPU·RAM은 원본 범위 하한값."),
    ("T2", "팝콘7", "주력", 12, 600, 8, 32, 1000, 2,
     "원본 §2 RTX 5060Ti16GB/RTX 5070 12GB/RX 9070. VRAM은 세 모델 중 최소값"
     "(5070 12GB). gpu_watt_min=600W는 5060 Ti 실측(n=139, 최저 전력 모델)."),
    ("T3", "팝콘7+", "고성능", 16, 750, 8, 32, 2000, 3,
     "원본 §2 RTX 5070Ti16GB/RX 9070XT16GB. gpu_watt_min=750W 두 모델 실측"
     " 일치(n=91,36). VRAM이 T4와 같아 gpu_watt_min이 실질 구분축."),
    ("T4", "팝콘9", "상급", 16, 850, 12, 64, 2000, 4,
     "원본 §2 RTX 5080 16GB. gpu_watt_min=850W 재고 실측 고정값(n=92)."),
    ("T5", "팝콘X", "워크스테이션", 32, 1000, 16, 128, 4000, 5,
     "원본 §2 RTX 5090 32GB(필요시 2장). gpu_watt_min=1000W 재고 실측 고정값"
     "(n=52). ssd_min_gb=4000 — 재고 실측 재확인(2026-09-15): 3932GB 없음,"
     " 4096GB만 14건이라 탈락 위험 없음."),
]

# ── ② game_load_grades — E/A/B/C/S(원본) + L(신규, 2026-09-15) ───────────
GAME_LOAD_GRADES = [
    # grade, label, example_titles, note, sort_order
    ("E", "경쟁 이스포츠",
     "발로란트, CS2, 리그 오브 레전드, 오버워치, 에이펙스",
     "기준: 60fps 이상·업스케일링 없음(원본 §3 머리말). 1080p 144fps+.", 1),
    ("A", "일반 AAA(래스터)",
     "어쌔신 크리드 섀도우스, 스파이더맨, 호라이즌",
     "VRAM 3단 계단의 기준 등급 — 1080p 8GB·1440p 12GB·4K 16GB(원본 §3).", 2),
    ("B", "RT 적용 AAA",
     "스타워즈 아웃로스, 몬스터헌터 와일즈",
     "4K는 업스케일링 사실상 필수(원본 §3).", 3),
    ("C", "패스트레이싱·UE5 극한",
     "사이버펑크 2077 RT 오버드라이브, 앨런 웨이크 2, 검은 신화: 오공, 아바타",
     "4K는 프레임 생성 없이 60fps 불가(원본 §3).", 4),
    ("S", "CPU 바운드 시뮬레이션",
     "MS 플라이트 시뮬레이터, 시티즈: 스카이라인 II, 대규모 전략·경영 시뮬",
     "GPU/CPU 비대칭(원본 §3): GPU는 T2급, CPU는 T4급.", 5),
    ("L", "경량 캐주얼",
     "메이플스토리, 로블록스, 로스트아크, 던전앤파이터, 마인크래프트(바닐라)",
     "2026-09-15 사장님 확정 신설 — E/A/B/C/S 등급 정의가 다루지 않는 장르"
     "(MMORPG·2D 액션·샌드박스)를 묶는다. \"해당 게임들은 높은 성능을 필요로"
     " 하지 않는다\"(사장님 확인). 2회 웹조사(game-grades-2026-09-15.md·"
     "game-grades-round2-2026-09-15.md)로 공식 사양은 확보했으나 5등급"
     " 어디에도 정의상 맞지 않는 6종을 근거로 신설.", 6),
]

# ── ③ game_grade_resolution_tiers — 등급×해상도 → spec_tiers ─────────────
GAME_GRADE_TIERS = [
    # grade, resolution, gpu_tier_key, cpu_tier_key_override, note
    ("E", "1080p", "T1", None, "144fps+ 목표(원본 §3)"),
    ("E", "1440p", "T1", None, "240fps 목표 시 T2로 올린다(개별 판단)"),
    ("E", "4K", "T2", None, None),
    ("A", "1080p", "T1", None, "VRAM 8GB(원본 §3)"),
    ("A", "1440p", "T2", None, "VRAM 12GB(원본 §3)"),
    ("A", "4K", "T3", None, "VRAM 16GB(원본 §3)"),
    ("B", "1080p", "T2", None, None),
    ("B", "1440p", "T3", None, None),
    ("B", "4K", "T4", None, "업스케일링 사실상 필수(원본 §3)"),
    ("C", "1080p", "T3", None, None),
    ("C", "1440p", "T4", None, None),
    ("C", "4K", "T5", None, "프레임 생성 없이는 60fps 불가(원본 §3)"),
    ("S", "1080p", "T2", "T4", "GPU T2급/CPU T4급 비대칭(원본 §3), 해상도 무관 동일 적용"),
    ("S", "1440p", "T2", "T4", "위와 동일"),
    ("S", "4K", "T2", "T4", "위와 동일"),
    # L(신규) — T1 고정, 해상도 구분 없음(경량 캐주얼은 해상도별 사양 분리가
    # 없다 — 2회 조사 전부 게임이 단일 권장사양만 공식 발표). CPU 비대칭 없음.
    ("L", "1080p", "T1", None,
     "2026-09-15 신설. T0보다 위인 이유: 로스트아크(GTX1660S)·마인크래프트"
     "(2026-07 Mojang 공식 개정 RTX2060)는 내장그래픽만으로 부족(사장님 확정"
     " \"T0보단 약간 위인 T1\")."),
    ("L", "1440p", "T1", None, "위와 동일 — 해상도별 공식 사양 분리 없음"),
    ("L", "4K", "T1", None, "위와 동일 — 해상도별 공식 사양 분리 없음"),
]

# ── ④ game_grade_assignments — games 23행 → 등급(확정 22 · 미배정 1) ─────
# game_id는 db/seed 시드 순서 기준(1~23). name으로도 재확인해 안전하게 UPDATE한다.
GAME_ASSIGNMENTS = [
    # (game_id, name, grade, is_confirmed, note)
    (1, "리그 오브 레전드", "E", True,
     "원본 §3 명시 + Riot 공식 사양 실측 일치(game-grades 1차)"),
    (2, "FC온라인", "E", True,
     "넥슨 공식 자료실 + 재고값 완전 일치(game-grades 2차 신규 확정)"),
    (3, "서든어택", "E", True,
     "Nexon 공식 권장사양 실측 일치(game-grades 1차)"),
    (4, "발로란트", "E", True,
     "원본 §3 명시 + Riot 공식 사양 목표fps 체계 일치(game-grades 1차)"),
    (5, "오버워치2", "E", True,
     "원본 §3 \"오버워치\" 시리즈 명시 + 이스포츠 경량 범주 재확인(game-grades 1차)"),
    (6, "로스트아크", "L", True,
     "5등급 정의 밖(MMORPG 쿼터뷰) — 2026-09-15 L등급 신설로 배정"
     "(game-grades-round2 §3 상세)"),
    (7, "메이플스토리", "L", True,
     "5등급 정의 밖(2D 액션) — 2026-09-15 L등급 신설로 배정"
     "(game-grades-round2 §3 상세, DB rec_gpu 신뢰성 의문 별도 기록됨)"),
    (8, "던전앤파이터", "L", True,
     "5등급 정의 밖(2.5D 액션) — 2026-09-15 L등급 신설로 배정"
     "(game-grades-round2 §3 상세, CPU 논란은 공식 사양으로 해소됨)"),
    (9, "디아블로4", "A", True,
     "Blizzard 공식 4단계 사양, 재고값이 Medium 등급과 정확히 일치"
     "(game-grades 2차 신규 확정)"),
    (10, "패스 오브 엑자일2", "S", True,
     "Steam+공식포럼 CPU 논란 해소, 엔드게임 CPU 바운드 커뮤니티 합의"
     "(game-grades 2차 신규 확정)"),
    (11, "배틀그라운드", "E", True,
     "PUBG 공식 문서 \"144fps 목표\" 문구 직접 확인(game-grades 2차 신규 확정)"),
    (12, "사이버펑크2077", "C", True,
     "원본 §3 \"RT 오버드라이브\" 명시 + 벤치마크 실측 정확히 일치(game-grades 1차)."
     " 단서: RT 끈 일반 옵션은 A/B급에 더 가까울 수 있음."),
    (13, "붉은사막", "B", True,
     "펄어비스 공식 사양·IGN 실측 리뷰·재고값 삼중 일치(game-grades 1차)"),
    (14, "몬스터헌터 와일즈", "B", True,
     "원본 §3 명시 + 재고값 부합(game-grades 1차)"),
    (15, "스텔라 블레이드", "A", True,
     "Steam+PlayStation 이중 공식 소스, RT 미사용 확인(game-grades 2차 신규 확정)"),
    (16, "검은신화 오공", "C", True,
     "원본 §3 명시 + Steam 공식·NVIDIA 자료 삼중 일치(game-grades 1차)"),
    (17, "GTA", None, False,
     "미배정 — 재고 rec_gpu 값 자체가 없고 게임명이 V/Enhanced/VI 중 어느"
     " 버전인지 특정 불가(game-grades-round2 §3 상세)"),
    (18, "콜 오브 듀티", "A", True,
     "Activision 공식 사양 VRAM 8GB 요구가 A등급 계단과 정확히 일치(game-grades 1차)"),
    (19, "아크 서바이벌", "C", True,
     "공식 사양(RTX3080/RX6800, RAM32GB) UE5 극한 패턴 부합(game-grades 1차)"),
    (20, "헬다이버즈2", "S", True,
     "Steam+PlayStation 공식 + Arrowhead CEO \"CPU 바운드\" 명시적 발언"
     "(game-grades 2차 신규 확정, 근거 강도 최상위)"),
    (21, "로블록스", "L", True,
     "5등급 정의 밖(샌드박스, 공식이 GPU 모델명 자체를 제시 안 함) — 2026-09-15"
     " L등급 신설로 배정(game-grades-round2 §3 상세)"),
    (22, "마인크래프트", "L", True,
     "5등급 정의 밖(샌드박스) — 2026-09-15 L등급 신설로 배정. 2026-07 Mojang"
     " 공식 개정 권장사양이 재고값과 정확히 일치(game-grades-round2 §3 상세)"),
    # 23(스팀 인디, 통칭)은 특정 게임이 아니라 조사 대상에서 원천 제외 — 행 자체를
    # 만들지 않는다(미배정 게임은 game_grade_assignments에 없으면 곧 미배정이다).
]


def upgrade() -> None:
    conn = op.get_bind()

    # ① spec_tiers
    op.create_table(
        "spec_tiers",
        sa.Column("tier_key", sa.String(4), primary_key=True),
        sa.Column("popcorn_name", sa.String(12), nullable=False, unique=True),
        sa.Column("label", sa.String(20), nullable=False),
        sa.Column("gpu_vram_min_gb", sa.Integer),
        sa.Column("gpu_watt_min", sa.Integer),
        sa.Column("cpu_cores_min", sa.Integer, nullable=False),
        sa.Column("ram_min_gb", sa.Integer, nullable=False),
        sa.Column("ssd_min_gb", sa.Integer, nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, unique=True),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "tier_key <> 'T0' OR (gpu_vram_min_gb IS NULL AND gpu_watt_min IS NULL)",
            name="ck_spec_tiers_t0_gpu_null"),
    )
    for row in SPEC_TIERS:
        conn.execute(sa.text(
            "INSERT INTO spec_tiers (tier_key, popcorn_name, label, gpu_vram_min_gb,"
            " gpu_watt_min, cpu_cores_min, ram_min_gb, ssd_min_gb, sort_order, note)"
            " VALUES (:tk, :pn, :lb, :gv, :gw, :cc, :rm, :sd, :so, :nt)"),
            {"tk": row[0], "pn": row[1], "lb": row[2], "gv": row[3], "gw": row[4],
             "cc": row[5], "rm": row[6], "sd": row[7], "so": row[8], "nt": row[9]})

    # ② game_load_grades
    op.create_table(
        "game_load_grades",
        sa.Column("grade", sa.String(1), primary_key=True),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("example_titles", sa.Text, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("sort_order", sa.Integer, nullable=False, unique=True),
    )
    for grade, label, examples, note, order in GAME_LOAD_GRADES:
        conn.execute(sa.text(
            "INSERT INTO game_load_grades (grade, label, example_titles, note, sort_order)"
            " VALUES (:g, :l, :e, :n, :o)"),
            {"g": grade, "l": label, "e": examples, "n": note, "o": order})

    # ③ game_grade_resolution_tiers
    op.create_table(
        "game_grade_resolution_tiers",
        sa.Column("grade", sa.String(1), sa.ForeignKey("game_load_grades.grade"), nullable=False),
        sa.Column("resolution", sa.String(6), nullable=False),
        sa.Column("gpu_tier_key", sa.String(4), sa.ForeignKey("spec_tiers.tier_key"), nullable=False),
        sa.Column("cpu_tier_key_override", sa.String(4), sa.ForeignKey("spec_tiers.tier_key")),
        sa.Column("note", sa.Text),
        sa.PrimaryKeyConstraint("grade", "resolution"),
    )
    for grade, res, gpu_tk, cpu_tk, note in GAME_GRADE_TIERS:
        conn.execute(sa.text(
            "INSERT INTO game_grade_resolution_tiers"
            " (grade, resolution, gpu_tier_key, cpu_tier_key_override, note)"
            " VALUES (:g, :r, :gt, :ct, :n)"),
            {"g": grade, "r": res, "gt": gpu_tk, "ct": cpu_tk, "n": note})

    # ④ game_grade_assignments
    op.create_table(
        "game_grade_assignments",
        sa.Column("game_id", sa.Integer, sa.ForeignKey("games.game_id"), primary_key=True),
        sa.Column("grade", sa.String(1), sa.ForeignKey("game_load_grades.grade")),
        sa.Column("is_confirmed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("note", sa.Text),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for game_id, name, grade, confirmed, note in GAME_ASSIGNMENTS:
        # name으로 game_id를 재확인 — 시드 순서가 어긋나면 엉뚱한 게임에 등급이 붙는
        # 사고가 나므로, 하드코딩한 game_id와 실제 이름이 일치하는지 대조 후 삽입한다.
        actual_id = conn.execute(sa.text(
            "SELECT game_id FROM games WHERE game_id = :gid AND name = :nm"),
            {"gid": game_id, "nm": name}).scalar()
        if actual_id is None:
            raise RuntimeError(
                f"games 테이블의 game_id={game_id}가 예상 이름 '{name}'과 다릅니다 — "
                "시드 순서가 바뀌었을 수 있습니다. 마이그레이션을 중단합니다.")
        conn.execute(sa.text(
            "INSERT INTO game_grade_assignments (game_id, grade, is_confirmed, note)"
            " VALUES (:gid, :g, :c, :n)"),
            {"gid": game_id, "g": grade, "c": confirmed, "n": note})


def downgrade() -> None:
    op.drop_table("game_grade_assignments")
    op.drop_table("game_grade_resolution_tiers")
    op.drop_table("game_load_grades")
    op.drop_table("spec_tiers")
