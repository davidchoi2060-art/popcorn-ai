# -*- coding: utf-8 -*-
"""웹 사양 채움 — 진행 조회 (읽기 전용 · ADM-AI-020, 1a안 재구축 2026-08-15).

■ 이 모듈이 하는 일 — **집계 SELECT 뿐이다**
  `/admin2/spec-fill` 화면의 실행 상태·정본 반영 경고·실행 원장·통계 카드·최근 제안
  표가 쓰는 유일한 API 모듈. 근거: `docs/design/spec-spec-fill.md`(1a안, 사장님 확정
  2026-08-15), 요구사항 `docs/design/req/req-spec-fill.md`.

■ 이 모듈이 하지 않는 일 — 정본을 복제하지 않는다
  · **실행**은 여기 없다. 화면의 [웹 사양 채움 실행] 버튼은 기존 대시보드 큐
    (`POST /api/admin/dash/say`, `api/dash.py` — 이 작업 담당 밖)에 구조화된 메시지를
    넣을 뿐이고, 감시자→하네스→채움 담당(specfiller)→`tools/spec_fill_apply.py`로
    이어지는 기존 체인을 그대로 탄다. 그 체인은 **사람이 큐를 읽어 판단해야** 다음
    단계로 넘어간다(`api/dash.py`의 `say()` docstring이 이미 이 한계를 적어 뒀다) —
    그래서 이 화면은 "실행 완료"를 주장하지 않는다(아래 `/runs` 참조).
  · **승인**도 여기 없다. `product_specs`에 값을 반영하는 것은 검수 화면(ADM-PRD-020,
    `api/admin_reviews._approve`)만 한다(A-18 계약과 동일선상) — 이 모듈은
    `product_reviews`·`product_specs`에 쓰지 않는다.
  · **사양 항목의 정의**도 여기 없다. `spec_field_defs`는 `spec_fields`/
    `admin_spec_fields.py`가 정본이고, 이 모듈은 조회만 한다(화면이 다시 정의하지 않는다).

■ `spec_fill_runs`(실행 원장)는 아직 스키마조차 없다
  마이그레이션 `db/migrations/versions/0052_spec_fill_runs.py`가 테이블을 정의하지만
  **파일만 있고 DB에 적용되지 않았다**(권한 분류기가 `alembic upgrade`를 막고 있다 —
  마이그레이션 0051과 같은 상태). `api/auth.py`의 `_schema_ready()`와 같은 방식으로
  `_runs_table_ready()`가 매 요청 존재를 확인하고, 없으면 `ok:false` + "실행 원장 신설
  필요"를 돌려준다 — **"0건"으로 지어내지 않는다.**
"""
from fastapi import APIRouter
from sqlalchemy import text

from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin/spec-fill", tags=["admin-spec-fill"])

# 정본에 실제로 반영된 검수 상태 — api/admin_reviews.py `_approve()` 실측(승인·수정만
# product_specs에 쓴다. '처리'는 다른 경로(예: 재적재)로 값이 채워져 이 검수 행이
# 더는 필요 없어졌다는 뜻이라 "이 제안이 반영됐다"와 다른 사실이다 — 섞지 않는다).
APPLIED_STATUSES = ("승인", "수정")


def _table_exists(conn, table: str) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM information_schema.tables"
        " WHERE table_name = :t"), {"t": table}).first())


def _runs_table_ready(conn) -> bool:
    """실행 원장(`spec_fill_runs`) 마이그레이션 0052 적용 여부.

    `api/auth.py`의 `_schema_ready()`와 같은 이유 — 없는 표를 그냥 SELECT하면 이
    화면 전체가 500으로 죽는다. 여기서는 요청마다 다시 확인한다(그 함수와 달리
    프로세스 캐싱을 하지 않는다): 이 화면은 인증 미들웨어처럼 모든 요청이 지나는
    핫패스가 아니라서, information_schema 조회 한 번을 아끼는 이득보다 "마이그레이션을
    막 적용했는데도 화면이 낡은 캐시를 들고 있다"는 혼란을 피하는 이득이 크다.
    """
    return _table_exists(conn, "spec_fill_runs")


def _field_row(conn, field_key: str):
    """`spec_field_defs`에서 이 필드 정의를 읽는다 — 화면이 다시 정의하지 않는다."""
    return conn.execute(text(
        "SELECT field_key, label, part_types FROM spec_field_defs"
        " WHERE field_key = :f"), {"f": field_key}).mappings().first()


def _real_column(conn, field_key: str) -> bool:
    """`product_specs`에 실제로 그 컬럼이 있는가.

    `spec_field_defs`에 메타 행만 있고 컬럼이 없는 "유령" 상태가 있을 수 있다
    (`api/admin_spec_fields.py`의 `ghosts` 처리와 같은 이유). 이 확인을 통과한
    `field_key`만 동적 SQL(`s.` + field_key)에 쓴다 — 그래서 그 문자열은 항상
    ① `spec_field_defs`에 실재하는 행이고 ② `information_schema.columns`에 실재하는
    식별자다(둘 다 매개변수화 조회로 확인) — 임의 문자열이 이 자리까지 올 수 없다.
    """
    return bool(conn.execute(text(
        "SELECT 1 FROM information_schema.columns"
        " WHERE table_name = 'product_specs' AND column_name = :c"),
        {"c": field_key}).first())


@router.get("/status")
def status(field: str = "cooler_tdp", page: int = 1, size: int = 20):
    """실행 상태·정본 반영·통계 카드·최근 제안 목록(서버 페이지네이션).

    `field`로 대상 필드를 좁힌다 — 사장님 확정(②) "대상 필드는 `cooler_tdp` 하나"를
    반영해 기본값을 그것으로 두되, 화면이 다시 필드를 정의하지 않도록 값 자체는
    호출부(화면)가 `spec_field_defs` 목록에서 고른 것을 그대로 받는다.

    - `total` — 이 필드의 `spec_web_suggestions` 총 행 수.
    - `applied_count` — 그중 검수가 **승인/수정**으로 끝나 `product_specs`에 실제로
      반영된 건수(②의 "정본 반영 0건" 경고가 쓰는 수).
    - `pending_review` — 아직 **대기** 상태인 건수.
    - `latest_fetched_at` — 가장 최근 제안이 채워진 시각.
    - `items` — 최근 제안 목록(상품명·필드·제안값·출처·출처 신뢰 표시·확신도·
      **메모(note)**·적용 시각·검수 상태). `note`는 2026-08-15까지 SELECT에 없어
      값이 있어도 화면에 오지 않았다 — 이번에 추가했다(선행 작업).
    """
    size = max(1, min(size, 100))
    page = max(1, page)
    field = (field or "cooler_tdp").strip()
    with engine.connect() as conn:
        if not _table_exists(conn, "spec_web_suggestions"):
            return {"ok": False,
                    "reason": "spec_web_suggestions 테이블이 없습니다 — 마이그레이션 0045 미적용",
                    "field": field, "items": [], "total": 0, "applied_count": 0,
                    "pending_review": 0, "page": page, "size": size, "pages": 0,
                    "latest_fetched_at": None}
        total = conn.execute(text(
            "SELECT count(*) FROM spec_web_suggestions WHERE field_name = :f"),
            {"f": field}).scalar_one()
        latest = conn.execute(text(
            "SELECT max(fetched_at) FROM spec_web_suggestions WHERE field_name = :f"),
            {"f": field}).scalar_one()
        applied_count = conn.execute(text(
            "SELECT count(*) FROM spec_web_suggestions s"
            " JOIN product_reviews r ON r.review_id = s.applied_review_id"
            " WHERE s.field_name = :f AND r.review_status = ANY(:sts)"),
            {"f": field, "sts": list(APPLIED_STATUSES)}).scalar_one()
        pending = conn.execute(text(
            "SELECT count(*) FROM spec_web_suggestions s"
            " JOIN product_reviews r ON r.review_id = s.applied_review_id"
            " WHERE s.field_name = :f AND r.review_status = '대기'"),
            {"f": field}).scalar_one()
        rows = conn.execute(text("""
            SELECT s.id, s.product_code, p.product_name, s.field_name, s.suggested_value,
                   s.source_url, s.source_name, s.confidence, s.note, s.fetched_at,
                   r.review_status
            FROM spec_web_suggestions s
            JOIN products p USING (product_code)
            LEFT JOIN product_reviews r ON r.review_id = s.applied_review_id
            WHERE s.field_name = :f
            ORDER BY s.fetched_at DESC, s.id DESC
            LIMIT :size OFFSET :offset
        """), {"f": field, "size": size, "offset": (page - 1) * size}).mappings().all()
    items = [{
        "id": r["id"], "product_code": r["product_code"], "name": r["product_name"],
        "field": r["field_name"], "value": r["suggested_value"],
        "source_url": r["source_url"], "source_name": r["source_name"],
        # "제조사 공식" 접두 문자열 판정 — 2026-08-15 실측(38건 중 16건)이 이 규칙과
        # 정확히 일치한다(req-spec-fill.md ④ "엄격 판정 16/38"). source_name은
        # 자유텍스트라 이 규칙 밖의 표기("한국 공식 수입사(...)" 등)는 공식으로 세지
        # 않는다 — 느슨하게 잡으면 "공식"이라는 낱말만 있어도 굵게 표시돼 신뢰도를
        # 과장한다.
        "source_official": bool(r["source_name"] and r["source_name"].startswith("제조사 공식")),
        "confidence": float(r["confidence"]) if r["confidence"] is not None else None,
        "note": r["note"],
        "fetched_at": iso(r["fetched_at"]),
        # None이면 applied_review_id가 가리키던 검수 행이 다른 경로로 이미 사라진
        # 예외적인 경우다 — 화면이 지어내지 않고 그대로 보인다.
        "review_status": r["review_status"],
    } for r in rows]
    return {"ok": True, "field": field, "total": total, "applied_count": applied_count,
            "pending_review": pending, "page": page, "size": size,
            "pages": (total + size - 1) // size if total else 0,
            "latest_fetched_at": iso(latest) if latest else None,
            "items": items,
            "note": ("spec_web_suggestions 집계입니다. product_specs 반영(승인)은"
                     " 상품 사양 검수(ADM-PRD-020)에서만 합니다 — 이 화면은 쓰지 않습니다.")}


@router.get("/field-context")
def field_context(field: str = "cooler_tdp"):
    """"왜 이 필드인가" 근거 — 결측 수·전체 수·엔진 필드 중 결측률 순위·다나와 커버리지.

    화면 로드 시 한 번만 부른다(구조적 사실이라 15초마다 다시 잴 이유가 없다 —
    `/status`처럼 폴링하지 않는다). `is_engine` 필드 전체(2026-08-15 실측 22개)를
    같은 정의(전 상품 대상 결측률 — `products.status`/`stock_qty`로 좁히지 않는다)로
    다시 계산해 순위를 매긴다. **하드코딩된 "1위"가 아니다** — 이 계산이 실제로
    cooler_tdp를 1위(77.6%)로 재현한다(2026-08-15 측정 시점 기준. CLAUDE.md에 이미
    같은 수가 문서화돼 있다 — 여기서 그 수를 다시 지어내지 않고 같은 질의로
    재현했을 뿐이다).
    """
    field = (field or "cooler_tdp").strip()
    with engine.connect() as conn:
        row = _field_row(conn, field)
        if not row or not _real_column(conn, field):
            return {"ok": False, "field_key": field, "found": False,
                    "reason": f"'{field}' 항목 정의를 찾을 수 없습니다"}
        part_types = list(row["part_types"] or [])
        if not part_types:
            return {"ok": True, "field_key": field, "label": row["label"], "found": True,
                    "applicable": False,
                    "reason": "이 항목에 적용 부품 종류가 지정돼 있지 않습니다"}

        def _missing_rate(conn, key, pts):
            r = conn.execute(text(
                "SELECT count(*) AS total, count(s." + key + ") AS filled"
                " FROM products p JOIN product_specs s USING (product_code)"
                " WHERE p.part_type = ANY(:pts)"), {"pts": pts}).mappings().first()
            t, f = r["total"] or 0, r["filled"] or 0
            return t, f

        total, filled = _missing_rate(conn, field, part_types)
        missing = total - filled
        missing_pct = round(missing / total * 100, 1) if total else None

        # 엔진 필드 전체에서 결측률 순위 — 같은 정의(전 상품)로 다시 잰다.
        eng_fields = conn.execute(text(
            "SELECT field_key, part_types FROM spec_field_defs WHERE is_engine = true")).all()
        rates = []
        for fk, pts in eng_fields:
            pts = list(pts or [])
            if not pts or not _real_column(conn, fk):
                continue
            t, f = _missing_rate(conn, fk, pts)
            rates.append((fk, (1 - f / t) if t else 0.0))
        rates.sort(key=lambda x: x[1], reverse=True)
        rank = next((i + 1 for i, (fk, _r) in enumerate(rates) if fk == field), None)

        review_pending = conn.execute(text(
            "SELECT count(*) FROM product_reviews"
            " WHERE review_status = '대기' AND field_name = :f"), {"f": field}).scalar_one()
        review_pending_empty = conn.execute(text(
            "SELECT count(*) FROM product_reviews WHERE review_status = '대기'"
            " AND field_name = :f AND origin_value IS NULL AND suggested_value IS NULL"),
            {"f": field}).scalar_one()
        danawa_pending = conn.execute(text(
            "SELECT count(*) FROM product_reviews WHERE review_status = '대기'"
            " AND field_name = :f AND detail LIKE '%다나와%'"), {"f": field}).scalar_one()

    return {"ok": True, "field_key": field, "label": row["label"], "found": True,
            "applicable": True,
            "missing": missing, "total": total, "missing_pct": missing_pct,
            "rank": rank, "rank_total": len(rates),
            "review_pending": review_pending, "review_pending_empty": review_pending_empty,
            "danawa_suggested_pending": danawa_pending,
            "note": ("전체 상품 기준입니다(판매중·재고 필터를 두지 않습니다) —"
                     " CLAUDE.md에 기록된 결측 수와 같은 정의입니다.")}


@router.get("/runs")
def runs(page: int = 1, size: int = 20):
    """실행 원장(`spec_fill_runs`) 목록 + 진행 중인 실행.

    ⚠ 마이그레이션 0052가 파일까지만 있고 DB에 적용되지 않았다 — 그래서 지금은
    거의 항상 `ok:false`를 돌려준다. **"0건"이 아니라 그 사실 자체를 말한다**
    (모듈 docstring·`_runs_table_ready()` 참조). 이 표에 실제로 행을 쓰는 코드는
    이번 작업 범위 밖이라(모듈 docstring 참조), 마이그레이션이 적용된 뒤에도 별도
    작업 전까지는 계속 비어 있을 수 있다 — 그때는 `ok:true` + `items: []`로
    "실행한 적 없음"과 "원장 자체가 없음"이 갈린다.
    """
    size = max(1, min(size, 100))
    page = max(1, page)
    with engine.connect() as conn:
        if not _runs_table_ready(conn):
            return {"ok": False,
                    "reason": "실행 원장 신설 필요 — 마이그레이션 0052 미적용",
                    "items": [], "total": 0, "page": page, "size": size, "pages": 0,
                    "running": None}
        total = conn.execute(text("SELECT count(*) FROM spec_fill_runs")).scalar_one()
        running = conn.execute(text("""
            SELECT r.run_id, r.field_name, r.requested_count, r.started_at,
                   COALESCE(o.name, o.email) AS requested_by
            FROM spec_fill_runs r
            LEFT JOIN admin_operators o ON o.operator_id = r.requested_by
            WHERE r.status = '진행중'
            ORDER BY r.started_at DESC LIMIT 1
        """)).mappings().first()
        rows = conn.execute(text("""
            SELECT r.run_id, r.field_name, r.requested_count, r.status,
                   r.found_count, r.not_found_count, r.started_at, r.finished_at, r.note,
                   COALESCE(o.name, o.email) AS requested_by
            FROM spec_fill_runs r
            LEFT JOIN admin_operators o ON o.operator_id = r.requested_by
            ORDER BY r.started_at DESC, r.run_id DESC
            LIMIT :size OFFSET :offset
        """), {"size": size, "offset": (page - 1) * size}).mappings().all()
    items = [{
        "run_id": r["run_id"], "field": r["field_name"],
        "requested_count": r["requested_count"], "requested_by": r["requested_by"],
        "status": r["status"], "found_count": r["found_count"],
        "not_found_count": r["not_found_count"],
        "started_at": iso(r["started_at"]),
        "finished_at": iso(r["finished_at"]) if r["finished_at"] else None,
        "note": r["note"],
    } for r in rows]
    # ⚠ running을 dict(row mapping) 그대로 돌려주지 않는다 — DB 시각 컬럼은 타임존 없는
    # UTC라(`api/timeutil.py` 참조), iso()를 거치지 않으면 브라우저가 그 값을 로컬(KST)
    # 시각으로 잘못 읽어 9시간이 어긋난다(그 파일이 이미 겪은 실사고). 위 items처럼
    # started_at을 명시적으로 iso()에 태운다.
    running_out = None
    if running:
        running_out = dict(running)
        running_out["started_at"] = iso(running["started_at"])
    return {"ok": True, "items": items, "total": total, "page": page, "size": size,
            "pages": (total + size - 1) // size if total else 0,
            "running": running_out}
