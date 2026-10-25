"""고객 PC 구성(/mvp4/pc-builder/) — 서버가 쥐는 후보·가격·호환·예산 계산 (2026-10-25 대표 지시
「실제 코딩하고 LLM도 연결 … 부품별로 추천받고 왜 추천했는지 설명 … 터무니없는 예산에는 가능한 대안을 안내」).

이 파일은 AI 를 부르지 않는다. AI(api/pc_builder_advisor.py)가 고를 수 있는 상품과 그 근거를 여기서 정하고,
AI 가 돌려준 상품번호·금액은 여기서 계산한 값과 대조한다. 화면이 보여 주는 가격·합계·호환·판매 가능 여부도 여기서 나온다.

■ 후보 출처(공급자 어댑터)
  지금은 `SampleCatalogSource` — 2026-10-23 팝콘PC 공개 판매목록에서 조사한 32개 상품번호(products.product_code =
  몰 원상품번호 pd_no)만 허용목록으로 쓴다. 보유 재고 전체가 아니다. 가격·판매 상태·규격은 그 번호로 DB(products ·
  product_specs)를 다시 읽어 정한다. 조사 파일의 가격·사양 문구는 화면 사진·이름 보조로만 쓴다.
  팝콘PC 상품 API 계약이 정해지면 같은 모양(entries · as_of · name)의 어댑터로 바꾼다.
  ⚠ /api/customer/pc-offers 구성의 partId 는 순번이라 허용목록으로 쓰지 않는다.

■ 판매 가능 = mvp3_free_build 와 같은 거름(판매중 · 판매가 > 0 · 실데이터 · 검수 대기 아님 · 중고·노트북용 아님).
  `stock_qty` 는 실보유 수량을 보장하지 않아(조달 가능과 구분 안 됨) 「판매중 · 실보유 수량 확인 전」으로만 알린다.

■ 호환 = `mvp3_free_build.judge`(관리자 조립·부품 직접 고르기와 같은 `build_check` 규칙). 판정하지 못한 규칙(unknown)은
  통과로 세지 않고 「확인 필요」로 남긴다. 그래픽카드·쿨러도 필수 자리로 본다(내장 그래픽·기본 쿨러를 추정해 빼지 않는다).

■ 금액 = 판매단위 1개 판매가의 합(부품 합계). 조립비·배송·OS 는 별도라고 함께 알린다(화면 문구와 같은 기준).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from . import mvp3_free_build as FB
from .build_check import load_rules, load_specs
from .catalog_map import has_used_mark
from .mvp3_build import not_desktop_ram, not_storage
from .product_name import display_name
from .taxonomy import slot_of
from .timeutil import KST

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / 'mockups' / 'mvp4' / 'pc-builder' / 'data' / 'catalog.json'

# 화면 분류 -> 서버 자리. 순서는 화면 슬롯 순서.
CATEGORIES = ('cpu', 'board', 'memory', 'gpu', 'storage', 'cooler', 'case', 'power')
SLOT = {'cpu': 'CPU', 'board': 'MB', 'memory': 'RAM', 'gpu': 'GPU', 'storage': 'SSD', 'cooler': 'COOLER',
        'case': 'CASE', 'power': 'POWER'}
CATEGORY_OF = {v: k for k, v in SLOT.items()}
LABEL = {'cpu': 'CPU', 'board': '메인보드', 'memory': '메모리', 'gpu': '그래픽카드', 'storage': '저장장치',
         'cooler': 'CPU 쿨러', 'case': '케이스', 'power': '파워'}
PURPOSES = {'gaming': '게임', 'office': '사무·일상', 'creator': '영상·작업'}
# 용도별로 남는 예산을 먼저 쓰는 자리(근거 없는 성능 수치 대신 「어디에 돈을 쓰는 편이 용도에 맞는가」의 일반 원칙).
UPGRADE_ORDER = {'gaming': ('gpu', 'cpu', 'memory', 'storage', 'power', 'case', 'cooler', 'board'),
                 'creator': ('cpu', 'memory', 'gpu', 'storage', 'board', 'power', 'cooler', 'case'),
                 'office': ('storage', 'memory', 'cpu')}
NODE_CAP = 6000            # 최소 구성 탐색에서 호환 판정 횟수 하한 -- 후보 수에 따라 늘린다(node_cap)
NODE_PER_PART = 400       # 후보 1개당 판정 횟수(32개 표본 = 12,800회). 다 써도 못 찾으면 「구성 불가」가 아니라 「확인 못 함」
EXCLUDE_LABEL = {'not_found': 'DB에서 상품을 찾지 못함', 'not_on_sale': '판매중이 아님', 'no_price': '판매가 확인 안 됨',
                 'review': '상품 정보 검수 대기', 'slot_mismatch': '분류가 다름', 'used': '중고·리퍼 표시',
                 'not_real': '실데이터 아님', 'not_desktop': '데스크톱 부품이 아님'}
PRICE_NOTE = '판매단위 1개 판매가의 합(부품 합계) · 조립비·배송·OS 별도'
PSU_LABEL = '파워 권장 여유(그래픽카드 권장 파워 + 100W)'
CPU_MEM_LABEL = 'CPU 플랫폼과 메모리 규격'
# CPU 소켓이 받는 메모리 세대. build_check 의 메모리 규칙은 메인보드와 메모리만 비교해서, 보드를 아직 고르지 않으면
# AM5 CPU 에 DDR4 메모리를 「통과」로 보였다(2026-10-25 개발 서버 실호출에서 발견). 소켓으로 확정되는 것만 적는다 --
# LGA1700 은 보드에 따라 DDR4·DDR5 둘 다 되므로 막지 않는다. CPU 규격의 mem_type 한 값은 LGA1700 에서 믿을 수 없다(119268 = DDR5 로 적혀 있으나 DDR4 보드 구성).
SOCKET_MEMORY = {'AM5': {'DDR5'}, 'LGA1851': {'DDR5'}, 'AM4': {'DDR4'}, 'LGA1200': {'DDR4'},
                 'LGA1700': {'DDR4', 'DDR5'}}


def cpu_memory_ok(sel: dict) -> bool:
    cpu, mem = sel.get('cpu'), sel.get('memory')
    if cpu is None or mem is None:
        return True
    allowed = SOCKET_MEMORY.get(str(cpu.facts.get('소켓') or '').upper())
    kind = str(mem.facts.get('메모리 규격') or '').upper()
    return not (allowed and kind and kind not in allowed)
STOCK_NOTE = '판매중 · 실보유 수량 확인 전'


# ── 공급자 어댑터 ─────────────────────────────────────────────────────────
class SampleCatalogSource:
    """2026-10-23 조사 표본 32개의 상품번호 허용목록. 사진·짧은 이름·몰 상세 주소만 여기서 가져온다."""
    name = 'sample-20261023'

    def __init__(self, path: Path = CATALOG_PATH):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        self.as_of = data.get('asOf')
        self.presets = [p for p in data.get('presets', []) if p.get('purpose') in PURPOSES]
        self._entries = {}
        for p in data.get('parts', []):
            if p.get('category') in SLOT and str(p.get('id', '')).isdigit():
                self._entries[int(p['id'])] = dict(category=p['category'], short=p.get('shortName') or p.get('name'),
                                                   image=p.get('image'), unit=p.get('unit') or '1개',
                                                   source_url=p.get('sourceUrl'))

    def entries(self) -> dict[int, dict]:
        return dict(self._entries)


_SOURCE: SampleCatalogSource | None = None


def source() -> SampleCatalogSource:
    global _SOURCE
    if _SOURCE is None:
        _SOURCE = SampleCatalogSource()
    return _SOURCE


# ── 후보 읽기 ────────────────────────────────────────────────────────────
POOL_SQL = """SELECT p.product_code, p.product_name, p.sale_price, p.status, p.part_type, p.spec_source_text, p.maker,
                     p.data_origin, p.review_required_yn, p.updated_at, p.pricing_basis_revision
                FROM products p WHERE p.product_code = ANY(:codes)"""


@dataclass
class Part:
    code: int
    category: str
    name: str
    short: str
    price: int | None
    usable: bool
    reason: str | None
    updated_at: str | None
    revision: int | None
    unit: str
    image: str | None
    source_url: str | None
    facts: dict = field(default_factory=dict)
    row: dict = field(default_factory=dict, repr=False)

    @property
    def slot(self):
        return SLOT[self.category]

    def public(self) -> dict:
        """화면·AI 에게 주는 모양(내부 행·규격 원문은 뺀다)."""
        return dict(id=str(self.code), category=self.category, name=self.name, shortName=self.short, price=self.price,
                    usable=self.usable, excluded=EXCLUDE_LABEL.get(self.reason) if self.reason else None,
                    updatedAt=self.updated_at, unit=self.unit, facts=self.facts)


def _iso(v):
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(KST).isoformat(timespec='minutes')
    return None


def _reason(r, category) -> str | None:
    if r is None:
        return 'not_found'
    if r.get('data_origin') != 'real':
        return 'not_real'
    if slot_of(r.get('part_type') or '') != SLOT[category]:
        return 'slot_mismatch'
    if r.get('review_required_yn'):
        return 'review'
    if r.get('status') != '판매중':
        return 'not_on_sale'
    if type(r.get('sale_price')) is not int or r['sale_price'] <= 0:
        return 'no_price'
    if has_used_mark(r.get('product_name'), r.get('spec_source_text') or ''):
        return 'used'
    if not_desktop_ram(r) or not_storage(r):
        return 'not_desktop'
    return None


def facts_of(category, spec, row) -> dict:
    """AI 와 화면이 근거로 쓰는 확인된 규격. 값이 없는 항목은 넣지 않는다(지어내지 않는다)."""
    s = spec or {}
    f = {}

    def put(key, value):
        if value not in (None, '', [], {}):
            f[key] = value
    if category == 'cpu':
        put('소켓', s.get('socket')); put('코어', s.get('cpu_cores')); put('TDP(W)', s.get('tdp_watt'))
        if s.get('cpu_gpu') is True: put('내장 그래픽', '있음')
        elif s.get('cpu_gpu') is False: put('내장 그래픽', '없음')
    elif category == 'board':
        put('소켓', s.get('socket')); put('칩셋', s.get('chipset')); put('메모리 규격', s.get('mem_type'))
        put('폼팩터', s.get('form_factor'))
    elif category == 'memory':
        put('메모리 규격', s.get('mem_type')); put('클럭(MHz)', s.get('clock_mhz'))
        modules, cap = FB.ram_cap(row, spec)
        if cap: put('총 용량(GB)', cap); put('모듈 수', modules)
    elif category == 'gpu':
        put('VRAM(GB)', s.get('vram_gb')); put('길이(mm)', s.get('length_mm'))
        put('권장 파워(W)', s.get('required_power_watt')); put('소비전력 참고(W)', s.get('gpu_power_draw_watt'))
    elif category == 'storage':
        put('용량(GB)', s.get('capacity_gb')); put('인터페이스', s.get('interface')); put('폼팩터', s.get('form_factor'))
    elif category == 'cooler':
        put('지원 소켓', s.get('socket_list') or s.get('socket')); put('높이(mm)', s.get('cooler_height_mm'))
        put('쿨링 TDP(W)', s.get('cooler_tdp'))
    elif category == 'case':
        put('GPU 최대(mm)', s.get('gpu_max_mm')); put('CPU 쿨러 최대(mm)', s.get('cooler_height_mm'))
        put('지원 보드', s.get('form_factor_list') or s.get('form_factor'))
    elif category == 'power':
        put('정격(W)', s.get('rated_watt')); put('규격', s.get('form_factor'))
    return f


@dataclass
class Pool:
    parts: dict[int, Part]
    specs: dict
    rules: list
    advice: dict
    as_of: str | None            # 조사 표본 날짜
    loaded_at: str               # 이번 DB 조회 시각
    source_name: str
    presets: list = field(default_factory=list)

    def by_category(self, category, usable_only=True):
        out = [p for p in self.parts.values() if p.category == category and (p.usable or not usable_only)]
        return sorted(out, key=lambda p: (p.price or 0, p.code))

    def get(self, code) -> Part | None:
        try:
            return self.parts.get(int(code))
        except (TypeError, ValueError):
            return None


def load_pool(conn, src: SampleCatalogSource | None = None) -> Pool:
    src = src or source()
    entries = src.entries()
    rows = {r['product_code']: dict(r) for r in conn.execute(text(POOL_SQL), dict(codes=list(entries))).mappings()}
    specs = load_specs(conn, list(rows))
    parts = {}
    for code, e in entries.items():
        r = rows.get(code)
        reason = _reason(r, e['category'])
        parts[code] = Part(code=code, category=e['category'], name=display_name(r['product_name']) if r else e['short'],
                           short=e['short'], price=r['sale_price'] if r and type(r.get('sale_price')) is int else None,
                           usable=reason is None, reason=reason, updated_at=_iso(r.get('updated_at')) if r else None,
                           revision=r.get('pricing_basis_revision') if r else None, unit=e['unit'], image=e['image'],
                           source_url=e['source_url'], facts=facts_of(e['category'], specs.get(code), r or {}), row=r or {})
    return Pool(parts=parts, specs=specs, rules=load_rules(conn), advice=FB.load_advice(conn), as_of=src.as_of,
                loaded_at=datetime.now(KST).isoformat(timespec='seconds'), source_name=src.name, presets=src.presets)


# ── 호환 ────────────────────────────────────────────────────────────────
def pick_of(part: Part, specs: dict | None = None) -> dict:
    """mvp3_free_build.judge 가 받는 한 자리 모양. 메모리는 모듈 수·총 용량을 함께 싣는다(슬롯·용량 판정)."""
    d = dict(product_code=part.code, quantity=1, name=part.name, row=part.row)
    if part.category == 'memory':
        modules, cap = FB.ram_cap(part.row, (specs or {}).get(part.code))
        d.update(modules=modules, gb=cap)
    return d


class Checker:
    """호환 판정 한 곳. 시험에서는 같은 모양의 가짜로 바꾼다(state, labels)."""

    def __init__(self, pool: Pool):
        self.pool = pool
        self._cache = {}

    def _picks(self, sel: dict) -> dict:
        return {SLOT[cat]: pick_of(part, self.pool.specs) for cat, part in sel.items()}

    def slot(self, sel: dict, category: str) -> tuple[str, list[str]]:
        """sel(분류 -> Part)에서 category 자리가 다른 고른 자리와 맞는가. 비어 있는 자리는 그 자리를 고를 때 다시 본다."""
        key = ('s', category, tuple(sorted((c, p.code) for c, p in sel.items())))
        if key in self._cache:
            return self._cache[key]
        picks = self._picks(sel)
        bad, _ = FB.judge(picks, self.pool.specs, self.pool.rules, [FB.KEY[SLOT[category]]])
        if SLOT[category] in ('RAM', 'MB') and not FB.ram_fits(picks, self.pool.specs):
            bad = bad + [dict(label='메모리 슬롯·용량', state='fail')]
        if category in ('gpu', 'power') and not self.psu_margin_ok(sel):
            bad = bad + [dict(label=PSU_LABEL, state='fail')]
        if category in ('cpu', 'memory') and not cpu_memory_ok(sel):
            bad = bad + [dict(label=CPU_MEM_LABEL, state='fail')]
        res = _verdict(bad)
        self._cache[key] = res
        return res

    def full(self, sel: dict) -> tuple[str, list[str]]:
        """8개 자리 전체 판정. 하나라도 비면 incomplete."""
        missing = [c for c in CATEGORIES if c not in sel]
        if missing:
            return 'incomplete', [LABEL[c] for c in missing]
        key = ('f', tuple(sorted((c, p.code) for c, p in sel.items())))
        if key in self._cache:
            return self._cache[key]
        picks = self._picks(sel)
        bad, _ = FB.judge(picks, self.pool.specs, self.pool.rules, list(FB.KEY.values()), final=True)
        if not FB.ram_fits(picks, self.pool.specs):
            bad = bad + [dict(label='메모리 슬롯·용량', state='fail')]
        if not self.psu_margin_ok(sel):
            bad = bad + [dict(label=PSU_LABEL, state='fail')]
        if not cpu_memory_ok(sel):
            bad = bad + [dict(label=CPU_MEM_LABEL, state='fail')]
        res = _verdict(bad)
        self._cache[key] = res
        return res

    def psu_margin_ok(self, sel: dict) -> bool:
        """파워 정격이 그래픽카드 「권장 파워 + 100W」 이상인가. 둘 중 하나라도 모르면 막지 않는다(호환 규칙이 따로 본다).
        예산을 맞추려고 파워 여유를 줄이지 않는다(2026-10-25 요청 §4) -- 상담 안내(power_rule)와 같은 기준."""
        need = self.psu_safe_watt(sel)
        have = sel['power'].facts.get('정격(W)') if sel.get('power') else None
        return not (need and have and have < need)

    def psu_safe_watt(self, sel: dict) -> int | None:
        """고른 그래픽카드의 「권장 파워 + 100W」(상담 안내와 같은 기준). 모르면 None."""
        gpu = sel.get('gpu')
        if gpu is None:
            return None
        return FB.psu_advice_watt({'GPU': pick_of(gpu)}, self.pool.advice)


def _verdict(bad) -> tuple[str, list[str]]:
    if not bad:
        return 'ok', []
    failed = [c for c in bad if c.get('state') == 'fail']
    labels = list(dict.fromkeys(c.get('label') or '규칙' for c in (failed or bad)))
    return ('fail' if failed else 'unknown'), labels


# ── 고른 구성 ────────────────────────────────────────────────────────────
class SelectionError(ValueError):
    def __init__(self, message, *, category=None, code=None):
        super().__init__(message)
        self.category, self.code = category, code


def resolve(pool: Pool, selection: dict) -> dict[str, Part]:
    """화면이 보낸 {분류: 상품번호} 를 허용목록·DB 값으로 다시 읽는다. 목록 밖·자리 다름·판매 불가는 거절."""
    out = {}
    for cat, code in (selection or {}).items():
        if cat not in SLOT:
            raise SelectionError(f'알 수 없는 부품 자리예요: {cat}')
        if code in (None, ''):
            continue
        part = pool.get(code)
        if part is None:
            raise SelectionError(f'{LABEL[cat]} 상품번호 {code}는 이 화면의 후보 목록에 없어요.', category=cat, code=code)
        if part.category != cat:
            raise SelectionError(f'{part.short}은(는) {LABEL[cat]} 자리에 넣을 수 없어요.', category=cat, code=code)
        if not part.usable:
            raise SelectionError(f'{part.short}은(는) 지금 담을 수 없어요({EXCLUDE_LABEL[part.reason]}). 다른 부품을 골라 주세요.',
                                 category=cat, code=code)
        out[cat] = part
    return out


def total_of(sel: dict) -> int:
    return sum(p.price or 0 for p in sel.values())


def selection_key(sel: dict) -> str:
    """요청 때 본 구성의 표식 — 늦게 온 응답을 다른 구성에 적용하지 않게 화면이 비교한다."""
    return '|'.join(f'{c}:{sel[c].code}' for c in CATEGORIES if c in sel)


def price_key(sel: dict) -> str:
    """가격·판매 기준의 표식 — 적용 직전 다시 계산해 바뀌었으면 고객에게 다시 확인받는다."""
    raw = '|'.join(f'{c}:{sel[c].code}:{sel[c].price}:{sel[c].revision}' for c in CATEGORIES if c in sel)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def price_basis(sel_or_parts) -> str | None:
    """이 금액이 기대는 가장 최근 DB 갱신 시각."""
    vals = [p.updated_at for p in (sel_or_parts.values() if isinstance(sel_or_parts, dict) else sel_or_parts) if p.updated_at]
    return max(vals) if vals else None


# ── 한 자리의 후보 ────────────────────────────────────────────────────────
def slot_candidates(pool: Pool, checker: Checker, sel: dict, category: str, part_cap: int | None = None,
                    budget_total: int | None = None) -> dict:
    """category 자리에 넣을 수 있는 후보와 근거. ok = 판정 통과, check = 판정 못 함(확인 필요), fail = 불가."""
    others = {c: p for c, p in sel.items() if c != category}
    other_total = total_of(others)
    current = sel.get(category)
    # 이 자리와 이미 고른 자리를 뺀 빈 자리의 최저가 합(호환 무시 하한). 이 자리는 후보 가격으로 한 번만 더한다
    # (2026-10-25 E2E-01: 이 자리를 None 으로 넘겨 이 자리 최저가를 한 번 더 더하던 중복을 고침).
    rest_min = min_rest_cost(pool, set(others) | {category})
    safe = checker.psu_safe_watt(others) if category == 'power' else None
    out = dict(ok=[], check=[], fail=[], excluded=[])
    for part in pool.by_category(category, usable_only=False):
        if not part.usable:
            out['excluded'].append(dict(id=str(part.code), shortName=part.short, reason=EXCLUDE_LABEL[part.reason]))
            continue
        state, labels = checker.slot({**others, category: part}, category)
        notes = []
        if category == 'power' and safe and (part.facts.get('정격(W)') or 0) < safe:
            notes.append(f'고른 그래픽카드 권장 여유 {safe}W보다 정격이 낮아요')
        if category == 'gpu' and others.get('power'):
            need = FB.psu_advice_watt({'GPU': pick_of(part)}, pool.advice)
            have = others['power'].facts.get('정격(W)')
            if need and have and have < need:
                notes.append(f'고른 파워 {have}W가 권장 여유 {need}W보다 낮아요')
        item = dict(part.public(), state=state, checks=labels, notes=notes,
                    priceDiff=(part.price - current.price) if current else None,
                    selectedTotal=other_total + part.price,                     # 부분 합계: 이미 고른 부품 + 이 후보(빈 자리 제외)
                    withinPartBudget=(part.price <= part_cap) if part_cap else None,
                    overPartBudget=(part.price - part_cap) if part_cap and part.price > part_cap else None,
                    **complete_with(pool, checker, others, category, part, state, budget_total))
        out['ok' if state == 'ok' else 'check' if state == 'unknown' else 'fail'].append(item)
    out.update(otherTotal=other_total, restMin=rest_min, current=str(current.code) if current else None,
               psuSafeWatt=safe)
    return out


def min_rest_cost(pool: Pool, filled) -> int | None:
    """filled(이미 정해진 분류들) 밖의 자리를 각자 가장 싼 판매 가능 후보로 채울 때의 합 -- 호환을 보지 않은 하한이다.
    완성 합계로 부르지 않는다(완성 합계는 complete_with 의 호환 탐색 값)."""
    total = 0
    for c in CATEGORIES:
        if c in filled:
            continue
        cands = pool.by_category(c)
        if not cands:
            return None
        total += cands[0].price
    return total


def complete_with(pool: Pool, checker: Checker, others: dict, category: str, part: Part, state: str,
                  budget_total: int | None) -> dict:
    """이 후보를 넣고 빈 자리를 호환 부품으로 채운 완성 구성의 최소 합계와 전체 예산 판정(min_build -- 금액 역할이 하나).
    completeMin   = 탐색을 끝까지 마친 완성 최소 합계(전체 합계). 탐색 한도로 못 마치면 None, 찾은 값은 completeFound.
    withinTotalBudget = 완성 최소 기준 예산 안(True)/밖(False). 최소를 확정 못 했고 찾은 값이 예산 밖이면 None.
    overTotalBudget = 완성 최소 - 전체 예산(확정일 때만). totalHeadroom = 전체 예산 - 완성 합계(최소 미확정이면 「적어도」 값)."""
    # completeState: exact(최소 확정) · found(찾았으나 최소 미확정) · none(호환 완성 구성 없음 확인) · unknown(탐색 한도로 못 찾음) · skip(판정 미통과 후보)
    res = dict(completeState='skip', completeMin=None, completeFound=None, withinTotalBudget=None,
               overTotalBudget=None, totalHeadroom=None)
    if state != 'ok':
        return res
    mb = min_build(pool, checker, {**others, category: part})
    if mb is None:
        res['completeState'] = 'none'
        return res
    if not mb.get('sel'):
        res['completeState'] = 'unknown'
        return res
    exact = not mb['exhausted']
    res.update(completeState='exact' if exact else 'found', completeFound=mb['total'], completeMin=mb['total'] if exact else None)
    if budget_total:
        if mb['total'] <= budget_total:
            res.update(withinTotalBudget=True, totalHeadroom=budget_total - mb['total'])
        elif exact:
            res.update(withinTotalBudget=False, overTotalBudget=mb['total'] - budget_total)
    return res


# ── 최소 구성 · 채우기 ────────────────────────────────────────────────────
FILL_ORDER = ('cpu', 'board', 'memory', 'gpu', 'case', 'cooler', 'storage', 'power')   # mvp3_free_build.ORDER 와 같은 순서


def node_cap(pool: Pool) -> int:
    return max(NODE_CAP, NODE_PER_PART * sum(1 for p in pool.parts.values() if p.usable))


def min_build(pool: Pool, checker: Checker, fixed: dict) -> dict | None:
    """고정 부품을 유지한 8개 자리 최소 금액 호환 구성(분기 한정 · 자리마다 싼 것부터).
    None = 호환 구성이 없음을 끝까지 확인. {'sel': None, 'exhausted': True} = 탐색 한도 안에 찾지 못함(없다고 단정하지 않는다)."""
    choices = {}
    for c in FILL_ORDER:
        choices[c] = [fixed[c]] if fixed.get(c) is not None else pool.by_category(c)
        if not choices[c]:
            return None
    floor = {c: min(p.price for p in choices[c]) for c in FILL_ORDER}
    best = {'total': None, 'sel': None}
    budget = [node_cap(pool)]

    def step(i, sel, cost):
        if budget[0] <= 0:
            return
        if best['total'] is not None and cost + sum(floor[c] for c in FILL_ORDER[i:]) >= best['total']:
            return
        if i == len(FILL_ORDER):
            budget[0] -= 1
            if checker.full(sel)[0] == 'ok':
                best['total'], best['sel'] = cost, dict(sel)
            return
        c = FILL_ORDER[i]
        for part in choices[c]:
            trial = dict(sel, **{c: part})
            budget[0] -= 1
            if checker.slot(trial, c)[0] != 'ok':
                continue
            step(i + 1, trial, cost + part.price)
    step(0, {}, 0)
    if best['sel'] is None:
        return dict(sel=None, total=None, exhausted=True) if budget[0] <= 0 else None
    return dict(sel=best['sel'], total=best['total'], exhausted=budget[0] <= 0)


def preset_build(pool: Pool, checker: Checker, fixed: dict, purpose: str) -> dict | None:
    """조사 표본의 용도별 시작 구성을 고정 부품에 맞춰 채운 것. 맞지 않는 자리는 가장 싼 호환 후보로."""
    preset = next((p for p in pool.presets if p.get('purpose') == purpose), None)
    if not preset:
        return None
    sel = {}
    for c in FILL_ORDER:
        if fixed.get(c) is not None:
            sel[c] = fixed[c]
            continue
        want = pool.get(preset['components'].get(c))
        order = ([want] if want and want.usable else []) + [p for p in pool.by_category(c) if not want or p.code != want.code]
        for part in order:
            if checker.slot(dict(sel, **{c: part}), c)[0] == 'ok':
                sel[c] = part
                break
        else:
            return None
    if checker.full(sel)[0] != 'ok':
        return None
    return dict(sel=sel, total=total_of(sel))


def upgrade_build(pool: Pool, checker: Checker, base: dict, fixed: dict, purpose: str, budget_total: int) -> dict | None:
    """최소 구성에서 출발해 용도에 맞는 자리부터 한 단계씩 올리되 전체 예산을 넘지 않는다. 바뀐 것이 없으면 None."""
    sel = dict(base)
    changed = True
    while changed:
        changed = False
        for c in UPGRADE_ORDER.get(purpose, ()):
            if fixed.get(c) is not None:
                continue
            for part in [p for p in pool.by_category(c) if p.price > sel[c].price]:
                trial = dict(sel, **{c: part})
                if total_of(trial) > budget_total:
                    break
                if checker.slot(trial, c)[0] == 'ok' and checker.full(trial)[0] == 'ok':
                    sel = trial
                    changed = True
                    break
    if all(sel[c].code == base[c].code for c in CATEGORIES):
        return None
    return dict(sel=sel, total=total_of(sel))


def fill_options(pool: Pool, checker: Checker, fixed: dict, purpose: str, budget_total: int | None) -> list[dict]:
    """AI 가 고를 수 있는 완성 구성 후보(전부 서버 판정 통과). 고정 부품은 어떤 후보에서도 바꾸지 않는다."""
    out = []

    def add(kind, label, build):
        if not build or not build.get('sel'):
            return
        key = selection_key(build['sel'])
        if any(o['key'] == key for o in out):
            return
        out.append(dict(id=f'opt{len(out) + 1}', kind=kind, label=label, key=key, sel=build['sel'], total=build['total'],
                        within=(budget_total is None or build['total'] <= budget_total)))
    base = min_build(pool, checker, fixed)
    add('min', '확인된 후보 기준 최소 금액 구성' if base and not base['exhausted'] else '찾은 구성 중 가장 싼 구성(최소 여부 확인 못 함)', base)
    add('preset', f'{PURPOSES.get(purpose, "")} 참고 구성', preset_build(pool, checker, fixed, purpose))
    if base and base['sel'] and budget_total and base['total'] <= budget_total:
        add('upgrade', f'예산 안에서 {PURPOSES.get(purpose, "")} 용도 자리를 올린 구성',
            upgrade_build(pool, checker, base['sel'], fixed, purpose, budget_total))
    return out


def feasibility(pool: Pool, checker: Checker, fixed: dict, budget_total: int | None) -> dict:
    """예산으로 구성이 되는가 — 확인된 후보·판매 상태·호환·고정 부품 기준. 숫자는 지금 계산한 값만 쓴다."""
    base = min_build(pool, checker, fixed)
    free = min_build(pool, checker, {}) if fixed else base
    found = base['total'] if base and base['sel'] else None
    exact = found is not None and not base['exhausted']      # 탐색을 끝까지 마친 최소 금액인가(Codex 재검수 P2-4)
    res = dict(scope=f'현재 확인된 후보 {sum(1 for p in pool.parts.values() if p.usable)}개 기준 (전체 시장 최저가 아님)',
               priceBasis=price_basis(pool.parts.values()), loadedAt=pool.loaded_at, budget=budget_total,
               minTotal=found if exact else None, minExact=exact if found is not None else None, foundTotal=found,
               minTotalFree=free['total'] if free and free['sel'] and not free['exhausted'] else None,
               status=None, shortfall=None, headroom=None, relax=[], conflicts=[], note=PRICE_NOTE)
    if base is None:
        res['status'] = 'no_build'
    elif found is None:
        res['status'] = 'unknown'          # 탐색 한도 -- 하나도 못 찾았다. 최소 금액을 지어내지 않는다
    elif budget_total is None:
        res['status'] = 'no_budget'
    elif found <= budget_total:
        res['status'] = 'feasible'         # 예산 안 구성을 실제로 찾았으니 가능은 확정. 최소가 아니면 여유는 「적어도」 값
        res['headroom'] = budget_total - found
    elif exact:
        res['status'] = 'over'
        res['shortfall'] = found - budget_total
    else:
        res['status'] = 'unknown'          # 찾은 구성은 예산 초과지만 더 싼 구성이 남았을 수 있다 -- 부족액을 단정하지 않는다
    # 고정 부품 때문에 안 되거나 비싸지는지 — 하나씩 풀어 본 최소 금액(고객 동의 후 바꿀 대안으로만 보여 준다)
    if fixed and res['status'] in ('no_build', 'over', 'unknown'):
        for c, part in fixed.items():
            rest = {k: v for k, v in fixed.items() if k != c}
            alt = min_build(pool, checker, rest)
            if alt and alt['sel'] and (found is None or alt['total'] < found):
                res['relax'].append(dict(category=c, label=LABEL[c], current=part.short, currentPrice=part.price,
                                         replacement=alt['sel'][c].short, replacementId=str(alt['sel'][c].code),
                                         minTotal=alt['total'], exact=not alt['exhausted'],
                                         saving=(found - alt['total']) if found is not None and exact and not alt['exhausted'] else None,
                                         fits=budget_total is not None and alt['total'] <= budget_total))
        res['relax'].sort(key=lambda r: r['minTotal'])
    # 고정 부품끼리 맞지 않는 자리 -- 하나만 풀어서는 풀리지 않을 때도 무엇이 왜 막히는지 알린다(Antigravity 검토 6)
    if fixed and res['status'] == 'no_build':
        seen = set()
        for c, part in fixed.items():
            state, labels = checker.slot(fixed, c)
            if state == 'fail' and tuple(labels) not in seen:
                seen.add(tuple(labels))
                res['conflicts'].append(dict(category=c, label=LABEL[c], current=part.short, checks=labels))
    return res


# ── 예산 말 읽기 ──────────────────────────────────────────────────────────
AMOUNT_RX = re.compile(r'(?<![\d.,])(-?\d+(?:[.,]\d+)*)\s*(억\s*원?|천\s*만\s*원?|백\s*만\s*원?|만\s*원?|천\s*원|원)?')
TOTAL_WORDS = re.compile(r'전체|총\s*예산|총액|합계|본체|PC\s*(?:한\s*대|전체|예산)|컴퓨터\s*(?:전체|예산)|다\s*합쳐|모두\s*합쳐')
PART_WORDS = re.compile(r'이하|미만|안쪽|안으로|이내|상한|넘지\s*않|부품만|한\s*개|하나|짜리|'
                        r'(?:그래픽\s*카드|GPU|CPU|메모리|램|SSD|저장\s*장치|파워|케이스|쿨러|보드)\s*만', re.I)
UNIT_MUL = {'억': 100_000_000, '천만': 10_000_000, '백만': 1_000_000, '만': 10_000, '천': 1_000, '원': 1}
NOT_MONEY_AFTER = re.compile(r'\s*(GB|TB|G\b|T\b|W\b|mm|MHz|Hz|기가|테라|와트|인치|fps|프레임|개|대|명|년|세대|코어|스레드|[A-Za-z])', re.I)
MODEL_BEFORE = re.compile(r'(?:[A-Za-z]|RTX|GTX|RX|i[3579]|라이젠|ryzen|울트라)\s*-?\s*$', re.I)
MAX_BUDGET = 100_000_000       # 1억 원을 넘는 부품 예산은 입력 실수로 보고 확인을 받는다


def _amount_tokens(t: str) -> list[dict]:
    """글 속 금액 조각. 「1억 5천만원」처럼 억 뒤에 바로 붙는 작은 단위는 한 금액으로 합친다(Antigravity 검토 3)."""
    out = []
    for m in AMOUNT_RX.finditer(t):
        unit = re.sub(r'\s+', '', m.group(2) or '')
        if not unit and (NOT_MONEY_AFTER.match(t, m.end()) or MODEL_BEFORE.search(t[:m.start()])):
            continue            # 용량·전력·개수·모델 번호(RTX 5060 · i5-14400F) 같은 다른 숫자
        base = unit if unit == '원' else unit[:-1] if unit.endswith('원') else unit
        mul = UNIT_MUL.get(base)
        try:
            won = int(round(float(m.group(1).replace(',', '')) * mul)) if mul else None
        except ValueError:
            won = None
        tok = dict(start=m.start(), end=m.end(), raw=m.group(0).strip(), unit=base, won=won)
        prev = out[-1] if out else None
        if (prev and prev['unit'] == '억' and won is not None and prev['won'] is not None and base in ('천만', '백만', '만', '천')
                and not t[prev['end']:m.start()].strip()):
            prev.update(end=m.end(), raw=t[prev['start']:m.end()].strip(), won=prev['won'] + won, unit=base)
            continue
        out.append(tok)
    return out


def _token_problem(tok) -> str | None:
    if tok['won'] is None:
        return 'unit'
    if tok['won'] <= 0:
        return 'nonpositive'
    if tok['won'] > MAX_BUDGET:
        return 'too_large'
    return None


def _scope(ctx: str) -> str | None:
    return 'total' if TOTAL_WORDS.search(ctx) else 'part' if PART_WORDS.search(ctx) else None


# 금액 두 개를 나눠 받을 때만 쓰는 경계·부품 이름(「그래픽카드는 80만원, 전체 150만원」). 금액 하나일 때 부품 이름만으로 부품 예산이라 정하지 않는다.
PAIR_SPLIT = re.compile(r'[,，;/]|이고|이며|그리고|\s하고\s|\s고\s')
PART_NAMES = re.compile(r'그래픽\s*카드|GPU|CPU|메모리|램|SSD|저장\s*장치|파워|케이스|쿨러|메인\s*보드|보드', re.I)


def _pair_scope(ctx: str) -> str | None:
    return 'total' if TOTAL_WORDS.search(ctx) else 'part' if PART_WORDS.search(ctx) or PART_NAMES.search(ctx) else None


def parse_budget(text_in: str) -> dict | None:
    """질문 속 금액을 읽는다. None = 금액 없음. 단위가 없거나(80) 범위가 정해지지 않은 여러 금액은 해석하지 않고 문제로 돌려준다.
    {'won', 'raw', 'unit_clear', 'scope'('total'|'part'|'both'|None), 'problem'('unit'|'nonpositive'|'too_large'|'multiple'|None)}
    scope='both' 이면 'total' 과 'part' 에 각각 금액이 있다(「전체 150만원이고 그래픽카드는 80만원 이하」)."""
    t = (text_in or '').replace('，', ',')
    toks = _amount_tokens(t)
    if not toks:
        return None
    if len(toks) == 2:
        # 금액마다 그 앞뒤 말(다른 금액과의 경계까지)로 범위를 정한다 -- 하나는 전체, 하나는 부품일 때만 나눠 받는다
        between = t[toks[0]['end']:toks[1]['start']]
        cut = PAIR_SPLIT.search(between)
        edge = toks[0]['end'] + (cut.start() if cut else len(between))
        scopes = [_pair_scope(t[:edge]), _pair_scope(t[edge:])]
        if sorted(s or '' for s in scopes) == ['part', 'total']:
            for tok in toks:
                problem = _token_problem(tok)
                if problem:
                    return dict(won=None, raw=tok['raw'], unit_clear=tok['won'] is not None, scope=None, problem=problem)
            total = toks[scopes.index('total')]['won']
            part = toks[scopes.index('part')]['won']
            return dict(won=None, raw=' · '.join(x['raw'] for x in toks), unit_clear=True, scope='both', problem=None,
                        total=total, part=part)
    if len(toks) > 1:
        return dict(won=None, raw=' · '.join(x['raw'] for x in toks), unit_clear=False, scope=None, problem='multiple')
    tok = toks[0]
    res = dict(won=tok['won'], raw=tok['raw'], unit_clear=tok['won'] is not None, scope=_scope(t), problem=_token_problem(tok))
    if res['problem'] == 'unit':
        res['won'] = None
    return res


def budget_check(won) -> str | None:
    """화면의 전체 예산 칸 값. 문제가 있으면 고객에게 보일 짧은 확인 문장."""
    if won is None:
        return None
    if type(won) is not int or won <= 0:
        return '전체 부품 예산은 0원보다 커야 해요. 금액을 다시 확인해 주세요.'
    if won > MAX_BUDGET:
        return '전체 부품 예산이 1억 원을 넘어요. 입력한 금액이 맞는지 확인해 주세요.'
    return None


def won(n) -> str:
    return f'{int(n):,}원'
