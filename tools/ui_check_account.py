# -*- coding: utf-8 -*-
"""브라우저 점검 전용 운영자 계정을 세운다 (개발 전용).

**왜 있나.** 화면을 브라우저에서 확인하려면 세션이 필요한데, 세션 쿠키는 `HttpOnly`라
서버가 심어야 한다 — 즉 로그인 요청을 브라우저 안에서 보내야 하고, 그때 비밀번호가
대화 기록에 남는다. 공용 `ADMIN_PW`(운영자 계정)를 그렇게 쓰고 싶지 않아서
**점검 전용 계정을 따로 둔다.** 값은 `.env`(gitignore)에만 있다.

**쓰는 법**

    .venv/Scripts/python tools/ui_check_account.py          # 활성화(없으면 만든다)
    .venv/Scripts/python tools/ui_check_account.py --off     # 정지 + 비밀번호 무효화

**지우지 않는 이유.** 이 계정으로 한 작업이 `admin_operator_activity_logs`에 남는다.
계정을 지우면 그 원장이 깨진다(FK 위반). 그래서 끌 때도 삭제가 아니라 **정지**다 —
되돌림이 삭제가 아니라 역방향 전이인 것과 같은 규칙이다.

**개발 서버 전용이다.** 운영 서버에서는 돌리지 않는다(CLAUDE.md 베타 배포 상태 참조).
"""
import os
import sys

import sqlalchemy as sa

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.db import engine                      # noqa: E402
from api.passwords import hash_password        # noqa: E402

EMAIL = os.environ.get("UI_CHECK_EMAIL", "").strip()
PW = os.environ.get("UI_CHECK_PW", "")


def _load_env():
    """루트 `.env`를 읽는다 — 회귀와 같은 방식(리포에 값은 없다)."""
    global EMAIL, PW
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "UI_CHECK_EMAIL" and not EMAIL:
                EMAIL = v.strip()
            elif k.strip() == "UI_CHECK_PW" and not PW:
                PW = v.strip()


def main():
    _load_env()
    if not EMAIL or not PW:
        print("  UI_CHECK_EMAIL / UI_CHECK_PW 가 없습니다 — `.env`에 넣으세요"
              " (리포에는 적지 않습니다).")
        return 2

    off = "--off" in sys.argv
    with engine.begin() as c:
        row = c.execute(sa.text(
            "SELECT operator_id FROM admin_operators WHERE email=:e"), {"e": EMAIL}).first()

        if off:
            if row:
                c.execute(sa.text("DELETE FROM admin_sessions WHERE operator_id=:o"),
                          {"o": row[0]})
                # 삭제하지 않는다 — 이 계정의 작업 기록이 원장에 남아 있다.
                c.execute(sa.text(
                    "UPDATE admin_operators SET status='정지', password_hash=NULL"
                    " WHERE email=:e"), {"e": EMAIL})
                print("  점검 계정 정지 + 비밀번호 무효화: " + EMAIL)
            else:
                print("  점검 계정이 없습니다 — 할 일 없음")
            return 0

        # 상태 값은 **한글 '활성'** 이다. 'active' 로 넣으면 로그인은 200 을 주는데
        # `resolve_session` 이 상태를 보고 세션을 버려서 계속 401 이 난다(실제로 겪었다).
        if row:
            c.execute(sa.text(
                "UPDATE admin_operators SET status='활성', role='owner',"
                " password_hash=:ph, must_change_password=false WHERE email=:e"),
                {"e": EMAIL, "ph": hash_password(PW)})
            print("  점검 계정 활성: " + EMAIL + " (operator_id=%d)" % row[0])
        else:
            oid = c.execute(sa.text(
                "INSERT INTO admin_operators (name, email, role, status, provider,"
                " provider_uid, password_hash, must_change_password)"
                " VALUES ('UI점검', :e, 'owner', '활성', 'dev', :e, :ph, false)"
                " RETURNING operator_id"),
                {"e": EMAIL, "ph": hash_password(PW)}).scalar()
            print("  점검 계정 생성: " + EMAIL + " (operator_id=%d)" % oid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
