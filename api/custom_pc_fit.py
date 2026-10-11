"""신규 조립PC 용도 평가 — 부품 사양으로 여는 평가 입구 (2026-10-11 부품 상품화 5단계).

몰 조립PC 의 용도 평가(0115 · `tools/product_fit.py`)는 몰 상품의 «부품명»에서 CPU·그래픽카드·
메모리·저장장치를 읽어 단계를 매긴다. 신규 조립PC 는 몰 상품번호가 없어 그 표에 없지만, 구성표의
부품명이 있으므로 **같은 판독 함수와 같은 기준표**로 평가한다(판정을 두 벌 두지 않는다).

■ 「정보 없음」 (2026-10-10 중헌 님 「사양 몰라도 구매 지장 없음 · 데이터 없으면 정보 없음」)
  표에 없는 칩·용량을 못 읽은 부품처럼 «몰라서» 못 넘은 조건만 남으면 판정은 unknown 이고,
  카드에는 「정보 없음」으로 둔다. 공개를 막지 않는다. 분명히 모자란 조건이 하나라도 있으면 short 다.
"""
from tools.product_fit import REQUIREMENTS, check, evaluate, find_cpu, find_gpu, ram_gb, ssd_gb

NO_INFO = '정보 없음'
GPU_ABSENT = ('외장 그래픽 없음', '엔비디아 그래픽 아님')


def _total(parts, slot, reader):
    rows = [p for p in parts if p['slot'] == slot]
    if not rows:
        return None
    values = [reader(p['name']) for p in rows]
    if any(v is None for v in values):
        return None
    return sum(v * p['quantity'] for v, p in zip(values, rows))


def spec_from_parts(parts):
    """구성표 부품 [{slot, name, quantity}] -> tools.product_fit 판정 입력. gpu_part 는 판독 못 한 그래픽카드 표시."""
    cpu_name = next((p['name'] for p in parts if p['slot'] == 'CPU'), None)
    gpu_name = next((p['name'] for p in parts if p['slot'] == 'GPU'), None)
    cpu = find_cpu(cpu_name)
    gpu = find_gpu(gpu_name) if gpu_name else (find_gpu(cpu_name) if cpu_name else None)
    return dict(cpu=cpu, gpu=gpu, ram=_total(parts, 'RAM', ram_gb), ssd=_total(parts, 'SSD', ssd_gb),
                gpu_part=bool(gpu_name))


def _unknown(miss, sp):
    return '미확인' in miss or (sp['gpu_part'] and sp['gpu'] is None and miss in GPU_ABSENT)


def judge(sp, usage, level):
    """그 용도의 그 단계를 넘는가: fit · unknown(정보 없음) · short."""
    step = next((s for s in REQUIREMENTS.get(usage, []) if s[0] == level), None)
    if step is None:
        return 'unknown'
    miss = check(sp, step[2])
    if not miss:
        return 'fit'
    return 'unknown' if all(_unknown(m, sp) for m in miss) else 'short'


def reached(sp, usage):
    """그 용도에서 넘은 가장 높은 단계 이름, 없으면 None."""
    return evaluate(sp).get(usage, (None, []))[0]
