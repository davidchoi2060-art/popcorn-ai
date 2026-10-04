"""Read current recommendation evidence using the caller's connection only."""
import re

from sqlalchemy import text

from .taxonomy import CORE_TYPES


PRODUCTS = '/admin2/products?admin=new'
REVIEWS = '/admin2/reviews?admin=new'
STOCK = '/admin2/stock-inbound?admin=new'
PRICE = '/admin2/price-review?admin=new'
STATE_LABELS = {'needs_work': '보완 필요', 'needs_check': '확인 필요',
                'basis_met': '추천 근거 충족', 'excluded': '추천 대상 제외'}

_SELECT = """
SELECT p.product_code, p.sku, p.product_name, p.part_type, p.category_group,
       p.data_origin, p.status, p.stock_qty, p.sale_price,
       p.review_required_yn, p.ai_candidate_yn, p.locked_fields,
       (s.product_code IS NOT NULL) AS has_specs,
       (candidate.product_code IS NOT NULL) AS in_pool
FROM products p
LEFT JOIN product_specs s ON s.product_code = p.product_code
LEFT JOIN (SELECT product_code FROM v_recommendation_candidates WHERE stock_qty > 0)
  candidate ON candidate.product_code = p.product_code
"""


def project_part(row):
    """Explain the existing gates; actual view membership remains authoritative."""
    checks, reasons = [], []

    def check(key, label, value, detail, href, *, excluded=False):
        state = 'unknown' if value is None else 'met' if value else 'blocked'
        checks.append(dict(key=key, label=label, state=state, detail=detail))
        if state != 'met':
            reasons.append(dict(key=key, label=label, detail=detail, href=href,
                                severity='unknown' if state == 'unknown' else 'info' if excluded else 'blocker'))

    category = (None if row['category_group'] is None or row['part_type'] is None
                else row['category_group'] == 'core_part' and row['part_type'] in CORE_TYPES)
    demo = row['data_origin'] == 'demo'
    check('category', '추천 부품 분류', category, row['part_type'] or '분류 미확인', PRODUCTS, excluded=True)
    check('origin', '실상품 구분', not demo, '시연용 상품' if demo else '시연용 제외 조건 충족', PRODUCTS, excluded=True)
    check('spec_row', '사양 정보', row['has_specs'],
          '사양 행 미확인' if row['has_specs'] is None else '사양 행 있음' if row['has_specs'] else '사양 행 없음', PRODUCTS)
    review = None if row['review_required_yn'] is None else not row['review_required_yn']
    check('review', '사양 검수', review, '검수 여부 미확인' if review is None else '검수 완료' if review else '사양 검수 필요', REVIEWS)
    check('candidate', '후보 지정', row['ai_candidate_yn'],
          '후보 여부 미확인' if row['ai_candidate_yn'] is None else '후보 지정됨' if row['ai_candidate_yn'] else '후보 미지정', REVIEWS)
    price = row['sale_price']
    price_href = PRICE if review is True and 'sale_price' not in (row['locked_fields'] or []) else PRODUCTS
    check('price', '판매가 등록', price is not None, '판매가 없음' if price is None else f'{price:,}원', price_href)
    status = None if row['status'] is None else row['status'] == '판매중'
    check('status', '판매 상태', status, row['status'] or '판매 상태 미확인', PRODUCTS)
    stock = None if row['stock_qty'] is None else row['stock_qty'] > 0
    check('stock', '현재 재고', stock, '재고 미확인' if stock is None else f"{row['stock_qty']}개", STOCK)
    membership = row['in_pool']
    check('pool', '실제 추천 후보', membership,
          '조회 상태 미확인' if membership is None else '추천 후보 조회됨' if membership else '추천 후보 조회되지 않음', PRODUCTS)

    explanations = checks[:-1]
    blocked = any(c['state'] == 'blocked' for c in explanations)
    unknown = any(c['state'] == 'unknown' for c in explanations)
    mismatch = (membership is True and (blocked or unknown)) or (membership is False and not blocked and not unknown)
    if mismatch:
        reasons.append(dict(key='pool_mismatch', label='추천 근거 대조 필요',
                            detail='조건 설명과 실제 추천 후보 조회가 일치하지 않습니다', href=PRODUCTS, severity='unknown'))
    if demo or category is False:
        state = 'excluded'
    elif unknown or mismatch or membership is None:
        state = 'needs_check'
    elif blocked:
        state = 'needs_work'
    else:
        state = 'basis_met'
    return dict(id=str(row['product_code']), name=row['product_name'] or str(row['product_code']),
                code=str(row['sku'] or row['product_code']), state=state, state_label=STATE_LABELS[state],
                reasons=reasons, checks=checks, href=PRODUCTS)


def list_parts(conn):
    """One bulk read, including explicit recommendation exclusions."""
    rows = conn.execute(text(_SELECT + ' ORDER BY p.product_code')).mappings().all()
    return [project_part(row) for row in rows]


def detail_part(conn, identity):
    if not isinstance(identity, str) or re.fullmatch(r'[1-9][0-9]{0,18}', identity) is None:
        return None
    code = int(identity)
    if code > 9223372036854775807:
        return None
    row = conn.execute(text(_SELECT + ' WHERE p.product_code = :code'), {'code': code}).mappings().first()
    return None if row is None else project_part(row)
