"""삭제 상품 조회(ADM-DEL-010) — **신설**. 사장님 확정(2026-08-14 최초·2026-08-15 재확인):
본체 **1b**(경로 그룹 + 서랍), 빈 상태만 **1c**. 1a는 탈락. decision-log `UX-26`.

원안: `docs/design/dc-product-deleted-2안.html`. 정의서: `docs/design/req/req-product-deleted.md`.

■ 이 파일이 «화면 라우트 + 조회 API»를 함께 갖는 이유
  정의서 ④가 스스로 밝히듯 **이 화면 전용 조회 API가 원래 없었다**
  (`GET /api/admin/products`는 파생 버킷 ok/review/oos/price만 필터하고, 원본
  `status='삭제대기'`를 직접 거르는 경로가 어디에도 없다). 이 작업의 담당 파일은
  이 화면 파일 하나로 한정돼 있어(제작팀 규약) `api/admin_products.py`는 건드리지
  않는다 — 대신 그 파일이 이미 갖고 있는 **되돌리기·완전 삭제 API를 그대로 소비**하고
  (`POST .../merge/undo/{log_id}` · `POST .../undo/{log_id}` ·
  `POST .../bulk-status/undo` · `PATCH /products/{code}` · `DELETE /products/{code}`),
  **새로 필요한 것은 "목록 + 경로 판정" 조회 하나뿐**이라 이 파일에 같이 둔다.
  `admin_ui_price_review.py`가 같은 이유로 같은 패턴을 이미 썼다(그 파일 docstring
  참고 — "담당 파일이 이 둘로 한정돼 있어 admin_price_review.py는 건드리지 않는다").
  그래서 `router = APIRouter(tags=["admin-ui"])`처럼 **prefix 없이** 두고 각
  라우트에 전체 경로를 직접 쓴다(`/admin2/...` 와 `/api/admin/...` 를 한 모듈에
  같이 등록하는 유일한 방법 — `api/main.py`의 자동 등록은 모듈당 `router` 속성
  하나만 본다).

■ 핵심 로직 — "왜 삭제대기(또는 단종)가 됐는가" 3경로 판정 (정의서 ④·decision-log UX-26)
  삭제대기로 내려가는 알려진 경로는 셋이고, 결과(`status`)는 같아도 **되돌리는 API가
  다르다**:
    ① 중복 편입   `product_merge` 로그, `detail.dup` = 이 상품          → merge/undo
    ② 단건 상태 수정 `product_edit` 로그, `detail.changes.status.to` = 대상 상태 → undo
    ③ 일괄 상태 변경 `"상품 상태 일괄 변경"` 로그, `detail.to` = 대상 상태,
                     `detail.before[]` 에 이 상품 포함                  → bulk-status/undo
  이 셋 중 어느 것과도 안 맞으면 **"판정 불가"**로 두고 숨기지 않는다(UX-26) —
  대신 "상태만 판매중으로 되돌리기"(`PATCH /products/{code}`) 대안만 제공하고,
  재고·공급처는 복원되지 않는다는 것을 명시한다.

  판정은 세 종류 로그를 **`log_id` 내림차순 한 번에 훑어 상품별로 처음 만나는 것**을
  쓴다(=가장 최근 것) — 이미 되돌려진 로그(`*_undo`가 `ref_log_id`로 역참조하는 것,
  `admin_activity_logs.py`와 같은 판정 방식)는 건너뛴다. **편입은 `target=='삭제대기'`
  일 때만 후보다** — `merge_product()`가 상태를 항상 `'삭제대기'`로 하드코딩하므로
  단종에는 구조적으로 편입 경로가 없다(회귀·현실 데이터 어디에도 없다 — 코드로 확인).

■ 실측(정의서 ④, 2026-08-13 스냅샷 — 여기 숫자를 화면에 박지 않는다, 서버가 매번 다시 센다)
  `products.status` 분포: 판매중 7,602 · 품절 15,238 · 단종 0 · 삭제대기 0(전체 22,840건).
  **지금 실데이터 기준 이 화면은 두 탭 다 빈 상태(1c)로 열린다.** 과거 활동 로그에
  `product_merge`·`product_merge_undo`·`product_delete` 흔적이 있으나(정의서는 "회귀
  테스트 흔적으로 보인다"고 추정) 그 판단은 이 화면이 검증할 수 없는 주장이라 **옮기지
  않는다** — 빈 상태 안내문은 이 세 action의 로그 건수만 서버가 다시 세어(`history_note`)
  중립적으로 보여준다("N건이 있지만 지금 목록엔 없다"는 사실만).

■ 승인 디자인과 다르게 구현한 지점(전부 이유가 있다 — 제작 보고서 참조)
  ① 1b 원안 자체에는 검색창·경로 필터 칩·체크박스·상단 툴바가 **없다**(그건 탈락한
     1a에만 있다). 그대로 없앴다 — 원안에 없는 것을 만들지 않는다는 규약(MAKER-
     CHECKLIST) 그대로.
  ② 빈 상태(1c) 안내문의 "삭제대기·단종 각각 N건" · "판매중 N · 품절 N" ·
     "편입 N건·되돌림 N건·완전 삭제 N건" 은 전부 이 API가 매 요청 다시 센 값이다
     (원안의 22,840/7,602/15,238/2/1/6 은 스냅샷 예시일 뿐 — 코드에 박지 않는다).
  ③ 원안 1b의 그룹 설명 문구는 "삭제대기"로 고정돼 있었는데, 이 화면은 단종 탭도
     같은 그룹 구조를 쓰므로 "단건 상태 수정" 그룹 설명만 대상 상태를 대입해
     일반화했다(편입 그룹은 단종에 아예 없으므로 문제 없음).
  ④ 서랍의 "활동 이력" 라벨은 `admin_activity_logs.ACTION_LABELS`(65종 사전, 이
     화면과 무관한 주문·환불·정산 라벨까지 포함)를 통째로 가져오지 않고, 이 화면이
     실제로 다루는 상품 도메인 action 10종만 이 파일 안에 작게 다시 둔다 — 그 파일이
     지금 다른 제작자가 동시에 수정 중이라(git status) 거기 이름을 얹으면 그쪽 저장
     시점에 따라 깨질 수 있다(제작팀 규약 "담당 밖은 읽어도 되지만 고치지 않는다"의
     안전한 쪽 — import 의존조차 최소화).
  ⑤ 완전 삭제 2단계 확인 모달은 1b 캔버스 자체에는 그려져 있지 않다(1b는 "완전
     삭제…" 버튼만 있고 다음 단계는 캔버스 밖). UX-26이 "완전 삭제 포함하되 지금
     수준 유지(operator + force 2단계 확인)"를 명시 확정했고, 그 2단계 확인의
     실제 문구·구조는 같은 원안 파일의 1a 모달에 있다(1a/1b 차이는 "경로·되돌리기를
     보여주는 방식"뿐 — decision-log UX-26 원문). 그래서 1a 모달의 문구·구조를
     그대로 가져오되 하드코딩된 예시(PD91027 등)를 서버 응답(`refs`)으로 대체했다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from .admin_ui_common import render
from .db import engine
from .timeutil import iso
# 부품 어휘는 taxonomy가 단일 원천(.claude/CANON.md §1) — 여기서 다시 정의하지 않는다.
from .taxonomy import PART_LABELS as PART_TYPE_LABELS

router = APIRouter(tags=["admin-ui"])

TARGET_STATUSES = ("삭제대기", "단종")
CAP = 500  # 초과 시 total과 함께 정직 표기 — activity-logs와 같은 관행(페이지네이션 이관)

# 이 화면의 "활동 이력" 서랍에만 쓰는 좁은 라벨(위 docstring ④ — 전체 사전을 가져오지 않는다)
_ACTION_LABEL = {
    "product_register": "상품 등록", "product_edit": "상품 수정",
    "product_edit_undo": "상품 수정 되돌림", "spec_edit": "사양 수정",
    "spec_edit_undo": "사양 수정 되돌림", "part_type_change": "분류 변경",
    "part_type_change_undo": "분류 변경 되돌림", "product_merge": "중복 상품 편입",
    "product_merge_undo": "중복 상품 편입 되돌림", "product_delete": "상품 삭제",
    "supplier_price": "공급처 매입가 등록", "supplier_price_remove": "공급처 매입가 삭제",
    "상품 상태 일괄 변경": "상품 상태 일괄 변경",
    "상품 상태 일괄 변경 되돌림": "상품 상태 일괄 변경 되돌림",
}

# 판정에 쓰는 로그 action 6종(=편입/단건수정/일괄변경 각각의 실행+되돌림) — 정의서 ④ 표 그대로
_CLASSIFY_ACTIONS = ["product_merge", "product_merge_undo",
                     "product_edit", "product_edit_undo",
                     "상품 상태 일괄 변경", "상품 상태 일괄 변경 되돌림"]


def _group_meta(target: str) -> dict:
    """경로 키 -> 그룹 카드 메타(원안 1b `GROUPS`/`P` 배열 그대로 · edit만 대상 상태를 대입)."""
    BLUE, AMBER, RED, GRAY = ("oklch(0.5 0.12 250)", "oklch(0.62 0.15 55)",
                             "oklch(0.52 0.16 30)", "#7d7669")
    meta = {
        "merge": {"mark": "◆", "color": BLUE, "bg": "oklch(0.96 0.02 250)",
                  "title": "중복 편입으로 내려간 것",
                  "desc": ("재고·공급처를 원본으로 옮기고 내려간 것 — 되돌리면"
                           " 그 이전 상태로 전부 복원됩니다"),
                  "api": "POST /products/merge/undo/{log_id}", "btn": "편입 되돌리기"},
        "edit": {"mark": "●", "color": GRAY, "bg": "#f2eee5",
                 "title": "단건 상태 수정",
                 "desc": (f"상세에서 상태만 '{target}'(으)로 바꾼 것 — 상태값만"
                          " 되돌립니다"),
                 "api": "POST /products/undo/{log_id}", "btn": "상태 되돌리기"},
        "bulk": {"mark": "▣", "color": AMBER, "bg": "oklch(0.96 0.035 70)",
                 "title": "일괄 상태 변경",
                 "desc": ("목록에서 여러 건을 한 번에 내린 것 — 그 일괄 작업 단위로"
                          " 되돌립니다"),
                 "api": "POST /products/bulk-status/undo", "btn": "일괄 되돌리기"},
        "unknown": {"mark": "▲", "color": RED, "bg": "oklch(0.97 0.02 30)",
                    "title": "경로를 판정하지 못한 것",
                    "desc": ("세 로그(편입·단건 수정·일괄 변경) 어느 것과도 맞지"
                             " 않습니다(로그 소실·적재 갱신 등). 자동 되돌리기는 없고,"
                             " 상태만 판매중으로 바꾸는 대안만 제공합니다 —"
                             " 재고·공급처는 복원되지 않습니다"),
                    "api": "대안: PATCH /products/{code}", "btn": "상태만 되돌리기"},
    }
    return meta


_GROUP_ORDER = ["merge", "edit", "bulk", "unknown"]


def _history_line(action: str, detail: dict) -> str:
    """활동 이력 한 줄. 모르는 것은 지어내지 않고 라벨만(원본 폴백)."""
    d = detail or {}
    label = _ACTION_LABEL.get(action, action)
    if action == "product_edit":
        chg = (d.get("changes") or {}).get("status")
        if chg:
            return f"{label} · 상태 {chg.get('from')} → {chg.get('to')}"
    elif action == "product_merge":
        return f"{label} · → 삭제대기(into {d.get('keep_sku') or d.get('into')})"
    elif action == "상품 상태 일괄 변경":
        n = d.get("changed")
        return f"{label} · → {d.get('to')}" + (f"(일괄 {n}건)" if n else "")
    elif action in ("product_merge_undo", "product_edit_undo",
                    "상품 상태 일괄 변경 되돌림"):
        return f"{label} · 원 기록 #{d.get('ref_log_id')}"
    return label


def _build_item(r, c: dict | None, path: str, meta: dict, into_map: dict,
                history_by_sku: dict, target: str) -> dict:
    code, sku, name = r["product_code"], r["sku"], r["product_name"]
    cat = PART_TYPE_LABELS.get(r["part_type"], r["part_type"] or "미지정")
    hist = [{"log_id": h["log_id"], "at": iso(h["created_at"]),
             "line": _history_line(h["action"], h["detail"])}
            for h in history_by_sku.get(sku, [])]
    base = {
        "code": code, "sku": sku, "name": name, "cat": cat, "part_type": r["part_type"],
        "stock": r["stock_qty"], "sale_price": r["sale_price"], "status": r["status"],
        "updated_at": iso(r["updated_at"]), "path": path,
        "mark": meta["mark"], "color": meta["color"], "bg": meta["bg"], "btn": meta["btn"],
        "history": hist,
    }
    if path == "unknown" or c is None:
        base.update({
            "log_id": None, "at": None, "operator": None,
            "note": "판정 가능한 로그(편입·단건 수정·일괄 변경)를 찾지 못했습니다",
            "into": None, "restore": [],
            "undo_api": None, "undo_method": None, "undo_body": None,
            "fallback": {"method": "PATCH", "url": f"/api/admin/products/{code}",
                        "body": {"changes": {"status": "판매중"}}},
        })
        return base
    base["log_id"] = c["log_id"]
    base["at"] = c["at"]
    base["operator"] = c["operator"]
    base["fallback"] = None
    if path == "merge":
        into_row = into_map.get(c.get("into_code")) or {}
        into = ({"code": c.get("into_code"), "sku": into_row.get("sku") or c.get("into_sku"),
                "name": into_row.get("product_name")} if c.get("into_code") is not None else None)
        base["into"] = into
        into_sku = into["sku"] if into else (c.get("into_sku") or "?")
        base["note"] = (f"{into_sku}(으)로 재고 {c['moved_stock']}개 · 공급처"
                        f" {c['moved_suppliers']}곳 이동 · log {c['log_id']}")
        restore = [{"what": "상태", "detail": f"{target} → 판매중(편입 이전 값)"}]
        if c["moved_stock"]:
            restore.append({"what": "재고",
                            "detail": (f"원본에서 {c['moved_stock']}개를 되돌려 이 상품으로"
                                       " — 원장에 역방향 전이로 기록됩니다")})
        if c["moved_suppliers"]:
            restore.append({"what": "공급처",
                            "detail": f"{c['moved_suppliers']}건이 이 상품으로 돌아옵니다"})
        base["restore"] = restore
        base["undo_api"] = f"/api/admin/products/merge/undo/{c['log_id']}"
        base["undo_method"] = "POST"
        base["undo_body"] = None
    elif path == "edit":
        base["into"] = None
        base["note"] = f"상세에서 상태만 '{target}'(으)로 변경 · log {c['log_id']}"
        base["restore"] = [{"what": "상태",
                            "detail": (f"{target} → {c.get('from_status') or '이전 값'}"
                                       "(수정 이전 값)")}]
        base["undo_api"] = f"/api/admin/products/undo/{c['log_id']}"
        base["undo_method"] = "POST"
        base["undo_body"] = None
    elif path == "bulk":
        base["into"] = None
        n = c.get("bulk_total")
        base["note"] = ("일괄 변경" + (f" {n}건 중 하나" if n else "")
                        + f" · log {c['log_id']}")
        base["restore"] = [{"what": "상태",
                            "detail": (f"{target} → {c.get('from_status') or '이전 값'}"
                                       "(일괄 변경 이전 값)")}]
        base["undo_api"] = "/api/admin/products/bulk-status/undo"
        base["undo_method"] = "POST"
        base["undo_body"] = {"log_id": c["log_id"]}
    return base


@router.get("/api/admin/deleted-products")
def list_deleted_products(status: str = "삭제대기", q: str = ""):
    """삭제 상품 조회의 신설 목록 API(정의서 ④가 "지금 없다"고 밝힌 바로 그 조회).

    조회 전용 — viewer 이상(다른 목록 API와 같은 선례, 정의서 ①). 되돌리기·완전
    삭제 같은 실제 쓰기는 **이 API가 하지 않는다** — 화면이 `api/admin_products.py`의
    기존 쓰기 엔드포인트를 각 아이템의 `undo_api`/`fallback`/`code`로 직접 부른다.
    """
    target = status.strip() if status.strip() in TARGET_STATUSES else "삭제대기"
    q = q.strip()

    with engine.connect() as conn:
        # 탭 배지 — 두 상태 다 항상 함께 센다(q 무관, 화면 어느 탭에서도 옆 탭 수를 본다)
        tab_rows = conn.execute(text(
            "SELECT status, count(*) FROM products WHERE status = ANY(:sts)"
            " GROUP BY status"), {"sts": list(TARGET_STATUSES)}).all()
        tab_counts = {s: 0 for s in TARGET_STATUSES}
        tab_counts.update({r[0]: r[1] for r in tab_rows})

        # 빈 상태(1c) 안내문이 쓰는 카탈로그 전체 구성 — 전부 서버가 다시 센 값
        cat_rows = conn.execute(text(
            "SELECT status, count(*) FROM products GROUP BY status")).all()
        catalog_by_status = {r[0]: r[1] for r in cat_rows}
        catalog_total = sum(catalog_by_status.values())

        # 빈 상태(1c) 안내문의 "과거 활동 로그" 문장 — 원안의 2/1/6은 스냅샷 예시라
        # 서버가 다시 센다(정의서 ④의 추정 "회귀 테스트 흔적"은 이 화면이 검증할
        # 수 없는 판단이라 옮기지 않는다 — 중립적으로 건수만 보여준다).
        hist_rows = conn.execute(text(
            "SELECT action, count(*) FROM admin_operator_activity_logs"
            " WHERE action IN ('product_merge','product_merge_undo','product_delete')"
            " GROUP BY action")).all()
        history_note = {a: 0 for a in ("product_merge", "product_merge_undo", "product_delete")}
        history_note.update({r[0]: r[1] for r in hist_rows})

        where_q = ("(:q = '' OR product_name ILIKE '%%' || :q || '%%'"
                   " OR sku ILIKE '%%' || :q || '%%'"
                   " OR CAST(product_code AS TEXT) ILIKE '%%' || :q || '%%')")
        matched = conn.execute(text(
            f"SELECT count(*) FROM products WHERE status=:t AND {where_q}"),
            {"t": target, "q": q}).scalar_one()
        rows = conn.execute(text(
            "SELECT product_code, sku, product_name, part_type, status, stock_qty,"
            f" sale_price, updated_at FROM products WHERE status=:t AND {where_q}"
            " ORDER BY updated_at DESC NULLS LAST, product_code DESC LIMIT :cap"),
            {"t": target, "q": q, "cap": CAP}).mappings().all()

        codes_set = {r["product_code"] for r in rows}
        classification: dict[int, dict] = {}
        into_codes: set[int] = set()

        if codes_set:
            logs = conn.execute(text(
                "SELECT l.log_id, l.action, l.detail, l.created_at,"
                " COALESCE(o.name, '—') AS operator"
                " FROM admin_operator_activity_logs l"
                " LEFT JOIN admin_operators o USING (operator_id)"
                " WHERE l.action = ANY(:actions) ORDER BY l.log_id DESC"),
                {"actions": _CLASSIFY_ACTIONS}).mappings().all()

            undone_ids: set[str] = set()
            for lr in logs:
                if lr["action"] in ("product_merge_undo", "product_edit_undo",
                                    "상품 상태 일괄 변경 되돌림"):
                    rid = (lr["detail"] or {}).get("ref_log_id")
                    if rid is not None:
                        undone_ids.add(str(rid))

            # log_id 내림차순(=최신 먼저)을 그대로 훑어, 상품별로 "처음 만나는" 것을 쓴다
            # — 세 유형을 한 시퀀스로 합쳐 돌기 때문에 유형이 섞여도 항상 최신이 이긴다.
            for lr in logs:
                if lr["action"] not in ("product_merge", "product_edit", "상품 상태 일괄 변경"):
                    continue
                if str(lr["log_id"]) in undone_ids:
                    continue
                d = lr["detail"] or {}
                if lr["action"] == "product_merge":
                    if target != "삭제대기":
                        continue  # merge_product()가 상태를 항상 '삭제대기'로 고정한다
                    pc = d.get("dup")
                    if pc in codes_set and pc not in classification:
                        classification[pc] = {
                            "log_id": lr["log_id"], "at": iso(lr["created_at"]),
                            "operator": lr["operator"], "into_code": d.get("into"),
                            "into_sku": d.get("keep_sku"),
                            "moved_stock": d.get("moved_stock") or 0,
                            "moved_suppliers": len(d.get("moved_suppliers") or []),
                            "_path": "merge",
                        }
                        if d.get("into") is not None:
                            into_codes.add(d.get("into"))
                elif lr["action"] == "product_edit":
                    pc = d.get("product_code")
                    chg = (d.get("changes") or {}).get("status") or {}
                    if pc in codes_set and pc not in classification and chg.get("to") == target:
                        classification[pc] = {
                            "log_id": lr["log_id"], "at": iso(lr["created_at"]),
                            "operator": lr["operator"], "from_status": chg.get("from"),
                            "_path": "edit",
                        }
                elif lr["action"] == "상품 상태 일괄 변경":
                    if d.get("to") != target:
                        continue
                    for b in (d.get("before") or []):
                        pc = b.get("pc")
                        if pc in codes_set and pc not in classification:
                            classification[pc] = {
                                "log_id": lr["log_id"], "at": iso(lr["created_at"]),
                                "operator": lr["operator"], "from_status": b.get("st"),
                                "bulk_total": d.get("changed"), "_path": "bulk",
                            }

        into_map = {}
        if into_codes:
            into_map = {r["product_code"]: r for r in conn.execute(text(
                "SELECT product_code, sku, product_name FROM products"
                " WHERE product_code = ANY(:c)"), {"c": list(into_codes)}).mappings()}

        skus = [r["sku"] for r in rows]
        history_by_sku: dict[str, list] = {}
        if skus:
            hrows = conn.execute(text(
                "SELECT log_id, action, detail, created_at, target_id"
                " FROM admin_operator_activity_logs"
                " WHERE target_kind='product' AND target_id = ANY(:skus)"
                " ORDER BY log_id DESC"), {"skus": skus}).mappings().all()
            for hr in hrows:
                bucket = history_by_sku.setdefault(hr["target_id"], [])
                if len(bucket) < 6:
                    bucket.append(hr)

    meta_map = _group_meta(target)
    groups_out = []
    for key in _GROUP_ORDER:
        if key == "merge" and target != "삭제대기":
            continue
        meta = meta_map[key]
        items = []
        for r in rows:
            pc = r["product_code"]
            c = classification.get(pc)
            path = c["_path"] if c else "unknown"
            if path != key:
                continue
            items.append(_build_item(r, c, path, meta, into_map, history_by_sku, target))
        if not items:
            continue
        groups_out.append({
            "key": key, "mark": meta["mark"], "color": meta["color"], "bg": meta["bg"],
            "title": meta["title"], "desc": meta["desc"], "api": meta["api"],
            "count": len(items), "items": items,
        })

    note = None
    if matched > CAP:
        note = (f"최근 갱신순 {CAP:,}건까지 표시합니다 — 전체 {matched:,}건 중 일부입니다."
                " 경로 판정·그룹 건수도 이 범위 안에서만 계산됩니다.")

    return {
        "status": target,
        "tabs": [{"key": s, "label": s, "count": tab_counts.get(s, 0)} for s in TARGET_STATUSES],
        "total": tab_counts.get(target, 0),
        "matched": matched,
        "shown": len(rows),
        "capped": matched > CAP,
        "cap": CAP,
        "groups": groups_out,
        "note": note,
        "catalog": {"total": catalog_total, "by_status": catalog_by_status},
        "history_note": history_note,
    }


@router.get("/admin2/deleted-products", response_class=HTMLResponse)
def deleted_products_page(request: Request) -> HTMLResponse:
    """삭제 상품 조회(ADM-DEL-010) — 사장님 확정 1b(+ 빈 상태 1c). decision-log UX-26.

    LNB 연결은 이 작업의 소관이 아니다(`api/admin_nav.py`는 정본 — 하네스만 만진다,
    지금은 `href=None`인 채로 "신설"만 표시돼 있고 정상이다). 주소를 직접 쳐서 들어간다.
    """
    return render(request, "admin/product_deleted.html.j2",
                  screen_id="ADM-DEL-010", domain="deleted-products",
                  crumb_group="상품관리", crumb_now="삭제 상품 조회")
