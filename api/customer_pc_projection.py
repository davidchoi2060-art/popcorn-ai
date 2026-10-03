"""Pure, fail-closed customer contract. No routes, I/O or publication decisions.

Callers must freshly load config/parts/review together, obtain an explicit public
permission, prepare the version-bound details contract, and call the existing
pc_sales_conditions.customer_conditions(config, parts, offers) for terms.values.
This module never imports the DB-backed source modules. It cannot establish that
inputs are fresh/authentic; that is the future server adapter's responsibility.
Publication/details/terms envelopes are proposed contracts, not existing DB rows.
"""
from collections.abc import Mapping
import re


_LABELS = {
    'os': '운영체제', 'keyboard': '키보드', 'mouse': '마우스',
    'monitor': '모니터', 'warranty': '보증·AS',
}


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _integer(value, minimum=None):
    return type(value) is int and (minimum is None or value >= minimum)


def _text(value):
    return value if isinstance(value, str) else None


def _bound(value, identity, revision, basis):
    value = _mapping(value)
    return (value.get('configuration_id') == identity
            and type(value.get('revision')) is int
            and value['revision'] == revision and value.get('basis') == basis)


def _gate(config, review, publication, details, terms):
    config, review = _mapping(config), _mapping(review)
    publication = _mapping(publication)
    identity, revision, basis = (config.get('configuration_id'),
                                 config.get('revision'), review.get('basis'))
    saved = _mapping(_mapping(config.get('content')).get('_review'))
    return (isinstance(identity, str) and bool(identity.strip())
            and _integer(revision, 1)
            and isinstance(basis, str) and re.fullmatch(r'[a-f0-9]{64}', basis) is not None
            and config.get('status') == 'approved'
            and saved.get('state') == 'approved' and saved.get('basis') == basis
            and review.get('state') == 'approved' and review.get('eligible') is True
            and review.get('customer_publishable') is True
            and publication.get('allowed') is True
            and all(_bound(v, identity, revision, basis)
                    for v in (review, publication, details, terms)))


def _description(value):
    value = _mapping(value)
    result = {key: _text(value.get(key)) for key in ('title', 'intro', 'scene')}
    result['benefits'] = [
        [pair[0], pair[1]] for pair in value.get('benefits', [])
        if isinstance(pair, (list, tuple)) and len(pair) == 2
        and all(isinstance(x, str) for x in pair)
    ] if isinstance(value.get('benefits'), (list, tuple)) else []
    result['checks'] = [x for x in value.get('checks', []) if isinstance(x, str)] \
        if isinstance(value.get('checks'), (list, tuple)) else []
    result['faq'] = [
        {'question': item['question'], 'answer': item['answer']}
        for item in value.get('faq', []) if isinstance(item, Mapping)
        and isinstance(item.get('question'), str) and isinstance(item.get('answer'), str)
    ] if isinstance(value.get('faq'), (list, tuple)) else []
    return result


def _parts(raw_parts, public_parts, identity):
    if not isinstance(raw_parts, (list, tuple)) or not raw_parts:
        return None
    if not isinstance(public_parts, (list, tuple)):
        return None
    by_ordinal = {}
    for item in public_parts:
        if not isinstance(item, Mapping) or not _integer(item.get('ordinal')):
            return None
        if item['ordinal'] in by_ordinal:
            return None
        by_ordinal[item['ordinal']] = item
    result, seen = [], set()
    for raw in raw_parts:
        if not isinstance(raw, Mapping):
            return None
        ordinal, slot, quantity = raw.get('ordinal'), raw.get('slot'), raw.get('quantity')
        if (raw.get('configuration_id') != identity or not _integer(ordinal)
                or ordinal in seen or not isinstance(slot, str) or not slot.strip()
                or not _integer(quantity, 1) or type(raw.get('pseudo')) is not bool
                or ordinal not in by_ordinal):
            return None
        seen.add(ordinal)
        public = by_ordinal[ordinal]
        # Ordinal is the existing part key; no invented stable line ID or slot map.
        item = {'ordinal': ordinal, 'slot': slot, 'quantity': quantity, 'pseudo': raw['pseudo'],
                'name': _text(public.get('name')), 'description': _text(public.get('description'))}
        specs = public.get('specs')
        item['specs'] = [
            {'label': s['label'], 'value': s['value']} for s in specs
            if isinstance(s, Mapping) and isinstance(s.get('label'), str)
            and isinstance(s.get('value'), str)
        ] if isinstance(specs, (list, tuple)) else []
        result.append(item)
    if seen != set(by_ordinal):
        return None
    return sorted(result, key=lambda item: item['ordinal'])


def _price(value):
    value = _mapping(value)
    confirmed = (value.get('state') == 'confirmed' and _integer(value.get('amount'), 1)
                 and isinstance(value.get('checked_at'), str) and bool(value['checked_at'].strip()))
    reference = value.get('state') in ('snapshot', 'estimated') and _integer(value.get('amount'), 1)
    state = 'confirmed' if confirmed else (value['state'] if reference else (
        'needs_reconfirmation' if value.get('state') == 'needs_reconfirmation' else 'unknown'))
    model = value.get('model')
    return {'state': state, 'amount': value['amount'] if confirmed or reference else None,
            'checked_at': value['checked_at'] if confirmed else None,
            'observed_date': _text(value.get('observed_date')) if reference else None,
            'model': model if model in ('bundle', 'new_parts_sum', 'derived_delta') else None}


def _terms(value):
    value = _mapping(value)
    result = {}
    for key, label in _LABELS.items():
        item = _mapping(value.get(key))
        stale = item.get('needs_reconfirmation') is True
        valid_flag = type(item.get('needs_reconfirmation')) is bool
        state, detail, months = item.get('state'), item.get('detail'), item.get('months')
        valid = (state == 'verified' and _integer(months, 1) and months <= 120
                 and isinstance(detail, str) and bool(detail.strip())) if key == 'warranty' else (
                     state in ('included', 'excluded') and isinstance(detail, str)
                     and (state != 'included' or bool(detail.strip())) and months is None)
        known = valid and valid_flag and not stale and isinstance(item.get('customer_statement'), str)
        unknown_statement = (f'{label} 포함 여부를 구매 전에 확인해 주세요.' if key != 'warranty'
                             else '보증·AS 조건을 구매 전에 확인해 주세요.')
        result[key] = {'state': state if known else 'unknown', 'detail': detail if known else '',
                       'months': months if known and key == 'warranty' else None,
                       'needs_reconfirmation': stale or (bool(item) and state != 'unknown' and not known),
                       'customer_statement': item['customer_statement'] if known else unknown_statement}
    return result


def project_configuration(config, parts, review, *, publication=None, details=None, terms=None):
    """Return {status:404,error:not_public} or {status:200,data:<allowlist>}.

details and terms must be bound to configuration_id/revision/basis. terms.values
is the existing safe converter output, not raw _sales_conditions or admin detail.
Price/stock/part presentation fields are normalized contract examples; no source
price mapping, freshness clock, stock authority or media policy is invented here.
No raw basis, operator, source, history, arbitrary content or private part IDs exit.
"""
    if not _gate(config, review, publication, details, terms):
        return {'status': 404, 'error': 'not_public'}
    projected_parts = _parts(parts, _mapping(details).get('parts'), config['configuration_id'])
    if projected_parts is None:
        return {'status': 404, 'error': 'not_public'}
    stock = _mapping(details.get('stock'))
    stock_state = stock.get('state')
    stock_checked = stock.get('checked_at')
    stock_known = (stock_state in ('available', 'unavailable')
                   and isinstance(stock_checked, str) and bool(stock_checked.strip()))
    compatibility = _mapping(details.get('compatibility'))
    document_state = compatibility.get('document_state')
    return {'status': 200, 'data': {
        'configuration_id': config['configuration_id'], 'revision': config['revision'],
        'offer_id': _text(details.get('offer_id')),
        'description': _description(details.get('description')), 'parts': projected_parts,
        'price': _price(details.get('price')),
        'stock': {'state': stock_state if stock_known else 'unknown',
                  'checked_at': stock_checked if stock_known else None},
        'compatibility': {'document_state': document_state if document_state in ('pass', 'fail') else 'unknown',
                          'public_summary': _text(compatibility.get('public_summary'))
                          if document_state in ('pass', 'fail') else None,
                          'assembly_state': 'unknown'},
        'customer_conditions': _terms(_mapping(terms).get('values')),
    }}
