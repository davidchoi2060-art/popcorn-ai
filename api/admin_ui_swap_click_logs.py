"""부품 교체 · 클릭 기록(ADM-ORD-030) 페이지 라우트 — `api/main.py`가 자동으로 싣는다
(§discovery, `api/` 평면에 둔다 — 하위 폴더는 자동 등록이 훑지 않는다).

**조회 전용.** 계약 `docs/design/spec-swap-click-logs.md`(사장님 확정 1a "슬롯 교체율 +
정책 연결", 2026-08-14. 1b "패턴 카드 + 최근 원본"은 탈락). 정의서
`docs/design/req/req-swap-click-logs.md`. 원문(Claude Design)은 하네스만 연다
(`docs/design/MAKER-CHECKLIST.md` §1) — 이 화면은 로컬에 원안(dc-*.html)이 없어
계약 요약 텍스트만으로 지었다(치수 대조 대상 아님).

■ 이 화면이 답하는 질문
  "고객이 우리가 고른 부품을 그대로 받아들이는가, 아니면 어디를 자주 바꾸는가" —
  교체율은 "최선의 부품"이라는 정체성 주장의 직접 측정값이다. 가격 변화 방향(상향/
  하향/변화없음)은 그 자체로 어느 정책 화면을 봐야 하는지를 가리킨다(계약 §공통 확정 ①).

■★ 데이터 API — 새로 만들지 않았다(담당 파일 밖, 실측만 했다: `api/admin_swap_logs.py`).
  정본: `GET /api/admin/swap-logs?limit=`(기본 100·최대 500, 오프셋 없음). 코드를 직접
  읽어 계약이 요구하는 집계를 실제로 주는지 대조했다:

    total        swap_event_logs 전체 건수
    pairs[]      교체 쌍(빈도순) — from/to 상품명·SKU·건수·평균가격변화·signal
    rate[]       **슬롯별 교체율**. 분모(`proposed`)는 `quote_snapshots`를 배열/
                 `{parts:[...]}` 양쪽 형식 다 방어적으로 펼쳐 센다(계약 §방어적 읽기
                 그대로 서버가 이미 구현) — `recommendation_items`(0행)는 쓰지 않는다
                 (계약이 경고한 그대로, 코드로 확인함). swapped=0인 슬롯은 `fix:null`.
    by_slot[]    swap_event_logs만의 슬롯별 분포(교체가 실제로 일어난 슬롯만 — 지금
                 4종: GPU·MB·CPU·RAM. proposed 개념이 없어 rate[]와는 다른 배열이다)
    clicks       count·identified·unidentified·top[10]·reason(0건-두-뜻 구분 문구 포함)
    note         서버 안내 문장

  **없는 것 — 지어내지 않고 화면에서 명시한다:** 상단 경고 박스가 참고하는 원안 예시
  ("273개 서로 다른 세션 · 26명 방문자 · 12일에 걸쳐 반복")에 해당하는 **특정 교체 쌍의
  distinct 세션 수·distinct 방문자 수·발생 기간**은 이 API 응답 어디에도 없다(`pairs[]`는
  건수만, `recent[]`는 최근 20건 전역 로그일 뿐 쌍 단위로 안 좁혀진다). 이 화면은 그
  숫자를 계산해 내밀지 않고, 배너 안에 "이 API가 세지 않는다"는 사실 자체를 문장으로
  남긴다(추가 집계가 필요하면 `api/admin_swap_logs.py` 확장이 필요 — 담당 파일 밖).

  **1a에는 없는 것** — 정의서 §⑤·⑥은 "최근 교체 20건 원본"을 기능으로 적었지만, 그건
  1b("패턴 카드 + 최근 원본")의 요소였고 1b는 탈락했다. 1a 구조(계약 §1a구조)에는 그
  표가 없다 — 그래서 서버가 주는 `recent[]`를 이 화면은 쓰지 않는다(정의서가 계약보다
  하루 먼저 쓰였고, 계약이 정본이다 — `docs/design/MAKER-CHECKLIST.md` §1 "확정 안만
  정본이다").

■★★ 정책 화면 링크 3종 — **경로(route path)로 조회한다. 라벨로 조회하지 않는다.**

  ⚠ **2026-08-14 실사고(하네스 보고, 이 파일이 원인).** 처음엔 admin_nav.py의 `NAV`를
  **라벨 문자열**로 조회했다(`"추천 기준 설정"`을 키로 씀). 그런데 사장님이 그 화면
  이름을 "추천 기준 설정" -> "추천 기준 보기"로 확정하며 admin_nav.py의 라벨이
  바뀌었고, 라벨 키 조회가 **조용히** `None`을 돌려주기 시작했다 — 하향(▼) 신호의
  버튼만 죽었는데 "비활성"으로 보여 결함처럼 드러나지도 않았다. 판단 자체(있으면
  링크, 없으면 비활성)는 옳았고 깨진 것은 **조회 키 선택**이었다.

  **교훈은 "라벨을 바꾸지 말자"가 아니라 "라벨은 조회 키가 될 수 없다"다.** 사람이
  읽는 문구는 사장님 확정마다 바뀐다 — ETC 라벨 사고(화면이 `labels[0]==='미분류'`로
  판정하다 라벨이 바뀌면 13건이 오류 없이 0으로 표시될 뻔한 사고, P-12 근거)와 같은
  병이다. **그래서 경로(route path)를 조회 키로 쓴다.**

  admin_nav.py는 `(label, href, note)` 세 값만 갖고 화면 ID를 담지 않는다 — 그래서
  "화면 ID로 조회"는 admin_nav.py만 읽어서는 할 수 없다. 대신 각 정책 화면의 **실제
  라우트 선언**을 다른 제작자의 `admin_ui_*.py`에서 직접 읽어 확인한 경로 문자열을
  `POLICY_TARGETS`에 둔다. admin_nav.py는 "그 경로가 지금 NAV 어딘가에 실제로
  링크돼 있는가"만 확인하는 용도로 쓴다(여전히 읽기만 — 고치지 않는다) — **라벨
  문자열은 조회에 전혀 관여하지 않는다.** 그 화면 이름이 다시 바뀌어도(예: "추천
  기준 보기" -> 다른 이름) 이 조회는 안 깨진다: URL은 화면 이름보다 훨씬 안정적이고,
  admin_nav.py 자신도 모든 화면을 라벨이 아니라 경로 문자열로 링크한다 — 같은 관례를
  따른 것뿐이다.

  경로 실측 근거(전부 해당 `admin_ui_*.py`의 `@router.get(...)` 선언을 직접 읽어
  확인, 2026-08-15 재확인 — 세 화면 모두 그 시점 사이에 다른 제작자가 라우트
  코드까지는 이미 만들어 두었다):

      up   /admin2/usage-floors    api/admin_ui_usage_floors.py   (ADM-ENG-040)
      down /admin2/policy-weights  api/admin_ui_policy_weights.py (ADM-ENG-020)
      flat /admin2/part-grade      api/admin_ui_part_grade.py     (ADM-ENG-050)

  세 화면 모두 **라우트 코드는 이미 있지만 admin_nav.py의 href는 여전히 `None`**이다
  (실측 2026-08-15) — 그래서 지금은 셋 다 비활성으로 보이는 것이 맞다(화면 결함
  아님). 하네스가 admin_nav.py에 href를 채우면(그 시점 라벨이 무엇이든) 이 화면은
  코드 수정 없이 다음 요청부터 바로 살아있는 링크를 낸다 — 하드코딩한 것은 "경로
  문자열"뿐이고 "그 경로가 지금 연결됐는가"는 여전히 admin_nav.py를 매 요청 실측한다.

  `api/admin_swap_logs.py`가 이미 만들어 보내는 `rate[].fix`(label/href/why)는 그대로
  쓰지 않는다 — 그 href가 옛 목업 상대경로(`usage-floors.html` 등)라 admin2에서 죽은
  링크가 된다. **href는 위 경로 실측으로 다시 계산하고, `fix.why`(해석 문장)만 서버
  문구를 그대로 옮긴다** — 서버가 준 판정을 화면이 버리지 않는다는 원칙과, 죽은
  링크를 내밀지 않는다는 원칙이 부딪히는 지점이라 후자를 택했다.

  화면 표시 라벨은 계약 원문 표기("추천 기준 보기"/"용도별 최소 사양"/"부품 등급
  관리")를 그대로 쓴다 — admin_nav.py의 현재 라벨과 다르게 부를 이유가 이제 없다
  (조회가 라벨에 안 걸리므로 admin_nav.py 라벨이 무엇이든 화면 표시 문구는 계약
  원문을 따르면 된다).

■★ "분모 0" 구분 — `taxonomy.SLOT_LABELS`(정본, 읽기 전용)를 카드 렌더의 전체
  모집단으로 쓴다. `rate[]`는 `quote_snapshots`에 실제로 나타난 슬롯만 행으로 주므로
  (분모 0인 슬롯은 애초에 행 자체가 없다 — proposed=0인 행은 SQL 구조상 나오지 않는다),
  화면이 `rate[]`만 그리면 "교체 0건(제안은 있었음)"과 "애초에 제안된 적 없음(분모
  0)"이 똑같이 "카드가 안 보인다"로 뭉개진다. `SLOT_LABELS`의 8슬롯과 `rate[]`에 실린
  슬롯을 대조해, 빠진 슬롯은 "분모 0" 카드로 명시한다(계약 §"이 화면이 지키는 것" 1·
  정의서 §⑦ 요구 그대로).

■ 실측 오기 — `api/admin_swap_logs.py` 모듈 docstring은 자신을 "ADM-ANL-020"이라 적었지만,
  이 화면의 화면 ID(마크업 계약)와 카탈로그 문서(`docs/decisions/admin-identity.md`) 둘
  다 "ADM-ORD-030"으로 일치한다(정의서 §② 실측 그대로). 그 파일은 담당 밖이라 고치지
  않았다 — docstring 오기 수정은 이 작업 범위 밖(정의서 "사장님 결정이 필요한 지점" ①).

■ 권한 — 조회는 로그인만 되면 등급 무관(viewer 이상). `/api/admin/swap-logs`는
  `api/auth.py`의 `OWNER_WRITE_PREFIXES`에 없다(실측) — GET 기본 규칙을 그대로 따른다.
  이 화면은 쓰기 버튼이 하나도 없다(견적 API·스왑 API를 호출하지 않는다).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

import json

from .admin_ui_common import render
from .admin_nav import NAV
from .taxonomy import SLOT_LABELS

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


# 계약 §공통 확정 ① — 가격 변화 방향이 가리키는 정책 화면 3종.
#
# ⚠ **키는 "경로"다. "라벨"이 아니다** — 위 모듈 docstring "■★★ 정책 화면 링크 3종"에
# 이 파일이 실제로 겪은 사고(라벨 리네임으로 조회가 조용히 깨짐)와 근거를 남겼다.
# 다음 사람이 "라벨이 더 읽기 쉬운데" 하고 되돌리지 않도록 요약만 다시 적는다:
# 라벨은 사장님 확정마다 바뀌는 **표시 문구**이고, 경로(URL)는 그 화면의 **식별자**에
# 가깝다 — admin_nav.py 자신도 화면을 라벨이 아니라 경로로 링크한다. 경로는 각
# 화면의 `admin_ui_*.py`에서 `@router.get(...)`을 직접 읽어 확인했다(아래 값 옆 근거).
#   up   상향(+)     하한이 낮아 싼 부품이 뽑혔을 수 있다 -> 용도별 최소 사양
#   down 하향(-)     예산 배분이 과했을 수 있다           -> 추천 기준 보기(구 "추천 기준 설정")
#   flat 변화 없음   매긴 서열이 취향과 어긋난다           -> 부품 등급 관리
POLICY_TARGETS = {
    "up": {"display": "용도별 최소 사양",
           "path": "/admin2/usage-floors"},    # api/admin_ui_usage_floors.py 실측
    "down": {"display": "추천 기준 보기",
             "path": "/admin2/policy-weights"},  # api/admin_ui_policy_weights.py 실측
    "flat": {"display": "부품 등급 관리",
             "path": "/admin2/part-grade"},     # api/admin_ui_part_grade.py 실측
}


def _policy_links() -> dict:
    """admin_nav.NAV를 "그 경로가 실제로 링크돼 있는가"로만 훑는다.

    라벨 문자열은 조회에 전혀 쓰지 않는다(위 POLICY_TARGETS 주석 참조 — 라벨로
    조회하다 실제로 조용히 깨진 적이 있다). href가 채워지면(다른 제작자가 그 화면을
    완성하고 하네스가 메뉴에 연결한 뒤) 이 함수는 다음 요청부터 바로 그 경로를
    돌려준다 — 이 파일을 다시 고칠 필요가 없다.
    """
    live_hrefs = {href for _title, _icon, items in NAV for _label, href, _note in items if href}
    out = {}
    for key, t in POLICY_TARGETS.items():
        available = t["path"] in live_hrefs
        out[key] = {
            "label": t["display"],
            "href": t["path"] if available else None,
            "available": available,
            "reason": None if available else "아직 admin2 메뉴에 연결되지 않았습니다 — 신설 예정",
        }
    return out


@router.get("/swap-click-logs", response_class=HTMLResponse)
def swap_click_logs(request: Request) -> HTMLResponse:
    """부품 교체 · 클릭 기록(ADM-ORD-030). 조회 전용 — 쓰기 API를 하나도 부르지 않는다.

    `GET /api/admin/swap-logs?limit=500`(서버 상한) 한 번으로 이 화면의 데이터 전부가
    온다. 여기서는 정책 링크 3종의 실측 결과(`policy_links_json`, 경로 기반 — 위
    참조)와 슬롯 전체 모집단(`all_slots_json`, `taxonomy.SLOT_LABELS` 그대로)만
    추가로 실어 보낸다. 후자는 "분모 0"(애초에 제안된 적 없음)과 "교체 0건"(제안은
    됐지만 안 바뀜)을 화면이 구분하는 데 쓴다 — `rate[]`만으로는 분모 0인 슬롯이
    그냥 행 자체가 없어(SQL 구조상) 두 상태가 똑같이 "안 보임"으로 뭉개진다.
    """
    return render(request, "admin/swap_click_logs.html.j2",
                  screen_id="ADM-ORD-030", domain="swap-click-logs",
                  crumb_group="상품사양관리", crumb_now="부품 교체 · 클릭 기록",
                  policy_links_json=json.dumps(_policy_links(), ensure_ascii=False),
                  all_slots_json=json.dumps(SLOT_LABELS, ensure_ascii=False))
