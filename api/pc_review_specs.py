"""Resolve source-bound assembly-only facts for administrative BOM review.

Retail products always use public.product_specs. These facts do not create retail
availability, price, approval, or a second compatibility rule engine.
"""
from .part_explanations import fingerprint


def specs_for_review(rows, by_product):
    result = {}
    for code, row in rows.items():
        if row.get('product_code') is not None:
            result[code] = by_product.get(row['product_code'], {})
            continue
        content = row.get('content') or {}
        evidence = content.get('review_specs') or {}
        snapshot = row.get('source_snapshot') or {}
        source_hash = fingerprint(snapshot.get('name'), snapshot.get('spec'))
        sources = {s['id'] for s in content.get('sources', [])
                   if s.get('id') and s.get('kind') == 'manufacturer' and s.get('url', '').startswith('https://')}
        if (content.get('availability_scope') != 'assembly_only' or not snapshot
                or source_hash != row.get('source_fingerprint')
                or evidence.get('source_fingerprint') != source_hash
                or evidence.get('source_id') not in sources):
            result[code] = {}
            continue
        fields = evidence.get('fields') or {}
        slot = content.get('slot')
        allowed = {'CPU': {'socket', 'tdp_watt', 'cpu_gpu'},
                   'MB': {'socket', 'mem_type', 'form_factor'}}.get(slot, set())
        spec = {'part_type': slot} if allowed else {}
        for field in allowed:
            value = fields.get(field)
            if field == 'tdp_watt':
                valid = type(value) is int and 0 < value <= 1000
            elif field == 'cpu_gpu':
                valid = type(value) is bool
            else:
                valid = isinstance(value, str) and 0 < len(value) <= 40
            if valid:
                spec[field] = value
        result[code] = spec
    return result
