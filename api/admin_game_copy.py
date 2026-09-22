"""게임 견적 근거 검수 API (ADM-TLK-020) — `GET/POST /api/admin/game-copy*`.

`api/main.py` 의 자동 라우터 탐색(§discovery · `api/` 평면 1단계)이 이 모듈을 싣는다.

■ 이 화면이 답하는 질문
  「`game_customer_copy` 86행의 네 문단을 고객에게 내보내도 되는가」 — 그 하나뿐이다.

  이 86행은 «게임 소개문»이 아니라 **«이 게임에 왜 이런 PC 가 필요한가» 견적 근거**다
  (남의 권장사양을 옮긴 것이 아니라 우리가 판단한 것). 고객 경로(팝콘톡·견적 카드)는
  `api/game_copy.load_reviewed_copy` 하나를 거친다 — 그 함수가 검수 통과 행만 낸다.
  ★ **검수만 통과하면 코드 수정 없이 그대로 나간다.** 이 API 는 그 «통과»를 만든다.

■ 왜 검수자에게 games 원본 값을 나란히 보여주는가 (`/api/admin/game-copy/{id}` 의 `source`)
  문구만 보여주면 검수는 «읽고 도장 찍기»가 된다. 검수자가 판정할 수 있어야 하는 것은
  「이 문장이 저 값에서 나왔는가」이고, 그러려면 그 게임의 `games` 원본 값
  (rec_gpu · rec_target_fps · typical_monitor_hz · community_note …)이 같은 화면에
  있어야 한다. `source_fields`(0103 이 남긴 «근거로 쓴 컬럼명 배열»)를 열쇠로 그 값을
  꺼내 준다 — 화면이 컬럼 목록을 박지 않는다(단일 원천: 어느 컬럼을 봤는지는 행이 안다).

■ 권한 — 승인·반려·되돌리기는 **operator 이상**(owner 를 요구하지 않는다). 근거:
  ① 미들웨어(`api/auth.py` `required_role`)의 기본 규칙이 이미 쓰기=operator 다.
     `OWNER_WRITE_PREFIXES` 에 든 것들은 **되돌릴 수 없거나 돈·계정·정책을 바꾸는 쓰기**다
     (판매가·마진·운영자·22,000건 일괄 적재). 이 화면의 쓰기는 그 성격이 아니다 —
     행 하나의 상태 전이이고 **되돌리기가 이 화면 안에 있다**(아래 unapprove).
  ② 고객에게 나가는 문구라 무겁게 볼 이유가 있지만, 사장님 확정이 「**86종을 보신 뒤**
     견적 화면에 쓴다」이므로 **최종 관문은 사장님의 열람**이지 API 권한 등급이 아니다.
     owner 전용으로 잠그면 사장님 혼자 86번을 눌러야 하고, 그건 검수를 도장찍기로 만든다.
  ③ 대신 «누가 승인했는가»를 두 곳에 남긴다 — `reviewed_by`(행) · 활동 로그(사건).
     owner 가 아닌 사람이 승인한 행을 사장님이 찾아낼 수 있어야 검수가 성립한다.
  ⚠ 이 판단은 뒤집을 수 있다 — `OWNER_WRITE_PREFIXES` 에 `/api/admin/game-copy` 한 줄을
    더하면 즉시 owner 전용이 된다(이 모듈 코드는 고치지 않아도 된다).

■ 원장 — 새 이력표를 만들지 않는다
  `admin_operator_activity_logs`(기존 · 5,000행 넘게 굴러가는 원장)에 `target_kind=
  'game_copy'` 로 남긴다. 되돌리기(`undo`)도 그 로그 한 건을 근거로 역전이한다 —
  기존 화면들(admin_reviews·admin_category_mapping·admin_members)이 전부 같은 모양이다.

■ 「전 행 반환 금지」
  목록은 서버 페이지네이션이다(`page`·`size`, size 상한 100). 필터 선택지
  (확신도·검수상태)도 **서버가 준다**(`filters`) — 화면이 현재 페이지에서 뽑으면
  1페이지에 '낮음' 이 없다는 이유로 선택지가 사라진다.

■ 로그는 ASCII 기호만(서버 stdout cp949).
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import bindparam, text

from . import game_copy as GC
from .auth import current_operator
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin/game-copy", tags=["admin-game-copy"])

log = logging.getLogger(__name__)

# 상태 어휘 — 0112 의 체크 제약과 **같은 값**이어야 한다. 화면은 이 목록을
# `/filters`(또는 목록 응답의 `filters`)로 받아 간다 — 마크업에 박지 않는다.
REVIEW_STATES = ("대기", "승인", "반려")
CONFIDENCES = ("높음", "보통", "낮음")

# 한 페이지 상한. 전체 행수(86)보다 **낮게** 잡는다 — 근거는 list_copies 참조.
MAX_PAGE_SIZE = 50

# 검수자가 고칠 수 있는 네 문단. 이 밖의 컬럼은 이 API 로 못 바꾼다(화이트리스트).
EDITABLE_COLS = ("spec_summary_ko", "why_this_pc", "upgrade_hint", "caution")

# 상세의 「근거」 칸이 games 에서 꺼내 보여주는 컬럼. `source_fields` 에 적힌 것을
# 우선 쓰되, 그 배열이 비었거나 games 에 없는 이름이면 아래 기본 묶음으로 떨어진다.
# **화면이 아니라 여기서 정한다** — 화면은 서버가 준 (라벨, 값) 쌍을 그리기만 한다.
SOURCE_FALLBACK = (
    "min_cpu", "rec_cpu", "min_gpu", "rec_gpu", "min_ram_gb", "rec_ram_gb",
    "min_vram_gb", "rec_vram_gb", "rec_target_fps", "rec_target_resolution",
    "bottleneck", "competitive_fps_target", "comfortable_fps_target",
    "typical_monitor_hz", "esports_standard_hz", "community_note",
)

# 사람이 읽는 이름. 없는 컬럼은 컬럼명을 그대로 쓴다(지어내지 않는다).
FIELD_LABELS = {
    "min_cpu": "최소 CPU", "rec_cpu": "권장 CPU",
    "min_gpu": "최소 그래픽카드", "rec_gpu": "권장 그래픽카드",
    "rec_gpu_nvidia": "권장 그래픽카드(NVIDIA)", "rec_gpu_amd": "권장 그래픽카드(AMD)",
    "rec_gpu_intel": "권장 그래픽카드(Intel)",
    "min_ram_gb": "최소 램(GB)", "rec_ram_gb": "권장 램(GB)",
    "min_vram_gb": "최소 VRAM(GB)", "rec_vram_gb": "권장 VRAM(GB)",
    "min_storage_gb": "최소 저장공간(GB)", "rec_storage_gb": "권장 저장공간(GB)",
    "requires_ssd": "SSD 필요", "requires_nvme": "NVMe 필요",
    "min_target_fps": "최소 목표 프레임", "rec_target_fps": "권장 목표 프레임",
    "min_target_resolution": "최소 목표 해상도", "rec_target_resolution": "권장 목표 해상도",
    "min_preset": "최소 그래픽 설정", "rec_preset": "권장 그래픽 설정",
    "bottleneck": "병목 부품", "bottleneck_evidence": "병목 근거",
    "fps_sensitivity": "프레임 민감도",
    "competitive_fps_target": "경쟁 플레이 목표 프레임",
    "comfortable_fps_target": "쾌적 목표 프레임",
    "minimum_fps_target": "최소 목표 프레임(하한)",
    "typical_monitor_hz": "일반 모니터 주사율", "esports_standard_hz": "대회 모니터 주사율",
    "refresh_selection_note": "주사율 판단 메모",
    "community_note": "커뮤니티 실사용 메모", "community_confidence": "커뮤니티 근거 확신도",
    "min_spec_note_raw": "게임사 최소사양 원문", "rec_spec_note_raw": "게임사 권장사양 원문",
    "official_source_url": "게임사 공지 주소", "checked_date": "사양 확인일",
    "confidence": "사양 확신도", "genre": "장르", "vendor": "제작사",
    "release_date": "출시일", "note": "메모", "description": "사양 부하 메모",
}

PARAGRAPHS = (
    ("spec_summary_ko", "한 줄 요약"),
    ("why_this_pc", "이 PC 가 필요한 이유"),
    ("upgrade_hint", "다음 업그레이드"),
    ("caution", "주의 · 오해"),
)


def _me() -> dict:
    """로그인한 운영자. 미들웨어가 이미 막지만 여기서도 확인한다(이중 방어)."""
    op = current_operator()
    if not op:
        raise HTTPException(401, "로그인이 필요합니다")
    return op


def _log(conn, action: str, game_id: int, detail: dict) -> int:
    """작업 기록 — 기존 원장(`admin_operator_activity_logs`)에 남긴다.

    `target_kind='game_copy'` 는 이 화면이 처음 쓰는 값이다(실측: 기존 21종에 없다).
    새 표를 만들지 않는 이유는 모듈 docstring §원장 참조.
    """
    op = _me()
    return conn.execute(text(
        "INSERT INTO admin_operator_activity_logs"
        " (operator_id, action, target_kind, target_id, detail)"
        " VALUES (:op, :a, 'game_copy', :t, CAST(:d AS JSONB)) RETURNING log_id"),
        {"op": op["operator_id"], "a": action, "t": str(game_id),
         "d": json.dumps(detail, ensure_ascii=False)}).scalar()


def _row_for_update(conn, game_id: int):
    r = conn.execute(text(
        "SELECT * FROM game_customer_copy WHERE game_id = :g FOR UPDATE"),
        {"g": game_id}).mappings().first()
    if r is None:
        raise HTTPException(404, "해당 게임의 문구가 없습니다")
    return r


def _iso(v):
    """시각 -> 타임존이 붙은 ISO. **`timeutil.iso()` 만 쓴다 · 직접 변환 금지** —
    DB 가 UTC 로 돌고 컬럼이 naive 라, 직접 변환하면 브라우저가 로컬 시각으로 읽어
    9시간이 어긋난다(`api/timeutil.py` 의 실사고 기록). 단일 원천은 그 모듈이다.

    date(시각 없는 값)도 `iso()` 가 그대로 통과시킨다 — 여기서 다시 갈래를 두지 않는다.
    """
    return iso(v)


def _source_value(v):
    """`games` 의 임의 컬럼 값 -> 화면에 실을 수 있는 값.

    값이 없으면 **문자열을 지어내지 않고 None** 으로 준다(화면이 「미기재」를 그린다).
    날짜·시각만 `_iso` 로 돌리고, 나머지(문자열·숫자·불리언·JSON 배열)는 그대로 둔다 —
    그 편이 검수자가 DB 값을 «있는 그대로» 대조할 수 있다.
    """
    if v is None:
        return None
    if hasattr(v, "isoformat"):          # date · datetime
        return _iso(v)
    if isinstance(v, (str, int, float, bool, list, dict)):
        return v
    return str(v)                        # Decimal 등 — 화면은 글자로만 쓴다


# ── 조회 ────────────────────────────────────────────────────────────────────
@router.get("")
def list_copies(page: int = 1, size: int = 20, state: str = "",
                confidence: str = "", keyword: str = ""):
    """검수 목록 — **서버 페이지네이션**. 전 행을 반환하지 않는다.

    `total` 은 지금 걸린 필터에서의 전체 건수다. 화면의 큰 숫자는 이 값을 써야 한다
    (현재 페이지 길이를 «전체»라 부르면 그게 화면이 지어내는 수치다 —
    CLAUDE.md §화면 정직성).

    `filters` 는 **선택지와 그 건수**를 서버가 만들어 준다. 화면이 현재 페이지에서
    뽑으면 1페이지에 '낮음'(7건)이 없다는 이유만으로 그 선택지가 사라진다.
    건수는 **필터 없는 전수** 기준이다 — 「'반려' 를 고르면 몇 건이 보이나」를
    미리 알려 주는 것이 목적이라 지금 필터에 종속되면 안 된다.
    """
    _me()
    # size 상한 50 — 전 행(86)이 **한 요청에 다 담기지 않게** 정한 값이다.
    # 상한이 100이면 `size=100` 한 번으로 86행이 통째로 나가, 「전 행 반환 금지」가
    # 「지금은 마침 86행이라 안 나간다」는 우연이 된다. 상한을 전체보다 낮게 두면
    # 그 규약이 구조로 지켜진다(회귀가 이 관계를 대조한다).
    size = max(1, min(int(size or 20), MAX_PAGE_SIZE))
    page = max(1, int(page or 1))
    state = (state or "").strip()
    confidence = (confidence or "").strip()
    keyword = (keyword or "").strip()
    if state and state not in REVIEW_STATES:
        raise HTTPException(400, "검수 상태 값이 올바르지 않습니다")
    if confidence and confidence not in CONFIDENCES:
        raise HTTPException(400, "확신도 값이 올바르지 않습니다")

    where = ("WHERE (:state = '' OR c.review_state = :state)"
             "  AND (:conf = '' OR c.confidence = :conf)"
             "  AND (:kw = '' OR g.name ILIKE '%%' || :kw || '%%'"
             "                OR c.spec_summary_ko ILIKE '%%' || :kw || '%%'"
             "                OR c.why_this_pc ILIKE '%%' || :kw || '%%')")
    p = {"state": state, "conf": confidence, "kw": keyword,
         "size": size, "off": (page - 1) * size}

    with engine.connect() as conn:
        total = conn.execute(text(
            "SELECT count(*) FROM game_customer_copy c JOIN games g USING (game_id) "
            + where), p).scalar_one()
        # 인기순위는 `game_popularity_snapshots` 의 최신 스냅샷이 정본이다
        # (`games.popularity_rank` 는 0/86 죽은 컬럼 — talk_answer 도 안 읽는다).
        rows = conn.execute(text(
            "SELECT c.game_id, g.name, c.confidence, c.review_state,"
            "       c.reviewed_by, c.reviewed_at, c.reject_reason, c.updated_at,"
            "       (c.original_spec_summary_ko IS NOT NULL"
            "        OR c.original_why_this_pc IS NOT NULL"
            "        OR c.original_upgrade_hint IS NOT NULL"
            "        OR c.original_caution IS NOT NULL) AS edited,"
            "       p.pcbang_rank, p.snapshot_date"
            "  FROM game_customer_copy c"
            "  JOIN games g USING (game_id)"
            "  LEFT JOIN LATERAL (SELECT pcbang_rank, snapshot_date"
            "                       FROM game_popularity_snapshots s"
            "                      WHERE s.game_id = c.game_id"
            "                      ORDER BY s.snapshot_date DESC LIMIT 1) p ON TRUE "
            + where +
            " ORDER BY p.pcbang_rank NULLS LAST, g.name"
            " LIMIT :size OFFSET :off"), p).mappings().all()

        # 선택지 — 전수 기준 건수(위 docstring 참조).
        by_state = dict(conn.execute(text(
            "SELECT review_state, count(*) FROM game_customer_copy GROUP BY 1")).all())
        by_conf = dict(conn.execute(text(
            "SELECT confidence, count(*) FROM game_customer_copy GROUP BY 1")).all())
        grand_total = conn.execute(text(
            "SELECT count(*) FROM game_customer_copy")).scalar_one()
        # 「지금 실제로 고객에게 나갈 수 있는 문구가 몇 건인가」 — 고객 경로가 쓰는
        # 게이트(`api/game_copy.GATE_SQL`)를 **그대로** 세어 준다. 화면이
        # '승인' 건수로 대신 세면 언젠가 둘이 갈라진다(같은 것을 두 벌 두지 않는다).
        live = conn.execute(text(
            "SELECT count(*) FROM game_customer_copy WHERE " + GC.GATE_SQL)
        ).scalar_one()

    return {
        "items": [{
            "game_id": r["game_id"], "name": r["name"],
            "confidence": r["confidence"], "review_state": r["review_state"],
            "reviewed_by": r["reviewed_by"], "reviewed_at": _iso(r["reviewed_at"]),
            "reject_reason": r["reject_reason"], "edited": bool(r["edited"]),
            "updated_at": _iso(r["updated_at"]),
            "pcbang_rank": r["pcbang_rank"],
            "rank_as_of": str(r["snapshot_date"]) if r["snapshot_date"] else None,
        } for r in rows],
        "page": page, "size": size, "total": total,
        "pages": (total + size - 1) // size,
        "grand_total": grand_total,
        "live_count": live,
        # 화면이 「왜 이 수가 고객 노출 건수인가」를 스스로 지어내 설명하지 않게,
        # 그 조건을 서버가 사람 말로 준다(상세의 `customer_gate` 와 같은 사실).
        "customer_gate_label": "검수 통과한 문구만 싣습니다",
        "filters": {
            "states": [{"value": s, "n": int(by_state.get(s, 0))} for s in REVIEW_STATES],
            "confidences": [{"value": c, "n": int(by_conf.get(c, 0))} for c in CONFIDENCES],
        },
        "applied": {"state": state, "confidence": confidence, "keyword": keyword},
    }


@router.get("/{game_id}")
def get_copy(game_id: int):
    """상세 — 네 문단 전문 + **그 게임의 games 원본 값** + source_fields + confidence.

    원본 값이 이 응답의 핵심이다. 검수자가 「이 문장이 저 값에서 나왔나」를 대조할 수
    없으면 검수가 아니라 도장찍기다(작업 지시 원문).
    """
    _me()
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT c.*, g.name FROM game_customer_copy c JOIN games g USING (game_id)"
            " WHERE c.game_id = :g"), {"g": game_id}).mappings().first()
        if r is None:
            raise HTTPException(404, "해당 게임의 문구가 없습니다")

        # source_fields 가 가리키는 games 컬럼을 실제로 꺼낸다. 실재하는 컬럼만
        # 고른다 — 배열에 오타/삭제된 컬럼명이 있어도 500 이 되지 않는다.
        real_cols = {c[0] for c in conn.execute(text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'games'")).all()}
        wanted = [f for f in (r["source_fields"] or []) if f in real_cols]
        missing = [f for f in (r["source_fields"] or []) if f not in real_cols]
        used_fallback = not wanted
        if used_fallback:
            wanted = [f for f in SOURCE_FALLBACK if f in real_cols]
        g = conn.execute(text(
            "SELECT " + ", ".join('"%s"' % c for c in wanted) +
            " FROM games WHERE game_id = :g"), {"g": game_id}).mappings().first()

        pop = conn.execute(text(
            "SELECT pcbang_rank, pcbang_share_pct, steam_ccu, snapshot_date, source"
            "  FROM game_popularity_snapshots WHERE game_id = :g"
            " ORDER BY snapshot_date DESC LIMIT 1"), {"g": game_id}).mappings().first()

    source = []
    for col in wanted:
        v = g[col] if g is not None else None
        source.append({
            "field": col,
            "label": FIELD_LABELS.get(col, col),
            # ⚠ 여기 값은 **아무 타입이나 온다**(문자열·정수·불리언·날짜 — games 의
            # 임의 컬럼이다). 그래서 시각 변환기(`_iso`)에 통째로 넘기지 않는다 —
            # 넘겼다가 `'str' object has no attribute 'isoformat'` 으로 500 이 났다
            # (2026-09-21 실측·수정). 시각/날짜만 골라 변환하고 나머지는 그대로 둔다.
            "value": _source_value(v),
        })

    paragraphs = [{
        "field": col, "label": label,
        "text": r[col],
        # 사람이 고쳤으면 기계 원문이 함께 온다 — 검수자가 무엇이 바뀌었는지 본다.
        "original": r["original_" + col],
    } for col, label in PARAGRAPHS]

    return {
        "game_id": r["game_id"], "name": r["name"],
        "confidence": r["confidence"],
        "review_state": r["review_state"],
        "reviewed_by": r["reviewed_by"], "reviewed_at": _iso(r["reviewed_at"]),
        "reviewed_note": r["reviewed_note"], "reject_reason": r["reject_reason"],
        "source_url": r["source_url"], "updated_at": _iso(r["updated_at"]),
        "paragraphs": paragraphs,
        "source_fields": list(r["source_fields"] or []),
        "source_fields_missing": missing,   # games 에 없는 이름이 적혀 있었다
        "source_is_fallback": used_fallback,
        "source": source,
        "popularity": ({
            "pcbang_rank": pop["pcbang_rank"],
            "pcbang_share_pct": float(pop["pcbang_share_pct"]) if pop["pcbang_share_pct"] is not None else None,
            "steam_ccu": pop["steam_ccu"],
            "as_of": str(pop["snapshot_date"]), "source": pop["source"],
        } if pop else None),
        # 화면이 「승인하면 고객에게 나간다」를 사실로 말할 수 있게, 그 조건을
        # 서버가 밝힌다(화면이 문장을 지어내지 않는다).
        "customer_gate": GC.GATE_SQL,
    }


# ── 쓰기 ────────────────────────────────────────────────────────────────────
class ApproveBody(BaseModel):
    # 문구를 고쳐서 승인하는 경우에만 채운다. 없으면 원문 그대로 승인한다.
    edits: dict | None = None
    note: str | None = None


class RejectBody(BaseModel):
    reason: str


def _apply_edits(conn, row, edits: dict) -> dict:
    """문구 수정 — 바뀐 칸만 UPDATE 하고, **기계 원문을 첫 수정 때 한 번 보존**한다.

    original_* 이 이미 차 있으면 덮지 않는다. 원문은 «최초 기계 출력» 하나여야 한다
    (두 번째 수정 때 덮으면 그건 원문이 아니라 «직전 값»이 된다 — 0112 참조).
    """
    sets, params, changed = [], {"g": row["game_id"]}, {}
    for col, val in edits.items():
        if col not in EDITABLE_COLS:
            raise HTTPException(400, "수정할 수 없는 항목입니다: %s" % col)
        new = (val or "").strip() or None
        old = row[col]
        if new == old:
            continue
        if col in ("spec_summary_ko", "why_this_pc") and not new:
            raise HTTPException(400, "한 줄 요약과 이 PC 가 필요한 이유는 비울 수 없습니다")
        sets.append('"%s" = :%s' % (col, col))
        params[col] = new
        if row["original_" + col] is None:
            sets.append('"original_%s" = :o_%s' % (col, col))
            params["o_" + col] = old
        changed[col] = {"before": old, "after": new}
    if sets:
        conn.execute(text(
            "UPDATE game_customer_copy SET " + ", ".join(sets) +
            ", updated_at = now() WHERE game_id = :g"), params)
    return changed


@router.post("/{game_id}/approve")
def approve(game_id: int, body: ApproveBody):
    """승인 — `reviewed_by`/`reviewed_at` 을 채우고 `review_state='승인'` 으로 전이.

    ★ 이 한 번으로 그 게임의 문구가 **팝콘톡 답변에 실제로 나가기 시작한다**
      (고객 경로는 `api/game_copy.load_reviewed_copy` 하나를 거치고, 그 함수가
       검수 통과 행만 싣는다. 코드 수정 없이 켜지는 것이 설계다).

    문구를 고쳐서 승인하면 기계 원문을 `original_*` 에 보존한다(0112 §③).
    """
    me = _me()
    with engine.begin() as conn:
        row = _row_for_update(conn, game_id)
        if row["review_state"] == "승인":
            raise HTTPException(409, "이미 승인된 문구입니다")
        changed = _apply_edits(conn, row, body.edits or {}) if body.edits else {}
        conn.execute(text(
            "UPDATE game_customer_copy"
            "   SET review_state = '승인', reviewed_by = :by, reviewed_at = now(),"
            "       reviewed_note = :note, reject_reason = NULL, updated_at = now()"
            " WHERE game_id = :g"),
            {"g": game_id, "by": me["name"] or me["email"],
             "note": (body.note or "").strip() or None})
        log_id = _log(conn, "game_copy_approve", game_id, {
            "from": row["review_state"], "to": "승인",
            "reviewed_by": me["name"] or me["email"],
            "edited": bool(changed), "changes": changed,
            "note": (body.note or "").strip() or None,
        })
    log.info("[game-copy] approve game_id=%s log_id=%s edited=%s",
             game_id, log_id, bool(changed))
    return {"ok": True, "game_id": game_id, "review_state": "승인",
            "log_id": log_id, "edited": bool(changed),
            "changed_fields": sorted(changed)}


@router.post("/{game_id}/reject")
def reject(game_id: int, body: RejectBody):
    """반려 — 사유를 기록한다. `reviewed_by` 는 **NULL 그대로**다.

    반려자 이름을 reviewed_by 에 적으면 그 순간 반려한 문구가 고객에게 나간다
    (조회 조건이 그 칸 하나다). 0112 의 체크 제약이 그 실수를 DB 에서 막는다.
    «누가 반려했는가»는 활동 로그가 갖는다.
    """
    me = _me()
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "반려 사유를 입력해야 합니다")
    with engine.begin() as conn:
        row = _row_for_update(conn, game_id)
        if row["review_state"] == "반려":
            raise HTTPException(409, "이미 반려된 문구입니다")
        conn.execute(text(
            "UPDATE game_customer_copy"
            "   SET review_state = '반려', reviewed_by = NULL, reviewed_at = NULL,"
            "       reject_reason = :r, updated_at = now()"
            " WHERE game_id = :g"), {"g": game_id, "r": reason})
        log_id = _log(conn, "game_copy_reject", game_id, {
            "from": row["review_state"], "to": "반려", "reason": reason,
            "was_reviewed_by": row["reviewed_by"],
            "operator": me["name"] or me["email"],
        })
    log.info("[game-copy] reject game_id=%s log_id=%s", game_id, log_id)
    return {"ok": True, "game_id": game_id, "review_state": "반려", "log_id": log_id}


@router.post("/{game_id}/unapprove")
def unapprove(game_id: int):
    """되돌리기 — 승인을 물린다. **삭제가 아니라 역전이**다.

    `review_state='대기'` · `reviewed_by=NULL` · `reviewed_at=NULL`. 문구 자체는
    그대로 남는다(수정한 문구도 남는다 — 되돌리는 것은 «승인»이지 «수정»이 아니다.
    수정을 되돌리려면 original_* 를 보고 다시 고쳐 승인한다).
    되돌린 즉시 그 게임은 팝콘톡 답변에서 빠진다.
    """
    me = _me()
    with engine.begin() as conn:
        row = _row_for_update(conn, game_id)
        if row["review_state"] != "승인":
            raise HTTPException(409, "승인된 문구만 되돌릴 수 있습니다")
        conn.execute(text(
            "UPDATE game_customer_copy"
            "   SET review_state = '대기', reviewed_by = NULL, reviewed_at = NULL,"
            "       updated_at = now() WHERE game_id = :g"), {"g": game_id})
        log_id = _log(conn, "game_copy_unapprove", game_id, {
            "from": "승인", "to": "대기",
            "was_reviewed_by": row["reviewed_by"],
            "was_reviewed_at": _iso(row["reviewed_at"]),
            "operator": me["name"] or me["email"],
        })
    log.info("[game-copy] unapprove game_id=%s log_id=%s", game_id, log_id)
    return {"ok": True, "game_id": game_id, "review_state": "대기", "log_id": log_id}


class BulkBody(BaseModel):
    game_ids: list[int]


# 일괄 승인 상한 — 한 번에 이만큼까지만 받는다. 숨기지 않고 응답에 그대로 싣는다
# (CLAUDE.md §목록 화면 규약 「상한도 숨기지 않는다」).
BULK_MAX = 20

# 일괄 승인이 **손대지 않는** 확신도. 근거는 아래 bulk_approve docstring.
BULK_BLOCKED_CONFIDENCE = "낮음"


@router.post("/bulk-approve")
def bulk_approve(body: BulkBody):
    """일괄 승인 — **연다. 다만 좁게 연다.**

    ■ 판단과 근거
      열지 않으면 86번을 눌러야 하고, 그러면 뒤쪽 수십 건은 실제로 «읽지 않고» 넘어간다
      (도장찍기는 버튼이 하나여서가 아니라 **사람이 지치면** 생긴다).
      반대로 전부 열면 한 번의 클릭으로 86건이 고객에게 나간다 — 되돌릴 수 있어도
      그 사이에 이미 고객이 읽는다.
      그래서 **셋으로 좁혔다**:
        ① 상한 20건(BULK_MAX). 넘으면 400 — 조용히 자르지 않는다.
        ② 확신도 '낮음'(7건)은 **건너뛴다**. 근거가 얇다고 생성기 스스로 밝힌 문구를
           일괄로 내보내는 것은 검수가 아니다. 한 건씩 상세를 열어 승인해야 한다.
        ③ 이미 승인된 행·없는 행도 건너뛴다.
      ★ **건너뛴 것을 막지 않고 «사유와 함께» 돌려준다**(CLAUDE.md §목록 화면 규약 —
        \"일괄 동작은 자격 없는 대상을 막지 않고 사유와 함께 건너뛴다\"). 그래서 이 API 는
        자격 없는 대상이 섞여 있어도 400 을 내지 않는다(상한 초과만 400 이다 —
        그건 «요청 자체가 규약 밖»이라 처리할 대상 집합이 정의되지 않는다).

    ■ 상태 전이를 일괄용으로 다시 쓰지 않는다
      단건 승인과 **같은 UPDATE 문**을 쓰고, 로그도 **건마다** 남긴다 — 그래야
      되돌리기(`unapprove`)를 단건용 그대로 쓸 수 있다(같은 규약).
    """
    me = _me()
    ids = [int(i) for i in (body.game_ids or [])]
    if not ids:
        raise HTTPException(400, "승인할 항목을 선택해야 합니다")
    if len(ids) > BULK_MAX:
        raise HTTPException(400, "한 번에 최대 %d건까지 승인할 수 있습니다(요청 %d건)"
                            % (BULK_MAX, len(ids)))

    approved, skipped = [], []
    with engine.begin() as conn:
        rows = {r["game_id"]: r for r in conn.execute(text(
            "SELECT c.game_id, g.name, c.confidence, c.review_state"
            "  FROM game_customer_copy c JOIN games g USING (game_id)"
            " WHERE c.game_id IN :ids FOR UPDATE OF c"
        ).bindparams(bindparam("ids", expanding=True)), {"ids": ids}).mappings().all()}
        for gid in ids:
            r = rows.get(gid)
            if r is None:
                skipped.append({"game_id": gid, "name": None,
                                "reason": "문구가 없는 게임입니다"})
                continue
            if r["review_state"] == "승인":
                skipped.append({"game_id": gid, "name": r["name"],
                                "reason": "이미 승인되어 있습니다"})
                continue
            if r["confidence"] == BULK_BLOCKED_CONFIDENCE:
                skipped.append({"game_id": gid, "name": r["name"],
                                "reason": "확신도 '%s' 는 일괄 승인 대상이 아닙니다 —"
                                          " 상세를 열어 한 건씩 승인하십시오"
                                          % BULK_BLOCKED_CONFIDENCE})
                continue
            conn.execute(text(
                "UPDATE game_customer_copy"
                "   SET review_state = '승인', reviewed_by = :by, reviewed_at = now(),"
                "       reject_reason = NULL, updated_at = now()"
                " WHERE game_id = :g"),
                {"g": gid, "by": me["name"] or me["email"]})
            log_id = _log(conn, "game_copy_approve", gid, {
                "from": r["review_state"], "to": "승인", "bulk": True,
                "reviewed_by": me["name"] or me["email"], "edited": False,
            })
            approved.append({"game_id": gid, "name": r["name"], "log_id": log_id})
    log.info("[game-copy] bulk approve ok=%d skipped=%d", len(approved), len(skipped))
    return {"ok": True, "approved": approved, "skipped": skipped,
            "approved_count": len(approved), "skipped_count": len(skipped),
            "bulk_max": BULK_MAX,
            "blocked_confidence": BULK_BLOCKED_CONFIDENCE}


@router.get("/{game_id}/activity")
def activity(game_id: int, limit: int = 20):
    """이 문구의 작업 기록 — 누가 언제 무엇을 했는가(원장 조회).

    화면의 상세 하단이 이걸 그린다. 이력표를 따로 만들지 않은 대신 이 조회가
    「이 행에 무슨 일이 있었나」를 답한다.
    """
    _me()
    limit = max(1, min(int(limit or 20), 100))
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT l.log_id, l.action, l.detail, l.created_at, o.name AS operator_name"
            "  FROM admin_operator_activity_logs l"
            "  LEFT JOIN admin_operators o ON o.operator_id = l.operator_id"
            " WHERE l.target_kind = 'game_copy' AND l.target_id = :t"
            " ORDER BY l.log_id DESC LIMIT :lim"),
            {"t": str(game_id), "lim": limit}).mappings().all()
    return {"items": [{
        "log_id": r["log_id"], "action": r["action"],
        "operator_name": r["operator_name"], "detail": r["detail"],
        "created_at": _iso(r["created_at"]),
    } for r in rows], "total": len(rows), "limit": limit}
