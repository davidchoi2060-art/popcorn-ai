"""Read-only administrative evidence summary; never grants sale/publication approval."""
from urllib.parse import quote

from .pc_configuration_copy import catalog_rows, read_configuration
from .pc_configuration_edit import description_complete


STATE_LABELS = {
    'needs_work': '등록 근거 보완 필요',
    'needs_check': '판매 준비 미확인',
    'basis_met': '등록 근거 충족',
    'excluded': '추천 대상 제외',
}
SALES_LABELS = {
    'os': '운영체제', 'keyboard': '키보드', 'mouse': '마우스',
    'monitor': '모니터', 'warranty': '보증·AS',
}


def _project(row, *, review=None, terms=None):
    identity = str(row['configuration_id'])
    href = '/admin2/pc-workspace?id=' + quote(identity, safe='')
    reasons, checks = [], []

    def reason(key, label, detail, severity='unknown'):
        reasons.append(dict(key=key, label=label, detail=detail,
                            href=href, severity=severity))

    def check(key, label, state, detail):
        checks.append(dict(key=key, label=label, state=state, detail=detail))

    excluded = (row.get('status') == 'retired'
                or row.get('management_state') == 'excluded'
                or (review is not None and review.get('state') == 'revoked'))
    if excluded:
        reason('excluded', '추천 대상 제외',
               '보관 또는 현재 추천 제외 판정입니다. 판매·출고 판정은 별도입니다.', 'blocker')

    part_count = row.get('part_count')
    affected = row.get('affected_parts') or []
    if part_count == 0:
        check('parts', '구성 부품', 'blocked', '등록된 구성 부품이 없습니다.')
        reason('parts', '구성 부품 등록 필요', '기존 구성 화면에서 부품을 확인해 주세요.', 'blocker')
    elif affected:
        check('parts', '구성 부품', 'unknown', '연결 부품 정보 또는 설명의 변경 확인이 필요합니다.')
        reason('parts', '부품 정보 확인 필요',
               '현재 부품 근거에 확인 항목이 있습니다. 추천·조립 단계의 구분은 검토 화면에서 확인해 주세요.')
    elif isinstance(part_count, int) and part_count > 0:
        check('parts', '구성 부품', 'met',
              '구성 부품이 등록되어 있습니다. 실제 장착·재고·출고 확인은 별도입니다.')
    else:
        check('parts', '구성 부품', 'unknown', '등록 부품 근거를 확인하지 못했습니다.')
        reason('parts', '구성 부품 미확인', '기존 구성 상세에서 확인해 주세요.')

    description_ready = row.get('description_ready')
    if description_ready is True:
        check('description', '상품 설명', 'met',
              '기존 설명 등록 요건을 충족합니다. 문구 전체의 사실검증 완료를 뜻하지 않습니다.')
    elif description_ready is False:
        check('description', '상품 설명', 'blocked', '상품 설명 또는 실부품 역할 설명 보완이 필요합니다.')
        reason('description', '상품·부품 설명 보완', '기존 상품 설명과 부품 설명을 확인해 주세요.', 'blocker')
    else:
        check('description', '상품 설명', 'unknown', '설명 등록 요건을 확인하지 못했습니다.')
        reason('description', '상품 설명 미확인', '기존 상품 설명 화면에서 확인해 주세요.')

    alerts = row.get('market_alerts') or []
    for index, alert in enumerate(alerts):
        reason('market:' + str(index), '가격·판매 조건 확인',
               alert['label'], 'blocker')
    check('price', '판매가격', 'unknown',
          '등록 가격은 저장 시점의 참고가격입니다. 현재 실판매가격 확정 근거가 아닙니다.')
    reason('price', '현재 판매가격 미확인',
           '가격·판매 경고가 없어도 현재 실판매가격 확정을 뜻하지 않습니다.')
    check('stock', '판매 가능 재고', 'unknown', '구성PC 정본에는 현재 가용 재고 확인 결과가 없습니다.')
    reason('stock', '판매 가능 재고 미확인', '판매중 상태와 실제 가용 재고는 별개입니다.')

    review_state = review.get('state') if review is not None else row.get('review_state')
    blockers = review.get('blockers', []) if review is not None else []
    if review is not None:
        for index, blocker in enumerate(blockers):
            reason('review:blocker:' + str(index), '추천 검토 전 보완', blocker, 'blocker')
        seen = set()
        for index, item in enumerate(review.get('checks', [])):
            seen.add(item.get('key'))
            check('review:check:' + str(index), item['label'],
                  {'pass': 'met', 'fail': 'blocked'}.get(item.get('state'), 'unknown'), item['detail'])
            if item.get('state') == 'unknown' and item.get('stage') == 'recommendation':
                reason('review:unknown:' + str(index), item['label'], item['detail'])
        for index, item in enumerate(review.get('assembly_checks', [])):
            if item.get('key') not in seen:
                check('assembly:check:' + str(index), item['label'],
                      {'pass': 'met', 'fail': 'blocked'}.get(item.get('state'), 'unknown'), item['detail'])
    else:
        # Bulk rows contain rendered reasons, not their structured blocker/stage data.
        for index, detail in enumerate(row.get('review_reasons') or []):
            reason('review:source:' + str(index), '현재 추천 검토 사유', detail)

    eligible = (review.get('eligible') is True if review is not None
                else review_state == 'approved')
    if eligible:
        check('review', '추천 검토', 'met', '현재 추천 검토 승인 기록이 유효합니다. 판매·공개 승인은 별도입니다.')
    elif review_state in ('stale', 'pending', 'revoked') or blockers or row.get('management_state') == 'hold':
        check('review', '추천 검토', 'blocked', '현재 추천 검토의 보완 또는 승인 기록 확인이 필요합니다.')
        reason('review', '추천 검토 확인 필요',
               '현재 구성·가격·설명·근거 기준으로 검토를 다시 확인해 주세요.', 'blocker')
    else:
        check('review', '추천 검토', 'unknown', '현재 유효한 추천 검토 승인을 확인하지 못했습니다.')
        reason('review', '추천 검토 승인 미확인', '추천 가능 후보와 검토 승인 여부는 별개입니다.')
    if row.get('needs_review') is True:
        reason('review:changes', '현재 정보 확인 필요',
               '가격·설명·부품·구성 변경 또는 검토 항목을 상세에서 확인해 주세요.')

    if terms is None:
        check('sales_conditions', '판매조건', 'unknown', '목록에는 판매조건 판정이 없습니다. 상품 상세에서 확인해 주세요.')
        reason('sales_conditions', '판매조건 상세 확인 필요',
               '운영체제·주변기기 포함 여부와 보증을 목록 정보만으로 추정하지 않습니다.')
    else:
        for key, label in SALES_LABELS.items():
            item = terms.get(key) or {}
            state = item.get('state')
            known = (not item.get('stale') and
                     state in (('verified',) if key == 'warranty' else ('included', 'excluded')))
            if known:
                check('sales:' + key, label, 'met', item['customer_statement'])
            else:
                detail = '현재 구성 기준 재확인이 필요합니다.' if item.get('stale') else '확인된 판매조건 근거가 없습니다.'
                check('sales:' + key, label, 'unknown', detail)
                reason('sales:' + key, label + (' 재확인' if item.get('stale') else ' 미확인'), detail)

    check('publication', '고객 공개', 'unknown',
          '현재 구성PC 응답은 비공개입니다. 추천 검토 승인과 별도의 공개 허용 근거가 필요합니다.'
          if row.get('customer_publishable') is False else '별도의 고객 공개 허용 정본을 확인하지 못했습니다.')
    reason('publication', '고객 공개 별도 확인', '이 요약은 고객 공개 상태를 변경하거나 판매를 승인하지 않습니다.')
    check('assembly', '실제 조립·출고', 'unknown', '추천 규격 대조와 실제 조립·출고 검수는 별개입니다.')
    reason('assembly', '실제 조립·출고 미확인', '등록 근거만으로 실조립·부하 검사·출고 완료를 판단하지 않습니다.')

    state = ('excluded' if excluded else 'needs_work' if any(r['severity'] == 'blocker' for r in reasons)
             else 'needs_check' if any(c['state'] == 'unknown' for c in checks) else 'basis_met')
    return dict(id=identity, name=row.get('title') or identity, code=identity,
                state=state, state_label=STATE_LABELS[state], reasons=reasons,
                checks=checks, href=href)


def list_configurations(conn):
    """One canonical bulk read; never obtains each item's detail separately."""
    return [_project(row) for row in catalog_rows(conn)]


def detail_configuration(conn, identity):
    """One selected canonical detail read; propagate its existing 404 unchanged."""
    detail = read_configuration(conn, identity)
    content, parts = detail['content'], detail['parts']
    row = dict(detail, title=content.get('title', ''),
               part_count=sum(not part['pseudo'] for part in parts),
               description_ready=bool(description_complete(content) and parts) and all(
                   part['pseudo'] or bool(part.get('explanation', {}).get('role')) for part in parts))
    return _project(row, review=detail['current_review'], terms=detail['sales_conditions'])
