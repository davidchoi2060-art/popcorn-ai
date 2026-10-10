"""관리자 화면 표시용 한국어 이름표 — 내부 코드를 화면에 그대로 내보내지 않는다 (2026-10-10).

권한 등급 코드(viewer·operator·owner)는 DB·권한 검사에서만 쓰는 값이다. 화면에는
아래 이름표를 거쳐 한국어로 보여 준다. 같은 표가 `admin_operators`·`admin_profile`·
`admin_system` 세 곳에 따로 있던 것을 여기로 모았다(§단일 원천). 브라우저 쪽 같은 표는
`mockups/shared/admin2/admin2-shell.js` 의 ROLE_KO(`Admin2Shell.roleKo`)다.

`router` 를 두지 않는다 — 로직만 있는 공용 모듈이다(`admin_ui_common` 과 같은 이유).
"""

ROLE_KO = {"viewer": "조회", "operator": "운영자", "owner": "관리자"}

# 자료가 없어 비어 있는 칸의 표시 문구 (2026-10-10 사장님 결정)
MISSING = "정보 없음"


def role_ko(code: str | None) -> str:
    """권한 등급 코드를 한국어 이름으로. 모르는 코드는 그대로 돌려준다."""
    if not code:
        return MISSING
    return ROLE_KO.get(code, code)
