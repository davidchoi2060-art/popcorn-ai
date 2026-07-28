"""빈 DB로 시작해도 엔진이 규칙을 갖게 한다 — 부트스트랩 시드 (슬라이스 81).

발단: "아무 데이터도 없는 상태에서 운영자는 뭐부터 해야 하는가"를 처음부터 짚다가,
**빈 상태에서 출발하는 길이 검증된 적이 없다**는 것을 알았다. `alembic upgrade head`만
돌린 DB는 이랬다.

    spec_field_defs   29   ✓ 0014가 넣는다
    usage_floors      21   ✓ 0016이 넣는다
    compat_rules       0   ✗ 0005는 **테이블만** 만든다
    pricing_settings   0   ✗ 어디에도 없다
    ops_settings       0   ✗ 어디에도 없다

호환 규칙이 없으면 엔진은 실패하지 않는다 — **조용히 전부 통과시킨다.**
`load_compat_rules`가 빈 dict를 돌려주고 `_slot_ok`는 "규칙 없는 슬롯은 독립"으로 판정한다.
소켓이 안 맞는 CPU와 보드, 케이스에 안 들어가는 그래픽카드가 견적으로 나가고
아무도 경고를 못 본다. "조립 불가능한 PC는 우리에게선 안 나온다"가 그 순간 거짓말이 된다.

지금까지 이 값들은 `db/seed/seed*.sql`에만 있었고, 그 파일들은 **더미 상품·주문·회원을
함께 싣는 개발 시드**다. 실제로 문을 여는 사람은 그걸 돌릴 수 없다(가짜 주문이 원장에 남는다).
그래서 운영에 필요한 최소값만 마이그레이션으로 옮긴다 — spec_field_defs·usage_floors가
이미 그렇게 하는 것과 같은 이유다. 서버를 다시 세우거나 백업에서 복구해도 규칙은 따라온다.

**더미 데이터는 넣지 않는다.** 상품·주문·회원·공급처는 운영자가 만든다.

재실행 안전: 전부 '없을 때만' 넣는다. 이미 값이 있는 DB에서는 한 행도 바뀌지 않는다.

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


# 조립 호환 규칙 8종 — **운영 DB의 현재 정의를 그대로** 옮긴다(2026-07-29 실측).
# ref_slot은 탐색 순서(CPU→MB→RAM→GPU→CASE→COOLER→POWER→SSD)에서 slot보다 앞이어야 한다.
# 어기면 load_compat_rules가 그 규칙을 건너뛰고 경고만 남긴다.
#
# `db/seed/seed_0013`을 베끼지 않았다 — 그 파일은 낡았다. 쿨러 소켓이 아직 `socket`/`eq`인데
# 실제 엔진은 슬라이스 39부터 `socket_list`/`contains`를 쓴다(쿨러는 소켓을 평균 5~6개
# 지원해 단일값 비교로 표현할 수 없다). 시드를 그대로 옮겼다면 새로 세운 서버에서
# **모든 쿨러가 탈락**해 견적이 한 건도 안 나왔을 것이다.
RULES = [
    ("socket", "MB", "socket", "eq", "CPU", "socket",
     "CPU 소켓 규격 일치", "{r} = {v}", 10),
    ("mem", "RAM", "mem_type", "eq", "MB", "mem_type",
     "메모리 규격 일치", "{v} = {r}", 20),
    ("gpu_len", "CASE", "gpu_max_mm", "gte", "GPU", "length_mm",
     "그래픽카드 장착 길이", "GPU {r}mm ≤ 케이스 {v}mm", 30),
    # 케이스는 규격을 여러 개 지원한다(실측 3개 1,110건) — 단일값이 아니라 목록 비교.
    ("case_board", "CASE", "form_factor_list", "contains", "MB", "form_factor",
     "메인보드 규격 수용", "{r} 지원", 35),
    ("cooler_socket", "COOLER", "socket_list", "contains", "CPU", "socket",
     "쿨러 소켓 지원", "{r} 지원", 40),
    ("cooler_tdp", "COOLER", "cooler_tdp", "gte", "CPU", "tdp_watt",
     "쿨러 발열(TDP) 통과", "{v}W ≥ {r}W", 50),
    ("cooler_height", "COOLER", "cooler_height_mm", "lte", "CASE", "cooler_height_mm",
     "쿨러 높이 여유", "쿨러 {v}mm ≤ 케이스 {r}mm", 60),
    ("power", "POWER", "rated_watt", "gte", "GPU", "required_power_watt",
     "전원 용량 여유", "{v}W ≥ 권장 {r}W", 70),
]

# 운영 전환 기본값 — 1단계 프리셋(회원만 자체, 나머지는 쇼핑몰 인계).
# 가장 보수적인 출발점이다. 운영자가 '시스템 > 운영 전환 설정'에서 단계를 올린다.
OPS = [("member", "own"), ("pay", "mall"), ("settle", "mall"),
       ("ship", "mall"), ("refund", "mall")]


def upgrade() -> None:
    conn = op.get_bind()

    for r in RULES:
        conn.exec_driver_sql(
            "INSERT INTO compat_rules (rule_key, slot, field, op, ref_slot, ref_field,"
            " label, detail_fmt, sort_order)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (rule_key) DO NOTHING", r)

    for k, m in OPS:
        conn.exec_driver_sql(
            "INSERT INTO ops_settings (key, mode) VALUES (%s, %s)"
            " ON CONFLICT (key) DO NOTHING", (k, m))

    # 가격 정책 — 유니크 키가 없으므로 '한 행도 없을 때만' 넣는다.
    # 마진 0%는 **의도한 기본값**이다. 운영자가 '가격·매입 > 마진 정책'에서 정하기 전까지
    # 시스템이 이익률을 지어내지 않는다. 카드수수료 2.2%도 예시값 — 실요율로 바꿔야 한다.
    # 화면이 이 사실을 먼저 말한다(마진 0%면 판매가 = 매입가 + 수수료).
    conn.exec_driver_sql(
        "INSERT INTO pricing_settings (card_fee_rate, margin_rate, effective_from)"
        " SELECT 0.0220, 0, now()"
        " WHERE NOT EXISTS (SELECT 1 FROM pricing_settings)")


def downgrade() -> None:
    """넣은 것만 되돌린다 — 운영자가 나중에 고친 값은 건드리지 않는다.

    가격 정책은 지우지 않는다. 판매가 산정의 근거였던 행을 없애면
    이미 산정된 가격이 어떤 정책에서 나왔는지 설명할 수 없다.
    """
    conn = op.get_bind()
    keys = tuple(r[0] for r in RULES)
    conn.exec_driver_sql("DELETE FROM compat_rules WHERE rule_key IN %s", (keys,))
    conn.exec_driver_sql("DELETE FROM ops_settings WHERE key IN %s",
                         (tuple(k for k, _ in OPS),))
