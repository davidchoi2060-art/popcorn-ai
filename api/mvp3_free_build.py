"""MVP3 부품 직접 고르기 — 고객이 말한 부품 조건으로 PC 한 대를 채우고, 나머지는 고객이 바꾼다
(2026-10-16 중헌 님 「메모리 32기가, RTX 5060ti, CPU는 i9 시리즈 … 그대로 부품카테고리에 반영하고
나머지를 고를 수 있도록 … 그리고 장바구니에 넣을 수 있도록」).

■ 무엇을 하나
  start    고객 말(text) 또는 정리된 조건(conditions)을 받아, 조건에 맞는 부품을 그 자리에 넣고 비어 있는
           자리는 호환되는 판매 부품 중 싼 것부터 채운다. 처음부터 «다 채워진 PC 한 대»로 돌려준다.
  options  한 자리를 바꿀 수 있는 판매 부품 — 나머지 구성과 호환 규칙을 모두 통과한 것만.
  quote    고객이 고른 구성을 지금 판매가로 다시 계산하고 호환을 다시 판정한다(보관·상담 신청이 같은 계산을 쓴다).

■ 가격 노출 (사장님 지시 — 부품별 가격·마진 금지)
  고객에게는 «PC 총액»과 «바꿀 때 생기는 차액»만 준다. 줄마다 판매가를 싣지 않는다.
  총액 = 부품 판매가(`products.sale_price`) × 수량의 합 + 조립비(`api/orders.ASSEMBLY_FEE`) — `api/custom_pc` 와 같은 규칙.

■ 호환  `api/build_check.evaluate`(관리자 조립·고객 부품 바꾸기와 같은 판정). 실패는 물론, 판정하지 못한 것(unknown)도
         통과로 세지 않는다 — 엔진도 넘기는 skip 규칙(`mvp3_build.settled`)만 예외다.
         일부러 비운 자리(내장 그래픽을 쓰는 PC 의 그래픽카드 · 호환을 확인할 쿨러가 없을 때의 쿨러)는 그 자리 때문에
         판정하지 못한 규칙을 막지 않고, 쿨러는 `warnings` 로 알린다(`mvp3_build.WARNING_TEXT` 와 같은 뜻).
■ 후보  `mvp3_build.CANDIDATE_SQL`(판매중 · 판매가 > 0 · 실데이터 · 검수 대기 아님)과 같은 거름 + 노트북·서버용 메모리,
         저장장치가 아닌 상품 제외(`mvp3_build.not_desktop_ram` · `not_storage`).
■ 장바구니  몰 상품번호가 있는 한 대가 아니라 부품 묶음이라 몰 장바구니에 넣지 않는다. 「구매 상담 신청」
         (`api/mvp3_purchase_inquiry`, `free_build`)이 이 구성을 다시 계산해 신청에 붙인다. 주문·결제는 하지 않는다.
■ 읽기만 한다.
"""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text

from . import mvp3_quantity as QTY
from .build_check import evaluate, load_rules, load_specs
from .catalog_map import has_used_mark
from .db import engine
from .mvp3_build import CANDIDATE_SQL, not_desktop_ram, not_storage, settled, touches
from .orders import ASSEMBLY_FEE
from .product_name import display_name
from .taxonomy import QUOTE_SLOTS, SLOT_LABELS, slot_of

router = APIRouter(prefix='/api/mvp3', tags=['mvp3'])

# 채우는 순서 — 앞 자리가 뒤 자리의 호환을 정한다(소켓 → 메모리 세대 → 그래픽카드 → 케이스 → 쿨러 → 파워 전력).
ORDER = ('CPU', 'MB', 'RAM', 'GPU', 'CASE', 'COOLER', 'SSD', 'POWER')
KEY = {s: i for i, s in enumerate(ORDER)}
REQUIRED = ('CPU', 'MB', 'RAM', 'SSD', 'POWER', 'CASE')
OPTIONAL = ('GPU', 'COOLER')
PER_SLOT = 12            # 자리마다 호환을 통과한 것 중 싼 것부터 이만큼만 다음 자리로 넘긴다(같은 이름은 하나로)
NODE_CAP = 4000          # 채우기 탐색에서 판정하는 횟수 상한 — 넘으면 «채우지 못함»으로 끝낸다
OPTIONS_CHEAPER, OPTIONS_PRICIER = 6, 10
DEFAULT_RAM_GB = 16      # 고객이 메모리를 말하지 않았을 때
DEFAULT_SSD_GB = 500     # 고객이 저장장치를 말하지 않았을 때(이상)
MAX_STICKS_UNCHECKED = 2  # 메인보드 슬롯 수를 모를 때 꽂는 모듈 수 상한
WARNING_COOLER = '이 구성에 맞는 CPU 쿨러를 호환 자료로 확인하지 못해 쿨러는 비워 두었어요. 상담에서 맞춰 드려요.'
NOTE = ('호환 규칙을 통과한 판매 중 부품만 넣었어요. 금액은 PC 총액이고, 부품을 바꾸면 차액만 보여 드려요. '
        '몰 장바구니가 아니라 「이 구성으로 구매 상담 신청」으로 주문을 도와드려요.')
PARTS_SQL = """SELECT p.product_code, p.product_name, p.sale_price, p.status, p.part_type, p.spec_source_text, p.maker
                 FROM products p JOIN product_specs s ON s.product_code = p.product_code
                WHERE p.product_code = ANY(:codes) AND p.data_origin = 'real' AND NOT p.review_required_yn"""
# 후보 거름은 mvp3_build 와 같고, 여기서 더 읽는 열(status · maker)만 붙인다 — _usable 이 status 를 본다.
CANDIDATES_SQL = CANDIDATE_SQL.replace('p.spec_source_text', 'p.spec_source_text, p.maker, p.status', 1)
assert 'p.status' in CANDIDATES_SQL and 'p.maker' in CANDIDATES_SQL


# ── 조건 ────────────────────────────────────────────────────────────────
class Conditions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cpu: str | None = Field(default=None, max_length=40)       # 'i9' · 'i7-14700K' · '라이젠 7' · '7800X3D' · '울트라 7'
    gpu: str | None = Field(default=None, max_length=40)       # 'RTX 5060 Ti' · 'RX 9070 XT'
    ram_gb: StrictInt | None = Field(default=None, ge=4, le=256)
    ssd_gb: StrictInt | None = Field(default=None, ge=120, le=16000)
    platform: Literal['인텔', 'AMD'] | None = None


GPU_RX = re.compile(r'(RTX|RTS|GTX|RX|ARC)?\s*-?\s*([A-Z]?\d{3,4})\s*(TI\s*SUPER|TI|SUPER|XTX|XT|GRE|슈퍼|티아이)?(?![A-Z0-9])')
GPU_BARE_RX = re.compile(r'(?<![0-9])([2-5]0[5-9]0)\s*(TI|SUPER|슈퍼|티아이)?(?![0-9A-Z])')
SUFFIX = {'슈퍼': 'SUPER', '티아이': 'TI', 'TISUPER': 'TI SUPER'}


def _suffix(s):
    s = re.sub(r'\s+', '', (s or '').upper())
    s = SUFFIX.get(s, s)
    return 'TI SUPER' if s == 'TISUPER' else s


def gpu_model(s):
    """'RTX 5060 Ti' -> ('5060', 'TI'). 알아보지 못하면 None. RTS 는 RTX 오타로 읽는다."""
    u = (s or '').upper()
    for m in GPU_RX.finditer(u):
        if m[1]:
            return m[2], _suffix(m[3])
    m = GPU_BARE_RX.search(u)
    return (m[1], _suffix(m[2])) if m else None


def gpu_matches(name, want):
    u = (name or '').upper()
    for m in GPU_RX.finditer(u):
        if m[1] and m[1] != 'RTS' and m[2] == want[0] and _suffix(m[3]) == want[1]:
            return True
    return False


_CPU_NEXT_PART = (r'(?:RAM|SSD|HDD|CPU|GPU|DDR[345]|RTX|GTX|RX|ARC|NVIDIA|GEFORCE|RADEON|'
                  r'POWER|PSU|CASE|COOLER|MB|MOTHERBOARD)(?=\d|[^A-Za-z0-9]|$)')


def _cpu_model_spacing(s):
    """모델 숫자와 ASCII 접미사 사이 공백만 접는다. 뒤의 한국어 설명은 건드리지 않는다."""
    def join(match):
        if re.match(_CPU_NEXT_PART, match[2], re.I):
            return match[0]       # RAM/SSD/RTX 등 다음 부품절을 CPU 접미사로 붙이지 않는다.
        return match[1] + match[2]
    return re.sub(r'(?<![A-Za-z0-9])([GNJ]?\d{3,5})\s+([A-Za-z][A-Za-z0-9]*)(?![A-Za-z0-9])',
                  join, s, flags=re.I)


def cpu_rule(s):
    """CPU 조건 글을 판정 함수로 바꾼다. 알아보지 못하면 None(지어내지 않는다)."""
    u = _cpu_model_spacing(s or '').upper()
    series = re.search(r'(?<![A-Z0-9])I\s*([3579])(?![0-9])', u)
    ultra = re.search(r'(ULTRA|울트라)\s*([579])(?![0-9])', u)
    ryzen = re.search(r'(RYZEN|라이젠)\s*([3579])(?![0-9])', u)
    intel = bool(series or ultra or INTEL_RX.search(u))
    amd = bool(ryzen or AMD_RX.search(u))
    if intel and amd:
        return None
    brand = (re.compile(INTEL_RX.pattern + r'|(?<![A-Z0-9])I\s*[3579](?![0-9])|ULTRA|울트라', re.I)
             if intel else AMD_RX if amd else None)
    series_pat = None
    if series:
        series_pat = re.compile(r'(?<![A-Z0-9])I\s*' + series[1] + r'(?![0-9])')
    if ultra:
        series_pat = re.compile(r'(ULTRA|울트라)\s*' + ultra[2] + r'(?![0-9])')
    if ryzen:
        series_pat = re.compile(r'(RYZEN|라이젠)\s*' + ryzen[2] + r'(?![0-9])')
    model = re.search(r'(?<![A-Z0-9])([GNJ]?\d{4,5}[A-Z0-9]*|\d{3}[A-Z0-9]*)(?![A-Z0-9])', u)
    model_pat = None
    if model:
        token = model[1]
        valid = re.fullmatch(r'([GNJ]?\d{4,5}|\d{3})(X3D|KF|KS|GE|HX|HS|K|F|X|G|T|U|H|V)?', token)
        if not valid or (len(valid[1]) == 3 and not ultra and not valid[2]):
            return None          # 모르는 접미사를 자르거나 모델 조건을 시리즈로 낮추지 않는다.
        model_pat = re.compile(r'(?<![A-Z0-9])' + re.escape(token) + r'(?![A-Z0-9])')
    elif re.search(r'\d{3,5}', u) or series_pat is None:
        return None

    def matches(name):
        name = (name or '').upper()
        return bool((brand is None or brand.search(name))
                    and (series_pat is None or series_pat.search(name))
                    and (model_pat is None or model_pat.search(name)))
    return matches


INTEL_RX = re.compile(r'INTEL|인텔|코어|CORE', re.I)
AMD_RX = re.compile(r'AMD|라이젠|RYZEN', re.I)


def platform_of(row):
    words = ' '.join(str(row.get(k) or '') for k in ('maker', 'product_name'))
    if AMD_RX.search(words):
        return 'AMD'
    if INTEL_RX.search(words):
        return '인텔'
    return None


def _gb(num, unit):
    n = float(num)
    return int(round(n * 1000)) if unit.upper() in ('TB', 'T', '테라') else int(round(n))


def parse_text(s):
    """고객 말에서 부품 조건만 읽는다. 읽은 것만 채우고, 읽지 못한 것은 조건으로 만들지 않는다."""
    u = (s or '')
    out = {}
    ram = (re.search(r'(?:메모리|램|RAM|DDR[45])\s*(?:DDR[45])?\s*(\d{1,3})\s*(?:GB|G|기가)', u, re.I)
           or re.search(r'(\d{1,3})\s*(?:GB|G|기가)\s*(?:짜리\s*)?(?:메모리|램|RAM)', u, re.I))
    if ram and 4 <= int(ram[1]) <= 256:
        out['ram_gb'] = int(ram[1])
    ssd = (re.search(r'(?:SSD|저장\s*장치|저장|용량)\s*(\d+(?:\.\d+)?)\s*(TB|테라|T|GB|기가|G)(?![A-Z])', u, re.I)
           or re.search(r'(\d+(?:\.\d+)?)\s*(TB|테라|GB|기가)\s*(?:짜리\s*)?(?:SSD|저장)', u, re.I)
           or re.search(r'(\d+(?:\.\d+)?)\s*(TB|테라)(?![A-Z])', u, re.I))
    if ssd and 120 <= _gb(ssd[1], ssd[2]) <= 16000:
        out['ssd_gb'] = _gb(ssd[1], ssd[2])
    gpu = gpu_model(u)
    if gpu:
        out['gpu'] = ('RTX ' if gpu[0][0] in '2345' and len(gpu[0]) == 4 else '') + gpu[0] + (' ' + gpu[1] if gpu[1] else '')
        m = re.search(r'(RTX|RTS|GTX|RX|ARC)\s*-?\s*' + gpu[0], u, re.I)
        if m:
            family = 'RTX' if m[1].upper() == 'RTS' else m[1].upper()
            out['gpu'] = family + ' ' + gpu[0] + (' ' + gpu[1] if gpu[1] else '')
    cpu_tail = r'[A-Za-z0-9]*(?:\s+(?!' + _CPU_NEXT_PART + r')[A-Za-z][A-Za-z0-9]*)?'
    cpu = (re.search(r'(?<![A-Za-z0-9])i\s*[3579](?:\s*-?\s*\d{4,5}' + cpu_tail + r')?', u, re.I)
           or re.search(r'(?:울트라|ultra)\s*[579](?:\s*-?\s*\d{3}' + cpu_tail + r')?', u, re.I)
           or re.search(r'(?:라이젠|ryzen)\s*[3579](?:\s*-?\s*\d{4}' + cpu_tail + r')?', u, re.I)
           or re.search(r'(?<![0-9])\d{4,5}\s*(?:X3D|KF|KS|K)(?![0-9A-Za-z])', u, re.I)
           or re.search(r'(?<![0-9])\d{3}\s*(?:KF|K|F|HX|H|U|V)(?![0-9A-Za-z])', u, re.I))
    if cpu:
        out['cpu'] = re.sub(r'\s+', ' ', _cpu_model_spacing(cpu[0])).strip()
    if 'cpu' not in out:
        if re.search(r'인텔|intel', u, re.I):
            out['platform'] = '인텔'
        elif re.search(r'(?<![A-Za-z])AMD(?![A-Za-z])|라이젠|ryzen', u, re.I):
            out['platform'] = 'AMD'
    return Conditions(**out)


def condition_view(cond):
    """화면이 보여 줄 «받은 조건» 줄. 원문 값을 그대로 쓴다."""
    out = []
    if cond.cpu: out.append(dict(slot='CPU', label='CPU', value=cond.cpu))
    if cond.platform and not cond.cpu: out.append(dict(slot='CPU', label='CPU', value=cond.platform))
    if cond.gpu: out.append(dict(slot='GPU', label='그래픽카드', value=cond.gpu))
    if cond.ram_gb: out.append(dict(slot='RAM', label='메모리', value=f'{cond.ram_gb}GB'))
    if cond.ssd_gb: out.append(dict(slot='SSD', label='SSD',
                                    value=(f'{cond.ssd_gb / 1000:g}TB' if cond.ssd_gb >= 1000 else f'{cond.ssd_gb}GB')))
    return out


# ── 후보 ────────────────────────────────────────────────────────────────
def _usable(r):
    # 중고·리퍼 표시가 있는 상품은 새 PC 에 넣지 않는다(사장님 2026-08-16 「중고 부품은 견적에서 빼둔다」) —
    # 개발 서버에서 「[중고]」 파워가 가장 싸다는 이유로 들어갔다(2026-10-17).
    return (r['status'] == '판매중' and type(r['sale_price']) is int and r['sale_price'] > 0
            and slot_of(r['part_type'] or '') in ORDER and not not_desktop_ram(r) and not not_storage(r)
            and not has_used_mark(r['product_name'], r.get('spec_source_text') or ''))


def ram_cap(row, spec):
    return QTY.ram_unit(spec, row.get('spec_source_text'), row.get('product_name'))


def ssd_cap(spec):
    v = (spec or {}).get('capacity_gb')
    return v if type(v) is int and v > 0 else None


def _uniq(items):
    seen, out = set(), []
    for it in sorted(items, key=lambda x: (x['cost'], x['product_code'], x['quantity'])):
        k = (it['name'], it['quantity'])
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


def slot_candidates(rows, specs, cond, slot):
    """한 자리의 후보 [{product_code, quantity, cost, name, row}] — 조건이 걸린 자리는 조건에 맞는 것만."""
    want_cpu = cpu_rule(cond.cpu) if slot == 'CPU' and cond.cpu else None
    want_gpu = gpu_model(cond.gpu) if slot == 'GPU' and cond.gpu else None
    out = []
    for r in rows:
        if slot_of(r['part_type'] or '') != slot or not _usable(r):
            continue
        name = display_name(r['product_name'])
        if slot == 'CPU':
            if want_cpu and not want_cpu(r['product_name']):
                continue
            if cond.platform and not cond.cpu and platform_of(r) != cond.platform:
                continue
        if slot == 'GPU' and want_gpu and not gpu_matches(r['product_name'], want_gpu):
            continue
        if slot == 'RAM':
            modules, cap = ram_cap(r, specs.get(r['product_code']))
            if not cap:
                continue
            target = cond.ram_gb or DEFAULT_RAM_GB
            for qty in (1, 2):
                if cap * qty == target:
                    out.append(dict(product_code=r['product_code'], quantity=qty, cost=r['sale_price'] * qty,
                                    name=name, row=r, modules=modules * qty, gb=cap * qty))
            continue
        if slot == 'SSD':
            cap = ssd_cap(specs.get(r['product_code']))
            if cap is None:
                continue
            if cond.ssd_gb and not (cond.ssd_gb * 0.9 <= cap <= cond.ssd_gb * 1.1):
                continue
            if not cond.ssd_gb and cap < DEFAULT_SSD_GB:
                continue
        out.append(dict(product_code=r['product_code'], quantity=1, cost=r['sale_price'], name=name, row=r))
    return _uniq(out)


# ── 판정 ────────────────────────────────────────────────────────────────
def lines_of(picks):
    return [dict(key=KEY[s], slot=s, spec_key=p['product_code'], label=str(p['product_code']))
            for s, p in picks.items() if p is not None]


def ram_fits(picks, specs):
    """꽂는 메모리 모듈 수 · 합계 용량이 메인보드가 받는 만큼인가. 모르면 모듈 2개까지만 받는다."""
    ram, mb = picks.get('RAM'), picks.get('MB')
    if ram is None or mb is None:
        return True
    b = QTY.board(specs.get(mb['product_code']), mb['row'].get('spec_source_text'))
    sticks = ram.get('modules') or ram['quantity']
    if b['mem_slots'] is None:
        if sticks > MAX_STICKS_UNCHECKED:
            return False
    elif sticks > b['mem_slots']:
        return False
    return b['mem_max_gb'] is None or not ram.get('gb') or ram['gb'] <= b['mem_max_gb']


def storage_refusal(picks, specs):
    """SSD를 늘릴 때 메인보드의 M.2/SATA 수를 지킨다. 지원 정보를 모르면 늘리지 않는다."""
    lines = [dict(ordinal=KEY[s], slot=s, product_code=p['product_code'], quantity=p['quantity'], name=p['name'])
             for s, p in picks.items() if p is not None]
    raws = {p['product_code']: p['row'].get('spec_source_text') for p in picks.values() if p is not None}
    usage = QTY.usage(lines, specs, raws)
    raised = {KEY[s]: p['quantity'] for s, p in picks.items()
              if s == 'SSD' and p is not None and p['quantity'] > 1}
    return QTY.refusal(usage, raised)


def blocking(checks, keys, empty, by_key):
    """받아들일 수 없는 판정. keys = 이번에 본 줄 번호, empty = 아직 고르지 않았거나 일부러 비운 자리."""
    bad = []
    for c in checks:
        mine = touches(c, keys) or (':' not in c['key'])
        if not mine:
            continue
        if c['state'] == 'fail':
            bad.append(c)
            continue
        if c['state'] != 'unknown' or settled(c, by_key):
            continue
        missing = set(c.get('missing_slots') or [])
        if missing and missing <= empty:
            continue           # 그 자리를 아직 안 골랐거나 일부러 비웠다 — 그 자리를 고를 때 다시 본다
        bad.append(c)
    return bad


def judge(picks, specs, rules, keys, final=False):
    """picks 에 대해 keys 줄이 만든 문제. final 이면 구성 전체(화면 출력 포함)를 보고, 일부러 비운 자리만 비어 있다고 본다."""
    empty = {s for s in (OPTIONAL if final else ORDER) if picks.get(s) is None}
    out = evaluate(lines_of(picks), specs, rules, display=final)
    by_key = {r['rule_key']: r for r in rules}
    return blocking(out['checks'], keys, empty, by_key), out


def fill(cands, specs, rules, gpu_optional=False):
    """자리마다 싼 것부터, 앞 자리와 호환되는 첫 조합을 찾는다(깊이 우선 · 판정 NODE_CAP 회까지).

    찾으면 (picks, 막힌 횟수), 못 찾으면 (None, 막힌 횟수).
    """
    budget = [NODE_CAP]
    stuck = {}
    reasons = {}      # (자리, 규칙 이름, fail|unknown) -> 횟수 — 못 채웠을 때 무엇에 막혔는지 알린다

    def step(i, picks):
        if i == len(ORDER):
            bad, _ = judge(picks, specs, rules, list(KEY.values()), final=True)
            return picks if not bad else None
        slot = ORDER[i]
        # 싼 것부터 보되, 막힌 후보는 PER_SLOT 에 세지 않는다 — 싼 파워 12개가 그래픽카드 전력에 모두 모자라
        # 그래픽카드를 지정한 요청이 전부 「못 채움」이던 것(2026-10-17 개발 서버). 판정 횟수는 NODE_CAP 이 묶는다.
        options = cands.get(slot, [])
        if slot == 'GPU' and gpu_optional:
            options = [None] + options      # 내장 그래픽을 쓰는 PC 를 먼저 본다(그래픽카드를 말하지 않았다)
        elif slot == 'COOLER':
            options = options + [None]      # 맞는 쿨러를 못 찾으면 비우고 알린다
        tried = 0
        for o in options:
            if budget[0] <= 0:
                return None
            if o is not None and tried >= PER_SLOT:
                continue                    # 비우는 선택지(None)는 상한과 무관하게 본다
            trial = dict(picks, **{slot: o})
            if o is not None:
                budget[0] -= 1
                bad, _ = judge(trial, specs, rules, [KEY[slot]])
                if bad or (slot in ('RAM', 'MB') and not ram_fits(trial, specs)):
                    stuck[slot] = stuck.get(slot, 0) + 1
                    for c in bad or [dict(label='메모리 슬롯·용량', state='fail')]:
                        why = (slot, c['label'], c['state'])
                        reasons[why] = reasons.get(why, 0) + 1
                    continue
            elif slot == 'GPU':
                cpu = trial.get('CPU')
                if cpu is None or (specs.get(cpu['product_code']) or {}).get('cpu_gpu') is not True:
                    continue
            tried += 1
            got = step(i + 1, trial)
            if got is not None:
                return got
        return None

    picks = step(0, {})
    return picks, dict(stuck=stuck, exhausted=budget[0] <= 0,
                       reasons=[dict(slot=k[0], rule=k[1], state=k[2], count=n)
                                for k, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:5]])


# ── 결과 ────────────────────────────────────────────────────────────────
def total_of(picks):
    return sum(p['row']['sale_price'] * p['quantity'] for p in picks.values() if p is not None) + ASSEMBLY_FEE


def view(picks, cond=None, matched=None):
    """고객에게 주는 구성. 줄마다 판매가는 싣지 않는다 — 총액만 준다."""
    lines = []
    for s in ORDER:
        p = picks.get(s)
        line = dict(slot=s, label=SLOT_LABELS[s], product_code=None, name=None, quantity=None,
                    from_request=bool(matched and s in matched))
        if p is not None:
            line.update(product_code=p['product_code'], name=p['name'], quantity=p['quantity'])
        elif s == 'GPU':
            line['name'] = 'CPU 내장 그래픽'
        elif s == 'COOLER':
            line['name'] = '쿨러 상담 후 결정'
        lines.append(line)
    warnings = [WARNING_COOLER] if picks.get('COOLER') is None else []
    return dict(lines=lines, total=total_of(picks), assembly_fee_included=True, warnings=warnings,
                requested=condition_view(cond) if cond else [], note=NOTE)


def load(conn, codes=None):
    rows = [dict(r) for r in conn.execute(text(PARTS_SQL if codes is not None else CANDIDATES_SQL),
                                          dict(codes=codes) if codes is not None else
                                          dict(types=[t for s in ORDER for t in QUOTE_SLOTS[s]])).mappings()]
    return rows


def start_build(conn, cond, rules=None):
    if cond.cpu is not None and cpu_rule(cond.cpu) is None:
        raise HTTPException(422, 'CPU 조건을 읽지 못했어요. CPU 시리즈나 정확한 모델명을 확인해 주세요.')
    rows = load(conn)
    specs = load_specs(conn, [r['product_code'] for r in rows])
    rules = load_rules(conn) if rules is None else rules
    if not rules:
        raise HTTPException(503, '호환 규칙을 불러오지 못해 구성을 만들 수 없어요. 잠시 뒤 다시 시도해 주세요.')
    cands = {s: slot_candidates(rows, specs, cond, s) for s in ORDER}
    missing = [dict(slot=x['slot'], label=x['label'], value=x['value'],
                    reason='지금 판매 중인 부품 중 이 조건에 맞는 것이 없어요.')
               for x in condition_view(cond) if not cands.get(x['slot'])]
    if missing:
        raise HTTPException(409, dict(error='no_match', unmatched=missing,
                                      detail='말씀하신 조건에 맞는 판매 부품을 찾지 못했어요: '
                                             + ' · '.join(f"{m['label']} {m['value']}" for m in missing)))
    picks, stuck = fill(cands, specs, rules, gpu_optional=not cond.gpu)
    if picks is None:
        raise HTTPException(409, dict(error='no_build', detail='말씀하신 조건을 모두 함께 쓰는 호환 구성을 찾지 못했어요. '
                                                               '조건 하나를 바꿔 다시 시도해 주세요.',
                                      blocked=stuck['reasons'], exhausted=stuck['exhausted']))
    return view(picks, cond, {x['slot'] for x in condition_view(cond)})


# ── 고객이 고른 구성 ──────────────────────────────────────────────────────
class Pick(BaseModel):
    model_config = ConfigDict(extra='forbid')
    slot: Literal['CPU', 'MB', 'RAM', 'GPU', 'CASE', 'COOLER', 'SSD', 'POWER']
    product_code: StrictInt = Field(gt=0)
    quantity: StrictInt = Field(default=1, ge=1, le=2)


class BuildBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    parts: list[Pick] = Field(min_length=1, max_length=8)


class OptionsBody(BuildBody):
    slot: Literal['CPU', 'MB', 'RAM', 'GPU', 'CASE', 'COOLER', 'SSD', 'POWER']


class StartBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str | None = Field(default=None, max_length=500)
    conditions: Conditions | None = None


def resolve(conn, parts):
    """화면이 보낸 고른 부품을 지금 DB 값으로 다시 읽는다. 판매 중이 아니거나 자리가 다르면 거절한다."""
    slots = [p.slot for p in parts]
    if len(set(slots)) != len(slots):
        raise HTTPException(422, '한 자리에는 부품을 하나만 고를 수 있어요.')
    rows = {r['product_code']: r for r in load(conn, [p.product_code for p in parts])}
    specs = load_specs(conn, list(rows))
    picks = {}
    for p in parts:
        r = rows.get(p.product_code)
        if r is None or not _usable(r) or slot_of(r['part_type'] or '') != p.slot:
            raise HTTPException(409, f'{SLOT_LABELS[p.slot]} 부품이 지금 판매 중이 아니에요. 다시 골라 주세요.')
        if p.quantity != 1 and p.slot not in QTY.QTY_SLOTS:
            raise HTTPException(422, '메모리와 SSD만 수량을 바꿀 수 있어요.')
        pick = dict(product_code=r['product_code'], quantity=p.quantity, name=display_name(r['product_name']), row=r)
        if p.slot == 'RAM':
            modules, cap = ram_cap(r, specs.get(r['product_code']))
            pick.update(modules=modules * p.quantity, gb=cap * p.quantity if cap else None)
        picks[p.slot] = pick
    for s in REQUIRED:
        if s not in picks:
            raise HTTPException(422, f'{SLOT_LABELS[s]}을(를) 골라 주세요.')
    for s in OPTIONAL:
        picks.setdefault(s, None)
    return picks, specs


def check_build(picks, specs, rules):
    """고른 구성 전체를 판정한다. 막히면 409(고객이 읽을 말)."""
    if not rules:
        raise HTTPException(503, '호환 규칙을 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.')
    if picks.get('GPU') is None and (specs.get(picks['CPU']['product_code']) or {}).get('cpu_gpu') is not True:
        raise HTTPException(409, '이 CPU는 내장 그래픽이 없어 그래픽카드를 골라야 해요.')
    if not ram_fits(picks, specs):
        raise HTTPException(409, '메모리 개수나 용량이 메인보드가 받는 범위를 넘어요. 메모리를 다시 골라 주세요.')
    storage_error = storage_refusal(picks, specs)
    if storage_error:
        raise HTTPException(409, storage_error)
    bad, _ = judge(picks, specs, rules, list(KEY.values()), final=True)
    if bad:
        failed = [c for c in bad if c['state'] == 'fail']
        names = ' · '.join(dict.fromkeys(c['label'] for c in (failed or bad)))
        raise HTTPException(409, ('이 조합은 호환되지 않아요: ' if failed else '호환을 확인하지 못한 부분이 있어요: ') + names)


def quote_build(conn, parts, rules=None):
    """보관·상담 신청이 다시 부르는 계산. (picks, 고객용 구성)."""
    rules = load_rules(conn) if rules is None else rules
    picks, specs = resolve(conn, parts)
    check_build(picks, specs, rules)
    return picks, view(picks)


def options_build(conn, parts, slot, rules=None):
    rules = load_rules(conn) if rules is None else rules
    picks, specs0 = resolve(conn, parts)
    check_build(picks, specs0, rules)
    current = picks.get(slot)
    rows = [r for r in load(conn) if slot_of(r['part_type'] or '') == slot]
    specs = load_specs(conn, [p['product_code'] for p in picks.values() if p] + [r['product_code'] for r in rows])
    if slot == 'RAM':
        # 메모리는 용량별로 고를 수 있게 지금 용량에 묶지 않는다 — 8 · 16 · 32 · 64GB 를 모두 본다
        cands = []
        for gb in (8, 16, 32, 64, 128):
            cands += slot_candidates(rows, specs, Conditions(ram_gb=gb), 'RAM')
        cands = _uniq(cands)
    elif slot == 'SSD':
        cands = _uniq([c for gb in (500, 1000, 2000, 4000) for c in slot_candidates(rows, specs, Conditions(ssd_gb=gb), 'SSD')])
    else:
        cands = slot_candidates(rows, specs, Conditions(), slot)
    base = total_of(picks)
    now_cost = current['row']['sale_price'] * current['quantity'] if current else 0
    ok, untested = [], 0
    for c in cands:
        if current and c['product_code'] == current['product_code'] and c['quantity'] == current['quantity']:
            continue
        trial = dict(picks, **{slot: c})
        bad, _ = judge(trial, specs, rules, list(KEY.values()), final=True)
        if bad or not ram_fits(trial, specs) or storage_refusal(trial, specs):
            untested += bool(bad) and all(x['state'] == 'unknown' for x in bad)
            continue
        diff = c['cost'] - now_cost
        ok.append(dict(product_code=c['product_code'], name=c['name'], quantity=c['quantity'],
                       price_diff=diff, total=base + diff))
    ok.sort(key=lambda o: (o['price_diff'], o['product_code']))
    cheaper = [o for o in ok if o['price_diff'] < 0][-OPTIONS_CHEAPER:]
    pricier = [o for o in ok if o['price_diff'] >= 0][:OPTIONS_PRICIER]
    can_clear = (slot == 'GPU' and current is not None
                 and (specs.get(picks['CPU']['product_code']) or {}).get('cpu_gpu') is True)
    return dict(slot=slot, label=SLOT_LABELS[slot], current=dict(product_code=current['product_code'], name=current['name'],
                                                                 quantity=current['quantity']) if current else None,
                total=base, options=cheaper + pricier, checked=len(cands), untested=untested,
                clear=dict(name='CPU 내장 그래픽 사용', price_diff=-now_cost, total=base - now_cost) if can_clear else None,
                note='호환 규칙을 통과한 판매 중 부품만 보여 드려요. 금액은 바꿨을 때의 차액과 PC 총액이에요.')


# ── 경로 ────────────────────────────────────────────────────────────────
@router.post('/free-build/start')
def start(body: StartBody, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    if body.conditions is None and not (body.text or '').strip():
        raise HTTPException(422, '원하시는 부품 조건을 적어 주세요. 예: 메모리 32GB, RTX 5060 Ti, i9')
    cond = body.conditions or parse_text(body.text)
    with engine.connect() as c:
        res = start_build(c, cond)
    return {'ok': True, 'conditions': cond.model_dump(exclude_none=True), **res}


@router.post('/free-build/options')
def options(body: OptionsBody, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with engine.connect() as c:
        res = options_build(c, body.parts, body.slot)
    return {'ok': True, **res}


@router.post('/free-build/quote')
def quote(body: BuildBody, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with engine.connect() as c:
        _, res = quote_build(c, body.parts)
    return {'ok': True, **res}
