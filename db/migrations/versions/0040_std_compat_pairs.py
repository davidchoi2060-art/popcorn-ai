# -*- coding: utf-8 -*-
"""호환성 관계 22쌍을 정본으로 옮긴다 — `std.compat_pairs` (2026-08-11)

■ 왜 필요한가
  관계 번호(A1~F5)는 지금까지 **설계 문서와 조감도 HTML에만** 있었다.
  `std.spec_defs.compat_pairs` 는 번호만 들고 있고 **그 번호가 무슨 관계인지는 어디에도
  데이터로 없다.** 화면을 만들려면 화면이 그걸 지어내거나 하드코딩해야 하는데,
  둘 다 이 리포가 오래 앓은 병이다(선택지 하드코딩 · 화면이 숫자를 지어냄).

■ `compat_rules`(public)와의 관계
  `compat_rules` 9행이 **엔진이 실제로 검사하는 것**이고, 여기 22행은
  **검사해야 하는 것 전부**다. 둘은 `rule_key` 로 잇는다 —
  `rule_key` 가 채워진 쌍은 「검사 중」, 비어 있으면 「아직 안 함」이다.
  **public 은 건드리지 않는다**(P-08). 참조만 한다.

■ 범위 밖도 넣는다
  E1(모니터)·F1~F5(팬·확장카드·ODD)는 지금 다루지 않기로 했지만
  **행은 만든다.** 빠뜨린 것과 미룬 것은 다르고, 화면이 그 차이를 보여야 한다.
  `in_scope=false` 로 구분한다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

# (번호, 그룹, 왼쪽, 오른쪽, 무엇을 비교, 규칙키, 범위 안, 메모)
PAIRS = [
    ("A1", "A", "CPU", "MB", "소켓 규격이 같은가", "socket", True, None),
    ("A2", "A", "CPU", "MB", "칩셋이 그 CPU 세대를 지원하는가", None, True,
     "보드의 지원 세대 목록이 아직 비어 있다"),
    ("A3", "A", "CPU", "MB", "BIOS 버전이 그 CPU를 받는가", None, True,
     "막지 않고 경고한다 — 보드의 현재 BIOS 는 출고 시점마다 달라 알 수 없다(0039)"),
    ("A4", "A", "RAM", "MB", "메모리 규격(DDR4/DDR5)", "mem", True, None),
    ("A5", "A", "RAM", "MB", "모듈 개수 ≤ 슬롯 수 · 최대 용량", None, True, None),
    ("A6", "A", "RAM", "MB", "램 클럭 ≤ 보드 지원 상한", None, True,
     "초과해도 조립은 된다(다운클럭) — 경고 축"),
    ("A7", "A", "GPU", "MB", "PCIe 세대", None, True,
     "하위호환이라 막지 않는다. 느릴 뿐 동작한다"),
    ("A8", "A", "SSD", "MB", "NVMe면 M.2 슬롯, SATA면 포트가 있는가", None, True,
     "SSD 는 견적 슬롯인데 지금 호환 규칙이 0개다"),
    ("A9", "A", "MB", "CASE", "보드 규격(ATX/mATX/ITX) 수용", "case_board", True, None),
    ("B1", "B", "GPU", "CASE", "카드 길이 ≤ 케이스 허용", "gpu_len", True, None),
    ("B2", "B", "GPU", "CASE", "카드 두께(슬롯) · 높이", None, True,
     "양쪽 다 값이 0% — 케이스 최대 높이는 2026-08-11 에 신설했다"),
    ("B3", "B", "COOLER_CPU_AIR", "CASE", "쿨러 높이 ≤ 케이스 허용", "cooler_height", True, None),
    ("B4", "B", "COOLER_CPU_AIO", "CASE", "라디에이터 열 수 · 두께", "radiator", True,
     "두께는 2026-08-11 에 신설했다 — 상단 장착 시 보드·램과 간섭한다"),
    ("B5", "B", "POWER", "CASE", "파워 규격(ATX/SFX) · 길이", None, True, None),
    ("B6", "B", "HDD", "CASE", "3.5\" / 2.5\" 베이가 남는가", None, True, None),
    ("C1", "C", "POWER", "GPU", "정격 출력 ≥ GPU 권장 전원", "power", True, None),
    ("C2", "C", "POWER", "구성 전체", "CPU + GPU + 여유 20~30%", None, True,
     "사양이 아니라 **규칙 상수**로 푼다. 부품마다 소비전력을 받으면 못 채울 항목이 는다"),
    ("C3", "C", "POWER", "GPU", "보조전원 커넥터(8핀 · 12V-2x6)", None, True, None),
    ("C4", "C", "POWER", "MB", "EPS 12V 커넥터 개수", None, True, None),
    ("D1", "D", "COOLER_CPU_AIR", "CPU", "지원 소켓 목록에 그 소켓이 있는가", "cooler_socket", True, None),
    ("D2", "D", "COOLER_CPU_AIR", "CPU", "냉각 성능(W) ≥ CPU 발열(TDP)", "cooler_tdp", True,
     "규칙은 있는데 값이 없어 상당수가 자동 탈락한다"),
    ("D3", "D", "COOLER_CPU_AIR", "RAM", "램 방향 여유 ≥ 램 높이", None, True,
     "PCPartPicker 도 못 한다고 밝히는 항목이다"),
    # ── 지금 범위 밖 (빠뜨린 것이 아니라 미룬 것이다) ───────────────────────
    ("E1", "E", "GPU", "MONITOR", "출력 포트가 목표 해상도·주사율을 내는가", None, False,
     "주변기기 사양이 사실상 비어 있어 판정 불가"),
    ("F1", "F", "FAN", "CASE", "팬 크기·두께 vs 케이스 장착 위치", None, False,
     "분류가 없어 ETC 에 묻혀 있다 — 재고 194종"),
    ("F2", "F", "FAN", "MB", "팬 커넥터 vs 보드 팬 헤더 수", None, False, None),
    ("F3", "F", "EXPANSION", "MB", "요구 슬롯(PCIe x1/x4/x16) vs 여유 슬롯", None, False,
     "재고 84종"),
    ("F4", "F", "EXPANSION", "GPU", "3슬롯 두께 GPU 가 아래 PCIe 를 막는다", None, False,
     "둘 다 파는데 이걸 안 보면 «둘 다 샀는데 하나는 못 꽂는» 일이 난다"),
    ("F5", "F", "ODD", "CASE", "5.25\" 베이 · SATA 포트", None, False, "재고 10종"),
]

GROUPS = [
    ("A", "메인보드 중심", "논리·전기 — 거의 모든 관계가 보드로 모인다"),
    ("B", "물리 공간", "케이스가 담을 수 있는가"),
    ("C", "전력", "파워가 감당하는가"),
    ("D", "냉각·간섭", "열을 식히고 서로 부딪히지 않는가"),
    ("E", "출력", "화면으로 나가는가"),
    ("F", "선택 부품", "팬·확장카드·ODD — 분류부터 필요하다"),
]


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS std.compat_groups (
            group_key   VARCHAR(2)  PRIMARY KEY,
            label       VARCHAR(40) NOT NULL,
            note        TEXT,
            sort_order  INTEGER     NOT NULL DEFAULT 0
        )"""))
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS std.compat_pairs (
            pair_key    VARCHAR(4)  PRIMARY KEY,
            group_key   VARCHAR(2)  NOT NULL REFERENCES std.compat_groups(group_key),
            left_part   VARCHAR(20) NOT NULL,
            right_part  VARCHAR(20) NOT NULL,
            compares    TEXT        NOT NULL,
            rule_key    VARCHAR(40),
            in_scope    BOOLEAN     NOT NULL DEFAULT true,
            note        TEXT,
            sort_order  INTEGER     NOT NULL DEFAULT 0
        )"""))
    conn.execute(sa.text(
        "COMMENT ON COLUMN std.compat_pairs.rule_key IS "
        "'public.compat_rules 의 rule_key. 채워져 있으면 엔진이 실제로 검사한다. "
        "FK 를 걸지 않는 이유: public 을 건드리지 않는다(P-08)'"))
    conn.execute(sa.text(
        "COMMENT ON COLUMN std.compat_pairs.in_scope IS "
        "'false = 지금 다루지 않기로 한 것. 빠뜨린 것과 미룬 것은 다르다'"))

    for i, (k, l, n) in enumerate(GROUPS, start=1):
        conn.execute(sa.text(
            "INSERT INTO std.compat_groups (group_key, label, note, sort_order)"
            " VALUES (:k, :l, :n, :s) ON CONFLICT (group_key) DO NOTHING"),
            {"k": k, "l": l, "n": n, "s": i * 10})
    for i, (pk, gk, lp, rp, cmp_, rk, scope, note) in enumerate(PAIRS, start=1):
        conn.execute(sa.text(
            "INSERT INTO std.compat_pairs"
            " (pair_key, group_key, left_part, right_part, compares, rule_key,"
            "  in_scope, note, sort_order)"
            " VALUES (:p, :g, :l, :r, :c, :rk, :s, :n, :o)"
            " ON CONFLICT (pair_key) DO NOTHING"),
            {"p": pk, "g": gk, "l": lp, "r": rp, "c": cmp_, "rk": rk,
             "s": scope, "n": note, "o": i * 10})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS std.compat_pairs"))
    conn.execute(sa.text("DROP TABLE IF EXISTS std.compat_groups"))
