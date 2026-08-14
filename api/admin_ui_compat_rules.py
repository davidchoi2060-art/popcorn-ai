"""ADM-ENG-010 조립 호환 규칙 - 페이지 라우트(SSR 셸만, 데이터는 클라이언트 fetch).

이 화면은 "모든 견적에는 이유가 있습니다"의 근거 표다. compat_rules(엔진의 단일
원천, api/recommend.py의 load_compat_rules)를 사람이 읽을 수 있게 보여준다.

이 라우트는 DB를 직접 읽지 않는다 - /admin2/* 페이지 라우트는 auth 미들웨어 게이트
밖이다(그 게이트는 /api/admin/* 경로만 검사한다, api/auth.py의 auth_middleware 참조).
그래서 여기서 서버 렌더로 규칙 데이터를 박으면 "열람은 로그인만 되면 등급 무관"이 아니라
"열람은 아무나"가 된다. 셸만 내려주고, 실제 규칙 데이터는 화면의 스크립트가
GET /api/admin/engine-rules(auth_middleware가 지키는 경로, viewer 이상)를 불러 채운다
- 그 경로가 401을 주면 화면이 "로그인이 필요합니다"를 보여준다(조용히 감추지 않는다).

쓰기 API가 없다(compat_rules에 대한 INSERT/UPDATE/DELETE 0건, 2026-08-14 전수 검색
- docs/design/req/req-compat-rules.md ④ 참조). 그래서 이 화면은 조회 전용이다: 편집
UI는 "여는 것을 전제로" 만들되 저장 버튼은 실제 disabled다(decision-log UX-28).

로드 스킵(ref_slot이 slot보다 탐색 순서상 뒤라 조용히 건너뛰는 것 - api/recommend.py
load_compat_rules 89번째 줄 부근 `SLOTS.index(ref_slot) >= SLOTS.index(slot)`)은 지금
GET /api/admin/engine-rules가 알려주지 않는다. 화면은 그 열을 "확인 불가"로만 표시한다
(지어내지 않는다 - 백엔드가 규칙별 로드 성공 여부를 추가해야 해소된다).
"""
from fastapi import APIRouter, Request

from .admin_ui_common import render

router = APIRouter(prefix="/admin2")


@router.get("/compat-rules")
def compat_rules_page(request: Request):
    return render(
        request, "admin/compat_rules.html.j2",
        screen_id="ADM-ENG-010", domain="호환",
        crumb_group="상품사양관리", crumb_now="조립 호환 규칙",
    )
