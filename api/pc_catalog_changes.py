"""Read-only admin alerts from current catalog data; never reprice or approve."""
import re
from datetime import datetime, timezone
from sqlalchemy import text


def load_market(conn):
    products = {str(r['product_code']): dict(r) for r in conn.execute(text('''
        SELECT product_code,product_name,status,sale_price FROM products
        WHERE product_code IN (SELECT product_code FROM product_explanations WHERE
          source_product_code IN (SELECT explanation_code FROM pc_configuration_parts))
        OR product_code::text IN (SELECT substring(offer_id from 2) FROM pc_configuration_offers
          WHERE offer_id ~ '^P[0-9]+$')''')).mappings()}
    history = {str(r['product_code']): dict(r) for r in conn.execute(text('''
        SELECT DISTINCT ON (product_code) product_code,old_price,new_price,
          changed_at AT TIME ZONE current_setting('TIMEZONE') AS changed_at
        FROM product_price_history WHERE field='sale' AND old_price IS DISTINCT FROM new_price
          AND product_code=ANY(:codes)
        ORDER BY product_code,changed_at DESC,history_id DESC'''),
        dict(codes=[int(code) for code in products])).mappings()}
    baselines = {r['configuration_id']: r['recorded_at'] for r in conn.execute(text('''
        SELECT c.configuration_id,coalesce((SELECT h.snapshot->>'updated_at'
          FROM pc_configuration_history h WHERE h.configuration_id=c.configuration_id
          ORDER BY h.revision LIMIT 1),c.updated_at::text) AS recorded_at
        FROM pc_configurations c''')).mappings()}
    return products, history, baselines


def instant(value):
    if not value: return None
    result = datetime.fromisoformat(str(value).replace('Z','+00:00'))
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def changes_for(config, parts, offers, explanations, products, history, baselines=None):
    alerts = []
    saved = config.get('content',{}).get('_review',{})
    # Only an approved review acknowledges intervening price-history events.
    baseline = instant(saved.get('at') if saved.get('state')=='approved'
        else (baselines or {}).get(config['configuration_id']))
    # Without a precise initial capture timestamp, do not turn same-day imports
    # into false "changed after capture" alerts. Direct price/status checks remain.
    seen = set()
    for part in parts:
        if part['pseudo']: continue
        explanation = explanations.get(part['explanation_code'],{})
        code = explanation.get('product_code')
        if code is None: continue  # assembly-only identities have no retail stock claim
        code = str(code)
        if code in seen: continue
        seen.add(code)
        product = products.get(code)
        if not product or product['status'] != '판매중':
            alerts.append(dict(kind='sale',code=code,label=f"부품 {code} · {product['status'] if product else 'DB 연결 없음'}"))
        event = history.get(code)
        if baseline and event and instant(event['changed_at']) > baseline:
            alerts.append(dict(kind='price_history',code=code,
                label=f"부품 {code} · DB 판매가 변경 이력 확인",
                old_price=event['old_price'],new_price=event['new_price'],changed_at=str(event['changed_at'])))
    for offer in offers:
        oid = offer['offer_id']; expected = None
        if re.fullmatch(r'P\d+',oid):
            product = products.get(oid[1:])
            if not product or product['status'] != '판매중':
                alerts.append(dict(kind='sale',code=oid,label=f"완제품 {oid} · {product['status'] if product else 'DB 연결 없음'}"))
            if product: expected = product['sale_price']
            label = '완제품 DB 판매가 · 옵션 기준 대조'
        elif config.get('content',{}).get('source')=='신규' and not offer.get('payload',{}).get('quote_only'):
            values = [explanations.get(p['explanation_code'],{}).get('sale_price') for p in parts if not p['pseudo']]
            if values and all(v is not None and v > 0 for v in values):
                expected = sum(explanations[p['explanation_code']]['sale_price']*p['quantity'] for p in parts if not p['pseudo']) + offer.get('payload',{}).get('assembly_fee_added',0)
            label = '현재 부품 합계 + 등록 조립비'
        else:
            # Modified bundle quotes use base price + delta, not retail component sums.
            continue
        if expected is not None and expected != offer['price_snapshot']:
            alerts.append(dict(kind='price',code=oid,label=label,
                saved_price=offer['price_snapshot'],current_price=expected))
    return alerts


def issue_groups(rows):
    groups = {}
    for row in rows:
        for issue in row.get('review_reasons',[]):
            # Unknown rules share a root label; keep exact evidence in product detail.
            key = issue.split(' · ')[0]
            if row.get('management_state')=='excluded': key += ' · 제외 사유 확인'
            group = groups.setdefault(key,dict(label=key,configurations=[]))
            if row['configuration_id'] not in group['configurations']:
                group['configurations'].append(row['configuration_id'])
    return sorted(groups.values(),key=lambda x:(-len(x['configurations']),x['label']))
