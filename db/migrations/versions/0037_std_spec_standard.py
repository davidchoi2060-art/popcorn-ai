# -*- coding: utf-8 -*-
"""조립 보증 사양 표준 — 코어 8부품 46항목을 `std.spec_defs` 에 세운다 (2026-08-10)

■ 정본
  `docs/design/build-compatibility-matrix-2026-08-10.md` (호환성 22쌍) 에서 역산한
  `docs/design/part-spec-standard-2026-08-10.md` (부품별 사양 표준).
  **코어 8부품 몫만** 넣는다 — 팬·확장카드·ODD 는 사용자 결정으로 다음 단계다.

■ 왜 마이그레이션인가 (시드가 아니라)
  빈 DB 에서 `alembic upgrade head` 만으로 **운영 규칙이 전부 서야 한다**(슬라이스 81).
  `db/seed/*.sql` 은 개발용 더미 전용이라 여기에 두면 새 서버에서 표준이 안 선다.

■ `required_for` 는 전부 비어 있다
  호환 사양은 NULL 불통과이고, 필수로 올리면 채워진 상품이 없어 추천 후보가 0이 된다.
  **채운 뒤 항목별로 따로 승격**한다(승격 전 드라이런으로 이탈 건수를 보여준다).

■ `is_blocking=false` 인 항목이 있다
  PCIe 세대는 **하위호환**이라 Gen4 SSD 를 Gen3 슬롯에 꽂아도 동작한다(느릴 뿐).
  막으면 멀쩡한 조합을 떨어뜨린다 — 조립 불가가 아니라 **성능 경고**로 다룬다.
  `capacity_gb`·`clock_mhz` 도 같은 이유로 정보 항목이다.

■ `fill_hint` 는 실측이다
  `products.spec_source_text`(99.7% 보유) 원문에서 그 값을 찾을 단서다.
  비율은 `part-spec-standard §4.1` 에서 전수로 쟀다. **단서가 있다는 것이지
  파싱에 성공한다는 뜻이 아니다** — 파서를 만든 뒤 드라이런으로 다시 잰다.
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

CORE = ["CPU", "MB", "RAM", "GPU", "SSD", "HDD", "POWER", "CASE",
        "COOLER_CPU_AIR", "COOLER_CPU_AIO"]
AIR, AIO = "COOLER_CPU_AIR", "COOLER_CPU_AIO"

# (키, 라벨, 형, 단위, 적용대상, 쌍, 막는가, 원문단서, 메모)
DEFS = [
    # ── 기존 항목의 개념 이관 (값은 아직 옮기지 않는다) ─────────────────────
    ("socket", "소켓", "TEXT", None, ["CPU", "MB"], "A1", True, "LGA|AM5|AM4",
     "가장 기본. 안 맞으면 물리적으로 안 꽂힌다"),
    ("socket_list", "지원 소켓 목록", "LIST", None, [AIR, AIO], "D1", True, "소켓",
     "쿨러는 소켓을 평균 5~6개 지원해 단일값으로는 표현할 수 없다"),
    ("chipset", "칩셋", "TEXT", None, ["MB"], "A2", True, "B650|B760|Z790|X670",
     "A2 — 같은 소켓이어도 칩셋이 그 CPU 세대를 지원하지 않을 수 있다"),
    ("mem_type", "메모리 규격", "TEXT", None, ["MB", "RAM"], "A4", True, "DDR4|DDR5",
     "DDR4 와 DDR5 는 물리적으로 호환되지 않는다"),
    ("tdp_watt", "설계 전력(TDP)", "INT", "W", ["CPU"], "D2", True, "TDP|설계전력",
     "쿨러 선정(D2)과 총전력 합산(C2) 양쪽에 쓰인다"),
    ("rated_watt", "정격 출력", "INT", "W", ["POWER"], "C1", True, "정격",
     "표기 출력이 아니라 정격이다 — 비정격 파워가 실재한다"),
    ("required_power_watt", "권장 전원 용량", "INT", "W", ["GPU"], "C1", True, "권장|정격",
     "제조사 권장값. 총전력 합산(C2)의 GPU 몫"),
    ("length_mm", "길이", "INT", "mm", ["GPU", "POWER"], "B1", True, "길이|mm",
     "GPU 는 카드 길이, POWER 는 파워 길이 — 둘 다 케이스가 수용 판정한다"),
    ("gpu_max_mm", "GPU 최대 길이", "INT", "mm", ["CASE"], "B1", True, "그래픽카드",
     "케이스가 받을 수 있는 카드 길이. 앞면 팬을 달면 줄어드는데 그건 표기에 없다"),
    ("cooler_height_mm", "쿨러 높이", "INT", "mm", ["CASE", AIR], "B3", True, "높이",
     "CASE 는 최대 허용, 쿨러는 실제 높이"),
    ("cooler_tdp", "쿨러 냉각 성능", "INT", "W", [AIR, AIO], "D2", True, "TDP",
     "채움률이 낮아 규칙이 있어도 대부분 탈락한다 — 다나와에도 없는 값이다"),
    ("radiator_rows", "라디에이터 열 수", "INT", None, [AIO], "B4", True, "240|360|280",
     "120mm 팬 기준 열 수"),
    ("radiator_max_rows", "라디에이터 최대 열 수", "INT", None, ["CASE"], "B4", True, "라디에이터",
     None),
    ("form_factor", "폼팩터", "TEXT", None, ["MB", "SSD", "HDD", "POWER"], "A9", True,
     "ATX|m-ATX|ITX|SFX|M.2", "MB 는 보드 규격, POWER 는 ATX/SFX, 저장장치는 M.2 2280 등"),
    ("form_factor_list", "수용 보드 규격", "LIST", None, ["CASE"], "A9", True, "ATX",
     None),
    ("interface", "인터페이스", "TEXT", None, ["SSD", "HDD"], "A8", True, "NVMe|SATA",
     "A8 — NVMe 는 M.2 슬롯이, SATA 는 SATA 포트가 있어야 한다"),
    ("capacity_gb", "용량", "INT", "GB", ["RAM", "SSD", "HDD"], None, False, "GB|TB",
     "정보 항목 — 조립을 막지 않는다"),
    ("clock_mhz", "동작 클럭", "INT", "MHz", ["RAM"], "A6", False, "MHz",
     "보드 지원 상한을 넘으면 다운클럭된다 — 조립은 되므로 막지 않고 알린다"),
    ("pcie_gen", "PCIe 세대", "INT", None, ["GPU", "SSD"], "A7", False, "PCIe",
     "하위호환이라 막지 않는다. Gen4 를 Gen3 에 꽂으면 느릴 뿐 동작한다"),
    ("size_inch", "크기", "NUM", "inch", ["HDD"], "B6", True, "3.5|2.5",
     "케이스 베이 판정"),
    # ── 신설: CPU ─────────────────────────────────────────────────────────
    ("mem_type_support", "지원 메모리 규격", "LIST", None, ["CPU"], "A4", True, "DDR4|DDR5",
     "AM5 는 DDR5 만 받는다 — 보드뿐 아니라 CPU 도 메모리 컨트롤러를 갖는다"),
    ("igpu_yn", "내장그래픽", "BOOL", None, ["CPU"], None, False, "내장",
     "GPU 슬롯 생략 판정. 지금은 내장그래픽 CPU 에도 GPU 를 반드시 붙인다(원문 단서 85%)"),
    ("cpu_generation", "CPU 세대", "TEXT", None, ["CPU"], "A2", True, "레이크|Zen|라파엘",
     "소켓만으로는 세대를 알 수 없어 칩셋 지원 판정(A2)이 불가능하다(단서 62%)"),
    # ── 신설: 메인보드 (호환성의 허브) ─────────────────────────────────────
    ("supported_cpu_gens", "지원 CPU 세대", "LIST", None, ["MB"], "A2", True, None,
     "칩셋만으로는 부족하다 — 실제 지원 목록이 필요하다"),
    ("bios_min_version", "세대별 최소 BIOS", "LIST", None, ["MB"], "A3", True, None,
     "소켓·칩셋이 맞아도 BIOS 가 낮으면 부팅하지 않는다. 실무에서 가장 흔한 사고이고 "
     "저쪽에도 없다 — 우리가 만들어야 할 표준이다"),
    ("mem_slots", "메모리 슬롯 수", "INT", "개", ["MB"], "A5", True, "슬롯 :",
     "4모듈 세트를 2슬롯 보드에 꽂을 수 없다(원문 단서 81%)"),
    ("mem_max_gb", "최대 메모리 용량", "INT", "GB", ["MB"], "A5", True, "최대 ",
     "단서 79%"),
    ("mem_max_clock_mhz", "지원 최대 클럭", "INT", "MHz", ["MB"], "A6", False, "MHz",
     "초과하면 다운클럭 — 막지 않고 알린다"),
    ("pcie_x16_gen", "x16 슬롯 세대", "INT", None, ["MB"], "A7", False, "PCIe",
     "단서 16% — 대부분 사람이 넣어야 한다"),
    ("m2_slots", "M.2 슬롯 수", "INT", "개", ["MB"], "A8", True, "M.2 :",
     "**지금 SSD 호환 규칙이 0개다.** NVMe 를 M.2 없는 보드와 묶어도 통과한다(단서 84%)"),
    ("m2_form_factors", "M.2 지원 규격", "LIST", None, ["MB"], "A8", True, "2280|22110",
     None),
    ("sata_ports", "SATA 포트 수", "INT", "개", ["MB"], "A8", True, "SATA3 :",
     "단서 80%"),
    ("m2_sata_shared", "M.2/SATA 레인 공유", "TEXT", None, ["MB"], "A8", False, None,
     "M.2 를 쓰면 특정 SATA 포트가 죽는 보드가 흔하다. 규칙이 아니라 경고 문구로 쓴다"),
    ("eps_connectors", "EPS 12V 커넥터", "INT", "개", ["MB", "POWER"], "C4", True, "EPS",
     "MB 는 필요 개수, POWER 는 제공 개수 — 규칙은 제공 >= 필요. 원문 단서 0%"),
    # ── 신설: 메모리 ──────────────────────────────────────────────────────
    ("module_count", "모듈 개수", "INT", "개", ["RAM"], "A5", True, "x2|2개",
     "슬롯 수와 대조한다. 원문 단서 1% — 사람이 넣어야 한다"),
    ("height_mm", "높이", "INT", "mm", ["RAM", "GPU"], "D3", True, "높이",
     "RAM 은 쿨러 간섭(D3), GPU 는 케이스 여유(B2). 둘 다 '이 부품의 높이'라 한 항목이다"),
    # ── 신설: 그래픽카드 ──────────────────────────────────────────────────
    ("thickness_slots", "두께(슬롯)", "NUM", "슬롯", ["GPU"], "B2", True, None,
     "3슬롯 카드는 아래 PCIe 슬롯을 물리적으로 막는다. 원문 단서 0%"),
    ("aux_power_req", "요구 보조전원", "LIST", None, ["GPU"], "C3", True, "핀",
     "8pin x N 또는 12V-2x6. RTX 50 계열은 12V-2x6 이다. 단서 3%"),
    # ── 신설: 파워 ────────────────────────────────────────────────────────
    ("aux_power_provided", "제공 보조전원", "LIST", None, ["POWER"], "C3", True, "PCI",
     "C3 의 짝. 단서 33%"),
    ("sata_connectors", "SATA 전원 커넥터", "INT", "개", ["POWER"], None, True, "SATA",
     "저장장치 개수 대응. 단서 62%"),
    # ── 신설: 케이스 ──────────────────────────────────────────────────────
    ("gpu_max_slots", "GPU 최대 두께", "NUM", "슬롯", ["CASE"], "B2", True, None,
     "원문 단서 0%"),
    ("psu_form_factor_list", "수용 파워 규격", "LIST", None, ["CASE"], "B5", True, "파워",
     "SFX 케이스에 ATX 파워는 물리적으로 안 들어간다(단서 88%)"),
    ("psu_max_mm", "파워 최대 길이", "INT", "mm", ["CASE"], "B5", True, "파워 ",
     "단서 88%"),
    ("bay_35_count", "3.5\" 베이 수", "INT", "개", ["CASE"], "B6", True, "3.5",
     "단서 65%"),
    ("bay_25_count", "2.5\" 베이 수", "INT", "개", ["CASE"], "B6", True, "2.5",
     "단서 54%"),
    # ── 신설: CPU 쿨러 ────────────────────────────────────────────────────
    ("ram_clearance_mm", "램 방향 여유", "INT", "mm", [AIR], "D3", True, "높이",
     "PCPartPicker 도 못 한다고 밝히는 항목이다. 단서 80% 지만 그 '높이'가 쿨러 자체 "
     "높이일 수 있어 파싱 검증이 필요하다"),
]


def upgrade():
    conn = op.get_bind()
    for i, (key, label, dt, unit, parts, pair, blocking, hint, note) in enumerate(DEFS, start=1):
        bad = [p for p in parts if p not in CORE]
        if bad:
            raise RuntimeError(f"[0037] 코어 8부품 밖의 적용 대상: {key} -> {bad}")
        conn.execute(sa.text(
            "INSERT INTO std.spec_defs"
            " (field_key, label, data_type, unit, part_types, required_for,"
            "  compat_pair, is_blocking, fill_hint, note, sort_order)"
            " VALUES (:k, :l, :t, :u, CAST(:p AS JSONB), CAST('[]' AS JSONB),"
            "         :c, :b, :h, :n, :s)"
            " ON CONFLICT (field_key) DO NOTHING"),
            {"k": key, "l": label, "t": dt, "u": unit,
             "p": json.dumps(parts, ensure_ascii=False),
             "c": pair, "b": blocking, "h": hint, "n": note, "s": i * 10})


def downgrade():
    op.get_bind().execute(sa.text(
        "DELETE FROM std.spec_defs WHERE field_key = ANY(:ks)"),
        {"ks": [d[0] for d in DEFS]})
