"""단가표 반영(ADM-PRC-040) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery,
`api/` 평면에 둔다 — 하위 폴더는 자동 등록이 훑지 않는다).

계약: `docs/design/spec-price-import.md`(사장님 확정 **1b 안** — 좌 공급처별 최신 파일
목록 + 우 diff). 원문(Claude Design)은 하네스만 연다(`DesignSync`가 서브에이전트에서
막혀 있다) — 이 화면은 계약 요약 텍스트로 지었다(로컬 원안 `dc-*.html` 없음 · 치수
대조 대상 아님 — 계약 요약뿐인 화면의 선례는 `admin_ui_reprice.py`·`admin_ui_price_
history.py`와 같다).

■ 데이터 — 쓰기는 이미 있는 API 넷만 쓴다(`api/admin_price_import.py`, 새로 만들지
  않았다 — 딱 하나, 아래 ★ 항목만 담당 파일 자격으로 고쳤다):
    GET  /api/admin/price-import                  공급처별 최신 파일 + diff(chg/nw/stat/same)
    POST /api/admin/price-import/upload            실파일 업로드(파일명→공급처 자동 인식)
    POST /api/admin/price-import/{file_id}/apply    선택 반영 = 승인(부분성공 없음 — 문제
                                                     행 하나면 전체 400)
    POST /api/admin/price-import/undo/{log_id}      되돌리기(겹친 변경 409 · 이력 없음 404)
  이 라우트 자신은 위 넷을 직접 부르지 않는다 — 다른 admin2 화면과 같은 관행대로
  클라이언트 스크립트가 브라우저에서 직접 불러 그린다. 여기서는 페이지 뼈대와,
  요청마다 다시 계산할 필요가 없는 SSR 참조값(아래 §SSR)만 얹는다.

■★ 제작 전 실측(계약 §「제작자가 먼저 재야 하는 것」 다섯 항목 — 값은 제작 보고서에도
  남긴다. 전부 2026-08-15, 이 제작자가 코드 열람 + 로컬 서버(:8002) 실호출로 확인):
    ① `api/admin_price_import.py`는 이미 있다 — 업로드·조회·반영·되돌리기 넷 다
       실동작(코드 열람 + `GET /api/admin/price-import` 200 실호출로 확인).
    ② 반영 응답이 "시도 / 실제 변경 / 잠겨 건너뜀" 셋을 **준다** — `apply_rows()`가
       `{"applied": ..., "price_changed": ..., "sale_locked_skipped": ..., "undo_id": ...,
       "file_status": ...}`를 돌려준다(코드 확인, 187행대). `applied`는 요청 전체가
       한 번에 성공하므로(부분 성공 없음) 곧 "시도 = 요청 건수"와 같다.
    ③ 되돌리기 409(겹친 변경 — 최종 승자 원칙)는 **있었지만 상품 목록을 안 줬다**
       (첫 번째로 어긋난 상품에서 즉시 raise — 나머지는 확인도 안 함). 계약 §④
       "어느 상품인지 목록으로 보여주고, 조용히 넘기지 않습니다"를 어겼다 — 이 파일이
       담당 파일 목록에 있어(`⚠ 필요하면 열어라`) `undo()`를 고쳤다: 첫 건에서 멈추지
       않고 전수 스캔해 겹친 상품 전부(코드 + 상품명)를 409 메시지에 나열한다.
       (`api/admin_price_import.py` 2026-08-15 변경 — 함수 시그니처·다른 모듈이 쓰는
       `_reprice`/`_settings`는 손대지 않았다. `.venv/Scripts/python -c
       "import api.admin_price_import"`로 무결성 확인. 서버가 이미 떠 있어(`--reload`
       없음, T-05) **재시작 전까지는 옛 동작 그대로다** — 재검증은 재시작 후 필요.)
    ④ 프리셋 — `supplier_presets`(공급처별 최신 버전만 본다). 실측: 공급처 **5곳** 중
       **2곳**(MSI(웨이코스) · 클릭나라)만 프리셋 보유. 나머지 3곳(점검-공급처-A ·
       용산 중앙 · 화면점검-공급처-임시)은 업로드 자체가 400(공급처 인식 실패)이다.
    ⑤ 무변동 판정은 **서버**(`_file_diff()`의 `same` 카운트)가 한다 — 화면은 그 값을
       그대로 보여줄 뿐 스스로 세지 않는다(코드 확인).
    부가 실측 — `GET /api/admin/price-import`는 지금 파일 **2건**(공급처별 최신 1건씩,
    6건 중 4건은 "이 목록이 감추는 것" 경고대로 조용히 숨어 있다)을 준다. 그 2건의
    `chg`(가격이 바뀐 행)는 **전부 미매칭**이라 지금 이 순간은 두 파일 다 "선택 반영"
    가능한 행이 0건이다(체크박스가 전부 비활성인 상태를 정상으로 렌더해야 한다는 뜻 —
    이 사실도 화면이 지어낼 수 없어 실측대로 반영했다).

■ SSR로 얹는 값(§data-*) — 상호작용마다 바뀌는 값(파일 목록·diff·반영 결과)은 전부
  클라이언트가 위 API로 직접 받는다. 아래 셋만 렌더 시점에 계산해 얹는다:
    suppliers_json    전체 공급처 + 프리셋 보유 여부. `GET /price-import`는 파일이
                      **있는** 공급처만 주므로(내부 조인), 계약이 요구하는 "목록 안에서도
                      그 공급처는 「프리셋 없음」 상태 배지로 드러난다(파일명 자리는 「—」)"
                      를 만족하려면 전체 공급처 목록이 따로 필요하다.
    match_stats_json   ④ 하단 좌 "매칭은 이 순서로 정해진다"의 ①②줄 실적(전역 사실 —
                      기억된 매핑 건수 · 다나와코드 보유 상품 수). ③④줄(이름 유사도
                      후보 · 매칭 없음)은 지금 화면에 뜬 파일들의 실시간 값이라 서버에
                      다시 묻지 않고 클라이언트가 이미 받은 `nw[]`에서 직접 센다.
    recent_json        "결과 · 되돌리기" 패널의 지난 반영 이력(참고용, 최근 20건) — 아래
                      §판단한 것 참조. 이번 세션에서 방금 실행한 반영의 3수 전체(시도/
                      실제 변경/잠김)는 그 자리에서 받은 실제 API 응답을 그대로 쓴다.

■ 판단한 것(계약이 명시하지 않아 이 제작자가 정함 — 검증 대상)
    · diff 표 7열([체크]·단가표 모델명·매칭된 상품·이전 매입가·새 매입가·매칭·상태)은
      `chg` 버킷(전 파일 대비 가격이 실제로 바뀐 행 — 매칭·미매칭 함께)만 담는다.
      "매칭" 칸엔 매칭 여부 배지를, "상태" 칸엔 서버가 이미 주는 `sub`(가격 열 결측이라
      다른 열의 최저가로 대체) · `alt`(타 공급처가 이미 더 싸서 반영해도 안 움직임)
      보조 문구를 얹었다 — 둘 다 `chg` 항목에 이미 있는 필드이고 새로 계산하지 않았다.
    · "가격 변동 · 매칭 안 됨" 카드 = (chg 중 미매칭 행 수) + (nw 전체 건수). `nw`(이번
      파일에 처음 나타난 모델)는 이전 매입가 자체가 없어 7열 표에 넣을 수 없으므로
      별도 목록으로 뺐다.
      ⚠ 코드로 확인한 간극(보고에도 남긴다): `_file_diff()`는 `nw` 항목을 매칭 종류
      (`k`)와 무관하게 전부 `pending`에서 제외한다(새 모델 분기가 `continue`로
      `pending[...]=r` 대입 코드 자체를 건너뛴다) — 그래서 **다나와코드로 이미 자동
      매칭된 신규 모델(`k='code'`)도 지금은 이 화면에서 반영할 수 없다.** 계약 §⑤는
      "매칭 안 된" 신규 모델만 반영 불가라 적었는데, 실제 서버 동작은 매칭 여부와
      무관하게 신규 모델 전부다. 화면은 실제 동작대로 체크박스를 주지 않되, `k='code'`
      항목엔 "이미 연결된 상품: {sku}" 보조 정보를 얹어 이 간극을 감추지 않는다 —
      고치지 않았다(pending 정의를 넓히는 것은 `_file_diff`/`apply_rows` 동작을 바꾸는
      더 큰 판단이라 이 화면의 담당 범위를 넘는다고 봤다. §화면 작업의 경계).
    · 발주 상태 전환(`stat`) 행은 체크박스를 주지 않는다 — `apply_rows()`의 `pending`은
      가격이 바뀐 행에서만 채워지므로, `stat` 전용 `row_id`로 반영을 시도하면 서버가
      항상 400(미매칭·미대기)으로 거부한다(코드 확인). 정보 표시만 한다.
    · 지난 반영 이력(`recent_json`)에서 과거 회차의 "실제 변경 / 잠김" 수는 다시
      계산하지 않는다 — `admin_operator_activity_logs.detail.items`는 반영 당시
      매입가만 남기고 `_reprice()`의 판정 결과(purchase_changed/sale_changed/
      sale_locked)는 저장하지 않는다(코드 확인, `apply_rows()`가 로그에 넘기는
      `items` 딕셔너리에 그 필드가 없다). 지어내지 않고 "시도 {n}건"과 되돌림 여부만
      보여준다 — 3수 전체 분해는 방금 이 세션에서 반영한 결과에만 보인다.
    · 좌측 "이 목록이 감추는 것" 경고는 계약이 준 문구를 그대로 옮긴다(결정 대기 상태
      자체가 확정 문구라 다시 쓰지 않는다 — MAKER-CHECKLIST §1 "디자인이 확정 문구로
      박아 둔 상태 표기는 그대로 옮긴다").

■ 권한 — `api/auth.py`의 `OWNER_WRITE_PREFIXES`에 `/api/admin/price-import`가 없다
  (실측 확인) → `required_role()`상 조회는 viewer, 업로드·반영·되돌리기는 operator
  이상(owner 전용 아님). 화면은 `Admin2Shell.canWrite()`(기본 인자 'operator')로 gate.
"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from .admin_ui_common import render
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/admin2", tags=["admin-ui"])

RECENT_LIMIT = 20


def _suppliers(conn) -> list:
    """전체 공급처 + 프리셋 보유 여부 — `GET /price-import`가 못 주는 "파일이 아직
    없는 공급처"까지 좌측 패널에 그리기 위한 값(모듈 docstring §SSR 참조)."""
    rows = conn.execute(text(
        "SELECT s.supplier_id, s.name,"
        " EXISTS(SELECT 1 FROM supplier_presets p WHERE p.supplier_id = s.supplier_id) AS has_preset"
        " FROM suppliers s ORDER BY s.name")).mappings().all()
    return [{"supplier_id": r["supplier_id"], "name": r["name"], "has_preset": bool(r["has_preset"])}
            for r in rows]


def _match_stats(conn) -> dict:
    """매칭 순서 ①②줄의 실적(전역 사실). ③④줄은 화면에 이미 실린 nw[]에서 클라이언트가 센다."""
    remembered = conn.execute(text("SELECT count(*) FROM supplier_product_map")).scalar_one()
    danawa = conn.execute(text("SELECT count(*) FROM products WHERE danawa_code IS NOT NULL")).scalar_one()
    total = conn.execute(text("SELECT count(*) FROM products")).scalar_one()
    return {"remembered_map": remembered, "danawa_products": danawa, "total_products": total}


def _detail(row) -> dict:
    d = row["detail"]
    if isinstance(d, dict):
        return d
    return json.loads(d) if d else {}


def _recent(conn, limit: int = RECENT_LIMIT) -> list:
    """"결과 · 되돌리기" 패널의 참고용 지난 이력 — 전용 표가 없어 admin_operator_
    activity_logs가 원천이다(`admin_ui_reprice.py._rounds()`와 같은 선례·같은 방식).
    과거 회차의 "실제 변경 · 잠김" 세부는 로그에 없어 재계산하지 않는다(모듈 docstring
    §판단한 것 참조) — "시도 {n}건"과 되돌림 여부만 보여준다."""
    rows = conn.execute(text(
        "SELECT l.log_id, l.detail, l.created_at, COALESCE(o.name, '—') AS operator"
        "  FROM admin_operator_activity_logs l"
        "  LEFT JOIN admin_operators o USING (operator_id)"
        " WHERE l.action = 'price_import_apply'"
        " ORDER BY l.log_id DESC LIMIT :lim"), {"lim": limit}).mappings().all()
    if not rows:
        return []

    undo_rows = conn.execute(text(
        "SELECT l.detail, l.created_at, COALESCE(o.name, '—') AS operator"
        "  FROM admin_operator_activity_logs l"
        "  LEFT JOIN admin_operators o USING (operator_id)"
        " WHERE l.action = 'price_import_undo'")).mappings().all()
    undo_by_ref = {}
    for u in undo_rows:
        ref = _detail(u).get("ref_log_id")
        if ref is not None:
            undo_by_ref[int(ref)] = u

    parsed = [(r, _detail(r)) for r in rows]
    file_ids = [d["file_id"] for _r, d in parsed if d.get("file_id") is not None]
    file_info = {}
    if file_ids:
        frows = conn.execute(text(
            "SELECT f.file_id, f.file_name, s.name AS supplier"
            "  FROM supplier_price_files f JOIN suppliers s USING (supplier_id)"
            " WHERE f.file_id = ANY(:ids)"), {"ids": file_ids}).mappings().all()
        file_info = {r["file_id"]: r for r in frows}

    out = []
    for r, d in parsed:
        fi = file_info.get(d.get("file_id"))
        u = undo_by_ref.get(r["log_id"])
        out.append({
            "log_id": r["log_id"],
            "at": iso(r["created_at"]),
            "operator": r["operator"],
            "file_name": fi["file_name"] if fi else None,
            "supplier": fi["supplier"] if fi else None,
            "attempted": len(d.get("items") or []),
            "undone": u is not None,
            "undo_at": iso(u["created_at"]) if u else None,
            "undo_operator": u["operator"] if u else None,
        })
    return out


@router.get("/price-import", response_class=HTMLResponse)
def price_import_page(request: Request) -> HTMLResponse:
    """ADM-PRC-040 단가표 반영. 실데이터는 클라이언트가
    `GET /api/admin/price-import`(공급처별 최신 파일 + diff) + 위 세 API로 채운다.

    `preset_total`/`preset_with`/`preset_without_names`는 좌측 "프리셋 없는 공급처"
    경고 상자용 스칼라 값 — JS 없이도(진행형 향상) Jinja가 바로 그린다. 이 상자는
    계약이 준 문구를 그대로 옮기고 숫자만 끼운다(정적 텍스트에 굳이 JS 렌더 함수를
    두지 않았다).
    """
    with engine.connect() as conn:
        suppliers = _suppliers(conn)
        match_stats = _match_stats(conn)
        recent = _recent(conn)
    preset_without_names = [s["name"] for s in suppliers if not s["has_preset"]]
    return render(request, "admin/price_import.html.j2",
                  screen_id="ADM-PRC-040", domain="price-import",
                  crumb_group="매입 · 소싱", crumb_now="단가표 반영",
                  suppliers_json=json.dumps(suppliers, ensure_ascii=False),
                  match_stats_json=json.dumps(match_stats, ensure_ascii=False),
                  recent_json=json.dumps(recent, ensure_ascii=False),
                  preset_total=len(suppliers),
                  preset_with=sum(1 for s in suppliers if s["has_preset"]),
                  preset_without_names=preset_without_names)
