"""ADM-CUS-010 회원 관리 — 자체 회원 원장 읽기 + 쇼핑몰 계정 매핑 요청(쓰기 1종).

매핑 상태 3종(스키마가 요구하는 정직 확장 — 목업은 2상태였음):
  mapped    = mall_member_id 존재(매핑 완료)
  requested = mall_map_requested_at만 존재(DB 요청 기록 — 외부 전달 여부 미확인)
  none      = 미연결
관리자 임의 연결 ID 쓰기는 범위 밖. 고객 동의 경로는 my_account에 구현되어 있으나
ID는 데모 규칙으로 발급되므로 실몰 검증/동기화 완료를 뜻하지 않는다.
요청은 운영 모드와 무관하게 DB 시각과 원장만 저장한다. 이메일 발송 경로가 아니다.
현행 고객 화면의 안내 진입은 별도 담당 범위이며 도착을 보장하지 않는다.
이메일 원문 노출(사용자 확정 — 기존 관리자 화면 정합, 마스킹은 실 인증·권한 체계 시 재결정).
consults는 직접 member_id 귀속분만 집계. recommend가 member_id NULL을 저장하므로
0건을 익명 방문자 상담 이력 전체의 부재로 판정하지 않는다.
note는 서버 파생 문장(손글 서술 저장처 없음). 이관: 회원 딥링크·status UI·검색/페이지네이션.
"""
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Path
from sqlalchemy import text

from .timeutil import iso, now_iso
from .admin_orders import _log
from .db import engine
# 세션 조회 술어(「어느 세션을 포함하는가」) 단일 원천 — U-34 대응, 그 파일 docstring 참조.
from .session_scope import session_scope_where, scope_note

router = APIRouter(prefix="/api/admin")

# ⚠ 2026-08-15 점검자 실측(members 전수 SELECT joined_via, count(*)) — "google"이
# 빠져 있었다(회원 1명이 영문 "google" 그대로 노출). 전수 조회로 다른 값(email·kakao·
# naver)엔 누락이 없음을 함께 확인했다.
VIA_KO = {"email": "이메일", "kakao": "카카오", "naver": "네이버", "google": "구글"}


def _note(r) -> str:
    parts = []
    if r["mall_member_id"]:
        parts.append(f"쇼핑몰 연결 ID 기록 — {r['mall_member_id']} · 실몰 검증 정보 없음")
    elif r["requested_at"]:
        parts.append("연결 요청 기록 — 외부 전달 여부 미확인")
    else:
        parts.append("쇼핑몰 계정 미연결 — 연결 요청 기록 없음")
    if r["alerts"]:
        parts.append(f"가격 알림 {r['alerts']}건 활성")
    if r["orders"]:
        parts.append(f"주문 {r['orders']}건")
    return " · ".join(parts)


@router.get("/members")
def list_members():
    with engine.connect() as conn:
        rows = conn.execute(text(_select_sql(extended=False) + ' ORDER BY m.member_id')).mappings().all()
        mode = _member_mode(conn)
    items = [_item(r, extended=False) for r in rows]
    # 2026-08-15 추가 — VIA_KO에 없어 원문이 그대로 노출되는 joined_via. 기존 필드는
    # 그대로 두고 **추가만** 한다 — 새 가입 경로(예: 애플 로그인)가 조용히 영문으로
    # 새는 것을 다음에는 이 필드로 알아챈다("google" 1건이 3주 넘게 몰랐던 것과 같은
    # 재발 방지).
    unmapped_via = sorted({r["joined_via"] for r in rows if r["joined_via"] not in VIA_KO})
    return {"items": items, "member_mode": mode, "unmapped_via": unmapped_via}


def _select_sql(*, extended: bool = True) -> str:
    """The legacy activity population, with extra read-only member facts."""
    extra = 'm.status, m.last_login_at, m.user_id, m.data_origin,' if extended else ''
    return f"""
        SELECT m.member_id, m.nickname, m.email, m.joined_via, m.created_at,
               {extra}
               m.mall_member_id, m.mall_map_requested_at AS requested_at,
               COALESCE(o.cnt,0) AS orders, o.last_at AS o_last,
               COALESCE(c.cnt,0) AS consults, c.last_at AS c_last,
               COALESCE(r.cnt,0) AS reviews, r.last_at AS r_last,
               COALESCE(f.cnt,0) AS favs, COALESCE(f.alerts,0) AS alerts, f.last_at AS f_last
        FROM members m
        LEFT JOIN (SELECT member_id, COUNT(*) cnt, MAX(created_at) last_at
                   FROM orders GROUP BY member_id) o USING (member_id)
        LEFT JOIN (SELECT member_id, COUNT(*) cnt, MAX(created_at) last_at
                   FROM consult_sessions s WHERE {session_scope_where()} AND s.member_id IS NOT NULL
                   GROUP BY member_id) c USING (member_id)
        LEFT JOIN (SELECT member_id, COUNT(*) cnt, MAX(created_at) last_at
                   FROM member_reviews GROUP BY member_id) r USING (member_id)
        LEFT JOIN (SELECT member_id, COUNT(*) cnt,
                          COUNT(*) FILTER (WHERE price_alert) alerts, MAX(created_at) last_at
                   FROM member_favorites GROUP BY member_id) f USING (member_id)
    """


def _item(r, *, extended: bool = True) -> dict:
    last = max((t for t in (r['o_last'], r['c_last'], r['r_last'], r['f_last']) if t), default=None)
    item = {
        'id': r['member_id'], 'name': r['nickname'], 'email': r['email'],
        'via': VIA_KO.get(r['joined_via'], r['joined_via']), 'joined': iso(r['created_at']),
        'map_state': 'mapped' if r['mall_member_id'] else ('requested' if r['requested_at'] else 'none'),
        'mall_id': r['mall_member_id'], 'requested_at': iso(r['requested_at']),
        'orders': r['orders'], 'consults': r['consults'], 'reviews': r['reviews'],
        'favs': r['favs'], 'alerts': r['alerts'], 'last': iso(last), 'note': _note(r),
    }
    if extended:
        item.update(via_code=r['joined_via'], status=r['status'],
                    last_login_at=iso(r['last_login_at']), visitor_linked=r['user_id'] is not None,
                    data_origin=r['data_origin'])
    return item


def _member_mode(conn) -> str:
    return dict(conn.execute(text('SELECT key, mode FROM ops_settings')).all()).get('member', 'own')


def _metric_notes() -> dict:
    return {
        'consults': '회원번호에 직접 귀속된 상담만 집계. 익명 방문자 상담 전체와 별도. ' + scope_note(),
        'orders': '자체 주문 원장 전체 상태의 기록 수. 실구매 완료 수 및 외부 쇼핑몰 주문 수와 별도.',
        'reviews': '게시·숨김 등 모든 상태의 후기 기록 수.',
        'alerts': '가격 알림 설정 수. 실제 발송 및 전달 성공 횟수와 별도.',
        'last': '주문·회원 귀속 상담·후기·관심 부품의 최근 생성 시각. 로그인 및 설정 변경 시각과 별도.',
        'via': '저장된 가입 경로. OAuth 인증 완료 증거와 별도.',
    }


@router.get('/members/search')
def search_members(
    q: Annotated[str, Query(max_length=100)] = '',
    via: Annotated[str | None, Query(max_length=20)] = None,
    map_state: Literal['', 'none', 'requested', 'mapped'] = '',
    status: Annotated[str | None, Query(max_length=20)] = None,
    sort: Literal['joined_desc', 'id_asc', 'activity_desc'] = 'joined_desc',
    page: Annotated[int, Query(ge=1, le=10000000)] = 1,
    page_size: Annotated[int, Query(ge=10, le=50)] = 20,
):
    if page_size not in (10, 20, 50):
        raise HTTPException(422, '표시 수는 10, 20, 50만 지원합니다')
    where, params = [], {}
    query = q.strip()
    if query:
        params['q'] = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        match = "(m.nickname ILIKE :q ESCAPE '\\' OR m.email ILIKE :q ESCAPE '\\')"
        if query.isascii() and query.isdigit() and int(query) <= 9223372036854775807:
            params['member_id'] = int(query)
            match = 'm.member_id=:member_id'
        where.append(match)
    if via is not None:
        where.append('m.joined_via=:via'); params['via'] = via
    if status is not None:
        where.append('m.status=:status'); params['status'] = status
    conditions = {
        'mapped': "NULLIF(m.mall_member_id, '') IS NOT NULL",
        'requested': "NULLIF(m.mall_member_id, '') IS NULL AND m.mall_map_requested_at IS NOT NULL",
        'none': "NULLIF(m.mall_member_id, '') IS NULL AND m.mall_map_requested_at IS NULL",
    }
    if map_state:
        where.append(conditions[map_state])
    predicate = ' AND '.join('(' + clause + ')' for clause in where) or 'TRUE'
    ordering = {
        'joined_desc': 'm.created_at DESC, m.member_id DESC',
        'id_asc': 'm.member_id ASC',
        'activity_desc': 'GREATEST(o.last_at,c.last_at,r.last_at,f.last_at) DESC NULLS LAST, m.member_id DESC',
    }[sort]
    # A single snapshot keeps total, page and global filter metadata consistent.
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        total = conn.execute(text('SELECT COUNT(*) FROM members m WHERE ' + predicate), params).scalar_one()
        rows = conn.execute(text(_select_sql() + ' WHERE ' + predicate + ' ORDER BY ' + ordering
                                 + ' LIMIT :limit OFFSET :offset'),
                            {**params, 'limit': page_size, 'offset': (page-1)*page_size}).mappings().all()
        filters = conn.execute(text('SELECT DISTINCT joined_via, status FROM members ORDER BY joined_via, status')).all()
        mode = _member_mode(conn)
    vias = sorted({v for v, _ in filters})
    return {'items': [_item(r) for r in rows], 'total': total, 'page': page, 'page_size': page_size,
            'member_mode': mode, 'unmapped_via': [v for v in vias if v not in VIA_KO],
            'available_filters': {'via': vias, 'status': sorted({s for _, s in filters})},
            'metric_notes': _metric_notes(), 'generated_at': now_iso()}


@router.get('/members/{member_id}')
def member_detail(member_id: Annotated[int, Path(ge=1)]):
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        row = conn.execute(text(_select_sql() + ' WHERE m.member_id=:id'), {'id': member_id}).mappings().first()
        if row is None:
            raise HTTPException(404, '회원이 없습니다')
        mode = _member_mode(conn)
    return {'member': _item(row), 'member_mode': mode, 'metric_notes': _metric_notes(),
            'mapping_evidence': {'source': 'members_ledger', 'request_delivery': 'not_verified',
                                 'mall_verification': 'not_verified'}}


@router.post("/members/{member_id}/map-request")
def map_request(member_id: int):
    with engine.begin() as conn:
        m = conn.execute(text(
            "SELECT member_id, nickname, mall_member_id, mall_map_requested_at FROM members"
            " WHERE member_id=:i FOR UPDATE"), {"i": member_id}).mappings().first()
        if m is None:
            raise HTTPException(404, "회원이 없습니다")
        if m["mall_member_id"]:
            raise HTTPException(409, "이미 쇼핑몰 계정이 매핑된 회원입니다")
        if m["mall_map_requested_at"]:
            raise HTTPException(409, "이미 연결 요청 기록이 있는 회원입니다")
        requested_at = conn.execute(text(
            "UPDATE members SET mall_map_requested_at=now() WHERE member_id=:i"
            " RETURNING mall_map_requested_at"), {"i": member_id}).scalar_one()
        mode = dict(conn.execute(text("SELECT key, mode FROM ops_settings")).all()).get("member", "own")
        log_id = _log(conn, "member_map_request", str(member_id),
                      {"member_id": member_id, "nickname": m["nickname"],
                       "before": {"mall_map_requested_at": None},
                       "after": {"mall_map_requested_at": iso(requested_at)}}, kind="member")
        return {"ok": True, "undo_id": log_id, "member_mode": mode,
                "requested_at": iso(requested_at)}


@router.post("/members/map-request/undo/{log_id}")
def undo_map_request(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if log is None or log["action"] != "member_map_request":
            raise HTTPException(404, "되돌릴 연결 요청 기록이 없습니다")
        d = log["detail"]
        m = conn.execute(text(
            "SELECT mall_member_id, mall_map_requested_at FROM members WHERE member_id=:i FOR UPDATE"),
            {"i": d["member_id"]}).mappings().first()
        if m is None or m["mall_member_id"] or m["mall_map_requested_at"] is None:
            raise HTTPException(409, "요청 이후 상태가 변경되어 되돌릴 수 없습니다")
        if conn.execute(text(
                "SELECT 1 FROM admin_operator_activity_logs"
                " WHERE action='member_map_request_undo' AND (detail->>'ref_log_id')::int=:i LIMIT 1"),
                {"i": log_id}).first():
            raise HTTPException(409, "이미 되돌린 요청 기록입니다")
        # Member row lock serializes request/undo. Legacy logs have no timestamp;
        # latest-log identity still prevents undo A from deleting a later request B.
        latest = conn.execute(text(
            "SELECT log_id FROM admin_operator_activity_logs WHERE action='member_map_request'"
            " AND target_kind='member' AND target_id=:member ORDER BY log_id DESC LIMIT 1"),
            {'member': str(d['member_id'])}).scalar()
        expected = (d.get('after') or {}).get('mall_map_requested_at')
        if latest != log_id or (expected is not None and expected != iso(m['mall_map_requested_at'])):
            raise HTTPException(409, '현재 요청과 다른 기록입니다 — 최신 상태를 다시 확인해 주세요')
        conn.execute(text(
            "UPDATE members SET mall_map_requested_at=NULL WHERE member_id=:i"), {"i": d["member_id"]})
        _log(conn, "member_map_request_undo", str(log_id),
             {"ref_log_id": log_id, "member_id": d["member_id"]}, kind="member")
        return {"ok": True}
