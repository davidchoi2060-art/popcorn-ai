"""신규 조립PC 고객 공개 · 공개 중지 — 관리자 API (2026-10-11 부품 상품화 4단계).

「신규 조립PC 생성」 화면 아래 「고객 공개」 목록이 쓴다. 판정은 `api/custom_pc.py` 한 곳이다.

  GET  /api/admin/pc-releases                     신규 조립PC 목록 + 공개 점검 + 공개 상태
  POST /api/admin/pc-releases/{id}/release        고객 공개 (점검 통과 · 화면에서 본 가격과 같을 때만)
  POST /api/admin/pc-releases/{id}/withdraw       공개 중지 (사유 필수 · 지우지 않고 한 줄 더한다)
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text

from . import custom_pc
from .admin_pc_builder import permission
from .db import engine
from .pc_configuration_review import load_review

router = APIRouter()



class ReleaseBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_price: StrictInt = Field(gt=0)
    note: str = Field(default='', max_length=500)


class WithdrawBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=500)


def gate(conn, config, latest, state):
    """공개 전 점검. blockers 가 비어야 공개할 수 있다. notes 는 막지 않는 안내다."""
    review = load_review(conn, config['configuration_id'])[3]
    blockers, notes = list(state['problems']), []
    if config['status'] == 'retired':
        blockers.append('보관된 제품군')
    if not review['eligible']:
        blockers.append('구성 검토 승인 필요' + (' (가격·부품 자료가 바뀌어 다시 검토해야 함)' if review['state'] == 'stale' else ''))
    intro = (config['content'] or {}).get('intro') or ''
    if not intro.strip() or intro.startswith(custom_pc.PLACEHOLDER_INTRO):
        blockers.append('고객에게 보일 상품 소개 문구 작성 필요')
    if state['compat']['unknown']:
        notes.append(f"DB 사양으로 판정하지 못한 호환 항목 {len(state['compat']['unknown'])}건 · 검토 승인 때 확인한 근거를 따릅니다")
    missing_copy = sum(1 for p in state['parts'] if not p['explanation_approved'])
    if missing_copy:
        notes.append(f'부품 설명 승인 전 {missing_copy}개 · 고객 화면에는 부품 이름만 보입니다')
    missing_photo = sum(1 for p in state['parts'] if not p['has_photo'])
    if missing_photo:
        notes.append(f'부품 사진 없음 {missing_photo}개 · 고객 화면에는 사진을 싣지 않습니다')
    return dict(blockers=list(dict.fromkeys(blockers)), notes=notes, review_state=review['state'])


def row(conn, config, latest, state):
    live = custom_pc.is_live_release(config, latest)
    released = bool(latest and latest['action'] == 'release')
    return dict(configuration_id=config['configuration_id'], title=(config['content'] or {}).get('title'),
                revision=config['revision'], status=config['status'],
                release_state='public' if live and state['ok'] else 'hidden' if released else 'not_released',
                release_hidden_reason=None if not released or (live and state['ok']) else
                    ('구성이 공개 뒤 바뀜 · 다시 공개해야 함' if not live else ' / '.join(state['problems'])),
                last_event=None if not latest else dict(event_id=latest['event_id'], action=latest['action'],
                    at=latest['created_at'].isoformat(), price_at_release=latest['price_at_release'], note=latest['note']),
                price=state['price'], subtotal=state['subtotal'], assembly_fee=state['assembly_fee'],
                parts=state['parts'], compat=dict(ok=state['compat']['ok'], failures=state['compat']['failures'],
                                                  unknown=len(state['compat']['unknown'])),
                check=gate(conn, config, latest, state))


@router.get('/api/admin/pc-releases')
def list_releases():
    with engine.connect() as conn:
        return dict(ok=True, items=[row(conn, *x) for x in custom_pc.load(conn)], price_note=custom_pc.PRICE_NOTE)


def _one(conn, identity):
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('custom_pc_release:' || :id))"), dict(id=identity))
    found = custom_pc.load(conn, [identity])
    if not found:
        raise HTTPException(404, '신규 조립PC 생성에서 만든 제품군이 아닙니다.')
    return found[0]


def release_one(conn, identity, body, actor):
    config, latest, state = _one(conn, identity)
    if custom_pc.is_live_release(config, latest):
        raise HTTPException(409, '이미 고객에게 공개된 제품군입니다.')
    check = gate(conn, config, latest, state)
    if check['blockers']:
        raise HTTPException(422, '공개 전 보완 필요: ' + ' / '.join(check['blockers']))
    if state['price'] != body.expected_price:
        raise HTTPException(409, f"부품 판매가가 바뀌어 지금 가격은 {state['price']:,}원입니다. 목록을 새로 열어 확인해 주세요.")
    event = conn.execute(text('''INSERT INTO custom_pc_release_events
        (configuration_id, action, revision, bom_fingerprint, price_at_release, note, operator_id)
        VALUES (:id, 'release', :rev, :bom, :price, :note, :op) RETURNING event_id'''),
        dict(id=identity, rev=config['revision'], bom=config['bom_fingerprint'], price=state['price'],
             note=body.note.strip() or None, op=actor['operator_id'])).scalar()
    return dict(ok=True, configuration_id=identity, event_id=event, price=state['price'],
                note=f"고객 공개 완료 · {state['price']:,}원")


def withdraw_one(conn, identity, body, actor):
    config, latest, state = _one(conn, identity)
    if not latest or latest['action'] != 'release':
        raise HTTPException(409, '공개 중인 기록이 없습니다.')
    event = conn.execute(text('''INSERT INTO custom_pc_release_events
        (configuration_id, action, revision, bom_fingerprint, ref_event_id, note, operator_id)
        VALUES (:id, 'withdraw', :rev, :bom, :ref, :note, :op) RETURNING event_id'''),
        dict(id=identity, rev=config['revision'], bom=config['bom_fingerprint'], ref=latest['event_id'],
             note=body.reason.strip(), op=actor['operator_id'])).scalar()
    return dict(ok=True, configuration_id=identity, event_id=event, note='고객 공개 중지 완료')


@router.post('/api/admin/pc-releases/{identity}/release')
def release(identity: str, body: ReleaseBody, request: Request):
    actor = permission(request)
    with engine.begin() as conn:
        return release_one(conn, identity, body, actor)


@router.post('/api/admin/pc-releases/{identity}/withdraw')
def withdraw(identity: str, body: WithdrawBody, request: Request):
    actor = permission(request)
    with engine.begin() as conn:
        return withdraw_one(conn, identity, body, actor)
