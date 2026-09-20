"""0095: T0(사무·웹) CPU 코어 하한 6 -> 4 — 저가 구성이 죽던 원인 제거

■ 무엇이 고장나 있었나 (2026-09-17 실측)

사장님이 화면을 보고 지적하셨다: "단순질문에 선택지를 너무 넓혀서 알려준다".
실측해 보니 화면 문제가 아니라 **격자 데이터가 틀린 것**이었다.

  고객이 말한 예산: 700,000원 (사무·인강)
  화면이 내민 것:   9개 구성이 «전부» 예산 초과, 최저 858,400 ~ 최고 4,651,900원

사무용 PC 에 465만원을 내밀고 있었다.

■ 원인 — T0 의 CPU 6코어 하한이 저가 티어를 통째로 죽였다

엔진을 조건별로 갈라 돌려 범인을 좁혔다(모두 사무·인강 70만원):

    스펙하한 없음          value=346,200  reco=699,900  high=1,049,900   정상
    T0 하한 전체 적용       value=None     reco=None     high=752,000     깨짐
    cpu_cores_min=4       value=346,200  reco=699,900  high=1,049,900   정상
    cpu_cores_min=6       value=None     reco=None     high=1,049,900   깨짐  <<<

**정확히 6코어에서 끊어진다.** 이유는 iGPU 와의 조합이다:

    4코어 이상 + iGPU 보유 CPU  최저 102,000원 (라이젠3 3200G)
    6코어 이상 + iGPU 보유 CPU  최저 215,300원 (라이젠5 5600G)   <<< 2.1배

사무·인강은 GPU 하한이 없어 iGPU 생략(2026-09-15, b4180fd)이 켜진다. 그래서
CPU 는 반드시 iGPU 를 가진 것이어야 하는데, 6코어를 요구하는 순간 그 최저가가
21.5만원이 된다. 여기에 usage_alloc(office) 의 CPU 배분 20~40% 가 겹치면:

    215,300원이 총액의 40% 이하이려면 -> 총액 538,250원 이상이어야 한다
    그런데 가성비(value)는 «조건 안 최저가»가 정의라 총액을 낮추려 한다
    -> 서로 모순 -> 조합 없음 -> null

가성비·추천이 죽으면 격자에는 고성능 계열만 남는다. 그것이 «85만~1,719만원»의
정체이고, 70만원 고객에게 465만원이 나간 경로다.

■ 무엇을 바꾸나

`spec_tiers.cpu_cores_min` T0: **6 -> 4**. 사장님 확정(2026-09-17):
"사무·웹은 4코어면 충분하고, iGPU 포함 10만원대 CPU 가 열려 저가 구성이 살아난다".

■ 다른 용도에 미치는 영향 — 실측으로 확인했다

T0 는 사무·인강 전용이 아니라 **6개 용도가 공유**한다(grid_cells T0 12칸):
사무·인강 · 주식·트레이딩 · 디자인 · 영상편집 · 3D 그래픽 · AI 작업.

그래서 «4코어 CPU 가 영상편집·3D·AI 구성에 들어가 저사양이 되지 않는가»를 확인했다.
결론: 되지 않는다. 그 셋은 **용도 하한이 따로 막는다**(2026-09-17 실측):

    영상편집    GPU>=600W · RAM>=32GB · SSD>=2000GB
    3D 그래픽   GPU>=850W · RAM>=64GB · SSD>=2000GB
    AI 작업     GPU>=650W · RAM>=32GB · SSD>=1000GB

GPU 하한이 있으면 iGPU 생략이 꺼지고(allow_igpu_omit 조건), 그 예산대에서는
4코어 저가 CPU 가 선택될 여지가 없다. 또 **CPU 코어 하한을 가진 용도는 하나도 없다** —
즉 이 값이 유일한 CPU 축이었고, 그것이 사무용에 과했던 것이다.

새로 열리는 후보: 4~5코어 CPU **8종**.

■ 되돌리기

downgrade 는 6 으로 되돌린다. 값 하나뿐이라 데이터 손실은 없다.

■ ⚠ 적용 후 반드시 할 일

`tools/grid_generate.py` 를 다시 돌려야 격자 카드가 새 하한으로 다시 지어진다.
이 마이그레이션은 **기준만** 바꾼다 — 이미 배치된 grid_quotes 는 옛 하한으로
만들어진 값이라 그대로 두면 화면은 어제와 같은 것을 보여준다.

Revision ID: 0095
Revises: 0094
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0095"
down_revision = "0094"
branch_labels = None
depends_on = None


# 왜 이 값인가 — 근거를 코드 옆에 둔다(문서만 고치면 다음 사람이 못 믿는다).
_NOTE_NEW = (
    "원본 §2: 별도 그래픽카드 불필요. GPU 하한 NULL. iGPU 슬롯 생략(2026-09-15, b4180fd)으로 "
    "엔진 구현 완료. cpu_cores_min 은 2026-09-17 에 6->4 로 내렸다(0095) — 6코어를 요구하면 "
    "iGPU 보유 CPU 최저가가 102,000원에서 215,300원으로 뛰고, usage_alloc(office) CPU 20~40% 와 "
    "모순돼 가성비·추천 티어가 통째로 사라졌다(70만원 사무 요청에 465만원 구성이 나간 원인). "
    "사장님 확정: 사무·웹은 4코어로 충분하다."
)


def upgrade():
    conn = op.get_bind()

    # 현재 값이 6 일 때만 내린다 — 이미 다른 값이면 사람이 손댄 것이므로 덮지 않는다
    # (§원장 규약: 모르는 과거를 지어내지 않는다와 같은 정신).
    cur = conn.execute(
        sa.text("SELECT cpu_cores_min FROM spec_tiers WHERE tier_key='T0'")
    ).scalar()
    if cur is None:
        raise RuntimeError("spec_tiers T0 행이 없다 - 0091 이 적용되지 않았다")
    if cur != 6:
        # 값이 이미 다르면 note 만 남기고 값은 건드리지 않는다.
        conn.execute(
            sa.text(
                "UPDATE spec_tiers SET note = note || ' / 0095 적용 시점 cpu_cores_min="
                + str(cur)
                + " 였다 - 값을 바꾸지 않았다.' WHERE tier_key='T0'"
            )
        )
        return

    conn.execute(
        sa.text("UPDATE spec_tiers SET cpu_cores_min=4, note=:n WHERE tier_key='T0'"),
        {"n": _NOTE_NEW},
    )


def downgrade():
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE spec_tiers SET cpu_cores_min=6, "
            "note='원본 §2: 별도 그래픽카드 불필요. GPU 하한 NULL. iGPU 슬롯 생략(2026-09-15, b4180fd)으로 엔진 구현 완료.' "
            "WHERE tier_key='T0'"
        )
    )
