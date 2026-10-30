"""고객 흐름 연결 읽기 — 관리자 세 화면이 같은 뜻으로 읽는다 (2026-10-18 관리자 정리 기획 1묶음).

관리자 「구매 상담 신청」·「고객 문의 · 보관 견적」·「인계 기록」이 고객 화면(mvp3)의 기록을
**같은 규칙**으로 읽게 한 곳에 둔다. 라우터가 없다(화면 모듈이 가져다 쓴다).

■ 지키는 것 (기획 README §1·§5 · 대표 승인 2026-10-18)
  · 명시적인 연결만 잇는다 — 방문자 번호(user_id) · 견적 번호(quote_id) · 인계 note 의
    `mvp3_quote_id` · 신청의 `configuration_id`. 같은 전화번호·이름·비슷한 시각으로 합치지 않는다.
  · 남기지 않은 것은 지어내지 않는다:
      보관 목적(직접 보관 / 이동용 보관)  저장하지 않는다 -> 「목적 미기록」
      상담 신청 접수 경로                  저장하지 않는다 -> quote_id 가 있어도 「접수 경로 미기록」
      팝콘PC 이동 이유                     저장하지 않는다 -> note 에 바꾼 부품이 있어도 「이동 이유 미기록」
      팝콘PC 구매 결과                     모른다 -> 「구매 결과 미확인」
  · 보관 견적 금액은 「현재 보관 견적 금액」이다 — 인계 때 쇼핑몰 가격으로 고쳐질 수 있어
    상담 신청 당시 확정 금액으로 소급해 부르지 않는다(api/mvp3_handoff).
  · 부품 단품가는 고객에게 다시 보이지 않는다. 관리자에게는 바꾼 부품의 전후 이름과 차액만 준다.
"""
import json

NO_PURPOSE = '목적 미기록'
NO_SOURCE = '접수 경로 미기록'
NO_REASON = '이동 이유 미기록'
NO_RESULT = '구매 결과 미확인'
QUOTE_PRICE_NOTE = '현재 보관 견적 금액 · 접수 당시 확정 금액 아님'

# 인계 한 건을 견적에 잇는 표시 — api/mvp3_handoff._marker 와 같은 모양이어야 한다(테스트가 대조한다).
def ho_for_quote_sql(quote_col):
    """보관 견적 하나에 걸린 가장 최근 mvp3 인계(LATERAL 서브쿼리 본문)."""
    return ("SELECT h.handoff_no, h.created_at FROM handoffs h WHERE h.quote_type = 'mvp3'"
            " AND {q} IS NOT NULL AND h.note LIKE '%\"mvp3_quote_id\": \"' || {q}::text || '\"%'"
            " ORDER BY h.handoff_id DESC LIMIT 1").format(q=quote_col)


def _int(v):
    return v if type(v) is int else None


def changes(snapshot):
    """보관 견적의 바꾼 부품 — 전후 이름 · 수량 · 차액만. 모양이 다르면 빈 목록(예전 보관 견적)."""
    build = (snapshot or {}).get('build')
    if not isinstance(build, dict) or not isinstance(build.get('changes'), list):
        return []
    out = []
    for c in build['changes']:
        if not isinstance(c, dict) or _int(c.get('delta')) is None:
            continue
        before, after = c.get('before') or {}, c.get('after') or {}
        out.append({'label': c.get('label') or c.get('slot'), 'before': before.get('name'), 'after': after.get('name'),
                    'quantity': _int(c.get('quantity')), 'delta': c['delta']})
    return out


def sets(snapshot):
    n = _int((snapshot or {}).get('sets'))
    return n if n and 1 <= n <= 10 else 1


def quote_view(snapshot):
    """보관 견적 요약 — PC 한 대 총액 · 대수 · 바꾼 부품 차액. 스냅숏이 없으면 None."""
    if not isinstance(snapshot, dict):
        return None
    ch = changes(snapshot)
    n = sets(snapshot)
    price = _int(snapshot.get('price'))
    return {'name': snapshot.get('name'), 'product_code': _int(snapshot.get('product_code')),
            'price': price, 'sets': n, 'total': price * n if price is not None else None,
            'ai_composed': snapshot.get('ai_composed') is True,
            'changes': ch, 'delta_sum': sum(c['delta'] for c in ch),
            'price_note': QUOTE_PRICE_NOTE, 'purpose': NO_PURPOSE}


def kind(snapshot=None, configuration_id=None, free_build=None, fixed_product=None):
    """구성 유형 — 서버가 저장한 표시만 읽는다. (key, 라벨)."""
    if isinstance(fixed_product, dict):     # /mvp4 AI 슈퍼컴퓨터 고정 완제품 문의(0165)
        return 'fixed_product', 'AI 슈퍼컴퓨터 완제품'
    if free_build:
        return 'free_build', '부품 직접 고르기'
    if isinstance(snapshot, dict):
        # /mvp4 AI 슈퍼컴퓨터 「견적에 저장」(2026-10-21 #373 · api/mvp3_saved_quotes.save_device) — 연락처 없이 장비만 보관한다.
        # 2026-10-31 전에는 이 표시를 읽지 않아 「쇼핑몰 완제품」으로 잘못 보였다(관리자단 개선 PR-1).
        if snapshot.get('kind') == 'ai_device':
            return 'ai_device', 'AI 슈퍼컴퓨터 장비'
        if snapshot.get('ai_composed') is True:
            return 'ai_composed', '팝콘AI 구성'
        return 'mall', '쇼핑몰 완제품'
    if configuration_id:
        return 'configuration', '새로 구성된 PC'
    return None, '상품 연결 없음'


def link_label(quote_id=None, configuration_id=None):
    """신청이 무엇에 이어져 있나 — 접수 경로는 남기지 않으므로 함께 밝힌다."""
    if quote_id:
        return '견적 연결 있음 · ' + NO_SOURCE
    if configuration_id:
        return '새로 구성된 PC 연결 · ' + NO_SOURCE
    return '연결 자료 없음'


def handoff_note(raw):
    """mvp3 인계 note(JSON 문자열) -> 견적 번호 · 대수 · 바꾼 부품. 읽지 못하면 빈 값."""
    try:
        note = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        note = None
    if not isinstance(note, dict) or note.get('source') != 'mvp3':
        return None
    build = note.get('build') if isinstance(note.get('build'), dict) else {}
    ch = [{'label': c.get('label') or c.get('slot'), 'before': (c.get('before') or {}).get('name'),
           'after': (c.get('after') or {}).get('name'), 'delta': c['delta']}
          for c in (build.get('changes') or []) if isinstance(c, dict) and _int(c.get('delta')) is not None]
    qid = note.get('mvp3_quote_id')
    return {'quote_id': qid if isinstance(qid, str) else None,
            'sets': sets(note), 'changes': ch, 'delta_sum': sum(c['delta'] for c in ch),
            'reason': NO_REASON, 'result': NO_RESULT}


def digits(v):
    return ''.join(ch for ch in (v or '') if ch.isdigit())
