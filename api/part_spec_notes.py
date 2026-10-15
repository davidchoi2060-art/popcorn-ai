"""고객 공개 구성(BOM) 상세에 «읽을 때» 덧붙이는 사양 두 줄 — 영상 출력 · 파워 판정 기준.

■ 왜 저장 행이 아니라 읽을 때인가
  승인된 부품 설명(`product_explanations.content`)은 공개 PC 가 해시(`explanation_digest`)로 고정한다.
  내용을 고치면 공개된 PC 가 전부 「근거 변경」으로 닫힌다. 그래서 승인본은 건드리지 않고, 승인 당시
  판매처 원문(`source_snapshot.spec` — 공개 판정이 지금 원문과 같음을 이미 확인한 값)과 서버 값에서만
  파생한다. 지어낸 값은 없다: 원문에 없으면 「확인 필요」라고 적는다.

■ 영상 출력 (오픈테스트 C01-F01)
  메인보드 상세에 HDMI·DP·D-SUB 정보가 없어 「HDMI 모니터 두 대」 고객이 확인할 길이 없었다.
  · 승인 사실에 이미 「영상 출력」이 있으면 덧붙이지 않는다.
  · 검수자가 주의 문구로 영상 출력 확정을 보류했으면(113685: 판매처 DVI 표기와 제조사 rev.1.0 불일치)
    원문을 다시 꺼내지 않고 그 주의 문구를 그대로 보인다 — 사람이 뺀 값을 파생으로 되살리지 않는다.
  · 보드 단자는 CPU 내장그래픽이 있어야 쓴다. 같은 구성의 CPU 가 「내장그래픽 없음」이면 그 사실을 함께 적는다.
  · 단자 «개수»는 보드 원문에 없어 적지 않는다(그래픽카드는 원문에 개수가 있어 적는다).

■ 파워 판정 기준 (오픈테스트 C06-F04)
  그래픽카드 상세의 「권장 파워 정격 650(W) 이상」은 판매처 원문(시스템 권장 등급값)이고, 호환 규칙은
  2026-09-17 결정(마이그레이션 0094)대로 `정격 >= 카드 소비전력(gpu_power_draw_watt) + ref_offset` 을 본다.
  그래서 600W 파워가 규칙을 통과한 것은 설계대로다. 다만 화면이 그 차이를 말하지 않았다 —
  장착 파워가 «판매처 권장 + 100W»(상담과 같은 여유 기준, 2026-10-15 사장님 확정)보다 낮을 때 판정 기준을
  서버 값(소비전력·규칙 여유)으로 밝힌다.
"""
import re

from .power_rule import PSU_ADVICE_MARGIN_W

PORTS = {'HDMI': 'HDMI', 'DP': 'DP', 'DISPLAYPORT': 'DP', 'D-SUB': 'D-SUB', 'DSUB': 'D-SUB', 'DVI': 'DVI'}
GPU_PORT = re.compile(r'출력단자\((HDMI|DP|DVI|D-SUB)\)\s*:\s*(\d+)\s*\(EA\)', re.I)
OUTPUT_LABEL = '영상 출력'
POWER_LABEL = '파워 판정 기준'
POWER_SLOTS = ('POWER', 'PSU')


def _port(token):
    return PORTS.get(re.sub(r'\s+', '', token or '').upper())


def board_ports(spec):
    """판매처 보드 원문의 영상 단자(원문 순서, 중복 제거). 「DVI : DP」처럼 키·값 둘 다 단자명인 칸은 값을 쓴다."""
    found = []
    for token in (spec or '').split('/'):
        token = token.strip()
        port = _port(token)
        if port is None and ':' in token:
            key, value = (x.strip() for x in token.split(':', 1))
            port = _port(value) if _port(key) else None
        if port and port not in found:
            found.append(port)
    return found


def gpu_ports(spec):
    out = []
    for kind, count in GPU_PORT.findall(spec or ''):
        label = PORTS[kind.upper()] + ' ' + str(int(count)) + '개'
        if label not in out:
            out.append(label)
    return out


def _facts(row):
    content = row.get('content') if isinstance(row.get('content'), dict) else {}
    facts = content.get('facts') if isinstance(content.get('facts'), list) else []
    return {f['label']: f['value'] for f in facts
            if isinstance(f, dict) and isinstance(f.get('label'), str) and isinstance(f.get('value'), str)}


def _slot(row):
    content = row.get('content') if isinstance(row.get('content'), dict) else {}
    return content.get('slot') or row.get('slot')


def _watt(value):
    m = re.search(r'([\d,]+)\s*\(?W\)?', value or '')
    return int(m[1].replace(',', '')) if m and m[1].replace(',', '') else None


def _has_output_fact(facts):
    return any(OUTPUT_LABEL in label for label in facts)


def _output_caution(row):
    content = row.get('content') if isinstance(row.get('content'), dict) else {}
    cautions = content.get('cautions') if isinstance(content.get('cautions'), list) else []
    return next((c for c in cautions if isinstance(c, str) and OUTPUT_LABEL in c), None)


def output_spec(row, cpu_without_igpu=False):
    """메인보드·그래픽카드 줄의 영상 출력 한 줄. 덧붙일 것이 없으면 None."""
    slot, facts = _slot(row), _facts(row)
    if slot not in ('MB', 'GPU') or _has_output_fact(facts):
        return None
    caution = _output_caution(row)
    if caution:
        return dict(label=OUTPUT_LABEL, value='확인 필요 · ' + caution)
    spec = row.get('source_spec') or ''
    if slot == 'GPU':
        ports = gpu_ports(spec)
        return dict(label=OUTPUT_LABEL, value=(' · '.join(ports) + ' (판매처 표기)') if ports
                    else '판매처 표기 없음 · 확인 필요')
    ports = board_ports(spec)
    if not ports:
        return dict(label=OUTPUT_LABEL, value='판매처 표기 없음 · 확인 필요')
    tail = ('이 구성의 CPU는 내장그래픽이 없어 보드 단자로는 화면이 나오지 않아요' if cpu_without_igpu
            else 'CPU 내장그래픽 필요 · 판매처 표기')
    return dict(label=OUTPUT_LABEL, value=' · '.join(ports) + ' (' + tail + ')')


def power_spec(gpu_row, psu_row, offset):
    """장착 파워가 «판매처 권장 + 100W»(PSU_ADVICE_MARGIN_W)보다 낮을 때만 판정 기준 한 줄. 아니면 None.

    offset 은 활성 파워 규칙(rule_key='power', ref_field='gpu_power_draw_watt')의 ref_offset — 없으면 None.
    여유 기준은 상담 판정과 같은 「권장값 + 100W」다(2026-10-15 사장님 확정). 조립 호환은 규칙 값으로 따로 밝힌다.
    """
    recommended = _watt(_facts(gpu_row).get('권장 파워'))
    rated = _watt(_facts(psu_row).get('정격 출력'))
    if not recommended or not rated:
        return None
    safe = recommended + PSU_ADVICE_MARGIN_W
    if rated >= safe:
        return None
    head = (f'장착 파워 {rated}W는 판매처 권장 {recommended}W보다 낮아요. ' if rated < recommended
            else f'장착 파워 {rated}W는 판매처 권장 {recommended}W는 넘지만 여유 기준 {safe}W(권장 + {PSU_ADVICE_MARGIN_W}W)보다 낮아요. ')
    tail = f'여유 있게 쓰시려면 {safe}W 이상 파워로 바꿔 주세요.'
    draw = gpu_row.get('gpu_power_draw_watt')
    if type(draw) is not int or draw <= 0 or type(offset) is not int:
        return dict(label=POWER_LABEL, value=head + '그래픽카드 소비전력 자료가 없어 파워 호환을 확정하지 못했어요. 구매 전 확인이 필요해요.')
    need = draw + offset
    if rated < need:
        return dict(label=POWER_LABEL, value=head + f'호환 기준 {need}W에도 못 미쳐 구성 확인이 필요해요.')
    return dict(label=POWER_LABEL, value=head + f'조립 호환은 그래픽카드 소비전력 {draw}W + 시스템 여유 {offset}W = {need}W 기준으로 통과했어요. ' + tail)


def derived_specs(rows, offset=None):
    """{ordinal: 행} -> {ordinal: [덧붙일 사양]}. 행은 content·slot·source_spec·gpu_power_draw_watt 를 가진다."""
    by_slot = {}
    for ordinal, row in rows.items():
        by_slot.setdefault(_slot(row), []).append(ordinal)
    no_igpu = any(_facts(rows[o]).get('내장그래픽', '').strip() == '없음' for o in by_slot.get('CPU', []))
    out = {}
    for ordinal, row in rows.items():
        spec = output_spec(row, no_igpu)
        if spec:
            out.setdefault(ordinal, []).append(spec)
    gpus = by_slot.get('GPU', [])
    psus = [o for s in POWER_SLOTS for o in by_slot.get(s, [])]
    if len(gpus) == 1 and len(psus) == 1:
        spec = power_spec(rows[gpus[0]], rows[psus[0]], offset)
        if spec:
            out.setdefault(gpus[0], []).append(spec)
    return out
